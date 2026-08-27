#!/usr/bin/env python3
"""Build the Federal Defendants exact-coordinate semantic oracle.

Semantic values are copied only from the separately authored authority JSON. This
module expands declared rectangles and verifies exact source assertions. Labels,
proof text, indentation, style, proximity, and row order are evidence only and
never assign semantics.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import os
import platform
import posixpath
import re
import stat
import sys
import sysconfig
import tempfile
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = "fixtures/product-prototype/federal-defendants-semantic-plan-v1.json"
ROOT_MANIFEST_NAME = "federal-defendants-source-coordinate-semantic-oracle-v1.json"
SHARD_DIR_NAME = "federal-defendants-source-coordinate-semantic-oracle-v1"
CANONICAL_MANIFEST = f"fixtures/product-prototype/{ROOT_MANIFEST_NAME}"
CANONICAL_SHARD_DIR = f"fixtures/product-prototype/{SHARD_DIR_NAME}"
SCHEMA_PATHS = (
    "contracts/product-prototype/v1/federal-defendants-controlled-vocabulary.schema.json",
    "contracts/product-prototype/v1/federal-defendants-methodology-evidence.schema.json",
    "contracts/product-prototype/v1/federal-defendants-semantic-plan.schema.json",
    "contracts/product-prototype/v1/federal-defendants-source-coordinate-semantic-oracle-member.schema.json",
    "contracts/product-prototype/v1/federal-defendants-source-coordinate-semantic-oracle.schema.json",
)
TOOLCHAIN_PATHS = (
    ".python-version",
    "scripts/build-federal-defendants-semantic-oracle.py",
    "scripts/verify-federal-defendants-semantic-oracle.py",
)
DEPENDENCY_PATHS = ("pyproject.toml", "uv.lock")
REQUIRED_EVIDENCE = {
    "boundedExclusions",
    "controlledVocabulary",
    "familyCrosswalk",
    "familyMembership",
    "methodologyEvidence",
    "releaseDownloads",
    "sourceInventory",
}
RUNTIME_DISTRIBUTIONS: tuple[str, ...] = ()
RUNTIME_TREE_EXCLUDED_DIRECTORIES = frozenset({"site-packages", "dist-packages"})
MAX_PATH_BYTES = 512
MAX_PATH_COMPONENTS = 32
MAX_AUTHORITY_BYTES = 8_000_000
MAX_EVIDENCE_JSON_BYTES = 10_000_000
MAX_SCHEMA_BYTES = 1_000_000
MAX_TOOLCHAIN_BYTES = 10_000_000
MAX_DEPENDENCY_BYTES = 20_000_000
MAX_RUNTIME_FILE_BYTES = 100_000_000
MAX_RUNTIME_TOTAL_BYTES = 250_000_000
MAX_RUNTIME_TREE_FILES = 20_000
MAX_RUNTIME_TREE_SYMLINKS = 1_000
MAX_RUNTIME_TREE_NODES = 25_000
MAX_JSON_NODES = 2_000_000
MAX_ZIP_ENTRIES = 10_000
MAX_ENTRY_BYTES = 50_000_000
MAX_TOTAL_BYTES = 200_000_000
MAX_XML_NODES = 2_000_000
MAX_PARSED_CELLS = 2_000_000
MAX_MERGED_CELLS = 2_000_000
MAX_COMMENTS = 100_000
MAX_RECORDS = 18_793
ADDRESS = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
BUILTIN_NUMBER_FORMATS = {
    0: "General",
    1: "0",
    2: "0.00",
    3: "#,##0",
    4: "#,##0.00",
}
NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}


def fail(code: str, detail: object) -> None:
    raise RuntimeError(f"{code}: {detail}")


def digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def stable_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def utf8_key(value: str) -> bytes:
    return value.encode("utf-8")


def json_node_count(value: object) -> int:
    if isinstance(value, dict):
        return 1 + sum(
            json_node_count(key) + json_node_count(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return 1 + sum(json_node_count(child) for child in value)
    return 1


def load_json(data: bytes, label: str, maximum: int) -> object:
    if len(data) > maximum:
        fail("FEDERAL_ORACLE_JSON_BYTE_LIMIT", f"{label}:{len(data)}>{maximum}")
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail("FEDERAL_ORACLE_JSON_INVALID", f"{label}:{error}")
    nodes = json_node_count(value)
    if nodes > MAX_JSON_NODES:
        fail("FEDERAL_ORACLE_JSON_NODE_LIMIT", f"{label}:{nodes}")
    return value


class SchemaSubsetError(Exception):
    pass


def _schema_error(code: str, detail: object) -> None:
    raise SchemaSubsetError(f"{code}: {detail}")


SUPPORTED_SCHEMA_KEYWORDS = {
    "$schema",
    "$id",
    "$defs",
    "$ref",
    "title",
    "type",
    "const",
    "enum",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "minProperties",
    "minimum",
    "maximum",
    "pattern",
    "anyOf",
    "oneOf",
    "allOf",
    "if",
    "then",
    "format",
}
MAX_SCHEMA_DEPTH = 128
MAX_SCHEMA_VALIDATION_STEPS = 50_000_000


def _json_equal(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def _schema_type_matches(instance: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, int | float) and not isinstance(instance, bool)
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "null":
        return instance is None
    _schema_error("UNSUPPORTED_TYPE", expected)
    return False


def _resolve_local_ref(root_schema: dict[str, object], reference: str) -> object:
    if reference == "#":
        return root_schema
    if not reference.startswith("#/"):
        _schema_error("UNSUPPORTED_REF", reference)
    current: object = root_schema
    for encoded in reference[2:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            _schema_error("REF_NOT_FOUND", reference)
        current = current[token]
    return current


def _validate_schema_subset(
    instance: object,
    schema: object,
    root_schema: dict[str, object],
    path: str,
    depth: int,
    state: list[int],
) -> None:
    state[0] += 1
    if state[0] > MAX_SCHEMA_VALIDATION_STEPS:
        _schema_error("STEP_LIMIT", path)
    if depth > MAX_SCHEMA_DEPTH:
        _schema_error("DEPTH_LIMIT", path)
    if isinstance(schema, bool):
        if not schema:
            _schema_error("FALSE_SCHEMA", path)
        return
    if not isinstance(schema, dict):
        _schema_error("SCHEMA_SHAPE", path)
    unsupported = set(schema) - SUPPORTED_SCHEMA_KEYWORDS
    if unsupported:
        _schema_error("UNSUPPORTED_KEYWORD", sorted(unsupported))
    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict):
        _schema_error("DEFS_SHAPE", path)
    for name, child_schema in definitions.items():
        if not isinstance(name, str):
            _schema_error("DEFS_NAME", path)
        _check_schema_keywords(child_schema, root_schema, depth + 1, state)
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str):
            _schema_error("REF_SHAPE", path)
        _validate_schema_subset(
            instance,
            _resolve_local_ref(root_schema, reference),
            root_schema,
            path,
            depth + 1,
            state,
        )
    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = (
            [expected_type] if isinstance(expected_type, str) else expected_type
        )
        if (
            not isinstance(expected_types, list)
            or not expected_types
            or any(not isinstance(item, str) for item in expected_types)
        ):
            _schema_error("TYPE_SHAPE", path)
        if not any(_schema_type_matches(instance, item) for item in expected_types):
            _schema_error("TYPE", f"{path}:{expected_types}:{type(instance).__name__}")
    if "const" in schema and not _json_equal(instance, schema["const"]):
        _schema_error("CONST", path)
    if "enum" in schema:
        choices = schema["enum"]
        if not isinstance(choices, list) or not choices:
            _schema_error("ENUM_SHAPE", path)
        if not any(_json_equal(instance, choice) for choice in choices):
            _schema_error("ENUM", path)
    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword not in schema:
            continue
        branches = schema[keyword]
        if not isinstance(branches, list) or not branches:
            _schema_error(f"{keyword.upper()}_SHAPE", path)
        matches = 0
        errors: list[Exception] = []
        for branch in branches:
            try:
                _validate_schema_subset(
                    instance, branch, root_schema, path, depth + 1, state
                )
                matches += 1
            except SchemaSubsetError as error:
                errors.append(error)
        if keyword == "allOf" and matches != len(branches):
            raise errors[0]
        if keyword == "anyOf" and matches == 0:
            _schema_error("ANYOF", path)
        if keyword == "oneOf" and matches != 1:
            _schema_error("ONEOF", f"{path}:{matches}")
    if "if" in schema:
        condition_matches = True
        try:
            _validate_schema_subset(
                instance, schema["if"], root_schema, path, depth + 1, state
            )
        except SchemaSubsetError:
            condition_matches = False
        if condition_matches and "then" in schema:
            _validate_schema_subset(
                instance, schema["then"], root_schema, path, depth + 1, state
            )
    if isinstance(instance, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or any(
            not isinstance(item, str) for item in required
        ):
            _schema_error("REQUIRED_SHAPE", path)
        missing = [item for item in required if item not in instance]
        if missing:
            _schema_error("REQUIRED", f"{path}:{missing}")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            _schema_error("PROPERTIES_SHAPE", path)
        for key, child in instance.items():
            if key in properties:
                _validate_schema_subset(
                    child,
                    properties[key],
                    root_schema,
                    f"{path}/{key}",
                    depth + 1,
                    state,
                )
            elif schema.get("additionalProperties", True) is False:
                _schema_error("ADDITIONAL_PROPERTY", f"{path}/{key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                _validate_schema_subset(
                    child,
                    schema["additionalProperties"],
                    root_schema,
                    f"{path}/{key}",
                    depth + 1,
                    state,
                )
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            _schema_error("MIN_PROPERTIES", path)
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            _schema_error("MIN_ITEMS", path)
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            _schema_error("MAX_ITEMS", path)
        if schema.get("uniqueItems") is True:
            for index, value in enumerate(instance):
                if any(_json_equal(value, prior) for prior in instance[:index]):
                    _schema_error("UNIQUE_ITEMS", f"{path}/{index}")
        if "items" in schema:
            for index, value in enumerate(instance):
                _validate_schema_subset(
                    value,
                    schema["items"],
                    root_schema,
                    f"{path}/{index}",
                    depth + 1,
                    state,
                )
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            _schema_error("MIN_LENGTH", path)
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            _schema_error("MAX_LENGTH", path)
        if "pattern" in schema:
            pattern = schema["pattern"]
            if not isinstance(pattern, str):
                _schema_error("PATTERN_SHAPE", path)
            try:
                matched = re.search(pattern, instance) is not None
            except re.error as error:
                _schema_error("PATTERN_INVALID", f"{path}:{error}")
            if not matched:
                _schema_error("PATTERN", path)
        if schema.get("format") == "date":
            try:
                parsed = datetime.date.fromisoformat(instance)
            except ValueError:
                _schema_error("FORMAT_DATE", path)
            if parsed.isoformat() != instance:
                _schema_error("FORMAT_DATE", path)
        elif "format" in schema:
            _schema_error("UNSUPPORTED_FORMAT", schema["format"])
    if isinstance(instance, int | float) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            _schema_error("MINIMUM", path)
        if "maximum" in schema and instance > schema["maximum"]:
            _schema_error("MAXIMUM", path)


def _check_schema_keywords(
    schema: object, root_schema: dict[str, object], depth: int, state: list[int]
) -> None:
    state[0] += 1
    if state[0] > MAX_SCHEMA_VALIDATION_STEPS:
        _schema_error("STEP_LIMIT", "schema")
    if depth > MAX_SCHEMA_DEPTH:
        _schema_error("DEPTH_LIMIT", "schema")
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        _schema_error("SCHEMA_SHAPE", type(schema).__name__)
    unsupported = set(schema) - SUPPORTED_SCHEMA_KEYWORDS
    if unsupported:
        _schema_error("UNSUPPORTED_KEYWORD", sorted(unsupported))
    for name in ("$defs", "properties"):
        mapping = schema.get(name, {})
        if not isinstance(mapping, dict):
            _schema_error(f"{name.upper()}_SHAPE", type(mapping).__name__)
        for child in mapping.values():
            _check_schema_keywords(child, root_schema, depth + 1, state)
    for name in ("items", "additionalProperties", "if", "then"):
        if name not in schema:
            continue
        if not isinstance(schema[name], dict | bool):
            _schema_error(f"{name.upper()}_SHAPE", type(schema[name]).__name__)
        _check_schema_keywords(schema[name], root_schema, depth + 1, state)
    for name in ("allOf", "anyOf", "oneOf"):
        if name in schema:
            branches = schema[name]
            if not isinstance(branches, list) or not branches:
                _schema_error(f"{name.upper()}_SHAPE", type(branches).__name__)
            for child in branches:
                _check_schema_keywords(child, root_schema, depth + 1, state)
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str):
            _schema_error("REF_SHAPE", type(reference).__name__)
        _resolve_local_ref(root_schema, reference)


def validate_schema_subset(instance: object, schema: object, label: str) -> None:
    if not isinstance(schema, dict):
        _schema_error("ROOT_SCHEMA_SHAPE", label)
    if (
        json_node_count(schema) > MAX_JSON_NODES
        or json_node_count(instance) > MAX_JSON_NODES
    ):
        _schema_error("NODE_LIMIT", label)
    _check_schema_keywords(schema, schema, 0, [0])
    _validate_schema_subset(instance, schema, schema, "$", 0, [0])


def validate_schema(instance: object, schema: object, label: str) -> None:
    try:
        validate_schema_subset(instance, schema, label)
    except SchemaSubsetError as error:
        fail("FEDERAL_ORACLE_SCHEMA_INVALID", f"{label}:{error}")


def validate_relative(relative: str) -> PurePosixPath:
    if len(relative.encode("utf-8")) > MAX_PATH_BYTES:
        fail("FEDERAL_ORACLE_PATH_LENGTH", relative)
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or len(pure.parts) > MAX_PATH_COMPONENTS
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        fail("FEDERAL_ORACLE_PATH_INVALID", relative)
    return pure


def _descriptor_read(
    base: Path,
    parts: tuple[str, ...],
    maximum: int,
    identity: str,
    runtime: bool = False,
) -> tuple[Path, bytes]:
    """Read through a held openat chain; no checked parent is reopened by path."""
    if not parts or any(part in {"", ".", ".."} for part in parts):
        fail("FEDERAL_ORACLE_PATH_INVALID", identity)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    file_flags = (
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    base_absolute = Path(os.path.abspath(base))
    base_parts = PurePosixPath(str(base_absolute)).parts[1:]
    chain = (*base_parts, *parts)
    if len(chain) > MAX_PATH_COMPONENTS * 3:
        fail("FEDERAL_ORACLE_PATH_INVALID", identity)
    descriptors: list[int] = []
    file_descriptor: int | None = None
    try:
        root_descriptor = os.open(Path("/"), directory_flags)
        descriptors.append(root_descriptor)
        current = root_descriptor
        for component in chain[:-1]:
            before = os.stat(component, dir_fd=current, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                fail("FEDERAL_ORACLE_SYMLINK_REJECTED", identity)
            if not stat.S_ISDIR(before.st_mode):
                fail("FEDERAL_ORACLE_PATH_COMPONENT_NOT_DIRECTORY", identity)
            child = os.open(component, directory_flags, dir_fd=current)
            opened = os.fstat(child)
            after = os.stat(component, dir_fd=current, follow_symlinks=False)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or len(
                    {
                        (before.st_dev, before.st_ino),
                        (opened.st_dev, opened.st_ino),
                        (after.st_dev, after.st_ino),
                    }
                )
                != 1
            ):
                os.close(child)
                fail("FEDERAL_ORACLE_INODE_CHANGED", identity)
            descriptors.append(child)
            current = child
        filename = chain[-1]
        before_file = os.stat(filename, dir_fd=current, follow_symlinks=False)
        if stat.S_ISLNK(before_file.st_mode):
            fail("FEDERAL_ORACLE_SYMLINK_REJECTED", identity)
        if not stat.S_ISREG(before_file.st_mode):
            fail("FEDERAL_ORACLE_NOT_REGULAR_FILE", identity)
        file_descriptor = os.open(filename, file_flags, dir_fd=current)
        opened_before = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened_before.st_mode) or (
            opened_before.st_dev,
            opened_before.st_ino,
        ) != (before_file.st_dev, before_file.st_ino):
            fail("FEDERAL_ORACLE_INODE_CHANGED", identity)
        byte_limit_code = (
            "FEDERAL_ORACLE_RUNTIME_BYTE_LIMIT"
            if runtime
            else "FEDERAL_ORACLE_INPUT_BYTE_LIMIT"
        )
        if opened_before.st_size > maximum:
            fail(byte_limit_code, f"{identity}:{opened_before.st_size}>{maximum}")
        data = bytearray()
        while True:
            chunk = os.read(file_descriptor, min(1_048_576, maximum + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > maximum:
                fail(byte_limit_code, f"{identity}:{len(data)}>{maximum}")
        opened_after = os.fstat(file_descriptor)
        after_file = os.stat(filename, dir_fd=current, follow_symlinks=False)
        if (
            opened_before.st_size != opened_after.st_size
            or len(
                {
                    (before_file.st_dev, before_file.st_ino),
                    (opened_before.st_dev, opened_before.st_ino),
                    (opened_after.st_dev, opened_after.st_ino),
                    (after_file.st_dev, after_file.st_ino),
                }
            )
            != 1
        ):
            fail("FEDERAL_ORACLE_INODE_CHANGED", identity)
        return base_absolute.joinpath(*parts), bytes(data)
    except OSError as error:
        fail("FEDERAL_ORACLE_PATH_DESCRIPTOR", f"{identity}:{error.errno}")
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def vetted_project_read(relative: str, maximum: int) -> bytes:
    pure = validate_relative(relative)
    return _descriptor_read(ROOT, pure.parts, maximum, relative)[1]


def vetted_absolute_read(path: Path, maximum: int) -> tuple[Path, bytes]:
    if not path.is_absolute() or len(str(path).encode("utf-8")) > 2048:
        fail("FEDERAL_ORACLE_RUNTIME_PATH", str(path))
    pure = PurePosixPath(str(path))
    if len(pure.parts) - 1 > MAX_PATH_COMPONENTS * 2:
        fail("FEDERAL_ORACLE_RUNTIME_PATH", str(path))
    return _descriptor_read(Path("/"), pure.parts[1:], maximum, str(path), runtime=True)


def read_pinned(desc: dict[str, object], maximum: int) -> bytes:
    if set(desc) != {"path", "digest", "byteLength"}:
        fail("FEDERAL_ORACLE_PIN_SHAPE", desc)
    data = vetted_project_read(str(desc["path"]), maximum)
    if len(data) != desc["byteLength"] or digest_bytes(data) != desc["digest"]:
        fail("FEDERAL_ORACLE_PIN_MISMATCH", desc["path"])
    return data


def parse_address(address: str) -> tuple[int, int]:
    match = ADDRESS.fullmatch(address)
    if not match:
        fail("FEDERAL_ORACLE_ADDRESS_INVALID", address)
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - 64
    return int(match.group(2)), column


def make_address(row: int, column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"


def expand_range(value: str) -> list[str]:
    parts = value.split(":")
    if len(parts) != 2:
        fail("FEDERAL_ORACLE_RANGE_INVALID", value)
    start_row, start_col = parse_address(parts[0])
    end_row, end_col = parse_address(parts[1])
    if start_row > end_row or start_col > end_col:
        fail("FEDERAL_ORACLE_RANGE_REVERSED", value)
    count = (end_row - start_row + 1) * (end_col - start_col + 1)
    if count > MAX_RECORDS:
        fail("FEDERAL_ORACLE_RANGE_BUDGET", value)
    return [
        make_address(row, col)
        for row in range(start_row, end_row + 1)
        for col in range(start_col, end_col + 1)
    ]


def inside_range(address: str, specification: str) -> bool:
    row, column = parse_address(address)
    first, last = specification.split(":")
    first_row, first_column = parse_address(first)
    last_row, last_column = parse_address(last)
    return first_row <= row <= last_row and first_column <= column <= last_column


def require_authoritative_range(
    specification: str, identity: object, *addresses: str
) -> None:
    if not all(inside_range(item, specification) for item in addresses):
        fail("FEDERAL_ORACLE_AUTHORITATIVE_RANGE", f"{identity}:{addresses}")


def domain_digest(domain: str, value: object) -> str:
    payload = domain.encode("utf-8") + b"\0" + stable_bytes(value).rstrip(b"\n")
    return digest_bytes(payload)


def xml_root(data: bytes, part: str) -> ET.Element:
    if len(data) > MAX_ENTRY_BYTES:
        fail("FEDERAL_ORACLE_XML_TOO_LARGE", part)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        fail("FEDERAL_ORACLE_XML_INVALID", f"{part}:{error}")
    nodes = sum(1 for _ in root.iter())
    if nodes > MAX_XML_NODES:
        fail("FEDERAL_ORACLE_XML_NODE_LIMIT", f"{part}:{nodes}")
    return root


def joined_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(item.text or "" for item in node.findall(".//m:t", NS))


class RawSheet:
    """A bounded, non-executing OOXML projection built from already-vetted bytes."""

    def __init__(
        self,
        workbook_bytes: bytes,
        physical_sheet: str,
        identity: str,
        bounded_range: str | None = None,
    ) -> None:
        with zipfile.ZipFile(io.BytesIO(workbook_bytes)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > MAX_ZIP_ENTRIES
                or sum(entry.file_size for entry in entries) > MAX_TOTAL_BYTES
            ):
                fail("FEDERAL_ORACLE_ZIP_LIMIT", identity)
            names_list = [entry.filename for entry in entries]
            if len(names_list) != len(set(names_list)):
                fail("FEDERAL_ORACLE_ZIP_DUPLICATE_ENTRY", identity)
            for entry in entries:
                if entry.file_size > MAX_ENTRY_BYTES:
                    fail("FEDERAL_ORACLE_ZIP_ENTRY_LIMIT", entry.filename)
                if (
                    entry.filename.startswith("/")
                    or ".." in PurePosixPath(entry.filename).parts
                ):
                    fail("FEDERAL_ORACLE_ZIP_PATH_INVALID", entry.filename)
            names = set(names_list)
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                shared_root = xml_root(
                    archive.read("xl/sharedStrings.xml"), "xl/sharedStrings.xml"
                )
                shared = [joined_text(item) for item in shared_root.findall("m:si", NS)]
            self.number_formats = ["General"]
            self.indents = [0]
            if "xl/styles.xml" in names:
                styles = xml_root(archive.read("xl/styles.xml"), "xl/styles.xml")
                custom_formats = {
                    int(item.attrib["numFmtId"]): item.attrib["formatCode"]
                    for item in styles.findall("m:numFmts/m:numFmt", NS)
                }
                xfs = styles.findall("m:cellXfs/m:xf", NS)
                self.number_formats = [
                    custom_formats.get(
                        int(item.attrib.get("numFmtId", "0")),
                        BUILTIN_NUMBER_FORMATS.get(
                            int(item.attrib.get("numFmtId", "0")), "General"
                        ),
                    )
                    for item in xfs
                ]
                self.indents = []
                for item in xfs:
                    alignment = item.find("m:alignment", NS)
                    self.indents.append(
                        0
                        if alignment is None
                        else int(alignment.attrib.get("indent", "0"))
                    )
            workbook = xml_root(archive.read("xl/workbook.xml"), "xl/workbook.xml")
            relations = xml_root(
                archive.read("xl/_rels/workbook.xml.rels"), "xl/_rels/workbook.xml.rels"
            )
            targets = {
                item.attrib["Id"]: item.attrib["Target"]
                for item in relations.findall("r:Relationship", REL_NS)
            }
            sheet = next(
                (
                    item
                    for item in workbook.findall("m:sheets/m:sheet", NS)
                    if item.attrib["name"] == physical_sheet
                ),
                None,
            )
            if sheet is None:
                fail("FEDERAL_ORACLE_SHEET_MISSING", physical_sheet)
            target = targets[sheet.attrib[f"{{{NS['r']}}}id"]]
            self.part = (
                target[1:]
                if target.startswith("/")
                else posixpath.normpath(posixpath.join("xl", target))
            )
            sheet_root = xml_root(archive.read(self.part), self.part)
            self.cells: dict[str, dict[str, object]] = {}
            self.merges: dict[str, str] = {}
            for item in sheet_root.findall(".//m:c", NS):
                if len(self.cells) >= MAX_PARSED_CELLS:
                    fail("FEDERAL_ORACLE_CELL_LIMIT", identity)
                cell_address = item.attrib["r"]
                value_node = item.find("m:v", NS)
                formula_node = item.find("m:f", NS)
                cell_type = item.attrib.get("t")
                if cell_type == "s" and value_node is not None:
                    raw_value: object = shared[int(value_node.text or "0")]
                elif cell_type == "inlineStr":
                    raw_value = joined_text(item.find("m:is", NS))
                elif cell_type in {"str", "e"} and value_node is not None:
                    raw_value = value_node.text or ""
                elif cell_type == "b" and value_node is not None:
                    raw_value = value_node.text == "1"
                elif value_node is not None:
                    lexeme = value_node.text or ""
                    number = float(lexeme)
                    raw_value = int(number) if number.is_integer() else number
                else:
                    raw_value = None
                data_type = (
                    "blank"
                    if raw_value is None
                    else "boolean"
                    if isinstance(raw_value, bool)
                    else "number"
                    if isinstance(raw_value, int | float)
                    else "string"
                )
                style_index = int(item.attrib.get("s", "0"))
                if style_index >= len(self.number_formats):
                    fail(
                        "FEDERAL_ORACLE_STYLE_INDEX",
                        f"{identity}:{cell_address}:{style_index}",
                    )
                raw_lexeme = None if value_node is None else value_node.text
                raw_semantic_scalar = None
                if raw_value is not None:
                    raw_semantic_scalar = (
                        raw_lexeme
                        if data_type in {"number", "boolean"}
                        else str(raw_value)
                    )
                self.cells[cell_address] = {
                    "address": cell_address,
                    "rawValue": raw_value,
                    "rawLexeme": raw_lexeme,
                    "rawSemanticScalar": raw_semantic_scalar,
                    "dataType": data_type,
                    "formula": None if formula_node is None else formula_node.text,
                    "styleIndex": style_index,
                    "numberFormat": self.number_formats[style_index],
                    "indent": self.indents[style_index],
                    "comment": None,
                }
            merged_count = 0
            for merge in sheet_root.findall("m:mergeCells/m:mergeCell", NS):
                merge_ref = merge.attrib["ref"]
                first, last = merge_ref.split(":")
                first_row, first_column = parse_address(first)
                last_row, last_column = parse_address(last)
                if bounded_range is not None:
                    bound_first, bound_last = bounded_range.split(":")
                    bound_first_row, bound_first_column = parse_address(bound_first)
                    bound_last_row, bound_last_column = parse_address(bound_last)
                    row_start = max(first_row, bound_first_row)
                    row_end = min(last_row, bound_last_row)
                    column_start = max(first_column, bound_first_column)
                    column_end = min(last_column, bound_last_column)
                    if row_start > row_end or column_start > column_end:
                        continue
                else:
                    row_start, row_end = first_row, last_row
                    column_start, column_end = first_column, last_column
                merged_count += (row_end - row_start + 1) * (
                    column_end - column_start + 1
                )
                if merged_count > MAX_MERGED_CELLS:
                    fail("FEDERAL_ORACLE_MERGE_LIMIT", identity)
                for row in range(row_start, row_end + 1):
                    for column in range(column_start, column_end + 1):
                        self.merges[make_address(row, column)] = first
            relation_part = posixpath.join(
                posixpath.dirname(self.part),
                "_rels",
                posixpath.basename(self.part) + ".rels",
            )
            comment_count = 0
            if relation_part in names:
                sheet_relations = xml_root(archive.read(relation_part), relation_part)
                for relation in sheet_relations.findall("r:Relationship", REL_NS):
                    if relation.attrib.get("Type", "").endswith("/comments"):
                        comments_target = relation.attrib["Target"]
                        comments_part = (
                            comments_target[1:]
                            if comments_target.startswith("/")
                            else posixpath.normpath(
                                posixpath.join(
                                    posixpath.dirname(self.part), comments_target
                                )
                            )
                        )
                        comments = xml_root(archive.read(comments_part), comments_part)
                        for comment in comments.findall("m:commentList/m:comment", NS):
                            comment_count += 1
                            if comment_count > MAX_COMMENTS:
                                fail("FEDERAL_ORACLE_COMMENT_LIMIT", identity)
                            item_address = comment.attrib["ref"]
                            self.cells.setdefault(
                                item_address, self._blank(item_address)
                            )["comment"] = joined_text(comment)

    def _blank(self, cell_address: str) -> dict[str, object]:
        return {
            "address": cell_address,
            "rawValue": None,
            "rawLexeme": None,
            "rawSemanticScalar": None,
            "dataType": "blank",
            "formula": None,
            "styleIndex": 0,
            "numberFormat": self.number_formats[0],
            "indent": self.indents[0],
            "comment": None,
        }

    def cell(
        self, requested_address: str, *, merged: bool = False
    ) -> dict[str, object]:
        source = (
            self.merges.get(requested_address, requested_address)
            if merged
            else requested_address
        )
        result = dict(self.cells.get(source, self._blank(source)))
        result["requestedAddress"] = requested_address
        result["sourceAddress"] = source
        return result


def formatted_value(cell: dict[str, object]) -> object:
    if cell["dataType"] != "number":
        return cell["rawValue"]
    value = float(cell["rawValue"])
    number_format = cell["numberFormat"]
    if number_format == "#,##0":
        return f"{value:,.0f}"
    if number_format == "#,##0.0":
        return f"{value:,.1f}"
    if number_format == "0.0":
        return f"{value:.1f}"
    if number_format == "0.00":
        return f"{value:.2f}"
    if number_format in {"General", "0"}:
        return cell["rawLexeme"]
    fail("FEDERAL_ORACLE_NUMBER_FORMAT_UNSUPPORTED", number_format)


def exact_source_proof(cell: dict[str, object]) -> dict[str, object]:
    return {
        "sourceAddress": cell["sourceAddress"],
        "rawValue": cell["rawValue"],
        "dataType": cell["dataType"],
        "comment": cell["comment"],
        "styleIndex": cell["styleIndex"],
        "numberFormat": cell["numberFormat"],
        "indent": cell["indent"],
    }


def classify(cell: dict[str, object]) -> dict[str, object]:
    raw = cell["rawValue"]
    comment = cell["comment"]
    if raw is None:
        if comment != "not published\n":
            fail("FEDERAL_ORACLE_UNEXPLAINED_BLANK", cell["address"])
        return {
            "valueStatus": "not-published",
            "markerSource": "cell-comment",
            "sourceComment": comment,
            "valueStatusAuthority": {
                "kind": "exact-comment",
                "rawComment": "not published\n",
                "status": "not-published",
            },
        }
    if raw == "np":
        return {
            "valueStatus": "not-published",
            "markerSource": "cell-value",
            "sourceComment": comment,
            "valueStatusAuthority": None,
        }
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        fail("FEDERAL_ORACLE_TARGET_VALUE_INVALID", f"{cell['address']}={raw!r}")
    return {
        "valueStatus": "observed",
        "markerSource": None,
        "sourceComment": comment,
        "valueStatusAuthority": None,
    }


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def local_descriptor(relative: str, maximum: int) -> dict[str, object]:
    data = vetted_project_read(relative, maximum)
    return {"path": relative, "digest": digest_bytes(data), "byteLength": len(data)}


def _path_is_under(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _open_absolute_directory(path: Path) -> int:
    """Open an absolute directory through retained, no-follow component FDs."""
    absolute = Path(os.path.abspath(path))
    pure = PurePosixPath(str(absolute))
    if not pure.is_absolute() or len(pure.parts) - 1 > MAX_PATH_COMPONENTS * 2:
        fail("FEDERAL_ORACLE_RUNTIME_TREE_PATH", str(path))
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    current = os.open(Path("/"), flags)
    try:
        for component in pure.parts[1:]:
            before = os.stat(component, dir_fd=current, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode) or stat.S_ISLNK(before.st_mode):
                fail("FEDERAL_ORACLE_RUNTIME_TREE_COMPONENT", str(path))
            child = os.open(component, flags, dir_fd=current)
            opened = os.fstat(child)
            after = os.stat(component, dir_fd=current, follow_symlinks=False)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or len(
                    {
                        (before.st_dev, before.st_ino),
                        (opened.st_dev, opened.st_ino),
                        (after.st_dev, after.st_ino),
                    }
                )
                != 1
            ):
                os.close(child)
                fail("FEDERAL_ORACLE_RUNTIME_TREE_INODE", str(path))
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def _read_runtime_tree_file(parent_fd: int, name: str, identity: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        fail("FEDERAL_ORACLE_RUNTIME_TREE_FILE_TYPE", identity)
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        opened_before = os.fstat(descriptor)
        if (opened_before.st_dev, opened_before.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            fail("FEDERAL_ORACLE_RUNTIME_TREE_INODE", identity)
        if opened_before.st_size > MAX_RUNTIME_FILE_BYTES:
            fail("FEDERAL_ORACLE_RUNTIME_BYTE_LIMIT", identity)
        payload = bytearray()
        while True:
            chunk = os.read(
                descriptor,
                min(1_048_576, MAX_RUNTIME_FILE_BYTES + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > MAX_RUNTIME_FILE_BYTES:
                fail("FEDERAL_ORACLE_RUNTIME_BYTE_LIMIT", identity)
        opened_after = os.fstat(descriptor)
        after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            opened_before.st_size != opened_after.st_size
            or len(
                {
                    (before.st_dev, before.st_ino),
                    (opened_before.st_dev, opened_before.st_ino),
                    (opened_after.st_dev, opened_after.st_ino),
                    (after.st_dev, after.st_ino),
                }
            )
            != 1
        ):
            fail("FEDERAL_ORACLE_RUNTIME_TREE_INODE", identity)
        return bytes(payload)
    finally:
        os.close(descriptor)


def inventory_runtime_tree(
    root: Path, roles: list[str]
) -> tuple[dict[str, object], set[str]]:
    """Inventory one stdlib tree through held descriptor-relative traversal."""
    root_path = Path(os.path.abspath(root))
    root_fd = _open_absolute_directory(root_path)
    entries: list[dict[str, object]] = []
    covered: set[str] = set()
    regular_bytes = 0
    regular_count = 0
    symlink_count = 0
    node_count = 0
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )

    def walk(directory_fd: int, prefix: tuple[str, ...]) -> None:
        nonlocal regular_bytes, regular_count, symlink_count, node_count
        names = sorted(os.listdir(directory_fd), key=utf8_key)
        for name in names:
            if name in RUNTIME_TREE_EXCLUDED_DIRECTORIES:
                continue
            if name in {"", ".", ".."} or "/" in name or "\x00" in name:
                fail("FEDERAL_ORACLE_RUNTIME_TREE_ENTRY", name)
            relative_parts = (*prefix, name)
            relative = "/".join(relative_parts)
            if len(relative.encode("utf-8")) > 2_048:
                fail("FEDERAL_ORACLE_RUNTIME_TREE_PATH", relative)
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            node_count += 1
            if node_count > MAX_RUNTIME_TREE_NODES:
                fail("FEDERAL_ORACLE_RUNTIME_TREE_NODE_LIMIT", node_count)
            if stat.S_ISDIR(before.st_mode):
                child = os.open(name, directory_flags, dir_fd=directory_fd)
                try:
                    opened = os.fstat(child)
                    after_open = os.stat(
                        name, dir_fd=directory_fd, follow_symlinks=False
                    )
                    if (
                        not stat.S_ISDIR(opened.st_mode)
                        or len(
                            {
                                (before.st_dev, before.st_ino),
                                (opened.st_dev, opened.st_ino),
                                (after_open.st_dev, after_open.st_ino),
                            }
                        )
                        != 1
                    ):
                        fail("FEDERAL_ORACLE_RUNTIME_TREE_INODE", relative)
                    walk(child, relative_parts)
                    after_walk = os.stat(
                        name, dir_fd=directory_fd, follow_symlinks=False
                    )
                    if (after_walk.st_dev, after_walk.st_ino) != (
                        opened.st_dev,
                        opened.st_ino,
                    ):
                        fail("FEDERAL_ORACLE_RUNTIME_TREE_INODE", relative)
                finally:
                    os.close(child)
            elif stat.S_ISREG(before.st_mode):
                blob = _read_runtime_tree_file(directory_fd, name, relative)
                regular_count += 1
                regular_bytes += len(blob)
                if regular_count > MAX_RUNTIME_TREE_FILES:
                    fail("FEDERAL_ORACLE_RUNTIME_TREE_FILE_LIMIT", regular_count)
                if regular_bytes > MAX_RUNTIME_TOTAL_BYTES:
                    fail("FEDERAL_ORACLE_RUNTIME_TOTAL_BYTE_LIMIT", regular_bytes)
                entries.append(
                    {
                        "kind": "regular-file",
                        "path": relative,
                        "digest": digest_bytes(blob),
                        "byteLength": len(blob),
                    }
                )
                covered.add(str(root_path.joinpath(*relative_parts)))
            elif stat.S_ISLNK(before.st_mode):
                target = os.readlink(name, dir_fd=directory_fd)
                after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
                    fail("FEDERAL_ORACLE_RUNTIME_TREE_INODE", relative)
                if len(target.encode("utf-8")) > 2_048:
                    fail("FEDERAL_ORACLE_RUNTIME_TREE_SYMLINK", relative)
                symlink_count += 1
                if symlink_count > MAX_RUNTIME_TREE_SYMLINKS:
                    fail("FEDERAL_ORACLE_RUNTIME_TREE_SYMLINK_LIMIT", symlink_count)
                entries.append(
                    {
                        "kind": "symlink",
                        "path": relative,
                        "target": target,
                        "mode": stat.S_IMODE(before.st_mode),
                    }
                )
            else:
                fail("FEDERAL_ORACLE_RUNTIME_TREE_NODE_TYPE", relative)

    try:
        walk(root_fd, ())
    finally:
        os.close(root_fd)
    entries.sort(key=lambda item: utf8_key(str(item["path"])))
    descriptor = {
        "roles": sorted(roles, key=utf8_key),
        "path": str(root_path),
        "regularFileCount": regular_count,
        "regularFileByteLength": regular_bytes,
        "symlinkCount": symlink_count,
        "contentDigest": digest_bytes(stable_bytes(entries)),
    }
    return descriptor, covered


def _runtime_tree_roots() -> list[tuple[Path, list[str]]]:
    roles_by_path: dict[str, list[str]] = {}
    base = str(Path(sys._base_executable).resolve(strict=True).parents[1])
    variables = {
        "base": base,
        "platbase": base,
        "installed_base": base,
        "installed_platbase": base,
    }
    for role in ("stdlib", "platstdlib"):
        path = os.path.abspath(sysconfig.get_path(role, vars=variables))
        roles_by_path.setdefault(path, []).append(role)
    return [
        (Path(path), sorted(roles, key=utf8_key))
        for path, roles in sorted(
            roles_by_path.items(), key=lambda item: utf8_key(item[0])
        )
    ]


def _allowed_import_paths(tree_roots: list[tuple[Path, list[str]]]) -> list[str]:
    allowed = {str(ROOT), str(ROOT / "scripts")}
    for root, _ in tree_roots:
        allowed.add(str(root))
        allowed.add(str(root / "lib-dynload"))
        allowed.add(
            str(
                root.parent
                / f"python{sys.version_info.major}{sys.version_info.minor}.zip"
            )
        )
    return sorted(allowed, key=utf8_key)


def bootstrap_runtime_custody() -> tuple[dict[str, object], set[str]]:
    """Pin complete stdlib trees plus explicit executable/shared-library bytes."""
    total = 0
    files: dict[str, Path] = {"cpython-executable": Path(sys._base_executable)}
    framework = Path(sys._base_executable).resolve(strict=True).parents[1] / "Python"
    if framework.is_file():
        files["python-shared-library"] = framework
    descriptors: list[dict[str, object]] = []
    for identity, runtime_path in sorted(
        files.items(), key=lambda item: utf8_key(item[0])
    ):
        resolved, blob = vetted_absolute_read(runtime_path, MAX_RUNTIME_FILE_BYTES)
        total += len(blob)
        if total > MAX_RUNTIME_TOTAL_BYTES:
            fail("FEDERAL_ORACLE_RUNTIME_TOTAL_BYTE_LIMIT", total)
        descriptors.append(
            {
                "identity": identity,
                "path": str(resolved),
                "digest": digest_bytes(blob),
                "byteLength": len(blob),
            }
        )
    tree_roots = _runtime_tree_roots()
    trees: list[dict[str, object]] = []
    covered: set[str] = set()
    tree_bytes = 0
    for root, roles in tree_roots:
        descriptor, tree_covered = inventory_runtime_tree(root, roles)
        tree_bytes += int(descriptor["regularFileByteLength"])
        if total + tree_bytes > MAX_RUNTIME_TOTAL_BYTES:
            fail("FEDERAL_ORACLE_RUNTIME_TOTAL_BYTE_LIMIT", total + tree_bytes)
        trees.append(descriptor)
        covered.update(tree_covered)
    runtime = {
        "implementation": sys.implementation.name,
        "version": list(sys.version_info[:3]),
        "cacheTag": sys.implementation.cache_tag,
        "byteOrder": sys.byteorder,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "libc": list(platform.libc_ver()),
        "macVersion": [
            platform.mac_ver()[0],
            list(platform.mac_ver()[1]),
            platform.mac_ver()[2],
        ],
        "zlibCompileVersion": zlib.ZLIB_VERSION,
        "zlibRuntimeVersion": zlib.ZLIB_RUNTIME_VERSION,
        "files": descriptors,
        "trees": trees,
        "allowedImportPaths": _allowed_import_paths(tree_roots),
        "distributions": [],
    }
    return runtime, covered


def require_acceptance_cli_flags() -> None:
    if not (
        sys.implementation.name == "cpython"
        and sys.flags.isolated == 1
        and sys.flags.no_site == 1
        and sys.flags.dont_write_bytecode == 1
        and sys.flags.ignore_environment == 1
        and sys.flags.safe_path
    ):
        fail("FEDERAL_ORACLE_RUNTIME_FLAGS", "require CPython -I -S -B")


def audit_acceptance_import_path(runtime: dict[str, object]) -> None:
    allowed = {os.path.abspath(str(path)) for path in runtime["allowedImportPaths"]}
    forbidden_roots = {
        os.path.abspath(sysconfig.get_paths()[key]) for key in ("purelib", "platlib")
    }
    observed: list[str] = []
    for value in sys.path:
        if not isinstance(value, str) or value == "":
            fail("FEDERAL_ORACLE_RUNTIME_SYS_PATH", value)
        absolute = os.path.abspath(value)
        components = PurePosixPath(absolute).parts
        if any(part in RUNTIME_TREE_EXCLUDED_DIRECTORIES for part in components):
            fail("FEDERAL_ORACLE_RUNTIME_SYS_PATH", absolute)
        if any(_path_is_under(absolute, root) for root in forbidden_roots):
            fail("FEDERAL_ORACLE_RUNTIME_SYS_PATH", absolute)
        if absolute not in allowed:
            fail("FEDERAL_ORACLE_RUNTIME_SYS_PATH", absolute)
        observed.append(absolute)
    if len(observed) != len(set(observed)):
        fail("FEDERAL_ORACLE_RUNTIME_SYS_PATH", "duplicate")


def audit_all_loaded_modules(runtime: dict[str, object], covered: set[str]) -> None:
    toolchain = {str(ROOT / path) for path in TOOLCHAIN_PATHS if path.endswith(".py")}
    forbidden_roots = {
        os.path.abspath(sysconfig.get_paths()[key]) for key in ("purelib", "platlib")
    }
    uncovered: list[str] = []
    for name in sorted(sys.modules, key=utf8_key):
        module = sys.modules.get(name)
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None)
        if origin in {"built-in", "frozen"}:
            continue
        for attribute in ("__file__", "__cached__"):
            value = getattr(module, attribute, None)
            if not value:
                continue
            absolute = os.path.abspath(str(value))
            if attribute == "__cached__" and not os.path.exists(absolute):
                continue
            is_forbidden = any(
                _path_is_under(absolute, root) for root in forbidden_roots
            )
            if is_forbidden or (absolute not in covered and absolute not in toolchain):
                uncovered.append(f"{name}:{attribute}:{absolute}")
    if uncovered:
        fail("FEDERAL_ORACLE_RUNTIME_MODULE_UNCOVERED", uncovered)


def attest_acceptance_runtime(runtime: dict[str, object]) -> None:
    audit_acceptance_import_path(runtime)
    observed, covered = bootstrap_runtime_custody()
    if observed != runtime:
        fail("FEDERAL_ORACLE_RUNTIME_TREE_PIN", observed)
    audit_all_loaded_modules(runtime, covered)


def semantic_payload(cell: dict[str, object]) -> dict[str, str]:
    payload = {"address": str(cell["address"])}
    if cell["formula"] is not None:
        payload["formula"] = str(cell["formula"])
    scalar = cell["rawSemanticScalar"]
    if scalar not in {None, ""}:
        payload["value"] = str(scalar)
    return payload


def validate_exclusion_ledger(
    ledger: dict[str, object],
    inventory: dict[str, object],
    workbook_cache: dict[str, tuple[bytes, str, int]],
) -> None:
    sheets = ledger.get("sheets")
    if not isinstance(sheets, list) or len(sheets) != ledger.get("boundedSheetCount"):
        fail("FEDERAL_ORACLE_EXCLUSION_LEDGER_SHAPE", "sheets")
    excluded_total = 0
    for entry in sheets:
        source_path = str(entry["sourcePath"])
        if source_path not in workbook_cache:
            fail("FEDERAL_ORACLE_EXCLUSION_SOURCE", source_path)
        workbook_bytes, source_digest, _ = workbook_cache[source_path]
        if source_digest != entry["sourceDigest"]:
            fail("FEDERAL_ORACLE_EXCLUSION_SOURCE_DIGEST", source_path)
        sheet = RawSheet(
            workbook_bytes,
            str(entry["physicalSheetName"]),
            source_path,
            str(entry["authoritativeRange"]),
        )
        authority = sheet.cell(str(entry["authorityCell"]))
        if authority["rawValue"] != entry["authorityText"]:
            fail("FEDERAL_ORACLE_EXCLUSION_AUTHORITY", source_path)
        bounded: list[dict[str, str]] = []
        excluded: list[dict[str, str]] = []
        for cell in sheet.cells.values():
            if cell["formula"] is None and cell["rawSemanticScalar"] in {None, ""}:
                continue
            payload = semantic_payload(cell)
            (
                bounded
                if inside_range(str(cell["address"]), str(entry["authoritativeRange"]))
                else excluded
            ).append(payload)
        bounded.sort(key=lambda item: utf8_key(item["address"]))
        excluded.sort(key=lambda item: utf8_key(item["address"]))
        if (
            len(bounded) != entry["boundedSemanticCellCount"]
            or domain_digest("tidy.xlsx-bounded-semantic-cells/v1", bounded)
            != entry["boundedSemanticCellDigest"]
        ):
            fail("FEDERAL_ORACLE_BOUNDED_SEMANTIC_CLOSURE", source_path)
        if (
            excluded != entry["excludedNonblankCells"]
            or len(excluded) != entry["excludedNonblankCellCount"]
        ):
            fail("FEDERAL_ORACLE_EXCLUSION_CELL_CLOSURE", source_path)
        if (
            domain_digest(
                "tidy.xlsx-out-of-authoritative-range-nonblank-cells/v1", excluded
            )
            != entry["exclusionDigest"]
        ):
            fail("FEDERAL_ORACLE_EXCLUSION_DIGEST", source_path)
        excluded_total += len(excluded)
    if (
        excluded_total != ledger.get("excludedNonblankCellCount")
        or excluded_total != 1_041
    ):
        fail("FEDERAL_ORACLE_EXCLUSION_TOTAL", excluded_total)
    ledger_body = dict(ledger)
    declared_ledger_digest = ledger_body.pop("ledgerDigest", None)
    recomputed_ledger_digest = domain_digest(str(ledger["schemaVersion"]), ledger_body)
    if declared_ledger_digest != recomputed_ledger_digest:
        fail("FEDERAL_ORACLE_EXCLUSION_LEDGER_DIGEST", declared_ledger_digest)
    if (
        inventory.get("boundedRangeExclusionLedgerDigest") != recomputed_ledger_digest
        or inventory.get("boundedRangeExcludedNonblankCellCount") != excluded_total
        or inventory.get("boundedRangeSheetCount") != len(sheets)
    ):
        fail("FEDERAL_ORACLE_EXCLUSION_INVENTORY_RELATION", recomputed_ledger_digest)


def validate_family_custody(
    authority: dict[str, object], evidence: dict[str, object]
) -> None:
    members = authority["members"]
    policies = authority["familyPolicies"]
    member_ids = [member["memberId"] for member in members]
    if len(member_ids) != len(set(member_ids)):
        fail("FEDERAL_ORACLE_MEMBER_DUPLICATE", member_ids)
    actual_by_family: dict[str, list[str]] = {}
    for member in members:
        actual_by_family.setdefault(member["familyId"], []).append(member["memberId"])
    policy_by_family = {item["familyId"]: item for item in policies}
    if set(actual_by_family) != set(policy_by_family) or len(policy_by_family) != 23:
        fail(
            "FEDERAL_ORACLE_FAMILY_POLICY_SET",
            set(actual_by_family) ^ set(policy_by_family),
        )
    for family_id, ids in actual_by_family.items():
        if policy_by_family[family_id]["memberIds"] != sorted(ids, key=utf8_key):
            fail("FEDERAL_ORACLE_FAMILY_POLICY_MEMBERS", family_id)
    membership = evidence["familyMembership"]
    crosswalk = evidence["familyCrosswalk"]
    for document, label in ((membership, "membership"), (crosswalk, "crosswalk")):
        families = document.get("families")
        if not isinstance(families, list) or {
            item["familyId"] for item in families
        } != set(actual_by_family):
            fail("FEDERAL_ORACLE_FAMILY_CUSTODY_SET", label)
        by_family = {item["familyId"]: item for item in families}
        for family_id, ids in actual_by_family.items():
            authority_members = [
                next(item for item in members if item["memberId"] == member_id)
                for member_id in ids
            ]
            custody_members = by_family[family_id]["members"]
            expected = sorted(
                (item["releaseId"], item["sheet"], item["publishedTitle"])
                for item in authority_members
            )
            observed = sorted(
                (item["releaseId"], item["physicalSheetName"], item["publishedTitle"])
                for item in custody_members
            )
            if expected != observed:
                fail("FEDERAL_ORACLE_FAMILY_CUSTODY_MEMBERS", f"{label}:{family_id}")


def build(output_root: Path, *, attesting_runtime: bool = False) -> dict[str, object]:
    authority_bytes = vetted_project_read(AUTHORITY, MAX_AUTHORITY_BYTES)
    authority = load_json(authority_bytes, AUTHORITY, MAX_AUTHORITY_BYTES)
    if not isinstance(authority, dict):
        fail("FEDERAL_ORACLE_AUTHORITY_SHAPE", type(authority).__name__)
    # Acceptance-critical generation uses isolated, complete stdlib-tree custody.
    runtime, _ = bootstrap_runtime_custody()
    schemas: dict[str, object] = {}
    for schema_path in SCHEMA_PATHS:
        schemas[schema_path] = load_json(
            vetted_project_read(schema_path, MAX_SCHEMA_BYTES),
            schema_path,
            MAX_SCHEMA_BYTES,
        )
    validate_schema(
        authority,
        schemas[
            "contracts/product-prototype/v1/federal-defendants-semantic-plan.schema.json"
        ],
        AUTHORITY,
    )
    if set(authority["evidence"]) != REQUIRED_EVIDENCE:
        fail(
            "FEDERAL_ORACLE_EVIDENCE_SET",
            set(authority["evidence"]) ^ REQUIRED_EVIDENCE,
        )
    evidence_bytes = {
        name: read_pinned(descriptor, MAX_EVIDENCE_JSON_BYTES)
        for name, descriptor in authority["evidence"].items()
    }
    evidence_documents = {
        name: load_json(
            data, str(authority["evidence"][name]["path"]), MAX_EVIDENCE_JSON_BYTES
        )
        for name, data in evidence_bytes.items()
    }
    validate_schema(
        evidence_documents["controlledVocabulary"],
        schemas[
            "contracts/product-prototype/v1/federal-defendants-controlled-vocabulary.schema.json"
        ],
        "controlledVocabulary",
    )
    validate_schema(
        evidence_documents["methodologyEvidence"],
        schemas[
            "contracts/product-prototype/v1/federal-defendants-methodology-evidence.schema.json"
        ],
        "methodologyEvidence",
    )
    vocabulary = evidence_documents["controlledVocabulary"]
    controlled_values = {
        item["field"]: {entry["id"] for entry in item["values"]}
        for item in vocabulary["fields"]
    }
    methodology = evidence_documents["methodologyEvidence"]
    methodology_documents: dict[str, str] = {}
    for descriptor in methodology["documents"]:
        document_pin = {
            key: descriptor[key] for key in ("path", "digest", "byteLength")
        }
        data = read_pinned(document_pin, MAX_EVIDENCE_JSON_BYTES)
        methodology_documents[descriptor["path"]] = data.decode("utf-8")
    for claim in methodology["claims"]:
        if (
            claim["exactExcerpt"]
            not in methodology_documents[claim["evidenceDocument"]]
        ):
            fail("FEDERAL_ORACLE_METHODOLOGY_EXCERPT", claim["claimId"])
    validate_family_custody(authority, evidence_documents)
    if sum(len(member["blocks"]) for member in authority["members"]) != 148:
        fail("FEDERAL_ORACLE_BLOCK_TOTAL", "not 148")

    downloads = evidence_documents["releaseDownloads"]
    inventory = evidence_documents["sourceInventory"]
    download_by_path = {item["path"]: item for item in downloads["downloads"]}
    inventory_by_path = {item["path"]: item for item in inventory["downloads"]}
    workbook_cache: dict[str, tuple[bytes, str, int]] = {}
    for member in authority["members"]:
        source_path = member["sourcePath"]
        for catalog, label in (
            (download_by_path, "downloads"),
            (inventory_by_path, "inventory"),
        ):
            declaration = catalog.get(source_path)
            if (
                declaration is None
                or declaration["contentDigest"] != member["sourceDigest"]
                or declaration["byteLength"] != member["sourceByteLength"]
            ):
                fail("FEDERAL_ORACLE_SOURCE_CUSTODY", f"{label}:{source_path}")
        if source_path not in workbook_cache:
            data = vetted_project_read(
                "fixtures/product-prototype/" + source_path, 25_000_000
            )
            if (
                len(data) != member["sourceByteLength"]
                or digest_bytes(data) != member["sourceDigest"]
            ):
                fail("FEDERAL_ORACLE_SOURCE_IDENTITY", member["memberId"])
            workbook_cache[source_path] = (data, member["sourceDigest"], len(data))
    validate_exclusion_ledger(
        evidence_documents["boundedExclusions"],
        evidence_documents["sourceInventory"],
        workbook_cache,
    )

    family_policies = {item["familyId"]: item for item in authority["familyPolicies"]}
    all_keys: dict[str, set[bytes]] = {key: set() for key in family_policies}
    shard_payloads: list[tuple[str, bytes]] = []
    shard_descriptors: list[dict[str, object]] = []
    totals = {
        "targetCount": 0,
        "notPublishedCount": 0,
        "zeroCount": 0,
        "formulaCount": 0,
    }
    raw_comment_notes: set[tuple[str, str, str]] = set()
    tail_note_cells: set[tuple[str, str, str]] = set()
    layout_headings: set[tuple[str, str, str]] = set()
    comment_statuses: set[tuple[str, str]] = set()

    members = sorted(authority["members"], key=lambda item: utf8_key(item["memberId"]))
    for member in members:
        workbook_bytes = workbook_cache[member["sourcePath"]][0]
        sheet = RawSheet(
            workbook_bytes,
            member["sheet"],
            member["memberId"],
            member["authoritativeRange"],
        )
        authoritative_range = member["authoritativeRange"]
        addresses_to_check = [member["titleSourceAddress"]]
        source_title = member["tableRule"]["sourceTitle"]
        actual_title = sheet.cell(member["titleSourceAddress"], merged=True)
        require_authoritative_range(
            authoritative_range,
            (member["memberId"], "title"),
            member["titleSourceAddress"],
            actual_title["sourceAddress"],
        )
        expected_title = {
            "address": actual_title["sourceAddress"],
            "requestedAddress": member["titleSourceAddress"],
            "sourceAddress": actual_title["sourceAddress"],
            "rawValue": actual_title["rawValue"],
            "rawLexeme": actual_title["rawLexeme"],
            "dataType": actual_title["dataType"],
            "formula": actual_title["formula"],
            "comment": actual_title["comment"],
            "styleIndex": actual_title["styleIndex"],
            "numberFormat": actual_title["numberFormat"],
            "indent": actual_title["indent"],
        }
        if (
            source_title != expected_title
            or actual_title["rawValue"] != member["publishedTitle"]
        ):
            fail("FEDERAL_ORACLE_SOURCE_TITLE_ASSERTION", member["memberId"])
        for field in ("tailNoteRange",):
            if member[field] is not None and not all(
                inside_range(item, authoritative_range)
                for item in expand_range(member[field])
            ):
                fail(
                    "FEDERAL_ORACLE_AUTHORITATIVE_RANGE",
                    f"{member['memberId']}:{field}",
                )
        for assertion in member["layoutAssertions"]:
            addresses_to_check.append(assertion["requestedAddress"])
            actual = sheet.cell(assertion["requestedAddress"], merged=True)
            require_authoritative_range(
                authoritative_range,
                (member["memberId"], "layout"),
                assertion["requestedAddress"],
                actual["sourceAddress"],
            )
            if exact_source_proof(actual) != {
                key: assertion[key]
                for key in (
                    "sourceAddress",
                    "rawValue",
                    "dataType",
                    "comment",
                    "styleIndex",
                    "numberFormat",
                    "indent",
                )
            }:
                fail(
                    "FEDERAL_ORACLE_LAYOUT_ASSERTION",
                    f"{member['memberId']}:{assertion['requestedAddress']}",
                )
            layout_headings.add(
                (
                    member["memberId"],
                    assertion["sourceAddress"],
                    str(assertion["rawValue"]),
                )
            )
        records: list[dict[str, object]] = []
        member_coordinates: list[str] = []
        member_totals = {
            "targetCount": 0,
            "notPublishedCount": 0,
            "zeroCount": 0,
            "formulaCount": 0,
        }
        table_canonical = member["tableRule"]["canonical"]
        expected_comments: set[tuple[str, str]] = set()
        expected_tail_notes: set[tuple[str, str]] = set()
        expected_layout: set[tuple[str, str]] = {
            (item["sourceAddress"], item["rawValue"])
            for item in member["layoutAssertions"]
        }
        for block in member["blocks"]:
            range_fields = ["bodyRange", "rowHeaderRange", "columnHeaderRange"]
            range_fields.extend(
                field
                for field in ("sexHeaderRange", "statisticHeaderRange")
                if block[field] is not None
            )
            for field in range_fields:
                if not all(
                    inside_range(item, authoritative_range)
                    for item in expand_range(block[field])
                ):
                    fail(
                        "FEDERAL_ORACLE_AUTHORITATIVE_RANGE",
                        f"{block['blockId']}:{field}",
                    )
            direct_addresses = [block["panelKeyAddress"]]
            direct_addresses.extend(
                assertion["requestedAddress"] for assertion in block["sourceAssertions"]
            )
            for rule in [*block["rowRules"], *block["columnRules"], block["panelRule"]]:
                direct_addresses.extend([rule["requestedAddress"]])
                if rule.get("parentAddress") is not None:
                    direct_addresses.append(rule["parentAddress"])
            direct_addresses.extend(
                note["sourceAddress"] for note in block["noteDefinitions"]
            )
            addresses_to_check.extend(direct_addresses)
            if not all(
                inside_range(item, authoritative_range) for item in direct_addresses
            ):
                fail("FEDERAL_ORACLE_AUTHORITATIVE_RANGE", block["blockId"])
            coordinates = expand_range(block["bodyRange"])
            if (
                len(coordinates) != block["expandedTargetCount"]
                or digest_bytes(("\n".join(coordinates) + "\n").encode())
                != block["expandedCoordinateDigest"]
            ):
                fail("FEDERAL_ORACLE_COORDINATE_AUTHORITY", block["blockId"])
            for assertion in block["sourceAssertions"]:
                actual = sheet.cell(assertion["requestedAddress"], merged=True)
                require_authoritative_range(
                    authoritative_range,
                    (block["blockId"], "source-assertion"),
                    assertion["requestedAddress"],
                    actual["sourceAddress"],
                )
                expected = {
                    key: assertion[key]
                    for key in (
                        "sourceAddress",
                        "rawValue",
                        "dataType",
                        "comment",
                        "styleIndex",
                        "numberFormat",
                        "indent",
                    )
                }
                if exact_source_proof(actual) != expected:
                    fail(
                        "FEDERAL_ORACLE_SOURCE_ASSERTION",
                        f"{member['memberId']}:{assertion['requestedAddress']}",
                    )
            note_definitions = {
                item["noteBindingId"]: item for item in block["noteDefinitions"]
            }
            for note in note_definitions.values():
                source_cell = sheet.cell(note["sourceAddress"], merged=True)
                require_authoritative_range(
                    authoritative_range,
                    (block["blockId"], "note"),
                    note["sourceAddress"],
                    source_cell["sourceAddress"],
                )
                source_text = (
                    source_cell["comment"]
                    if note["sourceKind"] == "comment"
                    else source_cell["rawValue"]
                )
                if (
                    source_cell["sourceAddress"] != note["sourceAddress"]
                    or source_text != note["exactText"]
                    or source_cell["styleIndex"] != note["sourceStyleIndex"]
                    or source_cell["indent"] != note["sourceIndent"]
                    or source_cell["numberFormat"] != note["sourceNumberFormat"]
                ):
                    fail(
                        "FEDERAL_ORACLE_NOTE_SOURCE_ASSERTION",
                        f"{member['memberId']}:{note['sourceAddress']}",
                    )
                key = (note["sourceAddress"], note["exactText"])
                if note["sourceKind"] == "comment":
                    expected_comments.add(key)
                    raw_comment_notes.add((member["memberId"], *key))
                else:
                    expected_tail_notes.add(key)
                    tail_note_cells.add((member["memberId"], *key))
            referenced_notes = set(block["blockNoteBindingIds"])
            referenced_notes.update(block["panelRule"]["noteBindingIds"])
            for rule in [*block["rowRules"], *block["columnRules"]]:
                referenced_notes.update(rule["noteBindingIds"])
            if referenced_notes != set(note_definitions):
                fail("FEDERAL_ORACLE_NOTE_COVERAGE", block["blockId"])
            row_rules = {
                parse_address(item["requestedAddress"])[0]: item
                for item in block["rowRules"]
            }
            column_rules = {item["targetColumn"]: item for item in block["columnRules"]}
            policy = family_policies[member["familyId"]]
            for address in coordinates:
                row, column = parse_address(address)
                row_rule = row_rules[row]
                column_rule = column_rules[column]
                panel_rule = block["panelRule"]
                for rule, label in (
                    (row_rule, "row"),
                    (column_rule, "column"),
                    (panel_rule, "panel"),
                ):
                    actual = sheet.cell(rule["requestedAddress"], merged=True)
                    require_authoritative_range(
                        authoritative_range,
                        (block["blockId"], label),
                        rule["requestedAddress"],
                        actual["sourceAddress"],
                    )
                    if (
                        actual["sourceAddress"] != rule["address"]
                        or actual["rawValue"] != rule["rawValue"]
                        or actual["styleIndex"] != rule["styleIndex"]
                        or actual["indent"] != rule["indent"]
                        or actual["numberFormat"] != rule["numberFormat"]
                    ):
                        fail(
                            "FEDERAL_ORACLE_AXIS_ASSERTION",
                            f"{block['blockId']}:{label}:{rule['requestedAddress']}",
                        )
                if column_rule["parentAddress"] is not None:
                    parent = sheet.cell(column_rule["parentAddress"], merged=True)
                    require_authoritative_range(
                        authoritative_range,
                        (block["blockId"], "parent"),
                        column_rule["parentAddress"],
                        parent["sourceAddress"],
                    )
                    if (
                        parent["sourceAddress"] != column_rule["parentAddress"]
                        or parent["rawValue"] != column_rule["parentRawValue"]
                        or parent["styleIndex"] != column_rule["parentStyleIndex"]
                        or parent["indent"] != column_rule["parentIndent"]
                        or parent["numberFormat"] != column_rule["parentNumberFormat"]
                    ):
                        fail(
                            "FEDERAL_ORACLE_PARENT_ASSERTION",
                            f"{block['blockId']}:{column_rule['parentAddress']}",
                        )
                target = sheet.cell(address)
                status = classify(target)
                if status["markerSource"] == "cell-comment":
                    comment_statuses.add((member["memberId"], address))
                    expected_comments.add((address, str(target["comment"])))
                pieces = {
                    "table": table_canonical,
                    "block": block["blockCanonical"],
                    "row": row_rule["canonical"],
                    "column": column_rule["canonical"],
                    "panel": panel_rule["canonical"],
                }
                canonical: dict[str, object] = {}
                for owner, piece in pieces.items():
                    for field, value in piece.items():
                        if (
                            block["fieldOwners"].get(field) != owner
                            or field in canonical
                        ):
                            fail(
                                "FEDERAL_ORACLE_FIELD_OWNERSHIP",
                                f"{block['blockId']}:{field}",
                            )
                        canonical[field] = value
                note_ids = sorted(
                    set(
                        block["blockNoteBindingIds"]
                        + row_rule["noteBindingIds"]
                        + column_rule["noteBindingIds"]
                        + panel_rule["noteBindingIds"]
                    ),
                    key=utf8_key,
                )
                if block["fieldOwners"].get("footnoteReferenceSet") != "notes":
                    fail("FEDERAL_ORACLE_NOTE_OWNERSHIP", block["blockId"])
                canonical["footnoteReferenceSet"] = note_ids
                if set(canonical) != set(authority["canonicalFields"]):
                    fail("FEDERAL_ORACLE_CANONICAL_COVERAGE", block["blockId"])
                for field, allowed in controlled_values.items():
                    if field in canonical and canonical[field] not in allowed:
                        fail(
                            "FEDERAL_ORACLE_VOCABULARY_VALUE",
                            f"{field}:{canonical[field]}",
                        )
                semantic_key = {
                    field: canonical[field] for field in policy["canonicalKeyFields"]
                }
                key_bytes = stable_bytes(semantic_key)
                if key_bytes in all_keys[member["familyId"]]:
                    fail(
                        "FEDERAL_ORACLE_DUPLICATE_SEMANTIC_KEY",
                        f"{member['familyId']}:{semantic_key}",
                    )
                all_keys[member["familyId"]].add(key_bytes)
                proof = {
                    "rawValue": target["rawValue"],
                    "rawLexeme": target["rawLexeme"],
                    "dataType": target["dataType"],
                    "formula": target["formula"],
                    "formatted": formatted_value(target),
                    "comment": target["comment"],
                    "styleIndex": target["styleIndex"],
                    "numberFormat": target["numberFormat"],
                }
                source_bindings = {
                    "row": {
                        "address": row_rule["address"],
                        "requestedAddress": row_rule["requestedAddress"],
                        "rawValue": row_rule["rawValue"],
                        "styleIndex": row_rule["styleIndex"],
                        "numberFormat": row_rule["numberFormat"],
                        "indent": row_rule["indent"],
                    },
                    "column": {
                        "address": column_rule["address"],
                        "requestedAddress": column_rule["requestedAddress"],
                        "rawValue": column_rule["rawValue"],
                        "styleIndex": column_rule["styleIndex"],
                        "numberFormat": column_rule["numberFormat"],
                        "indent": column_rule["indent"],
                        "parentAddress": column_rule["parentAddress"],
                        "parentRawValue": column_rule["parentRawValue"],
                        "parentStyleIndex": column_rule["parentStyleIndex"],
                        "parentNumberFormat": column_rule["parentNumberFormat"],
                        "parentIndent": column_rule["parentIndent"],
                    },
                    "panel": {
                        "address": panel_rule["address"],
                        "requestedAddress": panel_rule["requestedAddress"],
                        "rawValue": panel_rule["rawValue"],
                        "styleIndex": panel_rule["styleIndex"],
                        "numberFormat": panel_rule["numberFormat"],
                        "indent": panel_rule["indent"],
                    },
                }
                rule_bindings = {
                    "tableRuleId": member["tableRule"]["ruleId"],
                    "blockId": block["blockId"],
                    "rowRuleId": row_rule["ruleId"],
                    "columnRuleId": column_rule["ruleId"],
                    "panelRuleId": panel_rule["ruleId"],
                    "noteBindingIds": note_ids,
                }
                records.append(
                    {
                        "sourceIdentity": {
                            "workbookDigest": member["sourceDigest"],
                            "physicalSheet": member["sheet"],
                            "address": address,
                        },
                        "sourceProof": {
                            **proof,
                            "cellProofDigest": digest_bytes(stable_bytes(proof)),
                        },
                        "valueState": status,
                        "sourceBindings": source_bindings,
                        "ruleBindings": rule_bindings,
                        "canonical": canonical,
                        "semanticKey": semantic_key,
                    }
                )
                member_coordinates.append(address)
                member_totals["targetCount"] += 1
                member_totals["notPublishedCount"] += (
                    status["valueStatus"] == "not-published"
                )
                member_totals["zeroCount"] += target["rawValue"] == 0
                member_totals["formulaCount"] += target["formula"] is not None
        if not all(
            inside_range(item, authoritative_range) for item in addresses_to_check
        ):
            fail("FEDERAL_ORACLE_AUTHORITATIVE_RANGE", member["memberId"])
        raw_comments = {
            (address, str(cell["comment"]))
            for address, cell in sheet.cells.items()
            if cell["comment"] is not None
        }
        if raw_comments != expected_comments:
            comment_difference = {
                "memberId": member["memberId"],
                "missing": sorted(raw_comments - expected_comments),
                "extra": sorted(expected_comments - raw_comments),
            }
            fail("FEDERAL_ORACLE_RAW_COMMENT_SET", comment_difference)
        if member["tailNoteRange"] is None:
            actual_tail: set[tuple[str, str]] = set()
        else:
            actual_tail = {
                (address, str(sheet.cell(address)["rawValue"]))
                for address in expand_range(member["tailNoteRange"])
                if sheet.cell(address)["rawValue"] is not None
                or sheet.cell(address)["formula"] is not None
            }
        if actual_tail != expected_tail_notes | expected_layout:
            expected_tail_and_layout = expected_tail_notes | expected_layout
            tail_difference = {
                "memberId": member["memberId"],
                "missing": sorted(actual_tail - expected_tail_and_layout),
                "extra": sorted(expected_tail_and_layout - actual_tail),
            }
            fail("FEDERAL_ORACLE_TAIL_NOTE_SET", tail_difference)
        if member_totals != member["expected"]:
            fail(
                "FEDERAL_ORACLE_MEMBER_TOTALS",
                f"{member['memberId']}:{member_totals}!={member['expected']}",
            )
        records.sort(
            key=lambda record: parse_address(record["sourceIdentity"]["address"])
        )
        member_coordinates = [record["sourceIdentity"]["address"] for record in records]
        if len(member_coordinates) != len(set(member_coordinates)):
            fail("FEDERAL_ORACLE_MEMBER_COORDINATE_OVERLAP", member["memberId"])
        coordinate_digest = digest_bytes(
            ("\n".join(member_coordinates) + "\n").encode()
        )
        shard = {
            "schemaVersion": (
                "tidy.federal-defendants-source-coordinate-semantic-oracle-member/v1"
            ),
            "oracleId": "federal-defendants-source-coordinate-semantic-oracle-v1",
            "publicationId": authority["publicationId"],
            "memberId": member["memberId"],
            "familyId": member["familyId"],
            "releaseId": member["releaseId"],
            "publicationVintageDate": member["publicationVintageDate"],
            "sourcePath": member["sourcePath"],
            "sourceDigest": member["sourceDigest"],
            "sourceByteLength": member["sourceByteLength"],
            "physicalSheet": member["sheet"],
            "authoritativeRange": authoritative_range,
            "targetCoordinateCount": len(member_coordinates),
            "targetCoordinateDigest": coordinate_digest,
            "counts": member_totals,
            "records": records,
        }
        validate_schema(
            shard,
            schemas[
                "contracts/product-prototype/v1/federal-defendants-source-coordinate-semantic-oracle-member.schema.json"
            ],
            member["memberId"],
        )
        shard_bytes = stable_bytes(shard)
        relative = f"{CANONICAL_SHARD_DIR}/{member['memberId']}.json"
        shard_payloads.append((member["memberId"] + ".json", shard_bytes))
        shard_descriptors.append(
            {
                "memberId": member["memberId"],
                "familyId": member["familyId"],
                "path": relative,
                "digest": digest_bytes(shard_bytes),
                "byteLength": len(shard_bytes),
                "targetCoordinateCount": len(member_coordinates),
                "targetCoordinateDigest": coordinate_digest,
                "counts": member_totals,
            }
        )
        for key in totals:
            totals[key] += member_totals[key]
    expected_totals = {key: authority["expected"][key] for key in totals}
    if totals != expected_totals:
        fail("FEDERAL_ORACLE_AGGREGATE_TOTALS", totals)
    expected_comment_statuses = {
        ("2022-23-federal-offence-group-table-7", address)
        for address in ("F19", "G19", "F24", "G24", "F28", "G28", "F52", "G52")
    }
    if comment_statuses != expected_comment_statuses:
        fail("FEDERAL_ORACLE_COMMENT_STATUS_SET", comment_statuses)
    note_counts = {
        "attachableTailNoteCellCount": len(tail_note_cells),
        "sourceCommentNoteCount": len(raw_comment_notes),
        "sourceLayoutHeadingCount": len(layout_headings),
        "commentStatusCount": len(comment_statuses),
    }
    if any(note_counts[key] != authority["expected"][key] for key in note_counts):
        fail("FEDERAL_ORACLE_NOTE_COUNTS", note_counts)

    schemas_descriptors = [
        local_descriptor(path, MAX_SCHEMA_BYTES)
        for path in sorted(SCHEMA_PATHS, key=utf8_key)
    ]
    toolchain_descriptors = [
        local_descriptor(path, MAX_TOOLCHAIN_BYTES)
        for path in sorted(TOOLCHAIN_PATHS, key=utf8_key)
    ]
    dependency_descriptors = [
        local_descriptor(path, MAX_DEPENDENCY_BYTES)
        for path in sorted(DEPENDENCY_PATHS, key=utf8_key)
    ]
    shard_descriptors.sort(key=lambda item: utf8_key(item["path"]))
    root = {
        "schemaVersion": "tidy.federal-defendants-source-coordinate-semantic-oracle/v1",
        "oracleId": "federal-defendants-source-coordinate-semantic-oracle-v1",
        "publicationId": authority["publicationId"],
        "authority": {
            "path": AUTHORITY,
            "digest": digest_bytes(authority_bytes),
            "byteLength": len(authority_bytes),
        },
        "evidence": authority["evidence"],
        "schemas": schemas_descriptors,
        "toolchain": toolchain_descriptors,
        "dependencies": dependency_descriptors,
        "runtime": runtime,
        "expected": authority["expected"],
        "shards": shard_descriptors,
        "semanticKeyCountsByFamily": {
            key: len(all_keys[key]) for key in sorted(all_keys, key=utf8_key)
        },
    }
    validate_schema(
        root,
        schemas[
            "contracts/product-prototype/v1/federal-defendants-source-coordinate-semantic-oracle.schema.json"
        ],
        ROOT_MANIFEST_NAME,
    )
    root_bytes = stable_bytes(root)

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if output_root.is_symlink() or not output_root.is_dir():
        fail("FEDERAL_ORACLE_OUTPUT_ROOT", output_root)
    stage = Path(tempfile.mkdtemp(prefix=".federal-oracle-stage-", dir=output_root))
    try:
        stage_shards = stage / SHARD_DIR_NAME
        stage_shards.mkdir()
        for name, data in shard_payloads:
            write_atomic(stage_shards / name, data)
        write_atomic(stage / ROOT_MANIFEST_NAME, root_bytes)
        fsync_directory(stage_shards)
        fsync_directory(stage)
        target_shards = output_root / SHARD_DIR_NAME
        target_manifest = output_root / ROOT_MANIFEST_NAME
        backup_shards = output_root / f".{SHARD_DIR_NAME}.backup"
        if backup_shards.exists():
            fail("FEDERAL_ORACLE_OUTPUT_BACKUP_EXISTS", backup_shards)
        replaced_shards = False
        try:
            if target_shards.exists():
                os.replace(target_shards, backup_shards)
                replaced_shards = True
            os.replace(stage_shards, target_shards)
            write_atomic(target_manifest, root_bytes)
            fsync_directory(output_root)
            if replaced_shards:
                for child in backup_shards.iterdir():
                    child.unlink()
                backup_shards.rmdir()
                fsync_directory(output_root)
        except Exception:
            if target_shards.exists() and replaced_shards:
                for child in target_shards.iterdir():
                    child.unlink()
                target_shards.rmdir()
            if replaced_shards and backup_shards.exists():
                os.replace(backup_shards, target_shards)
            fsync_directory(output_root)
            raise
    finally:
        if stage.exists():
            for child in list(stage.rglob("*"))[::-1]:
                child.unlink() if child.is_file() else child.rmdir()
            stage.rmdir()
    if attesting_runtime:
        attest_acceptance_runtime(runtime)
    return {
        "rootDigest": digest_bytes(root_bytes),
        "rootByteLength": len(root_bytes),
        **totals,
        **note_counts,
        "memberCount": len(shard_descriptors),
        "familyCount": len(family_policies),
        "totalShardBytes": sum(item["byteLength"] for item in shard_descriptors),
    }


def main() -> None:
    require_acceptance_cli_flags()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root", type=Path, default=ROOT / "fixtures/product-prototype"
    )
    arguments = parser.parse_args()
    print(
        json.dumps(build(arguments.output_root, attesting_runtime=True), sort_keys=True)
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise

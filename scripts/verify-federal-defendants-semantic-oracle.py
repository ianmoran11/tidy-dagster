#!/usr/bin/env python3
"""Independent verifier for Federal Defendants exact-coordinate semantic shards."""

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
import xml.etree.ElementTree as ElementTree
import zipfile
import zlib
from pathlib import Path, PurePosixPath

PROJECT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = (
    "fixtures/product-prototype/"
    "federal-defendants-source-coordinate-semantic-oracle-v1.json"
)
ROOT_FILE_NAME = "federal-defendants-source-coordinate-semantic-oracle-v1.json"
SHARD_DIRECTORY_NAME = "federal-defendants-source-coordinate-semantic-oracle-v1"
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
MAX_MANIFEST_BYTES = 1_000_000
MAX_AUTHORITY_BYTES = 8_000_000
MAX_EVIDENCE_BYTES = 10_000_000
MAX_SCHEMA_BYTES = 1_000_000
MAX_TOOLCHAIN_BYTES = 10_000_000
MAX_DEPENDENCY_BYTES = 20_000_000
MAX_RUNTIME_FILE_BYTES = 100_000_000
MAX_RUNTIME_TOTAL_BYTES = 250_000_000
MAX_RUNTIME_TREE_FILES = 20_000
MAX_RUNTIME_TREE_SYMLINKS = 1_000
MAX_RUNTIME_TREE_NODES = 25_000
MAX_JSON_NODES = 2_000_000
MAX_FILES = 36
MAX_RECORDS = 18_793
MAX_SHARD_BYTES = 10_000_000
MAX_TOTAL_SHARD_BYTES = 100_000_000
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_ENTRY_BYTES = 50_000_000
MAX_ZIP_TOTAL_BYTES = 200_000_000
MAX_XML_NODES = 2_000_000
MAX_CELLS = 2_000_000
MAX_MERGED_CELLS = 2_000_000
MAX_COMMENTS = 100_000
ADDRESS = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
BUILTIN_FORMATS = {0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00"}
ARTIFACT_ROOT = PROJECT / "fixtures/product-prototype"


def stop(code: str, context: object) -> None:
    raise AssertionError(f"{code}: {context}")


def checksum(blob: bytes) -> str:
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def canonical_blob(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def byte_key(value: str) -> bytes:
    return value.encode("utf-8")


def count_json_nodes(value: object) -> int:
    if isinstance(value, dict):
        return 1 + sum(
            count_json_nodes(key) + count_json_nodes(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return 1 + sum(count_json_nodes(child) for child in value)
    return 1


def decode_json(blob: bytes, label: str, maximum: int) -> object:
    if len(blob) > maximum:
        stop("FD_ORACLE_JSON_BYTE_LIMIT", (label, len(blob), maximum))
    try:
        value = json.loads(blob)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        stop("FD_ORACLE_JSON_INVALID", (label, str(error)))
    nodes = count_json_nodes(value)
    if nodes > MAX_JSON_NODES:
        stop("FD_ORACLE_JSON_NODE_LIMIT", (label, nodes))
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
        count_json_nodes(schema) > MAX_JSON_NODES
        or count_json_nodes(instance) > MAX_JSON_NODES
    ):
        _schema_error("NODE_LIMIT", label)
    _check_schema_keywords(schema, schema, 0, [0])
    _validate_schema_subset(instance, schema, schema, "$", 0, [0])


def check_schema(instance: object, schema: object, label: str) -> None:
    try:
        validate_schema_subset(instance, schema, label)
    except SchemaSubsetError as error:
        stop("FD_ORACLE_SCHEMA_INVALID", (label, str(error)))


def lexical_relative(relative: str) -> PurePosixPath:
    if len(relative.encode("utf-8")) > MAX_PATH_BYTES:
        stop("FD_ORACLE_PATH_LENGTH", relative)
    lexical = PurePosixPath(relative)
    if (
        lexical.is_absolute()
        or not lexical.parts
        or len(lexical.parts) > MAX_PATH_COMPONENTS
        or any(component in ("", ".", "..") for component in lexical.parts)
    ):
        stop("FD_ORACLE_PATH_LEXICAL", relative)
    return lexical


def _descriptor_read(
    base: Path,
    parts: tuple[str, ...],
    maximum: int,
    identity: str,
    runtime: bool = False,
) -> tuple[Path, bytes]:
    """Read through a held openat chain; no checked parent is reopened by path."""
    if not parts or any(part in ("", ".", "..") for part in parts):
        stop("FD_ORACLE_PATH_LEXICAL", identity)
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
        stop("FD_ORACLE_PATH_LEXICAL", identity)
    descriptors: list[int] = []
    file_descriptor: int | None = None
    try:
        root_descriptor = os.open(Path("/"), directory_flags)
        descriptors.append(root_descriptor)
        current = root_descriptor
        for component in chain[:-1]:
            before = os.stat(component, dir_fd=current, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                stop("FD_ORACLE_PATH_SYMLINK", identity)
            if not stat.S_ISDIR(before.st_mode):
                stop("FD_ORACLE_PATH_PARENT_TYPE", identity)
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
                stop("FD_ORACLE_PATH_INODE", identity)
            descriptors.append(child)
            current = child
        filename = chain[-1]
        before_file = os.stat(filename, dir_fd=current, follow_symlinks=False)
        if stat.S_ISLNK(before_file.st_mode):
            stop("FD_ORACLE_PATH_SYMLINK", identity)
        if not stat.S_ISREG(before_file.st_mode):
            stop("FD_ORACLE_PATH_FILE_TYPE", identity)
        file_descriptor = os.open(filename, file_flags, dir_fd=current)
        opened_before = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened_before.st_mode) or (
            opened_before.st_dev,
            opened_before.st_ino,
        ) != (before_file.st_dev, before_file.st_ino):
            stop("FD_ORACLE_PATH_INODE", identity)
        byte_limit_code = (
            "FD_ORACLE_RUNTIME_BYTE_LIMIT" if runtime else "FD_ORACLE_INPUT_BYTE_LIMIT"
        )
        if opened_before.st_size > maximum:
            stop(byte_limit_code, (identity, opened_before.st_size, maximum))
        payload = bytearray()
        while True:
            chunk = os.read(file_descriptor, min(1_048_576, maximum + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > maximum:
                stop(byte_limit_code, (identity, len(payload), maximum))
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
            stop("FD_ORACLE_PATH_INODE", identity)
        return base_absolute.joinpath(*parts), bytes(payload)
    except OSError as error:
        stop("FD_ORACLE_PATH_DESCRIPTOR", (identity, error.errno))
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def read_under(base: Path, relative: str, maximum: int) -> tuple[Path, bytes]:
    lexical = lexical_relative(relative)
    return _descriptor_read(base, lexical.parts, maximum, relative)


def vetted_read(relative: str, maximum: int = MAX_EVIDENCE_BYTES) -> tuple[Path, bytes]:
    return read_under(PROJECT, relative, maximum)


def artifact_read(relative: str, maximum: int) -> tuple[Path, bytes]:
    shard_prefix = (
        "fixtures/product-prototype/"
        "federal-defendants-source-coordinate-semantic-oracle-v1/"
    )
    if relative == MANIFEST_NAME:
        return read_under(ARTIFACT_ROOT, ROOT_FILE_NAME, maximum)
    if relative.startswith(shard_prefix):
        name = relative[len(shard_prefix) :]
        if "/" in name:
            stop("FD_ORACLE_ARTIFACT_PATH", relative)
        return read_under(ARTIFACT_ROOT, f"{SHARD_DIRECTORY_NAME}/{name}", maximum)
    return vetted_read(relative, maximum)


def read_absolute(path: Path, maximum: int) -> tuple[Path, bytes]:
    if not path.is_absolute() or len(str(path).encode("utf-8")) > 2048:
        stop("FD_ORACLE_RUNTIME_PATH", path)
    pure = PurePosixPath(str(path))
    if len(pure.parts) - 1 > MAX_PATH_COMPONENTS * 2:
        stop("FD_ORACLE_RUNTIME_PATH", path)
    return _descriptor_read(Path("/"), pure.parts[1:], maximum, str(path), runtime=True)


def a1(cell_address: str) -> tuple[int, int]:
    match = ADDRESS.fullmatch(cell_address)
    if match is None:
        stop("FD_ORACLE_ADDRESS", cell_address)
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - 64
    return int(match.group(2)), column


def address(row: int, column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters + str(row)


def rectangle(specification: str) -> list[str]:
    left, right = specification.split(":")
    first_row, first_column = a1(left)
    last_row, last_column = a1(right)
    if first_row > last_row or first_column > last_column:
        stop("FD_ORACLE_RANGE", specification)
    count = (last_row - first_row + 1) * (last_column - first_column + 1)
    if count > MAX_RECORDS:
        stop("FD_ORACLE_RANGE_BUDGET", specification)
    return [
        address(row, column)
        for row in range(first_row, last_row + 1)
        for column in range(first_column, last_column + 1)
    ]


def inside(cell_address: str, specification: str) -> bool:
    row, column = a1(cell_address)
    left, right = specification.split(":")
    first_row, first_column = a1(left)
    last_row, last_column = a1(right)
    return first_row <= row <= last_row and first_column <= column <= last_column


def require_authoritative_range(
    specification: str, identity: object, *addresses: str
) -> None:
    if not all(inside(item, specification) for item in addresses):
        stop("FD_ORACLE_AUTHORITATIVE_RANGE", (identity, addresses))


def domain_checksum(domain: str, value: object) -> str:
    return checksum(
        domain.encode("utf-8") + b"\0" + canonical_blob(value).rstrip(b"\n")
    )


def texts(element: ElementTree.Element | None) -> str:
    if element is None:
        return ""
    return "".join(node.text or "" for node in element.iter(f"{{{MAIN}}}t"))


def xml_member(archive: zipfile.ZipFile, member: str) -> ElementTree.Element:
    information = archive.getinfo(member)
    if information.file_size > MAX_ZIP_ENTRY_BYTES:
        stop("FD_ORACLE_OOXML_MEMBER_SIZE", member)
    try:
        root = ElementTree.fromstring(archive.read(member))
    except ElementTree.ParseError as error:
        stop("FD_ORACLE_OOXML_XML", (member, str(error)))
    nodes = sum(1 for _ in root.iter())
    if nodes > MAX_XML_NODES:
        stop("FD_ORACLE_OOXML_XML_NODE_LIMIT", (member, nodes))
    return root


class IndependentSheet:
    """Independent OOXML reader; it accepts only the previously vetted byte buffer."""

    def __init__(
        self, workbook_blob: bytes, sheet_name: str, bounded_range: str, identity: str
    ) -> None:
        with zipfile.ZipFile(io.BytesIO(workbook_blob)) as archive:
            infos = archive.infolist()
            names_list = [item.filename for item in infos]
            if (
                len(infos) > MAX_ZIP_ENTRIES
                or sum(item.file_size for item in infos) > MAX_ZIP_TOTAL_BYTES
            ):
                stop("FD_ORACLE_OOXML_ARCHIVE_BUDGET", identity)
            if len(names_list) != len(set(names_list)):
                stop("FD_ORACLE_OOXML_DUPLICATE_MEMBER", identity)
            for item in infos:
                if (
                    item.file_size > MAX_ZIP_ENTRY_BYTES
                    or item.filename.startswith("/")
                    or ".." in PurePosixPath(item.filename).parts
                ):
                    stop("FD_ORACLE_OOXML_MEMBER_PATH", item.filename)
            names = set(names_list)
            shared_values: list[str] = []
            if "xl/sharedStrings.xml" in names:
                shared_values = [
                    texts(item)
                    for item in xml_member(archive, "xl/sharedStrings.xml").findall(
                        f"{{{MAIN}}}si"
                    )
                ]
            number_formats = ["General"]
            indents = [0]
            if "xl/styles.xml" in names:
                styles = xml_member(archive, "xl/styles.xml")
                custom = {
                    int(node.attrib["numFmtId"]): node.attrib["formatCode"]
                    for node in styles.findall(f"{{{MAIN}}}numFmts/{{{MAIN}}}numFmt")
                }
                xfs = styles.findall(f"{{{MAIN}}}cellXfs/{{{MAIN}}}xf")
                number_formats = [
                    custom.get(
                        int(node.attrib.get("numFmtId", "0")),
                        BUILTIN_FORMATS.get(
                            int(node.attrib.get("numFmtId", "0")), "General"
                        ),
                    )
                    for node in xfs
                ]
                indents = []
                for node in xfs:
                    alignment = node.find(f"{{{MAIN}}}alignment")
                    indents.append(
                        0
                        if alignment is None
                        else int(alignment.attrib.get("indent", "0"))
                    )
            book = xml_member(archive, "xl/workbook.xml")
            relationships = xml_member(archive, "xl/_rels/workbook.xml.rels")
            relation_targets = {
                node.attrib["Id"]: node.attrib["Target"]
                for node in relationships.findall(f"{{{PACKAGE_REL}}}Relationship")
            }
            selected = next(
                (
                    node
                    for node in book.findall(f"{{{MAIN}}}sheets/{{{MAIN}}}sheet")
                    if node.attrib["name"] == sheet_name
                ),
                None,
            )
            if selected is None:
                stop("FD_ORACLE_OOXML_SHEET", sheet_name)
            target = relation_targets[selected.attrib[f"{{{OFFICE_REL}}}id"]]
            worksheet_member = (
                target[1:]
                if target.startswith("/")
                else posixpath.normpath(posixpath.join("xl", target))
            )
            worksheet = xml_member(archive, worksheet_member)
            self.number_formats = number_formats
            self.indents = indents
            self.cells: dict[str, dict[str, object]] = {}
            self.merges: dict[str, str] = {}
            for node in worksheet.iter(f"{{{MAIN}}}c"):
                if len(self.cells) >= MAX_CELLS:
                    stop("FD_ORACLE_OOXML_CELL_LIMIT", identity)
                coordinate = node.attrib["r"]
                value_node = node.find(f"{{{MAIN}}}v")
                formula_node = node.find(f"{{{MAIN}}}f")
                kind = node.attrib.get("t")
                if kind == "s" and value_node is not None:
                    raw: object = shared_values[int(value_node.text or "0")]
                elif kind == "inlineStr":
                    raw = texts(node.find(f"{{{MAIN}}}is"))
                elif kind in ("str", "e") and value_node is not None:
                    raw = value_node.text or ""
                elif kind == "b" and value_node is not None:
                    raw = value_node.text == "1"
                elif value_node is None:
                    raw = None
                else:
                    numeric = float(value_node.text or "")
                    raw = int(numeric) if numeric.is_integer() else numeric
                style_index = int(node.attrib.get("s", "0"))
                if style_index >= len(number_formats):
                    stop("FD_ORACLE_OOXML_STYLE", (identity, coordinate, style_index))
                data_type = (
                    "blank"
                    if raw is None
                    else "boolean"
                    if isinstance(raw, bool)
                    else "number"
                    if isinstance(raw, int | float)
                    else "string"
                )
                raw_lexeme = None if value_node is None else value_node.text
                semantic_scalar = (
                    None
                    if raw is None
                    else raw_lexeme
                    if data_type in ("number", "boolean")
                    else str(raw)
                )
                self.cells[coordinate] = {
                    "address": coordinate,
                    "rawValue": raw,
                    "rawLexeme": raw_lexeme,
                    "rawSemanticScalar": semantic_scalar,
                    "dataType": data_type,
                    "formula": None if formula_node is None else formula_node.text,
                    "styleIndex": style_index,
                    "numberFormat": number_formats[style_index],
                    "indent": indents[style_index],
                    "comment": None,
                }
            bound_left, bound_right = bounded_range.split(":")
            bound_first_row, bound_first_column = a1(bound_left)
            bound_last_row, bound_last_column = a1(bound_right)
            merged_count = 0
            for merge in worksheet.findall(f"{{{MAIN}}}mergeCells/{{{MAIN}}}mergeCell"):
                merge_left, merge_right = merge.attrib["ref"].split(":")
                first_row, first_column = a1(merge_left)
                last_row, last_column = a1(merge_right)
                row_start, row_end = (
                    max(first_row, bound_first_row),
                    min(last_row, bound_last_row),
                )
                column_start, column_end = (
                    max(first_column, bound_first_column),
                    min(last_column, bound_last_column),
                )
                if row_start > row_end or column_start > column_end:
                    continue
                merged_count += (row_end - row_start + 1) * (
                    column_end - column_start + 1
                )
                if merged_count > MAX_MERGED_CELLS:
                    stop("FD_ORACLE_OOXML_MERGE_LIMIT", identity)
                for row in range(row_start, row_end + 1):
                    for column in range(column_start, column_end + 1):
                        self.merges[address(row, column)] = merge_left
            relation_member = posixpath.join(
                posixpath.dirname(worksheet_member),
                "_rels",
                posixpath.basename(worksheet_member) + ".rels",
            )
            comment_count = 0
            if relation_member in names:
                for relation in xml_member(archive, relation_member).findall(
                    f"{{{PACKAGE_REL}}}Relationship"
                ):
                    if relation.attrib.get("Type", "").endswith("/comments"):
                        comment_target = relation.attrib["Target"]
                        comment_member = (
                            comment_target[1:]
                            if comment_target.startswith("/")
                            else posixpath.normpath(
                                posixpath.join(
                                    posixpath.dirname(worksheet_member), comment_target
                                )
                            )
                        )
                        for comment in xml_member(archive, comment_member).findall(
                            f"{{{MAIN}}}commentList/{{{MAIN}}}comment"
                        ):
                            comment_count += 1
                            if comment_count > MAX_COMMENTS:
                                stop("FD_ORACLE_OOXML_COMMENT_LIMIT", identity)
                            coordinate = comment.attrib["ref"]
                            self.cells.setdefault(coordinate, self.blank(coordinate))[
                                "comment"
                            ] = texts(comment)

    def blank(self, coordinate: str) -> dict[str, object]:
        return {
            "address": coordinate,
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

    def cell(self, requested: str, merged: bool = False) -> dict[str, object]:
        source = self.merges.get(requested, requested) if merged else requested
        result = dict(self.cells.get(source, self.blank(source)))
        result["sourceAddress"] = source
        result["requestedAddress"] = requested
        return result


def render(cell: dict[str, object]) -> object:
    if cell["dataType"] != "number":
        return cell["rawValue"]
    value = float(cell["rawValue"])
    formats = {
        "#,##0": f"{value:,.0f}",
        "#,##0.0": f"{value:,.1f}",
        "0.0": f"{value:.1f}",
        "0.00": f"{value:.2f}",
        "0": f"{value:.0f}",
        "General": cell["rawLexeme"],
    }
    if cell["numberFormat"] not in formats:
        stop("FD_ORACLE_NUMBER_FORMAT", cell["numberFormat"])
    return formats[cell["numberFormat"]]


def source_proof(cell: dict[str, object]) -> dict[str, object]:
    return {
        "sourceAddress": cell["sourceAddress"],
        "rawValue": cell["rawValue"],
        "dataType": cell["dataType"],
        "comment": cell["comment"],
        "styleIndex": cell["styleIndex"],
        "numberFormat": cell["numberFormat"],
        "indent": cell["indent"],
    }


def independent_state(cell: dict[str, object]) -> dict[str, object]:
    if cell["rawValue"] is None:
        if cell["comment"] != "not published\n":
            stop("FD_ORACLE_UNEXPLAINED_BLANK", cell["address"])
        return {
            "valueStatus": "not-published",
            "markerSource": "cell-comment",
            "sourceComment": "not published\n",
            "valueStatusAuthority": {
                "kind": "exact-comment",
                "rawComment": "not published\n",
                "status": "not-published",
            },
        }
    if cell["rawValue"] == "np":
        return {
            "valueStatus": "not-published",
            "markerSource": "cell-value",
            "sourceComment": cell["comment"],
            "valueStatusAuthority": None,
        }
    if not isinstance(cell["rawValue"], int | float) or isinstance(
        cell["rawValue"], bool
    ):
        stop("FD_ORACLE_VALUE_TYPE", (cell["address"], cell["rawValue"]))
    return {
        "valueStatus": "observed",
        "markerSource": None,
        "sourceComment": cell["comment"],
        "valueStatusAuthority": None,
    }


def _path_is_under(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _open_absolute_directory(path: Path) -> int:
    absolute = Path(os.path.abspath(path))
    pure = PurePosixPath(str(absolute))
    if not pure.is_absolute() or len(pure.parts) - 1 > MAX_PATH_COMPONENTS * 2:
        stop("FD_ORACLE_RUNTIME_TREE_PATH", path)
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
                stop("FD_ORACLE_RUNTIME_TREE_COMPONENT", path)
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
                stop("FD_ORACLE_RUNTIME_TREE_INODE", path)
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
        stop("FD_ORACLE_RUNTIME_TREE_FILE_TYPE", identity)
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        opened_before = os.fstat(descriptor)
        if (opened_before.st_dev, opened_before.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            stop("FD_ORACLE_RUNTIME_TREE_INODE", identity)
        if opened_before.st_size > MAX_RUNTIME_FILE_BYTES:
            stop("FD_ORACLE_RUNTIME_BYTE_LIMIT", identity)
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
                stop("FD_ORACLE_RUNTIME_BYTE_LIMIT", identity)
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
            stop("FD_ORACLE_RUNTIME_TREE_INODE", identity)
        return bytes(payload)
    finally:
        os.close(descriptor)


def inventory_runtime_tree(
    root: Path, roles: list[str]
) -> tuple[dict[str, object], set[str]]:
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
        names = sorted(os.listdir(directory_fd), key=byte_key)
        for name in names:
            if name in RUNTIME_TREE_EXCLUDED_DIRECTORIES:
                continue
            if name in {"", ".", ".."} or "/" in name or "\x00" in name:
                stop("FD_ORACLE_RUNTIME_TREE_ENTRY", name)
            relative_parts = (*prefix, name)
            relative = "/".join(relative_parts)
            if len(relative.encode("utf-8")) > 2_048:
                stop("FD_ORACLE_RUNTIME_TREE_PATH", relative)
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            node_count += 1
            if node_count > MAX_RUNTIME_TREE_NODES:
                stop("FD_ORACLE_RUNTIME_TREE_NODE_LIMIT", node_count)
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
                        stop("FD_ORACLE_RUNTIME_TREE_INODE", relative)
                    walk(child, relative_parts)
                    after_walk = os.stat(
                        name, dir_fd=directory_fd, follow_symlinks=False
                    )
                    if (after_walk.st_dev, after_walk.st_ino) != (
                        opened.st_dev,
                        opened.st_ino,
                    ):
                        stop("FD_ORACLE_RUNTIME_TREE_INODE", relative)
                finally:
                    os.close(child)
            elif stat.S_ISREG(before.st_mode):
                blob = _read_runtime_tree_file(directory_fd, name, relative)
                regular_count += 1
                regular_bytes += len(blob)
                if regular_count > MAX_RUNTIME_TREE_FILES:
                    stop("FD_ORACLE_RUNTIME_TREE_FILE_LIMIT", regular_count)
                if regular_bytes > MAX_RUNTIME_TOTAL_BYTES:
                    stop("FD_ORACLE_RUNTIME_TOTAL_BYTE_LIMIT", regular_bytes)
                entries.append(
                    {
                        "kind": "regular-file",
                        "path": relative,
                        "digest": checksum(blob),
                        "byteLength": len(blob),
                    }
                )
                covered.add(str(root_path.joinpath(*relative_parts)))
            elif stat.S_ISLNK(before.st_mode):
                target = os.readlink(name, dir_fd=directory_fd)
                after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
                    stop("FD_ORACLE_RUNTIME_TREE_INODE", relative)
                if len(target.encode("utf-8")) > 2_048:
                    stop("FD_ORACLE_RUNTIME_TREE_SYMLINK", relative)
                symlink_count += 1
                if symlink_count > MAX_RUNTIME_TREE_SYMLINKS:
                    stop("FD_ORACLE_RUNTIME_TREE_SYMLINK_LIMIT", symlink_count)
                entries.append(
                    {
                        "kind": "symlink",
                        "path": relative,
                        "target": target,
                        "mode": stat.S_IMODE(before.st_mode),
                    }
                )
            else:
                stop("FD_ORACLE_RUNTIME_TREE_NODE_TYPE", relative)

    try:
        walk(root_fd, ())
    finally:
        os.close(root_fd)
    entries.sort(key=lambda item: byte_key(str(item["path"])))
    descriptor = {
        "roles": sorted(roles, key=byte_key),
        "path": str(root_path),
        "regularFileCount": regular_count,
        "regularFileByteLength": regular_bytes,
        "symlinkCount": symlink_count,
        "contentDigest": checksum(canonical_blob(entries)),
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
        (Path(path), sorted(roles, key=byte_key))
        for path, roles in sorted(
            roles_by_path.items(), key=lambda item: byte_key(item[0])
        )
    ]


def _allowed_import_paths(tree_roots: list[tuple[Path, list[str]]]) -> list[str]:
    allowed = {str(PROJECT), str(PROJECT / "scripts")}
    for root, _ in tree_roots:
        allowed.add(str(root))
        allowed.add(str(root / "lib-dynload"))
        allowed.add(
            str(
                root.parent
                / f"python{sys.version_info.major}{sys.version_info.minor}.zip"
            )
        )
    return sorted(allowed, key=byte_key)


def bootstrap_runtime_snapshot() -> tuple[dict[str, object], set[str]]:
    total = 0
    files: dict[str, Path] = {"cpython-executable": Path(sys._base_executable)}
    framework = Path(sys._base_executable).resolve(strict=True).parents[1] / "Python"
    if framework.is_file():
        files["python-shared-library"] = framework
    descriptors: list[dict[str, object]] = []
    for identity, runtime_path in sorted(
        files.items(), key=lambda item: byte_key(item[0])
    ):
        resolved, blob = read_absolute(runtime_path, MAX_RUNTIME_FILE_BYTES)
        total += len(blob)
        if total > MAX_RUNTIME_TOTAL_BYTES:
            stop("FD_ORACLE_RUNTIME_TOTAL_BYTE_LIMIT", total)
        descriptors.append(
            {
                "identity": identity,
                "path": str(resolved),
                "digest": checksum(blob),
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
            stop("FD_ORACLE_RUNTIME_TOTAL_BYTE_LIMIT", total + tree_bytes)
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
        stop("FD_ORACLE_RUNTIME_FLAGS", "require CPython -I -S -B")


def audit_acceptance_import_path(runtime: dict[str, object]) -> None:
    allowed = {os.path.abspath(str(path)) for path in runtime["allowedImportPaths"]}
    forbidden_roots = {
        os.path.abspath(sysconfig.get_paths()[key]) for key in ("purelib", "platlib")
    }
    observed: list[str] = []
    for value in sys.path:
        if not isinstance(value, str) or value == "":
            stop("FD_ORACLE_RUNTIME_SYS_PATH", value)
        absolute = os.path.abspath(value)
        components = PurePosixPath(absolute).parts
        if any(part in RUNTIME_TREE_EXCLUDED_DIRECTORIES for part in components):
            stop("FD_ORACLE_RUNTIME_SYS_PATH", absolute)
        if any(_path_is_under(absolute, root) for root in forbidden_roots):
            stop("FD_ORACLE_RUNTIME_SYS_PATH", absolute)
        if absolute not in allowed:
            stop("FD_ORACLE_RUNTIME_SYS_PATH", absolute)
        observed.append(absolute)
    if len(observed) != len(set(observed)):
        stop("FD_ORACLE_RUNTIME_SYS_PATH", "duplicate")


def audit_all_loaded_modules(runtime: dict[str, object], covered: set[str]) -> None:
    toolchain = {
        str(PROJECT / path) for path in TOOLCHAIN_PATHS if path.endswith(".py")
    }
    forbidden_roots = {
        os.path.abspath(sysconfig.get_paths()[key]) for key in ("purelib", "platlib")
    }
    uncovered: list[str] = []
    for name in sorted(sys.modules, key=byte_key):
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
        stop("FD_ORACLE_RUNTIME_MODULE_UNCOVERED", uncovered)


def attest_acceptance_runtime(runtime: dict[str, object]) -> None:
    audit_acceptance_import_path(runtime)
    observed, covered = bootstrap_runtime_snapshot()
    if observed != runtime:
        stop("FD_ORACLE_RUNTIME_TREE_PIN", observed)
    audit_all_loaded_modules(runtime, covered)


def semantic_payload(cell: dict[str, object]) -> dict[str, str]:
    payload = {"address": str(cell["address"])}
    if cell["formula"] is not None:
        payload["formula"] = str(cell["formula"])
    if cell["rawSemanticScalar"] not in (None, ""):
        payload["value"] = str(cell["rawSemanticScalar"])
    return payload


def validate_exclusions(
    ledger: dict[str, object],
    inventory: dict[str, object],
    workbook_cache: dict[str, bytes],
) -> None:
    if len(ledger["sheets"]) != ledger["boundedSheetCount"]:
        stop("FD_ORACLE_EXCLUSION_LEDGER_SHAPE", "sheets")
    total = 0
    for entry in ledger["sheets"]:
        source_path = entry["sourcePath"]
        if source_path not in workbook_cache:
            stop("FD_ORACLE_EXCLUSION_SOURCE", source_path)
        sheet = IndependentSheet(
            workbook_cache[source_path],
            entry["physicalSheetName"],
            entry["authoritativeRange"],
            source_path,
        )
        if sheet.cell(entry["authorityCell"])["rawValue"] != entry["authorityText"]:
            stop("FD_ORACLE_EXCLUSION_AUTHORITY", source_path)
        bounded: list[dict[str, str]] = []
        excluded: list[dict[str, str]] = []
        for cell in sheet.cells.values():
            if cell["formula"] is None and cell["rawSemanticScalar"] in (None, ""):
                continue
            payload = semantic_payload(cell)
            (
                bounded
                if inside(cell["address"], entry["authoritativeRange"])
                else excluded
            ).append(payload)
        bounded.sort(key=lambda item: byte_key(item["address"]))
        excluded.sort(key=lambda item: byte_key(item["address"]))
        if (
            len(bounded) != entry["boundedSemanticCellCount"]
            or domain_checksum("tidy.xlsx-bounded-semantic-cells/v1", bounded)
            != entry["boundedSemanticCellDigest"]
        ):
            stop("FD_ORACLE_BOUNDED_SEMANTIC_CLOSURE", source_path)
        if (
            excluded != entry["excludedNonblankCells"]
            or len(excluded) != entry["excludedNonblankCellCount"]
            or domain_checksum(
                "tidy.xlsx-out-of-authoritative-range-nonblank-cells/v1", excluded
            )
            != entry["exclusionDigest"]
        ):
            stop("FD_ORACLE_EXCLUSION_CELL_CLOSURE", source_path)
        total += len(excluded)
    if total != ledger["excludedNonblankCellCount"] or total != 1_041:
        stop("FD_ORACLE_EXCLUSION_TOTAL", total)
    ledger_body = dict(ledger)
    declared_ledger_digest = ledger_body.pop("ledgerDigest", None)
    recomputed_ledger_digest = domain_checksum(
        str(ledger["schemaVersion"]), ledger_body
    )
    if declared_ledger_digest != recomputed_ledger_digest:
        stop("FD_ORACLE_EXCLUSION_LEDGER_DIGEST", declared_ledger_digest)
    if (
        inventory.get("boundedRangeExclusionLedgerDigest") != recomputed_ledger_digest
        or inventory.get("boundedRangeExcludedNonblankCellCount") != total
        or inventory.get("boundedRangeSheetCount") != len(ledger["sheets"])
    ):
        stop("FD_ORACLE_EXCLUSION_INVENTORY_RELATION", recomputed_ledger_digest)


def expected_descriptor(path: str, maximum: int) -> dict[str, object]:
    _, blob = vetted_read(path, maximum)
    return {"path": path, "digest": checksum(blob), "byteLength": len(blob)}


def verify(
    expected_root_digest: str,
    artifact_root: Path | None = None,
    *,
    attesting_runtime: bool = False,
) -> dict[str, object]:
    global ARTIFACT_ROOT
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_root_digest):
        stop("FD_ORACLE_EXPECTED_ROOT_FORMAT", expected_root_digest)
    if artifact_root is not None:
        ARTIFACT_ROOT = artifact_root
    _, manifest_blob = artifact_read(MANIFEST_NAME, MAX_MANIFEST_BYTES)
    if checksum(manifest_blob) != expected_root_digest:
        stop(
            "FD_ORACLE_EXTERNAL_ROOT_MISMATCH",
            (expected_root_digest, checksum(manifest_blob)),
        )
    manifest = decode_json(manifest_blob, MANIFEST_NAME, MAX_MANIFEST_BYTES)
    # Authenticate complete stdlib trees against the literal-pinned root.
    runtime, _ = bootstrap_runtime_snapshot()
    if not isinstance(manifest, dict) or manifest.get("runtime") != runtime:
        stop(
            "FD_ORACLE_RUNTIME_PIN",
            manifest.get("runtime")
            if isinstance(manifest, dict)
            else type(manifest).__name__,
        )
    schemas: dict[str, object] = {}
    for path in SCHEMA_PATHS:
        _, blob = vetted_read(path, MAX_SCHEMA_BYTES)
        schemas[path] = decode_json(blob, path, MAX_SCHEMA_BYTES)
    check_schema(
        manifest,
        schemas[
            "contracts/product-prototype/v1/federal-defendants-source-coordinate-semantic-oracle.schema.json"
        ],
        MANIFEST_NAME,
    )
    expected_schema_descriptors = [
        expected_descriptor(path, MAX_SCHEMA_BYTES)
        for path in sorted(SCHEMA_PATHS, key=byte_key)
    ]
    expected_toolchain = [
        expected_descriptor(path, MAX_TOOLCHAIN_BYTES)
        for path in sorted(TOOLCHAIN_PATHS, key=byte_key)
    ]
    expected_dependencies = [
        expected_descriptor(path, MAX_DEPENDENCY_BYTES)
        for path in sorted(DEPENDENCY_PATHS, key=byte_key)
    ]
    if manifest["schemas"] != expected_schema_descriptors:
        stop("FD_ORACLE_SCHEMA_PINS", manifest["schemas"])
    if manifest["toolchain"] != expected_toolchain:
        stop("FD_ORACLE_TOOLCHAIN_PINS", manifest["toolchain"])
    if manifest["dependencies"] != expected_dependencies:
        stop("FD_ORACLE_DEPENDENCY_PINS", manifest["dependencies"])

    _, authority_blob = vetted_read(manifest["authority"]["path"], MAX_AUTHORITY_BYTES)
    if manifest["authority"] != {
        "path": manifest["authority"]["path"],
        "digest": checksum(authority_blob),
        "byteLength": len(authority_blob),
    }:
        stop("FD_ORACLE_AUTHORITY_PIN", manifest["authority"])
    authority = decode_json(
        authority_blob, manifest["authority"]["path"], MAX_AUTHORITY_BYTES
    )
    check_schema(
        authority,
        schemas[
            "contracts/product-prototype/v1/federal-defendants-semantic-plan.schema.json"
        ],
        "authority",
    )
    if (
        set(authority["evidence"]) != REQUIRED_EVIDENCE
        or manifest["evidence"] != authority["evidence"]
    ):
        stop("FD_ORACLE_EVIDENCE_RELATION", manifest["evidence"])
    evidence: dict[str, object] = {}
    for name in sorted(REQUIRED_EVIDENCE, key=byte_key):
        descriptor = manifest["evidence"][name]
        _, blob = vetted_read(descriptor["path"], MAX_EVIDENCE_BYTES)
        if descriptor != {
            "path": descriptor["path"],
            "digest": checksum(blob),
            "byteLength": len(blob),
        }:
            stop("FD_ORACLE_EVIDENCE_PIN", descriptor["path"])
        evidence[name] = decode_json(blob, descriptor["path"], MAX_EVIDENCE_BYTES)
    check_schema(
        evidence["controlledVocabulary"],
        schemas[
            "contracts/product-prototype/v1/federal-defendants-controlled-vocabulary.schema.json"
        ],
        "controlledVocabulary",
    )
    check_schema(
        evidence["methodologyEvidence"],
        schemas[
            "contracts/product-prototype/v1/federal-defendants-methodology-evidence.schema.json"
        ],
        "methodologyEvidence",
    )
    methodology = evidence["methodologyEvidence"]
    methodology_documents: dict[str, str] = {}
    for descriptor in methodology["documents"]:
        _, blob = vetted_read(descriptor["path"], MAX_EVIDENCE_BYTES)
        if descriptor != {
            **descriptor,
            "digest": checksum(blob),
            "byteLength": len(blob),
        }:
            stop("FD_ORACLE_METHODOLOGY_DOCUMENT_PIN", descriptor["path"])
        methodology_documents[descriptor["path"]] = blob.decode("utf-8")
    for claim in methodology["claims"]:
        if (
            claim["exactExcerpt"]
            not in methodology_documents[claim["evidenceDocument"]]
        ):
            stop("FD_ORACLE_METHODOLOGY_EXCERPT", claim["claimId"])
    vocabulary = evidence["controlledVocabulary"]
    controlled = {
        item["field"]: {entry["id"] for entry in item["values"]}
        for item in vocabulary["fields"]
    }

    members = authority["members"]
    policies = authority["familyPolicies"]
    if members != sorted(
        members, key=lambda item: byte_key(item["memberId"])
    ) or policies != sorted(policies, key=lambda item: byte_key(item["familyId"])):
        stop("FD_ORACLE_AUTHORITY_ORDER", "members/families")
    if (
        sum(len(member["blocks"]) for member in members)
        != authority["expected"]["blockCount"]
        or authority["expected"]["blockCount"] != 148
    ):
        stop("FD_ORACLE_BLOCK_COUNT", "not 148")
    member_authority = {item["memberId"]: item for item in members}
    family_policy = {item["familyId"]: item for item in policies}
    actual_members_by_family: dict[str, list[str]] = {}
    for member in members:
        actual_members_by_family.setdefault(member["familyId"], []).append(
            member["memberId"]
        )
    if set(actual_members_by_family) != set(family_policy) or len(family_policy) != 23:
        stop(
            "FD_ORACLE_FAMILY_POLICY_SET",
            set(actual_members_by_family) ^ set(family_policy),
        )
    for family_id, ids in actual_members_by_family.items():
        if family_policy[family_id]["memberIds"] != sorted(ids, key=byte_key):
            stop("FD_ORACLE_FAMILY_POLICY_MEMBERS", family_id)
    for document_name in ("familyMembership", "familyCrosswalk"):
        families = evidence[document_name]["families"]
        if {item["familyId"] for item in families} != set(family_policy):
            stop("FD_ORACLE_FAMILY_CUSTODY_SET", document_name)
        custody = {item["familyId"]: item for item in families}
        for family_id, ids in actual_members_by_family.items():
            expected = sorted(
                (
                    member_authority[item]["releaseId"],
                    member_authority[item]["sheet"],
                    member_authority[item]["publishedTitle"],
                )
                for item in ids
            )
            observed = sorted(
                (item["releaseId"], item["physicalSheetName"], item["publishedTitle"])
                for item in custody[family_id]["members"]
            )
            if expected != observed:
                stop("FD_ORACLE_FAMILY_CUSTODY_MEMBERS", (document_name, family_id))

    downloads = {
        item["path"]: item for item in evidence["releaseDownloads"]["downloads"]
    }
    inventory = {
        item["path"]: item for item in evidence["sourceInventory"]["downloads"]
    }
    workbook_cache: dict[str, bytes] = {}
    for member in members:
        for catalog, label in ((downloads, "downloads"), (inventory, "inventory")):
            declaration = catalog.get(member["sourcePath"])
            if (
                declaration is None
                or declaration["contentDigest"] != member["sourceDigest"]
                or declaration["byteLength"] != member["sourceByteLength"]
            ):
                stop("FD_ORACLE_SOURCE_CUSTODY", (label, member["sourcePath"]))
        if member["sourcePath"] not in workbook_cache:
            _, blob = vetted_read(
                "fixtures/product-prototype/" + member["sourcePath"], 25_000_000
            )
            if (
                checksum(blob) != member["sourceDigest"]
                or len(blob) != member["sourceByteLength"]
            ):
                stop("FD_ORACLE_WORKBOOK_PIN", member["memberId"])
            workbook_cache[member["sourcePath"]] = blob
    validate_exclusions(
        evidence["boundedExclusions"], evidence["sourceInventory"], workbook_cache
    )

    descriptors = manifest["shards"]
    if descriptors != sorted(descriptors, key=lambda item: byte_key(item["path"])):
        stop("FD_ORACLE_SHARD_DESCRIPTOR_ORDER", "not UTF-8 byte order")
    expected_paths = {
        f"fixtures/product-prototype/{SHARD_DIRECTORY_NAME}/{member['memberId']}.json"
        for member in members
    }
    if (
        len(descriptors) != MAX_FILES
        or {item["path"] for item in descriptors} != expected_paths
        or len({item["path"] for item in descriptors}) != MAX_FILES
    ):
        stop("FD_ORACLE_SHARD_PATH_SET", "not exact")
    semantic_keys: dict[str, set[bytes]] = {key: set() for key in family_policy}
    aggregate = {
        "targetCount": 0,
        "notPublishedCount": 0,
        "zeroCount": 0,
        "formulaCount": 0,
    }
    total_bytes = 0
    exact_comment_coordinates: set[tuple[str, str]] = set()
    raw_comment_notes: set[tuple[str, str, str]] = set()
    tail_notes: set[tuple[str, str, str]] = set()
    layout_headings: set[tuple[str, str, str]] = set()
    member_schema = schemas[
        "contracts/product-prototype/v1/federal-defendants-source-coordinate-semantic-oracle-member.schema.json"
    ]
    forbidden_key_tokens = (
        "source",
        "address",
        "digest",
        "sheet",
        "table",
        "panelkey",
        "panelid",
        "member",
        "rule",
        "hash",
        "ordinal",
        "referencedate",
    )

    for descriptor in descriptors:
        _, shard_blob = artifact_read(descriptor["path"], MAX_SHARD_BYTES)
        total_bytes += len(shard_blob)
        if total_bytes > MAX_TOTAL_SHARD_BYTES:
            stop("FD_ORACLE_SHARD_BYTE_BUDGET", descriptor["path"])
        if (
            len(shard_blob) != descriptor["byteLength"]
            or checksum(shard_blob) != descriptor["digest"]
        ):
            stop("FD_ORACLE_SHARD_PIN", descriptor["path"])
        shard = decode_json(shard_blob, descriptor["path"], MAX_SHARD_BYTES)
        check_schema(shard, member_schema, descriptor["path"])
        member = member_authority[descriptor["memberId"]]
        expected_header = {
            "memberId": member["memberId"],
            "familyId": member["familyId"],
            "releaseId": member["releaseId"],
            "publicationVintageDate": member["publicationVintageDate"],
            "sourcePath": member["sourcePath"],
            "sourceDigest": member["sourceDigest"],
            "sourceByteLength": member["sourceByteLength"],
            "physicalSheet": member["sheet"],
            "authoritativeRange": member["authoritativeRange"],
        }
        if (
            any(shard[key] != value for key, value in expected_header.items())
            or descriptor["familyId"] != member["familyId"]
        ):
            stop("FD_ORACLE_SHARD_IDENTITY", descriptor["path"])
        sheet = IndependentSheet(
            workbook_cache[member["sourcePath"]],
            member["sheet"],
            member["authoritativeRange"],
            member["memberId"],
        )
        title = sheet.cell(member["titleSourceAddress"], merged=True)
        require_authoritative_range(
            member["authoritativeRange"],
            (member["memberId"], "title"),
            member["titleSourceAddress"],
            title["sourceAddress"],
        )
        expected_title = {
            "address": title["sourceAddress"],
            "requestedAddress": member["titleSourceAddress"],
            "sourceAddress": title["sourceAddress"],
            "rawValue": title["rawValue"],
            "rawLexeme": title["rawLexeme"],
            "dataType": title["dataType"],
            "formula": title["formula"],
            "comment": title["comment"],
            "styleIndex": title["styleIndex"],
            "numberFormat": title["numberFormat"],
            "indent": title["indent"],
        }
        if (
            member["tableRule"]["sourceTitle"] != expected_title
            or title["rawValue"] != member["publishedTitle"]
        ):
            stop("FD_ORACLE_SOURCE_TITLE_ASSERTION", member["memberId"])
        expected_layout: set[tuple[str, str]] = set()
        for assertion in member["layoutAssertions"]:
            actual = sheet.cell(assertion["requestedAddress"], merged=True)
            require_authoritative_range(
                member["authoritativeRange"],
                (member["memberId"], "layout"),
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
            if (
                source_proof(actual) != expected
                or assertion["address"] != assertion["sourceAddress"]
            ):
                stop(
                    "FD_ORACLE_LAYOUT_ASSERTION",
                    (member["memberId"], assertion["requestedAddress"]),
                )
            expected_layout.add((assertion["sourceAddress"], assertion["rawValue"]))
            layout_headings.add(
                (member["memberId"], assertion["sourceAddress"], assertion["rawValue"])
            )
        expected_records: dict[str, dict[str, object]] = {}
        expected_comments: set[tuple[str, str]] = set()
        expected_tail: set[tuple[str, str]] = set()
        occupied: set[str] = set()
        if member["tailNoteRange"] is not None:
            for coordinate in rectangle(member["tailNoteRange"]):
                require_authoritative_range(
                    member["authoritativeRange"],
                    (member["memberId"], "tail-note-range"),
                    coordinate,
                )
        for block in member["blocks"]:
            require_authoritative_range(
                member["authoritativeRange"],
                (block["blockId"], "panel-key"),
                block["panelKeyAddress"],
            )
            for range_field in (
                "bodyRange",
                "rowHeaderRange",
                "columnHeaderRange",
                "sexHeaderRange",
                "statisticHeaderRange",
            ):
                if block[range_field] is not None and not all(
                    inside(item, member["authoritativeRange"])
                    for item in rectangle(block[range_field])
                ):
                    stop(
                        "FD_ORACLE_AUTHORITATIVE_RANGE", (block["blockId"], range_field)
                    )
            coordinates = rectangle(block["bodyRange"])
            if (
                len(coordinates) != block["expandedTargetCount"]
                or checksum(("\n".join(coordinates) + "\n").encode())
                != block["expandedCoordinateDigest"]
            ):
                stop("FD_ORACLE_BLOCK_COORDINATES", block["blockId"])
            if occupied.intersection(coordinates):
                stop("FD_ORACLE_BLOCK_OVERLAP", block["blockId"])
            occupied.update(coordinates)
            for assertion in block["sourceAssertions"]:
                actual = sheet.cell(assertion["requestedAddress"], merged=True)
                require_authoritative_range(
                    member["authoritativeRange"],
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
                if (
                    source_proof(actual) != expected
                    or assertion["address"] != assertion["sourceAddress"]
                ):
                    stop(
                        "FD_ORACLE_SOURCE_ASSERTION",
                        (member["memberId"], assertion["requestedAddress"]),
                    )
            note_definitions = {
                item["noteBindingId"]: item for item in block["noteDefinitions"]
            }
            for note in note_definitions.values():
                source = sheet.cell(note["sourceAddress"], merged=True)
                require_authoritative_range(
                    member["authoritativeRange"],
                    (block["blockId"], "note"),
                    note["sourceAddress"],
                    source["sourceAddress"],
                )
                source_text = (
                    source["comment"]
                    if note["sourceKind"] == "comment"
                    else source["rawValue"]
                )
                if (
                    source["sourceAddress"] != note["sourceAddress"]
                    or source_text != note["exactText"]
                    or source["styleIndex"] != note["sourceStyleIndex"]
                    or source["numberFormat"] != note["sourceNumberFormat"]
                    or source["indent"] != note["sourceIndent"]
                ):
                    stop(
                        "FD_ORACLE_NOTE_SOURCE_ASSERTION",
                        (member["memberId"], note["sourceAddress"]),
                    )
                if note["sourceKind"] == "comment":
                    expected_comments.add((note["sourceAddress"], note["exactText"]))
                    raw_comment_notes.add(
                        (member["memberId"], note["sourceAddress"], note["exactText"])
                    )
                else:
                    expected_tail.add((note["sourceAddress"], note["exactText"]))
                    tail_notes.add(
                        (member["memberId"], note["sourceAddress"], note["exactText"])
                    )
            referenced = set(
                block["blockNoteBindingIds"] + block["panelRule"]["noteBindingIds"]
            )
            for rule in [*block["rowRules"], *block["columnRules"]]:
                referenced.update(rule["noteBindingIds"])
            if referenced != set(note_definitions):
                stop("FD_ORACLE_NOTE_COVERAGE", block["blockId"])
            rows = {a1(rule["requestedAddress"])[0]: rule for rule in block["rowRules"]}
            columns = {rule["targetColumn"]: rule for rule in block["columnRules"]}
            for coordinate in coordinates:
                row_number, column_number = a1(coordinate)
                row_rule, column_rule, panel_rule = (
                    rows[row_number],
                    columns[column_number],
                    block["panelRule"],
                )
                for rule, label in (
                    (row_rule, "row"),
                    (column_rule, "column"),
                    (panel_rule, "panel"),
                ):
                    actual = sheet.cell(rule["requestedAddress"], merged=True)
                    require_authoritative_range(
                        member["authoritativeRange"],
                        (block["blockId"], label),
                        rule["requestedAddress"],
                        actual["sourceAddress"],
                    )
                    if (
                        actual["sourceAddress"] != rule["address"]
                        or actual["rawValue"] != rule["rawValue"]
                        or actual["styleIndex"] != rule["styleIndex"]
                        or actual["numberFormat"] != rule["numberFormat"]
                        or actual["indent"] != rule["indent"]
                    ):
                        stop(
                            "FD_ORACLE_AXIS_ASSERTION",
                            (block["blockId"], label, rule["requestedAddress"]),
                        )
                if column_rule["parentAddress"] is not None:
                    parent = sheet.cell(column_rule["parentAddress"], merged=True)
                    require_authoritative_range(
                        member["authoritativeRange"],
                        (block["blockId"], "parent"),
                        column_rule["parentAddress"],
                        parent["sourceAddress"],
                    )
                    if (
                        parent["sourceAddress"] != column_rule["parentAddress"]
                        or parent["rawValue"] != column_rule["parentRawValue"]
                        or parent["styleIndex"] != column_rule["parentStyleIndex"]
                        or parent["numberFormat"] != column_rule["parentNumberFormat"]
                        or parent["indent"] != column_rule["parentIndent"]
                    ):
                        stop(
                            "FD_ORACLE_PARENT_ASSERTION",
                            (block["blockId"], column_rule["parentAddress"]),
                        )
                sources = {
                    "table": member["tableRule"]["canonical"],
                    "block": block["blockCanonical"],
                    "row": row_rule["canonical"],
                    "column": column_rule["canonical"],
                    "panel": panel_rule["canonical"],
                }
                canonical: dict[str, object] = {}
                for owner, source in sources.items():
                    for field, value in source.items():
                        if (
                            block["fieldOwners"].get(field) != owner
                            or field in canonical
                        ):
                            stop("FD_ORACLE_FIELD_OWNER", (block["blockId"], field))
                        canonical[field] = value
                note_ids = sorted(
                    set(
                        block["blockNoteBindingIds"]
                        + row_rule["noteBindingIds"]
                        + column_rule["noteBindingIds"]
                        + panel_rule["noteBindingIds"]
                    ),
                    key=byte_key,
                )
                if block["fieldOwners"].get("footnoteReferenceSet") != "notes":
                    stop("FD_ORACLE_NOTE_OWNER", block["blockId"])
                canonical["footnoteReferenceSet"] = note_ids
                if set(canonical) != set(authority["canonicalFields"]):
                    stop("FD_ORACLE_CANONICAL_FIELD_COVER", block["blockId"])
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
                expected_records[coordinate] = {
                    "canonical": canonical,
                    "sourceBindings": source_bindings,
                    "ruleBindings": rule_bindings,
                }
        records = shard["records"]
        record_coordinates = [record["sourceIdentity"]["address"] for record in records]
        expected_coordinates = sorted(expected_records, key=a1)
        if record_coordinates != expected_coordinates or len(record_coordinates) != len(
            set(record_coordinates)
        ):
            stop("FD_ORACLE_RECORD_COORDINATE_COVER", member["memberId"])
        coordinate_digest = checksum(("\n".join(record_coordinates) + "\n").encode())
        if (
            shard["targetCoordinateCount"] != len(record_coordinates)
            or descriptor["targetCoordinateCount"] != len(record_coordinates)
            or shard["targetCoordinateDigest"] != coordinate_digest
            or descriptor["targetCoordinateDigest"] != coordinate_digest
        ):
            stop("FD_ORACLE_MEMBER_COORDINATE_DESCRIPTOR", member["memberId"])
        member_counts = {
            "targetCount": 0,
            "notPublishedCount": 0,
            "zeroCount": 0,
            "formulaCount": 0,
        }
        policy = family_policy[member["familyId"]]
        for record in records:
            identity = record["sourceIdentity"]
            coordinate = identity["address"]
            if identity != {
                "workbookDigest": member["sourceDigest"],
                "physicalSheet": member["sheet"],
                "address": coordinate,
            }:
                stop("FD_ORACLE_RECORD_IDENTITY", coordinate)
            raw = sheet.cell(coordinate)
            proof = {
                "rawValue": raw["rawValue"],
                "rawLexeme": raw["rawLexeme"],
                "dataType": raw["dataType"],
                "formula": raw["formula"],
                "formatted": render(raw),
                "comment": raw["comment"],
                "styleIndex": raw["styleIndex"],
                "numberFormat": raw["numberFormat"],
            }
            if record["sourceProof"] != {
                **proof,
                "cellProofDigest": checksum(canonical_blob(proof)),
            }:
                stop("FD_ORACLE_RECORD_PROOF", f"{member['memberId']}:{coordinate}")
            if record["valueState"] != independent_state(raw):
                stop(
                    "FD_ORACLE_COMPLETE_VALUE_STATE",
                    f"{member['memberId']}:{coordinate}",
                )
            if record["valueState"]["markerSource"] == "cell-comment":
                exact_comment_coordinates.add((member["memberId"], coordinate))
                expected_comments.add((coordinate, "not published\n"))
            expected = expected_records[coordinate]
            if record["sourceBindings"] != expected["sourceBindings"]:
                stop(
                    "FD_ORACLE_RECORD_SOURCE_BINDINGS",
                    f"{member['memberId']}:{coordinate}",
                )
            if record["ruleBindings"] != expected["ruleBindings"]:
                stop(
                    "FD_ORACLE_RECORD_RULE_BINDINGS",
                    f"{member['memberId']}:{coordinate}",
                )
            if record["canonical"] != expected["canonical"]:
                stop("FD_ORACLE_RECORD_CANONICAL", f"{member['memberId']}:{coordinate}")
            for field, allowed in controlled.items():
                if (
                    field in record["canonical"]
                    and record["canonical"][field] not in allowed
                ):
                    stop(
                        "FD_ORACLE_VOCABULARY_VALUE",
                        (field, record["canonical"][field]),
                    )
            if any(
                any(token in field.casefold() for token in forbidden_key_tokens)
                for field in policy["canonicalKeyFields"]
            ):
                stop("FD_ORACLE_SEMANTIC_KEY_FORBIDDEN_FIELD", policy["familyId"])
            semantic_key = {
                field: record["canonical"][field]
                for field in policy["canonicalKeyFields"]
            }
            if record["semanticKey"] != semantic_key:
                stop("FD_ORACLE_SEMANTIC_KEY_PROJECTION", coordinate)
            semantic_blob = canonical_blob(semantic_key)
            if semantic_blob in semantic_keys[member["familyId"]]:
                stop(
                    "FD_ORACLE_SEMANTIC_KEY_DUPLICATE", (member["familyId"], coordinate)
                )
            semantic_keys[member["familyId"]].add(semantic_blob)
            member_counts["targetCount"] += 1
            member_counts["notPublishedCount"] += (
                record["valueState"]["valueStatus"] == "not-published"
            )
            member_counts["zeroCount"] += raw["rawValue"] == 0
            member_counts["formulaCount"] += raw["formula"] is not None
        raw_comments = {
            (coordinate, str(cell["comment"]))
            for coordinate, cell in sheet.cells.items()
            if cell["comment"] is not None
        }
        if raw_comments != expected_comments:
            stop(
                "FD_ORACLE_RAW_COMMENT_SET",
                (
                    member["memberId"],
                    raw_comments - expected_comments,
                    expected_comments - raw_comments,
                ),
            )
        actual_tail = (
            set()
            if member["tailNoteRange"] is None
            else {
                (coordinate, str(sheet.cell(coordinate)["rawValue"]))
                for coordinate in rectangle(member["tailNoteRange"])
                if sheet.cell(coordinate)["rawValue"] is not None
                or sheet.cell(coordinate)["formula"] is not None
            }
        )
        if actual_tail != expected_tail | expected_layout:
            stop(
                "FD_ORACLE_TAIL_NOTE_SET",
                (
                    member["memberId"],
                    actual_tail - (expected_tail | expected_layout),
                    (expected_tail | expected_layout) - actual_tail,
                ),
            )
        if (
            member_counts != member["expected"]
            or member_counts != shard["counts"]
            or member_counts != descriptor["counts"]
        ):
            stop("FD_ORACLE_MEMBER_COUNTS", (member["memberId"], member_counts))
        for key in aggregate:
            aggregate[key] += member_counts[key]

    expected_comment_coordinates = {
        ("2022-23-federal-offence-group-table-7", cell)
        for cell in ("F19", "G19", "F24", "G24", "F28", "G28", "F52", "G52")
    }
    if exact_comment_coordinates != expected_comment_coordinates:
        stop("FD_ORACLE_EXACT_COMMENT_SET", exact_comment_coordinates)
    expected_aggregate = {key: manifest["expected"][key] for key in aggregate}
    if aggregate != expected_aggregate or aggregate["targetCount"] != MAX_RECORDS:
        stop("FD_ORACLE_AGGREGATE", aggregate)
    note_counts = {
        "attachableTailNoteCellCount": len(tail_notes),
        "sourceCommentNoteCount": len(raw_comment_notes),
        "sourceLayoutHeadingCount": len(layout_headings),
        "commentStatusCount": len(exact_comment_coordinates),
    }
    if any(note_counts[key] != manifest["expected"][key] for key in note_counts):
        stop("FD_ORACLE_NOTE_COUNTS", note_counts)
    family_counts = {
        key: len(semantic_keys[key]) for key in sorted(semantic_keys, key=byte_key)
    }
    if family_counts != manifest["semanticKeyCountsByFamily"]:
        stop("FD_ORACLE_FAMILY_KEY_COUNTS", family_counts)
    if attesting_runtime:
        attest_acceptance_runtime(runtime)
    return {
        "manifestDigest": checksum(manifest_blob),
        **aggregate,
        **note_counts,
        "memberCount": len(descriptors),
        "familyCount": len(family_policy),
        "blockCount": sum(len(member["blocks"]) for member in members),
        "sourceExclusionCount": evidence["boundedExclusions"][
            "excludedNonblankCellCount"
        ],
        "totalShardBytes": total_bytes,
    }


def main() -> None:
    require_acceptance_cli_flags()
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-root-digest", required=True)
    parser.add_argument(
        "--artifact-root", type=Path, default=PROJECT / "fixtures/product-prototype"
    )
    arguments = parser.parse_args()
    print(
        json.dumps(
            verify(
                arguments.expected_root_digest,
                arguments.artifact_root,
                attesting_runtime=True,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise

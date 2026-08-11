"""Deterministic no-copy selection of the first real migration canary."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest
from .source_export import load_and_verify_export

_SCHEMA_VERSION = "tidy.migration-canary-manifest/v1"
_SELECTOR_VERSION = "tidy-migration-canary-selector/v1"
_CANARY_ID = "tidycell-phase-b-stratified-canary-v1"
_RANKING_VERSION = "tidy.migration-canary-ranking/v1"
_ITEM_SET_VERSION = "tidy.migration-canary-item-set/v1"
_DUPLICATE_GROUP_VERSION = "tidy.source-duplicate-group/v1"
_MAX_ITEMS = 96
_MAX_SOURCE_READ_BYTES = 64 * 1024 * 1024
_MAX_UNIQUE_COPY_BYTES = 64 * 1024 * 1024
_MAX_EMBEDDED_RECORDS = 4096
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
_MAX_JSON_DEPTH = 128
_MAX_JSON_NODES = 2_000_000
_COPY_DISPOSITIONS = frozenset(("import", "duplicate-alias", "quarantine"))
_DISPOSITIONS = ("duplicate-alias", "exclude", "import", "quarantine")
_DUPLICATE_BUCKETS = ("pair", "small", "large", "cross-artifact-class")
_SIZE_BUCKETS = ("empty", "small", "medium", "large")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class MigrationCanaryError(RuntimeError):
    """The frozen canary could not be selected or verified safely."""


@dataclass(frozen=True)
class _Requirement:
    requirement_id: str
    kind: str
    observed_count: int
    target_count: int
    predicate: Callable[[Mapping[str, Any]], bool]


class _Selection:
    def __init__(
        self,
        *,
        snapshot_digest: str,
        items: Sequence[Mapping[str, Any]],
        groups: Mapping[str, Sequence[Mapping[str, Any]]],
        canonical: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self.snapshot_digest = snapshot_digest
        self.items = tuple(items)
        self.groups = groups
        self.canonical = canonical
        self.selected: dict[str, Mapping[str, Any]] = {}
        self.reasons: dict[str, set[str]] = defaultdict(set)

    def satisfy(self, requirement: _Requirement) -> dict[str, Any]:
        if requirement.observed_count == 0:
            return {
                "requirementId": requirement.requirement_id,
                "kind": requirement.kind,
                "observedCount": 0,
                "targetCount": 0,
                "status": "not-observed",
                "selectedPaths": [],
            }
        matching = [
            item for item in self.selected.values() if requirement.predicate(item)
        ]
        for item in self._rank(requirement.requirement_id, matching)[
            : requirement.target_count
        ]:
            self.reasons[item["relativePath"]].add(requirement.requirement_id)
        while len(matching) < requirement.target_count:
            candidates = [
                item
                for item in self.items
                if requirement.predicate(item)
                and item["relativePath"] not in self.selected
            ]
            admitted = None
            for candidate in self._rank(requirement.requirement_id, candidates):
                if self._try_add(candidate, requirement.requirement_id):
                    admitted = candidate
                    break
            if admitted is None:
                raise MigrationCanaryError(
                    f"Canary hard bounds prevent {requirement.requirement_id}"
                )
            matching = [
                item for item in self.selected.values() if requirement.predicate(item)
            ]
        chosen = self._rank(requirement.requirement_id, matching)[
            : requirement.target_count
        ]
        for item in chosen:
            self.reasons[item["relativePath"]].add(requirement.requirement_id)
        return {
            "requirementId": requirement.requirement_id,
            "kind": requirement.kind,
            "observedCount": requirement.observed_count,
            "targetCount": requirement.target_count,
            "status": "covered",
            "selectedPaths": sorted(item["relativePath"] for item in chosen),
        }

    def satisfy_duplicate_bucket(self, bucket: str) -> dict[str, Any]:
        requirement_id = f"duplicate-group:{bucket}"
        candidates = [
            group
            for group in self.groups.values()
            if len(group) > 1 and _group_in_bucket(group, bucket)
        ]
        candidates.sort(
            key=lambda group: domain_digest(
                _RANKING_VERSION,
                {
                    "snapshotDigest": self.snapshot_digest,
                    "requirementId": requirement_id,
                    "contentDigest": group[0]["contentDigest"],
                },
            )
        )
        for group in candidates:
            canonical = self.canonical[group[0]["contentDigest"]]
            aliases = [
                item for item in group if item["disposition"] == "duplicate-alias"
            ]
            aliases = self._rank(requirement_id, aliases)
            if bucket == "cross-artifact-class":
                different = [
                    item
                    for item in aliases
                    if item["artifactClass"] != canonical["artifactClass"]
                ]
                if not different:
                    continue
                chosen_aliases = different[:1]
            else:
                chosen_aliases = aliases[: 1 if bucket == "pair" else 2]
            unit = [canonical, *chosen_aliases]
            if len(unit) < 2:
                continue
            if self._try_add_unit(unit, requirement_id):
                paths = sorted(item["relativePath"] for item in unit)
                return {
                    "requirementId": requirement_id,
                    "kind": "duplicate-group",
                    "observedCount": len(candidates),
                    "targetCount": len(paths),
                    "status": "covered",
                    "selectedPaths": paths,
                }
        raise MigrationCanaryError(f"Canary hard bounds prevent {requirement_id}")

    def _try_add(self, candidate: Mapping[str, Any], reason: str) -> bool:
        unit = [candidate]
        if candidate["disposition"] == "duplicate-alias":
            canonical = self.canonical.get(candidate["contentDigest"])
            if canonical is None:
                raise MigrationCanaryError("Duplicate alias lacks one canonical import")
            unit.insert(0, canonical)
        return self._try_add_unit(unit, reason)

    def _try_add_unit(self, unit: Sequence[Mapping[str, Any]], reason: str) -> bool:
        unique = {
            item["relativePath"]: item
            for item in unit
            if item["relativePath"] not in self.selected
        }
        projected = {**self.selected, **unique}
        if not _within_limits(tuple(projected.values())):
            return False
        self.selected.update(unique)
        for item in unit:
            suffix = reason
            if item["disposition"] == "import" and any(
                other["disposition"] == "duplicate-alias" for other in unit
            ):
                suffix = f"duplicate-closure:{reason}"
            self.reasons[item["relativePath"]].add(suffix)
        return True

    def _rank(
        self, requirement_id: str, items: Sequence[Mapping[str, Any]]
    ) -> list[Mapping[str, Any]]:
        return sorted(
            items,
            key=lambda item: (
                domain_digest(
                    _RANKING_VERSION,
                    {
                        "snapshotDigest": self.snapshot_digest,
                        "requirementId": requirement_id,
                        "sourceItemDigest": _source_item_digest(item),
                    },
                ),
                item["relativePath"],
            ),
        )


def select_migration_canary(
    *,
    snapshot: Mapping[str, Any],
    snapshot_file_digest: str,
    snapshot_file_bytes: int,
    frozen_at: str,
) -> dict[str, Any]:
    """Select a deterministic bounded canary from snapshot metadata only."""

    frozen_at = _canonical_timestamp(frozen_at)
    if snapshot.get("schemaVersion") != "tidy.source-export-snapshot/v1":
        raise MigrationCanaryError("Canary requires a frozen source snapshot")
    inventory = _mapping(snapshot.get("inventory"), "snapshot inventory")
    source = _mapping(inventory.get("source"), "snapshot source")
    if source.get("sourceSystem") != "tidycell":
        raise MigrationCanaryError("Canary source must be TidyCell")
    items_value = inventory.get("items")
    if not isinstance(items_value, list) or not items_value:
        raise MigrationCanaryError("Snapshot has no source items")
    items = tuple(_mapping(item, "source item") for item in items_value)
    paths = [item.get("relativePath") for item in items]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise MigrationCanaryError("Snapshot source items are not uniquely sorted")

    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in items:
        if item.get("entryType") == "file":
            digest = item.get("contentDigest")
            if not isinstance(digest, str):
                raise MigrationCanaryError("Regular source item lacks content digest")
            groups[digest].append(item)
    canonical: dict[str, Mapping[str, Any]] = {}
    for digest, group in groups.items():
        if len(group) == 1:
            continue
        imports = [item for item in group if item.get("disposition") == "import"]
        aliases = [
            item for item in group if item.get("disposition") == "duplicate-alias"
        ]
        if len(imports) != 1 or len(aliases) != len(group) - 1:
            raise MigrationCanaryError(
                "Duplicate group lacks exact import/alias closure"
            )
        canonical[digest] = imports[0]

    selector = _Selection(
        snapshot_digest=str(snapshot["snapshotDigest"]),
        items=items,
        groups=groups,
        canonical=canonical,
    )
    requirements = _requirements(items)
    requirement_records = [selector.satisfy(value) for value in requirements]
    for bucket in _DUPLICATE_BUCKETS:
        requirement_records.append(selector.satisfy_duplicate_bucket(bucket))
    requirement_records.sort(key=lambda value: value["requirementId"])

    selected_items = _selected_item_records(
        tuple(selector.selected.values()),
        reasons=selector.reasons,
        groups=groups,
        canonical=canonical,
    )
    duplicate_groups = _selected_duplicate_groups(
        selected_items=selected_items,
        groups=groups,
        canonical=canonical,
    )
    coverage = _coverage(selected_items, duplicate_groups)
    if not _within_limits(tuple(selector.selected.values())):
        raise MigrationCanaryError("Selected canary exceeds its hard bounds")
    producer_before = _producer_source_digest()
    producer_after = _producer_source_digest()
    if producer_before != producer_after:
        raise MigrationCanaryError("Canary selector changed while freezing")
    selected_item_set_digest = domain_digest(_ITEM_SET_VERSION, selected_items)
    semantic = {
        "schemaVersion": _SCHEMA_VERSION,
        "completionStatus": "frozen-no-copy",
        "canaryId": _CANARY_ID,
        "frozenAt": frozen_at,
        "sourceSnapshot": {
            "snapshotDigest": snapshot["snapshotDigest"],
            "inventoryDigest": inventory["inventoryDigest"],
            "itemManifestDigest": inventory["itemManifestDigest"],
            "sourceRootId": source["sourceRootId"],
            "snapshotFileDigest": _require_digest(snapshot_file_digest),
            "snapshotFileBytes": _bounded_int(
                snapshot_file_bytes, "snapshotFileBytes", 1, _MAX_SNAPSHOT_BYTES
            ),
        },
        "selector": {
            "version": _SELECTOR_VERSION,
            "sourceDigest": producer_after,
            "canonicalizationAlgorithm": "tidy-python-sorted-json-v1",
            "rankingAlgorithm": "sha256-domain-requirement-source-item-v1",
            "duplicateClosurePolicy": "include-exact-canonical-import-v1",
            "limits": {
                "maximumItems": _MAX_ITEMS,
                "maximumSourceReadBytes": _MAX_SOURCE_READ_BYTES,
                "maximumUniqueCopyBytes": _MAX_UNIQUE_COPY_BYTES,
                "maximumEmbeddedRecords": _MAX_EMBEDDED_RECORDS,
            },
            "quotas": {
                "regularAdmittedItemsPerObservedStratum": 2,
                "otherItemsPerObservedStratum": 1,
                "duplicateGroupBuckets": list(_DUPLICATE_BUCKETS),
                "sizeBuckets": list(_SIZE_BUCKETS),
            },
        },
        "selectedItems": selected_items,
        "requirements": requirement_records,
        "duplicateGroups": duplicate_groups,
        "coverage": coverage,
        "gates": {
            "sourceBytesCopied": False,
            "importAuthorized": False,
            "liveImporterImplemented": False,
            "typedReconciliationComplete": False,
            "nasServiceIdentityVerified": False,
            "smbSigningVerified": False,
            "snapshotRestoreDrillPassed": False,
            "sqliteOnNasAllowed": False,
            "fullImportAuthorized": False,
        },
        "limitations": [
            "The selector used frozen metadata only and copied no source bytes.",
            *(
                ["Quarantine is not observed in the frozen source snapshot."]
                if not any(item["disposition"] == "quarantine" for item in items)
                else []
            ),
            "Selection does not establish typed interpretation or reconciliation.",
            "NAS service identity, SMB signing, snapshots, and restore remain gates.",
            (
                f"The complete {len(items):,}-item source snapshot remains "
                "separately unauthorized."
            ),
        ],
        "selectedItemSetDigest": selected_item_set_digest,
    }
    return {**semantic, "manifestDigest": domain_digest(_SCHEMA_VERSION, semantic)}


def freeze_canary_from_snapshot(
    *, snapshot_path: Path, frozen_at: str
) -> dict[str, Any]:
    data = _read_regular_stable(snapshot_path, _MAX_SNAPSHOT_BYTES, "source snapshot")
    snapshot, verified_digest = load_and_verify_export(snapshot_path)
    if verified_digest != snapshot.get("snapshotDigest"):
        raise MigrationCanaryError("Snapshot verifier returned a different identity")
    if (
        _read_regular_stable(snapshot_path, _MAX_SNAPSHOT_BYTES, "source snapshot")
        != data
    ):
        raise MigrationCanaryError("Snapshot changed while selecting the canary")
    return select_migration_canary(
        snapshot=snapshot,
        snapshot_file_digest=sha256_digest(data),
        snapshot_file_bytes=len(data),
        frozen_at=frozen_at,
    )


def verify_migration_canary(
    *, manifest: Mapping[str, Any], snapshot_path: Path
) -> None:
    canonical_manifest_digest(manifest)
    rebuilt = freeze_canary_from_snapshot(
        snapshot_path=snapshot_path,
        frozen_at=str(manifest.get("frozenAt")),
    )
    if dict(manifest) != rebuilt:
        raise MigrationCanaryError(
            "Canary manifest differs from deterministic snapshot selection"
        )


def canonical_manifest_digest(manifest: Mapping[str, Any]) -> str:
    root = _mapping(manifest, "canary manifest")
    semantic = dict(root)
    digest = semantic.pop("manifestDigest", None)
    if digest != domain_digest(_SCHEMA_VERSION, semantic):
        raise MigrationCanaryError("Canary manifest identity differs")
    selected = semantic.get("selectedItems")
    if not isinstance(selected, list) or not selected:
        raise MigrationCanaryError("Canary selected item set is empty")
    paths = [item.get("relativePath") for item in selected if isinstance(item, dict)]
    if (
        len(paths) != len(selected)
        or paths != sorted(paths)
        or len(paths) != len(set(paths))
    ):
        raise MigrationCanaryError("Canary selected items are not uniquely sorted")
    if semantic.get("selectedItemSetDigest") != domain_digest(
        _ITEM_SET_VERSION, selected
    ):
        raise MigrationCanaryError("Canary selected-item-set identity differs")
    gates = semantic.get("gates")
    if not isinstance(gates, dict) or any(
        gates.get(name) is not False
        for name in (
            "sourceBytesCopied",
            "importAuthorized",
            "liveImporterImplemented",
            "typedReconciliationComplete",
            "nasServiceIdentityVerified",
            "smbSigningVerified",
            "snapshotRestoreDrillPassed",
            "sqliteOnNasAllowed",
            "fullImportAuthorized",
        )
    ):
        raise MigrationCanaryError("Canary manifest grants forbidden authority")
    return str(digest)


def load_canary_manifest(path: Path) -> dict[str, Any]:
    return _read_strict_json(path, _MAX_MANIFEST_BYTES, "canary manifest")


def write_canary_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    canonical_manifest_digest(manifest)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise MigrationCanaryError("Canary output already exists")
    payload = canonical_json_bytes(dict(manifest)) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as error:
            raise MigrationCanaryError("Canary output already exists") from error
        temporary.unlink()
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _requirements(items: Sequence[Mapping[str, Any]]) -> tuple[_Requirement, ...]:
    requirements: list[_Requirement] = []
    strata: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for item in items:
        strata[(item["artifactClass"], item["disposition"], item["entryType"])].append(
            item
        )
    for (artifact_class, disposition, entry_type), values in sorted(strata.items()):
        target = (
            2
            if entry_type == "file"
            and disposition in _COPY_DISPOSITIONS
            and len(values) >= 2
            else 1
        )
        requirements.append(
            _Requirement(
                requirement_id=(
                    f"artifact:{artifact_class}:disposition:{disposition}:entry:{entry_type}"
                ),
                kind="artifact-disposition-entry",
                observed_count=len(values),
                target_count=target,
                predicate=lambda item, a=artifact_class, d=disposition, e=entry_type: (
                    item["artifactClass"] == a
                    and item["disposition"] == d
                    and item["entryType"] == e
                ),
            )
        )
    for disposition in _DISPOSITIONS:
        count = sum(item["disposition"] == disposition for item in items)
        requirements.append(
            _Requirement(
                requirement_id=f"disposition:{disposition}",
                kind="disposition-presence",
                observed_count=count,
                target_count=1 if count else 0,
                predicate=lambda item, value=disposition: item["disposition"] == value,
            )
        )
    for warning in sorted({value for item in items for value in item["warnings"]}):
        count = sum(warning in item["warnings"] for item in items)
        requirements.append(
            _Requirement(
                requirement_id=f"warning:{warning}",
                kind="warning",
                observed_count=count,
                target_count=1,
                predicate=lambda item, value=warning: value in item["warnings"],
            )
        )
    kinds = sorted(
        {record["kind"] for item in items for record in item["embeddedRecords"]}
    )
    for kind in kinds:
        count = sum(
            any(record["kind"] == kind for record in item["embeddedRecords"])
            for item in items
        )
        requirements.append(
            _Requirement(
                requirement_id=f"embedded-kind:{kind}",
                kind="embedded-kind",
                observed_count=count,
                target_count=1,
                predicate=lambda item, value=kind: any(
                    record["kind"] == value for record in item["embeddedRecords"]
                ),
            )
        )
    for git_state in sorted({item["gitState"] for item in items}):
        count = sum(item["gitState"] == git_state for item in items)
        requirements.append(
            _Requirement(
                requirement_id=f"git-state:{git_state}",
                kind="git-state",
                observed_count=count,
                target_count=1,
                predicate=lambda item, value=git_state: item["gitState"] == value,
            )
        )
    for bucket in _SIZE_BUCKETS:
        count = sum(_size_bucket(item) == bucket for item in items)
        requirements.append(
            _Requirement(
                requirement_id=f"size-bucket:{bucket}",
                kind="size-bucket",
                observed_count=count,
                target_count=1 if count else 0,
                predicate=lambda item, value=bucket: _size_bucket(item) == value,
            )
        )
    return tuple(sorted(requirements, key=lambda value: value.requirement_id))


def _selected_item_records(
    items: Sequence[Mapping[str, Any]],
    *,
    reasons: Mapping[str, set[str]],
    groups: Mapping[str, Sequence[Mapping[str, Any]]],
    canonical: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda value: value["relativePath"]):
        digest = item["contentDigest"] if item["entryType"] == "file" else None
        group = groups.get(digest, ()) if digest is not None else ()
        canonical_item = canonical.get(digest) if digest is not None else None
        group_digest = _duplicate_group_digest(group) if len(group) > 1 else None
        records.append(
            {
                "relativePath": item["relativePath"],
                "sourceItemDigest": _source_item_digest(item),
                "entryType": item["entryType"],
                "artifactClass": item["artifactClass"],
                "disposition": item["disposition"],
                "ruleId": item["ruleId"],
                "sourceMode": item["sourceMode"],
                "byteLength": item["byteLength"],
                "contentDigest": item["contentDigest"],
                "gitState": item["gitState"],
                "embeddedRecordCount": len(item["embeddedRecords"]),
                "embeddedRecordKinds": sorted(
                    {record["kind"] for record in item["embeddedRecords"]}
                ),
                "warnings": list(item["warnings"]),
                "selectionReasons": sorted(reasons[item["relativePath"]]),
                "duplicateGroupDigest": group_digest,
                "canonicalImportPath": (
                    canonical_item["relativePath"]
                    if canonical_item is not None
                    else None
                ),
            }
        )
    if any(not item["selectionReasons"] for item in records):
        raise MigrationCanaryError("Selected canary item lacks a selection reason")
    return records


def _selected_duplicate_groups(
    *,
    selected_items: Sequence[Mapping[str, Any]],
    groups: Mapping[str, Sequence[Mapping[str, Any]]],
    canonical: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    selected_paths = {item["relativePath"] for item in selected_items}
    records: list[dict[str, Any]] = []
    for digest, group in sorted(groups.items()):
        members = sorted(
            (item for item in group if item["relativePath"] in selected_paths),
            key=lambda item: item["relativePath"],
        )
        if len(members) < 2:
            continue
        canonical_item = canonical.get(digest)
        if (
            canonical_item is None
            or canonical_item["relativePath"] not in selected_paths
        ):
            raise MigrationCanaryError(
                "Selected duplicate aliases lack canonical import"
            )
        records.append(
            {
                "contentDigest": digest,
                "groupSizeInSnapshot": len(group),
                "selectedMemberCount": len(members),
                "canonicalImportPath": canonical_item["relativePath"],
                "selectedPaths": [item["relativePath"] for item in members],
                "artifactClasses": sorted({item["artifactClass"] for item in members}),
                "dispositions": sorted({item["disposition"] for item in members}),
            }
        )
    return records


def _coverage(
    selected_items: Sequence[Mapping[str, Any]],
    duplicate_groups: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    copy_items = [
        item for item in selected_items if item["disposition"] in _COPY_DISPOSITIONS
    ]
    unique_copy: dict[str, int] = {}
    for item in copy_items:
        digest = item["contentDigest"]
        if not isinstance(digest, str):
            raise MigrationCanaryError("Copy-eligible canary item lacks content digest")
        previous = unique_copy.setdefault(digest, item["byteLength"])
        if previous != item["byteLength"]:
            raise MigrationCanaryError("Equal content digests have different lengths")
    warnings = Counter(value for item in selected_items for value in item["warnings"])
    embedded_kinds = Counter(
        value for item in selected_items for value in item["embeddedRecordKinds"]
    )
    size_buckets = Counter(
        _selected_size_bucket(item)
        for item in selected_items
        if item["entryType"] == "file"
    )
    return {
        "itemCount": len(selected_items),
        "fileCount": sum(item["entryType"] == "file" for item in selected_items),
        "sourceReadBytes": sum(
            item["byteLength"] for item in selected_items if item["entryType"] == "file"
        ),
        "copyEligibleItemCount": len(copy_items),
        "uniqueCopyObjectCount": len(unique_copy),
        "uniqueCopyBytes": sum(unique_copy.values()),
        "embeddedRecordCount": sum(
            item["embeddedRecordCount"] for item in selected_items
        ),
        "countsByArtifactClass": _count_map(selected_items, "artifactClass"),
        "countsByDisposition": _count_map(selected_items, "disposition"),
        "countsByEntryType": _count_map(selected_items, "entryType"),
        "countsByGitState": _count_map(selected_items, "gitState"),
        "warningCounts": dict(sorted(warnings.items())),
        "embeddedKindCounts": dict(sorted(embedded_kinds.items())),
        "sizeBucketCounts": dict(sorted(size_buckets.items())),
        "duplicateGroupCount": len(duplicate_groups),
        "duplicateAliasCount": sum(
            item["disposition"] == "duplicate-alias" for item in selected_items
        ),
    }


def _within_limits(items: Sequence[Mapping[str, Any]]) -> bool:
    if len(items) > _MAX_ITEMS:
        return False
    source_read = sum(
        item["byteLength"] for item in items if item["entryType"] == "file"
    )
    if source_read > _MAX_SOURCE_READ_BYTES:
        return False
    unique_copy: dict[str, int] = {}
    for item in items:
        if item["disposition"] not in _COPY_DISPOSITIONS:
            continue
        digest = item["contentDigest"]
        previous = unique_copy.setdefault(digest, item["byteLength"])
        if previous != item["byteLength"]:
            return False
    if sum(unique_copy.values()) > _MAX_UNIQUE_COPY_BYTES:
        return False
    return sum(len(item["embeddedRecords"]) for item in items) <= _MAX_EMBEDDED_RECORDS


def _group_in_bucket(group: Sequence[Mapping[str, Any]], bucket: str) -> bool:
    if bucket == "pair":
        return len(group) == 2
    if bucket == "small":
        return 3 <= len(group) <= 9
    if bucket == "large":
        return len(group) >= 10
    if bucket == "cross-artifact-class":
        return len({item["artifactClass"] for item in group}) >= 2
    raise MigrationCanaryError(f"Unsupported duplicate bucket {bucket}")


def _duplicate_group_digest(group: Sequence[Mapping[str, Any]]) -> str:
    if len(group) < 2:
        raise MigrationCanaryError("Duplicate group must contain at least two items")
    return domain_digest(
        _DUPLICATE_GROUP_VERSION,
        {
            "contentDigest": group[0]["contentDigest"],
            "sourceItemDigests": sorted(_source_item_digest(item) for item in group),
        },
    )


def _source_item_digest(item: Mapping[str, Any]) -> str:
    return domain_digest("tidy.export-item/v1", item)


def _size_bucket(item: Mapping[str, Any]) -> str | None:
    if item["entryType"] != "file":
        return None
    return _byte_size_bucket(int(item["byteLength"]))


def _selected_size_bucket(item: Mapping[str, Any]) -> str:
    return _byte_size_bucket(int(item["byteLength"]))


def _byte_size_bucket(byte_length: int) -> str:
    if byte_length == 0:
        return "empty"
    if byte_length <= 4096:
        return "small"
    if byte_length <= 1024 * 1024:
        return "medium"
    return "large"


def _count_map(items: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(item[field]) for item in items).items()))


def _producer_source_digest() -> str:
    project = Path(__file__).parents[2]
    paths = (
        project / "pyproject.toml",
        project / "uv.lock",
        Path(__file__),
        Path(__file__).with_name("migration_canary_cli.py"),
        Path(__file__).with_name("artifacts.py"),
        Path(__file__).with_name("source_export.py"),
        project / "contracts/migration-canary/v1/manifest.schema.json",
    )

    def capture() -> list[dict[str, Any]]:
        return [
            {
                "relativePath": path.relative_to(project).as_posix(),
                "byteLength": path.stat().st_size,
                "contentDigest": sha256_digest(path.read_bytes()),
            }
            for path in paths
        ]

    before = capture()
    after = capture()
    if before != after:
        raise MigrationCanaryError("Canary producer changed while hashing")
    return domain_digest(
        "tidy.migration-canary-selector-source-closure/v1",
        {
            "version": _SELECTOR_VERSION,
            "files": before,
            "pythonImplementation": sys.implementation.name,
            "pythonVersion": list(sys.version_info[:3]),
        },
    )


def _canonical_timestamp(value: str) -> str:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise MigrationCanaryError("Canary time must be canonical UTC seconds")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise MigrationCanaryError("Canary time is invalid") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise MigrationCanaryError("Canary time is not canonical")
    return value


def _require_digest(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise MigrationCanaryError("Expected a SHA-256 digest")
    return value


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise MigrationCanaryError(f"{label} is outside its bound")
    return value


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise MigrationCanaryError(f"{label} must be an object")
    return dict(value)


def _read_strict_json(path: Path, maximum: int, label: str) -> dict[str, Any]:
    data = _read_regular_stable(path, maximum, label)

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"invalid constant {token}")
            ),
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise MigrationCanaryError(f"{label} must be strict UTF-8 JSON") from error
    nodes = 0
    pending = [(value, 1)]
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise MigrationCanaryError(f"{label} exceeds JSON complexity limits")
        if isinstance(current, dict):
            pending.extend((entry, depth + 1) for entry in current.values())
        elif isinstance(current, list):
            pending.extend((entry, depth + 1) for entry in current)
    return _mapping(value, label)


def _read_regular_stable(path: Path, maximum: int, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise MigrationCanaryError(
            f"{label} must be a readable non-symlink file"
        ) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise MigrationCanaryError(f"{label} exceeds its regular-file bound")
        chunks: list[bytes] = []
        length = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - length))
            if not chunk:
                break
            chunks.append(chunk)
            length += len(chunk)
            if length > maximum:
                raise MigrationCanaryError(f"{label} exceeds its byte bound")
        after = os.fstat(descriptor)

        def identity(value: os.stat_result) -> tuple[int, ...]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if identity(before) != identity(after) or length != before.st_size:
            raise MigrationCanaryError(f"{label} changed while reading")
        path_info = path.lstat()
        if stat.S_ISLNK(path_info.st_mode) or identity(path_info) != identity(after):
            raise MigrationCanaryError(f"{label} path changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

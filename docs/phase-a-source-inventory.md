# Phase A source inventory

- Status: frozen implementation candidate published and verified on the NAS
- Acceptance status: committed review candidate; pending independent review
- Provider calls: zero
- TidyCell source writes: zero
- TidyCell content bytes imported: zero
- Active recipe changes: zero

## Purpose

Phase A inventories the current TidyCell on-disk estate without copying source
content or making TidyCell a runtime dependency. It classifies every observed
file or explicitly excluded subtree, hashes exact file bytes, finds duplicate
content, records bounded nested recipe/prompt/response pointers, captures Git
and source-filesystem evidence, and evaluates destination storage headroom.

The implementation is deliberately separate from Phase B import. It cannot
write source content into the authoritative content repository or advance a
recipe pointer.

## Implementation

- `src/tidy_orchestrator/source_export.py`
  - strict policy parser;
  - fd-relative no-follow traversal;
  - file, raw symlink-target, directory, Git, and exporter-closure mutation
    detection;
  - symlink/special-file handling;
  - bounded hashing and JSON/JSONL discovery;
  - workbook container-signature checks;
  - deterministic deduplication, item-manifest identity, and inventory identity;
  - Git HEAD/tree/dirty and tracked/untracked/ignored evidence;
  - source device/inode/mode evidence;
  - storage headroom calculation;
  - report/snapshot integrity verification;
  - committed, idempotent NAS snapshot publication without hard links.
- `src/tidy_orchestrator/source_export_cli.py`
  - `inventory`, `freeze`, `verify`, `publish`, and `verify-publication`;
  - private atomic local output;
  - freeze refusal when headroom fails;
  - fail-closed NAS publication behind `COMMITTED.json`.
- `contracts/migration/v1/`
  - `TidyCellExportSnapshotV1`;
  - `SourceCodeExportSnapshotV1` for the later selected code closure;
  - `ExportItemV1`;
  - `ImportDispositionV1`;
  - strict inventory, policy, storage-assessment, and NAS-commit contracts.
- `tests/test_source_export.py`
  - deterministic replay;
  - duplicate aliases;
  - embedded evidence;
  - malformed protected JSON/JSONL quarantine;
  - policy conflicts and strict JSON;
  - workbook signatures and extension/format mismatch disclosure;
  - symlink target hashing and mutation;
  - special-file, unreadable-file, mutation, limit, overlap, Git-state,
    headroom, tamper, atomic-output, NAS idempotence, incomplete-publication,
    private-mode, cleanup, schema-resolution, and CLI negatives.

The exporter source digest is a domain-separated closure over exact
`artifacts.py`, `source_export.py`, `source_export_cli.py`, and all seven
migration JSON Schema files. The closure is read before and after each scan. The
command is installed as `tidy-source-export` through the locked Python project.

`SourceCodeExportSnapshotV1` is a strict contract only in Phase A. No Tidybank
code has been selected or imported; that point-in-time closure remains a Phase C
gate.

## Final frozen snapshot

The final inventory was run twice with the same source-root identifier, exact
exporter closure, and policy. The deterministic inventory objects were
byte-for-byte equal.

### Identity

| Field                          | Value                                                                     |
| ------------------------------ | ------------------------------------------------------------------------- |
| Source root ID                 | `tidycell-worktree-2026-08-10-phase-a-v1-final-3`                         |
| Frozen at                      | `2026-08-10T07:41:55Z`                                                    |
| TidyCell Git HEAD              | `1be6c995fa931e9860468e40490433161b0121cb`                                |
| TidyCell Git tree              | `96a76a1cbc6f2da3facd31d7cdae5b05926361d3`                                |
| Tracked-dirty digest           | `sha256:3a919b64cd8e5c5d856d13eb4b2ac75c74455f5356ec7fa666b28159d21e3d8e` |
| Source device ID               | `16777230`                                                                |
| Source root inode              | `202332540`                                                               |
| Source root mode               | `16877`                                                                   |
| Policy digest                  | `sha256:64d0fa3671372b5fd9e63ba2dbb3a7fb3176fbdc82bfd6153195c036b6ede632` |
| Exporter source-closure digest | `sha256:f01b7cd7691c5c25d906c35db72a9006c047f3154746532b6f0a4c33d93f2941` |
| Item-manifest digest           | `sha256:b8b62cbdee7f7ff90dca561d8c0605fc40f3dd6ed23de56d7beadff490d6b180` |
| Inventory digest               | `sha256:5b8fc7725f5227f65470f53fc1cc312f73a847c6fec7941d1a4b19976f81e004` |
| Snapshot digest                | `sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d` |
| Snapshot-file digest           | `sha256:d209968e3b590d08788d0d3ca9349cc6f4e263aef0b9235ad616fa63ea08afce` |
| Snapshot-file bytes            | `23,329,847`                                                              |
| Local ignored copy             | `.source-exports/tidycell-phase-a-snapshot-v1-final.json`                 |
| NAS commit-marker digest       | `sha256:b9dd0dd6f4001d7267ccd953ec5b14a183529984b56bb915082b3648c62190f2` |

`tidy-source-export verify` accepted the local and NAS snapshot bytes;
`verify-publication` accepted the exact committed NAS directory. The checked-in
policy and current code/schema exporter closure match the digests recorded in
the snapshot.

### Counts

| Measure                                  |                      Value |
| ---------------------------------------- | -------------------------: |
| Classified items                         |                     44,682 |
| Regular files                            |                     44,670 |
| Explicitly excluded subtrees             |                         10 |
| Explicitly excluded symlinks             |                          2 |
| Proposed imported primary objects        |                     33,080 |
| Duplicate path aliases                   |                     11,511 |
| Explicit exclusions                      |                         91 |
| Quarantines                              |                          0 |
| Unique proposed import bytes             | 20,760,424,705 (19.33 GiB) |
| Duplicate-alias path bytes               |             14,414,981,880 |
| Workbook paths                           |                        414 |
| Unique workbook byte hashes              |                        375 |
| Workbook path bytes                      |                227,672,255 |
| Recipe-evidence paths                    |                      3,985 |
| Model binaries                           |                         65 |
| Embedded recipe/prompt/response pointers |                     23,753 |

Every regular file, including explicitly excluded files, has source mode, byte
size, and SHA-256 evidence. Excluded development subtrees remain intentionally
opaque. The two explicitly permitted generated symlinks bind raw link-target
size and hash without following them.

The broad source policy reduced fallback exclusions to six files: four uploaded
JPGs, one uploaded MP4, and one TypeScript build-info file. No remaining fallback
path name indicated a workbook, recipe, prompt, response, model, approval,
manifest, or report.

### Bounded and format warnings

| Warning                              | Count | Meaning                                                                                                                                                                                                   |
| ------------------------------------ | ----: | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `WORKBOOK_EXTENSION_FORMAT_MISMATCH` |    13 | A `.xls` path contains ZIP/OpenXML bytes. The bytes remain imported, but Phase B must preserve and classify the conversion/provenance distinction.                                                        |
| `EMBEDDED_SCAN_SKIPPED_SIZE`         |   177 | Large JSON/JSONL was still hashed and classified, but nested-pointer scanning was skipped above 16 MiB. The observed files were predominantly feature/prediction corpora plus one harvest candidate file. |
| `EMBEDDED_SCAN_RECORD_LIMIT`         |    18 | Nested discovery stopped at 1,000 pointers in large catalog/feature/label files; bytes and file dispositions remain complete.                                                                             |
| `SYMLINK_NOT_FOLLOWED`               |     2 | Known generated `ltmain.sh` development links were explicitly excluded, target-hashed, and never followed.                                                                                                |

The 13 extension/format mismatches are:

- `abs-spreadsheets/labour/earnings-and-working-conditions/average-weekly-earnings-australia/may-2020/63020010a.xls`;
- three 2016 Personal Safety `.xls` paths (`49060DO0008_2016`,
  `49060do0002_2016`, and `49060do0003_2016`);
- four 2019 Prisoners paths (`4517do001_2019`, `4517do002_2019`,
  `4517do003_2019`, and the guide);
- five 2020 Prisoners paths (the four numbered workbook groups and the guide).

No workbook signature failed, no protected recipe file was quarantined, and no
item was silently omitted. Phase B must use typed parsers rather than treating
bounded discovery pointers or a container magic value as complete domain
semantics.

## Source non-mutation evidence

Immediately after the final freeze and deterministic repeat:

- TidyCell still reported 531 working-tree status entries;
- the tracked-dirty digest remained exactly
  `sha256:3a919b64cd8e5c5d856d13eb4b2ac75c74455f5356ec7fa666b28159d21e3d8e`;
- no source file was written by the exporter; and
- no content import, provider, ML, domain-output/public publication, or
  recipe-activation operation ran.

An excluded `operations/.DS_Store` grew by 4,096 bytes between an early
candidate and the first NAS-qualified prototype. This was disclosed during the
run. The final freeze and its immediate repeat were identical.

## Storage decisions

### Rejected internal volume

The internal data volume failed both agreed storage gates. It had approximately
29.4 GiB free, required 48.67 GiB under `2 × import + 10 GiB`, and would have
reached approximately 97.8% utilization. Meeting the 85% ceiling would have
required freeing approximately 59 GiB. Freeze correctly failed against that
destination.

During definitive validation, concurrent workstation activity reduced internal
free space further to approximately 11.47 GiB (98% utilized) and produced heavy
I/O contention. One pre-publication scan attempt timed out after 30 minutes with
no output and no orphaned process. The successful definitive scan took 32m43s;
the byte-identical repeat took 19m16s. This does not change the passing NAS
assessment, but it independently blocks Phase B and additional large local work
until workstation free space and contention are addressed. No unrelated process
or temporary directory was removed.

### Qualified Synology share

The user mounted the existing Synology SMB share at `/Volumes/Shared Folder`.
The dedicated private root is:

```text
/Volumes/Shared Folder/tidy-dagster
```

Final storage assessment:

| Measure                     |                                  Value |
| --------------------------- | -------------------------------------: |
| Filesystem                  |                                `smbfs` |
| Volume size                 | 3,931,605,622,784 bytes (3,661.59 GiB) |
| Used                        |     741,898,973,184 bytes (690.95 GiB) |
| Free                        | 3,189,706,649,600 bytes (2,970.65 GiB) |
| Estimated unique import     |       20,760,424,705 bytes (19.33 GiB) |
| Required free               |       52,258,267,650 bytes (48.67 GiB) |
| Projected utilization       |                                 19.40% |
| Maximum allowed utilization |                                    85% |
| Headroom result             |                                   pass |

A disposable probe passed private directory behavior, exclusive creation,
write/fsync/read/hash/delete, file and directory `fsync`, same-directory atomic
rename, directory rename, Unicode filenames, and cleanup. SMB mapped requested
private regular-file mode `0600` to private mode `0700`.

Hard links failed with `ENOTSUP` (`errno 45`). Consequently:

- immutable local `freeze` output remains on a hard-link-capable local
  filesystem;
- NAS publication uses an exclusive digest directory and writes verified
  `snapshot.json` before publishing canonical `COMMITTED.json` last;
- consumers ignore any directory without a valid commit marker; and
- the current SQLite-backed `LocalArtifactRepository` must not be pointed at
  SMB directly.

The final committed snapshot is stored at:

```text
/Volumes/Shared Folder/tidy-dagster/source-snapshots/
  sha256-2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d/
    COMMITTED.json
    snapshot.json
```

Three pre-final NAS prototype copies and four superseded local prototype
manifests were removed after the definitive publication verified. They contained
only reproducible inventory manifests, not TidyCell content. The NAS now
contains one snapshot publication and its commit marker.

Server-side Synology ACLs, snapshots/backups, and at-rest encryption were not
administratively verified. The mounted SMB view enforced owner-only modes, which
is sufficient for this manifest candidate but not authorization for bulk raw
prompt/response or model-evidence import.

## Validation

Before the final freeze:

- Python: `91 passed, 1 skipped`;
- focused Phase A: `23 passed`;
- TypeScript/Vitest: `128 passed, 1 skipped`;
- locked Python sync, Ruff format/lint, Python and TypeScript boundary scans,
  TypeScript typecheck/lint/format, pinned fixture verification, parity replay,
  and `git diff --check` passed;
- all seven migration schemas passed Draft 2020-12 meta-schema validation;
- the checked-in policy, final snapshot, representative `ExportItemV1`,
  `ImportDispositionV1`, and NAS commit marker passed their schemas; and
- the real Dagster operational regression passed independently of this
  non-Dagster boundary.

## Remaining acceptance gates

This commit preserves the implementation candidate but does not mark Phase A
accepted. Acceptance still requires:

1. an independent code/evidence reviewer to accept the implementation, policy,
   final snapshot, warning treatment, workbook-format disclosure, and NAS
   publication protocol; and
2. any review findings to be resolved in a follow-up commit without changing the
   exporter closure bound above, or a new snapshot to be frozen if they do.

Bulk Phase B import remains blocked. Before importing 19.33 GiB, Phase B must:

- restore safe internal free space and resolve current workstation I/O
  contention;
- implement and review a NAS content-blob adapter while keeping authoritative
  SQLite metadata local, or select a separately reviewed network-safe metadata
  store;
- verify Synology server-side ACL, backup/snapshot, and at-rest-encryption policy
  for restricted evidence;
- verify each source object against this snapshot; and
- produce item-level reconciliation.

SQLite-over-SMB is not authorized.

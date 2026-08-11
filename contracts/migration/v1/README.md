# `tidy.source-export/v1`

Phase A is a provider-free, read-only inventory boundary. It does not copy
source bytes into the authoritative repository, move recipe pointers, call a
provider, train a model, or publish outputs.

## Contracts

- `policy.schema.json` — strict ordered classification policy.
- `tidycell-source-policy.json` — initial TidyCell estate policy. It is data,
  not a runtime dependency on the sibling repository.
- `import-disposition.schema.json` — `ImportDispositionV1`.
- `export-item.schema.json` — `ExportItemV1`.
- `inventory.schema.json` — deterministic TidyCell inventory core plus a
  current storage assessment.
- `snapshot.schema.json` — `TidyCellExportSnapshotV1`; freeze is refused when
  destination headroom fails.
- `source-code-snapshot.schema.json` — `SourceCodeExportSnapshotV1` for the
  fixture-only explicit source-selection scaffold.
- `source-closure-discovery.schema.json` and
  `source-closure-review.schema.json` — exact two-source no-copy discovery and
  implementing-agent self-review for the pinned real TidyCell/Tidybank summary
  and prompt closure. Neither schema claims parity or independent review.
- `source-closure-copy-commit.schema.json` — immutable repository-local custody
  after reviewed discovery. It binds every copied item and evidence file while
  explicitly denying runtime and parity authority.
- `source-closure-replay.schema.json` — relocated, network-denied execution of
  every copied TidyCell source-owned test. Passing remains source-owned
  regression evidence rather than independent parity.
- `nas-commit.schema.json` — exact commit marker for publishing a verified
  snapshot to a filesystem such as SMB that does not support hard links.

## Identity

The deterministic inventory digest binds:

- the source-system and source-root identifiers (not a workstation path);
- Git HEAD/tree and tracked-dirty evidence when available;
- exact policy and exporter source-closure digests;
- source filesystem device, root inode, and root mode;
- every classified file or explicitly excluded subtree;
- source mode, size, and byte hash for every regular file;
- raw link-target size/hash for explicitly excluded symlinks without following
  them;
- a separately named sorted item-manifest digest;
- source Git state when determinable;
- nested recipe/prompt/response discovery pointers; and
- aggregate disposition, artifact-class, deduplication, and byte counts.

Storage capacity is an observation and is kept outside the deterministic
inventory digest. A frozen snapshot binds completion status, the inventory
digest, the storage-assessment digest, and an explicit UTC freeze time.

The exporter source digest is a domain-separated closure over exact
`artifacts.py`, `source_export.py`, `source_export_cli.py`, and every migration
JSON Schema file. The closure is read before and after every scan;
mutation fails the run.

The Python sorted-JSON digest is named `tidy-python-sorted-json-v1`. It is not
RFC 8785/JCS and is not the historical TidyCell RecipeV01 `digestRecord`
algorithm.

## Fixture-only Phase C source-closure scaffold

`source_code_snapshot.py` accepts only source system `phase-c-fixture`, a
source-root-bound authorization, and an explicit tracked-file selection capped
at 100 files/8 MiB. It hashes every selected file twice through no-follow
root-relative descriptors and binds Git HEAD/tree, status plus exact binary
tracked diff, roles, licence, and producer identity. It returns an in-memory
snapshot and has no CLI or source-copy operation. Real closure selection remains
unauthorized and Phase C parity remains incomplete.

## Real no-copy source-closure discovery

`tidy-source-closure` receives both source roots only through an external
configuration. TidyCell files are no-follow read twice and must exactly match
the frozen Phase A item length, mode, and digest. Tidybank files are read from a
pinned immutable Git commit with `git cat-file`, not from its dirty worktree.
Literal relative and `@/` imports are closed transitively; unresolved relative
imports fail. External package specifiers, entrypoints, source-owned fixtures,
licences, manifests, and lockfiles remain explicit in the output. The checked-in
manifest contains no workstation path and copies no source bytes.

## Safety

The scanner:

- receives source/destination roots as external arguments;
- rejects source-root symlinks and overlapping source/destination trees;
- uses no-follow directory/file opens;
- rejects in-scope symlinks and special files; an exact policy may record a
  known development symlink as excluded without following it;
- hashes excluded regular files as well as import/quarantine candidates;
- detects file, raw symlink-target, and directory mutation during reads;
- re-verifies every observed file and traversed directory before finalization;
- bounds entries, file bytes, JSON scanning, nesting, and embedded-record counts;
- records excluded development subtrees without following them;
- checks workbook container signatures, quarantines invalid signatures, and
  discloses `.xls` paths that contain ZIP/OpenXML bytes;
- treats equal-priority rule matches as policy conflicts; and
- writes reports atomically with private permissions.

A freeze requires:

- free bytes of at least `2 × estimated unique import bytes + 10 GiB`; and
- projected post-import volume utilization no greater than 85%.

APFS clone savings are not assumed.

NAS publication creates one exclusive snapshot-digest directory, writes and
read-verifies `snapshot.json`, and publishes canonical `COMMITTED.json` last.
Consumers must ignore a directory without a valid commit marker. A repeated
publication is idempotent only when both exact files and every bound digest
match. Incomplete, extra-file, non-canonical, or conflicting directories fail
closed.

## CLI

```sh
uv run tidy-source-export inventory \
  --source-root /path/to/source \
  --source-root-id source-snapshot-candidate \
  --destination-root /path/to/destination-repository \
  --destination-id local-authoritative-repository \
  --policy contracts/migration/v1/tidycell-source-policy.json \
  --output /path/to/inventory.json

uv run tidy-source-export freeze \
  --source-root /path/to/source \
  --source-root-id source-frozen-1 \
  --destination-root /path/to/destination-repository \
  --destination-id local-authoritative-repository \
  --policy contracts/migration/v1/tidycell-source-policy.json \
  --frozen-at 2026-08-09T00:00:00Z \
  --output /path/to/snapshot.json

uv run tidy-source-export verify --input /path/to/inventory-or-snapshot.json

uv run tidy-source-export publish \
  --input /path/to/snapshot.json \
  --destination-root '/Volumes/Shared Folder/tidy-dagster'

uv run tidy-source-export verify-publication \
  --directory '/Volumes/Shared Folder/tidy-dagster/source-snapshots/sha256-...'

uv run tidy-source-closure discover \
  --config /private/path/source-closure-request.json \
  --output fixtures/source-closure/summary-prompt-closure-v1.discovery.json

uv run tidy-source-closure verify \
  --config /private/path/source-closure-request.json \
  --manifest fixtures/source-closure/summary-prompt-closure-v1.discovery.json

uv run tidy-source-closure-copy copy \
  --config /private/path/source-closure-request.json \
  --manifest fixtures/source-closure/summary-prompt-closure-v1.discovery.json \
  --review fixtures/source-closure/summary-prompt-closure-v1.self-review.json \
  --destination reference/source-closures/sha256-... \
  --copied-at 2026-08-11T16:45:00Z

uv run tidy-source-closure-copy verify \
  --directory reference/source-closures/sha256-...

npx tsx scripts/replay-source-closure.ts \
  --bundle reference/source-closures/sha256-... \
  --output fixtures/source-closure/summary-prompt-closure-v1.replay.json \
  --recorded-at 2026-08-11T18:30:00Z
```

`inventory` reports failed headroom without failing the scan. `freeze` fails and
publishes no snapshot when headroom does not pass. Existing reports are not
overwritten unless `inventory --replace` is explicit; snapshots are never
replaced. `publish` accepts only a fully verified frozen snapshot. It does not
copy any source-estate content object.

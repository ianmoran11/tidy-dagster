# Phase B fixture-only import contracts

These contracts cover the provider-free, fixture-tested content core and
conservative semantic-import groundwork.
They do **not** authorize the real 19.33 GiB TidyCell import.

## Contracts

- `blob-commit.schema.json` — immutable committed blob marker used on filesystems
  such as SMB that do not support hard links.
- `snapshot-registration.schema.json` — local-metadata registration of one
  verified frozen export and its separately stored exact bytes.
- `import-item.schema.json` — item-level checkpoint binding source evidence,
  proposed disposition, final import state, and optional stored blob.
- `source-alias.schema.json` — immutable path/custody alias. Paths are evidence,
  never content identity.
- `reconciliation.schema.json` — sorted item-level content reconciliation with a
  digest over the mapping.
- `legacy-approval-snapshot.schema.json` — an exact point-in-time observation of
  the mutable legacy registry; it never claims append-only history and retains
  the verifier configuration plus honest production/insecure isolation state.
- `reviewer-label-confirmation-request.schema.json`,
  `reviewer-identity.schema.json`, `approval-resolution.schema.json`, and
  `approval-domain-reconciliation.schema.json` — a Phase A-bound exact-label
  confirmation request, explicit reviewer-label curation, evidence-bearing
  resolved/ambiguous/unresolved/conflicting outcomes, and exact
  one-resolution-per-observed-row coverage without activation or training
  authority.
- `digest-record-vectors.schema.json` and
  `recipe-digest-verification.schema.json` — strict vectors plus bindings to the
  pinned historical TypeScript `digestRecord` compatibility algorithm, source,
  imported recipe, durable worker output, derivation, producer/configuration,
  and honest isolation authority.
- `approval-registry-evidence.schema.json`,
  `recipe-evidence-import.schema.json`, `generation-evidence.schema.json`, and
  `model-package-disposition.schema.json` — conservative typed dispositions.
  These records cannot create approval authority, activate recipes, make
  evidence training-eligible, load a model, or interpret provider evidence.
- `semantic-reconciliation.schema.json` — a per-source-item binding from the
  complete core reconciliation to the exact conservative typed records (or an
  explicit `core-content-only` outcome). Its status still declares full
  semantic import pending.
- `migration-worker-derivation.schema.json` and
  `migration-worker-output.schema.json` — repository authority for one exact
  sandboxed migration-worker derivation and each durable output. Output records
  bind source, configuration, worker/gateway producers, reproduction identity,
  CAS custody, and the honest isolation mode while forcing activation and
  training eligibility to false. The effective normalized Seatbelt profile and
  imported macOS `system.sb` bytes are configuration-bound.

## Current authorization boundary

`FixtureImportAuthorization` has hard limits of 1,000 items and 64 MiB and
requires source system `phase-b-fixture`. There is no live-import authorization
or CLI. The final TidyCell snapshot therefore cannot be copied by this slice.

## Storage boundary

- SQLite authority remains under a local metadata root; the fixture importer
  requires it to share the fixture source's local filesystem device.
- Large bytes are written through `CommittedFilesystemBlobStore` under a
  separate blob root.
- A blob becomes authoritative only after its exact bytes, length, and digest
  verify and canonical `COMMITTED.json` is published last.
- A crash may leave unreferenced committed bytes or an orphaned incomplete
  directory, but never committed metadata pointing to an uncommitted blob.
- Migration-worker outputs use the same durable-blob-first rule. Their output,
  derivation, and reproduction rows commit in one SQLite transaction only after
  the repository re-verifies every referenced CAS object.
- Retry is idempotent and verifies existing committed bytes; a reproduction key
  producing a different fingerprint or derivation fails closed.
- No effective recipe pointer table or transition exists in this repository.

## Deliberate incomplete scope

The core reconciliation report states
`core-content-complete-semantic-import-pending`. Fixture-only groundwork now
covers historical `digestRecord` vectors, exact reviewer-label resolution,
legacy approval outcome states, non-authoritative approval/recipe/generation/
model dispositions, and complete per-item reconciliation of that conservative
pass. The real TidyCell approval registry was read only through a stable
no-follow Phase A digest check to freeze three pending labels; it was not copied,
imported, interpreted as identity authority, or used by tests.

Phase B is not complete until the frozen estate is imported under a separately
reviewed live authorization, typed parsers bind complete recipe and generation
records, every target/reviewer ambiguity is retained, and full domain
reconciliation proves that every source item has exactly one justified typed
outcome. `human_approved` is possible only when exact target, explicit reviewer
identity, and independently verified recipe digest all agree; the fixture path
confers no production authority.

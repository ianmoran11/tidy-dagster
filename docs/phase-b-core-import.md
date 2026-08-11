# Phase B provider-free core import

- Status: core content import plus conservative semantic groundwork implemented for fixtures
- Overall Phase B status: incomplete — live typed import and full domain reconciliation remain pending
- Real TidyCell content copied: zero bytes
- Real canary selection: frozen, 63 items, metadata-only
- Live-import authorization: not implemented
- Provider calls: zero
- Effective recipe pointers changed: zero

## Scope decision

The user explicitly waived independent Phase A review for progression and chose
the bounded Phase B option: implement and test the importer, but do not copy the
real 19.33 GiB estate. ADR 0004 records this decision and its residual risk.

## Implemented

### Split storage boundary

`src/tidy_orchestrator/migration_import.py` adds:

- `MigrationRepository`, which keeps authoritative SQLite metadata under a
  local metadata root;
- `CommittedFilesystemBlobStore`, which stores large bytes under a separate,
  replaceable blob root and does not require hard links;
- mandatory non-overlap checks between source, metadata, and blob roots, plus a
  fixture guard requiring SQLite metadata to share the source's local device;
- exact producer identity over the core importer, lock/project files, Python
  and SQLite runtime versions, dependencies, and five core import schemas;
  typed evidence and approval resolvers carry separate runtime-bound producer
  closures; and
- no pointer table or pointer-changing method.

A blob is authoritative only after:

1. source bytes are streamed through bounded digest/length verification;
2. a private same-filesystem staging file is fsynced;
3. the digest directory is created exclusively;
4. exact bytes are moved into place and read-verified; and
5. canonical `COMMITTED.json` is published last and the directories are fsynced.

A crash may leave unreferenced committed bytes or an incomplete directory moved
to `orphaned/`. Metadata never commits before the blob. Retry verifies and
reuses exact existing bytes.

### Item import and checkpoints

Each fixture item is read with fd-relative no-follow traversal and checked
against the frozen snapshot:

- source root device, inode, and mode;
- safe relative path;
- entry type and source mode;
- exact byte length and SHA-256;
- raw symlink-target hash without following it; and
- pre/post-read filesystem identity.

Each transactional checkpoint binds the exact source item digest, importer
digest, artifact class, proposed disposition, final state, source digest,
storage decision, actor, and fixed record time.

The mapping is:

| Proposed disposition | Final state       | Blob stored                              |
| -------------------- | ----------------- | ---------------------------------------- |
| `import`             | `imported`        | yes                                      |
| `duplicate-alias`    | `duplicate-alias` | shares the same CAS object               |
| `quarantine`         | `quarantined`     | yes, with restricted item classification |
| `exclude`            | `excluded`        | no; bytes/target are still verified      |

### Reconciliation

The core report includes a sorted mapping for every source item and separate
digests for each source item, the full mapping, and the report. It verifies all
referenced committed blobs and reports item/byte counts by final state plus
unique stored objects and bytes.

It deliberately reports:

```text
core-content-complete-semantic-import-pending
```

It cannot be mistaken for full Phase B acceptance.

### Historical digest and approval-resolution groundwork

The TypeScript domain worker now contains an exact compatibility port of the
historical TidyCell `digestRecord` algorithm pinned to
`scripts/harvest/candidate-contract.ts` at source digest
`sha256:ca0f38e741ba43886f809a2c96b782cec4db3a46787eb17f655fad019464114c`.
Eighteen independently derived vectors include Unicode, numeric edge cases,
and simple/rich approval rows. This is compatibility behavior, not RFC
8785/JCS.

`src/tidy_orchestrator/legacy_approvals.py` adds fixture-only records for:

- exact point-in-time snapshots of the mutable legacy approval registry, with
  each resolution bound to the snapshot identity and exact row index/digest;
- curated reviewer identities with exact accepted labels and no case/typo
  repair;
- explicit target outcomes: `resolved`, `ambiguous`, `unresolved`, or
  `conflict`;
- source- and verifier-bound recipe-digest verification; and
- authority outcomes: `human_approved`, `legacy_approved_unattributed`,
  `incomplete_evidence`, or `inactive`.

A fixture-only bridge now requires the approval-registry import checkpoint and
read-verifies its exact committed CAS bytes before constructing and storing the
point-in-time snapshot. A synthetic simple row then resolves to one exact
workbook candidate while remaining `legacy_approved_unattributed`. A separate
approval-domain reconciliation requires exactly one stored resolution for every
observed row and reports target, reviewer, and authority-state counts while
explicitly setting activation and training authorization to false.

A record becomes `human_approved` only if exactly one workbook/sheet target,
one explicitly curated reviewer label, the declared recipe digest, the
historical verifier result, and candidate recipe evidence all agree. A simple
legacy approval can remain `legacy_approved_unattributed`; ambiguity or conflict
is inactive. The fixture tests do not establish any real reviewer identity or
production approval.

### Separate migration-only TypeScript worker

`apps/migration-worker/` adds a dedicated provider-free executable without
expanding the accepted production domain-worker protocol. Its strict
`tidy.migration-worker/v1` protocol currently:

- validates, normalizes, and computes the historical digest of one RecipeV01
  document while keeping the revision inactive and training-ineligible; and
- validates the exact bounded version-1 `{version, approvals}` legacy registry
  and emits the historical digest of every complete approval row.

Every request binds the frozen snapshot, source item, import record, and source
path. Staged inputs are no-follow, length- and digest-verified; JSON bytes,
depth, nodes, and records are capped; roots may not overlap; and declared
outputs publish atomically. The actual bundled executable is exercised in the
suite.

`src/tidy_orchestrator/migration_gateway.py` now supplies the Python-owned
execution authority that was previously missing. It accepts only a complete
import checkpoint whose snapshot, item, record ID, path, artifact class, final
state, content digest, and byte length all match read-verified CAS bytes. It
stages only those bytes, launches the exact bundled executable with bounded
process-group/resource controls, and uses macOS `/usr/bin/sandbox-exec` for the
production factory. The Seatbelt profile denies network and writes outside the
private run root. `insecure-test-only` remains available solely for adversarial
unit tests and its records explicitly state that network isolation was not
enforced. That state is retained in any derived legacy-approval snapshot and
blocks `human_approved` authority; it is never silently upgraded.

The gateway binds the Node executable, bundled worker, exact TypeScript source
closure and historical vectors, migration schemas, package/lock/toolchain
files, runtime version/platform, Python gateway/sandbox/repository/approval
source, and output-custody schemas. The effective normalized Seatbelt profile
and imported macOS `system.sb` bytes are configuration-bound; Mach lookup and
process execution are narrowly allowlisted while network remains denied. It
rechecks producer and source identity after execution, validates the worker
envelope, JSON complexity limits, operation-specific artifact schema, and
recipe-digest comparison independently, publishes output blobs durably, and
transactionally publishes
output custody, derivation, and reproduction rows. A divergent replay fails;
repeated exact execution is idempotent. Recipe revisions and gateway records
remain inactive and training-ineligible.

The approval fixture now obtains its row digests from this actual executable
and gateway before constructing the exact legacy snapshot; Python no longer
supplies pre-recorded digests on that integration path. A valid RecipeV01
fixture likewise enters durable custody only through the gateway. Its typed
historical digest verification binds the imported source item, exact worker
output record, derivation, configuration, producer set, and isolation evidence,
and is persisted before it can contribute to approval resolution. Reviewer
identities must also be persisted. Missing worker output, verification, reviewer
records, or production isolation prevents `human_approved`; insecure approval
digests are `inactive`.

Broader
original-candidate, generation, restricted provider-evidence, model-manifest,
and evaluation parsers remain pending.

### Conservative typed evidence dispositions

`src/tidy_orchestrator/migration_evidence.py` emits immutable fixture records
that deliberately preserve non-authority:

- approval registries remain uninterpreted point-in-time evidence and create no
  approval, activation, or training authority;
- recipe evidence is `incomplete_evidence`, inactive, and training-ineligible;
- model binaries are `archival-unreviewed`, non-runnable, training-ineligible,
  and never deserialized; and
- generation/prompt/response evidence is pointer-classified and marked
  restricted without putting raw prompt or response text in the typed record.

The local metadata repository has an immutable generic typed-record table. A
separate conservative semantic reconciliation now binds every fixture source
item to the exact current-pass typed record IDs or to an explicit
`core-content-only` outcome. It reports
`conservative-dispositions-complete-full-semantic-import-pending`, so it cannot
be mistaken for complete typed import. There is still no active-recipe pointer
table.

### Contracts

`contracts/import/v1/` contains strict schemas for:

- committed blob markers;
- snapshot registration;
- item import checkpoints;
- source aliases and core migration reconciliation;
- legacy approval snapshots, reviewer identities, recipe-digest verification,
  approval-resolution outcomes, and per-row approval-domain reconciliation; and
- conservative approval, recipe, generation, and model evidence dispositions;
- per-source-item conservative semantic reconciliation; and
- migration-worker derivations and inactive durable output custody.

## Fixture-only authorization

There is no live-import CLI or live authorization. `MigrationImporter` requires
`FixtureImportAuthorization`, which:

- requires source system `phase-b-fixture`;
- permits at most 1,000 items;
- permits at most 64 MiB of source-file bytes; and
- binds the exact snapshot and source-root device/inode.

The frozen TidyCell snapshot has 44,682 items and cannot satisfy this boundary.

### Frozen real-import canary

`tidy-migration-canary` now mechanically derives a bounded cohort from the exact
Phase A snapshot without reading or copying selected source bytes. The checked-in
`fixtures/migration-canary/phase-b-canary-v1.json` binds:

- manifest digest
  `sha256:ee072650751fa76d456ba8cf034878a2a48137b02e6e7d459cb7945cb9474139`;
- 63 items, 61 regular files, and 44,084,669 source-read bytes;
- 58 copy-eligible aliases/items representing 36 unique objects and 42,423,291
  unique bytes;
- all 17 observed artifact classes, all three observed dispositions, all entry
  types and Git states, four size buckets, four embedded-record kinds, and all
  four observed warning/adverse classes;
- 22 duplicate aliases across 20 selected groups, always with their exact
  canonical import item; and
- pair, small, large, and cross-artifact-class duplicate-group coverage.

`quarantine` is explicitly recorded as `not-observed`; it is not fabricated.
The implementing-agent self-review digest is
`sha256:8d761f3c697672a8f651a2c81d1a4332ea2eb8b0961550dc51bb22bdf5755bf9`.
It permits only live-import gate implementation and read-only NAS inspection.
Byte copy, canary execution, full import, provider dispatch, activation, and
training all remain unauthorized. The selector is capped at 96 items, 64 MiB of
source reads, 64 MiB of unique copy allocation, and 4,096 embedded records.

### Read-only NAS control inspection

The sanitized implementing-agent inspection at
`fixtures/nas-readiness/phase-b-current-v1.json` has report digest
`sha256:0515d6b98ded8206170ecba7cc2188ba58f7828c21726f500724106f34607053`.
It made no NAS write or configuration change and stores no raw output, server
address, account label, SID, credential, or workstation path. It found:

- the mounted session currently uses SMB 3.1.1;
- AES-128-CMAC signing is observed and supported, but neither client nor server
  reports signing as required, so the ADR signing gate fails;
- payload encryption is off, which ADR 0005 permits;
- the network label matches the local interactive-user label, while dedicated,
  non-admin, subtree-restricted service identity remains unattested;
- snapshot enumeration failed with a sanitized `resource-busy` result, so
  snapshot availability remains unverified rather than being claimed absent;
- no restore procedure or successful drill evidence was provided;
- authoritative SQLite remains on the local device, not SMB; and
- implementation plus integrity/restart/recovery test coverage and the earlier
  real SMB probe are present, but no formal current adapter gate record exists.

`canaryImportReady` is false. The exact blockers are signing-required policy,
dedicated service identity, snapshot evidence, restore drill, and formal adapter
gate evidence. SMB1 negotiation capability is advertised even though the current
session is SMB 3.1.1; no server setting was changed or inferred.

## Validation

The fixture suite covers:

- split metadata/blob roots;
- primary content plus exact duplicate alias reuse;
- excluded files, excluded opaque subtree, excluded symlink, quarantined
  malformed recipe evidence, a never-loaded model binary, and restricted
  prompt/response evidence;
- partial-run checkpoints and incomplete-reconciliation rejection;
- run-twice idempotence and repository reopen;
- crash after snapshot blob but before snapshot registration;
- crash after source blob but before item metadata;
- SQLite transaction rollback immediately before item commit;
- orphan recovery for an incomplete blob directory;
- source-byte mutation and file-to-symlink swap rejection;
- hard fixture limits and non-fixture source rejection;
- metadata/blob/source root overlap rejection;
- committed-blob plus checkpoint/alias/content/registration metadata tamper
  rejection;
- strict schema validation;
- exact reviewer labels, ambiguous/unresolved/conflicting approval outcomes,
  incomplete evidence, and historical approval-row digest vectors;
- non-runnable model plus non-authoritative approval/recipe/generation
  dispositions and their per-item semantic reconciliation; and
- absence of a pointer table.

Results:

- focused migration gateway and import repository: `23 passed`;
- bundled migration-worker protocol: `7 passed`;
- complete Python suite: `149 passed, 1 skipped`;
- TypeScript/Vitest: `155 passed, 1 skipped`;
- real Dagster operational regression: `1 passed`;
- Ruff, format, boundary checks, locked sync, fixture verification, typecheck,
  lint, and parity replay passed.

A disposable 65,536-byte payload was published twice through the new blob store
on the real Synology SMB mount. First publication succeeded, the second was
idempotent, readback matched, no orphan remained, and the entire probe root was
removed. Probe content digest:

```text
sha256:897a120b91a857d50811eab5f04457336ae3a94455f0234535d4240b2025d5d5
```

The Phase A snapshot still verifies after this work. No TidyCell content was
used by any Phase B test.

## Still required for Phase B

The following accepted Phase B work is not implemented:

1. process the now-frozen deterministic real canary under a separately gated
   live authorization, while retaining every unresolved identity and target;
2. extend the now-integrated Python migration gateway beyond approval-row
   digests and RecipeV01 revisions to original candidates, generation attempts,
   raw restricted prompt/responses, model manifests, and evaluation evidence;
3. preserve legacy model packages as unopened archives, as required by ADR
   0005;
4. perform full domain-by-domain reconciliation and prove one justified typed
   outcome for every frozen canary source item and alias;
5. replace the interactive identity with an attested dedicated non-admin
   Synology service identity, require SMB3 signing, establish snapshot evidence,
   and complete a successful restore drill; at-rest encryption was explicitly
   waived in ADR 0005;
6. self-review and authorize a bounded live importer and operational CLI without
   claiming independent review; and
7. run and self-review the real canary. The complete 44,682-item import remains
   separately unauthorized.

The internal volume has recovered to approximately 72 GiB free (83% utilized),
but that transient improvement does not waive the remaining storage-security and
semantic-import gates. SQLite-over-SMB remains unauthorized.

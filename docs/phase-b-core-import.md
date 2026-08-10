# Phase B provider-free core import

- Status: core content import plus conservative semantic groundwork implemented for fixtures
- Overall Phase B status: incomplete — live typed import and full domain reconciliation remain pending
- Real TidyCell content copied: zero bytes
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

A record becomes `human_approved` only if exactly one workbook/sheet target,
one explicitly curated reviewer label, the declared recipe digest, the
historical verifier result, and candidate recipe evidence all agree. A simple
legacy approval can remain `legacy_approved_unattributed`; ambiguity or conflict
is inactive. The fixture tests do not establish any real reviewer identity or
production approval.

### Conservative typed evidence dispositions

`src/tidy_orchestrator/migration_evidence.py` emits immutable fixture records
that deliberately preserve non-authority:

- recipe evidence is `incomplete_evidence`, inactive, and training-ineligible;
- model binaries are `archival-unreviewed`, non-runnable, training-ineligible,
  and never deserialized; and
- generation/prompt/response evidence is pointer-classified and marked
  restricted without putting raw prompt or response text in the typed record.

The local metadata repository has an immutable generic typed-record table. It
has no active-recipe pointer table.

### Contracts

`contracts/import/v1/` contains strict schemas for:

- committed blob markers;
- snapshot registration;
- item import checkpoints;
- source aliases and core migration reconciliation;
- legacy approval snapshots, reviewer identities, recipe-digest verification,
  and approval-resolution outcomes; and
- conservative recipe, generation, and model evidence dispositions.

## Fixture-only authorization

There is no live-import CLI or live authorization. `MigrationImporter` requires
`FixtureImportAuthorization`, which:

- requires source system `phase-b-fixture`;
- permits at most 1,000 items;
- permits at most 64 MiB of source-file bytes; and
- binds the exact snapshot and source-root device/inode.

The frozen TidyCell snapshot has 44,682 items and cannot satisfy this boundary.

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
- non-runnable model and non-authoritative recipe/generation dispositions; and
- absence of a pointer table.

Results:

- focused Phase B content/semantic fixtures: `23 passed`;
- complete Python suite: `114 passed, 1 skipped`;
- TypeScript/Vitest: `148 passed, 1 skipped`;
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

1. process the real frozen registry and estate under a separately reviewed live
   authorization, while retaining every unresolved identity and target;
2. parse and bind complete RecipeV01 revisions, original candidates,
   generation attempts, raw restricted prompt/responses, model manifests, and
   evaluation evidence rather than only conservative fixture dispositions;
3. perform safe isolated model-package inspection/parity and licensing/corpus
   classification without loading pickles in the orchestrator;
4. perform full domain-by-domain reconciliation and prove one justified typed
   outcome for every frozen source item and alias;
5. verify Synology server-side ACL, encryption, and backup/snapshot controls;
6. review and authorize a live importer and operational CLI; and
7. run and independently review the real import.

The internal volume has recovered to approximately 72 GiB free (83% utilized),
but that transient improvement does not waive the remaining storage-security and
semantic-import gates. SQLite-over-SMB remains unauthorized.

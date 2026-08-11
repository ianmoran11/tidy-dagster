# Phase C source-closure custody boundary

- Fixture scaffold status: implemented and tested with synthetic Git repositories
- Real no-copy discovery status: frozen and self-reviewed
- Repository-local reference custody: transactionally committed
- Relocated copied-source replay: 117/117 source-owned tests passed
- Overall Phase C status: incomplete
- Real source bytes copied into Tidy Dagster: 4,781,394 reference-only bytes
- Summary parity: exact on four sheets across three frozen fixture workbooks
- Compact-context parity: exact on the same four sheets
- Formatting and role-aware catalogue: exact on the same four sheets; 43 copied tests pass
- Produced-CSV diagnostic behavior: ported; six copied tests pass
- Rendered prompt-input parity: 14 copied source-owned cases and snapshot exact
- Provider calls: zero

## Purpose

Phase C requires an exact, licensed source-code closure before summary and
prompt-input behavior can be reimplemented and refereed. The original fixture
scaffold exercises that custody boundary without touching real sources.

`src/tidy_orchestrator/source_code_snapshot.py` implements the existing
`SourceCodeExportSnapshotV1` contract for fixture repositories only. It has no
operational CLI and accepts only source system `phase-c-fixture`.

ADR 0005 subsequently authorized read-only discovery of both pinned real
sources. `source_closure_discovery.py` and `tidy-source-closure` now produce and
verify an exact no-copy manifest from an external configuration. No workstation
path is written into the manifest and no sibling runtime dependency is allowed.

## Boundary

`FixtureSourceCodeAuthorization` binds one source-root device and inode and is
hard-capped at:

- 100 explicitly named files;
- 4 MiB per file; and
- 8 MiB for the selected closure.

The caller must assign every selected path one contract role. Selection is
explicit—there is no globbing or dependency inference—and exactly one selected
tracked file must carry the `license` role.

The freezer:

1. requires a committed Git repository and selected files tracked by Git;
2. records HEAD, tree, tracked-dirty state, and a digest over status plus the
   exact binary tracked diff;
3. opens every path relative to a root descriptor with no-follow traversal;
4. accepts bounded regular files only;
5. hashes the complete selection twice and compares both observations;
6. checks root and Git evidence again after reading;
7. binds exact file mode, length, digest, role, licence, exporter closure, and
   runtime identity; and
8. returns an in-memory snapshot without copying or writing source bytes.

Verification rebuilds the snapshot from the same authorized source root and
requires exact equality. Producer drift, selected or unselected tracked-source
mutation, untracked selection, symlink substitution, unsafe paths, and fixture
limit violations fail closed.

## Frozen real no-copy discovery

The selected `tidycell-tidybank-summary-prompt-closure-v1` manifest is committed
at `fixtures/source-closure/summary-prompt-closure-v1.discovery.json`:

- manifest digest:
  `sha256:3ac83cc30cedc9edcf2f68b31c51297a914c755e117ee2b3887f5c90abd7de17`;
- 140 exact items and 4,781,394 bytes;
- 128 TidyCell items exactly matching Phase A snapshot
  `sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d`;
- 12 Tidybank items read from commit
  `c26e7f67091c414b411221af461b8ea3974c6320`, tree
  `6b73f893f0d1a98432251f23cbdaab435ba8dacc`;
- exact MIT licence and package-lock digests for both sources;
- summary builder/detector/renderers, compact context, formatting/catalogue,
  V13 prompt, semantic-map compiler/parser, produced-CSV summary, ML-hint
  renderer, and their transitive imports; and
- 48 source-owned fixture items, including three summary workbooks/recipes,
  eight smoke assets with recipes and expected CSV evidence, both historical
  smoke plans, and the prompt snapshot oracle.

All relative imports resolve. External package imports are explicit and bound
through the selected package manifests and lockfiles. Known dynamically read
source-owned fixtures were inspected and included manually. Discovery hashes
TidyCell through no-follow reads and requires every selected byte to match Phase
A; Tidybank bytes come from immutable Git objects rather than its dirty
worktree. Request, snapshot, and manifest JSON reject duplicate keys,
non-finite values, excess depth, and excess nodes. Producer identity now binds
the discovery, Phase A verifier, digest implementation, contracts, lock/project
metadata, and exact Git executable/version with before/after stability checks.

`summary-prompt-closure-v1.self-review.json` records implementing-agent
self-review digest
`sha256:7d4c8e23a0085b66dc836ef2e03673f01efa38998326b829190d680c0b838369`.
It accepts the manifest only for bounded copy and parity implementation. It
explicitly claims neither independent review nor parity. Its
`sourceBytesCopied: false` claim describes the review-time no-copy state, not the
subsequent separately committed custody event.

## Repository-local reference custody

`tidy-source-closure-copy` copied exactly the 140 reviewed items to:

`reference/source-closures/sha256-3ac83cc30cedc9edcf2f68b31c51297a914c755e117ee2b3887f5c90abd7de17/`

The directory was published by same-parent atomic rename only after every source
item, copied discovery manifest, and copied self-review reverified. Its canonical
`COMMITTED.json` was written last and binds:

- commit digest
  `sha256:579ca12438a6a0a89bbf54fdbb7d9c2b4f506db9c98a5f65e9d8697192e92799`;
- closure manifest digest
  `sha256:3ac83cc30cedc9edcf2f68b31c51297a914c755e117ee2b3887f5c90abd7de17`;
- 140 items and 4,781,394 bytes;
- exact discovery/self-review file bytes and copy-producer closure; and
- `runtimeAuthorized: false` plus `parityEstablished: false`.

The standalone verifier walks the copied tree without sibling worktrees,
rejects symlinks/special/undeclared files, and rechecks every byte, digest,
evidence identity, item-set digest, and canonical commit marker. Copy-time source
paths do not appear in the bundle.

## Relocated source-owned replay

`scripts/replay-source-closure.ts` verifies the immutable bundle, copies only
its TidyCell subtree to a disposable repository-local relocation, runs all 13
copied source-owned tests under macOS Seatbelt with network denied, proves no
source/fixture byte changed, removes the relocation, and verifies the immutable
bundle again. The frozen result is
`fixtures/source-closure/summary-prompt-closure-v1.replay.json`:

- replay digest
  `sha256:8bc23e5eb6b0cc2045d0a2ad417d6516b8c37bb6737bce82cedfe7ec7141eedb`;
- 13/13 test files and 117/117 tests passed, with zero failures/skips;
- source-tree digest was unchanged at
  `sha256:f21a096bff904935300e206abeb1b41f21858c75befa027db724ae02bab967e6`;
- no sibling runtime dependency or source-worktree path was used; and
- network isolation was enforced.

This is source-owned regression evidence, not independent parity gold. It uses
Tidy Dagster's locked `node_modules` rather than installing the copied full
TidyCell lockfile, and Tidybank has no copied source-owned summary test.
Accordingly `parityEstablished` remains false.

## Default sheet-summary parity increment

The historical summary/detector/Markdown/HTML closure is now ported into
`apps/domain-worker/src/summary/`, with candidate-block detection and selector
decomposition retained as separate deterministic modules. The worker accepts
`includeSummary: true` and emits `sheet-summary.json`; false/absent preserves the
existing output set.

`scripts/freeze-source-summary-reference.ts` runs only the copied historical
source in a disposable relocation under network-denied macOS Seatbelt. It
verifies the immutable bundle before and after, proves the copied source tree is
unchanged, and writes the self-reviewed historical reference at
`fixtures/reference-summary/historical-v1.json`:

- reference digest
  `sha256:0d0dca23d4f08204cbf02d6cc841fbd5ba15df32aeab92da77a0f91f5ff49c70`;
- three exact workbook digests and four sheet summaries;
- default summary options with `checked: true`;
- no candidate implementation used; and
- no sibling runtime dependency or network access.

Two repeated reference runs produced an identical record. The candidate port
passes the nine copied source-owned summary tests and exactly matches all four
frozen summary objects. The separate self-reviewed candidate parity record at
`fixtures/reference-summary/candidate-parity-v1.json` binds candidate source
digest
`sha256:8b9100009d4d9d137b0f696d334094602b3bb1d3c7d03c94e1a142079b204b43`
and parity digest
`sha256:c18a2b12f8acea488798c23123371a9d1f2d684bb713506aac50c84d452d45c4`.
This establishes bounded default-option compatibility, not full Phase C parity
or independent review. The historical reference honestly retains
`parityEstablished: false`; the later parity record establishes only its
explicit fixture/default-option scope without rewriting reference provenance.

## Compact complete semantic-context parity increment

The copied `cell-role-compact-context-v1` implementation is now ported as
`apps/domain-worker/src/context/compactContext.ts`. It preserves complete
row-major coordinates, explicit blanks, bounded style boundaries, deterministic
serialization and digesting, completeness checks, and prompt-leakage guards.
The worker emits `compact-context.json` only when
`includeCompactContext: true`.

A separate network-denied historical-source harness freezes four contexts at
`fixtures/reference-context/historical-v1.json` with reference digest
`sha256:1bf6352d8379cec115896e74642dd4cefaa4bf50c21540827815055164cd8cb9`.
Two runs produce the same record. The candidate matches all four snapshots
exactly. Its source digest is
`sha256:90f0a5d447c7187ef5ffb652c365f21612440aeb6b260b0ee49b875a084fc174`
and scoped parity digest is
`sha256:d7cc5a3905e6cb3d78d379e27e76b02b936775e0da4d3e7c5c8e3e34e834636a`.
As with summaries, the historical reference remains provenance-only and false
for candidate/full parity; the later self-reviewed comparison establishes only
the explicit four-context scope.

## Formatting, catalogue, and compiler increment

The bounded V13-era catalogue/compilation closure is now standalone under
`apps/domain-worker/src/catalog/`: CellRole Sketch V0.2 parsing, geometry,
RecipeV01 compilation and equivalence proofs, SemanticTableMap V1, format-aware
V2 candidates, and role/year-aware V5 candidates. `includeRegionCatalog: true`
emits `region-catalog.json` without requiring a provider. All 43 copied
historical source tests pass, including exact direction, correction,
completeness, formatting, repeated-panel, and year-like geometry cases.
A separate network-denied relocated harness also freezes four historical
catalogues with reference digest
`sha256:7632516d91c47855105d72b072df7368bf67b2167c0e74a4ab4833f6b5a954df`.
The candidate source closure digest is
`sha256:642319362bdc654d2b37ca9ed69b3234dd9fa41b756cfabc423404e054760da4`
and the implementing-agent self-reviewed scoped parity digest is
`sha256:1ff8c4be2c785745f1e2c8fbd839160da659f56c6a571911368526047b76c0a1`.
The historical record remains provenance-only and false for candidate/full
parity; the separate candidate record establishes only exact four-catalogue
compatibility.

## Produced-CSV diagnostic increment

`apps/domain-worker/src/review/producedCsvSummary.ts` now carries the frozen
column-summary, duplicate-key, numeric-parse, missingness, sparse-column-pair,
suspicious-row, and bounded prompt-sample behavior. All six copied historical
source tests pass against the standalone port. This module remains provider-free
and is not exposed as a standalone worker output.

## Rendered prompt-input increment

The frozen prompt assembler, candidate-range hints, variants, rule tiers,
example loader, compact ML hints, and publication-ontology hint closure are now
standalone under `apps/domain-worker/src/prompt/`. All 14 copied source-owned
prompt tests pass against the exact copied snapshot bytes
`sha256:590b27f2e3f87bc6efcf614e9e9a1c5eb6590c640a5d518aad4596628dfd612e`.
The snapshot covers generate, repair, review, provider caching, ontology,
candidate-range, and produced-CSV review payloads. The prompt parity record has
candidate source digest
`sha256:8dae7aca93c056b262c07fd0c51c350dc5dd0747a76be06903b8c8867186e67d`
and scoped parity digest
`sha256:8f96220e3d617ab61c315556d749ab28d57e2f1d4fd00167c2ea95dcc45e72c2`.

This remains synthetic, implementing-agent self-reviewed compatibility
evidence. Raw production prompts remain restricted, absent from ordinary
Dagster logs, and intentionally not exposed as an ordinary worker output.
Provider dispatch and independent review remain separate gates.

## Validation

- focused source-closure discovery/copy and source-export suite: `30 passed`;
- copied summary behavior tests: `9 passed`;
- historical-reference candidate summary parity: `4/4` sheets exact;
- focused compact-context behavior tests: `4 passed`;
- historical-reference candidate compact-context parity: `4/4` exact;
- copied V0.2/V1/V2/V5 compiler/catalogue tests: `43 passed`;
- historical-reference candidate region-catalogue parity: `4/4` exact;
- copied produced-CSV diagnostic tests: `6 passed`;
- copied rendered prompt and exact snapshot tests: `14 passed`;
- complete TypeScript/Vitest suite: `235 passed, 1 skipped`;
- complete Python suite: `158 passed, 1 skipped`;
- strict JSON Schemas validate discovery, self-review, copy, replay, reference,
  and scoped parity records;
- the checked-in producer digest binds the exact discovery implementation;
- repeated discovery and `tidy-source-closure verify` reproduce the manifest;
- the standalone copy verifier accepts the 140-item committed bundle; and
- two relocated replay runs produced the same exact 117-test evidence record.

## Deliberately not implemented

This boundary does not yet:

- authorize the copied closure as a runtime dependency;
- prove custody of arbitrary dynamic runtime paths beyond the explicitly
  inspected fixture reads;
- complete summary/context/catalogue/prompt adversarial parity or expose
  restricted production prompt evidence without an explicit custody policy;
- create independent parity gold; or
- expose prompt-generation behavior through the worker.

## Next Phase C gate

ADR 0005 permitted the now-completed bounded copy after exact custody and
implementing-agent self-review. Relocated source-owned replay and bounded default
summary and compact-context parity now pass; the role-aware catalogue/compiler,
produced-CSV diagnostics, and rendered prompt assembly are ported. The next step
is broader adversarial/option coverage plus explicit restricted prompt custody.
Phase C remains incomplete until full intermediate
and rendered-output parity, adversarial fixtures, independently refereed
relocated parity, and all existing M0–M4 checks pass.

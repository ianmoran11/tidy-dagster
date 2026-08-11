# Phase C source-closure custody boundary

- Fixture scaffold status: implemented and tested with synthetic Git repositories
- Real no-copy discovery status: frozen and self-reviewed
- Overall Phase C status: incomplete
- Real source bytes copied into Tidy Dagster: none
- Summary/prompt-input parity claim: none
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
  `sha256:5ebbc33af007da70bbda676eff79d40f4c08decb38d713c0083003ff01154c3f`;
- 138 exact items and 4,233,461 bytes;
- 126 TidyCell items exactly matching Phase A snapshot
  `sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d`;
- 12 Tidybank items read from commit
  `c26e7f67091c414b411221af461b8ea3974c6320`, tree
  `6b73f893f0d1a98432251f23cbdaab435ba8dacc`;
- exact MIT licence and package-lock digests for both sources;
- summary builder/detector/renderers, compact context, formatting/catalogue,
  V13 prompt, semantic-map compiler/parser, produced-CSV summary, ML-hint
  renderer, and their transitive imports; and
- 46 source-owned fixture items, including three summary workbooks/recipes and
  eight smoke assets with recipes and expected CSV evidence.

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
`sha256:17e8f477ffab91708ea1649625a9c5e8b2572cf57cdc6c93d8f5de1fbb74f742`.
It accepts the manifest only for bounded copy and parity implementation. It
explicitly claims neither independent review nor parity.

## Validation

- focused source-closure discovery/scaffold and source-export suite: `29 passed`;
- strict JSON Schemas validate the checked-in discovery and self-review;
- the checked-in producer digest binds the exact discovery implementation; and
- repeated discovery and `tidy-source-closure verify` reproduce the manifest
  without copying source bytes.

## Deliberately not implemented

This boundary does not yet:

- copy the selected source closure into Tidy Dagster;
- prove custody of arbitrary dynamic runtime paths beyond the explicitly
  inspected fixture reads;
- implement detector, renderer, compact-context, formatting, catalogue, or
  produced-CSV summary behavior;
- create independent parity gold; or
- modify the production worker protocol.

## Next Phase C gate

ADR 0005 permits bounded copying after exact custody and implementing-agent
self-review. The next step is therefore a transactional copy of only these 138
selected items behind an immutable commit marker, followed by a relocated
reference replay. Phase C remains incomplete until full intermediate and
rendered-output parity, adversarial fixtures, relocated replay, and all existing
M0–M4 checks pass.

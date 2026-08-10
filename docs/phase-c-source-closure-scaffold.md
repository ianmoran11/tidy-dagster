# Phase C fixture-only source-closure scaffold

- Scaffold status: implemented and tested with synthetic Git repositories
- Overall Phase C status: incomplete
- Real TidyCell or Tidybank source selected, read, or copied: none
- Summary/prompt-input parity claim: none
- Provider calls: zero

## Purpose

Phase C requires an exact, licensed source-code closure before summary and
prompt-input behavior can be reimplemented and independently refereed. This
scaffold exercises that custody boundary without choosing or touching the real
TidyCell/Tidybank closure.

`src/tidy_orchestrator/source_code_snapshot.py` implements the existing
`SourceCodeExportSnapshotV1` contract for fixture repositories only. It has no
operational CLI and accepts only source system `phase-c-fixture`.

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

## Validation

- focused source-closure scaffold: `4 passed`;
- complete Python suite: `118 passed, 1 skipped`;
- TypeScript/Vitest: `148 passed, 1 skipped`;
- Ruff, format, boundary checks, typecheck, fixture verification, and parity
  replay passed.

## Deliberately not implemented

This scaffold does not:

- choose the real TidyCell or Tidybank summary closure;
- traverse or read either sibling worktree;
- copy source into Tidy Dagster;
- infer transitive dependencies;
- implement detector, renderer, compact-context, formatting, catalogue, or
  produced-CSV summary behavior;
- create independent parity gold; or
- modify the production worker protocol.

## Next Phase C gate

A separate explicit decision must select the real closure. That decision should
name every source, fixture, manifest, lockfile, notice, and licence byte from the
pinned repositories. Only after the resulting source snapshot is frozen and
reviewed should implementation begin against an independent reference bundle.
Phase C remains incomplete until full intermediate and rendered-output parity,
adversarial fixtures, relocated replay, and all existing M0–M4 checks pass.

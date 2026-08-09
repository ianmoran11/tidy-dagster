# tidy-dagster

`tidy-dagster` is a staged, standalone reimplementation of TidyCell's spreadsheet-to-recipe pipeline and its future semantic-data and microsimulation-calibration workflow.

## Current status

**M0–M3 provider-free execution is implemented; M2 is not yet accepted because summary remains unsupported.** A provider-free TypeScript worker parses and executes the three pinned synthetic fixtures (`simple-crosstab`, `sparse-headers`, and `multi-table`) through strict file manifests. It emits parsed workbook, normalized recipe, selector, geometry, full execution, and exact per-table CSV evidence.

M3 adds a Python-owned authoritative local repository for content, derivations, custody, append-only decisions, and compare-and-swap pointers. Its hardened POSIX gateway launches the actual TypeScript executable in private roots, enforces process and file bounds, terminates the complete process group on timeout, verifies every declared output, and publishes only a fully verified output set. The offline application runs all three fixtures twice with identical semantic derivation and output fingerprints.

Summary is deliberately unsupported because the full reviewed TidyCell/Tidybank detector and renderer closure is not included. M4 Dagster projection is not implemented. No provider, recipe-approval, semantic-adoption, calibration, ML, ABS/research, or Sembla implementation or authority is present.

Two architectural decisions were confirmed on 2026-08-09:

1. Build a **staged standalone reimplementation**, proving parity one vertical slice at a time rather than wrapping TidyCell indefinitely or attempting a big-bang rewrite.
2. Use **deliberate polyglot boundaries**:
   - Python owns Dagster orchestration and ML;
   - a standalone TypeScript worker owns workbook, RecipeV01, and evidence-building behavior, and may validate pinned semantic exports without claiming semantic-contract authority;
   - Sembla will remain an external Rust CLI and must be pinned before real use; no version or artifact is selected yet.

Dagster is a replaceable control-plane adapter. It must not become the sole store of evidence, identities, approvals, or business rules.

## Planning documents

- [Staged reimplementation plan](docs/reimplementation-plan.md)
- [Source evidence and planning baseline](docs/source-evidence.md)
- [M3 provider-free runtime](docs/m3-provider-free-runtime.md)
- [ADR 0001 — staged standalone reimplementation](docs/decisions/0001-staged-standalone-reimplementation.md)
- [ADR 0002 — deliberate polyglot boundaries](docs/decisions/0002-deliberate-polyglot-boundaries.md)

## Intended end-to-end path

```text
source inventory
  → immutable workbook bytes
  → worksheet profile
  → recipe candidate
  → deterministic RecipeV01 execution
  → human recipe decision
  → effective approved recipe, when applicable
  → deterministic tidy output
  → separately authorized publication, when applicable
  → semantic tables and cells
  → semantic review and adoption
  → frozen calibration-design ledger
  → Sembla target projection
  → simulation observations and scores
```

The semantic and calibration stages are future gated capabilities. The current justice scaffold remains draft/provisional, calibration-role assignment remains deferred, and the Sembla justice integration is still proposed rather than implemented.

## Implemented provider-free slice

```text
three pinned synthetic workbook/recipe triplets
  → standalone TypeScript parsing
  → strict RecipeV01 validation and execution
  → parsed/selector/geometry/execution JSON and exact table CSV
  → external run-twice fixture harness and frozen compatibility gold
```

### Commands

Requires Node 24.7.x and npm.

```sh
npm ci
npm run verify:fixtures
npm test
npm run typecheck
npm run lint
npm run format:check
npm run parity:replay
# or all validation after installation:
npm run check
```

Build the worker with `npm run build`; the stable package bin is `tidy-domain-worker` and its wire contract is documented in [`contracts/worker/v1`](contracts/worker/v1/README.md). Fixture custody is recorded in [`fixtures/parity/source-manifest.json`](fixtures/parity/source-manifest.json). Independently executed pinned-reference bytes and their clean-checkout procedure are recorded in [`fixtures/gold/manifest.json`](fixtures/gold/manifest.json), while `fixtures/expected/*.json` remains an additional source-authored partial oracle.

The Python repositories/gateway are implemented in `src/tidy_orchestrator`. A thin Dagster projection, external review authority, generation/provider dispatch, semantic contracts, and Sembla integration remain later gated milestones.

## M3 provider-free Python execution

Requires Python 3.13 and `uv`. The lockfile pins the complete development environment.

```sh
uv sync --locked
uv run ruff check .
uv run python -m tidy_orchestrator.boundaries
uv run pytest -q
npm run build
uv run tidy-provider-free demo \
  --repository .provider-free-demo/repository \
  --project-root "$PWD"
```

The demo verifies the fixture source manifest, invokes the actual built `tidy-domain-worker`, compares every output with frozen independent-reference gold, stores immutable bytes and records under the selected repository root, and runs each fixture twice. Its JSON result records `providerCalls: 0` and `networkIsolationEnforced: true` on the required macOS production path.

Production execution currently requires macOS `/usr/bin/sandbox-exec`. A generated deny-default profile limits runtime reads, permits writes only in the private run root, and denies network and process forks. The gateway also applies rlimits and process-group cleanup. The explicitly named `insecure-test-only` mode is used for portable failure drills and does not claim filesystem, detached-process, or network isolation; no non-macOS production sandbox is selected yet.

## Permanent guardrails

- Content bytes and explicit contract versions define identity; paths and display names do not.
- Human decisions are attributable immutable records, not inferred from file presence or passing checks.
- Provider responses are saved before interpretation and reused on retry.
- Large artifacts live in content-addressed storage, not Dagster event logs or step payloads.
- Deterministic domain behavior remains runnable and testable without Dagster.
- The new project must not import mutable source code from the TidyCell, justice-scaffold, or Sembla worktrees.
- Research evidence, production approvals, semantic adoption, calibration design, and execution authorization remain separate authorities.

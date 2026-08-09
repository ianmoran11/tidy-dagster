# tidy-dagster

`tidy-dagster` is a staged, standalone reimplementation of TidyCell's spreadsheet-to-recipe pipeline and its future semantic-data and microsimulation-calibration workflow.

## Current status

**M0–M2-scoped deterministic compatibility slice implemented; M2 is not yet accepted.** A provider-free, networkless TypeScript worker now parses and executes the three pinned synthetic fixtures (`simple-crosstab`, `sparse-headers`, and `multi-table`) through strict file manifests. It emits parsed workbook, normalized recipe, selector, geometry, full execution, and exact per-table CSV evidence. The external harness replays every fixture twice in relocated temporary roots.

Summary is deliberately unsupported because this milestone does not include the full reviewed TidyCell/Tidybank detector and renderer closure. No Python, Dagster, provider, recipe-approval, semantic-adoption, calibration, ML, ABS/research, or Sembla implementation or authority is present.

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

Python repositories/gateways, a thin Dagster projection, external review decisions, replayed generation, live-provider readiness, semantic contracts, and Sembla integration remain later gated milestones.

## Permanent guardrails

- Content bytes and explicit contract versions define identity; paths and display names do not.
- Human decisions are attributable immutable records, not inferred from file presence or passing checks.
- Provider responses are saved before interpretation and reused on retry.
- Large artifacts live in content-addressed storage, not Dagster event logs or step payloads.
- Deterministic domain behavior remains runnable and testable without Dagster.
- The new project must not import mutable source code from the TidyCell, justice-scaffold, or Sembla worktrees.
- Research evidence, production approvals, semantic adoption, calibration design, and execution authorization remain separate authorities.

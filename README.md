# tidy-dagster

`tidy-dagster` is a staged, standalone reimplementation of TidyCell's spreadsheet-to-recipe pipeline and its future semantic-data and microsimulation-calibration workflow.

## Current status

**M0–M4 provider-free execution and its replaceable Dagster OSS projection are implemented; M2 is not yet accepted, although default sheet summaries and compact contexts now match four frozen historical-reference sheets exactly.** A provider-free TypeScript worker parses and executes the three pinned synthetic fixtures (`simple-crosstab`, `sparse-headers`, and `multi-table`) through strict file manifests. It emits parsed workbook, normalized recipe, selector, geometry, full execution, and exact per-table CSV evidence, plus parity-locked default summary/compact-context evidence and a bounded provider-free V5 region catalogue when requested.

M3 adds a Python-owned authoritative local repository for content, derivations, custody, append-only decisions, and compare-and-swap pointers. Its hardened macOS production gateway launches the bundled TypeScript executable in private roots, enforces process/file/sandbox bounds, verifies every declared output, and publishes only a fully verified output set. The offline application runs all three fixtures twice with identical semantic derivation and output fingerprints.

M4 adds one Dagster 1.13.17 code location, a shared dynamic work-unit partition topology, immutable gate mirrors, a default sensor, persistent-instance reconstruction, and repo-owned loopback/Tailscale operations. Dagster remains an operational projection rather than evidence authority. Default summary and compact-context outputs are supported against relocated historical-source references. The V5 role-aware catalogue/compiler is also ported with 43 copied tests passing; exact catalogue-reference, broader options, and rendered prompt-input closure remain incomplete.

The post-M4 Phase A boundary has frozen and NAS-published a deterministic read-only TidyCell inventory. Independent review did not occur; ADR 0005 now permits implementing-agent self-review while requiring that status to remain explicit. A fixture-only Phase B core proves split local-SQLite/NAS-compatible blob storage, crash-safe item checkpoints, deduplication, content reconciliation, historical approval-digest compatibility, explicit reviewer/approval outcomes, conservative approval/recipe/generation/model dispositions, and per-item semantic-pass reconciliation. A separate bounded TypeScript migration executable now parses RecipeV01 evidence and computes exact legacy approval-row digests without expanding the production worker protocol; its Python gateway binds imported CAS sources, launches under production macOS Seatbelt, and transactionally publishes inactive output custody, derivation, and reproduction authority. Real import remains absent, but a 63-item/44,084,669-byte deterministic stratified canary is now frozen from Phase A metadata with byte-copy and import authority explicitly false. A sanitized read-only NAS inspection confirms SMB 3.1.1 and local SQLite while leaving signing-required policy, dedicated service identity, snapshots, restore, and formal adapter evidence blocked. Phase C now has a self-reviewed manifest and transactionally committed repository-local reference copy for 140 exact TidyCell/Tidybank summary, prompt, dependency, licence, lockfile, and fixture items (4,781,394 bytes). A relocated, network-denied replay passes all 117 copied TidyCell source-owned tests without mutating the bundle. Separate historical-source harnesses freeze four default sheet summaries and four complete compact contexts, and the standalone worker matches them exactly. The V5 region catalogue/compiler and produced-CSV diagnostic behavior are also ported with 43 and six copied tests passing respectively; this is implementing-agent compatibility evidence, not independent review or full prompt-input parity. Phase B has no live authorization or CLI and cannot import the 44,682-item TidyCell snapshot. The internal volume has recovered to about 83% utilization, but real import remains blocked by Synology service-identity/recovery gates and incomplete full-estate typed reconciliation. No TidyCell content object has been imported, no provider or ML operation has run, and no recipe, domain-publication, semantic, calibration, or Sembla authority has changed.

Two architectural decisions were confirmed on 2026-08-09:

1. Build a **staged standalone reimplementation**, proving parity one vertical slice at a time rather than wrapping TidyCell indefinitely or attempting a big-bang rewrite.
2. Use **deliberate polyglot boundaries**:
   - Python owns Dagster orchestration and ML;
   - a standalone TypeScript worker owns workbook, RecipeV01, and evidence-building behavior, and may validate pinned semantic exports without claiming semantic-contract authority;
   - Sembla will remain an external Rust CLI and must be pinned before real use; no version or artifact is selected yet.

Dagster is a replaceable control-plane adapter. It must not become the sole store of evidence, identities, approvals, or business rules.

## Planning documents

- [Staged reimplementation plan](docs/reimplementation-plan.md)
- [Post-M4 canonical migration, generation, and automated acceptance plan](docs/post-m4-canonical-migration-and-generation-plan.md)
- [Source evidence and planning baseline](docs/source-evidence.md)
- [M3 provider-free runtime](docs/m3-provider-free-runtime.md)
- [M4 Dagster projection and operations](docs/m4-dagster-operations.md)
- [Phase A source inventory evidence and review waiver](docs/phase-a-source-inventory.md)
- [Phase B provider-free core import](docs/phase-b-core-import.md)
- [Phase C fixture-only source-closure scaffold](docs/phase-c-source-closure-scaffold.md)
- [ADR 0001 — staged standalone reimplementation](docs/decisions/0001-staged-standalone-reimplementation.md)
- [ADR 0002 — deliberate polyglot boundaries](docs/decisions/0002-deliberate-polyglot-boundaries.md)
- [ADR 0003 — canonical migration and automated recipe acceptance](docs/decisions/0003-canonical-migration-and-automated-recipe-acceptance.md)
- [ADR 0004 — waive Phase A review for dry Phase B work](docs/decisions/0004-waive-phase-a-review-for-dry-phase-b-work.md)
- [ADR 0005 — bounded autonomy and canary controls](docs/decisions/0005-bounded-autonomy-and-canary-controls.md)

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

Build the workers with `npm run build`. The stable production package bin is `tidy-domain-worker`; its wire contract is documented in [`contracts/worker/v1`](contracts/worker/v1/README.md). The separate one-time `tidy-migration-worker` contract is documented in [`contracts/migration-worker/v1`](contracts/migration-worker/v1/README.md). Fixture custody is recorded in [`fixtures/parity/source-manifest.json`](fixtures/parity/source-manifest.json). Independently executed pinned-reference bytes and their clean-checkout procedure are recorded in [`fixtures/gold/manifest.json`](fixtures/gold/manifest.json), while `fixtures/expected/*.json` remains an additional source-authored partial oracle.

The Python repositories/gateway and replaceable Dagster projection are implemented in `src/tidy_orchestrator`. Phase A review was waived rather than performed. The Phase B content/semantic groundwork and Phase C source-closure tooling are fixture-only and explicitly incomplete. External review authority, live import, full summary/prompt parity, generation/provider dispatch, semantic contracts, and Sembla integration remain later gated milestones.

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

## M4 Dagster UI

```sh
uv run dg check defs
scripts/dagster-ui start
scripts/dagster-ui status
# After local acceptance only:
scripts/tailscale-dagster-ui enable
```

The UI binds only to `127.0.0.1:3030`. Its tailnet-only Android URL is
`https://ians-mac-mini-1.taild519de.ts.net:3030/`. See
[`docs/m4-dagster-operations.md`](docs/m4-dagster-operations.md) for scoped
enable/disable, security limits, tests, and reboot behavior.

## Phase A source inventory candidate

```sh
uv run tidy-source-export inventory \
  --source-root /path/to/source \
  --source-root-id source-candidate \
  --destination-root /path/to/destination \
  --destination-id destination-id \
  --policy contracts/migration/v1/tidycell-source-policy.json \
  --output .source-exports/inventory.json

uv run tidy-source-export verify \
  --input .source-exports/inventory.json

uv run tidy-source-export publish \
  --input .source-exports/snapshot.json \
  --destination-root '/Volumes/Shared Folder/tidy-dagster'

uv run tidy-source-export verify-publication \
  --directory '/Volumes/Shared Folder/tidy-dagster/source-snapshots/sha256-...'
```

`freeze` additionally requires a canonical UTC `--frozen-at` and refuses to
write when free-space or projected-utilization gates fail. NAS publication
writes `COMMITTED.json` last and copies no source content. The SQLite-backed
local repository is not authorized on SMB. See
[`contracts/migration/v1`](contracts/migration/v1/README.md) and
[`docs/phase-a-source-inventory.md`](docs/phase-a-source-inventory.md).

## Phase B fixture-only content core

```sh
uv run pytest -q \
  tests/test_migration_import.py \
  tests/test_migration_evidence.py \
  tests/test_legacy_approvals.py
npm test -- apps/domain-worker/test/migrationDigestRecord.test.ts
```

The importer keeps SQLite metadata and blob bytes under separate non-overlapping
roots. Blob publication uses exact digest directories and writes
`COMMITTED.json` last, so it works without SMB hard links. Historical approval
digests are computed only by the pinned TypeScript compatibility port. Reviewer
labels resolve exactly; ambiguity/conflict stays inactive. Approval/recipe/
model/provider evidence receives conservative, non-authoritative dispositions,
every fixture item receives an explicit semantic-pass outcome, and model bytes
are never deserialized. The only available authorization requires source system
`phase-b-fixture` and hard-caps execution at 1,000 items and 64 MiB. There is
deliberately no live import command. See
[`contracts/import/v1`](contracts/import/v1/README.md) and
[`docs/phase-b-core-import.md`](docs/phase-b-core-import.md).

## Phase C source closure and bounded summary parity

```sh
uv run pytest -q tests/test_source_code_snapshot.py tests/test_reference_summary.py
```

The original `FixtureSourceCodeAuthorization` remains as a synthetic no-copy
scaffold. Exact repository-local custody now supersedes it for the selected real
closure. Network-denied historical-source harnesses freeze default summaries and compact
contexts for four fixture sheets, and the standalone worker matches those
objects exactly. This is fixture-scoped implementing-agent evidence; complete M2/Phase C
summary-and-prompt parity and independent review are not claimed. See
[`docs/phase-c-source-closure-scaffold.md`](docs/phase-c-source-closure-scaffold.md).

## Permanent guardrails

- Content bytes and explicit contract versions define identity; paths and display names do not.
- Human decisions are attributable immutable records, not inferred from file presence or passing checks.
- Provider responses are saved before interpretation and reused on retry.
- Large artifacts live in content-addressed storage, not Dagster event logs or step payloads.
- Deterministic domain behavior remains runnable and testable without Dagster.
- The new project must not import mutable source code from the TidyCell, justice-scaffold, or Sembla worktrees.
- Research evidence, production approvals, semantic adoption, calibration design, and execution authorization remain separate authorities.

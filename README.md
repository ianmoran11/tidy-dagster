# tidy-dagster

## End-to-end spreadsheet product prototype

The replay-first product slice processes the *Prisoners in Australia* Table 30
cohort for 2021–2025 through V13 preparation, saved-response interpretation,
RecipeV01 compilation and execution, automatic table-family acceptance,
exception routing, and canonical cross-year collation:

```sh
npm run build
scripts/tidy-prototype run \
  --cohort fixtures/product-prototype/prisoners-table-30-2021-2025.json \
  --mode replay \
  --output .product-prototype/five-year-replay
```

A second provider-free cohort processes Table 21 for the same five years,
producing prisoner counts by jurisdiction, Indigenous status, sex, and age
group. It excludes the separately measured imprisonment-rate column and the
mean/median age summary rows under an explicit contract, leaving 5,265 accepted
count observations:

```sh
scripts/tidy-prototype run \
  --cohort fixtures/product-prototype/prisoners-table-21-2021-2025.json \
  --mode replay \
  --output .product-prototype/table-21-five-year-replay
```

Table 22 adds a third provider-free five-year cohort covering selected country
of birth by jurisdiction. Its 1,709 canonical observations retain 1,539
prisoner counts and 170 national imprisonment rates as separate measures and
units, including four explicitly `not_applicable` published rate cells:

```sh
scripts/tidy-prototype run \
  --cohort fixtures/product-prototype/prisoners-table-22-2021-2025.json \
  --mode replay \
  --output .product-prototype/table-22-five-year-replay
```

The live model is pinned to `openai-codex/gpt-5.6-luna` with high reasoning.
The checked live campaign made three calls for USD 0.0197296, compiled and
executed all three fresh candidates, automatically accepted 2023–2025, and
collated 729 canonical observations. The Table 30 provider-free expansion reuses
non-authoritative historical semantic-map responses for 2021–2022 and the
checked Luna responses for 2023–2025; the independent acceptance contract, not
the saved responses, accepts all five workbooks into 1,215 observations. Safe
checked evidence for the original live campaign is under
`fixtures/product-prototype/live-evidence/`; raw prompts and provider envelopes
remain restricted under the ignored `.product-prototype/` root. Replay makes
zero provider calls and explicitly treats its historical responses as
non-authoritative integration fixtures. See
[`docs/end-to-end-product-prototype-plan.md`](docs/end-to-end-product-prototype-plan.md).

### Tidy Data Asset Status

A minimal read-only page projects the three five-year cohorts as 15 sheet-assets
across five physical workbooks. It derives `Identified`, `On disk`, `Tidied`,
`Canonicalised`, `Integrated`, and automated-check status directly from the
checked cohort, run, canonical-output, and collation evidence. The page is not
an evidence authority and exposes no run, approval, or editing controls.

The deterministic committed snapshot is
[`docs/data-asset-status/index.html`](docs/data-asset-status/index.html). Refresh,
verify, or serve it in the foreground with:

```sh
scripts/tidy-data-status refresh
scripts/tidy-data-status check
scripts/tidy-data-status serve
```

Serving binds only to `http://127.0.0.1:3031/`. In another terminal, explicitly
manage the separate tailnet-only route with:

```sh
scripts/tailscale-data-status-ui enable
scripts/tailscale-data-status-ui status
scripts/tailscale-data-status-ui disable
```

The Tailnet URL is
`https://ians-mac-mini-1.taild519de.ts.net:3031/`. It has no application-level
authentication and relies on the Tailnet identity boundary.

`tidy-dagster` is a staged, standalone reimplementation of TidyCell's spreadsheet-to-recipe pipeline and its future semantic-data and microsimulation-calibration workflow.

## Current status

**M0–M4 provider-free execution and its replaceable Dagster OSS projection are implemented; M2 is not yet accepted, although default sheet summaries and compact contexts now match four frozen historical-reference sheets exactly.** A provider-free TypeScript worker parses and executes the three pinned synthetic fixtures (`simple-crosstab`, `sparse-headers`, and `multi-table`) through strict file manifests. It emits parsed workbook, normalized recipe, selector, geometry, full execution, and exact per-table CSV evidence, plus parity-locked default summary/compact-context evidence and a bounded provider-free V5 region catalogue when requested.

M3 adds a Python-owned authoritative local repository for content, derivations, custody, append-only decisions, and compare-and-swap pointers. Its hardened macOS production gateway launches the bundled TypeScript executable in private roots, enforces process/file/sandbox bounds, verifies every declared output, and publishes only a fully verified output set. The offline application runs all three fixtures twice with identical semantic derivation and output fingerprints.

M4 adds one Dagster 1.13.17 code location, a shared dynamic work-unit partition topology, immutable gate mirrors, a default sensor, persistent-instance reconstruction, and repo-owned loopback/Tailscale operations. Dagster remains an operational projection rather than evidence authority. Default summary, compact-context, and V5 role-aware catalogue outputs are supported against relocated historical-source references. The catalogue/compiler also passes 43 copied tests, and 14 copied rendered-prompt tests match the exact source-owned snapshot; broader adversarial options and restricted production-prompt custody remain incomplete.

The post-M4 Phase A boundary froze a deterministic read-only TidyCell inventory; its implementing-agent review status remains explicit. Phase B now has a narrow live CLI authorization for exactly the frozen 63-item canary—never the 44,682-item estate. The local migration and custody pilot imported all 63 item outcomes into separate disposable CAS and SQLite authority trees, produced complete content reconciliation, and ran every applicable bounded interpretation: 331 approval-row digests, four schema-valid inactive RecipeV01 revisions, and two restricted generation profiles without raw prompt/response output. The bounded TypeScript migration worker runs under macOS Seatbelt, and its Python gateway transactionally publishes inactive custody, derivation, and reproduction authority. No provider, ML, activation, training, legacy-model deserialization, full-estate import, or source-of-truth cutover occurred; unresolved approval targets and reviewer evidence remain non-authoritative. NAS migration is deferred and is not a dependency of this local pilot. Phase C separately retains the self-reviewed 140-item TidyCell/Tidybank source closure and relocated network-denied replay (117 copied source-owned tests), plus scoped summary, compact-context, region-catalogue, compiler, produced-CSV, and rendered-prompt parity evidence. These remain implementing-agent compatibility evidence rather than independent broad production parity.

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

The Python repositories/gateway and replaceable Dagster projection are implemented in `src/tidy_orchestrator`. Phase A review was waived rather than performed. The Phase B content/semantic groundwork and Phase C source-closure tooling are fixture-only and explicitly incomplete. External review authority, live import, broad adversarial summary/prompt parity, restricted prompt custody, generation/provider dispatch, semantic contracts, and Sembla integration remain later gated milestones.

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

## Migration and custody canary

The exact frozen 63-item Phase B canary now runs end to end in dedicated local
disposable blob and SQLite authority trees with no NAS dependency. See
[`docs/hobby-canary-mvp.md`](docs/hobby-canary-mvp.md) for the bounded result,
manual-inspection report, rebuild command, and deliberately deferred production
infrastructure.

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

## Phase B bounded content core and live canary

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
are never deserialized. The general-purpose authorization remains fixture-only and hard-capped at 1,000
items and 64 MiB. A separate operational CLI now authorizes only the exact
63-item frozen canary and cannot widen to the full estate. See
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

# Staged standalone reimplementation plan

- **Status:** Accepted staged baseline; M0-M4 implemented and the post-M4 planning baseline separately linked below
- **Prepared:** 2026-08-09
- **Accepted architecture decisions:** [ADR 0001](decisions/0001-staged-standalone-reimplementation.md), [ADR 0002](decisions/0002-deliberate-polyglot-boundaries.md), [ADR 0003](decisions/0003-canonical-migration-and-automated-recipe-acceptance.md)
- **Implementation authorization:** M0-M4 are implemented. The user accepted the post-M4 direction and authorized Phase A provider-free inventory work on 2026-08-09. Later copying, porting, activation, and the maximum-USD-25 pilot remain bound to the phase gates and authorization table in the post-M4 plan; semantic adoption, publication, calibration, and Sembla remain unauthorized.

## 1. Executive recommendation

Build `tidy-dagster` as a sequence of small, end-to-end replacements rather than reproducing TidyCell's directory tree or encoding the current scripts directly as Dagster assets.

The first slice should do one thing exceptionally well and without network access:

```text
exact workbook bytes
  → standalone TypeScript parser
  → exact RecipeV01 validation and execution
  → exact JSON/CSV evidence
  → external fixture harness verifies local content and derivation records
```

Once that slice is stable, the next increment invokes it through Python and projects the same immutable records into Dagster. The central design rule is:

> Dagster coordinates durable domain products, but it does not define their meaning or become their only evidence store.

Python/Dagster, the TypeScript worker, ML processes, review clients, storage, providers, and Sembla communicate through small, strict contracts. This makes infrastructure replaceable while protecting the difficult spreadsheet and recipe semantics.

## 2. Status and authority taxonomy

The following is shared planning vocabulary, not one universal status enum. Each bounded context has its own smaller lifecycle, and serialized records use only the states relevant to that context:

| Term              | Meaning                                                                                                         |
| ----------------- | --------------------------------------------------------------------------------------------------------------- |
| `proposed`        | A design exists but is not an executable authority.                                                             |
| `frozen`          | Exact bytes, versions, selection rules, and fingerprints have been recorded. Freezing does not grant authority. |
| `implemented`     | Code exists and its declared tests pass.                                                                        |
| `parity_verified` | A specified reference fixture reproduces at every declared comparison layer.                                    |
| `reviewed`        | An attributable reviewer decision binds exact subject and evidence fingerprints.                                |
| `approved`        | A recipe revision is approved for the stated extraction purpose; publication remains separate.                  |
| `adopted`         | A versioned semantic contract or corpus has passed its distinct adoption gate.                                  |
| `authorized`      | A scoped, unexpired decision permits a side effect such as a provider call or simulation run.                   |
| `stale`           | A prior decision remains auditable but no longer matches the current subject fingerprint.                       |
| `superseded`      | A later immutable revision or decision has become effective without deleting history.                           |

Current planning facts are recorded in [source-evidence.md](source-evidence.md). In particular:

- TidyCell is reference behavior, not a runtime dependency.
- The justice scaffold implements draft mechanics and an approved direction, but its artifacts remain unadopted.
- Calibration-role assignment remains deferred.
- Sembla's justice documents are proposals, not a released integration contract.
- No live provider or Sembla execution is authorized.

## 3. Outcomes and non-goals

### 3.1 Intended outcomes

1. Reproduce deterministic workbook and RecipeV01 behavior independently of TidyCell.
2. Make every cross-component input and output versioned, content-addressed, replayable, and independently verifiable.
3. Preserve provider responses before interpretation so retries never pay for known results twice.
4. Separate recipe creation, machine validation, human approval, semantic adoption, calibration design, and execution authorization.
5. Expose durable spreadsheet-derived evidence suitable for a future, separately reviewed calibration target ledger.
6. Run Python ML and external Sembla work without moving their logic into the TypeScript domain core.
7. Allow Dagster, storage, launchers, providers, model families, reviewer clients, and Sembla versions to change behind stable ports.
8. Support cohort-by-cohort cutover and rollback.

### 3.2 Initial non-goals

- Reimplementing every TidyCell research experiment.
- Rebuilding the Next.js application or Visual Recipe Editor in the first milestones.
- Treating LLM output as deterministic.
- Copying ABS workbooks, historical approvals, or paid provider responses into initial tests.
- Adopting justice V1 contracts or assigning calibration roles.
- Modifying or embedding Sembla.
- General event-history microsimulation based only on annual prisoner stock snapshots.
- Making a custom Dagster Component/YAML language before repeated stable definitions justify one.

The long-term standalone system will need a supported review client. During migration, the existing editor may act as a temporary client through a versioned review API, but it must not remain an implicit filesystem/runtime dependency.

## 4. Strategic programming rules

### 4.1 Build deep modules around difficult decisions

Expose a small number of capability-oriented interfaces:

- artifact repository;
- workbook/recipe worker;
- generation session;
- provider dispatch ledger;
- review decision store;
- semantic bundle verifier;
- target projection compiler; and
- Sembla client.

Do not expose each parser helper, Dagster step, or storage table as an architectural interface. Internal decomposition should be changeable without forcing every caller to understand it.

### 4.2 Hide volatile choices

The stable interface belongs in front of the likely change:

| Likely change                    | Stable boundary                                         | Hidden implementation                      |
| -------------------------------- | ------------------------------------------------------- | ------------------------------------------ |
| Excel library or workbook quirks | `parse_workbook@1` result contract and goldens          | ExcelJS and parser internals               |
| Provider/model/prompt changes    | provider-neutral call intent and attempt ledger         | Pi/provider SDKs and model names           |
| Object store or database         | content/record repository ports                         | local filesystem, S3, Postgres             |
| Dagster deployment/edition       | application use cases and manifest IDs                  | assets, sensors, launcher, UI              |
| ML framework/model               | versioned prediction evidence                           | XGBoost or later models                    |
| Review UI or identity provider   | review subject/decision API                             | current editor, future client, auth system |
| Justice contract edition         | exported schema/vector set and migration record         | Zod/validator implementation               |
| Sembla packaging or CLI          | capability and run-result contract                      | binary, container, remote runner           |
| Catalog path/taxonomy            | durable registry identity and alias projection          | folder names and public layout             |
| Calibration method               | role-neutral semantic evidence and frozen design ledger | optimisation/NPE implementation            |

### 4.3 Keep orchestration out of the domain

Every important use case must run from a small CLI or application function without Dagster. Domain identifiers must not contain Dagster run IDs. Domain code must not read Dagster event metadata.

Dagster may project a content digest as `DataVersion`, attach searchable metadata, and schedule missing work, but authoritative bytes, derivations, decisions, and side-effect ledgers remain reconstructable without Dagster.

### 4.4 Pull complexity downward

Callers should not have to coordinate atomic writes, canonicalization, stale-decision checks, provider ambiguity, or Sembla pin verification themselves. Those rules belong inside their owning deep module.

### 4.5 Define expected failures as data

Invalid workbooks, recipes, maps, evidence, and decisions are normal bounded outcomes. They should produce stable error codes and reviewable artifacts rather than uncontrolled exception/retry loops. Exceptions are reserved for bugs and infrastructure loss.

### 4.6 Prefer vertical slices over temporal layers

Repository packages represent durable capabilities, not `stage1`, `silver`, `new`, or a copy of today's script sequence. Each milestone should exercise a complete path through contracts, storage, and tests.

## 5. Architecture and ownership

### 5.1 Context diagram

```text
┌──────────────────────┐        ┌────────────────────────────┐
│ Sources and provider │        │ Review client / identity   │
│ responses            │        │ attributable decisions     │
└──────────┬───────────┘        └─────────────┬──────────────┘
           │                                  │ API/events
           ▼                                  ▼
     ┌─────────────────────────────────────────────────────┐
     │ Python application ports + thin Dagster adapters   │
     └───────┬──────────────────┬──────────────────┬───────┘
             │ sandboxed        │ records          │ launch contracts
             │ file manifests   ▼                  │
             │          ┌─────────────────────┐    ├──────────────┐
             │          │ Authoritative       │    ▼              ▼
             │          │ repositories        │ ┌─────────┐  ┌──────────┐
             │          │ content, derivation,│ │Python ML│  │ Sembla   │
             │          │ custody, decisions, │ └─────────┘  │ Rust CLI │
             │          │ dispatch and budget │              └──────────┘
             │          └─────────────────────┘
             ▼
     ┌─────────────────────┐
     │ TypeScript worker   │
     │ pure file transform │
     └─────────────────────┘
```

### 5.2 Ownership table

| Capability                                                           | Runtime owner                                      | Must not know about                                    |
| -------------------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------ |
| Workbook bytes to sparse semantic workbook                           | TypeScript worker                                  | Dagster, providers, approval state, Sembla             |
| R1C1/range algebra, RecipeV01, selectors, geometry, execution/export | TypeScript worker                                  | storage vendor, Dagster run state, reviewer UI         |
| Bounded sheet summaries and review evidence                          | TypeScript worker                                  | provider credentials, spend authority                  |
| Generation-response interpretation                                   | TypeScript worker                                  | authorization, budget and provider SDK/network         |
| Provider dispatch, credentials, rate and cost policy                 | Python gateway                                     | workbook bytes and recipe geometry                     |
| ML training/inference/evaluation                                     | Python ML package/process                          | approval authority and recipe compilation              |
| Content, derivation, custody, decision and dispatch records          | Python-owned ports with language-neutral contracts | Dagster asset graph                                    |
| Asset graph, scheduling, partitions, sensors, retries, concurrency   | Python/Dagster adapter                             | canonical business state                               |
| Pinned semantic-export validation/processing                         | TypeScript worker under released schemas/vectors   | contract authority, calibration role and runtime state |
| Target-ledger projection                                             | Python application service, initially disabled     | semantic mutation and calibration algorithm            |
| Simulation execution                                                 | external Sembla CLI, pinned before real use        | TidyCell or Dagster internals                          |

### 5.3 Dependency rule

```text
apps/orchestrator (Dagster)
        ↓
Python application ports ───────────────┐
        ↓                              │
Python adapters                 language-neutral contracts
                                       ↑
                       TypeScript worker / ML / Sembla CLI
```

Adapters depend inward. Contract packages contain wire formats and vectors, not application behavior. No package may import from the three source worktrees.

## 6. Proposed repository structure

```text
tidy-dagster/
  README.md
  docs/
    reimplementation-plan.md
    source-evidence.md
    decisions/
    runbooks/
  contracts/
    artifact/v1/
    worker/v1/
    approval/v1/
    provider/v1/
    semantic/                 # pinned exported versions, not source imports
    sembla/v1/
    vectors/
  apps/
    domain-worker/            # TypeScript executable
      src/
        protocol/
        workbook/
        recipe/
        generation/
        semantic/
      test/
    orchestrator/             # thin Python/Dagster application
      src/tidy_orchestrator/
        assets/
        checks/
        automation/
        resources/
        definitions.py
      tests/
  packages/python/
    tidy_artifacts/            # authoritative content/record ports and adapters
    tidy_gateways/             # worker, provider, review and Sembla adapters
    tidy_ml/
    tidy_catalog/
  fixtures/
    parity/
    contracts/
    fake-provider/
    fake-sembla/
  deploy/
  scripts/
```

Start with one Dagster code location. Split only when incompatible dependencies, independent ownership/deploy cadence, or fault isolation provides concrete benefit. A language boundary alone is not a Dagster code-location boundary.

This tree is an ownership map, not an instruction to create every package on day one. Begin with the few directories needed by the first slice and split a package only after a real cohesion, dependency or deployment boundary appears. Avoid a monorepo framework until ordinary Python and Node workspaces become painful. Pin tools and dependencies, but do not make tool selection part of the domain contract.

## 7. Identity, artifacts, and provenance

### 7.1 Separate three concepts

A single mutable "manifest" tends to conflate deterministic identity with storage and time. Use three related records instead.

#### Content descriptor

Identifies exact bytes and remains stable when the bytes move:

```text
kind
schemaVersion
mediaType
byteLength
contentDigest
canonicalizationAlgorithm (when applicable)
```

#### Derivation record

Explains deterministic production:

```text
operation + contract version
ordered input content digests
configuration/policy digest
producer source/image/tool digests
output content digests
```

Its identity excludes timestamps, storage locations, Dagster IDs, and display names.

#### Custody receipt

Records where and when bytes were observed or stored:

```text
contentDigest
storage URI
observed/stored time
actor/workload identity
source locator and retrieval metadata
retention/security classification
```

A content object may have many custody receipts without changing identity.

### 7.2 Canonicalization

- Raw workbooks use SHA-256 over exact bytes.
- Existing RecipeV01 approval fingerprints must preserve their legacy canonical digest during compatibility migration.
- New owned JSON contracts use RFC 8785/JCS plus an explicit domain separator only after TypeScript and Python agree on published numeric, Unicode, and ordering vectors.
- Justice draft identities keep the old draft algorithm. V1 identities cannot silently replace them; migration records preserve both.
- Semantically ordered arrays remain ordered. Only arrays explicitly declared set-like may be normalized, and the contract must name that rule.

Suggested owned identity form:

```text
SHA-256("tidy-dagster:" + artifact-kind + ":" + schema-version + NUL + canonical-bytes)
```

The separator, bytes, and encoding must be part of the contract and test vectors.

### 7.3 Core identities

| Object               | Identity inputs                                                                            |
| -------------------- | ------------------------------------------------------------------------------------------ |
| Workbook             | Exact byte SHA-256                                                                         |
| Sheet occurrence     | Workbook digest + exact sheet name                                                         |
| Processing profile   | Parser/summary/normalization contract and option fingerprints                              |
| Work unit            | Sheet occurrence + requested use case + processing profile                                 |
| Parsed-sheet content | Canonical content digest; work unit/profile inputs live in its derivation record           |
| Generation attempt   | Prompt-input digest + provider/model/effort/prompt policy + prior evidence + ordinal       |
| Recipe revision      | Version-specific canonical recipe digest; original/current digests kept separately         |
| Execution            | Recipe digest + parsed-sheet digest + executor/options contract                            |
| Review subject       | Work unit + exact recipe and evidence-packet digests                                       |
| Approval decision    | Review subject + actor + decision/policy record; effective pointer stored separately       |
| Semantic cell        | Adopted semantic contract identity plus table/cell provenance and value descriptor         |
| Calibration design   | Semantic-bundle hash + dependency/role ledger + projection policy                          |
| Sembla run           | Executable/image + model + plan + target ledger + seed + relevant environment fingerprints |

Do not truncate digests in authoritative keys. Friendly short IDs may be indexed aliases with collision detection.

### 7.4 Storage rules

- Blobs are immutable.
- Writes are stage → hash/verify → idempotent insert → transactional derivation record → optional compare-and-swap pointer.
- Partial files never become visible through authoritative records.
- Mutable pointers such as "effective approved recipe" are small projections protected by compare-and-swap and recoverable from immutable decisions.
- Large data never travels through Dagster event metadata or Python pickles.
- Dagster metadata contains only safe indexed summaries such as kind, digest, row count, status, tool version, and artifact link.

## 8. Explicit state models

Keep related state machines separate so one runtime never jointly owns an invariant-heavy lifecycle with another and one transition cannot accidentally grant another authority.

### 8.1 Provider dispatch attempt — Python-owned

```text
planned
  → authorization_required
  → reserved
  → dispatched
  → response_recorded
```

Terminal/exception states:

```text
blocked | budget_exhausted | failed_known | dispatch_ambiguous | cancelled
```

Replay may begin from an already recorded response without a dispatch authorization. A recorded response is reused. `dispatch_ambiguous` never automatically retries.

### 8.2 Generation interpretation session — TypeScript-owned pure transition

```text
response_recorded
  → interpreted
  → candidate_produced | bounded_correction_requested | terminal_failure
```

The only bridge from dispatch to interpretation is the versioned immutable response record. TypeScript never changes budget or dispatch state; Python never interprets recipe geometry or semantic maps.

### 8.3 Recipe revision

```text
created → schema_valid → executed → reviewable
           └──────────→ invalid
                execution_failed
```

A repair creates a new immutable revision linked to its parent. It does not overwrite the failed candidate.

### 8.4 Review and approval

Review decisions are append-only records. A deterministic projection resolves whether a decision is active, rejected, stale, superseded, or conflicting. Changing recipe bytes makes the old approval stale; it does not mutate or delete the original decision.

Recipe approval is separate from publication. Recipe approval is also separate from semantic adjudication.

### 8.5 Semantic lifecycle

```text
provisional bundle
  → machine_validated
  → frozen gold subject
  → independent reviews
  → adjudicated
  → externally adopted
```

Missing evidence or disagreement blocks adoption. Machine validation alone never advances to adoption.

### 8.6 Calibration and simulation

```text
adopted role-neutral evidence
  → dependency analysis
  → externally approved frozen role/design ledger
  → Sembla projection
  → separately authorized run
  → observations
  → fitted and held-out scoring
```

The design ledger, not the semantic cell, owns fitted/held-out/diagnostic/redundant/unsupported roles.

## 9. Failure taxonomy and retry ownership

| Category                  | Examples                                                      | Owner and response                                       |
| ------------------------- | ------------------------------------------------------------- | -------------------------------------------------------- |
| `INPUT_INVALID`           | corrupt XLSX, invalid RecipeV01, range cap                    | Deterministic terminal result; no retry                  |
| `INTEGRITY_VIOLATION`     | digest mismatch, undeclared file, canonicalization mismatch   | Quarantine and alert; no retry                           |
| `POLICY_BLOCKED`          | missing authorization, unadopted contract, role ledger absent | Wait for a new external record; no polling run held open |
| `BUDGET_EXHAUSTED`        | call/token/cost limit                                         | Preserve accounting and stop                             |
| `PROVIDER_TRANSIENT`      | classified pre-response 429/5xx                               | Provider gateway owns bounded retry                      |
| `PROVIDER_AMBIGUOUS`      | timeout after possible dispatch                               | Reconcile/manual decision; never blind retry             |
| `INFRA_TRANSIENT`         | worker crash, object-store outage                             | Launcher/Dagster run recovery using same idempotency key |
| `TOOL_INCOMPATIBLE`       | unsupported worker/Sembla version                             | Fail closed until pin/config changes                     |
| `NONDETERMINISTIC_OUTPUT` | same derivation produces different digest                     | Release/cutover blocker; retain both results             |
| `DECISION_STALE`          | decision fingerprints no longer match                         | Require a new decision                                   |
| `HUMAN_REJECTED`          | attributed rejection                                          | Terminal for that revision                               |
| `INVARIANT_BROKEN`        | impossible state or duplicate authoritative identity          | Bug/security event; stop affected cohort                 |

Exactly one layer owns each retry budget. Provider SDK, activity, Dagster asset, and run retries must not multiply calls.

## 10. TypeScript worker boundary

### 10.1 Transport

Begin with a Dagster-agnostic executable using a strict request manifest and response manifest. A JSONL/stdin mode may be used for control envelopes, while substantive inputs and outputs are files referenced by relative paths and digests.

- stdout is machine protocol only and both stdout and stderr are capped;
- diagnostics go to stderr;
- input files are read-only and output is confined to a dedicated directory;
- absolute/escaping paths, unknown versions/fields, undeclared output, digest drift, and output-limit violations fail closed;
- the worker has no provider credentials and should run without network access; and
- the Python launcher owns cancellation and wall-clock enforcement: terminate the complete process/container tree, allow a bounded grace period, force-kill, clean temporary files, and classify signals/exit codes deterministically.

The request's `timeoutMs` is a declared limit, not self-enforcement by the worker. Decide during M3 whether Dagster Pipes wraps this domain protocol; the file-manifest contract remains authoritative either way.

Example request:

```json
{
  "protocolVersion": "tidy.worker/v1",
  "requestId": "019...",
  "operation": "execute-recipe-v01",
  "inputs": [
    {
      "name": "workbook",
      "relativePath": "inputs/workbook.xlsx",
      "contentDigest": "sha256:..."
    },
    {
      "name": "recipe",
      "relativePath": "inputs/recipe.json",
      "contentDigest": "sha256:..."
    }
  ],
  "parameters": {},
  "limits": { "timeoutMs": 30000, "maxOutputBytes": 10000000 }
}
```

The result identifies output files and digests plus deterministic warnings and a stable error object. Timings may be reported as observational metadata but must not participate in deterministic derivation identity.

### 10.2 Stable operations

- `health`
- `capabilities`
- `profile-workbook` — parse a workbook and emit the requested bounded sheet profiles as one coherent result;
- `execute-recipe-v01` — validate, resolve selectors, execute, and export all requested parity evidence in one operation;
- later, `prepare-generation-intent`, `interpret-generation-response`, `build-review-evidence`, and version-specific `validate-semantic-bundle` operations.

Parsing, recipe validation, selector resolution and CSV formatting remain independently testable internal modules, but they are not separate public wire operations unless a demonstrated external use case later needs one. This prevents callers from coordinating a shallow copy of the worker's internal pipeline.

### 10.3 Parity-sensitive behavior

Freeze and test independently:

- formula and cached-result handling;
- dates, formatted text, comments, hyperlinks, styles, styled blanks and merges;
- logical sheet bounds and historical phantom dimensions;
- merge-child blanking and range limits;
- R1C1 normalization and numeric ordering;
- RecipeV01 strictness, compatibility preprocessing and diagnostic-key stripping;
- selector unions, predicates and warnings;
- N/W/NNW/WNW geometry, fill, overrides and tie-breaking;
- option precedence;
- row, warning, trace, source-column and non-table-cell ordering; and
- exact CSV quoting and line endings.

## 11. Dagster design

### 11.1 What is an asset

An asset represents a durable product or externally observed decision, not every function call.

Proposed graph:

```text
source_catalog_snapshot
  → workbook_content
  → workbook_profile
  → sheet_work_unit
      ├→ sheet_summary
      └→ ml_hint_set
             ↓
      generation_evidence_index
             ↓
      recipe_revision_index
             ↓
      execution_evidence_index
             ↓
      review_packet

external_recipe_decision → effective_approved_recipe

effective_approved_recipe + semantic_mapping
  → provisional_semantic_bundle
  → semantic_validation_evidence

external_semantic_adoption → adopted_semantic_bundle          [future]
external_calibration_design + adopted_semantic_bundle
  → target_ledger → Sembla projection → simulation evidence   [future]
```

Cells, rows, warnings, generation attempts and recipe revisions are authoritative records inside durable bundles; they are not individual Dagster assets. Each `*_index` materialization points to an immutable, complete manifest of known records for that work unit. Dagster's latest materialization is an operational projection, not the revision ledger or the effective approval.

### 11.2 Partitions

The independently retryable/auditable unit is a stable work-unit ID derived from immutable inputs and processing profile. Use full stable keys or registry-issued IDs, not mutable names/statuses or unguarded digest prefixes.

- Source-catalog snapshots and workbook discovery are initially unpartitioned/observable inputs in Dagster; their complete records live in the authoritative repository.
- All sheet-level work-unit products share one explicitly named `DynamicPartitionsDefinition`. A work-unit manifest binds its workbook, sheet and processing profile, so no implicit cross-partition mapping is required.
- A discovery sensor returns dynamic-partition additions and corresponding run requests in one `SensorResult`; tests prove add-plus-launch and duplicate-tick behavior against the pinned Dagster version.
- If a separate workbook partition topology is later justified, its partition mapping must be named, tested and reviewed before use.
- Generation attempts and recipe revisions remain immutable records under a work unit rather than additional partition dimensions.
- Time partitions are used only when operational time is genuinely part of the obligation, not because a publication has a year label.
- Default backfills use one run per work unit for fault isolation. Batched/range backfills arrive only after set-based idempotent writing is proven.
- Before M4, choose and load-test a bounded operational projection: for example cohort-scoped asset keys/code locations or a bounded active-key set with explicit tombstones. The authoritative registry retains all history, while Dagster reconstruction intentionally restores the declared active cohorts plus external observations for older evidence. Do not allow one asset's active dynamic keys to grow toward the documented 100,000-partition UI risk without a tested sharding/retention decision.

### 11.3 Checks and gates

Asset checks mirror machine-verifiable properties:

- content hash;
- schema validity;
- provenance closure;
- deterministic reproduction;
- decision signature/authentication, scope and freshness;
- leakage and target-role disjointness;
- projection completeness; and
- publication package integrity.

A check must not wait for or fabricate human approval. Critical domain validation also produces an explicit immutable gate-result artifact so the architecture does not depend on preview partitioned-check behavior.

### 11.4 Resources and I/O

Resources expose narrow external capabilities: artifact repository, metadata database, review service, provider gateway, process/container launcher, model registry, and Sembla client. They contain configuration and clients, not business state machines.

Use explicit artifact references for polyglot/large data. Use an I/O manager only where it materially simplifies Python-native values; never use Python pickle as a cross-language contract.

### 11.5 Sensors and automation

- Explicit sensors are the M4 default for external workbook records and review/authorization decisions.
- Every sensor uses a cursor and stable run key.
- Sensor evaluation is fast and side-effect-light.
- Defer declarative automation until the active partition projection is bounded and load-tested; any adoption must name the exact condition, daemon configuration and maximum evaluation scope.
- Schedules are for real clock-driven obligations.
- Human review does not hold a run or worker open; a decision event starts a later run.

### 11.6 Retries and concurrency

- Infrastructure run recovery is distinct from deterministic step failure.
- Dagster cross-run pools provide coarse, statically configured admission control for TypeScript workers, ML/GPU work, database writers, notifications, Sembla and broad provider classes.
- The provider gateway—not a Dagster pool—owns dynamic account/model rate limits, token/cost budgets and dispatch uniqueness.
- Deployment and per-run caps protect CPU/RAM and backfills.
- Concurrency never substitutes for a uniqueness claim, transaction, rate ledger or budget reservation.

### 11.7 Replaceability and operational integration tests

Periodically delete a disposable Dagster instance and reconstruct the declared active-cohort projection plus historical external observations from authoritative records. If authoritative state cannot be recovered, the boundary has leaked.

For the initial bounded M4 vertical slice, run a persistent-instance reconstruction suite plus a real daemon/executor test covering duplicate sensor evaluation, dynamic partition add-plus-launch, revision-bound run keys, control-plane restart, and run deduplication. `execute_in_process` remains a fast smoke test, not operational proof. Before any production-scale orchestration claim, add separate deterministic drills for in-flight run recovery, queued backfills, and concurrency-pool saturation; those are explicitly outside the accepted three-fixture M4 slice.

## 12. Review, approval, provider and ML boundaries

### 12.1 Human recipe flow

1. Store immutable recipe and execution/review evidence.
2. Publish a review subject through a versioned API.
3. End the Dagster run successfully.
4. A review client submits an attributable decision with exact subject, packet, original recipe and current recipe fingerprints, policy version, time, reason/comment and an idempotency key scoped to the reviewer action.
5. A decision sensor verifies and projects it.
6. A compare-and-swap operation updates the effective approval pointer.
7. An edit is a new recipe revision with parent linkage; it requires edit provenance.
8. Approval may emit a governed active-learning event, but never automatically publishes, retrains, or starts provider work.

Cryptographic signatures are an implementation choice to be made with the identity/threat model. The stable requirement is authenticated attribution and tamper-evident binding to exact bytes.

### 12.2 Provider safety

A live call requires an external authorization record binding:

- work unit and allowed operation;
- provider/model/reasoning settings;
- maximum calls, tokens and cost;
- expiry;
- pricing-policy version; and
- authorizing identity/provenance.

Before dispatch, transactionally reserve budget and claim a unique attempt. Record the raw response before parsing. If dispatch outcome is ambiguous, preserve that state and reconcile rather than retrying.

Provider adapters are default-off. Stub and replay providers support all initial and CI work. Implementing a live adapter does not authorize its use.

### 12.3 Generation strategies

Generation volatility belongs behind a strategy contract:

```text
prepare deterministic evidence
  → provider-neutral call intent
  → recorded raw response
  → deterministic interpretation
  → candidate revision / bounded correction / terminal failure
```

Direct RecipeV01, semantic-map compilation, ML-assisted prompting, and fallback behavior remain distinct named strategies with separate versions and evidence. Shared execution and review paths must not erase strategy identity.

### 12.4 ML

Python ML emits neutral, versioned prediction evidence containing training-corpus, exclusion, feature, model, image and configuration fingerprints. The TypeScript worker consumes it as compact fallible hints.

Training requires approved-only policy, frozen target-workbook exclusion by actual workbook SHA-256, and explicit split evidence. ML output never becomes recipe or semantic truth by itself.

## 13. Semantic evidence and calibration boundary

### 13.1 Preserve current authority

The approved justice V1 direction remains:

- 2019–2025 prisoner stock counts at midnight on 30 June;
- reporting jurisdiction, sex and legal status;
- release-pinned sources and methodology;
- distinct total/missing/not-applicable/observed-zero/structural-zero states;
- layered table/cell provenance;
- RFC 8785/JCS migration before adoption; and
- frozen 50–100-cell, two-reviewer, fully adjudicated semantic gold.

TidyCell remains the named owner of V1 extraction-facing contracts until a separately reviewed ownership/cutover decision says otherwise. `tidy-dagster` may verify and consume pinned exports during migration; it must not silently claim ownership by copying draft files.

### 13.2 Semantic port

Input is a closed, self-contained bundle and manifest. Validation rejects unknown versions, fields, IDs, schemes, members, rules and dangling references. Table provenance owns workbook hash, sheet, recipe digest and table range; each cell adds its exact source coordinate.

The draft six-artifact scaffold may be used only for provider-free provisional conformance tests. Real evidence waits for a reviewed schema that can represent it honestly.

### 13.3 Adoption gate

Adoption remains blocked until all are present:

1. released schemas and exact JCS vectors;
2. explicit draft-to-V1 migration records preserving both identities;
3. exact ABS authorities and publication-local-member policy;
4. real provenance support;
5. a frozen representative semantic-gold set selected before tuning;
6. two independent reviews;
7. adjudication of every disagreement;
8. exact deterministic reproduction; and
9. a separate attributable adoption decision.

Dagster checks can verify these records but cannot create the decision.

### 13.4 Dependency and target ledger

Semantic evidence remains role-neutral. A later immutable calibration-design ledger records:

- stable observation keys;
- duplicate/repeated-vintage relationships;
- totals/components and derived-measure dependencies;
- exactly one of `fitted`, `heldout`, `diagnostic`, `redundant`, `unsupported` plus reason;
- frozen vector order;
- model/plan/projection fingerprints; and
- complete source-cell provenance.

No role is assigned until that track is separately authorized and frozen. Start with independent counts; do not double weight totals and components or dependent percentages/rates.

### 13.5 Sembla anti-corruption layer

Develop first against a deterministic fake CLI. A real adapter requires a released CLI/output contract, selected binary or image, checksum/signature, license review, capability probe and explicit run authorization.

The initial projection is count-only with one to four grouped keys. The current Sembla executable contract only understands `fitted` and `heldout`; other roles stay in the audit ledger unless Sembla adopts a new versioned contract. Silent coercion is forbidden.

The proposed `PrisonerSlot` stock-state MVP remains a later Sembla track. Annual stock evidence cannot identify detailed court, admission, release or sentencing hazards, and it must not trigger premature runtime event-stream features.

## 14. Validation and parity strategy

### 14.1 Comparison layers

Parity is layered. A matching final CSV does not waive a parser or warning mismatch.

| Layer                 | Required evidence                                                      |
| --------------------- | ---------------------------------------------------------------------- |
| Source custody        | exact bytes, source commit/path, license and SHA-256                   |
| Parsed workbook       | exact canonical sparse representation                                  |
| Summary               | exact budgets, ordering, detector versions and bytes                   |
| Recipe validation     | normalized recipe or exact stable error code                           |
| Selector resolution   | exact addresses and warning order                                      |
| Relationship geometry | exact attachments and tie-breaking                                     |
| Execution             | rows, values, options, trace, provenance, non-table cells and warnings |
| Export                | byte-identical CSV                                                     |
| Derivation            | identical input/algorithm/output fingerprints on replay                |
| Dagster projection    | correct assets, dependencies, versions, sensor cursor/run keys         |

The initial fixture sequence is:

1. `simple-crosstab`;
2. `sparse-headers`;
3. `multi-table`.

Add small JSON-only cases for geometry and validation edges instead of creating many workbooks.

### 14.2 Test layers

- TypeScript unit/property tests for domain behavior.
- Python unit tests for ports, records, budgeting and projections.
- Cross-language canonicalization and protocol vectors.
- Golden parity tests for every deterministic layer.
- Artifact-store crash, tamper and compare-and-swap tests.
- Worker sandbox/path/output-limit tests.
- Sensor cursor/run-key and definition-loading tests.
- One provider-free `execute_in_process` Dagster smoke slice.
- A persistent-instance Dagster integration suite covering daemon sensor ticks, dynamic add-plus-launch, run-key deduplication, selected launcher/executor failure, backfill queueing, pool saturation and reconstruction.
- Fake-provider ambiguity, rate and budget tests.
- Review attribution, stale decision, edit provenance and race tests.
- Leakage/holdout tests for ML.
- Semantic positive and one-reason-negative fixtures.
- Fake-Sembla pin, capability, timeout, grouping, run-twice and non-interference tests.
- CI scan forbidding runtime/path imports from source worktrees.

### 14.3 Required failure drills

- Kill the worker after output is written but before publication: rerun must publish once.
- Kill provider orchestration after a response is saved: rerun must interpret the saved response without a call.
- Simulate timeout after provider dispatch: state must become ambiguous and not retry.
- Run two approvals concurrently: both decisions remain; only one compare-and-swap pointer wins.
- Modify one stored byte: verification fails and quarantines it.
- Delete a disposable Dagster database: operational lineage reconstructs from authoritative stores.
- Re-run the same semantic expansion and fake simulation: exact output fingerprints match.

## 15. Security and operations

- Treat XLSX/ZIP, JSON, provider responses and CLI output as untrusted.
- Enforce compressed/uncompressed size, row, column, merge, range, memory, output and time limits.
- Never execute spreadsheet macros or external links.
- Launch subprocesses with argument arrays, fixed locale/timezone, read-only inputs, isolated outputs, no inherited secrets, and no network unless the operation explicitly requires it.
- Keep provider credentials only in the provider gateway.
- Classify artifact sensitivity; avoid logging cells, prompts, responses, reviewer data or secrets in Dagster.
- Pin Node, Python, Dagster, ExcelJS, canonicalization libraries, model images and Sembla artifacts.
- Produce lockfiles, SBOMs, dependency/license scans and release provenance.
- Use backup/restore appropriate to the selected production instance/metadata database, plus object-store immutability/versioning; if Postgres is selected, test point-in-time recovery.
- Alert on integrity mismatch, nondeterminism, ambiguous dispatch, stale decisions, budget thresholds, queue saturation, sensor lag and failed reconciliation.
- Provide kill switches for provider dispatch, publication and Sembla execution.
- Maintain runbooks for pointer rollback, quarantine, secret exposure, canonicalization mismatch and reconstruction.

The implementation should begin locally and provider-free. Production choices—Dagster OSS versus Dagster+, object storage, launcher, authentication, signing and retention—are milestone decisions informed by a threat model and restore test.

## 16. Phased roadmap

### M0 — Foundation gate: ownership and one frozen fixture

M0 is a governance prerequisite, not an executable vertical slice.

**Deliverables**

- Initialize Git only after explicit implementation authorization.
- Choose pinned Python/Node toolchains and licenses.
- Add repository-boundary CI.
- Review and copy only the `simple-crosstab` workbook/recipe/expected triplet.
- Create a source manifest with exact commit, paths, licenses and digests.
- Define the first parity report format.

**Done when**

- a clean install is reproducible;
- every copied byte has reviewed provenance;
- no absolute dependency on the source worktrees exists; and
- no credential or live network configuration is present.

**Stop if** fixture rights, source commit or expected artifacts are unclear.

### M1 — First executable slice: `simple-crosstab`

Create only the contracts and pure transformation behavior needed by this slice:

- minimal content, derivation and custody record schemas;
- worker request/result/error contract and vectors;
- a fixture harness outside the worker that verifies and retains local output records without claiming authoritative publication;
- TypeScript protocol shell;
- workbook parsing and deep `execute-recipe-v01` operation; and
- exact parsed, validation, execution and CSV evidence.

The TypeScript worker remains a pure file transform. The fixture harness may copy/hash expected outputs for tests, but the first authoritative repository adapter is Python-owned and begins in M3.

**Done when** the fixture runs twice without Dagster or network access, every declared intermediate/final byte matches, unknown protocol versions fail closed, and relocating fixture output bytes does not change content identity.

### M2 — Extend deterministic parity

**Acceptance status:** Not yet accepted; summary detector/renderer closure remains a separate follow-up.

Introduce the `sparse-headers` triplet with focused geometry negatives only after M1 is accepted. Introduce `multi-table` only after sparse parity is stable. Complete summary prioritization/truncation, merges/styles, all relationship directions, option precedence, warning/trace ordering and exact CSV.

**Done when** every declared intermediate and final artifact for all three fixtures matches exactly twice in succession without Dagster or network access.

**Stop if** any parser, geometry, warning or CSV mismatch lacks an explicit reviewed compatibility decision.

### M3 — Add the Python gateway and authoritative repositories

**Implementation status:** Implemented and reviewed provider-free on the initial macOS target. Production requires a deny-default Seatbelt profile that confines writes, denies process forks and network access, and is tested separately from the explicit insecure failure-drill mode. No non-macOS production sandbox is selected.

**Deliverables**

- sandboxed worker invocation with process-tree termination;
- verified staging/collection;
- immutable publication;
- full derivation and custody records;
- append-only decision primitives;
- compare-and-swap pointers; and
- crash/replay tests.

**Done when** the full offline use case runs through Python with identical fingerprints and survives termination, tamper and concurrency fault injection.

### M4 — Add the minimal Dagster vertical slice

**Implementation status:** Implemented provider-free with Dagster OSS 1.13.17. The real-daemon test proves sensor add-plus-launch, dispatch-bound revision/catalog tags, stable revision-aware run keys, cursor persistence, successful work-unit runs, and restart deduplication. A separate persistent-instance test proves all-work-unit and immutable-gate reconstruction from the external authoritative repository after Dagster metadata deletion. Queue/pool saturation, large backfills, daemon-run crash recovery, and HA remain explicitly unaccepted operational gaps rather than simulated claims.

**Deliverables**

- one code location and an explicit OSS/Dagster+ decision matrix for the pinned version;
- unpartitioned/observable discovery plus one shared dynamic work-unit partition definition;
- assets that project immutable indexes rather than revision truth;
- checks mirroring immutable gate records;
- explicit sensor cursor/run-key and atomic add-plus-launch behavior;
- a tested bounded active-cohort partition policy; and
- a persistent local instance using the selected instance store, daemon and executor/launcher.

**Done when** the offline fixture is visible in Dagster, the persistent integration suite covers duplicate ticks, control-plane restart, authoritative reconstruction, and deletion of Dagster metadata without destroying or redefining evidence. Deterministic queue/pool saturation, large backfills, and in-flight daemon-run crash recovery remain named operational gaps for a later acceptance slice.

### Horizon roadmap — re-plan before each gate

M5–M10 describe desired gated outcomes, not approved package layouts or settled external contracts. Before starting each milestone, revise its PRD against the then-current provider, review, semantic, calibration or Sembla authority and retain only interfaces justified by that evidence.

For canonical TidyCell evidence migration, V13 ML-assisted Pi generation, workbook-specific automated acceptance, and the hard-capped first provider pilot, the accepted planning baseline is [`post-m4-canonical-migration-and-generation-plan.md`](post-m4-canonical-migration-and-generation-plan.md), governed by [ADR 0003](decisions/0003-canonical-migration-and-automated-recipe-acceptance.md). It refines the package assumptions for the still-unimplemented M5-M8 and historical-import portions of M10 without changing accepted M0-M4 behavior or M7-M8 semantic authority. Semantic adoption, calibration, public publication, and Sembla remain outside that plan.

### M5 — Add replay-only generation and review decisions

**Deliverables**

- named generation-strategy contract;
- stub/replay provider;
- bounded review/repair transition records;
- review packet API;
- external decision verification;
- stale/superseded approval projection;
- temporary adapter for the existing editor if chosen.

**Done when** scripted generation/review/repair scenarios terminate deterministically, no network is reachable, and no approval is inferred.

### M6A — Add live-provider readiness, still default-off

**Deliverables**

- authorization and budget contracts;
- reservation/dispatch/settlement ledger;
- ambiguity reconciliation and kill switch; and
- provider-gateway distributed rate/budget controls plus coarse Dagster admission pools.

**Done when** fake-provider failures prove no duplicate dispatch, ambiguous calls do not retry and costs reconcile. A separate authorization is required before any live call.

### M6B — Add neutral ML hints independently

**Deliverables**

- neutral ML prediction contract and frozen hints;
- training/model/configuration lineage; and
- approved-only/leakage exclusion checks.

**Done when** TypeScript consumes frozen hints without treating them as authority and all target-workbook/holdout exclusions are reproducible. M6B neither depends on nor authorizes M6A.

### M7 — Add provisional semantic validation

**Deliverables**

- hash-pinned exported draft schemas/vectors;
- closed-graph validator boundary;
- provisional semantic assets/checks;
- synthetic positive and one-reason-negative tests;
- explicit adoption-gate verifier interface.

**Done when** draft fixtures behave exactly and all outputs remain visibly provisional. No real source is mislabeled synthetic.

### M8 — Prepare semantic adoption and target design

**Deliverables**

- JCS migration verifier;
- real-provenance contract support after review;
- semantic-gold selection/review/adjudication records;
- exact reproduction report;
- role-neutral dependency-analysis output;
- disabled target-ledger compiler requiring an external frozen design.

**Done when** the system can verify—but not invent—every adoption prerequisite. Actual adoption and role assignment need separate decisions.

### M9 — Add fake then pinned Sembla integration

**Deliverables**

- fake CLI and fixtures;
- capability/pin/checksum contract;
- count-only grouped projection validation;
- deterministic run evidence and scoring ingestion;
- disabled real adapter configuration.

**Done when** fake runs recover known counts, repeat exactly, and demonstrate observation non-interference. Real Sembla remains blocked until its contract, artifact and authorization are selected.

### M10 — Shadow migration and cohort cutover

**Deliverables**

- durable publication/subject registry;
- legacy alias and approval importer;
- discrepancy reports by deterministic layer;
- dual-read/shadow-run mode;
- backup/reconstruction and rollback rehearsal;
- cohort authority pointers;
- an attributable `CutoverAuthorization` record; and
- a post-transaction `CutoverCompletion` record.

**Done when** `CutoverAuthorization` binds the exact cohort-manifest digest, expected old and new authority-pointer values, parity/discrepancy report digests, approved-exception policy/version and fingerprints, fixed shadow duration, restore RTO/RPO evidence digests, sensor/dispatch drain evidence, rollback triggers/owner and final go/no-go decision. After compare-and-swap, `CutoverCompletion` binds the authorization digest, transaction/CAS outcome, actual resulting pointer and observation-window policy.

Expand only after the completion record's fixed observation window passes. Avoid dual-authoring approvals.

## 17. PRD-sized work breakdown

1. Repository bootstrap, licenses, boundary checks and `simple-crosstab` baseline manifest.
2. Minimum content/derivation/custody and worker contracts for the first executable slice.
3. TypeScript protocol shell, sandbox rules and `simple-crosstab` workbook/RecipeV01 vertical slice.
4. Sparse, merge and relationship parity extension.
5. Multi-table, summary, warning/trace and CSV parity completion.
6. Authoritative artifact repository, derivation records and compare-and-swap pointers.
7. Python worker gateway and crash-safe replay.
8. Minimal offline Dagster definitions, partitions, checks and sensor.
9. Stub/replay generation strategies and bounded transition records.
10. Review subject/decision API and approval projection.
11. Provider authorization, budget and ambiguity ledger with fake adapter.
12. Neutral ML hint contract and leakage-clean fixture integration.
13. Provisional semantic export/validation boundary.
14. Semantic adoption verification and gold-review workflow.
15. Disabled calibration-design/target-ledger compiler.
16. Fake and later pinned Sembla adapter.
17. Catalog/identity compatibility and historical import tooling.
18. Deployment hardening, restore/reconstruction and cohort cutover.

Each PRD must state:

- exact scope and non-goals;
- accepted contracts and source fingerprints;
- side effects that remain disabled;
- deterministic acceptance artifacts;
- failure and rollback behavior;
- commands/tests and evidence expected; and
- decisions that require escalation rather than implementation guesses.

## 18. Migration, cutover and rollback

1. Freeze the exact reference source and fixture set; never read mutable source worktrees at runtime.
2. Prove synthetic parity before historical shadow comparisons.
3. Replay saved provider responses rather than regenerating them.
4. Import content, derivations and attributable approvals separately. For the canonical TidyCell migration governed by ADR 0003, approval snapshots use the refined `human_approved`, `legacy_approved_unattributed`, `incomplete_evidence`, and resolved/ambiguous/unresolved/conflict vocabulary; do not collapse them into the older generic `legacy_unverified` label.
5. Reconcile durable publication and sheet identities before changing an authority pointer.
6. Shadow-read/write first while TidyCell remains authoritative.
7. Produce immutable discrepancy reports at every deterministic layer.
8. Cut over one cohort only after `CutoverAuthorization` binds its exact cohort manifest, expected old/new pointer values, discrepancy and exception-policy fingerprints, shadow duration, restore/drain evidence, rollback owner/triggers and go/no-go decision. Change the authority pointer through compare-and-swap, then record the actual transaction and resulting pointer in `CutoverCompletion`.
9. Roll back by disabling sensors/dispatch, restoring the prior authority pointer, and routing clients to the prior projection. Never delete new immutable evidence.
10. External provider calls and simulations are irreversible. Rollback prevents further effects and quarantines ambiguity; it cannot erase history.

## 19. Major risks and mitigations

| Risk                              | Mitigation                                                                                       |
| --------------------------------- | ------------------------------------------------------------------------------------------------ |
| Parser or geometry drift          | Freeze intermediate artifacts and focused edge fixtures; keep TS authoritative                   |
| Cross-language identity drift     | Exact JCS/legacy vectors; separate algorithms; no informal reserialization                       |
| Dagster coupling                  | Framework-neutral use cases; reconstruction drill; event log is projection only                  |
| Duplicate provider cost           | transactionally claimed attempts; raw response first; ambiguous state without blind retry        |
| Approval races or stale decisions | append-only decisions, exact fingerprint binding and compare-and-swap pointers                   |
| Data leakage into ML or tuning    | approved-only exports, whole-workbook SHA exclusions, frozen split manifests                     |
| Artifact exposure through logs    | small safe metadata projection, access-controlled evidence store and redaction tests             |
| Partition explosion               | shared work-unit definition, bounded active cohorts, explicit tombstones/sharding and load tests |
| Justice authority confusion       | explicit draft/adopted status and external adoption decision                                     |
| Calibration double weighting      | dependency graph and frozen role/design ledger before fitting                                    |
| Sembla contract mismatch          | fake first, capability probe, versioned adapter, no role coercion                                |
| Stock-data overclaim              | count-only V1 and explicit identifiability limits                                                |
| Legacy mutable identity           | durable registry plus aliases and conflict reconciliation                                        |
| Rollback illusion                 | immutable audit history and kill switches rather than deletion                                   |

## 20. Decisions deliberately deferred

| Decision                                         | Required before   | Evidence needed                                                   |
| ------------------------------------------------ | ----------------- | ----------------------------------------------------------------- |
| Git remote, project license and package managers | M0 implementation | ownership and build/deployment requirements                       |
| Exact JCS libraries                              | M1                | cross-language adversarial vectors                                |
| Local and production storage adapters            | M3/M4             | scale, threat model, restore test                                 |
| Dagster version and OSS versus Dagster+          | M4 deployment     | edition/lifecycle review and operations needs                     |
| Long-term review client and authentication       | M5 integration    | user workflow and security ownership                              |
| Provider/model/pricing/budget issuer             | any live M6A use  | explicit cost/security authorization                              |
| ML framework/model release                       | M6B               | frozen benchmark and leakage/resource evidence                    |
| Justice V1 ownership handoff or adoption         | M8                | released schemas, authorities, gold and human decision            |
| Calibration dependency and role ledger           | after adoption    | separate frozen design and approval                               |
| Sembla version/artifact/CLI/license              | real M9 use       | released contract, checksum, capability fixture and authorization |
| Historical cohort and discrepancy policy         | M10               | shadow reports and rollback rehearsal                             |

## 21. Definition of successful reimplementation

The reimplementation is successful when:

1. deterministic TidyCell reference fixtures reproduce at every layer;
2. all authoritative domain state is reconstructable without Dagster;
3. providers cannot be called without an explicit scoped authorization and budget;
4. known provider responses are never purchased twice through retry;
5. reviews and approvals bind exact immutable evidence and remain auditable after edits;
6. ML is leakage-clean and advisory;
7. semantic evidence remains provisional until the full independent adoption gate passes;
8. calibration design is frozen separately from semantic meaning;
9. Sembla receives only a self-contained, versioned, hash-pinned projection through its documented boundary;
10. simulation observations cannot feed back into state;
11. cutover and rollback work one cohort at a time; and
12. changing Dagster, storage, provider, model, review UI or Sembla packaging does not require rewriting workbook or RecipeV01 semantics.

Implementation currently includes the M0-M3 deterministic/artifact runtime and the replaceable M4 Dagster projection. The accepted post-M4 plan additionally authorizes its provider-free Phase A inventory work. Evidence copying, code ports, auto-activation, and live provider dispatch remain disabled until their stated gates pass; the already-authorized live pilot may never exceed USD 25. Semantic adoption, public publication, calibration, and Sembla execution remain unauthorized.

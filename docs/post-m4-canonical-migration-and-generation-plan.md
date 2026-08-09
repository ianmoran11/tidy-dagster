# Post-M4 canonical migration, generation, and automated acceptance plan

- Status: accepted planning baseline; implementation remains phased and gate-bound
- Date: 2026-08-09
- Architectural decision: `docs/decisions/0003-canonical-migration-and-automated-recipe-acceptance.md`
- Baseline implementation: M0-M4 at or after `353da0573f062559bc02c75680a48290ae29b31a`
- TidyCell source baseline observed during planning:
  - commit `1be6c995fa931e9860468e40490433161b0121cb`;
  - tree `96a76a1cbc6f2da3facd31d7cdae5b05926361d3`;
  - the commit/tree anchor source-code custody only: the bulk workbook, research,
    harvest, benchmark, and ML artifact roots are ignored or untracked; and
  - dirty/untracked on-disk domain artifacts are intentionally not represented by
    that tree and require a frozen export manifest.
- Tidybank summary-closure source baseline observed during planning:
  - commit `c26e7f67091c414b411221af461b8ea3974c6320`;
  - tree `6b73f893f0d1a98432251f23cbdaab435ba8dacc`;
  - one working-tree status entry was present, so Phase C must freeze the exact
    selected code bytes rather than relying on HEAD alone; and
  - MIT licence SHA-256
    `f0c38e43895b9f54b60d367ae39f48c275b0f59627e7c61073ce4cb11533cf54`.

## 1. Purpose

Move TidyCell's spreadsheet-to-recipe estate into standalone `tidy-dagster`
without turning the sibling repository into a runtime dependency.

The destination must be able to:

1. inventory and import all canonical downloaded workbook bytes;
2. preserve all discoverable approved, generated, failed, repaired, and
   superseded recipe evidence;
3. preserve all relevant ML, prompt, evaluation, and provider evidence;
4. reproduce the ML-assisted V13 Pi/Sol-high generation path;
5. execute and judge each candidate against independent workbook-specific rules;
6. activate clean candidates automatically while routing only exceptions to
   people; and
7. run one bounded live pilot without exceeding USD 25.

This plan supersedes the package assumptions in the unimplemented horizon M5-M8
and historical-import parts of M10 in `docs/reimplementation-plan.md`. It does
not alter accepted M0-M4 behavior or authorize semantic adoption, publication,
calibration, or Sembla.

## 2. Settled decisions

The following are implementation constraints, not open design questions:

- migration is content-addressed and evidence-complete, not a literal duplicate
  filesystem mirror;
- the source is a point-in-time snapshot of the current TidyCell filesystem,
  including in-scope uncommitted and ignored domain artifacts;
- TidyCell is read-only during export and is never imported at runtime;
- historical approvals become `human_approved` only when reviewer free text
  resolves through an attributable reviewer-identity registry and required
  digest evidence resolves; all others remain `legacy_approved_unattributed`
  and are never fabricated into human approval or training gold;
- a strict automated policy may update the effective recipe pointer using the
  separate state `auto_accepted`;
- every workbook digest requires an attributable manually curated acceptance
  manifest before automatic acceptance;
- auto-accepted recipes cannot train ML;
- all model and prompt artifacts are preserved, but only explicitly eligible,
  pinned packages may run;
- the active generation approach is XGBoost hints plus the V13 semantic-map
  prompt through Pi, `openai-codex/gpt-5.6-sol`, high reasoning;
- the initial pilot reproduces the V13 parity policy: at most one correction for
  pre-execution region-resolution or geometry compilation failure; output-level
  validation failures route to exception review without another provider call;
- live provider execution is separated from the network-denied deterministic
  worker;
- the first campaign has a hard USD 25 limit enforced before dispatch; and
- Dagster remains reconstructable and non-authoritative.

## 3. Existing baseline that must remain green

### Implemented

- standalone TypeScript workbook parsing and RecipeV01 execution;
- strict worker request/response schemas and adversarial fixtures;
- independently frozen TidyCell compatibility gold;
- a bundled, digest-bound TypeScript production worker;
- macOS Seatbelt execution with network, process-fork, and write confinement;
- Python immutable content, derivation, custody, decision, reproduction, and
  compare-and-swap pointer repositories;
- blob-first, orphan-safe, transactionally authoritative publication;
- one replaceable Dagster code location with bounded dynamic partitions,
  immutable gate mirrors, sensor deduplication, revision pinning, and persistent
  reconstruction;
- loopback-only Dagster UI and scoped tailnet access.

### Known gap

M2 remains unaccepted because the complete reviewed workbook-summary and
prompt-input detector/renderer closure has not been ported. The active generation
path cannot claim TidyCell prompt parity until this gap is closed or an
independently accepted equivalent contract replaces it. This plan closes the
full closure rather than silently narrowing the claim.

## 4. Scope

### 4.1 In-scope source domains

The exporter must classify domain objects across the complete TidyCell tree,
including at least:

- `abs-spreadsheets/**`, including workbook-adjacent recipe, metadata, source-URL,
  judgement, and conversion sidecars;
- `xlsx-examples/**` and any other top-level workbook-byte roots discovered by
  the whole-tree classifier;
- `data/harvest/cache/**` and `data/harvest/**` campaign evidence;
- `approvals.json`;
- `public/catalog/**`;
- `benchmark-results/**` where it contains workbook, recipe, execution, judge,
  or provider evidence;
- `research-runs/**` where it contains workbook, recipe, prompt, response,
  execution, correction, scoring, or lifecycle evidence;
- `data/ml-prepass/**`;
- `public/ml-prepass/**`;
- `ml/recipe_prepass/**`, `ml/pyproject.toml`, available environment manifests,
  training code, and model documentation;
- `src/lib/workbook/**`, `src/lib/summary/**`, `src/lib/address.ts`,
  `src/lib/recipe/**`, `src/lib/executor/**`, `src/lib/llm/**`,
  `src/lib/ml-prepass/**`, and relevant `src/lib/ontology/**` codelist and
  canonical-value prior art needed to reconstruct behavior;
- `src/server/llm/**`, `src/server/recipe-generation/**`, and relevant
  catalog/review source;
- `scripts/harvest/**`, `scripts/benchmark/**`, `scripts/ml/**`, and the
  required `scripts/experiments/cell-role-pipeline/**` prompt, context,
  semantic-map, compiler, metric, and evidence modules;
- source package manifests/locks and exact copied-source notices;
- prompt-efficiency results and frozen evaluation manifests needed to explain
  promotion decisions; and
- historical XLS source bytes and their separately identified OpenXML
  conversions.

Discovery during clarification found 232 workbook files in the primary
`abs-spreadsheets` and harvest-cache roots representing 198 unique content
hashes, 331 approval records, and thousands of recipe-named artifacts across the
repository. These are preliminary discovery figures only. The signed export and
reconciliation reports are the authoritative counts.

### 4.2 First-class Tidybank summary-source custody

Phase C's full reviewed summary closure includes selected Tidybank behavior. It
is a separate code-custody source, not part of the TidyCell workbook-evidence
snapshot and not a runtime sibling dependency.

Before any port, create `SourceCodeExportSnapshotV1` binding the exact selected
Tidybank files, Git commit/tree, working-tree byte digests, MIT licence, source
paths, and closure manifest. Import only the reviewed summary/detector/renderer
code and fixtures required by Phase C. Do not migrate unrelated Tidybank data or
allow runtime imports/paths. Independent gold must be produced from the frozen
reference source, never the candidate worker.

### 4.3 Explicit exclusions

Do not import these as domain evidence:

- `.git/**` internals;
- `node_modules/**`;
- Python virtual environments;
- `.next/**`, generic build output, tool caches, and operating-system metadata;
- secrets, OAuth stores, API tokens, shell histories, or unrelated local config;
- transient files with no completed publication or evidence role, unless needed
  to explain an ambiguous provider attempt; and
- non-commercial model weights as runnable production packages.

Every exclusion class must be explicit and counted. A file that resembles a
recipe, response, model, workbook, judgement, source/custody metadata sidecar, or
conversion report cannot be omitted by a generic cache rule. Operating-system
metadata such as `.DS_Store` is excluded and counted rather than imported.

### 4.4 Non-goals

This plan does not:

- publish outputs outside the local authoritative repository;
- make TidyCell read from `tidy-dagster`;
- infer human approval;
- train on auto-accepted recipes;
- adopt justice semantic contracts;
- assign calibration roles;
- select or execute Sembla;
- make the Dagster event log authoritative; or
- enable provider calls for unmanifested or sensitive workbooks.

## 5. Authority and dependency model

| Domain                                         | Authoritative implementation                                | Forbidden shortcut                        |
| ---------------------------------------------- | ----------------------------------------------------------- | ----------------------------------------- |
| Raw and derived bytes                          | Python immutable content repository                         | Mutable source path as identity           |
| Source aliases and custody                     | Python append-only records                                  | Path copy as provenance                   |
| Workbook parsing and summaries                 | TypeScript domain worker                                    | Python workbook interpretation            |
| RecipeV01 parsing/canonicalization/execution   | TypeScript domain worker                                    | Python RecipeV01 reimplementation         |
| Semantic-map parsing and RecipeV01 compilation | TypeScript domain worker                                    | Provider-produced recipe trusted directly |
| Structural and output checks                   | TypeScript domain worker                                    | Dagster check as sole evidence            |
| Acceptance-manifest schema validation          | TypeScript for sheet/table semantics; Python stores records | Model-authored oracle                     |
| ML model registry/training/inference launch    | Python application layer                                    | Dagster decorator business logic          |
| ML hints                                       | Immutable, non-binding evidence                             | Hint treated as gold                      |
| Pi process and credentials                     | Restricted Python gateway                                   | Network access in deterministic worker    |
| Budget and attempt state                       | Python transactional repository                             | Environment variable or post-hoc sum      |
| Lifecycle decisions and active pointers        | Python authoritative repository                             | Filename or materialization status        |
| Human curation/approval                        | Attributable external decision                              | Fabricated system reviewer                |
| Orchestration                                  | Replaceable Dagster projection                              | Dagster event log as authority            |

Copied code and fixtures retain MIT notices and source custody. Runtime boundary
scans continue to forbid path imports from TidyCell, Tidybank, Sembla, and the
justice scaffold.

## 6. Identity model

### 6.1 Content

Every byte object has:

- `content_digest = sha256:<hex>`;
- exact byte size;
- media type and artifact class;
- repository blob location;
- first-seen and verified timestamps; and
- optional restricted-access classification.

The same bytes imported through many paths produce one content record and many
source/custody aliases.

### 6.2 Source snapshot

A `TidyCellExportSnapshotV1` binds:

- source root identifier without making it a runtime path dependency;
- Git commit and tree when available;
- UTC freeze time;
- exporter source digest and version;
- repository dirty-state summary;
- sorted item manifest digest;
- category counts, bytes, and unique-content counts;
- explicit exclusion policy digest;
- source filesystem/device information needed for safe reads;
- no-follow path and symlink policy; and
- completion status.

Each item binds relative path, file mode, size, SHA-256, source classification,
Git tracked/untracked/ignored state when determinable, and proposed disposition.
The exporter must use no-follow reads and detect pre/post-read mutation.

### 6.3 JSON and recipe identity

Preserve both exact source-byte identity and named domain identities. Do not
collapse distinct algorithms into a generic "canonical JSON" claim.

- TidyCell historical recipe approvals use the exact TypeScript `digestRecord`
  behavior from `scripts/harvest/candidate-contract.ts`. Port it with independent
  adversarial vectors and identify it as `tidycell-digest-record-v1`.
- New RecipeV01 semantic identities are produced by the standalone TypeScript
  worker under an explicit algorithm identifier. Historical approval binding
  continues to use the historical algorithm rather than silently rehashing.
- Python repository records may continue using their existing named
  `domain_digest`/sorted-JSON identity for Python-owned records. It is not used
  to reinterpret historical RecipeV01 approval digests.
- Any identity that crosses the TypeScript/Python boundary requires exact shared
  vectors, including Unicode keys, escaping, numbers, and ordering.

Do not describe either current sorted-JSON algorithm as RFC 8785/JCS. A future
JCS migration must create a new identity namespace rather than silently changing
old digests.

### 6.4 Work unit and generation revision

Stable work-unit identity remains:

- workbook content digest;
- exact sheet name;
- requested use case; and
- processing-profile digest.

A generation revision additionally binds:

- workbook acceptance-manifest digest;
- summary/context implementation digest;
- ML model-package digests and hint digest;
- prompt-pattern and rendered-message digests;
- provider/model/reasoning configuration;
- pricing and budget-authorization digests;
- correction policy;
- acceptance-policy digest; and
- recipe revision digest once produced.

Run keys must bind this exact revision. A queued run cannot rediscover mutable
current state.

## 7. New authoritative records

Implement strict versioned contracts for:

1. `TidyCellExportSnapshotV1`
2. `SourceCodeExportSnapshotV1`
3. `ExportItemV1`
4. `ImportDispositionV1`
5. `WorkbookRecordV1`
6. `WorkbookSheetRecordV1`
7. `RecipeRevisionV1`
8. `RecipeDigestVerificationV1`
9. `LegacyApprovalSnapshotV1`
10. `ReviewerIdentityV1`
11. `ApprovalResolutionV1`
12. `GenerationAttemptV1`
13. `GenerationInterpretationV1`
14. `PromptPatternPackageV1`
15. `RenderedPromptBundleV1`
16. `ModelPackageV1`
17. `MlHintBundleV1`
18. `WorkbookAcceptanceManifestV1`
19. `AcceptanceGateResultV1`
20. `AcceptanceDecisionV1`
21. `ProviderCampaignAuthorizationV1`
22. `ProviderAttemptV1`
23. `BudgetReservationV1`
24. `PricingPolicyV1`
25. `MigrationReconciliationReportV1`

All records use strict schemas, reject unknown fields at external boundaries,
and bind referenced content by digest. Append-only events and compare-and-swap
pointers retain revision history.

## 8. Export, import, and reconciliation

### 8.1 Provider-free dry-run inventory

The first executable artifact is an inventory tool. It must not copy bytes or
alter TidyCell.

It will:

1. walk approved source roots with no-follow semantics;
2. classify files by domain role using paths plus content validation;
3. hash exact bytes;
4. identify duplicates across paths;
5. find nested recipe/prompt/response records inside result envelopes;
6. identify incomplete or conflicting evidence;
7. estimate destination unique bytes and temporary headroom;
8. produce a deterministic proposed-disposition report; and
9. stop if source files mutate during the scan.

Because local free space is limited and research/ML evidence spans several GB,
no bulk copy begins until an approved repository volume satisfies both:

- free bytes are at least twice the estimated new physical allocation plus 10
  GiB of temporary/recovery reserve; and
- projected post-import volume utilization is at most 85%.

Estimate conservatively without assuming APFS clone savings. Clone copies may
reduce initial physical usage, but correctness, restore capacity, and acceptance
must never depend on the continued existence of source paths or shared mutable
metadata.

### 8.2 Frozen export

The frozen exporter writes a staged same-filesystem manifest and verifies every
file immediately before finalization. It never modifies, renames, or locks a
TidyCell source file. A source change produces a failed item and invalidates the
snapshot until rerun.

### 8.3 Import

The importer is restartable and idempotent:

1. verify the snapshot and exporter identity;
2. read one source item safely;
3. verify digest and size;
4. durably publish content to the destination CAS;
5. publish custody, aliases, and typed records transactionally after blobs;
6. mark the item imported, duplicate, quarantined, or excluded; and
7. checkpoint without changing any effective recipe pointer.

Imported path aliases are evidence only. Application code resolves content and
records through repositories, never the TidyCell path.

### 8.4 Legacy approval resolution

The frozen `approvals.json` is current mutable state, not an append-only decision
log. Preliminary inspection found 331 rows: 266 have richer reviewer/digest
fields and roughly 65 are simple legacy rows. The frozen exporter provides the
authoritative breakdown.

Approval identity currently uses `(assetId, sheetName)`. `assetId` may be a
lossily sanitized display name and may point through mutable `latest-release`
aliases, so it cannot be inverted into workbook identity by string convention.
For every approval, write `ApprovalResolutionV1` with one outcome:

- `resolved`: one exact workbook digest and exact sheet are proven by digest-bound
  harvest/custody/catalog evidence;
- `ambiguous`: more than one candidate workbook/sheet remains;
- `unresolved`: no candidate can be proven;
- `conflict`: source fields or recipe digest evidence disagree.

The resolution record retains the original row digest, every candidate digest,
all evidence consulted, and the algorithm/version. Names and paths may discover
candidates but cannot alone prove resolution. Ambiguous, unresolved, and
conflicting rows never activate and require attributable human resolution or a
new independently gated auto-accepted recipe.

Reviewer attribution is resolved independently through `ReviewerIdentityV1`.
A free-text `approvedBy` value must match an explicitly curated identity or
approved alias; case-folding, typo repair, and values that describe judgement
rather than a person do not create identity automatically. The resolution retains
the original value and attributable mapping decision.

A row with no resolved reviewer identity remains
`legacy_approved_unattributed` even when its workbook is resolved and other
digest evidence exists. It is not `human_approved` and is not eligible for new
ML training.

### 8.5 Reconciliation

A successful migration report proves, separately for each domain:

- source item count and bytes;
- unique content count and bytes;
- imported objects;
- duplicate aliases;
- excluded items by rule;
- quarantined items by reason;
- unresolved conflicts;
- approvals broken down by resolved/unresolved reviewer identity,
  attributable/unattributed status, and
  resolved/ambiguous/unresolved/conflict workbook status;
- recipe revisions and generation attempts;
- prompt and response evidence;
- model packages and training/evaluation evidence; and
- source-to-destination digest closure.

Counts alone are insufficient. The report includes a sorted item-level mapping
and a digest over that mapping. It also states that approval removals, prior
values, rejections, and revocations already overwritten by TidyCell cannot be
recovered from the point-in-time snapshot.

## 9. Recipe lifecycle and activation

### 9.1 States

At minimum:

```text
discovered
generated
validation_failed
execution_failed
validated
auto_accepted
human_approved
legacy_approved_unattributed
rejected
deferred
superseded
revoked
incomplete_evidence
provider_ambiguous
```

Destination state is a projection over append-only events; no destination
transition erases an earlier imported or newly created event. Imported TidyCell
approval data is explicitly marked as a point-in-time current-state snapshot,
not falsely represented as complete historical event history.

### 9.2 Migration mapping

- an approval with a reviewer value resolved through the curated identity
  registry plus unambiguous workbook, sheet, and recipe-digest resolution becomes
  `human_approved`;
- a simple approval without reviewer/digest evidence remains
  `legacy_approved_unattributed` even if its target is later resolved;
- ambiguous or unresolved name-keyed approvals remain inactive;
- a generated valid recipe remains `validated` until current gates run;
- invalid recipes retain failure evidence;
- missing prompt/response/provenance becomes `incomplete_evidence`, not approval;
- superseded, rejected, or revoked evidence is retained only when discoverable;
  missing history is reported, never reconstructed; and
- conflicting approvals or digest mismatches stop activation and enter review.

### 9.3 Activation policy

An effective pointer may select only a revision that has:

- exact workbook/sheet binding;
- successful deterministic execution;
- successful applicable acceptance gates;
- a valid `auto_accepted` or `human_approved` decision; and
- compare-and-swap success against the expected prior pointer revision.

Gate first, activate second. A human-approved pointer cannot be displaced by an
auto-accepted revision without a separate attributable supersession decision.
Historical approval remains preserved even when a current compatibility gate
fails; the incompatible revision is not activated in the new runtime.

## 10. Summary and prompt-input parity closure

Port the complete reviewed TidyCell/Tidybank summary detector and renderer closure
needed by recipe generation, including:

- candidate block detection and prioritization;
- sheet logical bounds and phantom-dimension normalization;
- merged-cell and formatting evidence;
- warning prioritization and truncation;
- source-address preservation;
- compact semantic context;
- semantic formatting and cell-data facts;
- role-aware region catalogue construction;
- deterministic context and catalogue digests; and
- produced-CSV summary used for factual correction/review.

Freeze independent reference artifacts from a pinned TidyCell export bundle.
The candidate worker cannot generate its own compatibility gold. Parity compares
intermediate artifacts, rendered messages, warnings, and truncation—not only the
final recipe.

M2 must be accepted for the selected full closure through representative and
adversarial fixtures before the live V13 path can proceed. There is no
"unsupported but live" escape hatch in this plan.

## 11. Model registry and ML inference

### 11.1 Preserve, classify, and pin

Every discovered model artifact receives a disposition:

- runtime eligible under current training policy;
- `legacy_hint_eligible` for disclosed pre-policy non-binding hint use;
- research only;
- superseded;
- licence blocked;
- incompatible runtime;
- incomplete evidence; or
- corrupt/quarantined.

A newly promoted runnable package requires:

- model bytes and SHA-256;
- task and model family;
- exact feature schema and ordering;
- predictor implementation and a newly frozen exact runtime lock;
- training code/source snapshot;
- training corpus and split digests;
- workbook-level exclusion and leakage report;
- all recoverable hyperparameters, seed, and calibration evidence;
- evaluation and frozen prediction evidence;
- licence determination; and
- an explicit destination promotion decision.

Historical packages missing a lock, seed, hyperparameter, licence, or promotion
record are preserved as `legacy_incomplete`, not rejected or silently declared
runnable. Phase D may promote an existing XGBoost model without retraining only
as `legacy_hint_eligible` after it:

- classifies every recoverable historical training source by approval authority
  and discloses legacy/unattributed/non-approved inputs rather than claiming
  current-policy compliance;
- creates a fresh exact isolated-runtime lock;
- proves exact target-workbook exclusion;
- proves prediction parity against frozen feature/prediction fixtures;
- passes licence review; and
- receives an explicit destination promotion decision limiting it to compact
  non-binding hints.

If these conditions cannot be proven, the model remains archival and the live
path is blocked; this plan does not authorize an invented retrain.

Do not copy virtual environments as model evidence. Preserve their package
inventory as source evidence where useful, then build and lock a clean separate
inference runtime.

### 11.2 Isolated inference and intended initial hints

The intended initial path uses promoted XGBoost cell-role and header-direction
packages. Pickle is executable code and must never be loaded inside the
orchestrator or authoritative repository process.

Any operation that unpickles model bytes—including one-time conversion—must run
in the dedicated macOS deny-default sandbox below, never in the orchestrator,
importer, repository, or an unrestricted migration process. Prefer sandboxed
one-time conversion of allowlisted, digest-pinned legacy pickles into a safer
native XGBoost serialization, followed by exact prediction parity. Runtime
inference then uses the safer form. If conversion is impossible, each inference
may load only explicitly allowlisted model bytes inside the same sandbox, which:

- denies network and process forks;
- reads only the exact model and feature inputs;
- writes only a private bounded run root;
- receives a scrubbed environment;
- applies CPU, memory, file, stdout/stderr, and process-tree limits; and
- returns a strict bounded hint schema that is verified before publication.

For each target workbook:

- prove exact target SHA-256 absence from training inputs;
- disclose that the initial operational policy is exact-SHA exclusion only and
  does not claim adjacent-year/publication-family independence;
- fail closed if metadata cannot prove exact exclusion; and
- record model predictions as compact fallible evidence.

A future deciding ML-performance claim requires a separately frozen
near-duplicate/publication-vintage exclusion policy. ML never writes approval or
the final recipe. TypeScript owns how hints are projected into the prompt and how
semantic maps compile.

### 11.3 Training authority

For every new training or retraining run after this plan, only approvals with a
reviewer identity resolved through the curated registry plus required workbook,
sheet, and recipe-digest evidence may enter a training snapshot.
`auto_accepted`, `legacy_approved_unattributed`, unresolved, and unattributed
examples remain excluded unless a later attributable human promotion event is
added. The `legacy_hint_eligible` exception permits use of an existing frozen
model as non-binding evidence; it does not authorize reuse of its historical rows
in a future training snapshot. Training, validation, deciding benchmarks, and
operational pilot cohorts must remain separately frozen and hash-reconciled.

## 12. Prompt registry and active V13 generation

### 12.1 Prompt packages

Archive and classify all relevant direct, semantic-map, repair, review, and
experimental patterns. A runnable prompt package binds:

- source and dependency digests;
- prompt version;
- examples and rule tiers;
- summary/compact-context versions;
- formatting and ML-hint projection versions;
- renderer and canonical message digest rules;
- output schema;
- compatible provider/model capabilities;
- correction policy;
- snapshot tests; and
- evaluation/promotion evidence.

Only explicitly promoted prompt packages are selectable in production.

### 12.2 Active path

The initial path reproduces the recorded V13 role-aware semantic-map contract:

1. construct pinned compact context and role-aware catalogue;
2. apply eligible XGBoost hints as suggestions;
3. render the exact V13 prompt;
4. call Pi with provider `openai-codex`, model `gpt-5.6-sol`, high reasoning;
5. retain raw response before parsing;
6. strictly parse the semantic-map schema;
7. attempt deterministic RecipeV01 compilation;
8. only when compilation fails at `region-resolution` or `geometry`, permit one
   bounded V13 correction call and compile the corrected map; and
9. execute the compiled recipe, inspect actual CSV/evidence, and run acceptance
   gates.

Execution, duplicate, codelist, total, and other output-level failures route to
exception review in the initial pilot; they do not trigger another provider
call. A future post-execution correction policy is a distinct policy version
requiring separate frozen evaluation and authorization.

Provider transport retries before confirmed dispatch may be separately defined.
A model correction is not a transport retry. No second correction is permitted
in the initial pilot.

## 13. Workbook acceptance manifests

### 13.1 Human curation contract

Each manifest binds:

- workbook digest and source evidence;
- manifest revision, curator, time, and rationale;
- exact sheet names and data/non-data classification;
- expected table identities and source ranges or permitted regions;
- required dimensions and composite observation keys;
- codelist ID/version, raw labels, canonical members, exact/subset policy, and
  expected cardinality;
- expected observation and table-count constraints;
- total/component equations, dimensions over which they hold, tolerances, and
  rounding rules;
- units, scale, universe, and reference period;
- suppression, confidentiality, missing, not-applicable, observed-zero, and
  structural-zero representations;
- totals-as-observation/check/excluded treatment;
- permitted overlaps, source-cell reuse, and warnings; and
- provenance for every assertion.

A manifest cannot be generated and approved by the same LLM attempt. Tools may
suggest assertions, but the attributable human curator owns the final manifest.
The record binds distinct proposer and curator identities and rejects a provider
attempt identity as curator.

Every unique downloaded workbook intended for operational processing eventually
requires its own completed manifest. Canonical import and archival preservation
do not wait for all manifests: Phase E proves the contract and curates the frozen
pilot subset first. A full-estate operational rollout is incomplete until every
imported downloaded-workbook digest is either manifested or explicitly assigned
an attributable non-operational/archive disposition.

### 13.2 Revision and staleness

A manifest is exact-workbook-bound. A new workbook digest requires a new
manifest or an explicit human-authored derivation that identifies and reviews
every inherited and changed assertion. Sheet-name or content drift fails closed.

## 14. Acceptance gates

All gate outputs are immutable and digest-bound. Unless a manifest explicitly
allows a warning code, warnings block automatic acceptance.

### Gate A — source admission

- workbook digest and size match;
- exact sheet exists;
- XLSX archive, XML, cell, merge, row, column, output, and memory limits pass;
- unsupported encryption, macros, or external execution fail closed;
- sensitivity classification permits the selected local/provider path;
- work claim and generation revision are unique.

### Gate B — recipe and semantic-map structure

- raw response is retained;
- strict JSON parsing and unknown-field rejection pass;
- semantic-map and RecipeV01 schemas pass;
- table/header/value names are unique and output columns do not collide;
- selectors resolve only within the intended sheet;
- ranges are bounded;
- relationship geometry is valid;
- table and observation counts are non-zero and bounded.

### Gate C — deterministic execution

- execution completes under the sandbox and resource limits;
- declared output hashes and rows match actual files;
- repeated execution yields identical normalized recipe and table bytes;
- no undeclared output or filesystem mutation occurs.

### Gate D — duplicate, overlap, and coverage

Check independently:

- duplicate composite observation keys;
- one source value coordinate producing unintended multiple observations;
- unexpected cross-table source-cell reuse;
- duplicate semantic observations;
- missing dimensions that collapse distinct observations;
- extraction from titles, notes, footnotes, or excluded totals;
- unexpected selector overlap;
- expected value cells left unconsumed; and
- actual source coverage against permitted/expected ranges.

Repeated labels, dimension cells, or values are not automatically errors. Only
manifest-authorized reuse passes.

### Gate E — codelists and dimensions

- every required dimension is present;
- raw labels map to the pinned codelist version;
- unknown, ambiguous, or duplicate canonical members fail;
- exact/subset and missing-member rules pass;
- permitted cardinalities pass;
- totals and special members remain distinct from ordinary members; and
- raw and canonical forms remain in evidence.

### Gate F — totals and statistical meaning

- declared component/total equations pass at the correct dimensional slice;
- tolerances and rounding rules are applied exactly;
- unit and scale match;
- universe and reference period match;
- suppression, missing, not-applicable, zero, and structural-zero rules pass;
- percentages and rates use their declared denominator/scale behavior; and
- expected table/observation counts pass.

Counts and totals alone cannot prove correct dimension assignment. All applicable
gates must pass.

### Gate G — policy and activation

- all required gate digests are present and successful;
- inputs match the queued generation revision;
- policy, manifest, prompt, model, provider, and pricing versions are current;
- no provider attempt remains ambiguous;
- no unallowlisted warning exists;
- acceptance decision is written append-only; and
- active pointer moves by compare-and-swap only after the decision commits.

## 15. Provider gateway and budget

### 15.1 Isolation

The Pi gateway is not the deterministic worker. It must:

- run under a dedicated restricted service boundary;
- receive only the exact rendered messages and model configuration;
- expose no general shell, repository, browser, or filesystem tools to the model;
- use a scrubbed environment containing only required runtime/auth variables;
- pin the Pi executable/source and verify it immediately before spawn;
- verify authorization freshness;
- cap stdin/stdout/stderr, time, and process tree;
- retain prompts/responses as restricted blobs, not normal Dagster metadata; and
- transmit only workbooks classified as permitted for external processing.

Workbook cells are untrusted data, never instructions for the gateway.

### 15.2 Attempt state

At minimum:

```text
planned
reserved
dispatching
dispatched
response_durable
settled
failed_pre_dispatch
ambiguous
refused_budget
cancelled_pre_dispatch
```

A unique attempt claim is authoritative. Dagster retries and run keys cannot
create a second call for the same claimed attempt.

### 15.3 Hard USD 25 campaign

`ProviderCampaignAuthorizationV1` binds:

- frozen pilot cohort digest;
- exact provider/model/reasoning;
- prompt, model, correction, and pricing-policy digests;
- maximum calls and corrections;
- maximum input/output/reasoning tokens per call;
- absolute USD 25 campaign ceiling;
- validity window;
- authorizer and purpose;
- permitted data classification; and
- kill-switch state.

Before dispatch, reserve the maximum possible cost of the initial call and its
permitted correction. Atomic reservations across concurrent workers cannot
exceed USD 25. Settlement records observed usage and releases only demonstrably
unused reservation. Missing or invalid usage settles conservatively and blocks
further calls pending reconciliation.

No blind retry follows a timeout, lost process, or crash after possible dispatch.
Such attempts become `ambiguous` and consume their reservation until resolved.

## 16. Dagster projection

Do not alter the accepted provider-free work-unit topology to make provider calls.
Add a separately named generation topology and leave provider dispatch default-off
outside an active campaign authorization.

### Suggested asset groups

#### Migration

- `tidycell_export_snapshot`
- `canonical_source_objects`
- `historical_recipe_evidence`
- `historical_approval_decisions`
- `migration_reconciliation_report`

#### Registries and oracle

- `model_package_registry`
- `prompt_pattern_registry`
- `workbook_acceptance_manifest`
- `generation_input_bundle`

#### Generation and validation

- `ml_hint_bundle`
- `rendered_prompt_bundle`
- `provider_attempt_evidence`
- `semantic_map_candidate`
- `recipe_revision_candidate`
- `recipe_execution_evidence`
- `acceptance_gate_bundle`
- `effective_recipe_projection`
- `exception_review_projection`

Every Dagster asset reads authoritative records through application services and
publishes only after those services succeed. Asset checks mirror immutable gate
results; they do not define them.

### Partitions and sensors

- use a separately named dynamic partition definition and leave the accepted
  `provider_free_work_units_v1` definition/cap unchanged;
- cap the new active generation definition at 1,000 keys across its own existing
  plus proposed set; historical imported objects are repository records or
  bounded batches, not one permanently active dynamic partition each;
- when the union would exceed the cap, add nothing, publish an authoritative
  capacity-refusal result, and return a visible Dagster `SkipReason` rather than
  partially adding keys or repeatedly throwing a sensor exception;
- bind partition identity to stable work-unit identity;
- bind run keys/tags/config to exact generation revision and campaign;
- add partitions atomically with bounded discovery;
- never let the default sensor dispatch a provider call without a valid campaign
  authorization and budget reservation;
- use coarse Dagster pools for admission only; authoritative concurrency and
  budget controls remain in repositories; and
- preserve restart/deduplication/reconstruction behavior.

## 17. Delivery phases and gates

The labels below replace, for this work, the unimplemented package assumptions in
historical M5-M8. They do not renumber accepted M0-M4.

### Phase A — provider-free inventory and source snapshot

**Deliverables**

- strict export/disposition schemas;
- read-only no-follow inventory tool;
- category classifier and nested evidence discovery;
- disk/headroom and deduplication report;
- frozen point-in-time export manifest;
- source mutation and path-escape negatives.

**Done when**

- repeated scans of unchanged source produce identical manifests;
- every in-scope item has one explicit proposed disposition;
- mutation, symlink, unreadable, and conflict tests fail closed;
- the selected destination satisfies the two-times-plus-10-GiB and 85%
  utilization headroom rules;
- no TidyCell file changes;
- the report is independently reviewed; and
- no content import or provider call has occurred.

### Phase B — canonical import and reconciliation

**Deliverables**

- import repository extensions and typed records;
- restartable importer;
- content/custody/alias publication;
- recipe/approval/generation/model/prompt disposition importers;
- curated reviewer-identity registry and per-approval resolution records;
- historical `digestRecord` implementation/vectors; and
- quarantine and reconciliation reports.

**Done when**

- import is idempotent and crash-recoverable;
- every item reconciles by digest;
- exact duplicates share content identity;
- incomplete evidence is visible and inactive;
- every approval has an attributable/unattributed classification and an explicit
  resolved/ambiguous/unresolved/conflict resolution record;
- historical `digestRecord` approval bindings verify through independent
  TypeScript vectors;
- no effective recipe pointer moves; and
- reconstruction succeeds without Dagster metadata or TidyCell runtime access.

### Phase C — summary and prompt-input parity

**Deliverables**

- frozen code-custody snapshots for the exact selected TidyCell and Tidybank
  summary closure, with licences and source manifests;
- full reviewed summary/detector/renderer closure;
- compact context, formatting facts, catalogue, and produced-CSV summaries;
- independent reference bundle from those frozen sources;
- strict worker protocol additions and parity fixtures.

**Done when**

- independent intermediate and rendered-output parity passes;
- truncation/warning/adversarial fixtures pass;
- relocated worker replay passes;
- M2 is explicitly accepted for the full selected closure; otherwise Phase C is
  incomplete and Phases D-H cannot enable live generation;
- all existing M0-M4 checks remain green.

### Phase D — model and prompt registries, replay only

**Deliverables**

- model/prompt package schemas and registries;
- licence/runtime/leakage eligibility policy;
- selected XGBoost hint path;
- V13 rendering, semantic-map parsing, compilation, and correction transition;
- recorded-response replay fixtures.

**Done when**

- all discovered packages have explicit classifications;
- every intended legacy hint model has a classified historical training corpus
  and never claims compliance it cannot prove;
- promoted packages are digest-pinned and reproduce frozen predictions in a
  newly locked isolated inference runtime;
- runtime inference cannot access network, spawn children, or write outside its
  private run root, and the orchestrator never unpickles model bytes;
- target-workbook exact-SHA exclusions are mechanically proven and the absence
  of adjacent-vintage independence is disclosed;
- recorded responses reproduce TidyCell candidate recipes/evidence;
- invalid and drifted packages fail closed;
- no network is reachable.

### Phase E — workbook oracle and automated acceptance

**Deliverables**

- acceptance-manifest schema, validator, and curation tooling;
- structural, duplicate, coverage, codelist, totals, and meaning gates;
- lifecycle and policy engine;
- exception queue projection;
- gated compare-and-swap activation.

**Done when**

- every positive fixture has an attributable manifest;
- one-reason negatives exist for every gate/failure code;
- no warning passes unless the exact manifest allows it;
- auto acceptance never creates human approval or training eligibility;
- a training exporter rejects `auto_accepted`,
  `legacy_approved_unattributed`, unresolved, and unattributed records;
- proposer/curator identity tests reject an LLM/provider attempt as manifest
  curator;
- provider-egress classification tests reject unpermitted workbooks before
  prompt dispatch is claimable;
- gate failure leaves the previous active pointer unchanged;
- human-approved pointers cannot be silently displaced;
- independent reviewers find no blocker/high findings.

### Phase F — fake provider, restricted gateway, and budget ledger

**Deliverables**

- pinned Pi gateway contract with fake executable;
- campaign authorization and pricing contracts;
- transactional reserve/dispatch/settle/release ledger;
- unique attempt claims, ambiguity handling, and kill switch;
- security/redaction and restricted-evidence storage.

**Done when**

- concurrent reservations cannot exceed USD 25;
- crash points before/after dispatch have correct states;
- ambiguous attempts never retry automatically;
- missing usage settles conservatively;
- corrections consume the same campaign budget;
- prompt injection cannot gain tools, files, or unrelated secrets;
- all tests use a fake provider and network remains blocked.

### Phase G — Dagster generation projection and operational proof

**Deliverables**

- separate bounded generation partitions/assets/checks/job/sensor;
- exact generation-revision propagation;
- campaign-aware dispatch admission;
- exception review projection;
- persistent restart/reconstruction operational tests.

**Done when**

- duplicate ticks do not duplicate imports, decisions, or provider attempts;
- queued runs cannot drift prompt/model/manifest/recipe revisions;
- deleting only Dagster metadata reconstructs the view;
- daemon restart preserves cursor/run-key deduplication;
- provider dispatch is impossible without an authoritative authorization;
- loopback/tailnet UI remains healthy.

### Phase H — frozen live pilot, maximum USD 25

**Cohort selection**

Before viewing new generation outcomes:

1. consider only public workbooks with completed acceptance manifests;
2. require exact target-workbook exclusion from active ML training inputs;
3. exclude sheets with an effective human-approved recipe unless the pilot is
   explicitly a non-activating parity replay;
4. mechanically stratify eligible sheets by observable geometry/format metadata;
5. select at most ten sheets and at most twenty provider calls under the one-
   correction policy, reducing the cohort if worst-case reservations require it;
6. freeze and hash the cohort, campaign, models, prompts, manifests, pricing, and
   correction policy; and
7. run a single readiness canary before the remaining cohort.

**Done when**

- cumulative settled plus outstanding reserved cost never exceeds USD 25;
- every call has exact prompt/model/usage/response/attempt evidence;
- no ambiguity is retried;
- every candidate is accepted or routed to a reasoned exception;
- active pointers move only for successful strict policy decisions;
- API-equivalent cost, calls, tokens, validity, exceptions, and outcomes are
  reported;
- independent operations and correctness reviewers accept the evidence; and
- no public publication occurs.

## 18. Test matrix

### TypeScript unit and contract tests

- summary candidate selection and truncation;
- logical bounds, merges, formatting, and phantom dimensions;
- canonical JSON/recipe digest vectors;
- compact context and catalogue snapshots;
- ML-hint projection ownership;
- prompt rendering and section-size evidence;
- semantic-map strict parsing;
- deterministic compilation and correction diagnostics;
- recipe schema, selector, geometry, execution, and output limits;
- duplicate header/table/output names;
- duplicate observation/source-cell/cross-table reuse;
- expected/consumed range coverage;
- codelist exact/subset/cardinality behavior;
- total equations, rounding, rates, percentages, suppression, and zero states;
- manifest drift and warning allowlists.

### Python unit tests

- source no-follow reads and pre/post mutation checks;
- export classification and deterministic manifest ordering;
- import idempotence, conflicts, quarantine, and transaction boundaries;
- model/prompt registry eligibility;
- isolated model conversion/inference sandbox and rejection of unallowlisted
  pickle bytes;
- reviewer-identity resolution rejects judgement labels, unknown aliases,
  misspellings, and case variants unless an attributable curated alias decision
  exists;
- approval resolution with lossy names, mutable aliases, zero/one/many digest
  candidates, and conflicts;
- training-export rejection of `auto_accepted`,
  `legacy_approved_unattributed`, unresolved, and unattributed records;
- proposer/curator separation and provider-attempt curator rejection;
- provider-egress classification before attempt claim/dispatch;
- append-only destination lifecycle events, point-in-time legacy snapshots, and
  pointer CAS;
- provider authorization, pricing, reservation, settlement, release, and expiry;
- concurrent budget reservations;
- unique provider-attempt claims;
- pre-dispatch failure versus post-dispatch ambiguity;
- missing/invalid usage;
- restricted environment and process-tree cleanup;
- raw evidence redaction/access classification.

### Cross-language and integration tests

- strict protocol unknown-field rejection;
- digest and canonicalization vectors;
- independent TidyCell reference parity;
- model prediction schema parity;
- recorded-response V13 replay;
- map-to-recipe-to-CSV end-to-end replay;
- acceptance-manifest positive and one-reason-negative fixtures;
- attributable and legacy-unattributed approval import without fabricated
  reviewer, including invalid reviewer labels/aliases and ambiguous/unresolved
  workbook targets;
- generated valid, generated invalid, repaired, superseded, and incomplete flows;
- auto acceptance with immutable gate bundle;
- gate failure preserving prior pointer;
- fake provider correction and ambiguity scenarios;
- reconstruction from authoritative repositories after deleting Dagster state.

### Operational tests

- dynamic partition union cap;
- sensor tick, restart, cursor, and revision-aware run-key deduplication;
- queue concurrency and provider claim concurrency;
- service restart during import, execution, reservation, dispatch, and
  publication;
- disk-full and orphan-blob recovery;
- repository backup and restore;
- local UI/Tailscale health without exposing restricted evidence;
- boundary scan across Python/TypeScript/scripts.

### Regression floor

Every phase must continue to pass:

- locked Python sync;
- Ruff check and formatting;
- full Python tests;
- real provider-free Dagster operational test;
- `dg check defs`;
- `npm ci`;
- full TypeScript check/parity replay;
- relocated executable tests;
- boundary scans;
- `git diff --check`; and
- no unexpected staged or sibling-worktree changes.

## 19. Review gates and stop rules

### Required independent reviews

- Phase A: inventory completeness, path safety, and disk estimate;
- Phase B: reconciliation and authority boundaries;
- Phase C: independent parity and copied-source custody;
- Phase D: model licensing/leakage and prompt parity;
- Phase E: false-acceptance, semantic-oracle, and pointer ordering;
- Phase F: security, ambiguity, concurrency, and hard budget enforcement;
- Phase G: Dagster revision pinning and operational recovery;
- Phase H: preflight authorization and post-pilot evidence.

### Stop immediately when

- TidyCell source mutates during a frozen export;
- source/destination digest mismatch occurs;
- disk headroom is insufficient;
- a source item has no safe disposition;
- prompt/summary/model parity is unresolved for the selected path;
- model licensing, isolated prediction parity, or target leakage is unproven;
- an approval resolves to zero or multiple workbook/sheet candidates while an
  activation is requested;
- automatic acceptance or activation is requested for a workbook without a
  completed acceptance manifest;
- provider or model identity differs from campaign authorization;
- Pi cannot be run without general tools/repository access;
- pricing or worst-case reservation cannot be calculated;
- the next reservation could exceed USD 25;
- a provider attempt is ambiguous;
- any gate emits an unallowlisted warning;
- an active pointer would move before gate/decision commit; or
- an unapproved publication, training, semantic, or Sembla side effect is
  requested.

## 20. Migration, cutover, and rollback

1. TidyCell remains the read-only source and existing authority during export and
   shadow verification.
2. Import never changes a destination active pointer.
3. Provider-free replay and acceptance run in shadow first.
4. Historical decisions are imported separately from bytes and derivations.
5. Conflicts and incomplete evidence remain quarantined.
6. A cohort may become active only through an exact compare-and-swap decision.
7. Rollback disables generation sensors/provider authorization and moves a
   destination pointer through a new attributable decision; immutable evidence
   remains.
8. TidyCell is not deleted, rewritten, or dual-authored by this work.
9. Live provider history cannot be undone. Rollback stops future dispatch and
   preserves ambiguous evidence.
10. Incremental delta snapshots may follow the initial snapshot until a later
    separately authorized source-of-truth cutover.

## 21. Likely implementation layout

Names are proposed, not binding, but ownership is binding.

```text
contracts/
  migration/v1/
  generation/v1/
  acceptance/v1/
  provider/v1/
  model/v1/
  prompt/v1/

apps/domain-worker/src/
  summary/
  prompt-input/
  semantic-map/
  generation-evidence/
  acceptance/

src/tidy_orchestrator/
  migration.py
  lifecycle.py
  models.py
  prompts.py
  provider.py
  budget.py
  acceptance.py
  generation_work_units.py
  generation_dagster_defs.py

scripts/
  inventory-source-export
  freeze-source-export
  import-source-export
  reconcile-source-import
  run-provider-pilot

fixtures/
  migration/
  summary-parity/
  generation-replay/
  acceptance/
  provider/

schemas/
  workbook-acceptance-manifest-v1.schema.json
```

Keep one authoritative writer per repository slice. Reviewers and reference
builders remain read-only. Copied TidyCell code and fixtures must update
`docs/ported-source-provenance.json` or a successor import manifest with exact
source bytes and notices.

Migration commands receive the source root and source-system metadata through a
strict external configuration/CLI contract. Runtime Python contains no sibling
imports, workstation paths, or literal source-root reads. The accepted boundary
scan is not weakened to make migration pass.

## 22. Authorization table

| Activity                                                          | Status under this plan                                                 |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Draft and independently review this plan/ADR                      | Authorized                                                             |
| Provider-free inventory and dry-run design                        | Authorized direction; implementation begins only after plan acceptance |
| Copy/import TidyCell evidence                                     | Gate-bound; no copy before Phase A disk/reconciliation review          |
| Port summary/prompt/ML/semantic-map code                          | Gate-bound, with exact custody and parity                              |
| Build workbook-manifest and automated-check tooling               | Authorized direction                                                   |
| Activate `auto_accepted` recipes in the isolated pilot repository | Authorized only after Phase E/G gates                                  |
| Use auto-accepted recipes for ML training                         | Prohibited                                                             |
| Live Pi readiness canary and pilot                                | Authorized up to USD 25 only after Phase A-G acceptance                |
| Any provider spend above USD 25                                   | Not authorized                                                         |
| Blind retry after ambiguous dispatch                              | Prohibited                                                             |
| Public or downstream publication                                  | Not authorized                                                         |
| Justice semantic adoption                                         | Not authorized                                                         |
| Calibration or simulation                                         | Not authorized                                                         |
| Real Sembla execution                                             | Not authorized                                                         |

## 23. Residual risks

- The TidyCell working tree has hundreds of current modifications/untracked
  entries; the export snapshot, not Git HEAD alone, must define source truth.
- Complete research and ML evidence may exceed current local disk headroom.
- Some historical generation attempts may lack raw response or prompt evidence.
- Full summary/prompt parity may require a larger detector/renderer closure than
  the current worker.
- Manually curating every workbook manifest is the dominant human workload.
- Codelist/total assertions can still be wrong; attribution and revision history
  are required.
- Adjacent publication years may be near-duplicate ML leakage even when exact
  hashes differ.
- Pi/provider/model availability, pricing, and authentication can drift before
  the pilot.
- External model calls disclose the selected compact workbook context to the
  provider; only explicitly public workbooks are eligible by default.
- Strict fail-closed policy may create a large exception queue initially.
- Dagster queue and partition limits remain bounded single-host controls, not HA.

## 24. Definition of completion

This post-M4 phase is complete only when:

- the frozen TidyCell source estate reconciles to explicit destination
  dispositions;
- imported evidence is reconstructable without TidyCell or Dagster metadata;
- summary/prompt-input parity is independently accepted;
- model and prompt packages are fully classified and active versions pinned;
- every live-pilot workbook has a human-curated acceptance manifest, and every
  other imported downloaded workbook is tracked as manifest-pending or has an
  attributable non-operational/archive disposition;
- replayed and fake-provider flows prove deterministic generation, strict
  acceptance, exception routing, ambiguity safety, and hard budget enforcement;
- Dagster projects exact immutable revisions without becoming authority;
- the live pilot remains at or below USD 25 and produces a complete evidence
  report; and
- no auto-accepted recipe enters ML training, no public publication occurs, and
  semantic/Sembla/calibration side effects remain disabled.

# End-to-end spreadsheet product prototype plan

- **Status:** implemented and checked; see the implementation record below
- **Product model:** `openai-codex/gpt-5.6-luna`
- **Reasoning level:** high
- **Initial cohort:** *Prisoners in Australia*, Table 30, 2023–2025
- **Related architecture:**
  - `docs/reimplementation-plan.md`
  - `docs/post-m4-canonical-migration-and-generation-plan.md`
  - `docs/decisions/0003-canonical-migration-and-automated-recipe-acceptance.md`

## 1. The simple goal

Build a small working prototype using three related spreadsheets from the
*Prisoners in Australia* publications for 2023, 2024, and 2025.

The prototype must:

1. read each workbook;
2. use `openai-codex/gpt-5.6-luna` to generate a recipe for the selected sheet;
3. compile and run the recipe deterministically;
4. test the result automatically;
5. accept a passing result automatically;
6. send only failures or uncertain results to a person for review; and
7. combine accepted observations from the three years into one dataset.

In short:

> Put three real spreadsheets in. Get newly generated recipes, checked results,
> a problem queue, and one combined dataset out.

## 2. Important distinction

The completed frozen 63-item canary is a **migration and custody pilot**. It
proved that selected files and evidence could be copied, stored, interpreted,
and rebuilt safely. It did not prove the spreadsheet product workflow described
above.

The product prototype is not complete unless it generates recipes, executes
them, tests their outputs, routes exceptions, and combines compatible data.

## 3. Why use this cohort?

Use the same logical table across three publications:

> Prisoner counts by state or territory, Indigenous status, sex, and legal
> status.

The selected sheets are expected to be Table 30 or their verified equivalent in
2023, 2024, and 2025. Their exact workbook digests and sheet identities must be
frozen before implementation begins.

This cohort is useful because:

- it contains real layout changes between years;
- all years should fit one understandable output schema;
- the main dimensions have small, checkable code lists;
- historical recipes and outputs already exist for comparison; and
- it proves that the system can combine related observations across workbooks.

Historical recipes and results may be used as **hidden comparison evidence only**.
They must not be shown to Luna, included in its prompt, or used as the automatic
acceptance rule for newly generated recipes.

If the 2023 publication does not contain the same logical table under a verified
sheet identity, freeze the closest coherent three-year range instead. Do not
silently substitute a different table.

## 4. Expected output

Each accepted observation should use a shared format similar to:

```text
reference_date
jurisdiction_id
indigenous_status_id
sex_id
legal_status_id
measure_id
unit_id
value
value_status
source_workbook_digest
source_sheet
source_cell
recipe_digest
```

The prototype should produce:

- one generated RecipeV01 recipe for each selected sheet;
- one tidy output file for each workbook;
- one automatic acceptance report for each result;
- one exception record for every failed or uncertain result;
- one combined, consistently sorted 2023–2025 dataset; and
- provenance that connects every value to its workbook, sheet, cell, recipe,
  prompt package, model, and generation attempt.

Raw provider prompts and responses remain restricted evidence and must not be
written to ordinary logs or worker output.

## 5. Work plan

### Step 1 — Correct the project language

Relabel the completed 63-item work consistently as a **migration and custody
pilot**, rather than a product MVP.

Write down this product rule where it cannot be overlooked:

```text
workbooks
→ generated recipes
→ deterministic execution
→ automatic tests
→ automatic acceptance or exception
→ canonical mapping
→ combined dataset
```

Migration, storage, and governance work does not count as progress on this
prototype unless it directly enables that path.

**Done when:** the main documentation clearly distinguishes the migration pilot
from this product prototype.

### Step 2 — Freeze the three-workbook cohort

Create a small manifest that records:

- exact workbook paths, SHA-256 digests, and byte lengths;
- exact sheet names and stable sheet identities;
- publication identity and reference date for each workbook;
- the shared table-family identity;
- the code-list and schema versions used for testing;
- the allowed generation model: `openai-codex/gpt-5.6-luna`;
- high reasoning;
- the provider-call and spending limits; and
- the hidden historical comparison artifacts, kept outside generation inputs.

The manifest must fail closed if a workbook, sheet, schema, code list, model, or
prompt package no longer matches its recorded identity.

**Done when:** one digest-bound manifest identifies exactly three related source
sheets and all inputs needed to process them.

### Step 3 — Define an independent table-family acceptance contract

Create one human-authored contract for this logical table family. The contract
should describe what a correct result means without prescribing the recipe that
must produce it.

At minimum, define:

- required dimensions;
- the unique observation key;
- accepted jurisdiction, Indigenous-status, sex, and legal-status codes;
- the count measure and unit;
- the reference-date rule;
- expected categories and reasonable category counts;
- treatment of totals and subtotals, plus a fail-closed rule for any missing,
  suppressed, or not-applicable marker; observed zero remains an ordinary numeric
  observation;
- permitted source-cell reuse;
- expected coverage and overlap rules; and
- any total-versus-component equations that can be checked safely.

This table-family contract replaces routine per-recipe human approval for this
bounded prototype. A person authors and versions the acceptance rules; the
system applies them to every generated result. Luna and the ML hints cannot
author or weaken the rules that judge their own output.

**Done when:** the contract can accept a valid fixture and reject fixtures with a
duplicate key, unknown code, missing dimension, or inconsistent total.

### Step 4 — Connect the existing deterministic components

Add thin worker operations around the components already present in the
repository.

#### Prepare generation

For one selected sheet:

1. parse the workbook;
2. build the sheet summary and compact context;
3. build the structural and format-aware region catalogue;
4. obtain eligible ML cell-role and header-direction hints when enabled; and
5. render the pinned V13 semantic-map prompt.

#### Interpret and execute

For one Luna response:

1. parse the semantic map strictly;
2. compile it deterministically into RecipeV01;
3. validate the recipe;
4. execute it against the exact workbook bytes;
5. produce tidy rows and source-cell evidence; and
6. return structured success or failure data.

TypeScript continues to own deterministic workbook, prompt, semantic-map,
RecipeV01, execution, and validation behaviour. Python continues to own effects,
provider dispatch, budgets, custody, decisions, and orchestration.

**Done when:** the full provider-free path works through stable worker contracts
without importing or executing code from the TidyCell sibling repository.

### Step 5 — Prove the wiring in replay mode

Before making fresh provider calls, run the complete path with saved provider
responses that are eligible for replay.

Replay must create the same kinds of artifacts as a live run:

- parsed semantic map;
- compiled recipe;
- execution output;
- acceptance report;
- semantic observations;
- exception record when appropriate; and
- combined dataset.

This step tests the software integration without spending money. Replay evidence
is not proof that fresh generation works.

**Done when:** one command processes all three frozen sheets in replay mode and
repeated runs produce the same deterministic artifacts and decisions.

### Step 6 — Add bounded fresh generation with Luna

Use only:

```text
model: openai-codex/gpt-5.6-luna
reasoning: high
```

The live provider gateway must:

- have no general repository access or arbitrary tools;
- receive only the pinned prompt inputs for one work unit;
- enforce a small fixed campaign budget;
- reserve the maximum possible cost before dispatch;
- record ambiguous dispatch separately from a safe failure;
- never blindly retry a possibly dispatched call;
- allow at most one correction for semantic-map parsing, region resolution, or
  geometry compilation failure; and
- make no second provider call for output-level acceptance failures.

A practical initial ceiling is three normal calls plus at most three permitted
correction calls, with a hard campaign budget chosen and recorded before the
run. No live call is authorized merely by this plan; provider execution starts
only after replay, budget, security, and explicit run-authorization checks pass.

ML hints remain optional and non-binding. Any active model package must be
explicitly eligible, safe to load, pinned by digest, and proven to exclude all
three target workbook digests from its training data. If that cannot be proved,
run the Luna-only path rather than using an ineligible model.

**Done when:** Luna freshly generates a candidate for each selected sheet, and
every attempt is budget-bound and reproducible from restricted evidence.

### Step 7 — Run automatic checks and route exceptions

Run the following checks after deterministic execution.

#### Structural checks

- semantic map and RecipeV01 are schema-valid;
- execution succeeds;
- deterministic replay gives identical output;
- output is non-empty and within expected bounds;
- required columns and dimensions are present;
- observation keys are unique;
- source ranges have no unintended overlap;
- source cells are not reused unexpectedly; and
- required table coverage is complete.

#### Semantic checks

- every dimension value maps to an allowed code;
- jurisdiction, Indigenous status, sex, and legal status use the pinned code
  lists;
- measure, unit, population, and reference date are correct;
- totals and components agree where the acceptance contract defines an equation;
- totals are represented as explicit rollups, not ordinary members;
- observed zero remains numeric, while any missing, suppressed, or
  not-applicable marker routes to exception until this family has an explicit
  pinned marker mapping; and
- no unknown warning or ambiguous mapping is ignored.

The decision is mechanical:

```text
all required checks pass
→ prototype_auto_accepted
→ include in the combined dataset

any required check fails or remains uncertain
→ exception_required
→ exclude from the combined dataset
→ create a review packet
```

Normal passing results require no approval click. Human review is for exceptions,
policy changes, and later promotion of data to training gold. Automatic
acceptance does not make a recipe eligible for ML training.

**Done when:** valid results pass without human action, while deliberately broken
fixtures reliably enter the exception queue.

### Step 8 — Standardise and combine accepted observations

Map raw output labels to canonical identifiers while preserving the original
labels. Use the pinned table-family schema and code lists rather than guessing.

For every accepted row, record:

- canonical observation identity;
- raw and canonical dimension values;
- value and value status;
- workbook digest and publication identity;
- sheet and source cell or range;
- recipe and execution digests; and
- acceptance-policy version and decision digest.

Then combine accepted observations from all three years into one sorted dataset.
The collation report must list:

- included workbooks and row counts;
- excluded exceptions;
- duplicate canonical keys;
- conflicting values;
- unmapped labels;
- missing expected categories; and
- all code-list or schema failures.

Never include an exception in the accepted combined dataset merely to make the
three-year output complete.

**Done when:** at least two real years pass and combine successfully, and any
non-passing year remains clearly visible as an exception.

### Step 9 — Provide one command and a Dagster view

Expose the complete workflow through one command, conceptually:

```sh
scripts/tidy-prototype run \
  --cohort fixtures/product-prototype/prisoners-table-30-2023-2025.json
```

The exact command name may follow existing CLI conventions, but it must run
directly and be covered by an operational test.

Project the same stages, checks, artifacts, and exception states into Dagster.
Dagster remains replaceable and non-authoritative: stopping or rebuilding its UI
must not lose product decisions or artifacts.

**Done when:** the CLI completes independently and Dagster accurately displays
the same run without becoming the source of truth.

## 6. Required negative tests

The prototype must include deliberately invalid fixtures or mutations proving
that automatic review is real. At minimum test:

1. an unknown legal-status code;
2. a duplicate canonical observation key;
3. a missing required dimension;
4. an inconsistent total;
5. unintended source-cell reuse or range overlap;
6. an unsupported or ambiguous semantic mapping;
7. a malformed Luna response;
8. a valid-looking recipe that executes to empty output; and
9. a second run whose deterministic output differs.

Each case must create a structured exception and must not enter the combined
accepted dataset.

## 7. Definition of prototype completion

Do not call the product prototype complete until a clean, independently checked
run proves all of the following:

- [x] Exactly three real, related workbook sheets are bound by the cohort
  manifest.
- [x] `openai-codex/gpt-5.6-luna` freshly generated all three candidate recipes
  without seeing the historical recipes or outputs.
- [x] Each candidate compiled into valid RecipeV01 and ran against its bound
  prototype workbook. The 2025 prototype workbook is a deterministic formatting
  normalization of the generation-time source; exact source-byte identity is not
  a hobby-prototype completion gate.
- [x] Re-running an accepted recipe requires no provider call and gives identical
  deterministic output.
- [x] Passing results were accepted automatically without routine human review.
- [x] Deliberately invalid results are routed to the exception queue.
- [x] All three real years are included in one combined dataset.
- [x] Every combined row passes the pinned schema and code-list checks.
- [x] Duplicate keys, conflicts, omissions, and unmapped values are explicitly
  reported.
- [x] Every combined value can be traced to its workbook, sheet, source cell,
  recipe, execution, and acceptance decision.
- [x] Provider prompts and responses remain restricted.
- [x] Provider cost stayed within the recorded hard campaign limit.
- [x] The whole workflow runs from one tested command.
- [x] Dagster displays checked replay and live-evidence states without owning the
  authoritative records.
- [x] Historical replay artifacts remain separate and non-authoritative; they
  were not inputs to fresh generation or automatic acceptance.

## 8. Work deliberately deferred

Do not make these prerequisites for the prototype:

- the complete 44,682-item import;
- NAS storage, NAS backup, or NAS deployment;
- production source-of-truth cutover;
- a polished review website;
- processing every table in the Prisoners publication;
- adopting the complete justice semantic model;
- Sembla execution or calibration;
- broad provider campaigns;
- new ML training beyond what is strictly needed for an eligible optional hint
  package; or
- public publication of the combined data.

## 9. Safety and authority boundaries

This prototype does not change the following rules:

- Luna proposes structure; it does not define acceptance truth.
- ML hints are suggestions, not authority.
- TypeScript owns deterministic spreadsheet and recipe semantics.
- Python owns provider effects, budgets, custody, and decisions.
- The deterministic worker remains network-denied and production-isolated.
- Automatic acceptance is specific to the pinned table-family contract and does
  not create human approval or training eligibility.
- Unknown or unsupported semantics route to exception review.
- Historical reviewer identity, approval targets, and provenance are never
  inferred.
- Existing source repositories, frozen manifests, and source bytes remain
  unchanged.

## 10. Implementation record

The provider-free milestone and the bounded live campaign are complete.

- Cohort manifest:
  `fixtures/product-prototype/prisoners-table-30-2023-2025.json`
- Acceptance contract:
  `fixtures/product-prototype/acceptance/prisoners-table-30-v1.json`
- Worker operations: `prepare-semantic-map-v13` and
  `interpret-semantic-map-v13`
- CLI: `scripts/tidy-prototype run`
- Dagster assets: `product_prototype_replay`,
  `product_prototype_live_evidence`, and `product_prototype_stage_projection`
  (per-workbook prepare, generation, interpretation, execution, validation,
  decision, exception, and collation states)
- Checked live evidence:
  `fixtures/product-prototype/live-evidence/manifest.json`
- Live evidence manifest digest:
  `sha256:3348045777ba9fff77da9f4d10978b2259f1675df5bf713080720204145cf675`
- Model: `openai-codex/gpt-5.6-luna`, high reasoning
- Fresh calls: 3; corrections: 0
- API-equivalent cost: USD 0.0197296
- Result: 3 automatically accepted workbooks, 0 exceptions, and 729 collated
  canonical observations
- Every canonical row carries publication, workbook, sheet, source-cell,
  recipe, execution, acceptance-policy, decision, prompt-package, model, and
  generation-attempt identities.
- `collation-report.json` explicitly records inclusions, exclusions, duplicate
  keys, conflicts, unmapped labels, missing categories, and schema/code-list
  failures, including empty lists for clean categories.
- All nine required negative classes are tested for structured exception
  creation and exclusion; malformed provider output is exercised through the
  real end-to-end interpretation path.
- Raw prompts and provider envelopes remain restricted and are not committed as
  ordinary evidence. Their digests, the settled ledger state/cost, executable
  digest, authorization digest, and the exact originally authorized cohort
  digest are bound by `campaign-evidence.json`.
- The live calls used the originally authorized cohort
  `sha256:77c770fca86b691e2c94e658ec0f4c0027a5494628805a2d9da201cf47f32f63`.
  The checked prototype run uses current cohort
  `sha256:6d3ab88366b1e52c6e3fc58e0197e0c565a0a6e2c024b6335137efab8e7d84fc`.
  Its 2025 workbook applies the recorded
  `trim-pathological-full-width-formatting-merge-v1` normalization so a
  formatting-only `A47:XFD47` merge is bounded to the meaningful table width.
  The semantic map is reused because this transform does not change Table 30's
  values or layout semantics. Both identities remain explicit; this is accepted
  as proportionate provenance for the hobby prototype and is not production
  custody or activation evidence.

The live candidates were generated without historical recipes or outputs in
their prompts. The replay fixtures remain explicitly non-authoritative. The
human-authored table-family contract, not Luna or replay gold, made each
acceptance decision.

## 11. Milestone outcome

The first provider-free milestone completed before live dispatch. The exact
live-run authorization then bound the cohort, V13 prompt contract, Pi executable,
Luna/high settings, six-call ceiling, USD 2 ceiling, work units, and expiry.
Three normal calls completed; no correction slot was used. The checked evidence
above is the result of that separately authorized campaign.

## 12. Five-year provider-free expansion

The first post-prototype expansion adds the matching 2021 and 2022 Table 30
workbooks without altering the original three-workbook live campaign. The
expanded cohort is
`fixtures/product-prototype/prisoners-table-30-2021-2025.json`.

The 2021 and 2022 semantic-map responses are existing Sol/high research
artifacts; the 2023–2025 responses remain the checked Luna replay fixtures.
Every response is explicitly non-authoritative. The same deterministic worker
and human-authored Table 30 acceptance contract decide whether each year enters
the combined output. No new provider call was made for this expansion.

The checked replay at `fixtures/product-prototype/five-year-evidence/` records:

- five automatically accepted workbooks and zero exceptions;
- 243 canonical observations per year and 1,215 observations overall;
- no duplicate keys, conflicts, missing categories, unmapped labels, schema
  failures, code-list failures, or cross-year issues; and
- run digest
  `sha256:8a40f31314de3a2ddfe12343085aced377b84379e03c1c5f17211f5440c564bd`.

The standalone CLI and `product_prototype_replay` Dagster asset now use the
five-year cohort. The original checked live-evidence and stage-projection assets
remain unchanged so historical live claims are not rewritten.

## 13. Five-year Table 21 age expansion

The next provider-free product slice processes Table 21 for 2021–2025:
prisoner counts by jurisdiction, Indigenous status, sex, and age group. The
cohort is `fixtures/product-prototype/prisoners-table-21-2021-2025.json`; all
five replay responses are existing Sol/high artifacts and remain
non-authoritative.

Table 21 contains three kinds of values in one grid. The independent
`acceptance/prisoners-table-21-v1.json` contract deliberately accepts only
prisoner counts. It maps and checks every dimension, then excludes the
imprisonment-rate column and the mean/median age summary rows. Those exclusions
are explicit in the cohort evidence rather than silently discarded.

The checked replay at
`fixtures/product-prototype/table-21-five-year-evidence/` records:

- 6,732 deterministic raw values;
- 1,467 explicitly excluded auxiliary rate or age-summary values;
- 5,265 canonical prisoner counts (1,053 per year);
- five automatically accepted workbooks, zero exceptions, and zero cross-year
  issues; and
- run digest
  `sha256:231de80ca4925e6784d9bf81c2bbf8615c8ce41aac52237211bedce31140c4f6`.

The cohort raises only the bounded warning-descriptor ceiling from 10,000 to
20,000 because the conservative pre-execution upper bound for this larger table
exceeds the original limit; actual executions emitted no warnings. The
standalone CLI and the replaceable `product_prototype_age_replay` Dagster asset
both expose this run without making provider calls.

## 14. Minimal data-asset status projection

`Tidy Data Asset Status` is a deliberately read-only consumer of the checked
Table 21 and Table 30 evidence. The explicit registry at
`fixtures/product-prototype/data-asset-status-v1.json` selects ten sheet-assets
across five shared physical workbooks. For each sheet it derives independent
`Identified`, `On disk`, `Tidied`, `Canonicalised`, and `Integrated` facts and a
separate automated-check result. Missing current source custody does not erase
historical processing evidence; it creates a visible contradiction instead.

Python standard-library code generates the self-contained, deterministic
snapshot at `docs/data-asset-status/index.html`. Vanilla JavaScript supplies
sorting, core filters, text search, and inline evidence details without adding
a frontend framework or API. The tiny foreground server exposes only `/`,
`/index.html`, and `/healthz` on `127.0.0.1:3031`; a separately controlled,
exactly scoped Tailscale Serve route can expose the same page to the Tailnet.
Dagster links remain operational conveniences, not evidence authority. CI runs
the deterministic snapshot drift check, and neither page generation nor serving
makes provider calls.

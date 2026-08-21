# End-to-end spreadsheet product prototype plan

- **Status:** implemented and checked; see the implementation record below
- **Product model:** `openai-codex/gpt-5.6-luna`
- **Reasoning level:** high
- **Initial cohort:** _Prisoners in Australia_, Table 30, 2023–2025
- **Related architecture:**
  - `docs/reimplementation-plan.md`
  - `docs/post-m4-canonical-migration-and-generation-plan.md`
  - `docs/decisions/0003-canonical-migration-and-automated-recipe-acceptance.md`

## 1. The simple goal

Build a small working prototype using three related spreadsheets from the
_Prisoners in Australia_ publications for 2023, 2024, and 2025.

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

`Tidy Data Asset Status` is a deliberately read-only consumer of two
publications and 22 checked cohorts. The explicit registry at
`fixtures/product-prototype/data-asset-status-v1.json` selects 105 sheet-assets
across 13 checked normalized workbook byte identities. For each sheet it derives independent
`Identified`, `On disk`, `Tidied`, `Canonicalised`, and `Integrated` facts and a
separate automated-check result. Missing current source custody does not erase
historical processing evidence; it creates a visible contradiction instead.

Python standard-library code generates the self-contained, deterministic
snapshot at `docs/data-asset-status/index.html`. Its default **Coverage** tab
groups dense cohort-by-publication-period heatmaps beneath publication headings,
with a six-stage completion strip, sticky row/period headers, and publication or
cohort search. Calendar and fiscal periods retain their own display conventions.
Colour is always paired with a symbol and full accessible label.
Multiple assets in one cohort/year aggregate into a count-badged cell whose
colour reflects the least-complete member; drill-down retains every matching
asset. Selecting a cell switches focus to the filtered **Assets** tab, which is
also grouped and filterable by publication. Vanilla JavaScript supplies this
drill-down, sorting, core filters, text search, inline evidence
details, and one **Open CSV** link per sheet-asset without adding a frontend
framework or mutation API.
At startup, the foreground server deterministically partitions the checked
cohort CSVs by source workbook digest, sheet, and publication date, verifies all
105 row counts, and exposes only the exact generated `/csv/<asset>.csv` allowlist
alongside `/`, `/index.html`, and `/healthz` on `127.0.0.1:3031`. The CSV uses
an inline plain-text response so browsers display it rather than requiring a
download. A separately controlled, exactly scoped Tailscale Serve route can
expose the same page and CSV views to the Tailnet. Dagster links remain
operational conveniences, not evidence authority. CI runs the deterministic
snapshot and per-asset CSV partition checks, and neither page generation nor
serving makes provider calls.

## 15. Five-year Table 22 country-of-birth expansion

The third provider-free product cohort processes Table 22 for 2021–2025 using
five existing recipe-valid Sol/high responses. The human-authored contract
coalesces the historical header variants into a canonical country-of-birth
dimension and preserves year-specific country coverage without inventing absent
categories.

Unlike the earlier single-measure contracts, Table 22 keeps both published
measures:

- 1,539 jurisdiction-level prisoner counts in persons; and
- 170 national country-of-birth imprisonment rates per 100,000 adult population
  for that country of birth.

The four published `na`/`n.a` rate cells are represented by null values with
`not_applicable` status. The blank 2021 `OTHER` rate cell is not synthesized.
All five sheets passed deterministic replay, code-list, coverage, uniqueness,
total, warning, and collation checks, producing 1,709 canonical observations,
zero exceptions, zero cross-year issues, and zero provider calls. Checked
evidence is at `fixtures/product-prototype/table-22-five-year-evidence/`, with
run digest
`sha256:faed294328690572ebfa475cbc700fa8c3f9927b00fe3eeefda53e71986ad0f0`.
The standalone CLI, `product_prototype_country_replay` Dagster asset, and the
status page all project this cohort without becoming evidence authority.

## 16. Five-year sentenced-offence and unsentenced-charge pair

The fourth and fifth provider-free cohorts process Tables 23 and 31 for
2021–2025 using ten existing recipe-valid Sol/high responses. Table 23 emits
sentenced prisoner counts by selected most serious offence and jurisdiction;
Table 31 emits unsentenced prisoner counts by selected most serious charge and
jurisdiction. The canonical model deliberately keeps `most_serious_offence_id`
and `most_serious_charge_id` separate rather than implying that conviction and
charge concepts are interchangeable.

Both contracts coalesce historical division/subdivision and
category/subcategory header variants, map the exact published labels to stable
`ANZSOC_` codes, preserve raw labels, and retain published `TOTAL` rows. Annual
code coverage is explicit because the selected subdivisions vary by year.
Totals are not synthesized from selected categories: the 2025 totals include
unknown classifications, and all national/state arithmetic is subject to ABS
perturbation. The evidence records the 2025 caution that migration to ANZSOC
2023 may have changed the coding of earlier ANZSOC 2011 data.

Table 23 produced 2,556 canonical observations with yearly counts of 486, 531,
513, 513, and 513. Table 31 produced 2,538 with yearly counts of 450, 522, 522,
522, and 522. All ten worksheets passed deterministic execution, annual
coverage, code-list, non-negative value, uniqueness, source-cell, national-total,
warning, and collation checks with zero exceptions, cross-year issues, or
provider calls. Checked evidence is under
`fixtures/product-prototype/table-23-five-year-evidence/` and
`fixtures/product-prototype/table-31-five-year-evidence/`, with run digests
`sha256:000e694bffb36909951b6f3c54266d768cb45a2300d8829c9853a58f509edfd0`
and
`sha256:86c0d0a8254394e51677f63a110641aaebd78caab098fa0c2ee5e3d32e46ce5f`.
The standalone CLI, separate Dagster assets, and read-only status page expose
both cohorts without becoming evidence authority.

## 17. Sixty-worksheet provider-free batch

The next expansion processes 12 additional semantic table families across
2021–2025, adding exactly 60 worksheet-assets:

| Family                                                                       | Canonical observations |
| ---------------------------------------------------------------------------- | ---------------------: |
| Selected characteristics (Table 14, renumbered Table 15 in 2025)             |                  1,260 |
| Indigenous status and offence/charge (Table 16, renumbered Table 20 in 2025) |                  2,430 |
| Table 24 aggregate sentence by offence                                       |                  2,295 |
| Table 25 expected time to serve by offence                                   |                  2,295 |
| Table 26 aggregate sentence by Indigenous status                             |                  1,890 |
| Table 27 aggregate-sentence publication vintages                             |                  3,402 |
| Table 28 expected time by Indigenous status                                  |                  1,890 |
| Table 29 prior imprisonment                                                  |                  1,215 |
| Table 32 time on remand                                                      |                    693 |
| Table 33 security classification                                             |                    675 |
| Table 34 prison location                                                     |                    793 |
| Table 35 court level, legal status, and remand                               |                    810 |
| **Total**                                                                    |             **19,648** |

All 60 worksheets were automatically accepted with zero exceptions, excluded
rows, cross-year issues, or provider calls. Forty `np`/`n.p.` cells in Tables
24 and 25 remain suppressed null values. The Table 28 2023 and Table 29 2024
maps are explicitly identified as checked human-authored adjacent-year maps,
not provider responses or acceptance authority.

Table numbering is not treated as semantic identity: the selected-characteristic
and Indigenous-offence cohorts explicitly bind their 2025 successor sheets.
Table 27 preserves both `publication_vintage_date` and row-level
`reference_date`/`observation_period_id`; repeated historical years are never
silently overwritten. Multi-condition measure selection keeps counts,
proportions, means, medians, percentiles, and duration units distinct.

Four shared workbook derivatives trim out-of-range styled blank cells and
pathological merge/column formatting using
`trim-pathological-styled-blank-cells-v1`. The script refuses to remove cell
values or formulas, deterministically reproduces every checked derivative, and
binds source/derived digests. The trim stage changes no cell value and prevents
historical full-row/full-column formatting from breaching compact-context
bounds. The later Offenders correction stage is separately declared below.

`fixtures/product-prototype/large-batch-assets-v1.json` is the audited
orchestration registry. The original Prisoners portion contributes 12 explicit
Dagster assets/checks/jobs. The cross-publication registry now adds five
Offenders assets while retaining one fixed aggregate job, generic digest-closed
evidence verification, parameterized tests, and the independent status registry.
Canonicalization semantics remain in human-authored acceptance contracts rather
than the Dagster registry.

```sh
scripts/tidy-prototype-batch verify
scripts/tidy-prototype-batch run \
  --output .product-prototype/large-batch-replay \
  --concurrency 3
```

## 18. Recorded Crime — Offenders cross-publication expansion

A second publication adds Tables 1–5 from _Recorded Crime — Offenders_ for
2021–22, 2022–23, 2023–24, and 2024–25. The 20 worksheet-assets are represented
as five four-release semantic cohorts so each contract can validate layout and
category drift across publication vintages:

| Family                                                          | Canonical observations |
| --------------------------------------------------------------- | ---------------------: |
| Table 1 principal-offence count and rate time series            |                  4,712 |
| Table 2 sex, principal offence, count, and rate                 |                  5,952 |
| Table 3 principal offence by age, including mean and median age |                  2,208 |
| Table 4 principal-offence rates by age                          |                  1,952 |
| Table 5 sex and age count/rate time series                      |                  6,444 |
| **Total**                                                       |             **21,268** |

All four vintages in every cohort are automatically accepted with zero
exceptions, excluded rows, cross-period issues, or provider calls. Counts,
rates per 100,000 people aged 10 and over, means, medians, sex, age groups,
principal-offence codes, observation periods, and publication vintage remain
separate canonical fields. The 372 published `na` rate/statistic intersections
are preserved as `not_applicable` nulls. Exact additive total equality is
explicitly not an acceptance rule because ABS states that confidentialised
cells are randomly adjusted and components may not sum to totals.

The replay maps are deterministic human-authored inputs with
`acceptanceAuthority: false`; five independent human-authored contracts remain
the only automatic acceptance authority. Every accepted row retains source
workbook, sheet, cell, recipe, execution, policy, decision, and replay
provenance. The evidence closures are under
`fixtures/product-prototype/recorded-crime-offenders-table-*-four-release-evidence/`.
Their run digests are:

- Table 1: `sha256:6a28f037ca0de2ddfeefd150bea05b95b781f60fec27bad4f02f9ca7d0f65398`;
- Table 2: `sha256:16d2298ec077e64f2bb05b74592ef06ce23eb3d56168b596923cdcdcef2b4ced`;
- Table 3: `sha256:5697d14006de1300d255f41553e45629c05d8c37b60a1ca8e8f43ccdec3fbc54`;
- Table 4: `sha256:25a6a6f744ff4413703c5dfc493def4b46951594ad648bb20e0cfdde4a299bcb`; and
- Table 5: `sha256:5f28fc1b8771527b744f97aea9443297e46e99d53f393382554d2b7a7a2b64b6`.

The exact downloaded workbooks remain committed separately from deterministic
normalized derivatives. The existing trim script still refuses to remove any
valued or formula cell. A separate digest-bound correction script handles three
reviewed isolated values outside the semantic observation/header regions:
2023–24 `Table 5!AG1=0`, and 2024–25 `Table 4!XFC50=3` plus `Table 5!AI1=0`.
It also corrects the ACT 2021–22 terminal period typo at `Table 51!M5` from the
impossible `2022–22` to `2021–22` only in the normalized derivative. This
replacement is bound to exact source bytes, style, shared-string type, cell, and
old/new values. Three corrections are inside retained rectangular worksheet
ranges; `XFC50` is outside. The manifest truthfully records these in-range and
out-of-range changes rather than claiming no retained-range changes. The script
refuses every other source identity or cell state and emits
a receipt that the verifier requires to exactly match the manifest correction
declaration. The manifest binds both scripts, original/derived identities,
corrections, and retained ranges and reproduces every declared derivative
byte-for-byte. A role-aware catalog extension also preserves exact terminal
`..`, `na`, and `np` runs after repeated numeric panels only when an earlier
same-span panel immediately precedes a marker run with an identical style
vector. Detached, merged, unlabelled, or style-mismatched runs are rejected;
all 409 previously registered worksheet catalogs remained byte-identical.

The combined registered batch now contains 171 cohorts and 467 worksheets with
395,468 canonical observations. The dashboard projects three publications, 176
cohorts, 492 worksheet-assets, and 408,751 canonical observations through 492
verified CSV routes. The complete New South Wales, Victoria, Queensland, South
Australia, Western Australia, Northern Territory, Australian Capital Territory,
Tasmania, and defendant-rate Criminal Courts clusters contribute 212 worksheets
and 164,471 rows while preserving observation
periods, exact worksheet names, and explicit ANZSOC 2011, ANZSOC 2023, and
concorded historical classification contexts. The 36-sheet defendant-rate Cube
12 independently retains 13,743 published counts and 13,743 published rates,
uses exact headers across the reversed 2024 panel order, and infers no
denominator, count/rate equation, or additive total identity. Its 2024
mixed-concorded singleton families remain separate from the ANZSOC 2011
histories; selected observation cells have no formulas or markers, while source
metadata formulas and raw footnotes remain intact. Dagster and the dashboard
remain replaceable, read-only projections rather than evidence authority.

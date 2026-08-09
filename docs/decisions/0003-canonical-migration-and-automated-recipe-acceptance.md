# ADR 0003: canonical TidyCell migration and automated recipe acceptance

- Status: accepted direction; implementation remains staged and gate-bound
- Date: 2026-08-09
- Supersedes: no accepted M0-M4 behavior
- Refines: the package assumptions for horizon M5-M8 and the historical-import
  portions of M10 in `docs/reimplementation-plan.md`; it does not revise the
  semantic adoption authority of M7-M8

## Context

TidyCell contains the working source estate for the next `tidy-dagster` phase:
downloaded workbooks, approved and generated RecipeV01 artifacts, generation and
review evidence, conventional ML models, prompt patterns, and the Pi-backed
ML-assisted GPT-5.6 Sol workflow. The estate is large, path-duplicated, partly
uncommitted, and contains both operational artifacts and research history.

The user wants `tidy-dagster` to carry this estate forward while minimising
per-recipe human approval. The user has found the XGBoost-assisted, high-reasoning
Sol workflow reliable enough to make strict automated checks the normal approval
path. Duplicate observations/source cells, codelist membership, and expected
totals are especially important acceptance signals.

The existing M0-M4 implementation remains deliberately standalone and
provider-free. Dagster is an operational projection, TypeScript owns workbook and
RecipeV01 semantics, and Python owns repositories, orchestration, process
launching, and future ML/provider integration. M2 remains unaccepted until the
reviewed summary/prompt-input closure is present.

## Decision

### 1. Migrate canonically, with complete evidence

`tidy-dagster` will import every in-scope unique content object once by SHA-256,
while preserving every known source path, URL, custody record, lifecycle event,
and relationship as immutable metadata.

This is not a literal path-for-path duplicate mirror. Identical bytes have one
content identity and multiple aliases. The migration must nevertheless reconcile
every source item to one explicit disposition:

- imported;
- duplicate alias;
- excluded development/cache material with a reason; or
- quarantined because evidence is incomplete or invalid.

The import source is a frozen point-in-time export of the current TidyCell
filesystem. It may include uncommitted and ignored domain artifacts, but it must
never depend on the mutable sibling worktree at runtime.

### 2. Preserve the full recipe lifecycle

Carry forward approved, generated, repaired, failed, invalid, deferred,
superseded, and incomplete recipe evidence where discoverable. Preserve raw
provider responses and rendered prompts as restricted evidence when present.
Do not infer approval from the presence of a recipe file.

Historical approvals with a reviewer value resolved through an attributable
reviewer-identity registry plus digest evidence remain `human_approved`. A
nonblank free-text label is not automatically an identity: misspellings,
judgement labels, unknown aliases, and unresolved people remain
`legacy_approved_unattributed`. Legacy rows that lack reviewer and/or
workbook/recipe digests receive the same state. They are preserved but are not
fabricated into attributable approvals or training gold. Newly generated recipes
may become `auto_accepted`. These are different decision types and must never be
serialized as each other.

The source `approvals.json` is a mutable point-in-time projection, not an
append-only history. Migration preserves exactly what is observable in the frozen
snapshot. It cannot reconstruct approval removals, earlier values, rejections, or
revocations that TidyCell already overwrote or deleted.

### 3. Automated acceptance may update the effective recipe pointer

A versioned policy engine may activate a recipe without a per-recipe human click
only when every required immutable gate succeeds against exact pinned inputs.
Any missing oracle, unallowlisted warning, drift, ambiguity, or failed check
routes the recipe to exception review.

An imported human or legacy approval is preserved as a historical authority
record, but operational activation in `tidy-dagster` still requires an
unambiguous resolution to exact workbook bytes and sheet identity plus
compatibility with current execution and safety gates. A newly auto-accepted
recipe must not silently displace a currently effective human-approved recipe.
A lossy asset-name match or mutable `latest-release` path is insufficient proof.

### 4. Every operational workbook receives a manually curated acceptance manifest

For each imported workbook digest intended for operational processing, a human
curator will define the independent rules used to judge generated recipes. The
manifest may cover several sheets and tables, but it is specific to one exact
workbook content digest and one manifest revision. Archival/non-operational
workbooks are preserved without a manifest only through an attributable explicit
archive disposition.

It must be capable of specifying:

- included and excluded sheets;
- expected table blocks or permitted source ranges;
- required dimensions and unique observation keys;
- codelist identifiers, versions, members, and permitted subsets;
- expected category cardinalities and coverage;
- total/component equations and rounding tolerances;
- unit, scale, universe, and reference period;
- missing, not-applicable, suppressed, confidential, observed-zero, and
  structural-zero semantics;
- whether totals are observations, checks, or excluded cells;
- permitted source-cell reuse, overlap, and warning codes.

The ML model or LLM response cannot author the oracle that accepts its own
output.

### 5. Only human-approved recipes may train new ML models

For every training or retraining run after this ADR, only approvals with a
resolved reviewer identity and the required digest evidence may enter the
training snapshot. `auto_accepted`, `legacy_approved_unattributed`, unresolved,
and unattributed recipes remain ineligible unless a later attributable human
decision promotes them. Benchmark gold and training authority remain distinct
from automated operational acceptance.

Existing pre-ADR XGBoost artifacts may be considered only for the separate
`legacy_hint_eligible` class. Promotion requires complete disclosure and
classification of their historical corpus, exact target-workbook exclusion,
licence review, isolated-runtime prediction parity, and a destination promotion
decision. This exception permits only compact non-binding hints; it does not
relabel historical training as policy-conformant, create gold, or authorize those
rows for future training.

### 6. Preserve all models and prompts, but activate only pinned eligible versions

Model packages include bytes, feature schema, available environment evidence,
training and split manifests, leakage evidence, metrics, licensing, and
promotion status. Prompt packages include source, dependencies, rendered-message
reconstruction, examples, rule tiers, ML/context projection, tests, and
evaluation evidence.

Research, obsolete, incomplete, legacy-unreproducible, and non-commercial
artifacts may be archived but cannot become runtime-active. A missing historical
lock, seed, licence record, or promotion decision is recorded as missing rather
than invented. Runtime selection requires an explicit content-digest-bound
promotion manifest and prediction-parity evidence under a newly pinned isolated
inference runtime.

### 7. The active generation path is the ML-assisted V13 semantic-map workflow

The intended active path is:

1. deterministic workbook summary, compact context, and formatting facts;
2. XGBoost cell-role and header-direction suggestions with exact target-workbook
   SHA-256 exclusion; this does not claim adjacent-year or publication-family
   independence;
3. the versioned V13 role-aware semantic-map prompt;
4. Pi using `openai-codex/gpt-5.6-sol` with high reasoning;
5. strict semantic-map parsing;
6. deterministic TypeScript compilation to RecipeV01;
7. execution against the actual workbook and output inspection;
8. at most one correction for the parity V13 policy's pre-execution
   region-resolution or geometry compilation failures; and
9. execution, strict automated acceptance, or exception review.

Output-level duplicate, codelist, total, or semantic failures do not trigger a
second provider call in the initial pilot. A later post-execution correction
policy would be a new version requiring its own evaluation and authorization.

The deterministic worker remains network-denied. Live Pi execution is a separate
restricted provider gateway with no general tools or repository access.

### 8. Authorize one hard-capped live pilot only after provider-free gates

The first live pilot may spend no more than USD 25 API-equivalent cost. The
budget service must transactionally reserve the maximum possible cost before
dispatch, settle observed usage, conservatively handle missing usage, and prevent
concurrent reservations from overspending.

A timeout or crash after possible dispatch becomes `ambiguous`; it is not
blindly retried. Correction calls are included in both call and cost ceilings.
No live call may occur until replay, fake-provider, concurrency, ambiguity,
budget, security, and independent review gates pass.

## Authority boundaries

| Concern                                                              | Authority                                                         |
| -------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Workbook and artifact bytes                                          | Python-owned immutable content repository                         |
| Workbook/RecipeV01/summary/prompt-input/compiler/execution semantics | Standalone TypeScript domain worker                               |
| ML training, inference launching, model registry                     | Python application boundary; predictions remain non-binding       |
| Pi launch, credentials, attempts, ambiguity, and budget              | Restricted Python provider gateway and authoritative repositories |
| Workbook acceptance assertions                                       | Attributable human-curated immutable manifest                     |
| Automated activation                                                 | Versioned policy decision over immutable gate evidence            |
| Human approval                                                       | Separate attributable human decision                              |
| Effective recipe                                                     | Compare-and-swap pointer advanced only after the applicable gates |
| Dagster                                                              | Replaceable operational projection only                           |
| External publication                                                 | Not authorized by this ADR                                        |
| Justice semantic adoption, calibration, and Sembla                   | Not authorized by this ADR                                        |

## Consequences

### Positive

- The complete TidyCell evidence estate can move without retaining runtime
  coupling to TidyCell.
- Duplicate source copies do not multiply authoritative identities.
- Most recipes can become usable without repetitive approval clicks.
- Human effort moves to workbook-level oracle curation and genuine exceptions.
- Automated outputs cannot silently contaminate training gold.
- Provider cost and ambiguous side effects remain bounded and auditable.

### Costs and limitations

- Manually curating every workbook acceptance manifest is substantial work.
- The current disk has limited free capacity; a dry-run size and deduplication
  report must pass before copying large research/model evidence.
- Historical artifacts may lack raw prompts, responses, or complete provenance
  and therefore require quarantine rather than activation.
- Full prompt parity requires the missing summary and prompt-input closure.
- Public ABS workbooks may be eligible for the live pilot, but non-public or
  sensitive workbooks remain provider-blocked without separate data-egress
  authorization.

## Explicit non-decisions

This ADR does not:

- authorize public publication;
- authorize ML retraining from auto-accepted recipes;
- adopt the justice semantic scaffold;
- select or execute Sembla;
- authorize calibration or simulation;
- make Dagster an evidence or approval authority;
- permit unrestricted Pi tools, filesystem access, or networking; or
- remove the requirement for independent review before the live pilot.

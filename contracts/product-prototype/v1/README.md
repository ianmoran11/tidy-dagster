# Product prototype contracts

`tidy.product-prototype-cohort/v1` binds an ordered cohort of one to twelve
related workbooks, including honestly singleton or discontinued publication
families, their source bytes and sheets, the independent table-family
acceptance contract, the V13 prompt contract, and
`openai-codex/gpt-5.6-luna` with high reasoning and hard call/cost ceilings.
The original live milestone remains the three-workbook 2023-2025 cohort; the
provider-free expansion adds 2021 and 2022 to form a five-workbook replay.
An optional cohort-level `workerLimits.maxWarnings` supports larger but still
bounded tables; Table 21 uses 20,000 and the reviewed Criminal Courts cluster
uses 100,000 because the conservative warning upper bound counts every possible
header diagnostic. Actual warnings remain independently allowlisted and output
bytes retain their separate hard cap.

Replay responses are non-authoritative integration fixtures. They may exercise
the provider-free interpretation path, but they do not determine acceptance and
must not be treated as fresh Luna evidence.

The Prisoners release inventory, family crosswalk, and membership manifest are
a source-custody and completeness foundation only. They bind the five annual
guides, 17 substantive source cubes, and all 203 numbered data sheets without
claiming semantic extraction for every sheet. Canonical extraction covers
134/203 members, with 69 members pending reviewed semantic contracts. The five
state/territory and five national snapshot cohorts are registered dynamically in
the status snapshot, Dagster assets, and dashboard totals. The provider-free custody check is runnable as
`scripts/tidy-prisoners-release verify`.

The Criminal Courts release inventory applies the same custody/completeness
boundary to 69 downloads, 65 substantive cubes, 198 reviewed semantic families,
and all 430 numbered sheets across 2021–22 through 2024–25. The first 338
registered assets are split where ANZSOC 2011, preliminary ANZSOC 2023, final
ANZSOC 2023, and concorded historical identities cannot safely share one alias
namespace. The remaining 92 sheets stay pending. The preliminary concordance
contract uses the explicit `principal_offence_anzsoc_2011` dimension beside the
ordinary `principal_offence` dimension so the two principal-offence
classifications are not collapsed or mislabeled as offence versus charge. The
complete New South Wales, Victoria, Queensland, South Australia, Western
Australia, Northern Territory, Australian Capital Territory, and Tasmania jurisdiction
contracts add a source-bound `classification_context` dimension so identical
principal-offence labels remain distinct when paired
with ANZSOC 2011, ANZSOC 2023, or the mixed concorded historical series. The
36-sheet defendant-rate Cube 12 keeps published defendant counts and rates per
100,000 persons aged 10 years and over as independent measures. Its contracts
identify panels from exact headers rather than position because 2024 reverses
them; they infer no denominator, count/rate equation, or additive total identity.
Published total rows remain observations under `totalValidation: not_applicable`,
and the nine 2024 mixed-concorded singletons remain separate from the nine
ANZSOC 2011 histories. Run `scripts/tidy-criminal-courts-release verify` for the
provider-free closure.

The completed safe live-evidence closure is at
`fixtures/product-prototype/live-evidence/manifest.json`. It binds three fresh
Luna/high calls, USD 0.0197296 API-equivalent cost, three automatically accepted
workbooks, zero exceptions, and 729 canonical observations. Raw prompts,
responses, and provider event streams stay under the ignored restricted local
root and are deliberately absent from this ordinary evidence closure.

The runnable entrypoint is:

```sh
scripts/tidy-prototype run \
  --cohort fixtures/product-prototype/prisoners-table-30-2021-2025.json \
  --mode replay \
  --output .product-prototype/five-year-replay
```

The Table 21 age cohort uses
`acceptance/prisoners-table-21-v1.json`. Its explicit selection policy excludes
imprisonment-rate and mean/median-age auxiliary cells before validating 5,265
canonical prisoner counts:

```sh
scripts/tidy-prototype run \
  --cohort fixtures/product-prototype/prisoners-table-21-2021-2025.json \
  --mode replay \
  --output .product-prototype/table-21-five-year-replay
```

The Table 22 country-of-birth contract demonstrates explicit multi-measure
selection. Jurisdiction columns become `prisoner-count` observations in persons;
the separately labelled rate column becomes
`imprisonment-rate-country-of-birth` at national jurisdiction in persons per
100,000 adult population for that country of birth. Published `na`/`n.a` cells
are retained as `not_applicable` rather than coerced or dropped:

```sh
scripts/tidy-prototype run \
  --cohort fixtures/product-prototype/prisoners-table-22-2021-2025.json \
  --mode replay \
  --output .product-prototype/table-22-five-year-replay
```

Tables 23 and 31 use separate `most_serious_offence` and
`most_serious_charge` dimensions. Both map published ANZSOC-style division and
subdivision labels to stable prefixed codes while preserving each raw label and
source cell. Published total rows remain explicit `TOTAL` categories because
they can include unknown classifications and must not be reconstructed from the
selected component rows. National totals are checked against all eight
jurisdictions with the publication's perturbation allowance. The contracts use
annual category coverage because the selected code sets vary by year, and they
do not claim that the 2025 ANZSOC 2023 migration is perfectly comparable with
earlier ANZSOC 2011 coding.

```sh
scripts/tidy-prototype run \
  --cohort fixtures/product-prototype/prisoners-table-23-2021-2025.json \
  --mode replay \
  --output .product-prototype/table-23-five-year-replay
scripts/tidy-prototype run \
  --cohort fixtures/product-prototype/prisoners-table-31-2021-2025.json \
  --mode replay \
  --output .product-prototype/table-31-five-year-replay
```

The 467-worksheet cross-publication batch supports acceptance-policy v1 and v2
without weakening existing cohorts. Policy v1 retains its legacy canonical-JSON
contract digest and behavior unchanged. Policy v2 binds acceptance to the exact
contract-file digest and recomputes decisions from contract-pinned recipe,
workbook, check, and replay-timestamp identities. Northern Territory, Australian
Capital Territory, Tasmania, and the defendant-rate Cube 12 cohorts use v2;
future clusters should use v2.

The shared contract capabilities include:

- multi-measure selection may use an AND conjunction across several dimensions;
- a measure can declare applicable publication years plus reviewed annual
  combination counts and exact combination-set digests for intentionally
  non-Cartesian tables;
- a table without a valid arithmetic identity must explicitly set
  `totalValidation: not_applicable`; an unmarked empty equation list fails;
- Table 27 and the state/territory rolling families declare
  `referenceDateDimension` and `preservePublicationVintage`, making publication
  vintage and row-level observation date separate canonical key fields;
  current-period-only tables may preserve publication vintage without inventing
  a spreadsheet dimension, while their reference date remains the cohort's
  exact publication period;
- `preserveRawValueText` is opt-in for reviewed marker-bearing families and
  retains the exact published marker beside its canonical null status;
- `expectedWarningCountsByYear` can freeze exact reviewed execution-warning
  counts; acceptance, run evidence, and the large-batch verifier must all agree
  before the workbook can pass;
- `strictAliasMatching` prevents unreviewed footnote-suffix inference, while
  `excludeMissingValues` accounts for reviewed non-observation markers; and
- cohort normalization now also recognizes
  `trim-pathological-styled-blank-cells-v1` and the reviewed full-width
  formatting variant, which trim out-of-range styled blanks and pathological
  merge/column formatting while refusing to remove
  cell values or formulas.

The batch registry is
`fixtures/product-prototype/large-batch-assets-v1.json`. Each of its 171 cohort
contracts pins exact annual dimensions, measure applicability, value statuses,
combination counts, and source-header variants. Verification remains
provider-free:

```sh
scripts/tidy-prototype-batch verify
```

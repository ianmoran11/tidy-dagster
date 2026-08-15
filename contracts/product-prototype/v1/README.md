# Product prototype contracts

`tidy.product-prototype-cohort/v1` binds an ordered cohort of two to twelve
related workbooks, their source bytes and sheets, the independent table-family
acceptance contract, the V13 prompt contract, and
`openai-codex/gpt-5.6-luna` with high reasoning and hard call/cost ceilings.
The original live milestone remains the three-workbook 2023-2025 cohort; the
provider-free expansion adds 2021 and 2022 to form a five-workbook replay.
An optional cohort-level `workerLimits.maxWarnings` supports larger but still
bounded tables; Table 21 uses 20,000 because its conservative warning upper
bound exceeds the original 10,000 limit.

Replay responses are non-authoritative integration fixtures. They may exercise
the provider-free interpretation path, but they do not determine acceptance and
must not be treated as fresh Luna evidence.

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

# Product prototype contracts

`tidy.product-prototype-cohort/v1` binds an ordered cohort of two to twelve
related workbooks, their source bytes and sheets, the independent table-family
acceptance contract, the V13 prompt contract, and
`openai-codex/gpt-5.6-luna` with high reasoning and hard call/cost ceilings.
The original live milestone remains the three-workbook 2023-2025 cohort; the
provider-free expansion adds 2021 and 2022 to form a five-workbook replay.

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

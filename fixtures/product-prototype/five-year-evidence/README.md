# Five-year Table 30 replay evidence

This directory records the provider-free expansion of the accepted *Prisoners
in Australia* Table 30 prototype from 2023–2025 to 2021–2025.

The run processed five real workbooks, accepted all five under the same
human-authored table-family contract, produced 243 observations per year (1,215
total), created no exceptions, and reported no cross-year conflicts.

The 2021 and 2022 replay responses came from existing
`openai-codex/gpt-5.6-sol` high-reasoning research artifacts. The 2023–2025
responses are the existing checked Luna replay fixtures. All replay responses
are non-authoritative: deterministic execution and the acceptance contract make
the acceptance decision. This expansion made no provider calls.

Reproduce it with:

```sh
npm run build
scripts/tidy-prototype run \
  --cohort fixtures/product-prototype/prisoners-table-30-2021-2025.json \
  --mode replay \
  --output .product-prototype/five-year-replay \
  --recorded-at 2026-08-14T03:00:00+00:00
```

`manifest.json` binds the committed output files and the cohort manifest.

# Five-year Table 21 age replay evidence

This directory records the provider-free 2021–2025 replay of *Prisoners in
Australia* Table 21: prisoner counts by jurisdiction, Indigenous status, sex,
and age group.

All five workbooks passed the independent Table 21 acceptance contract. The
worker extracted 6,732 raw values. The pinned selection policy excluded 1,467
auxiliary values belonging to the imprisonment-rate column or the mean/median
age summary rows, leaving 5,265 canonical prisoner-count observations: 1,053
per year. The canonical `AGE_18_OR_YOUNGER` code preserves the 2025 footnote
that the reported 18-year category may include younger people. No provider
calls were made.

The five replay responses are existing `openai-codex/gpt-5.6-sol`
high-reasoning research artifacts. They are non-authoritative: deterministic
execution and `acceptance/prisoners-table-21-v1.json` determine acceptance.

Reproduce the run with:

```sh
npm run build
scripts/tidy-prototype run \
  --cohort fixtures/product-prototype/prisoners-table-21-2021-2025.json \
  --mode replay \
  --output .product-prototype/table-21-five-year-replay \
  --recorded-at 2026-08-14T06:00:00+00:00
```

`manifest.json` binds the cohort and committed output files.

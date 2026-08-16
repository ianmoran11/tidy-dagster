# table-25 five-year checked replay evidence

This provider-free closure covers 2021–2025 sentenced prisoners by offence and expected-time-to-serve statistics as five independently
accepted worksheet-assets.

It produced 2,295 canonical observations from 2,295
raw values, with zero excluded rows, exceptions, provider calls, or cross-year
collation issues. Measures and value statuses are pinned in `manifest.json`.

Prisoner counts, mean expected time to serve, and median expected time to serve remain separate measures. Twenty published np/n.p. cells are retained as suppressed null values rather than dropped or coerced.

Four shared annual workbook copies use the deterministic
`trim-pathological-styled-blank-cells-v1` normalization to remove out-of-range
styled blanks and pathological merge/column formatting. It refuses to remove
cell values or formulas and deterministically reproduces the checked derivatives.
The 2024 workbook needs no batch normalization. Historical and human-authored replay maps are non-authoritative;
acceptance comes only from deterministic execution and the committed family
contract. Raw prompts and provider envelopes are not included.

Run digest:
`sha256:9ecaae9d955bf4b71773106f1e8cec865829402004754089cb3d89359fb2f7a1`.

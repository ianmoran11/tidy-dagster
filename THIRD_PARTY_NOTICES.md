# Third-party notices and source provenance

## TidyCell deterministic compatibility closure and synthetic fixtures

The workbook/RecipeV01 implementation files identified in
`docs/ported-source-provenance.json` and the nine fixture files identified in
`fixtures/parity/source-manifest.json` were ported or copied from TidyCell commit
`1be6c995fa931e9860468e40490433161b0121cb` under the MIT License:

> Copyright (c) 2026 Ian Moran

The full MIT terms are reproduced in the top-level `LICENSE`. Exact fixture
Git blobs, byte lengths, SHA-256 digests, source paths, copied paths, and
admission milestones are recorded in the machine-readable manifest.
The full-layer compatibility gold was executed independently from a clean,
sparse checkout of that pinned TidyCell commit. The digested runner adds only
evidence serialization and never imports candidate modules; exact source,
runner, toolchain, dependency, command, and output hashes are recorded in
`fixtures/gold/manifest.json`. It is not represented as source-authored gold.

## TidyCell all-approved-gold XGBoost model package

The paired cell-role and header-direction model custody sources, their metadata,
and the exact feature extraction port in the local ML hint integration are from
TidyCell under the MIT License (Copyright (c) 2026 Ian Moran). The full upstream
MIT text is retained at
`vendor/tidycell-ml/all-approved-gold-exclusion-v1/TIDYCELL_LICENSE.txt`.
Exact source, native derivative, conversion, parity, toolchain, cohort, and
package-closure hashes are recorded in that directory's `manifest.json` and
`conversion-receipt.json`. Production code loads only native XGBoost JSON and
never deserializes the retained pickle custody bytes. XGBoost is an optional
local runtime dependency distributed under the Apache License 2.0.

## Tidybank

Tidybank commit `6eed7df0c54a53d4680a5a0551655bf6346d4c7d`
is MIT-licensed (Copyright (c) 2026 TidyBank contributors). The post-M4 summary
increment includes the candidate-block detector adapted in the frozen TidyCell
source; its source path, commit, SHA-256, detector version, and compatibility
adaptations remain embedded in
`apps/domain-worker/src/recipe/detectCandidateBlocks.ts`. The separately copied
reference closure also preserves selected Tidybank summary source at pinned
commit `c26e7f67091c414b411221af461b8ea3974c6320` with its exact MIT licence.
Default summary parity is fixture-scoped and does not claim full prompt-input
parity or independent review.

Runtime npm dependencies retain their own license files in the lockfile
installation. `exceljs` 4.4.0 and `zod` 4.4.3 are MIT-licensed.

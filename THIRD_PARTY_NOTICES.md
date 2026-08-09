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

## Tidybank

Tidybank commit `6eed7df0c54a53d4680a5a0551655bf6346d4c7d`
is MIT-licensed (Copyright (c) 2026 TidyBank contributors). No Tidybank
summary/detector implementation is included in M0–M2, so no Tidybank code is
redistributed here. This notice records the reviewed provenance gate and the
reason summary parity remains unsupported.

Runtime npm dependencies retain their own license files in the lockfile
installation. `exceljs` 4.4.0 and `zod` 4.4.3 are MIT-licensed.

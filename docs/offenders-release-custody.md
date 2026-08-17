# Recorded Crime — Offenders release custody

Phase 1 closes source custody and semantic-family completeness for all numbered
worksheets in the ABS *Recorded Crime — Offenders* releases 2021–22 through
2024–25. It does not create semantic maps, contracts, normalized derivatives,
or provider calls for pending members.

The checked declarations are:

- `fixtures/product-prototype/offenders-release-downloads-v1.json`: 33 exact
  ABS downloads (27 substantive cubes and six reviewed guide/concordance
  exclusions), with URL, byte length, SHA-256 digest, and physical sheet list.
- `fixtures/product-prototype/offenders-release-family-crosswalk-v1.json`: the
  reviewed 52-family, 190-member exact crosswalk.
- `offenders-release-source-inventory-v1.json` and
  `offenders-release-family-membership-v1.json`: deterministic generated
  expansions of those declarations.

Exact official XLSX sources are under `fixtures/product-prototype/workbooks/`
and remain separate from normalized derivatives. Member identity is the tuple
`(releaseId, downloadOrdinal, physicalSheetName)` plus declared semantic cube
and table namespace. This prevents local `Table 1` sheets in the main, family
and domestic violence, COVID-19, and preliminary ANZSOC cubes from colliding.
The physical COVID-19 sheet name `Table 1 ` intentionally retains its trailing
space. Preliminary ANZSOC 2023 is a distinct two-release family.

Run:

```sh
scripts/generate-offenders-release-inventory.py --check
scripts/tidy-offenders-release verify
# or
npm run offenders:verify
```

The verifier is offline and standard-library-only. It fails closed on unsafe
paths, changed custody bytes, malformed OOXML relationships/shared strings,
sheet drift, duplicate or incomplete family assignment, fabricated
availability, ambiguous registration, and generated-file drift. The expected
report closes at four releases, 33 downloads, six reviewed exclusions, 27
cubes, 190 numbered worksheets, 52 families, 20 registered members, 170
pending semantic contracts, and zero provider calls.

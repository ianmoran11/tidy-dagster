# Criminal Courts, Australia release custody

## Scope

The checked inventory covers every official XLSX download in the 2021–22,
2022–23, 2023–24, and 2024–25 ABS *Criminal Courts, Australia* releases.

| Release | Downloads | Guide exclusions | Substantive cubes | Numbered sheets |
| --- | ---: | ---: | ---: | ---: |
| 2021–22 | 16 | 1 | 15 | 94 |
| 2022–23 | 17 | 1 | 16 | 102 |
| 2023–24 | 18 | 1 | 17 | 116 |
| 2024–25 | 18 | 1 | 17 | 118 |
| **Total** | **69** | **4** | **65** | **430** |

The guides are exact custodied exclusions. Every substantive numbered main,
preliminary ANZSOC 2023, and FDV sheet belongs to exactly one of 192 explicit
semantic families. Review merged the 2023–24 abbreviated offence-by-sentence
title into its continuing four-release family instead of treating wording drift
as a new family.

## First accepted national cluster

The first cluster covers physical Tables 1–7 in all four releases plus
2024–25 Table 8. The extra sheet is required because ABS inserted a new Table 4
in 2024–25 and moved the established guilty-outcome summary family to Table 8.
The result is 29 accepted worksheet-assets across ten cohorts:

- seven continuing semantic families;
- one family introduced in 2024–25; and
- separate ANZSOC 2011 and ANZSOC 2023 contract namespaces where identical raw
  offence labels would otherwise conceal a classification change.

The cluster contains 68,778 canonical observations. It preserves counts,
mean/median age, mean/median case duration, zeros, `..`, `na`, `np`, raw labels,
publication vintage, observation period, exact source cells, and source and
recipe digests. Confidentialisation means no unreviewed additive total equation
is imposed.

The region compiler deterministically reports `AMBIGUOUS_HEADER` when several
vertically repeated court-level anchors are visible. The family contracts allow
that diagnostic only when the selected output resolves to a reviewed canonical
court-level code. Other warning codes fail acceptance.

## Second accepted national cluster

The second cluster covers the complete national guilty-outcome cube: Tables
8–11 in 2021–22 through 2023–24 and renumbered/expanded Tables 9–15 in 2024–25.
It adds 19 worksheet-assets across eight contracts and 25,602 canonical
observations. The 2024–25 split of the earlier combined sex/age table remains
explicit for All, Higher, Magistrates', and Children's Courts.

Counts remain separate from mean and median age and duration measures. Principal
sentence, court level, observation period, ANZSOC 2011 offence, and ANZSOC 2023
offence codes retain exact raw labels and header-source provenance. Published
`..`, `na`, and `np` values remain typed null statuses. Where court level and
observation period both produce deterministic ambiguity diagnostics, acceptance
matches each warning to its own dimension-specific, year-specific source-header
allowlist.

Together the two clusters cover 48 of 430 worksheets and produce 94,380
canonical observations; 382 worksheets remain pending reviewed contracts.

## Classification identity

- 2021–22 and 2022–23 use ANZSOC 2011.
- The main 2023–24 tables remain ANZSOC 2011; the separate preliminary ANZSOC
  2023 cube has its own namespace.
- 2024–25 uses ANZSOC 2023. Where a title identifies earlier values as concorded
  from ANZSOC 2011, the inventory records that mixed publication context rather
  than claiming the historical observations were originally coded to ANZSOC
  2023.
- Experimental family and domestic violence tables remain in a separate FDV
  namespace.

## Authority and reproduction

Human-authored replay maps are deterministic inputs, not acceptance authority.
Family-specific contracts independently check exact categories, combinations,
measures, value statuses, source cells, and warnings. All 48 assets replay with
zero provider calls and zero exceptions.

```sh
scripts/generate-criminal-courts-release-inventory.py --check
scripts/tidy-criminal-courts-release verify
scripts/tidy-prototype-batch verify
scripts/tidy-data-status check
```

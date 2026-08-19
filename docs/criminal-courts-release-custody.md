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
preliminary ANZSOC 2023, and FDV sheet belongs to exactly one of 198 explicit
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

Together the first two clusters cover 48 worksheets and produce 94,380
canonical observations.

## Third accepted national cluster

The third cluster covers all 31 numbered worksheets in the national sentence
length and fine amount cubes: Tables 65–72 in 2021–22 and 2022–23, Tables 73–80
in 2023–24, and Tables 78–84 in 2024–25. Fourteen contracts preserve selected
principal sentence, offence, sentence-length or community-service bands, fine
bands, court level, jurisdiction, and Indigenous status.

ANZSOC 2011 and ANZSOC 2023 contracts remain separate whenever an identical raw
offence label could otherwise collapse two classifications. Counts,
proportions, mean and median duration, and mean and median fine amount remain
separate measures with `person`, `percent`, `month`, `hour`, and `dollar` units.
The contracts preserve all published zeros and typed `..`, `na`, and `np`
markers. Repeated jurisdiction panels may emit deterministic `AMBIGUOUS_HEADER`
warnings; each contract accepts them only when the selected canonical
jurisdiction and exact year-specific source header match its reviewed allowlist.

## Fourth accepted Indigenous-status cluster

The fourth cluster covers all 17 numbered worksheets in the selected
states-and-territories Indigenous-status cube, which is separate from the third
cluster's national sentence-length and fine cubes. Six independent contracts cover
court level, summary characteristics, principal sentence and age, crude and
age-standardised defendant rates, rate ratios, and the 2024–25 ANZSOC 2023
custody sentence-length counterpart.

The cluster adds 24,643 canonical observations. Counts, mean and median age,
crude and age-standardised rates per 100,000 people aged 10 years and over, rate
ratios, proportions, and mean and median custody durations remain distinct
measures and units. Publication vintage remains separate from the row-level
observation period. Published `..`, `na`, and `np` values remain respectively
not applicable, not available, and suppressed rather than becoming zero.

## Fifth accepted youth-defendants cluster

The fifth cluster covers all 24 numbered worksheets in the youth-defendants
cube across 2022–23 through 2024–25. Nine stable contracts span table renumbering
and title-order drift while keeping genuinely different Indigenous-status-only
and Indigenous-status-by-age tables separate. They cover national and
jurisdiction summary characteristics, finalised and guilty-outcome offence and
sentence tables, sex and age, Indigenous status, and mean and median sentence
length by jurisdiction.

The cluster adds 10,302 canonical observations. Defendant counts, mean and
median defendant age, mean and median case duration, and mean and median sentence
duration remain separate measures with person, year, week, and month units. The
2024–25 offence aliases remain ANZSOC 2023, earlier offence aliases remain ANZSOC
2011, and the 2024–25 national historical summary identifies its concorded
ANZSOC 2011 series explicitly. Published `..`, `na`, and `np` values remain
respectively not applicable, not available, and suppressed. The literal
2022–23 worksheet name `Table 80 ` is preserved through source provenance and
CSV projection.

## Sixth accepted preliminary ANZSOC 2023 cluster

The sixth cluster covers all six worksheets in the separately published
2023–24 preliminary ANZSOC 2023 cube. Six singleton contracts preserve method of
finalisation, court level, jurisdiction, sex and age, Indigenous status,
principal sentence, and the source publication's preliminary-classification
warning. Table 6 carries preliminary ANZSOC 2023 principal offence on one axis
and ANZSOC 2011 principal offence on the other; the canonical output keeps those
as two explicitly named dimensions rather than treating one as a charge or
silently collapsing them.

The cluster adds 2,371 defendant-count observations, including 204 published
zeros. All values are numeric and observed; this cube contains none of the
`..`, `na`, or `np` markers used elsewhere. The repeated method-of-finalisation
panels produce reviewed ambiguity warnings bound to the exact six source header
cells and canonical-output equivalence. Perturbation notes prevent invalid
additive acceptance equations.

The six clusters now cover 126 of 430 worksheets and produce 174,980 canonical
observations; 304 worksheets remain pending reviewed contracts.

## Classification identity

- 2021–22 and 2022–23 use ANZSOC 2011.
- The main 2023–24 tables remain ANZSOC 2011; the separate preliminary ANZSOC
  2023 cube has its own namespace.
- 2024–25 uses ANZSOC 2023. Where a title identifies earlier values as concorded
  from ANZSOC 2011, the inventory records that mixed publication context rather
  than claiming the historical observations were originally coded to ANZSOC
  2023.
- The ANZSOC 2023 Indigenous-status sentence-length counterpart is 2024–25
  Table 19 in a different cube from its third-cluster predecessor. It remains a
  distinct accepted family rather than being silently folded into the
  three-release ANZSOC 2011 cohort.
- Experimental family and domestic violence tables remain in a separate FDV
  namespace.

## Authority and reproduction

Human-authored replay maps are deterministic inputs, not acceptance authority.
Family-specific contracts independently check exact categories, combinations,
measures, value statuses, source cells, and warnings. All 126 assets replay with
zero provider calls and zero exceptions.

```sh
scripts/generate-criminal-courts-release-inventory.py --check
scripts/tidy-criminal-courts-release verify
scripts/tidy-prototype-batch verify
scripts/tidy-data-status check
```

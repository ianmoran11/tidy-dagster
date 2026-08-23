# Criminal Courts, Australia release custody

## Scope

The checked inventory covers every official XLSX download in the 2021–22,
2022–23, 2023–24, and 2024–25 ABS _Criminal Courts, Australia_ releases.

| Release   | Downloads | Guide exclusions | Substantive cubes | Numbered sheets |
| --------- | --------: | ---------------: | ----------------: | --------------: |
| 2021–22   |        16 |                1 |                15 |              94 |
| 2022–23   |        17 |                1 |                16 |             102 |
| 2023–24   |        18 |                1 |                17 |             116 |
| 2024–25   |        18 |                1 |                17 |             118 |
| **Total** |    **69** |            **4** |            **65** |         **430** |

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

## Seventh accepted New South Wales cluster

The seventh cluster covers the complete 22-sheet New South Wales cube across
2021–22 through 2024–25. Nine contracts keep the long-running summary family,
the later method-of-finalisation family, selected-offence outcome families, and
the broader 2024–25 all-offence families separate. Physical numbering drift is
bound through exact family membership, and the literal 2021–22 and 2022–23
worksheet name `Table 19 ` remains byte-faithful in provenance and CSV output.

The cluster adds 17,691 canonical observations: defendant counts, mean and
median defendant age in years, and mean and median case duration in weeks. It
preserves 926 published zeros, 61 `..` not-applicable cells, and 52 `na`
not-available cells. The source-bound `classification_context` dimension keeps
ANZSOC 2011, ANZSOC 2023, and the mixed 2024–25 concorded historical series
explicit alongside principal offence. All 10,807 repeated-panel ambiguity
warnings are matched independently by dimension and exact year-specific source
headers. Perturbation notes again preclude additive total equations.

## Eighth accepted Victoria cluster

The eighth cluster covers the complete 22-sheet Victoria cube across 2021–22
through 2024–25. Its nine contracts independently bind the long-running summary,
later method-of-finalisation, selected-offence, and 2024–25 all-offence families
to the exact Cube 5 sheets and source cells.

The cluster adds 17,524 canonical observations: 16,660 defendant counts plus 216
each for mean and median defendant age and mean and median case duration. It
preserves 1,419 published numeric zeros, 61 `..` not-applicable cells, and 52
`na` not-available cells. Its source-bound classification context keeps ANZSOC
2011, ANZSOC 2023, and the mixed concorded 2024–25 historical series distinct.
All 10,720 repeated-panel ambiguity warnings are bound by dimension, year, exact
header source, and canonical-output equivalence. Perturbation notes preclude
speculative additive total equations.

## Ninth accepted Queensland cluster

The ninth cluster covers the complete 22-sheet Queensland cube across 2021–22
through 2024–25. Nine contracts bind Cube 6 Tables 26–30, 26–30, 28–33, and
33–38 respectively, while keeping the long-running selected-offence families
separate from the 2024–25 all-offence singletons. Its 17,415 canonical rows
retain 16,551 defendant counts plus 216 observations for each mean/median age
and mean/median case duration measure. Published numeric zeros remain distinct
from 117 `..` and 136 `na` markers.

The 10,640 repeated-panel warnings are frozen by year and dimension, require
canonical-output equivalence, and pin the exact selected header source cells.
The mixed 2024–25 concorded summary context remains separate from ANZSOC 2011
and ANZSOC 2023. No additive total equations are imposed.

## Tenth accepted South Australia cluster

The tenth cluster covers the complete 22-sheet South Australia cube across
2021–22 through 2024–25. Nine contracts bind Cube 7 Tables 31–35, 31–35,
34–39, and 39–44 respectively. The 2024–25 all-principal-offence All Courts and
Magistrates' Courts tables remain singleton families, separate from the
selected-offence continuations.

The cluster adds 17,495 canonical rows: 16,631 defendant counts plus 216
observations for each mean/median defendant age and mean/median case duration
measure. It preserves 1,522 published numeric zeros separately from 57 `..`
not-applicable and 148 `na` not-available cells. The source-bound classification
context distinguishes ANZSOC 2011, ANZSOC 2023, and the mixed concorded 2024–25
summary series. All 10,734 ambiguity warnings require canonical-output
equivalence and exact year-specific selected header sources. Perturbation notes
preclude additive total equations.

## Eleventh accepted Western Australia cluster

The eleventh cluster covers the complete 22-sheet Western Australia cube across
2021–22 through 2024–25. Nine contracts bind Cube 8 Tables 36–40, 36–40,
40–45, and 45–50 respectively. The 2024–25 all-principal-offence All Courts and
Magistrates' Courts tables remain singleton families, separate from the
selected-offence continuations.

The cluster adds 17,327 canonical rows: 16,463 defendant counts plus 216
observations for each mean/median defendant age and mean/median case duration
measure. It preserves 1,441 published numeric zeros separately from 61 `..`
not-applicable, 100 `na` not-available, and 198 `np` suppressed cells. The
source-bound classification context distinguishes ANZSOC 2011, ANZSOC 2023,
and the mixed concorded 2024–25 summary series. All 10,576 ambiguity warnings
require canonical-output equivalence and exact year-specific selected header
sources. Method-of-finalisation categories, including guilty ex-parte, retain
`GROUP_METHOD_OF_FINALISATION`; perturbation notes preclude additive equations.

## Twelfth accepted Northern Territory cluster

The twelfth cluster covers the complete 22-sheet Northern Territory Cube 10
across 2021–22 through 2024–25. Nine stable families bind Tables 46–50,
46–50, 52–57, and 57–62 respectively. The 2024–25 all-principal-offence All
Courts and Magistrates' Courts tables remain singleton families, separate from
the selected-offence continuations. Four normalized workbooks retain only each
sheet's reviewed used range; their original Cube 10 downloads remain separately
custodied, and no correction is applied.

The cluster adds 16,931 canonical rows: 16,067 defendant counts plus 216
observations for each mean/median defendant age and mean/median case duration
measure. It preserves 2,913 published numeric zeros separately from 49 `..`
not-applicable and 88 `na` not-available cells; no selected cell is suppressed.
All 10,424 ambiguity warnings require canonical-output equivalence and exact
year-specific header sources. The 2024 all-principal-offence headers preserve
the published non-breaking spaces, including
`14 Offences against justice procedures and orders(c)`, and the contracts bind
the exact NT footnote variants rather than inferring suffixes. Guilty ex-parte
is a category under `GROUP_METHOD_OF_FINALISATION`; blank cells on that source
row never make it a parent for the following transfer, withdrawn, or total
categories. Perturbation notes preclude additive total equations.

## Thirteenth accepted Australian Capital Territory cluster

The thirteenth cluster covers the complete 22-sheet Australian Capital Territory
Cube 11 across 2021–22 through 2024–25. Nine stable families bind Tables 51–55,
51–55, 58–63, and 63–68 respectively. The two 2024–25 all-principal-offence
tables remain singleton families, separate from selected-offence continuations.
Four deterministic normalized workbooks retain only reviewed ranges. The
2021–22 source remains byte-custodied with its impossible `Table 51!M5` value
`2022–22`; an exact digest-, style-, type-, cell-, and old-value-bound correction
changes only the normalized derivative to `2021–22` before trimming.

The cluster adds 16,057 canonical rows: 15,193 defendant counts plus 216
observations for each mean/median defendant age and mean/median case duration
measure. It preserves 2,844 published numeric zeros separately from 49 `..`
not-applicable and 88 `na` not-available cells; no selected cell is suppressed.
All 9,969 ambiguity warnings require canonical-output equivalence and exact
source headers. Classification context remains separated across 11,283 ANZSOC
2011, 2,104 ANZSOC 2023, and 2,670 mixed-concorded observations. Policy v2
binds each decision to exact contract bytes, recipe, workbook identity, checks,
and the pinned replay timestamp `2026-08-21T09:00:00+00:00`.

## Fourteenth accepted Tasmania cluster

The fourteenth cluster covers the complete 22-sheet Tasmania Cube 9 across
2021–22 through 2024–25. Ten stable families bind Tables 41–45, 41–45, 46–51,
and 51–56 respectively. Source-title changes deliberately keep the two selected
Magistrates' families separate, and the 2024 all-principal-offence tables remain
singletons. Four normalized workbooks retain exact reviewed ranges without
changing any valued or formula cell.

The cluster adds 16,545 canonical rows: 15,681 defendant counts plus 216
observations for each mean/median defendant age and mean/median case duration
measure. It preserves 2,342 numeric zeros separately from 129 `np` suppressed,
53 `..` not-applicable, and 39 `na` not-available cells. All 10,231 ambiguity
warnings require canonical-output equivalence and exact source headers.
Classification context remains separated across 11,622 ANZSOC 2011, 2,268
ANZSOC 2023, and 2,655 mixed-concorded observations. Policy v2 binds each
decision to exact contract bytes, recipe, workbook identity, checks, and the
pinned replay timestamp `2026-08-22T09:00:00+00:00`.

A role-aware catalog addition exposes exact terminal repeated-panel marker runs
only when an earlier same-span panel has an immediately following marker run
with the same complete style vector. It is limited to exact `..`, `na`, and
`np`, rejects detached/merged/unlabelled/style-mismatched rows, appends after
established candidate IDs, and produced no catalog delta for all 409 previously
registered worksheets. It preserves Tasmania Table 54's terminal 12 `np` cells
without a workbook correction. Source `regulaton` remains raw provenance while
the canonical offence identifier correctly uses `REGULATION`. Perturbation and
residual-category footnotes make additive total equations inapplicable; explicit
hierarchy checks preserve method and principal-offence aggregates instead.

## Fifteenth accepted defendant-rate cluster

The fifteenth cluster covers the complete 36-sheet defendant-rate Cube 12 across
2021–22 through 2024–25. Nine three-vintage ANZSOC 2011 families and nine
2024–25 mixed-concorded singletons bind Tables 56–64, 56–64, 64–72, and 69–77.
The 2024 singletons remain separate because the publication context concords
earlier ANZSOC 2011 values into the ANZSOC 2023 presentation; no cross-vintage
classification equivalence is asserted.

The cluster retains 27,486 canonical observations: 13,743 published defendant
counts in persons and 13,743 published rates per 100,000 persons aged 10 years
and over. Both panels are accepted independently. Exact source headers identify
the measure rather than row order because 2024 places the rate panel above the
count panel, reversing the earlier releases. Rates are not recomputed, no
population denominator or count/rate identity is inferred, and confidentialised
components are not forced into additive equations. Published total rows remain
source observations with `totalValidation: not_applicable`.

All 27,486 selected observation cells are numeric, include 20 exact zeros, and
contain no selected formula or marker; source workbooks still retain unrelated
metadata formulas and raw footnote markers. The canonical rows and contracts
preserve raw labels and footnote markers `(a)`–`(l)`; complete footnote prose
remains in the digest-bound source workbooks. Their 13,743 exact lower-panel
ambiguity warnings are bound to the reviewed RATE headers in 2021–23 and the
COUNT header after the
2024 reversal. Policy v2 binds exact contract bytes, recipes, workbook/sheet/date
identities, checks, and replay time `2026-08-23T09:00:00+00:00`; replay maps
remain non-authoritative and training-ineligible.

Only the 2023–24 Cube 12 derivative is normalized. Table 68 is bounded to
`A1:O84`, and Table 71 to `A1:O82`, removing empty full-width formatting and the
pathological empty merge `A82:O1048576`. Reproduction is byte-identical, all
retained values, formulas, types, styles, number formats, and legitimate merges
are unchanged, and the original workbook remains immutable.

### Complete FDV order-breach cube

The complete FDV order-breach boundary adds 18 families and 36 worksheets:
nine 2021–22 through 2023–24 `Breach of violence orders, Summary
characteristics` histories (FDV Tables 14–22) and nine separate 2024–25 `Breach
of restraining order – violence` singletons (FDV Tables 18–26). The split
preserves the publication's changed experimental classification identity rather
than implying cross-vintage equivalence.

The cluster retains 6,463 observations: 6,097 published defendant counts, 183
mean ages, and 183 median ages. It preserves 6,357 observed values, 94 exact
`na` not-available nulls, 12 exact `..` not-applicable nulls, and 227 observed
numeric zeros. No selected formula or execution warning exists. Era-specific
age bands, method, sentence, outcome, and Indigenous-status categories remain
separate; 2024 `Not stated` remains distinct, and the 2023 ACT published title's
trailing space remains raw provenance. No additive total or other unsafe
identity is inferred.

The 2023–24 Cube 17 normalized derivative trims Tables 15–19 to their reviewed
semantic ranges. Before trimming, the correction removes only the far-right
`FDV Table 16!XEX59` footnote that is an exact duplicate of retained `A58`,
bound to the exact workbook digest, byte length, sheet, cell, shared-string
value/type, style, merge, and retained duplicate. The original source remains
immutable, `A58` and `A59` remain exact, and all prior correction-bearing
outputs reproduce byte-identically.

Policy v2 binds all 18 exact contract files, 36 recipe pins, workbook/sheet/date
identities, checks, and replay time `2026-08-24T09:00:00+00:00`. All replay maps
remain explicitly non-authoritative and training-ineligible.

The seventeenth and final cluster accepts all remaining FDV-offence worksheets
as one indivisible 31-family boundary: 13 sheets from each of 2021–22 Cube 14,
2022–23 Cube 15, and 2023–24 Cube 16, plus nine national 2024–25 Cube 15 sheets
and eight state/territory 2024–25 Cube 16 sheets. The semantic families cross
the physical 39/9/8 inventory split, so partial registration would have broken
family lifecycle and classification identity.

The cluster retains 76,189 source observations: 67,425 defendant counts, 2,331
each of mean and median age, and 2,051 each of mean and median duration. It
preserves 75,320 observed values, 633 exact `na` not-available nulls, 118 exact
`..` not-applicable nulls, 118 exact `np` suppressed nulls, and 10,152 observed
numeric zeros. The 53,808 exact source-grounded header warnings are allowed by
contract. Every complete raw-dimension tuple is unique; no selected cell is a
formula. All 78 historical metadata formulas (39 in each of 2021–22 and
2022–23) remain exact source provenance.

Release-specific classification remains explicit. True historical
principal-offence titles use the FDV ANZSOC 2011 context; the 2023–24 titles
that make no concordance claim use a neutral 2023–24 release context; and 2024
ANZSOC 2023, mixed-concorded, and release-specific panels remain distinct. No
rate, denominator, total, residual, additive identity, or cross-vintage
equivalence is inferred. Canonical JSON and source provenance preserve exact
whitespace. CSV follows the existing string `rstrip` projection except that
`source_sheet` is byte-faithful; 3,484 projected fields across 110 exact raw
labels exercise that documented distinction.

The only new derivative is 2023–24 Cube 16. Its exact 413,928-byte source
(`sha256:65e4e00d…9815`) remains immutable. A digest-bound correction receipt
validates and removes 4,680 empty pathological Table 8 merges outside retained
`A1:L256` and the one pathological Table 13 `A2:XFD2` merge outside retained
`A1:K261`; legitimate Table 8 `A2:L2` remains. The 252,687-byte derivative is
`sha256:52118023…a146fc`, all removed cells are empty and formula-free, and all
non-target ZIP members remain exact.

All 31 v2 decisions bind exact contract bytes, 56 recipe pins, workbook, sheet,
reference date, checks, and replay time `2026-08-25T09:00:00+00:00` through the
explicit date-bound decision identity. Seven-file evidence bundles total 217
files and reproduce byte-identically with zero providers, retries, exceptions,
or exclusions; replay maps remain non-authoritative and training-ineligible.

The seventeen clusters now cover all 198 families and 430 of 430 worksheets,
produce 422,103 Criminal Courts observations, and leave zero pending semantic
contracts. This final boundary accepts five previously unregistered physical
workbooks (2021–22 Cube 14, 2022–23 Cube 15, 2023–24 Cube 16, and 2024–25 Cubes
15 and 16), raising the cross-publication dashboard from 79 to 84 physical
workbooks.

## Classification identity

- 2021–22 and 2022–23 use ANZSOC 2011.
- The main 2023–24 tables remain ANZSOC 2011; the separate preliminary ANZSOC
  2023 cube has its own namespace.
- 2024–25 uses ANZSOC 2023. Where a title identifies earlier values as concorded
  from ANZSOC 2011, the inventory records that mixed publication context rather
  than claiming the historical observations were originally coded to ANZSOC 2023.
- The ANZSOC 2023 Indigenous-status sentence-length counterpart is 2024–25
  Table 19 in a different cube from its third-cluster predecessor. It remains a
  distinct accepted family rather than being silently folded into the
  three-release ANZSOC 2011 cohort.
- Experimental family and domestic violence tables remain in a separate FDV
  namespace.

## Authority and reproduction

Human-authored replay maps are deterministic inputs, not acceptance authority.
Family-specific contracts independently check exact categories, combinations,
measures, value statuses, source cells, and warnings. All 430 assets replay with
zero provider calls and zero exceptions.

```sh
scripts/generate-criminal-courts-release-inventory.py --check
scripts/tidy-criminal-courts-release verify
scripts/tidy-prototype-batch verify
scripts/tidy-data-status check
```

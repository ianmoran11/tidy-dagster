# Recorded Crime — Offenders Table 5 four-release evidence

This directory is the committed, provider-free replay closure for Table 5 of
*Recorded Crime — Offenders* across publication periods 2021–22 through
2024–25. The four semantic maps are deterministic human-authored replay inputs;
they are explicitly non-authoritative. Acceptance is controlled by the pinned
table-family contract and deterministic execution.

The canonical rows preserve publication vintage separately from each observation
period. Published `na` cells are retained as `not_applicable` nulls where present.
No additive total equality is asserted because the publication states that cells
are randomly adjusted for confidentiality. Exact source and normalized workbook
identities are bound by `batch-workbook-normalization-v1.json`; the 2023–24 and
2024–25 corrections remove only digest-bound isolated values outside the semantic
observation/header regions. The manifest records whether each change is inside
the retained rectangular range and preserves the original source workbooks.

This closure contains no prompts, provider envelopes, secrets, or mutation
authority. Dagster and the status page are read-only projections of these files.

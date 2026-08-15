# Table 22 five-year checked evidence

This directory is the safe, provider-free evidence closure for *Prisoners in
Australia*, Table 22, for 2021–2025. Five existing Sol/high semantic-map
responses were replayed through the deterministic worker and judged only by the
human-authored Table 22 contract.

The run accepted all five workbook/sheet assets with no exceptions or
cross-year issues. Its 1,709 canonical observations keep two measures separate:

- 1,539 prisoner counts, measured in persons, across nine jurisdictions; and
- 170 national imprisonment-rate observations, measured per 100,000 adult
  population for the relevant country of birth.

Four published `na`/`n.a` rate cells for the `OTHER` country category are
retained with a null value and `not_applicable` status. The absent 2021
`OTHER`-country rate cell is not synthesized and its year-specific absence is
part of the acceptance contract. No provider calls were made.

Raw prompts and provider envelopes are not included. The responses are
non-authoritative replay fixtures; deterministic execution, canonical code
mappings, measure separation, and the acceptance contract decide inclusion.

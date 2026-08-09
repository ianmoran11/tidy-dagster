# Source evidence and planning baseline

- **Recorded:** 2026-08-09
- **Purpose:** Planning provenance only
- **Authority:** Informative; it does not authorize copying, provider work, approval, adoption, calibration, or simulation

This document records what was inspected while preparing the reimplementation plan. The implementation must create a new, reviewed baseline manifest before copying fixtures or claiming parity.

## Repository state observed

| Repository                                               | Observed commit                            | Working-tree status relevant to this plan                                                                                                                  |
| -------------------------------------------------------- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/Users/ian/projects/tidycell`                           | `1be6c995fa931e9860468e40490433161b0121cb` | Heavily dirty and 48 commits ahead of `origin/main`; read only during planning. The pipeline guide below is currently untracked.                           |
| `/Users/ian/projects/tidycell-justice-semantic-scaffold` | `f0bd6ed7a9cb16c154fa3d2b5f25ed526641dd4b` | Clean feature worktree; draft scaffold plus approved decisions, not adopted contracts.                                                                     |
| `/Users/ian/projects/sembla`                             | `0e7570f2e200b0b309d125efaa1a907b032daf19` | Dirty; both justice proposal documents are untracked. Existing committed grouped-observation and target behavior is precedent, not a released justice API. |
| `/Users/ian/projects/tidy-dagster`                       | None                                       | Initially empty and not a Git repository. This planning pass added documentation only.                                                                     |

The observed commits are navigation anchors, not automatically the migration baseline. Milestone M0 must identify exact source commits, verify licenses, and freeze every copied byte in `fixtures/parity/source-manifest.json`.

## TidyCell documentation evidence

| Document                                                                | SHA-256                                                            | Status/use                                                                                            |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `tidycell/docs/tidycell-current-spreadsheet-to-recipe-data-pipeline.md` | `f2a164a6426369451b8f552862f1a91cc0649b81314306cd3ca6a2c1335bc366` | Plain-English description of the current implementation; untracked in the observed TidyCell worktree. |
| `tidycell/docs/justice-event-schema-implementation-sequence.md`         | `a26bb9f2f1833f1c45a3cb41c988279fd6c824453a35180d843692d2d7d87698` | Proposed phased semantic/calibration workflow.                                                        |
| `tidycell/docs/justice-event-schema-and-aggregate-statistics.md`        | `24a8b69ef9e222c8558489a1f82c1af0ca6112f35f0336d77c77846e7567aab0` | Proposed layered justice representation and semantic-validation design.                               |

The current implementation contains four distinct generation paths that must not be collapsed in parity reports:

1. direct RecipeV01 generation in the large-scale Luna harvest path;
2. CellRole V5 semantic-map generation followed by deterministic compilation;
3. leakage-clean ML-assisted Sol semantic-map generation used by frozen Prisoners research runs; and
4. a general interactive fallback with its own bounded repair/review behavior.

Shared deterministic behavior includes workbook parsing, RecipeV01 validation, selector resolution, relationship geometry, execution, trace/provenance, and export. Research wrappers, provider routing, and approval strength differ.

## Initial synthetic fixture candidates

The following files are tracked and byte-identical to the observed TidyCell commit. They are candidates only; copying still requires a license/source review.

| Fixture file                              | SHA-256                                                            |
| ----------------------------------------- | ------------------------------------------------------------------ |
| `fixtures/workbooks/simple-crosstab.xlsx` | `7453482b08710e46d97868aed317359fcd06303698f96e021c4a4d2f52ece85a` |
| `fixtures/recipes/simple-crosstab.json`   | `cd9bf8d3c144f46584513ccb9cf22d708c46e2e7905a9c5f2f6cf04c3fdd8359` |
| `fixtures/expected/simple-crosstab.json`  | `a1feaaeeeb1770932addf53a7ac902cadd03bffcef29fce3278f7b934bde139c` |
| `fixtures/workbooks/sparse-headers.xlsx`  | `9cf91a692ba65c0488a8b078aa4d95206717db7e7dc12409909b347a3784d878` |
| `fixtures/recipes/sparse-headers.json`    | `4102ebd9c09f4e1ece41ae665e9099f301bb7f7ee71b2a2580dfcfe7e3818e25` |
| `fixtures/expected/sparse-headers.json`   | `268f34256b70c996fa7ad8838a42a149504c674845ce3737511b93a27b8da7e3` |
| `fixtures/workbooks/multi-table.xlsx`     | `e89b640950be64cabe90bc71c69d0a7ce664193873e483064165ecc2f8355164` |
| `fixtures/recipes/multi-table.json`       | `38910e39d1717a976dc041f16e4bee6215bbbf00432f4cde7a68468aa2f6a4d2` |
| `fixtures/expected/multi-table.json`      | `3f6463546cbceb5a44799aee40c6d98e94cfab20a379fced169890ad79b1da39` |

The first fixture should establish exact intermediate and final parity. The other two should be added only after the first slice is stable. ABS downloads, approval records, provider responses, and large research runs are deliberately excluded from the initial fixture set.

## Justice scaffold evidence

| Document                                                                             | SHA-256                                                            |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `tidycell-justice-semantic-scaffold/docs/justice-semantic-scaffold-decisions.md`     | `2bb35c92ea5d808bc72bd2768361af071815bc954a6856d7828dae19adbfeb91` |
| `tidycell-justice-semantic-scaffold/docs/justice-semantic-scaffold-review-packet.md` | `513948890562af1c3cae8bc5fc4551b805edc0ec65e142c1f92429b378374576` |

The approved direction is narrower than the earlier proposal:

- prisoner stock counts at midnight on 30 June for 2019–2025;
- reporting jurisdiction, sex, and legal status only;
- stable `justice:*` identities with contract versions and classification editions represented separately;
- RFC 8785/JCS plus domain-separated SHA-256 before adoption;
- release-pinned ABS authority, declarative scoped methodology, explicit statistical states, layered provenance, and a frozen two-reviewer semantic-gold gate.

Approval of those decisions is not adoption. The six current schemas and fixtures remain `0.1.0-draft` and `reviewStatus: provisional`. Complete ANZSOC data, calibration-role assignment, and a Sembla implementation remain deferred.

## Sembla evidence

| Document                        | SHA-256                                                            | Use                                                                |
| ------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `sembla/docs/guides/targets.md` | `c7b6a49e419f58e90a346f13aa0027c82cf7b6d9b3e50d4ca6ae1d543c891482` | Committed population-target and scoring precedent.                 |
| `sembla/DESIGN.md`              | `a3822b7514442010a50b97690e3c19a2c0a3ca0b1c8f9286e5ea813d03fa4f8e` | Runtime, reproducibility, observation, and manifest principles.    |
| `sembla/DECISIONS.md`           | `3faa000c8b284fe1e2a5df9508a42666061ee8a9453d3308096111c5d1f57223` | Accepted Sembla design decisions and current calibration approach. |

Relevant committed constraints include grouped observations with one to four keys and current executable target roles of `fitted` and `heldout`. Observation non-interference is a Sembla design principle and a proposed justice-integration acceptance gate; no implemented justice model was observed. The proposed justice target ledger names additional audit roles, so an adapter must never silently coerce them into the current executable schema.

## Dagster primary sources

The official documentation reported Dagster `1.13.17` as current when retrieved on 2026-08-09. The design must pin and recheck the exact version selected during implementation:

- [OSS deployment architecture](https://docs.dagster.io/deployment/oss/oss-deployment-architecture)
- [Software-defined assets](https://docs.dagster.io/guides/build/assets)
- [Partitions and backfills](https://docs.dagster.io/guides/build/partitions-and-backfills/partitioning-assets)
- [Asset checks](https://docs.dagster.io/guides/test/asset-checks)
- [Resources](https://docs.dagster.io/guides/build/external-resources/defining-resources)
- [I/O managers](https://docs.dagster.io/guides/build/io-managers)
- [External pipelines and Dagster Pipes](https://docs.dagster.io/integrations/external-pipelines)
- [Sensors](https://docs.dagster.io/guides/automate/sensors)
- [Concurrency](https://docs.dagster.io/guides/operate/managing-concurrency)
- [Asset versions and caching](https://docs.dagster.io/guides/build/assets/asset-versioning-and-caching)

Important lifecycle cautions observed during planning:

- [Dagster+](https://docs.dagster.io/deployment/dagster-plus) adds managed and plan-dependent operational capabilities; alerting, health, RBAC, authentication and some concurrency behavior must be compared explicitly with OSS;
- [partitioned asset checks](https://docs.dagster.io/guides/test/asset-checks) were documented as Preview;
- [`backfill_policy`](https://docs.dagster.io/api/dagster/assets) was documented as Beta;
- [Components](https://docs.dagster.io/guides/build/components) are relatively new and should not become a custom DSL before stable repetition exists; and
- Dagster's [GraphQL API](https://docs.dagster.io/api/graphql) is evolving and should not be the unversioned core approval protocol.

Before M4, produce an OSS-versus-Dagster+ matrix for the pinned version covering the daemon, run coordinator/retries, launcher/executor, concurrency pools, alerts/health, authentication/RBAC and high availability.

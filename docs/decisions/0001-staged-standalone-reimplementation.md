# ADR 0001: staged standalone reimplementation

- **Status:** Accepted
- **Decision date:** 2026-08-09
- **Decision owner:** User
- **Scope:** Target ownership and migration strategy

## Context

TidyCell already contains valuable deterministic behavior for workbook parsing, RecipeV01 validation and execution, generation evidence, review, approval, and export. It also contains several research-specific generation paths and a heavily used, dirty worktree. A Dagster integration could either wrap that implementation, replace it in one operation, or migrate capability by capability.

A permanent wrapper would retain accidental coupling to TidyCell's directory structure, mutable worktree, web application, and research code. A big-bang rewrite would make semantic drift difficult to detect and would delay useful end-to-end evidence.

## Decision

Build `tidy-dagster` as an independently deployable implementation using a **strangler-style, parity-gated migration**:

1. Freeze small, license-safe reference fixtures and exact expected intermediate artifacts.
2. Reimplement a narrow provider-free vertical slice.
3. Compare every deterministic layer, not only final CSV output.
4. Add orchestration, review, generation, semantic, and simulation capabilities incrementally.
5. Cut over one explicitly reviewed cohort at a time.
6. Keep the previous authority available until rollback has been rehearsed.

The project may copy or port reviewed behavior and fixtures with provenance and licensing, but it must not have a runtime import or filesystem dependency on the existing TidyCell, justice-scaffold, or Sembla source trees.

## Consequences

### Positive

- Deterministic drift becomes visible before operational cutover.
- Each milestone produces an independently useful system slice.
- TidyCell and Sembla can evolve without silently changing this system.
- Rollback can occur per cohort rather than per platform.
- The architecture can be changed behind stable contracts as scale and deployment needs evolve.

### Costs

- Temporary duplication is intentional.
- Compatibility contracts and parity fixtures require sustained maintenance.
- Some legacy behavior may need an explicit compatibility adapter instead of becoming the preferred internal design.
- Full independence requires a later decision about the long-term recipe-review client; the initial plan only defines its API and decision boundary.

## Rejected alternatives

- **Dagster wrapper only:** useful as a spike, but insufficient as the long-term ownership model.
- **Complete one-shot rewrite:** too much undetected semantic and operational risk.
- **Shared mutable package extracted from TidyCell:** makes release and ownership boundaries ambiguous during migration.

## Guardrail

Parity does not authorize live provider calls, recipe approval, semantic adoption, calibration-role assignment, or Sembla execution. Each remains a separate explicit gate.

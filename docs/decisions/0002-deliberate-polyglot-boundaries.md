# ADR 0002: deliberate polyglot boundaries

- **Status:** Accepted
- **Decision date:** 2026-08-09
- **Decision owner:** User
- **Scope:** Runtime and component ownership

## Context

Dagster is Python-native. Existing spreadsheet, RecipeV01, and semantic-contract behavior is predominantly TypeScript. ML training and inference are already Python-oriented, while Sembla is implemented in Rust and has its own reproducibility and CLI contracts.

Moving every concern into one language would simplify local imports but would increase porting risk, collapse independent release boundaries, and encourage orchestration-framework concepts to leak into the domain model.

## Decision

Use explicit polyglot ownership:

- **Python:** Dagster definitions, sensors, partitions, retry/concurrency policy, artifact-store adapters, provider dispatch, ML, approval-service adapters, and Sembla process invocation.
- **TypeScript:** authoritative workbook representation, R1C1/range algebra, RecipeV01 parsing and validation, selectors and relationship geometry, deterministic execution/export, bounded prompt context, generation-response interpretation, review evidence, and validation/processing of pinned semantic exports. TidyCell retains V1 semantic-contract authority until a separate reviewed ownership or cutover decision.
- **Rust/Sembla:** remains an external executable or container. This repository owns only a versioned anti-corruption adapter and invocation evidence. A real version or artifact must be selected and pinned later; none is selected by this ADR.

Cross-runtime communication begins with strict JSON/JSONL envelopes plus immutable file manifests. Large bytes are referenced by digest and URI/path rather than passed through orchestration results. Local subprocess transport may later be replaced by containers or remote workers without changing the domain contract.

## Dependency rule

```text
Dagster adapters → application ports → versioned wire contracts
                                    ↑
           TypeScript worker / Python ML / Sembla CLI
```

Domain code must not import Dagster. The TypeScript worker receives no Dagster object or run identity as business input. Python orchestration must not reimplement workbook or recipe semantics. Neither side imports Sembla internals.

## Consequences

### Positive

- Existing semantic behavior can be reproduced in its natural runtime.
- Dagster remains replaceable.
- ML and simulation runtimes can scale independently.
- Transport, storage, provider, and deployment choices stay behind narrow ports.
- Cross-language contracts make hidden assumptions testable.

### Costs

- Canonicalization, numeric, Unicode, date, and error behavior need cross-language vectors.
- Subprocess/container lifecycle and artifact staging require careful implementation.
- Debugging crosses process boundaries.
- Contract compatibility must be maintained deliberately.

## Rejected alternatives

- **Python-first rewrite:** simpler Dagster imports, but high workbook/recipe semantic-drift risk.
- **TypeScript-first orchestration:** preserves one application runtime but fights Dagster's Python-native model and complicates ML integration.
- **Direct source-tree imports:** fast initially, but violates standalone ownership and reproducibility.

## Guardrail

A language boundary is not a reason to create a shallow service for every helper. Each executable should expose a small set of deep, capability-oriented operations and hide its internal decomposition.

# Migration canary contracts v1

These provider-free contracts freeze the first real Phase B import cohort without
copying source bytes or authorizing an import.

- `manifest.schema.json` binds the exact Phase A snapshot, deterministic selector
  producer, hard limits, selected source-item digests, artifact/disposition/adverse
  coverage, duplicate closure, and every still-closed gate.
- `review.schema.json` records implementing-agent self-review honestly. It accepts
  the cohort only for importer-gate implementation and read-only NAS inspection.

The selector covers every observed artifact-class/disposition/entry stratum,
warning, embedded-record kind, Git state, and size bucket. It also selects exact
canonical-plus-alias closures for pair, small, large, and cross-artifact duplicate
groups. `quarantine` is explicitly `not-observed` rather than fabricated.

```sh
uv run python -m tidy_orchestrator.migration_canary_cli freeze \
  --snapshot .source-exports/tidycell-phase-a-snapshot-v1-final.json \
  --output fixtures/migration-canary/phase-b-canary-v1.json \
  --frozen-at 2026-08-11T20:00:00Z

uv run python -m tidy_orchestrator.migration_canary_cli verify \
  --snapshot .source-exports/tidycell-phase-a-snapshot-v1-final.json \
  --manifest fixtures/migration-canary/phase-b-canary-v1.json
```

Neither record grants byte-copy, live-import, full-import, provider, activation,
or training authority. SQLite over SMB remains prohibited.

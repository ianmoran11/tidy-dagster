# Hobby canary MVP v1

`report.schema.json` describes the bounded end-to-end result for the exact frozen
63-item canary. The canary copies at most 64 MiB into the dedicated disposable
NAS share while retaining SQLite and authority evidence locally.

This MVP explicitly waives snapshots and restore drills for disposable canary
bytes. It does not authorize the full import, provider dispatch, automatic
activation, model training, or a source-of-truth cutover.

Run from the repository root after mounting the dedicated share with the
`tidy-dagster` non-admin identity:

```sh
uv run python -m tidy_orchestrator.canary_mvp_cli run \
  --source-root /absolute/path/to/frozen-tidycell \
  --metadata-root .canary-mvp/metadata \
  --blob-root /Volumes/tidy-dagster/canary-blobs \
  --output-root .canary-mvp/evidence
```

The command verifies the frozen source and canary manifest, imports exact source
bytes into content-addressed `COMMITTED.json` objects, writes local checkpoints,
creates conservative typed dispositions, performs core and semantic
reconciliation, and repeats the import to prove idempotence. The result remains
manual-inspection-only.

# Hobby canary MVP v1

`report.schema.json` describes the bounded end-to-end result for the exact frozen
63-item canary. The canary copies at most 64 MiB into a dedicated disposable
local blob tree while retaining SQLite and authority evidence in a separate
local tree. It has no NAS, SMB, service-account, network, or credential
dependency.

This MVP does not authorize the full import, provider dispatch, automatic
activation, model training, or a source-of-truth cutover.

Run from the repository root with empty project-controlled local directories:

```sh
uv run python -m tidy_orchestrator.canary_mvp_cli run \
  --source-root /absolute/path/to/frozen-tidycell \
  --metadata-root .canary-mvp-local/metadata \
  --blob-root .canary-mvp-local/blobs \
  --output-root .canary-mvp-local/evidence
```

The command verifies the frozen source and canary manifest, imports exact source
bytes into content-addressed `COMMITTED.json` objects, restores missing blobs
from those digest-bound sources when retained metadata is reused, writes local checkpoints,
creates conservative typed dispositions, executes every applicable bounded
approval/RecipeV01/generation interpretation, performs core and semantic
reconciliation, and repeats the import to prove idempotence. Approval targets
and unresolved reviewer labels stay unresolved, all outputs remain inactive,
and the result remains manual-inspection-only.

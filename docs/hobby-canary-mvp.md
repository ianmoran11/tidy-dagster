# Frozen 63-item hobby canary MVP

## Result

The exact frozen Phase B canary was copied and reconciled end to end on
2026-08-12. The run is bound to:

- canary manifest
  `sha256:ee072650751fa76d456ba8cf034878a2a48137b02e6e7d459cb7945cb9474139`;
- frozen Phase A snapshot
  `sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d`;
- derived 63-item import snapshot
  `sha256:09f35bf91d33879299bfde9bec3c8a5a65b327ca94e26cbd51bc4fe63ee90cb2`;
- core reconciliation
  `sha256:041aee2fde46112b11a83641be74d47015285f201604e6074a6f22271213fc22`;
- semantic reconciliation
  `sha256:31fbd3175b07709a5ff25b3388ce779d4f6ca4480b9d100519cdf7333cb19256`;
- concise report
  `sha256:0dbdf0b0c7bc391e3e06c0b6d2f8534501795372fda049ec65a4bbcd9fe52e4d`.

The report is committed at
`fixtures/canary-mvp/phase-b-63-item-report-v1.json`.

## Outcomes

| Outcome         |  Items |   Source bytes |
| --------------- | -----: | -------------: |
| imported        |     36 |     42,423,291 |
| duplicate alias |     22 |        703,443 |
| excluded        |      5 |        958,003 |
| **total**       | **63** | **44,084,737** |

Exact source bytes were deduplicated into 36 content-addressed NAS objects,
totalling 42,423,291 bytes. The frozen derived canary snapshot and two bounded generation-profile outputs
bring the total to 39 committed CAS objects. Every stored object has a
`COMMITTED.json` marker. The same importer was run a second time and yielded the exact same core
reconciliation, establishing restart/idempotence on the real SMB store.

Conservative typed disposition records were created locally. In addition, both selected `generation-json-evidence` sources were deeply profiled by the network-denied migration worker; the profile emitted no raw restricted text and found no strict nested recipe candidate:

- 1 approval-registry evidence record;
- 38 generation-evidence records;
- 2 archive-only model-package records; and
- 4 inactive recipe-evidence records.

No model binary was opened or deserialized. No provider was called. No recipe
was activated and no effective pointer moved.

## Hobby boundary

The NAS share `tidy-dagster` is dedicated to disposable, rebuildable canary
blobs. The non-admin NAS identity `tidy-dagster` has read/write permission on
that share. SMB 3.1.1 signing is forced and was verified on a newly established
session. SQLite and all authoritative checkpoints remain under the local
`.canary-mvp/metadata` directory, never on SMB.

Snapshots and restore drills are intentionally waived for this disposable hobby
canary. The complete 44,682-item import, backups, provider spend, automatic
activation, model training, and source-of-truth cutover remain unauthorized.

## Manual inspection and rebuild

The run is deliberately manual-inspection-only. Current retained limitations are
recorded in the report, notably that broad typed RecipeV01 and generation
interpretation remain incomplete. Those limitations do not invalidate the MVP's
content custody and conservative reconciliation; they prevent stronger semantic
or activation claims.

To discard only disposable bytes, delete the contents of the dedicated NAS
`canary-blobs` directory. Never delete `.canary-mvp/metadata` when retaining the
local audit trail. To rebuild, remount the dedicated share and run:

```sh
uv run python -m tidy_orchestrator.canary_mvp_cli run \
  --source-root /Users/ian/projects/tidycell \
  --metadata-root .canary-mvp/metadata \
  --blob-root /Volumes/tidy-dagster/canary-blobs \
  --output-root .canary-mvp/evidence
```

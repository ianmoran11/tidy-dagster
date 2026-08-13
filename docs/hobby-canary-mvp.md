# Frozen 63-item local hobby canary MVP

## Result

The exact frozen Phase B canary was copied and reconciled end to end on
2026-08-13. The run is bound to:

- canary manifest
  `sha256:ee072650751fa76d456ba8cf034878a2a48137b02e6e7d459cb7945cb9474139`;
- frozen Phase A snapshot
  `sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d`;
- derived 63-item import snapshot
  `sha256:7fda956b0b924ff5fbc337c151fb07b1e4563efad8b3fdfec174e0614bd3e824`;
- core reconciliation
  `sha256:e36187d4137d0a7e184f7584103412ac9dad0f04cf846041596bfaf89991b64c`;
- semantic reconciliation
  `sha256:19496be401d99481464313c97e5a5edfeba6b0ee03f2f12e25d9fb0f02ffd470`;
- concise report
  `sha256:108be57c4ef180371fded6e4f65cd7301a07e96efa818a00e7e734033b46fb8c`.

The report is committed at
`fixtures/canary-mvp/phase-b-63-item-report-v1.json`.

## Outcomes

| Outcome         |  Items |   Source bytes |
| --------------- | -----: | -------------: |
| imported        |     36 |     42,423,291 |
| duplicate alias |     22 |        703,443 |
| excluded        |      5 |        958,003 |
| **total**       | **63** | **44,084,737** |

Exact source bytes were deduplicated into 36 content-addressed local objects,
totalling 42,423,291 bytes. The frozen derived canary snapshot and seven bounded interpretation outputs
bring the total to 44 committed CAS objects. Every stored object has a
`COMMITTED.json` marker. The same importer was run a second time and yielded the exact same core
reconciliation, establishing restart/idempotence on the local disposable CAS.

Conservative typed disposition records were created locally. Every applicable selected source also ran through the production network-denied migration worker: 331 approval rows were digest-captured into one inactive point-in-time snapshot, all four selected RecipeV01 sources parsed as schema-valid inactive revisions, and both selected generation JSON sources were deeply profiled without emitting raw restricted text. Approval targets and unresolved reviewer labels remain unresolved and non-authoritative.

No model binary was opened or deserialized. No provider was called. No recipe
was activated and no effective pointer moved.

## Hobby boundary

The disposable blobs live under the dedicated local `.canary-mvp-local/blobs` tree. SQLite authority, worker staging, and immutable records live separately under `.canary-mvp-local/metadata`; checked report output is copied from `.canary-mvp-local/evidence`. The run has no NAS, SMB, service-account, network, provider, or credential dependency.

The complete 44,682-item import, NAS migration, backups, provider spend, automatic activation, model training, and source-of-truth cutover remain unauthorized.

## Manual inspection and rebuild

The run is deliberately manual-inspection-only. Applicable canary interpretation is complete, but approval target/reviewer uncertainty, archived models, and the absence of any effective recipe-pointer change intentionally prevent activation or stronger authority claims.

To discard only disposable bytes, delete the contents of `.canary-mvp-local/blobs`. Never delete `.canary-mvp-local/metadata` when retaining the local audit trail. To rebuild locally, recreate an empty blob directory and run:

```sh
uv run python -m tidy_orchestrator.canary_mvp_cli run \
  --source-root /Users/ian/projects/tidycell \
  --metadata-root .canary-mvp-local/metadata \
  --blob-root .canary-mvp-local/blobs \
  --output-root .canary-mvp-local/evidence
```

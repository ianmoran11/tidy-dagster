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
  `sha256:5b322226dac14f511ffdd374a161b1803ba3088ecb3fc41b61f67c66de1d51d7`;
- semantic reconciliation
  `sha256:50718b4e1eea98ab7f7d7e2a0399eff6b02c3cd6af6ba5fa2bb7ee07aae22021`;
- concise report
  `sha256:754cfba2cc04ad4598862985df8e2754212c659f34f2f998404d2c222b613b0b`.

The report is committed at
`fixtures/canary-mvp/phase-b-63-item-report-v1.json`.

## Outcomes

| Outcome           |  Items |   Source bytes |
| ----------------- | -----: | -------------: |
| imported          |     36 |     42,423,291 |
| duplicate alias   |     22 |        703,443 |
| excluded          |      5 |        958,003 |
| **item outcomes** | **63** | **44,084,737** |

Actual regular-file source reads total 44,084,669 bytes. The additional 68 outcome bytes describe one excluded symlink target that was verified without reading or following a file. The run recorded zero failures (`failureCount: 0`, `failures: []`).

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

To discard only disposable bytes, delete the contents of `.canary-mvp-local/blobs`. Never delete `.canary-mvp-local/metadata` when retaining the local audit trail. The importer reconstructs every missing source and derived CAS object from digest-bound source bytes while reusing the immutable local authority records. To rebuild the deleted blob tree, recreate the empty directory and run:

```sh
uv run python -m tidy_orchestrator.canary_mvp_cli run \
  --source-root /Users/ian/projects/tidycell \
  --metadata-root .canary-mvp-local/metadata \
  --blob-root .canary-mvp-local/blobs \
  --output-root .canary-mvp-local/evidence
```

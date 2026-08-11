# Migration worker protocol v1

`tidy.migration-worker/v1` is a separate, provider-free, one-shot TypeScript
boundary for migration interpretation. It deliberately does not extend the
accepted production `tidy.worker/v1` protocol.

## Operations

- `health` and `capabilities` require no inputs.
- `digest-legacy-approval-registry-v1` validates the exact bounded
  point-in-time version-1 `{version, approvals}` legacy registry and emits the
  Phase-A-pinned TidyCell `digestRecord` for every approval row.
- `parse-recipe-v01` validates and normalizes one RecipeV01 document, computes
  its historical TidyCell digest, and emits an inactive, training-ineligible
  schema-valid revision artifact. An optional declared digest is compared but
  never treated as approval.

Every interpretation request binds the frozen source snapshot, source item,
import record, and original relative path. The executable re-verifies staged
input byte length and SHA-256, rejects symlink traversal and overlapping roots,
enforces byte/JSON depth/node/record limits, and atomically publishes only
declared output files.

The worker has no provider, model, repository, approval, pointer, or network
capability. `MigrationWorkerGateway` in Python now performs exact imported-CAS
source authorization, process-group and resource controls, production macOS
Seatbelt launch, worker bundle/source/vector/contract/runtime identity, strict
output-schema and JSON-complexity verification, independent declared-recipe-
digest checking, durable output CAS publication, and one-transaction custody,
derivation, and reproduction publication. The effective Seatbelt profile is
digest-bound and uses narrow process/Mach allowlists. Insecure test mode is
explicitly recorded as non-isolating in both worker custody and any derived
approval snapshot. Neither mode can activate a recipe or grant training
authority.

## Contracts

- `request.schema.json` — operation-specific strict request envelope.
- `success.schema.json` and `error.schema.json` — bounded result envelopes.
- `approval-row-digests.schema.json` — exact historical per-row digest output.
- `recipe-revision.schema.json` — normalized inactive RecipeV01 revision output.

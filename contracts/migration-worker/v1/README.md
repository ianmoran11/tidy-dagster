# Migration worker protocol v1

`tidy.migration-worker/v1` is a separate, provider-free, one-shot TypeScript
boundary for migration interpretation. It deliberately does not extend the
accepted production `tidy.worker/v1` protocol.

## Operations

- `health` and `capabilities` require no inputs.
- `digest-legacy-approval-registry-v1` validates a bounded point-in-time legacy
  approval array and emits the exact Phase-A-pinned TidyCell `digestRecord` for
  every row.
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
capability. Python remains responsible for authorization, sandbox launch,
producer-bundle identity, durable custody, and reconciliation.

## Contracts

- `request.schema.json` — operation-specific strict request envelope.
- `success.schema.json` and `error.schema.json` — bounded result envelopes.
- `approval-row-digests.schema.json` — exact historical per-row digest output.
- `recipe-revision.schema.json` — normalized inactive RecipeV01 revision output.

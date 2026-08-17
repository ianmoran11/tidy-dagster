# ADR: vendored local ML hints for fresh live generation

Status: accepted

## Decision

Fresh provider-backed `live` generation uses the vendored TidyCell
`all-approved-gold` exclusion XGBoost pair by default. Replay and live runs from
already-captured responses do not invoke ML and preserve their historical prompt
and strict-v1 evidence bytes.

`extract-ml-features-v1` parses the digest-declared workbook, selects the exact
sheet, ports the approved TidyCell feature algorithm, and emits only cell
addresses and the task-specific 56/54-number encoded vectors. The isolated
Python runner verifies those bindings and loads only native XGBoost JSON. The
original pickle bytes are retained solely as non-runnable custody sources and
are never opened by runtime code.

Production inference requires macOS `/usr/bin/sandbox-exec`. Its deny-default
profile denies networking and process forks and uses private roots, an
allowlisted environment, single-threaded boosters, and fixed time/CPU/file
and output limits. The gateway copies the verified manifest and native models
into a private snapshot tree that is distinct from the writable request, output,
temporary, and runtime tree. Production Seatbelt grants the runner read-only
access to the snapshot tree and no write, unlink, rename, or metadata-change
permission there; the gateway also applies read-only filesystem modes and
reverifies the snapshot after every clean runner exit. The runner has no read
access to the custody pickle paths. `insecure-test-only` exists only as an
explicitly constructor-injected test configuration; no CLI flag or environment
variable selects it.

Feature and hint identities use `canonical-json-v1`: UTF-8-byte key ordering,
UTF-8 JSON strings, and normalized 17-place binary64 scientific numbers. Shared
Unicode and exponent vectors test TypeScript/Python round trips.

A successful inference produces the strict `tidy.ml-hints/v1` artifact, bound to
the workbook digest, sheet, feature digest, package manifest, exact native model
hashes, and exact source cohort hash. `prepare-semantic-map-v13` accepts that
optional digest-declared input. The original prompt builder/version is unchanged;
a separately versioned extension compacts categorical predictions into ranges
and states that hints may be wrong and have no semantic or acceptance authority.

Missing optional XGBoost runtime, timeout/resource exhaustion, or a clean
inference failure falls back to the exact one-input baseline prompt. Package,
manifest, digest, schema, workbook, sheet, or sandbox integrity failures stop
before provider dispatch. There is no retry and no additional provider call.
Hints do not enter semantic-map interpretation, RecipeV01, selectors, execution,
acceptance, decisions, dashboards, or Dagster authority. Fresh live attempt
evidence records status and package/model/feature/hint provenance; historical
replay evidence is not rewritten.

## Package custody

The closed package is `vendor/tidycell-ml/all-approved-gold-exclusion-v1`.
`manifest.json` declares every other file and runtime verifies the exact closure.
`conversion-receipt.json` records the sandbox policy, toolchain, fixed-vector
probability/argmax parity, cohort identity, and native hashes. The public `scripts/convert_tidycell_ml_models.py` command launches its private
pickle-loading child under `/usr/bin/sandbox-exec`. Before deserialization the
child actively proves that both a loopback network bind and `fork()` are denied;
a plain invocation cannot produce a receipt. `--check` converts into a private
temporary package and compares every byte. The converter is the only
tidy-dagster code permitted to deserialize the custody pickles, and its receipt
records fitted label mappings plus decoded-label and probability parity.

Practical v1 bounds are 25,000 explicit sheet cells, a 15 MB inference request,
a 5 MB stdout cap, 64 KB stderr cap, and an 8 second wall timeout.

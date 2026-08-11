# M3 provider-free runtime

## Scope

M3 implements the Python-owned authoritative local repository, the hardened
POSIX gateway to the TypeScript domain worker, and the Dagster-independent
fixture application. It does not implement Dagster, providers, ML, review
authority, semantic contracts, calibration, justice behavior, or Sembla.
M3 itself did not implement recipe summaries. A later post-M4 Phase C increment
now supports historical default sheet-summary and complete compact-context
contracts on the frozen four-sheet fixture cohort; this does not retroactively
expand M3 acceptance.

## Authority and identity

The repository keeps four concepts separate:

- exact bytes use `sha256:<64 lowercase hex>` identity and immutable blob paths;
- derivations contain only the operation/contract, ordered input and output
  digests, configuration digest, and producer digests;
- custody receipts record location, actor, and observation time without
  changing content or derivation identity; and
- mutable pointers are generic integer-revision compare-and-swap projections.

Canonical semantic JSON uses sorted keys, compact separators, UTF-8, and
non-finite-number rejection. Domain-separated SHA-256 prefixes every semantic
identity. It is deliberately not presented as the future justice-contract JCS
canonicalizer.

Blobs are written to a private same-filesystem staging file, hashed, flushed,
`fsync`ed, hard-linked into their final immutable location, and followed by a
SQLite metadata transaction. The unavoidable filesystem/database boundary is
blob-first: an interrupted publication can leave an unreferenced orphan blob,
but an authoritative content row is never deliberately inserted before the
verified blob exists. Repeating the same put repairs the missing metadata.
For a worker run, every output content row, custody receipt, reproduction
mapping, and derivation is committed in one transaction after all blobs are
durable; drift or a crash cannot expose an authoritative prefix of the set.
Blob reads use no-follow file descriptors and reject symlink/non-regular
poisoning. Detected tampered bytes are retained in the private quarantine.

## Gateway boundary

Each invocation receives private `0700` roots and `0400` input copies. The
request declares exact lengths and digests. Python launches an argument vector
without a shell, closes inherited file descriptors, provides a small fixed
environment with no inherited credentials, starts a new POSIX session, and
applies address-space, CPU, file-size, and descriptor limits where the host
supports them. Stdout and stderr are file-backed and capped. Responses reject
duplicate JSON keys, non-finite numbers, unknown fields, and out-of-contract
counts or lengths.

Production execution is currently macOS-only and requires
`/usr/bin/sandbox-exec`. Its generated deny-default Seatbelt profile allows
runtime reads only from the self-contained built worker bundle, the selected
Node installation and its exact linked Homebrew libraries/OpenSSL
configuration, required system locations, and the private run root. Runtime
dependencies are bundled rather than loaded from `node_modules`. The profile
permits writes only inside the private run root and denies both network and
process forks. The production demo therefore records
`networkIsolationEnforced: true`. The explicit `insecure-test-only` mode is
used only for portable failure drills; it records false and is not a production
sandbox. No non-macOS production sandbox has been selected.

Timeout sends `TERM` and then `KILL` to the process group. A direct child that
exits while same-group descendants remain is rejected and those descendants
are terminated. Detached descendants cannot be contained by process groups,
which is why production additionally denies process forks. Every output is
checked for confinement, symlinks, undeclared files, bounded traversal,
count/size, byte length, and SHA-256 before any output is published. A
pre-launch producer manifest binds the resolved executable, compiled worker
closure, command inputs, lock/toolchain metadata, and protocol contracts; it is
recomputed after execution so concurrent producer drift fails before
publication. A reproduction key excluding outputs binds one deterministic
input/configuration/producer tuple to one ordered output-set fingerprint and
rejects drift.

## Verification

```sh
uv sync --locked
uv run ruff check .
uv run python -m tidy_orchestrator.boundaries
uv run pytest -q
npm run check
npm run build
rm -rf .provider-free-demo
uv run tidy-provider-free demo \
  --repository .provider-free-demo/repository \
  --project-root "$PWD"
git diff --check
```

The demo uses only the three licensed synthetic fixture triplets and the
actual built TypeScript executable. Running it again against the same
repository must return the same suite index, derivation IDs, reproduction
keys, and output fingerprints. Custody observations may be appended without
changing those deterministic identities.

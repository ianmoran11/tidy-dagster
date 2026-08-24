# Consolidated SQLite data-asset export

The consolidated export schema is `tidy.sqlite-data-asset-export/v1`. It is a
local, replaceable query projection of the complete explicit
`fixtures/product-prototype/data-asset-status-v1.json` registry. The exporter
does not discover files. A build fails closed unless every registered cohort
and sheet-asset passes the existing digest/length-checked status evidence,
every accepted row maps to exactly one registered asset, authority digests and all declared counts agree, and the manifest/run provider
and non-authority boundaries pass strict type checks. Manifest/run accepted,
exception, and canonical aggregate counts must be non-boolean non-negative
integers, equal each other, and equal registered/derived totals. Declared raw
and excluded aggregates are likewise type-checked, cross-checked when present
in both files, and bound to totals derived from the registered workbook reports.

The export is **not acceptance authority**, is **not training-eligible**, and
makes **zero provider calls**. Those boundaries are stored as checked integer
zeroes in `export_metadata`. Acceptance remains with the existing contracts,
decisions, and evidence; this database can be deleted and rebuilt without
changing them.

## Build, check, and path behavior

The default raw database is ignored local output:

```sh
scripts/tidy-sqlite-export build
scripts/tidy-sqlite-export check
```

Successful commands print one compact JSON object on stdout, including the
artifact path, byte length, SHA-256, schema version, logical digest, counts, and
boundary results. A controlled error prints `sqlite export error: ...` on
stderr and exits `2` without JSON output. Relative output paths are resolved
from `--project-root`; the registry path is relative to that root.

Build writes a temporary database in the destination directory, closes it in
`journal_mode=DELETE`, sets mode `0644`, and atomically replaces the destination.
It refuses output symlinks, existing output WAL/SHM/journal sidecars, and any
path that resolves to a registered input: the registry, cohort/evidence/
acceptance manifests, a declared evidence file, or a registered source
workbook. It never removes sidecars belonging to an existing destination. A
successful result is one raw `.sqlite3` file with no sidecars.

To select another ignored local path:

```sh
scripts/tidy-sqlite-export build \
  --output .product-prototype/sqlite-export/all-assets.sqlite3
scripts/tidy-sqlite-export check \
  --database .product-prototype/sqlite-export/all-assets.sqlite3
```

`check` uses normal read-only SQLite locking. It hashes the file before and
after validation and rejects changes or WAL/SHM/journal sidecars. It runs
SQLite integrity and foreign-key checks; verifies exact DDL, columns, strict
constraints, metadata, and authority boundaries; rebuilds the current status
projection from registered evidence; revalidates provenance digest/lengths;
compares every relational value and semantic canonical-row JSON value, and
re-derives workbook cardinality plus accepted, exception, canonical, raw, and
excluded aggregate totals.

## Schema and identities

The schema has `publication`, `cohort`, `asset`, `asset_check`,
`provenance_file`, `observation`, and singleton `export_metadata` tables.

- IDs are stable natural identities; zero-based ordinals make deterministic
  publication/cohort/asset/provenance and per-asset row order explicit.
- Composite foreign keys ensure each observation's asset, cohort, and registry
  publication form one consistent hierarchy.
- `provenance_file` records seven roles per cohort: `cohort_manifest`,
  `acceptance_contract`, `evidence_manifest`, `canonical_json`, `canonical_csv`,
  `run`, and `collation`. Paths are project-relative and paired with literal
  SHA-256 and byte length.
- `observation.publication_id` is the current status-registry grouping identity.
  `canonical_publication_id` preserves the publication identity in the source
  canonical row. They intentionally differ for historical Prisoners evidence
  (`prisoners-australia` versus `prisoners-in-australia`).
- `value_type` selects exactly one of `value_integer` or `value_real`, or neither
  for null. `raw_value_type` distinguishes missing, null, boolean, integer,
  real, and string and permits only its corresponding payload column. Strict
  CHECK constraints enforce discriminator/payload exclusivity.
- Decision, policy, recipe, execution, prompt-package, source, and generation
  provenance are queryable columns. Canonical decision IDs are bound to the
  registered asset decision. Policy identity is derived from the cohort's
  digest-checked acceptance contract using the existing v1/v2 policy semantics
  and is cross-checked with manifest/run contract declarations.

`canonical_json` stores a deterministic canonical serialization of every
complete canonical row. It is **semantically lossless**, including heterogeneous
keys and JSON scalar types: decoding it reproduces the canonical row value.
It is not lexically lossless with respect to whitespace or original JSON key
order in the evidence array.

Examples:

```sh
sqlite3 .product-prototype/sqlite-export/tidy-data-asset-status.sqlite3 \
  'select publication_id, count(*) from observation group by publication_id;'

sqlite3 -header -column \
  .product-prototype/sqlite-export/tidy-data-asset-status.sqlite3 \
  "select measure_id, unit_id, value_status, value_type, count(*) as rows
     from observation group by 1,2,3,4 order by rows desc limit 20;"

sqlite3 .product-prototype/sqlite-export/tidy-data-asset-status.sqlite3 \
  "select canonical_json from observation where observation_id = 1;"
```

## Determinism and disk planning

For identical registered source bytes and the same implementation/schema,
logical rows, IDs, ordinals, provenance, metadata, canonical JSON, and logical
SHA-256 are deterministic. Raw SQLite byte identity is not promised across
SQLite versions, platforms, or page-layout implementations. Gzip packaging is
byte-repeatable only when its raw SQLite input bytes are identical and the same
pinned compression implementation/runtime is used; gzip bytes are not promised
stable across SQLite or zlib/runtime versions.

Current approximate planning sizes are 57 MB downloaded (`.sqlite3.gz`) and
2.1 GB expanded (`.sqlite3`). Allow at least 4.3 GB free for an atomic rebuild
when an old raw database and the new temporary database coexist, plus temporary
and package headroom; 5 GB free is a practical minimum. Recompute from command
JSON for each release rather than treating these approximations as limits.

## Release packaging

Create the **sole GitHub Release asset** as fixed-header gzip; do not upload
the raw local `.sqlite3` directly:

```sh
scripts/tidy-sqlite-export package
```

Packaging first retains the complete successful `check` result. While reading
the database it hashes and counts the exact bytes sent to gzip and requires
those metrics to equal the checked SHA-256 and length. It then decompresses the
temporary gzip and independently requires the expanded SHA-256 and length to
match before atomic replacement. Same source/output paths and output symlinks
are refused. Only after this continuity proof does JSON report
`validatedAgainstEvidence: true` and `decompressedSourceVerified: true`.

The gzip header has an empty stored filename and timestamp zero. The strict
size guard applies to this actual release asset: replacement is refused unless
it is **strictly less than 2 GiB** (`2,147,483,648` bytes). Record the printed
package byte length and SHA-256 in GitHub Release notes, then independently
verify before upload:

```sh
gzip -t .product-prototype/sqlite-export/tidy-data-asset-status.sqlite3.gz
shasum -a 256 \
  .product-prototype/sqlite-export/tidy-data-asset-status.sqlite3.gz
```

Create a GitHub Release from a reviewed tag and upload only the `.sqlite3.gz`
file. Include the registry/evidence revision, checksum, size, link to this
document, and non-authority statement. Publication, tag creation, and upload
are manual and outside this command.

## Attribution and licensing

The projected observations derive from Australian Bureau of Statistics (ABS)
publications. Release notes must retain appropriate ABS attribution, identify
source publications and vintages, and link to applicable ABS copyright and
Creative Commons licensing terms. Before distribution, a release reviewer must
confirm that attribution, third-party notices, source-specific caveats, and the
repository `LICENSE`/`THIRD_PARTY_NOTICES.md` fit the exact bundled scope. This
exporter does not make a new licensing determination.

# `tidy.worker/v1`

The M0–M2-scoped deterministic compatibility worker is a networkless file
transform. Build with `npm run build` and invoke the stable
`tidy-domain-worker` package bin with `--request FILE --input-root DIR
--output-root DIR`. Standard output contains exactly one JSON envelope line.
Exit 0 means success, exit 1 means a machine-readable request/domain failure,
and exit 2 means invocation or CLI infrastructure failure.

The strict public schemas are [`request.schema.json`](request.schema.json),
[`success.schema.json`](success.schema.json), and
[`error.schema.json`](error.schema.json); machine-readable positive and
negative vectors are under [`vectors`](vectors). Unknown fields fail closed.
Each input declares an exact `byteLength` and SHA-256 digest. Names, request
IDs, paths, messages, envelope bytes, aggregate inputs and outputs, XLSX
compressed bytes, ZIP central-directory entries and expanded sizes, sheets,
cells, merges, selectors, and output rows are bounded.

Before ExcelJS loads the workbook, a streaming preflight inflates every ZIP
entry once, counts actual decompressed bytes instead of trusting ZIP metadata,
and scans worksheet XML to enforce sheet, cell, merge, and merge-expansion
limits. ExcelJS then performs the compatibility parse, so launcher memory and
time budgets must account for these two bounded passes. Manifest paths are
normalized portable relative paths and cannot traverse symlinks. Input and
output roots must be distinct,
non-nested, canonically non-overlapping, existing directories. Publication is
all-or-nothing: files are written and checked in a private sibling staging
directory before an atomic root rename, with staging cleaned on every failure.
Node cannot completely eliminate directory swap races without a trusted
launcher boundary, so the launcher must create private roots inaccessible to
other users/processes.

The request `timeoutMs` is declarative. Wall-clock cancellation, complete
process-tree termination, and hard process memory enforcement belong to the
M3 launcher and are not claimed by this M1/M2 worker.

`execute-recipe-v01` requires exactly `workbook` and `recipe`, with
`evidenceProfile` `m1-simple-v1` or `m2-deterministic-parity-v1`. It emits
parsed workbook, normalized recipe, selector, geometry, execution, and exact
recipe-aware CSV evidence. With `includeSummary: true`, it also emits
`sheet-summary.json` using the historical default options. With
`includeCompactContext: true`, it emits the complete row-major
`compact-context.json`. Both outputs match all four sheets in the three
relocated historical-source reference workbooks. With
`includeRegionCatalog: true`, it emits the bounded provider-free V5
`region-catalog.json`; 43 copied source-owned compiler/catalogue tests pass and
all four historical-reference catalogues match exactly. M2 remains incomplete
pending broader option/adversarial coverage and produced-CSV/rendered
prompt-input integration.

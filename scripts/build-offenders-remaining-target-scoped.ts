import { readFile, mkdir, writeFile } from "node:fs/promises";
import { basename, dirname, resolve } from "node:path";
import { parseWorkbook } from "../apps/domain-worker/src/workbook/parseWorkbook.js";
import type {
  ParsedSheet,
  TidyCell,
} from "../apps/domain-worker/src/workbook/types.js";
import {
  compileTargetScopedRecipeV02,
  executeTargetScopedRecipeV02,
  digestTargetScopedBytes,
  digestTargetScopedCanonical,
  MAX_TARGET_SCOPED_JSON_BYTES,
  MAX_TARGET_SCOPED_JSON_NODES,
  MAX_TARGET_SCOPED_ENVELOPE_BYTES,
  MAX_TARGET_SCOPED_ENVELOPE_NODES,
  MAX_TARGET_SCOPED_EXECUTION_BYTES,
  MAX_TARGET_SCOPED_EXECUTION_NODES,
  TARGET_SCOPED_SEMANTIC_MAP_V1,
  TARGET_SCOPED_SOURCE_CONTEXT_V1,
  type TargetScopedSemanticMapV1,
} from "../apps/domain-worker/src/catalog/target-scoped-recipe-v02.js";
import {
  digestAtomicRegionCatalog,
  type AtomicRegionCatalog,
} from "../apps/domain-worker/src/catalog/semantic-map-v2.js";
import {
  TARGET_SCOPED_RUNTIME_SOURCE_PATHS,
  assertContained,
  assertExactKeys,
  assertSafeComponent,
  beginTargetTransaction,
  countJsonNodes,
  digestFileRecords,
  jsonBytes,
  listRegularFiles,
  readPinnedJson,
  readRegularFile,
  sha256,
  stable,
  verifyPinnedClosure,
  verifyToolchainClosure,
  type FilePin,
} from "./offenders-target-scoped-safety.js";

const FIX = "fixtures/product-prototype";
const ROOT = ".product-prototype/offenders-remaining-phase1";
const ORACLE = `${ROOT}/source-partition-canary/run-a-remediated`;
const AUTH_DEFAULT = `${FIX}/offenders-remaining-target-scoped-generation-authorization-v1.json`;
const B2_AUTH = `${FIX}/offenders-remaining-semantic-generation-authorization-v1.json`;
const CAPABILITY = `${FIX}/offenders-remaining-capability-routing-pin-v1.json`;
const PLAN = `${FIX}/offenders-remaining-semantic-map-plan-v1.json`;
const PARTITION = `${ORACLE}/partition-manifest.json`;
const BUNDLE = `${ORACLE}/temporary-maps-recipes.json`;
const DISCREPANCY = `${ORACLE}/discrepancy-ledger.json`;
const COLLISION = `${ORACLE}/collision-ledger.json`;
const MEASUREMENT = `${ROOT}/multi-panel-b2a/measurement/exact-ownership-measurement.json`;
const METHOD_ALLOWLIST = `${ROOT}/source-partition-canary/method-anchor-allowlist-v1.json`;
const CANDIDATE_ALLOWLIST = `${ROOT}/source-partition-canary/candidate-correction-allowlist-v1.json`;
const REMEDIATED_MANIFEST = `${ORACLE}/manifest.json`;
const B2_AUTH_DIGEST =
  "sha256:13624947ec0620b0b48b64ef1cd9126a62fada7adad458f64be2598b8d7f4d6a";
const CAPABILITY_DIGEST =
  "sha256:62fb94b842714e7d8243950b9d92e6ed880e0228f6548d8955e4f18a5da939a4";
const EXPECTED = {
  members: 18,
  families: 6,
  rows: 28681,
  partitions: 262,
  universes: 2206,
  attachments: 8131,
  vectors: 28681,
  operations: 1160748,
  changes: 2739,
  b2aChanges: 49628,
  combinedChanges: 52367,
};

function arg(name: string, fallback?: string): string {
  const i = process.argv.indexOf(name);
  if (i >= 0 && process.argv[i + 1]) return process.argv[i + 1];
  if (fallback !== undefined) return fallback;
  throw Error(`${name} required`);
}
function args(name: string): string[] {
  const values: string[] = [];
  for (let i = 0; i < process.argv.length; i++)
    if (process.argv[i] === name && process.argv[i + 1])
      values.push(process.argv[++i]);
  return values;
}
const requestedOut = arg("--out");
const authPath = arg("--authorization", AUTH_DEFAULT);
const expectedAuthDigest = arg("--authorization-digest");
const verificationReplay = process.argv.includes("--verification-replay");
const verificationToken = process.argv.includes("--verification-token")
  ? arg("--verification-token")
  : undefined;
const forbiddenReplayRoots = args("--verification-forbid-root");
if (verificationReplay) {
  if (
    !verificationToken ||
    !/^[a-f0-9-]{36}$/.test(verificationToken) ||
    process.env.C2_VERIFIER_REPLAY_TOKEN !== verificationToken ||
    !/^run-verify-[A-Za-z0-9._-]+$/.test(basename(requestedOut)) ||
    dirname(resolve(requestedOut)) !==
      resolve(
        ".product-prototype/offenders-remaining-phase1/target-scoped-c2",
      ) ||
    forbiddenReplayRoots.some((path) => resolve(path) === resolve(requestedOut))
  )
    throw Error("INVALID_VERIFICATION_REPLAY_HANDSHAKE");
} else if (
  basename(requestedOut).startsWith("run-verify-") ||
  verificationToken ||
  forbiddenReplayRoots.length ||
  process.env.C2_VERIFIER_REPLAY_TOKEN
) {
  throw Error("VERIFICATION_REPLAY_MODE_REQUIRED");
}
const injected = process.argv.includes("--inject-failure")
  ? arg("--inject-failure")
  : undefined;
assertContained(authPath, FIX, "authorization");
const tx = await beginTargetTransaction(requestedOut, injected);
const OUT = tx.temporaryPath;
if (injected === "hold-lock") {
  await new Promise((resolve) => setTimeout(resolve, 5_000));
  await tx.abort();
  throw Error("INJECTED_FAILURE:hold-lock");
}

const authBytes = await readRegularFile(authPath, ".", "authorization");
if (sha256(authBytes) !== expectedAuthDigest)
  throw Error("EXTERNAL_TARGET_AUTHORIZATION_PIN_MISMATCH");
if (authBytes.length > 4_000_000) throw Error("AUTHORIZATION_BYTE_LIMIT");
const auth = JSON.parse(authBytes.toString("utf8"));
countJsonNodes(auth, 250000);
assertExactKeys(
  auth,
  [
    "schemaVersion",
    "authorizedForTargetScopedEngineering",
    "pendingExternalAuthorizationReview",
    "acceptanceAuthority",
    "trainingEligibility",
    "productionAcceptance",
    "promotionAuthorization",
    "authorizationBoundary",
    "toolchainClosure",
    "runtimeSourceClosure",
    "inputs",
    "expectedScope",
    "reviewStatus",
  ],
  "authorization",
);
if (
  auth.schemaVersion !==
    "tidy.offenders-target-scoped-generation-authorization/v1" ||
  auth.authorizedForTargetScopedEngineering !== true ||
  auth.pendingExternalAuthorizationReview !== true ||
  auth.acceptanceAuthority !== false ||
  auth.trainingEligibility !== false ||
  auth.productionAcceptance !== false ||
  auth.promotionAuthorization !== false ||
  auth.reviewStatus !== "pending-independent-review" ||
  stable(auth.expectedScope) !== stable(EXPECTED)
)
  throw Error("INVALID_TARGET_AUTHORIZATION");
const pins = new Map<string, FilePin>();
for (const p of auth.inputs as FilePin[]) {
  if (pins.has(p.path)) throw Error(`DUPLICATE_INPUT_PIN:${p.path}`);
  pins.set(p.path, p);
}
await verifyPinnedClosure(
  auth.runtimeSourceClosure,
  TARGET_SCOPED_RUNTIME_SOURCE_PATHS,
);
for (const p of auth.runtimeSourceClosure as FilePin[]) {
  const q = pins.get(p.path);
  if (!q || stable(p) !== stable(q))
    throw Error(`RUNTIME_INPUT_PIN_MISMATCH:${p.path}`);
}
// Verify every externally declared byte before parsing any semantic artifact.
for (const p of auth.inputs as FilePin[]) {
  assertExactKeys(
    p,
    ["path", "byteLength", "sha256"],
    "authorization-input-pin",
  );
  const b = await readRegularFile(p.path, ".", "authorization-input");
  if (b.length !== p.byteLength || sha256(b) !== p.sha256)
    throw Error(`AUTH_INPUT_DRIFT:${p.path}`);
}
await verifyToolchainClosure(auth.toolchainClosure, pins);
async function pinned(
  path: string,
  maxBytes = 450_000_000,
  maxNodes = 15_000_000,
) {
  const p = pins.get(path);
  if (!p) throw Error(`UNPINNED_INPUT:${path}`);
  return readPinnedJson(path, p, maxBytes, maxNodes);
}
for (const required of [
  B2_AUTH,
  CAPABILITY,
  PLAN,
  PARTITION,
  BUNDLE,
  DISCREPANCY,
  COLLISION,
  MEASUREMENT,
  METHOD_ALLOWLIST,
  CANDIDATE_ALLOWLIST,
  REMEDIATED_MANIFEST,
  "apps/domain-worker/src/catalog/target-scoped-recipe-v02.ts",
  "apps/domain-worker/test/target-scoped-recipe-v02.test.ts",
]) {
  if (!pins.has(required)) throw Error(`MISSING_REQUIRED_PIN:${required}`);
}
if (
  pins.get(B2_AUTH)!.sha256 !== B2_AUTH_DIGEST ||
  pins.get(CAPABILITY)!.sha256 !== CAPABILITY_DIGEST ||
  pins.get(PARTITION)!.sha256 !==
    "sha256:f8b15cff3272b53b014f6072150b9d97370badf1a0469b197f75f6554a74e627" ||
  pins.get(DISCREPANCY)!.sha256 !==
    "sha256:2a5efea1ed2b9e7e2f616c4ec6237ee625646ff80c0464d1b9e9f49a4a249bf4" ||
  pins.get(BUNDLE)!.sha256 !==
    "sha256:d9b26eba899305ce18e1de10c11e5eba98a0fb3cf96dd789afe40f4e3ccc0641" ||
  pins.get(MEASUREMENT)!.sha256 !==
    "sha256:40c1ae487058c13aff3e2c1ec4d9549d1c9e1f95a02a68ff7f28341774ab1537" ||
  pins.get(COLLISION)!.sha256 !==
    "sha256:b8f19c61e5b85b45e6cfe7750c397246587b5305eef5bc875de44827ab0c5a7a" ||
  pins.get(REMEDIATED_MANIFEST)!.sha256 !==
    "sha256:36105ed0df04f12e9ab56ae656eabb62b247bafa08795c37cba96ed43f957509" ||
  pins.get("apps/domain-worker/src/catalog/target-scoped-recipe-v02.ts")!
    .sha256 !==
    "sha256:2295c5e6cf8ad45168e16fa17627f63710170351982f986b602eec25a6b281b9" ||
  pins.get("apps/domain-worker/test/target-scoped-recipe-v02.test.ts")!
    .sha256 !==
    "sha256:a50abb00132fad06dd8bb80c08c4cc906effeecafb1fbf139b957eefcd33083d"
)
  throw Error("REVIEWED_DIGEST_DRIFT");
const capability = await pinned(CAPABILITY, 2_000_000, 100000),
  plan = await pinned(PLAN),
  ownership = await pinned(PARTITION),
  bundles = await pinned(BUNDLE),
  discrepancies = await pinned(DISCREPANCY),
  collisions = await pinned(COLLISION),
  measurement = await pinned(MEASUREMENT);
await pinned(B2_AUTH);
await pinned(METHOD_ALLOWLIST);
await pinned(CANDIDATE_ALLOWLIST);
await pinned(REMEDIATED_MANIFEST);
const targets = capability.members.filter(
  (m: any) => m.status === "target-scoped-required",
);
if (
  targets.length !== EXPECTED.members ||
  targets.reduce((s: number, m: any) => s + m.rows, 0) !== EXPECTED.rows ||
  new Set(targets.map((m: any) => m.familyId)).size !== EXPECTED.families
)
  throw Error("CAPABILITY_TARGET_SCOPE");
if (capability.members.length !== 170) throw Error("CAPABILITY_CAMPAIGN_SCOPE");

function key(m: any) {
  return `${m.familyId}:${m.year}`;
}
function pos(a: string): [number, number] {
  const m = /^R(\d+)C(\d+)$/.exec(a);
  if (!m) throw Error(`BAD_ADDRESS:${a}`);
  return [+m[1], +m[2]];
}
function cmp(a: string, b: string) {
  const x = pos(a),
    y = pos(b);
  return x[0] - y[0] || x[1] - y[1];
}
function unique<T>(xs: T[], label: string): T[] {
  if (new Set(xs).size !== xs.length) throw Error(`DUPLICATE:${label}`);
  return xs;
}
function distinct<T>(xs: T[]): T[] {
  return [...new Set(xs)];
}
function selectors(
  addresses: string[],
): Array<{ address: string } | { range: string }> {
  const xs = unique([...addresses].sort(cmp), "selector-address");
  const out: any[] = [];
  let i = 0;
  while (i < xs.length) {
    const [r, c] = pos(xs[i]);
    let j = i;
    while (j + 1 < xs.length) {
      const [nr, nc] = pos(xs[j + 1]);
      if (nr !== r || nc !== c + (j + 1 - i)) break;
      j++;
    }
    out.push(
      j > i ? { range: `R${r}C${c}:R${r}C${c + j - i}` } : { address: xs[i] },
    );
    i = j + 1;
  }
  return out;
}
function cellMap(sheet: ParsedSheet) {
  return new Map(sheet.cells.map((c) => [c.address, c]));
}
function opt(o: any, k: string) {
  return Object.prototype.hasOwnProperty.call(o, k)
    ? o[k] === undefined
      ? { state: "undefined" }
      : { state: "value", value: o[k] }
    : { state: "absent" };
}
function cellProof(c: TidyCell | undefined) {
  if (!c) throw Error("MISSING_EQUIVALENCE_CELL");
  return {
    sheet: c.sheet,
    address: c.address,
    row: c.row,
    col: c.col,
    value: c.value,
    data_type: c.data_type,
    formula: opt(c, "formula"),
    formatted: opt(c, "formatted"),
    comment: opt(c, "comment"),
    hyperlink: opt(c, "hyperlink"),
    style: opt(c, "style"),
    merge: opt(c, "merge"),
  };
}
function selectedProof(sheet: ParsedSheet, addresses: string[]) {
  const cells = cellMap(sheet);
  return {
    sheet: sheet.name,
    addresses: addresses.map((a) => cellProof(cells.get(a))),
    merges: sheet.merges.filter((m) =>
      addresses.some((a) => {
        const [r, c] = pos(a);
        const z = /^R(\d+)C(\d+):R(\d+)C(\d+)$/.exec(m.range)!;
        return r >= +z[1] && r <= +z[3] && c >= +z[2] && c <= +z[4];
      }),
    ),
  };
}
function exact(a: any, b: any) {
  return Object.is(a, b);
}
function norm(v: any) {
  return typeof v === "string" ? v.trim().replace(/\s+/g, " ") : v;
}
function alias(v: any) {
  return String(norm(v))
    .replace(/(?:\s*\([a-z]\))+$/gi, "")
    .toUpperCase()
    .trim()
    .replace(/\s+/g, " ");
}
function code(v: any) {
  const raw = alias(v),
    slug = raw.replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "VALUE";
  return `${slug.slice(0, 80)}_${sha256(raw).slice(7, 15)}`;
}
function collisionAudit(rows: any[], dims: string[], date: string) {
  const modes: any[] = [
    ["exact", (v: any) => `${typeof v}:${stable(v)}`],
    ["normalized", (v: any) => `${typeof norm(v)}:${stable(norm(v))}`],
    ["canonical", code],
  ];
  const out: any = {};
  for (const [n, f] of modes) {
    const seen = new Set<string>();
    let excess = 0;
    for (const r of rows) {
      const k = stable([
        date,
        date,
        ...dims.map((d) => f(r[d])),
        "published-value",
      ]);
      if (seen.has(k)) excess++;
      seen.add(k);
    }
    out[`${n}DuplicateExcess`] = excess;
  }
  let aliases = 0;
  for (const d of dims) {
    const by = new Map<string, Set<string>>();
    for (const r of rows) {
      const c = code(r[d]),
        s = by.get(c) || new Set();
      s.add(alias(r[d]));
      by.set(c, s);
    }
    aliases += [...by.values()].filter((s) => s.size > 1).length;
  }
  out.aliasCollisions = aliases;
  return out;
}
function resources(v: any) {
  const b = jsonBytes(v);
  return {
    bytes: b.length,
    nodes: countJsonNodes(v, 3_000_000),
    digest: sha256(b),
  };
}

const by = (items: any[]) => new Map(items.map((m) => [key(m), m]));
const ownershipBy = by(ownership.members),
  bundleBy = by(bundles.members),
  measureBy = by(measurement.members),
  collisionBy = by(collisions.members);
const planBy = new Map(plan.families.map((f: any) => [f.familyId, f]));
for (const collection of [ownershipBy, bundleBy, measureBy, collisionBy])
  if (collection.size !== 170) throw Error("ORACLE_IDENTITY_CLOSURE");
const discrepancyBy = new Map<string, any>();
for (const d of discrepancies.rows) {
  const k = `${d.familyId}:${d.year}:${d.valueAddress}:${d.dimension}`;
  if (discrepancyBy.has(k)) throw Error(`DUPLICATE_LEDGER:${k}`);
  discrepancyBy.set(k, d);
}
const expectedLedgerKeys = new Set<string>();
for (const m of targets)
  for (const d of discrepancies.rows)
    if (d.familyId === m.familyId && d.year === m.year) {
      if (
        d.changeClass !== "exact-source-null-repair" ||
        d.dimension === "method of proceeding"
      )
        throw Error("TARGET_LEDGER_CLASS");
      expectedLedgerKeys.add(
        `${d.familyId}:${d.year}:${d.valueAddress}:${d.dimension}`,
      );
    }
if (expectedLedgerKeys.size !== EXPECTED.changes)
  throw Error("TARGET_LEDGER_SCOPE");
const results: any[] = [];
const observedLedger = new Set<string>();
let totalRows = 0,
  totalPartitions = 0,
  totalUniverses = 0,
  totalAttachments = 0,
  totalVectors = 0,
  totalOps = 0;
let max: any = {
  mapBytes: 0,
  mapNodes: 0,
  envelopeBytes: 0,
  envelopeNodes: 0,
  executionBytes: 0,
  executionNodes: 0,
  operations: 0,
};
await mkdir(OUT, { recursive: true });
for (const route of [...targets].sort((a: any, b: any) =>
  a.familyId < b.familyId ? -1 : a.familyId > b.familyId ? 1 : a.year - b.year,
)) {
  const identity = key(route),
    oracle = ownershipBy.get(identity),
    bundle = bundleBy.get(identity),
    measure = measureBy.get(identity),
    family: any = planBy.get(route.familyId);
  if (!oracle || !bundle || !measure || !family)
    throw Error(`IDENTITY_JOIN:${identity}`);
  const planMember = family.members.find(
    (m: any) => Number(m.releaseId.slice(0, 4)) === route.year,
  );
  if (
    !planMember ||
    planMember.releaseId !== route.releaseId ||
    oracle.releaseId !== route.releaseId ||
    bundle.releaseId !== route.releaseId ||
    measure.releaseId !== route.releaseId
  )
    throw Error(`RELEASE_JOIN:${identity}`);
  const dims = planMember.semanticMap.table.dimensions.map((d: any) => d.name);
  if (stable(dims) !== stable(measure.dimensions))
    throw Error(`DIMENSION_ORDER:${identity}`);
  const parts = [...oracle.partitions].sort(
    (a: any, b: any) => a.partitionOrder - b.partitionOrder,
  );
  if (parts.length !== bundle.partitions.length)
    throw Error(`PARTITION_COUNT:${identity}`);
  unique(
    parts.map((p: any) => p.partitionId),
    `partition:${identity}`,
  );
  const tempBy = new Map(bundle.partitions.map((p: any) => [p.partitionId, p]));
  const targetSets: any[] = [],
    universes: any[] = [],
    attachments: any[] = [],
    vectors: any[] = [],
    mapTargets: any[] = [];
  const universeId = new Map<string, string>(),
    attachmentId = new Map<string, string>();
  let ui = 0,
    ai = 0,
    vi = 0;
  const assignments = parts
    .flatMap((p: any) => p.valueAssignments)
    .sort((a: any, b: any) => cmp(a.valueAddress, b.valueAddress));
  if (
    assignments.length !== route.rows ||
    assignments.length !== oracle.expectedCount ||
    stable(assignments.map((a: any) => a.valueAddress)) !==
      stable([...oracle.expectedValueAddresses].sort(cmp))
  )
    throw Error(`TARGET_CLOSURE:${identity}`);
  for (const [pi, p] of parts.entries()) {
    const temp: any = tempBy.get(p.partitionId);
    if (
      !temp ||
      temp.partitionOrder !== p.partitionOrder ||
      stable([...temp.valueAddresses].sort(cmp)) !==
        stable(p.valueAssignments.map((a: any) => a.valueAddress).sort(cmp)) ||
      temp.warnings?.length
    )
      throw Error(`PARTITION_JOIN:${identity}:${p.partitionId}`);
    const valueAddresses = p.valueAssignments
      .map((a: any) => a.valueAddress)
      .sort(cmp);
    const parents = Object.entries(temp.sourcePartitions)
      .filter(([, xs]: any) =>
        valueAddresses.every((a: string) => xs.includes(a)),
      )
      .map(([id]) => id);
    if (parents.length !== 1)
      throw Error(`TARGET_PARENT:${identity}:${p.partitionId}`);
    targetSets.push({
      id: `t${String(pi + 1).padStart(4, "0")}`,
      regionId: parents[0],
      selectors: selectors(valueAddresses),
    });
    for (const dim of dims as string[]) {
      for (const region of distinct<string>(
        p.valueAssignments.map((a: any) =>
          String(a.dimensionSources[dim].candidateRegionId),
        ),
      )) {
        const scoped = p.valueAssignments.filter(
          (a: any) => a.dimensionSources[dim].candidateRegionId === region,
        );
        const directions = distinct<string>(
          scoped.map((a: any) => String(a.dimensionSources[dim].direction)),
        );
        if (directions.length !== 1) throw Error("DIRECTION_SCOPE");
        const addresses = distinct<string>(
          scoped.map((a: any) => String(a.dimensionSources[dim].sourceAddress)),
        ).sort(cmp);
        const sourcePart: string[] = temp.sourcePartitions[region];
        if (
          !sourcePart ||
          addresses.some((a: string) => !sourcePart.includes(a))
        )
          throw Error(`SOURCE_SUBSET:${identity}`);
        const uk = `${p.partitionId}|${dim}|${region}|${directions[0]}`,
          id = `u${String(++ui).padStart(4, "0")}`;
        universeId.set(uk, id);
        universes.push({
          id,
          regionId: region,
          selectors: selectors(addresses),
        });
      }
    }
    for (const a of [...p.valueAssignments].sort((x: any, y: any) =>
      cmp(x.valueAddress, y.valueAddress),
    )) {
      const ids: string[] = [];
      for (const [di, dim] of dims.entries()) {
        const s = a.dimensionSources[dim];
        if (
          !s ||
          !exact(s.exactTypedRawLabel.value, s.exactTypedRawLabel.value) ||
          !["string", "number"].includes(s.exactTypedRawLabel.type)
        )
          throw Error(`ASSIGNMENT_DIMENSION:${identity}`);
        const uk = `${p.partitionId}|${dim}|${s.candidateRegionId}|${s.direction}`,
          uid = universeId.get(uk);
        if (!uid) throw Error("UNIVERSE_LOOKUP");
        const ak = `${dim}|${s.direction}|${s.sourceAddress}|${uid}`;
        let id = attachmentId.get(ak);
        if (!id) {
          id = `a${String(++ai).padStart(6, "0")}`;
          attachmentId.set(ak, id);
          attachments.push({
            id,
            dimensionId: `d${String(di + 1).padStart(2, "0")}`,
            direction: s.direction,
            selectedAddress: s.sourceAddress,
            universeId: uid,
          });
        }
        ids.push(id);
      }
      const vid = `v${String(++vi).padStart(6, "0")}`;
      vectors.push({ id: vid, attachmentIds: ids });
      mapTargets.push({
        address: a.valueAddress,
        targetSetId: `t${String(pi + 1).padStart(4, "0")}`,
        vectorId: vid,
      });
    }
  }
  if (stable(dims) !== stable(Object.keys(assignments[0].dimensionSources)))
    throw Error(`ASSIGNMENT_DIMENSION_KEYS:${identity}`);
  if (
    measure.assignments !== assignments.length ||
    measure.exactSourceVectors !== assignments.length
  )
    throw Error(`MEASUREMENT_JOIN:${identity}`);
  const catalogPath = bundle.catalogPath;
  if (!pins.has(catalogPath)) throw Error(`UNPINNED_CATALOG:${identity}`);
  const catalogPayload = await pinned(catalogPath, 20_000_000, 600000),
    catalog = catalogPayload.catalog as AtomicRegionCatalog;
  const catalogRaw = JSON.stringify(catalog),
    catalogDigest = digestTargetScopedBytes(catalogRaw);
  const executionPath = `${FIX}/${oracle.executionWorkbookPath}`,
    sourcePath = `${FIX}/${oracle.sourceWorkbookPath}`;
  for (const p of [executionPath, sourcePath])
    if (!pins.has(p)) throw Error(`UNPINNED_WORKBOOK:${p}`);
  const executionBytes = await readRegularFile(
    executionPath,
    ".",
    "execution-workbook",
  );
  if (
    sha256(executionBytes) !== oracle.executionWorkbookDigest ||
    oracle.executionWorkbookDigest !== planMember.executionDigest
  )
    throw Error(`EXECUTION_CUSTODY:${identity}`);
  const parsed = await parseWorkbook(executionBytes);
  if (!parsed.ok) throw Error(`WORKBOOK_PARSE:${identity}`);
  const sheet = parsed.workbook.sheets.find(
    (s) => s.name === oracle.physicalSheetIdentity,
  );
  if (!sheet || sheet.name !== planMember.physicalSheetName)
    throw Error(`SHEET_IDENTITY:${identity}`);
  const map: TargetScopedSemanticMapV1 = {
    version: TARGET_SCOPED_SEMANTIC_MAP_V1,
    catalog: {
      version: catalog.version,
      bytesDigest: catalogDigest,
      contentDigest: digestAtomicRegionCatalog(catalog),
    },
    source: {
      version: TARGET_SCOPED_SOURCE_CONTEXT_V1,
      workbookDigest: oracle.executionWorkbookDigest,
      physicalSheet: sheet.name,
    },
    logicalTable: {
      id: "offenders-target",
      name: planMember.semanticMap.table.name,
      valuesName: planMember.semanticMap.table.values.name,
      dimensions: dims.map((name: string, i: number) => ({
        id: `d${String(i + 1).padStart(2, "0")}`,
        name,
      })),
    },
    targetSets,
    sourceUniverses: universes,
    attachments,
    vectors,
    targets: mapTargets,
  };
  const mapRaw = JSON.stringify(map),
    mapDigest = digestTargetScopedBytes(mapRaw);
  const compiled = compileTargetScopedRecipeV02({
    mapRaw,
    expectedMapBytesDigest: mapDigest,
    catalogRaw,
    expectedCatalogBytesDigest: catalogDigest,
    sheet,
    source: map.source,
  });
  if (!compiled.ok)
    throw Error(
      `TARGET_COMPILE:${identity}:${compiled.stage}:${compiled.code}:${compiled.message}`,
    );
  const envelope = compiled.envelope;
  const execution = executeTargetScopedRecipeV02(envelope, {
    mapRaw,
    catalogRaw,
    sheet,
    source: map.source,
    trustedEnvelopeDigest: envelope.envelopeDigest,
  });
  if (
    execution.providerCalls !== 0 ||
    execution.warnings.length ||
    execution.table.rows.length !== assignments.length ||
    execution.table.trace.length !== assignments.length
  )
    throw Error(`EXECUTION_CLOSURE:${identity}`);
  const rows = execution.table.rows,
    trace = execution.table.trace;
  for (let i = 0; i < assignments.length; i++) {
    const a = assignments[i],
      r: any = rows[i],
      t: any = trace[i];
    if (
      r._source.address !== a.valueAddress ||
      t.target.address !== a.valueAddress ||
      !exact(r[map.logicalTable.valuesName], t.value)
    )
      throw Error(`TARGET_TRACE:${identity}:${a.valueAddress}`);
    for (const [di, dim] of dims.entries()) {
      const s = a.dimensionSources[dim],
        tr = t.attachments[di];
      if (
        !exact(r[dim], s.exactTypedRawLabel.value) ||
        r[`${dim}_source`] !== s.sourceAddress ||
        tr.dimensionName !== dim ||
        tr.direction !== s.direction ||
        tr.selected !== s.sourceAddress ||
        tr.candidates.length !== 1 ||
        tr.candidates[0] !== s.sourceAddress ||
        !exact(tr.value, s.exactTypedRawLabel.value) ||
        tr.source.data_type !==
          (s.exactTypedRawLabel.type === "number"
            ? "numeric"
            : s.exactTypedRawLabel.type)
      )
        throw Error(
          `ORACLE_ATTACHMENT:${identity}:${a.valueAddress}:${dim}:${stable({ rowValue: r[dim], rowSource: r[`${dim}_source`], oracleValue: s.exactTypedRawLabel.value, oracleSource: s.sourceAddress, trace: tr })}`,
        );
      if (
        r[dim] === null ||
        r[dim] === undefined ||
        typeof r[dim] === "boolean"
      )
        throw Error(`REQUIRED_DIMENSION:${identity}`);
    }
  }
  const cohortPath = `${FIX}/recorded-crime-offenders-${route.familyId}.json`;
  const cohort = await pinned(cohortPath, 10_000_000, 600000),
    entry = cohort.workbooks.find((x: any) => x.year === route.year);
  if (
    !entry ||
    entry.path !== oracle.executionWorkbookPath ||
    entry.contentDigest !== oracle.executionWorkbookDigest
  )
    throw Error(`COHORT_CUSTODY:${identity}`);
  const audit = collisionAudit(rows, dims, entry.referenceDate);
  if (Object.values(audit).some((v) => v !== 0))
    throw Error(`KEY_AUDIT:${identity}:${stable(audit)}`);
  const expectedCollision = collisionBy.get(identity);
  if (
    !expectedCollision ||
    expectedCollision.exact.duplicateRowExcess !== audit.exactDuplicateExcess ||
    expectedCollision.normalized.duplicateRowExcess !==
      audit.normalizedDuplicateExcess ||
    expectedCollision.canonical.duplicateRowExcess !==
      audit.canonicalDuplicateExcess ||
    expectedCollision.aliasCollisionCount !== audit.aliasCollisions
  )
    throw Error(`COLLISION_LEDGER:${identity}`);
  const baselinePath = `${ROOT}/direct/${route.familyId}/${route.year}.json`,
    baseline = await pinned(baselinePath),
    baseRows = baseline.execution.tables[0].rows,
    baseBy = new Map(baseRows.map((r: any) => [r._source.address, r]));
  let changed = 0;
  for (const r of rows) {
    const old: any = baseBy.get((r as any)._source.address);
    if (
      !old ||
      !exact(
        (r as any)[map.logicalTable.valuesName],
        old[map.logicalTable.valuesName],
      )
    )
      throw Error(`BASELINE_VALUE:${identity}`);
    for (const dim of dims)
      if (
        !exact((r as any)[dim], old[dim]) ||
        (r as any)[`${dim}_source`] !== (old[`${dim}_source`] ?? null)
      ) {
        const lk = `${identity}:${(r as any)._source.address}:${dim}`,
          d = discrepancyBy.get(lk);
        if (
          !d ||
          !exact(old[dim], d.oldValue) ||
          (old[`${dim}_source`] ?? null) !== (d.oldSourceAddress ?? null) ||
          !exact((r as any)[dim], d.newRawLabel) ||
          (r as any)[`${dim}_source`] !== d.selectedSourceAddress ||
          d.direction !==
            assignments.find(
              (a: any) => a.valueAddress === (r as any)._source.address,
            ).dimensionSources[dim].direction
        )
          throw Error(`UNAUTHORIZED_LEDGER:${lk}`);
        observedLedger.add(lk);
        changed++;
      }
  }
  const selected = distinct<string>(
    assignments.flatMap((a: any) => [
      a.valueAddress,
      ...dims.map((d: string) => a.dimensionSources[d].sourceAddress),
    ]),
  ).sort(cmp);
  const execProof = selectedProof(sheet, selected);
  let sourceProof = execProof;
  if (oracle.sourceWorkbookDigest !== oracle.executionWorkbookDigest) {
    const sb = await readRegularFile(sourcePath, ".", "source-workbook");
    if (
      sha256(sb) !== oracle.sourceWorkbookDigest ||
      oracle.sourceWorkbookDigest !== planMember.sourceDigest
    )
      throw Error(`SOURCE_CUSTODY:${identity}`);
    const sp = await parseWorkbook(sb);
    if (!sp.ok) throw Error(`SOURCE_PARSE:${identity}`);
    const ss = sp.workbook.sheets.find((s) => s.name === sheet.name);
    if (!ss) throw Error(`SOURCE_SHEET:${identity}`);
    sourceProof = selectedProof(ss, selected);
    if (stable(sourceProof) !== stable(execProof))
      throw Error(`SOURCE_EXECUTION_CELL_DRIFT:${identity}`);
  } else if (sourcePath !== executionPath)
    throw Error(`IDENTICAL_DIGEST_PATH_DRIFT:${identity}`);
  const equivalenceDigest = digestTargetScopedCanonical({
    source: sourceProof,
    execution: execProof,
  });
  const mapResource = resources(map),
    envelopeResource = resources(envelope),
    executionResource = resources(execution);
  if (
    mapResource.bytes > MAX_TARGET_SCOPED_JSON_BYTES ||
    mapResource.nodes > MAX_TARGET_SCOPED_JSON_NODES ||
    envelopeResource.bytes > MAX_TARGET_SCOPED_ENVELOPE_BYTES ||
    envelopeResource.nodes > MAX_TARGET_SCOPED_ENVELOPE_NODES ||
    executionResource.bytes > MAX_TARGET_SCOPED_EXECUTION_BYTES ||
    executionResource.nodes > MAX_TARGET_SCOPED_EXECUTION_NODES
  )
    throw Error(`RESOURCE_LIMIT:${identity}`);
  max = {
    mapBytes: Math.max(max.mapBytes, mapResource.bytes),
    mapNodes: Math.max(max.mapNodes, mapResource.nodes),
    envelopeBytes: Math.max(max.envelopeBytes, envelopeResource.bytes),
    envelopeNodes: Math.max(max.envelopeNodes, envelopeResource.nodes),
    executionBytes: Math.max(max.executionBytes, executionResource.bytes),
    executionNodes: Math.max(max.executionNodes, executionResource.nodes),
    operations: Math.max(
      max.operations,
      envelope.attachmentManifest.operations,
    ),
  };
  const rel = `${route.familyId}/${route.year}.json`;
  const member = {
    schemaVersion: "tidy.offenders-target-scoped-member/v1",
    pendingExternalAuthorizationReview: true,
    acceptanceAuthority: false,
    trainingEligibility: false,
    productionAcceptance: false,
    promotionAuthorization: false,
    familyId: route.familyId,
    year: route.year,
    releaseId: route.releaseId,
    rows: rows.length,
    dimensions: dims,
    partitions: parts.length,
    targetSets: targetSets.length,
    sourceUniverses: universes.length,
    attachmentChoices: attachments.length,
    vectors: vectors.length,
    resolutionOperations: envelope.attachmentManifest.operations,
    providerCalls: 0,
    sourceWorkbookPath: oracle.sourceWorkbookPath,
    sourceWorkbookDigest: oracle.sourceWorkbookDigest,
    executionWorkbookPath: oracle.executionWorkbookPath,
    executionWorkbookDigest: oracle.executionWorkbookDigest,
    physicalSheet: sheet.name,
    selectedCellCount: selected.length,
    sourceExecutionEquivalenceDigest: equivalenceDigest,
    mapPath: `maps/${rel}`,
    mapDigest: mapResource.digest,
    envelopePath: `envelopes/${rel}`,
    trustedEnvelopeDigest: envelope.envelopeDigest,
    executionPath: `executions/${rel}`,
    executionDigest: executionResource.digest,
    oracleProof: {
      partitionManifestDigest: pins.get(PARTITION)!.sha256,
      assignments: assignments.length,
      attachmentEquality: true,
      typedLabelEquality: true,
      orderedAddressEquality: true,
      ambiguities: 0,
      gaps: 0,
      overlaps: 0,
      changedFields: changed,
      unauthorizedChanges: 0,
    },
    keyAudit: audit,
    resources: {
      map: mapResource,
      envelope: envelopeResource,
      execution: executionResource,
    },
  };
  for (const [dir, value] of [
    ["maps", map],
    ["envelopes", envelope],
    ["executions", execution],
    ["members", member],
  ] as const) {
    const p = `${OUT}/${dir}/${rel}`;
    await mkdir(dirname(p), { recursive: true });
    await writeFile(p, jsonBytes(value));
  }
  results.push(member);
  totalRows += rows.length;
  totalPartitions += parts.length;
  totalUniverses += universes.length;
  totalAttachments += attachments.length;
  totalVectors += vectors.length;
  totalOps += envelope.attachmentManifest.operations;
}
if (
  observedLedger.size !== EXPECTED.changes ||
  stable([...observedLedger].sort()) !== stable([...expectedLedgerKeys].sort())
)
  throw Error("LEDGER_EXACT_CLOSURE");
if (
  results.length !== EXPECTED.members ||
  totalRows !== EXPECTED.rows ||
  totalPartitions !== EXPECTED.partitions ||
  totalUniverses !== EXPECTED.universes ||
  totalAttachments !== EXPECTED.attachments ||
  totalVectors !== EXPECTED.vectors ||
  totalOps !== EXPECTED.operations
)
  throw Error(
    `STRUCTURAL_CLOSURE:${stable({ results: results.length, totalRows, totalPartitions, totalUniverses, totalAttachments, totalVectors, totalOps })}`,
  );
const payloadFiles = (await listRegularFiles(OUT)).map(async (path) => {
  const b = await readFile(`${OUT}/${path}`);
  return { path, byteLength: b.length, sha256: sha256(b) };
});
const payloadRecords = await Promise.all(payloadFiles),
  payloadRootDigest = digestFileRecords(payloadRecords);
const summary = {
  schemaVersion: "tidy.offenders-target-scoped-summary/v1",
  pendingExternalAuthorizationReview: true,
  acceptanceAuthority: false,
  trainingEligibility: false,
  productionAcceptance: false,
  promotionAuthorization: false,
  authorizationPath: authPath,
  authorizationDigest: expectedAuthDigest,
  members: results.length,
  families: new Set(results.map((r) => r.familyId)).size,
  rows: totalRows,
  partitions: totalPartitions,
  targetSets: totalPartitions,
  sourceUniverses: totalUniverses,
  attachmentChoices: totalAttachments,
  vectors: totalVectors,
  resolutionOperations: totalOps,
  changedFields: observedLedger.size,
  b2aChangedFields: EXPECTED.b2aChanges,
  combinedAuthorizedChangedFields: observedLedger.size + EXPECTED.b2aChanges,
  providerCalls: 0,
  warnings: 0,
  ambiguities: 0,
  gaps: 0,
  overlaps: 0,
  keyDefects: 0,
  maxResources: max,
  payloadRootDigest,
};
const routing = {
  schemaVersion: "tidy.offenders-target-scoped-routing-manifest/v1",
  pendingExternalAuthorizationReview: true,
  acceptanceAuthority: false,
  trainingEligibility: false,
  productionAcceptance: false,
  promotionAuthorization: false,
  summary: { members: results.length, rows: totalRows },
  members: results.map((r) => ({
    familyId: r.familyId,
    year: r.year,
    releaseId: r.releaseId,
    status: "target-scoped-v02-engineering",
    rows: r.rows,
    mapDigest: r.mapDigest,
    trustedEnvelopeDigest: r.trustedEnvelopeDigest,
    executionDigest: r.executionDigest,
    memberPath: `members/${r.familyId}/${r.year}.json`,
  })),
};
const attestation = {
  schemaVersion: "tidy.offenders-target-scoped-reproduction-attestation/v1",
  pendingExternalAuthorizationReview: true,
  acceptanceAuthority: false,
  trainingEligibility: false,
  productionAcceptance: false,
  promotionAuthorization: false,
  pairedRunPolicy: "fresh-run-a-and-run-b-must-be-byte-identical",
  payloadRootDigest,
  members: results.length,
  rows: totalRows,
  providerCalls: 0,
};
await writeFile(`${OUT}/summary.json`, jsonBytes(summary));
await writeFile(`${OUT}/routing-manifest.json`, jsonBytes(routing));
await writeFile(`${OUT}/reproduction-attestation.json`, jsonBytes(attestation));
if (injected === "after-writes") throw Error("INJECTED_FAILURE:after-writes");
const files = await listRegularFiles(OUT);
const records = [] as any[];
for (const path of files) {
  const b = await readFile(`${OUT}/${path}`);
  records.push({ path, byteLength: b.length, sha256: sha256(b) });
}
const manifest = {
  schemaVersion: "tidy.offenders-target-scoped-output-manifest/v1",
  pendingExternalAuthorizationReview: true,
  acceptanceAuthority: false,
  trainingEligibility: false,
  productionAcceptance: false,
  promotionAuthorization: false,
  files: records,
  outputRootDigest: digestFileRecords(records),
};
await writeFile(`${OUT}/manifest.json`, jsonBytes(manifest));
await tx.commit();
console.log(
  JSON.stringify(
    {
      ...summary,
      outputRootDigest: manifest.outputRootDigest,
      files: records.length + 1,
    },
    null,
    2,
  ),
);

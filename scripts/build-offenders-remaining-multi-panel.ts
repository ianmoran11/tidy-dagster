import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { basename, dirname } from "node:path";
import {
  assertContained,
  assertDistinctPaths,
  assertExactKeys,
  assertSafeComponent,
  assertSafeYear,
  beginDirectoryTransaction,
  countJsonNodes,
  OFFENDERS_PHASED_ROUTED_RUNTIME_SOURCE_PATHS,
  readBoundedJson,
  sha256,
  verifyPinnedFileClosure,
  type FilePin,
} from "./offenders-phased-safety.js";
import { parseWorkbook } from "../apps/domain-worker/src/workbook/parseWorkbook.js";
import { buildCompactSemanticContext } from "../apps/domain-worker/src/context/compactContext.js";
import { compileRoleAwareSemanticTableMap } from "../apps/domain-worker/src/catalog/role-aware-region-catalog-v5.js";
import { executeRecipe } from "../apps/domain-worker/src/executor/executeRecipe.js";
import {
  compileAtomicSemanticTableMapV2,
  digestAtomicRegionCatalog,
  executeAtomicSemanticTableMapV2,
  type AtomicRegionCatalog,
} from "../apps/domain-worker/src/catalog/semantic-map-v2.js";

const FIX = "fixtures/product-prototype";
const ROOT = ".product-prototype/offenders-remaining-phase1";
const ORACLE = `${ROOT}/source-partition-canary/run-a-remediated`;
const AUTH_PATH = `${FIX}/offenders-remaining-semantic-generation-authorization-v1.json`;
const CAPABILITY_PIN_PATH = `${FIX}/offenders-remaining-capability-routing-pin-v1.json`;
const CAMPAIGN_AUTHORIZATION_DIGEST =
  "sha256:13624947ec0620b0b48b64ef1cd9126a62fada7adad458f64be2598b8d7f4d6a";
const CAMPAIGN_CAPABILITY_PIN_DIGEST =
  "sha256:62fb94b842714e7d8243950b9d92e6ed880e0228f6548d8955e4f18a5da939a4";
function argument(name: string): string {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1])
    throw new Error(`${name} is required`);
  return process.argv[index + 1];
}
const requestedOut = argument("--out");
const expectedAuthDigest = argument("--authorization-digest");
const expectedCapabilityDigest = argument("--capability-pin-digest");
if (
  expectedAuthDigest !== CAMPAIGN_AUTHORIZATION_DIGEST ||
  expectedCapabilityDigest !== CAMPAIGN_CAPABILITY_PIN_DIGEST
)
  throw new Error("CAMPAIGN_EXTERNAL_PIN_MISMATCH");
const injectedFailure = process.argv.includes("--inject-failure")
  ? argument("--inject-failure")
  : undefined;
const transaction = await beginDirectoryTransaction(
  requestedOut,
  `${ROOT}/multi-panel-b2a`,
  injectedFailure,
);
const OUT = transaction.temporaryPath;
assertDistinctPaths([
  ["output", requestedOut],
  ["oracle", ORACLE],
  ["fixtures", FIX],
]);
await mkdir(`${OUT}/maps`, { recursive: true });
await mkdir(`${OUT}/members`, { recursive: true });
await mkdir(`${OUT}/cohorts`, { recursive: true });

const authRaw = await readFile(AUTH_PATH);
if (sha256(authRaw) !== expectedAuthDigest)
  throw new Error("EXTERNAL_AUTHORIZATION_PIN_MISMATCH");
if (authRaw.length > 2_000_000) throw new Error("AUTHORIZATION_BYTE_LIMIT");
const AUTHORIZATION = JSON.parse(authRaw.toString("utf8"));
countJsonNodes(AUTHORIZATION, 100_000);
assertExactKeys(
  AUTHORIZATION,
  [
    "schemaVersion",
    "authorizedForVersionedMapGeneration",
    "acceptanceAuthority",
    "trainingEligibility",
    "productionAcceptance",
    "promotionAuthorization",
    "authorizationBoundary",
    "canary",
    "reviewedSemanticStatus",
    "runtimeSourceClosure",
    "inputs",
    "reviewStatus",
  ],
  "authorization",
);
if (
  AUTHORIZATION.schemaVersion !==
    "tidy.offenders-semantic-generation-authorization/v1" ||
  AUTHORIZATION.authorizedForVersionedMapGeneration !== true ||
  AUTHORIZATION.acceptanceAuthority !== false ||
  AUTHORIZATION.trainingEligibility !== false ||
  AUTHORIZATION.productionAcceptance !== false ||
  AUTHORIZATION.promotionAuthorization !== false ||
  AUTHORIZATION.reviewStatus !== "pending-independent-review"
)
  throw new Error("INVALID_SEMANTIC_GENERATION_AUTHORIZATION");
const authPins = new Map<string, FilePin>();
for (const pin of AUTHORIZATION.inputs as FilePin[]) {
  if (authPins.has(pin.path))
    throw new Error(`DUPLICATE_AUTHORIZATION_INPUT:${pin.path}`);
  authPins.set(pin.path, pin);
}
await verifyPinnedFileClosure(
  AUTHORIZATION.runtimeSourceClosure as FilePin[],
  OFFENDERS_PHASED_ROUTED_RUNTIME_SOURCE_PATHS,
);
for (const pin of AUTHORIZATION.runtimeSourceClosure as FilePin[]) {
  const semanticPin = authPins.get(pin.path);
  if (!semanticPin || stable(semanticPin) !== stable(pin))
    throw new Error(`RUNTIME_SOURCE_AUTHORIZATION_MISMATCH:${pin.path}`);
}
async function pinnedJson(
  path: string,
  maxBytes = 64_000_000,
  maxNodes = 2_000_000,
): Promise<any> {
  const pin = authPins.get(path);
  if (!pin) throw new Error(`UNPINNED_SEMANTIC_INPUT:${path}`);
  return (await readBoundedJson(path, { maxBytes, maxNodes, pin })).value;
}
const capabilityRaw = await readFile(CAPABILITY_PIN_PATH);
if (sha256(capabilityRaw) !== expectedCapabilityDigest)
  throw new Error("EXTERNAL_CAPABILITY_PIN_MISMATCH");
if (capabilityRaw.length > 2_000_000)
  throw new Error("CAPABILITY_PIN_BYTE_LIMIT");
const CAPABILITY_PIN = JSON.parse(capabilityRaw.toString("utf8"));
countJsonNodes(CAPABILITY_PIN, 100_000);
assertExactKeys(
  CAPABILITY_PIN,
  [
    "schemaVersion",
    "authorizedForPhasedEngineering",
    "acceptanceAuthority",
    "trainingEligibility",
    "productionAcceptance",
    "promotionAuthorization",
    "semanticGenerationAuthorizationPath",
    "semanticGenerationAuthorizationSha256",
    "routingManifest",
    "expectedSummary",
    "expectedTargetScopedFamilies",
    "members",
    "reviewStatus",
  ],
  "capability-pin",
);
if (
  CAPABILITY_PIN.schemaVersion !== "tidy.offenders-capability-routing-pin/v1" ||
  CAPABILITY_PIN.authorizedForPhasedEngineering !== true ||
  CAPABILITY_PIN.acceptanceAuthority !== false ||
  CAPABILITY_PIN.trainingEligibility !== false ||
  CAPABILITY_PIN.productionAcceptance !== false ||
  CAPABILITY_PIN.promotionAuthorization !== false ||
  CAPABILITY_PIN.reviewStatus !== "pending-independent-review" ||
  CAPABILITY_PIN.semanticGenerationAuthorizationSha256 !== expectedAuthDigest
)
  throw new Error("INVALID_CAPABILITY_PIN");
const expectedRouteBy = new Map<string, any>();
for (const member of CAPABILITY_PIN.members) {
  const familyId = assertSafeComponent(member.familyId, "pinned-family");
  const year = assertSafeYear(member.year);
  const key = `${familyId}:${year}`;
  if (expectedRouteBy.has(key))
    throw new Error(`DUPLICATE_PINNED_IDENTITY:${key}`);
  expectedRouteBy.set(key, member);
}
if (expectedRouteBy.size !== 170) throw new Error("CAPABILITY_PIN_SCOPE");

const PLAN_PATH = `${FIX}/offenders-remaining-semantic-map-plan-v1.json`;
const PARTITION_PATH = `${ORACLE}/partition-manifest.json`;
const BUNDLES_PATH = `${ORACLE}/temporary-maps-recipes.json`;
const DISCREPANCY_PATH = `${ORACLE}/discrepancy-ledger.json`;
const COLLISION_PATH = `${ORACLE}/collision-ledger.json`;
const METHOD_ALLOWLIST_PATH = `${ROOT}/source-partition-canary/method-anchor-allowlist-v1.json`;
const CANDIDATE_ALLOWLIST_PATH = `${ROOT}/source-partition-canary/candidate-correction-allowlist-v1.json`;
const MEASUREMENT_PATH = `${ROOT}/multi-panel-b2a/measurement/exact-ownership-measurement.json`;
const CANARY_MANIFEST_PATH = `${ORACLE}/manifest.json`;
const PLAN = await pinnedJson(PLAN_PATH);
const OWNERSHIP = await pinnedJson(PARTITION_PATH, 400_000_000, 15_000_000);
const BUNDLES = await pinnedJson(BUNDLES_PATH, 128_000_000, 5_000_000);
const DISCREPANCIES = await pinnedJson(
  DISCREPANCY_PATH,
  128_000_000,
  5_000_000,
);
const COLLISIONS = await pinnedJson(COLLISION_PATH, 16_000_000, 1_000_000);
const METHOD_ALLOWLIST = await pinnedJson(
  METHOD_ALLOWLIST_PATH,
  4_000_000,
  250_000,
);
const CANDIDATE_ALLOWLIST = await pinnedJson(
  CANDIDATE_ALLOWLIST_PATH,
  4_000_000,
  250_000,
);
const MEASUREMENT = await pinnedJson(MEASUREMENT_PATH, 64_000_000, 5_000_000);
const CANARY_MANIFEST = await pinnedJson(
  CANARY_MANIFEST_PATH,
  4_000_000,
  250_000,
);
if (
  CANARY_MANIFEST.outputRootDigest !== AUTHORIZATION.canary.outputRootDigest ||
  AUTHORIZATION.canary.manifestSha256 !==
    sha256(await readFile(CANARY_MANIFEST_PATH))
)
  throw new Error("CANARY_MANIFEST_PIN_MISMATCH");

function sha(data: string | Buffer): string {
  return `sha256:${createHash("sha256").update(data).digest("hex")}`;
}
function stable(value: any): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stable(value[key])}`)
      .join(",")}}`;
  if (typeof value === "number" && Object.is(value, -0)) return '"-0"';
  return JSON.stringify(value);
}
function bytes(value: any): Buffer {
  return Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
}
function pos(address: string): [number, number] {
  const m = /^R(\d+)C(\d+)$/.exec(address);
  if (!m) throw new Error(`bad address ${address}`);
  return [+m[1], +m[2]];
}
function addressSort(a: string, b: string): number {
  const x = pos(a),
    y = pos(b);
  return x[0] - y[0] || x[1] - y[1];
}
function uniq<T>(items: T[]): T[] {
  return [...new Set(items)];
}
function exact(a: any, b: any): boolean {
  return Object.is(a, b);
}
function norm(value: any): any {
  return typeof value === "string" ? value.trim().replace(/\s+/g, " ") : value;
}
function semanticAlias(value: any): string {
  return String(norm(value))
    .replace(/(?:\s*\([a-z]\))+$/gi, "")
    .toUpperCase()
    .trim()
    .replace(/\s+/g, " ");
}
function code(value: any): string {
  const raw = semanticAlias(value);
  const slug =
    raw.replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "VALUE";
  return `${slug.slice(0, 80)}_${createHash("sha256").update(raw).digest("hex").slice(0, 8)}`;
}
function typedValue(entry: any): any {
  return entry?.value;
}
function slug(value: string): string {
  const base =
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "dimension";
  return base.slice(0, 30);
}
function selectorRanges(addresses: string[]): any[] {
  const byRow = new Map<number, number[]>();
  for (const address of uniq(addresses).sort(addressSort)) {
    const [r, c] = pos(address);
    const list = byRow.get(r) ?? [];
    list.push(c);
    byRow.set(r, list);
  }
  const runs: Array<{ r1: number; r2: number; c1: number; c2: number }> = [];
  for (const [row, colsRaw] of [...byRow].sort((a, b) => a[0] - b[0])) {
    const cols = uniq(colsRaw).sort((a, b) => a - b);
    let start = cols[0],
      prev = cols[0];
    const rowRuns: Array<{ c1: number; c2: number }> = [];
    for (const col of cols.slice(1)) {
      if (col === prev + 1) prev = col;
      else {
        rowRuns.push({ c1: start, c2: prev });
        start = prev = col;
      }
    }
    rowRuns.push({ c1: start, c2: prev });
    for (const run of rowRuns) {
      const prior = [...runs]
        .reverse()
        .find((x) => x.r2 === row - 1 && x.c1 === run.c1 && x.c2 === run.c2);
      if (prior) prior.r2 = row;
      else runs.push({ r1: row, r2: row, c1: run.c1, c2: run.c2 });
    }
  }
  return runs.map((x) =>
    x.r1 === x.r2 && x.c1 === x.c2
      ? { address: `R${x.r1}C${x.c1}` }
      : { range: `R${x.r1}C${x.c1}:R${x.r2}C${x.c2}` },
  );
}
function ownedSubsets(byRegion: Map<string, Set<string>>): any[] {
  return [...byRegion]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([regionId, set]) => ({
      regionId,
      selectors: selectorRanges([...set]),
    }));
}
function addRegion(
  map: Map<string, Set<string>>,
  region: string,
  address: string,
): void {
  const set = map.get(region) ?? new Set<string>();
  set.add(address);
  map.set(region, set);
}
function cellMap(sheet: any): Map<string, any> {
  return new Map(sheet.cells.map((cell: any) => [cell.address, cell]));
}
function compareRowsToOracle(
  rows: any[],
  assignments: any[],
  dimensions: string[],
  sheet: any,
  trace?: any,
): { ok: boolean; reason?: string } {
  if (rows.length !== assignments.length)
    return {
      ok: false,
      reason: `row count ${rows.length} != ${assignments.length}`,
    };
  const byAddress = new Map(rows.map((row) => [row._source?.address, row]));
  const cells = cellMap(sheet);
  const traceBy = new Map(
    (trace?.value_cells ?? []).map((item: any) => [item.source?.address, item]),
  );
  if (byAddress.size !== assignments.length)
    return { ok: false, reason: "duplicate target" };
  if (trace && traceBy.size !== assignments.length)
    return { ok: false, reason: "trace target closure" };
  for (const assignment of assignments) {
    const row = byAddress.get(assignment.valueAddress);
    if (!row)
      return { ok: false, reason: `missing ${assignment.valueAddress}` };
    if (
      !exact(row["published value"], cells.get(assignment.valueAddress)?.value)
    )
      return { ok: false, reason: `value ${assignment.valueAddress}` };
    for (const name of dimensions) {
      const expected = assignment.dimensionSources[name];
      if (!expected) return { ok: false, reason: `oracle dimension ${name}` };
      if (
        row[`${name}_source`] !== expected.sourceAddress ||
        !exact(row[name], typedValue(expected.exactTypedRawLabel))
      )
        return {
          ok: false,
          reason: `attachment ${assignment.valueAddress}:${name}`,
        };
      if (trace) {
        const valueTrace: any = traceBy.get(assignment.valueAddress);
        const headers = (valueTrace?.headers ?? []).filter(
          (h: any) => h.header === name,
        );
        if (
          headers.length !== 1 ||
          headers[0].direction !== expected.direction ||
          headers[0].selected !== expected.sourceAddress ||
          headers[0].missing !== false ||
          headers[0].ambiguous !== false ||
          headers[0].candidates?.length !== 1 ||
          headers[0].candidates[0] !== expected.sourceAddress ||
          !exact(headers[0].value, typedValue(expected.exactTypedRawLabel))
        )
          return {
            ok: false,
            reason: `trace ${assignment.valueAddress}:${name}`,
          };
      }
    }
  }
  return { ok: true };
}
function buildV2Map(
  member: any,
  bundle: any,
  measurement: any,
  catalog: any,
): { map: any; dimensions: string[]; assignments: any[]; panelCount: number } {
  const assignments = member.partitions.flatMap((p: any) => p.valueAssignments);
  const tempById = new Map(
    bundle.partitions.map((p: any) => [p.partitionId, p]),
  );
  const dimensions = bundle.partitions[0].map.table.dimensions.map(
    (d: any) => d.name,
  );
  if (stable(dimensions) !== stable(measurement.dimensions))
    throw Error(
      `measurement dimension drift ${member.familyId}:${member.year}`,
    );
  const dimIds = new Map(
    dimensions.map((name: string, index: number) => [
      name,
      `d${String(index + 1).padStart(2, "0")}`,
    ]),
  );
  if (new Set(dimIds.values()).size !== dimensions.length)
    throw Error(`dimension id collision ${member.familyId}:${member.year}`);
  const targetParent = new Map<string, string>();
  for (const partition of member.partitions) {
    const temp: any = tempById.get(partition.partitionId);
    if (!temp) throw Error(`temp partition ${partition.partitionId}`);
    for (const a of partition.valueAssignments) {
      const parents = temp.map.table.values.regions.filter((r: string) =>
        (temp.sourcePartitions[r] ?? []).includes(a.valueAddress),
      );
      if (parents.length !== 1)
        throw Error(
          `target parent ${partition.partitionId}:${a.valueAddress}:${parents}`,
        );
      targetParent.set(a.valueAddress, parents[0]);
    }
  }
  const byVector = new Map<string, any[]>();
  for (const a of assignments) {
    const dirs = dimensions.map((d: string) => a.dimensionSources[d].direction),
      sources = dimensions.map(
        (d: string) => a.dimensionSources[d].sourceAddress,
      ),
      key = JSON.stringify([dirs, sources]);
    const list = byVector.get(key) ?? [];
    list.push(a);
    byVector.set(key, list);
  }
  const groups = measurement.panels.map((panel: any) =>
    panel.nodeKeys.flatMap((key: string) => {
      const found = byVector.get(key);
      if (!found)
        throw Error(
          `measurement vector ${member.familyId}:${member.year}:${key}`,
        );
      return found;
    }),
  );
  const owned = groups.flat();
  if (
    owned.length !== assignments.length ||
    new Set(owned.map((a: any) => a.valueAddress)).size !== assignments.length
  )
    throw Error(`measurement ownership ${member.familyId}:${member.year}`);
  const uses = new Map<string, Set<number>>();
  groups.forEach((items: any[], index: number) => {
    for (const a of items)
      for (const name of dimensions) {
        const addr = a.dimensionSources[name].sourceAddress;
        const s = uses.get(addr) ?? new Set<number>();
        s.add(index);
        uses.set(addr, s);
      }
  });
  const logicalTargets = new Map<string, Set<string>>();
  for (const a of assignments)
    addRegion(
      logicalTargets,
      targetParent.get(a.valueAddress)!,
      a.valueAddress,
    );
  const panels = groups.map((items: any[], index: number) => {
    const targets = new Map<string, Set<string>>();
    for (const a of items)
      addRegion(targets, targetParent.get(a.valueAddress)!, a.valueAddress);
    return {
      id: `panel-${String(index + 1).padStart(3, "0")}`,
      order: index + 1,
      tableName: `Offenders ${member.familyId} ${member.releaseId} p${index + 1}`,
      target: ownedSubsets(targets),
      dimensions: dimensions.map((name: string) => {
        const sources = new Map<string, Set<string>>();
        for (const a of items) {
          const s = a.dimensionSources[name];
          addRegion(sources, s.candidateRegionId, s.sourceAddress);
        }
        const directions = uniq(
          items.map((a: any) => a.dimensionSources[name].direction),
        );
        if (directions.length !== 1)
          throw Error(
            `panel direction ${member.familyId}:${member.year}:${index}:${name}`,
          );
        const shared = [...sources.values()].some((set) =>
          [...set].some((address) => (uses.get(address)?.size ?? 0) > 1),
        );
        return {
          id: dimIds.get(name),
          source: ownedSubsets(sources),
          direction: directions[0],
          ...(shared ? { allowSharedSource: true } : {}),
        };
      }),
    };
  });
  const map = {
    version: "semantic-table-map-v2",
    catalog: {
      version: catalog.version,
      digest: digestAtomicRegionCatalog(catalog),
    },
    logicalTable: {
      id: "observations",
      name: `Recorded Crime Offenders ${member.familyId} ${member.releaseId}`,
      values: {
        id: "published-value",
        name: "published value",
        target: ownedSubsets(logicalTargets),
      },
      dimensions: dimensions.map((name: string) => ({
        id: dimIds.get(name),
        name,
      })),
    },
    panels,
  };
  return { map, dimensions, assignments, panelCount: panels.length };
}
function collisionAudit(
  rows: any[],
  dimensions: string[],
  referenceDate: string,
): any {
  const modes = [
    ["exact", (v: any) => `${typeof v}:${stable(v)}`],
    ["normalized", (v: any) => `${typeof norm(v)}:${stable(norm(v))}`],
    ["canonical", (v: any) => code(v)],
  ] as const;
  const result: any = {};
  for (const [name, keyer] of modes) {
    const keys = new Set<string>();
    let excess = 0;
    for (const row of rows) {
      const key = stable([
        referenceDate,
        referenceDate,
        ...dimensions.map((d) => keyer(row[d])),
        "published-value",
      ]);
      if (keys.has(key)) excess++;
      keys.add(key);
    }
    result[`${name}DuplicateExcess`] = excess;
  }
  let aliasCollisions = 0;
  for (const dim of dimensions) {
    const by = new Map<string, Set<string>>();
    for (const row of rows) {
      const c = code(row[dim]),
        s = by.get(c) ?? new Set<string>();
      s.add(semanticAlias(row[dim]));
      by.set(c, s);
    }
    aliasCollisions += [...by.values()].filter((s) => s.size > 1).length;
  }
  result.aliasCollisions = aliasCollisions;
  return result;
}
function exactDiscrepancyKey(item: any): string {
  return `${item.familyId}:${item.year}:${item.valueAddress}:${item.dimension}`;
}

if (
  OWNERSHIP.summary.families !== 47 ||
  OWNERSHIP.summary.members !== 170 ||
  OWNERSHIP.summary.affectedCases !== 164 ||
  OWNERSHIP.summary.assignedDistinctAddresses !== 224997
)
  throw Error("oracle scope drift");
if (
  METHOD_ALLOWLIST.anchors.length !== 72 ||
  CANDIDATE_ALLOWLIST.cases.length !== 8
)
  throw Error("allowlist drift");
const methodAllowed = new Map<string, any>();
for (const anchor of METHOD_ALLOWLIST.anchors) {
  const key = `${anchor.familyId}:${anchor.year}:${anchor.sourceAddress}:${anchor.candidateRegionId}:${stable(anchor.exactTypedRawLabel?.value)}`;
  if (methodAllowed.has(key)) throw Error(`duplicate method allowlist ${key}`);
  methodAllowed.set(key, anchor);
}
const candidateAllowed = new Map<string, any>();
for (const item of CANDIDATE_ALLOWLIST.cases)
  for (const cell of item.addedAllowedCells) {
    const key = `${item.familyId}:${item.year}:${item.dimension}:${cell.sourceAddress}:${item.candidateRegionId}:${stable(cell.exactTypedRawLabel?.value)}`;
    if (candidateAllowed.has(key))
      throw Error(`duplicate candidate allowlist ${key}`);
    candidateAllowed.set(key, { item, cell });
  }
const candidateCaseKeys = new Set<string>(
  CANDIDATE_ALLOWLIST.cases.map(
    (x: any) => `${x.familyId}:${x.year}:${x.dimension}`,
  ),
);
const affectedKeys = new Set<string>(
  OWNERSHIP.affectedCaseInventory.map(
    (x: any) => `${x.familyId}:${x.year}:${x.dimension}`,
  ),
);
for (const key of candidateCaseKeys)
  if (!affectedKeys.has(key))
    throw Error(`candidate case outside inventory ${key}`);
const mixedCases = [...affectedKeys].filter(
  (key) => !candidateCaseKeys.has(key),
);
const mixedFamilies = new Set(mixedCases.map((key) => key.split(":")[0]));
if (mixedCases.length !== 156 || mixedFamilies.size !== 43)
  throw Error(`mixed scope ${mixedCases.length}/${mixedFamilies.size}`);
const discrepancyEntries =
  DISCREPANCIES.rows ??
  DISCREPANCIES.records ??
  DISCREPANCIES.discrepancies ??
  [];
if (discrepancyEntries.length !== 52367)
  throw Error(`discrepancy count ${discrepancyEntries.length}`);
const expectedDiscrepancies = new Map(
  discrepancyEntries.map((x: any) => [exactDiscrepancyKey(x), x]),
);
if (expectedDiscrepancies.size !== discrepancyEntries.length)
  throw Error("duplicate discrepancy identity");
for (const item of discrepancyEntries) {
  const raw = item.newRawValue ?? item.newValue ?? item.newRawLabel;
  const source =
    item.selectedSourceAddress ?? item.newSourceAddress ?? item.newSource;
  if (item.dimension === "method of proceeding") {
    const key = `${item.familyId}:${item.year}:${source}:${item.candidateRegionId}:${stable(raw)}`;
    if (!methodAllowed.has(key))
      throw Error(
        `method correction outside exact allowlist ${exactDiscrepancyKey(item)}`,
      );
  }
  const caseKey = `${item.familyId}:${item.year}:${item.dimension}`;
  if (candidateCaseKeys.has(caseKey)) {
    const key = `${caseKey}:${source}:${item.candidateRegionId}:${stable(raw)}`;
    if (!candidateAllowed.has(key))
      throw Error(
        `candidate correction outside exact allowlist ${exactDiscrepancyKey(item)}`,
      );
  }
}
const ownershipBy = new Map(
  OWNERSHIP.members.map((m: any) => [`${m.familyId}:${m.year}`, m]),
);
const bundleBy = new Map(
  BUNDLES.members.map((m: any) => [`${m.familyId}:${m.year}`, m]),
);
const planBy = new Map(PLAN.families.map((f: any) => [f.familyId, f]));
const measurementBy = new Map(
  MEASUREMENT.members.map((m: any) => [`${m.familyId}:${m.year}`, m]),
);
const collisionBy = new Map(
  COLLISIONS.members.map((m: any) => [`${m.familyId}:${m.year}`, m]),
);
if (collisionBy.size !== 170) throw Error("collision ledger member closure");
const SOURCE_INVENTORY_PATH = `${FIX}/offenders-release-source-inventory-v1.json`;
const FAMILY_MEMBERSHIP_PATH = `${FIX}/offenders-release-family-membership-v1.json`;
const SOURCE_INVENTORY = await pinnedJson(
  SOURCE_INVENTORY_PATH,
  8_000_000,
  500_000,
);
const FAMILY_MEMBERSHIP = await pinnedJson(
  FAMILY_MEMBERSHIP_PATH,
  8_000_000,
  500_000,
);
if (!SOURCE_INVENTORY || !FAMILY_MEMBERSHIP)
  throw Error("custody inventory missing");
const inputPaths = new Set<string>([
  AUTH_PATH,
  CAPABILITY_PIN_PATH,
  CANARY_MANIFEST_PATH,
  PLAN_PATH,
  PARTITION_PATH,
  BUNDLES_PATH,
  DISCREPANCY_PATH,
  COLLISION_PATH,
  METHOD_ALLOWLIST_PATH,
  CANDIDATE_ALLOWLIST_PATH,
  MEASUREMENT_PATH,
  SOURCE_INVENTORY_PATH,
  FAMILY_MEMBERSHIP_PATH,
  ...OFFENDERS_PHASED_ROUTED_RUNTIME_SOURCE_PATHS,
  `scripts/build-offenders-remaining-multi-panel.ts`,
]);
const members: any[] = [];
let capableRows = 0,
  requiredRows = 0,
  v1Members = 0,
  b1Members = 0,
  requiredMembers = 0,
  maxPanels = 0,
  capableChanges = 0;
const observedChangedKeys = new Set<string>();
for (const family of [...PLAN.families].sort((a: any, b: any) =>
  a.familyId.localeCompare(b.familyId),
)) {
  const cohortPath = `${FIX}/recorded-crime-offenders-${family.familyId}.json`;
  inputPaths.add(cohortPath);
  const cohort = await pinnedJson(cohortPath, 8_000_000, 500_000);
  const outputCohort = structuredClone(cohort);
  for (const entry of [...cohort.workbooks].sort(
    (a: any, b: any) => a.year - b.year,
  )) {
    const key = `${family.familyId}:${entry.year}`;
    const oracle: any = ownershipBy.get(key),
      bundle: any = bundleBy.get(key),
      measurement: any = measurementBy.get(key);
    if (!oracle || !bundle || !measurement)
      throw Error(`missing oracle ${key}`);
    const originalMember = (planBy.get(family.familyId) as any).members.find(
      (m: any) => Number(m.releaseId.slice(0, 4)) === entry.year,
    );
    if (!originalMember) throw Error(`plan member ${key}`);
    const sheetSlug = originalMember.physicalSheetName.replace(/ /g, "_");
    const catalogPath = `${ROOT}/catalogs/${originalMember.releaseId}-${originalMember.downloadOrdinal}-${sheetSlug}.json`;
    if (catalogPath !== bundle.catalogPath)
      throw Error(`catalog closure ${key}`);
    inputPaths.add(catalogPath);
    const catalogPayload = await pinnedJson(catalogPath, 16_000_000, 500_000);
    const catalog = catalogPayload.catalog as AtomicRegionCatalog;
    const workbookPath = `${FIX}/${entry.path}`;
    inputPaths.add(workbookPath);
    const workbookBytes = await readFile(workbookPath);
    const workbookPin = authPins.get(workbookPath);
    if (
      !workbookPin ||
      workbookPin.byteLength !== workbookBytes.length ||
      workbookPin.sha256 !== sha(workbookBytes) ||
      sha(workbookBytes) !== entry.contentDigest ||
      entry.path !== originalMember.executionPath ||
      entry.contentDigest !== originalMember.executionDigest ||
      entry.sheet !== originalMember.physicalSheetName
    )
      throw Error(`workbook/custody digest ${key}`);
    const parsed = await parseWorkbook(workbookBytes);
    if (!parsed.ok) throw Error(`workbook parse ${key}`);
    const sheet = parsed.workbook.sheets.find(
      (s: any) => s.name === entry.sheet,
    );
    if (!sheet) throw Error(`sheet ${key}`);
    const context = buildCompactSemanticContext(sheet);
    const built = buildV2Map(oracle, bundle, measurement, catalog);
    const expectedAddresses = oracle.expectedValueAddresses;
    const expectedAssignments = oracle.partitions
      .flatMap((p: any) => p.valueAssignments)
      .sort((a: any, b: any) => addressSort(a.valueAddress, b.valueAddress));
    let status = "target-scoped-required",
      mode: any = null,
      map: any = null,
      recipe: any = null,
      physicalExecution: any = null,
      logicalTable: any = null,
      envelope: any = null,
      trustedEnvelopeDigest: any = null,
      failure: any = null;
    const expectedRoute = expectedRouteBy.get(key);
    if (!expectedRoute) throw Error(`unpinned route ${key}`);
    if (expectedRoute.mode === "semantic-map-v1") {
      const v1Compiled = compileRoleAwareSemanticTableMap({
        map: originalMember.semanticMap,
        catalog: catalog as any,
        context,
      });
      if (!v1Compiled.ok)
        throw Error(`pinned v1 compile ${key}:${v1Compiled.code}`);
      const execution = executeRecipe(v1Compiled.recipe, sheet);
      const comparison =
        execution.tables.length === 1 &&
        execution.warnings.length === 0 &&
        execution.tables[0].warnings.length === 0
          ? compareRowsToOracle(
              execution.tables[0].rows,
              expectedAssignments,
              built.dimensions,
              sheet,
              execution.tables[0].trace,
            )
          : { ok: false, reason: "v1 warnings/table closure" };
      if (!comparison.ok)
        throw Error(`pinned v1 oracle ${key}:${comparison.reason}`);
      status = "multi-table-v1-capable";
      mode = "semantic-map-v1";
      map = originalMember.semanticMap;
      recipe = v1Compiled.recipe;
      physicalExecution = execution;
      logicalTable = execution.tables[0];
    } else if (
      expectedRoute.mode === "semantic-table-map-v2-recipe-v1" ||
      expectedRoute.status === "target-scoped-required"
    ) {
      try {
        const compiled = compileAtomicSemanticTableMapV2({
          map: built.map,
          catalog,
          context,
          sheet,
        });
        if (!compiled.ok) {
          failure = {
            stage: compiled.stage,
            code: compiled.code,
            message: compiled.message,
            diagnostics: (compiled as any).diagnostics ?? null,
          };
        } else if (expectedRoute.status === "target-scoped-required") {
          throw Error(`target-scoped route became B1-capable ${key}`);
        } else {
          envelope = compiled.envelope;
          trustedEnvelopeDigest = envelope.envelopeDigest;
          const execution = executeAtomicSemanticTableMapV2(
            envelope,
            sheet,
            trustedEnvelopeDigest,
          );
          status = "multi-table-v1-capable";
          mode = "semantic-table-map-v2-recipe-v1";
          map = built.map;
          recipe = envelope.recipe;
          physicalExecution = execution.physicalExecution;
          logicalTable = execution.logicalTable;
        }
      } catch (error: any) {
        if (
          String(error?.message ?? error).startsWith(
            "target-scoped route became",
          )
        )
          throw error;
        failure = {
          stage: "execution",
          code: error?.code ?? error?.name ?? "EXECUTION_FAILURE",
          message: String(error?.message ?? error),
        };
      }
    } else throw Error(`unknown pinned route ${key}`);
    if (
      status !== expectedRoute.status ||
      mode !== (expectedRoute.mode ?? null) ||
      stable(
        failure
          ? {
              stage: failure.stage,
              code: failure.code,
              message: failure.message,
            }
          : null,
      ) !==
        stable(
          expectedRoute.failure
            ? {
                stage: expectedRoute.failure.stage,
                code: expectedRoute.failure.code,
                message: expectedRoute.failure.message,
              }
            : null,
        )
    )
      throw Error(`CAPABILITY_ROUTE_DRIFT:${key}`);
    const sameSourceWitnesses = expectedAssignments
      .flatMap((a: any) => {
        const seen = new Map<string, string>();
        const out: any[] = [];
        for (const d of built.dimensions) {
          const source = a.dimensionSources[d].sourceAddress,
            prior = seen.get(source);
          if (prior && prior !== d)
            out.push({
              targetAddress: a.valueAddress,
              sourceAddress: source,
              dimensions: [prior, d],
            });
          else seen.set(source, d);
        }
        return out;
      })
      .slice(0, 5);
    const common = {
      familyId: family.familyId,
      year: entry.year,
      releaseId: entry.releaseId,
      referenceDate: entry.referenceDate,
      status,
      rows: expectedAssignments.length,
      dimensions: built.dimensions,
      proposedPanels: built.panelCount,
      catalogPath,
      catalogBytesDigest: sha(await readFile(catalogPath)),
      catalogContentDigest: digestAtomicRegionCatalog(catalog),
      sourceWorkbookPath: oracle.sourceWorkbookPath,
      sourceWorkbookDigest: oracle.sourceWorkbookDigest,
      executionWorkbookPath: entry.path,
      executionWorkbookDigest: entry.contentDigest,
      physicalSheet: entry.sheet,
      providerCalls: 0,
    };
    const outEntry = outputCohort.workbooks.find(
      (x: any) => x.year === entry.year,
    );
    if (status !== "multi-table-v1-capable") {
      requiredMembers++;
      requiredRows += expectedAssignments.length;
      outEntry.replayResponse = undefined;
      outEntry.capabilityDisposition = {
        status,
        failure,
        oraclePartitionDigest: sha(await readFile(PARTITION_PATH)),
      };
      members.push({ ...common, failure, sameSourceWitnesses });
      continue;
    }
    const comparison = compareRowsToOracle(
      logicalTable.rows,
      expectedAssignments,
      built.dimensions,
      sheet,
      logicalTable.trace,
    );
    if (!comparison.ok)
      throw Error(`logical oracle ${key}:${comparison.reason}`);
    const actualAddresses = logicalTable.rows.map(
      (r: any) => r._source.address,
    );
    if (stable(actualAddresses) !== stable(expectedAddresses))
      throw Error(`address order ${key}`);
    const warnings =
      (physicalExecution.warnings?.length ?? 0) +
      physicalExecution.tables.reduce(
        (s: number, t: any) => s + (t.warnings?.length ?? 0),
        0,
      );
    if (warnings) throw Error(`warnings ${key}`);
    let nulls = 0;
    for (const row of logicalTable.rows)
      for (const dim of built.dimensions)
        if (
          row[dim] === null ||
          row[dim] === undefined ||
          typeof row[dim] === "boolean"
        )
          nulls++;
    if (nulls) throw Error(`required dimension ${key}:${nulls}`);
    const audit = collisionAudit(
      logicalTable.rows,
      built.dimensions,
      entry.referenceDate,
    );
    if (Object.values(audit).some((v) => v !== 0))
      throw Error(`key defects ${key}:${stable(audit)}`);
    const collisionExpected: any = collisionBy.get(key);
    if (
      !collisionExpected ||
      stable(collisionExpected.requiredDimensions) !==
        stable(built.dimensions) ||
      collisionExpected.referenceDate !== entry.referenceDate ||
      collisionExpected.publicationVintageDate !== entry.referenceDate ||
      collisionExpected.measureId !== "published-value" ||
      collisionExpected.exact?.duplicateRowExcess !==
        audit.exactDuplicateExcess ||
      collisionExpected.normalized?.duplicateRowExcess !==
        audit.normalizedDuplicateExcess ||
      collisionExpected.canonical?.duplicateRowExcess !==
        audit.canonicalDuplicateExcess ||
      collisionExpected.aliasCollisionCount !== audit.aliasCollisions
    )
      throw Error(`collision ledger drift ${key}`);
    const baselinePath = `${ROOT}/direct/${family.familyId}/${entry.year}.json`;
    inputPaths.add(baselinePath);
    const baseline = await pinnedJson(baselinePath, 128_000_000, 5_000_000);
    const baseRows = baseline.execution.tables[0].rows;
    const baseBy = new Map(baseRows.map((r: any) => [r._source.address, r]));
    const assignmentByAddress = new Map(
      expectedAssignments.map((a: any) => [a.valueAddress, a]),
    );
    let unauthorized = 0,
      changed = 0;
    for (const row of logicalTable.rows) {
      const old: any = baseBy.get(row._source.address);
      if (!old) throw Error(`baseline target ${key}`);
      if (!exact(row["published value"], old["published value"]))
        throw Error(`published value drift ${key}:${row._source.address}`);
      for (const dim of built.dimensions) {
        if (
          !exact(row[dim], old[dim]) ||
          row[`${dim}_source`] !== old[`${dim}_source`]
        ) {
          changed++;
          const ledger: any = expectedDiscrepancies.get(
            `${key}:${row._source.address}:${dim}`,
          );
          if (
            !ledger ||
            !exact(old[dim], ledger.oldValue) ||
            (old[`${dim}_source`] ?? null) !==
              (ledger.oldSourceAddress ?? null) ||
            !exact(
              row[dim],
              ledger.newRawValue ?? ledger.newValue ?? ledger.newRawLabel,
            ) ||
            row[`${dim}_source`] !==
              (ledger.selectedSourceAddress ??
                ledger.newSourceAddress ??
                ledger.newSource) ||
            (assignmentByAddress.get(row._source.address) as any)
              ?.dimensionSources[dim]?.direction !== ledger.direction
          )
            unauthorized++;
          else observedChangedKeys.add(`${key}:${row._source.address}:${dim}`);
        }
      }
    }
    if (unauthorized)
      throw Error(`unauthorized discrepancy ${key}:${unauthorized}`);
    const mapBytes = bytes(map);
    if (
      sha(mapBytes) !== expectedRoute.mapDigest ||
      sha(bytes(recipe)) !== expectedRoute.recipeDigest ||
      (trustedEnvelopeDigest ?? null) !==
        (expectedRoute.trustedEnvelopeDigest ?? null)
    )
      throw Error(`externally pinned capable artifact drift ${key}`);
    const replayRelative = entry.replayResponse.path;
    const mapOutput = `${OUT}/maps/${replayRelative}`;
    await mkdir(dirname(mapOutput), { recursive: true });
    await writeFile(mapOutput, mapBytes);
    const physicalExecutionDigest = sha(bytes(physicalExecution));
    const memberArtifact = {
      schemaVersion: "tidy.offenders-verified-logical-execution/v1",
      acceptanceAuthority: false,
      trainingEligibility: false,
      productionAcceptance: false,
      promotionAuthorization: false,
      ...common,
      mode,
      mapPath: replayRelative,
      mapDigest: sha(mapBytes),
      recipe,
      recipeDigest: sha(bytes(recipe)),
      ...(envelope
        ? { envelope, trustedEnvelopeDigest }
        : { trustedEnvelopeDigest: null }),
      physicalExecutionDigest,
      logicalExecution: { providerCalls: 0, logicalTable },
      oracleProof: {
        partitionManifestDigest: sha(await readFile(PARTITION_PATH)),
        assignments: expectedAssignments.length,
        attachmentEquality: true,
        orderedAddressEquality: true,
        unauthorizedDiscrepancies: 0,
        changedFields: changed,
      },
      keyAudit: audit,
    };
    const artifactBytes = bytes(memberArtifact);
    if (sha(artifactBytes) !== expectedRoute.memberArtifactDigest)
      throw Error(`externally pinned member artifact drift ${key}`);
    const memberOutput = `${OUT}/members/${family.familyId}/${entry.year}.json`;
    await mkdir(dirname(memberOutput), { recursive: true });
    await writeFile(memberOutput, artifactBytes);
    outEntry.replayResponse = {
      path: replayRelative,
      contentDigest: sha(mapBytes),
      byteLength: mapBytes.length,
      historicalModel:
        mode === "semantic-table-map-v2-recipe-v1"
          ? "human-authored/oracle-backed-atomic-multi-panel-v2"
          : "human-authored/oracle-verified-semantic-map-v1",
      acceptanceAuthority: false,
      trainingEligibility: false,
    };
    members.push({
      ...common,
      mode,
      panels: mode === "semantic-table-map-v2-recipe-v1" ? built.panelCount : 1,
      mapPath: replayRelative,
      mapDigest: sha(mapBytes),
      recipeDigest: sha(bytes(recipe)),
      trustedEnvelopeDigest,
      physicalExecutionDigest,
      memberArtifactPath: `members/${family.familyId}/${entry.year}.json`,
      memberArtifactDigest: sha(artifactBytes),
      changedFields: changed,
      keyAudit: audit,
    });
    capableRows += logicalTable.rows.length;
    capableChanges += changed;
    maxPanels = Math.max(
      maxPanels,
      mode === "semantic-table-map-v2-recipe-v1" ? built.panelCount : 1,
    );
    if (mode === "semantic-map-v1") v1Members++;
    else b1Members++;
  }
  const cohortBytes = bytes(outputCohort);
  await writeFile(`${OUT}/cohorts/${basename(cohortPath)}`, cohortBytes);
}
members.sort((a, b) => a.familyId.localeCompare(b.familyId) || a.year - b.year);
if (
  members.length !== 170 ||
  new Set(members.map((m) => m.familyId)).size !== 47 ||
  capableRows + requiredRows !== 224997 ||
  v1Members + b1Members + requiredMembers !== 170
)
  throw Error(
    `routing closure ${stable({ members: members.length, capableRows, requiredRows, v1Members, b1Members, requiredMembers })}`,
  );
const reasonCounts = Object.entries(
  members
    .filter((m) => m.status === "target-scoped-required")
    .reduce((acc: any, m: any) => {
      const key = `${m.failure?.stage ?? "unknown"}:${m.failure?.code ?? "unknown"}`;
      acc[key] = (acc[key] ?? 0) + 1;
      return acc;
    }, {}),
)
  .sort((a: any, b: any) => a[0].localeCompare(b[0]))
  .map(([reason, members]) => ({ reason, members }));
const capableFamilyIds = new Set(
  members
    .filter((m) => m.status === "multi-table-v1-capable")
    .map((m) => m.familyId),
);
const requiredFamilyIds = new Set(
  members
    .filter((m) => m.status === "target-scoped-required")
    .map((m) => m.familyId),
);
const expectedCapableLedgerKeys = new Set(
  discrepancyEntries
    .filter(
      (item: any) =>
        expectedRouteBy.get(`${item.familyId}:${item.year}`)?.status ===
        "multi-table-v1-capable",
    )
    .map((item: any) => exactDiscrepancyKey(item)),
);
if (
  observedChangedKeys.size !== 49628 ||
  expectedCapableLedgerKeys.size !== 49628 ||
  [...observedChangedKeys].some((key) => !expectedCapableLedgerKeys.has(key))
)
  throw Error("capable discrepancy exact-set drift");
const scope = {
  schemaVersion: "tidy.offenders-remaining-capability-routing/v1",
  acceptanceAuthority: false,
  trainingEligibility: false,
  productionAcceptance: false,
  promotionAuthorization: false,
  atomicAcceptanceBoundary: {
    families: 47,
    members: 170,
    status: "unaccepted-unregistered",
    partialAcceptancePermitted: false,
  },
  semanticCorrectionAuthorization: {
    status: "independently-authorized-for-versioned-map",
    methodCorrections: 25544,
    nullRepairs: 26823,
    totalAuthorizedFieldChanges: 52367,
    methodAllowlistDigest: sha(await readFile(METHOD_ALLOWLIST_PATH)),
    candidateAllowlistDigest: sha(await readFile(CANDIDATE_ALLOWLIST_PATH)),
    oraclePartitionDigest: sha(await readFile(PARTITION_PATH)),
    oracleDiscrepancyDigest: sha(await readFile(DISCREPANCY_PATH)),
  },
  summary: {
    families: 47,
    members: 170,
    rows: 224997,
    capableMembers: v1Members + b1Members,
    capableFamilies: capableFamilyIds.size,
    capableRows,
    technicalRowCoverage: capableRows / 224997,
    v1Members,
    b1Members,
    targetScopedRequiredMembers: requiredMembers,
    targetScopedRequiredFamilies: requiredFamilyIds.size,
    targetScopedRequiredRows: requiredRows,
    maxCapablePanelsPerMember: maxPanels,
    providerCalls: 0,
    capableAuthorizedFieldChanges: capableChanges,
    reasonCounts,
  },
  members,
};
if (stable(scope.summary) !== stable(CAPABILITY_PIN.expectedSummary))
  throw Error(`CAPABILITY_SUMMARY_DRIFT:${stable(scope.summary)}`);
const expectedIdentities = [...expectedRouteBy.keys()].sort();
const actualIdentities = members.map((m) => `${m.familyId}:${m.year}`).sort();
if (stable(actualIdentities) !== stable(expectedIdentities))
  throw Error("CAPABILITY_IDENTITY_DRIFT");
const routingBytes = bytes(scope);
if (
  sha(routingBytes) !== CAPABILITY_PIN.routingManifest.sha256 ||
  routingBytes.length !== CAPABILITY_PIN.routingManifest.byteLength
)
  throw Error("EXTERNALLY_PINNED_ROUTING_MANIFEST_DRIFT");
await writeFile(`${OUT}/routing-manifest.json`, routingBytes);
const summary = {
  schemaVersion: "tidy.offenders-remaining-phased-summary/v1",
  acceptanceAuthority: false,
  trainingEligibility: false,
  productionAcceptance: false,
  promotionAuthorization: false,
  ...scope.summary,
};
await writeFile(`${OUT}/summary.json`, bytes(summary));
const inputFiles: any[] = [];
for (const path of [...inputPaths].sort()) {
  const data = await readFile(path);
  inputFiles.push({ path, byteLength: data.length, sha256: sha(data) });
}
const generated: string[] = [];
async function walk(path: string): Promise<void> {
  for (const e of await readdir(path, { withFileTypes: true })) {
    const p = `${path}/${e.name}`;
    if (e.isDirectory()) await walk(p);
    else if (e.isFile() && !p.endsWith("/manifest.json")) generated.push(p);
  }
}
await walk(OUT);
const outputFiles = [];
for (const path of generated.sort()) {
  const data = await readFile(path);
  outputFiles.push({
    path: path.slice(OUT.length + 1),
    byteLength: data.length,
    sha256: sha(data),
  });
}
const manifest = {
  schemaVersion: "tidy.offenders-remaining-phased-run-manifest/v1",
  acceptanceAuthority: false,
  trainingEligibility: false,
  productionAcceptance: false,
  promotionAuthorization: false,
  providerCalls: 0,
  inputFiles,
  outputFiles,
  outputRootDigest: sha(stable(outputFiles)),
  summary: scope.summary,
};
await writeFile(`${OUT}/manifest.json`, bytes(manifest));
if (injectedFailure === "after-writes")
  throw new Error("INJECTED_FAILURE:after-writes");
await transaction.commit();
console.log(
  JSON.stringify({
    ok: true,
    ...scope.summary,
    outputRootDigest: manifest.outputRootDigest,
    manifestDigest: sha(
      await readFile(`${transaction.finalPath}/manifest.json`),
    ),
  }),
);

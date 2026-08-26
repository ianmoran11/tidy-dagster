import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { basename, dirname } from "node:path";
import { buildCompactSemanticContext } from "../apps/domain-worker/src/context/compactContext.js";
import { compileRoleAwareSemanticTableMap } from "../apps/domain-worker/src/catalog/role-aware-region-catalog-v5.js";
import {
  compileAtomicSemanticTableMapV2,
  executeAtomicSemanticTableMapV2,
  type AtomicRegionCatalog,
} from "../apps/domain-worker/src/catalog/semantic-map-v2.js";
import { executeRecipe } from "../apps/domain-worker/src/executor/executeRecipe.js";
import { parseWorkbook } from "../apps/domain-worker/src/workbook/parseWorkbook.js";
import {
  assertAllowedKeys,
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

const FIX = "fixtures/product-prototype";
const ROOT = ".product-prototype/offenders-remaining-phase1";
const ALLOWED = `${ROOT}/multi-panel-b2a`;
function argument(name: string): string {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1])
    throw new Error(`${name} is required`);
  return process.argv[index + 1];
}
function stable(value: any): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${stable(value[k])}`)
      .join(",")}}`;
  if (typeof value === "number" && Object.is(value, -0)) return '"-0"';
  return JSON.stringify(value);
}
function jsonBytes(value: unknown): Buffer {
  return Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
}
function exact(a: any, b: any): boolean {
  return Object.is(a, b);
}
function normalized(value: any): any {
  return typeof value === "string" ? value.trim().replace(/\s+/g, " ") : value;
}
function semanticAlias(value: any): string {
  return String(normalized(value))
    .replace(/(?:\s*\([a-z]\))+$/gi, "")
    .toUpperCase()
    .trim()
    .replace(/\s+/g, " ");
}
function canonicalCode(value: any): string {
  const raw = semanticAlias(value);
  const slug =
    raw.replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "VALUE";
  return `${slug.slice(0, 80)}_${createHash("sha256").update(raw).digest("hex").slice(0, 8)}`;
}
function collisionAudit(
  rows: any[],
  dimensions: string[],
  referenceDate: string,
): Record<string, number> {
  const modes = [
    ["exact", (value: any) => `${typeof value}:${stable(value)}`],
    [
      "normalized",
      (value: any) =>
        `${typeof normalized(value)}:${stable(normalized(value))}`,
    ],
    ["canonical", (value: any) => canonicalCode(value)],
  ] as const;
  const result: Record<string, number> = {};
  for (const [name, keyer] of modes) {
    const keys = new Set<string>();
    let excess = 0;
    for (const row of rows) {
      const key = stable([
        referenceDate,
        referenceDate,
        ...dimensions.map((dimension) => keyer(row[dimension])),
        "published-value",
      ]);
      if (keys.has(key)) excess++;
      keys.add(key);
    }
    result[`${name}DuplicateExcess`] = excess;
  }
  let aliasCollisions = 0;
  for (const dimension of dimensions) {
    const byCode = new Map<string, Set<string>>();
    for (const row of rows) {
      const code = canonicalCode(row[dimension]);
      const values = byCode.get(code) ?? new Set<string>();
      values.add(semanticAlias(row[dimension]));
      byCode.set(code, values);
    }
    aliasCollisions += [...byCode.values()].filter(
      (values) => values.size > 1,
    ).length;
  }
  result.aliasCollisions = aliasCollisions;
  return result;
}
function pos(address: string): [number, number] {
  const match = /^R(\d+)C(\d+)$/.exec(address);
  if (!match) throw new Error(`BAD_ADDRESS:${address}`);
  return [Number(match[1]), Number(match[2])];
}
function addressSort(a: string, b: string): number {
  const x = pos(a),
    y = pos(b);
  return x[0] - y[0] || x[1] - y[1];
}

const routingPath = argument("--routing-manifest");
const expectedRoutingDigest = argument("--routing-digest");
const capabilityPath = argument("--capability-pin");
const expectedCapabilityDigest = argument("--capability-pin-digest");
const authorizationPath = argument("--authorization");
const expectedAuthorizationDigest = argument("--authorization-digest");
const mapsRoot = argument("--maps-root");
const membersRoot = argument("--members-root");
const requestedOut = argument("--out");
const injectedFailure = process.argv.includes("--inject-failure")
  ? argument("--inject-failure")
  : undefined;
assertContained(routingPath, ALLOWED, "routing");
assertContained(mapsRoot, ALLOWED, "maps");
assertContained(membersRoot, ALLOWED, "members");
assertContained(capabilityPath, FIX, "capability-pin");
assertContained(authorizationPath, FIX, "authorization");
assertDistinctPaths([
  ["routing", routingPath],
  ["maps", mapsRoot],
  ["members", membersRoot],
  ["out", requestedOut],
]);
const transaction = await beginDirectoryTransaction(
  requestedOut,
  ALLOWED,
  injectedFailure,
);
const out = transaction.temporaryPath;
await mkdir(out, { recursive: true });

const authorizationBytes = await readFile(authorizationPath);
if (authorizationBytes.length > 2_000_000)
  throw new Error("AUTHORIZATION_BYTE_LIMIT");
if (sha256(authorizationBytes) !== expectedAuthorizationDigest)
  throw new Error("EXTERNAL_AUTHORIZATION_PIN_MISMATCH");
const authorization = JSON.parse(authorizationBytes.toString("utf8"));
countJsonNodes(authorization, 100_000);
assertExactKeys(
  authorization,
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
  authorization.authorizedForVersionedMapGeneration !== true ||
  authorization.acceptanceAuthority !== false ||
  authorization.trainingEligibility !== false ||
  authorization.productionAcceptance !== false ||
  authorization.promotionAuthorization !== false ||
  authorization.reviewStatus !== "pending-independent-review"
)
  throw new Error("INVALID_AUTHORIZATION");
const semanticPins = new Map<string, FilePin>();
for (const pin of authorization.inputs as FilePin[]) {
  if (semanticPins.has(pin.path))
    throw new Error(`DUPLICATE_SEMANTIC_PIN:${pin.path}`);
  semanticPins.set(pin.path, pin);
}
await verifyPinnedFileClosure(
  authorization.runtimeSourceClosure as FilePin[],
  OFFENDERS_PHASED_ROUTED_RUNTIME_SOURCE_PATHS,
);
for (const pin of authorization.runtimeSourceClosure as FilePin[]) {
  const semanticPin = semanticPins.get(pin.path);
  if (!semanticPin || stable(semanticPin) !== stable(pin))
    throw new Error(`RUNTIME_SOURCE_AUTHORIZATION_MISMATCH:${pin.path}`);
}
async function pinnedJson(
  path: string,
  maxBytes = 128_000_000,
  maxNodes = 5_000_000,
): Promise<any> {
  const pin = semanticPins.get(path);
  if (!pin) throw new Error(`UNPINNED_SEMANTIC_INPUT:${path}`);
  return (await readBoundedJson(path, { maxBytes, maxNodes, pin })).value;
}
const capabilityBytes = await readFile(capabilityPath);
if (capabilityBytes.length > 2_000_000)
  throw new Error("CAPABILITY_PIN_BYTE_LIMIT");
if (sha256(capabilityBytes) !== expectedCapabilityDigest)
  throw new Error("EXTERNAL_CAPABILITY_PIN_MISMATCH");
const capability = JSON.parse(capabilityBytes.toString("utf8"));
countJsonNodes(capability, 100_000);
assertExactKeys(
  capability,
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
  capability.schemaVersion !== "tidy.offenders-capability-routing-pin/v1" ||
  capability.semanticGenerationAuthorizationSha256 !==
    expectedAuthorizationDigest ||
  capability.authorizedForPhasedEngineering !== true ||
  capability.acceptanceAuthority !== false ||
  capability.trainingEligibility !== false ||
  capability.productionAcceptance !== false ||
  capability.promotionAuthorization !== false ||
  capability.reviewStatus !== "pending-independent-review"
)
  throw new Error("INVALID_CAPABILITY_PIN");
const routingBytes = await readFile(routingPath);
if (routingBytes.length > 2_000_000)
  throw new Error("ROUTING_MANIFEST_BYTE_LIMIT");
if (
  sha256(routingBytes) !== expectedRoutingDigest ||
  expectedRoutingDigest !== capability.routingManifest.sha256 ||
  routingBytes.length !== capability.routingManifest.byteLength
)
  throw new Error("EXTERNAL_ROUTING_PIN_MISMATCH");
const routing = JSON.parse(routingBytes.toString("utf8"));
countJsonNodes(routing, 250_000);
assertExactKeys(
  routing,
  [
    "schemaVersion",
    "acceptanceAuthority",
    "trainingEligibility",
    "productionAcceptance",
    "promotionAuthorization",
    "atomicAcceptanceBoundary",
    "semanticCorrectionAuthorization",
    "summary",
    "members",
  ],
  "routing-manifest",
);
if (
  routing.schemaVersion !== "tidy.offenders-remaining-capability-routing/v1" ||
  routing.acceptanceAuthority !== false ||
  routing.trainingEligibility !== false ||
  routing.productionAcceptance !== false ||
  routing.promotionAuthorization !== false ||
  routing.members?.length !== 170
)
  throw new Error("INVALID_ROUTING_MANIFEST");
const expectedBy = new Map<string, any>();
for (const item of capability.members) {
  const key = `${assertSafeComponent(item.familyId, "family")}:${assertSafeYear(item.year)}`;
  if (expectedBy.has(key))
    throw new Error(`DUPLICATE_CAPABILITY_IDENTITY:${key}`);
  expectedBy.set(key, item);
}
const routeBy = new Map<string, any>();
for (const item of routing.members) {
  assertAllowedKeys(
    item,
    [
      "familyId",
      "year",
      "releaseId",
      "referenceDate",
      "status",
      "rows",
      "dimensions",
      "proposedPanels",
      "catalogPath",
      "catalogBytesDigest",
      "catalogContentDigest",
      "sourceWorkbookPath",
      "sourceWorkbookDigest",
      "executionWorkbookPath",
      "executionWorkbookDigest",
      "physicalSheet",
      "providerCalls",
      "failure",
      "sameSourceWitnesses",
      "mode",
      "panels",
      "mapPath",
      "mapDigest",
      "recipeDigest",
      "trustedEnvelopeDigest",
      "physicalExecutionDigest",
      "memberArtifactPath",
      "memberArtifactDigest",
      "changedFields",
      "keyAudit",
    ],
    `routing-member:${String(item.familyId)}:${String(item.year)}`,
  );
  const key = `${assertSafeComponent(item.familyId, "family")}:${assertSafeYear(item.year)}`;
  if (routeBy.has(key)) throw new Error(`DUPLICATE_ROUTING_IDENTITY:${key}`);
  routeBy.set(key, item);
}
if (
  expectedBy.size !== 170 ||
  routeBy.size !== 170 ||
  stable([...expectedBy.keys()].sort()) !== stable([...routeBy.keys()].sort())
)
  throw new Error("ROUTING_IDENTITY_CLOSURE");
let pinnedCapable = 0,
  pinnedRefused = 0,
  pinnedV1 = 0,
  pinnedB1 = 0,
  pinnedCapableRows = 0,
  pinnedRefusedRows = 0;
for (const [identity, route] of routeBy) {
  const expected = expectedBy.get(identity);
  for (const field of [
    "status",
    "mode",
    "rows",
    "mapDigest",
    "recipeDigest",
    "trustedEnvelopeDigest",
    "memberArtifactDigest",
  ])
    if ((route[field] ?? null) !== (expected[field] ?? null))
      throw new Error(`ROUTE_FIELD_DRIFT:${identity}:${field}`);
  if (stable(route.failure ?? null) !== stable(expected.failure ?? null))
    throw new Error(`ROUTE_FAILURE_DRIFT:${identity}`);
  if (route.status === "target-scoped-required") {
    if (!route.failure) throw new Error(`MISSING_ROUTE_FAILURE:${identity}`);
    pinnedRefused++;
    pinnedRefusedRows += route.rows;
  } else if (route.status === "multi-table-v1-capable") {
    if (route.mode === "semantic-map-v1") pinnedV1++;
    else if (route.mode === "semantic-table-map-v2-recipe-v1") pinnedB1++;
    else throw new Error(`UNKNOWN_ROUTE:${identity}`);
    pinnedCapable++;
    pinnedCapableRows += route.rows;
  } else throw new Error(`UNKNOWN_ROUTE:${identity}`);
}
if (
  pinnedCapable !== 152 ||
  pinnedRefused !== 18 ||
  pinnedV1 !== 14 ||
  pinnedB1 !== 138 ||
  pinnedCapableRows !== 196316 ||
  pinnedRefusedRows !== 28681
)
  throw new Error(
    `ROUTING_SPLIT_DRIFT:${pinnedCapable}:${pinnedRefused}:${pinnedV1}:${pinnedB1}:${pinnedCapableRows}:${pinnedRefusedRows}`,
  );

const partitionPath = `${ROOT}/source-partition-canary/run-a-remediated/partition-manifest.json`;
const discrepancyPath = `${ROOT}/source-partition-canary/run-a-remediated/discrepancy-ledger.json`;
const ownership = await pinnedJson(partitionPath, 400_000_000, 15_000_000);
const discrepancies = await pinnedJson(discrepancyPath);
const ownershipBy = new Map(
  ownership.members.map((m: any) => [`${m.familyId}:${m.year}`, m]),
);
const discrepancyBy = new Map(
  (discrepancies.rows as any[]).map((x: any) => [
    `${x.familyId}:${x.year}:${x.valueAddress}:${x.dimension}`,
    x,
  ]),
);
const inputPaths = new Set<string>([
  authorizationPath,
  capabilityPath,
  routingPath,
  partitionPath,
  discrepancyPath,
  ...OFFENDERS_PHASED_ROUTED_RUNTIME_SOURCE_PATHS,
]);
const results: any[] = [];
let compiled = 0,
  refused = 0,
  providerCalls = 0,
  rows = 0,
  changedFields = 0,
  injectedV1 = false;
for (const route of [...routing.members].sort(
  (a: any, b: any) => a.familyId.localeCompare(b.familyId) || a.year - b.year,
)) {
  const identity = `${route.familyId}:${route.year}`;
  const expected = expectedBy.get(identity);
  if (!expected) throw new Error(`UNPINNED_ROUTE:${identity}`);
  for (const field of [
    "status",
    "mode",
    "rows",
    "mapDigest",
    "recipeDigest",
    "trustedEnvelopeDigest",
    "memberArtifactDigest",
  ])
    if ((route[field] ?? null) !== (expected[field] ?? null))
      throw new Error(`ROUTE_FIELD_DRIFT:${identity}:${field}`);
  if (stable(route.failure ?? null) !== stable(expected.failure ?? null))
    throw new Error(`ROUTE_FAILURE_DRIFT:${identity}`);
  if (route.status === "target-scoped-required") {
    refused++;
    results.push({
      familyId: route.familyId,
      year: route.year,
      status: "refused",
      code: "TARGET_SCOPED_REQUIRED",
      failure: route.failure,
    });
    continue;
  }
  if (
    route.status !== "multi-table-v1-capable" ||
    !["semantic-map-v1", "semantic-table-map-v2-recipe-v1"].includes(route.mode)
  )
    throw new Error(`UNKNOWN_ROUTE:${identity}`);
  const mapPath = `${mapsRoot}/${route.mapPath}`;
  assertContained(mapPath, mapsRoot, "map");
  const mapBytes = await readFile(mapPath);
  if (sha256(mapBytes) !== expected.mapDigest || mapBytes.length > 8_000_000)
    throw new Error(`MAP_PIN_DRIFT:${identity}`);
  const map = JSON.parse(mapBytes.toString("utf8"));
  countJsonNodes(map, 250_000);
  const memberPath = `${membersRoot}/${route.familyId}/${route.year}.json`;
  assertContained(memberPath, membersRoot, "member-artifact");
  const memberBytes = await readFile(memberPath);
  if (
    sha256(memberBytes) !== expected.memberArtifactDigest ||
    memberBytes.length > 64_000_000
  )
    throw new Error(`MEMBER_PIN_DRIFT:${identity}`);
  const memberArtifact = JSON.parse(memberBytes.toString("utf8"));
  countJsonNodes(memberArtifact, 2_000_000);
  const catalogPath = route.catalogPath;
  const catalogPayload = await pinnedJson(catalogPath, 16_000_000, 500_000);
  const catalog = catalogPayload.catalog as AtomicRegionCatalog;
  const workbookPath = `${FIX}/${route.executionWorkbookPath}`;
  const workbookPin = semanticPins.get(workbookPath);
  const workbookBytes = await readFile(workbookPath);
  if (
    !workbookPin ||
    workbookPin.byteLength !== workbookBytes.length ||
    workbookPin.sha256 !== sha256(workbookBytes) ||
    route.executionWorkbookDigest !== sha256(workbookBytes)
  )
    throw new Error(`WORKBOOK_PIN_DRIFT:${identity}`);
  const parsed = await parseWorkbook(workbookBytes);
  if (!parsed.ok) throw new Error(`WORKBOOK_PARSE:${identity}`);
  const sheet = parsed.workbook.sheets.find(
    (item) => item.name === route.physicalSheet,
  );
  if (!sheet) throw new Error(`PHYSICAL_SHEET:${identity}`);
  const context = buildCompactSemanticContext(sheet);
  let recipe: any,
    logicalTable: any,
    physicalWarnings = 0;
  if (route.mode === "semantic-table-map-v2-recipe-v1") {
    const result = compileAtomicSemanticTableMapV2({
      map,
      catalog,
      context,
      sheet,
    });
    if (!result.ok)
      throw new Error(`B1_COMPILE:${identity}:${result.stage}:${result.code}`);
    if (result.envelope.envelopeDigest !== expected.trustedEnvelopeDigest)
      throw new Error(`ENVELOPE_PIN_DRIFT:${identity}`);
    const verified = executeAtomicSemanticTableMapV2(
      result.envelope,
      sheet,
      expected.trustedEnvelopeDigest,
    );
    recipe = result.envelope.recipe;
    logicalTable = verified.logicalTable;
    physicalWarnings =
      verified.physicalExecution.warnings.length +
      verified.physicalExecution.tables.reduce(
        (n, t) => n + t.warnings.length,
        0,
      );
  } else {
    const result = compileRoleAwareSemanticTableMap({
      map,
      catalog: catalog as any,
      context,
    });
    if (!result.ok) throw new Error(`V1_COMPILE:${identity}:${result.code}`);
    if (!injectedV1 && injectedFailure === "v1-direction") {
      const header = result.recipe.tables[0]?.headers[0];
      if (!header) throw new Error("V1_DIRECTION_INJECTION_UNAVAILABLE");
      header.direction = header.direction === "N" ? "W" : "N";
      injectedV1 = true;
    }
    const physical = executeRecipe(result.recipe, sheet);
    if (!injectedV1 && injectedFailure === "v1-warning") {
      physical.warnings.push({ code: "AMBIGUOUS_HEADER", message: "injected" });
      injectedV1 = true;
    }
    if (physical.tables.length !== 1)
      throw new Error(`V1_TABLE_CLOSURE:${identity}`);
    recipe = result.recipe;
    logicalTable = physical.tables[0];
    physicalWarnings =
      physical.warnings.length + physical.tables[0].warnings.length;
  }
  if (
    physicalWarnings !== 0 ||
    sha256(jsonBytes(recipe)) !== expected.recipeDigest
  )
    throw new Error(`RECIPE_OR_WARNING_DRIFT:${identity}`);
  const oracle: any = ownershipBy.get(identity);
  if (!oracle) throw new Error(`ORACLE_IDENTITY:${identity}`);
  const assignments = oracle.partitions
    .flatMap((p: any) => p.valueAssignments)
    .sort((a: any, b: any) => addressSort(a.valueAddress, b.valueAddress));
  const rowsBy = new Map(
    logicalTable.rows.map((row: any) => [row._source?.address, row]),
  );
  const traceBy = new Map(
    (logicalTable.trace?.value_cells ?? []).map((item: any) => [
      item.source?.address,
      item,
    ]),
  );
  if (
    assignments.length !== route.rows ||
    rowsBy.size !== assignments.length ||
    traceBy.size !== assignments.length
  )
    throw new Error(`ROW_TRACE_CLOSURE:${identity}`);
  let memberChanges = 0;
  for (const assignment of assignments) {
    const row: any = rowsBy.get(assignment.valueAddress),
      trace: any = traceBy.get(assignment.valueAddress);
    if (!row || !trace || !exact(row["published value"], trace.value))
      throw new Error(`TARGET_VALUE:${identity}:${assignment.valueAddress}`);
    for (const dimension of route.dimensions) {
      const source = assignment.dimensionSources[dimension];
      const headers = trace.headers.filter((h: any) => h.header === dimension);
      if (
        headers.length !== 1 ||
        headers[0].direction !== source.direction ||
        headers[0].selected !== source.sourceAddress ||
        headers[0].candidates?.length !== 1 ||
        headers[0].candidates[0] !== source.sourceAddress ||
        headers[0].missing !== false ||
        headers[0].ambiguous !== false ||
        row[`${dimension}_source`] !== source.sourceAddress ||
        !exact(row[dimension], source.exactTypedRawLabel.value) ||
        !exact(headers[0].value, source.exactTypedRawLabel.value)
      )
        throw new Error(
          `ORACLE_ATTACHMENT:${identity}:${assignment.valueAddress}:${dimension}`,
        );
      const ledger = discrepancyBy.get(
        `${identity}:${assignment.valueAddress}:${dimension}`,
      );
      if (
        ledger &&
        exact(row[dimension], ledger.newRawLabel) &&
        row[`${dimension}_source`] === ledger.selectedSourceAddress
      )
        memberChanges++;
    }
  }
  if (
    memberChanges !== expected.changedFields ||
    memberChanges !== memberArtifact.oracleProof.changedFields
  )
    throw new Error(`LEDGER_CHANGE_DRIFT:${identity}`);
  const keyAudit = collisionAudit(
    logicalTable.rows,
    route.dimensions,
    route.referenceDate,
  );
  if (
    stable(keyAudit) !== stable(expected.keyAudit) ||
    stable(keyAudit) !== stable(route.keyAudit) ||
    stable(keyAudit) !== stable(memberArtifact.keyAudit) ||
    Object.values(keyAudit).some((value) => value !== 0)
  )
    throw new Error(`KEY_AUDIT_DRIFT:${identity}`);
  if (
    stable({ providerCalls: 0, logicalTable }) !==
    stable(memberArtifact.logicalExecution)
  )
    throw new Error(`LOGICAL_OUTPUT_PIN_DRIFT:${identity}`);
  const outputPath = `${out}/${route.familyId}/${route.year}.json`;
  await mkdir(dirname(outputPath), { recursive: true });
  const output = {
    schemaVersion:
      "tidy.offenders-capability-routed-verified-logical-execution/v2",
    acceptanceAuthority: false,
    trainingEligibility: false,
    productionAcceptance: false,
    promotionAuthorization: false,
    providerCalls: 0,
    familyId: route.familyId,
    year: route.year,
    mode: route.mode,
    mapDigest: expected.mapDigest,
    recipeDigest: expected.recipeDigest,
    trustedEnvelopeDigest: expected.trustedEnvelopeDigest ?? null,
    oraclePartitionDigest: sha256(await readFile(partitionPath)),
    logicalExecution: { providerCalls: 0, logicalTable },
  };
  await writeFile(outputPath, jsonBytes(output));
  inputPaths.add(mapPath);
  inputPaths.add(memberPath);
  inputPaths.add(catalogPath);
  inputPaths.add(workbookPath);
  compiled++;
  rows += route.rows;
  changedFields += memberChanges;
  results.push({
    familyId: route.familyId,
    year: route.year,
    status: "compiled",
    mode: route.mode,
    rows: route.rows,
    changedFields: memberChanges,
  });
}
if (
  compiled !== 152 ||
  refused !== 18 ||
  rows !== 196316 ||
  changedFields !== 49628 ||
  providerCalls !== 0
)
  throw new Error(
    `COMPILATION_CLOSURE:${compiled}:${refused}:${rows}:${changedFields}`,
  );
const summary = {
  schemaVersion: "tidy.offenders-capability-routed-compilation/v2",
  acceptanceAuthority: false,
  trainingEligibility: false,
  productionAcceptance: false,
  promotionAuthorization: false,
  compiled,
  refused,
  rows,
  changedFields,
  providerCalls,
  results,
};
await writeFile(`${out}/summary.json`, jsonBytes(summary));
const inputFiles = [];
for (const path of [...inputPaths].sort()) {
  const data = await readFile(path);
  inputFiles.push({ path, byteLength: data.length, sha256: sha256(data) });
}
const outputPaths: string[] = [];
async function walk(path: string): Promise<void> {
  for (const entry of await readdir(path, { withFileTypes: true })) {
    const child = `${path}/${entry.name}`;
    if (entry.isDirectory()) await walk(child);
    else if (entry.isFile() && !child.endsWith("/manifest.json"))
      outputPaths.push(child);
  }
}
await walk(out);
const outputFiles = [];
for (const path of outputPaths.sort()) {
  const data = await readFile(path);
  outputFiles.push({
    path: path.slice(out.length + 1),
    byteLength: data.length,
    sha256: sha256(data),
  });
}
const manifest = {
  schemaVersion: "tidy.offenders-capability-routed-compilation-manifest/v1",
  acceptanceAuthority: false,
  trainingEligibility: false,
  productionAcceptance: false,
  promotionAuthorization: false,
  providerCalls: 0,
  externalPins: {
    authorization: expectedAuthorizationDigest,
    capability: expectedCapabilityDigest,
    routing: expectedRoutingDigest,
  },
  inputFiles,
  outputFiles,
  outputRootDigest: sha256(stable(outputFiles)),
  summary: { compiled, refused, rows, changedFields, providerCalls },
};
await writeFile(`${out}/manifest.json`, jsonBytes(manifest));
if (injectedFailure === "after-writes")
  throw new Error("INJECTED_FAILURE:after-writes");
await transaction.commit();
console.log(
  JSON.stringify({
    compiled,
    refused,
    rows,
    changedFields,
    providerCalls,
    outputRootDigest: manifest.outputRootDigest,
  }),
);

import { createHash } from "node:crypto";
import { lstat, mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import { dirname, relative, resolve, sep } from "node:path";
import { buildCompactSemanticContext } from "../apps/domain-worker/src/context/compactContext.js";
import { buildSemanticCellFormattingFacts } from "../apps/domain-worker/src/catalog/format-aware-region-catalog-v2.js";
import {
  buildRoleAwareSemanticRegionCatalog,
  buildSemanticCellDataFacts,
  compileRoleAwareSemanticTableMap,
} from "../apps/domain-worker/src/catalog/role-aware-region-catalog-v5.js";
import { parseSemanticTableMapJson } from "../apps/domain-worker/src/catalog/semantic-map-v1.js";
import {
  compileAtomicSemanticTableMapV2,
  executeAtomicSemanticTableMapV2,
  parseSemanticTableMapV2Json,
  digestAtomicRegionCatalog,
} from "../apps/domain-worker/src/catalog/semantic-map-v2.js";
import {
  compileTargetScopedRecipeV02,
  digestTargetScopedBytes,
  executeTargetScopedRecipeV02,
  parseTargetScopedSemanticMapV1,
} from "../apps/domain-worker/src/catalog/target-scoped-recipe-v02.js";
import { executeRecipe } from "../apps/domain-worker/src/executor/executeRecipe.js";
import { parseWorkbook } from "../apps/domain-worker/src/workbook/parseWorkbook.js";
import { beginDirectoryTransaction } from "./offenders-phased-safety.js";

const ROOT = resolve(".");
const PROPOSAL_ALLOWED = ".product-prototype/offenders-remaining-phase1/c4-proposal";
const RUNTIME_ALLOWED = ".product-prototype/offenders-remaining-c4-runtime";
const LIMITS = {
  routeBytes: 2_000_000,
  mapBytes: 2_000_000,
  workbookBytes: 10_000_000,
  jsonDepth: 100,
  jsonNodes: 2_000_000,
  workbookSheets: 100,
  workbookCells: 1_000_000,
  sheetCells: 500_000,
  memberRows: 10_000,
  totalRows: 225_000,
  memberOutputBytes: 64_000_000,
  totalOutputBytes: 1_000_000_000,
} as const;
const ROUTES = [
  "semantic-map-v1-recipe-v01",
  "semantic-map-v2-recipe-v01",
  "target-scoped-recipe-v02",
] as const;
type Route = (typeof ROUTES)[number];
type Member = {
  familyId: string; year: number; releaseId: string; route: Route;
  cohortPath: string; workbookPath: string; workbookDigest: string; workbookBytes: number;
  physicalSheet: string; mapPath: string; mapDigest: string; mapBytes: number;
  rows: number; dimensions: string[]; orderedAddressDigest: string; rowTraceDigest: string;
  c3MemberPath: string; c3MemberDigest: string;
};
function arg(name: string): string { const i=process.argv.indexOf(name); if(i<0||!process.argv[i+1]) throw Error(`${name} required`); return process.argv[i+1]; }
function sha(value: Buffer|string): string { return `sha256:${createHash("sha256").update(value).digest("hex")}`; }
function stable(v: any): string { if(Array.isArray(v)) return `[${v.map(stable).join(",")}]`; if(v&&typeof v==="object") return `{${Object.keys(v).sort().map(k=>`${JSON.stringify(k)}:${stable(v[k])}`).join(",")}}`; if(typeof v==="number"&&Object.is(v,-0)) return '"-0"'; return JSON.stringify(v); }
function pretty(v: unknown): Buffer { return Buffer.from(`${JSON.stringify(v,null,2)}\n`); }
function pos(a:string):[number,number]{const m=/^R(\d+)C(\d+)$/.exec(a);if(!m)throw Error(`BAD_ADDRESS:${a}`);return[+m[1],+m[2]];}
function sortedAddresses(values:string[]):string[]{return [...values].sort((a,b)=>{const x=pos(a),y=pos(b);return x[0]-y[0]||x[1]-y[1]});}
function typeData(v:any):string { if(v===null||typeof v==="boolean")return "invalid"; if(typeof v==="number")return "numeric"; if(typeof v==="string")return "string"; return "invalid"; }
async function safeFile(path:string,label:string,maxBytes=Number.MAX_SAFE_INTEGER):Promise<Buffer>{
  const absolute=resolve(path), rel=relative(ROOT,absolute);
  if(!rel||rel===".."||rel.startsWith(`..${sep}`))throw Error(`PATH_ESCAPE:${label}`);
  let cursor=ROOT; for(const part of rel.split(sep)){cursor=resolve(cursor,part);const info=await lstat(cursor);if(info.isSymbolicLink())throw Error(`SYMLINK_PATH:${label}`);}
  const info=await lstat(absolute);if(!info.isFile())throw Error(`NOT_FILE:${label}`);
  if(await realpath(absolute)!==absolute)throw Error(`REALPATH_DRIFT:${label}`);
  if(info.size>maxBytes)throw Error(`RESOURCE_FILE_BYTES:${label}:${info.size}`);
  return readFile(absolute);
}
function boundedJson(bytes:Buffer,label:string):any{
  let value:any;try{value=JSON.parse(bytes.toString("utf8"));}catch{throw Error(`INVALID_JSON:${label}`);}
  let nodes=0;const stack:Array<[any,number]>=[[value,1]];
  while(stack.length){const [item,depth]=stack.pop()!;nodes++;if(nodes>LIMITS.jsonNodes||depth>LIMITS.jsonDepth)throw Error(`RESOURCE_JSON:${label}`);if(Array.isArray(item))for(const child of item)stack.push([child,depth+1]);else if(item&&typeof item==="object")for(const child of Object.values(item))stack.push([child,depth+1]);}
  return value;
}
function exactKeys(value:any,keys:string[],label:string){if(!value||typeof value!=="object"||Array.isArray(value)||stable(Object.keys(value).sort())!==stable([...keys].sort()))throw Error(`SHAPE:${label}`);}
function identity(execution:any):string{return stable(execution);}

const routePath=arg("--routes"), requestedOut=arg("--out");
const fixtureRoot=process.argv.includes("--fixture-root")?resolve(arg("--fixture-root")):ROOT;
const selectedFamily=process.argv.includes("--family")?arg("--family"):undefined;
if(selectedFamily&&(!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(selectedFamily)||resolve(routePath)!==resolve("fixtures/product-prototype/offenders-remaining-c4-route-manifest-v1.json")||fixtureRoot!==ROOT))throw Error("INVALID_RUNTIME_FAMILY_HANDSHAKE");
const injected=process.argv.includes("--inject-failure")?arg("--inject-failure"):undefined;
const routeBytes=await safeFile(routePath,"routes",LIMITS.routeBytes);
const manifest=boundedJson(routeBytes,"routes");
exactKeys(manifest,["schemaVersion","acceptanceAuthority","trainingEligibility","productionAcceptance","promotionAuthorization","c3AuthorizationDigest","members","summary"],"manifest");
if(manifest.schemaVersion!=="tidy.offenders-c4-route-manifest/v1"||manifest.acceptanceAuthority!==false||manifest.trainingEligibility!==false||manifest.productionAcceptance!==false||manifest.promotionAuthorization!==false)throw Error("ROUTE_AUTHORITY");
if(!Array.isArray(manifest.members)||manifest.members.length!==170)throw Error("ROUTE_MEMBER_COUNT");
const allMembers=manifest.members as Member[];
const memberKeys=["familyId","year","releaseId","route","cohortPath","workbookPath","workbookDigest","workbookBytes","physicalSheet","mapPath","mapDigest","mapBytes","rows","dimensions","orderedAddressDigest","rowTraceDigest","c3MemberPath","c3MemberDigest"];
const seen=new Set<string>(), allCounts:Record<Route,number>={"semantic-map-v1-recipe-v01":0,"semantic-map-v2-recipe-v01":0,"target-scoped-recipe-v02":0};
for(const m of allMembers){exactKeys(m,memberKeys,"member");const key=`${m.familyId}:${m.year}`;if(!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(m.familyId)||!Number.isInteger(m.year)||m.rows<1||m.rows>LIMITS.memberRows||m.workbookBytes<1||m.workbookBytes>LIMITS.workbookBytes||m.mapBytes<1||m.mapBytes>LIMITS.mapBytes)throw Error(`RESOURCE_OR_IDENTITY:${key}`);if(seen.has(key))throw Error(`DUPLICATE_ROUTE:${key}`);seen.add(key);if(!ROUTES.includes(m.route))throw Error(`UNKNOWN_ROUTE:${key}`);allCounts[m.route]++;}
if(stable(allCounts)!==stable({"semantic-map-v1-recipe-v01":14,"semantic-map-v2-recipe-v01":138,"target-scoped-recipe-v02":18}))throw Error("ROUTE_UNION");
const members=selectedFamily?allMembers.filter(x=>x.familyId===selectedFamily):allMembers;if(!members.length)throw Error("FAMILY_NOT_ROUTED");
const counts:Record<Route,number>={"semantic-map-v1-recipe-v01":0,"semantic-map-v2-recipe-v01":0,"target-scoped-recipe-v02":0};for(const m of members)counts[m.route]++;
if(members.reduce((total,m)=>total+m.rows,0)>LIMITS.totalRows)throw Error("RESOURCE_TOTAL_ROWS");
// Complete digest/size/path preflight before acquiring an output lease or writing.
for(const m of members){const workbook=await safeFile(m.workbookPath,"workbook-preflight",LIMITS.workbookBytes),map=await safeFile(resolve(fixtureRoot,m.mapPath),"map-preflight",LIMITS.mapBytes);if(workbook.length!==m.workbookBytes||sha(workbook)!==m.workbookDigest||map.length!==m.mapBytes||sha(map)!==m.mapDigest)throw Error(`PREFLIGHT_PIN:${m.familyId}:${m.year}`);boundedJson(map,`map-preflight:${m.familyId}:${m.year}`);const parsed=await parseWorkbook(workbook);if(!parsed.ok||parsed.workbook.sheets.length>LIMITS.workbookSheets||parsed.workbook.sheets.reduce((n,s)=>n+s.cells.length,0)>LIMITS.workbookCells||parsed.workbook.sheets.some(s=>s.cells.length>LIMITS.sheetCells)||parsed.workbook.sheets.filter(s=>s.name===m.physicalSheet).length!==1)throw Error(`PREFLIGHT_WORKBOOK:${m.familyId}:${m.year}`);}
const tx=await beginDirectoryTransaction(requestedOut,selectedFamily?RUNTIME_ALLOWED:PROPOSAL_ALLOWED,injected); const out=tx.temporaryPath; await mkdir(out,{recursive:false});
let rowsTotal=0,totalOutputBytes=0;
for(const m of [...members].sort((a,b)=>a.familyId.localeCompare(b.familyId)||a.year-b.year)){
  const workbookBytes=await safeFile(m.workbookPath,"workbook",LIMITS.workbookBytes), mapBytes=await safeFile(resolve(fixtureRoot,m.mapPath),"map",LIMITS.mapBytes);
  if(workbookBytes.length!==m.workbookBytes||sha(workbookBytes)!==m.workbookDigest)throw Error(`WORKBOOK_PIN:${m.familyId}:${m.year}`);
  if(mapBytes.length!==m.mapBytes||sha(mapBytes)!==m.mapDigest)throw Error(`MAP_PIN:${m.familyId}:${m.year}`);
  const parsed=await parseWorkbook(workbookBytes);if(!parsed.ok)throw Error(`WORKBOOK_PARSE:${m.familyId}:${m.year}`);
  if(parsed.workbook.sheets.length>LIMITS.workbookSheets||parsed.workbook.sheets.reduce((n,s)=>n+s.cells.length,0)>LIMITS.workbookCells||parsed.workbook.sheets.some(s=>s.cells.length>LIMITS.sheetCells))throw Error(`RESOURCE_WORKBOOK:${m.familyId}:${m.year}`);
  const matchingSheets=parsed.workbook.sheets.filter(x=>x.name===m.physicalSheet);if(matchingSheets.length!==1)throw Error(`SHEET_UNIQUE:${m.familyId}:${m.year}`);const sheet=matchingSheets[0];
  const context=buildCompactSemanticContext(sheet);
  const catalog=buildRoleAwareSemanticRegionCatalog(context,{formattingFacts:buildSemanticCellFormattingFacts(sheet.cells),cellDataFacts:buildSemanticCellDataFacts(sheet.cells)});
  const raw=mapBytes.toString("utf8"),mapJson=boundedJson(mapBytes,`map:${m.familyId}:${m.year}`); let recipe:any, execution:any, nativeTrace:any[], protocol:string;
  if(m.route==="semantic-map-v1-recipe-v01"){
    if(mapJson.version!=="semantic-table-map-v1")throw Error(`ROUTE_SCHEMA_V1:${m.familyId}:${m.year}`);
    const compiled=compileRoleAwareSemanticTableMap({map:parseSemanticTableMapJson(raw),catalog,context});if(!compiled.ok)throw Error(`V1_COMPILE:${compiled.code}`);
    recipe=compiled.recipe; const first=executeRecipe(recipe,sheet),second=executeRecipe(recipe,sheet);if(identity(first)!==identity(second))throw Error("NONDETERMINISTIC_V1");execution=first;nativeTrace=first.tables[0].trace.value_cells;protocol="RecipeV01";
  }else if(m.route==="semantic-map-v2-recipe-v01"){
    if(mapJson.version!=="semantic-table-map-v2")throw Error(`ROUTE_SCHEMA_B1:${m.familyId}:${m.year}`);
    const compiled=compileAtomicSemanticTableMapV2({map:parseSemanticTableMapV2Json(raw),catalog,context,sheet});if(!compiled.ok)throw Error(`B1_COMPILE:${compiled.code}`);
    const first=executeAtomicSemanticTableMapV2(compiled.envelope,sheet,compiled.envelope.envelopeDigest),second=executeAtomicSemanticTableMapV2(compiled.envelope,sheet,compiled.envelope.envelopeDigest);if(identity(first)!==identity(second))throw Error("NONDETERMINISTIC_B1");
    recipe=compiled.envelope.recipe;execution={sheet:sheet.name,tables:[first.logicalTable],warnings:[]};nativeTrace=first.logicalTable.trace.value_cells;protocol="RecipeV01";
  }else{
    if(mapJson.version!=="target-scoped-semantic-map-v1")throw Error(`ROUTE_SCHEMA_C2:${m.familyId}:${m.year}`);
    const parsedMap=parseTargetScopedSemanticMapV1(raw),catalogRaw=JSON.stringify(catalog),source=parsedMap.source;
    const compiled=compileTargetScopedRecipeV02({mapRaw:raw,expectedMapBytesDigest:sha(mapBytes),catalogRaw,expectedCatalogBytesDigest:digestTargetScopedBytes(catalogRaw),sheet,source});if(!compiled.ok)throw Error(`C2_COMPILE:${compiled.code}`);
    const input={mapRaw:raw,catalogRaw,sheet,source,trustedEnvelopeDigest:compiled.envelope.envelopeDigest};const first=executeTargetScopedRecipeV02(compiled.envelope,input),second=executeTargetScopedRecipeV02(compiled.envelope,input);if(identity(first)!==identity(second))throw Error("NONDETERMINISTIC_C2");
    recipe=compiled.envelope.recipe;execution={sheet:sheet.name,tables:[{table:first.table.name,sheet:first.table.sheet,rows:first.table.rows,trace:{value_cells:first.table.trace},warnings:[]}],warnings:[]};nativeTrace=first.table.trace;protocol="TargetScopedRecipeV02";
  }
  const table=execution.tables[0], rows=table.rows;
  if(execution.warnings.length||rows.length!==m.rows||table.sheet!==m.physicalSheet)throw Error(`EXECUTION_CLOSURE:${m.familyId}:${m.year}`);
  const addresses=sortedAddresses(rows.map((r:any)=>r._source.address));if(new Set(addresses).size!==rows.length||sha(stable(addresses))!==m.orderedAddressDigest)throw Error(`ADDRESS_PROOF:${m.familyId}:${m.year}`);
  const traceBy=new Map(nativeTrace.map((t:any)=>[(t.source??t.target).address,t]));
  const proof=addresses.map(address=>{const row=rows.find((r:any)=>r._source.address===address),tr=traceBy.get(address);if(!tr)throw Error(`TRACE_GAP:${address}`);const attached=m.route==="target-scoped-recipe-v02"?new Map(tr.attachments.map((x:any)=>[x.dimensionName,x])):new Map(tr.headers.map((x:any)=>[x.header,x]));return {address,value:row["published value"],valueDataType:typeData(row["published value"]),dimensions:m.dimensions.map(d=>{const x:any=attached.get(d);if(!x||x.missing!==false||x.ambiguous!==false||x.candidates.length!==1||x.selected!==row[`${d}_source`]||!Object.is(x.value,row[d]))throw Error(`ATTACHMENT_PROOF:${m.familyId}:${m.year}:${address}:${d}`);return {dimension:d,value:row[d],source:x.selected,direction:x.direction,dataType:typeData(row[d])};})};});
  if(sha(stable(proof))!==m.rowTraceDigest)throw Error(`ROW_TRACE_PROOF:${m.familyId}:${m.year}`);
  const recipeBytes=pretty(recipe),executionBytes=pretty(execution),proofBytes=pretty({schemaVersion:"tidy.offenders-c4-route-proof/v1",acceptanceAuthority:false,trainingEligibility:false,familyId:m.familyId,year:m.year,releaseId:m.releaseId,route:m.route,recipeProtocol:protocol,mapDigest:m.mapDigest,recipeDigest:sha(recipeBytes),executionDigest:sha(executionBytes),workbookDigest:m.workbookDigest,physicalSheet:m.physicalSheet,rows:rows.length,orderedAddressDigest:m.orderedAddressDigest,rowTraceDigest:m.rowTraceDigest,c3MemberDigest:m.c3MemberDigest,providerCalls:0,warnings:0,deterministic:true}),memberOutputBytes=recipeBytes.length+executionBytes.length+proofBytes.length;if(memberOutputBytes>LIMITS.memberOutputBytes||totalOutputBytes+memberOutputBytes>LIMITS.totalOutputBytes)throw Error(`RESOURCE_OUTPUT:${m.familyId}:${m.year}`);totalOutputBytes+=memberOutputBytes;const directory=resolve(out,"members",m.familyId,String(m.year));await mkdir(directory,{recursive:true});
  await writeFile(resolve(directory,"normalized-recipe.json"),recipeBytes);await writeFile(resolve(directory,"execution.json"),executionBytes);
  await writeFile(resolve(directory,"route-proof.json"),proofBytes); rowsTotal+=rows.length;
}
const expectedRows=members.reduce((total,m)=>total+m.rows,0);if(expectedRows>LIMITS.totalRows||rowsTotal!==expectedRows||(!selectedFamily&&rowsTotal!==224997))throw Error(`ROW_TOTAL:${rowsTotal}`);
const records:any[]=[];
// Fixed member paths are the complete payload; avoid recursive path discovery as authority.
for(const m of [...members].sort((a,b)=>a.familyId.localeCompare(b.familyId)||a.year-b.year))for(const name of ["execution.json","normalized-recipe.json","route-proof.json"]){const rel=`members/${m.familyId}/${m.year}/${name}`,bytes=await readFile(resolve(out,rel));records.push({path:rel,byteLength:bytes.length,sha256:sha(bytes)});}
const payloadRoot=sha(stable(records));const outputManifest={schemaVersion:"tidy.offenders-c4-replay-output/v1",acceptanceAuthority:false,trainingEligibility:false,providerCalls:0,routeManifestDigest:sha(routeBytes),members:members.length,families:new Set(members.map(x=>x.familyId)).size,rows:rowsTotal,routes:counts,files:records,payloadRootDigest:payloadRoot};await writeFile(resolve(out,"manifest.json"),pretty(outputManifest));await tx.commit();console.log(JSON.stringify({members:outputManifest.members,families:outputManifest.families,rows:rowsTotal,routes:counts,payloadRootDigest:payloadRoot}));

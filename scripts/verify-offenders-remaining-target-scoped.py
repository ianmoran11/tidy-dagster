#!/usr/bin/env python3
"""Fail-closed external verifier for non-authoritative Offenders C2 artifacts."""
import argparse, hashlib, json, os, shutil, stat, subprocess, sys, uuid
from pathlib import Path, PurePosixPath

REPO = Path.cwd().resolve()
ALLOWED = Path('.product-prototype/offenders-remaining-phase1/target-scoped-c2')
AUTH_DEFAULT = Path('fixtures/product-prototype/offenders-remaining-target-scoped-generation-authorization-v1.json')
FALSE_FLAGS = ('acceptanceAuthority','trainingEligibility','productionAcceptance','promotionAuthorization')
DIGEST = 'sha256:'
EXPECTED_SUMMARY = {'members':18,'families':6,'rows':28681,'partitions':262,'targetSets':262,'sourceUniverses':2206,'attachmentChoices':8131,'vectors':28681,'resolutionOperations':1160748,'changedFields':2739,'b2aChangedFields':49628,'combinedAuthorizedChangedFields':52367,'providerCalls':0,'warnings':0,'ambiguities':0,'gaps':0,'overlaps':0,'keyDefects':0}
SUMMARY_KEYS = {'schemaVersion','pendingExternalAuthorizationReview',*FALSE_FLAGS,'authorizationPath','authorizationDigest',*EXPECTED_SUMMARY,'maxResources','payloadRootDigest'}
MEMBER_KEYS = {'schemaVersion','pendingExternalAuthorizationReview',*FALSE_FLAGS,'familyId','year','releaseId','rows','dimensions','partitions','targetSets','sourceUniverses','attachmentChoices','vectors','resolutionOperations','providerCalls','sourceWorkbookPath','sourceWorkbookDigest','executionWorkbookPath','executionWorkbookDigest','physicalSheet','selectedCellCount','sourceExecutionEquivalenceDigest','mapPath','mapDigest','envelopePath','trustedEnvelopeDigest','executionPath','executionDigest','oracleProof','keyAudit','resources'}

def sha(data): return DIGEST+hashlib.sha256(data).hexdigest()
def stable(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def root_digest(records): return sha(stable(sorted(records,key=lambda x:x['path'])).encode())
def exact_keys(value, keys, label):
 if type(value) is not dict or set(value)!=set(keys): raise RuntimeError(f'SCHEMA_KEYS:{label}')
def is_int(value): return type(value) is int and value>=0
def digest(value): return type(value) is str and len(value)==71 and value.startswith(DIGEST) and all(c in '0123456789abcdef' for c in value[7:])
def flags(value,label):
 if value.get('pendingExternalAuthorizationReview') is not True or any(value.get(k) is not False for k in FALSE_FLAGS): raise RuntimeError(f'AUTHORITY_FLAGS:{label}')
def canonical_rel(value,label):
 if type(value) is not str or not value or '\\' in value or value.startswith('/') or value.endswith('/') or str(PurePosixPath(value))!=value or any(p in ('','.','..') for p in value.split('/')): raise RuntimeError(f'UNSAFE_REFERENCE:{label}:{value}')
 return value

def safe_regular(base:Path, rel:str, label:str, declared=None):
 rel=canonical_rel(rel,label)
 if declared is not None and rel not in declared: raise RuntimeError(f'UNDECLARED_REFERENCE:{label}:{rel}')
 root=base.resolve(strict=True); cur=root
 for part in rel.split('/'):
  cur=cur/part
  info=cur.lstat()
  if stat.S_ISLNK(info.st_mode): raise RuntimeError(f'SYMLINK:{label}:{rel}')
  if cur != root/rel and not stat.S_ISDIR(info.st_mode): raise RuntimeError(f'SPECIAL_ANCESTOR:{label}:{rel}')
 real=cur.resolve(strict=True)
 try: real.relative_to(root)
 except ValueError: raise RuntimeError(f'PATH_ESCAPE:{label}:{rel}')
 if not stat.S_ISREG(real.stat().st_mode): raise RuntimeError(f'SPECIAL:{label}:{rel}')
 return real

def safe_repo_file(rel,label): return safe_regular(REPO,canonical_rel(rel,label),label)
def load_file(path:Path,max_bytes=450_000_000):
 info=path.lstat()
 if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode): raise RuntimeError(f'UNSAFE_FILE:{path}')
 raw=path.read_bytes()
 if len(raw)>max_bytes: raise RuntimeError(f'BYTE_LIMIT:{path}')
 try: value=json.loads(raw)
 except Exception as exc: raise RuntimeError(f'JSON:{path}:{exc}')
 return value,raw

def json_nodes(value):
 count=0; stack=[value]
 while stack:
  item=stack.pop(); count+=1
  if type(item) is list: stack.extend(item)
  elif type(item) is dict: stack.extend(item.values())
 return count

def executable_proof(proof,label):
 exact_keys(proof,{'version','executablePath','realPath','linkTarget','byteLength','sha256'},f'{label}-executable')
 path=Path(proof['executablePath']);info=path.lstat()
 if not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):raise RuntimeError(f'TOOLCHAIN_EXECUTABLE_TYPE:{label}')
 real=path.resolve(strict=True);raw=real.read_bytes();link=os.readlink(path) if path.is_symlink() else None
 if str(real)!=proof['realPath'] or link!=proof['linkTarget'] or len(raw)!=proof['byteLength'] or sha(raw)!=proof['sha256']:raise RuntimeError(f'TOOLCHAIN_EXECUTABLE_DRIFT:{label}')
 version=subprocess.run([proof['executablePath'],'--version'],capture_output=True,text=True,check=True).stdout.strip() or subprocess.run([proof['executablePath'],'--version'],capture_output=True,text=True,check=True).stderr.strip()
 if version!=proof['version']:raise RuntimeError(f'TOOLCHAIN_VERSION:{label}')
def node_modules_entries(root):
 boundary=root.resolve(strict=True);entries=[]
 def add(path):
  rel=path.relative_to(root).as_posix();info=path.lstat()
  if stat.S_ISLNK(info.st_mode):
   target=os.readlink(path);real=path.resolve(strict=True)
   try:target_rel=real.relative_to(boundary).as_posix()
   except ValueError:raise RuntimeError(f'NODE_MODULES_SYMLINK_ESCAPE:{rel}')
   if not real.is_file():raise RuntimeError(f'NODE_MODULES_SYMLINK_TARGET:{rel}')
   raw=real.read_bytes();entries.append({'path':rel,'kind':'symlink','target':target,'targetPath':target_rel,'targetByteLength':len(raw),'targetSha256':sha(raw)})
  elif stat.S_ISREG(info.st_mode):
   raw=path.read_bytes();entries.append({'path':rel,'kind':'file','byteLength':len(raw),'sha256':sha(raw)})
  else:raise RuntimeError(f'NODE_MODULES_SPECIAL:{rel}')
 for base,dirs,files in os.walk(root,followlinks=False):
  basep=Path(base);kept=[]
  for name in sorted(dirs):
   path=basep/name;rel=path.relative_to(root).as_posix()
   if rel in ('.cache','.vite'):continue
   if path.is_symlink():add(path)
   else:kept.append(name)
  dirs[:]=kept
  for name in sorted(files):
   path=basep/name;rel=path.relative_to(root).as_posix()
   if rel=='.DS_Store' or rel.startswith('.cache/') or rel.startswith('.vite/'):continue
   add(path)
 entries.sort(key=lambda x:x['path']);return entries
def verify_toolchain(toolchain,pins):
 exact_keys(toolchain,{'schemaVersion','packageJson','packageLock','node','python','nodeModules','tsxEntrypoint'},'toolchain')
 if toolchain['schemaVersion']!='tidy.offenders-target-scoped-toolchain/v1':raise RuntimeError('TOOLCHAIN_SCHEMA')
 for field,path in (('packageJson','package.json'),('packageLock','package-lock.json')):
  if toolchain[field]!=pins.get(path):raise RuntimeError(f'TOOLCHAIN_PACKAGE_PIN:{path}')
 executable_proof(toolchain['node'],'node');executable_proof(toolchain['python'],'python')
 if Path(sys.executable).resolve(strict=True)!=Path(toolchain['python']['realPath']).resolve(strict=True):raise RuntimeError('TOOLCHAIN_PYTHON_PROCESS_MISMATCH')
 nm=toolchain['nodeModules'];exact_keys(nm,{'root','manifest','entryCount','regularFiles','symlinks','totalBytes','merkleRoot'},'node-modules-toolchain')
 if nm['root']!='node_modules' or nm['manifest']!=pins.get(nm['manifest']['path']):raise RuntimeError('NODE_MODULES_MANIFEST_PIN')
 manifest,raw=load_file(safe_repo_file(nm['manifest']['path'],'node-modules-manifest'),8_000_000)
 if len(raw)!=nm['manifest']['byteLength'] or sha(raw)!=nm['manifest']['sha256']:raise RuntimeError('NODE_MODULES_MANIFEST_DIGEST')
 exact_keys(manifest,{'schemaVersion','policy','root','regularFiles','symlinks','totalBytes','entryCount','merkleRoot','entries'},'node-modules-manifest')
 policy={'include':'all regular files and symlinks with regular in-root targets','excluded':['.DS_Store (Finder metadata, never imported)','.cache/** (Jiti/Pi compile cache outside project runtime imports)','.vite/** (Vitest result cache, never imported by replay)']}
 if manifest['schemaVersion']!='tidy.node-modules-closure/v1' or manifest['root']!='node_modules' or manifest['policy']!=policy:raise RuntimeError('NODE_MODULES_MANIFEST_SCHEMA')
 entries=node_modules_entries(REPO/'node_modules');regular=sum(x['kind']=='file' for x in entries);symlinks=len(entries)-regular;total=sum(x.get('byteLength',0) for x in entries);merkle=sha(stable(entries).encode())
 actual={'entryCount':len(entries),'regularFiles':regular,'symlinks':symlinks,'totalBytes':total,'merkleRoot':merkle}
 if manifest['entries']!=entries or any(manifest[k]!=v or nm[k]!=v for k,v in actual.items()):raise RuntimeError('NODE_MODULES_CLOSURE_DRIFT')
 tsx=toolchain['tsxEntrypoint'];path='node_modules/tsx/dist/cli.mjs'
 if tsx!=pins.get(path) or tsx['path']!=path:raise RuntimeError('TSX_ENTRYPOINT_DRIFT')
 entry=next((x for x in entries if x['path']=='tsx/dist/cli.mjs'),None)
 if not entry or entry['kind']!='file' or entry['byteLength']!=tsx['byteLength'] or entry['sha256']!=tsx['sha256']:raise RuntimeError('TSX_ENTRYPOINT_CLOSURE')
 return toolchain

def authority(path:Path, expected_digest:str):
 auth_path=safe_repo_file(canonical_rel(path.as_posix(),'authorization'),'authorization')
 auth,raw=load_file(auth_path,5_000_000)
 if sha(raw)!=expected_digest: raise RuntimeError('AUTHORIZATION_DIGEST')
 exact_keys(auth,{'schemaVersion','authorizedForTargetScopedEngineering','pendingExternalAuthorizationReview',*FALSE_FLAGS,'authorizationBoundary','toolchainClosure','runtimeSourceClosure','inputs','expectedScope','reviewStatus'},'authorization')
 flags(auth,'authorization')
 if auth['schemaVersion']!='tidy.offenders-target-scoped-generation-authorization/v1' or auth['authorizedForTargetScopedEngineering'] is not True or auth['reviewStatus']!='pending-independent-review' or auth['expectedScope']!={'members':18,'families':6,'rows':28681,'partitions':262,'universes':2206,'attachments':8131,'vectors':28681,'operations':1160748,'changes':2739,'b2aChanges':49628,'combinedChanges':52367}: raise RuntimeError('AUTHORIZATION_SCHEMA')
 pins={}
 for item in auth['inputs']:
  exact_keys(item,{'path','byteLength','sha256'},'input-pin'); rel=canonical_rel(item['path'],'input-pin')
  if rel in pins or not is_int(item['byteLength']) or not digest(item['sha256']): raise RuntimeError('INPUT_PIN_SCHEMA')
  pins[rel]=item
 runtime=[]
 for item in auth['runtimeSourceClosure']:
  exact_keys(item,{'path','byteLength','sha256'},'runtime-pin'); rel=canonical_rel(item['path'],'runtime-pin')
  if rel in runtime: raise RuntimeError('DUPLICATE_RUNTIME_PIN')
  runtime.append(rel)
  if pins.get(rel)!=item: raise RuntimeError('RUNTIME_INPUT_PIN_MISMATCH')
 for rel,pin in pins.items():
  file=safe_repo_file(rel,'authorized-input'); info=file.stat()
  if info.st_size!=pin['byteLength'] or sha(file.read_bytes())!=pin['sha256']: raise RuntimeError(f'PIN_DRIFT:{rel}')
 def pinned(rel):
  pin=pins.get(rel)
  if not pin: raise RuntimeError(f'UNPINNED:{rel}')
  value,raw=load_file(safe_repo_file(rel,'pinned-json'))
  if len(raw)!=pin['byteLength'] or sha(raw)!=pin['sha256']: raise RuntimeError(f'PIN_DRIFT:{rel}')
  return value
 cap=pinned('fixtures/product-prototype/offenders-remaining-capability-routing-pin-v1.json')
 own=pinned('.product-prototype/offenders-remaining-phase1/source-partition-canary/run-a-remediated/partition-manifest.json')
 routes={}
 for member in cap['members']:
  if member['status']=='target-scoped-required':
   ident=(member['familyId'],member['year'])
   if ident in routes: raise RuntimeError('DUPLICATE_CAPABILITY_ROUTE')
   routes[ident]=member
 custody={(m['familyId'],m['year']):m for m in own['members'] if (m['familyId'],m['year']) in routes}
 if len(routes)!=18 or len(custody)!=18 or sum(m['rows'] for m in routes.values())!=28681: raise RuntimeError('AUTH_SCOPE')
 toolchain=verify_toolchain(auth['toolchainClosure'],pins)
 return auth,pins,routes,custody,toolchain

def expected_paths(routes):
 core=[]
 for family,year in sorted(routes):
  for kind in ('maps','envelopes','executions','members'): core.append(f'{kind}/{family}/{year}.json')
 metadata=['summary.json','routing-manifest.json','reproduction-attestation.json']
 return set(core),set(core+metadata)

def read_declared(root,rel,declared): return load_file(safe_regular(root,rel,rel,declared))
def check_digest_record(record,label):
 exact_keys(record,{'path','byteLength','sha256'},label)
 canonical_rel(record['path'],label)
 if not is_int(record['byteLength']) or not digest(record['sha256']): raise RuntimeError(f'RECORD_SCHEMA:{label}')

def validate(root_arg:str, expected_auth:str, routes, custody):
 root_rel=canonical_rel(root_arg,'root')
 root_parts=PurePosixPath(root_rel)
 if root_parts.parent!=PurePosixPath(ALLOWED.as_posix()) or not root_parts.name.startswith('run-') or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-' for c in root_parts.name): raise RuntimeError('UNSAFE_ROOT_POLICY')
 root=(REPO/root_rel)
 # Validate every existing ancestor before resolving the root.
 cur=REPO
 for part in root_rel.split('/'):
  cur=cur/part; info=cur.lstat()
  if stat.S_ISLNK(info.st_mode): raise RuntimeError(f'SYMLINK_ROOT:{cur}')
  if not stat.S_ISDIR(info.st_mode): raise RuntimeError(f'SPECIAL_ROOT:{cur}')
 root=root.resolve(strict=True)
 allowed_root=(REPO/ALLOWED).resolve(strict=True)
 if root.parent!=allowed_root: raise RuntimeError('UNSAFE_ROOT_POLICY')
 try: root.relative_to(allowed_root)
 except ValueError: raise RuntimeError('ROOT_ESCAPE')
 core,expected_records=expected_paths(routes); expected_all=expected_records|{'manifest.json'}
 actual=set()
 for base,dirs,files in os.walk(root,followlinks=False):
  for name in dirs+files:
   p=Path(base)/name; info=p.lstat()
   if stat.S_ISLNK(info.st_mode): raise RuntimeError(f'SYMLINK_OUTPUT:{p}')
   if name in dirs and not stat.S_ISDIR(info.st_mode): raise RuntimeError(f'SPECIAL_OUTPUT:{p}')
  for name in files:
   p=Path(base)/name; info=p.lstat()
   if not stat.S_ISREG(info.st_mode): raise RuntimeError(f'SPECIAL_OUTPUT:{p}')
   actual.add(p.relative_to(root).as_posix())
 if actual!=expected_all or len(actual)!=76: raise RuntimeError(f'EXACT_FILE_SET:{sorted(actual^expected_all)}')
 manifest,_=read_declared(root,'manifest.json',expected_all)
 exact_keys(manifest,{'schemaVersion','pendingExternalAuthorizationReview',*FALSE_FLAGS,'files','outputRootDigest'},'manifest');flags(manifest,'manifest')
 if manifest['schemaVersion']!='tidy.offenders-target-scoped-output-manifest/v1' or not digest(manifest['outputRootDigest']) or type(manifest['files']) is not list or len(manifest['files'])!=75: raise RuntimeError('MANIFEST_SCHEMA')
 manifest_paths=[]
 for record in manifest['files']: check_digest_record(record,'manifest-record');manifest_paths.append(record['path'])
 if set(manifest_paths)!=expected_records or len(set(manifest_paths))!=75 or manifest_paths!=sorted(manifest_paths): raise RuntimeError('MANIFEST_PATH_SET')
 records=[]
 for record in manifest['files']:
  file=safe_regular(root,record['path'],'manifest-file',expected_records);raw=file.read_bytes()
  if len(raw)!=record['byteLength'] or sha(raw)!=record['sha256']: raise RuntimeError(f'MANIFEST_DIGEST:{record["path"]}')
  records.append(record)
 if root_digest(records)!=manifest['outputRootDigest']: raise RuntimeError('OUTPUT_ROOT_DIGEST')
 declared=set(manifest_paths)
 summary,_=read_declared(root,'summary.json',declared);exact_keys(summary,SUMMARY_KEYS,'summary');flags(summary,'summary')
 if summary['schemaVersion']!='tidy.offenders-target-scoped-summary/v1' or summary['authorizationPath']!=AUTH_DEFAULT.as_posix() or summary['authorizationDigest']!=expected_auth: raise RuntimeError('SUMMARY_SCHEMA')
 for key,value in EXPECTED_SUMMARY.items():
  if summary[key]!=value: raise RuntimeError(f'SUMMARY:{key}')
 routing,_=read_declared(root,'routing-manifest.json',declared);exact_keys(routing,{'schemaVersion','pendingExternalAuthorizationReview',*FALSE_FLAGS,'summary','members'},'routing');flags(routing,'routing')
 if routing['schemaVersion']!='tidy.offenders-target-scoped-routing-manifest/v1' or routing['summary']!={'members':18,'rows':28681} or type(routing['members']) is not list or len(routing['members'])!=18: raise RuntimeError('ROUTING_SCHEMA')
 attestation,_=read_declared(root,'reproduction-attestation.json',declared);exact_keys(attestation,{'schemaVersion','pendingExternalAuthorizationReview',*FALSE_FLAGS,'pairedRunPolicy','payloadRootDigest','members','rows','providerCalls'},'attestation');flags(attestation,'attestation')
 if attestation['schemaVersion']!='tidy.offenders-target-scoped-reproduction-attestation/v1' or attestation['pairedRunPolicy']!='fresh-run-a-and-run-b-must-be-byte-identical' or attestation['members']!=18 or attestation['rows']!=28681 or attestation['providerCalls']!=0: raise RuntimeError('ATTESTATION_SCHEMA')
 core_records=[record for record in records if record['path'] in core]
 if len(core_records)!=72: raise RuntimeError('CORE_RECORD_COUNT')
 payload=root_digest(core_records)
 if summary['payloadRootDigest']!=payload or attestation['payloadRootDigest']!=payload: raise RuntimeError('PAYLOAD_ROOT_DIGEST')
 routed={}
 for item in routing['members']:
  exact_keys(item,{'familyId','year','releaseId','status','rows','mapDigest','trustedEnvelopeDigest','executionDigest','memberPath'},'route')
  ident=(item['familyId'],item['year'])
  if ident in routed: raise RuntimeError('DUPLICATE_ROUTE')
  if ident not in routes or item['memberPath']!=f'members/{ident[0]}/{ident[1]}.json' or item['status']!='target-scoped-v02-engineering' or item['releaseId']!=routes[ident]['releaseId'] or item['rows']!=routes[ident]['rows']: raise RuntimeError('ROUTE_IDENTITY')
  if not all(digest(item[k]) for k in ('mapDigest','trustedEnvelopeDigest','executionDigest')): raise RuntimeError('ROUTE_DIGEST')
  routed[ident]=item
 if set(routed)!=set(routes): raise RuntimeError('ROUTE_SET')
 totals={k:0 for k in ('rows','partitions','targetSets','sourceUniverses','attachmentChoices','vectors','resolutionOperations','changedFields')}; max_resources={'mapBytes':0,'mapNodes':0,'envelopeBytes':0,'envelopeNodes':0,'executionBytes':0,'executionNodes':0,'operations':0}
 partition_digest='sha256:f8b15cff3272b53b014f6072150b9d97370badf1a0469b197f75f6554a74e627'
 for ident in sorted(routes):
  family,year=ident; mrel=f'members/{family}/{year}.json'; member,mraw=read_declared(root,mrel,declared)
  exact_keys(member,MEMBER_KEYS,f'member:{ident}');flags(member,f'member:{ident}')
  route,own,rr=routes[ident],custody[ident],routed[ident]
  if member['schemaVersion']!='tidy.offenders-target-scoped-member/v1' or member['familyId']!=family or member['year']!=year or member['releaseId']!=route['releaseId'] or member['rows']!=route['rows'] or member['providerCalls']!=0: raise RuntimeError(f'MEMBER_IDENTITY:{ident}')
  for key in ('sourceWorkbookPath','sourceWorkbookDigest','executionWorkbookPath','executionWorkbookDigest'):
   if member[key]!=own[key]: raise RuntimeError(f'CUSTODY:{ident}:{key}')
  if not digest(member['sourceExecutionEquivalenceDigest']): raise RuntimeError(f'EQUIVALENCE:{ident}')
  expected_refs={'mapPath':f'maps/{family}/{year}.json','envelopePath':f'envelopes/{family}/{year}.json','executionPath':f'executions/{family}/{year}.json'}
  for key,expected in expected_refs.items():
   if member[key]!=expected: raise RuntimeError(f'ARTIFACT_PATH:{ident}:{key}')
   safe_regular(root,member[key],key,declared)
  oracle=member['oracleProof']; exact_keys(oracle,{'partitionManifestDigest','assignments','attachmentEquality','typedLabelEquality','orderedAddressEquality','ambiguities','gaps','overlaps','changedFields','unauthorizedChanges'},'oracle-proof')
  if oracle['partitionManifestDigest']!=partition_digest or oracle['assignments']!=member['rows'] or oracle['attachmentEquality'] is not True or oracle['typedLabelEquality'] is not True or oracle['orderedAddressEquality'] is not True or any(oracle[k]!=0 for k in ('ambiguities','gaps','overlaps','unauthorizedChanges')): raise RuntimeError(f'ORACLE_PROOF:{ident}')
  key_audit=member['keyAudit']; exact_keys(key_audit,{'exactDuplicateExcess','normalizedDuplicateExcess','canonicalDuplicateExcess','aliasCollisions'},'key-audit')
  if any(key_audit.values()): raise RuntimeError(f'KEY_AUDIT:{ident}')
  resources=member['resources']; exact_keys(resources,{'map','envelope','execution'},'resources')
  artifacts={}
  for kind in ('map','envelope','execution'):
   res=resources[kind];exact_keys(res,{'bytes','nodes','digest'},f'resource:{kind}')
   rel=expected_refs[{'map':'mapPath','envelope':'envelopePath','execution':'executionPath'}[kind]]; obj,raw=read_declared(root,rel,declared)
   if res['bytes']!=len(raw) or res['nodes']!=json_nodes(obj) or res['digest']!=sha(raw): raise RuntimeError(f'RESOURCE:{ident}:{kind}')
   artifacts[kind]=(obj,raw)
  map_obj,map_raw=artifacts['map']; env,env_raw=artifacts['envelope']; execution,execution_raw=artifacts['execution']
  exact_keys(map_obj,{'version','catalog','source','logicalTable','targetSets','sourceUniverses','attachments','vectors','targets'},'map')
  if map_obj['version']!='target-scoped-semantic-map-v1' or len(map_obj['targets'])!=member['rows'] or len({x['address'] for x in map_obj['targets']})!=member['rows'] or len(map_obj['targetSets'])!=member['targetSets'] or len(map_obj['sourceUniverses'])!=member['sourceUniverses'] or len(map_obj['attachments'])!=member['attachmentChoices'] or len(map_obj['vectors'])!=member['vectors']: raise RuntimeError(f'MAP_CLOSURE:{ident}')
  exact_keys(env,{'version','compilerVersion','source','map','catalog','sheetProof','recipe','recipeDigest','targetManifest','attachmentManifest','logicalExecutionProof','envelopeDigest'},'envelope')
  if env['version']!='target-scoped-compilation-envelope/v02' or env['compilerVersion']!='target-scoped-recipe-v02-compiler-v1' or not digest(env['envelopeDigest']) or env['targetManifest']['count']!=member['rows'] or env['attachmentManifest']['count']!=member['rows']*len(member['dimensions']) or env['attachmentManifest']['operations']!=member['resolutionOperations'] or env['logicalExecutionProof']['rows']!=member['rows']: raise RuntimeError(f'ENVELOPE_CLOSURE:{ident}')
  recipe=env['recipe']; universes={x['id']:x['addresses'] for x in recipe['sourceUniverses']}; attachments={x['id']:x for x in recipe['attachments']};vectors={x['id']:x for x in recipe['vectors']}; operations=0
  for target in recipe['targets']:
   vector=vectors[target['vectorId']]
   for aid in vector['attachmentIds']: operations+=len(universes[attachments[aid]['universeId']])+1
  if operations!=member['resolutionOperations']: raise RuntimeError(f'OPERATION_TOTAL:{ident}')
  exact_keys(execution,{'version','recipeVersion','source','table','warnings','providerCalls','acceptanceAuthority','trainingEligibility'},'execution')
  if execution['version']!='target-scoped-logical-execution/v02' or execution['recipeVersion']!='TargetScopedRecipeV02' or execution['providerCalls']!=0 or execution['warnings']!=[] or execution['acceptanceAuthority'] is not False or execution['trainingEligibility'] is not False or len(execution['table']['rows'])!=member['rows'] or len(execution['table']['trace'])!=member['rows']: raise RuntimeError(f'EXECUTION_CLOSURE:{ident}')
  if map_obj['source']['workbookDigest']!=member['executionWorkbookDigest'] or map_obj['source']['physicalSheet']!=member['physicalSheet'] or env['source']!=map_obj['source'] or execution['source']!=map_obj['source']: raise RuntimeError(f'SOURCE_CONTEXT:{ident}')
  if sha(map_raw)!=member['mapDigest'] or sha(execution_raw)!=member['executionDigest'] or env['envelopeDigest']!=member['trustedEnvelopeDigest'] or rr['mapDigest']!=member['mapDigest'] or rr['executionDigest']!=member['executionDigest'] or rr['trustedEnvelopeDigest']!=member['trustedEnvelopeDigest']: raise RuntimeError(f'ARTIFACT_DIGEST:{ident}')
  for key in ('rows','partitions','targetSets','sourceUniverses','attachmentChoices','vectors','resolutionOperations'): totals[key]+=member[key]
  totals['changedFields']+=oracle['changedFields']
  max_resources['mapBytes']=max(max_resources['mapBytes'],resources['map']['bytes']);max_resources['mapNodes']=max(max_resources['mapNodes'],resources['map']['nodes']);max_resources['envelopeBytes']=max(max_resources['envelopeBytes'],resources['envelope']['bytes']);max_resources['envelopeNodes']=max(max_resources['envelopeNodes'],resources['envelope']['nodes']);max_resources['executionBytes']=max(max_resources['executionBytes'],resources['execution']['bytes']);max_resources['executionNodes']=max(max_resources['executionNodes'],resources['execution']['nodes']);max_resources['operations']=max(max_resources['operations'],member['resolutionOperations'])
 expected_totals={'rows':28681,'partitions':262,'targetSets':262,'sourceUniverses':2206,'attachmentChoices':8131,'vectors':28681,'resolutionOperations':1160748,'changedFields':2739}
 if totals!=expected_totals or summary['maxResources']!=max_resources: raise RuntimeError(f'AGGREGATE_TOTALS:{totals}:{max_resources}')
 return {'root':root,'records':records,'payloadRootDigest':payload,'outputRootDigest':manifest['outputRootDigest']}

def safe_delete_temp(path:Path):
 allowed=(REPO/ALLOWED).resolve(strict=True);info=path.lstat()
 if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise RuntimeError('UNSAFE_VERIFY_TEMP')
 real=path.resolve(strict=True);real.relative_to(allowed)
 token=str(uuid.uuid4());lock=Path(str(real)+'.lock');marker=real/'.c2-verification-cleanup-owner.json'
 try:
  lock.mkdir();(lock/'owner.json').write_text(json.dumps({'version':'c2-verification-cleanup-owner/v1','token':token,'path':str(real)})+'\n');marker.write_text(json.dumps({'version':'c2-verification-cleanup-owner/v1','token':token,'path':str(real)})+'\n')
  lock_owner=json.loads((lock/'owner.json').read_text());path_owner=json.loads(marker.read_text())
  if lock_owner!=path_owner or lock_owner!={'version':'c2-verification-cleanup-owner/v1','token':token,'path':str(real)}:raise RuntimeError('VERIFY_CLEANUP_NOT_OWNED')
  shutil.rmtree(real)
 finally:
  if lock.exists():
   owner=json.loads((lock/'owner.json').read_text()) if (lock/'owner.json').is_file() else None
   if owner!={'version':'c2-verification-cleanup-owner/v1','token':token,'path':str(real)}:raise RuntimeError('VERIFY_CLEANUP_LOCK_LOST')
   shutil.rmtree(lock)

def semantic_replay(candidate,compare_candidate,auth_path,auth_digest,toolchain):
 if os.environ.get('C2_VERIFIER_REPLAY_TOKEN'): raise RuntimeError('RECURSIVE_VERIFY_REPLAY')
 token=str(uuid.uuid4()); rel=f'{ALLOWED.as_posix()}/run-verify-{os.getpid()}-{token}'
 temp=REPO/rel
 forbidden=[candidate['root']]+([compare_candidate['root']] if compare_candidate else [])
 if temp.exists() or any(temp.resolve()==path for path in forbidden): raise RuntimeError('VERIFY_TEMP_COLLISION')
 env=dict(os.environ);env['C2_VERIFIER_REPLAY_TOKEN']=token
 command=[toolchain['node']['executablePath'],toolchain['tsxEntrypoint']['path'],'scripts/build-offenders-remaining-target-scoped.ts','--verification-replay','--verification-token',token,'--out',rel,'--authorization',auth_path.as_posix(),'--authorization-digest',auth_digest]
 for path in forbidden: command += ['--verification-forbid-root',str(path)]
 try:
  completed=subprocess.run(command,cwd=REPO,env=env,capture_output=True,text=True,timeout=1800)
  if completed.returncode: raise RuntimeError(f'SEMANTIC_REPLAY_BUILD:{completed.stderr[-2000:]}')
  regenerated={p.relative_to(temp).as_posix():p.read_bytes() for p in sorted(temp.rglob('*')) if p.is_file()}
  original={p.relative_to(candidate['root']).as_posix():p.read_bytes() for p in sorted(candidate['root'].rglob('*')) if p.is_file()}
  if set(regenerated)!=set(original) or any(regenerated[k]!=original[k] for k in regenerated): raise RuntimeError('SEMANTIC_REPLAY_BYTE_MISMATCH')
 finally:
  if temp.exists(): safe_delete_temp(temp)
  if temp.exists(): raise RuntimeError('VERIFY_TEMP_CLEANUP')

ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--authorization-digest',required=True);ap.add_argument('--authorization',default=AUTH_DEFAULT.as_posix());ap.add_argument('--compare');a=ap.parse_args()
if os.environ.get('C2_VERIFIER_REPLAY_TOKEN'): raise RuntimeError('RECURSIVE_VERIFY_REPLAY')
auth_path=Path(canonical_rel(a.authorization,'authorization-argument'));_,_,routes,custody,toolchain=authority(auth_path,a.authorization_digest)
one=validate(a.root,a.authorization_digest,routes,custody)
two=None
if a.compare:
 two=validate(a.compare,a.authorization_digest,routes,custody)
 if two['root']==one['root']: raise RuntimeError('COMPARE_ROOT_COLLISION')
semantic_replay(one,two,auth_path,a.authorization_digest,toolchain)
if two:
 original={p.relative_to(one['root']).as_posix():p.read_bytes() for p in sorted(one['root'].rglob('*')) if p.is_file()};compared={p.relative_to(two['root']).as_posix():p.read_bytes() for p in sorted(two['root'].rglob('*')) if p.is_file()}
 if original!=compared: raise RuntimeError('RUN_BYTE_DRIFT')
print(json.dumps({'root':str(one['root']),'comparedRoot':str(two['root']) if two else None,'byteIdentical':bool(two),'semanticReplay':True,'files':76,'members':18,'rows':28681,'payloadRootDigest':one['payloadRootDigest'],'outputRootDigest':one['outputRootDigest']},indent=2,sort_keys=True))

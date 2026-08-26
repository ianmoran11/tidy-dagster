#!/usr/bin/env python3
"""Strict independent verifier for non-authoritative Offenders all-170 replay."""
from __future__ import annotations
import argparse,json,os,shutil,sys,uuid
from pathlib import Path
if sys.flags.isolated!=1:raise RuntimeError('ISOLATED_PYTHON_REQUIRED')
_SCRIPT_DIR=Path(__file__).resolve(strict=True).parent
if _SCRIPT_DIR!=(Path.cwd().resolve(strict=True)/'scripts') or _SCRIPT_DIR.is_symlink():raise RuntimeError('SCRIPT_DIRECTORY_IDENTITY')
sys.path.insert(0,str(_SCRIPT_DIR))
from offenders_all_replay_safety import *

AUTH_DEFAULT='fixtures/product-prototype/offenders-remaining-all-replay-authorization-v1.json'
CAPABILITY='fixtures/product-prototype/offenders-remaining-capability-routing-pin-v1.json'
PARTITION='.product-prototype/offenders-remaining-phase1/source-partition-canary/run-a-remediated/partition-manifest.json'
PLAN='fixtures/product-prototype/offenders-remaining-semantic-map-plan-v1.json'
EXPECTED={'members':170,'families':47,'rows':224997,'v1Routes':14,'b1Routes':138,'c2Routes':18,'b2aRows':196316,'c2Rows':28681,'changedFields':52367,'b2aChangedFields':49628,'c2ChangedFields':2739,'providerCalls':0}
BASE_KEYS={'pendingExternalAuthorizationReview',*FALSE_FLAGS}
def is_digest(v):return type(v) is str and len(v)==71 and v.startswith('sha256:')
def unique(items,keyer,count,label):
 if type(items) is not list or len(items)!=count:raise RuntimeError(f'{label}_COUNT')
 out={}
 for x in items:
  k=keyer(x)
  if k in out:raise RuntimeError(f'{label}_DUPLICATE')
  out[k]=x
 return out
def direct_root(value,label):return direct_allowed_path(value,label)
def authorization(path,digest):
 p=safe_repo_file(path,'authorization');raw=p.read_bytes()
 if sha(raw)!=digest:raise RuntimeError('AUTHORIZATION_DIGEST')
 a=json.loads(raw);exact_keys(a,{'schemaVersion','authorizedForAllReplayEngineering','pendingExternalAuthorizationReview',*FALSE_FLAGS,'authorizationBoundary','phasePins','toolchainClosure','runtimeSourceClosure','inputs','expectedScope','reviewStatus'},'authorization');flags(a,'authorization')
 if a['schemaVersion']!='tidy.offenders-all-replay-authorization/v1' or a['authorizedForAllReplayEngineering'] is not True or a['reviewStatus']!='pending-independent-review' or a['expectedScope']!=EXPECTED:raise RuntimeError('AUTHORIZATION_SCHEMA')
 pins={}
 for item in a['inputs']:
  exact_keys(item,{'path','byteLength','sha256'},'input-pin')
  if item['path'] in pins:raise RuntimeError('DUPLICATE_INPUT_PIN')
  pins[item['path']]=item;p=safe_repo_file(item['path'],'authorized-input');b=p.read_bytes()
  if len(b)!=item['byteLength'] or sha(b)!=item['sha256']:raise RuntimeError(f'PIN_DRIFT:{item["path"]}')
 for item in a['runtimeSourceClosure']:
  if pins.get(item['path'])!=item:raise RuntimeError('RUNTIME_INPUT_PIN_MISMATCH')
 toolchain=verify_toolchain_closure(a['toolchainClosure'],pins,True)
 def pinned(rel):
  pin=pins.get(rel)
  if not pin:raise RuntimeError(f'UNPINNED:{rel}')
  return json.loads(safe_repo_file(rel,'pinned-json').read_bytes())
 cap=pinned(CAPABILITY);part=pinned(PARTITION);plan=pinned(PLAN)
 routes=unique(cap['members'],lambda x:(x['familyId'],x['year']),170,'CAPABILITY')
 phase=a['phasePins'];b2_manifest=pinned(phase['b2a']['approvedRoutedManifest']['path']);c2_manifest=pinned(phase['c2']['approvedManifest']['path'])
 if phase['b2a']['approvedRoutedManifest']!=pins.get(phase['b2a']['approvedRoutedManifest']['path']) or phase['c2']['approvedManifest']!=pins.get(phase['c2']['approvedManifest']['path']):raise RuntimeError('PHASE_MANIFEST_PIN')
 execution_records={}
 for ident,route in routes.items():
  if route['status']=='target-scoped-required':
   rel=f'executions/{ident[0]}/{ident[1]}.json';record=next((x for x in c2_manifest['files'] if x['path']==rel),None);key=('c2',ident)
  else:
   rel=f'{ident[0]}/{ident[1]}.json';record=next((x for x in b2_manifest['outputFiles'] if x['path']==rel),None);key=('b2a',ident)
  if not record or key in execution_records:raise RuntimeError(f'PHASE_EXECUTION_AUTHORITY:{ident}')
  exact_keys(record,{'path','byteLength','sha256'},'phase-execution-record');execution_records[key]=record
 if len(execution_records)!=170:raise RuntimeError('PHASE_EXECUTION_AUTHORITY_COUNT')
 custody=unique(part['members'],lambda x:(x['familyId'],x['year']),170,'PARTITION')
 plan_rows=[]
 for fam in plan['families']:
  for m in fam['members']:
   t=m['semanticMap']['table'];plan_rows.append({'familyId':fam['familyId'],'year':int(m['releaseId'][:4]),'releaseId':m['releaseId'],'dimensions':[x['name'] for x in t['dimensions']]})
 dimensions=unique(plan_rows,lambda x:(x['familyId'],x['year']),170,'PLAN')
 if set(routes)!=set(custody) or set(routes)!=set(dimensions):raise RuntimeError('AUTHORITY_IDENTITY_SET')
 return a,toolchain,routes,custody,dimensions,execution_records

def validate(value,digest,authority):
 auth,toolchain,routes,custody,dimensions,execution_records=authority;root=direct_root(value,'root')
 expected_members={f'members/{f}/{y}.json' for f,y in routes};expected_payload=expected_members|{'summary.json','routing-manifest.json','reproduction-attestation.json'};expected_all=expected_payload|{'manifest.json'}
 actual=set(walk_regular(root))
 if actual!=expected_all or len(actual)!=174:raise RuntimeError('EXACT_FILE_SET')
 manifest=json.loads((root/'manifest.json').read_bytes());exact_keys(manifest,{'schemaVersion',*BASE_KEYS,'authorizationDigest','files','payloadRootDigest','outputRootDigest','summary'},'manifest');flags(manifest,'manifest')
 if manifest['schemaVersion']!='tidy.offenders-all-replay-manifest/v1' or manifest['authorizationDigest']!=digest or manifest['summary']!={'members':170,'rows':224997,'changedFields':52367,'providerCalls':0}:raise RuntimeError('MANIFEST_SCHEMA')
 records=[file_record(root/rel,rel) for rel in sorted(expected_payload)]
 if manifest['files']!=records or manifest['outputRootDigest']!=root_digest(records):raise RuntimeError('OUTPUT_ROOT')
 member_records=[x for x in records if x['path'].startswith('members/')]
 if manifest['payloadRootDigest']!=root_digest(member_records):raise RuntimeError('PAYLOAD_ROOT')
 summary=json.loads((root/'summary.json').read_bytes());routing=json.loads((root/'routing-manifest.json').read_bytes());attest=json.loads((root/'reproduction-attestation.json').read_bytes())
 exact_keys(summary,{'schemaVersion',*BASE_KEYS,'authorizationDigest','members','families','rows','v1Routes','b1Routes','c2Routes','b2aRows','c2Rows','changedFields','b2aChangedFields','c2ChangedFields','changeClasses','providerCalls','warnings','ambiguities','gaps','overlaps','keyDefects','payloadRootDigest','regeneratedPhaseRoots'},'summary');flags(summary,'summary')
 summary_expected={**EXPECTED,'warnings':0,'ambiguities':0,'gaps':0,'overlaps':0,'keyDefects':0,'payloadRootDigest':manifest['payloadRootDigest']}
 if summary['schemaVersion']!='tidy.offenders-all-replay-summary/v1' or summary['authorizationDigest']!=digest or any(summary[k]!=v for k,v in summary_expected.items()):raise RuntimeError('SUMMARY_SCHEMA')
 expected_roots={'b2aBuild':auth['phasePins']['b2a']['approvedBuildRoot'],'b2aRouted':auth['phasePins']['b2a']['approvedRoutedRoot'],'c2':auth['phasePins']['c2']['approvedRoot']}
 if summary['regeneratedPhaseRoots']!=expected_roots or summary['changeClasses']!={'b2a':{'exact-source-null-repair':24084,'bootstrap-method-semantic-correction':25544},'c2':{'exact-source-null-repair':2739}}:raise RuntimeError('SUMMARY_PROOFS')
 exact_keys(routing,{'schemaVersion',*BASE_KEYS,'summary','members'},'routing');flags(routing,'routing')
 if routing['schemaVersion']!='tidy.offenders-all-replay-routing/v1' or routing['summary']!={'members':170,'rows':224997} or len(routing['members'])!=170:raise RuntimeError('ROUTING_SCHEMA')
 exact_keys(attest,{'schemaVersion',*BASE_KEYS,'authorizationDigest','members','rows','changedFields','providerCalls','payloadRootDigest','semanticReplay','routeUnion'},'attestation');flags(attest,'attestation')
 if attest['schemaVersion']!='tidy.offenders-all-replay-attestation/v1' or attest['authorizationDigest']!=digest or attest['members']!=170 or attest['rows']!=224997 or attest['changedFields']!=52367 or attest['providerCalls']!=0 or attest['payloadRootDigest']!=manifest['payloadRootDigest'] or attest['semanticReplay'] is not True or attest['routeUnion']!={'v1':14,'b1':138,'c2':18}:raise RuntimeError('ATTESTATION_SCHEMA')
 seen=set();counts={'v1':0,'b1':0,'c2':0};rows=changes=0;families=set();phase_rows={'b2a':0,'c2':0}
 for route in routing['members']:
  exact_keys(route,{'familyId','year','releaseId','route','mode','rows','memberPath','rowTraceDigest','changedFields'},'route');ident=(route['familyId'],route['year']);cap=routes.get(ident)
  if ident in seen or not cap or route['memberPath']!=f'members/{ident[0]}/{ident[1]}.json':raise RuntimeError('ROUTE_IDENTITY')
  expected_route='c2' if cap['status']=='target-scoped-required' else ('v1' if cap['mode']=='semantic-map-v1' else 'b1');expected_mode='target-scoped-recipe-v02' if expected_route=='c2' else cap['mode']
  if route['releaseId']!=cap['releaseId'] or route['rows']!=cap['rows'] or route['route']!=expected_route or route['mode']!=expected_mode or not is_digest(route['rowTraceDigest']) or type(route['changedFields']) is not int:raise RuntimeError('ROUTE_CAPABILITY_BINDING')
  seen.add(ident);families.add(ident[0]);counts[route['route']]+=1;rows+=route['rows'];changes+=route['changedFields'];phase_rows['c2' if route['route']=='c2' else 'b2a']+=route['rows']
  m=json.loads((root/route['memberPath']).read_bytes());exact_keys(m,{'schemaVersion',*BASE_KEYS,'familyId','year','releaseId','route','mode','rows','dimensions','providerCalls','warnings','sourceWorkbookPath','sourceWorkbookDigest','executionWorkbookPath','executionWorkbookDigest','physicalSheet','sourceExecutionPath','sourceExecutionDigest','orderedAddressDigest','rowTraceDigest','changeSetDigest','changedFields','oracleProof','keyAudit','resource'},'member');flags(m,'member');c=custody[ident];dims=dimensions[ident]
  expected_source=('c2/executions/' if expected_route=='c2' else 'b2a/')+f'{ident[0]}/{ident[1]}.json'
  if m['schemaVersion']!='tidy.offenders-all-replay-member/v1' or (m['familyId'],m['year'])!=ident or m['releaseId']!=cap['releaseId'] or m['route']!=expected_route or m['mode']!=expected_mode or m['rows']!=cap['rows'] or m['dimensions']!=dims['dimensions'] or m['sourceWorkbookPath']!=c['sourceWorkbookPath'] or m['sourceWorkbookDigest']!=c['sourceWorkbookDigest'] or m['executionWorkbookPath']!=c['executionWorkbookPath'] or m['executionWorkbookDigest']!=c['executionWorkbookDigest'] or m['physicalSheet']!=c['physicalSheetIdentity'] or m['sourceExecutionPath']!=expected_source:raise RuntimeError('MEMBER_AUTHORITY_BINDING')
  exact_keys(m['oracleProof'],{'addressEquality','valueEquality','attachmentEquality','typedLabelEquality','dataTypeEquality','custodyEquality','ledgerProvenanceEquality'},'oracle-proof');exact_keys(m['keyAudit'],{'exactDuplicateExcess','normalizedDuplicateExcess','canonicalDuplicateExcess','aliasCollisions'},'key-audit');exact_keys(m['resource'],{'sourceExecutionBytes','proofRows'},'resource')
  phase_record=execution_records[('c2' if expected_route=='c2' else 'b2a',ident)]
  if m['sourceExecutionDigest']!=phase_record['sha256'] or m['resource']['sourceExecutionBytes']!=phase_record['byteLength']:raise RuntimeError('MEMBER_SOURCE_EXECUTION_BINDING')
  if any(x is not True for x in m['oracleProof'].values()) or any(type(x) is not int or x!=0 for x in m['keyAudit'].values()) or m['resource']['proofRows']!=m['rows'] or any(not is_digest(m[k]) for k in ('sourceExecutionDigest','orderedAddressDigest','rowTraceDigest','changeSetDigest')) or m['rowTraceDigest']!=route['rowTraceDigest'] or m['changedFields']!=route['changedFields'] or m['providerCalls']!=0 or m['warnings']!=0:raise RuntimeError('MEMBER_PROOF_SCHEMA')
 if seen!=set(routes) or len(families)!=47 or counts!={'v1':14,'b1':138,'c2':18} or rows!=224997 or changes!=52367 or phase_rows!={'b2a':196316,'c2':28681}:raise RuntimeError('ROUTE_UNION')
 return {'root':root,'manifest':manifest}

def semantic(candidate,compare,auth_path,digest,toolchain):
 if os.environ.get('C3_VERIFIER_REPLAY_TOKEN'):raise RuntimeError('RECURSIVE_REPLAY')
 token=str(uuid.uuid4());rel=(ALLOWED/f'run-verify-{os.getpid()}-{token}').as_posix();temp=REPO/rel;forbidden=[candidate['root']]+([compare['root']] if compare else [])
 if lexists(temp) or any(temp.absolute()==x.absolute() for x in forbidden):raise RuntimeError('REPLAY_COLLISION')
 lease=VerifierLease(rel,token);env={'C3_VERIFIER_REPLAY_TOKEN':token};cmd=[toolchain['python'],'-I','scripts/replay-offenders-remaining-all.py','--verification-replay','--verification-token',token,'--out',rel,'--authorization',auth_path,'--authorization-digest',digest]
 for x in forbidden:cmd+=['--verification-forbid-root',str(x)]
 try:
  run_child(cmd,env,1800);lease.capture()
  regenerated={x:(temp/x).read_bytes() for x in walk_regular(temp)};original={x:(candidate['root']/x).read_bytes() for x in walk_regular(candidate['root'])}
  if regenerated!=original:raise RuntimeError('SEMANTIC_REPLAY_BYTE_MISMATCH')
 finally:
  lease.cleanup()

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--compare');ap.add_argument('--authorization',default=AUTH_DEFAULT);ap.add_argument('--authorization-digest',required=True);a=ap.parse_args()
 if os.environ.get('C3_VERIFIER_REPLAY_TOKEN'):raise RuntimeError('RECURSIVE_REPLAY')
 au=authorization(a.authorization,a.authorization_digest);one=validate(a.root,a.authorization_digest,au);two=validate(a.compare,a.authorization_digest,au) if a.compare else None
 if two and two['root']==one['root']:raise RuntimeError('COMPARE_ROOT_COLLISION')
 semantic(one,two,a.authorization,a.authorization_digest,au[1])
 if two and {x:(one['root']/x).read_bytes() for x in walk_regular(one['root'])}!={x:(two['root']/x).read_bytes() for x in walk_regular(two['root'])}:raise RuntimeError('RUN_BYTE_DRIFT')
 print(json.dumps({'semanticReplay':True,'byteIdentical':bool(two),'files':174,'members':170,'rows':224997,'changedFields':52367,'payloadRootDigest':one['manifest']['payloadRootDigest'],'outputRootDigest':one['manifest']['outputRootDigest']},indent=2,sort_keys=True))
if __name__=='__main__':main()

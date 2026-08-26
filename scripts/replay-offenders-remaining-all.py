#!/usr/bin/env python3
"""Provider-free common replay for all 170 remaining Offenders worksheets."""
from __future__ import annotations
import argparse, hashlib, json, math, os, re, shutil, stat, subprocess, sys, uuid
from pathlib import Path, PurePosixPath
if sys.flags.isolated!=1:raise RuntimeError('ISOLATED_PYTHON_REQUIRED')
_SCRIPT_DIR=Path(__file__).resolve(strict=True).parent
if _SCRIPT_DIR!=(Path.cwd().resolve(strict=True)/'scripts') or _SCRIPT_DIR.is_symlink():raise RuntimeError('SCRIPT_DIRECTORY_IDENTITY')
sys.path.insert(0,str(_SCRIPT_DIR))
from offenders_all_replay_safety import *

AUTH_DEFAULT='fixtures/product-prototype/offenders-remaining-all-replay-authorization-v1.json'
B2_AUTH='fixtures/product-prototype/offenders-remaining-semantic-generation-authorization-v1.json'
CAPABILITY='fixtures/product-prototype/offenders-remaining-capability-routing-pin-v1.json'
C2_AUTH='fixtures/product-prototype/offenders-remaining-target-scoped-generation-authorization-v1.json'
ORACLE='.product-prototype/offenders-remaining-phase1/source-partition-canary/run-a-remediated'
PLAN='fixtures/product-prototype/offenders-remaining-semantic-map-plan-v1.json'
COLLISION=f'{ORACLE}/collision-ledger.json';DISCREPANCY=f'{ORACLE}/discrepancy-ledger.json';PARTITION=f'{ORACLE}/partition-manifest.json';TEMPORARY=f'{ORACLE}/temporary-maps-recipes.json'
B2_BOUNDARY=Path('.product-prototype/offenders-remaining-phase1/multi-panel-b2a')
C2_BOUNDARY=Path('.product-prototype/offenders-remaining-phase1/target-scoped-c2')
EXPECTED={'members':170,'families':47,'rows':224997,'v1Routes':14,'b1Routes':138,'c2Routes':18,'b2aRows':196316,'c2Rows':28681,'changedFields':52367,'b2aChangedFields':49628,'c2ChangedFields':2739,'providerCalls':0}

def exact(a,b):
 if type(a) is not type(b):return False
 if isinstance(a,float) and a==0 and b==0:return math.copysign(1,a)==math.copysign(1,b)
 return a==b
def pos(a):
 m=re.fullmatch(r'R(\d+)C(\d+)',a)
 if not m:raise RuntimeError(f'BAD_ADDRESS:{a}')
 return int(m.group(1)),int(m.group(2))
def digest_file(path):return sha(path.read_bytes())
def run(cmd,env=None,timeout=1800):return run_child(cmd,env,timeout)
def is_int(v):return type(v) is int and v>=0
def pin_index(auth):
 pins={}
 for p in auth['inputs']:
  exact_keys(p,{'path','byteLength','sha256'},'input-pin')
  if p['path'] in pins:raise RuntimeError(f'DUPLICATE_PIN:{p["path"]}')
  pins[p['path']]=p
 return pins
def verify_pin(pin):
 path=safe_repo_file(pin['path'],'pinned-input');raw=path.read_bytes()
 if len(raw)!=pin['byteLength'] or sha(raw)!=pin['sha256']:raise RuntimeError(f'PIN_DRIFT:{pin["path"]}')
def load_pinned(pins,path,max_bytes=500_000_000):
 pin=pins.get(path)
 if not pin:raise RuntimeError(f'UNPINNED:{path}')
 verify_pin(pin);return load_json(safe_repo_file(path,'pinned-json'),max_bytes)[0]
def verify_toolchain(auth,pins):return verify_toolchain_closure(auth['toolchainClosure'],pins,True)
def auth_boundary(path,digest):
 raw=safe_repo_file(path,'authorization').read_bytes()
 if sha(raw)!=digest:raise RuntimeError('EXTERNAL_ALL_REPLAY_AUTHORIZATION_PIN_MISMATCH')
 auth=json.loads(raw);exact_keys(auth,{'schemaVersion','authorizedForAllReplayEngineering','pendingExternalAuthorizationReview',*FALSE_FLAGS,'authorizationBoundary','phasePins','toolchainClosure','runtimeSourceClosure','inputs','expectedScope','reviewStatus'},'authorization')
 flags(auth,'authorization')
 if auth['schemaVersion']!='tidy.offenders-all-replay-authorization/v1' or auth['authorizedForAllReplayEngineering'] is not True or auth['reviewStatus']!='pending-independent-review' or auth['expectedScope']!=EXPECTED:raise RuntimeError('AUTHORIZATION_SCHEMA')
 pins=pin_index(auth)
 for p in auth['runtimeSourceClosure']:
  if pins.get(p['path'])!=p:raise RuntimeError('RUNTIME_INPUT_PIN_MISMATCH')
 for p in auth['inputs']:verify_pin(p)
 toolchain=verify_toolchain(auth,pins)
 return auth,pins,toolchain

def phase_regenerate(auth,pins,toolchain,token,forbidden,leases):
 node=toolchain['node'];tsx=toolchain['tsx'];py=toolchain['python'];phase=auth['phasePins']
 b2maps=B2_BOUNDARY/f'run-c3-{token}-maps';b2routed=B2_BOUNDARY/f'run-c3-{token}-routed';c2=C2_BOUNDARY/f'run-verify-c3-{token}'
 try:
  for path,kind in ((b2maps,'b2a-maps'),(b2routed,'b2a-routed'),(c2,'c2')):
   lease=PhaseLease(path,token,kind);leases.append(lease)
  run([node,tsx,'scripts/build-offenders-remaining-multi-panel.ts','--out',b2maps.as_posix(),'--authorization-digest',phase['b2a']['authorizationDigest'],'--capability-pin-digest',phase['b2a']['capabilityDigest']])
  cap=load_pinned(pins,CAPABILITY);routing=cap['routingManifest']
  run([node,tsx,'scripts/compile-offenders-remaining.ts','--routing-manifest',(b2maps/'routing-manifest.json').as_posix(),'--routing-digest',routing['sha256'],'--capability-pin',CAPABILITY,'--capability-pin-digest',phase['b2a']['capabilityDigest'],'--authorization',B2_AUTH,'--authorization-digest',phase['b2a']['authorizationDigest'],'--maps-root',(b2maps/'maps').as_posix(),'--members-root',(b2maps/'members').as_posix(),'--out',b2routed.as_posix()])
  run([py,'-I','scripts/verify-offenders-remaining-phased.py','--run-a',b2maps.as_posix(),'--run-b',phase['b2a']['approvedBuildPath'],'--routed',b2routed.as_posix(),'--authorization',B2_AUTH,'--authorization-digest',phase['b2a']['authorizationDigest'],'--capability-pin',CAPABILITY,'--capability-pin-digest',phase['b2a']['capabilityDigest']])
  bm=load_json(b2maps/'manifest.json')[0];br=load_json(b2routed/'manifest.json')[0]
  if bm['outputRootDigest']!=phase['b2a']['approvedBuildRoot'] or br['outputRootDigest']!=phase['b2a']['approvedRoutedRoot']:raise RuntimeError('B2A_REGENERATED_ROOT_DRIFT')
  env={'C2_VERIFIER_REPLAY_TOKEN':token}
  command=[node,tsx,'scripts/build-offenders-remaining-target-scoped.ts','--verification-replay','--verification-token',token,'--out',c2.as_posix(),'--authorization',C2_AUTH,'--authorization-digest',phase['c2']['authorizationDigest']]
  for p in forbidden:command += ['--verification-forbid-root',str(p)]
  run(command,env=env)
  run([py,'-I','scripts/verify-offenders-remaining-target-scoped.py','--root',c2.as_posix(),'--compare',phase['c2']['approvedPath'],'--authorization',C2_AUTH,'--authorization-digest',phase['c2']['authorizationDigest']])
  cm=load_json(c2/'manifest.json')[0]
  if cm['outputRootDigest']!=phase['c2']['approvedRoot']:raise RuntimeError('C2_REGENERATED_ROOT_DRIFT')
  roots={'b2aBuild':bm['outputRootDigest'],'b2aRouted':br['outputRootDigest'],'c2':cm['outputRootDigest']}
  return b2maps,b2routed,c2,roots
 except BaseException as error:
  try:cleanup_phase_leases(leases)
  except BaseException as cleanup:raise RuntimeError(f'PHASE_FAILURE_AND_CLEANUP:{error}:{cleanup}') from error
  raise

def unique_index(items,keyer,expected,label):
 if type(items) is not list or len(items)!=expected:raise RuntimeError(f'{label}_RAW_COUNT:{len(items) if type(items) is list else -1}')
 out={}
 for item in items:
  key=keyer(item)
  if key in out:raise RuntimeError(f'{label}_DUPLICATE:{key}')
  out[key]=item
 return out
def plan_index(plan):
 rows=[]
 for fam in plan['families']:
  for m in fam['members']:
   year=int(m['releaseId'][:4]);sm=m['semanticMap'];table=sm['table'];rows.append({'familyId':fam['familyId'],'year':year,'raw':m,'dimensions':[x['name'] for x in table['dimensions']],'valueName':table['values']['name'],'sheet':m['physicalSheetName'],'sourcePath':m['sourcePath'],'sourceDigest':m['sourceDigest'],'executionPath':m['executionPath'],'executionDigest':m['executionDigest']})
 return unique_index(rows,lambda x:(x['familyId'],x['year']),170,'PLAN')
def temporary_index(bundle):return unique_index(bundle['members'],lambda x:(x['familyId'],x['year']),170,'TEMPORARY')
def validate_ledger_row(d,route,o,old,s,candidate_segments):
 expected_keys={'familyId','year','releaseId','sourceWorkbookPath','sourceWorkbookDigest','executionWorkbookPath','executionWorkbookDigest','physicalSheetIdentity','dimension','valueAddress','oldValue','oldSourceAddress','newRawLabel','selectedSourceAddress','candidateRegionId','candidateSegments','direction','changeClass','authorizationStatus','oldProvenance','newProvenance','sourceEvidence'}
 exact_keys(d,expected_keys,'discrepancy-row')
 address=d['valueAddress'];selected=s['sourceAddress'];old_source=old.get(d['dimension']+'_source') if old else None
 expected_old={'releaseId':route['releaseId'],'sourceWorkbookDigest':o['sourceWorkbookDigest'],'executionWorkbookDigest':o['executionWorkbookDigest'],'sheet':o['physicalSheetIdentity'],'valueAddress':address,'dimensionSourceAddress':old_source}
 expected_new={'releaseId':route['releaseId'],'sourceWorkbookDigest':o['sourceWorkbookDigest'],'executionWorkbookDigest':o['executionWorkbookDigest'],'sheet':o['physicalSheetIdentity'],'valueAddress':address,'dimensionSourceAddress':selected}
 checks=[d['releaseId']==route['releaseId'],d['sourceWorkbookPath']==o['sourceWorkbookPath'],d['sourceWorkbookDigest']==o['sourceWorkbookDigest'],d['executionWorkbookPath']==o['executionWorkbookPath'],d['executionWorkbookDigest']==o['executionWorkbookDigest'],d['physicalSheetIdentity']==o['physicalSheetIdentity'],d['candidateRegionId']==s['candidateRegionId'],d['candidateSegments']==candidate_segments,d['authorizationStatus']==('canary-evidence-only' if d['changeClass']=='exact-source-null-repair' else 'pending-independent-authorization'),d['oldProvenance']==expected_old,d['newProvenance']==expected_new,d['sourceEvidence']==f'{selected}={stable(s["exactTypedRawLabel"]["value"])}']
 if not all(checks):raise RuntimeError(f'LEDGER_PROVENANCE:{d["familyId"]}:{d["year"]}:{address}:{d["dimension"]}')
def assignment_index(member):
 out={}
 for part in sorted(member['partitions'],key=lambda x:x['partitionOrder']):
  for a in part['valueAssignments']:
   if a['valueAddress'] in out:raise RuntimeError('DUPLICATE_ORACLE_TARGET')
   out[a['valueAddress']]=a
 return out
def semantic_alias(value):
 raw=re.sub(r'\s+',' ',str(value).strip());raw=re.sub(r'(?:\s*\([a-z]\))+$','',raw,flags=re.I);return raw.upper().strip()
def canonical_code(value):
 raw=semantic_alias(value);slug=re.sub(r'[^A-Z0-9]+','_',raw).strip('_') or 'VALUE';return slug[:80]+'_'+hashlib.sha256(raw.encode()).hexdigest()[:8]
def norm(v):return re.sub(r'\s+',' ',v.strip()) if isinstance(v,str) else v
def collision_audit(rows,dims,reference,value_name):
 result={}
 for mode,keyer in [('exact',lambda v:(type(v).__name__,stable(v))),('normalized',lambda v:(type(norm(v)).__name__,stable(norm(v)))),('canonical',lambda v:canonical_code(v))]:
  seen=set();excess=0
  for row in rows:
   key=stable([reference,reference,*[keyer(row[d]) for d in dims],'published-value'])
   if key in seen:excess+=1
   seen.add(key)
  result[mode+'DuplicateExcess']=excess
 aliases=0
 for d in dims:
  by={}
  for row in rows:by.setdefault(canonical_code(row[d]),set()).add(semantic_alias(row[d]))
  aliases+=sum(len(v)>1 for v in by.values())
 result['aliasCollisions']=aliases
 return result

def normalize_execution(route,b2routed,c2root):
 family,year=route['familyId'],route['year']
 if route['status']=='target-scoped-required':
  path=c2root/f'executions/{family}/{year}.json';doc=load_json(path)[0];rows=doc['table']['rows'];trace=doc['table']['trace']
  return 'target-scoped-recipe-v02',path,doc,rows,{x['target']['address']:x for x in trace},doc['table']['sheet']
 path=b2routed/f'{family}/{year}.json';doc=load_json(path)[0];rows=doc['logicalExecution']['logicalTable']['rows'];trace=doc['logicalExecution']['logicalTable']['trace']['value_cells']
 return doc['mode'],path,doc,rows,{x['source']['address']:x for x in trace},doc['logicalExecution']['logicalTable']['sheet']
def type_data(value):
 if isinstance(value,bool) or value is None:return 'invalid'
 if isinstance(value,(int,float)):return 'numeric'
 if isinstance(value,str):return 'string'
 return 'invalid'

def compose(auth,pins,b2maps,b2routed,c2root,phase_roots,leases,out:Path,injected=None):
 capability=load_pinned(pins,CAPABILITY);partition=load_pinned(pins,PARTITION);plan=plan_index(load_pinned(pins,PLAN));ledger=load_pinned(pins,DISCREPANCY);collisions=load_pinned(pins,COLLISION);temporary=temporary_index(load_pinned(pins,TEMPORARY))
 route_index=unique_index(capability['members'],lambda x:(x['familyId'],x['year']),170,'CAPABILITY');routes=list(route_index.values());route_ids=set(route_index)
 oracle=unique_index(partition['members'],lambda x:(x['familyId'],x['year']),170,'PARTITION');collision=unique_index(collisions['members'],lambda x:(x['familyId'],x['year']),170,'COLLISION')
 if set(oracle)!=route_ids or set(collision)!=route_ids or set(plan)!=route_ids or set(temporary)!=route_ids:raise RuntimeError('SEMANTIC_IDENTITY_SET_CLOSURE')
 discrepancy=unique_index(ledger['rows'],lambda x:(x['familyId'],x['year'],x['valueAddress'],x['dimension']),52367,'LEDGER')
 observed=set();members=[];totals={'rows':0,'changed':0,'providerCalls':0,'warnings':0,'ambiguities':0,'gaps':0,'overlaps':0,'keyDefects':0};route_counts={'semantic-map-v1':0,'semantic-table-map-v2-recipe-v1':0,'target-scoped-recipe-v02':0};phase_changes={'b2a':0,'c2':0};phase_rows={'b2a':0,'c2':0};phase_classes={'b2a':{},'c2':{}};families=set();catalogs={}
 for route in sorted(routes,key=lambda x:(x['familyId'],x['year'])):
  ident=(route['familyId'],route['year']);o=oracle[ident];p=plan[ident];families.add(ident[0])
  if route['releaseId']!=o['releaseId'] or route['releaseId']!=p['raw']['releaseId'] or route['rows']!=o['expectedCount']:raise RuntimeError(f'RELEASE_IDENTITY:{ident}')
  mode,source_path,doc,rows,trace_by,sheet=normalize_execution(route,b2routed,c2root);route_counts[mode]=route_counts.get(mode,0)+1
  provider=doc.get('providerCalls',doc.get('logicalExecution',{}).get('providerCalls'));warnings=doc.get('warnings',[])
  if type(provider) is not int or provider<0 or type(warnings) is not list:raise RuntimeError(f'EXECUTION_COUNTER_SCHEMA:{ident}')
  totals['providerCalls']+=provider;totals['warnings']+=len(warnings)
  scope='c2' if route['status']=='target-scoped-required' else 'b2a';phase_rows[scope]+=len(rows)
  assignments=assignment_index(o);expected=set(o['expectedValueAddresses']);by={x['_source']['address']:x for x in rows}
  gaps=len(expected-set(by));overlaps=len(rows)-len(by);totals['gaps']+=gaps;totals['overlaps']+=overlaps
  if len(rows)!=route['rows'] or set(by)!=expected or len(by)!=len(rows) or len(trace_by)!=len(rows) or set(trace_by)!=expected:raise RuntimeError(f'TARGET_COVERAGE:{ident}')
  if sheet!=o['physicalSheetIdentity'] or p['sheet']!=sheet or p['sourcePath']!=o['sourceWorkbookPath'] or p['sourceDigest']!=o['sourceWorkbookDigest'] or p['executionPath']!=o['executionWorkbookPath'] or p['executionDigest']!=o['executionWorkbookDigest']:raise RuntimeError(f'SHEET_CUSTODY_IDENTITY:{ident}')
  temp=temporary[ident];catalog=load_pinned(pins,temp['catalogPath']);candidates=unique_index(catalog['catalog']['candidates'],lambda x:x['id'],len(catalog['catalog']['candidates']),f'CATALOG:{ident}')
  catalogs[ident]=candidates
  baseline_path=f'.product-prototype/offenders-remaining-phase1/direct/{route["familyId"]}/{route["year"]}.json';baseline=load_pinned(pins,baseline_path);base_rows=baseline['execution']['tables'][0]['rows'];base={x['_source']['address']:x for x in base_rows}
  cohort_path=f'fixtures/product-prototype/recorded-crime-offenders-{route["familyId"]}.json';cohort=load_pinned(pins,cohort_path);entry=next((x for x in cohort['workbooks'] if x['year']==route['year']),None)
  if not entry or entry['releaseId']!=route['releaseId'] or entry['path']!=o['executionWorkbookPath'] or entry['contentDigest']!=o['executionWorkbookDigest'] or entry['sheet']!=sheet:raise RuntimeError(f'CUSTODY:{ident}')
  dims=p['dimensions'];value_name=p['valueName'];proof=[];member_changes=[]
  for address in sorted(expected,key=pos):
   row=by[address];old=base.get(address);a=assignments[address];tr=trace_by[address]
   if not old or not exact(row[value_name],old[value_name]) or row['_source']['sheet']!=sheet:raise RuntimeError(f'PUBLISHED_VALUE:{ident}:{address}')
   if route['status']=='target-scoped-required':
    if tr['target']['address']!=address or not exact(tr['value'],row[value_name]) or tr['target']['data_type']!=type_data(row[value_name]):raise RuntimeError(f'C2_TARGET_TRACE:{ident}:{address}')
    headers={x['dimensionName']:x for x in tr['attachments']}
   else:
    if tr['source']['address']!=address or not exact(tr['value'],row[value_name]):raise RuntimeError(f'B2_TARGET_TRACE:{ident}:{address}')
    headers={x['header']:x for x in tr['headers']}
   dimproof=[]
   for dim in dims:
    s=a['dimensionSources'][dim];h=headers.get(dim);expected_type='numeric' if s['exactTypedRawLabel']['type']=='number' else s['exactTypedRawLabel']['type']
    if h:totals['ambiguities']+=int(h.get('ambiguous') is True)
    if row[dim] is None or isinstance(row[dim],bool) or not exact(row[dim],s['exactTypedRawLabel']['value']) or row.get(dim+'_source')!=s['sourceAddress']:raise RuntimeError(f'ORACLE_DIMENSION:{ident}:{address}:{dim}')
    if not h or h['direction']!=s['direction'] or h['selected']!=s['sourceAddress'] or h['candidates']!=[s['sourceAddress']] or not exact(h['value'],s['exactTypedRawLabel']['value']) or h.get('missing') is not False or h.get('ambiguous') is not False:raise RuntimeError(f'ORACLE_TRACE:{ident}:{address}:{dim}')
    if route['status']=='target-scoped-required' and h['source']['data_type']!=expected_type:raise RuntimeError(f'ORACLE_DATA_TYPE:{ident}:{address}:{dim}')
    if type_data(row[dim])!=expected_type:raise RuntimeError(f'TYPED_LABEL:{ident}:{address}:{dim}')
    if not exact(row[dim],old.get(dim)) or row.get(dim+'_source')!=(old.get(dim+'_source') if old.get(dim+'_source') is not None else None):
     key=(ident[0],ident[1],address,dim);d=discrepancy.get(key)
     if not d or not exact(old.get(dim),d['oldValue']) or (old.get(dim+'_source') if old.get(dim+'_source') is not None else None)!=(d['oldSourceAddress'] if d['oldSourceAddress'] is not None else None) or not exact(row[dim],d['newRawLabel']) or row[dim+'_source']!=d['selectedSourceAddress'] or s['direction']!=d['direction']:raise RuntimeError(f'UNAUTHORIZED_CHANGE:{key}')
     region=candidates.get(s['candidateRegionId'])
     if not region or not any(s['sourceAddress'] in part['sourcePartitions'].get(s['candidateRegionId'],[]) for part in temp['partitions']):raise RuntimeError(f'CANDIDATE_REGION_EVIDENCE:{key}')
     validate_ledger_row(d,route,o,old,s,region['segments'])
     observed.add(key);member_changes.append({'address':address,'dimension':dim,'class':d['changeClass'],'old':d['oldValue'],'new':d['newRawLabel'],'source':d['selectedSourceAddress'],'ledgerProvenanceDigest':sha(stable(d).encode())})
     scope='c2' if route['status']=='target-scoped-required' else 'b2a';phase_changes[scope]+=1;phase_classes[scope][d['changeClass']]=phase_classes[scope].get(d['changeClass'],0)+1
    dimproof.append({'dimension':dim,'value':row[dim],'source':s['sourceAddress'],'direction':s['direction'],'dataType':expected_type})
   proof.append({'address':address,'value':row[value_name],'valueDataType':type_data(row[value_name]),'dimensions':dimproof})
  audit=collision_audit(rows,dims,entry['referenceDate'],value_name);totals['keyDefects']+=sum(audit.values())
  if any(audit.values()):raise RuntimeError(f'KEY_DEFECT:{ident}:{audit}')
  expected_collision=collision[ident]
  if audit!={'exactDuplicateExcess':expected_collision['exact']['duplicateRowExcess'],'normalizedDuplicateExcess':expected_collision['normalized']['duplicateRowExcess'],'canonicalDuplicateExcess':expected_collision['canonical']['duplicateRowExcess'],'aliasCollisions':expected_collision['aliasCollisionCount']}:raise RuntimeError(f'COLLISION_LEDGER:{ident}')
  source_raw=source_path.read_bytes();route_kind='c2' if route['status']=='target-scoped-required' else ('v1' if mode=='semantic-map-v1' else 'b1')
  member={'schemaVersion':'tidy.offenders-all-replay-member/v1','pendingExternalAuthorizationReview':True,**{k:False for k in FALSE_FLAGS},'familyId':ident[0],'year':ident[1],'releaseId':route['releaseId'],'route':route_kind,'mode':mode,'rows':len(rows),'dimensions':dims,'providerCalls':provider,'warnings':len(warnings),'sourceWorkbookPath':o['sourceWorkbookPath'],'sourceWorkbookDigest':o['sourceWorkbookDigest'],'executionWorkbookPath':o['executionWorkbookPath'],'executionWorkbookDigest':o['executionWorkbookDigest'],'physicalSheet':sheet,'sourceExecutionPath':(f'c2/executions/{ident[0]}/{ident[1]}.json' if route_kind=='c2' else f'b2a/{ident[0]}/{ident[1]}.json'),'sourceExecutionDigest':sha(source_raw),'orderedAddressDigest':sha(stable(sorted(expected,key=pos)).encode()),'rowTraceDigest':sha(stable(proof).encode()),'changeSetDigest':sha(stable(member_changes).encode()),'changedFields':len(member_changes),'oracleProof':{'addressEquality':True,'valueEquality':True,'attachmentEquality':True,'typedLabelEquality':True,'dataTypeEquality':True,'custodyEquality':True,'ledgerProvenanceEquality':True},'keyAudit':audit,'resource':{'sourceExecutionBytes':len(source_raw),'proofRows':len(proof)}}
  members.append(member);totals['rows']+=len(rows);totals['changed']+=len(member_changes)
 if observed!=set(discrepancy):raise RuntimeError(f'LEDGER_SET_CLOSURE:{len(observed)}')
 expected_routes={'semantic-map-v1':14,'semantic-table-map-v2-recipe-v1':138,'target-scoped-recipe-v02':18}
 if route_counts!=expected_routes or len(families)!=47 or totals['rows']!=224997 or totals['changed']!=52367 or phase_rows!={'b2a':196316,'c2':28681} or phase_changes!={'b2a':49628,'c2':2739} or any(totals[k] for k in ('providerCalls','warnings','ambiguities','gaps','overlaps','keyDefects')):raise RuntimeError(f'AGGREGATE_CLOSURE:{route_counts}:{len(families)}:{totals}:{phase_rows}:{phase_changes}')
 expected_classes={'b2a':{'exact-source-null-repair':24084,'bootstrap-method-semantic-correction':25544},'c2':{'exact-source-null-repair':2739}}
 if phase_classes!=expected_classes or phase_roots!={'b2aBuild':auth['phasePins']['b2a']['approvedBuildRoot'],'b2aRouted':auth['phasePins']['b2a']['approvedRoutedRoot'],'c2':auth['phasePins']['c2']['approvedRoot']}:raise RuntimeError(f'CHANGE_OR_PHASE_ROOT_CLOSURE:{phase_classes}:{phase_roots}')
 (out/'members').mkdir(parents=True,exist_ok=True)
 for m in members:
  path=out/f'members/{m["familyId"]}/{m["year"]}.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(pretty(m))
 core=[f'members/{m["familyId"]}/{m["year"]}.json' for m in members];core_records=[file_record(out/x,x) for x in sorted(core)];payload=root_digest(core_records)
 base={'pendingExternalAuthorizationReview':True,**{k:False for k in FALSE_FLAGS}}
 summary={'schemaVersion':'tidy.offenders-all-replay-summary/v1',**base,'authorizationDigest':auth['_digest'],'members':len(members),'families':len(families),'rows':totals['rows'],'v1Routes':route_counts['semantic-map-v1'],'b1Routes':route_counts['semantic-table-map-v2-recipe-v1'],'c2Routes':route_counts['target-scoped-recipe-v02'],'b2aRows':phase_rows['b2a'],'c2Rows':phase_rows['c2'],'changedFields':totals['changed'],'b2aChangedFields':phase_changes['b2a'],'c2ChangedFields':phase_changes['c2'],'changeClasses':phase_classes,'providerCalls':totals['providerCalls'],'warnings':totals['warnings'],'ambiguities':totals['ambiguities'],'gaps':totals['gaps'],'overlaps':totals['overlaps'],'keyDefects':totals['keyDefects'],'payloadRootDigest':payload,'regeneratedPhaseRoots':phase_roots}
 routing={'schemaVersion':'tidy.offenders-all-replay-routing/v1',**base,'summary':{'members':len(members),'rows':totals['rows']},'members':[{'familyId':m['familyId'],'year':m['year'],'releaseId':m['releaseId'],'route':m['route'],'mode':m['mode'],'rows':m['rows'],'memberPath':f'members/{m["familyId"]}/{m["year"]}.json','rowTraceDigest':m['rowTraceDigest'],'changedFields':m['changedFields']} for m in members]}
 attest={'schemaVersion':'tidy.offenders-all-replay-attestation/v1',**base,'authorizationDigest':auth['_digest'],'members':len(members),'rows':totals['rows'],'changedFields':totals['changed'],'providerCalls':totals['providerCalls'],'payloadRootDigest':payload,'semanticReplay':True,'routeUnion':{'v1':route_counts['semantic-map-v1'],'b1':route_counts['semantic-table-map-v2-recipe-v1'],'c2':route_counts['target-scoped-recipe-v02']}}
 for name,obj in [('summary.json',summary),('routing-manifest.json',routing),('reproduction-attestation.json',attest)]: (out/name).write_bytes(pretty(obj))
 if injected=='after-writes':raise RuntimeError('INJECTED_FAILURE:after-writes')
 records=[file_record(out/x,x) for x in walk_regular(out) if x!=OWNER];manifest={'schemaVersion':'tidy.offenders-all-replay-manifest/v1',**base,'authorizationDigest':auth['_digest'],'files':records,'payloadRootDigest':payload,'outputRootDigest':root_digest(records),'summary':{'members':len(members),'rows':totals['rows'],'changedFields':totals['changed'],'providerCalls':totals['providerCalls']}}
 (out/'manifest.json').write_bytes(pretty(manifest));return summary|{'outputRootDigest':manifest['outputRootDigest'],'files':len(records)+1}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--authorization',default=AUTH_DEFAULT);ap.add_argument('--authorization-digest',required=True);ap.add_argument('--verification-replay',action='store_true');ap.add_argument('--verification-token');ap.add_argument('--verification-forbid-root',action='append',default=[]);ap.add_argument('--inject-failure');a=ap.parse_args()
 name=PurePosixPath(a.out).name
 if a.verification_replay:
  if not a.verification_token or os.environ.get('C3_VERIFIER_REPLAY_TOKEN')!=a.verification_token or not name.startswith('run-verify-') or PurePosixPath(a.out).parent!=ALLOWED or any(Path(x).absolute()==Path(a.out).absolute() for x in a.verification_forbid_root):raise RuntimeError('INVALID_VERIFICATION_REPLAY_HANDSHAKE')
 elif name.startswith('run-verify-') or a.verification_token or a.verification_forbid_root or os.environ.get('C3_VERIFIER_REPLAY_TOKEN'):raise RuntimeError('VERIFICATION_REPLAY_MODE_REQUIRED')
 auth,pins,toolchain=auth_boundary(a.authorization,a.authorization_digest);auth['_digest']=a.authorization_digest
 tx=Transaction(a.out,a.inject_failure,a.verification_token if a.verification_replay else None);token=str(uuid.uuid4());phases=None;leases=[]
 try:
  phases=phase_regenerate(auth,pins,toolchain,token,[Path(a.out).absolute(),*[Path(x).absolute() for x in a.verification_forbid_root]],leases)
  result=compose(auth,pins,*phases,leases,tx.temp,a.inject_failure);tx.commit();print(json.dumps(result,indent=2,sort_keys=True))
 except BaseException:
  if not tx.committed and lexists(tx.lock):tx.abort()
  raise
 finally:
  cleanup_phase_leases(leases)

if __name__=='__main__':main()

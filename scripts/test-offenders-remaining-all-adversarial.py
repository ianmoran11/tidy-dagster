#!/usr/bin/env python3
"""Checked adversarial matrix for the non-authoritative all-170 replay."""
from __future__ import annotations
import copy,hashlib,importlib.util,json,os,shutil,signal,stat,subprocess,sys,tempfile,time
from pathlib import Path
if sys.flags.isolated!=1:raise RuntimeError('ISOLATED_PYTHON_REQUIRED')
_SCRIPT_DIR=Path(__file__).resolve(strict=True).parent
if _SCRIPT_DIR!=(Path.cwd().resolve(strict=True)/'scripts') or _SCRIPT_DIR.is_symlink():raise RuntimeError('SCRIPT_DIRECTORY_IDENTITY')
sys.path.insert(0,str(_SCRIPT_DIR))
import offenders_all_replay_safety as safety
ROOT=Path('.product-prototype/offenders-remaining-phase1/all-170-replay');A=ROOT/'run-a';B=ROOT/'run-b';AUTH=Path('fixtures/product-prototype/offenders-remaining-all-replay-authorization-v1.json')
def sha(b):return 'sha256:'+hashlib.sha256(b).hexdigest()
def stable(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def load(p):return json.loads(p.read_text())
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n')
def auth_digest(path=AUTH):return sha(path.read_bytes())
def python(path=AUTH):return load(path)['toolchainClosure']['python']['executablePath']
def command(root,compare=None,auth=AUTH,digest=None,env=None):
 cmd=[python(auth),'-I','scripts/verify-offenders-remaining-all.py','--root',root.as_posix(),'--authorization',auth.as_posix(),'--authorization-digest',digest or auth_digest(auth)]
 if compare:cmd+=['--compare',compare.as_posix()]
 return subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=1800)
def records(root,paths):
 out=[]
 for rel in sorted(paths):
  raw=(root/rel).read_bytes();out.append({'path':rel,'byteLength':len(raw),'sha256':sha(raw)})
 return out
def rehash(root):
 members=[p.relative_to(root).as_posix() for p in (root/'members').rglob('*.json')];payload=sha(stable(records(root,members)).encode())
 s=load(root/'summary.json');s['payloadRootDigest']=payload;write(root/'summary.json',s);a=load(root/'reproduction-attestation.json');a['payloadRootDigest']=payload;write(root/'reproduction-attestation.json',a)
 paths=[p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='manifest.json'];rec=records(root,paths);m=load(root/'manifest.json');m['files']=rec;m['payloadRootDigest']=payload;m['outputRootDigest']=sha(stable(rec).encode());write(root/'manifest.json',m)
def reject(label,mutate,token=None,pair=False):
 x=ROOT/f'run-adversarial-{label}-a';y=ROOT/f'run-adversarial-{label}-b';shutil.rmtree(x,ignore_errors=True);shutil.rmtree(y,ignore_errors=True);shutil.copytree(A,x);mutate(x);rehash(x)
 if pair:shutil.copytree(x,y)
 r=command(x,y if pair else None)
 if r.returncode==0 or (token and token not in r.stderr):raise RuntimeError(f'ADVERSARIAL_ACCEPTED:{label}:{r.stderr[-600:]}')
 shutil.rmtree(x,ignore_errors=True);shutil.rmtree(y,ignore_errors=True);print(label,'rejected')

# Exact-list and provenance helpers reject collapse/mutation without phase execution.
spec=importlib.util.spec_from_file_location('c3replay','scripts/replay-offenders-remaining-all.py');replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
ledger=load(Path(replay.DISCREPANCY))['rows']
try:replay.unique_index(ledger+[ledger[0]],lambda x:(x['familyId'],x['year'],x['valueAddress'],x['dimension']),52367,'LEDGER');raise RuntimeError('LEDGER_DUPLICATE_ACCEPTED')
except RuntimeError as e:
 if 'LEDGER_RAW_COUNT' not in str(e):raise
# Build one exact provenance witness, then mutate every provenance group.
d=ledger[0];part=load(Path(replay.PARTITION));o=next(x for x in part['members'] if (x['familyId'],x['year'])==(d['familyId'],d['year']));assignment=next(a for p in o['partitions'] for a in p['valueAssignments'] if a['valueAddress']==d['valueAddress']);source=assignment['dimensionSources'][d['dimension']];cap=load(Path(replay.CAPABILITY));route=next(x for x in cap['members'] if (x['familyId'],x['year'])==(d['familyId'],d['year']));baseline=load(Path(f'.product-prototype/offenders-remaining-phase1/direct/{d["familyId"]}/{d["year"]}.json'));old=next(x for x in baseline['execution']['tables'][0]['rows'] if x['_source']['address']==d['valueAddress']);temp=load(Path(replay.TEMPORARY));tm=next(x for x in temp['members'] if (x['familyId'],x['year'])==(d['familyId'],d['year']));catalog=load(Path(tm['catalogPath']))['catalog'];segments=next(x['segments'] for x in catalog['candidates'] if x['id']==d['candidateRegionId']);replay.validate_ledger_row(d,route,o,old,source,segments)
for field in ('releaseId','sourceWorkbookDigest','executionWorkbookPath','physicalSheetIdentity','authorizationStatus','sourceEvidence','oldProvenance','newProvenance','candidateSegments'):
 bad=copy.deepcopy(d);bad[field]=('forged' if field not in ('oldProvenance','newProvenance','candidateSegments') else ({'forged':True} if field!='candidateSegments' else ['R1C1:R1C1']))
 try:replay.validate_ledger_row(bad,route,o,old,source,segments);raise RuntimeError(f'LEDGER_PROVENANCE_ACCEPTED:{field}')
 except RuntimeError as e:
  if 'LEDGER_PROVENANCE' not in str(e):raise
print('ledger duplicate/provenance rejected')

# Filesystem transaction boundary and ownership.
outside=Path(tempfile.mkdtemp(prefix='c3-outside-'));link=ROOT/'run-adversarial-link';link.unlink(missing_ok=True);link.symlink_to(outside,target_is_directory=True)
try:safety.Transaction(link.as_posix());raise RuntimeError('OUTPUT_SYMLINK_ACCEPTED')
except RuntimeError:pass
link.unlink();shutil.rmtree(outside)
fifo=ROOT/'run-adversarial-fifo';fifo.unlink(missing_ok=True);os.mkfifo(fifo)
try:safety.Transaction(fifo.as_posix());raise RuntimeError('OUTPUT_SPECIAL_ACCEPTED')
except RuntimeError:pass
fifo.unlink()
path=ROOT/'run-adversarial-transaction';shutil.rmtree(path,ignore_errors=True);path.mkdir();(path/'prior').write_text('prior')
t1=safety.Transaction(path.as_posix())
try:safety.Transaction(path.as_posix());raise RuntimeError('CONCURRENT_ACCEPTED')
except RuntimeError as e:
 if 'TRANSACTION_LOCKED' not in str(e):raise
t1.abort()
for mode in ('before-swap','after-swap'):
 t=safety.Transaction(path.as_posix(),mode);(t.temp/'new').write_text('new')
 try:t.commit();raise RuntimeError(f'{mode}_ACCEPTED')
 except RuntimeError:pass
 if (path/'prior').read_text()!='prior':raise RuntimeError(f'{mode}_ROLLBACK')
t=safety.Transaction(path.as_posix(),'cleanup-failure');(t.temp/'new').write_text('new')
try:t.commit();raise RuntimeError('CLEANUP_FAILURE_ACCEPTED')
except RuntimeError as e:
 if 'POST_COMMIT_CLEANUP_FAILURE' not in str(e):raise
if not (path/'new').is_file():raise RuntimeError('POST_COMMIT_FINAL_LOST')
t=safety.Transaction(path.as_posix());t.abort()
for p in ROOT.glob(path.name+'.backup-*'):raise RuntimeError('STALE_BACKUP_NOT_REAPED')
# Dangling owner marker is rejected without following.
shutil.rmtree(path);path.mkdir();(path/'prior').write_text('prior');(path/safety.OWNER).symlink_to('/tmp/c3-do-not-write')
t=safety.Transaction(path.as_posix());(t.temp/'new').write_text('new')
try:t.commit();raise RuntimeError('DANGLING_OWNER_ACCEPTED')
except RuntimeError:pass
if not (path/safety.OWNER).is_symlink():raise RuntimeError('DANGLING_OWNER_MUTATED')
t.abort() if safety.lexists(t.lock) else None
(path/safety.OWNER).unlink();shutil.rmtree(path)
# Constructor failures after lock and temp creation clean owned state.
orig=safety._secure_write
for fail_at in (1,2):
 count=[0]
 def fail(path,data):
  count[0]+=1
  if count[0]==fail_at:raise OSError('injected constructor write')
  return orig(path,data)
 safety._secure_write=fail
 p=ROOT/f'run-adversarial-constructor-{fail_at}'
 try:safety.Transaction(p.as_posix());raise RuntimeError('CONSTRUCTOR_FAILURE_ACCEPTED')
 except OSError:pass
 if safety.lexists(Path(str(p.absolute())+'.lock')) or any(ROOT.glob(p.name+'.temporary-*')):raise RuntimeError('CONSTRUCTOR_RESIDUE')
safety._secure_write=orig
# Signal rollback in a real child.
p=ROOT/'run-adversarial-signal';code="import sys,time;sys.path.insert(0,'scripts');from offenders_all_replay_safety import Transaction;t=Transaction('"+p.as_posix()+"');(t.temp/'x').write_text('x');print('ready',flush=True);time.sleep(60)"
proc=subprocess.Popen([python(),'-I','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True);proc.stdout.readline();os.kill(proc.pid,signal.SIGTERM);proc.wait(timeout=20)
if safety.lexists(p) or safety.lexists(Path(str(p.absolute())+'.lock')) or list(ROOT.glob(p.name+'.temporary-*')):raise RuntimeError('SIGNAL_RESIDUE')
# Phase lease refuses foreign ownership and then cleans exact owned namespace.
lease_token='11111111-1111-4111-8111-111111111111';phase=Path(f'.product-prototype/offenders-remaining-phase1/multi-panel-b2a/run-c3-{lease_token}-maps');lease=safety.PhaseLease(phase,lease_token,'b2a-maps');phase.mkdir();(phase/'x').write_text('x');data=load(lease.marker);data['token']='foreign';write(lease.marker,data)
try:lease.cleanup();raise RuntimeError('FOREIGN_PHASE_CLEANUP_ACCEPTED')
except RuntimeError:pass
data['token']=lease_token;write(lease.marker,data);lease.cleanup();print('transaction/signal/phase ownership passed')

# Root node_modules and allowed/phase ancestors are rejected lexically before writes.
old_repo,old_allowed=safety.REPO,safety.ALLOWED;old_phase=dict(safety.PHASE_BOUNDARIES);sandbox=Path(tempfile.mkdtemp(prefix='c3-boundary-')).resolve();outside=Path(tempfile.mkdtemp(prefix='c3-boundary-outside-')).resolve()
try:
 safety.REPO=sandbox;safety.ALLOWED=Path('.product-prototype/offenders-remaining-phase1/all-170-replay')
 (sandbox/'.product-prototype').mkdir();(sandbox/'.product-prototype/offenders-remaining-phase1').symlink_to(outside,target_is_directory=True)
 try:safety.direct_allowed_path('.product-prototype/offenders-remaining-phase1/all-170-replay/run-x');raise RuntimeError('ALLOWED_ANCESTOR_SYMLINK_ACCEPTED')
 except RuntimeError:pass
 if (outside/'all-170-replay').exists():raise RuntimeError('PREVALIDATION_WRITE_ESCAPED')
 (sandbox/'.product-prototype/offenders-remaining-phase1').unlink();(sandbox/'node_modules').symlink_to(outside,target_is_directory=True)
 try:safety._node_entries(sandbox/'node_modules');raise RuntimeError('NODE_ROOT_SYMLINK_ACCEPTED')
 except RuntimeError:pass
 (sandbox/'node_modules').unlink();(sandbox/'node_modules').mkdir();(outside/'escape.js').write_text('escape');(sandbox/'node_modules/escape.js').symlink_to(outside/'escape.js')
 try:safety._node_entries(sandbox/'node_modules');raise RuntimeError('NODE_LEAF_ESCAPE_ACCEPTED')
 except RuntimeError as e:
  if 'NODE_MODULES_SYMLINK_ESCAPE' not in str(e):raise
 shutil.rmtree(sandbox/'node_modules');phase_parent=sandbox/'.product-prototype/offenders-remaining-phase1/multi-panel-b2a';phase_parent.parent.mkdir(parents=True,exist_ok=True);phase_parent.symlink_to(outside,target_is_directory=True);safety.PHASE_BOUNDARIES['b2a-maps']=Path('.product-prototype/offenders-remaining-phase1/multi-panel-b2a')
 tok='22222222-2222-4222-8222-222222222222'
 try:safety.PhaseLease(phase_parent/f'run-c3-{tok}-maps',tok,'b2a-maps');raise RuntimeError('PHASE_ANCESTOR_SYMLINK_ACCEPTED')
 except RuntimeError:pass
 if list(outside.glob('*.c3-phase-owner.json')):raise RuntimeError('PHASE_PREVALIDATION_WRITE')
finally:
 safety.REPO=old_repo;safety.ALLOWED=old_allowed;safety.PHASE_BOUNDARIES.clear();safety.PHASE_BOUNDARIES.update(old_phase);shutil.rmtree(sandbox,ignore_errors=True);shutil.rmtree(outside,ignore_errors=True)

# Partial lease acquisition and multi-cleanup failures still clean every acquired lease.
tok='33333333-3333-4333-8333-333333333333';p1=Path(f'.product-prototype/offenders-remaining-phase1/multi-panel-b2a/run-c3-{tok}-maps');p2=Path(f'.product-prototype/offenders-remaining-phase1/multi-panel-b2a/run-c3-{tok}-routed');p2.mkdir();leases=[]
try:
 try:
  leases.append(safety.PhaseLease(p1,tok,'b2a-maps'));leases.append(safety.PhaseLease(p2,tok,'b2a-routed'));raise RuntimeError('PARTIAL_COLLISION_NOT_RAISED')
 except RuntimeError:safety.cleanup_phase_leases(leases)
 if safety.lexists(Path(str(p1.absolute())+safety.PHASE_OWNER_SUFFIX)):raise RuntimeError('PARTIAL_LEASE_MARKER_LEAK')
finally:shutil.rmtree(p2,ignore_errors=True)
tok='44444444-4444-4444-8444-444444444444';l1=safety.PhaseLease(Path(f'.product-prototype/offenders-remaining-phase1/multi-panel-b2a/run-c3-{tok}-maps'),tok,'b2a-maps');l2=safety.PhaseLease(Path(f'.product-prototype/offenders-remaining-phase1/multi-panel-b2a/run-c3-{tok}-routed'),tok,'b2a-routed');real_cleanup=l2.cleanup;l2.cleanup=lambda:(_ for _ in ()).throw(RuntimeError('injected cleanup'))
try:
 try:safety.cleanup_phase_leases([l1,l2]);raise RuntimeError('MULTI_CLEANUP_FAILURE_NOT_RAISED')
 except RuntimeError as e:
  if 'PHASE_CLEANUP_FAILURE' not in str(e):raise
 if safety.lexists(l1.marker):raise RuntimeError('OTHER_LEASE_NOT_CLEANED')
finally:real_cleanup()

# Integrated phase acquisition catches BaseException and timeout before returning.
class FakeLease:
 created=[];calls=0;fail_third=False
 def __init__(self,path,token,kind):
  FakeLease.calls+=1
  if FakeLease.fail_third and FakeLease.calls==3:raise SystemExit(143)
  self.kind=kind;self.marker=Path('/nonexistent-'+kind);self.cleaned=False;FakeLease.created.append(self)
 def cleanup(self):self.cleaned=True
old_lease,old_run=replay.PhaseLease,replay.run;replay.PhaseLease=FakeLease
try:
 FakeLease.created=[];FakeLease.calls=0;FakeLease.fail_third=True;leases=[]
 try:replay.phase_regenerate({'phasePins':{}},{},{'node':'n','tsx':'t','python':'p'},'55555555-5555-4555-8555-555555555555',[],leases);raise RuntimeError('INTEGRATED_SYSTEMEXIT_ACCEPTED')
 except SystemExit:pass
 if leases or not all(x.cleaned for x in FakeLease.created):raise RuntimeError('INTEGRATED_SYSTEMEXIT_LEAK')
 FakeLease.created=[];FakeLease.calls=0;FakeLease.fail_third=False;leases=[];replay.run=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('CHILD_TIMEOUT:injected'));phase={'b2a':{'authorizationDigest':'a','capabilityDigest':'c'}}
 try:replay.phase_regenerate({'phasePins':phase},{},{'node':'n','tsx':'t','python':'p'},'66666666-6666-4666-8666-666666666666',[],leases);raise RuntimeError('INTEGRATED_TIMEOUT_ACCEPTED')
 except RuntimeError as e:
  if 'CHILD_TIMEOUT' not in str(e):raise
 if leases or not all(x.cleaned for x in FakeLease.created):raise RuntimeError('INTEGRATED_TIMEOUT_LEAK')
finally:replay.PhaseLease=old_lease;replay.run=old_run

# Stale token/path mismatch is fatal and never deleted.
p=ROOT/'run-adversarial-stale';stale=Path(str(p.absolute())+'.temporary-77777777-7777-4777-8777-777777777777');stale.mkdir();safety._secure_write(stale/safety.OWNER,safety.pretty(safety.owner('88888888-8888-4888-8888-888888888888',p.absolute(),'temporary')))
try:safety.Transaction(p.as_posix());raise RuntimeError('STALE_TOKEN_MISMATCH_ACCEPTED')
except RuntimeError as e:
 if 'STALE_OWNER_MISMATCH' not in str(e):raise
if not stale.exists():raise RuntimeError('STALE_MISMATCH_DELETED')
shutil.rmtree(stale)

# Postcommit signal/cleanup interruption preserves the new final and releases ownership state.
for mode in ('postcommit-signal','cleanup-interrupt'):
 p=ROOT/f'run-adversarial-{mode}';p.mkdir();(p/'prior').write_text('prior');t=safety.Transaction(p.as_posix(),mode);(t.temp/'new').write_text('new')
 try:t.commit();raise RuntimeError(f'{mode}_NOT_INTERRUPTED')
 except SystemExit:pass
 if not (p/'new').is_file() or safety.lexists(Path(str(p.absolute())+'.lock')):raise RuntimeError(f'{mode}_POSTCOMMIT_STATE')
 for b in ROOT.glob(p.name+'.backup-*'):shutil.rmtree(b)
 shutil.rmtree(p)

# Verifier deletion needs its persistent lease and rejects root replacement.
tok='99999999-9999-4999-8999-999999999999';rel=(safety.ALLOWED/f'run-verify-{tok}').as_posix();vl=safety.VerifierLease(rel,tok);vl.path.mkdir();(vl.path/'x').write_text('x');vl.capture();original=Path(str(vl.path)+'.original');vl.path.rename(original);vl.path.mkdir()
try:vl.cleanup();raise RuntimeError('VERIFIER_REPLACEMENT_DELETED')
except RuntimeError as e:
 if 'VERIFIER_ROOT_REPLACED' not in str(e):raise
if not vl.path.exists():raise RuntimeError('VERIFIER_REPLACEMENT_LOST')
shutil.rmtree(vl.path);original.rename(vl.path);vl.cleanup()
tok='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';rel=(safety.ALLOWED/f'run-verify-{tok}').as_posix();vl=safety.VerifierLease(rel,tok);vl.path.mkdir();vl.capture();vl.cleanup()
print('extended transaction/node/phase/verifier ownership passed')

# Static verifier mutations.
def first_member(root):return sorted((root/'members').rglob('*.json'))[0]
def authority(root):d=load(root/'summary.json');d['acceptanceAuthority']=True;write(root/'summary.json',d)
reject('authority',authority,'AUTHORITY_FLAGS')
def extra(root):(root/'extra.json').write_text('{}\n')
reject('extra',extra,'EXACT_FILE_SET')
def route_mode(root):d=load(root/'routing-manifest.json');d['members'][0]['mode']='forged';write(root/'routing-manifest.json',d)
reject('route-mode',route_mode,'ROUTE_CAPABILITY_BINDING')
def route_rows(root):d=load(root/'routing-manifest.json');d['members'][0]['rows']+=1;write(root/'routing-manifest.json',d)
reject('route-rows',route_rows,'ROUTE_CAPABILITY_BINDING')
def custody(root):p=first_member(root);d=load(p);d['sourceWorkbookDigest']='sha256:'+'0'*64;write(p,d)
reject('custody',custody,'MEMBER_AUTHORITY_BINDING')
def resource(root):p=first_member(root);d=load(p);d['resource']['proofRows']+=1;write(p,d)
reject('resource',resource,'MEMBER_PROOF_SCHEMA')
def source_execution(root):p=first_member(root);d=load(p);d['sourceExecutionDigest']='sha256:'+'0'*64;d['resource']['sourceExecutionBytes']+=1;write(p,d)
reject('source-execution-pair',source_execution,'MEMBER_SOURCE_EXECUTION_BINDING',True)
def phase_root(root):d=load(root/'summary.json');d['regeneratedPhaseRoots']['c2']='sha256:'+'0'*64;write(root/'summary.json',d)
reject('phase-root',phase_root,'SUMMARY_PROOFS')
def oracle(root):p=first_member(root);d=load(p);d['oracleProof']['ledgerProvenanceEquality']=False;write(p,d)
reject('oracle',oracle,'MEMBER_PROOF_SCHEMA')
def key(root):p=first_member(root);d=load(p);d['keyAudit']['aliasCollisions']=1;write(p,d)
reject('key',key,'MEMBER_PROOF_SCHEMA')
def coherent(root):p=first_member(root);d=load(p);d['changeSetDigest']='sha256:'+'0'*64;write(p,d)
reject('coherent-pair',coherent,'SEMANTIC_REPLAY_BYTE_MISMATCH',True)
# Candidate/compare symlinks and exact collision.
link=ROOT/'run-adversarial-candidate-link';link.unlink(missing_ok=True);link.symlink_to('run-a',target_is_directory=True)
if command(link).returncode==0 or command(A,link).returncode==0:raise RuntimeError('VERIFIER_ROOT_SYMLINK_ACCEPTED')
link.unlink()
if command(A,A).returncode==0:raise RuntimeError('COMPARE_COLLISION_ACCEPTED')
env=dict(os.environ);env['C3_VERIFIER_REPLAY_TOKEN']='forged'
if command(A,env=env).returncode==0:raise RuntimeError('RECURSION_ACCEPTED')
# Isolated startup prevents real sitecustomize/PYTHONPATH/PYTHONHOME injection.
try:safety.sanitized_env({'NODE_OPTIONS':'--require=/tmp/forged'});raise RuntimeError('INJECTION_REINTRODUCTION_ACCEPTED')
except RuntimeError as e:
 if 'INJECTION_ENV_REINTRODUCED' not in str(e):raise
clean=safety.sanitized_env()
if any(k in clean for k in safety.INJECTION_ENV):raise RuntimeError('ENV_SANITIZATION')
inject=Path(tempfile.mkdtemp(prefix='c3-sitecustomize-'));sentinel=inject/'executed';(inject/'sitecustomize.py').write_text(f'from pathlib import Path\nPath({str(sentinel)!r}).write_text("executed")\n');env=dict(os.environ);env['PYTHONPATH']=str(inject);env['PYTHONHOME']='/definitely/forged'
r=subprocess.run([python(),'-I','scripts/verify-offenders-remaining-all.py','--help'],capture_output=True,text=True,env=env)
if r.returncode or sentinel.exists():raise RuntimeError(f'ISOLATED_STARTUP_INJECTION:{r.stderr[-500:]}')
r=subprocess.run([python(),'scripts/verify-offenders-remaining-all.py','--help'],capture_output=True,text=True,env=safety.sanitized_env())
if r.returncode==0 or 'ISOLATED_PYTHON_REQUIRED' not in r.stderr:raise RuntimeError('NONISOLATED_STARTUP_ACCEPTED')
shutil.rmtree(inject)
# Toolchain executable proof rejects coherent path/link drift before execution.
auth=load(AUTH);pins={x['path']:x for x in auth['inputs']};bad=copy.deepcopy(auth['toolchainClosure']);bad['node']['linkTarget']='forged'
try:safety.verify_toolchain_closure(bad,pins,True);raise RuntimeError('EXECUTABLE_DRIFT_ACCEPTED')
except RuntimeError as e:
 if 'TOOLCHAIN_EXECUTABLE_DRIFT' not in str(e):raise
if list(ROOT.glob('run-adversarial-*')) or list(ROOT.glob('*.lock')):raise RuntimeError('FINAL_RESIDUE')
print(json.dumps({'status':'passed','ledgerCases':10,'transactionCases':10,'staticVerifierCases':10,'semanticForgeryCases':1},sort_keys=True))

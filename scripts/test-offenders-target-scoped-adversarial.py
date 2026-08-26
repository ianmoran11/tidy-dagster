#!/usr/bin/env python3
"""Checked C2 adversarial verifier/replay and transaction matrix."""
import copy, hashlib, json, os, shutil, subprocess
from pathlib import Path

ROOT=Path('.product-prototype/offenders-remaining-phase1/target-scoped-c2');SOURCE=ROOT/'run-a';SOURCE_B=ROOT/'run-b';AUTH=Path('fixtures/product-prototype/offenders-remaining-target-scoped-generation-authorization-v1.json')
def sha(b):return 'sha256:'+hashlib.sha256(b).hexdigest()
def stable(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def write(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
def load(path):return json.loads(path.read_text())
def nodes(value):
 n=0;stack=[value]
 while stack:
  x=stack.pop();n+=1
  if type(x) is list:stack.extend(x)
  elif type(x) is dict:stack.extend(x.values())
 return n
def auth_digest():return sha(AUTH.read_bytes())
def toolchain(auth=AUTH):return load(auth)['toolchainClosure']
def builder_command(path,*extra,auth=AUTH):
 t=toolchain(auth);return [t['node']['executablePath'],t['tsxEntrypoint']['path'],'scripts/build-offenders-remaining-target-scoped.ts','--out',path.as_posix(),'--authorization',auth.as_posix(),'--authorization-digest',sha(auth.read_bytes()),*extra]
def command(root,compare=None,auth=AUTH,digest=None,env=None):
 py=toolchain(auth)['python']['executablePath'];cmd=[py,'scripts/verify-offenders-remaining-target-scoped.py','--root',root.as_posix(),'--authorization',auth.as_posix(),'--authorization-digest',digest or sha(auth.read_bytes())]
 if compare:cmd += ['--compare',compare.as_posix()]
 return subprocess.run(cmd,capture_output=True,text=True,env=env)
def records(root,paths):
 out=[]
 for rel in sorted(paths):
  raw=(root/rel).read_bytes();out.append({'path':rel,'byteLength':len(raw),'sha256':sha(raw)})
 return out
def rehash(root):
 core=[]
 for kind in ('maps','envelopes','executions','members'):
  core += [p.relative_to(root).as_posix() for p in (root/kind).rglob('*.json')]
 payload=sha(stable(records(root,core)).encode())
 summary=load(root/'summary.json');summary['payloadRootDigest']=payload;write(root/'summary.json',summary)
 attest=load(root/'reproduction-attestation.json');attest['payloadRootDigest']=payload;write(root/'reproduction-attestation.json',attest)
 paths=[p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='manifest.json']
 rec=records(root,paths);manifest=load(root/'manifest.json');manifest['files']=rec;manifest['outputRootDigest']=sha(stable(rec).encode());write(root/'manifest.json',manifest)
def first(root,kind):return sorted((root/kind).rglob('*.json'))[0]
def update_execution_refs(root,path):
 raw=path.read_bytes();d=sha(raw);rel=path.relative_to(root).as_posix();parts=rel.split('/');family,year=parts[1],int(parts[2][:-5]);mp=root/f'members/{family}/{year}.json';m=load(mp);m['executionDigest']=d;m['resources']['execution']={'bytes':len(raw),'nodes':nodes(load(path)),'digest':d};write(mp,m)
 routing=load(root/'routing-manifest.json');next(x for x in routing['members'] if x['familyId']==family and x['year']==year)['executionDigest']=d;write(root/'routing-manifest.json',routing)
def update_envelope_refs(root,path):
 obj=load(path);raw=path.read_bytes();rel=path.relative_to(root).as_posix();parts=rel.split('/');family,year=parts[1],int(parts[2][:-5]);mp=root/f'members/{family}/{year}.json';m=load(mp);m['trustedEnvelopeDigest']=obj['envelopeDigest'];m['resources']['envelope']={'bytes':len(raw),'nodes':nodes(obj),'digest':sha(raw)};write(mp,m)
 routing=load(root/'routing-manifest.json');next(x for x in routing['members'] if x['familyId']==family and x['year']==year)['trustedEnvelopeDigest']=obj['envelopeDigest'];write(root/'routing-manifest.json',routing)
def expect_reject(label,mutate,compare_forged=False,token=None):
 a=ROOT/f'run-adversarial-{label}-a';b=ROOT/f'run-adversarial-{label}-b';shutil.rmtree(a,ignore_errors=True);shutil.rmtree(b,ignore_errors=True);shutil.copytree(SOURCE,a);mutate(a);rehash(a)
 if compare_forged:shutil.copytree(a,b)
 result=command(a,b if compare_forged else None)
 if result.returncode==0:raise RuntimeError(f'ADVERSARIAL_ACCEPTED:{label}')
 if token and token not in result.stderr:raise RuntimeError(f'WRONG_REJECTION:{label}:{result.stderr[-500:]}')
 shutil.rmtree(a,ignore_errors=True);shutil.rmtree(b,ignore_errors=True)
 if list(ROOT.glob('run-verify-*')):raise RuntimeError(f'VERIFY_TEMP_RESIDUE:{label}')
 print(label,'rejected')

def mutate_member_path(value):
 def f(root):p=first(root,'members');m=load(p);m['mapPath']=value;write(p,m)
 return f
expect_reject('member-parent',mutate_member_path('../external.json'),token='ARTIFACT_PATH')
expect_reject('member-absolute',mutate_member_path('/tmp/external.json'),token='ARTIFACT_PATH')
expect_reject('undeclared-reference',mutate_member_path('maps/external.json'),token='ARTIFACT_PATH')
def extra(root):(root/'extra.json').write_text('{}\n')
expect_reject('extra-file',extra,token='EXACT_FILE_SET')
def payload(root):s=load(root/'summary.json');s['payloadRootDigest']='sha256:'+'0'*64;write(root/'summary.json',s);a=load(root/'reproduction-attestation.json');a['payloadRootDigest']='sha256:'+'0'*64;write(root/'reproduction-attestation.json',a)
# Rehash intentionally restores payload, so handcraft this case after rehash helper via authority mutation instead.
def authority(root):s=load(root/'summary.json');s['acceptanceAuthority']=True;write(root/'summary.json',s)
expect_reject('authority',authority,token='AUTHORITY_FLAGS')
def pending(root):a=load(root/'reproduction-attestation.json');a['pendingExternalAuthorizationReview']=False;write(root/'reproduction-attestation.json',a)
expect_reject('pending',pending,token='AUTHORITY_FLAGS')
def schema(root):r=load(root/'routing-manifest.json');r['schemaVersion']='forged';write(root/'routing-manifest.json',r)
expect_reject('schema',schema,token='ROUTING_SCHEMA')
def oracle(root):p=first(root,'members');m=load(p);m['oracleProof']['attachmentEquality']=False;write(p,m)
expect_reject('oracle',oracle,token='ORACLE_PROOF')
def attest_provider(root):a=load(root/'reproduction-attestation.json');a['providerCalls']=1;write(root/'reproduction-attestation.json',a)
expect_reject('attestation-provider',attest_provider,token='ATTESTATION_SCHEMA')
def operation(root):p=first(root,'members');m=load(p);m['resolutionOperations']+=1;write(p,m)
expect_reject('operation',operation,token='ENVELOPE_CLOSURE')
def resource(root):p=first(root,'members');m=load(p);m['resources']['map']['nodes']+=1;write(p,m)
expect_reject('resource',resource,token='RESOURCE')
def duplicate_route(root):r=load(root/'routing-manifest.json');r['members'][-1]=copy.deepcopy(r['members'][0]);write(root/'routing-manifest.json',r)
expect_reject('duplicate-route',duplicate_route,token='DUPLICATE_ROUTE')
def missing_route(root):r=load(root/'routing-manifest.json');r['members'].pop();write(root/'routing-manifest.json',r)
expect_reject('missing-route',missing_route,token='ROUTING_SCHEMA')
def warning(root):p=first(root,'executions');e=load(p);e['warnings']=['forged'];write(p,e);update_execution_refs(root,p)
expect_reject('warning',warning,token='EXECUTION_CLOSURE')
def custody(root):p=first(root,'members');m=load(p);m['sourceWorkbookDigest']='sha256:'+'0'*64;write(p,m)
expect_reject('custody',custody,token='CUSTODY')
def ledger(root):s=load(root/'summary.json');s['changedFields']=2740;write(root/'summary.json',s)
expect_reject('ledger',ledger,token='SUMMARY:changedFields')
def envelope(root):p=first(root,'envelopes');e=load(p);e['envelopeDigest']='sha256:'+'0'*64;write(p,e);update_envelope_refs(root,p)
expect_reject('forged-envelope',envelope,token='SEMANTIC_REPLAY_BYTE_MISMATCH')
def altered_execution(root):p=first(root,'executions');e=load(p);e['table']['rows'][0][next(k for k in e['table']['rows'][0] if k not in ('_source',) and not k.endswith('_source'))]='forged';e['table']['trace'][0]['value']='forged';write(p,e);update_execution_refs(root,p)
expect_reject('altered-row-trace',altered_execution,token='SEMANTIC_REPLAY_BYTE_MISMATCH')
expect_reject('identical-forged',altered_execution,compare_forged=True,token='SEMANTIC_REPLAY_BYTE_MISMATCH')
# Payload tamper that remains self-consistent with manifest but not the exact core recomputation.
a=ROOT/'run-adversarial-payload-a';shutil.rmtree(a,ignore_errors=True);shutil.copytree(SOURCE,a);s=load(a/'summary.json');s['payloadRootDigest']='sha256:'+'0'*64;write(a/'summary.json',s);att=load(a/'reproduction-attestation.json');att['payloadRootDigest']='sha256:'+'0'*64;write(a/'reproduction-attestation.json',att);paths=[p.relative_to(a).as_posix() for p in a.rglob('*') if p.is_file() and p.name!='manifest.json'];rec=records(a,paths);m=load(a/'manifest.json');m['files']=rec;m['outputRootDigest']=sha(stable(rec).encode());write(a/'manifest.json',m);result=command(a)
if result.returncode==0 or 'PAYLOAD_ROOT_DIGEST' not in result.stderr:raise RuntimeError('PAYLOAD_TAMPER_ACCEPTED')
shutil.rmtree(a);print('payload rejected')
# Wrong authorization digest.
result=command(SOURCE,digest='sha256:'+'0'*64)
if result.returncode==0 or 'AUTHORIZATION_DIGEST' not in result.stderr:raise RuntimeError('WRONG_AUTH_ACCEPTED')
print('wrong authorization rejected')
# Root symlink and special node.
link=ROOT/'run-adversarial-root-link';fifo=ROOT/'run-adversarial-root-fifo';link.unlink(missing_ok=True);fifo.unlink(missing_ok=True);link.symlink_to('run-a',target_is_directory=True)
if command(link).returncode==0:raise RuntimeError('ROOT_SYMLINK_ACCEPTED')
link.unlink();subprocess.run(['mkfifo',fifo.as_posix()],check=True)
if command(fifo).returncode==0:raise RuntimeError('ROOT_SPECIAL_ACCEPTED')
fifo.unlink();print('root symlink/special rejected')
# Candidate and compare roots must be direct canonical run-* children.
nested_parent=ROOT/'run-adversarial-nested-parent';nested=nested_parent/'run-nested';shutil.rmtree(nested_parent,ignore_errors=True);shutil.copytree(SOURCE,nested)
if command(nested).returncode==0:raise RuntimeError('NESTED_CANDIDATE_ROOT_ACCEPTED')
if command(SOURCE,nested).returncode==0:raise RuntimeError('NESTED_COMPARE_ROOT_ACCEPTED')
shutil.rmtree(nested_parent);print('nested candidate/compare roots rejected')
# Authorization and pinned input symlink/special nodes.
for kind in ('symlink','special'):
 auth=Path(f'fixtures/product-prototype/c2-adversarial-auth-{kind}.json');target=Path(f'.product-prototype/offenders-remaining-phase1/c2-adversarial-input-{kind}');target.unlink(missing_ok=True)
 data=load(AUTH);idx=next(i for i,x in enumerate(data['inputs']) if '/direct/' in x['path'])
 if kind=='symlink':target.symlink_to('source-partition-canary/run-a-remediated/manifest.json')
 else:subprocess.run(['mkfifo',target.as_posix()],check=True)
 data['inputs'][idx]={'path':target.as_posix(),'byteLength':0,'sha256':'sha256:'+'0'*64};write(auth,data)
 result=command(SOURCE,auth=auth)
 if result.returncode==0:raise RuntimeError(f'INPUT_{kind.upper()}_ACCEPTED')
 auth.unlink();target.unlink();print('input',kind,'rejected')
# Toolchain closure drift on a copied manifest/auth; real node_modules is untouched.
custom_auth=Path('fixtures/product-prototype/c2-adversarial-toolchain-auth.json');custom_manifest=Path('fixtures/product-prototype/c2-adversarial-node-modules.json')
data=load(AUTH);manifest=load(Path(data['toolchainClosure']['nodeModules']['manifest']['path']));manifest['entries'][0]['sha256']='sha256:'+'0'*64;manifest['merkleRoot']=sha(stable(manifest['entries']).encode());write(custom_manifest,manifest);pin={'path':custom_manifest.as_posix(),'byteLength':custom_manifest.stat().st_size,'sha256':sha(custom_manifest.read_bytes())};old=data['toolchainClosure']['nodeModules']['manifest']['path'];data['inputs']=[pin if x['path']==old else x for x in data['inputs']];data['toolchainClosure']['nodeModules']['manifest']=pin;data['toolchainClosure']['nodeModules']['merkleRoot']=manifest['merkleRoot'];write(custom_auth,data)
result=command(SOURCE,auth=custom_auth)
if result.returncode==0 or 'NODE_MODULES_CLOSURE_DRIFT' not in result.stderr:raise RuntimeError('TOOLCHAIN_DRIFT_ACCEPTED')
custom_auth.unlink();custom_manifest.unlink();print('toolchain drift rejected')
# The interpreter executing the verifier must be the exact authorization-pinned Python.
custom_auth=Path('fixtures/product-prototype/c2-adversarial-python-auth.json');wrapper=Path('.product-prototype/offenders-remaining-phase1/c2-adversarial-python')
base=load(AUTH);version=base['toolchainClosure']['python']['version'];wrapper.write_text(f'#!/bin/sh\necho "{version}"\n');wrapper.chmod(0o755);raw=wrapper.read_bytes();real=str(wrapper.resolve());base['toolchainClosure']['python']={'version':version,'executablePath':real,'realPath':real,'linkTarget':None,'byteLength':len(raw),'sha256':sha(raw)};write(custom_auth,base)
real_python=toolchain(AUTH)['python']['executablePath'];cmd=[real_python,'scripts/verify-offenders-remaining-target-scoped.py','--root',SOURCE.as_posix(),'--authorization',custom_auth.as_posix(),'--authorization-digest',sha(custom_auth.read_bytes())];result=subprocess.run(cmd,capture_output=True,text=True)
if result.returncode==0 or 'TOOLCHAIN_PYTHON_PROCESS_MISMATCH' not in result.stderr:raise RuntimeError(f'WRONG_PYTHON_ACCEPTED:{result.stderr[-500:]}')
custom_auth.unlink();wrapper.unlink();print('wrong Python interpreter rejected')
# Recursive verifier, compare-root collision, verification-mode nesting and overwrite handshakes.
env=dict(os.environ);env['C2_VERIFIER_REPLAY_TOKEN']='forged'
if command(SOURCE,env=env).returncode==0:raise RuntimeError('RECURSIVE_REPLAY_ACCEPTED')
if command(SOURCE,SOURCE).returncode==0:raise RuntimeError('COMPARE_COLLISION_ACCEPTED')
handshake=ROOT/'run-verify-adversarial-handshake';nested=ROOT/'run-parent'/'run-verify-nested';token='11111111-1111-4111-8111-111111111111'
if subprocess.run(builder_command(handshake),capture_output=True,text=True).returncode==0:raise RuntimeError('ORDINARY_VERIFY_ROOT_ACCEPTED')
env=dict(os.environ);env['C2_VERIFIER_REPLAY_TOKEN']=token
if subprocess.run(builder_command(nested,'--verification-replay','--verification-token',token),capture_output=True,text=True,env=env).returncode==0:raise RuntimeError('NESTED_VERIFY_ROOT_ACCEPTED')
if subprocess.run(builder_command(handshake,'--verification-replay','--verification-token',token,'--verification-forbid-root',handshake.as_posix()),capture_output=True,text=True,env=env).returncode==0:raise RuntimeError('VERIFY_COLLISION_ACCEPTED')
print('recursion/nesting/collision rejected')
# Real interleaving: the second builder fails on the atomic lock before mutation.
path=ROOT/'run-adversarial-concurrent';shutil.rmtree(path,ignore_errors=True);path.mkdir();(path/'prior.txt').write_text('prior\n')
first=subprocess.Popen(builder_command(path,'--inject-failure','hold-lock'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
lock=Path(str(path.resolve())+'.lock')
for _ in range(100):
 if lock.exists():break
 import time;time.sleep(.05)
if not lock.exists():first.kill();raise RuntimeError('CONCURRENT_LOCK_NOT_ACQUIRED')
second=subprocess.run(builder_command(path),capture_output=True,text=True,timeout=60)
out,err=first.communicate(timeout=20)
residue=list(ROOT.glob('run-adversarial-concurrent.*-*'))+list(ROOT.glob('run-adversarial-concurrent.lock'))
if second.returncode==0 or 'TRANSACTION_LOCKED' not in second.stderr or first.returncode==0 or (path/'prior.txt').read_text()!='prior\n' or residue:raise RuntimeError(f'CONCURRENT_TRANSACTION:{residue}:{second.stderr[-300:]}')
shutil.rmtree(path);print('concurrent transaction excluded')
# Full builder pre-commit transaction matrix: exact prior tree and no residue.
for mode in ('before-swap','after-swap','after-writes'):
 path=ROOT/'run-adversarial-transaction';shutil.rmtree(path,ignore_errors=True);path.mkdir();(path/'prior.txt').write_text('prior\n');before={p.relative_to(path).as_posix():p.read_bytes() for p in path.rglob('*') if p.is_file()}
 result=subprocess.run(builder_command(path,'--inject-failure',mode),capture_output=True,text=True,timeout=1800)
 after={p.relative_to(path).as_posix():p.read_bytes() for p in path.rglob('*') if p.is_file()}
 residue=list(ROOT.glob('run-adversarial-transaction.temporary-*'))+list(ROOT.glob('run-adversarial-transaction.backup-*'))+list(ROOT.glob('run-adversarial-transaction.lock'))
 if result.returncode==0 or before!=after or residue:raise RuntimeError(f'TRANSACTION:{mode}:{residue}')
 shutil.rmtree(path);print(mode,'transaction restored')
# Post-commit cleanup failure preserves the complete new final and an owned backup;
# the next locked build reaps only that marked stale backup and leaves a valid final.
path=ROOT/'run-adversarial-cleanup';shutil.rmtree(path,ignore_errors=True);path.mkdir();(path/'prior.txt').write_text('prior\n')
result=subprocess.run(builder_command(path,'--inject-failure','cleanup-failure'),capture_output=True,text=True,timeout=1800)
backup=list(ROOT.glob('run-adversarial-cleanup.backup-*'))
if result.returncode==0 or 'POST_COMMIT_CLEANUP_FAILURE' not in result.stderr or len(backup)!=1 or not (backup[0]/'.c2-transaction-owner.json').is_file() or list(ROOT.glob('run-adversarial-cleanup.lock')):raise RuntimeError('POST_COMMIT_CLEANUP_STATE')
expected={p.relative_to(SOURCE).as_posix():p.read_bytes() for p in SOURCE.rglob('*') if p.is_file()};installed={p.relative_to(path).as_posix():p.read_bytes() for p in path.rglob('*') if p.is_file()}
if installed!=expected:raise RuntimeError('POST_COMMIT_FINAL_DRIFT')
second=subprocess.run(builder_command(path),capture_output=True,text=True,timeout=1800)
if second.returncode or list(ROOT.glob('run-adversarial-cleanup.backup-*')) or list(ROOT.glob('run-adversarial-cleanup.lock')):raise RuntimeError('STALE_BACKUP_NOT_REAPED')
installed={p.relative_to(path).as_posix():p.read_bytes() for p in path.rglob('*') if p.is_file()}
if installed!=expected:raise RuntimeError('LATER_FINAL_DRIFT')
shutil.rmtree(path);print('post-commit cleanup failure preserved and later reaped')
if list(ROOT.glob('run-verify-*')) or list(ROOT.glob('*.lock')):raise RuntimeError('FINAL_TRANSACTION_RESIDUE')
print(json.dumps({'adversarialCases':31,'semanticReplayForgeryCases':3,'transactionFailures':4,'concurrentTransactions':1,'toolchainDrift':1,'wrongInterpreter':1,'status':'passed'},sort_keys=True))

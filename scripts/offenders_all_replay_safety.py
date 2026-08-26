#!/usr/bin/env python3
"""Fail-closed filesystem, toolchain and canonical helpers for Offenders all-170 replay."""
from __future__ import annotations
import atexit, hashlib, json, os, shutil, signal, stat, subprocess, sys, uuid
from pathlib import Path, PurePosixPath

REPO = Path.cwd().resolve()
ALLOWED = Path('.product-prototype/offenders-remaining-phase1/all-170-replay')
PHASE_BOUNDARIES = {
 'b2a-maps': Path('.product-prototype/offenders-remaining-phase1/multi-panel-b2a'),
 'b2a-routed': Path('.product-prototype/offenders-remaining-phase1/multi-panel-b2a'),
 'c2': Path('.product-prototype/offenders-remaining-phase1/target-scoped-c2'),
}
FALSE_FLAGS = ('acceptanceAuthority','trainingEligibility','productionAcceptance','promotionAuthorization')
OWNER = '.c3-transaction-owner.json'
PHASE_OWNER_SUFFIX = '.c3-phase-owner.json'
VERIFIER_OWNER_SUFFIX = '.c3-verifier-owner.json'
VERIFIER_DELETE_OWNER = '.c3-verifier-delete-owner.json'
INJECTION_ENV = ('NODE_OPTIONS','NODE_PATH','PYTHONPATH','PYTHONHOME','TS_NODE_PROJECT','TSX_TSCONFIG_PATH','BABEL_ENV','NODE_ENV_OPTIONS')

def sha(data: bytes) -> str: return 'sha256:'+hashlib.sha256(data).hexdigest()
def stable(value) -> str: return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def pretty(value) -> bytes: return (json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
def root_digest(records) -> str: return sha(stable(sorted(records,key=lambda x:x['path'])).encode())
def lexists(path: Path) -> bool: return os.path.lexists(path)
def canonical_rel(value: str,label='path') -> str:
 if type(value) is not str or not value or '\\' in value or value.startswith('/') or value.endswith('/') or str(PurePosixPath(value))!=value or any(x in ('','.','..') for x in value.split('/')): raise RuntimeError(f'UNSAFE_REFERENCE:{label}:{value}')
 return value
def exact_keys(value,keys,label):
 if type(value) is not dict or set(value)!=set(keys): raise RuntimeError(f'SCHEMA_KEYS:{label}')
def flags(value,label):
 if value.get('pendingExternalAuthorizationReview') is not True or any(value.get(k) is not False for k in FALSE_FLAGS): raise RuntimeError(f'AUTHORITY_FLAGS:{label}')
def sanitized_env(extra=None):
 env={k:v for k,v in os.environ.items() if k not in INJECTION_ENV and not k.startswith('PYTHONWARN')}
 if extra:
  if any(k in INJECTION_ENV or k.startswith('PYTHONWARN') for k in extra):raise RuntimeError('INJECTION_ENV_REINTRODUCED')
  env.update(extra)
 return env

def assert_plain_ancestor_chain(path: Path,boundary: Path,label: str,leaf_may_absent=True):
 boundary=boundary.absolute();path=path.absolute()
 try:path.relative_to(boundary)
 except ValueError:raise RuntimeError(f'PATH_ESCAPE:{label}:{path}')
 cur=boundary
 if not lexists(cur):raise RuntimeError(f'MISSING_BOUNDARY:{label}:{cur}')
 bi=cur.lstat()
 if stat.S_ISLNK(bi.st_mode) or not stat.S_ISDIR(bi.st_mode):raise RuntimeError(f'UNSAFE_BOUNDARY:{label}:{cur}')
 for part in path.relative_to(boundary).parts:
  cur=cur/part
  if not lexists(cur):
   if leaf_may_absent:continue
   raise RuntimeError(f'MISSING_PATH:{label}:{cur}')
  info=cur.lstat()
  if stat.S_ISLNK(info.st_mode):raise RuntimeError(f'SYMLINK:{label}:{cur}')
  if cur!=path and not stat.S_ISDIR(info.st_mode):raise RuntimeError(f'SPECIAL_ANCESTOR:{label}:{cur}')

def ensure_plain_directory(path: Path,boundary: Path,label: str):
 """Create missing components one at a time only after validating their parent."""
 boundary=boundary.absolute();path=path.absolute()
 assert_plain_ancestor_chain(boundary,boundary,label,False)
 try:parts=path.relative_to(boundary).parts
 except ValueError:raise RuntimeError(f'PATH_ESCAPE:{label}:{path}')
 cur=boundary
 for part in parts:
  parent=cur;cur=cur/part
  assert_plain_ancestor_chain(parent,boundary,label,False)
  if not lexists(cur):cur.mkdir()
  info=cur.lstat()
  if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise RuntimeError(f'UNSAFE_DIRECTORY:{label}:{cur}')

def direct_allowed_path(value: str,label='output') -> Path:
 rel=canonical_rel(value,label);p=PurePosixPath(rel)
 if p.parent!=PurePosixPath(ALLOWED.as_posix()) or not p.name.startswith('run-') or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-' for c in p.name):raise RuntimeError(f'UNSAFE_OUTPUT_NAME:{label}')
 allowed=(REPO/ALLOWED).absolute()
 ensure_plain_directory(allowed,REPO,'allowed')
 final=(REPO/rel).absolute();assert_plain_ancestor_chain(final,allowed,label)
 if lexists(final):
  info=final.lstat()
  if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise RuntimeError(f'UNSAFE_OUTPUT_ROOT:{label}:{final}')
 return final

def safe_regular(base: Path, rel: str, label='file') -> Path:
 rel=canonical_rel(rel,label);root=base.absolute();path=(root/rel).absolute();assert_plain_ancestor_chain(path,root,label,False)
 info=path.lstat()
 if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):raise RuntimeError(f'SPECIAL:{label}:{rel}')
 real=path.resolve(strict=True)
 try:real.relative_to(root.resolve(strict=True))
 except ValueError:raise RuntimeError(f'PATH_ESCAPE:{label}:{rel}')
 return path
def safe_repo_file(rel,label='input'): return safe_regular(REPO,canonical_rel(rel,label),label)
def load_json(path: Path,max_bytes=500_000_000):
 info=path.lstat()
 if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode): raise RuntimeError(f'UNSAFE_FILE:{path}')
 raw=path.read_bytes()
 if len(raw)>max_bytes: raise RuntimeError(f'BYTE_LIMIT:{path}')
 return json.loads(raw),raw
def file_record(path: Path, rel: str):
 info=path.lstat()
 if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):raise RuntimeError(f'UNSAFE_RECORD:{path}')
 raw=path.read_bytes();return {'path':rel,'byteLength':len(raw),'sha256':sha(raw)}
def walk_regular(root: Path):
 result=[]
 for base,dirs,files in os.walk(root,followlinks=False):
  for name in dirs:
   p=Path(base)/name;info=p.lstat()
   if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise RuntimeError(f'UNSAFE_OUTPUT_NODE:{p}')
  for name in files:
   p=Path(base)/name;info=p.lstat()
   if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):raise RuntimeError(f'UNSAFE_OUTPUT_NODE:{p}')
   result.append(p.relative_to(root).as_posix())
 return sorted(result)

def _secure_write(path: Path,data: bytes):
 flags_=os.O_WRONLY|os.O_CREAT|os.O_EXCL
 if hasattr(os,'O_NOFOLLOW'):flags_|=os.O_NOFOLLOW
 fd=os.open(path,flags_,0o600)
 try:os.write(fd,data);os.fsync(fd)
 finally:os.close(fd)
def owner(token: str,final: Path,kind: str):return {'version':'c3-transaction-owner/v2','token':token,'finalPath':str(final),'kind':kind}
def _owner_file(path: Path,kind: str):return path/('owner.json' if kind=='lock' else OWNER)
def read_owner(path: Path,kind: str):
 marker=_owner_file(path,kind)
 if not lexists(marker):raise RuntimeError(f'MISSING_OWNER:{path}')
 info=marker.lstat()
 if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):raise RuntimeError(f'INVALID_OWNER_FILE:{path}')
 data=json.loads(marker.read_bytes());exact_keys(data,{'version','token','finalPath','kind'},'owner')
 if data['version']!='c3-transaction-owner/v2' or data['kind']!=kind or type(data['token']) is not str or type(data['finalPath']) is not str:raise RuntimeError('INVALID_OWNER')
 return data
def _expected(token,final,kind):return owner(token,final,kind)
def _assert_owned(path,kind,token,final):
 if read_owner(path,kind)!=_expected(token,final,kind):raise RuntimeError(f'PATH_NOT_OWNED:{path}')
def _remove_owned(path,kind,token,final,lock):
 _assert_owned(lock,'lock',token,final);_assert_owned(path,kind,token,final)
 info=path.lstat()
 if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise RuntimeError(f'UNSAFE_OWNED_PATH:{path}')
 shutil.rmtree(path)
def _release_lock(lock,token,final):
 _assert_owned(lock,'lock',token,final);(_owner_file(lock,'lock')).unlink();lock.rmdir()

def recover_verification_transaction(requested: str,token: str):
 """Recover only a verifier-owned transaction for a fresh run-verify root."""
 final=direct_allowed_path(requested,'verification-recovery');lock=Path(str(final)+'.lock');temp=Path(str(final)+f'.temporary-{token}');backup=Path(str(final)+f'.backup-{token}')
 if not lexists(lock):
  if any(lexists(p) for p in (temp,backup)):raise RuntimeError('RECOVERY_WITHOUT_LOCK')
  return
 _assert_owned(lock,'lock',token,final)
 if lexists(final):
  if lexists(final/OWNER) and read_owner(final,'temporary')==_expected(token,final,'temporary'):
   _remove_owned(final,'temporary',token,final,lock)
  elif not lexists(final/OWNER):
   # A fresh verification root without its transaction marker crossed commit.
   if lexists(backup):_remove_owned(backup,'backup',token,final,lock)
   if lexists(temp):_remove_owned(temp,'temporary',token,final,lock)
   _release_lock(lock,token,final);return
  else:raise RuntimeError('RECOVERY_FINAL_NOT_OWNED')
 if lexists(backup):raise RuntimeError('UNEXPECTED_VERIFICATION_BACKUP')
 if lexists(temp):_remove_owned(temp,'temporary',token,final,lock)
 _release_lock(lock,token,final)

class Transaction:
 def __init__(self,requested: str,injected: str|None=None,token: str|None=None):
  self.final=direct_allowed_path(requested);self.injected=injected;self.token=token or str(uuid.uuid4());self.lock=Path(str(self.final)+'.lock');self.temp=Path(str(self.final)+f'.temporary-{self.token}');self.backup=Path(str(self.final)+f'.backup-{self.token}');self.committed=False;self.closed=False;self._finishing=False
  if lexists(self.lock):raise RuntimeError(f'TRANSACTION_LOCKED:{self.final}')
  lock_created=False;temp_created=False
  try:
   self.lock.mkdir();lock_created=True;_secure_write(_owner_file(self.lock,'lock'),pretty(_expected(self.token,self.final,'lock')))
   self._lock()
   for kind in ('temporary','backup'):
    prefix=self.final.name+f'.{kind}-'
    for p in sorted(self.final.parent.iterdir()):
     if not p.name.startswith(prefix):continue
     info=p.lstat()
     if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise RuntimeError(f'UNSAFE_STALE:{p}')
     data=read_owner(p,kind);suffix=p.name[len(prefix):]
     if data['finalPath']!=str(self.final) or data['token']!=suffix or data['kind']!=kind:raise RuntimeError('STALE_OWNER_MISMATCH')
     shutil.rmtree(p)
   self.temp.mkdir();temp_created=True;_secure_write(self.temp/OWNER,pretty(_expected(self.token,self.final,'temporary')))
  except BaseException:
   try:
    if temp_created and lexists(self.temp):
     if lexists(self.temp/OWNER) and lexists(self.lock) and lexists(_owner_file(self.lock,'lock')):_remove_owned(self.temp,'temporary',self.token,self.final,self.lock)
     elif not any(self.temp.iterdir()):self.temp.rmdir()
    if lock_created and lexists(self.lock):
     if lexists(_owner_file(self.lock,'lock')):_release_lock(self.lock,self.token,self.final)
     elif not any(self.lock.iterdir()):self.lock.rmdir()
   except BaseException:pass
   raise
  self._exit=lambda:self._close_noexcept()
  atexit.register(self._exit);self._signals={}
  try:
   for sig in (signal.SIGINT,signal.SIGTERM):self._signals[sig]=signal.getsignal(sig);signal.signal(sig,self._signal)
  except ValueError:self._signals={}
 def _signal(self,signum,frame):
  self._close_noexcept();raise SystemExit(128+signum)
 def _restore_handlers(self):
  for sig,handler in self._signals.items():signal.signal(sig,handler)
  self._signals={}
  try:atexit.unregister(self._exit)
  except Exception:pass
 def _lock(self):_assert_owned(self.lock,'lock',self.token,self.final)
 def _close_noexcept(self):
  if self.closed:return
  try:
   if self.committed:self._finish_postcommit()
   else:self.abort()
  except BaseException:pass
 def abort(self):
  if self.committed:
   self._finish_postcommit();return
  if self.closed:return
  self._lock()
  if lexists(self.final):
   installed_owned=False
   if lexists(self.final/OWNER):
    try:installed_owned=read_owner(self.final,'temporary')==_expected(self.token,self.final,'temporary')
    except Exception:installed_owned=False
   if installed_owned:_remove_owned(self.final,'temporary',self.token,self.final,self.lock)
   elif lexists(self.backup):raise RuntimeError('ROLLBACK_FINAL_NOT_OWNED')
  if lexists(self.backup):
   _assert_owned(self.backup,'backup',self.token,self.final);(_owner_file(self.backup,'backup')).unlink();self.backup.rename(self.final)
  if lexists(self.temp):_remove_owned(self.temp,'temporary',self.token,self.final,self.lock)
  _release_lock(self.lock,self.token,self.final);self.closed=True;self._restore_handlers()
 def _finish_postcommit(self,inject_cleanup=False):
  if self.closed:return None
  if not self.committed:raise RuntimeError('POSTCOMMIT_BEFORE_COMMIT')
  if self._finishing:return None
  self._finishing=True;cleanup=None
  blocked=None
  try:
   if hasattr(signal,'pthread_sigmask'):blocked=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM})
   try:
    self._lock()
    if inject_cleanup:raise RuntimeError('INJECTED_FAILURE:cleanup-failure')
    if lexists(self.backup):_remove_owned(self.backup,'backup',self.token,self.final,self.lock)
   except BaseException as exc:cleanup=exc
   finally:
    if lexists(self.lock):_release_lock(self.lock,self.token,self.final)
    self.closed=True;self._restore_handlers()
  finally:
   self._finishing=False
   if blocked is not None:signal.pthread_sigmask(signal.SIG_SETMASK,blocked)
  return cleanup
 def commit(self):
  self._lock();_assert_owned(self.temp,'temporary',self.token,self.final)
  if self.injected=='before-swap':self.abort();raise RuntimeError('INJECTED_FAILURE:before-swap')
  try:
   if lexists(self.final):
    info=self.final.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or lexists(self.final/OWNER):raise RuntimeError('UNSAFE_PRIOR')
    _secure_write(self.final/OWNER,pretty(_expected(self.token,self.final,'backup')));self.final.rename(self.backup)
   self.temp.rename(self.final)
   if self.injected=='after-swap':raise RuntimeError('INJECTED_FAILURE:after-swap')
   _assert_owned(self.final,'temporary',self.token,self.final)
   # Commit point: from here signal/atexit preserves the installed final.
   self.committed=True;(self.final/OWNER).unlink()
  except BaseException:
   if not self.committed:self.abort()
   raise
  if self.injected in ('postcommit-signal','cleanup-interrupt'):
   self._signal(signal.SIGTERM,None)
  cleanup=self._finish_postcommit(self.injected=='cleanup-failure')
  if cleanup:raise RuntimeError(f'POST_COMMIT_CLEANUP_FAILURE:{cleanup}')

class PhaseLease:
 """Own an exact child-output namespace created by an external phase process."""
 def __init__(self,path: Path,token: str,kind: str):
  boundary_rel=PHASE_BOUNDARIES.get(kind)
  if boundary_rel is None:raise RuntimeError(f'UNKNOWN_PHASE_KIND:{kind}')
  boundary=(REPO/boundary_rel).absolute();assert_plain_ancestor_chain(boundary,REPO,f'phase-{kind}-boundary',False)
  self.path=path.absolute();self.token=token;self.kind=kind
  expected_name={'b2a-maps':f'run-c3-{token}-maps','b2a-routed':f'run-c3-{token}-routed','c2':f'run-verify-c3-{token}'}[kind]
  if self.path.parent!=boundary or self.path.name!=expected_name:raise RuntimeError(f'PHASE_PATH_POLICY:{self.path}')
  self.marker=Path(str(self.path)+PHASE_OWNER_SUFFIX)
  assert_plain_ancestor_chain(self.marker,boundary,f'phase-{kind}-marker')
  if lexists(self.path) or lexists(self.marker):raise RuntimeError(f'PHASE_COLLISION:{self.path}')
  _secure_write(self.marker,pretty({'version':'c3-phase-owner/v1','token':token,'path':str(self.path),'kind':kind}))
 def _check(self):
  assert_plain_ancestor_chain(self.marker,self.path.parent,'phase-marker',False)
  info=self.marker.lstat()
  if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):raise RuntimeError('PHASE_MARKER_UNSAFE')
  value=json.loads(self.marker.read_bytes())
  if value!={'version':'c3-phase-owner/v1','token':self.token,'path':str(self.path),'kind':self.kind}:raise RuntimeError('PHASE_NOT_OWNED')
 def cleanup(self):
  self._check();parent=self.path.parent;prefix=self.path.name
  candidates=[p for p in parent.iterdir() if p!=self.marker and (p.name==prefix or p.name.startswith(prefix+'.tmp-') or p.name.startswith(prefix+'.temporary-') or p.name.startswith(prefix+'.backup-') or p.name.startswith(prefix+'.lock'))]
  for p in candidates:
   info=p.lstat()
   if stat.S_ISLNK(info.st_mode):raise RuntimeError(f'PHASE_RESIDUE_SYMLINK:{p}')
   if stat.S_ISDIR(info.st_mode):shutil.rmtree(p)
   elif stat.S_ISREG(info.st_mode):p.unlink()
   else:raise RuntimeError(f'PHASE_RESIDUE_SPECIAL:{p}')
  self.marker.unlink()

def cleanup_phase_leases(leases):
 errors=[]
 for lease in reversed(list(leases)):
  try:lease.cleanup()
  except BaseException as exc:errors.append(f'{lease.kind}:{exc}')
 leases.clear()
 if errors:raise RuntimeError('PHASE_CLEANUP_FAILURE:'+'|'.join(errors))

class VerifierLease:
 """Persistent verifier authority for deleting one fresh replay namespace."""
 def __init__(self,requested: str,token: str):
  self.path=direct_allowed_path(requested,'verifier-lease');self.token=token;self.marker=Path(str(self.path)+VERIFIER_OWNER_SUFFIX);self.identity=None
  if lexists(self.path) or lexists(self.marker):raise RuntimeError('VERIFIER_LEASE_COLLISION')
  _secure_write(self.marker,pretty({'version':'c3-verifier-owner/v1','token':token,'path':str(self.path)}))
 def _check(self):
  info=self.marker.lstat()
  if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):raise RuntimeError('VERIFIER_LEASE_MARKER')
  if json.loads(self.marker.read_bytes())!={'version':'c3-verifier-owner/v1','token':self.token,'path':str(self.path)}:raise RuntimeError('VERIFIER_LEASE_NOT_OWNED')
 def capture(self):
  self._check();info=self.path.lstat()
  if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise RuntimeError('VERIFIER_REPLAY_ROOT_UNSAFE')
  self.identity=(info.st_dev,info.st_ino)
 def cleanup(self):
  self._check();lock=Path(str(self.path)+'.lock')
  if lexists(lock):recover_verification_transaction(self.path.relative_to(REPO).as_posix(),self.token)
  if lexists(self.path):
   info=self.path.lstat()
   if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise RuntimeError('VERIFIER_DELETE_ROOT_UNSAFE')
   if self.identity is not None and self.identity!=(info.st_dev,info.st_ino):raise RuntimeError('VERIFIER_ROOT_REPLACED')
   inner=self.path/VERIFIER_DELETE_OWNER
   _secure_write(inner,pretty({'version':'c3-verifier-delete/v1','token':self.token,'path':str(self.path)}))
   if json.loads(inner.read_bytes())!={'version':'c3-verifier-delete/v1','token':self.token,'path':str(self.path)}:raise RuntimeError('VERIFIER_DELETE_NOT_OWNED')
   shutil.rmtree(self.path)
  for suffix in (f'.temporary-{self.token}',f'.backup-{self.token}'):
   if lexists(Path(str(self.path)+suffix)):raise RuntimeError('VERIFIER_TRANSACTION_RESIDUE')
  self.marker.unlink()

def run_child(command,env=None,timeout=1800):
 child_env=sanitized_env(env);proc=subprocess.Popen(command,cwd=REPO,env=child_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
 try:out,err=proc.communicate(timeout=timeout)
 except subprocess.TimeoutExpired:
  os.killpg(proc.pid,signal.SIGTERM)
  try:out,err=proc.communicate(timeout=10)
  except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);out,err=proc.communicate()
  raise RuntimeError(f'CHILD_TIMEOUT:{command[0]}:{err[-2000:]}')
 if proc.returncode:raise RuntimeError(f'CHILD_FAILURE:{command[0]}:{err[-4000:]}')
 return out

def _executable_proof(proof,label):
 exact_keys(proof,{'version','executablePath','realPath','linkTarget','byteLength','sha256'},f'{label}-executable')
 path=Path(proof['executablePath'])
 if not lexists(path):raise RuntimeError(f'TOOLCHAIN_EXECUTABLE_MISSING:{label}')
 info=path.lstat()
 if not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):raise RuntimeError(f'TOOLCHAIN_EXECUTABLE_TYPE:{label}')
 real=path.resolve(strict=True);raw=real.read_bytes();link=os.readlink(path) if stat.S_ISLNK(info.st_mode) else None
 if str(real)!=proof['realPath'] or link!=proof['linkTarget'] or len(raw)!=proof['byteLength'] or sha(raw)!=proof['sha256']:raise RuntimeError(f'TOOLCHAIN_EXECUTABLE_DRIFT:{label}')
 result=subprocess.run([str(real),'--version'],capture_output=True,text=True,check=True,env=sanitized_env());version=(result.stdout or result.stderr).strip()
 if version!=proof['version']:raise RuntimeError(f'TOOLCHAIN_VERSION:{label}')
 return str(real)
def _node_entries(root: Path):
 expected=(REPO/'node_modules').absolute();root=root.absolute()
 if root!=expected or not lexists(root):raise RuntimeError('NODE_MODULES_ROOT_IDENTITY')
 root_info=root.lstat()
 if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):raise RuntimeError('NODE_MODULES_ROOT_UNSAFE')
 assert_plain_ancestor_chain(root,REPO,'node-modules-root',False)
 boundary=root.resolve(strict=True)
 if boundary!=root:raise RuntimeError('NODE_MODULES_ROOT_ESCAPE')
 entries=[]
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
def verify_toolchain_closure(toolchain,pins,require_python_process=True):
 exact_keys(toolchain,{'schemaVersion','packageJson','packageLock','node','python','nodeModules','tsxEntrypoint'},'toolchain')
 if toolchain['schemaVersion']!='tidy.offenders-target-scoped-toolchain/v1':raise RuntimeError('TOOLCHAIN_SCHEMA')
 for field,path in (('packageJson','package.json'),('packageLock','package-lock.json')):
  if toolchain[field]!=pins.get(path):raise RuntimeError(f'TOOLCHAIN_PACKAGE_PIN:{path}')
 node=_executable_proof(toolchain['node'],'node');python=_executable_proof(toolchain['python'],'python')
 if require_python_process and Path(sys.executable).resolve(strict=True)!=Path(python):raise RuntimeError('TOOLCHAIN_PYTHON_PROCESS_MISMATCH')
 nm=toolchain['nodeModules'];exact_keys(nm,{'root','manifest','entryCount','regularFiles','symlinks','totalBytes','merkleRoot'},'node-modules-toolchain')
 manifest_pin=nm['manifest']
 if nm['root']!='node_modules' or manifest_pin!=pins.get(manifest_pin['path']):raise RuntimeError('NODE_MODULES_MANIFEST_PIN')
 manifest_path=safe_repo_file(manifest_pin['path'],'node-modules-manifest');raw=manifest_path.read_bytes()
 if len(raw)!=manifest_pin['byteLength'] or sha(raw)!=manifest_pin['sha256']:raise RuntimeError('NODE_MODULES_MANIFEST_DIGEST')
 manifest=json.loads(raw);entries=_node_entries(REPO/'node_modules');regular=sum(x['kind']=='file' for x in entries);symlinks=len(entries)-regular;total=sum(x.get('byteLength',0) for x in entries);merkle=sha(stable(entries).encode())
 actual={'entryCount':len(entries),'regularFiles':regular,'symlinks':symlinks,'totalBytes':total,'merkleRoot':merkle}
 if manifest.get('entries')!=entries or any(manifest.get(k)!=v or nm.get(k)!=v for k,v in actual.items()):raise RuntimeError('NODE_MODULES_CLOSURE_DRIFT')
 tsx=toolchain['tsxEntrypoint'];entry=next((x for x in entries if x['path']=='tsx/dist/cli.mjs'),None)
 if tsx!=pins.get('node_modules/tsx/dist/cli.mjs') or tsx.get('path')!='node_modules/tsx/dist/cli.mjs' or not entry or entry.get('sha256')!=tsx.get('sha256') or entry.get('byteLength')!=tsx.get('byteLength'):raise RuntimeError('TSX_ENTRYPOINT_DRIFT')
 return {'node':node,'python':python,'tsx':str((REPO/tsx['path']).absolute())}

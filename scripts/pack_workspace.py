#!/usr/bin/env python3
import pathlib,os,stat,hashlib,json,gzip,tarfile,subprocess,time,posixpath,re,datetime,urllib.request
ROOT=pathlib.Path('/workspace');OUT=ROOT/'research-release-upload';WORK=ROOT/'work/complete-backup';GROUP='workspace-supplement';LIMIT=32*1024*1024
SKIP_ROOTS={'research-backup-upload','research-release-upload','research-git-remote-verify'}
SECRET_NAMES={'auth.json','.env','.env.local','.env.production','credentials.json','id_rsa','id_ed25519','.netrc','.npmrc','debug.keystore','debug.keystore.lock'}
SECRET=re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[ \t]*(?:\r?\n)[A-Za-z0-9+/=]{32,}|[\"\'](?:access_token|refresh_token)[\"\']\s*:\s*[\"\'](?:eyJ|[A-Za-z0-9_-]{40,}))')
excluded=[];links=[];old={};repos=[];changed=[];vanished=[];seen=set();started=time.time()
for g in json.loads((OUT/'manifests/snapshot-index.json').read_text())['groups']:
 with gzip.open(OUT/'manifests'/f'{g}-files.jsonl.gz','rt') as f:
  for row in f:
   r=json.loads(row);old[r['path']]=r

def skip(p):
 rel=p.relative_to(ROOT);s=str(rel)
 reason=None
 if rel.parts[0] in SKIP_ROOTS:reason='Backup staging/verification duplicates; authoritative archives are already preserved remotely'
 elif s.startswith(('work/complete-backup','work/research-backup-restore','cairodrive-research/continuity/state','cairodrive-research/continuity/logs')):reason='Own backup scratch, restored test duplicate, or authenticated model runtime state/logs'
 elif p.name in SECRET_NAMES or p.suffix.lower() in {'.keystore','.jks','.p12','.pfx'}:reason='Authentication/private signing material; excluded from public backup'
 elif p.name=='.git':reason='Git administration replaced by verified Git bundles and checkout metadata'
 if reason:excluded.append({'path':s,'reason':reason});return True
 return False

def walk():
 for cur,dirs,files in os.walk(ROOT,followlinks=False):
  cur=pathlib.Path(cur);kept=[]
  for name in sorted(dirs):
   p=cur/name
   if name=='.git':repos.append(cur)
   if skip(p):continue
   if p.is_symlink():yield p
   else:kept.append(name)
  dirs[:]=kept
  for name in sorted(files):
   p=cur/name
   if name=='.git':repos.append(cur)
   if not skip(p):yield p
  if cur!=ROOT and not files and not dirs and not skip(cur):yield cur

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()

selected=[];checked=0;unchanged=0;totalbytes=0
for p in walk():
 name=str(p.relative_to(ROOT));st=p.lstat();seen.add(name);previous=old.get(name)
 if stat.S_ISREG(st.st_mode):
  checked+=1
  if previous and previous.get('sha256') and st.st_size==previous['bytes'] and st.st_mtime_ns==previous['mtime_ns']:
   unchanged+=1;continue
  selected.append(p);totalbytes+=st.st_size
 elif stat.S_ISLNK(st.st_mode):
  target=os.readlink(p)
  if target.startswith('/workspace/'):target=posixpath.relpath(target[len('/workspace/'):],posixpath.dirname(name))
  resolved=(p.parent/os.readlink(p)).resolve(strict=False)
  if not resolved.is_relative_to(ROOT):
   links.append({'path':name,'target':os.readlink(p),'resolved_target':str(resolved),'reason':'External system link; recorded separately, not extracted through unsafe tar target'});continue
  if previous and previous.get('stored_target')==target:unchanged+=1;continue
  selected.append(p)
 elif stat.S_ISDIR(st.st_mode):selected.append(p)
 else:excluded.append({'path':name,'reason':'Nonregular runtime object'})
 if checked%50000==0:print(json.dumps({'phase':'audit','checked_files':checked,'already_covered':unchanged,'additional_files':len(selected),'additional_bytes':totalbytes}),flush=True)

history=WORK/'workspace-git-history';history.mkdir(exist_ok=True);git_records=[]
for i,repo in enumerate(sorted(set(repos))):
 rel=str(repo.relative_to(ROOT));bundle=history/f'{i:03}.bundle';r={'path':rel,'bundle':str(bundle.relative_to(WORK))}
 def git(*args):return subprocess.run(['git','-C',str(repo),*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 head=git('rev-parse','HEAD');r['head']=head.stdout.strip() if head.returncode==0 else None
 branch=git('symbolic-ref','-q','--short','HEAD');r['branch']=branch.stdout.strip() if branch.returncode==0 else None
 r['refs']=git('show-ref').stdout.splitlines();r['status']=git('status','--porcelain=v1').stdout.splitlines()
 proc=git('bundle','create',str(bundle),'--all') if not bundle.exists() else git('bundle','verify',str(bundle))
 if proc.returncode==0:
  check=git('bundle','verify',str(bundle));assert check.returncode==0,rel;r['bundle_verified']=True;selected.append(bundle)
 else:r.update(bundle=None,bundle_verified=False,reason='No valid refs to bundle' if not r['refs'] else 'Bundle failure');assert not r['refs'],rel
 patch=history/f'{i:03}-staged.patch';patch.write_text(git('diff','--cached','--binary').stdout);selected.append(patch);git_records.append(r)
 print(json.dumps({'phase':'git_history','repository':rel,'verified':r['bundle_verified']}),flush=True)
(history/'repositories.json').write_text(json.dumps(git_records,indent=2)+'\n');selected.append(history/'repositories.json')
meta=WORK/'workspace-environment';meta.mkdir(exist_ok=True)
commands={'os-release':['cat','/etc/os-release'],'system-packages':['dpkg-query','-W','-f=${Package}\t${Version}\n'],'python-packages':['python','-m','pip','list','--format=json'],'git-version':['git','--version'],'node-version':['node','--version'],'java-version':['java','-version']}
for n,cmd in commands.items():
 try:r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True);(meta/f'{n}.txt').write_text(r.stdout)
 except FileNotFoundError:(meta/f'{n}.txt').write_text('Unavailable\n')
 selected.append(meta/f'{n}.txt')
(meta/'git-restore.py').write_text('''import pathlib,json,subprocess,sys\nroot=pathlib.Path(sys.argv[1]).resolve();history=root/'workspace-git-history'\nfor r in json.loads((history/'repositories.json').read_text()):\n if not r['bundle']:continue\n p=root/r['path'];p.mkdir(parents=True,exist_ok=True);subprocess.run(['git','init',str(p)],check=True)\n subprocess.run(['git','-C',str(p),'fetch','--update-head-ok',str(root/r['bundle']),'+refs/*:refs/*'],check=True)\n if r['branch']:subprocess.run(['git','-C',str(p),'symbolic-ref','HEAD','refs/heads/'+r['branch']],check=True)\n elif r['head']:subprocess.run(['git','-C',str(p),'update-ref','--no-deref','HEAD',r['head']],check=True)\n if r['head']:subprocess.run(['git','-C',str(p),'reset','--mixed',r['head']],check=True)\n patch=history/(pathlib.Path(r['bundle']).stem+'-staged.patch')\n if patch.exists() and patch.stat().st_size:subprocess.run(['git','-C',str(p),'apply','--cached',str(patch)],check=True)\n''');selected.append(meta/'git-restore.py')

allow_path=WORK/'public-fixtures.json';allow=json.loads(allow_path.read_text()) if allow_path.exists() else {};safe_selected=[]
for i,f in enumerate(selected):
 if not f.is_file() or f.is_symlink():safe_selected.append(f);continue
 name=str(f.relative_to(WORK)) if f.is_relative_to(WORK) else str(f.relative_to(ROOT));found=False;carry=b'';h=hashlib.sha256()
 with f.open('rb') as src:
  for b in iter(lambda:src.read(1024*1024),b''):
   h.update(b);found=found or bool(SECRET.search(carry+b));carry=(carry+b)[-256:]
 if found:
  if name not in allow or allow[name]['sha256']!=h.hexdigest():
   repo=next((r for r in sorted(set(repos),key=lambda p:len(p.parts),reverse=True) if f.is_relative_to(r)),None);ok=False
   if repo:
    origin=subprocess.run(['git','-C',str(repo),'remote','get-url','origin'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True).stdout.strip();match=re.fullmatch(r'https://github.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?',origin)
    head=subprocess.run(['git','-C',str(repo),'rev-parse','HEAD'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True).stdout.strip()
    if match and re.fullmatch('[a-f0-9]{40}',head):
     rel=str(f.relative_to(repo));url=f'https://raw.githubusercontent.com/{match[1]}/{match[2]}/{head}/{rel}'
     try:
      with urllib.request.urlopen(url,timeout=60) as src:public=src.read(f.stat().st_size+1)
      ok=hashlib.sha256(public).hexdigest()==h.hexdigest()
      if ok:allow[name]={'sha256':h.hexdigest(),'public_source':url,'reason':'Exact immutable public upstream bytes; credential-looking test/documentation fixture'}
     except Exception:pass
   if not ok:excluded.append({'path':name,'reason':'Credential pattern without identical immutable public upstream proof; excluded from public backup'});print(json.dumps({'phase':'credential_excluded','path':name}),flush=True);continue
  print(json.dumps({'phase':'public_fixture_verified','path':name}),flush=True)
 safe_selected.append(f)
 if i and i%20000==0:print(json.dumps({'phase':'credential_preflight','files':i}),flush=True)
selected=safe_selected;allow_path.write_text(json.dumps(allow,indent=2)+'\n')

class Chunks:
 def __init__(self):self.fd=None;self.parts=[];self.size=0
 def write(self,b):
  length=len(b)
  while b:
   if self.fd is None:
    self.path=OUT/'payloads'/f'{GROUP}.tar.gz.{len(self.parts)+1:03}.part';self.fd=self.path.open('wb');self.h=hashlib.sha256();self.size=0
   n=min(len(b),LIMIT-self.size);x=b[:n];b=b[n:];self.fd.write(x);self.h.update(x);self.size+=n
   if self.size==LIMIT:self.finish()
  return length
 def flush(self):
  if self.fd:self.fd.flush()
 def finish(self):
  if self.fd:
   self.fd.close();self.parts.append({'path':str(self.path.relative_to(OUT)),'bytes':self.size,'sha256':self.h.hexdigest()});self.fd=None
class Hashed:
 def __init__(self,f,n,name):self.f=f;self.n=n;self.name=name;self.h=hashlib.sha256();self.carry=b''
 def read(self,n=-1):
  n=self.n if n<0 else min(n,self.n);b=self.f.read(n);self.n-=len(b);self.h.update(b)
  if self.name not in allow and SECRET.search(self.carry+b):raise ValueError('Credential pattern detected during capture; abort archive and quarantine locally')
  self.carry=(self.carry+b)[-256:];return b

chunks=Chunks();count=0;bytes_=0;prior_hash={};manifest=OUT/'manifests'/f'{GROUP}-files.jsonl.gz'
with gzip.open(manifest,'wt',compresslevel=1) as records,tarfile.open(fileobj=chunks,mode='w|gz',compresslevel=1,format=tarfile.PAX_FORMAT) as tar:
 for f in selected:
  name=str(f.relative_to(WORK)) if f.is_relative_to(WORK) else str(f.relative_to(ROOT));before=f.lstat();info=tar.gettarinfo(str(f),arcname=name);record={'path':name,'type':'file','bytes':before.st_size,'mtime_ns':before.st_mtime_ns}
  if stat.S_ISREG(before.st_mode):
   if info.islnk():tar.addfile(info);record.update(type='hardlink',target=info.linkname,sha256=prior_hash[info.linkname])
   else:
    with f.open('rb') as raw:
     reader=Hashed(raw,info.size,name)
     try:tar.addfile(info,reader)
     except ValueError as e:raise ValueError('Credential-pattern scan stopped at '+name) from e
     assert reader.n==0;record['sha256']=reader.h.hexdigest()
     if name in allow:assert record['sha256']==allow[name]['sha256'],name
   prior_hash[name]=record['sha256'];bytes_+=before.st_size
  elif stat.S_ISLNK(before.st_mode):
   target=os.readlink(f);record['original_target']=target
   if target.startswith('/workspace/'):target=posixpath.relpath(target[len('/workspace/'):],posixpath.dirname(name))
   info.linkname=target;tar.addfile(info);record.update(type='symlink',stored_target=target)
  else:tar.addfile(info);record['type']='directory'
  after=f.lstat();record['changed_during_read']=(before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns)
  if record['changed_during_read']:changed.append(name)
  records.write(json.dumps(record,separators=(',',':'))+'\n');count+=1
  if count%10000==0:print(json.dumps({'phase':'packing','files':count,'bytes':bytes_}),flush=True)
chunks.finish();deleted=[n for n in old if n not in seen and not (ROOT/n).exists()]
audit={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Workspace data, all supplied projects, Git refs/history, installed workspace toolchains/caches, current research delta. Not VM image or account/session backup.','checked_files':checked,'previously_covered_same_size_and_mtime':unchanged,'previous_sha_audit':'Prior full-content audit compared baseline SHA256 and verified 482240 unchanged file entries before scanner false-positive; subsequent audit compares exact size and mtime, changed files are captured and hashed anew','supplement_members':count,'supplement_bytes':bytes_,'changed_during_read':changed,'deleted_since_previous_snapshot':deleted,'excluded':excluded,'external_system_links':links,'public_fixture_proofs':allow,'repositories':git_records,'capture_atomic':False,'system_image_reproducibility':'Package inventory only outside /workspace; credentials and authenticated model state intentionally excluded.'}
(OUT/'manifests/workspace-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
m={'group':GROUP,'files':count,'uncompressed_bytes':bytes_,'parts':chunks.parts,'file_manifest':str(manifest.relative_to(OUT)),'changed_during_read':changed,'duration_seconds':round(time.time()-started),'exclusions':excluded}
(OUT/'manifests'/f'{GROUP}.json').write_text(json.dumps(m,indent=2)+'\n')
print(json.dumps({'phase':'complete','files':count,'bytes':bytes_,'compressed_bytes':sum(p['bytes'] for p in chunks.parts),'parts':len(chunks.parts),'changed':len(changed)}),flush=True)

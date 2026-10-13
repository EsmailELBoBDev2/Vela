#!/usr/bin/env python3
import pathlib,json,gzip,os,stat,tarfile,hashlib,time,datetime,ast,posixpath,re
ROOT=pathlib.Path('/workspace');OUT=ROOT/'research-release-upload';WORK=ROOT/'work/complete-backup';GROUP='workspace-final-overlay';LIMIT=32*1024*1024
old={}
for g in json.loads((OUT/'manifests/snapshot-index.json').read_text())['groups']:
 with gzip.open(OUT/'manifests'/f'{g}-files.jsonl.gz','rt') as rows:
  for row in rows:
   r=json.loads(row);old[r['path']]=r
allow={e['path']:{'sha256':e['sha256']} for e in json.loads((WORK/'extra-files.json').read_text())}
source=ast.parse((OUT/'scripts/pack_workspace.py').read_text());needed=[]
for n in source.body:
 if isinstance(n,ast.ClassDef) and n.name in ['Chunks','Hashed']:needed.append(n)
 if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SECRET' for t in n.targets):needed.append(n)
exec(compile(ast.Module(body=needed,type_ignores=[]),'<backup-writer-components>','exec'))
selected=[];seen=set();R=ROOT/'cairodrive-research'
def add(f,force=False):
 name=str(f.relative_to(ROOT));st=f.lstat();prior=old.get(name)
 if name in seen:return
 seen.add(name)
 if not force and prior and (st.st_size,st.st_mtime_ns)==(prior['bytes'],prior['mtime_ns']):return
 if f.is_file() or f.is_symlink():selected.append(f)
for cur,dirs,files in os.walk(R,followlinks=False):
 cur=pathlib.Path(cur)
 dirs[:]=[d for d in dirs if d!='.git' and not str((cur/d).relative_to(R)).startswith(('continuity/state','continuity/logs'))]
 for d in list(dirs):
  f=cur/d
  if f.is_symlink():add(f);dirs.remove(d)
 for n in sorted(files):
  f=cur/n
  if n in ['auth.json','.env','.env.local','credentials.json','id_rsa','id_ed25519','.netrc','.npmrc'] and str(f.relative_to(ROOT)) not in allow:continue
  add(f)
for e in json.loads((WORK/'extra-files.json').read_text()):add(ROOT/e['path'],True)
proof=WORK/'final-overlay-fixture-proof.json';proof.write_text((WORK/'extra-files.json').read_text());selected.append(proof)
generated={proof:'workspace-environment/final-overlay-fixture-proof.json'}
for filename,arcname in [('workspace-git-history/repositories.json','workspace-git-history/repositories.json'),('workspace-environment/git-restore.py','workspace-environment/git-restore.py'),('standalone-bundle-verification.json','workspace-environment/standalone-bundle-verification.json')]:
 f=WORK/filename;selected.append(f);generated[f]=arcname
started=time.time();chunks=Chunks();count=0;bytes_=0;changed=[];prior_hash={};path=OUT/'manifests'/f'{GROUP}-files.jsonl.gz'
with gzip.open(path,'wt',compresslevel=1) as records,tarfile.open(fileobj=chunks,mode='w|gz',compresslevel=1,format=tarfile.PAX_FORMAT) as tar:
 for f in selected:
  name=generated.get(f,str(f.relative_to(ROOT)));before=f.lstat();info=tar.gettarinfo(str(f),arcname=name);captured=f
  if stat.S_ISREG(before.st_mode) and not info.islnk():
   captured=WORK/'stable-capture.bin'
   for attempt in range(10):
    before=f.lstat()
    with f.open('rb') as src,captured.open('wb') as dst:
     for b in iter(lambda:src.read(1024*1024),b''):dst.write(b)
    copied=f.lstat()
    if (before.st_size,before.st_mtime_ns)==(copied.st_size,copied.st_mtime_ns) and captured.stat().st_size==before.st_size:break
    time.sleep(0.25)
   else:raise RuntimeError('Could not obtain stable file capture: '+name)
   info.size=before.st_size;info.mtime=before.st_mtime
  r={'path':name,'type':'file','bytes':before.st_size,'mtime_ns':before.st_mtime_ns}
  if stat.S_ISREG(before.st_mode):
   if info.islnk():tar.addfile(info);r.update(type='hardlink',target=info.linkname,sha256=prior_hash[info.linkname])
   else:
    with captured.open('rb') as raw:
     reader=Hashed(raw,info.size,name);tar.addfile(info,reader);assert reader.n==0;r['sha256']=reader.h.hexdigest()
     if name in allow:assert r['sha256']==allow[name]['sha256'],name
   prior_hash[name]=r['sha256'];bytes_+=before.st_size
  elif stat.S_ISLNK(before.st_mode):
   target=os.readlink(f)
   if target.startswith('/workspace/'):target=posixpath.relpath(target[len('/workspace/'):],posixpath.dirname(name))
   info.linkname=target;tar.addfile(info);r.update(type='symlink',stored_target=target)
  else:continue
  after=f.lstat();r['changed_after_stable_capture']=(before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns);r['changed_during_read']=False
  if r['changed_during_read']:changed.append(name)
  records.write(json.dumps(r,separators=(',',':'))+'\n');count+=1
chunks.finish();m={'group':GROUP,'files':count,'uncompressed_bytes':bytes_,'parts':chunks.parts,'file_manifest':str(path.relative_to(OUT)),'changed_during_read':changed,'capture_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'restore_order':'Last, after workspace-supplement; completes public fixtures and decompiler outputs previously misclassified by basename and captures fresh research updates','duration_seconds':round(time.time()-started)}
(OUT/'manifests'/f'{GROUP}.json').write_text(json.dumps(m,indent=2)+'\n');print(json.dumps({'group':GROUP,'members':count,'compressed_bytes':sum(p['bytes'] for p in chunks.parts),'parts':len(chunks.parts),'changed':changed}),flush=True)

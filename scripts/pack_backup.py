#!/usr/bin/env python3
import argparse,collections,hashlib,io,json,os,pathlib,posixpath,stat,tarfile,time,gzip
P=pathlib.Path('/workspace');R=P/'cairodrive-research';OUT=P/'research-backup-upload'
EXCLUDED_PREFIXES=['continuity/state/','continuity/logs/']
SECRET_NAMES={'auth.json','.env','.env.local','credentials.json','id_rsa','id_ed25519','.netrc','.npmrc'}
class Chunks:
 def __init__(self,name):self.name=name;self.limit=512*1024*1024;self.parts=[];self.fd=None;self.size=0;self.digest=None
 def write(self,b):
  total=len(b)
  while b:
   if self.fd is None:
    self.path=OUT/'payloads'/f'{self.name}.tar.gz.{len(self.parts)+1:03}.part';self.fd=self.path.open('wb');self.digest=hashlib.sha256();self.size=0
   n=min(len(b),self.limit-self.size);chunk=b[:n];self.fd.write(chunk);self.digest.update(chunk);self.size+=n;b=b[n:]
   if self.size==self.limit:self.finish()
  return total
 def flush(self):
  if self.fd:self.fd.flush()
 def finish(self):
  if self.fd:
   self.fd.flush();os.fsync(self.fd.fileno());self.fd.close();self.parts.append({'path':str(self.path.relative_to(OUT)),'bytes':self.size,'sha256':self.digest.hexdigest()});self.fd=None
class Hashed:
 def __init__(self,f,n):self.f=f;self.remaining=n;self.digest=hashlib.sha256()
 def read(self,n=-1):
  n=self.remaining if n<0 else min(n,self.remaining);b=self.f.read(n);self.remaining-=len(b);self.digest.update(b);return b

def skip(path):
 try:rel=str(path.relative_to(R))
 except ValueError:rel=''
 return any(rel.startswith(x) for x in EXCLUDED_PREFIXES) or path.name in SECRET_NAMES or '.git' in path.parts or '__pycache__' in path.parts

def paths(root):
 if root.is_file() or root.is_symlink():yield root;return
 for current,dirs,files in os.walk(root,followlinks=False):
  current=pathlib.Path(current);kept=[]
  for d in sorted(dirs):
   f=current/d
   if skip(f):continue
   if f.is_symlink():yield f
   else:kept.append(d)
  dirs[:]=kept
  for name in sorted(files):
   f=current/name
   if not skip(f):yield f

def roots(group):
 if group=='latest-overlay':
  old={}
  for m in (OUT/'manifests').glob('*-files.jsonl.gz'):
   if m.name.startswith('latest-overlay'):continue
   with gzip.open(m,'rt') as f:
    for line in f:
     r=json.loads(line);old[r['path']]=r
  chosen=[]
  scanroots=[R]+[P/'tools'/x for x in ['ghidra-vela-usdot-isolated','rea-source-candidate','blutter-dart313-fix','blutter-here-isolated'] if (P/'tools'/x).exists()]
  for root in scanroots:
   for f in paths(root):
    name=str(f.relative_to(P));st=f.lstat();prior=old.get(name)
    if not prior or (st.st_size,st.st_mtime_ns)!=(prior['bytes'],prior['mtime_ns']):chosen.append(f)
  return chosen
 if group=='inputs':return [R/'originals',R/'extracted',R/'inputs']
 if group=='google-apk':return [R/'apps/com.google.android.apps.maps/apk']
 if group=='google-native':return [R/'apps/com.google.android.apps.maps/native-data']
 if group=='google-other':return [x for x in (R/'apps/com.google.android.apps.maps').iterdir() if x.name not in ['apk','native-data']]
 if group=='research-state':return [x for x in R.iterdir() if x.name not in ['apps','originals','extracted','inputs','work']]
 if group=='scratch-and-tool-fixes':return [R/'work']+[P/'tools'/x for x in ['ghidra-vela-usdot-isolated','rea-source-candidate','blutter-dart313-fix','blutter-here-isolated'] if (P/'tools'/x).exists()]
 raise ValueError(group)

def run(group):
 start=time.time();chunks=Chunks(group);manifest=OUT/'manifests'/f'{group}-files.jsonl.gz';count=0;bytes_=0;changes=[];excluded=[];archive_duplicates={};prior_hashes={}
 for prefix in EXCLUDED_PREFIXES:excluded.append({'path':str(R/prefix),'reason':'Runtime/model databases or logs may carry account/session configuration; restore from sanitized checkpoints and documented new login.'})
 with gzip.open(manifest,'wt',compresslevel=1) as records,tarfile.open(fileobj=chunks,mode='w|gz',compresslevel=1,format=tarfile.PAX_FORMAT) as tar:
  for root in sorted(roots(group)):
   for f in paths(root):
    name=str(f.relative_to(P));before=f.lstat();info=tar.gettarinfo(str(f),arcname=name);entry={'path':name,'type':'file','bytes':before.st_size,'mtime_ns':before.st_mtime_ns}
    if stat.S_ISLNK(before.st_mode):
     target=os.readlink(f);entry.update(type='symlink',original_target=target)
     if target.startswith('/workspace/'):
      target=posixpath.relpath(target[len('/workspace/'):],posixpath.dirname(name))
     info.linkname=target;tar.addfile(info);entry['stored_target']=target
    elif stat.S_ISREG(before.st_mode):
     # Uploaded zip duplicates are aliases, retained as tar hard links after hash proof.
     prehash=None
     if f.parent==R/'originals':
      h=hashlib.sha256()
      with f.open('rb') as raw:
       for b in iter(lambda:raw.read(4*1024*1024),b''):h.update(b)
      prehash=h.hexdigest()
     if prehash and prehash in archive_duplicates:
      info.type=tarfile.LNKTYPE;info.linkname=archive_duplicates[prehash];info.size=0;tar.addfile(info);entry.update(type='hardlink',target=info.linkname,sha256=prehash)
     elif info.islnk():
      tar.addfile(info);entry.update(type='hardlink',target=info.linkname,sha256=prior_hashes[info.linkname])
     else:
      with f.open('rb') as raw:
       reader=Hashed(raw,info.size);tar.addfile(info,reader);entry['sha256']=reader.digest.hexdigest()
       if reader.remaining:raise IOError('Truncated live file:'+name)
      if prehash:assert entry['sha256']==prehash;archive_duplicates[prehash]=name
     prior_hashes[name]=entry['sha256'];bytes_+=before.st_size
    else:excluded.append({'path':name,'reason':'Nonregular runtime object'});continue
    after=f.lstat();entry['changed_during_read']=(before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns)
    if entry['changed_during_read']:changes.append(name)
    records.write(json.dumps(entry,separators=(',',':'))+'\n');count+=1
    if count%20000==0:print(json.dumps({'group':group,'files':count,'uncompressed_bytes':bytes_,'elapsed_seconds':round(time.time()-start)}),flush=True)
 chunks.finish();r={'group':group,'files':count,'uncompressed_bytes':bytes_,'parts':chunks.parts,'file_manifest':str(manifest.relative_to(OUT)),'changed_during_read':changes,'exclusions':excluded,'duration_seconds':round(time.time()-start),'snapshot_scope':'Per-file capture of live research, not a stopped/atomic application transaction; original inputs immutable. Reconcile fresh checkpoints before restoring native projects.'};(OUT/'manifests'/f'{group}.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({'group':group,'done':True,'files':count,'compressed_bytes':sum(x['bytes'] for x in chunks.parts),'changed_files':len(changes),'seconds':r['duration_seconds']}),flush=True)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('group');run(ap.parse_args().group)

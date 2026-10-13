#!/usr/bin/env python3
import argparse,pathlib,json,gzip,hashlib,tarfile,urllib.request,time,datetime,subprocess,os
ROOT=pathlib.Path(__file__).resolve().parents[1]
a=argparse.ArgumentParser();a.add_argument('--group',required=True);a.add_argument('--commit');a.add_argument('--follow-upload',action='store_true');a.add_argument('--extract-prefix',action='append',default=[]);a.add_argument('--destination');a=a.parse_args();dest=pathlib.Path(a.destination).resolve() if a.destination else None
if dest:
 dest.mkdir(parents=True,exist_ok=True)
 if any(dest.iterdir()):raise ValueError('Extraction test destination must be empty')
commit=a.commit or subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();m=json.loads((ROOT/'manifests'/f'{a.group}.json').read_text())
class Remote:
 def __init__(self):self.i=0;self.data=b'';self.pos=0;self.proofs=[]
 def next(self):
  if self.i==len(m['parts']):return False
  p=m['parts'][self.i];part_commit=commit
  if a.follow_upload:
   deadline=time.time()+600
   while True:
    status=json.loads((ROOT/'git-upload-status.json').read_text());part_commit=status['commit']
    exists=subprocess.run(['git','cat-file','-e',part_commit+':'+p['path']],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    if exists:break
    if time.time()>deadline:raise TimeoutError('Uploader did not publish next part: '+p['path'])
    time.sleep(2)
  url=f"https://raw.githubusercontent.com/EsmailELBoBDev2/Vela/{part_commit}/{p['path']}"
  for attempt in range(4):
   try:
    with urllib.request.urlopen(url,timeout=120) as f:data=f.read(p['bytes']+1)
    if len(data)!=p['bytes'] or hashlib.sha256(data).hexdigest()!=p['sha256']:raise ValueError('Remote part size/hash mismatch: '+p['path'])
    break
   except Exception:
    if attempt==3:raise
    time.sleep(5)
  self.proofs.append(dict(p,verified_commit=part_commit));self.i+=1;self.data=data;self.pos=0;print(json.dumps({'group':a.group,'remote_parts_verified':self.i,'total_parts':len(m['parts'])}),flush=True);return True
 def read(self,n=-1):
  if n<0:n=1024*1024
  out=bytearray()
  while len(out)<n:
   if self.pos==len(self.data) and not self.next():break
   size=min(n-len(out),len(self.data)-self.pos);out.extend(self.data[self.pos:self.pos+size]);self.pos+=size
  return bytes(out)
r=Remote();seen={};count=0
with gzip.open(ROOT/m['file_manifest'],'rt') as rows,tarfile.open(fileobj=r,mode='r|gz') as tar:
 for member in tar:
  rec=json.loads(next(rows));assert rec['path']==member.name;path=pathlib.PurePosixPath(member.name);assert not path.is_absolute() and '..' not in path.parts
  selected=dest is not None and any(member.name.startswith(prefix) for prefix in a.extract_prefix)
  if member.isfile():
   h=hashlib.sha256();f=tar.extractfile(member);out=None
   if selected:
    target=dest/path;target.parent.mkdir(parents=True,exist_ok=True)
    if not target.parent.resolve().is_relative_to(dest):raise ValueError('Extraction parent escapes test workspace')
    out=target.open('wb')
   try:
    for b in iter(lambda:f.read(1024*1024),b''):
     h.update(b)
     if out:out.write(b)
   finally:
    if out:out.close();os.chmod(target,member.mode & 0o777)
   assert h.hexdigest()==rec['sha256'],member.name;seen[member.name]=rec['sha256']
  elif member.islnk():
   assert seen[member.linkname]==rec['sha256'];seen[member.name]=rec['sha256']
   if selected:tar.extract(member,path=dest,filter='data')
  elif member.issym():
   assert member.linkname==rec['stored_target']
   if selected:tar.extract(member,path=dest,filter='data')
  elif selected:tar.extract(member,path=dest,filter='data')
  count+=1
  if count%10000==0:print(json.dumps({'group':a.group,'remote_archive_members_verified':count}),flush=True)
 assert next(rows,None) is None
while r.read(1024*1024):pass
assert count==m['files'] and len(r.proofs)==len(m['parts'])
receipt={'verified_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'group':a.group,'data_commit':json.loads((ROOT/'git-upload-status.json').read_text())['commit'] if a.follow_upload else commit,'verification_method':'SHA256-verified complete remote archive; each part downloaded at recorded immutable published commit','remote_part_sha256_all_verified':True,'archive_member_sha256_all_verified':True,'verified_parts':len(r.proofs),'verified_members':count,'verified_bytes':sum(p['bytes'] for p in r.proofs),'parts':r.proofs,'selective_remote_restore_prefixes':a.extract_prefix,'selective_restore_destination':str(dest) if dest else None}
(ROOT/'manifests'/f'{a.group}-remote-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'state':'full_remote_archive_verified','group':a.group,'parts':len(r.proofs),'members':count,'bytes':receipt['verified_bytes']}),flush=True)

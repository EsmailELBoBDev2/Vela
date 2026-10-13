#!/usr/bin/env python3
import argparse,gzip,hashlib,json,pathlib,tarfile,sys,collections,re
REPO=pathlib.Path(__file__).resolve().parents[1]
class Joined:
 def __init__(self,paths):self.paths=iter(paths);self.fd=None
 def read(self,n=-1):
  if n<0:n=1024*1024
  out=bytearray()
  while len(out)<n:
   if self.fd is None:
    try:self.fd=next(self.paths).open('rb')
    except StopIteration:break
   b=self.fd.read(n-len(out))
   if b:out.extend(b)
   else:self.fd.close();self.fd=None
  return bytes(out)
 def close(self):
  if self.fd:self.fd.close()

def digest_file(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()

def verify(group,destination=None):
 m=json.loads((REPO/'manifests'/f'{group}.json').read_text());parts=[REPO/x['path'] for x in m['parts']]
 for f,rec in zip(parts,m['parts']):
  if f.stat().st_size!=rec['bytes'] or digest_file(f)!=rec['sha256']:raise ValueError('LFS part integrity failure:'+str(f))
 joined=Joined(parts);n=0;restored=[];seen_hashes={}
 with gzip.open(REPO/m['file_manifest'],'rt') as rows,tarfile.open(fileobj=joined,mode='r|gz') as archive:
  for member in archive:
   record=json.loads(next(rows));assert member.name==record['path'],(member.name,record['path']);path=pathlib.PurePosixPath(member.name)
   if path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe archive path')
   if member.isfile():
    h=hashlib.sha256();reader=archive.extractfile(member);carry=b""
    if destination:
     target=destination/path;target.parent.mkdir(parents=True,exist_ok=True);out=target.open('wb')
    else:out=None
    try:
     for b in iter(lambda:reader.read(1024*1024),b''):
      h.update(b)
      if member.name.startswith(("cairodrive-research/continuity/","cairodrive-research/work/")):
       window=carry+b
       if re.search(rb"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|[\"\']access_token[\"\']\s*:\s*[\"\']eyJ)",window):raise ValueError("Possible runtime credential in captured file: "+member.name)
       carry=window[-256:]
      if out:out.write(b)
    finally:
     if out:out.close()
    if h.hexdigest()!=record['sha256']:raise ValueError('File integrity failure:'+member.name)
    seen_hashes[member.name]=record['sha256']
   elif member.islnk():
    if seen_hashes.get(member.linkname)!=record.get('sha256'):raise ValueError('Hardlink integrity failure:'+member.name)
    seen_hashes[member.name]=record['sha256']
    if destination:archive.extract(member,path=destination,filter='data')
   elif member.issym():
    if member.linkname!=record.get('stored_target'):raise ValueError('Symlink target mismatch:'+member.name)
    if destination:archive.extract(member,path=destination,filter='data')
   elif destination:
    archive.extract(member,path=destination,filter='data')
   n+=1
  if next(rows,None) is not None:raise ValueError('Manifest has extra rows')
 joined.close();assert n==m['files'];return {'group':group,'verified_members':n,'compressed_bytes':sum(x['bytes'] for x in m['parts']),'captured_live_changes':len(m.get('changed_during_read',[]))}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--verify-only',action='store_true');ap.add_argument('--destination');ap.add_argument('--group',action='append');a=ap.parse_args()
 if not a.verify_only and not a.destination:ap.error('Choose --verify-only or --destination NEW_EMPTY_WORKSPACE')
 dest=pathlib.Path(a.destination).resolve() if a.destination else None
 if dest:
  dest.mkdir(parents=True,exist_ok=True)
  if any(dest.iterdir()):ap.error('Destination must be empty; never overwrite existing research or app inputs')
 groups=a.group or json.loads((REPO/'manifests/snapshot-index.json').read_text())['groups']
 results=[]
 for g in groups:
  r=verify(g,dest);results.append(r);print(json.dumps(r),flush=True)
 if dest:
  runtime=dest/'cairodrive-research/continuity';history=runtime/'restored-runtime-history';history.mkdir(exist_ok=True)
  for f in list(runtime.glob('*.pid'))+[runtime/'standalone-enabled',runtime/'research-thread.json',runtime/'worker-active.json',runtime/'watchdog-status.json',runtime/'guard-status.json']:
   if f.exists():f.rename(history/f.name)
  print('Restored exact archived bytes, then disarmed runtime and retained old process/thread records. Log in normally and reconcile checkpoints before starting new workers.')
 return results
if __name__=='__main__':main()

#!/usr/bin/env python3
import hashlib,json,pathlib,time
P=pathlib.Path(__file__).resolve().parents[1];SOURCE=pathlib.Path('/workspace/research-backup-upload');index=json.loads((P/'manifests/snapshot-index.json').read_text());(P/'payloads').mkdir(exist_ok=True);limit=32*1024*1024;total=0
for group in index['groups']:
 old=json.loads((SOURCE/'manifests'/f'{group}.json').read_text());parts=[];out=None;size=0;h=None
 def finish():
  global out
  if out:
   out.flush();out.close();parts.append({'path':str(path.relative_to(P)),'bytes':size,'sha256':h.hexdigest()});out=None
 for record in old['parts']:
  raw=SOURCE/record['path'];check=hashlib.sha256()
  with raw.open('rb') as f:
   for data in iter(lambda:f.read(4*1024*1024),b''):
    check.update(data)
    while data:
     if out is None:
      path=P/'payloads'/f'{group}.tar.gz.{len(parts)+1:03}.part';out=path.open('wb');size=0;h=hashlib.sha256()
     n=min(len(data),limit-size);chunk=data[:n];out.write(chunk);h.update(chunk);size+=n;data=data[n:]
     if size==limit:finish()
  assert check.hexdigest()==record['sha256']
 finish();old['parts']=parts;(P/'manifests'/f'{group}.json').write_text(json.dumps(old,indent=2)+'\n');total+=len(parts);print(json.dumps({'group':group,'new_parts':len(parts),'bytes':sum(r['bytes'] for r in parts)}),flush=True)
index.update(storage_backend='Regular Git, verified 32MiB archive chunks; LFS/release upload unavailable with current integration',part_limit_bytes=limit,total_parts=total,release_tag=None,release_url=None,failed_release_attempt='cairodrive-research-backup-20261013T211124',release_upload_failure='uploads.github.com returned401 while Git and metadata API work');(P/'manifests/snapshot-index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n');print('All sources checked, new part boundaries hashed; archive byte stream unchanged.')

#!/usr/bin/env python3
import pathlib,json,subprocess,time,datetime,hashlib,argparse
a=argparse.ArgumentParser();a.add_argument("--delete-staging-after-push",action="store_true");options=a.parse_args()
ROOT=pathlib.Path(__file__).resolve().parents[1]
def run(*args):
 return subprocess.run(args,cwd=ROOT,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT).stdout
idx=json.loads((ROOT/'manifests/snapshot-index.json').read_text());parts=[]
for g in ['research-state']+[g for g in idx['groups'] if g!='research-state']:
 parts.extend(json.loads((ROOT/'manifests'/f'{g}.json').read_text())['parts'])
tracked=set(run('git','ls-files','payloads').splitlines());pending=[p for p in parts if p['path'] not in tracked]
def push():
 for attempt in range(6):
  try:
   print(run('git','push','origin','HEAD:research-backup'),flush=True);return
  except subprocess.CalledProcessError as e:
   print(e.stdout,flush=True)
   if attempt==5:raise
   time.sleep(min(10*(attempt+1),50))
push()
while pending:
 batch=pending[:8];pending=pending[8:]
 run('git','add','--',*[p['path'] for p in batch]);run('git','commit','-m',f"Archive research backup parts: {len(parts)-len(pending)}/{len(parts)}")
 push();tracked.update(p['path'] for p in batch)
 if options.delete_staging_after_push:
  for p in batch:
   f=ROOT/p['path'];h=hashlib.sha256()
   with f.open('rb') as source:
    for b in iter(lambda:source.read(4*1024*1024),b''):h.update(b)
   assert h.hexdigest()==p['sha256'] and f.stat().st_size==p['bytes']
   assert run('git','hash-object',p['path']).strip()==run('git','rev-parse','HEAD:'+p['path']).strip()
   run('git','update-index','--skip-worktree','--',p['path']);f.unlink()
 done=[p for p in parts if p['path'] in tracked]
 status={'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'uploaded_parts':len(done),'total_parts':len(parts),'uploaded_bytes':sum(p['bytes'] for p in done),'total_bytes':sum(p['bytes'] for p in parts),'commit':run('git','rev-parse','HEAD').strip(),'state':'complete' if not pending else 'uploading'}
 (ROOT/'git-upload-status.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status),flush=True)
 if pending:time.sleep(13)

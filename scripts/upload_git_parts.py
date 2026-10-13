#!/usr/bin/env python3
import pathlib,json,subprocess,time,datetime
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
 batch=pending[:4];pending=pending[4:]
 run('git','add','--',*[p['path'] for p in batch]);run('git','commit','-m',f"Archive research backup parts: {len(parts)-len(pending)}/{len(parts)}")
 push();tracked.update(p['path'] for p in batch)
 done=[p for p in parts if p['path'] in tracked]
 status={'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'uploaded_parts':len(done),'total_parts':len(parts),'uploaded_bytes':sum(p['bytes'] for p in done),'total_bytes':sum(p['bytes'] for p in parts),'commit':run('git','rev-parse','HEAD').strip(),'state':'complete' if not pending else 'uploading'}
 (ROOT/'git-upload-status.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status),flush=True)
 if pending:time.sleep(13)

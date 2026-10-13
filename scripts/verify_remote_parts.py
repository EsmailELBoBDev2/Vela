#!/usr/bin/env python3
import concurrent.futures,hashlib,json,pathlib,subprocess,time,urllib.request,datetime
root=pathlib.Path(__file__).resolve().parents[1]
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
idx=json.loads((root/'manifests/snapshot-index.json').read_text());parts=[]
for g in idx['groups']:parts.extend(json.loads((root/'manifests'/f'{g}.json').read_text())['parts'])
def verify(p):
 url=f"https://raw.githubusercontent.com/EsmailELBoBDev2/Vela/{commit}/{p['path']}"
 for attempt in range(4):
  try:
   h=hashlib.sha256();n=0
   with urllib.request.urlopen(url,timeout=120) as response:
    for b in iter(lambda:response.read(1024*1024),b''):h.update(b);n+=len(b)
   if n!=p['bytes'] or h.hexdigest()!=p['sha256']:raise ValueError('Remote bytes/hash mismatch: '+p['path'])
   return {'path':p['path'],'bytes':n,'sha256':h.hexdigest()}
  except Exception:
   if attempt==3:raise
   time.sleep(5)
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for f in concurrent.futures.as_completed([pool.submit(verify,p) for p in parts]):
  r=f.result();results.append(r);print(json.dumps({'verified':len(results),'total':len(parts),'part':r['path']}),flush=True)
receipt={'verified_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'commit':commit,'method':'Independent HTTPS streaming download of every part at immutable Git commit; size and SHA256 checked','verified_parts':len(results),'verified_bytes':sum(r['bytes'] for r in results),'parts':sorted(results,key=lambda x:x['path'])}
(root/'manifests/remote-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'state':'all_remote_parts_verified','parts':len(results),'bytes':receipt['verified_bytes'],'commit':commit}),flush=True)

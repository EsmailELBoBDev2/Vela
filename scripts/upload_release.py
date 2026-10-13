#!/usr/bin/env python3
import concurrent.futures,fcntl,hashlib,json,os,pathlib,subprocess,sys,time
P=pathlib.Path(__file__).resolve().parents[1];SOURCE=pathlib.Path('/workspace/research-backup-upload');INDEX=json.loads((P/'manifests/snapshot-index.json').read_text());TAG=INDEX['release_tag'];REPO=INDEX['release_repository'];lock=(P/'.upload.lock').open('a')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:raise SystemExit('Release upload already owned')
log=(P/'upload-release.log').open('a',buffering=1)
def status(phase,**kw):(P/'upload-status.json').write_text(json.dumps({'pid':os.getpid(),'phase':phase,'updated':time.time(),**kw},indent=2)+'\n')
def command(args):
 r=subprocess.run(args,capture_output=True,text=True);log.write(json.dumps({'command':args,'exit':r.returncode,'stdout':r.stdout[-1500:],'stderr':r.stderr[-2000:]})+'\n')
 if r.returncode:raise RuntimeError(args[0]+':'+r.stderr[-600:])
 return r.stdout
parts=[]
for group in INDEX['groups']:parts+=json.loads((P/'manifests'/f'{group}.json').read_text())['parts']
release=next(r for r in json.loads(command(['gh','api',f'repos/{REPO}/releases'])) if r['tag_name']==TAG);RID=release['id']
def assets():return json.loads(command(['gh','api',f'repos/{REPO}/releases/{RID}/assets','--paginate']))
def upload(rec):
 name=pathlib.Path(rec['path']).name;existing={x['name']:x for x in assets()}
 if name in existing:
  obj=existing[name]
  if obj['size']==rec['bytes'] and obj.get('digest')=='sha256:'+rec['sha256'] and obj['state']=='uploaded':return name
  raise RuntimeError('Unexpected existing asset; no overwrite:'+name)
 for attempt in range(3):
  try:command(['gh','release','upload',TAG,str(SOURCE/rec['path']),'--repo',REPO]);return name
  except Exception as e:
   log.write(json.dumps({'asset':name,'attempt':attempt+1,'error':str(e)})+'\n')
   if attempt==2:raise
   time.sleep(2**(attempt+1))
try:
 first=next(x for x in parts if pathlib.Path(x['path']).name.startswith('research-state.'));status('uploading_first_research_state_asset',total=len(parts));done=[upload(first)];remaining=[x for x in parts if x!=first]
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  tasks={pool.submit(upload,r):r for r in remaining};status('uploading_archive_assets',completed=len(done),total=len(parts))
  for task in concurrent.futures.as_completed(tasks):
   done.append(task.result());status('uploading_archive_assets',completed=len(done),total=len(parts),last_asset=done[-1])
 remote={x['name']:x for x in assets()};audit=[]
 for rec in parts:
  obj=remote[pathlib.Path(rec['path']).name];assert obj['state']=='uploaded' and obj['size']==rec['bytes'];digest=obj.get('digest');assert digest=='sha256:'+rec['sha256'],(obj['name'],digest);audit.append({'asset':obj['name'],'asset_id':obj['id'],'bytes':obj['size'],'sha256':rec['sha256'],'server_digest_verified':True})
 status('verifying_remote_restore',completed=len(done),total=len(parts));sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=P,text=True).strip();verify=P.parent/('research-release-remote-verify-'+sha[:10]);env=os.environ.copy();env['GIT_LFS_SKIP_SMUDGE']='1'
 r=subprocess.run(['git','-c','credential.helper=!gh auth git-credential','clone','--branch','research-backup','--single-branch','https://github.com/'+REPO+'.git',str(verify)],capture_output=True,text=True,env=env);log.write(r.stdout+r.stderr);assert r.returncode==0
 (verify/'payloads').mkdir(exist_ok=True);command(['gh','release','download',TAG,'--repo',REPO,'--pattern',pathlib.Path(first['path']).name,'--dir',str(verify/'payloads')]);r=subprocess.run(['python3','scripts/restore_backup.py','--verify-only','--group','research-state'],cwd=verify,capture_output=True,text=True);log.write(r.stdout+r.stderr);assert r.returncode==0
 command(['gh','release','edit',TAG,'--repo',REPO,'--draft=false','--prerelease'])
 final=json.loads(command(['gh','api',f'repos/{REPO}/releases/tags/{TAG}']));assert not final['draft']
 record={'repository':REPO,'branch':'research-backup','commit':sha,'release_tag':TAG,'release_url':final['html_url'],'storage_backend':'GitHub release assets (LFS public-fork restriction)','public_upload_explicitly_authorized':True,'asset_count':len(parts),'compressed_bytes':sum(x['bytes'] for x in parts),'file_entries':INDEX['total_captured_file_entries'],'all_remote_sizes_and_sha256_digests_verified':True,'independent_remote_research_state_restore_verified':True,'asset_audit':audit,'finished_at':time.time()};(P/'upload-success.json').write_text(json.dumps(record,indent=2)+'\n');status('uploaded_published_and_verified',completed=len(done),total=len(parts),release_url=final['html_url'])
 c=pathlib.Path('/workspace/cairodrive-research/continuity');(c/'EXTERNAL_BACKUP.json').write_text(json.dumps(record,indent=2)+'\n')
 with pathlib.Path('/workspace/cairodrive-research/CONTINUITY.md').open('a') as f:f.write('\nنسخةالبحثالكاملةرُفعتوتحققت:فرعresearch-backupوإصدار '+TAG+' فيVela. تخزينالأجزاءعلىGitHubReleases لأنGitLFSرفضforkعاموإنشاءريبو مستقلمنعتهصلاحيةالاتصال. جميعبصماتالأجزاءالبعيدةوأحجامهاطابقتالأصل، واسترجاعمجموعةحالةالبحثمنتنزيلبعيدمستقلاجتازالتحقق. التفاصيلcontinuity/EXTERNAL_BACKUP.json. لقطةواحدةمؤرخة،ليسترفعًاتلقائيًالكلالنتائجالمستقبلية.\n')
except Exception as e:log.write('FAILURE '+str(e)+'\n');status('failed',error=str(e));sys.exit(1)

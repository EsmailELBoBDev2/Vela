#!/usr/bin/env python3
import json,pathlib,subprocess
p=pathlib.Path(__file__).resolve().parents[1];r=json.loads((p/'manifests/snapshot-index.json').read_text());dest=p/'payloads';dest.mkdir(exist_ok=True)
subprocess.run(['gh','release','download',r['release_tag'],'--repo',r['release_repository'],'--pattern','*.part','--dir',str(dest),'--skip-existing'],check=True)
print('Downloaded archive parts; run restore_backup.py --verify-only before restoring.')

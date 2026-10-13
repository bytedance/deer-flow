"""Coordinator-only role image refresh; caller must fence admission and verify global idle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

ROOT=Path('/srv/deerflow-native-task6b/56636cebddc6')
PRIVATE=ROOT/'private/820d7a3429d9/resident'
OLD='sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338'
NEW='sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1'
PATCH='bdd2931a1a6f8f35b9eb191fb809aa38c8dae85b6e65b44c15feb3d8a6cc8a9e'

def checked(args,timeout=120):
 r=subprocess.run(args,capture_output=True,timeout=timeout);assert r.returncode==0;return r.stdout

def data(path):
 s=path.lstat();assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o600
 return path.read_bytes()

def main(role):
 assert os.getuid()==0
 assert all(not p.is_symlink() for p in [PRIVATE,*PRIVATE.parents])
 for p in [ROOT,PRIVATE.parent,PRIVATE]:
  s=p.lstat();assert stat.S_ISDIR(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o700
 image=json.loads(checked(['docker','image','inspect',NEW]))[0];assert image['Id']==NEW and image['Architecture']=='amd64'
 patch=checked(['docker','run','--rm','--cpus','0.5','--memory','512m','--network','none',NEW,'python','-c','import hashlib,ecs_executor.publication as p;print(hashlib.sha256(open(p.__file__,"rb").read()).hexdigest())']).decode().strip();assert patch==PATCH
 paths=[PRIVATE/(role+'.env'),PRIVATE/'worker-ops.json']
 if role=='controller':paths.append(PRIVATE/'controller-ops.json')
 before={p:data(p) for p in paths};after={}
 for p,b in before.items():
  if p.suffix=='.env':
   lines=b.splitlines(keepends=True);hits=[i for i,x in enumerate(lines) if x.startswith(b'ECS_ROLE_IMAGE=')];assert len(hits)==1
   i=hits[0];assert lines[i].strip().split(b'=',1)[1].decode() in [OLD,NEW]
   ending=b'\r\n' if lines[i].endswith(b'\r\n') else b'\n' if lines[i].endswith(b'\n') else b''
   lines[i]=b'ECS_ROLE_IMAGE='+NEW.encode()+ending;after[p]=b''.join(lines)
  else:
   v=json.loads(b);assert v['image'] in [OLD,NEW] and v['node_id']=='native-820d7a3429d9' and v['project']=='deer-native-820d7a3429d9-'+v['role'] and v['sandbox_prefix']=='deer-native-aio-820d7a3429d9'
   v['image']=NEW;after[p]=(json.dumps(v,indent=2)+'\n').encode()
 # Validate all inputs before retaining backups or replacing any file.
 for p,b in before.items():
  backup=p.with_name(p.name+'.before-publication-bdd2931a1a6f')
  if backup.exists() or backup.is_symlink():
   previous=data(backup)
   assert previous==b or (p.suffix=='.env' and previous.replace(OLD.encode(),NEW.encode())==after[p]) or (p.suffix=='.json' and {**json.loads(previous),'image':NEW}==json.loads(after[p]))
  else:
   fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(fd,'wb') as f:f.write(b)
  temp=p.with_name(p.name+'.publication-new');fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as f:f.write(after[p]);f.flush();os.fsync(f.fileno())
  os.replace(temp,p)
 services=['gateway','mcp'] if role=='controller' else ['resident']
 compose=['docker','compose','--project-name','deer-native-820d7a3429d9-'+role,'--env-file',str(PRIVATE/(role+'.env')),'-f',str(ROOT/'source/examples/ecs-native/deploy'/ (role+'.compose.yaml'))]
 checked([*compose,'up','-d','--no-deps','--force-recreate','--no-build','--pull','never','--wait','--wait-timeout','180',*services],timeout=240)
 results=[]
 for service in services:
  ids=checked([*compose,'ps','-q',service]).decode().splitlines();assert len(ids)==1
  item=json.loads(checked(['docker','inspect',ids[0]]))[0];h=item['HostConfig']
  assert item['Image']==NEW and item['State']['Running']
  if service!='mcp':assert item['State']['Health']['Status']=='healthy'
  socket=any(x['Destination']=='/var/run/docker.sock' for x in item['Mounts']);assert socket==(role=='worker')
  result={'role':role,'service':service,'container_id':item['Id'],'image_id':NEW,'running':True,'health':item['State'].get('Health',{}).get('Status','no_healthcheck'),'docker_socket':socket}
  result.update(cpu=h['NanoCpus'],memory=h['Memory'])
  if service=='resident':
   assert h['NanoCpus']==500000000 and h['Memory']==1073741824
   result.update(cpu=h['NanoCpus'],memory=h['Memory'])
  results.append(result)
 print(json.dumps({'publication_role_refresh':results,'models_and_credentials_unchanged':True,'admission_resumed':False}))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('role',choices=['controller','worker']);main(p.parse_args().role)

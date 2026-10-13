"""Jenkins-only publication role refresh; preserve global drain and terminal history."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import stat

ROOT=Path('/data/jenkins-agent/deerflow/native-task6b-56636cebddc6')
REMOTE='/srv/deerflow-native-task6b/56636cebddc6'
OLD='sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338'
NEW='sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1'
REFRESH_SHA='abcd8155362b70ccb39c57d1e107c07b65fa3f3d440b15f0e5d48c62df0e8014'

def main():
 helper=ROOT/'scripts/ecs_native_shanghai_bootstrap.py';assert hashlib.sha256(helper.read_bytes()).hexdigest()=='8d9f9613a0bdda49b763a5cf84c8b41d25e1e13dc351a9d4012928e88952a92a'
 spec=importlib.util.spec_from_file_location('fixed_bootstrap',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 receipt=ROOT/'proof/publication-transfer.json';info=receipt.lstat();assert stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o600
 transferred=json.loads(receipt.read_text());assert transferred['base_image_id']==OLD and transferred['patch_sha256']=='bdd2931a1a6f8f35b9eb191fb809aa38c8dae85b6e65b44c15feb3d8a6cc8a9e'
 assert len(transferred['transfers'])==2 and {v['host'] for v in transferred['transfers']}=={'192.168.0.190','192.168.0.189'} and all(v['image_id']==NEW and not v['roles_started'] for v in transferred['transfers'])
 for host in ['192.168.0.190','192.168.0.189']:
  m.copy_public(host,ROOT/'scripts/ecs_native_publication_role_refresh.py',REMOTE+'/bootstrap/ecs_native_publication_role_refresh.py',REFRESH_SHA)
 def remote(host,code,timeout=300):
  return m.run(['ssh',*m.OPTIONS,'root@'+host,'python3 -c '+shlex.quote(code)],timeout=timeout)
 operator="\nimport pathlib,json,subprocess,http.cookiejar,urllib.request,ssl\nroot=pathlib.Path('/srv/deerflow-native-task6b/56636cebddc6');private=root/'private/820d7a3429d9/resident';op=private.parent/'operator'\ncore='sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338'\ndef checked(args,timeout=120):\n r=subprocess.run(args,capture_output=True,timeout=timeout)\n if r.returncode:\n  for line in r.stdout.decode().splitlines():\n   try:value=json.loads(line)\n   except json.JSONDecodeError:continue\n   if value.get('bc_main_failed'):print(json.dumps(value),flush=True)\n  raise SystemExit('Owned native C operation refused; private output withheld')\n return r.stdout\nbase=['docker','run','--rm','--cpus','0.5','--memory','1g','--network','deer-native-820d7a3429d9-controller_control','--env-file',str(private/'controller.env'),'-e','DEER_FLOW_HOME=/srv/deerflow-native-test','-e','DEER_FLOW_CONFIG_PATH=/run/operator/native.json','-e','DEER_FLOW_EXTENSIONS_CONFIG_PATH=/run/operator/extensions.json','-v',str(private)+':/run/operator:ro','-v',str(private)+':'+str(private)+':ro','-v','/srv/deerflow-native-test:/srv/deerflow-native-test','-v',str(op/'b-extensions.json')+':/run/operator/extensions.json:ro','-v',str(op/'b-extensions.json')+':'+str(private/'extensions.json')+':ro']\ndef admission(action):\n result=checked([*base,core,'python','-m','ecs_executor.operations',action,'--config','/run/operator/worker-ops.json'])\n return json.loads(result) if action=='status' else None\ndef owner_gate():\n jar=http.cookiejar.MozillaCookieJar(str(op/'owner.cookies'));jar.load(ignore_discard=True,ignore_expires=False)\n client=urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(private/'ca.crt'))),urllib.request.HTTPCookieProcessor(jar))\n with client.open('https://192.168.0.190:2026/health/ready',timeout=20) as r:assert r.status==200\n with client.open('https://192.168.0.190:2026/api/v1/auth/me',timeout=20) as r:value=json.load(r)\n assert value['id']==json.loads((op/'owner.json').read_text())['owner_id']\n"

 def fence(image):
  code=operator.replace(OLD,image)+"""
admission('drain');assert admission('status')=={'operator_drain':True,'unreleased':0};owner_gate()
import importlib.util
s=importlib.util.spec_from_file_location('cleanup',root/'bootstrap/ecs_native_shanghai_b_cleanup_recovery.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
assert m.query('deerflow',"SELECT count(*) FROM runs WHERE status NOT IN ('success','error','timeout','interrupted');")=='0'
assert m.query('deerflow',"SELECT count(*) FROM mcp_tasks WHERE notification_status NOT IN ('none','delivered','dead_letter');")=='0'

assert m.query('deerflow',"SELECT count(*) FROM runs WHERE run_id IN ('4198c7a1-551f-4647-b850-46f4f33208d2','0317e4ae-3164-4ed1-bc29-6d8103a4685c');")=='2'
assert m.query('deerflow_execution',"SELECT count(*) FROM ecs_execution_jobs WHERE id IN ('23b863fb6ffe4be2984acbf388b7d637','5ff4f3d09700430e90957d4fe2fa4f1c','aba5367785f34ce5be59704dc7fdf8a7');")=='3'
assert m.query('deerflow',"SELECT count(*) FROM mcp_tasks WHERE id='mcp-task-b154092d129b4d65a5d1061e7c5790b9' AND status='completed' AND notification_status='dead_letter';")=='1'

print(json.dumps({'operator_drain':True,'unreleased':0,'nonterminal_native_runs':0,'pending_notifications':0}))
"""
  return json.loads(remote('192.168.0.190',code))
 before=fence(OLD)
 physical="""
import json,subprocess
r=subprocess.run(['docker','ps','--format','{{.Names}}'],capture_output=True,text=True,check=True)
assert not any(n.startswith('deerflow-exec-') for n in r.stdout.splitlines())
print(json.dumps({'worker_ordinary_job_containers':0}))
"""
 physical_before=json.loads(remote('192.168.0.189',physical))
 refreshed=[]
 for host,role in [('192.168.0.190','controller'),('192.168.0.189','worker')]:
  if role=='worker':fence(NEW);json.loads(remote(host,physical))
  code='import subprocess;r=subprocess.run(["python3",'+repr(REMOTE+'/bootstrap/ecs_native_publication_role_refresh.py')+','+repr(role)+'],capture_output=True,timeout=300);assert r.returncode==0;print(r.stdout.decode(),end="")'
  refreshed.append(json.loads(remote(host,code,timeout=330)))
 after=fence(NEW)
 remote('192.168.0.190',operator.replace(OLD,NEW)+"admission('preflight');assert admission('status')=={'operator_drain':True,'unreleased':0};owner_gate()")
 value={'publication_deployment':'PASS','image_id':NEW,'base_image_id':OLD,'patch_sha256':'bdd2931a1a6f8f35b9eb191fb809aa38c8dae85b6e65b44c15feb3d8a6cc8a9e','before':before,'after':after,'physical_before':physical_before,'roles':refreshed,'admission_resumed':False,'models_called':False,'history_preserved':True}
 fd=os.open(ROOT/'proof/publication-deployment.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f)
 print(json.dumps(value),flush=True)

if __name__=='__main__':
 try:main()
 except Exception:raise SystemExit('Owned publication deployment failed; retain state, admission remains drained') from None

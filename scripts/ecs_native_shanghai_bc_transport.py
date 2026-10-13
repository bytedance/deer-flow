"""Run one installed native goal C-to-B-to-C main with admission fences."""

import hashlib
import importlib.util
from pathlib import Path
import shlex

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
REMOTE = "/srv/deerflow-native-task6b/56636cebddc6"
CONTROLLER = "192.168.0.190"
WORKER = "192.168.0.189"
MAIN_SHA = "6c39c7c7e19d17e45d215e969e65ef9b5d25edb7e117c7f3a280684cd102f1bd"


def main():
    helper = ROOT / "scripts/ecs_native_shanghai_bootstrap.py"
    assert (
        hashlib.sha256(helper.read_bytes()).hexdigest()
        == "8d9f9613a0bdda49b763a5cf84c8b41d25e1e13dc351a9d4012928e88952a92a"
    )
    spec = importlib.util.spec_from_file_location("fixed_bootstrap", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.copy_public(
        CONTROLLER,
        ROOT / "scripts/ecs_native_shanghai_bc_main.py",
        REMOTE + "/bootstrap/ecs_native_shanghai_bc_main.py",
        MAIN_SHA,
    )

    def remote(host, code, payload=None, timeout=300):
        return module.run(
            ["ssh", *module.OPTIONS, "root@" + host, "python3 -c " + shlex.quote(code)],
            payload,
            timeout=timeout,
        )

    # Existing socket-free operator CLI and original B signed snapshot; only its
    # task admission fence changes. No worker or controller listener is added.
    operator = r"""
import pathlib,json,subprocess,http.cookiejar,urllib.request,ssl
root=pathlib.Path('/srv/deerflow-native-task6b/56636cebddc6');private=root/'private/820d7a3429d9/resident';op=private.parent/'operator'
core='sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338'
def checked(args,timeout=120):
 r=subprocess.run(args,capture_output=True,timeout=timeout)
 if r.returncode:
  for line in r.stdout.decode().splitlines():
   try:value=json.loads(line)
   except json.JSONDecodeError:continue
   if value.get('bc_main_failed'):print(json.dumps(value),flush=True)
  raise SystemExit('Owned native C operation refused; private output withheld')
 return r.stdout
base=['docker','run','--rm','--cpus','0.5','--memory','1g','--network','deer-native-820d7a3429d9-controller_control','--env-file',str(private/'controller.env'),'-e','DEER_FLOW_HOME=/srv/deerflow-native-test','-e','DEER_FLOW_CONFIG_PATH=/run/operator/native.json','-e','DEER_FLOW_EXTENSIONS_CONFIG_PATH=/run/operator/extensions.json','-v',str(private)+':/run/operator:ro','-v',str(private)+':'+str(private)+':ro','-v','/srv/deerflow-native-test:/srv/deerflow-native-test','-v',str(op/'b-extensions.json')+':/run/operator/extensions.json:ro','-v',str(op/'b-extensions.json')+':'+str(private/'extensions.json')+':ro']
def admission(action):
 result=checked([*base,core,'python','-m','ecs_executor.operations',action,'--config','/run/operator/worker-ops.json'])
 return json.loads(result) if action=='status' else None
def owner_gate():
 jar=http.cookiejar.MozillaCookieJar(str(op/'owner.cookies'));jar.load(ignore_discard=True,ignore_expires=False)
 client=urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(private/'ca.crt'))),urllib.request.HTTPCookieProcessor(jar))
 with client.open('https://192.168.0.190:2026/health/ready',timeout=20) as r:assert r.status==200
 with client.open('https://192.168.0.190:2026/api/v1/auth/me',timeout=20) as r:value=json.load(r)
 assert value['id']==json.loads((op/'owner.json').read_text())['owner_id']
"""
    code = (
        operator
        + """
admission('drain');status=admission('status');assert status=={'operator_drain':True,'unreleased':0};owner_gate()
import importlib.util
s=importlib.util.spec_from_file_location('cleanup',root/'bootstrap/ecs_native_shanghai_b_cleanup_recovery.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
assert m.query('deerflow',"SELECT count(*) FROM runs WHERE status NOT IN ('success','error','timeout','interrupted');")=='0'
assert json.loads((root/'proof/c-repair-main.json').read_text())['c_main']=='PASS'
assert json.loads((private/'native.json').read_text())['sandbox']['container_prefix']=='deer-native-aio-820d7a3429d9'
assert m.query('deerflow',"SELECT count(*) FROM mcp_tasks WHERE notification_status NOT IN ('none','delivered','dead_letter');")=='0'
print(json.dumps({'fresh_admission_drained':True,'unreleased':0,'nonterminal_native_runs':0,'pending_notifications':0,'native_owner_authenticated':True}))
"""
    )
    print(remote(CONTROLLER, code).decode(), end="", flush=True)
    health = """
import subprocess,json
x=json.loads(subprocess.run(['docker','inspect','deer-native-820d7a3429d9-worker-resident-1'],capture_output=True,text=True,check=True).stdout)[0]
assert x['Image']=='sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338'
assert x['State']['Running'] and x['State']['Health']['Status']=='healthy'
print(json.dumps({'owned_worker_resident_healthy':True}))
"""
    print(remote(WORKER, health).decode(), end="", flush=True)
    code = (
        operator
        + """
status=admission('status');assert status=={'operator_drain':True,'unreleased':0};owner_gate()
try:
 admission('preflight');admission('resume');assert admission('status')=={'operator_drain':False,'unreleased':0}
 print(checked(['python3',str(root/'bootstrap/ecs_native_shanghai_bc_main.py')],timeout=700).decode(),end='',flush=True)
finally:
 admission('drain')
 print(json.dumps({'admission_drained_after_single_BC':True,'operator_status':admission('status')}),flush=True)
"""
    )
    print(remote(CONTROLLER, code, timeout=850).decode(), end="", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Owned native BC transport failed; retain work, no blind rerun"
        ) from None

"""Repair the owned namespace while drained, then run one C delivery main."""

import hashlib
import importlib.util
from pathlib import Path
import shlex

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
REMOTE = "/srv/deerflow-native-task6b/56636cebddc6"
CONTROLLER = "192.168.0.190"
WORKER = "192.168.0.189"
CONFIG_SHA = "15c1166a75606661cfcb26cb81dd7846cb68d998b9f12b7a26a97068f3ab2f1c"
MAIN_SHA = "d68027647c7e2f3650f295566318908cda2975f1c9f9df7e976011d492af2720"


def main():
    helper = ROOT / "scripts/ecs_native_shanghai_bootstrap.py"
    assert (
        hashlib.sha256(helper.read_bytes()).hexdigest()
        == "8d9f9613a0bdda49b763a5cf84c8b41d25e1e13dc351a9d4012928e88952a92a"
    )
    spec = importlib.util.spec_from_file_location("fixed_bootstrap", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for host in [CONTROLLER, WORKER]:
        module.copy_public(
            host,
            ROOT / "scripts/ecs_native_shanghai_prefix_repair.py",
            REMOTE + "/bootstrap/ecs_native_shanghai_prefix_repair.py",
            CONFIG_SHA,
        )
    module.copy_public(
        CONTROLLER,
        ROOT / "scripts/ecs_native_shanghai_c_repair_main.py",
        REMOTE + "/bootstrap/ecs_native_shanghai_c_repair_main.py",
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
   if value.get('c_main_failed'):print(json.dumps(value),flush=True)
  raise SystemExit('Owned native C operation refused; private output withheld')
 return r.stdout
base=['docker','run','--rm','--cpus','0.5','--memory','1g','--network','deer-native-820d7a3429d9-controller_control','--env-file',str(private/'controller.env'),'-e','DEER_FLOW_HOME=/srv/deerflow-native-test','-e','DEER_FLOW_CONFIG_PATH=/run/operator/native.json','-e','DEER_FLOW_EXTENSIONS_CONFIG_PATH=/run/operator/extensions.json','-v',str(private)+':/run/operator:ro','-v',str(private)+':'+str(private)+':ro','-v','/srv/deerflow-native-test:/srv/deerflow-native-test','-v',str(op/'b-extensions.json')+':/run/operator/extensions.json:ro','-v',str(op/'b-extensions.json')+':'+str(private/'extensions.json')+':ro']
def admission(action):
 result=checked([*base,core,'python','-m','ecs_executor.operations',action,'--config','/run/operator/worker-ops.json'])
 return json.loads(result) if action=='status' else None
def owner_gate():
 jar=http.cookiejar.MozillaCookieJar(str(op/'owner.cookies'));jar.load(ignore_discard=True,ignore_expires=False)
 client=urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(private/'ca.crt'))),urllib.request.HTTPCookieProcessor(jar))
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
assert m.query('deerflow',"SELECT count(*) FROM mcp_tasks WHERE notification_status NOT IN ('none','delivered','dead_letter');")=='0'
print(json.dumps({'fresh_admission_drained':True,'unreleased':0,'nonterminal_native_runs':0,'pending_notifications':0,'native_owner_authenticated':True}))
"""
    )
    print(remote(CONTROLLER, code).decode(), end="", flush=True)
    # Confirm no old/new namespace physical work before changing the selector.
    physical = """
import subprocess,json
prefixes=['deer-native-820d7a3429d9-','deer-native-aio-820d7a3429d9-']
r=subprocess.run(['docker','ps','--format','{{.Names}}'],capture_output=True,text=True,check=True)
assert not any(name.startswith(prefix) for name in r.stdout.splitlines() for prefix in prefixes)
print(json.dumps({'worker_old_and_new_prefix_running':0}))
"""
    print(remote(WORKER, physical).decode(), end="", flush=True)
    for host, role in [(CONTROLLER, "controller"), (WORKER, "worker")]:
        command = (
            'import subprocess;r=subprocess.run(["python3",'
            + repr(REMOTE + "/bootstrap/ecs_native_shanghai_prefix_repair.py")
            + ","
            + repr(role)
            + '],capture_output=True,timeout=30);assert r.returncode==0;print(r.stdout.decode(),end="")'
        )
        print(remote(host, command).decode(), end="", flush=True)
    for host, role, service in [
        (CONTROLLER, "controller", "gateway"),
        (WORKER, "worker", "resident"),
    ]:
        code = f"""
import pathlib,subprocess,json
root=pathlib.Path({REMOTE!r});private=root/'private/820d7a3429d9/resident'
args=['docker','compose','--project-name','deer-native-820d7a3429d9-{role}','--env-file',str(private/'{role}.env'),'-f',str(root/'source/examples/ecs-native/deploy/{role}.compose.yaml'),'up','-d','--no-deps','--force-recreate','--no-build','--pull','never','--wait','--wait-timeout','180',{service!r}]
r=subprocess.run(args,capture_output=True,timeout=210);assert r.returncode==0
print(json.dumps({{'owned_role_recreated_and_healthy':{role!r},'env_file_refreshed':True}}))
"""
        print(remote(host, code).decode(), end="", flush=True)
    code = (
        operator
        + """
status=admission('status');assert status=={'operator_drain':True,'unreleased':0};owner_gate()
try:
 admission('preflight');admission('resume');assert admission('status')=={'operator_drain':False,'unreleased':0}
 print(checked(['python3',str(root/'bootstrap/ecs_native_shanghai_c_repair_main.py')],timeout=700).decode(),end='',flush=True)
finally:
 admission('drain')
 print(json.dumps({'admission_drained_after_single_C':True,'operator_status':admission('status')}),flush=True)
"""
    )
    print(remote(CONTROLLER, code, timeout=850).decode(), end="", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Owned native C transport failed; retain work, no blind rerun"
        ) from None

"""Jenkins-only browser provider overlay and role refresh; preserve global drain and terminal history."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import stat

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
REMOTE = "/srv/deerflow-native-task6b/56636cebddc6"
OLD = "sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1"
NEW = None
REFRESH_SHA = "529f7a931e051300b84e921643b4b47364b2e0b95fd92866acb8f985a8f345ea"


def main():
    global NEW

    helper = ROOT / "scripts/ecs_native_shanghai_bootstrap.py"
    assert (
        hashlib.sha256(helper.read_bytes()).hexdigest()
        == "8d9f9613a0bdda49b763a5cf84c8b41d25e1e13dc351a9d4012928e88952a92a"
    )
    spec = importlib.util.spec_from_file_location("fixed_bootstrap", helper)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    receipt = ROOT / "proof/browser-transfer.json"
    info = receipt.lstat()
    assert (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o600
    )
    transferred = json.loads(receipt.read_text())
    assert (
        transferred["base_image_id"] == OLD
        and transferred["publication_source_sha256"]
        == "bdd2931a1a6f8f35b9eb191fb809aa38c8dae85b6e65b44c15feb3d8a6cc8a9e"
    )
    NEW = transferred["transfers"][0]["image_id"]
    assert NEW != OLD and __import__("re").fullmatch(r"sha256:[0-9a-f]{64}", NEW)
    assert (
        len(transferred["transfers"]) == 2
        and {v["host"] for v in transferred["transfers"]}
        == {"192.168.0.190", "192.168.0.189"}
        and all(
            v["image_id"] == NEW and not v["roles_started"]
            for v in transferred["transfers"]
        )
    )
    for host in ["192.168.0.190", "192.168.0.189"]:
        m.copy_public(
            host,
            ROOT / "scripts/ecs_native_browser_role_refresh_repair.py",
            REMOTE + "/bootstrap/ecs_native_browser_role_refresh_repair.py",
            REFRESH_SHA,
        )

    def remote(host, code, timeout=300):
        return m.run(
            ["ssh", *m.OPTIONS, "root@" + host, "python3 -c " + shlex.quote(code)],
            timeout=timeout,
        )

    operator = "\nimport pathlib,json,subprocess,http.cookiejar,urllib.request,ssl\nroot=pathlib.Path('/srv/deerflow-native-task6b/56636cebddc6');private=root/'private/820d7a3429d9/resident';op=private.parent/'operator'\ncore='sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1'\ndef checked(args,timeout=120):\n r=subprocess.run(args,capture_output=True,timeout=timeout)\n if r.returncode:\n  for line in r.stdout.decode().splitlines():\n   try:value=json.loads(line)\n   except json.JSONDecodeError:continue\n   if value.get('bc_main_failed'):print(json.dumps(value),flush=True)\n  raise SystemExit('Owned native C operation refused; private output withheld')\n return r.stdout\nbase=['docker','run','--rm','--cpus','0.5','--memory','1g','--network','deer-native-820d7a3429d9-controller_control','--env-file',str(private/'controller.env'),'-e','DEER_FLOW_HOME=/srv/deerflow-native-test','-e','DEER_FLOW_CONFIG_PATH=/run/operator/native.json','-e','DEER_FLOW_EXTENSIONS_CONFIG_PATH=/run/operator/extensions.json','-v',str(private)+':/run/operator:ro','-v',str(private)+':'+str(private)+':ro','-v','/srv/deerflow-native-test:/srv/deerflow-native-test','-v',str(op/'b-extensions.json')+':/run/operator/extensions.json:ro','-v',str(op/'b-extensions.json')+':'+str(private/'extensions.json')+':ro']\ndef admission(action):\n result=checked([*base,core,'python','-m','ecs_executor.operations',action,'--config','/run/operator/worker-ops.json'])\n return json.loads(result) if action=='status' else None\ndef owner_gate():\n jar=http.cookiejar.MozillaCookieJar(str(op/'owner.cookies'));jar.load(ignore_discard=True,ignore_expires=False)\n client=urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(private/'ca.crt'))),urllib.request.HTTPCookieProcessor(jar))\n with client.open('https://192.168.0.190:2026/health/ready',timeout=20) as r:assert r.status==200\n with client.open('https://192.168.0.190:2026/api/v1/auth/me',timeout=20) as r:value=json.load(r)\n assert value['id']==json.loads((op/'owner.json').read_text())['owner_id']\n"

    def fence(image):
        code = (
            operator.replace(OLD, image)
            + """
admission('drain');assert admission('status')=={'operator_drain':True,'unreleased':0};owner_gate()
import importlib.util
s=importlib.util.spec_from_file_location('cleanup',root/'bootstrap/ecs_native_shanghai_b_cleanup_recovery.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
assert m.query('deerflow',"SELECT count(*) FROM runs WHERE status NOT IN ('success','error','timeout','interrupted');")=='0'
assert m.query('deerflow',"SELECT count(*) FROM mcp_tasks WHERE notification_status NOT IN ('none','delivered','dead_letter');")=='0'

print(json.dumps({'operator_drain':True,'unreleased':0,'nonterminal_native_runs':0,'pending_notifications':0}))
"""
        )
        return json.loads(remote("192.168.0.190", code))

    before = fence(OLD)

    def snapshot(host, role, image):
        code = """
import pathlib,hashlib,importlib.util,json
path=pathlib.Path('/srv/deerflow-native-task6b/56636cebddc6/bootstrap/ecs_native_shanghai_lifecycle_host_repair.py')
assert hashlib.sha256(path.read_bytes()).hexdigest()=='098b6105a26abea10eed62e31b15c0a634daec468fd41c88f037d403b23fc89a'
spec=importlib.util.spec_from_file_location('fixed_lifecycle',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.IMAGE=SELECTED_IMAGE
value={'containers':m.containers(ROLE)}
if ROLE=='controller':value['history_sha256']=m.controller_fence()
else:value['idle_aio_count']=m.physical()
print(json.dumps(value))
""".replace("SELECTED_IMAGE", repr(image)).replace("ROLE", repr(role))
        return json.loads(remote(host, code))

    before_c = snapshot("192.168.0.190", "controller", OLD)
    before_w = snapshot("192.168.0.189", "worker", OLD)
    refreshed = []
    for host, role in [("192.168.0.190", "controller"), ("192.168.0.189", "worker")]:
        if role == "worker":
            fence(NEW)
            snapshot(host, "worker", OLD)
        code = (
            'import subprocess;r=subprocess.run(["python3",'
            + repr(REMOTE + "/bootstrap/ecs_native_browser_role_refresh_repair.py")
            + ","
            + repr(role)
            + ","
            + repr(NEW)
            + '],capture_output=True,timeout=300);assert r.returncode==0;print(r.stdout.decode(),end="")'
        )
        refreshed.append(json.loads(remote(host, code, timeout=330)))
    after = fence(NEW)
    after_c = snapshot("192.168.0.190", "controller", NEW)
    after_w = snapshot("192.168.0.189", "worker", NEW)
    assert before_c["history_sha256"] == after_c["history_sha256"]
    for service in ["postgres", "redis", "frontend", "proxy"]:
        assert next(
            x for x in before_c["containers"] if x["service"] == service
        ) == next(x for x in after_c["containers"] if x["service"] == service)
    assert before_w["idle_aio_count"] == after_w["idle_aio_count"]

    remote(
        "192.168.0.190",
        operator.replace(OLD, NEW)
        + "admission('preflight');assert admission('status')=={'operator_drain':True,'unreleased':0};owner_gate()",
    )
    value = {
        "browser_deployment": "PASS",
        "image_id": NEW,
        "base_image_id": OLD,
        "publication_source_sha256": "bdd2931a1a6f8f35b9eb191fb809aa38c8dae85b6e65b44c15feb3d8a6cc8a9e",
        "before": before,
        "after": after,
        "before_controller": before_c,
        "after_controller": after_c,
        "before_worker": before_w,
        "after_worker": after_w,
        "roles": refreshed,
        "admission_resumed": False,
        "models_called": False,
        "history_preserved": True,
    }
    fd = os.open(
        ROOT / "proof/browser-deployment.json",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "w") as f:
        json.dump(value, f)
    print(json.dumps(value), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Owned browser deployment failed; retain state, admission remains drained"
        ) from None

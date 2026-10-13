"""One zero-model installed cross-host native browser main; owned thread cleanup only."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import stat
import time
import uuid

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
REMOTE = "/srv/deerflow-native-task6b/56636cebddc6"
IMAGE = "sha256:52ce23272ed5c945389367eb92f97fdd6754aa93d1c369bb01d7a44d45c5f47e"
HOST_SHA = "199ad86d89bda8df93914ca862e0bdccd86ba97cf62d2d61870e30e5cd564fbc"
OWNED = ROOT / "proof/browser-control-repair-owned-thread.json"


def save(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f)


def private_json(path):
    s = path.lstat()
    assert (
        stat.S_ISREG(s.st_mode)
        and s.st_uid == os.getuid()
        and stat.S_IMODE(s.st_mode) == 0o600
    )
    return json.loads(path.read_text())


def main(cleanup=False):
    helper = ROOT / "scripts/ecs_native_shanghai_bootstrap.py"
    assert (
        hashlib.sha256(helper.read_bytes()).hexdigest()
        == "8d9f9613a0bdda49b763a5cf84c8b41d25e1e13dc351a9d4012928e88952a92a"
    )
    spec = importlib.util.spec_from_file_location("fixed_transport", helper)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    def remote(host, code, timeout=180):
        return json.loads(
            m.run(
                ["ssh", *m.OPTIONS, "root@" + host, "python3 -c " + shlex.quote(code)],
                timeout=timeout,
            )
        )

    def action(thread, verb):
        code = (
            'import subprocess,json;r=subprocess.run(["python3",'
            + repr(REMOTE + "/bootstrap/ecs_native_browser_control_repair_host.py")
            + ","
            + repr(verb)
            + ","
            + repr(thread)
            + ","
            + repr(IMAGE)
            + '],capture_output=True,timeout=150);assert r.returncode==0,"Owned browser control failed; private output withheld";print(r.stdout.decode(),end="")'
        )
        return remote("192.168.0.190", code)

    def browser():
        code = '''import subprocess,json
name='deer-native-820d7a3429d9-worker-resident-1'
r=subprocess.run(['docker','inspect',name],capture_output=True,check=True);c=json.loads(r.stdout)[0]
assert c['Image']==EXPECTED_IMAGE and c['State']['Health']['Status']=='healthy'
assert c['Config']['Labels']['com.docker.compose.project']=='deer-native-820d7a3429d9-worker' and c['Config']['Labels']['com.docker.compose.service']=='resident'
assert c['HostConfig']['NanoCpus']==500000000 and c['HostConfig']['Memory']==1073741824
inner="""import pathlib,json,os
root=pathlib.Path('/proc');values=[]
for p in root.iterdir():
 if not p.name.isdigit():continue
 try:
  if pathlib.Path(os.readlink(p/'exe')).name!='chrome-headless-shell':continue
  fields=(p/'stat').read_text().rsplit(') ',1)[1].split();parent=fields[1]
  if pathlib.Path(os.readlink(root/parent/'exe')).name!='node':continue
  values.append({'pid':int(p.name),'starttime':int(fields[19]),'parent_pid':int(parent)})
 except (FileNotFoundError,ProcessLookupError,PermissionError):continue
print(json.dumps({'browser_processes':values,'cpu_max':pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().strip(),'memory_max':pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip(),'memory_current':int(pathlib.Path('/sys/fs/cgroup/memory.current').read_text())}))
"""
r=subprocess.run(['docker','exec',c['Id'],'python','-c',inner],capture_output=True,check=True,timeout=20)
v=json.loads(r.stdout);assert v['cpu_max']=='50000 100000' and v['memory_max']=='1073741824';v['container_id']=c['Id'];print(json.dumps(v))
'''.replace("EXPECTED_IMAGE", repr(IMAGE))
        return remote("192.168.0.189", code)

    def scope(thread, expected=True):
        code = """import pathlib,hashlib,importlib.util,json,re
root=pathlib.Path('/srv/deerflow-native-task6b/56636cebddc6')
p=root/'bootstrap/ecs_native_shanghai_lifecycle_host_repair.py'
assert hashlib.sha256(p.read_bytes()).hexdigest()=='098b6105a26abea10eed62e31b15c0a634daec468fd41c88f037d403b23fc89a'
s=importlib.util.spec_from_file_location('fixed',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
cleanup_path=root/'bootstrap/ecs_native_shanghai_b_cleanup_recovery.py'
assert hashlib.sha256(cleanup_path.read_bytes()).hexdigest()=='01d5d4aa61ae537397b1eafdd6181ec4c8cc1a039bbdd4db261625f407c32d2d'
history=m.controller_fence()
q=importlib.util.spec_from_file_location('query',root/'bootstrap/ecs_native_shanghai_b_cleanup_recovery.py');d=importlib.util.module_from_spec(q);q.loader.exec_module(d)
thread=OWNED_THREAD
assert re.fullmatch(r'native-browser-installed-[0-9a-f]{32}',thread)
assert d.query('deerflow',"SELECT count(*) FROM runs WHERE thread_id='"+thread+"';")=='0'
assert d.query('deerflow_execution',"SELECT count(*) FROM ecs_execution_jobs WHERE record->'native'->>'thread_id'='"+thread+"';")=='0'
rows=json.loads(d.query('deerflow_execution',"SELECT coalesce(json_agg(row_to_json(t)),'[]'::json)::text FROM ecs_native_affinities t WHERE thread_id='"+thread+"';"))
owner=json.loads(m.private(m.PRIVATE.parent/'operator/owner.json').read_text())['owner_id']
if EXPECT_SCOPE:
 assert len(rows)==1 and rows[0]['user_id']==owner and rows[0]['node_id']=='native-820d7a3429d9' and rows[0]['incarnation']
print(json.dumps({'history_sha256':history,'affinity_sha256':hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(),'affinity_count':len(rows),'no_model_run_or_execution_job':True}))
""".replace("OWNED_THREAD", repr(thread)).replace("EXPECT_SCOPE", repr(expected))
        return remote("192.168.0.190", code)

    if cleanup:
        if not OWNED.exists():
            return
        owned = private_json(OWNED)
        assert owned["image_id"] == IMAGE
        thread = owned["thread"]
        assert re.fullmatch(r"native-browser-installed-[0-9a-f]{32}", thread)
        print(json.dumps(action(thread, "delete")), flush=True)
        return
    deployment = private_json(ROOT / "proof/browser-deployment.json")
    assert (
        deployment["browser_deployment"] == "PASS"
        and deployment["image_id"] == IMAGE
        and not deployment["admission_resumed"]
    )
    assert (
        not OWNED.exists()
        and not (ROOT / "proof/browser-control-repair-main.json").exists()
    )
    m.copy_public(
        "192.168.0.190",
        ROOT / "scripts/ecs_native_browser_control_repair_host.py",
        REMOTE + "/bootstrap/ecs_native_browser_control_repair_host.py",
        HOST_SHA,
    )
    thread = "native-browser-installed-" + uuid.uuid4().hex
    before = scope(thread, False)
    idle = browser()
    assert not idle["browser_processes"]
    save(OWNED, {"thread": thread, "image_id": IMAGE})
    result = None
    cleaned = False
    try:
        prepared = action(thread, "prepare")
        first = browser()
        assert len(first["browser_processes"]) == 1
        first_scope = scope(thread)
        live = action(thread, "live")
        second = browser()
        second_scope = scope(thread)
        assert (
            first["container_id"] == second["container_id"]
            and first["browser_processes"] == second["browser_processes"]
        )
        assert first_scope["affinity_sha256"] == second_scope["affinity_sha256"]
        assert before["history_sha256"] == second_scope["history_sha256"]
        result = {
            "browser_control_main": "PASS",
            "scope": "installed_native_HTTP_and_cross_host_WSS_control_only",
            "image_id": IMAGE,
            "thread": thread,
            "prepare": prepared,
            "live": live,
            "browser_before": first,
            "browser_after_reconnect": second,
            "same_native_scope_and_browser_pid": True,
            "affinity_sha256": first_scope["affinity_sha256"],
            "models_called": False,
            "admission_resumed": False,
        }
    finally:
        deletion = action(thread, "delete")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            retired = browser()
            if not retired["browser_processes"]:
                cleaned = True
                break
            time.sleep(0.5)
        assert cleaned, "Owned native browser retirement did not settle"
        after = scope(thread, False)
        assert before["history_sha256"] == after["history_sha256"]
        if result:
            result.update(
                cleanup=deletion, owned_browser_retired=True, history_preserved=True
            )
            save(ROOT / "proof/browser-control-repair-main.json", result)
            print(json.dumps(result), flush=True)


if __name__ == "__main__":
    assert os.sys.argv[1:] in [[], ["--cleanup"]]
    try:
        main(bool(os.sys.argv[1:]))
    except Exception as e:
        print(
            json.dumps(
                {
                    "browser_control_main_failed": True,
                    "exception_class": type(e).__name__,
                    "models_called": False,
                    "admission_resumed": False,
                }
            ),
            flush=True,
        )
        raise SystemExit(
            "Owned browser main failed; retain evidence and drain"
        ) from None

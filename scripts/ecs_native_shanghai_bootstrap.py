"""One fixed Jenkins Shanghai bootstrap sequence; public inputs and private streams fenced."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
REMOTE = "/srv/deerflow-native-task6b/56636cebddc6"
SHA = {
    "ecs_native_shanghai_b_config.py": "d3d8901da6ba0e126f783a623971c26328e0fbeff075adbcb04de05ba87bae00",
    "ecs_native_shanghai_deploy.py": "21c9e8a3263009408ff15bc3d0d08160a1971a183ba55728a41dd4fecec440ba",
    "ecs_native_shanghai_owner.py": "c331a7da98d4e10f8cd8e12009b45a9ed51e69a56317398404f6efc695305236",
    "ecs_native_shanghai_worker_private.py": "b62848091a24c325d90bdb67fde7709270cd66033240461c5c3ffb808a9479aa",
    "ecs_native_build.py": "11f86b382889c65fe5cd58eb4c6ed7a6c5a11825f9dea73d54c95a74d511ff80",
}
OPTIONS = [
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=yes",
    "-o",
    "UserKnownHostsFile=" + str(ROOT / "known_hosts.native"),
    "-i",
    os.environ["DEPLOY_KEY"],
]
assert os.environ["DEPLOY_USER"] == "root"


def run(args, payload=None, timeout=600):
    result = subprocess.run(args, input=payload, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Owned bootstrap failed; private output withheld")
    return result.stdout


def remote(host, code, payload=None):
    return run(
        ["ssh", *OPTIONS, "root@" + host, "python3 -c " + shlex.quote(code)], payload
    )


def copy_public(host, path, destination, expected):
    assert (
        not path.is_symlink()
        and hashlib.sha256(path.read_bytes()).hexdigest() == expected
    )
    code = f"""import os,stat,hashlib,json
from pathlib import Path
p=Path({destination!r});assert all(not x.is_symlink() for x in [p,*p.parents])
p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
assert p.parent.stat().st_uid==0 and stat.S_IMODE(p.parent.stat().st_mode)==0o700
if p.exists():
 s=p.stat();assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o600
 assert hashlib.sha256(p.read_bytes()).hexdigest()=={expected!r};print('skip')
else:
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd);print('copy')
"""
    if remote(host, code).strip() == b"copy":
        run(["scp", *OPTIONS, str(path), "root@" + host + ":" + destination])
    remote(
        host,
        f"import hashlib;from pathlib import Path;assert hashlib.sha256(Path({destination!r}).read_bytes()).hexdigest()=={expected!r}",
    )


def main():
    for host in ["192.168.0.190", "192.168.0.189"]:
        for name, h in SHA.items():
            copy_public(host, ROOT / "scripts" / name, REMOTE + "/bootstrap/" + name, h)
        copy_public(
            host,
            ROOT / "deer-native-task6b-shanghai-freeze.json",
            REMOTE + "/deer-native-task6b-shanghai-freeze.json",
            "8045118ba29d0f8d7a97a0afb94994b2898a81226a780b99a6cdfe2ddf7daf4e",
        )
        # Full existing verified archive, not a copy of mutable public docs or private files.
        remote(
            host,
            f"""import importlib.util,os,sys
from pathlib import Path
root=Path({REMOTE!r});archive=root/'received/deer-native-source-56636cebddc6.tar.gz'
target=root/'deer-native-source-56636cebddc6.tar.gz'
if not target.exists():os.link(archive,target)
assert not target.is_symlink() and target.read_bytes()==archive.read_bytes()
spec=importlib.util.spec_from_file_location('owned_public_build',root/'bootstrap/ecs_native_build.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.ROOT=root;sys.argv=['owned','verify-source',module.ARCHIVE_SHA];module.main('verify-source')
""",
        )
    controller = "192.168.0.190"
    worker = "192.168.0.189"
    # Existing feature configuration only for the owned zero-model B fixture.
    # Both Gateway background notification loops stay inactive until B thread cleanup.
    remote(
        controller,
        f"""import json,os,stat
from pathlib import Path
private=Path({REMOTE!r})/'private/820d7a3429d9/resident';operator=private.parent/'operator'
for path in [private/'native.json',operator/'worker-envelope.json']:
 s=path.lstat();assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o600
native=json.loads((private/'native.json').read_text());native['mcp_tasks']['enabled']=False
body=json.dumps(native,indent=2)+'\\n'
envelope=json.loads((operator/'worker-envelope.json').read_text());envelope['files']['native.json']=body
for path,text in [(private/'native.json',body),(operator/'worker-envelope.json',json.dumps(envelope,indent=2)+'\\n')]:
 temp=path.with_name(path.name+'.b-infra');fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:f.write(text)
 os.replace(temp,path)
print(json.dumps({{'b_notification_gate':False,'models_called':False}}))
""",
    )
    remote(
        controller,
        f'import subprocess;r=subprocess.run(["python3",{(REMOTE + "/bootstrap/ecs_native_shanghai_b_config.py")!r},"prepare"],capture_output=True);assert r.returncode==0;print(r.stdout.decode())',
    )
    deploy = REMOTE + "/bootstrap/ecs_native_shanghai_deploy.py"
    for phase in ["controller-db", "controller-up"]:
        remote(
            controller,
            f'import subprocess; r=subprocess.run(["python3",{deploy!r},{phase!r}],capture_output=True);assert r.returncode==0;print(r.stdout.decode())',
        )
    # Secret stays controller-local stdin of the already reviewed native-only login bootstrap.
    remote(
        controller,
        f"""import json,subprocess,stat
from pathlib import Path
p=Path({REMOTE!r})/'private/820d7a3429d9/operator/secrets.json';s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o600
value=json.loads(p.read_text());r=subprocess.run(['python3',{deploy!r},'native-login'],input=json.dumps({{'gateway_password':value['gateway']}}).encode(),capture_output=True);assert r.returncode==0;print(r.stdout.decode())
""",
    )
    owner = remote(
        controller,
        f'import subprocess;r=subprocess.run(["python3",{(REMOTE + "/bootstrap/ecs_native_shanghai_owner.py")!r}],capture_output=True);assert r.returncode==0;print(r.stdout.decode())',
    )
    print(owner.decode())
    remote(
        controller,
        f'import subprocess;r=subprocess.run(["python3",{(REMOTE + "/bootstrap/ecs_native_shanghai_b_config.py")!r},"bind"],capture_output=True);assert r.returncode==0;print(r.stdout.decode())',
    )
    remote(
        controller,
        f"""import importlib.util
from pathlib import Path
s=importlib.util.spec_from_file_location('owned_deploy',Path({deploy!r}));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m.compose('controller','restart','--timeout','240','gateway','mcp')
m.compose('controller','up','-d','--no-build','--pull','never','--wait','--wait-timeout','240')
m.health()
""",
    )
    # Private contents are never saved on Jenkins or printed. SSH transports one fixed envelope.
    payload = remote(
        controller,
        f"""import json,stat
from pathlib import Path
p=Path({REMOTE!r})/'private/820d7a3429d9/operator'
for name in ['worker-envelope.json','operator.env']:
 s=(p/name).lstat();assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o600
print(json.dumps({{'envelope':json.loads((p/'worker-envelope.json').read_text()),'operator_env':(p/'operator.env').read_text()}}))
""",
    )
    receipt = remote(
        worker,
        f'import runpy;runpy.run_path({(REMOTE + "/bootstrap/ecs_native_shanghai_worker_private.py")!r},run_name="__main__")',
        payload,
    )
    print(receipt.decode())
    # Worker startup/readiness is the actual private two-ECS connectivity check.
    remote(
        worker,
        f'import subprocess;r=subprocess.run(["python3",{deploy!r},"worker-up"],capture_output=True);assert r.returncode==0;print(r.stdout.decode())',
    )
    print(
        json.dumps(
            {
                "fixed_bootstrap": "PASS",
                "models_called": False,
                "browser_acceptance": "pending_unavailable",
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Owned Shanghai bootstrap refused; state retained, private details withheld"
        ) from None

"""Fixed public-input transport and controller-only frontend build via Jenkins binding."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
REMOTE = "/srv/deerflow-native-task6b/56636cebddc6/frontend-build"
HELPER_SHA = "11f86b382889c65fe5cd58eb4c6ed7a6c5a11825f9dea73d54c95a74d511ff80"
ARCHIVE_SHA = "e27c3d4ce58b7f762c09386cfe1fc97464c5df639dc2d855332713915e3fa34b"
INPUTS = [
    (
        ROOT / "deer-native-source-56636cebddc6.tar.gz",
        "deer-native-source-56636cebddc6.tar.gz",
        ARCHIVE_SHA,
    ),
    (
        ROOT / "deer-native-task6b-shanghai-freeze.json",
        "deer-native-task6b-shanghai-freeze.json",
        "8045118ba29d0f8d7a97a0afb94994b2898a81226a780b99a6cdfe2ddf7daf4e",
    ),
    (ROOT / "scripts/ecs_native_build.py", "scripts/ecs_native_build.py", HELPER_SHA),
    (
        Path(
            "/data/jenkins-agent/deerflow/native-task6b-95ba9f3063f9/oci/nodebase.tar"
        ),
        "oci/nodebase.tar",
        "c886630f02cc691a8dc81d49497a8974e1cda4bc08bdb33b591367a30ef21dda",
    ),
]
INPUTS.append(
    (
        ROOT / "transfer/buildkit0331-image.tar",
        "oci/buildkit0331-image.tar",
        "3316dca034bd7d43e5bef09ed56383b7d91e3a5744e88a861647ac0fb5b54b53",
    )
)
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
TARGET = os.environ["DEPLOY_USER"] + "@192.168.0.190"


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError("Owned controller build operation failed; output withheld")
    return result.stdout


def sha(path):
    assert path.is_file() and not path.is_symlink()
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remote(code):
    return run(
        ["ssh", *OPTIONS, TARGET, "python3", "-"], input=code.encode(), timeout=7200
    )


def main():
    for path, relative, expected in INPUTS:
        assert sha(path) == expected
        code = f"""from pathlib import Path
import os,stat,hashlib,json
root=Path({REMOTE!r}); destination=root/{relative!r}
assert all(not x.is_symlink() for x in [destination.parent,*destination.parent.parents])
for directory in [root, destination.parent]:
 directory.mkdir(parents=True,exist_ok=True,mode=0o700)
 assert not directory.is_symlink() and directory.stat().st_uid==0 and stat.S_IMODE(directory.stat().st_mode)==0o700
if destination.exists() or destination.is_symlink():
 info=destination.lstat();assert stat.S_ISREG(info.st_mode) and info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o600
 actual=hashlib.sha256(destination.read_bytes()).hexdigest()
 assert actual=={expected!r} or ({relative!r}=='scripts/ecs_native_build.py' and actual=='379d8ebbd8283a0defc269721b9168d274171ab98602855de9a95d7df9dfb351')
 print(json.dumps({{'copy':actual!={expected!r}}}))
else:
 fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
 print(json.dumps({{'copy':True}}))
"""
        state = json.loads(remote(code))
        if state["copy"]:
            run(
                ["scp", *OPTIONS, str(path), TARGET + ":" + REMOTE + "/" + relative],
                timeout=600,
            )
        remote(
            f"from pathlib import Path\nimport hashlib\np=Path({(REMOTE + '/' + relative)!r});assert not p.is_symlink();assert hashlib.sha256(p.read_bytes()).hexdigest()=={expected!r}\n"
        )
    # The original official image is a fifth fixed input; no registry pull occurs.
    assert (
        sha(ROOT / "scripts/ecs_native_transfer.py")
        == "1536b0e109d0a8db481eca906e50fbb2f0b84f217214d2e29056e97cd0d13300"
    )
    from ecs_native_transfer import assert_unaliased_archive

    assert_unaliased_archive(ROOT / "transfer/buildkit0331-image.tar")
    remote(f"""import subprocess,json,hashlib,os
from pathlib import Path
root=Path({REMOTE!r});image='sha256:cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea'
pin='moby/buildkit@sha256:cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea'
archive=root/'oci/buildkit0331-image.tar';assert hashlib.sha256(archive.read_bytes()).hexdigest()=='3316dca034bd7d43e5bef09ed56383b7d91e3a5744e88a861647ac0fb5b54b53'
prior=subprocess.run(['docker','image','inspect',pin],capture_output=True)
if prior.returncode==0:assert json.loads(prior.stdout)[0]['Id']==image
present=subprocess.run(['docker','image','inspect',image],capture_output=True)
if present.returncode:
 loaded=subprocess.run(['docker','image','load','-i',str(archive)],capture_output=True,timeout=300);assert loaded.returncode==0
info=json.loads(subprocess.check_output(['docker','image','inspect',image]))[0]
assert info['Id']==image and info['Architecture']=='amd64'
v=subprocess.run(['docker','run','--rm','--network','none','--cpus','0.25','--memory','256m','--entrypoint','buildkitd',image,'--version'],capture_output=True,timeout=20)
assert v.returncode==0 and v.stdout.decode().split()[2]=='v0.33.1'
proof=root/'proof';proof.mkdir(mode=0o700,exist_ok=True)
value={{'upstream_digest':pin,'image_id':image,'archive_sha256':'3316dca034bd7d43e5bef09ed56383b7d91e3a5744e88a861647ac0fb5b54b53','version':'v0.33.1','no_registry_pull':True}}
path=proof/'buildkit-cache.json'
assert not path.is_symlink()
if path.exists():
 import stat
 info=path.stat();assert info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o600 and stat.S_ISREG(info.st_mode)
 assert json.loads(path.read_text())==value
else:
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f)
""")
    code = f"""import os,subprocess
from pathlib import Path
root=Path({REMOTE!r});env={{**os.environ,'ECS_NATIVE_CONTROLLER_BUILD':'1'}}
helper=str(root/'scripts/ecs_native_build.py')
try:
 for args in [['verify-source',{ARCHIVE_SHA!r}],['builder'],['frontend']]:
  result=subprocess.run(['python3',helper,*args],env=env,capture_output=True)
  assert result.returncode==0, 'Owned frontend stage failed; inspect selected remote log metadata'
finally:
 subprocess.run(['python3',helper,'stop-builder'],env=env,capture_output=True)
"""
    remote(code)
    # Export exact ID and return the archive/proof for the already reviewed transfer.
    code = f"""import json,subprocess,os,hashlib
from pathlib import Path
root=Path({REMOTE!r});proof=json.loads((root/'proof/frontend-image.json').read_text())
assert proof['source_archive_sha256']=={ARCHIVE_SHA!r} and proof['image']=='deerflow-native-ui:56636cebddc6'
archive=root/'native-ui-image.tar'
fd=os.open(archive,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'wb') as f:
 r=subprocess.run(['nice','-n','15','docker','image','save',proof['image_id']],stdout=f,stderr=subprocess.PIPE,timeout=600)
 assert r.returncode==0
h=hashlib.sha256()
with archive.open('rb') as stream:
 for chunk in iter(lambda:stream.read(1048576),b''):h.update(chunk)
value={{"image_id":proof['image_id'],'sha256':h.hexdigest()}}
fd=os.open(root/'native-ui-archive.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as f:json.dump(value,f)
"""
    remote(code)
    for relative, destination in [
        ("proof/frontend-image.json", ROOT / "proof/frontend-image.json"),
        ("native-ui-image.tar", ROOT / "transfer/native-ui-image.tar"),
        ("native-ui-archive.json", ROOT / "transfer/native-ui-archive.json"),
    ]:
        assert not destination.exists() and not destination.is_symlink()
        fd = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        os.close(fd)
        run(
            ["scp", *OPTIONS, TARGET + ":" + REMOTE + "/" + relative, str(destination)],
            timeout=600,
        )
    archive_proof = json.loads((ROOT / "transfer/native-ui-archive.json").read_text())
    assert archive_proof["sha256"] == sha(ROOT / "transfer/native-ui-image.tar")
    assert (
        archive_proof["image_id"]
        == json.loads((ROOT / "proof/frontend-image.json").read_text())["image_id"]
    )
    print(
        json.dumps(
            {
                "controller_frontend_build": "PASS",
                "source_archive_sha256": ARCHIVE_SHA,
                "roles_started": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Owned controller frontend build failed; private output withheld, artifacts retained"
        ) from None

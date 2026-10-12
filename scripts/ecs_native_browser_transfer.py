"""Transfer the accepted official browser derivative; never start roles or resume admission."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
IMAGE = None
BASE = "sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1"
PATCH = "bdd2931a1a6f8f35b9eb191fb809aa38c8dae85b6e65b44c15feb3d8a6cc8a9e"
TAG = "deerflow-native:browser-mcr-1.61.0-1228-a216"


def main():
    global IMAGE
    helper = ROOT / "scripts/ecs_native_transfer.py"
    assert (
        hashlib.sha256(helper.read_bytes()).hexdigest()
        == "1536b0e109d0a8db481eca906e50fbb2f0b84f217214d2e29056e97cd0d13300"
    )
    spec = importlib.util.spec_from_file_location("reviewed_transfer", helper)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    def proof(path):
        s = path.lstat()
        assert (
            stat.S_ISREG(s.st_mode)
            and s.st_uid == os.getuid()
            and stat.S_IMODE(s.st_mode) == 0o600
        )
        return json.loads(path.read_text())

    image = proof(ROOT / "proof/browser-mcr-repair-image.json")
    green = proof(ROOT / "proof/browser-mcr-repair-green.json")
    assert (
        hashlib.sha256(
            (ROOT / "proof/browser-mcr-repair-image.json").read_bytes()
        ).hexdigest()
        == "7630d6fdbcd17a3039e8553133e077ccc5225a3387724040e460b916e8aa9bc2"
    )
    IMAGE = image["image_id"]
    assert (
        IMAGE
        == "sha256:52ce23272ed5c945389367eb92f97fdd6754aa93d1c369bb01d7a44d45c5f47e"
    )
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", IMAGE) and IMAGE != BASE
    assert (
        green["image_id"] == IMAGE
        and image["base_image_id"] == BASE
        and green["base_image_id"] == BASE
    )
    assert (
        image["verify_sha256"]
        == "b618cdaf34c19a4cf82263110ce21cc8dbb6708da8a935ac7bd80d3fdbb8d91e"
    )
    assert (
        image["official_distribution"]["layer_sha256"]
        == "d6767936d02bbcee2ee5e024d6e22a6edfa609a13b068b015be122a4b1f50026"
    )
    assert (
        image["official_distribution"]["layer_bytes"] == 806539070
        and image["official_distribution"]["other_browsers_or_ubuntu_libs_copied"]
        is False
    )
    assert image["browser_version"] == green["browser_version"] == "149.0.7827.55"
    assert (
        image["binary_sha256"] == green["binary_sha256"]
        and green["uid"] == 1000
        and green["input_verified"]
    )
    assert (
        green["scope"] == "headless_no_channel_distribution_only"
        and green["network"] == "none"
    )
    assert image["roles_changed"] is False and image["models_called"] is False

    archive = ROOT / "transfer/browser-mcr-1.61.0-1228-image.tar"
    receipt = archive.with_suffix(".json")
    assert not archive.is_symlink() and not receipt.is_symlink()
    if not archive.exists():
        fd = os.open(
            archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as out:
            r = subprocess.run(
                [
                    "nice",
                    "-n",
                    "15",
                    "ionice",
                    "-c",
                    "3",
                    "docker",
                    "image",
                    "save",
                    IMAGE,
                ],
                stdout=out,
                stderr=subprocess.PIPE,
                timeout=600,
            )
        assert r.returncode == 0
        fd = os.open(
            receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "w") as out:
            json.dump({"image_id": IMAGE, "sha256": m.digest(archive)}, out)
    saved = proof(receipt)
    s = archive.lstat()
    assert (
        stat.S_ISREG(s.st_mode)
        and s.st_uid == os.getuid()
        and stat.S_IMODE(s.st_mode) == 0o600
    )
    sha = m.digest(archive)
    assert saved == {"image_id": IMAGE, "sha256": sha}
    m.assert_unaliased_archive(archive)
    assert os.environ["DEPLOY_USER"] == "root"
    options = [
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile=" + str(ROOT / "known_hosts.native"),
        "-i",
        os.environ["DEPLOY_KEY"],
    ]
    results = []
    for host in ["192.168.0.190", "192.168.0.189"]:
        target = "/srv/deerflow-native-task6b/56636cebddc6/received/" + archive.name
        check = f"""import hashlib,json,os,pathlib,stat,subprocess
p=pathlib.Path({target!r});parent=p.parent;s=parent.lstat();assert stat.S_ISDIR(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o700
assert all(not d.is_symlink() for d in [parent,*parent.parents]);assert not p.is_symlink()
def digest():
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def checked(args):
 r=subprocess.run(args,capture_output=True,timeout=600);assert r.returncode==0;return r.stdout
def tag_guard():
 r=subprocess.run(['docker','image','inspect',{TAG!r}],capture_output=True)
 if r.returncode==0:assert json.loads(r.stdout)[0]['Id']=={IMAGE!r}
tag_guard()
"""
        reserve = (
            check
            + f"""if p.exists():
 s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o600 and digest()=={sha!r};print(json.dumps(False))
else:
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd);print(json.dumps(True))
"""
        )
        if json.loads(
            m.run(
                ["ssh", *options, "root@" + host, "python3 -c " + shlex.quote(reserve)],
                timeout=90,
            )
        ):
            m.run(
                [
                    "nice",
                    "-n",
                    "15",
                    "ionice",
                    "-c",
                    "3",
                    "scp",
                    *options,
                    str(archive),
                    "root@" + host + ":" + target,
                ],
                timeout=600,
            )
        load = (
            check
            + f"""assert p.is_file() and digest()=={sha!r}
checked(['docker','image','load','--input',str(p)])
i=json.loads(checked(['docker','image','inspect',{IMAGE!r}]))[0];assert i['Id']=={IMAGE!r} and i['Architecture']=='amd64'
tag_guard();checked(['docker','image','tag',{IMAGE!r},{TAG!r}]);assert json.loads(checked(['docker','image','inspect',{TAG!r}]))[0]['Id']=={IMAGE!r}
print(json.dumps({{'host':{host!r},'image_id':{IMAGE!r},'archive_sha256':{sha!r},'roles_started':False}}))
"""
        )
        results.append(
            json.loads(
                m.run(
                    [
                        "ssh",
                        *options,
                        "root@" + host,
                        "python3 -c " + shlex.quote(load),
                    ],
                    timeout=700,
                )
            )
        )
    fd = os.open(
        ROOT / "proof/browser-transfer.json",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "w") as out:
        json.dump(
            {
                "base_image_id": BASE,
                "publication_source_sha256": PATCH,
                "transfers": results,
            },
            out,
        )
    print(
        json.dumps(
            {"browser_transfer": "PASS", "image_id": IMAGE, "roles_started": False}
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Owned browser transfer failed; retain partials and private output"
        ) from None

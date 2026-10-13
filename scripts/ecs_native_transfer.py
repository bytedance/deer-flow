"""Transfer only the reviewed DeerFlow test artifacts using Jenkins binding."""

import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import tarfile
from pathlib import Path

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
ARTIFACTS = ROOT / "transfer"
ARCHIVE_SHA = "e27c3d4ce58b7f762c09386cfe1fc97464c5df639dc2d855332713915e3fa34b"
CORE_ID = "sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338"
CORE_SHA = "4bddb0efba126620ac03c6329e8858b10af7a72d01f28dd7293563fbf1cd3cdf"
RUNTIME_ARTIFACTS = [
    (
        "postgres16-image.tar",
        "postgres:16-alpine",
        "sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea",
        "5c14158de100c50f7b5809cec1b1cacdac03e6669e47b390fb0b4bd1238e0c7b",
        "192.168.0.190",
        "postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea",
    ),
    (
        "redis7-image.tar",
        "redis:7-alpine",
        "sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499",
        "fc65d676ae37f621128046dd3f8c56cb474ac01f6ce261dd81c108d5616df413",
        "192.168.0.190",
        "redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499",
    ),
    (
        "nginx-image.tar",
        "nginx:stable-alpine",
        "sha256:74694f2de64c44787a81f0554aa45b281e468c0c58b8665fafceda624d31e556",
        "879efd4b98e912a5628b1979cb7e1a79965ba1dcedcdb80f451118d6fff7895e",
        "192.168.0.190",
        "nginx@sha256:74694f2de64c44787a81f0554aa45b281e468c0c58b8665fafceda624d31e556",
    ),
    (
        "alpine320-image.tar",
        "alpine:3.20",
        "sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc",
        "51205a7f0f0e7b893c4c68797eb7e1ca8b579206428195d758b4afc0f96fad19",
        "192.168.0.189",
        "alpine@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc",
    ),
]


def run(args, **kw):
    result = subprocess.run(args, capture_output=True, **kw)
    if result.returncode:
        raise RuntimeError("Owned artifact operation failed; output withheld")
    return result.stdout


def digest(path):
    assert path.is_file() and not path.is_symlink()
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def assert_unaliased_archive(path):
    # Saving by ID currently emits no aliases; fail if that contract changes.
    with tarfile.open(path) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        assert all(not entry.get("RepoTags") for entry in manifest)
        pending = [json.load(archive.extractfile("index.json"))]
        while pending:
            entry = pending.pop()
            annotations = entry.get("annotations", {})
            assert not annotations.get("org.opencontainers.image.ref.name")
            assert not annotations.get("io.containerd.image.name")
            for descriptor in entry.get("manifests", []):
                pending.append(descriptor)
                kind = descriptor.get("mediaType", "")
                if kind.endswith(
                    (
                        "image.index.v1+json",
                        "image.manifest.v1+json",
                        "manifest.list.v2+json",
                        "manifest.v2+json",
                    )
                ):
                    sha = descriptor["digest"]
                    assert re.fullmatch(r"sha256:[0-9a-f]{64}", sha)
                    try:
                        stream = archive.extractfile("blobs/sha256/" + sha[7:])
                    except KeyError:
                        platform = descriptor.get("platform", {})
                        assert platform.get("os") and platform.get("architecture")
                        assert (platform["os"], platform["architecture"]) != (
                            "linux",
                            "amd64",
                        )
                    else:
                        pending.append(json.load(stream))


def main():
    assert not ARTIFACTS.is_symlink()
    directory = ARTIFACTS.stat()
    assert directory.st_uid == os.geteuid() and stat.S_IMODE(directory.st_mode) == 0o700
    core = ARTIFACTS / "native-core-image.tar"
    assert digest(core) == CORE_SHA
    assert_unaliased_archive(core)
    ui_proof = json.loads((ROOT / "proof/frontend-image.json").read_text())
    assert ui_proof["source_archive_sha256"] == ARCHIVE_SHA
    assert ui_proof["image"] == "deerflow-native-ui:56636cebddc6"
    ui_id = ui_proof["image_id"]
    assert ui_id.startswith("sha256:") and len(ui_id) == 71
    ui = ARTIFACTS / "native-ui-image.tar"
    ui_archive_proof = ARTIFACTS / "native-ui-archive.json"
    assert not ui.is_symlink() and not ui_archive_proof.is_symlink()
    if not ui.exists():
        fd = os.open(ui, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            result = subprocess.run(
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
                    ui_id,
                ],
                stdout=stream,
                stderr=subprocess.PIPE,
                timeout=600,
            )
        assert result.returncode == 0
        fd = os.open(
            ui_archive_proof,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "w") as stream:
            json.dump({"image_id": ui_id, "sha256": digest(ui)}, stream)
    previous = json.loads(ui_archive_proof.read_text())
    ui_sha = digest(ui)
    assert previous == {"image_id": ui_id, "sha256": ui_sha}
    assert_unaliased_archive(ui)
    for name, tag, image_id, sha, host, repo_digest in RUNTIME_ARTIFACTS:
        artifact = ARTIFACTS / name
        assert digest(artifact) == sha
        assert_unaliased_archive(artifact)
    source = ROOT / "deer-native-source-56636cebddc6.tar.gz"
    assert digest(source) == ARCHIVE_SHA
    key = os.environ["DEPLOY_KEY"]
    user = os.environ["DEPLOY_USER"]
    assert user == "root"
    options = [
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile=" + str(ROOT / "known_hosts.native"),
        "-i",
        key,
    ]
    proofs = []
    for host in ["192.168.0.190", "192.168.0.189"]:
        remote = "/srv/deerflow-native-task6b/56636cebddc6/received"
        prepare = (
            "from pathlib import Path;import os,stat;p=Path("
            + repr(remote)
            + ");assert all(not x.is_symlink() for x in [p,*p.parents]);p.mkdir(mode=0o700,parents=True,exist_ok=True);s=p.stat();assert s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o700"
        )
        run(
            ["ssh", *options, user + "@" + host, "python3 -c " + shlex.quote(prepare)],
            timeout=20,
        )
        files = [
            (core, CORE_SHA, CORE_ID, "deerflow-native:05e260329244-core"),
            (source, ARCHIVE_SHA, None, None),
        ]
        if host == "192.168.0.190":
            files.append((ui, ui_sha, ui_id, "deerflow-native-ui:56636cebddc6"))
        files += [
            (ARTIFACTS / name, sha, image_id, tag)
            for name, tag, image_id, sha, target, repo_digest in RUNTIME_ARTIFACTS
            if target == host
        ]
        for path, sha, image, tag in files:
            reserve = f"""from pathlib import Path
import hashlib,json,os,stat
p=Path({(remote + "/" + path.name)!r})
assert not p.is_symlink()
if p.exists():
 s=p.stat()
 assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o600
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 assert h.hexdigest()=={sha!r}, 'unknown_or_partial_artifact_retained'
 print(json.dumps(False))
else:
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 os.close(fd)
 print(json.dumps(True))
"""
            needed = json.loads(
                run(
                    [
                        "ssh",
                        *options,
                        user + "@" + host,
                        "python3 -c " + shlex.quote(reserve),
                    ],
                    timeout=60,
                )
            )
            if needed:
                run(
                    [
                        "nice",
                        "-n",
                        "15",
                        "ionice",
                        "-c",
                        "3",
                        "scp",
                        *options,
                        str(path),
                        user + "@" + host + ":" + remote + "/" + path.name,
                    ],
                    timeout=600,
                )
            code = (
                "import hashlib,json,subprocess;from pathlib import Path;p=Path("
                + repr(remote + "/" + path.name)
                + ");assert p.is_file() and not p.is_symlink();h=hashlib.sha256();f=p.open('rb');\nfor b in iter(lambda:f.read(1048576),b''):h.update(b)\nassert h.hexdigest()=="
                + repr(sha)
            )
            if image:
                code += f"""
t=subprocess.run(['docker','image','inspect',{tag!r}],capture_output=True,text=True)
if t.returncode==0:
 assert json.loads(t.stdout)[0]['Id']=={image!r}, 'unknown_tag_refused'
r=subprocess.run(['nice','-n','15','ionice','-c','3','docker','load','--input',str(p)],capture_output=True)
assert r.returncode==0
d=json.loads(subprocess.check_output(['docker','image','inspect',{image!r}],text=True))[0]
assert d['Id']=={image!r} and d['Architecture']=='amd64'
t=subprocess.run(['docker','image','inspect',{tag!r}],capture_output=True,text=True)
if t.returncode==0:
 assert json.loads(t.stdout)[0]['Id']=={image!r}, 'unknown_tag_refused'
else:
 subprocess.run(['docker','image','tag',{image!r},{tag!r}],check=True,capture_output=True)
assert json.loads(subprocess.check_output(['docker','image','inspect',{tag!r}],text=True))[0]['Id']=={image!r}
"""
            run(
                ["ssh", *options, user + "@" + host, "python3 -c " + shlex.quote(code)],
                timeout=600,
            )
            proofs.append(
                {
                    "host": host,
                    "file": path.name,
                    "sha256": sha,
                    "image_id": image,
                    "image_loaded": bool(image),
                    "image_source_sha256": "05e260329244d3194d23512320e88cf653206d7db75e34b737cf6e64b29401e8"
                    if image == CORE_ID
                    else "56636cebddc6060cc4929a7f0fd86d45eb7c21c5890fb2f7f1d1128226ac4af5"
                    if image in {None, ui_id}
                    else None,
                    "upstream_repo_digest": next(
                        (
                            repo
                            for name, tag, expected_id, sha, target, repo in RUNTIME_ARTIFACTS
                            if expected_id == image
                        ),
                        None,
                    ),
                    "verified_tag": tag,
                    "copied": needed,
                }
            )
    out = ROOT / "proof/transfer.json"
    out.write_text(
        json.dumps(
            {
                "source_archive_sha256": ARCHIVE_SHA,
                "artifacts": proofs,
                "roles_started": False,
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps({"transferred_artifacts": len(proofs), "roles_started": False}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Owned transfer refused/failed; output withheld") from None

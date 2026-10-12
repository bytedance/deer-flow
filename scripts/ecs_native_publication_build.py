"""One exact-core, single-public-file derivative; reuse the stopped owned builder."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
WORK = ROOT / "publication-bdd2931a1a6f"
ARCHIVE = ROOT / "transfer/native-core-image.tar"
ARCHIVE_SHA = "4bddb0efba126620ac03c6329e8858b10af7a72d01f28dd7293563fbf1cd3cdf"
BASE = "sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338"
PATCH = "bdd2931a1a6f8f35b9eb191fb809aa38c8dae85b6e65b44c15feb3d8a6cc8a9e"
IMAGE = "deerflow-native:publication-bdd2931a1a6f-core"
BUILDER = "deer-native-820d7a3429d9"
CONTAINER = "buildx_buildkit_" + BUILDER + "0"
CONTAINER_ID = "ff42351e365f430cf2251b8f54d2510915c1645339e7d44503e8c65c0c1e12b3"
BUILDKIT = "sha256:cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(args, timeout=120):
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError("Owned derivative command failed; private output withheld")
    return r.stdout


def save(name, value):
    path = ROOT / "proof" / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.write("\n")


def core_context():
    s = ARCHIVE.lstat()
    assert (
        stat.S_ISREG(s.st_mode)
        and s.st_uid == os.getuid()
        and stat.S_IMODE(s.st_mode) == 0o600
    )
    assert sha(ARCHIVE) == ARCHIVE_SHA
    layout = WORK / "core-oci"
    layout.mkdir(mode=0o700, exist_ok=True)
    assert not layout.is_symlink() and layout.stat().st_uid == os.getuid()
    for name in ["blobs", "blobs/sha256"]:
        p = layout / name
        p.mkdir(mode=0o700, exist_ok=True)
        assert not p.is_symlink() and p.is_dir()
    expected = set()
    with tarfile.open(ARCHIVE) as tar:
        for member in tar.getmembers():
            if member.name not in ["index.json", "oci-layout"] and not re.fullmatch(
                r"blobs/sha256/[0-9a-f]{64}", member.name
            ):
                continue
            assert member.isfile() or member.islnk()
            p = layout / member.name
            expected.add(member.name)
            assert not p.is_symlink()
            if not p.exists():
                with tar.extractfile(member) as source, p.open("xb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
            assert p.is_file()
            if member.name.startswith("blobs/"):
                assert sha(p) == p.name
            else:
                assert (
                    sha(p) == hashlib.sha256(tar.extractfile(member).read()).hexdigest()
                )
    actual = set()
    for p in layout.rglob("*"):
        assert not p.is_symlink()
        if p.is_file():
            actual.add(str(p.relative_to(layout)))
        else:
            assert str(p.relative_to(layout)) in ["blobs", "blobs/sha256"]
    assert actual == expected
    assert json.loads((layout / "oci-layout").read_text()) == {
        "imageLayoutVersion": "1.0.0"
    }
    index = json.loads((layout / "index.json").read_text())
    assert len(index["manifests"]) == 1

    def blob(d):
        assert re.fullmatch("sha256:[0-9a-f]{64}", d["digest"])
        p = layout / "blobs/sha256" / d["digest"].split(":")[1]
        assert p.is_file() and p.stat().st_size == d["size"] and sha(p) == p.name
        return p

    root = index["manifests"][0]
    manifest = json.loads(blob(root).read_text())
    if "manifests" in manifest:
        selected = [
            d
            for d in manifest["manifests"]
            if d.get("platform", {}).get("os") == "linux"
            and d["platform"].get("architecture") == "amd64"
        ]
        assert len(selected) == 1
        manifest = json.loads(blob(selected[0]).read_text())
    assert root["digest"] == BASE  # Docker 29 containerd image identity is the manifest descriptor.
    config = json.loads(blob(manifest["config"]).read_text())
    assert config["os"] == "linux" and config["architecture"] == "amd64"
    for layer in manifest["layers"]:
        blob(layer)
    return "oci-layout://" + str(layout) + "@" + root["digest"]


def main():
    assert WORK.is_dir() and not WORK.is_symlink() and WORK.stat().st_uid == os.getuid()
    context = WORK / "context"
    assert context.is_dir() and not context.is_symlink()
    assert {p.name for p in context.iterdir()} == {"Dockerfile", "publication.py"}
    assert all(p.is_file() and not p.is_symlink() for p in context.iterdir())
    assert sha(context / "publication.py") == PATCH
    assert (
        (context / "Dockerfile").read_text()
        == "FROM native-core\nCOPY publication.py /app/backend/packages/ecs-executor/ecs_executor/publication.py\n"
    )
    memory = {
        k: int(v.split()[0]) * 1024
        for k, v in (
            line.split(":", 1)
            for line in Path("/proc/meminfo").read_text().splitlines()
        )
        if k == "MemAvailable"
    }
    assert memory["MemAvailable"] >= 5 * 1024**3
    builder = json.loads(run(["docker", "inspect", CONTAINER]))[0]
    h = builder["HostConfig"]
    assert (
        builder["Id"] == CONTAINER_ID
        and builder["Image"] == BUILDKIT
        and not builder["State"]["Running"]
    )
    assert (
        h["Memory"] == h["MemorySwap"] == 3 * 1024**3
        and h["CpuQuota"] == h["CpuPeriod"] == 100000
    )
    base_image = json.loads(run(["docker", "image", "inspect", BASE]))[0]
    assert base_image["Id"] == base_image["Descriptor"]["digest"] == BASE
    assert (
        subprocess.run(
            ["docker", "image", "inspect", IMAGE], capture_output=True
        ).returncode
        != 0
    )
    ctx = core_context()
    try:
        run(["docker", "buildx", "inspect", BUILDER, "--bootstrap"])
        kernel = json.loads(run(["docker", "inspect", CONTAINER]))[0]
        assert kernel["Id"] == CONTAINER_ID and kernel["State"]["Running"]
        limits = (
            run(
                [
                    "docker",
                    "exec",
                    CONTAINER,
                    "cat",
                    "/sys/fs/cgroup/cpu.max",
                    "/sys/fs/cgroup/memory.max",
                    "/sys/fs/cgroup/memory.swap.max",
                ]
            )
            .decode()
            .splitlines()
        )
        assert limits == ["100000 100000", "3221225472", "0"]
        save(
            "publication-builder.json",
            {
                "container_id": CONTAINER_ID,
                "memory_available_before": memory["MemAvailable"],
                "kernel_limits": limits,
                "base_image_id": BASE,
                "patch_sha256": PATCH,
            },
        )
        run(
            [
                "docker",
                "buildx",
                "build",
                "--builder",
                BUILDER,
                "--platform",
                "linux/amd64",
                "--network",
                "none",
                "--build-context",
                "native-core=" + ctx,
                "--load",
                "--tag",
                IMAGE,
                str(context),
            ],
            timeout=600,
        )
        image = json.loads(run(["docker", "image", "inspect", IMAGE]))[0]
        assert image["Architecture"] == "amd64"
        check = (
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--cpus",
                    "1",
                    "--memory",
                    "512m",
                    image["Id"],
                    "python",
                    "-c",
                    "import hashlib,pathlib,ecs_executor.publication as p;assert pathlib.Path(p.__file__).as_posix()=='/app/backend/packages/ecs-executor/ecs_executor/publication.py';print(hashlib.sha256(pathlib.Path(p.__file__).read_bytes()).hexdigest())",
                ]
            )
            .decode()
            .strip()
        )
        assert check == PATCH
        save(
            "publication-image.json",
            {
                "tag": IMAGE,
                "image_id": image["Id"],
                "architecture": "amd64",
                "base_image_id": BASE,
                "base_archive_sha256": ARCHIVE_SHA,
                "publication_sha256": PATCH,
                "change": "only publication.py",
                "browser_installed": False,
                "scope": "exact_core_single_file_derivative",
            },
        )
        print(
            json.dumps(
                {
                    "derivative_build": "PASS",
                    "image_id": image["Id"],
                    "tag": IMAGE,
                    "base_image_id": BASE,
                    "patch_sha256": PATCH,
                }
            ),
            flush=True,
        )
    finally:
        run(["docker", "buildx", "stop", BUILDER])


if __name__ == "__main__":
    main()

"""Owned public Jenkins build helper; no credentials/config environment output."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

CONTROLLER_FRONTEND = os.environ.get("ECS_NATIVE_CONTROLLER_BUILD", "") == "1"
assert os.environ.get("ECS_NATIVE_CONTROLLER_BUILD", "") in {"", "1"}
ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
OCI_ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-95ba9f3063f9/oci")
BUILDER = "deer-native-820d7a3429d9"
BUILDKIT_IMAGE = "moby/buildkit@sha256:cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea"
NODE_IMAGE = (
    "node@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402"
)
ARCHIVE_SHA = "e27c3d4ce58b7f762c09386cfe1fc97464c5df639dc2d855332713915e3fa34b"
BASES = {
    "PYTHON_IMAGE": "python@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258",
    "DOCKER_CLI_IMAGE": "docker@sha256:b1805116a6a86cc591b5d5f60a910a0715cdcc9d18d866ad68b1457ead25c35c",
    "UV_IMAGE": "ghcr.io/astral-sh/uv@sha256:fc93e9ecd7218e9ec8fba117af89348eef8fd2463c50c13347478769aaedd0ce",
}

if CONTROLLER_FRONTEND:
    ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6/frontend-build")
    OCI_ROOT = ROOT / "oci"
    BUILDER = "deer-native-ui-820d7a3429d9"
    BASES = {}
    BUILDKIT_IMAGE = (
        "sha256:cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea"
    )


def run(args, **kw):
    r = subprocess.run(args, capture_output=True, **kw)
    if r.returncode:
        raise RuntimeError("Command refused/failed: " + args[0] + " (output withheld)")
    return r.stdout


def save(name, value):
    (ROOT / "proof").mkdir(exist_ok=True)
    (ROOT / "proof" / name).write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value))


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cached_oci_context(alias, pin):
    """Use Docker's original OCI bytes; verify the selected amd64 chain."""
    if CONTROLLER_FRONTEND:
        assert alias == "nodebase" and pin == NODE_IMAGE
        assert (OCI_ROOT / "nodebase.tar").is_file()
    else:
        image = json.loads(run(["docker", "image", "inspect", pin]))[0]
        assert pin in image.get("RepoDigests", []) and image["Architecture"] == "amd64"
    parent = OCI_ROOT
    parent.mkdir(exist_ok=True)
    assert not parent.is_symlink()
    archive, layout = parent / (alias + ".tar"), parent / alias
    assert not archive.is_symlink()
    if not archive.exists():
        run(["docker", "image", "save", "-o", str(archive), pin], timeout=60)
    assert archive.is_file() and not archive.is_symlink()
    new_layout = not layout.exists()
    layout.mkdir(exist_ok=True)
    assert not layout.is_symlink()
    assert all(not path.is_symlink() for path in layout.rglob("*"))
    expected_files = set()
    expected_metadata = {}
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            name = Path(member.name)
            assert not name.is_absolute() and ".." not in name.parts
            if member.name not in {"index.json", "oci-layout"} and not re.fullmatch(
                r"blobs/sha256/[0-9a-f]{64}", member.name
            ):
                continue
            assert member.isfile() or member.islnk()
            destination = layout / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            assert not destination.parent.is_symlink() and not destination.is_symlink()
            if new_layout:
                with (
                    tar.extractfile(member) as stream,
                    destination.open("xb") as output,
                ):
                    shutil.copyfileobj(stream, output, length=1024 * 1024)
            if member.name in {"index.json", "oci-layout"}:
                expected_metadata[member.name] = hashlib.sha256(
                    tar.extractfile(member).read()
                ).hexdigest()
            expected_files.add(member.name)
    actual_files = set()
    for path in layout.rglob("*"):
        assert not path.is_symlink()
        if path.is_file():
            name = str(path.relative_to(layout))
            actual_files.add(name)
            if name.startswith("blobs/"):
                assert file_sha256(path) == path.name
        else:
            assert str(path.relative_to(layout)) in {"blobs", "blobs/sha256"}
    assert actual_files == expected_files
    assert all(
        file_sha256(layout / name) == value for name, value in expected_metadata.items()
    )
    assert json.loads((layout / "oci-layout").read_text()) == {
        "imageLayoutVersion": "1.0.0"
    }
    index = json.loads((layout / "index.json").read_text())
    digest = pin.split("@", 1)[1]
    roots = [d for d in index["manifests"] if d["digest"] == digest]
    assert len(roots) == 1
    closed = set()

    def blob(descriptor):
        value = descriptor["digest"]
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", value)
        path = layout / "blobs/sha256" / value.split(":", 1)[1]
        assert path.is_file() and path.stat().st_size == descriptor["size"]
        assert file_sha256(path) == value.split(":", 1)[1]
        closed.add(value)
        return path

    manifest = json.loads(blob(roots[0]).read_text())
    if "manifests" in manifest:
        selected = [
            d
            for d in manifest["manifests"]
            if d.get("platform", {}).get("os") == "linux"
            and d["platform"].get("architecture") == "amd64"
        ]
        assert len(selected) == 1
        manifest = json.loads(blob(selected[0]).read_text())
    config = json.loads(blob(manifest["config"]).read_text())
    assert config["architecture"] == "amd64" and config["os"] == "linux"
    for layer in manifest["layers"]:
        blob(layer)
    proof = {
        "alias": alias,
        "original_repo_digest": pin,
        "original_oci_root_digest": digest,
        "verified_blob_count": len(actual_files) - 2,
        "closed_amd64_descriptor_count": len(closed),
    }
    save(alias + "-oci.json", proof)
    return "oci-layout://" + str(layout) + "@" + digest


def prepare_controller_builder_container():
    """Precreate the owned driver container so Buildx takes its existing path."""
    container = "buildx_buildkit_" + BUILDER + "0"
    volume = container + "_state"
    label = "deerflow.native.build"
    owner = "820d7a3429d9"
    metadata = (
        Path(os.environ.get("DOCKER_CONFIG", str(Path.home() / ".docker")))
        / "buildx/instances"
        / BUILDER
    )
    assert not metadata.is_symlink() and metadata.stat().st_uid == os.getuid()
    definition = json.loads(metadata.read_text())
    assert definition["Driver"] == "docker-container" and len(definition["Nodes"]) == 1
    node = definition["Nodes"][0]
    assert (
        node["Name"] == BUILDER + "0"
        and node["Endpoint"] == "unix:///var/run/docker.sock"
    )
    options = node["DriverOpts"]
    assert options == {
        "image": BUILDKIT_IMAGE,
        "memory": "5g",
        "memory-swap": "5g",
        "cpu-quota": "100000",
        "cpu-period": "100000",
        "restart-policy": "no",
    }
    flags = node.get("Flags") or []
    assert flags in ([], ["--allow-insecure-entitlement=network.host"])
    existing = subprocess.run(["docker", "inspect", container], capture_output=True)
    if existing.returncode == 0:
        value = json.loads(existing.stdout)[0]
        assert value["Config"]["Labels"].get(label) == owner
        assert value["Image"] == BUILDKIT_IMAGE and not value["State"]["Running"]
    else:
        prior_volume = subprocess.run(
            ["docker", "volume", "inspect", volume], capture_output=True
        )
        if prior_volume.returncode == 0:
            assert (
                json.loads(prior_volume.stdout)[0].get("Labels", {}).get(label) == owner
            )
        else:
            run(["docker", "volume", "create", "--label", label + "=" + owner, volume])
        args = [
            "docker",
            "create",
            "--pull",
            "never",
            "--name",
            container,
            "--label",
            label + "=" + owner,
            "--privileged",
            "--init",
            "--restart",
            "no",
            "--memory",
            "5g",
            "--memory-swap",
            "5g",
            "--cpu-quota",
            "100000",
            "--cpu-period",
            "100000",
            "--mount",
            "type=volume,src=" + volume + ",dst=/var/lib/buildkit",
        ]
        driver = run(
            [
                "docker",
                "info",
                "--format",
                "{{.CgroupDriver}} {{json .SecurityOptions}}",
            ]
        ).decode()
        if driver.startswith("cgroupfs "):
            args.extend(["--cgroup-parent", "/docker/buildx"])
        if "name=userns" in driver:
            args.extend(["--userns", "host"])
        run([*args, BUILDKIT_IMAGE, *flags])
    value = json.loads(run(["docker", "inspect", container]))[0]
    host = value["HostConfig"]
    assert (
        value["Config"]["Labels"].get(label) == owner
        and value["Image"] == BUILDKIT_IMAGE
    )
    assert (value["Config"].get("Cmd") or []) == flags
    assert (
        host["Privileged"] is True
        and host["Init"] is True
        and host["RestartPolicy"]["Name"] == "no"
    )
    assert (
        host["Memory"] == host["MemorySwap"] == 5368709120
        and host["CpuQuota"] == host["CpuPeriod"] == 100000
    )
    mounts = value["Mounts"]
    assert (
        len(mounts) == 1
        and mounts[0]["Type"] == "volume"
        and mounts[0]["Name"] == volume
        and mounts[0]["Destination"] == "/var/lib/buildkit"
        and mounts[0]["RW"] is True
    )
    assert (
        json.loads(run(["docker", "volume", "inspect", volume]))[0]
        .get("Labels", {})
        .get(label)
        == owner
    )


def main(action):
    if CONTROLLER_FRONTEND:
        assert action in {"verify-source", "builder", "frontend", "stop-builder"}
    if action == "verify-source":
        assert sys.argv[2] == ARCHIVE_SHA
        archive = ROOT / "deer-native-source-56636cebddc6.tar.gz"
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == ARCHIVE_SHA
        source = ROOT / "source"
        if not source.exists():
            source.mkdir()
            with tarfile.open(archive) as tar:
                for m in tar.getmembers():
                    p = Path(m.name)
                    assert (
                        not p.is_absolute()
                        and ".." not in p.parts
                        and (m.isfile() or m.issym())
                    )
                    if m.issym():
                        assert (
                            not Path(m.linkname).is_absolute()
                            and ".." not in Path(m.linkname).parts
                        )
                tar.extractall(source, filter="data")
        entries = {}
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                if member.issym():
                    assert (source / member.name).is_symlink()
                    assert os.readlink(source / member.name) == member.linkname
                    entries[member.name] = "link:" + member.linkname
                else:
                    expected = hashlib.sha256(
                        tar.extractfile(member).read()
                    ).hexdigest()
                    actual = source / member.name
                    assert actual.is_file() and not actual.is_symlink()
                    assert hashlib.sha256(actual.read_bytes()).hexdigest() == expected
                    entries[member.name] = "file:" + expected
        actual_entries = set()
        allowed_directories = {
            str(parent)
            for name in entries
            for parent in Path(name).parents
            if str(parent) != "."
        }
        for base, directories, files in os.walk(source, followlinks=False):
            for name in list(directories) + files:
                entry = Path(base) / name
                relative = str(entry.relative_to(source))
                if entry.is_symlink() or entry.is_file():
                    actual_entries.add(relative)
                else:
                    assert relative in allowed_directories
        assert actual_entries == set(entries)
        source_hash = hashlib.sha256(
            "\n".join(
                name + ":" + value[5:]
                for name, value in sorted(entries.items())
                if value.startswith("file:")
            ).encode()
        ).hexdigest()
        assert (
            source_hash
            == "56636cebddc6060cc4929a7f0fd86d45eb7c21c5890fb2f7f1d1128226ac4af5"
        )
        entry_hash = hashlib.sha256(
            "\n".join(
                name + ":" + value for name, value in sorted(entries.items())
            ).encode()
        ).hexdigest()
        manifest = json.loads(
            (ROOT / "deer-native-task6b-shanghai-freeze.json").read_text()
        )
        assert all(
            hashlib.sha256((source / n).read_bytes()).hexdigest() == h
            for n, h in manifest["files"].items()
        )
        save(
            "source.json",
            {
                "archive_sha256": ARCHIVE_SHA,
                "ci_helper_sha256": file_sha256(Path(__file__)),
                "ops_paths_hash_match": 27,
                "source_sha256": source_hash,
                "archive_entry_sha256": entry_hash,
                "verified_archive_entries": len(entries),
                "backend_uv_lock_sha256": hashlib.sha256(
                    (source / "backend/uv.lock").read_bytes()
                ).hexdigest(),
            },
        )
    elif action == "builder":
        assert shutil.disk_usage(ROOT).free >= 12 * 1024**3
        available = next(
            int(line.split()[1]) * 1024
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemAvailable:")
        )
        assert available >= (int(6.5 * 1024**3) if CONTROLLER_FRONTEND else 5 * 1024**3)
        existing = subprocess.run(
            ["docker", "buildx", "inspect", BUILDER], capture_output=True
        )
        if existing.returncode:
            run(
                [
                    "docker",
                    "buildx",
                    "create",
                    "--name",
                    BUILDER,
                    "--driver",
                    "docker-container",
                    "--driver-opt",
                    "image=" + BUILDKIT_IMAGE,
                    "--driver-opt",
                    "memory=5g" if CONTROLLER_FRONTEND else "memory=3g",
                    "--driver-opt",
                    "memory-swap=5g" if CONTROLLER_FRONTEND else "memory-swap=3g",
                    "--driver-opt",
                    "cpu-quota=100000",
                    "--driver-opt",
                    "cpu-period=100000",
                    "--driver-opt",
                    "restart-policy=no",
                ]
            )
        container = "buildx_buildkit_" + BUILDER + "0"
        expected_image = json.loads(
            run(["docker", "image", "inspect", BUILDKIT_IMAGE])
        )[0]
        if CONTROLLER_FRONTEND:
            assert expected_image["Id"] == BUILDKIT_IMAGE
        else:
            assert BUILDKIT_IMAGE in expected_image.get("RepoDigests", [])
        if CONTROLLER_FRONTEND:
            prepare_controller_builder_container()
        previous = subprocess.run(["docker", "inspect", container], capture_output=True)
        if previous.returncode == 0:
            prior = json.loads(previous.stdout)[0]
            assert prior["Image"] == expected_image["Id"]
            assert not prior["State"]["Running"]
        run(["docker", "buildx", "inspect", BUILDER, "--bootstrap"])
        data = json.loads(run(["docker", "inspect", container]))[0]
        assert data["Image"] == expected_image["Id"]
        version = (
            run(["docker", "exec", container, "buildkitd", "--version"])
            .decode()
            .strip()
        )
        assert version.split()[2] == "v0.33.1"
        c = data["HostConfig"]
        assert (
            c["Memory"] == (5368709120 if CONTROLLER_FRONTEND else 3221225472)
            and c["MemorySwap"] == (5368709120 if CONTROLLER_FRONTEND else 3221225472)
            and c["CpuQuota"] == 100000
            and c["CpuPeriod"] == 100000
        )
        cpu = (
            run(["docker", "exec", container, "cat", "/sys/fs/cgroup/cpu.max"])
            .decode()
            .strip()
        )
        memory = (
            run(["docker", "exec", container, "cat", "/sys/fs/cgroup/memory.max"])
            .decode()
            .strip()
        )
        swap = (
            run(["docker", "exec", container, "cat", "/sys/fs/cgroup/memory.swap.max"])
            .decode()
            .strip()
        )
        assert (
            cpu == "100000 100000"
            and memory == ("5368709120" if CONTROLLER_FRONTEND else "3221225472")
            and swap == "0"
        )
        save(
            "builder.json",
            {
                "builder": BUILDER,
                "container_id": data["Id"],
                "buildkit_image": BUILDKIT_IMAGE,
                "buildkit_upstream_digest": "moby/buildkit@sha256:cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea",
                "buildkit_image_id": data["Image"],
                "buildkit_version": version,
                "memory_bytes": c["Memory"],
                "cpu_quota": c["CpuQuota"],
                "cpu_period": c["CpuPeriod"],
                "kernel_cpu_max": cpu,
                "kernel_memory_max": memory,
                "kernel_memory_swap_max": swap,
                "bases": BASES,
            },
        )
    elif action in ("backend", "backend-core", "frontend"):
        is_backend = action in ("backend", "backend-core")
        image = (
            "deerflow-native:05e260329244"
            + ("-core" if action == "backend-core" else "")
            if is_backend
            else "deerflow-native-ui:56636cebddc6"
        )
        args = [
            "docker",
            "buildx",
            "build",
            "--builder",
            BUILDER,
            "--platform",
            "linux/amd64",
            "--load",
            "--progress",
            "plain",
            "--target",
            ("native-core" if action == "backend-core" else "native-role")
            if is_backend
            else "prod",
            "-f",
            "backend/Dockerfile" if is_backend else "frontend/Dockerfile",
            "-t",
            image,
        ]
        if is_backend:
            aliases = {
                "PYTHON_IMAGE": "pythonbase",
                "DOCKER_CLI_IMAGE": "dockerbase",
                "UV_IMAGE": "uvbase",
            }
            for key, pin in BASES.items():
                alias = aliases[key]
                args += [
                    "--build-context",
                    alias + "=" + cached_oci_context(alias, pin),
                    "--build-arg",
                    key + "=" + alias,
                ]
            args += [
                "--build-arg",
                "UV_EXTRAS=postgres,browser",
                "--build-arg",
                "UV_ARTIFACT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/pypi/web",
                "--build-arg",
                "UV_BUILD_LOG=uv_client=trace,uv_distribution=debug",
                "--build-arg",
                "APT_MIRROR=mirrors.tuna.tsinghua.edu.cn",
            ]
        else:
            args += [
                "--build-context",
                "node:22-alpine=" + cached_oci_context("nodebase", NODE_IMAGE),
                "--build-arg",
                "DEER_FLOW_BUILD_BUNDLER=webpack",
                "--build-arg",
                "DEER_FLOW_BUILD_MEMORY_OPTIMIZATIONS=1",
                "--build-arg",
                "NPM_REGISTRY=https://registry.npmmirror.com",
            ]
        args += ["."]
        log_path = ROOT / (action + "-build.log")
        assert not log_path.is_symlink()
        descriptor = os.open(
            log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as log:
            r = subprocess.run(
                args, cwd=ROOT / "source", stdout=log, stderr=subprocess.STDOUT
            )
        assert r.returncode == 0, (
            "Public build failed; captured log requires safe diagnosis"
        )
        data = json.loads(run(["docker", "image", "inspect", image]))[0]
        assert data["Architecture"] == "amd64"
        proof = {
            "image": image,
            "image_id": data["Id"],
            "architecture": "amd64",
            "source_archive_sha256": ARCHIVE_SHA,
        }
        if is_backend:
            code = "import hashlib,json;from pathlib import Path;import ecs_executor,deerflow,deerflow_extension_api;from playwright.sync_api import sync_playwright;p=sync_playwright().start();c=Path(p.chromium.executable_path);assert c.is_file();print(json.dumps({'uv_lock_sha256':hashlib.sha256(Path('/app/backend/uv.lock').read_bytes()).hexdigest(),'imports_current':all('/app/backend/' in str(x.__file__) for x in [ecs_executor,deerflow,deerflow_extension_api]),'chromium_present':True,'browser_installed':True}));p.stop()"
            if action == "backend-core":
                code = "import hashlib,json;from pathlib import Path;import ecs_executor,deerflow,deerflow_extension_api;assert not Path('/opt/deerflow-browsers').exists();print(json.dumps({'uv_lock_sha256':hashlib.sha256(Path('/app/backend/uv.lock').read_bytes()).hexdigest(),'imports_current':all('/app/backend/' in str(x.__file__) for x in [ecs_executor,deerflow,deerflow_extension_api]),'chromium_present':False,'browser_installed':False,'browser_capability':'pending_unavailable'}))"
            verified = json.loads(
                run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--network",
                        "none",
                        "--cpus",
                        "0.5",
                        "--memory",
                        "512m",
                        "--entrypoint",
                        "python",
                        data["Id"],
                        "-c",
                        code,
                    ]
                )
            )
            assert (
                verified["imports_current"]
                and verified["uv_lock_sha256"]
                == json.loads((ROOT / "proof/source.json").read_text())[
                    "backend_uv_lock_sha256"
                ]
            )
            proof.update(verified)
        save(action + "-image.json", proof)
    elif action == "stop-builder":
        subprocess.run(
            ["docker", "buildx", "stop", BUILDER],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        raise ValueError("Unsupported owned action")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as e:
        print(
            json.dumps(
                {
                    "result": "failed",
                    "exception_class": type(e).__name__,
                    "action": sys.argv[1],
                }
            )
        )
        raise SystemExit(1)

"""Fixed a216 derivative: official headless-shell install and one non-root launch proof."""

import base64
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import signal
import stat
import subprocess
import time

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
WORK = ROOT / "browser-mcr-repair-1.61.0-1228"
BASE = "sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1"
ARCHIVE_SHA = "7af52c065c3246eb96685897334d0cafe93c43e83fa9b72742798450a0549f03"
IMAGE = "deerflow-native:browser-mcr-1.61.0-1228-a216"
HELPER_SHA = "7e6740f52091e62cb805a31d425a59f22cc14b8d0b3dd9f17879bed56fb92874"
DOCKERFILE_SHA = "ac09bfa6c692488da98fac4a1cb48bb3458c793d01fe3ce269457bd89977db9f"
VERIFY_SHA = "b618cdaf34c19a4cf82263110ce21cc8dbb6708da8a935ac7bd80d3fdbb8d91e"
LAYER_HELPER_SHA = "f7dfbd6999ec785ef5cb60aee84da66f37162a09d4f7e721a7476e31335724fd"
DEADLINE = time.monotonic() + 1740


def public_file(path, expected):
    s = path.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and not path.is_symlink()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def checked(args, timeout=120):
    remaining = DEADLINE - time.monotonic() - 60
    assert remaining > 0, "Browser phase deadline reached"
    result = subprocess.run(args, capture_output=True, timeout=min(timeout, remaining))
    assert result.returncode == 0, "Owned browser command failed; retain diagnostics"
    return result.stdout


def module():
    helper = ROOT / "scripts/ecs_native_publication_build.py"
    public_file(helper, HELPER_SHA)
    spec = importlib.util.spec_from_file_location("reviewed_oci", helper)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.WORK = WORK
    m.BASE = BASE
    m.ARCHIVE = ROOT / "transfer/publication-bdd2931a1a6f-image.tar"
    m.ARCHIVE_SHA = ARCHIVE_SHA
    return m


def owned_builder(m):
    b = json.loads(checked(["docker", "inspect", m.CONTAINER]))[0]
    assert b["Id"] == m.CONTAINER_ID and b["Image"] == m.BUILDKIT
    h = b["HostConfig"]
    assert h["Memory"] == h["MemorySwap"] == 3 * 1024**3
    assert h["CpuQuota"] == h["CpuPeriod"] == 100000
    assert [
        (x["Type"], x.get("Name"), x["Destination"], x["RW"]) for x in b["Mounts"]
    ] == [
        (
            "volume",
            "buildx_buildkit_deer-native-820d7a3429d90_state",
            "/var/lib/buildkit",
            True,
        )
    ]
    return b


def stop_builder(m):
    # Cleanup never selects an unverified name or a controller/role container.
    b = json.loads(
        subprocess.check_output(["docker", "inspect", m.CONTAINER], timeout=15)
    )[0]
    assert b["Id"] == m.CONTAINER_ID and b["Image"] == m.BUILDKIT
    subprocess.run(
        ["docker", "stop", "--time", "10", m.CONTAINER_ID],
        check=True,
        capture_output=True,
        timeout=30,
    )
    assert not json.loads(
        subprocess.check_output(["docker", "inspect", m.CONTAINER_ID], timeout=15)
    )[0]["State"]["Running"]


def cleanup_check(m, kind):
    assert kind in ["red", "green"]
    cidfile = WORK / ("check-" + kind + ".cid")
    if not cidfile.exists():
        assert not cidfile.is_symlink()
        return  # Docker never created this fixture.
    for path in [cidfile, WORK / ("check-" + kind + ".image.json")]:
        s = path.lstat()
        assert (
            stat.S_ISREG(s.st_mode)
            and s.st_uid == os.getuid()
            and stat.S_IMODE(s.st_mode) == 0o600
        )
    cid = cidfile.read_text().strip()
    assert re.fullmatch(r"[0-9a-f]{64}", cid)
    receipt = json.loads((WORK / ("check-" + kind + ".image.json")).read_text())
    assert receipt["kind"] == kind and re.fullmatch(
        r"sha256:[0-9a-f]{64}", receipt["image_id"]
    )
    inspected = subprocess.run(
        ["docker", "container", "inspect", cid], capture_output=True, timeout=15
    )
    if inspected.returncode:
        assert inspected.returncode == 1 and b"No such container" in inspected.stderr
        return  # --rm already removed this exact CID.
    c = json.loads(inspected.stdout)[0]
    h = c["HostConfig"]
    assert c["Id"] == cid and c["Image"] == receipt["image_id"]
    assert (
        c["Name"] == "/deer-native-browser-mcr-repair-check-" + kind + "-820d7a3429d9"
    )
    assert c["Config"]["User"] == "1000:1000"
    assert (
        c["Config"]["Labels"]["org.deerflow.native.browser.phase"]
        == "browser-mcr-repair-1.61.0-1228-a216"
    )
    assert c["Config"]["Labels"]["org.deerflow.native.browser.check"] == kind
    assert h["NetworkMode"] == "none" and h["NanoCpus"] == 1000000000
    assert h["Memory"] == h["MemorySwap"] == 1073741824 and h["AutoRemove"]
    proof = {
        "container_id": cid,
        "image_id": receipt["image_id"],
        "kind": kind,
        "user": c["Config"]["User"],
        "network": h["NetworkMode"],
        "nano_cpus": h["NanoCpus"],
        "memory": h["Memory"],
        "memory_swap": h["MemorySwap"],
        "ownership_verified": True,
    }
    proofpath = ROOT / "proof" / ("browser-mcr-repair-check-" + kind + "-cleanup.json")
    if not proofpath.exists():
        m.save(proofpath.name, proof)
    if c["State"]["Running"]:
        subprocess.run(
            ["docker", "stop", "--time", "5", cid],
            check=True,
            capture_output=True,
            timeout=15,
        )
    remaining = subprocess.run(
        ["docker", "container", "inspect", cid], capture_output=True, timeout=15
    )
    if remaining.returncode == 0:
        assert json.loads(remaining.stdout)[0]["Id"] == cid
        subprocess.run(
            ["docker", "rm", cid], check=True, capture_output=True, timeout=15
        )
    else:
        assert remaining.returncode == 1 and b"No such container" in remaining.stderr


def verify(m, image, red=False):
    kind = "red" if red else "green"
    cidfile = WORK / ("check-" + kind + ".cid")
    imagefile = WORK / ("check-" + kind + ".image.json")
    name = "deer-native-browser-mcr-repair-check-" + kind + "-820d7a3429d9"
    assert not cidfile.exists() and not cidfile.is_symlink()
    assert not imagefile.exists() and not imagefile.is_symlink()
    assert (
        subprocess.run(
            ["docker", "container", "inspect", name], capture_output=True, timeout=15
        ).returncode
        != 0
    )
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image)
    fd = os.open(imagefile, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump({"image_id": image, "kind": kind}, stream)
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--cidfile",
                str(cidfile),
                "--name",
                name,
                "--label",
                "org.deerflow.native.browser.phase=browser-mcr-repair-1.61.0-1228-a216",
                "--label",
                "org.deerflow.native.browser.check=" + kind,
                "--network",
                "none",
                "--cpus",
                "1",
                "--memory",
                "1g",
                "--memory-swap",
                "1g",
                "--user",
                "1000:1000",
                "-e",
                "HOME=/tmp",
                "-v",
                str(WORK / "verify.py") + ":/run/browser-verify.py:ro",
                image,
                "python",
                "/run/browser-verify.py",
            ],
            capture_output=True,
            timeout=min(120, DEADLINE - time.monotonic() - 60),
        )
    finally:
        cleanup_check(m, kind)
    if red:
        assert result.returncode == 3 and json.loads(result.stdout) == {
            "browser_distribution": "MISSING_HEADLESS_SHELL_1228"
        }, "Prebuild missing-browser check did not fail as expected"
        m.save(
            "browser-mcr-repair-red.json",
            {
                "base_image_id": BASE,
                "missing_revision": "1228",
                "expected_failure": True,
                "models_called": False,
            },
        )
        return
    assert result.returncode == 0, (
        "Non-root browser launch failed; retain image for diagnosis"
    )
    proof = json.loads(result.stdout)
    png = base64.b64decode(proof.pop("screenshot_base64"), validate=True)
    assert hashlib.sha256(png).hexdigest() == proof["screenshot_sha256"]
    fd = os.open(
        ROOT / "proof/browser-mcr-repair-headless.png",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "wb") as stream:
        stream.write(png)
    assert (
        proof["browser_distribution"] == "PASS"
        and proof["uid"] == 1000
        and proof["input_verified"]
    )
    proof["image_id"] = image
    proof["base_image_id"] = BASE
    m.save("browser-mcr-repair-green.json", proof)
    return proof


def main():
    m = module()
    if os.sys.argv[1:] == ["--cleanup"]:
        try:
            for kind in ["red", "green"]:
                cleanup_check(m, kind)
        finally:
            stop_builder(m)
        return
    assert not os.sys.argv[1:]
    assert WORK.is_dir() and not WORK.is_symlink() and WORK.stat().st_uid == os.getuid()
    context = WORK / "context"
    assert (
        context.is_dir()
        and not context.is_symlink()
        and {p.name for p in context.iterdir()} == {"Dockerfile"}
    )
    public_file(context / "Dockerfile", DOCKERFILE_SHA)
    public_file(WORK / "verify.py", VERIFY_SHA)
    assert stat.S_IMODE((WORK / "verify.py").stat().st_mode) == 0o644
    memory = next(
        int(x.split()[1]) * 1024
        for x in Path("/proc/meminfo").read_text().splitlines()
        if x.startswith("MemAvailable:")
    )
    assert memory >= 5 * 1024**3
    assert not owned_builder(m)["State"]["Running"]
    assert not any(
        x.startswith("buildx_buildkit_")
        for x in checked(["docker", "ps", "--format", "{{.Names}}"])
        .decode()
        .splitlines()
    ), "Build host is not idle"
    base = json.loads(checked(["docker", "image", "inspect", BASE]))[0]
    assert base["Id"] == base["Descriptor"]["digest"] == BASE
    assert (
        subprocess.run(
            ["docker", "image", "inspect", IMAGE], capture_output=True, timeout=15
        ).returncode
        != 0
    )
    ctx = (
        m.core_context()
    )  # Reuses all archive, blob, size, architecture and manifest/config checks.
    try:
        verify(m, BASE, red=True)
        layer_helper = ROOT / "scripts/ecs_native_browser_mcr_repair_layer.py"
        public_file(layer_helper, LAYER_HELPER_SHA)
        spec = importlib.util.spec_from_file_location("official_layer", layer_helper)
        distribution = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(distribution)
        layer_receipt = distribution.prepare(WORK, DEADLINE - 420)
        m.save("browser-mcr-repair-layer.json", layer_receipt)
        assert {p.name for p in context.iterdir()} == {
            "Dockerfile",
            "browser-artifacts",
        }
        checked(["docker", "buildx", "inspect", m.BUILDER, "--bootstrap"])
        assert owned_builder(m)["State"]["Running"]
        limits = (
            checked(
                [
                    "docker",
                    "exec",
                    m.CONTAINER_ID,
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
        m.save(
            "browser-mcr-repair-builder.json",
            {
                "container_id": m.CONTAINER_ID,
                "kernel_limits": limits,
                "memory_available_before": memory,
                "base_image_id": BASE,
                "base_archive_sha256": ARCHIVE_SHA,
                "dockerfile_sha256": DOCKERFILE_SHA,
                "scope": "headless_no_channel_distribution_only",
            },
        )
        log = ROOT / "proof/browser-mcr-repair-build.log"
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            result = subprocess.run(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--builder",
                    m.BUILDER,
                    "--platform",
                    "linux/amd64",
                    "--progress",
                    "plain",
                    "--build-context",
                    "native-core=" + ctx,
                    "--load",
                    "--tag",
                    IMAGE,
                    str(context),
                ],
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=DEADLINE - time.monotonic() - 180,
            )
        assert result.returncode == 0, (
            "Official browser install failed; public build log retained"
        )
        image = json.loads(checked(["docker", "image", "inspect", IMAGE]))[0]
        assert (
            image["Architecture"] == "amd64"
            and image["Id"] == image["Descriptor"]["digest"]
        )
        proof = verify(m, image["Id"])
        m.save(
            "browser-mcr-repair-image.json",
            {
                "tag": IMAGE,
                "image_id": image["Id"],
                "base_image_id": BASE,
                "base_archive_sha256": ARCHIVE_SHA,
                "browser_version": proof["browser_version"],
                "binary_sha256": proof["binary_sha256"],
                "dockerfile_sha256": DOCKERFILE_SHA,
                "verify_sha256": VERIFY_SHA,
                "change": "verified official MCR headless-shell1228/FFmpeg1011 plus original CLI Debian dependencies/links/validation",
                "official_distribution": layer_receipt,
                "layer_helper_sha256": LAYER_HELPER_SHA,
                "scope": "headless_no_channel_distribution_only",
                "roles_changed": False,
                "models_called": False,
            },
        )
        print(
            json.dumps(
                {
                    "browser_build": "PASS",
                    "image_id": image["Id"],
                    "browser_version": proof["browser_version"],
                    "binary_sha256": proof["binary_sha256"],
                    "nonroot_page_screenshot": True,
                    "roles_changed": False,
                    "models_called": False,
                }
            ),
            flush=True,
        )
    except BaseException as exc:
        m.save(
            "browser-mcr-repair-build-failure.json",
            {
                "exception_class": type(exc).__name__,
                "roles_changed": False,
                "models_called": False,
                "public_build_log": "proof/browser-mcr-repair-build.log",
                "retry_automatic": False,
            },
        )
        raise
    finally:
        try:
            for kind in ["red", "green"]:
                cleanup_check(m, kind)
        finally:
            stop_builder(m)


def interrupted(signum, frame):
    raise RuntimeError("Browser phase interrupted")


if __name__ == "__main__":
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupted)
    main()

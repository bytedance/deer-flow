"""Owned Jenkins offline gates; no role, configuration, admission or model actions."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import uuid

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
IMAGE = "sha256:52ce23272ed5c945389367eb92f97fdd6754aa93d1c369bb01d7a44d45c5f47e"
INNER_SHA = "c6ae442b472e3c7f5cd998e0d168227b77a9e5ebf9331491d0cbec7595635ca7"


def public(path, expected):
    current = path
    while current != ROOT:
        assert not current.is_symlink()
        current = current.parent
        assert current.is_relative_to(ROOT)
    before = path.lstat()
    assert (
        stat.S_ISREG(before.st_mode)
        and before.st_nlink == 1
        and before.st_uid == os.getuid()
    )
    assert stat.S_IMODE(before.st_mode) == 0o600
    data = path.read_bytes()
    after = path.lstat()
    fields = [
        "st_dev",
        "st_ino",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_mode",
        "st_uid",
        "st_nlink",
    ]
    assert all(getattr(before, k) == getattr(after, k) for k in fields)
    assert hashlib.sha256(data).hexdigest() == expected
    return data


def inspect_exact(target):
    result = subprocess.run(
        ["docker", "container", "inspect", "--format", "{{json .}}", target],
        capture_output=True,
        timeout=15,
    )
    if result.returncode == 0:
        value = json.loads(result.stdout)
        assert isinstance(value, dict)
        return value
    assert result.returncode == 1 and result.stdout == b""
    assert (
        result.stderr
        == ("Error response from daemon: No such container: " + target + "\n").encode()
    ), "Unexpected Docker inspect failure"
    return None


def cleanup_fixture(work, archive):
    info = work.lstat()
    assert (
        stat.S_ISDIR(info.st_mode)
        and not work.is_symlink()
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o700
    )
    assert work.parent == ROOT and re.fullmatch(
        r"native-final-code-gates-[0-9a-f]{32}", work.name
    )
    cidfile = work / "fixture.cid"
    owned = work.name
    try:
        before = cidfile.lstat()
    except FileNotFoundError:
        assert inspect_exact(owned) is None, (
            "Missing CID but exact owned name exists; retain for diagnosis"
        )
        return True
    assert (
        stat.S_ISREG(before.st_mode)
        and not cidfile.is_symlink()
        and before.st_uid == os.getuid()
        and before.st_nlink == 1
    )
    assert stat.S_IMODE(before.st_mode) == 0o600
    cid = cidfile.read_text().strip()
    fields = [
        "st_dev",
        "st_ino",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_mode",
        "st_uid",
        "st_nlink",
    ]
    after = cidfile.lstat()
    assert all(getattr(before, k) == getattr(after, k) for k in fields)
    assert re.fullmatch("[0-9a-f]{64}", cid)
    c = inspect_exact(cid)
    if c is not None:
        h = c["HostConfig"]
        labels = c["Config"]["Labels"]
        assert c["Id"] == cid and c["Image"] == IMAGE and c["Config"]["User"] == "0:0"
        assert (
            labels["org.deerflow.native.owned"] == owned
            and labels["org.deerflow.native.phase"] == "final-offline-code-gates"
        )
        assert (
            h["NanoCpus"] == 1000000000
            and h["Memory"] == h["MemorySwap"] == 3221225472
            and h["NetworkMode"] == "none"
        )
        assert [(m["Source"], m["Destination"], m["RW"]) for m in c["Mounts"]] == [
            (str(archive), "/run/public-source.tar.gz", False)
        ]
        subprocess.run(
            ["docker", "rm", "-f", cid], check=True, capture_output=True, timeout=30
        )
    assert inspect_exact(cid) is None
    return True


def main():
    os.umask(0o077)
    active = ROOT / "proof/final-code-gates-active.json"
    if os.sys.argv[1:] == ["--cleanup"]:
        try:
            info = active.lstat()
        except FileNotFoundError:
            result = subprocess.run(
                [
                    "docker",
                    "container",
                    "ls",
                    "--all",
                    "--quiet",
                    "--no-trunc",
                    "--filter",
                    "label=org.deerflow.native.phase=final-offline-code-gates",
                ],
                check=True,
                capture_output=True,
                timeout=15,
            )
            assert result.stdout == b"", (
                "Missing active marker with a phase fixture present; retain for diagnosis"
            )
            print(
                json.dumps(
                    {"code_gate_not_started": True, "matching_phase_fixture_count": 0}
                )
            )
            return
        assert (
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600
            and not active.is_symlink()
        )
        record = json.loads(active.read_text())
        assert record["image_id"] == IMAGE and record["inner_sha256"] == INNER_SHA
        assert re.fullmatch(r"native-final-code-gates-[0-9a-f]{32}", record["owned"])
        assert re.fullmatch(
            r"deer-native-final-source-[0-9a-f]{12}\.tar\.gz", record["archive_name"]
        )
        work = ROOT / record["owned"]
        assert (
            work.is_dir()
            and not work.is_symlink()
            and stat.S_IMODE(work.stat().st_mode) == 0o700
        )
        assert cleanup_fixture(work, ROOT / "transfer" / record["archive_name"])
        print(json.dumps({"owned_code_gate_fixture_cleanup": True}))
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("archive_name")
    parser.add_argument("archive_sha256")
    parser.add_argument("source_sha256")
    parser.add_argument("manifest_sha256")
    args = parser.parse_args()
    assert re.fullmatch(
        r"deer-native-final-source-[0-9a-f]{12}\.tar\.gz", args.archive_name
    )
    for value in [args.archive_sha256, args.source_sha256, args.manifest_sha256]:
        assert re.fullmatch("[0-9a-f]{64}", value)
    assert args.source_sha256.startswith(args.archive_name[25:37])
    archive = ROOT / "transfer" / args.archive_name
    public(archive, args.archive_sha256)
    inner = public(ROOT / "scripts/ecs_native_final_code_gates_inner.py", INNER_SHA)
    image = json.loads(
        subprocess.check_output(["docker", "image", "inspect", IMAGE], timeout=15)
    )[0]
    assert image["Id"] == IMAGE
    owned = "native-final-code-gates-" + uuid.uuid4().hex
    work = ROOT / owned
    work.mkdir(mode=0o700)
    cidfile = work / "fixture.cid"
    log = work / "public-gates.log"
    assert not cidfile.exists()
    record = {
        "owned": owned,
        "archive_name": args.archive_name,
        "image_id": IMAGE,
        "inner_sha256": INNER_SHA,
    }
    fd = os.open(active, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(record, stream)
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--cidfile",
        str(cidfile),
        "--name",
        owned,
        "--label",
        "org.deerflow.native.phase=final-offline-code-gates",
        "--label",
        "org.deerflow.native.owned=" + owned,
        "--network",
        "none",
        "--user",
        "0:0",
        "--cpus",
        "1",
        "--memory",
        "3g",
        "--memory-swap",
        "3g",
        "-v",
        str(archive) + ":/run/public-source.tar.gz:ro",
        IMAGE,
        "python",
        "-",
        args.source_sha256,
        args.manifest_sha256,
    ]
    cleanup = False
    failure = None
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            try:
                result = subprocess.run(
                    command,
                    input=inner,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=4800,
                )
                failure = None if result.returncode == 0 else "gate_exit_nonzero"
            except subprocess.TimeoutExpired:
                failure = "phase_deadline"
    finally:
        cleanup = cleanup_fixture(work, archive)
    assert cleanup, "Exact owned fixture cleanup not proven"
    reports = []
    for line in log.read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "offline_code_gates" in value:
            reports.append(value)
    accepted = (
        len(reports) == 1
        and reports[0]["offline_code_gates"] == "PASS"
        and failure is None
    )
    receipt = {
        "offline_code_gates": "PASS" if accepted else "FAIL",
        "image_id": IMAGE,
        "archive_sha256": args.archive_sha256,
        "source_sha256": args.source_sha256,
        "manifest_sha256": args.manifest_sha256,
        "inner_sha256": INNER_SHA,
        "network": "none",
        "cpu_millis": 1000,
        "memory_mib": 3072,
        "uid": 0,
        "fixture_cleanup": cleanup,
        "reason": failure,
        "report": reports[0] if len(reports) == 1 else None,
        "public_log_path": str(log),
        "public_log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
    }
    fd = os.open(
        work / "receipt.json",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "w") as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps(receipt), flush=True)
    assert accepted


if __name__ == "__main__":

    def terminate(signum, frame):
        raise SystemExit("Owned offline gate interrupted")

    signal.signal(signal.SIGTERM, terminate)
    main()

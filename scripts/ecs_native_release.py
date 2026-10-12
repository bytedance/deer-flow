#!/usr/bin/env python3
"""Repeatable native role delivery on Jenkins; never resumes task admission."""

import argparse
from contextlib import contextmanager
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tarfile
import time
from urllib.parse import urlsplit

from ecs_native_release_host import (
    NAME,
    SHA,
    IMAGE,
    NATIVE_REVISION,
    EXECUTOR_REVISION,
    canonical,
    digest,
    exclusive_json,
    private_json,
    validate_lock,
)

ROOT = Path(__file__).resolve().parents[1]
HOST_SCRIPT = Path(__file__).with_name("ecs_native_release_host.py")
DEPLOY_STAGES = (
    ("controller", "preflight"),
    ("worker", "preflight"),
    ("controller", "fence"),
    ("worker", "stop"),
    ("controller", "activate"),
    ("worker", "activate"),
    ("controller", "smoke"),
    ("worker", "smoke"),
)


def binding(lock, environment_sha256):
    return {
        "release_id": lock["release_id"],
        "image": lock["image"],
        "image_archive_sha256": lock["image_archive_sha256"],
        "environment_sha256": environment_sha256,
    }


def require_binding(receipt, lock, environment_sha256):
    if any(
        receipt.get(key) != value
        for key, value in binding(lock, environment_sha256).items()
    ):
        raise ValueError("Receipt belongs to another release or environment")


def checked(args, timeout=120, stdout=None):
    result = subprocess.run(
        args, stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError("Release command failed; private output withheld")
    return (
        result.stdout.decode("utf-8", errors="strict").strip() if stdout is None else ""
    )


def source_check(expected):
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("Full source commit required")
    if checked(["git", "-C", str(ROOT), "rev-parse", "HEAD"]) != expected:
        raise ValueError("SCM checkout differs from selected source commit")
    if checked(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=all"]
    ):
        raise ValueError("A clean committed source snapshot is required")


def output_directory(path):
    path = canonical(path)
    if path == ROOT or ROOT in path.parents:
        raise ValueError("Release output must be outside the checkout/build context")
    info = path.stat()
    if not path.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Owned mode-0700 release directory required")
    return path


@contextmanager
def owned_builder(name):
    if not NAME.fullmatch(name) or not name.startswith("deer-native-"):
        raise ValueError("Explicit owned native builder required")
    data = json.loads(checked(["docker", "inspect", "buildx_buildkit_" + name + "0"]))[
        0
    ]
    limits = data["HostConfig"]
    if (
        not 0 < limits["Memory"] <= 3 * 1024**3
        or not 0 < limits["MemorySwap"] <= 3 * 1024**3
        or limits["CpuPeriod"] <= 0
        or not 0 < limits["CpuQuota"] <= limits["CpuPeriod"]
    ):
        raise ValueError("Builder requires at most 1 CPU/3GiB and no unlimited swap")
    if data["State"]["Running"]:
        raise ValueError("Dedicated builder must be idle/stopped before this job")
    try:
        checked(["docker", "buildx", "inspect", name, "--bootstrap"], timeout=180)
        after = json.loads(
            checked(["docker", "inspect", "buildx_buildkit_" + name + "0"])
        )[0]
        if (
            after["Id"] != data["Id"]
            or after["HostConfig"] != limits
            or not after["State"]["Running"]
        ):
            raise ValueError("Builder identity or resource accounting changed")
        yield
    finally:
        # Stop only the exact preselected container, retaining its build cache.
        current = json.loads(checked(["docker", "inspect", data["Id"]]))[0]
        if current["State"]["Running"]:
            checked(["docker", "stop", "--time", "60", data["Id"]], timeout=120)
        current = json.loads(checked(["docker", "inspect", data["Id"]]))[0]
        if current["State"]["Running"]:
            raise RuntimeError("Owned builder STOP not confirmed")


def build(args):
    source_check(args.expected_commit)
    if not NAME.fullmatch(args.release_id):
        raise ValueError("Fixed release ID required")
    parent = output_directory(args.output_root)
    directory = parent / args.release_id
    directory.mkdir(mode=0o700)
    archive = directory / "source.tar"
    with archive.open("xb") as stream:
        archive.chmod(0o600)
        checked(
            ["git", "-C", str(ROOT), "archive", "--format=tar", args.expected_commit],
            stdout=stream,
        )
    context = directory / "context"
    context.mkdir(mode=0o700)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        for member in members:
            path = Path(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError(
                    "Source archive requires canonical regular files/directories"
                )
        tar.extractall(context, members=members, filter="data")
    tag = "deerflow-native:" + args.release_id
    prior = subprocess.run(["docker", "image", "inspect", tag], capture_output=True)
    if prior.returncode == 0:
        raise ValueError("Release tag already exists; select a new release ID")
    log = directory / "build.log"
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream, owned_builder(args.builder):
        result = subprocess.run(
            [
                "docker",
                "buildx",
                "build",
                "--builder",
                args.builder,
                "--platform",
                "linux/amd64",
                "--load",
                "--target",
                "native-role",
                "--build-arg",
                "UV_EXTRAS=postgres,browser",
                "--label",
                "org.opencontainers.image.revision=" + args.expected_commit,
                "-f",
                str(context / "backend/Dockerfile"),
                "-t",
                tag,
                str(context),
            ],
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=7200,
        )
    if result.returncode:
        raise RuntimeError("Native role build failed; retained private build log")
    image = json.loads(checked(["docker", "image", "inspect", tag]))[0]
    labels = image["Config"].get("Labels") or {}
    if (
        not IMAGE.fullmatch(image["Id"])
        or image["Architecture"] != "amd64"
        or image["Os"] != "linux"
        or labels.get("org.opencontainers.image.revision") != args.expected_commit
        or labels.get("org.deerflow.native.native_revision") != NATIVE_REVISION
        or labels.get("org.deerflow.native.executor_revision") != EXECUTOR_REVISION
    ):
        raise ValueError("Built role image generation differs from source/schema")
    image_archive = directory / "role-image.tar"
    fd = os.open(
        image_archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(fd, "wb") as stream:
        checked(["docker", "image", "save", image["Id"]], timeout=900, stdout=stream)
    lock = {
        "format_version": 1,
        "release_id": args.release_id,
        "source_commit": args.expected_commit,
        "source_archive_sha256": digest(archive),
        "image": image["Id"],
        "image_archive_sha256": digest(image_archive),
        "image_archive_bytes": image_archive.stat().st_size,
        "native_revision": NATIVE_REVISION,
        "executor_revision": EXECUTOR_REVISION,
    }
    validate_lock(lock)
    exclusive_json(directory / "release.json", lock)
    return {"phase": "build", "release_id": args.release_id, "image": image["Id"]}


def environment(path):
    value = private_json(path)
    if (
        set(value) != {"format_version", "controller", "worker"}
        or value["format_version"] != 1
    ):
        raise ValueError("Unknown private environment format")
    fields = {
        "host",
        "role",
        "ops_config",
        "incoming_dir",
        "expected_image",
        "frontend_image",
        "config_sha256",
        "compose_sha256",
        "generation",
        "health_url",
        "ca_file",
    }
    for role in ("controller", "worker"):
        target = value[role]
        if set(target) != fields or target["role"] != role:
            raise ValueError("Exact private role selectors required")
        # Fixed private IPs avoid shell/SSH option interpretation and DNS drift.
        if not ipaddress.ip_address(target["host"]).is_private:
            raise ValueError("Private VPC target address required")
        for key in ("ops_config", "incoming_dir", "ca_file"):
            path_value = Path(target[key])
            if (
                not path_value.is_absolute()
                or ".." in path_value.parts
                or not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(path_value))
            ):
                raise ValueError("Canonical operator target paths required")
        if not all(
            IMAGE.fullmatch(target[key]) for key in ("expected_image", "frontend_image")
        ):
            raise ValueError("Immutable installed role/frontend identities required")
        if not all(
            SHA.fullmatch(target[key]) for key in ("config_sha256", "compose_sha256")
        ):
            raise ValueError("Private config and public Compose hashes required")
        if not NAME.fullmatch(target["generation"]) or not target[
            "health_url"
        ].startswith("https://"):
            raise ValueError("Reviewed backup generation and TLS endpoint required")
    if value["controller"]["host"] == value["worker"]["host"]:
        raise ValueError("Controller and worker must be distinct hosts")
    for role in ("controller", "worker"):
        url = urlsplit(value[role]["health_url"])
        if (
            url.scheme != "https"
            or url.hostname != value["controller"]["host"]
            or url.path != "/health/ready"
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or not 0 < (url.port or 443) <= 65535
        ):
            raise ValueError(
                "Readiness must select the exact private controller TLS endpoint"
            )
    return value, digest(path)


def ssh_options():
    user = os.environ["DEPLOY_USER"]
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
        raise ValueError("Fixed SSH account required")
    known = canonical(os.environ["ECS_RELEASE_KNOWN_HOSTS"])
    key = canonical(os.environ["DEPLOY_KEY"])
    return user, [
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile=" + str(known),
        "-i",
        str(key),
    ]


def remote(target, lock, step, baseline=None):
    user, options = ssh_options()
    payload = {"target": target, "lock": lock, "step": step, "baseline": baseline}
    command = shlex.join(["python3", "-c", HOST_SCRIPT.read_text(encoding="utf-8")])
    result = subprocess.run(
        ["ssh", *options, user + "@" + target["host"], command],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=1500,
    )
    if result.returncode:
        raise RuntimeError("Remote release phase refused; private output withheld")
    receipt = json.loads(result.stdout)
    for key, expected in {
        "role": target["role"],
        "step": step,
        "image": lock["image"],
        "release_id": lock["release_id"],
    }.items():
        if receipt.get(key) != expected:
            raise ValueError("Remote receipt does not match requested phase")
    return receipt


def loaded(args):
    directory = output_directory(Path(args.output_root) / args.release_id)
    lock = private_json(directory / "release.json")
    validate_lock(lock)
    if (
        lock["release_id"] != args.release_id
        or lock["source_commit"] != args.expected_commit
    ):
        raise ValueError("Release directory/checkout differs from lock")
    source_check(args.expected_commit)
    archive = directory / "role-image.tar"
    if (
        canonical(archive).stat().st_size != lock["image_archive_bytes"]
        or digest(archive) != lock["image_archive_sha256"]
    ):
        raise ValueError("Local archive differs from release lock")
    if digest(directory / "source.tar") != lock["source_archive_sha256"]:
        raise ValueError("Frozen source differs from release lock")
    targets, environment_sha = environment(args.environment)
    return directory, lock, targets, environment_sha


def transfer(args):
    directory, lock, targets, environment_sha = loaded(args)
    receipt_path = directory / "transfer.json"
    if receipt_path.exists():
        receipt = private_json(receipt_path)
        require_binding(receipt, lock, environment_sha)
        return {
            "phase": "transfer",
            "release_id": args.release_id,
            "previous_receipt_verified": True,
        }
    results = []
    for role in ("controller", "worker"):
        target = targets[role]
        receipt = remote(target, lock, "prepare")
        if receipt["needs_copy"]:
            user, options = ssh_options()
            destination = str(
                Path(target["incoming_dir"]) / args.release_id / "role-image.tar"
            )
            checked(
                [
                    "scp",
                    *options,
                    str(directory / "role-image.tar"),
                    user + "@" + target["host"] + ":" + destination,
                ],
                timeout=1200,
            )
        results.append(remote(target, lock, "load"))
    exclusive_json(receipt_path, {**binding(lock, environment_sha), "results": results})
    return {"phase": "transfer", "release_id": args.release_id, "image": lock["image"]}


def deploy(args):
    directory, lock, targets, environment_sha = loaded(args)
    require_binding(private_json(directory / "transfer.json"), lock, environment_sha)
    if list(directory.glob("deploy-*.json")) or (directory / "deploy.json").exists():
        raise ValueError(
            "Deployment has prior stage evidence; review recovery instead of replaying rollout"
        )
    completed = []
    baseline = None
    try:
        for index, (role, step) in enumerate(DEPLOY_STAGES):
            receipt = remote(targets[role], lock, step, baseline)
            if role == "controller" and step == "preflight":
                baseline = receipt["baseline"]
            exclusive_json(
                directory / f"deploy-{index:02d}-{role}-{step}.json",
                {**binding(lock, environment_sha), "result": receipt},
            )
            completed.append({"role": role, "step": step})
    except Exception:
        exclusive_json(
            directory / "deploy-failure.json",
            {
                **binding(lock, environment_sha),
                "completed": completed,
                "admission_resume_attempted": False,
            },
        )
        raise
    exclusive_json(
        directory / "deploy.json",
        {
            **binding(lock, environment_sha),
            "baseline": baseline,
            "completed": completed,
            "operator_drain": True,
            "models_called": False,
        },
    )
    return {
        "phase": "deploy",
        "release_id": args.release_id,
        "operator_drain": True,
        "models_called": False,
    }


def smoke(args):
    directory, lock, targets, environment_sha = loaded(args)
    installed = private_json(directory / "deploy.json")
    require_binding(installed, lock, environment_sha)
    results = [
        remote(targets[role], lock, "smoke", installed["baseline"])
        for role in ("controller", "worker")
    ]
    exclusive_json(
        directory / ("smoke-" + str(time.time_ns()) + ".json"),
        {**binding(lock, environment_sha), "results": results},
    )
    return {
        "phase": "smoke",
        "release_id": args.release_id,
        "operator_drain": True,
        "models_called": False,
    }


def main():
    def interrupted(signum, frame):
        raise RuntimeError("Release interrupted; confirm the last completed receipt")

    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("build", "transfer", "deploy", "smoke"))
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--builder")
    parser.add_argument("--environment")
    args = parser.parse_args()
    try:
        result = {
            "build": build,
            "transfer": transfer,
            "deploy": deploy,
            "smoke": smoke,
        }[args.phase](args)
        print(json.dumps(result))
    except Exception:
        raise SystemExit(
            "Native release phase refused; retain private artifacts and review stage receipts"
        ) from None


if __name__ == "__main__":
    main()

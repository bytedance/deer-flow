#!/usr/bin/env python3
"""Fixed Shanghai Task6B host bootstrap; run only via the test Jenkins credential binding.

Private reference files/envs are prepared separately. No config or credential values
are printed. Controller Docker access stays on the host, never in its Gateway.
"""

import argparse
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import sys
import urllib.request

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
SOURCE = ROOT / "source"
PRIVATE = ROOT / "private/820d7a3429d9/resident"
NAS = Path("/srv/deerflow-native-test")
NODE = "native-820d7a3429d9"
CORE = "sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338"
NAS_SOURCE = "031sp6l7o6sh4hzha32-jow11.cn-shanghai.nas.aliyuncs.com:/"


def run(args, payload=None):
    result = subprocess.run(args, input=payload, capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError("Owned bootstrap command failed; private output withheld")
    return result.stdout


def private_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("Private file ownership/type/mode invalid")
    return path


def compose(role, *args):
    return run(
        [
            "docker",
            "compose",
            "--project-name",
            "deer-native-820d7a3429d9-" + role,
            "--env-file",
            str(private_file(PRIVATE / (role + ".env"))),
            "-f",
            str(SOURCE / "examples/ecs-native/deploy" / (role + ".compose.yaml")),
            *args,
        ]
    )


def preflight(role):
    if os.getuid() != 0 or not NAS.is_dir() or not os.path.ismount(NAS):
        raise ValueError("Root and the existing NAS mount are required")
    mount = json.loads(
        run(["findmnt", "--json", "--target", str(NAS), "-o", "TARGET,SOURCE,FSTYPE"])
    )["filesystems"][0]
    if (
        mount["target"] != str(NAS)
        or mount["fstype"] != "nfs4"
        or not mount["source"].startswith(NAS_SOURCE)
    ):
        raise ValueError("NAS endpoint/type differs from the verified mount")
    if (NAS / "pool/pool-mount-id").read_text().strip() != "820d7a3429d9":
        raise ValueError("NAS generation marker differs")
    if (
        PRIVATE.is_symlink()
        or PRIVATE.stat().st_uid != 0
        or PRIVATE.stat().st_mode & 0o077
    ):
        raise ValueError("Resident private directory must be root-owned mode 0700")
    for name in (
        "central.json",
        "worker.json",
        "executor.json",
        "b-worker.json",
        "extensions.json",
        "native.json",
        role + ".env",
        "ca.crt",
    ):
        private_file(PRIVATE / name)
    env = dict(
        line.split("=", 1)
        for line in (PRIVATE / (role + ".env")).read_text().splitlines()
        if line and not line.startswith("#")
    )
    if (
        env.get("ECS_ROLE_IMAGE") != CORE
        or env.get("ECS_PRIVATE_DIR") != str(PRIVATE)
        or env.get("ECS_NAS_ROOT") != str(NAS)
    ):
        raise ValueError("Fixed image/private path/NAS references differ")
    if role == "controller":
        if (
            env.get("ECS_PRIVATE_BIND_HOST") != "192.168.0.190"
            or env.get("ECS_PUBLIC_BIND_HOST") != "192.168.0.190"
        ):
            raise ValueError("Only private controller listeners are permitted")
        private_file(PRIVATE / "tls.crt")
        private_file(PRIVATE / "tls.key")
    else:
        if (
            any(
                (PRIVATE / name).exists()
                for name in ("controller.env", "tls.key", "operator.env")
            )
            or "ECS_EXECUTOR_DATABASE_URL" in env
        ):
            raise ValueError(
                "Worker resident cannot receive controller/admin credentials"
            )
        if not env.get("DATABASE_URL", "").startswith("postgresql://gateway:"):
            raise ValueError("Worker requires its dedicated native-only login")
    central = json.loads((PRIVATE / "central.json").read_text())
    if central.get("remote_all") is not True or central.get("native_node") != NODE:
        raise ValueError("Central all-intent remote placement is required")
    return env


def health():
    context = ssl.create_default_context(cafile=str(PRIVATE / "ca.crt"))
    with urllib.request.urlopen(
        "https://192.168.0.190:2026/health/ready", context=context, timeout=10
    ) as response:
        if response.status != 200:
            raise RuntimeError("TLS readiness failed")


def native_login(password):
    if not re.fullmatch("[0-9a-f]{64}", password):
        raise ValueError("Dedicated login password must be newly generated hex")
    container = compose("controller", "ps", "-q", "postgres").decode().strip()
    if not re.fullmatch("[0-9a-f]{64}", container):
        raise ValueError("Exactly one owned Postgres container is required")
    project = (
        run(
            [
                "docker",
                "inspect",
                "--format",
                '{{index .Config.Labels "com.docker.compose.project"}}',
                container,
            ]
        )
        .decode()
        .strip()
    )
    if project != "deer-native-820d7a3429d9-controller":
        raise ValueError("Postgres ownership differs")
    # One transaction; existing gateway role is deliberately rejected. No old DB is touched.
    sql = f"""SET log_statement='none';
SET log_min_error_statement='panic';
SET log_min_duration_statement=-1;
BEGIN;
CREATE ROLE gateway LOGIN PASSWORD '{password}';
REVOKE CONNECT ON DATABASE deerflow_execution FROM PUBLIC;
GRANT CONNECT ON DATABASE deerflow TO gateway;
GRANT USAGE, CREATE ON SCHEMA public TO gateway;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO gateway;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO gateway;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO gateway;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO gateway;
COMMIT;
"""
    run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "deerflow",
        ],
        sql.encode(),
    )


def worker_proof():
    container = compose("worker", "ps", "-q", "resident").decode().strip()
    raw = (
        run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.Id}} {{.Image}} {{.HostConfig.NanoCpus}} {{.HostConfig.Memory}} {{.State.Health.Status}}",
                container,
            ]
        )
        .decode()
        .split()
    )
    if len(raw) != 5 or raw[1:] != [CORE, "500000000", "1073741824", "healthy"]:
        raise ValueError("Installed worker image/cgroups/readiness differ")
    kernel = (
        run(
            [
                "docker",
                "exec",
                container,
                "sh",
                "-c",
                "cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max",
            ]
        )
        .decode()
        .splitlines()
    )
    if kernel != ["50000 100000", "1073741824"]:
        raise ValueError("Worker kernel cgroups differ")
    return {
        "resident_id": raw[0],
        "image_id": CORE,
        "cpu_millis": 500,
        "memory_bytes": 1073741824,
        "kernel_verified": True,
        "health": "healthy",
        "browser": "pending_unavailable",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase", choices=["controller-db", "controller-up", "native-login", "worker-up"]
    )
    args = parser.parse_args()
    role = "worker" if args.phase == "worker-up" else "controller"
    preflight(role)
    if args.phase == "controller-db":
        compose(
            role,
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--wait",
            "postgres",
            "redis",
        )
        compose(
            role,
            "run",
            "--rm",
            "--no-deps",
            "mcp",
            "python",
            "-m",
            "ecs_executor.schema",
            "upgrade",
        )
    elif args.phase == "controller-up":
        compose(
            role,
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--wait",
            "--wait-timeout",
            "240",
        )
        health()
    elif args.phase == "native-login":
        native_login(json.load(sys.stdin)["gateway_password"])
    else:
        compose(
            role,
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--wait",
            "--wait-timeout",
            "240",
        )
        health()
        print(json.dumps(worker_proof(), sort_keys=True))
    print(
        json.dumps(
            {
                "phase": args.phase,
                "result": "PASS",
                "b_acceptance": "pending",
                "c_acceptance": "pending",
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Owned Shanghai bootstrap refused; private output withheld, resources retained"
        ) from None

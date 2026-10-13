"""Install the fixed worker-only envelope and separately fenced operator env from stdin."""

import hashlib
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
PRIVATE = ROOT / "private/820d7a3429d9/resident"
OPERATOR = PRIVATE.parent / "operator"
NAMES = {
    "central.json",
    "worker.json",
    "executor.json",
    "b-worker.json",
    "extensions.json",
    "native.json",
    "ca.crt",
    "ca-bundle.crt",
}
ENV_KEYS = {
    "GATEWAY_CORS_ORIGINS",
    "ECS_ROLE_IMAGE",
    "ECS_PRIVATE_DIR",
    "ECS_NAS_ROOT",
    "AUTH_JWT_SECRET",
    "DEER_FLOW_INTERNAL_AUTH_TOKEN",
    "ECS_NODE_TOKEN",
    "ECS_EXECUTOR_SCOPE_SECRET",
    "ECS_EXECUTOR_SCOPE_SERVER",
    "ECS_EXECUTOR_SCOPE_SUBMIT_TOOL",
    "ECS_EXECUTOR_SCOPE_STATUS_TOOL",
    "ECS_EXECUTOR_SCOPE_CANCEL_TOOL",
    "ECS_EXECUTOR_SCOPE_AUDIENCE",
    "ECS_OWNER_HEADER",
    "ECS_DISCOVERY_HEADER",
    "SSL_CERT_FILE",
    "ECS_MODEL_NAME",
    "ECS_MODEL_KEY",
    "ECS_MODEL_URL",
    "DATABASE_URL",
    "ECS_NATIVE_METADATA_DATABASE_URL",
    "REDIS_URL",
}


def env(text):
    rows = text.splitlines()
    assert rows and all(
        "=" in line and "\r" not in line and "\x00" not in line for line in rows
    )
    value = dict(line.split("=", 1) for line in rows)
    assert len(value) == len(rows)
    return value


def directory(path):
    for p in [path, *path.parents]:
        assert not p.is_symlink()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    s = path.stat()
    assert s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o700


def write(path, data):
    if path.exists() or path.is_symlink():
        s = path.lstat()
        assert (
            stat.S_ISREG(s.st_mode)
            and s.st_uid == 0
            and stat.S_IMODE(s.st_mode) == 0o600
        )
        assert path.read_bytes() == data, "unknown_or_partial_private_file_retained"
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def main():
    assert os.getuid() == 0
    payload = json.load(sys.stdin)
    assert set(payload) == {"envelope", "operator_env"}
    envelope = payload["envelope"]
    assert set(envelope) == {"files", "worker.env", "worker-ops.json"}
    assert set(envelope["files"]) == NAMES
    values = env(envelope["worker.env"])
    assert set(values) == ENV_KEYS
    assert values["DATABASE_URL"].startswith("postgresql://gateway:") and values[
        "DATABASE_URL"
    ].endswith("@192.168.0.190:5432/deerflow")
    assert values["ECS_NATIVE_METADATA_DATABASE_URL"].startswith(
        "postgresql+psycopg://gateway:"
    ) and values["ECS_NATIVE_METADATA_DATABASE_URL"].endswith(
        "@192.168.0.190:5432/deerflow"
    )
    assert (
        values["ECS_PRIVATE_DIR"] == str(PRIVATE)
        and values["ECS_NAS_ROOT"] == "/srv/deerflow-native-test"
    )
    assert (
        values["ECS_ROLE_IMAGE"]
        == "sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338"
    )
    assert values["SSL_CERT_FILE"] == "/run/operator/ca-bundle.crt"
    ops = envelope["worker-ops.json"]
    assert (
        ops["compose_file"]
        == str(ROOT / "source/examples/ecs-native/deploy/worker.compose.yaml")
        and ops["private_dir"] == str(PRIVATE)
        and ops["node_id"] == "native-820d7a3429d9"
    )
    admin = env(payload["operator_env"])
    assert set(admin) == {
        "ECS_EXECUTOR_DATABASE_URL",
        "ECS_NATIVE_METADATA_DATABASE_URL",
    }
    assert admin["ECS_EXECUTOR_DATABASE_URL"].startswith(
        "postgresql+psycopg://postgres:"
    ) and admin["ECS_EXECUTOR_DATABASE_URL"].endswith(
        "@192.168.0.190:5432/deerflow_execution"
    )
    assert admin["ECS_NATIVE_METADATA_DATABASE_URL"].startswith(
        "postgresql+psycopg://postgres:"
    ) and admin["ECS_NATIVE_METADATA_DATABASE_URL"].endswith(
        "@192.168.0.190:5432/deerflow"
    )
    directory(PRIVATE)
    directory(OPERATOR)
    assert not any(
        (PRIVATE / n).exists() or (PRIVATE / n).is_symlink()
        for n in [
            "controller.env",
            "operator.env",
            "secrets.json",
            "tls.key",
            "owner.cookies",
        ]
    )
    for name, text in envelope["files"].items():
        write(PRIVATE / name, text.encode())
    write(PRIVATE / "worker.env", envelope["worker.env"].encode())
    write(PRIVATE / "worker-ops.json", (json.dumps(ops, indent=2) + "\n").encode())
    # This sibling is never part of the resident mount; only explicit trusted oneoff ops may use it.
    write(OPERATOR / "operator.env", payload["operator_env"].encode())
    print(
        json.dumps(
            {
                "worker_private_installed": True,
                "resident_ledger_secret": False,
                "operator_sibling_only": True,
                "fixed_file_count": 10,
                "roles_started": False,
                "models_called": False,
                "envelope_sha256": hashlib.sha256(
                    json.dumps(envelope, sort_keys=True).encode()
                ).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Fixed worker private installation refused; files retained, private details withheld"
        ) from None

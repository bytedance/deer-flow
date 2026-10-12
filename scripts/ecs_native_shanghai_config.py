"""Prepare only fixed owned Shanghai private files; no Docker startup/model calls."""

import json
import os
from pathlib import Path
import secrets
import ssl
import stat
import subprocess
import uuid

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
SOURCE = ROOT / "frontend-build/source"
PRIVATE = ROOT / "private/820d7a3429d9/resident"
OPERATOR = PRIVATE.parent / "operator"
TLS = Path("/srv/deerflow-native-task6b/95ba9f3063f9/private/820d7a3429d9")
CORE = "sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338"
ALPINE = "sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc"
AIO = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox@sha256:6328d7fd2f0ff0b4c147c3d05b3df1ce331f4a482eb6e550ecd64ed1fcf906e7"


def write(path, data):
    assert not path.is_symlink()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def encoded(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def env_bytes(value):
    assert all("\n" not in k + v and "\r" not in k + v for k, v in value.items())
    return "".join(k + "=" + v + "\n" for k, v in value.items()).encode()


def main():
    assert os.getuid() == 0 and all(
        not p.is_symlink() for p in [PRIVATE, *PRIVATE.parents]
    )
    proof = json.loads((ROOT / "frontend-build/proof/source.json").read_text())
    assert (
        proof["source_sha256"]
        == "56636cebddc6060cc4929a7f0fd86d45eb7c21c5890fb2f7f1d1128226ac4af5"
        and proof["verified_archive_entries"] == 3799
    )
    assert not PRIVATE.exists() and not OPERATOR.exists()
    PRIVATE.mkdir(parents=True, mode=0o700)
    OPERATOR.mkdir(mode=0o700)
    for p in [TLS / "tls.crt", TLS / "tls.key"]:
        info = p.lstat()
        assert (
            stat.S_ISREG(info.st_mode)
            and info.st_uid == 0
            and stat.S_IMODE(info.st_mode) == 0o600
        )
    # The owned certificate is self-issued; retain strict identity/expiry checks.
    subprocess.run(
        [
            "openssl",
            "x509",
            "-in",
            str(TLS / "tls.crt"),
            "-noout",
            "-checkend",
            "86400",
        ],
        capture_output=True,
        check=True,
    )
    for ip in ["192.168.0.190", "47.117.93.194"]:
        subprocess.run(
            ["openssl", "x509", "-in", str(TLS / "tls.crt"), "-noout", "-checkip", ip],
            capture_output=True,
            check=True,
        )
    public_ca = next(
        p
        for p in [
            Path("/etc/ssl/certs/ca-certificates.crt"),
            Path("/etc/pki/tls/certs/ca-bundle.crt"),
        ]
        if p.is_file()
    )
    cert = (TLS / "tls.crt").read_bytes()
    bundle = public_ca.read_bytes() + b"\n" + cert
    for name, data in [
        ("ca.crt", cert),
        ("ca-bundle.crt", bundle),
        ("tls.crt", cert),
        ("tls.key", (TLS / "tls.key").read_bytes()),
    ]:
        write(PRIVATE / name, data)
    ssl.create_default_context(cafile=str(PRIVATE / "ca-bundle.crt"))
    keys = {
        name: secrets.token_hex(32)
        for name in [
            "postgres",
            "gateway",
            "redis",
            "jwt",
            "internal",
            "node",
            "scope",
            "owner",
            "discovery",
            "login_password",
        ]
    }
    owner = str(uuid.uuid4())
    args = [
        "python3",
        str(SOURCE / "scripts/ecs_native.py"),
        "generate",
        "--private-dir",
        str(PRIVATE),
        "--nas-root",
        "/srv/deerflow-native-test",
        "--central-url",
        "https://192.168.0.190:2026",
        "--node-id",
        "native-820d7a3429d9",
        "--owner",
        owner,
        "--image",
        CORE,
        "--project",
        "deer-native-820d7a3429d9",
        "--sandbox-prefix",
        "deer-native-aio-820d7a3429d9",
        "--b-image",
        ALPINE,
        "--aio-image",
        AIO,
    ]
    result = subprocess.run(args, capture_output=True)
    assert result.returncode == 0
    common = {
        "GATEWAY_CORS_ORIGINS": "https://192.168.0.190:2026",
        "ECS_ROLE_IMAGE": CORE,
        "ECS_PRIVATE_DIR": str(PRIVATE),
        "ECS_NAS_ROOT": "/srv/deerflow-native-test",
        "AUTH_JWT_SECRET": keys["jwt"],
        "DEER_FLOW_INTERNAL_AUTH_TOKEN": keys["internal"],
        "ECS_NODE_TOKEN": keys["node"],
        "ECS_EXECUTOR_SCOPE_SECRET": keys["scope"],
        "ECS_EXECUTOR_SCOPE_SERVER": "ecs",
        "ECS_EXECUTOR_SCOPE_SUBMIT_TOOL": "submit",
        "ECS_EXECUTOR_SCOPE_STATUS_TOOL": "status",
        "ECS_EXECUTOR_SCOPE_CANCEL_TOOL": "cancel",
        "ECS_EXECUTOR_SCOPE_AUDIENCE": "executor",
        "ECS_OWNER_HEADER": "Bearer " + keys["owner"],
        "ECS_DISCOVERY_HEADER": "Bearer " + keys["discovery"],
        "SSL_CERT_FILE": "/run/operator/ca-bundle.crt",
        "ECS_MODEL_NAME": "infra-no-model",
        "ECS_MODEL_KEY": "not-a-real-model-key",
        "ECS_MODEL_URL": "https://model.invalid/v1",
    }
    controller = {
        **common,
        "POSTGRES_PASSWORD": keys["postgres"],
        "REDIS_PASSWORD": keys["redis"],
        "DATABASE_URL": "postgresql://postgres:"
        + keys["postgres"]
        + "@postgres:5432/deerflow",
        "ECS_NATIVE_METADATA_DATABASE_URL": "postgresql+psycopg://postgres:"
        + keys["postgres"]
        + "@postgres:5432/deerflow",
        "ECS_EXECUTOR_DATABASE_URL": "postgresql+psycopg://postgres:"
        + keys["postgres"]
        + "@postgres:5432/deerflow_execution",
        "REDIS_URL": "redis://:" + keys["redis"] + "@redis:6379/0",
        "ECS_OWNER_TOKEN": keys["owner"],
        "ECS_DISCOVERY_TOKEN": keys["discovery"],
        "ECS_FRONTEND_IMAGE": "deerflow-native-ui:56636cebddc6",
        "ECS_PRIVATE_BIND_HOST": "192.168.0.190",
        "ECS_PUBLIC_BIND_HOST": "192.168.0.190",
        "ECS_TLS_PORT": "2026",
        "ECS_CONTROL_SUBNET": "172.29.61.0/24",
        "ECS_PROXY_IP": "172.29.61.10",
    }
    worker = {
        **common,
        "DATABASE_URL": "postgresql://gateway:"
        + keys["gateway"]
        + "@192.168.0.190:5432/deerflow",
        "ECS_NATIVE_METADATA_DATABASE_URL": "postgresql+psycopg://gateway:"
        + keys["gateway"]
        + "@192.168.0.190:5432/deerflow",
        "REDIS_URL": "redis://:" + keys["redis"] + "@192.168.0.190:6379/0",
    }
    write(PRIVATE / "controller.env", env_bytes(controller))
    # Envelope contains only worker-required files; admin data stays outside resident.
    names = [
        "central.json",
        "worker.json",
        "executor.json",
        "b-worker.json",
        "extensions.json",
        "native.json",
        "ca.crt",
        "ca-bundle.crt",
    ]
    envelope = {
        "files": {name: (PRIVATE / name).read_text() for name in names},
        "worker.env": env_bytes(worker).decode(),
        "worker-ops.json": json.loads((PRIVATE / "worker-ops.json").read_text()),
    }
    envelope["worker-ops.json"]["compose_file"] = str(
        ROOT / "source/examples/ecs-native/deploy/worker.compose.yaml"
    )
    write(OPERATOR / "worker-envelope.json", encoded(envelope))
    admin = {
        "ECS_EXECUTOR_DATABASE_URL": "postgresql+psycopg://postgres:"
        + keys["postgres"]
        + "@192.168.0.190:5432/deerflow_execution",
        "ECS_NATIVE_METADATA_DATABASE_URL": "postgresql+psycopg://postgres:"
        + keys["postgres"]
        + "@192.168.0.190:5432/deerflow",
    }
    write(OPERATOR / "operator.env", env_bytes(admin))
    write(OPERATOR / "secrets.json", encoded(keys))
    write(
        OPERATOR / "owner-init.json",
        encoded(
            {
                "email": "native-820d7a3429d9@example.com",
                "remember_me": False,
                "password": keys["login_password"],
                "placeholder_owner": owner,
            }
        ),
    )
    # No real model material is read/copied. Owner maps are rebound after real API initialization.
    print(
        json.dumps(
            {
                "private_generation": "PASS",
                "worker_native_only_login": True,
                "worker_ledger_credentials": False,
                "public_ca_bundle": True,
                "models_called": False,
                "roles_started": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Owned private preparation refused; private details withheld, files retained"
        ) from None

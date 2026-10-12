"""Trusted same-schema host rollout adapter; stdin is a private operator plan.

Only the Jenkins release entry invokes this adapter. No API/model tool exposes it.
All command output and private configuration remain on the host.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import sys
import urllib.request

NATIVE_REVISION = "0035_native_fork_compatibility"
EXECUTOR_REVISION = "e0001_execution_ledger"
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{1,62}\Z")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical(path):
    value = Path(path)
    if not value.is_absolute() or ".." in value.parts:
        raise ValueError("Absolute canonical operator path required")
    if any(part.is_symlink() for part in [value, *value.parents]):
        raise ValueError("Symlinked operator path refused")
    return value


def private_json(path):
    path = canonical(path)
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Private owned regular input required")
    return json.loads(path.read_text(encoding="utf-8"))


def exclusive_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def validate_lock(lock):
    required = {
        "format_version",
        "release_id",
        "source_commit",
        "source_archive_sha256",
        "image",
        "image_archive_sha256",
        "image_archive_bytes",
        "native_revision",
        "executor_revision",
    }
    if set(lock) != required or lock["format_version"] != 1:
        raise ValueError("Unknown release lock format")
    if not NAME.fullmatch(lock["release_id"]) or not re.fullmatch(
        r"[0-9a-f]{40}", lock["source_commit"]
    ):
        raise ValueError("Invalid release/source identity")
    if not IMAGE.fullmatch(lock["image"]) or not all(
        SHA.fullmatch(lock[key])
        for key in ("source_archive_sha256", "image_archive_sha256")
    ):
        raise ValueError("Immutable image and content hashes required")
    if type(lock["image_archive_bytes"]) is not int or lock["image_archive_bytes"] <= 0:
        raise ValueError("Nonempty image archive required")
    if (
        lock["native_revision"] != NATIVE_REVISION
        or lock["executor_revision"] != EXECUTOR_REVISION
    ):
        raise ValueError("Only the accepted same-schema generation is supported")


def require_idle(status):
    if (
        status.get("operator_drain") is not True
        or status.get("unreleased") != 0
        or status.get("native_active") != 0
        or status.get("native_revision") != NATIVE_REVISION
        or status.get("executor_revision") != EXECUTOR_REVISION
    ):
        raise RuntimeError(
            "Drain, physical accounting or schema generation is not settled"
        )


def run(args, timeout=300, env=None):
    result = subprocess.run(args, env=env, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Host operation failed; private output withheld")
    return result.stdout.decode("utf-8", errors="strict").strip()


def container_id(config, service):
    ids = compose(config, "ps", "-aq", service).split()
    if len(ids) != 1:
        raise RuntimeError("Exactly one installed role container required")
    return ids[0]


def inspect(config, service):
    return json.loads(run(["docker", "inspect", container_id(config, service)]))[0]


def compose(config, *args):
    environment = {
        **os.environ,
        "ECS_ROLE_IMAGE": config["image"],
        "ECS_PRIVATE_DIR": config["private_dir"],
        "ECS_NAS_ROOT": config["nas_root"],
        "ECS_FRONTEND_IMAGE": config["frontend_image"],
    }
    return run(
        [
            "docker",
            "compose",
            "--project-name",
            config["project"],
            "--env-file",
            str(Path(config["private_dir"]) / (config["role"] + ".env")),
            "-f",
            config["compose_file"],
            *args,
        ],
        timeout=600,
        env=environment,
    )


def configuration(target, lock, step):
    config = private_json(target["ops_config"])
    role = target["role"]
    if (
        config["role"] != role
        or role not in {"controller", "worker"}
        or not NAME.fullmatch(config["project"])
    ):
        raise ValueError("Exact role/project selector required")
    expected = lock["image"] if step == "smoke" else target["expected_image"]
    if config["image"] != expected or not IMAGE.fullmatch(target["frontend_image"]):
        raise ValueError("Installed image selector differs from reviewed generation")
    private = canonical(config["private_dir"])
    info = private.stat()
    if not private.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Owned private mode-0700 directory required")
    value = hashlib.sha256()
    for name in (
        "central.json",
        "executor.json",
        "worker.json",
        "b-worker.json",
        "extensions.json",
        "native.json",
        role + ".env",
    ):
        path = canonical(private / name)
        info = path.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise ValueError("Coherent private configuration required")
        value.update(name.encode("ascii") + b"\0" + path.read_bytes() + b"\0")
    if value.hexdigest() != target["config_sha256"]:
        raise ValueError("Private configuration generation drifted")
    compose_file = canonical(config["compose_file"])
    if not compose_file.is_file() or digest(compose_file) != target["compose_sha256"]:
        raise ValueError("Reviewed Compose content required")
    nas = canonical(config["nas_root"])
    marker = canonical(nas / "pool/pool-mount-id")
    if (
        not os.path.ismount(nas)
        or not marker.is_file()
        or marker.read_text(encoding="ascii").strip() != config["mount_id"]
    ):
        raise ValueError("Production NAS mount/marker required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", config["node_id"]) or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,64}", config["sandbox_prefix"]
    ):
        raise ValueError("Fixed physical ownership required")
    if (config["project"] + "-").startswith(config["sandbox_prefix"] + "-"):
        raise ValueError("Sandbox prefix must exclude role containers")
    return {**config, "frontend_image": target["frontend_image"]}


def archive_path(target, lock):
    root = canonical(target["incoming_dir"])
    info = root.stat()
    if not root.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Pre-provisioned owned incoming directory required")
    directory = root / lock["release_id"]
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Owned release directory required")
    return directory / "role-image.tar"


def verified_archive(path, lock):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Owned private archive required")
    if (
        info.st_size != lock["image_archive_bytes"]
        or digest(path) != lock["image_archive_sha256"]
    ):
        raise ValueError("Image archive content mismatch; retain partial input")


def image_check(lock):
    image = json.loads(run(["docker", "image", "inspect", lock["image"]]))[0]
    labels = image["Config"].get("Labels") or {}
    if (
        image["Id"] != lock["image"]
        or image["Architecture"] != "amd64"
        or image["Os"] != "linux"
        or labels.get("org.opencontainers.image.revision") != lock["source_commit"]
        or labels.get("org.deerflow.native.native_revision") != NATIVE_REVISION
        or labels.get("org.deerflow.native.executor_revision") != EXECUTOR_REVISION
    ):
        raise ValueError("Installed image provenance/schema mismatch")


def physical(config):
    b = run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=deerflow.execution.node=" + config["node_id"],
        ]
    ).split()
    aio = []
    for cid in run(
        ["docker", "ps", "-aq", "--filter", "name=" + config["sandbox_prefix"] + "-"]
    ).split():
        data = json.loads(run(["docker", "inspect", cid]))[0]
        if data["Name"].lstrip("/").startswith(config["sandbox_prefix"] + "-"):
            if (data["Config"].get("Labels") or {}).get("deerflow.role") != "sandbox":
                raise RuntimeError(
                    "Unknown prefix-owned container; cleanup quarantined"
                )
            aio.append(cid)
    if b:
        raise RuntimeError(
            "Node-owned B containers remain; normal worker cleanup required"
        )
    return aio


def ledger(config):
    # Runs inside the existing MCP container; no database URL reaches argv/output.
    code = """import json,os
from pathlib import Path
from sqlalchemy import create_engine,text
c=json.loads(Path('/run/operator/central.json').read_text())
s=create_engine(os.environ[c['database_url_env']])
try:
 with s.connect() as db:
  record=db.execute(text('SELECT record FROM ecs_execution_nodes WHERE id=:node'),{'node':c['native_node']}).scalar_one()
  result={'operator_drain':record.get('operator_drain',False)}
  result['unreleased']=db.execute(text("SELECT count(*) FROM ecs_execution_jobs WHERE record->>'node_id'=:node AND COALESCE((record->>'physical_stopped')::boolean,false)=false"),{'node':c['native_node']}).scalar_one()
  result['executor_revision']=db.execute(text('SELECT version_num FROM ecs_executor_alembic_version')).scalar_one()
finally:s.dispose()
e=create_engine(os.environ['ECS_NATIVE_METADATA_DATABASE_URL'])
try:
 with e.connect() as db:
  result['native_revision']=db.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
  result['native_active']=db.execute(text("SELECT count(*) FROM runs WHERE status IN ('pending','running')")).scalar_one()
finally:e.dispose()
print(json.dumps(result))"""
    value = json.loads(
        run(["docker", "exec", container_id(config, "mcp"), "python", "-c", code])
    )
    require_idle(value)
    return value


def baseline(config):
    return {
        service: inspect(config, service)["Id"]
        for service in ("postgres", "redis", "frontend", "proxy")
    }


def health(target):
    url = target["health_url"]
    if not url.startswith("https://"):
        raise ValueError("Strict TLS health endpoint required")
    context = ssl.create_default_context(cafile=str(canonical(target["ca_file"])))
    with urllib.request.urlopen(url, context=context, timeout=15) as response:
        if response.status != 200 or response.url != url:
            raise RuntimeError("TLS readiness failed")


def selected(config, target, lock):
    path = canonical(target["ops_config"])
    before = private_json(path)
    backup = archive_path(target, lock).parent / (config["role"] + "-ops.before.json")
    exclusive_json(backup, before)
    temporary = path.with_name(path.name + "." + lock["release_id"] + ".tmp")
    after = {**before, "image": lock["image"], "generation": target["generation"]}
    exclusive_json(temporary, after)
    os.replace(temporary, path)
    return {**config, "image": lock["image"]}


def main(payload):
    lock, target, step = payload["lock"], payload["target"], payload["step"]
    validate_lock(lock)
    config = configuration(target, lock, step)
    result = {
        "role": config["role"],
        "step": step,
        "image": lock["image"],
        "release_id": lock["release_id"],
    }
    if step == "prepare":
        path = archive_path(target, lock)
        if path.exists() or path.is_symlink():
            verified_archive(path, lock)
            result["needs_copy"] = False
        else:
            fd = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            os.close(fd)
            result["needs_copy"] = True
        return result
    if step == "load":
        path = archive_path(target, lock)
        verified_archive(path, lock)
        run(["docker", "image", "load", "--input", str(path)], timeout=900)
        image_check(lock)
        return result
    image_check(lock)
    role = config["role"]
    if step == "preflight":
        for service in ["gateway", "mcp"] if role == "controller" else ["resident"]:
            data = inspect(config, service)
            if (
                data["Image"] != target["expected_image"]
                or not data["State"]["Running"]
            ):
                raise RuntimeError("Expected installed generation is not running")
            if (
                service != "mcp"
                and data["State"].get("Health", {}).get("Status") != "healthy"
            ):
                raise RuntimeError("Installed role is not healthy")
        physical(config)
        health(target)
        if role == "controller":
            if inspect(config, "frontend")["Image"] != target["frontend_image"]:
                raise RuntimeError("Accepted frontend generation drifted")
            if any(
                not inspect(config, service)["State"]["Running"]
                for service in ("postgres", "redis", "frontend", "proxy")
            ):
                raise RuntimeError(
                    "Existing persistent/ingress services are not running"
                )
            result["baseline"] = baseline(config)
            result["ledger"] = ledger(config)
        return result
    if role == "controller" and step == "fence":
        ledger(config)
        compose(config, "stop", "--timeout", "240", "proxy", "gateway")
        result["ledger"] = ledger(config)
        return result
    if role == "worker" and step == "stop":
        aio = physical(config)
        compose(config, "stop", "--timeout", "240", "resident")
        for cid in aio:
            run(["docker", "stop", "--time", "120", cid])
            run(["docker", "rm", cid])
        if physical(config) or inspect(config, "resident")["State"]["Running"]:
            raise RuntimeError("Physical STOP not confirmed")
        return result
    if step == "activate":
        if role == "controller":
            if baseline(config) != payload["baseline"]:
                raise RuntimeError(
                    "Persistent/proxy/frontend container identity drifted"
                )
            if any(
                inspect(config, service)["State"]["Running"]
                for service in ("gateway", "proxy")
            ):
                raise RuntimeError("Native admission is not fenced")
            ledger(config)
        elif physical(config) or inspect(config, "resident")["State"]["Running"]:
            raise RuntimeError("Worker is not physically stopped")
        config = selected(config, target, lock)
        services = ["gateway", "mcp"] if role == "controller" else ["resident"]
        compose(
            config,
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--no-deps",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "180",
            *services,
        )
        if role == "controller":
            proxy = container_id(config, "proxy")
            run(["docker", "start", proxy])
            run(["docker", "exec", proxy, "nginx", "-t"])
            run(["docker", "exec", proxy, "nginx", "-s", "reload"])
        health(target)
        return result
    if step == "smoke":
        for service in ["gateway", "mcp"] if role == "controller" else ["resident"]:
            data = inspect(config, service)
            if data["Image"] != lock["image"] or not data["State"]["Running"]:
                raise RuntimeError("Selected generation is not running")
            if (
                service != "mcp"
                and data["State"].get("Health", {}).get("Status") != "healthy"
            ):
                raise RuntimeError("Role readiness is not healthy")
            if role == "worker" and (
                data["HostConfig"]["NanoCpus"] != 500000000
                or data["HostConfig"]["Memory"] != 1073741824
            ):
                raise RuntimeError("Resident resource limits drifted")
        physical(config)
        health(target)
        if role == "controller":
            if (
                baseline(config) != payload["baseline"]
                or inspect(config, "frontend")["Image"] != target["frontend_image"]
            ):
                raise RuntimeError("Persistent/proxy/frontend generation drifted")
            result["ledger"] = ledger(config)
        return result
    raise ValueError("Unknown role/phase combination")


if __name__ == "__main__":
    try:
        print(json.dumps(main(json.load(sys.stdin))))
    except Exception:
        raise SystemExit(
            "Release host phase refused; retain drain, partial artifacts and private configuration"
        ) from None

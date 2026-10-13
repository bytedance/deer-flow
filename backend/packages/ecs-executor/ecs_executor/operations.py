"""Private operator lifecycle commands; never exposed as a worker/model API."""

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path

from sqlalchemy import create_engine

from ecs_executor.job_store import JobStore
from ecs_executor.nodes import Node
from ecs_executor.scheduling import Scheduling


def private_json(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise ValueError("Operator files require owned regular mode 0600/0400 files")
    return json.loads(path.read_text(encoding="utf-8"))


def immutable_image(image):
    return isinstance(image, str) and bool(re.fullmatch(r"(?:sha256:|[^\s]+@sha256:)[0-9a-f]{64}", image))


def select_image(path):
    manifest = private_json(path)
    if not immutable_image(manifest.get("image")):
        raise ValueError("An immutable image ID/digest is required")
    if manifest.get("executor_revision") != "e0001_execution_ledger" or manifest.get("native_revision") != "0035_native_fork_compatibility":
        raise ValueError("Selected binary requires its matching schema generation")
    if not manifest.get("generation") or not re.fullmatch(r"[0-9a-f]{64}", manifest.get("config_sha256", "")):
        raise ValueError("Selected binary requires a coherent backup/config generation")
    return manifest


def preflight(config):
    root = Path(config["nas_root"])
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("The shared mount must already exist at an absolute path")
    if config.get("scope") != "owned-local-fixture" and not os.path.ismount(root):
        raise ValueError("Production NAS root is not a mounted filesystem")
    marker = root / "pool/pool-mount-id"
    if not marker.is_file() or marker.is_symlink() or marker.read_text(encoding="ascii").strip() != config["mount_id"]:
        raise ValueError("Shared mount marker is missing or mismatched")
    private = Path(config["private_dir"])
    if not private.is_absolute() or not private.is_dir() or private.is_symlink() or private.stat().st_mode & 0o077:
        raise ValueError("Private operator directory must be absolute mode 0700")
    if not immutable_image(config.get("image")):
        raise ValueError("An immutable image ID/digest is required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", config["node_id"]) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", config["sandbox_prefix"]):
        raise ValueError("Fixed node and sandbox prefix are required")


def configuration_preflight(config):
    """Validate private peer definitions before any process can create a fallback."""
    directory = Path(config["private_dir"])
    central, executor, worker, b_worker, extensions, native = [private_json(directory / name) for name in ("central.json", "executor.json", "worker.json", "b-worker.json", "extensions.json", "native.json")]
    node_id = config["node_id"]
    expected = {"cpu_millis": 2000, "memory_mib": 4096, "resident_cpu_millis": 1500, "resident_memory_mib": 2048, "max_concurrency": 1, "profiles": ["native", "small"], "kinds": ["B", "C"]}
    if central.get("nodes") != {node_id: expected} or executor.get("nodes") != central["nodes"] or central.get("remote_all") is not True:
        raise ValueError("Shared fixed 2CPU/4GiB serial capacity and all-intent remote placement are required")
    if central.get("profiles", {}).get("native") != {"cpu_millis": 500, "memory_mib": 1024}:
        raise ValueError("Native virtual profile exceeds the remaining budget")
    profile = executor["profiles"]["small"]
    if profile["cpu_millis"] > 500 or profile["memory_mib"] > 1024 or profile.get("network") != "none" or profile.get("user") in {None, "0", "root", "0:0"}:
        raise ValueError("B profile must fit remaining capacity and retain non-root/network-none isolation")
    for role in (central, executor, worker, b_worker):
        if role.get("artifact_root") != str(Path(config["nas_root"]) / "pool"):
            raise ValueError("Canonical shared pool paths must agree")
    if worker.get("node_id") != node_id or b_worker.get("node_id") != node_id or not worker.get("executor_url", "").startswith("https://"):
        raise ValueError("Fixed outbound worker identity and TLS are required")
    server = extensions["mcpServers"]["ecs"]
    if server.get("user_auth", {}).get("enabled") is not True or server["user_auth"].get("on_missing") != "deny" or not server["user_auth"].get("users") or not server.get("task_toolsets"):
        raise ValueError("Native owner-bound ordinary MCP task authentication is required")
    if native.get("sandbox", {}).get("replicas") != 1 or native["sandbox"].get("hard_capacity") is not True or native["sandbox"].get("container_prefix") != config["sandbox_prefix"]:
        raise ValueError("Native AIO physical serial capacity and prefix must match")


def config_fingerprint(config):
    import hashlib

    digest = hashlib.sha256()
    directory = Path(config["private_dir"])
    for name in ("central.json", "executor.json", "worker.json", "b-worker.json", "extensions.json", "native.json", config["role"] + ".env"):
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Missing coherent private config snapshot")
        digest.update(name.encode("ascii") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def require_native_revision(config):
    from sqlalchemy import text

    engine = create_engine(os.environ[config["native_database_url_env"]])
    try:
        with engine.connect() as connection:
            versions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        if versions != ["0035_native_fork_compatibility"]:
            raise ValueError("Native schema generation is incompatible with the selected binary")
    finally:
        engine.dispose()


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError("Local Docker operation failed; private output withheld")
    return result.stdout.strip()


def physical_ids(config):
    # B labels are authoritative; also count stopped B containers until removed.
    b = docker("ps", "-aq", "--filter", "label=deerflow.execution.node=" + config["node_id"]).split()
    aio = docker("ps", "-aq", "--filter", "name=" + config["sandbox_prefix"] + "-").split()
    result = []
    for container in aio:
        name = docker("inspect", "--format", "{{.Name}}", container).lstrip("/")
        if name.startswith(config["sandbox_prefix"] + "-"):
            role = docker("inspect", "--format", '{{index .Config.Labels "deerflow.role"}}', container)
            if role != "sandbox":
                raise RuntimeError("Unknown prefix-owned physical container; cleanup is quarantined")
            result.append(container)
    return b, result


def pool(config):
    central = private_json(Path(config["private_dir"]) / "central.json")
    store = JobStore(os.environ[central["database_url_env"]])
    return Scheduling(store, nodes={key: Node.model_validate(value) for key, value in central["nodes"].items()})


def compose(config, *args):
    role = config["role"]
    if role not in {"controller", "worker"}:
        raise ValueError("Unknown deployment role")
    compose_file = Path(config["compose_file"])
    if not compose_file.is_absolute() or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,62}", config["project"]):
        raise ValueError("Fixed absolute Compose file and project are required")
    env_file = Path(config["private_dir"]) / (role + ".env")
    info = env_file.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Compose environment must be a private regular file")
    # No shell evaluation, sourcing, or configuration/environment output.
    environment = {**os.environ, "ECS_ROLE_IMAGE": config["image"], "ECS_PRIVATE_DIR": config["private_dir"], "ECS_NAS_ROOT": config["nas_root"]}
    process = subprocess.run(["docker", "compose", "--project-name", config["project"], "--env-file", str(env_file), "-f", str(compose_file), *args], env=environment, capture_output=True, text=True)
    if process.returncode:
        raise RuntimeError("Compose operation failed; private output withheld")


def idle(config, scheduler):
    status = scheduler.node_status(config["node_id"])
    if not status["operator_drain"] or status["unreleased"]:
        raise RuntimeError("Drain remains incomplete; reservations/unknown physical work are retained")
    b, aio = physical_ids(config)
    if b:
        raise RuntimeError("Node-owned B containers remain; use the normal worker cleanup path")
    return aio


def main():
    parser = argparse.ArgumentParser(description="Private fixed-node native deployment operations (no force or volume destruction)")
    parser.add_argument("operation", choices=["preflight", "start", "drain", "status", "stop", "restart", "resume", "select-version"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--manifest")
    args = parser.parse_args()
    scheduler = None
    try:
        config = private_json(args.config)
        preflight(config)
        configuration_preflight(config)
        if args.operation == "preflight":
            print("Native mount/image/private-file preflight passed")
            return
        if args.operation == "select-version":
            if not args.manifest:
                raise ValueError("A reviewed generation manifest is required")
            manifest = select_image(args.manifest)
            # Selection alone does not restore a database/NAS backup. Verify the
            # private config snapshot matches the reviewed generation first.
            digest = config_fingerprint(config)
            if digest != manifest["config_sha256"]:
                raise ValueError("Restore the coherent private config generation before image selection")
            revisions = docker("image", "inspect", "--format", '{{index .Config.Labels "org.deerflow.native.executor_revision"}} {{index .Config.Labels "org.deerflow.native.native_revision"}}', manifest["image"])
            if revisions != manifest["executor_revision"] + " " + manifest["native_revision"]:
                raise ValueError("Selected installed image does not declare matching native/executor revisions")
            config.update(image=manifest["image"], generation=manifest["generation"])
            scheduler = pool(config)
            require_native_revision(config)
            idle(config, scheduler)
            containers = docker("ps", "-q", "--filter", "label=com.docker.compose.project=" + config["project"]).split()
            if containers:
                raise RuntimeError("Stop this deployment before selecting another image")
            path = Path(args.config)
            temporary = path.with_suffix(".selection.tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(config, output, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            print("Immutable role image selected; schema/backup compatibility still requires operator review")
            return
        scheduler = pool(config)
        node = config["node_id"]
        if args.operation == "status":
            print(json.dumps(scheduler.node_status(node), sort_keys=True))
            return
        if args.operation == "drain":
            scheduler.set_operator_drain(node, True)
            print("Node admission fenced; control and outbound reports remain serving")
            return
        if args.operation == "resume":
            scheduler.set_operator_drain(node, False)
            print("Operator drain cleared")
            return
        if args.operation in {"stop", "restart"}:
            scheduler.set_operator_drain(node, True)
            aio = idle(config, scheduler)
            # Stop the worker's resident processes only after ledger finalizers.
            # Controller stays available while outbound workers finish reports.
            if config["role"] == "controller":
                native = create_engine(os.environ[config["native_database_url_env"]])
                from sqlalchemy import text

                try:
                    with native.connect() as connection:
                        active = connection.execute(text("SELECT count(*) FROM runs WHERE status IN ('pending', 'running')")).scalar_one()
                    if active:
                        raise RuntimeError("Native runs remain active/queued; settle through native APIs before controller stop")
                finally:
                    native.dispose()
            compose(config, "stop", "--timeout", "240", *(["gateway", "mcp", "frontend", "proxy"] if config["role"] == "controller" else ["resident"]))
            # Idle native warm AIO is resident capacity, not active C. Exact
            # labeled/prefix-owned containers can now be stopped and removed.
            for container in aio:
                docker("stop", "--time", "120", container)
                docker("rm", container)
            b, aio = physical_ids(config)
            if b or aio:
                raise RuntimeError("Physical STOP remains unconfirmed")
            print("Resident role and exact idle physical containers stopped; drain preserved")
        if args.operation in {"start", "restart"}:
            # Start does not silently undrain either service initialization.
            compose(config, "up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "180")
            print("Installed role ready; use explicit resume after both peers are healthy")
    except Exception:
        raise SystemExit("Native operation refused; reservations preserved and private details withheld") from None
    finally:
        if scheduler is not None:
            scheduler.store.engine.dispose()


if __name__ == "__main__":
    main()

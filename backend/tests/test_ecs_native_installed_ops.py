"""Owned installed infrastructure proof; zero Agent/model invocations.

Opt in with ECS_NATIVE_INSTALLED_IMAGE=sha256:<owned current role image>.
The fixture's frontend image is a resolver-only nginx stub, not native UI proof.
"""

import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("ECS_NATIVE_INSTALLED_IMAGE"), reason="Explicit owned installed-image acceptance required")


def _fixture_idle(root, node, operator, execution_started):
    """Fence admissions and prove the normal native/ledger finalizers are idle."""
    if not execution_started:
        return True  # No execution role has ever been launched for this UUID.
    from ecs_executor.job_store import JobStore
    from ecs_executor.nodes import Node
    from ecs_executor.operations import private_json
    from ecs_executor.scheduling import Scheduling
    from sqlalchemy import create_engine, text

    store = native = None
    try:
        config = private_json(root / "private/central.json")
        store = JobStore(operator["ECS_EXECUTOR_DATABASE_URL"])
        pool = Scheduling(store, nodes={key: Node.model_validate(value) for key, value in config["nodes"].items()})
        pool.set_operator_drain(node, True)
        if pool.node_status(node)["unreleased"]:
            return False
        native = create_engine(operator["ECS_NATIVE_METADATA_DATABASE_URL"])
        with native.connect() as connection:
            return connection.execute(text("SELECT count(*) FROM runs WHERE status IN ('pending', 'running')")).scalar_one() == 0
    except Exception:
        return False
    finally:
        if store is not None:
            store.engine.dispose()
        if native is not None:
            native.dispose()


def _cleanup_owned_fixture(*, root, project, node, prefix, compose, operator, execution_started):
    """A failed smoke must not unlink NAS beneath unresolved physical work.

    Keep an owned private receipt with exact UUID handles. No SQL state/lease
    clearing, unknown-container removal, force kill or broad resource pruning.
    """
    from ecs_executor.operations import docker, physical_ids

    receipt = {"project": project, "node": node, "prefix": prefix, "nas_root": str(root / "nas"), "status": "uncertain-retained"}
    path = root / "cleanup-receipt.json"

    def save():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2)

    def snapshot():
        receipt["projects"] = {role: docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + project + "-" + role).split() for role in ("worker", "controller")}
        receipt["b_ids"] = docker("ps", "-aq", "--filter", "label=deerflow.execution.node=" + node).split()
        receipt["prefix_ids"] = []
        for container in docker("ps", "-aq", "--filter", "name=" + prefix + "-").split():
            if docker("inspect", "--format", "{{.Name}}", container).lstrip("/").startswith(prefix + "-"):
                receipt["prefix_ids"].append(container)

    save()
    try:
        if not _fixture_idle(root, node, operator, execution_started):
            # Preserve serving owners and their private recovery config/NAS.
            try:
                snapshot()
            except Exception:
                receipt["observation"] = "Docker observation unavailable"
            save()
            return False
        snapshot()
        b, aio = physical_ids({"node_id": node, "sandbox_prefix": prefix})
        if b:
            # Normal B engine owns cleanup even when the container has exited.
            save()
            return False
        if (root / "private/worker.env").exists():
            compose("worker", "stop", "--timeout", "240", "resident")
        for container in aio:
            # Known-label exact-prefix warm AIO is removable only after the
            # native/ledger idle proof and resident process shutdown above.
            docker("stop", "--time", "120", container)
            if docker("inspect", "--format", "{{.State.Running}}", container) != "false":
                save()
                return False
            docker("rm", container)
        for role in ("worker", "controller"):
            if (root / "private" / (role + ".env")).exists():
                compose(role, "down", "--timeout", "240", "--volumes")
        snapshot()
        if any(receipt["projects"].values()) or receipt["b_ids"] or receipt["prefix_ids"]:
            save()
            return False
        receipt["status"] = "physical-absence-proved"
        save()
        # Preserve the proof receipt outside the now disposable NAS fixture.
        final_receipt = root.with_suffix(".cleanup.json")
        path.replace(final_receipt)
        shutil.rmtree(root)
        print("Owned installed fixture cleanup proved physical absence; receipt: " + str(final_receipt))
        return True
    except Exception:
        try:
            snapshot()
        except Exception:
            receipt["observation"] = "Docker observation unavailable"
        save()
        return False


def test_installed_native_roles_tls_cgroups_drain_restart_and_version_selection():
    from ecs_executor.operations import config_fingerprint, private_json
    from websockets.sync.client import connect

    repo = Path(__file__).resolve().parents[2]
    image = os.environ["ECS_NATIVE_INSTALLED_IMAGE"]
    assert image.startswith("sha256:")
    identity = uuid.uuid4().hex[:12]
    project, node = "deer-ops-" + identity, "ops-" + identity
    root = Path(tempfile.mkdtemp(prefix=project + "-", dir="/private/tmp"))
    private, nas = root / "private", root / "nas"
    private.mkdir(mode=0o700)
    nas.mkdir()
    (nas / "pool").mkdir()
    (nas / "pool/pool-mount-id").write_text(identity, encoding="ascii")
    page_server = None
    serving = None
    execution_started = False
    environment = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "DOCKER_HOST", "DOCKER_CONTEXT"}}

    def command(argv, *, env=None):
        result = subprocess.run(argv, cwd=repo, env=env or environment, capture_output=True, text=True)
        assert result.returncode == 0, "Owned installed operation failed; private output withheld"
        return result.stdout.strip()

    def port():
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    tls_port, pg_port, redis_port = [port() for _ in range(3)]
    central = f"https://localhost:{tls_port}"
    peer = f"https://host.docker.internal:{tls_port}"
    password, redis_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    common = {
        "AUTH_JWT_SECRET": secrets.token_urlsafe(48),
        "DEER_FLOW_INTERNAL_AUTH_TOKEN": secrets.token_urlsafe(48),
        "ECS_NODE_TOKEN": secrets.token_urlsafe(48),
        "ECS_EXECUTOR_SCOPE_SECRET": secrets.token_urlsafe(48),
        "ECS_EXECUTOR_SCOPE_SERVER": "ecs",
        "ECS_EXECUTOR_SCOPE_SUBMIT_TOOL": "submit",
        "ECS_EXECUTOR_SCOPE_STATUS_TOOL": "status",
        "ECS_EXECUTOR_SCOPE_CANCEL_TOOL": "cancel",
        "ECS_EXECUTOR_SCOPE_AUDIENCE": "executor",
        "ECS_DISCOVERY_TOKEN": secrets.token_urlsafe(32),
        "ECS_OWNER_TOKEN": secrets.token_urlsafe(32),
        "ECS_MODEL_NAME": "owned-zero-model-fixture",
        "ECS_MODEL_KEY": "owned-zero-model-fixture",
        "ECS_MODEL_URL": "http://127.0.0.1:9/v1",
        "SSL_CERT_FILE": "/run/operator/tls.crt",
        "GATEWAY_CORS_ORIGINS": central,
    }
    common.update(ECS_OWNER_HEADER="Bearer " + common["ECS_OWNER_TOKEN"], ECS_DISCOVERY_HEADER="Bearer " + common["ECS_DISCOVERY_TOKEN"])
    control = {
        **common,
        "POSTGRES_PASSWORD": password,
        "REDIS_PASSWORD": redis_password,
        "DATABASE_URL": f"postgresql://postgres:{password}@postgres:5432/deerflow",
        "ECS_EXECUTOR_DATABASE_URL": f"postgresql+psycopg://postgres:{password}@postgres:5432/deerflow_execution",
        "ECS_NATIVE_METADATA_DATABASE_URL": f"postgresql+psycopg://postgres:{password}@postgres:5432/deerflow",
        "REDIS_URL": f"redis://:{redis_password}@redis:6379/0",
        "ECS_FRONTEND_IMAGE": "nginx:stable-alpine",
        "ECS_TLS_PORT": str(tls_port),
        "ECS_PG_PORT": str(pg_port),
        "ECS_REDIS_PORT": str(redis_port),
    }
    worker = {
        **common,
        "DATABASE_URL": f"postgresql://postgres:{password}@host.docker.internal:{pg_port}/deerflow",
        "ECS_NATIVE_METADATA_DATABASE_URL": f"postgresql+psycopg://postgres:{password}@host.docker.internal:{pg_port}/deerflow",
        "REDIS_URL": f"redis://:{redis_password}@host.docker.internal:{redis_port}/0",
    }
    operator = {
        **environment,
        "ECS_ROLE_IMAGE": image,
        "ECS_PRIVATE_DIR": str(private),
        "ECS_NAS_ROOT": str(nas),
        "ECS_EXECUTOR_DATABASE_URL": f"postgresql+psycopg://postgres:{password}@127.0.0.1:{pg_port}/deerflow_execution",
        "ECS_NATIVE_METADATA_DATABASE_URL": f"postgresql+psycopg://postgres:{password}@127.0.0.1:{pg_port}/deerflow",
    }

    def compose(role, *args):
        return command(["docker", "compose", "--project-name", project + "-" + role, "--env-file", str(private / (role + ".env")), "-f", str(repo / "examples/ecs-native/deploy" / (role + ".compose.yaml")), *args], env=operator)

    def ops(role, operation, *extra):
        return command([sys.executable, str(repo / "scripts/ecs_native.py"), operation, "--config", str(private / (role + "-ops.json")), *extra], env=operator)

    try:
        command(
            [
                sys.executable,
                str(repo / "scripts/ecs_native.py"),
                "generate",
                "--private-dir",
                str(private),
                "--nas-root",
                str(nas),
                "--central-url",
                peer,
                "--node-id",
                node,
                "--owner",
                "bootstrap",
                "--image",
                image,
                "--project",
                project,
                "--sandbox-prefix",
                project + "-aio",
                "--browser",
                "--owned-local-fixture",
            ]
        )
        for role, values in (("controller", control), ("worker", worker)):
            target = private / (role + ".env")
            target.write_text("\n".join(key + "=" + value for key, value in values.items()) + "\n", encoding="utf-8")
            target.chmod(0o600)
        command(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(private / "tls.key"),
                "-out",
                str(private / "tls.crt"),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,DNS:host.docker.internal",
            ]
        )
        (private / "tls.key").chmod(0o600)
        native = private_json(private / "native.json")
        next(tool for tool in native["tools"] if tool["name"] == "browser_navigate")["allow_private_addresses"] = True  # owned page only
        (private / "native.json").write_text(json.dumps(native), encoding="utf-8")
        compose("controller", "up", "-d", "--pull", "never", "postgres", "redis")
        for _ in range(90):
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    project + "-controller",
                    "--env-file",
                    str(private / "controller.env"),
                    "-f",
                    str(repo / "examples/ecs-native/deploy/controller.compose.yaml"),
                    "exec",
                    "-T",
                    "postgres",
                    "pg_isready",
                    "-U",
                    "postgres",
                ],
                env=operator,
                capture_output=True,
            )
            if result.returncode == 0:
                break
            time.sleep(0.5)
        else:
            pytest.fail("Owned PostgreSQL readiness failed")
        compose("controller", "run", "--rm", "--no-deps", "mcp", "python", "-m", "ecs_executor.schema", "upgrade")
        execution_started = True
        ops("controller", "start")
        context = ssl.create_default_context(cafile=str(private / "tls.crt"))
        with httpx.Client(base_url=central, verify=context, timeout=30) as client:
            initialized = client.post("/api/v1/auth/initialize", headers={"Origin": central}, json={"email": "ops@example.com", "password": "Owned!" + secrets.token_urlsafe(24)})
            assert initialized.status_code == 201
            owner = initialized.json()["id"]
            for name in ("executor.json", "extensions.json"):
                value = private_json(private / name)
                if name == "executor.json":
                    value["user_profiles"] = {owner: ["small"]}
                    value["user_credential_env"] = {owner: "ECS_OWNER_TOKEN"}
                else:
                    value["mcpServers"]["ecs"]["user_auth"]["users"] = {owner: "$ECS_OWNER_HEADER"}
                (private / name).write_text(json.dumps(value), encoding="utf-8")
            compose("controller", "restart", "--timeout", "240", "gateway", "mcp")
            for _ in range(180):
                try:
                    if client.get("/health/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                pytest.fail("Installed central readiness failed")
            ops("worker", "start")
            resident = compose("worker", "ps", "-q", "resident")
            limits = command(["docker", "inspect", "--format", "{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}", resident])
            assert limits == "500000000 1073741824"
            kernel = compose("worker", "exec", "-T", "resident", "python", "-c", 'from pathlib import Path; print(Path("/sys/fs/cgroup/cpu.max").read_text().strip()); print(Path("/sys/fs/cgroup/memory.max").read_text().strip())')
            assert kernel.splitlines() == ["50000 100000", "1073741824"]
            compose(
                "worker",
                "exec",
                "-T",
                "resident",
                "python",
                "-c",
                "from pathlib import Path; import ecs_executor, app, deerflow, psycopg, redis; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); assert Path(p.chromium.executable_path).is_file(); p.stop()",
            )
            ops("worker", "resume")
            headers = {"Origin": central, "X-CSRF-Token": client.cookies.get("csrf_token") or ""}
            thread = "owned-ops-" + identity
            assert client.post("/api/threads", headers=headers, json={"thread_id": thread}).status_code in (200, 201)
            # Serve a UUID-owned page; the normal native browser is the sole
            # browser engine. Production private-address guards stay unchanged.
            import threading
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

            class Page(BaseHTTPRequestHandler):
                def do_GET(self):
                    body = b"<title>owned-native-installed</title><h1>Native browser</h1>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *args):
                    pass

            page_server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
            serving = threading.Thread(target=page_server.serve_forever, daemon=True)
            serving.start()
            navigation = client.post(f"/api/threads/{thread}/browser/navigate", headers=headers, json={"url": f"http://host.docker.internal:{page_server.server_port}/"})
            assert navigation.status_code == 200
            assert navigation.json()["title"] == "owned-native-installed"
            cookie = "; ".join(key + "=" + value for key, value in client.cookies.items())
            with connect(central.replace("https://", "wss://") + f"/api/threads/{thread}/browser/stream?frame_format=binary", ssl=context, additional_headers={"Cookie": cookie}, origin=central, open_timeout=15) as live:
                for _ in range(20):
                    frame = live.recv(timeout=15)
                    if isinstance(frame, bytes):
                        assert frame.startswith(b"\xff\xd8")
                        break
                else:
                    pytest.fail("Installed native WSS JPEG missing")
            assert client.delete(f"/api/threads/{thread}", headers=headers).status_code in (200, 204)
        ops("worker", "drain")
        assert json.loads(ops("worker", "status")) == {"operator_drain": True, "unreleased": 0}
        ops("worker", "stop")
        config = private_json(private / "worker-ops.json")
        manifest = private / "previous.manifest.json"
        manifest.write_text(
            json.dumps({"image": image, "native_revision": "0035_native_fork_compatibility", "executor_revision": "e0001_execution_ledger", "generation": "owned-same-schema-version-selection", "config_sha256": config_fingerprint(config)}),
            encoding="utf-8",
        )
        manifest.chmod(0o600)
        ops("worker", "select-version", "--manifest", str(manifest))
        ops("worker", "restart")
        assert json.loads(ops("worker", "status"))["operator_drain"] is True
        ops("worker", "stop")
        print(
            "Installed native infrastructure: separate DB boot/schema, native/outbound roles, TLS WSS, Chromium, "
            "Docker/kernel 500m+1GiB, drain/stop/restart and same-image immutable version selection; zero model calls. "
            "Previous-version rollback/native UI/cloud remain pending."
        )
    finally:
        if page_server is not None:
            page_server.shutdown()
            page_server.server_close()
        if serving is not None:
            serving.join(timeout=5)
        cleaned = _cleanup_owned_fixture(root=root, project=project, node=node, prefix=project + "-aio", compose=compose, operator=operator, execution_started=execution_started)
        if not cleaned:
            print("Owned fixture recovery retained: " + str(root / "cleanup-receipt.json"))
        assert cleaned, "Owned fixture cleanup uncertain: private recovery receipt and NAS retained"

"""Queued and recovered batches must honor current account state and role."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from deerflow.persistence.postgres_schema import dsn_with_search_path

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "posix", reason="Tests SIGKILL recovery in separate Gateway processes")


def _until(check, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {check}")


@pytest.fixture(params=["sqlite", "postgres"])
def database(request, tmp_path):
    schema = None
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Gateway restart)")
        pytest.importorskip("psycopg")
        pytest.importorskip("asyncpg")
        schema = "test_batch_owner_" + uuid.uuid4().hex
        config = {"backend": "postgres", "postgres_url": uri, "postgres_schema": schema}
        engine = create_engine(make_url(dsn_with_search_path(uri, schema)).set(drivername="postgresql+psycopg"))
    else:
        config = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "db")}
        engine = create_engine(f"sqlite:///{tmp_path}/db/deerflow.db")

    def read(statement, **params):
        with engine.connect() as connection:
            return connection.execute(text(statement), params).all()

    try:
        if schema:
            with engine.begin() as connection:
                connection.execute(CreateSchema(schema))
        yield config, read
    finally:
        try:
            if schema:
                with engine.begin() as connection:
                    connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        finally:
            engine.dispose()


@contextmanager
def _gateway(root, client, port, generation):
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    env.update(
        PYTHONPATH=os.pathsep.join(str(ROOT / path) for path in ("backend/packages/harness", "backend/packages/extension-api", "backend", "backend/tests")),
        DEER_FLOW_HOME=str(root / "home"),
        DEER_FLOW_PROJECT_ROOT=str(ROOT),
        DEER_FLOW_CONFIG_PATH=str(root / "config.yaml"),
        DEER_FLOW_EXTENSIONS_CONFIG_PATH=str(root / "extensions.json"),
        DEER_FLOW_ENV_FILE=str(root / "empty.env"),
        BATCH_OWNER_PROBE_DIR=str(root),
        AUTH_JWT_SECRET="local-batch-owner-test-secret-1234567890",
        DEER_FLOW_AUTH_DISABLED="0",
        NO_PROXY="127.0.0.1,localhost",
        GATEWAY_WORKERS="1",
        WEB_CONCURRENCY="1",
        PYTHONIOENCODING="utf-8",
    )
    log_path = root / f"gateway-{generation}.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.gateway.app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:

            def healthy():
                assert process.poll() is None, log_path.read_text(encoding="utf-8")[-8000:]
                try:
                    return client.get("/health").status_code == 200
                except httpx.TransportError:
                    return False

            _until(healthy)
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)


@pytest.mark.parametrize("dispatch", ["batch_queue", "restart"])
@pytest.mark.parametrize("change", ["disabled", "demoted", "promoted", "unchanged_admin", "unchanged_user"])
def test_batch_revalidates_owner_at_execution(tmp_path, database, dispatch, change):
    database_config, read = database
    config = {
        "models": [{"name": "owner-probe", "use": "support.batch_owner:OwnerModel", "model": "offline", "supports_tool_calling": True}],
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "database": database_config,
        "tools": [{"name": name, "group": "probe", "use": "support.batch_owner:" + name} for name in ("owner_normal", "owner_admin")],
        "tool_groups": [{"name": "probe"}],
        "title": {"enabled": False},
        "memory": {"enabled": False},
        "summarization": {"enabled": False},
        "tool_search": {"enabled": False},
        "hitl_approval": {"enabled": False},
        "subagent_batches": {"enabled": True, "poll_interval_seconds": 0.1, "lease_seconds": 10, "default_max_running_items": 1, "max_attempts": 3 if dispatch == "restart" else 1},
        "subagent_runtime": {"max_running": 1},
        "authorization": {"enabled": True, "provider": {"use": "deerflow.authz.rbac:RbacAuthorizationProvider", "config": {"roles": {"admin": {}, "user": {"tools": {"deny": ["owner_admin"]}}}}}},
    }
    (tmp_path / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "extensions.json").write_text("{}", encoding="utf-8")
    (tmp_path / "empty.env").touch()
    (tmp_path / "hold").touch()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=30) as admin, httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=30) as actor:

        def request(client, method, path, *, expected=200, **kwargs):
            response = client.request(method, path, **kwargs)
            assert response.status_code == expected, response.text
            return response.json()

        with _gateway(tmp_path, admin, port, 1) as first:
            for client, route, email in ((admin, "initialize", "admin@example.com"), (actor, "register", "actor@example.com")):
                account = request(client, "POST", "/api/v1/auth/" + route, expected=201, json={"email": email, "password": "local-batch-owner-password-123"})
                client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
            owner = account["id"]
            original_role = "user" if change in ("unchanged_user", "promoted") else "admin"
            if original_role == "admin":
                request(admin, "PATCH", f"/api/v1/admin/users/{owner}", json={"system_role": "admin"})
            thread = request(actor, "POST", "/api/threads", json={})["thread_id"]
            request(
                actor,
                "POST",
                f"/api/threads/{thread}/runs/wait",
                json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "Submit the owner recovery batch"}]}, "context": {"mode": "pro", "subagent_enabled": True}},
            )
            _until(lambda: (tmp_path / "reached-first").exists())
            assert not (tmp_path / "reached-second").exists()
            assert not (tmp_path / "calls.jsonl").exists()
            batch_id, stored_spec = read("SELECT id, execution_spec FROM subagent_batches WHERE user_id = :owner", owner=owner)[0]
            spec = json.loads(stored_spec) if isinstance(stored_spec, str) else stored_spec
            assert spec["user_role"] == original_role

            def items():
                return read("SELECT item_key, status, attempt, error FROM subagent_batch_items WHERE batch_id = :batch_id ORDER BY position", batch_id=batch_id)

            _until(lambda: len(rows := items()) == 2 and rows[1][2] == 0)
            if change == "disabled":
                request(admin, "PATCH", f"/api/v1/admin/users/{owner}", json={"disabled": True})
                request(actor, "GET", "/api/v1/auth/me", expected=401)
            elif change in ("demoted", "promoted"):
                role = "user" if change == "demoted" else "admin"
                request(admin, "PATCH", f"/api/v1/admin/users/{owner}", json={"system_role": role})
                assert request(actor, "GET", "/api/v1/auth/me")["system_role"] == role

            def verify(pid):
                def terminal():
                    rows = items()
                    return rows if len(rows) == 2 and all(row[1] in ("succeeded", "failed", "cancelled") for row in rows) else None

                rows = _until(terminal)
                path = tmp_path / "calls.jsonl"
                calls = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
                # Preserve observable results before the PostgreSQL schema is
                # dropped; never manufacture task state for recovery.
                (tmp_path / "evidence.json").write_text(
                    json.dumps(
                        {"backend": database_config["backend"], "change": change, "dispatch": dispatch, "old_pid": first.pid, "new_pid": pid, "old_exit": first.returncode, "items": [dict(row._mapping) for row in rows], "calls": calls},
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                assert all(call["pid"] == pid and call["user_id"] == owner for call in calls)
                if dispatch == "restart":
                    assert rows[0][2] >= 2
                else:
                    assert rows[1][2] == 1
                    assert rows[0][1] == "succeeded"  # Already admitted, outside the revocation gate.
                observed = calls if dispatch == "restart" else [call for call in calls if call["item"] == "second"]
                if change in ("disabled", "demoted", "promoted"):
                    assert rows[1][1] == "failed", (rows, calls)
                    assert not observed
                    assert not (tmp_path / "reached-second").exists()
                else:
                    assert all(row[1] == "succeeded" for row in rows), (rows, calls)
                    assert all(call["role"] == original_role for call in observed)
                    assert {call["tool"] for call in observed} == ({"admin", "normal"} if original_role == "admin" else {"normal"})

            if dispatch != "restart":
                (tmp_path / "hold").unlink()
                verify(first.pid)
                return
            first.kill()
            first.wait(timeout=10)
            assert first.returncode == -signal.SIGKILL

        (tmp_path / "hold").unlink()
        with _gateway(tmp_path, admin, port, 2) as second:
            assert second.pid != first.pid
            verify(second.pid)

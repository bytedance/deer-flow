"""Kill a real Gateway during a task call and recover through its HTTP API.

Only the model and remote OAuth/MCP service are deterministic fixtures. Auth,
admission, task submission, leases, SQLite recovery and both Gateway lifespans
run in production code, in distinct OS processes over loopback TCP.
"""

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from support.mcp_agent_auth import agent_auth_env as agent_auth_env

from deerflow.config.agents_config import load_agent_config
from deerflow.mcp.agent_auth import agent_definition_digest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "posix", reason="Verifies SIGKILL and OS-process lease recovery")


def _until(check, *, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        # This polls observable HTTP state; correctness never depends on a delay.
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {check}")


@contextmanager
def _remote_service(operation):
    state = SimpleNamespace(generation=1, reached=threading.Event(), release=threading.Event(), calls=[], tokens=[])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, payload=None):
            body = json.dumps(payload).encode() if payload is not None else b""
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The killed Gateway cannot receive the parked response.

        def do_GET(self):
            self.reply(405)

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/token":
                form = parse_qs(body.decode())
                if form.get("client_id") != ["research-client"] or form.get("client_secret") != ["test-client-secret"]:
                    return self.reply(401)
                token = f"research-client-{len(state.tokens) + 1}"
                state.tokens.append(token)
                return self.reply(200, {"access_token": token, "expires_in": 3600})
            message = json.loads(body)
            if "id" not in message:
                return self.reply(202)
            method = message["method"]
            if method == "initialize":
                result = {"protocolVersion": message["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "restart-test", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": name, "description": name, "inputSchema": {"type": "object", "properties": {} if name == "submit_job" else {"task_id": {"type": "string"}}}} for name in ("submit_job", "poll_job", "cancel_job")]}
            elif method == "tools/call":
                name = message["params"]["name"]
                headers = self.headers.get_all("Authorization") or []
                state.calls.append({"generation": state.generation, "tool": name, "authorization": headers})
                if len(headers) != 1 or headers[0] not in ["Bearer " + token for token in state.tokens]:
                    return self.reply(401)
                if state.generation == 1 and name == operation + "_job":
                    state.reached.set()
                    if not state.release.wait(timeout=45):
                        return self.reply(500, {"error": "Test barrier timed out"})
                result = {"isError": False, "content": [], "structuredContent": {"task_id": "remote-1", "status": "cancelled" if name == "cancel_job" else "running", "poll_after_seconds": 1}}
            else:
                return self.reply(400)
            self.reply(200, {"jsonrpc": "2.0", "id": message["id"], "result": result})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def _gateway(tmp_path, client, port, generation):
    # Exclude ambient provider credentials and point dotenv/config/home at
    # temporary files. The child resolves its model through normal config.
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    env.update(
        PYTHONPATH=os.pathsep.join((str(ROOT / "backend"), str(ROOT / "backend/tests"))),
        DEER_FLOW_HOME=str(tmp_path),
        DEER_FLOW_PROJECT_ROOT=str(ROOT),
        DEER_FLOW_CONFIG_PATH=str(tmp_path / "config.yaml"),
        DEER_FLOW_EXTENSIONS_CONFIG_PATH=str(tmp_path / "extensions.json"),
        DEER_FLOW_ENV_FILE=str(tmp_path / "empty.env"),
        DEER_FLOW_AUTH_DISABLED="0",
        GATEWAY_WORKERS="1",
        WEB_CONCURRENCY="1",
        AUTH_JWT_SECRET="isolated-gateway-restart-test-secret-1234567890",
        NO_PROXY="127.0.0.1,localhost",  # Also overrides macOS system proxies.
        PYTHONIOENCODING="utf-8",
    )
    log_path = tmp_path / f"gateway-{generation}.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.gateway.app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=tmp_path, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:

            def healthy():
                assert process.poll() is None, log_path.read_text(encoding="utf-8")[-8000:]
                try:
                    return client.get("/health").status_code == 200
                except httpx.TransportError:
                    return False

            _until(healthy, seconds=45)
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)


def _write_config(path, data):
    replacement = path.with_suffix(".new")
    replacement.write_text(json.dumps(data), encoding="utf-8")
    replacement.replace(path)


@pytest.mark.parametrize("operation", ["poll", "cancel"])
@pytest.mark.parametrize("revoked", [False, True])
def test_gateway_process_restart_keeps_task_identity_and_enforces_revocation(agent_auth_env, tmp_path, operation, revoked):
    env = agent_auth_env
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with _remote_service(operation) as (remote_url, remote), httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False) as client:
        data = env.config.model_dump(mode="json", exclude={"extensions"})
        data.update(
            models=[{"name": "offline", "use": "support.mcp_agent_auth:AgentAuthModel", "model": "offline", "supports_tool_calling": True}],
            agents_api={"enabled": True},
            database={"backend": "sqlite", "sqlite_dir": str(tmp_path / "db")},
            title={"enabled": False},
            memory={"enabled": False},
            summarization={"enabled": False},
            tool_search={"enabled": False},
            mcp_tasks={"enabled": True, "poll_interval_seconds": 1, "lease_seconds": 5},
        )
        binding = data["mcp_agent_auth"]["research-tickets"]
        binding["oauth"].update(token_url=remote_url + "/token", client_secret="test-client-secret")
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, data)
        server = env.config.extensions.mcp_servers["tickets"].model_dump(mode="json")
        server.update(url=remote_url + "/mcp", task_toolsets=[{"name": "job", "submit_tool": "submit_job", "status_tool": "poll_job", "cancel_tool": "cancel_job"}])
        (tmp_path / "extensions.json").write_text(json.dumps({"mcpServers": {"tickets": server}}), encoding="utf-8")
        (tmp_path / "empty.env").touch()

        def request(method, path, *, expected=200, **kwargs):
            response = client.request(method, path, **kwargs)
            assert response.status_code == expected, response.text
            return response.json()

        with _gateway(tmp_path, client, port, 1) as first:
            owner = request("POST", "/api/v1/auth/register", expected=201, json={"email": "restart@example.com", "password": "isolated-test-password-123"})["id"]
            client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
            request("POST", "/api/agents", expected=201, json={"name": env.agent.name, "soul": env.soul, "tool_groups": ["mcp"], "skills": []})
            agent = load_agent_config(env.agent.name, user_id=owner)
            original_digest = agent_definition_digest(agent, env.soul)
            binding.update(owners=[owner], definition_digests=[original_digest])
            _write_config(config_path, data)
            thread_id = request("POST", "/api/threads", json={})["thread_id"]
            request(
                "POST",
                f"/api/threads/{thread_id}/runs/wait",
                json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "Submit a job."}]}, "context": {"agent_name": env.agent.name, "mode": "flash", "subagent_enabled": False}},
            )
            tasks = request("GET", f"/api/threads/{thread_id}/mcp-tasks")
            assert len(tasks) == 1, tasks
            task_url = f"/api/threads/{thread_id}/mcp-tasks/{tasks[0]['task_id']}"
            if operation == "cancel":
                request("POST", task_url + "/cancel")
            assert remote.reached.wait(timeout=20), remote.calls
            first.kill()
            first.wait(timeout=10)
            assert first.returncode == -signal.SIGKILL

        # Inspect production writes only; never manufacture a recoverable row.
        with closing(sqlite3.connect(tmp_path / "db/deerflow.db")) as connection:
            driver_data = json.loads(connection.execute("SELECT driver_data FROM mcp_tasks WHERE id = ?", (tasks[0]["task_id"],)).fetchone()[0])
        assert driver_data["agent_auth"]["definition_digest"] == original_digest
        assert "test-client-secret" not in json.dumps(driver_data)

        new_soul = "Reviewed definition revision two."
        (tmp_path / "users" / owner / "agents" / env.agent.name / "SOUL.md").write_text(new_soul, encoding="utf-8")
        binding["definition_digests"] = [agent_definition_digest(agent, new_soul)]
        binding["enabled"] = not revoked
        _write_config(config_path, data)
        remote.generation = 2
        remote.release.set()
        with _gateway(tmp_path, client, port, 2) as second:
            assert second.pid != first.pid
            target_status = "failed" if revoked else "cancelled" if operation == "cancel" else "working"

            def recovered():
                record = request("GET", task_url)
                sent = [call for call in remote.calls if call["generation"] == 2 and call["tool"] == operation + "_job"]
                return record if record["status"] == target_status and (revoked or sent) else None

            result = _until(recovered)
            if operation == "cancel":
                assert result["cancel_attempt_count"] >= 2, result
            later_calls = [call for call in remote.calls if call["generation"] == 2]
            if revoked:
                assert "revoked" in result["error"], result
                assert later_calls == []
                assert remote.tokens == ["research-client-1"]
            else:
                assert any(call["tool"] == operation + "_job" for call in later_calls)
                assert all(call["authorization"] == ["Bearer research-client-2"] for call in later_calls)
                assert remote.tokens == ["research-client-1", "research-client-2"]
            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {"operation": operation, "revoked": revoked, "old_pid": first.pid, "new_pid": second.pid, "old_exit": first.returncode, "task_status": result["status"], "token_acquisitions": len(remote.tokens), "calls": remote.calls},
                    indent=2,
                ),
                encoding="utf-8",
            )

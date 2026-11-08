"""Real process-kill regression for the write-before-batch-result crash window."""

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import httpx
import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "posix", reason="Gateway SIGKILL crash boundary requires POSIX")


class Gateway:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.log = None
        self.boot = 0
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.http = httpx.Client(base_url=f"http://127.0.0.1:{self.port}", timeout=10, trust_env=False)
        config = {
            "models": [{"name": "offline", "use": "support.batch_recovery_gateway:RecoveryModel", "model": "synthetic", "supports_tool_calling": True}],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "database": {"backend": "sqlite", "sqlite_dir": str(root / "db")},
            "run_events": {"backend": "db"},
            "subagent_batches": {"enabled": True, "recovery_policy": "conservative", "poll_interval_seconds": 0.1, "lease_seconds": 10},
            "tools": [{"name": "append_record", "group": "fixture", "use": "support.batch_recovery_gateway:append_record"}],
            "tool_groups": [{"name": "fixture"}],
            "skills": {"path": str(root / "skills")},
            "title": {"enabled": False},
            "memory": {"enabled": False, "token_counting": "char"},
            "summarization": {"enabled": False},
        }
        (root / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        (root / "extensions.json").write_text("{}", encoding="utf-8")
        (root / "empty.env").touch()

    def start(self, *, hold):
        self.boot += 1
        self.log_path = self.root / f"gateway-{self.boot}.log"
        self.log = self.log_path.open("w", encoding="utf-8")
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("DEER_FLOW_", "LANGSMITH_", "LANGCHAIN_", "OTEL_")) and key not in {"PYTHONPATH", "PYTHONHOME", "DATABASE_URL", "GATEWAY_WORKERS", "WEB_CONCURRENCY", "ENVIRONMENT"}
        }
        env.update(
            DEER_FLOW_CONFIG_PATH=str(self.root / "config.yaml"),
            DEER_FLOW_EXTENSIONS_CONFIG_PATH=str(self.root / "extensions.json"),
            DEER_FLOW_HOME=str(self.root / "home"),
            DEER_FLOW_PROJECT_ROOT=str(BACKEND.parent),
            DEER_FLOW_ENV_FILE=str(self.root / "empty.env"),
            DEER_FLOW_AUTH_DISABLED="1",
            LANGSMITH_TRACING="false",
            LANGCHAIN_TRACING_V2="false",
            PYTHONPATH=os.pathsep.join((str(BACKEND / "tests"), str(BACKEND))),
            BATCH_RECOVERY_FIXTURE_DIR=str(self.root),
            BATCH_RECOVERY_HOLD_RESULT="1" if hold else "0",
            GATEWAY_WORKERS="1",
            WEB_CONCURRENCY="1",
        )
        self.process = subprocess.Popen([sys.executable, str(BACKEND / "tests/support/batch_recovery_gateway.py"), str(self.port)], cwd=BACKEND, env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)

        def healthy():
            try:
                return self.http.get("/health").status_code == 200
            except httpx.TransportError:
                return False

        self.wait(healthy, "Gateway startup", timeout=90)

    def wait(self, predicate, description, *, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert self.process.poll() is None, self.log_path.read_text(encoding="utf-8")[-12000:]
            value = predicate()
            if value:
                return value
            time.sleep(0.05)
        raise AssertionError(f"Timed out waiting for {description}\n{self.log_path.read_text(encoding='utf-8')[-12000:]}")

    def request(self, method, path, **kwargs):
        response = self.http.request(method, path, **kwargs)
        assert response.status_code == 200, (response.status_code, response.text)
        return response.json()

    def kill(self):
        if self.process is not None:
            if self.process.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=10)
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def write_count(self):
        with sqlite3.connect(self.root / "external.sqlite") as db:
            return db.execute("SELECT count(*) FROM writes").fetchone()[0]


@pytest.fixture
def gateway(tmp_path):
    instance = Gateway(tmp_path)
    try:
        yield instance
    finally:
        instance.kill()
        instance.http.close()


def submit(gateway):
    thread = gateway.request("POST", "/api/threads", json={})["thread_id"]
    run = gateway.request("POST", f"/api/threads/{thread}/runs", json={"input": {"messages": [{"role": "user", "content": "START_BATCH and complete the requested follow-up"}]}, "context": {"subagent_enabled": True}})
    prefix = f"/api/threads/{thread}/subagent-batches"
    batches = gateway.wait(lambda: gateway.request("GET", prefix), "native batch submission")
    gateway.wait(lambda: gateway.request("GET", f"/api/threads/{thread}/runs/{run['run_id']}")["status"] == "success", "source run completion")
    return thread, prefix + "/" + batches[0]["id"]


def test_crash_after_external_write_preserves_unknown_outcome_and_blocks_dependents(gateway):
    gateway.start(hold=True)
    thread, batch_path = submit(gateway)
    gateway.wait(lambda: (gateway.root / "before-result.json").exists(), "external write committed, before batch result persistence")
    barrier = json.loads((gateway.root / "before-result.json").read_text(encoding="utf-8"))
    before = gateway.request("GET", batch_path + "/items")
    write, dependent = before
    assert barrier == {"item_id": write["id"], "result": "External write committed"}
    assert write["status"] in {"leased", "running"} and write["attempt"] == 1
    assert dependent["status"] == "pending" and dependent["attempt"] == 0
    assert gateway.write_count() == 1
    assert gateway.request("GET", batch_path)["continuation_status"] == "pending"
    gateway.kill()

    # Recovery must honor the policy saved at admission, even if the operator
    # restores the legacy default before this Gateway boots again.
    config_path = gateway.root / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["subagent_batches"]["recovery_policy"] = "retry"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    gateway.start(hold=False)

    def recovered():
        items = gateway.request("GET", batch_path + "/items")
        if items[0]["status"] in {"succeeded", "failed", "cancelled"} or gateway.write_count() > 1:
            pytest.fail(f"Uncertain external write was replayed or terminalized: {items}; writes={gateway.write_count()}")
        return items if items[0]["status"] == "outcome_unknown" else None

    after = gateway.wait(recovered, "conservative recovery after lease expiry")
    assert after[0]["attempt"] == 1
    assert after[0]["attempt_id"] == before[0]["attempt_id"]
    assert after[0]["dispatch_started_at"] == before[0]["dispatch_started_at"]
    assert after[0]["attempt_id"] and after[0]["dispatch_started_at"]
    assert after[1]["status"] == "pending" and after[1]["attempt"] == 0
    assert gateway.write_count() == 1
    assert gateway.request("GET", batch_path)["continuation_status"] == "pending"
    assert len(gateway.request("GET", f"/api/threads/{thread}/runs")) == 1
    assert gateway.http.post(batch_path + f"/items/{after[0]['id']}/retry").status_code == 409
    assert gateway.request("GET", batch_path + "/items/0")["status"] == "outcome_unknown"
    assert [item["id"] for item in gateway.request("GET", batch_path + "/items", params={"status": "outcome_unknown"})] == [after[0]["id"]]
    export = gateway.http.get(batch_path + "/results.jsonl")
    assert export.status_code == 200
    assert json.loads(export.text.splitlines()[0])["status"] == "outcome_unknown"

    # A second fresh process must preserve the uncertainty rather than merely
    # skipping it during one recovery pass; there is still no replay authority.
    gateway.kill()
    gateway.start(hold=False)
    assert gateway.request("GET", batch_path + "/items")[0]["status"] == "outcome_unknown"
    assert gateway.request("GET", batch_path + "/items")[1]["attempt"] == 0
    assert gateway.write_count() == 1
    assert len(gateway.request("GET", f"/api/threads/{thread}/runs")) == 1


def test_committed_result_survives_gateway_restart_without_repeating_tool_or_followup(gateway):
    gateway.start(hold=False)
    thread, batch_path = submit(gateway)
    gateway.wait(lambda: gateway.request("GET", batch_path)["continuation_status"] == "dispatched", "one completed batch follow-up")
    before = gateway.request("GET", batch_path + "/items")
    assert [item["status"] for item in before] == ["succeeded", "succeeded"]
    assert [item["attempt"] for item in before] == [1, 1]
    assert gateway.write_count() == 1
    batch = gateway.request("GET", batch_path)
    followup = batch["continuation_run_id"]
    gateway.wait(lambda: gateway.request("GET", f"/api/threads/{thread}/runs/{followup}")["status"] == "success", "follow-up completion")
    assert len(gateway.request("GET", f"/api/threads/{thread}/runs")) == 2
    gateway.kill()

    gateway.start(hold=False)
    assert gateway.request("GET", batch_path + "/items") == before
    assert gateway.request("GET", batch_path) == batch
    assert gateway.write_count() == 1
    assert len(gateway.request("GET", f"/api/threads/{thread}/runs")) == 2

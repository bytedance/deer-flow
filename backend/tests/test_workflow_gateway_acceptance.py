"""Opt-in real two-Gateway acceptance with disposable Docker Postgres/Redis/nginx.

Run with DEERFLOW_WORKFLOW_ACCEPTANCE=1 and a working Docker CLI. Only model
answers and fault delays are synthetic. All HTTP/auth/host/store paths are real.
"""

import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples/deerflow-extension-workflows"
pytestmark = pytest.mark.skipif(os.name != "posix" or os.getenv("DEERFLOW_WORKFLOW_ACCEPTANCE") != "1", reason="Opt-in POSIX two-Gateway Docker acceptance")


def until(fn, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {fn}")


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Cluster:
    def __init__(self, root):
        self.root = root
        self.docker = os.getenv("DEERFLOW_TEST_DOCKER", "docker")
        self.containers = []
        self.processes = {}
        self.logs = []
        self.ports = {key: port() for key in ("a", "b", "proxy", "pg", "redis")}
        self.http = httpx.Client(timeout=35, trust_env=False)
        self.cookies = {}

    def docker_run(self, image, *args, options=()):
        name = "workflow-acceptance-" + uuid.uuid4().hex[:12]
        self.containers.append(name)
        subprocess.run([self.docker, "run", "--detach", "--name", name, *options, image, *args], check=True, capture_output=True, text=True)
        return name

    def setup(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("workflow_multi_helper", ROOT / "scripts/dev_multi_instance.py")
        helper = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = helper
        try:
            spec.loader.exec_module(helper)
        finally:
            sys.modules.pop(spec.name, None)
        build_multi_instance_config, generate_shared_secrets = helper.build_multi_instance_config, helper.generate_shared_secrets

        pg = self.docker_run("postgres:17-alpine", options=("-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-p", f"127.0.0.1:{self.ports['pg']}:5432"))
        self.docker_run("redis:7-alpine", options=("-p", f"127.0.0.1:{self.ports['redis']}:6379"))
        until(lambda: subprocess.run([self.docker, "exec", pg, "pg_isready", "-U", "postgres"], capture_output=True).returncode == 0)
        self.dsn = f"postgresql://postgres@127.0.0.1:{self.ports['pg']}/postgres"
        config, _ = build_multi_instance_config({}, database_url=self.dsn, redis_url=f"redis://127.0.0.1:{self.ports['redis']}/0", sandbox_container_prefix="workflow-acceptance")
        config.update(
            config_version=61,
            models=[{"name": "acceptance", "use": "support.workflow_gateway:AcceptanceModel", "model": "synthetic", "supports_tool_calling": True}],
            sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            tools=[{"name": "write_file", "group": "file:write", "use": "deerflow.sandbox.tools:write_file_tool"}],
            tool_groups=[{"name": "file:write"}],
            title={"enabled": False},
            memory={"enabled": False},
            summarization={"enabled": False},
            plugins=[
                {
                    "name": "workflows",
                    "use": "deerflow_extension_workflows:install",
                    "enabled": True,
                    "config": {
                        "enabled": True,
                        "agents": ["lead_agent"],
                        "storage_path": str(self.root / "workflows.sqlite"),
                        "storage_url": self.dsn,
                        "lease_seconds": 5,
                        "max_workflows": 8,
                        "max_workflows_per_owner": 4,
                        "timeout_seconds": 120,
                    },
                }
            ],
        )
        self.config = config
        (self.root / "config.yaml").write_text(yaml.safe_dump(config))
        (self.root / "extensions.json").write_text("{}")
        self.env = {
            **os.environ,
            **generate_shared_secrets(),
            "DEER_FLOW_CONFIG_PATH": str(self.root / "config.yaml"),
            "DEER_FLOW_EXTENSIONS_CONFIG_PATH": str(self.root / "extensions.json"),
            "DEER_FLOW_HOME": str(self.root / "home"),
            "DEER_FLOW_PROJECT_ROOT": str(ROOT),
            "DEER_FLOW_ENV_FILE": str(self.root / "empty.env"),
            "DEER_FLOW_AUTH_DISABLED": "0",
            "GATEWAY_WORKERS": "1",
            "WEB_CONCURRENCY": "1",
        }
        (self.root / "empty.env").touch()
        self.start("a")
        self.start("b")
        # Linux host networking keeps both Gateway listeners loopback-only.
        # OrbStack/Docker Desktop exposes host loopback via host.docker.internal.
        linux = sys.platform == "linux"
        upstream = "127.0.0.1" if linux else "host.docker.internal"
        listen = f"127.0.0.1:{self.ports['proxy']}" if linux else "80"
        conf = (
            "events {}\nhttp { upstream gateways { "
            + " ".join(f"server {upstream}:{self.ports[k]};" for k in ("a", "b"))
            + f" }} server {{ listen {listen};"
            + " location / { proxy_pass http://gateways; proxy_buffering off; add_header X-Acceptance-Upstream $upstream_addr always; } } }"
        )
        (self.root / "nginx.conf").write_text(conf)
        network = ("--network", "host") if linux else ("-p", f"127.0.0.1:{self.ports['proxy']}:80", "--add-host", "host.docker.internal:host-gateway")
        self.docker_run("nginx:alpine", options=(*network, "-v", f"{self.root / 'nginx.conf'}:/etc/nginx/nginx.conf:ro"))
        until(lambda: self.healthy("proxy"))
        self.credentials = {"email": "acceptance@example.com", "password": uuid.uuid4().hex}
        response = self.request("a", "POST", "/api/v1/auth/initialize", json=self.credentials, expected=201)
        self.cookies = dict(response.cookies)

    def start(self, name, extension=EXAMPLE):
        fault = self.root / name
        fault.mkdir(exist_ok=True)
        for item in fault.iterdir():
            item.unlink()
        env = {**self.env, "WORKFLOW_FAULT_DIR": str(fault), "PYTHONHASHSEED": "1" if name == "a" else "2", "PYTHONPATH": os.pathsep.join((str(extension), str(ROOT / "backend/tests"), str(ROOT / "backend")))}
        log = (self.root / f"{name}.log").open("a")
        self.logs.append(log)
        self.processes[name] = subprocess.Popen([sys.executable, str(ROOT / "backend/tests/support/workflow_gateway.py"), str(self.ports[name])], cwd=ROOT / "backend", env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

        def ready():
            if self.processes[name].poll() is not None:
                raise AssertionError((self.root / f"{name}.log").read_text()[-10000:])
            return self.healthy(name)

        until(ready, 120)

    def healthy(self, name):
        try:
            return self.http.get(f"http://127.0.0.1:{self.ports[name]}/health").status_code == 200
        except httpx.TransportError:
            return False

    def kill(self, name):
        p = self.processes.pop(name, None)
        if p and p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=10)

    def close(self):
        for name in list(self.processes):
            self.kill(name)
        self.http.close()
        for log in self.logs:
            log.close()
        for name in self.containers:
            subprocess.run([self.docker, "rm", "-f", "-v", name], capture_output=True)

    def request(self, target, method, path, expected=200, **kwargs):
        headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
        if self.cookies.get("csrf_token"):
            headers["X-CSRF-Token"] = self.cookies["csrf_token"]
        r = self.http.request(method, f"http://127.0.0.1:{self.ports[target]}{path}", headers=headers, **kwargs)
        self.http.cookies.clear()
        assert r.status_code == expected, (r.status_code, r.text)
        return r

    def action(self, target, name, payload, expected=200):
        return self.request(target, "POST", f"/api/plugins/community.workflows/actions/{name}", json=payload, expected=expected).json()

    def launch(self, script, target="a"):
        return self.action(target, "launch", {"request_id": uuid.uuid4().hex, "script": script, "args": {}})["run_id"]

    def get(self, run_id, target="b"):
        return self.action(target, "get", {"run_id": run_id})

    def wait(self, run_id, status, target="b"):
        def check():
            record = self.get(run_id, target)
            if record["status"] in ("failed", "needs_reconciliation") and status != record["status"]:
                raise AssertionError((record, self.sql("SELECT run_id,status,error FROM runs WHERE thread_id=ANY(%s)", ([s["thread_id"] for s in record["steps"]],))))
            return record if record["status"] == status else None

        return until(check)

    def arm(self, boundary, target="a"):
        for name in ("reached.json", "release"):
            (self.root / target / name).unlink(missing_ok=True)
        (self.root / target / "arm.json").write_text(json.dumps({"boundary": boundary}))

    def reached(self, target="a"):
        until(lambda: (self.root / target / "reached.json").exists())

    def recover(self, run_id):
        self.wait(run_id, "recoverable")
        return self.action("b", "recover", {"run_id": run_id})

    def resume(self, run_id, target="b"):
        record = self.wait(run_id, "paused", target)
        return self.action(target, "resume", {"run_id": run_id, "fingerprint": record["fingerprint"], "step_id": record["checkpoints"][-1]["step_id"], "attempt": 1})

    def decide(self, run_id, target="b"):
        record = self.wait(run_id, "waiting_approval", target)
        checkpoint = record["checkpoints"][-1]
        payload = {"run_id": run_id, "step_id": checkpoint["step_id"], "attempt": 1, "artifact_version": checkpoint["artifact_version"], "decision": "approve"}
        self.action(target, "decide", payload)
        return payload

    def sql(self, statement, params=()):
        import psycopg

        with psycopg.connect(self.dsn) as db:
            return db.execute(statement, params).fetchall()


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    c = Cluster(tmp_path_factory.mktemp("workflow-gateway"))
    print(f"Acceptance logs: {c.root}")
    try:
        c.setup()
        yield c
    finally:
        c.close()


def final_gateway_port(response):
    # nginx records all attempts, including failed IPv6 -> IPv4 retries.
    destination = response.headers["x-acceptance-upstream"].rsplit(",", 1)[-1].strip()
    return int(destination.rsplit(":", 1)[-1])


def test_authenticated_cross_gateway_control_without_affinity(cluster):
    c = cluster
    for target in ("a", "b"):
        c.request(target, "GET", "/health/ready")
    upstreams = {final_gateway_port(c.request("proxy", "GET", "/api/plugins")) for _ in range(6)}
    assert upstreams == {c.ports["a"], c.ports["b"]}
    run = c.launch("await pause({stepId:'p'}); return await agent({stepId:'child',agentRef:'lead_agent',task:'hello'});")
    routed = [c.request("proxy", "POST", "/api/plugins/community.workflows/actions/get", json={"run_id": run}) for _ in range(6)]
    assert {r.json()["run_id"] for r in routed} == {run}
    assert {final_gateway_port(r) for r in routed} == {c.ports["a"], c.ports["b"]}
    c.resume(run)
    result = c.wait(run, "completed")
    assert len(result["steps"]) == 1
    assert result["steps"][0]["configuration_version"]
    run = c.launch("await pause({stepId:'p'}); return 1;")
    c.wait(run, "paused")
    c.action("b", "cancel", {"run_id": run})
    c.wait(run, "cancelled")


@pytest.mark.parametrize("boundary", ["admission", "result_before", "result", "approval"])
def test_sigkill_at_persistence_boundaries(cluster, boundary):
    c = cluster
    c.arm(boundary)
    script = "const a=await agent({stepId:'first',agentRef:'lead_agent',task:'first'});"
    if boundary == "approval":
        script += "await humanCheckpoint({stepId:'review',sourceStepId:'first',artifactVersion:a.artifactVersion});"
    script += "return await agent({stepId:'second',agentRef:'lead_agent',task:'second'});"
    run = c.launch(script)
    if boundary == "approval":
        c.decide(run)
    c.reached()
    # Confirm the real boundary before killing, then inspect the shared host DB.
    before = c.get(run)
    thread = before["steps"][0]["thread_id"]
    assert c.sql("SELECT count(*) FROM runs WHERE thread_id=%s", (thread,))[0][0] == 1
    if boundary == "admission":
        assert before["steps"][0]["run_id"] is None
    if boundary == "result":
        assert before["steps"][0]["status"] == "completed"
    if boundary == "approval":
        assert before["checkpoints"][0]["status"] == "approved"
    c.kill("a")
    try:
        recovered = c.recover(run)
        if boundary == "admission":
            assert recovered["status"] == "needs_reconciliation"
            assert len(c.get(run)["steps"]) == 1
            assert c.sql("SELECT count(*) FROM workflow_slots WHERE workflow=%s", (run,))[0][0] == 1
        else:
            record = c.wait(run, "completed")
            assert len(record["steps"]) == 2
            if boundary == "approval":
                assert record["checkpoints"][0]["status"] == "approved"
        assert c.sql("SELECT count(*) FROM runs WHERE thread_id=%s", (thread,))[0][0] == 1
    finally:
        c.start("a")


def test_file_approval_survives_owner_death_and_source_mutation(cluster):
    from support.workflow_gateway import EVIDENCE

    c = cluster
    run = c.launch(
        "await agent({stepId:'writer',agentRef:'lead_agent',task:'CREATE_EVIDENCE'});"
        "const f=await captureArtifact({stepId:'file',sourceStepId:'writer',path:'/mnt/user-data/outputs/evidence.txt'});"
        "await humanCheckpoint({stepId:'review',sourceStepId:'file',artifactVersion:f.artifactVersion});"
        "const bytes=await readArtifact({artifactVersion:f.artifactVersion});"
        "return await agent({stepId:'reader',agentRef:'lead_agent',task:bytes});"
    )
    record = c.wait(run, "waiting_approval")
    version = record["checkpoints"][0]["artifact_version"]
    chunk = c.action("b", "get_artifact", {"run_id": run, "version": version})
    assert base64.b64decode(chunk["content_base64"]) == EVIDENCE.encode()
    files = list((c.root / "home").glob("**/outputs/evidence.txt"))
    assert len(files) == 1
    files[0].write_text("MUTATED after capture")
    c.kill("a")
    try:
        c.recover(run)
        c.decide(run)
        record = c.wait(run, "completed")
        reader = record["result"]
        # The real model echoes the downstream human input; verify exact captured bytes.
        payload = json.loads(reader["output"]["echo"])
        assert base64.b64decode(payload["content_base64"]) == EVIDENCE.encode()
        assert payload["version"] == version
        assert len(record["steps"]) == 2
    finally:
        c.start("a")


def test_sigstop_stale_owner_cannot_admit_after_takeover(cluster):
    c = cluster
    c.arm("before_admission")
    run = c.launch("return await agent({stepId:'first',agentRef:'lead_agent',task:'stale'});")
    c.reached()
    record = c.get(run)
    thread = record["steps"][0]["thread_id"]
    assert c.sql("SELECT count(*) FROM runs WHERE thread_id=%s", (thread,))[0][0] == 0
    p = c.processes["a"]
    os.kill(p.pid, signal.SIGSTOP)
    try:
        assert c.recover(run)["status"] == "needs_reconciliation"
        after = c.sql("SELECT data FROM workflows WHERE id=%s", (run,))[0][0]
        (c.root / "a/release").touch()
    finally:
        os.kill(p.pid, signal.SIGCONT)
    until(lambda: (c.root / "a/admission_error").exists())
    assert c.sql("SELECT count(*) FROM runs WHERE thread_id=%s", (thread,))[0][0] == 0
    assert c.sql("SELECT data FROM workflows WHERE id=%s", (run,))[0][0] == after
    c.kill("a")
    c.start("a")


def test_distinct_runtime_rollout_drains_old_and_rejects_incompatible_takeover(cluster):
    c = cluster
    alternate = c.root / "alternate"
    shutil.copytree(EXAMPLE, alternate, ignore=shutil.ignore_patterns("__pycache__"))
    runtime = alternate / "deerflow_extension_workflows/worker.py"
    runtime.write_text(runtime.read_text().replace("MAX_FRAME = 48 * 1024", "MAX_FRAME = 47 * 1024"))
    c.kill("b")
    c.start("b", alternate)
    new_run = c.launch("return 11;", "b")
    assert c.wait(new_run, "completed")["result"] == 11
    run = c.launch("await pause({stepId:'p'}); return 17;")
    c.wait(run, "paused")
    assert c.sql("SELECT data::jsonb->>'runtime_version' FROM workflows WHERE id=%s", (run,)) != c.sql("SELECT data::jsonb->>'runtime_version' FROM workflows WHERE id=%s", (new_run,))
    c.resume(run)  # New replica can control the old live runtime; owner A drains it.
    assert c.wait(run, "completed")["result"] == 17
    run = c.launch("await pause({stepId:'p'}); return 19;")
    c.wait(run, "paused")
    c.kill("a")
    try:
        c.wait(run, "recoverable")
        before = c.sql("SELECT epoch FROM extension_execution_leases WHERE resource_id=%s", (run,))
        c.action("b", "recover", {"run_id": run}, expected=422)
        assert c.sql("SELECT epoch FROM extension_execution_leases WHERE resource_id=%s", (run,)) == before
    finally:
        c.start("a")
        c.kill("b")
        c.start("b")
    c.recover(run)
    c.resume(run)
    assert c.wait(run, "completed")["result"] == 19


def test_concurrent_duplicate_launch_and_approval(cluster):
    from concurrent.futures import ThreadPoolExecutor

    c = cluster
    payload = {
        "request_id": uuid.uuid4().hex,
        "args": {},
        "script": (
            "const a=await agent({stepId:'a',agentRef:'lead_agent',task:'first'});"
            "await humanCheckpoint({stepId:'review',sourceStepId:'a',artifactVersion:a.artifactVersion});"
            "return await agent({stepId:'b',agentRef:'lead_agent',task:'second'});"
        ),
    }
    with ThreadPoolExecutor(2) as pool:
        ids = list(pool.map(lambda target: c.action(target, "launch", payload)["run_id"], ("a", "b")))
    assert ids[0] == ids[1]
    run = ids[0]
    record = c.wait(run, "waiting_approval")
    checkpoint = record["checkpoints"][0]
    decision = {"run_id": run, "step_id": "review", "attempt": 1, "artifact_version": checkpoint["artifact_version"], "decision": "approve"}
    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(lambda target: c.action(target, "decide", decision), ("a", "b")))
    assert all(r["status"] == "approved" for r in replies)
    record = c.wait(run, "completed")
    threads = [s["thread_id"] for s in record["steps"]]
    assert c.sql("SELECT count(*) FROM runs WHERE thread_id=ANY(%s)", (threads,))[0][0] == 2
    assert c.sql("SELECT count(*) FROM workflow_controls WHERE workflow=%s", (run,))[0][0] == 1


def test_shared_owner_limit_across_gateways(cluster):
    from concurrent.futures import ThreadPoolExecutor

    c = cluster
    runs = []

    def launch(i):
        try:
            return c.launch("await pause({stepId:'p'}); return 1;", "a" if i % 2 else "b")
        except AssertionError as exc:
            assert "422" in str(exc)
            return None

    try:
        with ThreadPoolExecutor(5) as pool:
            runs = [r for r in pool.map(launch, range(5)) if r]
        assert len(runs) == 4
    finally:
        for run in runs:
            c.wait(run, "paused")
            c.action("b", "cancel", {"run_id": run})
            c.wait(run, "cancelled")


def test_revoked_session_and_changed_configuration_block_takeover(cluster):
    c = cluster
    run = c.launch("await pause({stepId:'p'}); return 23;")
    c.wait(run, "paused")
    c.kill("a")
    try:
        c.wait(run, "recoverable")
        epoch = c.sql("SELECT epoch FROM extension_execution_leases WHERE resource_id=%s", (run,))
        c.sql("UPDATE users SET token_version=token_version+1 RETURNING id")
        c.action("b", "recover", {"run_id": run}, expected=401)
        c.cookies = {}
        login = c.request("b", "POST", "/api/v1/auth/login/local", data={"username": c.credentials["email"], "password": c.credentials["password"]})
        c.cookies = dict(login.cookies)
        original = (c.root / "config.yaml").read_text()
        config = yaml.safe_load(original)
        config["models"][0]["temperature"] = 0.7
        (c.root / "config.yaml").write_text(yaml.safe_dump(config))
        try:
            c.action("b", "recover", {"run_id": run}, expected=422)
            assert c.sql("SELECT epoch FROM extension_execution_leases WHERE resource_id=%s", (run,)) == epoch
        finally:
            (c.root / "config.yaml").write_text(original)
        c.recover(run)
        c.resume(run)
        assert c.wait(run, "completed")["result"] == 23
    finally:
        c.start("a")


def test_sigstop_stale_artifact_writer_is_fenced(cluster):
    c = cluster
    c.arm("capture")
    run = c.launch(
        "await agent({stepId:'writer',agentRef:'lead_agent',task:'CREATE_EVIDENCE'});"
        "const f=await captureArtifact({stepId:'file',sourceStepId:'writer',path:'/mnt/user-data/outputs/evidence.txt'});"
        "await humanCheckpoint({stepId:'review',sourceStepId:'file',artifactVersion:f.artifactVersion}); return 31;"
    )
    c.reached()
    p = c.processes["a"]
    os.kill(p.pid, signal.SIGSTOP)
    try:
        c.recover(run)
        c.wait(run, "waiting_approval")
        assert c.sql("SELECT epoch > 1 AND expires_at > extract(epoch from clock_timestamp()) FROM extension_execution_leases WHERE resource_id=%s", (run,))[0][0]
        after = c.sql("SELECT data FROM workflows WHERE id=%s", (run,))
        artifact = c.sql("SELECT version,content FROM workflow_artifacts WHERE workflow=%s", (run,))
        (c.root / "a/release").touch()
    finally:
        os.kill(p.pid, signal.SIGCONT)
    until(lambda: (c.root / "a/capture_error").exists())
    assert (c.root / "a/capture_error").read_text() == "LeaseLost"
    assert c.sql("SELECT data FROM workflows WHERE id=%s", (run,)) == after
    assert c.sql("SELECT version,content FROM workflow_artifacts WHERE workflow=%s", (run,)) == artifact
    c.decide(run)
    assert c.wait(run, "completed")["result"] == 31
    c.kill("a")
    c.start("a")


def test_shared_child_limit_with_real_host_admissions(cluster):
    c = cluster
    reserved = c.sql("SELECT count(*) FROM workflow_slots")[0][0]
    assert 0 <= reserved < 4
    runs = []
    for target in ("a", "b"):
        (c.root / target / "hold_model").touch()
    try:
        for target in ("a", "b"):
            runs.append(c.launch("return await parallel([()=>agent({stepId:'x',agentRef:'lead_agent',task:'HOLD_MODEL'}),()=>agent({stepId:'y',agentRef:'lead_agent',task:'HOLD_MODEL'})]);", target))
        until(lambda: all(len(c.get(run)["steps"]) == 2 for run in runs))
        threads = [s["thread_id"] for run in runs for s in c.get(run)["steps"]]
        until(lambda: c.sql("SELECT count(*) FROM runs WHERE thread_id=ANY(%s)", (threads,))[0][0] == 4 - reserved)
        assert c.sql("SELECT count(*) FROM workflow_slots")[0][0] == 4
        assert sum(s["status"] == "queued" for run in runs for s in c.get(run)["steps"]) == reserved
    finally:
        for target in ("a", "b"):
            (c.root / target / "hold_model").unlink(missing_ok=True)
    for run in runs:
        assert len(c.wait(run, "completed")["steps"]) == 2
    assert c.sql("SELECT count(*) FROM workflow_slots")[0][0] == reserved


def test_peer_cancel_reaches_real_active_child(cluster):
    c = cluster
    (c.root / "a/hold_model").touch()
    try:
        run = c.launch("return await agent({stepId:'child',agentRef:'lead_agent',task:'HOLD_MODEL'});")
        until(lambda: c.get(run)["steps"] and c.get(run)["steps"][0]["status"] == "running")
        thread = c.get(run)["steps"][0]["thread_id"]
        c.action("b", "cancel", {"run_id": run})
        until(lambda: c.sql("SELECT status FROM runs WHERE thread_id=%s", (thread,))[0][0] == "interrupted", 30)
        # The extension has a bounded child-observation window; if the host's
        # heartbeat consumes cancellation later, uncertainty must stay explicit.
        until(lambda: c.get(run)["status"] in ("cancelled", "needs_reconciliation"))
        assert c.sql("SELECT count(*) FROM runs WHERE thread_id=%s", (thread,))[0][0] == 1
    finally:
        (c.root / "a/hold_model").unlink(missing_ok=True)


def test_sigkill_during_cancel_takeover_can_finish_and_delete(cluster):
    from concurrent.futures import ThreadPoolExecutor

    c = cluster
    run = c.launch("await pause({stepId:'p'}); return 1;")
    c.wait(run, "paused")
    c.kill("a")
    try:
        c.wait(run, "recoverable")
        c.arm("cancelling", "b")
        with ThreadPoolExecutor(1) as pool:
            request = pool.submit(c.action, "b", "cancel", {"run_id": run})
            c.reached("b")
            assert c.sql("SELECT status FROM workflows WHERE id=%s", (run,))[0][0] == "cancelling"
            c.kill("b")
            with pytest.raises(httpx.TransportError):
                request.result(timeout=10)
        c.start("a")
        c.wait(run, "recoverable", "a")
        # A pending cancellation must never replay the workflow body.
        c.action("a", "recover", {"run_id": run}, expected=422)
        assert c.action("a", "cancel", {"run_id": run})["status"] == "cancelled"
        c.action("a", "delete", {"run_id": run})
        assert not c.sql("SELECT id FROM workflows WHERE id=%s", (run,))
    finally:
        if "a" not in c.processes:
            c.start("a")
        if "b" not in c.processes:
            c.start("b")

"""Opt-in native HTTP/PG/Redis/DeepSeek/AIO acceptance (test-owned infra only).

ECS_NATIVE_LIVE=1 ECS_NATIVE_MODEL_CONFIG=/read-only/config.yaml
ECS_NATIVE_MODEL_ENV=/read-only/.env .venv/bin/python -m pytest tests/test_ecs_executor_c_live.py -s
"""

import json
import os
import re
import secrets
import socket
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest
import yaml
from dotenv import dotenv_values
from sqlalchemy import create_engine, text

pytestmark = [pytest.mark.live, pytest.mark.skipif(os.environ.get("ECS_NATIVE_LIVE") != "1", reason="Explicit live native acceptance opt-in required")]
IMAGE = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0"


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_native_http_remote_model_tool_and_peer_cancel(tmp_path):
    _native_http_acceptance(tmp_path)


def _native_memory_config(tmp_path, role, *, enabled):
    if not enabled:
        return {"enabled": False}
    return {
        "enabled": True,
        "mode": "tool",
        "manager_class": "deermem",
        "backend_config": {"retrieval_index_path": str(tmp_path / (role + "-memory-index")), "token_counting": "char"},
    }


def test_native_remote_memory_shared_facts_and_owner_isolation(tmp_path):
    _native_http_acceptance(tmp_path, memory_mode=True)


def _native_http_acceptance(tmp_path, *, dependency_mode=False, scheduled_mode=False, memory_mode=False):
    backend = Path(__file__).resolve().parents[1]
    run_id = uuid.uuid4().hex[:12]
    names, processes, handles = [], [], []
    private_env = dotenv_values(os.environ["ECS_NATIVE_MODEL_ENV"])
    source_config = yaml.safe_load(Path(os.environ["ECS_NATIVE_MODEL_CONFIG"]).read_text())
    model = next(value.copy() for value in source_config["models"] if value["name"] == "deepseek-chat")
    environment = {**os.environ, **{key: value for key, value in private_env.items() if value is not None}}
    # The generated config contains only references. Credentials stay in memory
    # and child environments; never write provider secrets into test files.
    for key in ("api_key", "base_url"):
        value = model.get(key)
        if value and not value.startswith("$"):
            variable = "C_NATIVE_MODEL_" + key.upper()
            environment[variable] = value
            model[key] = "$" + variable
    password = secrets.token_urlsafe(24)
    environment.update(
        POSTGRES_PASSWORD=password,
        AUTH_JWT_SECRET=secrets.token_urlsafe(48),
        DEER_FLOW_INTERNAL_AUTH_TOKEN=secrets.token_urlsafe(48),
        C_NATIVE_NODE_SECRET=secrets.token_urlsafe(48),
        DEER_FLOW_SANDBOX_CPUS="1",
        DEER_FLOW_SANDBOX_MEMORY="1g",
        DEER_FLOW_HOME=str(tmp_path / "nas"),
        DEER_FLOW_EXTENSIONS_CONFIG_PATH=str(tmp_path / "extensions.json"),
        PYTHONPATH=str(backend) + os.pathsep + str(backend / "packages/ecs-executor"),
    )
    (tmp_path / "extensions.json").write_text(json.dumps({"mcpServers": {}, "skills": {}}))
    artifacts = tmp_path / "nas/pool"
    artifacts.mkdir(parents=True)
    pg_port, redis_port, central_port, worker_port = [_port() for _ in range(4)]
    environment["C_NATIVE_DATABASE_URL"] = f"postgresql://postgres:{password}@127.0.0.1:{pg_port}/postgres"
    environment["C_NATIVE_EXECUTOR_DATABASE_URL"] = environment["C_NATIVE_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://")
    environment["C_NATIVE_REDIS_URL"] = f"redis://127.0.0.1:{redis_port}/0"
    prefix = "deer-c-main-" + run_id
    try:
        for service, image, port, inside, extra in (("pg", "postgres:16-alpine", pg_port, 5432, ["-e", "POSTGRES_PASSWORD"]), ("redis", "redis:7-alpine", redis_port, 6379, [])):
            name = prefix + "-" + service
            names.append(name)
            subprocess.run(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:{inside}", *extra, image], env=environment, check=True, capture_output=True)
        for _ in range(90):
            probe = subprocess.run(["docker", "exec", names[0], "pg_isready", "-U", "postgres"], capture_output=True)
            if probe.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise AssertionError("Test PostgreSQL failed readiness")
        example = yaml.safe_load((backend.parent / "config.example.yaml").read_text())
        config = {
            "models": [model],
            "tool_groups": example["tool_groups"],
            "tools": [tool for tool in example["tools"] if tool["group"] in {"bash", "file:read", "file:write"}],
            "sandbox": {
                "use": "deerflow.community.aio_sandbox:AioSandboxProvider",
                "image": IMAGE,
                "replicas": 1,
                "hard_capacity": True,
                "container_prefix": prefix,
                "ownership": {"type": "redis", "redis_url": "$C_NATIVE_REDIS_URL"},
                "idle_timeout": 600,
            },
            "database": {"backend": "postgres", "postgres_url": "$C_NATIVE_DATABASE_URL"},
            "deployment": {"multi_instance": True},
            "run_events": {"backend": "db"},
            "run_ownership": {"heartbeat_enabled": True, "lease_seconds": 120},
            "stream_bridge": {"type": "redis", "redis_url": "$C_NATIVE_REDIS_URL", "heartbeat_interval_seconds": 1},
            "memory": {"enabled": False},
            "scheduler": {"enabled": True, "tool_enabled": True, "multi_instance": True, "poll_interval_seconds": 1, "min_once_delay_seconds": 1, "max_concurrent_runs": 1} if scheduled_mode else {"enabled": False},
            "mcp_tasks": {"enabled": dependency_mode, "poll_interval_seconds": 1},
        }
        native = {
            "enabled": True,
            "role": "central",
            "artifact_root": str(artifacts),
            "database_url_env": "C_NATIVE_EXECUTOR_DATABASE_URL",
            "native_node": "one",
            "profile": "native",
            "profiles": {"native": {"cpu_millis": 500, "memory_mib": 1024}},
            "nodes": {"one": {"cpu_millis": 2000, "memory_mib": 4096, "resident_cpu_millis": 1500, "resident_memory_mib": 2048, "max_concurrency": 1, "profiles": ["native"], "kinds": ["B", "C"]}},
            "worker_credential_env": {"one": "C_NATIVE_NODE_SECRET"},
            "remote_origins": ["schedule"],
        }
        if dependency_mode:
            native["nodes"]["one"]["profiles"].append("small")
        for role, port in (("central", central_port), ("worker", worker_port)):
            role_config = {**config, "sandbox": {**config["sandbox"], "container_prefix": prefix + "-" + role}, "memory": _native_memory_config(tmp_path, role, enabled=memory_mode)}
            config_path = tmp_path / (role + ".yaml")
            config_path.write_text(yaml.safe_dump(role_config))
            dispatch_path = tmp_path / (role + "-native.json")
            dispatch_path.write_text(
                json.dumps(
                    native if role == "central" else {"enabled": True, "role": "worker", "artifact_root": str(artifacts), "executor_url": f"http://127.0.0.1:{central_port}", "node_id": "one", "credential_env": "C_NATIVE_NODE_SECRET"}
                )
            )
            log = (tmp_path / (role + ".log")).open("w")
            handles.append(log)
            child_env = {**environment, "DEER_FLOW_CONFIG_PATH": str(config_path), "ECS_NATIVE_CONFIG": str(dispatch_path)}
            process = subprocess.Popen([str(backend / ".venv/bin/python"), "-m", "uvicorn", "app.gateway.app:app", "--host", "127.0.0.1", "--port", str(port)], cwd=backend, env=child_env, stdout=log, stderr=subprocess.STDOUT)
            processes.append(process)
            for _ in range(180):
                if process.poll() is not None:
                    raise AssertionError(f"{role} Gateway startup failed; inspect sanitized test-owned log")
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health/ready", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                raise AssertionError(f"{role} Gateway failed readiness")
        central = f"http://127.0.0.1:{central_port}"
        worker = f"http://127.0.0.1:{worker_port}"
        with httpx.Client(base_url=central, timeout=240, limits=httpx.Limits(max_keepalive_connections=0)) as client:
            initialized = client.post("/api/v1/auth/initialize", json={"email": "native-c@example.com", "password": "NativeC!" + secrets.token_urlsafe(20)}, headers={"Origin": central})
            assert initialized.status_code == 201, initialized.status_code
            owner = initialized.json()["id"]
            headers = {"X-DeerFlow-Internal-Token": environment["DEER_FLOW_INTERNAL_AUTH_TOKEN"], "X-DeerFlow-Owner-User-Id": owner, "Authorization": "Bearer internal-test"}
            if memory_mode:
                _run_memory_main(client, worker, headers, owner, tmp_path, environment, run_id)
                return
            if dependency_mode:
                from test_ecs_executor_bc_main import _run_dependency_main, _setup_dependency_pool

                _setup_dependency_pool(backend, tmp_path, environment, native, owner, processes, handles, central_port, worker_port)
                _run_dependency_main(client, headers, owner, tmp_path, environment, run_id, scheduled_mode=scheduled_mode)
                return
            thread = "native-c-" + run_id
            response = client.post("/api/threads", json={"thread_id": thread}, headers=headers)
            assert response.status_code in (200, 201), response.text[:200]
            prompt = (
                "Use your native bash tool to write warm_native_c into /tmp/native_c_affinity.txt (container-local, not NAS), then run python3 in the sandbox. Calculate sum(i*i for i in range(1,101)), "
                "write the exact result and platform.system() to /mnt/user-data/outputs/native_c_main.txt. "
                "Read the file with your native read_file tool, then invoke native present_files on that exact output path to deliver it. Finally answer with its exact contents. You must actually execute the tool."
            )
            started = client.post(
                f"/api/threads/{thread}/runs",
                headers=headers,
                json={
                    "assistant_id": "lead_agent",
                    "input": {"messages": [{"role": "user", "content": prompt}]},
                    "metadata": {"deerflow_origin": {"kind": "schedule"}},
                    "context": {"model_name": "deepseek-chat", "non_interactive": True},
                    "stream_mode": ["values", "messages-tuple", "custom"],
                    "on_disconnect": "continue",
                    "config": {"recursion_limit": 100},
                },
            )
            assert started.status_code == 200, started.text[:250]
            admitted_run = started.json()["run_id"]
            peer = httpx.get(worker + f"/api/threads/{thread}/runs/{admitted_run}/join", headers=headers, timeout=240)
            assert peer.status_code == 200 and "event: end" in peer.text
            result = client.get(f"/api/threads/{thread}/runs/{admitted_run}", headers=headers).json()
            peer_state = httpx.get(worker + f"/api/threads/{thread}/state", headers=headers).json()
            messages = peer_state.get("values", {}).get("messages", [])
            (tmp_path / "peer-stream.txt").write_text(peer.text)
            if result["status"] != "success":
                diagnostic_engine = create_engine(environment["C_NATIVE_EXECUTOR_DATABASE_URL"])
                with diagnostic_engine.connect() as connection:
                    row = connection.execute(text("select status,error,stop_reason,owner_worker_id,cancel_action from runs where run_id=:id"), {"id": admitted_run}).mappings().one()
                    diagnostic = str(dict(row))[:2000]
                    for value in environment.values():
                        if len(value) >= 12:
                            diagnostic = diagnostic.replace(value, "<redacted>")
                    print("Native durable terminal diagnostic: " + diagnostic)
                diagnostic_engine.dispose()
                raise AssertionError("Native run terminal observation: " + str({key: result.get(key) for key in ("status", "error", "stop_reason")}))
            assert messages, "Native peer checkpoint messages missing"
            names_in_checkpoint = {call.get("name") for message in messages for call in message.get("tool_calls", [])}
            assert {"bash", "read_file", "present_files"} <= names_in_checkpoint, names_in_checkpoint
            artifact = tmp_path / "nas/users" / owner / "threads" / thread / "user-data/outputs/native_c_main.txt"
            assert "338350" in artifact.read_text() and "Linux" in artifact.read_text()
            sql = create_engine(environment["C_NATIVE_EXECUTOR_DATABASE_URL"])
            with sql.connect() as connection:
                jobs = [row[0] for row in connection.execute(text("select record from ecs_execution_jobs"))]
                assert len(jobs) == 1 and jobs[0]["native"]["run_id"] == admitted_run and jobs[0]["node_id"] == "one"
                assert connection.execute(text("select count(*) from runs where run_id=:id"), {"id": admitted_run}).scalar_one() == 1
                worker_identity = re.search(r"Run lease heartbeat started for worker ([^\n]+)", (tmp_path / "worker.log").read_text()).group(1)
                central_identity = re.search(r"Run lease heartbeat started for worker ([^\n]+)", (tmp_path / "central.log").read_text()).group(1)
                native_owner = connection.execute(text("select owner_worker_id from runs where run_id=:id"), {"id": admitted_run}).scalar_one()
                assert native_owner == worker_identity and native_owner != central_identity
                assert connection.execute(text("select count(*) from run_events where run_id=:id"), {"id": admitted_run}).scalar_one() > 0
            containers = json.loads(
                subprocess.run(
                    ["docker", "inspect", *subprocess.run(["docker", "ps", "-q", "--filter", "name=" + prefix + "-worker"], capture_output=True, text=True, check=True).stdout.split()], capture_output=True, text=True, check=True
                ).stdout
            )
            assert containers and all(value["HostConfig"]["NanoCpus"] == 1_000_000_000 and value["HostConfig"]["Memory"] == 1024**3 for value in containers)
            print("Native C receipt: one original Run ID, worker owner, DeepSeek+native AIO bash/read_file, Linux artifact, PG events/checkpoint and Redis peer END; AIO Docker limits 1CPU/1GiB.")
            continuation = client.post(
                f"/api/threads/{thread}/runs",
                headers=headers,
                json={
                    "assistant_id": "lead_agent",
                    "input": {
                        "messages": [
                            {
                                "role": "user",
                                "content": "Use bash immediately: cat /tmp/native_c_affinity.txt > /mnt/user-data/outputs/cancel_ready.txt; sleep 120. Do not create or change the existing /tmp marker. Actually invoke bash now.",
                            }
                        ]
                    },
                    "context": {"model_name": "deepseek-chat"},
                    "on_disconnect": "continue",
                    "config": {"recursion_limit": 30},
                },
            )
            assert continuation.status_code == 200, continuation.text[:200]
            cancelled_run = continuation.json()["run_id"]
            for _ in range(30):
                with sql.connect() as connection:
                    count = connection.execute(text("select count(*) from ecs_execution_jobs where record->'native'->>'run_id'=:id"), {"id": cancelled_run}).scalar_one()
                if count == 1:
                    break
                time.sleep(0.2)
            assert count == 1, "A later interactive run lost durable native thread affinity"
            ready = artifact.parent / "cancel_ready.txt"
            for _ in range(180):
                if ready.exists():
                    break
                time.sleep(0.25)
            assert ready.exists() and ready.read_text().strip() == "warm_native_c", "Native container-local warm state was not preserved"
            active_ids = subprocess.run(["docker", "ps", "-q", "--filter", "name=" + prefix + "-worker"], capture_output=True, text=True, check=True).stdout.split()
            assert active_ids == [containers[0]["Id"][:12]], "Affinity replaced the native warm container"
            cancel = client.post(f"/api/threads/{thread}/runs/{cancelled_run}/cancel", headers=headers)
            assert cancel.status_code in (202, 204), cancel.text[:200]
            for _ in range(480):
                with sql.connect() as connection:
                    stopped = connection.execute(text("select record from ecs_execution_jobs where record->'native'->>'run_id'=:id"), {"id": cancelled_run}).scalar_one()
                if stopped.get("physical_stopped"):
                    break
                time.sleep(0.25)
            assert stopped["state"] == "cancelled" and stopped["physical_stopped"] is True, "Cancellation released no physically settled native attempt"
            remaining = subprocess.run(["docker", "ps", "-q", "--filter", "name=" + prefix + "-worker"], capture_output=True, text=True, check=True).stdout.strip()
            assert not remaining, "Native cancelled shell container remained physically running"
            peer_result = httpx.get(worker + f"/api/threads/{thread}/runs/{cancelled_run}", headers=headers).json()
            assert peer_result["status"] == "interrupted"
            print(
                "Native C cancellation receipt: later interactive admission retained the worker and container-local /tmp state; "
                "central cancel reached worker, native finally drained, exact sandbox physically STOPped before dynamic reservation release."
            )
            sql.dispose()
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        for handle in handles:
            handle.close()
        own_sandboxes = subprocess.run(["docker", "ps", "-aq", "--filter", "name=" + prefix], capture_output=True, text=True).stdout.split()
        for name in names + own_sandboxes:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _run_memory_main(client, worker, headers, owner, tmp_path, environment, run_id):
    # Prime the peer before central writes, so its next read must see a peer revision.
    before = httpx.get(worker + "/api/memory", headers=headers)
    assert before.status_code == 200 and before.json()["facts"] == []
    lookup = "native-memory-" + run_id
    secret_value = "receipt-" + uuid.uuid4().hex
    seed_content = f"My {lookup} receipt value is {secret_value}."
    seed = client.post("/api/memory/facts", headers=headers, json={"content": seed_content, "category": "context", "confidence": 1.0})
    assert seed.status_code == 200, seed.status_code
    seed_fact = next(fact for fact in seed.json()["facts"] if fact["content"] == seed_content)
    peer = httpx.get(worker + "/api/memory", headers=headers)
    assert peer.status_code == 200 and seed_fact["id"] in {fact["id"] for fact in peer.json()["facts"]}
    bob = client.post("/api/v1/auth/register", headers={"Origin": str(client.base_url).rstrip("/")}, json={"email": "memory-peer@example.com", "password": "NativeM!" + secrets.token_urlsafe(20)})
    assert bob.status_code == 201, bob.status_code
    other_headers = {**headers, "X-DeerFlow-Owner-User-Id": bob.json()["id"]}
    for origin in (str(client.base_url).rstrip("/"), worker):
        other = httpx.get(origin + "/api/memory", headers=other_headers)
        assert other.status_code == 200 and secret_value not in other.text
    thread = "native-memory-" + run_id
    created = client.post("/api/threads", json={"thread_id": thread}, headers=headers)
    assert created.status_code in (200, 201), created.status_code
    added_content = f"My native memory acceptance label is {lookup}."
    prompt = (
        f"Use native memory_search to find my stored {lookup} receipt. Then use memory_get with the returned fact ID to read its full content. "
        "The receipt value is only in stored memory; do not guess it. "
        f"Use native memory_add to store exactly this new fact: {added_content} "
        "Use native write_file to write the full retrieved receipt fact into /mnt/user-data/outputs/native_memory_receipt.txt. "
        "Invoke native present_files on that exact file to deliver it. Finally answer with the retrieved full fact. Actually invoke all five tools."
    )
    assert secret_value not in prompt and seed_fact["id"] not in prompt
    started = client.post(
        f"/api/threads/{thread}/runs",
        headers=headers,
        json={
            "assistant_id": "lead_agent",
            "input": {"messages": [{"role": "user", "content": prompt}]},
            "metadata": {"deerflow_origin": {"kind": "schedule"}},
            "context": {"model_name": "deepseek-chat", "non_interactive": True},
            "stream_mode": ["values", "messages-tuple", "custom"],
            "on_disconnect": "continue",
            "config": {"recursion_limit": 100},
        },
    )
    assert started.status_code == 200, started.status_code
    admitted_run = started.json()["run_id"]
    joined = httpx.get(worker + f"/api/threads/{thread}/runs/{admitted_run}/join", headers=headers, timeout=240)
    assert joined.status_code == 200 and "event: end" in joined.text
    result = client.get(f"/api/threads/{thread}/runs/{admitted_run}", headers=headers).json()
    assert result["status"] == "success", {key: result.get(key) for key in ("status", "error", "stop_reason")}
    state = httpx.get(worker + f"/api/threads/{thread}/state", headers=headers).json()
    messages = state.get("values", {}).get("messages", [])
    calls = [call for message in messages for call in message.get("tool_calls", [])]
    assert {"memory_search", "memory_get", "memory_add", "write_file", "present_files"} <= {call["name"] for call in calls}
    get_calls = [call for call in calls if call["name"] == "memory_get"]
    assert any(call["args"].get("fact_id") == seed_fact["id"] for call in get_calls)
    tool_results = [message for message in messages if message.get("type") == "tool" or message.get("role") == "tool"]
    assert any(message.get("name") == "memory_get" and seed_content in str(message.get("content")) for message in tool_results)
    assert any(secret_value in str(message.get("content")) for message in messages if message.get("type") == "ai" or message.get("role") == "assistant")
    presented_path = "/mnt/user-data/outputs/native_memory_receipt.txt"
    assert presented_path in state.get("values", {}).get("artifacts", [])
    presented_calls = [call for call in calls if call["name"] == "present_files" and call["args"].get("filepaths") == [presented_path]]
    assert presented_calls, "Receipt path was not passed to native present_files"
    assert any(message.get("tool_call_id") in {call["id"] for call in presented_calls} and message.get("content") == "Successfully presented files" for message in tool_results), "Native present_files did not report successful delivery"
    delivered = client.get(f"/api/threads/{thread}/artifacts/{presented_path.lstrip('/')}", headers=headers)
    assert delivered.status_code == 200 and seed_content in delivered.text
    artifact = tmp_path / "nas/users" / owner / "threads" / thread / "user-data/outputs/native_memory_receipt.txt"
    assert seed_content in artifact.read_text()
    for origin in (str(client.base_url).rstrip("/"), worker):
        observed = httpx.get(origin + "/api/memory", headers=headers)
        assert observed.status_code == 200
        contents = {fact["content"] for fact in observed.json()["facts"]}
        assert {seed_content, added_content} <= contents
        other = httpx.get(origin + "/api/memory", headers=other_headers)
        assert other.status_code == 200 and secret_value not in other.text and added_content not in other.text
    root = tmp_path / "nas"
    assert (root / "users" / owner / "memory.json").is_file()
    facts = list((root / "users" / owner / "agents/__default__/facts").rglob("*.md"))
    assert len(facts) == 2 and all(any(content in fact.read_text() for fact in facts) for content in (seed_content, added_content))
    indexes = [tmp_path / (role + "-memory-index/memory-fts5.sqlite3") for role in ("central", "worker")]
    assert all(path.is_file() for path in indexes) and not indexes[0].samefile(indexes[1])
    assert not list(root.rglob("*.sqlite3*")), "Shared canonical home contains a derived SQLite/WAL file"
    sql = create_engine(environment["C_NATIVE_EXECUTOR_DATABASE_URL"])
    try:
        with sql.connect() as connection:
            jobs = list(connection.execute(text("select record from ecs_execution_jobs")).scalars())
            assert len(jobs) == 1 and jobs[0]["native"]["run_id"] == admitted_run and jobs[0]["node_id"] == "one"
            worker_identity = re.search(r"Run lease heartbeat started for worker ([^\n]+)", (tmp_path / "worker.log").read_text()).group(1)
            assert connection.execute(text("select owner_worker_id from runs where run_id=:id"), {"id": admitted_run}).scalar_one() == worker_identity
            assert connection.execute(text("select count(*) from runs where run_id=:id"), {"id": admitted_run}).scalar_one() == 1
            assert connection.execute(text("select count(*) from run_events where run_id=:id"), {"id": admitted_run}).scalar_one() > 0
    finally:
        sql.dispose()
    print("Native memory receipt: one remote original Run; actual memory_search/get/add and file delivery; shared per-owner Markdown facts, peer revision visibility, other-owner isolation; two local FTS indexes and no NAS SQLite/WAL.")

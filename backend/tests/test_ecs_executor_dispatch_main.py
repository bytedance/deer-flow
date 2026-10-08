"""Shared operator resource admission and outbound worker boundary."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def source(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "packages" / "ecs-executor"))


def test_shared_budget_resident_overhead_unknown_and_c_eligibility(tmp_path):
    from ecs_executor.job_store import JobStore
    from ecs_executor.nodes import Node
    from ecs_executor.scheduling import Scheduling

    store = JobStore("sqlite:///" + str(tmp_path / "jobs.db"))
    store.initialize()
    pool = Scheduling(store, nodes={"one": Node(cpu_millis=1000, memory_mib=256, resident_cpu_millis=500, resident_memory_mib=128, max_concurrency=1, profiles={"small"}, kinds={"B", "C"})})

    def queued(key, kind="B"):
        job = store.create(namespace="trusted", request_key=key, spec_digest=key, record={"kind": kind, "profile": {"cpu_millis": 500, "memory_mib": 128}, "spec": {"profile": "small"}})
        return store.mutate(job["id"], lambda row: row.update(state="queued"))

    history = queued("history")
    store.mutate(history["id"], lambda row: row.update(state="completed", physical_stopped=True, node_id="one", input_snapshot="historical"))
    from sqlalchemy import event

    statements = []
    event.listen(store.engine, "before_cursor_execute", lambda connection, cursor, statement, parameters, context, many: statements.append(statement.lower()))
    first, second = queued("first"), queued("second")
    claimed = pool.claim("one", "worker")
    assert claimed["id"] == first["id"]
    assert claimed["node_id"] == "one" and claimed["attempt"] == 1
    assert any("sum(" in statement for statement in statements)
    assert any("limit" in statement and "ecs_execution_jobs" in statement for statement in statements)
    statements.clear()
    assert [job["id"] for job in pool.owned("one", "worker")] == [first["id"]]
    reads = [statement for statement in statements if statement.startswith("select") and "ecs_execution_jobs" in statement]
    assert reads and all("where" in statement for statement in reads)
    assert pool.claim("one", "worker") is None
    store.mutate(first["id"], lambda row: row.update(state="uncertain", lease_until=0))
    assert pool.claim("one", "worker") is None
    with pytest.raises(ValueError, match="fence"):
        pool.report("one", "intruder", first["id"], claimed["generation"], {"physical_stopped": True})
    pool.report("one", "worker", first["id"], claimed["generation"], {"state": "failed", "physical_stopped": True})
    second_claim = pool.claim("one", "worker")
    assert second_claim["id"] == second["id"]
    c = queued("native", "C")
    assert pool.eligible("one", c)
    assert pool.claim("one", "worker") is None
    pool.report("one", "worker", second["id"], second_claim["generation"], {"state": "completed", "physical_stopped": True})
    assert pool.claim("one", "native-dispatch", kind="C")["id"] == c["id"]
    store.mutate(c["id"], lambda row: row.update(lease_until=0))
    before = store.get(c["id"])
    assert pool.owned("one", "docker-worker") == []
    assert store.get(c["id"]) == before
    assert pool.claim("one", "docker-worker") is None
    assert pool.owned("one", "native-recovery", kind="C")[0]["id"] == c["id"]
    assert pool.nodes["one"].resident_cpu_millis == 500


@pytest.mark.asyncio
async def test_real_postgres_tcp_two_workers_native_queue(tmp_path, monkeypatch):
    import asyncio
    import json
    import os
    import secrets
    import socket
    import sys
    import uuid
    from datetime import UTC, datetime, timedelta

    import httpx
    from ecs_executor.job_store import JobStore
    from ecs_executor.worker import Docker
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.mcp_tasks.service import McpTaskService
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller
    from deerflow.mcp.tasks import McpTaskDriverRegistry, TaskSubmitRequest
    from deerflow.mcp.tasks.ordinary import OrdinaryMcpTaskDriver
    from deerflow.persistence.mcp_tasks import McpTaskRepository
    from deerflow.persistence.mcp_tasks.model import McpTaskRow
    from deerflow.persistence.thread_meta.model import ThreadMetaRow

    if os.environ.get("ECS_EXECUTOR_POOL_TEST") != "1":
        pytest.skip("Set ECS_EXECUTOR_POOL_TEST=1 for task-owned PostgreSQL/TCP/Docker proof")
    docker = Docker()
    pg_name = "ecs-pool-test-" + uuid.uuid4().hex
    password = secrets.token_urlsafe(32)
    processes, job_ids = [], []
    engine = store = None
    try:
        await docker.checked("run", "-d", "--name", pg_name, "-e", "POSTGRES_PASSWORD=" + password, "-p", "127.0.0.1::5432", "postgres:16-alpine")
        mapped = (await docker.checked("port", pg_name, "5432/tcp")).decode().strip()
        pg_port = int(mapped.rsplit(":", 1)[1])
        db = f"postgresql+psycopg://postgres:{password}@127.0.0.1:{pg_port}/postgres"
        store = JobStore(db)
        for _ in range(100):
            try:
                await asyncio.to_thread(store.initialize)
                break
            except Exception:
                await asyncio.sleep(0.1)
        else:
            raise AssertionError("Task-owned PostgreSQL readiness failed")
        engine = create_async_engine(db.replace("+psycopg", "+asyncpg"))
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: ThreadMetaRow.__table__.create(conn, checkfirst=True))
            await connection.run_sync(lambda conn: McpTaskRow.__table__.create(conn, checkfirst=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            session.add(ThreadMetaRow(thread_id="pool-thread", user_id="alice", incarnation="generation", metadata_json={}))
            await session.commit()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        root = tmp_path / "nas"
        root.mkdir()
        secret = "scope-secret-at-least-32-bytes-long"
        node = {"cpu_millis": 1000, "memory_mib": 256, "resident_cpu_millis": 500, "resident_memory_mib": 128, "max_concurrency": 1, "profiles": ["small"], "kinds": ["B", "C"]}
        config = {
            "mode": "pool",
            "database_url": db,
            "audience": "executor",
            "profiles": {"small": {"image": "alpine:3.20", "cpu_millis": 500, "memory_mib": 128}},
            "user_profiles": {"alice": ["small"]},
            "artifact_root": str(root),
            "user_credential_env": {"alice": "POOL_USER"},
            "discovery_credential_env": "POOL_DISCOVERY",
            "worker_credential_env": {"one": "POOL_ONE", "two": "POOL_TWO"},
            "nodes": {"one": node, "two": node},
            "artifact_base_url": url,
            "port": port,
        }
        path = tmp_path / "central.json"
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        env = {**os.environ, "ECS_EXECUTOR_CONFIG": str(path), "ECS_EXECUTOR_SCOPE_SECRET": secret, "POOL_USER": "user-token", "POOL_DISCOVERY": "discovery-token", "POOL_ONE": "node-one-token", "POOL_TWO": "node-two-token"}
        env["PYTHONPATH"] = os.pathsep.join(str(Path(__file__).resolve().parents[1] / relative) for relative in ("packages/harness", "packages/extension-api", "packages/ecs-executor"))

        async def spawn(module, extra=None):
            process = await asyncio.create_subprocess_exec(sys.executable, "-m", module, env={**env, **(extra or {})}, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            processes.append(process)
            return process

        central = await spawn("ecs_executor.mcp_server")
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(100):
                assert central.returncode is None, "Pool central exited"
                try:
                    if (await client.get(url + "/artifacts/missing", headers={"Authorization": "Bearer user-token"})).status_code == 404:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("TCP central readiness failed")
            # Credentials cannot select another node, and mount/version drift
            # cannot activate jobs even with an authentic node credential.
            for headers, payload in [
                ({"Authorization": "Bearer node-one-token"}, {"owner": "bad", "protocol": "ecs-executor-1", "mount_id": (root / "pool-mount-id").read_text()}),
                ({"Authorization": "Bearer node-two-token"}, {"owner": "bad", "protocol": "old", "mount_id": "missing"}),
            ]:
                assert (await client.post(url + "/workers/two/poll", headers=headers, json=payload)).status_code == 403
        for node_id, variable in [("one", "POOL_ONE"), ("two", "POOL_TWO")]:
            worker_config = tmp_path / (node_id + ".json")
            worker_config.write_text(json.dumps({"executor_url": url, "node_id": node_id, "credential_env": variable, "artifact_root": str(root)}))
            await spawn("ecs_executor.dispatch", {"ECS_WORKER_CONFIG": str(worker_config)})
        for name, value in {
            "ECS_EXECUTOR_SCOPE_SECRET": secret,
            "ECS_EXECUTOR_SCOPE_SERVER": "ecs",
            "ECS_EXECUTOR_SCOPE_SUBMIT_TOOL": "submit",
            "ECS_EXECUTOR_SCOPE_STATUS_TOOL": "status",
            "ECS_EXECUTOR_SCOPE_CANCEL_TOOL": "cancel",
            "ECS_EXECUTOR_SCOPE_AUDIENCE": "executor",
        }.items():
            monkeypatch.setenv(name, value)
        native_config = ExtensionsConfig.model_validate(
            {
                "mcpInterceptors": ["ecs_executor.interceptor:build_execution_scope_interceptor"],
                "mcpServers": {
                    "ecs": {
                        "type": "http",
                        "url": url + "/mcp",
                        "headers": {"Authorization": "Bearer discovery-token"},
                        "user_auth": {"enabled": True, "on_missing": "deny", "users": {"alice": "Bearer user-token"}},
                        "task_toolsets": [{"name": "execution", "submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"}],
                    }
                },
            }
        )
        monkeypatch.setattr("ecs_executor.interceptor.get_extensions_config", lambda: native_config)
        repository = McpTaskRepository(sessions)
        registry = McpTaskDriverRegistry()
        registry.register("ordinary-tools", OrdinaryMcpTaskDriver(McpTaskToolCaller(native_config)))
        native = McpTaskService(repository=repository, drivers=registry, poll_interval_seconds=1, lease_seconds=30, max_concurrent_polls=4)
        rows = []

        @tool
        async def execute(request_key: str) -> str:
            """Submit through the unchanged native ordinary MCP task service."""
            row = await native.submit(
                driver_name="ordinary-tools",
                request=TaskSubmitRequest(
                    user_id="alice",
                    thread_id="pool-thread",
                    thread_incarnation="generation",
                    run_id="pool-run",
                    tool_call_id=request_key,
                    server_name="ecs",
                    task_name="execution",
                    arguments={"request_key": request_key, "profile": "small", "argv": ["sh", "-c", "sleep 4; printf pool-result"]},
                    driver_data={"submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"},
                ),
            )
            rows.append(row)
            return row["id"]

        graph = StateGraph(MessagesState, context_schema=dict)
        graph.add_node("tools", ToolNode([execute], handle_tool_errors=False))
        graph.add_edge(START, "tools")
        graph.add_edge("tools", END)
        graph = graph.compile()
        for key in ["first", "second", "waiting"]:
            await graph.ainvoke(
                {"messages": [AIMessage(content="", tool_calls=[{"name": "execute", "args": {"request_key": key}, "id": key, "type": "tool_call"}])]},
                context={"user_id": "alice", "thread_id": "pool-thread", "thread_incarnation": "generation", "run_id": "pool-run"},
            )
        await native.run_once(now=datetime.now(UTC) + timedelta(seconds=2))
        queued_observed = False
        used = set()
        maximum = 0
        for _ in range(250):
            active = await asyncio.to_thread(store.list_active)
            job_ids.extend(j["id"] for j in active if j["id"] not in job_ids)
            ledger = [store.get(job_id) for job_id in job_ids]
            reserved = [j for j in ledger if j.get("node_id") and not j.get("physical_stopped")]
            maximum = max(maximum, len(reserved))
            used.update(j["node_id"] for j in reserved)
            if len(reserved) == 2 and any(j["state"] == "queued" for j in active):
                queued_observed = True
            assert len(reserved) <= 2
            assert len({j["node_id"] for j in reserved}) == len(reserved)
            await native.run_once(now=datetime.now(UTC) + timedelta(seconds=2))
            tracked = [await repository.get(row["id"], user_id="alice", thread_id="pool-thread", thread_incarnation="generation") for row in rows]
            if all(row["status"] == "completed" for row in tracked):
                break
            assert all(p.returncode is None for p in processes), "A worker OS process exited"
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("Native pool tasks did not complete")
        assert queued_observed and maximum == 2 and used == {"one", "two"}
        assert len(job_ids) == 3
        for job_id in job_ids:
            job = store.get(job_id)
            assert job["attempt"] == 1 and job["state"] == "completed"
            assert json.loads((root / job_id / "result.json").read_text())["stdout"] == "pool-result"
        # Completion precedes removal; wait for actual cleanup proof before
        # asserting that the resource reservation has been released.
        for _ in range(100):
            if all(store.get(job_id).get("physical_stopped") for job_id in job_ids):
                break
            await asyncio.sleep(0.1)
        assert all(store.get(job_id).get("physical_stopped") for job_id in job_ids)
    finally:
        for process in reversed(processes):
            if process.returncode is None:
                process.terminate()
                await asyncio.wait_for(process.wait(), 10)
        for job_id in job_ids:
            await docker.command("rm", "-f", "deerflow-exec-" + job_id)
        if engine:
            await engine.dispose()
        if store:
            store.engine.dispose()
        await docker.command("rm", "-f", pg_name)

"""Ordinary MCP execution: durable staging, activation and local Docker work."""

from pathlib import Path

import pytest

SECRET = b"operator-secret-at-least-32-bytes-long"
SPEC = {"request_key": "request-1", "profile": "small", "argv": ["sh", "-c", "printf hello"]}


@pytest.fixture(autouse=True)
def optional_source(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "packages" / "ecs-executor"))


@pytest.fixture
def executor(tmp_path):
    import os

    from ecs_executor.job_store import JobStore
    from ecs_executor.jobs import ExecutionJobs, ExecutionProfile

    store = JobStore(os.environ.get("ECS_EXECUTOR_TEST_DB", "sqlite:///" + str(tmp_path / "execution.db")))
    store.initialize()
    return ExecutionJobs(store, secret=SECRET, audience="executor", profiles={"small": ExecutionProfile(image="alpine:3.20")}, user_profiles={"alice": {"small"}}, artifact_root=tmp_path / "artifacts")


def scope(operation, args, owner="alice", run="run-1"):
    from ecs_executor.scope import mint_execution_scope, mint_management_scope

    if operation != "submit":
        return mint_management_scope(secret=SECRET, audience="executor", user_id=owner, task_id=args["task_id"], operation=operation)
    return mint_execution_scope(secret=SECRET, audience="executor", user_id=owner, thread_id="thread", incarnation="generation", run_id=run, operation=operation, arguments=args)


def test_submission_is_durable_staged_until_signed_status(executor):
    submitted = executor.submit("alice", scope("submit", SPEC), SPEC)
    assert submitted["status"] == "running"
    job_id = submitted["task_id"]
    assert executor.store.get(job_id)["state"] == "staged"
    assert executor.store.claim_queued() is None
    with pytest.raises(ValueError):
        executor.status("alice", "", {"task_id": job_id})
    assert executor.store.get(job_id)["state"] == "staged"
    args = {"task_id": job_id}
    assert executor.status("alice", scope("status", args, run="background"), args)["status"] == "running"
    assert executor.store.claim_queued()["id"] == job_id


def test_owner_cancel_and_immutable_idempotency(executor):
    submitted = executor.submit("alice", scope("submit", SPEC), SPEC)
    assert executor.submit("alice", scope("submit", SPEC), SPEC) == submitted
    changed = {**SPEC, "argv": ["sh", "-c", "echo other"]}
    with pytest.raises(ValueError, match="request_key"):
        executor.submit("alice", scope("submit", changed), changed)
    args = {"task_id": submitted["task_id"]}
    with pytest.raises(ValueError):
        executor.status("bob", scope("status", args, owner="bob"), args)
    assert executor.cancel("alice", scope("cancel", args, run="background"), args)["status"] == "cancelled"
    assert executor.status("alice", scope("status", args, run="background"), args)["status"] == "cancelled"
    assert executor.store.claim_queued() is None


def test_expired_staging_cannot_be_activated(executor):
    submitted = executor.submit("alice", scope("submit", SPEC), SPEC)
    executor.store.expire_staged(now=10**12)
    args = {"task_id": submitted["task_id"]}
    assert executor.status("alice", scope("status", args), args)["status"] == "failed"
    assert executor.store.claim_queued() is None


@pytest.mark.asyncio
async def test_restart_never_replays_ambiguous_start(executor):
    from ecs_executor.worker import LocalWorker

    submitted = executor.submit("alice", scope("submit", SPEC), SPEC)
    args = {"task_id": submitted["task_id"]}
    executor.status("alice", scope("status", args), args)
    job = executor.store.claim_queued()
    executor.store.mutate(job["id"], lambda row: row.update(start_intent=True))

    class Docker:
        async def inspect(self, ref):
            return {"State": {"Status": "created", "Running": False}, "Config": {"Labels": {"deerflow.execution.job": job["id"], "deerflow.execution.spec": job["spec_digest"]}}}

        async def checked(self, *args):
            raise AssertionError("Restart must not replay docker start")

    await LocalWorker(executor, docker=Docker()).tick()
    assert executor.store.get(job["id"])["state"] == "uncertain"
    assert executor.store.get(job["id"])["start_intent"] is True


@pytest.mark.asyncio
async def test_real_http_mcp_discovery_cannot_submit(executor):
    import httpx
    from ecs_executor.mcp_server import create_server
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    server = create_server(executor, user_credentials={"alice": "alice-credential"}, discovery_credential="discover-only")
    app = server.streamable_http_app()

    def factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers=headers, timeout=timeout or 30, auth=auth)

    async with server.session_manager.run():
        async with streamablehttp_client("http://localhost:8003/mcp", headers={"Authorization": "Bearer discover-only"}, httpx_client_factory=factory) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert {tool.name for tool in (await session.list_tools()).tools} == {"submit", "status", "cancel"}
                result = await session.call_tool("submit", SPEC)
                assert result.isError
    assert executor.store.list_active() == []


@pytest.mark.asyncio
async def test_background_interceptor_signs_only_exact_bound_management(monkeypatch):
    from types import SimpleNamespace

    from ecs_executor.interceptor import build_execution_scope_interceptor
    from ecs_executor.scope import SCOPE_HEADER, verify_management_scope
    from langchain_mcp_adapters.interceptors import MCPToolCallRequest

    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    for name, value in {
        "ECS_EXECUTOR_SCOPE_SECRET": SECRET.decode(),
        "ECS_EXECUTOR_SCOPE_SERVER": "ecs",
        "ECS_EXECUTOR_SCOPE_SUBMIT_TOOL": "submit",
        "ECS_EXECUTOR_SCOPE_STATUS_TOOL": "status",
        "ECS_EXECUTOR_SCOPE_CANCEL_TOOL": "cancel",
        "ECS_EXECUTOR_SCOPE_AUDIENCE": "executor",
    }.items():
        monkeypatch.setenv(name, value)
    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "ecs": {
                    "type": "http",
                    "url": "http://localhost:8003/mcp",
                    "user_auth": {"enabled": True, "on_missing": "deny", "users": {"alice": "Bearer alice-credential"}},
                    "task_toolsets": [{"name": "execution", "submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"}],
                }
            }
        }
    )
    monkeypatch.setattr("ecs_executor.interceptor.get_extensions_config", lambda: config)
    interceptor = build_execution_scope_interceptor()
    headers = {}

    async def handler(request):
        headers.update(request.headers or {})

    token = set_current_user(SimpleNamespace(id="alice"))
    try:
        await interceptor(MCPToolCallRequest(name="status", args={"task_id": "job-1"}, server_name="ecs", runtime=None), handler)
    finally:
        reset_current_user(token)
    assert verify_management_scope(headers[SCOPE_HEADER], secret=SECRET, authenticated_user_id="alice", arguments={"task_id": "job-1"}, expected_audience="executor", expected_operation="status")["task_id"] == "job-1"


@pytest.mark.asyncio
async def test_native_sql_http_docker_main_cancel_restart(executor, tmp_path, monkeypatch):
    """Opt-in real Docker, real MCP protocol, native SQL tracking and recovery."""
    import asyncio
    import json
    import os
    import socket
    import sys
    import uuid
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    import httpx
    from ecs_executor.mcp_server import create_server
    from ecs_executor.worker import Docker, LocalWorker
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
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    if os.environ.get("ECS_EXECUTOR_DOCKER_TEST") != "1":
        pytest.skip("Set ECS_EXECUTOR_DOCKER_TEST=1 to run real local Docker")
    thread_id = "executor-" + uuid.uuid4().hex
    for name, value in {
        "ECS_EXECUTOR_SCOPE_SECRET": SECRET.decode(),
        "ECS_EXECUTOR_SCOPE_SERVER": "ecs",
        "ECS_EXECUTOR_SCOPE_SUBMIT_TOOL": "submit",
        "ECS_EXECUTOR_SCOPE_STATUS_TOOL": "status",
        "ECS_EXECUTOR_SCOPE_CANCEL_TOOL": "cancel",
        "ECS_EXECUTOR_SCOPE_AUDIENCE": "executor",
    }.items():
        monkeypatch.setenv(name, value)
    config = ExtensionsConfig.model_validate(
        {
            "mcpInterceptors": ["ecs_executor.interceptor:build_execution_scope_interceptor"],
            "mcpServers": {
                "ecs": {
                    "type": "http",
                    "url": "http://localhost:8003/mcp",
                    "headers": {"Authorization": "Bearer discover-only"},
                    "user_auth": {"enabled": True, "on_missing": "deny", "users": {"alice": "Bearer alice-credential"}},
                    "task_toolsets": [{"name": "execution", "submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"}],
                }
            },
        }
    )
    monkeypatch.setattr("ecs_executor.interceptor.get_extensions_config", lambda: config)
    tcp = os.environ.get("ECS_EXECUTOR_TCP_TEST") == "1"
    process = None
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    if not tcp:
        port = 8003
    base_url = f"http://127.0.0.1:{port}"
    config.mcp_servers["ecs"].url = base_url + "/mcp"
    server = create_server(executor, user_credentials={"alice": "alice-credential", "bob": "bob-credential"}, discovery_credential="discover-only", artifact_base_url=base_url)
    private_config = tmp_path / "executor-config.json"
    private_config.write_text(
        json.dumps(
            {
                "database_url": executor.store.engine.url.render_as_string(hide_password=False),
                "audience": "executor",
                "profiles": {"small": executor.profiles["small"].model_dump()},
                "user_profiles": {"alice": ["small"]},
                "artifact_root": str(executor.artifact_root),
                "user_credential_env": {"alice": "ECS_TEST_ALICE", "bob": "ECS_TEST_BOB"},
                "discovery_credential_env": "ECS_TEST_DISCOVERY",
                "artifact_base_url": base_url,
                "port": port,
            }
        ),
        encoding="utf-8",
    )
    private_config.chmod(0o600)

    async def start_process():
        nonlocal process
        env = {**os.environ, "ECS_EXECUTOR_CONFIG": str(private_config), "ECS_EXECUTOR_SCOPE_SECRET": SECRET.decode(), "ECS_TEST_ALICE": "alice-credential", "ECS_TEST_BOB": "bob-credential", "ECS_TEST_DISCOVERY": "discover-only"}
        env["PYTHONPATH"] = os.pathsep.join(str(Path(__file__).resolve().parents[1] / relative) for relative in ("packages/harness", "packages/extension-api", "packages/ecs-executor"))
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "ecs_executor.mcp_server", env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(100):
                if process.returncode is not None:
                    raise RuntimeError("Standalone executor exited during startup")
                try:
                    response = await client.get(base_url + "/artifacts/missing", headers={"Authorization": "Bearer alice-credential"})
                    if response.status_code == 404:
                        return
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(0.05)
        raise RuntimeError("Standalone executor readiness timed out")

    async def stop_process():
        nonlocal process
        if process and process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.wait(), 10)
        process = None

    @asynccontextmanager
    async def transport_lifespan():
        if tcp:
            await start_process()
            try:
                yield
            finally:
                await stop_process()
        else:
            async with server.session_manager.run():
                yield

    app = server.streamable_http_app()
    from deerflow.mcp import client as mcp_client

    original = mcp_client.build_server_params

    def params(name, server_config):
        result = original(name, server_config)
        result["httpx_client_factory"] = lambda headers=None, timeout=None, auth=None: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers=headers, timeout=timeout or 30, auth=auth)
        return result

    if not tcp:
        monkeypatch.setattr(mcp_client, "build_server_params", params)
        monkeypatch.setattr("deerflow.mcp.task_tool_caller.build_server_params", params)
    database_url = os.environ.get("ECS_EXECUTOR_NATIVE_TEST_DB", "sqlite+aiosqlite:///" + str(tmp_path / "native.db"))
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: ThreadMetaRow.__table__.create(conn, checkfirst=True))
        await connection.run_sync(lambda conn: McpTaskRow.__table__.create(conn, checkfirst=True))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(ThreadMetaRow(thread_id=thread_id, user_id="alice", incarnation="generation", metadata_json={}))
        await session.commit()
    repository = McpTaskRepository(session_factory)
    registry = McpTaskDriverRegistry()
    registry.register("ordinary-tools", OrdinaryMcpTaskDriver(McpTaskToolCaller(config)))

    def service():
        return McpTaskService(repository=repository, drivers=registry, poll_interval_seconds=1, lease_seconds=30, max_concurrent_polls=4)

    from ecs_executor.publication import WorkspacePublication

    native_metadata_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg").replace("sqlite+aiosqlite", "sqlite")
    workspace_root = tmp_path / "native-workspace"
    executor.publication = WorkspacePublication(workspace_root=workspace_root, metadata_database_url=native_metadata_url)
    private_options = json.loads(private_config.read_text())
    private_options.update(workspace_root=str(workspace_root), metadata_database_url=native_metadata_url)
    private_config.write_text(json.dumps(private_options), encoding="utf-8")
    native = service()
    submitted = []

    @tool
    async def execute(request_key: str, argv: list[str], input_files: dict[str, str] | None = None, input_refs: dict[str, dict[str, str]] | None = None) -> str:
        """Submit a command through the existing native task service."""
        row = await native.submit(
            driver_name="ordinary-tools",
            request=TaskSubmitRequest(
                user_id="alice",
                thread_id=thread_id,
                thread_incarnation="generation",
                run_id="run-1",
                tool_call_id=request_key,
                server_name="ecs",
                task_name="execution",
                arguments={"request_key": request_key, "profile": "small", "argv": argv, **({"input_files": input_files} if input_files is not None else {}), **({"input_refs": input_refs} if input_refs is not None else {})},
                driver_data={"submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"},
            ),
        )
        submitted.append(row)
        return row["id"]

    graph = StateGraph(MessagesState, context_schema=dict)
    graph.add_node("tools", ToolNode([execute], handle_tool_errors=False))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    graph = graph.compile()

    async def submit(key, argv, input_files=None, input_refs=None):
        await graph.ainvoke(
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "execute",
                                "args": {"request_key": key, "argv": argv, **({"input_files": input_files} if input_files is not None else {}), **({"input_refs": input_refs} if input_refs is not None else {})},
                                "id": key,
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            },
            context={"user_id": "alice", "thread_id": thread_id, "thread_incarnation": "generation", "run_id": "run-1"},
        )
        return submitted[-1]

    async def get(row):
        return await repository.get(row["id"], user_id="alice", thread_id=thread_id, thread_incarnation="generation")

    worker = LocalWorker(executor)

    async def tick():
        if tcp:
            await asyncio.sleep(0.1)
        else:
            await worker.tick()

    owner_token = set_current_user(SimpleNamespace(id="alice"))
    try:
        async with transport_lifespan():
            script = ("sleep 5; " if tcp else "sleep 1; ") + "printf input-snapshot-file > /output/result.txt; printf native-docker-result"
            import hashlib

            source = executor.publication.paths.sandbox_uploads_dir(thread_id, user_id="alice") / "program.sh"
            source.parent.mkdir(parents=True)
            source.write_text(script)
            row = await submit("main", ["sh", "/inputs/program.sh"], input_refs={"program.sh": {"path": "uploads/program.sh", "sha256": hashlib.sha256(script.encode()).hexdigest()}})
            source.write_text("printf mutated-source")
            assert (await get(row))["remote_task_id"] == row["remote_task_id"]
            assert executor.store.get(row["remote_task_id"])["state"] == "staged"
            await tick()
            assert executor.store.get(row["remote_task_id"])["state"] == "staged"
            await native.run_once(now=datetime.now(UTC) + timedelta(seconds=2))
            assert executor.store.get(row["remote_task_id"])["state"] in {"queued", "starting", "running"}
            await tick()
            if tcp:
                for _ in range(50):
                    observation = await Docker().inspect("deerflow-exec-" + row["remote_task_id"])
                    if observation and observation["State"]["Running"]:
                        break
                    await asyncio.sleep(0.1)
                assert observation["State"]["Running"]
                started_at = observation["State"]["StartedAt"]
                await stop_process()
                await start_process()
                assert (await Docker().inspect("deerflow-exec-" + row["remote_task_id"]))["State"]["StartedAt"] == started_at
            inspection = await Docker().inspect("deerflow-exec-" + row["remote_task_id"])
            assert inspection["HostConfig"]["Memory"] == 128 * 1024 * 1024
            assert inspection["HostConfig"]["NanoCpus"] == 500_000_000
            assert inspection["HostConfig"]["NetworkMode"] == "none"
            assert inspection["Config"]["User"] == "65534:65534"
            # Rebuild the native runtime against the same SQL rows.
            native = service()
            worker = LocalWorker(executor)
            for _ in range(100):
                await tick()
                await native.run_once(now=datetime.now(UTC) + timedelta(seconds=2))
                if (await get(row))["status"] == "completed":
                    break
                await asyncio.sleep(0.1)
            tracked = await get(row)
            assert tracked["status"] == "completed", tracked
            assert tracked["result_artifact"]["uri"].startswith(f"/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/")
            for _ in range(50):
                await tick()
                if await Docker().inspect("deerflow-exec-" + row["remote_task_id"]) is None:
                    break
                await asyncio.sleep(0.05)
            assert await Docker().inspect("deerflow-exec-" + row["remote_task_id"]) is None
            assert executor.store.get(row["remote_task_id"])["cleanup_pending"] is False
            artifact = executor.read_artifact("alice", row["remote_task_id"])
            assert artifact["stdout"] == "native-docker-result"
            assert artifact["exit_code"] == 0
            async with httpx.AsyncClient(transport=None if tcp else httpx.ASGITransport(app=app), base_url=base_url, trust_env=False) as client:
                assert (await client.get("/artifacts/" + row["remote_task_id"], headers={"Authorization": "Bearer bob-credential"})).status_code == 404
                assert (await client.get("/artifacts/" + row["remote_task_id"], headers={"Authorization": "Bearer alice-credential"})).json() == artifact
            from fastapi import FastAPI

            from app.gateway.authz import AuthContext, Permissions
            from app.gateway.routers.artifacts import router as artifact_router
            from deerflow.config.paths import Paths
            from deerflow.persistence.thread_meta import ThreadMetaRepository

            native_app = FastAPI()
            native_app.state.thread_store = ThreadMetaRepository(session_factory)

            @native_app.middleware("http")
            async def authenticated_native_request(request, call_next):
                # Authentication identity is a fixture; permission and native
                # SQL ownership checks are the production artifact decorator.
                user = SimpleNamespace(id=request.cookies.get("test_session", "alice"), system_role="user")
                request.state.auth = AuthContext(user=user, permissions=[Permissions.THREADS_READ])
                request.state.user = user
                identity_token = set_current_user(user)
                try:
                    return await call_next(request)
                finally:
                    reset_current_user(identity_token)

            native_app.include_router(artifact_router)
            monkeypatch.setattr("app.gateway.path_utils.get_paths", lambda: Paths(workspace_root))
            file_uri = tracked["result_artifact"]["uri"].removesuffix("result.json") + "files/result.txt"
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native_app), base_url="http://native-gateway") as client:
                response = await client.get(file_uri, cookies={"test_session": "alice"})
                assert response.status_code == 200, response.text
                assert response.content == b"input-snapshot-file"
                assert (await client.get(file_uri, cookies={"test_session": "bob"})).status_code == 404
            long = await submit("cancel", ["sh", "-c", "sleep 60"])
            await native.run_once(now=datetime.now(UTC) + timedelta(seconds=2))
            await tick()
            await native.cancel_task(task_id=long["id"], user_id="alice", thread_id=thread_id, thread_incarnation="generation")
            await native.run_once(now=datetime.now(UTC) + timedelta(seconds=2))
            assert (await get(long))["status"] != "cancelled"  # STOP still pending
            for _ in range(50):
                await tick()
                if executor.store.get(long["remote_task_id"])["state"] == "cancelled":
                    break
            assert executor.store.get(long["remote_task_id"])["state"] == "cancelled", executor.store.get(long["remote_task_id"])
            await native.run_once(now=datetime.now(UTC) + timedelta(seconds=120))
            assert (await get(long))["status"] == "cancelled", await get(long)
            assert await Docker().inspect("deerflow-exec-" + long["remote_task_id"]) is None
    finally:
        reset_current_user(owner_token)
        for row in submitted:
            await Docker().command("rm", "-f", "deerflow-exec-" + row["remote_task_id"])
        await engine.dispose()


def test_operator_network_allowlist_preserves_profile_authority(executor):
    from ecs_executor.jobs import ExecutionJobs, ExecutionProfile

    allowed = ExecutionJobs(
        executor.store,
        secret=SECRET,
        audience="executor",
        profiles={"net": ExecutionProfile(image="alpine:3.20", network="bridge")},
        user_profiles={"alice": {"net"}},
        artifact_root=executor.artifact_root,
        allowed_networks={"none", "bridge"},
    )
    spec = {**SPEC, "profile": "net"}
    submitted = allowed.submit("alice", scope("submit", spec), spec)
    assert allowed.store.get(submitted["task_id"])["profile"]["network"] == "bridge"
    with pytest.raises(ValueError):
        ExecutionJobs(executor.store, secret=SECRET, audience="executor", profiles={"net": ExecutionProfile(image="alpine:3.20", network="host")}, user_profiles={}, artifact_root=executor.artifact_root, allowed_networks={"none", "host"})


@pytest.mark.asyncio
async def test_declared_input_snapshots_reject_host_paths(executor, tmp_path, monkeypatch):
    import base64

    spec = {**SPEC, "input_files": {"program.py": base64.b64encode(b"print('safe')").decode()}}
    submitted = executor.submit("alice", scope("submit", spec), spec)
    assert executor.store.get(submitted["task_id"])["spec"]["input_files"] == spec["input_files"]
    import hashlib

    from ecs_executor.publication import WorkspacePublication
    from sqlalchemy import create_engine

    from deerflow.persistence.thread_meta.model import ThreadMetaRow

    url = "sqlite:///" + str(tmp_path / "native-ref.db")
    engine = create_engine(url)
    ThreadMetaRow.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(ThreadMetaRow.__table__.insert().values(thread_id="thread", user_id="alice", incarnation="generation", metadata_json={}))
    executor.publication = WorkspacePublication(workspace_root=tmp_path / "native-files", metadata_database_url=url)
    source = executor.publication.paths.sandbox_uploads_dir("thread", user_id="alice") / "报告.xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"immutable snapshot")
    refs = {"报告.xlsx": {"path": "uploads/报告.xlsx", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}
    declared = {**SPEC, "request_key": "native-ref", "input_refs": refs}
    tracked = executor.submit("alice", scope("submit", declared), declared)
    source.write_bytes(b"later edit")
    assert executor.submit("alice", scope("submit", declared), declared) == tracked
    assert base64.b64decode(executor.store.get(tracked["task_id"])["spec"]["input_files"]["报告.xlsx"]) == b"immutable snapshot"
    with pytest.raises(ValueError, match="digest"):
        executor.submit("alice", scope("submit", {**declared, "request_key": "changed-ref"}), {**declared, "request_key": "changed-ref"})
    from ecs_executor.files import collect, prepare

    job = executor.store.get(tracked["task_id"])
    boundary_name = "/".join(["a" * 255] * 2)
    assert len(boundary_name.encode("utf-8")) == 511
    job["spec"]["input_files"][boundary_name] = base64.b64encode(b"boundary input").decode()
    inputs, outputs = prepare(tmp_path / "jobs", job)
    assert (inputs / "报告.xlsx").read_bytes() == b"immutable snapshot"
    assert (inputs / boundary_name).read_bytes() == b"boundary input"
    (outputs / boundary_name).parent.mkdir()
    (outputs / boundary_name).write_bytes(b"boundary output")
    (outputs / "销售 report.csv").write_bytes(b"sales,total\n1,2\n")
    files = collect(outputs, limit=1024)
    assert files == {"销售 report.csv": b"sales,total\n1,2\n", boundary_name: b"boundary output"}
    uri = executor.publication.publish(job, b"{}", files)
    assert executor.publication.publish(job, b"{}", files) == uri

    from types import SimpleNamespace

    import httpx
    from _router_auth_helpers import make_authed_test_app
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.gateway.routers.artifacts import router as artifact_router
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    owner = "alice"
    app = make_authed_test_app(user_factory=lambda: SimpleNamespace(id=owner, system_role="user"), bind_current_user=True)
    native_engine = create_async_engine(url.replace("sqlite://", "sqlite+aiosqlite://"))
    app.state.thread_store = ThreadMetaRepository(async_sessionmaker(native_engine, expire_on_commit=False))
    app.include_router(artifact_router)
    monkeypatch.setattr("app.gateway.path_utils.get_paths", lambda: executor.publication.paths)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://native-gateway") as client:
            file_uri = uri.removesuffix("result.json") + "files/销售 report.csv"
            response = await client.get(file_uri)
            assert response.status_code == 200, response.text
            assert response.content == files["销售 report.csv"]
            owner = "bob"
            assert (await client.get(file_uri)).status_code == 404
    finally:
        await native_engine.dispose()

    for filename in (None, 1, "", "/etc/passwd", "../secret", "a/../secret", "a/./file", "a//file", "a/", "a\\file", "a\x00file", "a\nfile", "a\x7ffile", "a\x85file", "报" * 86, "/".join(["a" * 255] * 3)):
        bad = {**spec, "request_key": "bad", "input_files": {filename: "aGVsbG8="}}
        with pytest.raises(ValueError):
            executor.submit("alice", scope("submit", bad), bad)


def test_publication_rejects_stale_native_thread(tmp_path):
    from ecs_executor.publication import WorkspacePublication
    from sqlalchemy import create_engine

    from deerflow.persistence.thread_meta.model import ThreadMetaRow

    url = "sqlite:///" + str(tmp_path / "metadata.db")
    engine = create_engine(url)
    ThreadMetaRow.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(ThreadMetaRow.__table__.insert().values(thread_id="thread", user_id="alice", incarnation="new-generation", metadata_json={}))
    publication = WorkspacePublication(workspace_root=tmp_path / "workspace", metadata_database_url=url)
    with pytest.raises(ValueError, match="incarnation"):
        publication.publish({"id": "job", "user_id": "alice", "thread_id": "thread", "incarnation": "old-generation"}, b"{}", {"real.txt": b"output"})
    assert not list((tmp_path / "workspace").glob("**/real.txt"))


@pytest.mark.asyncio
async def test_combined_input_count_rejected_before_worker_admission(executor, tmp_path):
    # Snapshot/ownership is covered above; this case isolates the combined
    # request budget that must be checked before the remote ledger admission.
    from types import SimpleNamespace

    from ecs_executor.worker import LocalWorker

    executor.publication = SimpleNamespace(snapshot=lambda *args, **kwargs: {"reference.txt": b"reference"})
    oversized = {**SPEC, "input_files": {f"file-{n}.txt": "eA==" for n in range(64)}, "input_refs": {"reference.txt": {"path": "uploads/reference.txt", "sha256": "0" * 64}}}
    with pytest.raises(ValueError, match="64"):
        executor.submit("alice", scope("submit", oversized), oversized)
    assert executor.store.list_active() == []
    executor.publication = None
    valid = executor.submit("alice", scope("submit", SPEC), SPEC)
    executor.status("alice", scope("status", {"task_id": valid["task_id"]}), {"task_id": valid["task_id"]})

    class Docker:
        async def checked(self, *args):
            return b""

        async def inspect(self, ref):
            job = executor.store.get(valid["task_id"])
            return {"State": {"Status": "running", "Running": True}, "Config": {"Labels": {"deerflow.execution.job": job["id"], "deerflow.execution.spec": job["spec_digest"]}}}

    await LocalWorker(executor, docker=Docker()).tick()
    assert executor.store.get(valid["task_id"])["state"] == "running"


@pytest.mark.asyncio
async def test_terminal_cleanup_retries_after_restart_without_losing_result(executor):
    from ecs_executor.job_store import JobStore
    from ecs_executor.worker import LocalWorker

    submitted = executor.submit("alice", scope("submit", SPEC), SPEC)
    job_id = submitted["task_id"]
    executor.status("alice", scope("status", {"task_id": job_id}), {"task_id": job_id})
    executor.store.claim_queued()

    class Docker:
        removed = False
        failed = False

        async def inspect(self, ref):
            if self.removed:
                return None
            job = executor.store.get(job_id)
            return {"State": {"Status": "exited", "Running": False, "ExitCode": 0}, "Config": {"Labels": {"deerflow.execution.job": job_id, "deerflow.execution.spec": job["spec_digest"]}}}

        async def checked(self, *args):
            if args[0] == "logs":
                return b"durable result"
            assert args == ("rm", "deerflow-exec-" + job_id)
            if not self.failed:
                self.failed = True
                raise RuntimeError("Temporary removal failure")
            self.removed = True
            return b""

    docker = Docker()
    await LocalWorker(executor, docker=docker).tick()
    committed = executor.store.get(job_id)
    assert committed["state"] == "completed"
    assert committed["cleanup_pending"] is True
    assert executor.read_artifact("alice", job_id)["stdout"] == "durable result"
    # Reopen SQL and rebuild the worker, retaining only the physical observation.
    executor.store = JobStore(executor.store.engine.url.render_as_string(hide_password=False))
    await LocalWorker(executor, docker=docker).tick()
    assert docker.removed
    assert executor.store.get(job_id)["cleanup_pending"] is False
    assert executor.store.get(job_id)["state"] == "completed"
    assert executor.read_artifact("alice", job_id)["stdout"] == "durable result"

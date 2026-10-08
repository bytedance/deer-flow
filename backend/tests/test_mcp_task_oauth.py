"""Rotating OAuth credentials across discovery and durable deployment tasks."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths
from deerflow.mcp.cache import reset_mcp_tools_cache
from deerflow.mcp.oauth import get_initial_oauth_headers
from deerflow.mcp.task_tool_caller import McpTaskToolCaller
from deerflow.mcp.tasks import OrdinaryMcpTaskDriver, TaskReference, TaskStatus
from deerflow.mcp.tasks import runtime as task_runtime
from deerflow.mcp.tasks.runtime import (
    McpTaskConfigurationError,
    set_mcp_task_config_snapshot,
    set_mcp_task_submitter,
    validate_mcp_task_config_snapshot,
)
from deerflow.mcp.tools import get_mcp_tools
from deerflow.mcp.user_config import load_user_mcp_config, personal_server_name, user_mcp_config_path


class _Clock:
    current = datetime(2026, 1, 1, tzinfo=UTC)

    @classmethod
    def now(cls, _tz):
        return cls.current


class _RotatingServer:
    """Replace only HTTP transport; run real MCP client/adapters and OAuth code."""

    def __init__(self):
        self.refresh_token = "refresh-0"
        self.refresh_requests: list[str] = []
        self.generation = 0
        self.calls: list[tuple[str, str]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            submitted = parse_qs(request.content.decode())["refresh_token"][0]
            self.refresh_requests.append(submitted)
            if submitted != self.refresh_token:
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.generation += 1
            self.refresh_token = f"refresh-{self.generation}"
            return httpx.Response(
                200,
                json={"access_token": f"access-{self.generation}", "refresh_token": self.refresh_token, "expires_in": 120},
            )

        assert request.url.path == "/mcp"
        authorization = request.headers.get("Authorization")
        if authorization != f"Bearer access-{self.generation}":
            return httpx.Response(401)
        if request.method != "POST":
            return httpx.Response(405)
        message = json.loads(request.content)
        method = message["method"]
        if "id" not in message:
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "reports", "version": "1.0"},
            }
        elif method == "tools/list":
            result = {"tools": [{"name": name, "description": name, "inputSchema": {"type": "object", "properties": {}}} for name in ("submit_report", "status_report", "cancel_report", "search")]}
        elif method == "tools/call":
            name = message["params"]["name"]
            self.calls.append((name, authorization))
            result = {
                "isError": False,
                "content": [{"type": "text", "text": "ok"}],
                "structuredContent": {"task_id": "remote-1", "status": "cancelled" if name == "cancel_report" else "running"},
            }
        else:
            raise AssertionError(method)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})


@pytest.fixture
def rotating_server(monkeypatch):
    server = _RotatingServer()
    original_client = httpx.AsyncClient

    class OfflineClient(original_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(server.handle)
            kwargs["trust_env"] = False
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", OfflineClient)
    monkeypatch.setattr("deerflow.mcp.oauth.datetime", _Clock)
    monkeypatch.setattr(_Clock, "current", datetime(2026, 1, 1, tzinfo=UTC))
    yield server


@pytest.fixture
def task_config(tmp_path, monkeypatch):
    path = tmp_path / "extensions_config.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "reports": {
                        "type": "http",
                        "url": "https://reports.example.invalid/mcp",
                        "oauth": {
                            "token_url": "https://reports.example.invalid/token",
                            "grant_type": "refresh_token",
                            "refresh_token": "refresh-0",
                            "refresh_skew_seconds": 0,
                        },
                        "task_toolsets": [{"name": "reports", "submit_tool": "submit_report", "status_tool": "status_report", "cancel_tool": "cancel_report"}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(path))
    startup = ExtensionsConfig.from_file()
    set_mcp_task_config_snapshot(startup)
    try:
        yield path, startup
    finally:
        set_mcp_task_submitter(None)
        set_mcp_task_config_snapshot(None)


@pytest.mark.asyncio
async def test_discovery_submit_poll_and_rediscovery_share_rotating_oauth(task_config, rotating_server):
    path, startup = task_config
    initial_file = path.read_bytes()
    initial_config = startup.model_dump()
    driver = OrdinaryMcpTaskDriver(McpTaskToolCaller(startup))
    captured_requests = []

    # The Agent-visible wrapper reaches the real driver/caller. Persistence is
    # outside this test's scope; the submitter only records the request/handle.
    async def submit(*, driver_name, request):
        captured_requests.append(request)
        submission = await driver.submit(request)
        assert submission.remote_task_id == "remote-1"
        return {"id": "local-1", "status": submission.snapshot.status.value}

    set_mcp_task_submitter(SimpleNamespace(submit=submit))
    tools = await get_mcp_tools()
    assert [tool.name for tool in tools] == ["reports_submit_report", "reports_search"]
    graph = StateGraph(MessagesState, context_schema=dict)
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=False))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    result = await graph.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"name": "reports_submit_report", "args": {}, "id": "call-1", "type": "tool_call"}])]},
        context={"user_id": "user-1", "thread_id": "thread-1", "thread_incarnation": "incarnation-1"},
    )
    assert json.loads(result["messages"][-1].content)["task_id"] == "local-1"
    assert len(captured_requests) == 1
    reference = TaskReference(
        local_task_id="local-1",
        user_id="user-1",
        thread_id="thread-1",
        server_name="reports",
        remote_task_id="remote-1",
        driver_data=captured_requests[0].driver_data,
    )

    _Clock.current += timedelta(seconds=121)
    assert (await driver.get_status(reference)).status == TaskStatus.WORKING
    # Ordinary tools on the same task-enabled server must follow the poller's
    # refresh too, including tools rebuilt from the unchanged on-disk seed.
    assert await tools[1].ainvoke({})
    reset_mcp_tools_cache()
    rediscovered = await get_mcp_tools()
    assert [tool.name for tool in rediscovered] == ["reports_submit_report", "reports_search"]
    assert await rediscovered[1].ainvoke({})
    assert (await driver.cancel(reference)).status == TaskStatus.CANCELLED

    assert rotating_server.refresh_requests == ["refresh-0", "refresh-1"]
    assert rotating_server.calls == [
        ("submit_report", "Bearer access-1"),
        ("status_report", "Bearer access-2"),
        ("search", "Bearer access-2"),
        ("search", "Bearer access-2"),
        ("cancel_report", "Bearer access-2"),
    ]
    assert startup.model_dump() == initial_config
    assert path.read_bytes() == initial_file
    validate_mcp_task_config_snapshot(startup)
    validate_mcp_task_config_snapshot(ExtensionsConfig.from_file())


@pytest.mark.asyncio
async def test_rotation_does_not_mutate_loaded_config(task_config, rotating_server):
    _path, startup = task_config
    before = startup.model_dump()
    caller = McpTaskToolCaller(startup)
    await caller.call_tool(server_name="reports", tool_name="status_report", arguments={"task_id": "remote-1"}, user_id="user-1", thread_id="thread-1")
    assert startup.model_dump() == before
    validate_mcp_task_config_snapshot(startup)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["url", "refresh_token", "client_secret", "token_url"])
async def test_changed_task_credentials_still_require_restart(task_config, rotating_server, field):
    _path, startup = task_config
    await get_mcp_tools()
    changed = ExtensionsConfig.from_file()
    if field == "url":
        changed.mcp_servers["reports"].url = "https://other.example.invalid/mcp"
    else:
        setattr(changed.mcp_servers["reports"].oauth, field, "changed")
    with pytest.raises(McpTaskConfigurationError, match="restart DeerFlow"):
        await get_mcp_tools(changed)
    assert rotating_server.refresh_requests == ["refresh-0"]


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
async def test_task_transports_share_discovery_token(task_config, rotating_server, monkeypatch, transport):
    _path, startup = task_config
    startup.mcp_servers["reports"].type = transport
    set_mcp_task_config_snapshot(startup)
    caller = McpTaskToolCaller(startup)
    discovery = task_runtime.get_mcp_task_oauth_token_manager(startup.model_copy(deep=True))
    assert await get_initial_oauth_headers(startup, token_manager=discovery) == {"reports": "Bearer access-1"}
    connections = []

    @asynccontextmanager
    async def create_session(connection):
        connections.append(connection)
        yield SimpleNamespace(initialize=AsyncMock(), call_tool=AsyncMock(return_value="ok"))

    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", create_session)
    assert await caller.call_tool(server_name="reports", tool_name="status_report", arguments={}, user_id="user-1", thread_id="thread-1") == "ok"
    assert connections[0]["transport"] == transport
    assert connections[0]["headers"] == {"Authorization": "Bearer access-1"}
    assert rotating_server.refresh_requests == ["refresh-0"]


def test_separate_managers_deduplicate_refresh_across_event_loops(task_config, rotating_server, monkeypatch):
    managers = [task_runtime.get_mcp_task_oauth_token_manager(ExtensionsConfig.from_file()) for _ in range(3)]
    entered = threading.Event()
    all_acquiring = threading.Event()
    release = threading.Event()
    start = threading.Barrier(3)
    handle = rotating_server.handle
    state = managers[0]._states["reports"]
    original_lock = state.lock
    arrivals_lock = threading.Lock()
    arrivals = 0

    class ObservedLock:
        def acquire(self):
            nonlocal arrivals
            with arrivals_lock:
                arrivals += 1
                if arrivals == len(managers):
                    all_acquiring.set()
            return original_lock.acquire()

        def release(self):
            original_lock.release()

    monkeypatch.setattr(state, "lock", ObservedLock())

    async def held_response(request):
        if request.url.path == "/token":
            entered.set()
            assert await asyncio.to_thread(release.wait, 5), "test did not release token response"
        return handle(request)

    monkeypatch.setattr(rotating_server, "handle", held_response)

    def fetch(manager):
        start.wait(timeout=5)
        return asyncio.run(manager.get_authorization_header("reports"))

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(fetch, manager) for manager in managers]
        try:
            assert entered.wait(5), "token request did not start"
            assert all_acquiring.wait(5), "callers did not contend on the shared refresh lock"
        finally:
            release.set()
        assert [future.result(timeout=5) for future in futures] == ["Bearer access-1"] * 3
    assert rotating_server.refresh_requests == ["refresh-0"]


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_strand_shared_refresh_lock(task_config, rotating_server, monkeypatch):
    first = task_runtime.get_mcp_task_oauth_token_manager(ExtensionsConfig.from_file())
    second = task_runtime.get_mcp_task_oauth_token_manager(ExtensionsConfig.from_file())
    state = first._states["reports"]
    original_lock = state.lock
    entered = threading.Event()

    class ObservedLock:
        def acquire(self):
            entered.set()
            return original_lock.acquire()

        def release(self):
            original_lock.release()

    monkeypatch.setattr(state, "lock", ObservedLock())
    original_lock.acquire()
    waiter = asyncio.create_task(first.get_authorization_header("reports"))
    try:
        assert await asyncio.to_thread(entered.wait, 5), "waiter never reached lock acquisition"
        waiter.cancel()
    finally:
        original_lock.release()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, 5)
    following = asyncio.create_task(second.get_authorization_header("reports"))
    try:
        # asyncio.wait has a bounded return even if cancellation cleanup must
        # wait for an executor thread stuck acquiring a leaked lock.
        done, _pending = await asyncio.wait({following}, timeout=5)
        assert following in done, "cancelled waiter leaked the shared refresh lock"
        assert following.result() == "Bearer access-1"
    finally:
        if original_lock.locked():
            original_lock.release()
        await asyncio.gather(following, return_exceptions=True)
    assert rotating_server.refresh_requests == ["refresh-0"]


@pytest.mark.asyncio
async def test_task_runtime_reset_drops_rotated_oauth_state(task_config, rotating_server):
    _path, startup = task_config
    first = task_runtime.get_mcp_task_oauth_token_manager(ExtensionsConfig.from_file())
    assert await first.get_authorization_header("reports") == "Bearer access-1"
    set_mcp_task_config_snapshot(None)
    # A new lifetime needs a valid operator-supplied seed; retained in-process
    # credentials must not silently survive teardown or override that seed.
    startup.mcp_servers["reports"].oauth.refresh_token = "replacement-seed"
    rotating_server.refresh_token = "replacement-seed"
    set_mcp_task_config_snapshot(startup)
    second = task_runtime.get_mcp_task_oauth_token_manager(startup.model_copy(deep=True))
    assert await second.get_authorization_header("reports") == "Bearer access-2"
    assert rotating_server.refresh_requests == ["refresh-0", "replacement-seed"]


@pytest.mark.asyncio
async def test_hot_reloadable_servers_do_not_reuse_task_oauth_state(task_config, rotating_server):
    _path, startup = task_config
    other = startup.mcp_servers["reports"].model_copy(deep=True)
    other.task_toolsets = []
    startup.mcp_servers["other"] = other
    set_mcp_task_config_snapshot(startup)
    first = task_runtime.get_mcp_task_oauth_token_manager(startup)
    assert await first.get_authorization_header("other") == "Bearer access-1"
    changed = startup.model_copy(deep=True)
    changed.mcp_servers["other"].oauth.refresh_token = "replacement-seed"
    rotating_server.refresh_token = "replacement-seed"
    second = task_runtime.get_mcp_task_oauth_token_manager(changed)
    assert await second.get_authorization_header("other") == "Bearer access-2"
    assert rotating_server.refresh_requests == ["refresh-0", "replacement-seed"]


@pytest.mark.asyncio
async def test_snapshot_and_oauth_sharing_follow_the_same_server_selection(task_config, rotating_server, monkeypatch):
    _path, startup = task_config
    startup.mcp_servers["other"] = startup.mcp_servers["reports"].model_copy(deep=True)
    # Simulate a narrower task-server policy. A server excluded by that policy
    # must stay outside both the frozen snapshot and the shared OAuth lifetime.
    monkeypatch.setattr(task_runtime, "_task_enabled_servers", lambda config: {"reports": config.mcp_servers["reports"]}, raising=False)
    set_mcp_task_config_snapshot(startup)
    first = task_runtime.get_mcp_task_oauth_token_manager(startup)
    assert await first.get_authorization_header("reports") == "Bearer access-1"
    changed = startup.model_copy(deep=True)
    changed.mcp_servers["other"].oauth.refresh_token = "replacement-seed"
    validate_mcp_task_config_snapshot(changed)
    rotating_server.refresh_token = "replacement-seed"
    second = task_runtime.get_mcp_task_oauth_token_manager(changed)

    assert await second.get_authorization_header("reports") == "Bearer access-1"
    assert await second.get_authorization_header("other") == "Bearer access-2"
    assert rotating_server.refresh_requests == ["refresh-0", "replacement-seed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["discovery", "durable_call"])
async def test_personal_connection_cannot_reuse_same_named_deployment_oauth(task_config, rotating_server, tmp_path, monkeypatch, operation):
    _path, startup = task_config
    monkeypatch.setattr("deerflow.mcp.user_config.get_paths", lambda: Paths(base_dir=tmp_path))
    personal = startup.mcp_servers["reports"].model_dump(mode="json")
    personal["oauth"]["refresh_token"] = "personal-seed"
    personal["personal_public_network"] = True
    path = user_mcp_config_path("user-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": {"reports": personal}}), encoding="utf-8")
    name = personal_server_name("user-1", "reports", personal)
    startup.mcp_servers = {name: startup.mcp_servers["reports"]}
    set_mcp_task_config_snapshot(startup)
    caller = McpTaskToolCaller(startup)
    assert await get_initial_oauth_headers(startup, token_manager=task_runtime.get_mcp_task_oauth_token_manager(startup)) == {name: "Bearer access-1"}
    rotating_server.refresh_token = "personal-seed"
    before = path.read_bytes()

    if operation == "discovery":
        set_mcp_task_submitter(SimpleNamespace())
        tools = await get_mcp_tools(load_user_mcp_config("user-1"), personal_user_id="user-1")
        assert [tool.name for tool in tools] == [f"{name}_submit_report", f"{name}_search"]
        assert await tools[1].ainvoke({})
    else:
        await caller.call_tool(server_name=name, tool_name="status_report", arguments={"task_id": "remote-1"}, user_id="user-1", thread_id="thread-1", connection_scope="personal")
    assert rotating_server.refresh_requests == ["refresh-0", "personal-seed"]
    assert rotating_server.calls[-1][1] == "Bearer access-2"
    assert path.read_bytes() == before

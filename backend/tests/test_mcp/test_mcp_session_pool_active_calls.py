"""Capacity pressure must not interrupt already-admitted MCP calls."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, CallToolResult, ErrorData, TextContent

from deerflow.mcp.session_pool import MCPSessionPool, call_pooled_session_tool


class ControlledSession:
    def __init__(self, connection):
        self.connection = connection
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = connection.get("closed", asyncio.Event())

    async def initialize(self):
        if "initialize_started" in self.connection:
            self.connection["initialize_started"].set()
        if "initialize_gate" in self.connection:
            await self.connection["initialize_gate"].wait()

    async def call_tool(self, name, arguments, **kwargs):
        self.started.set()
        arguments.get("started", self.started).set()
        await arguments.get("release", self.release).wait()
        if self.closed.is_set():
            raise McpError(ErrorData(code=CONNECTION_CLOSED, message="Connection closed"))
        if "error" in arguments:
            raise arguments["error"]
        return CallToolResult(content=[TextContent(type="text", text="finished")], isError=arguments.get("is_error", False))


@pytest.fixture
def controlled_pool(monkeypatch):
    pool = MCPSessionPool()

    @asynccontextmanager
    async def create_session(connection):
        owner = asyncio.current_task()
        session = ControlledSession(connection)
        try:
            yield session
        finally:
            assert asyncio.current_task() is owner
            session.closed.set()

    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", create_session)
    return pool


async def call(session, pool, scope, *, domain="deployment", arguments=None):
    return await call_pooled_session_tool(session, pool, server_name="server", scope_key=scope, tool_name="slow", arguments=arguments or {}, call_kwargs={}, domain=domain)


@pytest.mark.asyncio
async def test_capacity_evicts_idle_session_instead_of_inflight_call(controlled_pool):
    pool = controlled_pool
    pool.MAX_SESSIONS = 2
    active = await pool.get_session("server", "active", {})
    idle = await pool.get_session("server", "idle", {})
    running = asyncio.create_task(call(active, pool, "active"))
    try:
        await asyncio.wait_for(active.started.wait(), 1)
        replacement = await pool.get_session("server", "replacement", {})
        assert not active.closed.is_set(), "LRU capacity eviction closed an in-flight call"
        assert idle.closed.is_set()
        active.release.set()
        result = await asyncio.wait_for(running, 1)
        assert result.content[0].text == "finished"
        assert len(pool._entries) == 2
        assert replacement is not idle
    finally:
        active.release.set()
        await asyncio.gather(running, return_exceptions=True)
        await pool.close_all()


@pytest.mark.asyncio
async def test_full_busy_pool_rejects_new_scope_without_closing_active_call(controlled_pool):
    pool = controlled_pool
    pool.MAX_SESSIONS = 1
    active = await pool.get_session("server", "active", {})
    running = asyncio.create_task(call(active, pool, "active"))
    try:
        await asyncio.wait_for(active.started.wait(), 1)
        with pytest.raises(RuntimeError, match="capacity"):
            await pool.get_session("server", "replacement", {})
        assert not pool._inflight
        assert len(pool._entries) == 1
        # Reusing an existing busy session does not require a new slot.
        assert await pool.get_session("server", "active", {}) is active
        assert not active.closed.is_set()
        active.release.set()
        assert (await asyncio.wait_for(running, 1)).content[0].text == "finished"
        replacement = await pool.get_session("server", "replacement", {})
        assert active.closed.is_set()
        assert replacement is not active
    finally:
        active.release.set()
        await asyncio.gather(running, return_exceptions=True)
        await pool.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["scope", "server", "session", "current", "all"])
async def test_explicit_close_still_retires_an_active_call(controlled_pool, operation):
    pool = controlled_pool
    active = await pool.get_session("server", "active", {})
    running = asyncio.create_task(call(active, pool, "active"))
    try:
        await asyncio.wait_for(active.started.wait(), 1)
        close = {
            "scope": lambda: pool.close_scope("active"),
            "server": lambda: pool.close_server("server"),
            "session": lambda: pool.close_session("server", "active"),
            "current": lambda: pool.close_session_if_current("server", "active", active),
            "all": pool.close_all,
        }[operation]
        await close()
        assert active.closed.is_set()
        active.release.set()
        with pytest.raises(McpError, match="Connection closed"):
            await asyncio.wait_for(running, 1)
    finally:
        active.release.set()
        await asyncio.gather(running, return_exceptions=True)
        await pool.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancel", "timeout", "protocol_error", "tool_error", "success"])
async def test_call_exit_releases_capacity_protection(controlled_pool, outcome):
    pool = controlled_pool
    pool.MAX_SESSIONS = 1
    session = await pool.get_session("server", "active", {})
    arguments = {}
    if outcome == "timeout":
        arguments["error"] = TimeoutError("tool timeout")
    elif outcome == "protocol_error":
        arguments["error"] = McpError(ErrorData(code=408, message="request timed out"))
    elif outcome == "tool_error":
        arguments["is_error"] = True
    running = asyncio.create_task(call(session, pool, "active", arguments=arguments))
    try:
        await asyncio.wait_for(session.started.wait(), 1)
        if outcome == "cancel":
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        else:
            session.release.set()
            if "error" in arguments:
                with pytest.raises(type(arguments["error"])):
                    await running
            else:
                assert (await running).isError is (outcome == "tool_error")
        assert not session.closed.is_set(), "nonfatal call exits must retain the session"
        assert not pool._active_calls
        await pool.get_session("server", "replacement", {})
        assert session.closed.is_set()
    finally:
        session.release.set()
        await asyncio.gather(running, return_exceptions=True)
        await pool.close_all()


@pytest.mark.asyncio
async def test_shared_session_stays_busy_until_last_call_exits(controlled_pool):
    pool = controlled_pool
    pool.MAX_SESSIONS = 1
    session = await pool.get_session("server", "active", {})
    starts = [asyncio.Event(), asyncio.Event()]
    releases = [asyncio.Event(), asyncio.Event()]
    calls = [asyncio.create_task(call(session, pool, "active", arguments={"started": starts[i], "release": releases[i]})) for i in range(2)]
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in starts)), 1)
        calls[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await calls[0]
        with pytest.raises(RuntimeError, match="capacity"):
            await pool.get_session("server", "replacement", {})
        assert not session.closed.is_set()
        releases[1].set()
        assert (await asyncio.wait_for(calls[1], 1)).content[0].text == "finished"
        await pool.get_session("server", "replacement", {})
        assert session.closed.is_set()
        assert not pool._active_calls
    finally:
        for event in releases:
            event.set()
        await asyncio.gather(*calls, return_exceptions=True)
        await pool.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_idle", [False, True])
async def test_promotion_rechecks_busy_sessions_after_initialization(controlled_pool, with_idle):
    pool = controlled_pool
    pool.MAX_SESSIONS = 2 if with_idle else 1
    initialized = asyncio.Event()
    initialize_gate = asyncio.Event()
    rejected_closed = asyncio.Event()
    pending = asyncio.create_task(pool.get_session("server", "pending", {"initialize_started": initialized, "initialize_gate": initialize_gate, "closed": rejected_closed}))
    running = None
    joiner = None
    try:
        await asyncio.wait_for(initialized.wait(), 1)
        active = await pool.get_session("server", "active", {})
        running = asyncio.create_task(call(active, pool, "active"))
        await asyncio.wait_for(active.started.wait(), 1)
        idle = await pool.get_session("server", "idle", {}) if with_idle else None
        # Join the already-admitted creation even though the registry is now full.
        joined = asyncio.Event()

        async def join():
            joined.set()
            return await pool.get_session("server", "pending", {})

        joiner = asyncio.create_task(join())
        await asyncio.wait_for(joined.wait(), 1)
        initialize_gate.set()
        if with_idle:
            replacement, shared = await asyncio.wait_for(asyncio.gather(pending, joiner), 1)
            assert replacement is shared
            await asyncio.wait_for(idle.closed.wait(), 1)
        else:
            outcomes = await asyncio.wait_for(asyncio.gather(pending, joiner, return_exceptions=True), 1)
            assert all(isinstance(error, RuntimeError) and "capacity" in str(error) for error in outcomes)
            await asyncio.wait_for(rejected_closed.wait(), 1)
        assert not active.closed.is_set()
        assert not pool._inflight
        assert len(pool._entries) == pool.MAX_SESSIONS
        active.release.set()
        assert (await asyncio.wait_for(running, 1)).content[0].text == "finished"
    finally:
        initialize_gate.set()
        if running is not None:
            active.release.set()
        await asyncio.gather(pending, *([joiner] if joiner is not None else []), *([running] if running is not None else []), return_exceptions=True)
        await pool.close_all()


@pytest.mark.asyncio
async def test_old_call_exit_cannot_unpin_replacement_owner(controlled_pool):
    pool = controlled_pool
    pool.MAX_SESSIONS = 1
    old = await pool.get_session("server", "active", {})
    old_call = asyncio.create_task(call(old, pool, "active"))
    new_call = None
    try:
        await asyncio.wait_for(old.started.wait(), 1)
        await pool.close_scope("active")
        new = await pool.get_session("server", "active", {})
        new_call = asyncio.create_task(call(new, pool, "active"))
        await asyncio.wait_for(new.started.wait(), 1)
        old.release.set()
        with pytest.raises(McpError, match="Connection closed"):
            await asyncio.wait_for(old_call, 1)
        with pytest.raises(RuntimeError, match="capacity"):
            await pool.get_session("server", "replacement", {})
        assert not new.closed.is_set()
        new.release.set()
        assert (await asyncio.wait_for(new_call, 1)).content[0].text == "finished"
        assert not pool._active_calls
        await pool.get_session("server", "replacement", {})
        assert new.closed.is_set()
    finally:
        old.release.set()
        if new_call is not None:
            new.release.set()
        await asyncio.gather(old_call, *([new_call] if new_call is not None else []), return_exceptions=True)
        await pool.close_all()


@pytest.mark.asyncio
async def test_busy_personal_session_survives_deployment_capacity_pressure(controlled_pool):
    pool = controlled_pool
    pool.MAX_SESSIONS = 2
    personal = await pool.get_session("server", "shared", {}, domain="personal")
    deployment = await pool.get_session("server", "shared", {})
    running = asyncio.create_task(call(personal, pool, "shared", domain="personal"))
    try:
        await asyncio.wait_for(personal.started.wait(), 1)
        await pool.get_session("server", "replacement", {})
        assert not personal.closed.is_set()
        assert deployment.closed.is_set()
        personal.release.set()
        assert (await asyncio.wait_for(running, 1)).content[0].text == "finished"
    finally:
        personal.release.set()
        await asyncio.gather(running, return_exceptions=True)
        await pool.close_all()


@pytest.mark.asyncio
async def test_rebinding_still_retires_active_calls(controlled_pool):
    pool = controlled_pool
    old_binding = pool.ensure_binding("server", "original-fingerprint")
    session = await pool.get_session("server", "active", {}, binding=old_binding)
    running = asyncio.create_task(call(session, pool, "active"))
    try:
        await asyncio.wait_for(session.started.wait(), 1)
        pool.reconcile_bindings({"server": "new-fingerprint"}, ())
        await asyncio.wait_for(session.closed.wait(), 1)
        session.release.set()
        with pytest.raises(McpError, match="Connection closed"):
            await asyncio.wait_for(running, 1)
        assert not pool._active_calls
        assert not pool._entries
    finally:
        session.release.set()
        await asyncio.gather(running, return_exceptions=True)
        await pool.close_all()


@pytest.mark.asyncio
async def test_detached_session_cannot_start_an_unprotected_call(controlled_pool):
    pool = controlled_pool
    pool.MAX_SESSIONS = 1
    old = await pool.get_session("server", "old", {})
    try:
        await pool.get_session("server", "replacement", {})
        with pytest.raises(RuntimeError, match="no longer pooled"):
            await call(old, pool, "old")
        assert not old.started.is_set()
        assert not pool._active_calls
    finally:
        await pool.close_all()

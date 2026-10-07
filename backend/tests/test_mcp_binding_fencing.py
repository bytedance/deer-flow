"""Regression tests for stdio MCP binding ownership/fencing."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp import session_pool as session_pool_module
from deerflow.mcp.session_pool import (
    MCPSessionPool,
    StaleMCPBindingError,
    normalized_connection_fingerprint,
)

_CONNECTION = {"transport": "stdio", "command": "x", "args": []}


class _GatedSessionCm:
    def __init__(self, gate: asyncio.Event | None = None) -> None:
        self.gate = gate
        self.initialize_started = asyncio.Event()
        self.closed = False
        self.enter_task = None
        self.exit_task = None
        self.session = MagicMock()
        self.session.initialize = self.initialize

    async def __aenter__(self):
        self.enter_task = asyncio.current_task()
        return self.session

    async def initialize(self):
        self.initialize_started.set()
        if self.gate is not None:
            await self.gate.wait()

    async def __aexit__(self, *_args):
        self.exit_task = asyncio.current_task()
        self.closed = True


def test_binding_digest_tracks_stdio_identity_without_leaking_env_value():
    a = normalized_connection_fingerprint({**_CONNECTION, "cwd": "/a", "env": {"TOKEN": "secret-a"}})
    b = normalized_connection_fingerprint({**_CONNECTION, "cwd": "/a", "env": {"TOKEN": "secret-b"}})
    c = normalized_connection_fingerprint({**_CONNECTION, "cwd": "/b", "env": {"TOKEN": "secret-a"}})

    assert a != b != c
    assert "secret-a" not in a
    assert len(a) == 64


def test_same_binding_is_idempotent_and_same_name_domains_are_independent():
    pool = MCPSessionPool()
    deployment = pool.ensure_binding("A", "fp-a", domain="deployment")

    assert pool.ensure_binding("A", "fp-a", domain="deployment") is deployment
    personal = pool.ensure_binding("A", "fp-a", domain="personal")
    assert personal is not deployment


@pytest.mark.asyncio
async def test_remove_readd_same_fingerprint_never_reauthorizes_old_binding():
    pool = MCPSessionPool()
    old = pool.ensure_binding("A", "same-fp")

    pool.reconcile_bindings({}, {"A"})
    tombstone = pool._bindings[("deployment", "A")]
    pool.reconcile_bindings({"A": "same-fp"}, ())
    current = pool._bindings[("deployment", "A")]

    assert tombstone.fingerprint is None
    assert current is not old
    assert current.epoch > tombstone.epoch > old.epoch

    with pytest.raises(StaleMCPBindingError):
        await pool.get_session("A", "u:t", _CONNECTION, binding=old)


@pytest.mark.asyncio
async def test_reconcile_detaches_only_changed_server_and_preserves_registry_key_shape():
    pool = MCPSessionPool()
    loop = asyncio.get_running_loop()
    a = pool.ensure_binding("A", "a1")
    b = pool.ensure_binding("B", "b1")
    cm_a = _GatedSessionCm()
    cm_b = _GatedSessionCm()

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=[cm_a, cm_b]):
        session_a = await pool.get_session("A", "u:t", _CONNECTION, binding=a)
        session_b = await pool.get_session("B", "u:t", _CONNECTION, binding=b)

    prepared = pool.reconcile_bindings({"A": "a2", "B": "b1"}, ())
    assert [entry[0] for entry in prepared.entries] == [session_a]
    assert prepared.inflight == ()
    assert pool._entries[("B", "u:t", loop, "deployment")][0] is session_b
    assert cm_b.closed is False

    await asyncio.wait_for(prepared.entries[0][2], timeout=1)
    assert cm_a.closed is True
    assert cm_a.exit_task is cm_a.enter_task


@pytest.mark.asyncio
async def test_stale_binding_fails_before_session_creation():
    pool = MCPSessionPool()
    old = pool.ensure_binding("A", "a1")
    pool.reconcile_bindings({"A": "a2"}, ())

    with patch("langchain_mcp_adapters.sessions.create_session") as create_session:
        with pytest.raises(StaleMCPBindingError):
            await pool.get_session("A", "u:t", _CONNECTION, binding=old)

    create_session.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_fences_creator_blocked_in_initialize():
    pool = MCPSessionPool()
    old = pool.ensure_binding("A", "a1")
    gate = asyncio.Event()
    cm = _GatedSessionCm(gate)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        creator = asyncio.create_task(pool.get_session("A", "u:t", _CONNECTION, binding=old))
        await asyncio.wait_for(cm.initialize_started.wait(), 1)

        prepared = pool.reconcile_bindings({"A": "a2"}, ())
        assert len(prepared.inflight) == 1
        gate.set()

        with pytest.raises(StaleMCPBindingError):
            await asyncio.wait_for(creator, 1)

    assert not pool._entries
    assert not pool._inflight
    assert cm.closed is True
    assert cm.exit_task is cm.enter_task


@pytest.mark.asyncio
async def test_creator_and_joiner_both_observe_superseded_binding():
    pool = MCPSessionPool()
    old = pool.ensure_binding("A", "a1")
    gate = asyncio.Event()
    cm = _GatedSessionCm(gate)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        creator = asyncio.create_task(pool.get_session("A", "u:t", _CONNECTION, binding=old))
        await asyncio.wait_for(cm.initialize_started.wait(), 1)
        joiner = asyncio.create_task(pool.get_session("A", "u:t", _CONNECTION, binding=old))
        await asyncio.sleep(0)

        pool.reconcile_bindings({"A": "a2"}, ())
        gate.set()

        with pytest.raises(StaleMCPBindingError):
            await asyncio.wait_for(creator, 1)
        with pytest.raises(StaleMCPBindingError):
            await asyncio.wait_for(joiner, 1)


@pytest.mark.asyncio
async def test_reset_fences_old_pool_and_old_binding():
    pool = MCPSessionPool()
    binding = pool.ensure_binding("A", "a1")
    session_pool_module._pool = pool

    retired = session_pool_module.reset_session_pool()
    assert retired is pool

    with patch("langchain_mcp_adapters.sessions.create_session") as create_session:
        with pytest.raises(StaleMCPBindingError):
            await pool.get_session("A", "u:t", _CONNECTION, binding=binding)
    create_session.assert_not_called()


class _EmptyArgs(BaseModel):
    pass


@pytest.mark.asyncio
async def test_discovery_captures_pool_and_binding_before_first_await():
    from deerflow.mcp.tools import get_mcp_tools

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "A": {
                    "type": "stdio",
                    "command": "x",
                    "args": [],
                }
            }
        }
    )
    servers = {"A": {"transport": "stdio", "command": "x", "args": []}}
    pool = MagicMock()
    binding = SimpleNamespace(domain="deployment", server_name="A")
    order: list[str] = []

    def ensure_binding(*_args, **_kwargs):
        order.append("bind")
        return binding

    pool.ensure_binding.side_effect = ensure_binding

    async def raw_tool() -> str:
        return "ok"

    tool = StructuredTool(
        name="A_echo",
        description="echo",
        args_schema=_EmptyArgs,
        coroutine=raw_tool,
    )

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            self.callbacks = None
            self.tool_interceptors = []

        async def get_tools(self, *, server_name=None):
            assert server_name == "A"
            order.append("discover")
            return [tool]

    with (
        patch("deerflow.mcp.tools.get_session_pool", return_value=pool),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
        patch("deerflow.mcp.tools.build_mcp_tool_interceptors", return_value=[]),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient),
        patch("deerflow.mcp.tools._make_session_pool_tool", side_effect=lambda wrapped, *_args, **_kwargs: wrapped) as wrap,
    ):
        tools = await get_mcp_tools(config)

    assert order[:2] == ["bind", "discover"]
    assert tools == [tool]
    assert wrap.call_args.kwargs["pool"] is pool
    assert wrap.call_args.kwargs["binding"] is binding


@pytest.mark.asyncio
async def test_durable_stdio_call_binds_base_connection_before_workspace_augmentation():
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "type": "stdio",
                    "command": "report-mcp",
                    "args": [],
                }
            }
        }
    )
    result = SimpleNamespace(structuredContent={"status": "running"}, isError=False)
    session = SimpleNamespace(call_tool=AsyncMock(return_value=result))
    pool = MCPSessionPool()
    pool.get_session = AsyncMock(return_value=session)

    prepared = {
        "transport": "stdio",
        "command": "report-mcp",
        "args": [],
        "cwd": "/workspace",
        "env": {"TMPDIR": "/workspace/tmp"},
    }

    caller = McpTaskToolCaller(config)
    with (
        patch("deerflow.mcp.task_tool_caller.get_session_pool", return_value=pool),
        patch("deerflow.mcp.task_tool_caller._prepare_stdio_connection", return_value=prepared),
    ):
        actual = await caller.call_tool(
            server_name="reports",
            tool_name="status_report",
            arguments={"task_id": "1"},
            user_id="u1",
            thread_id="t1",
        )

    assert actual is result
    binding = pool._bindings[("deployment", "reports")]
    assert binding.fingerprint == normalized_connection_fingerprint({"transport": "stdio", "command": "report-mcp", "args": []})
    pool.get_session.assert_awaited_once_with(
        "reports",
        "u1:t1",
        prepared,
        binding=binding,
    )


@pytest.mark.asyncio
async def test_joiner_rechecks_binding_after_ready_resolves():
    """A joiner cannot return a session superseded after ready resolved.

    The joiner path must be pinned to the post-await fence: the test waits until
    the joiner has passed admission and is parked inside ``shield(ready)``, lets
    the shared future resolve, and only then supersedes the binding. A joiner
    that merely raced into admission would fail for the wrong reason.
    """
    pool = MCPSessionPool()
    old = pool.ensure_binding("A", "a1")
    loop = asyncio.get_running_loop()
    key = ("A", "u:t", loop, "deployment")
    ready = loop.create_future()
    close_evt = asyncio.Event()

    async def owner_waiter():
        await close_evt.wait()

    owner = asyncio.create_task(owner_waiter())
    pool._inflight[key] = (loop, ready, owner, close_evt)

    real_shield = asyncio.shield
    joined = asyncio.Event()
    resolved = asyncio.Event()
    release = asyncio.Event()

    async def gated_shield(awaitable):
        if awaitable is not ready:
            return await real_shield(awaitable)
        # Past admission, parked on the shared future: report progress so the
        # test can sequence the supersede strictly after the result is consumed.
        joined.set()
        result = await real_shield(awaitable)
        resolved.set()
        await release.wait()
        return result

    with patch("deerflow.mcp.session_pool.asyncio.shield", new=gated_shield):
        joiner = asyncio.create_task(pool.get_session("A", "u:t", _CONNECTION, binding=old))

        # Proves the joiner cleared admission, saw the in-flight entry and
        # captured the join future instead of failing on the admission fence.
        await asyncio.wait_for(joined.wait(), 1)

        ready.set_result(MagicMock())
        # Proves shield already consumed the result while still parked, so the
        # supersede below lands before the post-await fence is evaluated.
        await asyncio.wait_for(resolved.wait(), 1)

        pool.reconcile_bindings({"A": "a2"}, ())
        release.set()

        with pytest.raises(StaleMCPBindingError):
            await asyncio.wait_for(joiner, 1)

    await asyncio.gather(owner, return_exceptions=True)

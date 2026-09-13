"""Persistent-loop regressions for concurrent sync callers (#5256)."""

import asyncio
import concurrent.futures
import sys
import threading
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.mcp.session_pool import MCPSessionPool
from deerflow.tools.sync import make_sync_tool_wrapper


@pytest.fixture
def loop_pool(monkeypatch):
    pool = MCPSessionPool()
    loops = [asyncio.new_event_loop(), asyncio.new_event_loop()]
    threads = [threading.Thread(target=loop.run_forever) for loop in loops]
    closed = []

    @asynccontextmanager
    async def create_session(connection):
        owner = asyncio.current_task()
        session = AsyncMock()
        try:
            yield session
        finally:
            assert asyncio.current_task() is owner
            closed.append(session)

    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", create_session)
    for thread in threads:
        thread.start()

    def run(index, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, loops[index]).result(timeout=5)

    try:
        yield pool, run, closed
    finally:
        run(0, pool.close_all())
        for loop in loops:
            loop.call_soon_threadsafe(loop.stop)
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()
        for loop in loops:
            loop.close()


def test_live_loops_reuse_only_their_own_sessions_and_disconnect_is_isolated(loop_pool):
    pool, run, closed = loop_pool
    first = run(0, pool.get_session("s", "u:t", {}))
    sibling = run(1, pool.get_session("s", "u:t", {}))
    assert first is not sibling
    assert not closed
    assert run(0, pool.get_session("s", "u:t", {})) is first
    assert run(1, pool.get_session("s", "u:t", {})) is sibling
    assert run(0, pool.close_session_if_current("s", "u:t", first))
    assert closed == [first]
    replacement = run(0, pool.get_session("s", "u:t", {}))
    assert replacement is not first
    assert not run(0, pool.close_session_if_current("s", "u:t", first))
    assert run(1, pool.get_session("s", "u:t", {})) is sibling
    assert run(0, pool.get_session("s", "u:t", {})) is replacement


@pytest.mark.parametrize("operation", ["scope", "server", "session", "all"])
def test_explicit_cleanup_closes_both_loops(loop_pool, operation):
    pool, run, closed = loop_pool
    sessions = [run(i, pool.get_session("s", "u:t", {})) for i in range(2)]
    other = run(1, pool.get_session("other", "u:other", {}))
    cleanup = {
        "scope": lambda: pool.close_scope("u:t"),
        "server": lambda: pool.close_server("s"),
        "session": lambda: pool.close_session("s", "u:t"),
        "all": pool.close_all,
    }[operation]
    run(0, cleanup())
    assert all(session in closed for session in sessions)
    if operation == "all":
        assert other in closed
    else:
        assert other not in closed
        assert run(1, pool.get_session("other", "u:other", {})) is other


def test_owner_completion_does_not_remove_a_replacement(loop_pool):
    pool, run, _closed = loop_pool

    async def replace():
        await pool.get_session("s", "u:t", {})
        key = ("s", "u:t", asyncio.get_running_loop())
        old_owner = pool._entries[key][2]
        await pool.close_session("s", "u:t")
        replacement = await pool.get_session("s", "u:t", {})
        pool._discard_owner(key, old_owner)
        assert await pool.get_session("s", "u:t", {}) is replacement

    run(0, replace())


@pytest.mark.parametrize("retirement", ["lru", "explicit"])
def test_abandoned_closed_loop_entry_can_be_retired(loop_pool, retirement):
    """Model the registry left by unsupported loop.close() with pending owners.

    Use a synthetic pending owner so the test itself does not leak a real task
    or transport on a closed loop. Normal owner shutdown is tested separately.
    """
    pool, run, _closed = loop_pool
    closed_loop = asyncio.new_event_loop()
    closed_loop.close()
    owner = MagicMock(spec=asyncio.Task)
    owner.done.return_value = False
    key = ("s", "u:t", closed_loop)
    pool._entries[key] = (MagicMock(), closed_loop, owner, asyncio.Event())
    pool.MAX_SESSIONS = 1
    if retirement == "explicit":
        run(0, pool.close_scope("u:t"))
        assert not pool._entries
    else:
        replacement = run(0, pool.get_session("s", "u:t", {}))
        assert key not in pool._entries
        assert len(pool._entries) == 1
        assert run(0, pool.get_session("s", "u:t", {})) is replacement
    owner.cancel.assert_not_called()


@pytest.mark.parametrize("operation", ["scope", "server", "session", "all"])
def test_cleanup_cancels_inflight_owners_on_both_loops(loop_pool, monkeypatch, operation):
    pool, run, _closed = loop_pool
    started = [threading.Event(), threading.Event()]
    exited = [threading.Event(), threading.Event()]

    @asynccontextmanager
    async def create_session(connection):
        index = connection["index"]
        owner = asyncio.current_task()

        async def initialize():
            started[index].set()
            await asyncio.Future()

        try:
            yield AsyncMock(initialize=initialize)
        finally:
            assert asyncio.current_task() is owner
            exited[index].set()

    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", create_session)

    async def start(index):
        return asyncio.create_task(pool.get_session("s", "u:t", {"index": index}))

    calls = [run(i, start(i)) for i in range(2)]
    assert all(event.wait(5) for event in started)
    cleanup = {
        "scope": lambda: pool.close_scope("u:t"),
        "server": lambda: pool.close_server("s"),
        "session": lambda: pool.close_session("s", "u:t"),
        "all": pool.close_all,
    }[operation]
    run(0, cleanup())
    assert all(event.wait(5) for event in exited)

    async def cancelled(call):
        with pytest.raises(asyncio.CancelledError):
            await call

    for i, call in enumerate(calls):
        run(i, cancelled(call))
    assert not pool._inflight and not pool._entries


def test_parallel_sync_wrappers_complete_real_stdio_calls(tmp_path):
    server = tmp_path / "echo_server.py"
    server.write_text(
        'from mcp.server.fastmcp import FastMCP\nmcp = FastMCP("echo")\n@mcp.tool()\ndef echo(text: str) -> str:\n    return text\nmcp.run(transport="stdio")\n',
        encoding="utf-8",
    )
    pool = MCPSessionPool()
    barrier = threading.Barrier(2)
    connection = {"transport": "stdio", "command": sys.executable, "args": [str(server)]}

    async def echo(text):
        await asyncio.to_thread(barrier.wait, 5)
        session = await pool.get_session("echo", "user:thread", connection)
        result = await session.call_tool("echo", {"text": text})
        return result.content[0].text

    wrapper = make_sync_tool_wrapper(echo, "echo")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(wrapper, text) for text in ("A", "B")]
            assert [future.result(timeout=30) for future in futures] == ["A", "B"]
        assert not pool._entries and not pool._inflight
    finally:
        pool.close_all_sync()

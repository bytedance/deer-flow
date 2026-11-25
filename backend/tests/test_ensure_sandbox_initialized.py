"""Tests for ensure_sandbox_initialized with fork-restored channel values."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, Mock

import pytest
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Overwrite

from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY, normalize_tool_message, tool_result_for_model
from deerflow.sandbox.exceptions import SandboxCapacityExceededError, SandboxNotFoundError
from deerflow.sandbox.lease import SANDBOX_LEASE_OWNER_CONTEXT_KEY, get_sandbox_lease_manager
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider, reset_sandbox_provider, set_sandbox_provider
from deerflow.sandbox.search import GrepMatch
from deerflow.sandbox.tools import (
    _run_sync_tool_after_async_sandbox_init,
    bash_tool,
    ensure_sandbox_initialized,
    ensure_sandbox_initialized_async,
    glob_tool,
    grep_tool,
    ls_tool,
    read_file_tool,
    str_replace_tool,
    write_file_tool,
)


class _StubSandbox(Sandbox):
    def __init__(self, sandbox_id: str) -> None:
        super().__init__(sandbox_id)
        self.released_scopes: list[str] = []

    def execute_command(self, command: str, env: dict | None = None, timeout: float | None = None) -> str:
        del env, timeout
        return "OK"

    def read_file(self, path: str) -> str:
        return "content"

    def download_file(self, path: str) -> bytes:
        return b"content"

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        return ["/mnt/user-data/workspace/file.txt"]

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        return None

    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        return [], False

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        return [], False

    def update_file(self, path: str, content: bytes) -> None:
        return None

    def release_command_scope(self, scope_id: str) -> None:
        self.released_scopes.append(scope_id)


class _RecordingProvider(SandboxProvider):
    def __init__(self) -> None:
        self.sandbox = _StubSandbox("stub")
        self.released: list[str] = []

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        raise AssertionError("state already carries a sandbox; acquire must not run")

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        raise AssertionError("state already carries a sandbox; acquire must not run")

    def get(self, sandbox_id: str) -> Sandbox | None:
        if sandbox_id == "parent-sandbox":
            return self.sandbox
        return None

    def get_scoped(self, sandbox_id: str, *, thread_id: str, user_id: str) -> Sandbox | None:
        del thread_id, user_id
        return self.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        self.released.append(sandbox_id)


class _FallthroughProvider(SandboxProvider):
    """Provider whose parent id has expired, forcing a fresh acquire."""

    def __init__(self) -> None:
        self.sandbox = _StubSandbox("fresh")
        self.acquired: list[str | None] = []
        self.released: list[str] = []

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        self.acquired.append(thread_id)
        return "fresh-sandbox"

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        self.acquired.append(thread_id)
        return "fresh-sandbox"

    def get(self, sandbox_id: str) -> Sandbox | None:
        if sandbox_id == "fresh-sandbox":
            return self.sandbox
        return None

    def release(self, sandbox_id: str) -> None:
        self.released.append(sandbox_id)


class _PostAcquireLookupFailureProvider(SandboxProvider):
    """Provider that binds an id but cannot return its active client."""

    def __init__(self) -> None:
        self.released: list[str] = []

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        return "lost-after-acquire"

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        return "lost-after-acquire"

    def get(self, sandbox_id: str) -> Sandbox | None:
        return None

    def release(self, sandbox_id: str) -> None:
        self.released.append(sandbox_id)


def _make_runtime(state: dict) -> ToolRuntime:
    return ToolRuntime(
        state=state,
        context={},
        config={"configurable": {}},
        stream_writer=lambda _: None,
        tools=[],
        tool_call_id="call-1",
        store=None,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize(
    ("tool", "args", "reason", "explanation"),
    [
        (bash_tool, {"command": "echo test"}, "capacity", "sandbox pool is busy"),
        (ls_tool, {"path": "/mnt/user-data/workspace"}, "capacity", "sandbox pool is busy"),
        (glob_tool, {"path": "/mnt/user-data/workspace", "pattern": "*.txt"}, "capacity", "sandbox pool is busy"),
        (grep_tool, {"path": "/mnt/user-data/workspace", "pattern": "test"}, "capacity", "sandbox pool is busy"),
        (read_file_tool, {"path": "/mnt/user-data/workspace/note.txt"}, "capacity", "sandbox pool is busy"),
        (str_replace_tool, {"path": "/mnt/user-data/workspace/note.txt", "old_str": "a", "new_str": "b"}, "capacity", "sandbox pool is busy"),
        (write_file_tool, {"path": "/mnt/user-data/workspace/note.txt", "content": "note"}, "shutdown", "provider is shutting down"),
        (ls_tool, {"path": "/mnt/user-data/workspace"}, "capacity_backend", "sandbox capacity service is unavailable"),
        (ls_tool, {"path": "/mnt/user-data/workspace"}, "capacity_initializing", "sandbox capacity service is initializing"),
        (ls_tool, {"path": "/mnt/user-data/workspace"}, "other", "capacity is temporarily unavailable"),
    ],
    ids=["bash", "ls", "glob", "grep", "read-file", "str-replace", "write-file", "backend-unavailable", "initializing", "other-reason"],
)
async def test_capacity_rejection_reaches_the_model(tool, args, reason, explanation, asynchronous, monkeypatch):
    error = SandboxCapacityExceededError(replicas=2, retry_after_seconds=17, reason=reason)
    provider = _FallthroughProvider()
    acquire = AsyncMock(side_effect=error) if asynchronous else Mock(side_effect=error)
    monkeypatch.setattr(provider, "acquire_async" if asynchronous else "acquire", acquire)
    graph = StateGraph(MessagesState).add_node("tools", ToolNode([tool])).add_edge(START, "tools").compile()
    inputs = {"messages": [AIMessage(content="", tool_calls=[{"name": tool.name, "args": args, "id": "call-1"}])]}
    config = {"configurable": {"thread_id": "capacity-test"}}

    set_sandbox_provider(provider)
    try:
        result = await graph.ainvoke(inputs, config) if asynchronous else await asyncio.to_thread(graph.invoke, inputs, config)
    finally:
        reset_sandbox_provider()

    acquire.assert_called_once()
    if asynchronous:
        acquire.assert_awaited_once()
    message = result["messages"][-1]
    assert isinstance(message, ToolMessage)
    assert (message.tool_call_id, message.name, message.status) == ("call-1", tool.name, "error")
    meta = normalize_tool_message(message).additional_kwargs[TOOL_META_KEY]
    assert meta["error_type"] == "capacity"
    assert meta["recommended_next_action"] == "retry_later"
    assert meta["retry_after_seconds"] == 17
    assert meta["recoverable_by_model"] is True
    model_message = tool_result_for_model(message)
    assert explanation in model_message.content
    assert "17 seconds" in model_message.content
    assert "tell the user" in model_message.content


def test_post_acquire_lookup_failure_unwinds_sync_execution_lease() -> None:
    provider = _PostAcquireLookupFailureProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({})
        runtime.context.update(
            {
                SANDBOX_LEASE_OWNER_CONTEXT_KEY: "sync-owner",
                "thread_id": "thread-1",
                "user_id": "user-1",
            }
        )
        manager = get_sandbox_lease_manager(provider)

        with pytest.raises(SandboxNotFoundError, match="Sandbox not found after acquisition"):
            ensure_sandbox_initialized(runtime)

        assert manager.binding_for("sync-owner") is None
        assert provider.released == ["lost-after-acquire"]
    finally:
        reset_sandbox_provider()


@pytest.mark.anyio
async def test_post_acquire_lookup_failure_unwinds_async_execution_lease() -> None:
    provider = _PostAcquireLookupFailureProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({})
        runtime.context.update(
            {
                SANDBOX_LEASE_OWNER_CONTEXT_KEY: "async-owner",
                "thread_id": "thread-1",
                "user_id": "user-1",
            }
        )
        manager = get_sandbox_lease_manager(provider)

        with pytest.raises(SandboxNotFoundError, match="Sandbox not found after acquisition"):
            await ensure_sandbox_initialized_async(runtime)

        assert manager.binding_for("async-owner") is None
        assert provider.released == ["lost-after-acquire"]
    finally:
        reset_sandbox_provider()


def test_ensure_sandbox_initialized_unwraps_overwrite_state() -> None:
    """Fork-restored state must not crash on the Overwrite wrapper."""
    provider = _RecordingProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": Overwrite({"sandbox_id": "parent-sandbox"})})
        runtime.context["thread_id"] = "thread-1"
        sandbox = ensure_sandbox_initialized(runtime)
    finally:
        reset_sandbox_provider()

    assert sandbox is provider.sandbox
    assert runtime.context["sandbox_id"] == "parent-sandbox"
    # The reuse path must not take ownership: the wrapped state is left
    # untouched, so after_agent still sees fork_restored and skips release.
    assert isinstance(runtime.state["sandbox"], Overwrite)


@pytest.mark.anyio
async def test_ensure_sandbox_initialized_async_unwraps_overwrite_state() -> None:
    provider = _RecordingProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": Overwrite({"sandbox_id": "parent-sandbox"})})
        runtime.context["thread_id"] = "thread-1"
        sandbox = await ensure_sandbox_initialized_async(runtime)
    finally:
        reset_sandbox_provider()

    assert sandbox is provider.sandbox
    assert runtime.context["sandbox_id"] == "parent-sandbox"


def test_fork_restored_owner_holds_non_releasing_scope_lease() -> None:
    provider = _RecordingProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": Overwrite({"sandbox_id": "parent-sandbox"})})
        runtime.context.update(
            {
                SANDBOX_LEASE_OWNER_CONTEXT_KEY: "fork-child",
                "thread_id": "thread-1",
                "user_id": "user-1",
            }
        )

        sandbox = ensure_sandbox_initialized(runtime)
        manager = get_sandbox_lease_manager(provider)

        assert sandbox is provider.sandbox
        assert manager.binding_for("fork-child") == "parent-sandbox"
        assert isinstance(runtime.state["sandbox"], Overwrite)

        manager.release("fork-child")

        assert provider.sandbox.released_scopes == ["fork-child"]
        assert provider.released == []
    finally:
        reset_sandbox_provider()


@pytest.mark.anyio
async def test_async_fork_restored_owner_holds_non_releasing_scope_lease() -> None:
    provider = _RecordingProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": Overwrite({"sandbox_id": "parent-sandbox"})})
        runtime.context.update(
            {
                SANDBOX_LEASE_OWNER_CONTEXT_KEY: "fork-child",
                "thread_id": "thread-1",
                "user_id": "user-1",
            }
        )

        sandbox = await ensure_sandbox_initialized_async(runtime)
        manager = get_sandbox_lease_manager(provider)

        assert sandbox is provider.sandbox
        assert manager.binding_for("fork-child") == "parent-sandbox"
        assert isinstance(runtime.state["sandbox"], Overwrite)

        await manager.release_async("fork-child")

        assert provider.sandbox.released_scopes == ["fork-child"]
        assert provider.released == []
    finally:
        reset_sandbox_provider()


def test_ensure_sandbox_initialized_plain_state_unchanged() -> None:
    provider = _RecordingProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": {"sandbox_id": "parent-sandbox"}})
        runtime.context["thread_id"] = "thread-1"
        sandbox = ensure_sandbox_initialized(runtime)
    finally:
        reset_sandbox_provider()

    assert sandbox is provider.sandbox
    assert runtime.context["sandbox_id"] == "parent-sandbox"


def test_ensure_sandbox_initialized_acquires_fresh_when_parent_missing() -> None:
    """Acquire fall-through: the fork-restored id is gone from the provider,
    so a fresh sandbox is acquired and the stale wrapped state is replaced
    by the freshly acquired plain dict."""
    provider = _FallthroughProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": Overwrite({"sandbox_id": "parent-sandbox"})})
        runtime.context["thread_id"] = "t-1"
        sandbox = ensure_sandbox_initialized(runtime)
    finally:
        reset_sandbox_provider()

    assert provider.acquired == ["t-1"]
    assert sandbox is provider.sandbox
    assert runtime.state["sandbox"] == {"sandbox_id": "fresh-sandbox"}
    assert runtime.context["sandbox_id"] == "fresh-sandbox"


def test_fork_restored_owner_normally_releases_fresh_replacement() -> None:
    provider = _FallthroughProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": Overwrite({"sandbox_id": "parent-sandbox"})})
        runtime.context.update(
            {
                SANDBOX_LEASE_OWNER_CONTEXT_KEY: "fork-child",
                "thread_id": "thread-1",
                "user_id": "user-1",
            }
        )

        sandbox = ensure_sandbox_initialized(runtime)
        manager = get_sandbox_lease_manager(provider)

        assert sandbox is provider.sandbox
        assert manager.binding_for("fork-child") == "fresh-sandbox"
        manager.release("fork-child")

        assert provider.sandbox.released_scopes == ["fork-child"]
        assert provider.released == ["fresh-sandbox"]
    finally:
        reset_sandbox_provider()


@pytest.mark.anyio
async def test_async_fork_restored_owner_normally_releases_fresh_replacement() -> None:
    provider = _FallthroughProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": Overwrite({"sandbox_id": "parent-sandbox"})})
        runtime.context.update(
            {
                SANDBOX_LEASE_OWNER_CONTEXT_KEY: "fork-child",
                "thread_id": "thread-1",
                "user_id": "user-1",
            }
        )

        sandbox = await ensure_sandbox_initialized_async(runtime)
        manager = get_sandbox_lease_manager(provider)

        assert sandbox is provider.sandbox
        assert manager.binding_for("fork-child") == "fresh-sandbox"
        await manager.release_async("fork-child")

        assert provider.sandbox.released_scopes == ["fork-child"]
        assert provider.released == ["fresh-sandbox"]
    finally:
        reset_sandbox_provider()


@pytest.mark.anyio
async def test_ensure_sandbox_initialized_async_plain_state_unchanged() -> None:
    provider = _RecordingProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": {"sandbox_id": "parent-sandbox"}})
        runtime.context["thread_id"] = "thread-1"
        sandbox = await ensure_sandbox_initialized_async(runtime)
    finally:
        reset_sandbox_provider()

    assert sandbox is provider.sandbox
    assert runtime.context["sandbox_id"] == "parent-sandbox"


def test_reuse_with_config_only_thread_id_binds_execution_owner() -> None:
    provider = _RecordingProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": {"sandbox_id": "parent-sandbox"}})
        runtime.context[SANDBOX_LEASE_OWNER_CONTEXT_KEY] = "config-owner"
        runtime.config["configurable"]["thread_id"] = "thread-from-config"

        sandbox = ensure_sandbox_initialized(runtime)

        assert sandbox is provider.sandbox
        assert get_sandbox_lease_manager(provider).binding_for("config-owner") == "parent-sandbox"
    finally:
        reset_sandbox_provider()


@pytest.mark.anyio
async def test_async_reuse_with_config_only_thread_id_binds_execution_owner() -> None:
    provider = _RecordingProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": {"sandbox_id": "parent-sandbox"}})
        runtime.context[SANDBOX_LEASE_OWNER_CONTEXT_KEY] = "config-owner"
        runtime.config["configurable"]["thread_id"] = "thread-from-config"

        sandbox = await ensure_sandbox_initialized_async(runtime)

        assert sandbox is provider.sandbox
        assert get_sandbox_lease_manager(provider).binding_for("config-owner") == "parent-sandbox"
    finally:
        reset_sandbox_provider()


def test_reuse_replaces_stale_checkpoint_and_owner_binding() -> None:
    provider = _FallthroughProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": {"sandbox_id": "parent-sandbox"}})
        runtime.context[SANDBOX_LEASE_OWNER_CONTEXT_KEY] = "stale-owner"
        runtime.context["thread_id"] = "thread-1"
        runtime.context["user_id"] = "user-1"
        manager = get_sandbox_lease_manager(provider)
        manager.retain(
            "stale-owner",
            "parent-sandbox",
            thread_id="thread-1",
            user_id="user-1",
        )

        sandbox = ensure_sandbox_initialized(runtime)

        assert sandbox is provider.sandbox
        assert runtime.state["sandbox"] == {"sandbox_id": "fresh-sandbox"}
        assert runtime.context["sandbox_id"] == "fresh-sandbox"
        assert manager.binding_for("stale-owner") == "fresh-sandbox"
        assert provider.acquired == ["thread-1"]
    finally:
        reset_sandbox_provider()


@pytest.mark.anyio
async def test_async_reuse_replaces_stale_checkpoint_and_owner_binding() -> None:
    provider = _FallthroughProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": {"sandbox_id": "parent-sandbox"}})
        runtime.context[SANDBOX_LEASE_OWNER_CONTEXT_KEY] = "stale-owner"
        runtime.context["thread_id"] = "thread-1"
        runtime.context["user_id"] = "user-1"
        manager = get_sandbox_lease_manager(provider)
        manager.retain(
            "stale-owner",
            "parent-sandbox",
            thread_id="thread-1",
            user_id="user-1",
        )

        sandbox = await ensure_sandbox_initialized_async(runtime)

        assert sandbox is provider.sandbox
        assert runtime.state["sandbox"] == {"sandbox_id": "fresh-sandbox"}
        assert runtime.context["sandbox_id"] == "fresh-sandbox"
        assert manager.binding_for("stale-owner") == "fresh-sandbox"
        assert provider.acquired == ["thread-1"]
    finally:
        reset_sandbox_provider()


@pytest.mark.anyio
async def test_ensure_sandbox_initialized_async_acquires_fresh_when_parent_missing() -> None:
    """Same fall-through as the sync path: the fork-restored id is gone from
    the provider, so a fresh sandbox is acquired and the stale wrapped state
    is replaced by the freshly acquired plain dict."""
    provider = _FallthroughProvider()
    set_sandbox_provider(provider)
    try:
        runtime = _make_runtime({"sandbox": Overwrite({"sandbox_id": "parent-sandbox"})})
        runtime.context["thread_id"] = "t-1"
        sandbox = await ensure_sandbox_initialized_async(runtime)
    finally:
        reset_sandbox_provider()

    assert provider.acquired == ["t-1"]
    assert sandbox is provider.sandbox
    assert runtime.state["sandbox"] == {"sandbox_id": "fresh-sandbox"}
    assert runtime.context["sandbox_id"] == "fresh-sandbox"


@pytest.mark.anyio
async def test_cancelled_async_tool_drains_worker_before_execution_lease_cleanup(monkeypatch) -> None:
    """Cancellation must not let a late sync body re-admit a released owner."""
    provider = _FallthroughProvider()
    set_sandbox_provider(provider)
    worker_started = threading.Event()
    allow_worker = threading.Event()
    worker_finished = threading.Event()
    try:
        runtime = _make_runtime({"sandbox": {"sandbox_id": "fresh-sandbox"}})
        runtime.context.update(
            {
                SANDBOX_LEASE_OWNER_CONTEXT_KEY: "cancelled-child",
                "thread_id": "thread-1",
                "user_id": "user-1",
            }
        )
        manager = get_sandbox_lease_manager(provider)
        await manager.acquire_async("cancelled-child", "thread-1", user_id="user-1")
        await manager.acquire_async("parallel-sibling", "thread-1", user_id="user-1")

        async def _allow_sandbox(*, context, app_config):
            del context, app_config

        async def _safe_config():
            return None

        monkeypatch.setattr("deerflow.sandbox.tools.authorize_sandbox_execution_async", _allow_sandbox)
        monkeypatch.setattr("deerflow.sandbox.tools.safe_app_config_async", _safe_config)

        def _blocking_tool(inner_runtime: ToolRuntime) -> str:
            worker_started.set()
            assert allow_worker.wait(timeout=2)
            try:
                sandbox = ensure_sandbox_initialized(inner_runtime)
                return sandbox.execute_command("late command")
            finally:
                worker_finished.set()

        async def _run_then_cleanup() -> str:
            try:
                return await _run_sync_tool_after_async_sandbox_init(_blocking_tool, runtime)
            finally:
                await manager.release_async("cancelled-child")

        execution = asyncio.create_task(_run_then_cleanup())
        assert await asyncio.to_thread(worker_started.wait, 1)

        for _ in range(3):
            execution.cancel()
            await asyncio.sleep(0)

        assert not execution.done()
        assert manager.binding_for("cancelled-child") == "fresh-sandbox"
        assert provider.released == []

        allow_worker.set()
        with pytest.raises(asyncio.CancelledError):
            await execution

        assert worker_finished.is_set()
        assert manager.binding_for("cancelled-child") is None
        assert manager.binding_for("parallel-sibling") == "fresh-sandbox"
        assert provider.released == []

        await manager.release_async("parallel-sibling")
        assert provider.released == ["fresh-sandbox"]
    finally:
        allow_worker.set()
        await asyncio.to_thread(worker_finished.wait, 2)
        reset_sandbox_provider()

"""Lifecycle regressions for optional sandbox speculation."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from deerflow.sandbox import prewarm
from deerflow.sandbox.exceptions import SandboxAuthorizationError
from deerflow.sandbox.lease import (
    SANDBOX_PREWARM_CLEANUP_CONTEXT_KEY,
    ensure_sandbox_lease_owner,
    get_sandbox_lease_manager,
    register_sandbox_prewarm_cleanup,
    release_sandbox_execution_lease_async,
    sandbox_prewarm_cleanup_registered,
)
from deerflow.sandbox.sandbox_provider import SandboxProvider, reset_sandbox_provider, set_sandbox_provider
from deerflow.sandbox.tools import ensure_sandbox_initialized_async


class Provider(SandboxProvider):
    def __init__(self):
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.finish.set()
        self.calls = []
        self.released = []
        self.clients = {}
        self.fail_once = False

    def acquire(self, thread_id=None, *, user_id=None):
        raise AssertionError("must use async provider hook")

    async def acquire_async(self, thread_id=None, *, user_id=None):
        self.calls.append((user_id, thread_id))
        self.started.set()
        await self.finish.wait()
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("prewarm failed")
        sid = f"{user_id}/{thread_id}"
        self.clients[sid] = SimpleNamespace(id=sid, release_command_scope=lambda _: None)
        return sid

    def get(self, sandbox_id):
        return self.clients.get(sandbox_id)

    def get_scoped(self, sandbox_id, *, thread_id, user_id):
        return self.get(sandbox_id) if sandbox_id == f"{user_id}/{thread_id}" else None

    def release(self, sandbox_id):
        self.released.append(sandbox_id)
        self.clients.pop(sandbox_id, None)

    def reset(self):
        for sandbox_id in list(self.clients):
            self.release(sandbox_id)


@pytest.fixture
def setup(monkeypatch):
    provider = Provider()
    config = SimpleNamespace(sandbox=SimpleNamespace(prewarm=True, prewarm_max_concurrent=1, use="deerflow.community.aio_sandbox:AioSandboxProvider"))
    monkeypatch.setattr(prewarm, "get_app_config", lambda: config)
    set_sandbox_provider(provider)
    yield provider, config
    reset_sandbox_provider()


def runtime(user="alice", thread="thread"):
    context = {"user_id": user, "thread_id": thread}
    ensure_sandbox_lease_owner(context)
    register_sandbox_prewarm_cleanup(context)
    return SimpleNamespace(context=context, state={})


def start(rt):
    prewarm.start_sandbox_prewarm({"messages": [HumanMessage(content="```sh\npytest tests\n```")]}, rt)
    return rt.context["__deerflow_sandbox_prewarm"]


@pytest.mark.parametrize("text", ["https://example.com/path/file.py", "https://example.com", "Python is useful", "git is a version control tool", "Please compare read/write behavior", "API/TUI", "Error: why is this phrasing confusing?"])
def test_non_execution_text_does_not_speculate(text):
    assert not prewarm.should_prewarm_sandbox({"messages": [HumanMessage(content=text)]})


@pytest.mark.anyio
async def test_denied_prewarm_never_acquires(setup, monkeypatch, caplog):
    provider, _ = setup

    async def deny(**kwargs):
        raise SandboxAuthorizationError()

    monkeypatch.setattr(prewarm, "authorize_sandbox_execution_async", deny, raising=False)
    rt = runtime()
    with caplog.at_level(logging.DEBUG, logger=prewarm.__name__):
        handle = start(rt)
        await handle.task
    await release_sandbox_execution_lease_async(rt.context)
    assert provider.calls == []
    records = [record for record in caplog.records if record.name == prewarm.__name__]
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG
    assert records[0].exc_info is None


@pytest.mark.anyio
async def test_unexpected_prewarm_failure_retains_diagnostic_traceback(setup, caplog):
    provider, _ = setup
    provider.fail_once = True
    rt = runtime()
    with caplog.at_level(logging.INFO, logger=prewarm.__name__):
        handle = start(rt)
        await handle.task
    await release_sandbox_execution_lease_async(rt.context)

    records = [record for record in caplog.records if record.name == prewarm.__name__]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert records[0].exc_info[0] is RuntimeError
    assert not prewarm._permits


@pytest.mark.anyio
async def test_unused_ready_prewarm_is_owned_and_outer_cleanup_releases(setup):
    provider, _ = setup
    rt = runtime()
    handle = start(rt)
    await handle.task
    owner = rt.context["sandbox_lease_owner_id"]
    assert get_sandbox_lease_manager(provider).binding_for(owner) == "alice/thread"
    assert "sandbox_id" not in rt.context
    await release_sandbox_execution_lease_async(rt.context)
    await release_sandbox_execution_lease_async(rt.context)
    assert provider.released == ["alice/thread"]
    assert get_sandbox_lease_manager(provider).binding_for(owner) is None


@pytest.mark.anyio
async def test_first_tool_claims_same_lease_after_auth_recheck(setup, monkeypatch):
    provider, _ = setup
    rt = runtime()
    handle = start(rt)
    await handle.task

    async def deny(**kwargs):
        raise SandboxAuthorizationError()

    monkeypatch.setattr("deerflow.sandbox.tools.authorize_sandbox_execution_async", deny)
    with pytest.raises(SandboxAuthorizationError):
        await ensure_sandbox_initialized_async(rt)
    assert rt.state == {}
    await release_sandbox_execution_lease_async(rt.context)
    assert provider.released == ["alice/thread"]


@pytest.mark.anyio
async def test_ready_unused_counts_against_budget(setup):
    provider, _ = setup
    first, second = runtime(), runtime("bob")
    await start(first).task
    await start(second).task
    assert provider.calls == [("alice", "thread")]
    await release_sandbox_execution_lease_async(first.context)
    third = runtime("carol")
    await start(third).task
    assert provider.calls[-1] == ("carol", "thread")
    await release_sandbox_execution_lease_async(second.context)
    await release_sandbox_execution_lease_async(third.context)


@pytest.mark.anyio
async def test_cancelled_claim_drains_late_acquire_through_repeated_cancellation(setup):
    provider, _ = setup
    provider.finish.clear()
    rt = runtime()
    handle = start(rt)
    await provider.started.wait()
    claim = asyncio.create_task(ensure_sandbox_initialized_async(rt))
    await asyncio.sleep(0)
    claim.cancel()
    with pytest.raises(asyncio.CancelledError):
        await claim
    cleanup = asyncio.create_task(release_sandbox_execution_lease_async(rt.context))
    await asyncio.sleep(0)
    cleanup.cancel()
    await asyncio.sleep(0)
    cleanup.cancel()
    await asyncio.sleep(0)
    assert not cleanup.done()
    provider.finish.set()
    with pytest.raises(asyncio.CancelledError):
        await cleanup
    assert handle.task.done()
    assert provider.released == ["alice/thread"]
    assert get_sandbox_lease_manager(provider).binding_for(rt.context["sandbox_lease_owner_id"]) is None


@pytest.mark.anyio
async def test_unused_prewarm_does_not_release_sibling_holder(setup):
    provider, _ = setup
    rt = runtime()
    await start(rt).task
    manager = get_sandbox_lease_manager(provider)
    await manager.reuse_or_acquire_async("sibling", "alice/thread", thread_id="thread", user_id="alice")
    await release_sandbox_execution_lease_async(rt.context)
    assert provider.released == []
    assert provider.get("alice/thread") is not None
    await manager.release_async("sibling")
    assert provider.released == ["alice/thread"]


@pytest.mark.anyio
async def test_tool_hit_and_failed_prewarm_fallback_keep_one_owner(setup):
    provider, _ = setup
    for failing in (False, True):
        provider.fail_once = failing
        rt = runtime(thread=f"failure-{failing}")
        handle = start(rt)
        await handle.task
        client = await ensure_sandbox_initialized_async(rt)
        assert client.id == f"alice/failure-{failing}"
        assert get_sandbox_lease_manager(provider).binding_for(rt.context["sandbox_lease_owner_id"]) == client.id
        await release_sandbox_execution_lease_async(rt.context)
    assert len(provider.calls) == 3
    assert len(provider.released) == 2


@pytest.mark.anyio
async def test_replaced_provider_is_not_claimed_or_released_by_wrong_manager(setup):
    old, _ = setup
    rt = runtime()
    handle = start(rt)
    await handle.task
    replacement = Provider()
    reset_sandbox_provider()
    set_sandbox_provider(replacement)
    # Reset owns destruction of old clients; a late claim must neither reuse
    # that detached provider nor release the new provider through its old handle.
    client = await ensure_sandbox_initialized_async(rt)
    assert client is replacement.get("alice/thread")
    assert old.released == ["alice/thread"]
    assert replacement.released == []
    await release_sandbox_execution_lease_async(rt.context)
    assert replacement.released == ["alice/thread"]


@pytest.mark.anyio
async def test_budget_pending_and_claim_releases_slot_for_another_user(setup):
    provider, _ = setup
    provider.finish.clear()
    first = runtime()
    handle = start(first)
    await provider.started.wait()
    second = runtime("bob")
    await start(second).task
    assert provider.calls == [("alice", "thread")]
    provider.finish.set()
    await ensure_sandbox_initialized_async(first)
    third = runtime("carol")
    await start(third).task
    assert provider.calls == [("alice", "thread"), ("carol", "thread")]
    for rt in (first, second, third):
        await release_sandbox_execution_lease_async(rt.context)
    assert handle.claimed


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["disabled", "other-provider", "snapshot-disabled", "existing", "fork"])
async def test_prewarm_admission_preserves_existing_modes(setup, mode):
    from langgraph.types import Overwrite

    provider, config = setup
    rt = runtime()
    state = {"messages": [HumanMessage(content="```sh\npytest\n```")]}
    if mode == "disabled":
        config.sandbox.prewarm = False
    elif mode == "other-provider":
        config.sandbox.use = "deerflow.sandbox.local:LocalSandboxProvider"
    elif mode == "snapshot-disabled":
        rt.context["app_config"] = SimpleNamespace(sandbox=SimpleNamespace(prewarm=False))
    elif mode == "existing":
        state["sandbox"] = {"sandbox_id": "existing"}
    else:
        state["sandbox"] = Overwrite({"sandbox_id": "parent"})
    prewarm.start_sandbox_prewarm(state, rt)
    handle = rt.context.get("__deerflow_sandbox_prewarm")
    if handle is not None:
        await handle.task
    await release_sandbox_execution_lease_async(rt.context)
    assert provider.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [False, True])
async def test_compiled_graph_model_outcome_cleans_unclaimed_prewarm(setup, monkeypatch, failure):
    from langchain.agents import create_agent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from deerflow.sandbox.middleware import SandboxMiddleware

    provider, _ = setup

    class Model(BaseChatModel):
        @property
        def _llm_type(self):
            return "prewarm-lifecycle-test"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise AssertionError("async model required")

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            await provider.started.wait()
            if failure:
                raise RuntimeError("model failed before tool call")
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="No execution needed"))])

    middleware = SandboxMiddleware()
    monkeypatch.setattr(middleware, "_prepare_agent_skill_projection", lambda *args, **kwargs: None)
    graph = create_agent(Model(), tools=[], middleware=[middleware])
    rt = runtime()
    try:
        if failure:
            with pytest.raises(RuntimeError, match="model failed"):
                await graph.ainvoke({"messages": [HumanMessage(content="```sh\npytest\n```")]}, context=rt.context)
        else:
            result = await graph.ainvoke({"messages": [HumanMessage(content="```sh\npytest\n```")]}, context=rt.context)
            assert result["messages"][-1].content == "No execution needed"
    finally:
        await release_sandbox_execution_lease_async(rt.context)
    assert provider.released == ["alice/thread"]
    assert get_sandbox_lease_manager(provider).binding_for(rt.context["sandbox_lease_owner_id"]) is None


@pytest.mark.anyio
@pytest.mark.parametrize("cancelled", [False, True], ids=["model-error", "cancel"])
async def test_gateway_worker_finally_cleans_prewarm_without_context_sandbox_id(setup, cancelled):
    from unittest.mock import AsyncMock

    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.worker import RunContext, run_agent

    provider, _ = setup
    manager = RunManager()
    record = await manager.create("gateway-prewarm-error")
    contexts = []
    ready = asyncio.Event()
    blocked = asyncio.Event()

    class FailingAgent:
        async def astream(self, graph_input, config=None, **kwargs):
            context = config["configurable"]["__pregel_runtime"].context
            contexts.append(context)
            ensure_sandbox_lease_owner(context)
            await start(SimpleNamespace(context=context)).task
            assert "sandbox_id" not in context
            ready.set()
            if cancelled:
                await blocked.wait()
            raise RuntimeError("failure after speculative startup")
            yield

    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    task = asyncio.create_task(run_agent(bridge, manager, record, ctx=RunContext(checkpointer=None), agent_factory=lambda **kwargs: FailingAgent(), graph_input={}, config={}))
    try:
        await asyncio.wait_for(ready.wait(), timeout=5)
        if cancelled:
            task.cancel()
        await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert len(provider.calls) == len(provider.released) == 1
    assert not prewarm._permits
    assert not sandbox_prewarm_cleanup_registered(contexts[0])


@pytest.mark.anyio
async def test_config_and_cold_provider_setup_do_not_block_event_loop(setup, monkeypatch):
    import threading

    provider, config = setup
    loop_thread = threading.get_ident()
    seen = []

    def load_config():
        assert threading.get_ident() != loop_thread
        seen.append("config")
        return config

    def load_provider():
        assert threading.get_ident() != loop_thread
        seen.append("provider")
        return provider

    monkeypatch.setattr(prewarm, "get_app_config", load_config)
    monkeypatch.setattr(prewarm, "get_initialized_sandbox_provider", lambda: None)
    monkeypatch.setattr(prewarm, "get_sandbox_provider", load_provider)
    rt = runtime()
    await start(rt).task
    await release_sandbox_execution_lease_async(rt.context)
    assert seen == ["config", "provider"]


@pytest.mark.anyio
async def test_concurrent_cleanup_waits_for_same_pending_reconciliation(setup):
    provider, _ = setup
    provider.finish.clear()
    rt = runtime()
    handle = start(rt)
    await provider.started.wait()
    first = asyncio.create_task(release_sandbox_execution_lease_async(rt.context))
    second = asyncio.create_task(release_sandbox_execution_lease_async(rt.context))
    await asyncio.sleep(0)
    assert not first.done() and not second.done()
    provider.finish.set()
    await asyncio.gather(first, second)
    assert provider.released == ["alice/thread"]
    assert handle.closed and handle.task.done()
    assert not prewarm._permits


@pytest.mark.anyio
async def test_no_second_speculation_in_same_execution_after_no_tool_turn(setup):
    provider, _ = setup
    rt = runtime()
    first = start(rt)
    await first.task
    await release_sandbox_execution_lease_async(rt.context)
    assert start(rt) is first
    assert provider.calls == [("alice", "thread")]


@pytest.mark.anyio
async def test_speculative_budget_is_shared_across_isolated_event_loops(setup):
    import threading

    provider, _ = setup
    admitted = threading.Barrier(5)
    finish = threading.Barrier(5)

    def run_user(user):
        async def run():
            rt = runtime(user)
            await start(rt).task
            await asyncio.to_thread(admitted.wait, 5)
            await asyncio.to_thread(finish.wait, 5)
            await release_sandbox_execution_lease_async(rt.context)

        asyncio.run(run())

    tasks = [asyncio.create_task(asyncio.to_thread(run_user, f"user-{i}")) for i in range(4)]
    try:
        await asyncio.to_thread(admitted.wait, 5)
        assert len(provider.calls) == 1
    finally:
        await asyncio.to_thread(finish.wait, 5)
        await asyncio.gather(*tasks)
    assert len(provider.released) == 1
    assert not prewarm._permits


@pytest.mark.anyio
async def test_repeated_cancel_during_release_keeps_budget_until_cleanup_finishes(setup, monkeypatch):
    import threading

    provider, _ = setup
    rt = runtime()
    await start(rt).task
    started, finish = threading.Event(), threading.Event()
    release = provider.release

    def blocking_release(sandbox_id):
        started.set()
        assert finish.wait(5)
        release(sandbox_id)

    monkeypatch.setattr(provider, "release", blocking_release)
    cleanup = asyncio.create_task(release_sandbox_execution_lease_async(rt.context))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        cleanup.cancel()
        await asyncio.sleep(0)
        cleanup.cancel()
        await asyncio.sleep(0)
        assert not cleanup.done()
        other = runtime("bob")
        await start(other).task
        assert provider.calls == [("alice", "thread")]
        await release_sandbox_execution_lease_async(other.context)
    finally:
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await cleanup
    assert provider.released == ["alice/thread"]
    assert not prewarm._permits


@pytest.mark.anyio
async def test_cancel_before_start_creates_no_provider_lease(setup):
    provider, _ = setup
    rt = runtime()
    handle = start(rt)
    handle.task.cancel()
    await release_sandbox_execution_lease_async(rt.context)
    assert provider.calls == []
    assert not prewarm._permits


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["disabled", "non-aio", "budget-full"])
async def test_cancelled_skipped_prewarm_cleanup_still_releases_actual_tool_lease(setup, monkeypatch, mode):
    provider, config = setup
    blocker = None
    if mode == "disabled":
        config.sandbox.prewarm = False
    elif mode == "non-aio":
        config.sandbox.use = "deerflow.sandbox.local:LocalSandboxProvider"
    else:
        blocker = runtime("slot-owner")
        await start(blocker).task
    rt = runtime()
    handle = start(rt)
    assert await handle.task is None
    await ensure_sandbox_initialized_async(rt)
    owner = rt.context["sandbox_lease_owner_id"]
    manager = get_sandbox_lease_manager(provider)
    assert manager.binding_for(owner) == "alice/thread"
    entered, finish = asyncio.Event(), asyncio.Event()
    wait_for_cleanup = handle._wait_for_cleanup

    async def gated_wait():
        entered.set()
        await finish.wait()
        await wait_for_cleanup()

    monkeypatch.setattr(handle, "_wait_for_cleanup", gated_wait)
    cleanup = asyncio.create_task(release_sandbox_execution_lease_async(rt.context))
    try:
        await entered.wait()
        cleanup.cancel()
        await asyncio.sleep(0)
        cleanup.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await cleanup
        assert manager.binding_for(owner) is None
        assert "alice/thread" in provider.released
    finally:
        finish.set()
        await asyncio.gather(cleanup, return_exceptions=True)
        await manager.release_async(owner)
        if blocker is not None:
            await release_sandbox_execution_lease_async(blocker.context)


@pytest.mark.anyio
async def test_prewarm_close_error_still_releases_actual_tool_lease(setup, monkeypatch):
    provider, config = setup
    config.sandbox.prewarm = False
    rt = runtime()
    await start(rt).task
    await ensure_sandbox_initialized_async(rt)
    manager = get_sandbox_lease_manager(provider)
    owner = rt.context["sandbox_lease_owner_id"]

    async def fail_close(context):
        raise RuntimeError("prewarm cleanup failed")

    monkeypatch.setattr(prewarm, "close_sandbox_prewarm_context", fail_close)
    try:
        with pytest.raises(RuntimeError, match="prewarm cleanup failed"):
            await release_sandbox_execution_lease_async(rt.context)
        assert manager.binding_for(owner) is None
        assert provider.released == ["alice/thread"]
    finally:
        await manager.release_async(owner)


@pytest.mark.anyio
async def test_cancel_after_disabled_prewarm_close_drains_blocked_ordinary_release(setup, monkeypatch):
    import threading

    provider, config = setup
    config.sandbox.prewarm = False
    rt = runtime()
    handle = start(rt)
    await handle.task
    await ensure_sandbox_initialized_async(rt)
    close_started, finish_close = asyncio.Event(), asyncio.Event()
    release_started, finish_release = threading.Event(), threading.Event()
    original_wait = handle._wait_for_cleanup
    original_release = provider.release

    async def gated_wait():
        close_started.set()
        await finish_close.wait()
        await original_wait()

    def blocking_release(sandbox_id):
        release_started.set()
        assert finish_release.wait(5)
        original_release(sandbox_id)

    monkeypatch.setattr(handle, "_wait_for_cleanup", gated_wait)
    monkeypatch.setattr(provider, "release", blocking_release)
    cleanup = asyncio.create_task(release_sandbox_execution_lease_async(rt.context))
    try:
        await close_started.wait()
        cleanup.cancel()
        finish_close.set()
        assert await asyncio.to_thread(release_started.wait, 1)
        cleanup.cancel()
        await asyncio.sleep(0)
        cleanup.cancel()
        await asyncio.sleep(0)
        assert not cleanup.done()
        finish_release.set()
        with pytest.raises(asyncio.CancelledError):
            await cleanup
        assert provider.released == ["alice/thread"]
    finally:
        finish_close.set()
        finish_release.set()
        await asyncio.gather(cleanup, return_exceptions=True)
        await get_sandbox_lease_manager(provider).release_async(rt.context["sandbox_lease_owner_id"])


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("method", ["invoke", "stream"])
def test_compiled_sync_graph_keeps_lazy_path_without_speculation(setup, monkeypatch, enabled, method):
    from langchain.agents import create_agent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from deerflow.sandbox.middleware import SandboxMiddleware

    provider, config = setup
    config.sandbox.prewarm = enabled

    class Model(BaseChatModel):
        @property
        def _llm_type(self):
            return "sync-prewarm-compatibility-test"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Explained without execution"))])

    middleware = SandboxMiddleware()
    monkeypatch.setattr(middleware, "_prepare_agent_skill_projection", lambda *args, **kwargs: None)
    graph = create_agent(Model(), tools=[], middleware=[middleware])
    context = {"thread_id": "sync-thread", "user_id": "alice", "app_config": config}
    state = {"messages": [HumanMessage(content="```python\nprint(42)\n```")]}
    if method == "invoke":
        result = graph.invoke(state, context=context)
    else:
        result = list(graph.stream(state, context=context, stream_mode="values"))[-1]
    assert result["messages"][-1].content == "Explained without execution"
    assert "__deerflow_sandbox_prewarm" not in context
    assert provider.calls == []
    assert not prewarm._permits


@pytest.mark.anyio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("outcome", ["success", "model-error", "cancel", "tool"])
@pytest.mark.parametrize("method", ["ainvoke", "astream"])
async def test_direct_sdk_graph_does_not_leak_speculation(setup, monkeypatch, enabled, outcome, method):
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import StructuredTool

    from deerflow.agents.factory import create_deerflow_agent
    from deerflow.agents.features import RuntimeFeatures
    from deerflow.sandbox.middleware import SandboxMiddleware

    provider, config = setup
    config.sandbox.prewarm = enabled
    context = {"thread_id": "direct-graph", "user_id": "alice", "app_config": config}
    entered = asyncio.Event()
    blocked = asyncio.Event()

    class Model(BaseChatModel):
        @property
        def _llm_type(self):
            return "direct-sdk-prewarm-test"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, *args, **kwargs):
            raise AssertionError("async model required")

        async def _agenerate(self, *args, **kwargs):
            messages = args[0] if args else kwargs["messages"]
            handle = context.get("__deerflow_sandbox_prewarm")
            if handle is not None:
                await handle.task
            entered.set()
            if outcome == "model-error":
                raise RuntimeError("direct model failed")
            if outcome == "cancel":
                await blocked.wait()
            if outcome == "tool" and not any(isinstance(message, ToolMessage) for message in messages):
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[{"name": "use_sandbox", "args": {}, "id": "sandbox-call"}]))])
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="No execution needed"))])

    monkeypatch.setattr(SandboxMiddleware, "_prepare_agent_skill_projection", lambda *args, **kwargs: None)

    async def use_sandbox():
        sandbox = await ensure_sandbox_initialized_async(SimpleNamespace(context=context, state={}))
        return sandbox.id

    tool = StructuredTool.from_function(coroutine=use_sandbox, name="use_sandbox", description="Acquire a sandbox for a real tool call")
    graph = create_deerflow_agent(Model(), tools=[tool] if outcome == "tool" else [], features=RuntimeFeatures(loop_detection=False))
    state = {"messages": [HumanMessage(content="```sh\npytest tests\n```")]}

    async def invoke():
        if method == "ainvoke":
            return await graph.ainvoke(state, context=context)
        return [chunk async for chunk in graph.astream(state, context=context, stream_mode="values")][-1]

    task = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif outcome == "model-error":
            with pytest.raises(RuntimeError, match="direct model failed"):
                await task
        else:
            result = await task
            assert result["messages"][-1].content == "No execution needed"

        # Observe the graph's own terminal state, before test teardown.
        assert provider.clients == {}
        assert get_sandbox_lease_manager(provider).binding_for(context["sandbox_lease_owner_id"]) is None
        assert not prewarm._permits
        if outcome == "tool":
            assert provider.calls == [("alice", "direct-graph")]
            assert provider.released == ["alice/direct-graph"]
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # Failure-only hygiene does not supply the graph's execution boundary.
        handle = context.get("__deerflow_sandbox_prewarm")
        if handle is not None:
            await handle.close()


@pytest.mark.anyio
@pytest.mark.parametrize("marker", ["missing", None, True, "registered", {}])
async def test_prewarm_requires_registered_execution_cleanup(setup, marker):
    provider, _ = setup
    rt = runtime()
    rt.context.pop(SANDBOX_PREWARM_CLEANUP_CONTEXT_KEY)
    if marker != "missing":
        rt.context[SANDBOX_PREWARM_CLEANUP_CONTEXT_KEY] = marker

    prewarm.start_sandbox_prewarm({"messages": [HumanMessage(content="```sh\npytest tests\n```")]}, rt)

    assert "__deerflow_sandbox_prewarm" not in rt.context
    assert provider.calls == []
    assert not prewarm._permits


@pytest.mark.anyio
async def test_execution_cleanup_revokes_prewarm_admission(setup):
    rt = runtime()
    assert sandbox_prewarm_cleanup_registered(rt.context)

    await release_sandbox_execution_lease_async(rt.context)

    assert not sandbox_prewarm_cleanup_registered(rt.context)

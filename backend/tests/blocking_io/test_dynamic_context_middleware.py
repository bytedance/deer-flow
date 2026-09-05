"""Regression anchor: DynamicContextMiddleware must not block the event loop.

``_inject`` performs synchronous file I/O (memory JSON loading) and
potentially blocking network calls (tiktoken encoding download on first
use — see issue #3402).  ``abefore_agent`` offloads the call via
``asyncio.to_thread`` so the event loop stays responsive.

This anchor drives the real ``create_agent`` graph via ``ainvoke`` under
the strict Blockbuster gate.  If the offload regresses and the blocking
I/O runs on the event loop, Blockbuster raises ``BlockingError`` and
this test fails.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import mock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import PrivateAttr

from deerflow.agents.lead_agent import prompt as prompt_module
from deerflow.agents.memory import MemoryManager, MemoryReadError, reset_memory_manager
from deerflow.agents.memory.manager import _scan_backends
from deerflow.agents.middlewares.dynamic_context_middleware import (
    _DYNAMIC_CONTEXT_REMINDER_KEY,
    DynamicContextMiddleware,
)
from deerflow.config.memory_config import MemoryConfig
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY

pytestmark = pytest.mark.asyncio


class _FakeModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel with a no-op ``bind_tools`` for create_agent."""

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


class _LegacyBackend(MemoryManager):
    """Third-party backend that inherits the default timeout-policy resolver."""

    _release: threading.Event = PrivateAttr(default_factory=threading.Event)
    _finished: threading.Event = PrivateAttr(default_factory=threading.Event)

    @classmethod
    def from_config(cls, backend_config, *, mode="middleware", **host_hooks):
        return cls(backend_config=backend_config, mode=mode)

    def add(self, thread_id, messages, **kwargs):
        pass

    def get_context(self, user_id, **kwargs):
        try:
            self._release.wait(timeout=2)
            return "Late memory context"
        finally:
            self._finished.set()


@pytest.fixture(autouse=True)
def _isolate_memory_manager() -> None:
    reset_memory_manager()
    yield
    reset_memory_manager()


async def test_abefore_agent_does_not_block_event_loop() -> None:
    """``abefore_agent`` must offload _inject() to a thread pool."""
    mw = DynamicContextMiddleware()

    # Mock _build_full_reminder to simulate a slow synchronous operation
    # (file I/O + tiktoken download).  The mock sleeps briefly to make any
    # event-loop blocking visible to the Blockbuster gate.
    original_build = mw._build_full_reminder

    def slow_build_reminder(runtime=None):
        import time

        time.sleep(0.05)  # 50ms sync sleep — blocks the thread it runs on
        return original_build(runtime)

    with (
        mock.patch.object(mw, "_build_full_reminder", slow_build_reminder),
        mock.patch.object(prompt_module, "_get_memory_context", return_value=""),
    ):
        agent = await asyncio.to_thread(
            lambda: create_agent(
                model=_FakeModel(responses=[AIMessage(content="ok")]),
                tools=[],
                middleware=[mw],
            )
        )

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="hi")]},
            {"configurable": {"thread_id": "test-thread"}},
        )

    assert result["messages"]


async def test_abefore_agent_returns_same_result_as_before_agent() -> None:
    """``abefore_agent`` (async, offloaded) must produce the same result as
    ``before_agent`` (sync, for backward compatibility)."""
    mw = DynamicContextMiddleware()

    state = {"messages": [HumanMessage(content="Hello", id="msg-1")]}
    runtime = SimpleNamespace(context={})

    with (
        mock.patch.object(prompt_module, "_get_memory_context", return_value=""),
        mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-05, Friday"

        # Sync path
        sync_result = mw.before_agent(state, runtime)

        # Async path (offloaded to thread)
        async_result = await mw.abefore_agent(state, runtime)

    assert sync_result is not None
    assert async_result is not None
    assert sync_result.keys() == async_result.keys()
    # Both return 2 messages: reminder + user content
    assert len(sync_result["messages"]) == 2
    assert len(async_result["messages"]) == 2
    # IDs match
    assert sync_result["messages"][0].id == async_result["messages"][0].id
    assert sync_result["messages"][1].id == async_result["messages"][1].id


async def test_abefore_agent_returns_none_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed-out worker must not emit a late, phantom context event."""
    monkeypatch.setenv("OPENVIKING_API_KEY", "test-key")
    await asyncio.to_thread(_scan_backends)
    mw = DynamicContextMiddleware(
        app_config=SimpleNamespace(
            memory=MemoryConfig(
                manager_class="openviking",
                backend_config={
                    "owner_user_id": "alice",
                    "failure_policy": {"read": "fail_open"},
                },
            )
        )
    )
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    journal = mock.MagicMock()

    def blocking_inject(state, runtime=None):
        started.set()
        release.wait(timeout=2)
        try:
            return {
                "messages": [
                    HumanMessage(
                        content="<memory>late context</memory>",
                        id="msg-1__memory",
                        additional_kwargs={
                            _DYNAMIC_CONTEXT_REMINDER_KEY: True,
                        },
                    )
                ]
            }
        finally:
            finished.set()

    with (
        mock.patch.object(mw, "_inject", blocking_inject),
        mock.patch(
            "deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS",
            0.01,
        ),
    ):
        state = {"messages": [HumanMessage(content="Hello", id="msg-1")]}
        runtime = SimpleNamespace(context={"__run_journal": journal})
        result = await mw.abefore_agent(state, runtime)

    assert started.is_set()
    assert result is None
    release.set()
    assert await asyncio.to_thread(finished.wait, 1)
    journal.record_memory_context.assert_not_called()


async def test_abefore_agent_propagates_strict_memory_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A strict backend must not degrade after the middleware timeout."""
    monkeypatch.setenv("OPENVIKING_API_KEY", "test-key")
    await asyncio.to_thread(_scan_backends)
    mw = DynamicContextMiddleware(
        app_config=SimpleNamespace(
            memory=MemoryConfig(
                manager_class="openviking",
                backend_config={
                    "owner_user_id": "alice",
                    "failure_policy": {"read": "raise"},
                },
            )
        )
    )
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_inject(state, runtime=None):
        started.set()
        release.wait(timeout=2)
        finished.set()

    with (
        mock.patch.object(mw, "_inject", blocking_inject),
        mock.patch(
            "deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS",
            0.01,
        ),
    ):
        state = {"messages": [HumanMessage(content="Hello", id="msg-1")]}
        runtime = SimpleNamespace(context={})
        with pytest.raises(MemoryReadError) as exc_info:
            await mw.abefore_agent(state, runtime)

    assert isinstance(exc_info.value.__cause__, TimeoutError)
    assert started.is_set()
    release.set()
    assert await asyncio.to_thread(finished.wait, 1)


@pytest.mark.parametrize(
    ("manager_class", "backend_config", "api_key"),
    [
        pytest.param(
            "openviking",
            {
                "owner_user_id": "alice",
                "failure_policy": {"read": "raise"},
            },
            None,
            id="missing_openviking_api_key",
        ),
        pytest.param(
            "openviking",
            {
                "owner_user_id": "alice",
                "failure_policy": {"read": "invalid"},
            },
            "test-key",
            id="invalid_backend_config",
        ),
        pytest.param(
            "missing.backend:Manager",
            {},
            None,
            id="unknown_manager_class",
        ),
    ],
)
async def test_abefore_agent_policy_resolution_failure_does_not_replace_timeout(
    monkeypatch: pytest.MonkeyPatch,
    manager_class: str,
    backend_config: dict,
    api_key: str | None,
) -> None:
    """An unresolved timeout policy must fail closed with the original cause."""
    if api_key is None:
        monkeypatch.delenv("OPENVIKING_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENVIKING_API_KEY", api_key)
    mw = DynamicContextMiddleware(
        app_config=SimpleNamespace(
            memory=MemoryConfig(
                manager_class=manager_class,
                backend_config=backend_config,
            )
        )
    )
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_inject(state, runtime=None):
        started.set()
        release.wait(timeout=2)
        finished.set()

    try:
        with (
            mock.patch.object(mw, "_inject", blocking_inject),
            mock.patch(
                "deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS",
                0.01,
            ),
        ):
            state = {"messages": [HumanMessage(content="Hello", id="msg-1")]}
            runtime = SimpleNamespace(context={})
            with pytest.raises(MemoryReadError) as exc_info:
                await mw.abefore_agent(state, runtime)
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 1)

    assert isinstance(exc_info.value.__cause__, TimeoutError)
    assert started.is_set()


async def test_abefore_agent_records_checkpointed_memory_on_timeout() -> None:
    """A timeout does not hide frozen memory that remains effective for the run."""
    mw = DynamicContextMiddleware()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    journal = mock.MagicMock()
    memory_content = "<memory>checkpoint context</memory>"

    def blocking_inject(state, runtime=None):
        started.set()
        release.wait(timeout=2)
        try:
            return {
                "messages": [
                    HumanMessage(
                        content="<memory>late replacement</memory>",
                        id="msg-2__memory",
                        additional_kwargs={_DYNAMIC_CONTEXT_REMINDER_KEY: True},
                    )
                ]
            }
        finally:
            finished.set()

    state = {
        "messages": [
            HumanMessage(
                content=memory_content,
                id="msg-1__memory",
                additional_kwargs={_DYNAMIC_CONTEXT_REMINDER_KEY: True},
            )
        ]
    }
    runtime = SimpleNamespace(
        context={
            "__run_journal": journal,
            CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset({"msg-1__memory"}),
        }
    )

    with (
        mock.patch.object(mw, "_inject", blocking_inject),
        mock.patch(
            "deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS",
            0.01,
        ),
    ):
        result = await mw.abefore_agent(state, runtime)

    recorded_call = journal.record_memory_context.call_args
    release.set()
    assert await asyncio.to_thread(finished.wait, 1)
    assert started.is_set()
    assert result is None
    assert recorded_call == mock.call(
        content_sha256=hashlib.sha256(memory_content.encode("utf-8")).hexdigest(),
    )
    journal.record_memory_context.assert_called_once()


@pytest.mark.parametrize("read_policy", ["fail_open", "raise"])
@pytest.mark.parametrize("already_saturated", [False, True], ids=["read_occupies_worker", "pool_already_full"])
async def test_timeout_does_not_wait_for_saturated_executor(monkeypatch, read_policy, already_saturated):
    """Neither a running read nor another request may delay timeout handling."""
    monkeypatch.setenv("OPENVIKING_API_KEY", "test-key")
    await asyncio.to_thread(_scan_backends)  # normal Gateway startup discovery
    mw = DynamicContextMiddleware(
        app_config=SimpleNamespace(
            memory=MemoryConfig(
                manager_class="openviking",
                backend_config={"owner_user_id": "alice", "failure_policy": {"read": read_policy}},
            )
        )
    )
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_running_loop()

    def occupy_worker(*_args):
        entered.set()
        release.wait(timeout=2)
        finished.set()

    try:
        with mock.patch.object(loop, "_default_executor", executor):
            if already_saturated:
                executor.submit(occupy_worker)
                while not entered.is_set():
                    await asyncio.sleep(0)
            with (
                mock.patch.object(mw, "_inject", side_effect=occupy_worker) as inject,
                mock.patch("deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS", 0.01),
            ):
                call = mw.abefore_agent({"messages": [HumanMessage(content="hi", id="m1")]}, SimpleNamespace(context={}))
                if read_policy == "raise":
                    with pytest.raises(MemoryReadError) as exc_info:
                        await asyncio.wait_for(call, 0.25)
                    assert isinstance(exc_info.value.__cause__, TimeoutError)
                else:
                    assert await asyncio.wait_for(call, 0.25) is None
                assert not finished.is_set()  # the request returned before its worker
                assert inject.call_count == (0 if already_saturated else 1)
    finally:
        release.set()
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)


@pytest.mark.parametrize("read_policy", ["fail_closed", "fail_open"])
async def test_legacy_backend_timeout_preserves_read_policy(read_policy):
    """The real read path honors legacy policy without waiting for its worker."""
    cfg = MemoryConfig(manager_class=f"{__name__}:_LegacyBackend", backend_config={"failure_policy": {"read": read_policy}})
    backend = _LegacyBackend.from_config(cfg.backend_config)
    mw = DynamicContextMiddleware(app_config=SimpleNamespace(memory=cfg))
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        with (
            mock.patch.object(asyncio.get_running_loop(), "_default_executor", executor),
            mock.patch("deerflow.agents.memory.get_memory_manager", return_value=backend),
            mock.patch("deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS", 0.01),
        ):
            call = mw.abefore_agent({"messages": [HumanMessage(content="hi", id="m1")]}, SimpleNamespace(context={}))
            if read_policy == "fail_closed":
                with pytest.raises(MemoryReadError) as exc_info:
                    await asyncio.wait_for(call, 0.25)
                assert isinstance(exc_info.value.__cause__, TimeoutError)
            else:
                assert await asyncio.wait_for(call, 0.25) is None
            assert not backend._finished.is_set()
    finally:
        backend._release.set()
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
    assert backend._finished.is_set()


@pytest.mark.parametrize("explicit_config", [True, False], ids=["cold_registry", "config_fallback"])
async def test_cold_policy_resolution_stays_off_event_loop(monkeypatch, tmp_path, explicit_config):
    """Cold discovery and the config-reload fallback remain inside the deadline."""
    from deerflow.agents.memory import manager as manager_module

    monkeypatch.setenv("OPENVIKING_API_KEY", "test-key")
    cfg = MemoryConfig(manager_class="openviking", backend_config={"owner_user_id": "alice", "failure_policy": {"read": "fail_open"}})
    policy_file = tmp_path / "policy.txt"
    await asyncio.to_thread(policy_file.write_text, "policy", encoding="utf-8")
    event_loop_thread = threading.get_ident()
    seen = []

    def cold_scan():
        assert threading.get_ident() != event_loop_thread
        policy_file.read_text(encoding="utf-8")
        seen.append("scan")
        return _scan_backends()

    def reload_config():
        assert threading.get_ident() != event_loop_thread
        policy_file.read_text(encoding="utf-8")
        seen.append("config")
        return cfg

    mw = DynamicContextMiddleware(app_config=SimpleNamespace(memory=cfg) if explicit_config else None)
    release = threading.Event()
    finished = threading.Event()

    def blocking_inject(*_):
        try:
            release.wait(timeout=2)
        finally:
            finished.set()

    try:
        with (
            mock.patch.object(manager_module, "_scan_backends", side_effect=cold_scan),
            mock.patch("deerflow.config.memory_config.get_memory_config", side_effect=reload_config),
            mock.patch.object(mw, "_inject", side_effect=blocking_inject),
            mock.patch("deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS", 0.2),
        ):
            assert await asyncio.wait_for(mw.abefore_agent({}, SimpleNamespace(context={})), 0.5) is None
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 1)
    assert "scan" in seen
    assert ("config" in seen) is not explicit_config


@pytest.mark.parametrize("disabled_field", [None, "enabled", "injection_enabled"], ids=["unknown_policy", "memory_disabled", "injection_disabled"])
async def test_cold_saturated_timeout_never_starts_discovery(monkeypatch, disabled_field):
    """An unknown policy fails closed; disabled memory needs no policy lookup."""
    cfg = MemoryConfig(manager_class="openviking")
    if disabled_field:
        setattr(cfg, disabled_field, False)
    mw = DynamicContextMiddleware(app_config=SimpleNamespace(memory=cfg))
    executor = ThreadPoolExecutor(max_workers=1)
    release = threading.Event()
    try:
        with (
            mock.patch.object(asyncio.get_running_loop(), "_default_executor", executor),
            mock.patch("deerflow.agents.memory.manager._scan_backends") as scan,
            mock.patch("deerflow.config.memory_config.get_memory_config") as reload_config,
            mock.patch.object(mw, "_inject") as inject,
            mock.patch("deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS", 0.01),
        ):
            executor.submit(release.wait, 2)
            call = mw.abefore_agent({}, SimpleNamespace(context={}))
            if disabled_field is None:
                with pytest.raises(MemoryReadError) as exc_info:
                    await asyncio.wait_for(call, 0.25)
                assert isinstance(exc_info.value.__cause__, TimeoutError)
            else:
                assert await asyncio.wait_for(call, 0.25) is None
            scan.assert_not_called()
            reload_config.assert_not_called()
            inject.assert_not_called()
    finally:
        release.set()
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)

"""Tests for the Mem0 write integration at the MemoryMiddleware call site.

These tests are the TDD contract for the write half of the integration.
They assert that when ``MEM0_ENABLED=1`` is set:

1. ``MemoryMiddleware.after_agent`` invokes ``maybe_write_to_mem0`` from
   the new ``deerflow.agents.memory.mem0_adapter`` module, after the
   existing ``queue.add(...)`` call.
2. ``maybe_write_to_mem0`` is called with the *same* filtered messages
   that ``queue.add`` receives (user + final AI messages only).
3. The ``user_id`` passed to ``maybe_write_to_mem0`` follows the
   precedence  ``configurable.mem0_user_id  >  configurable.agent_name
   >  'default'``.
4. When ``MEM0_ENABLED`` is unset, the adapter still receives the call
   but is a no-op internally (i.e., ``mem0.Memory`` is never imported
   and ``add()`` is never called). This test verifies the flag-gate by
   mocking ``is_mem0_enabled``.

The tests fail before implementation because
``deerflow.agents.memory.mem0_adapter`` does not exist yet — pytest
collection raises ImportError, which counts as a failure.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware


def _make_runtime(thread_id: str | None = "thread-under-test") -> SimpleNamespace:
    """Minimal runtime stub that matches what MemoryMiddleware.after_agent reads."""
    return SimpleNamespace(context={"thread_id": thread_id} if thread_id else {})


def _make_state() -> dict:
    """State with one user turn and one final AI response — passes the existing filter."""
    return {
        "messages": [
            HumanMessage(content="I prefer concise academic reports with inline citations."),
            AIMessage(content="Got it — I'll use that style going forward."),
        ]
    }


@pytest.fixture(autouse=True)
def _clear_mem0_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEM0_ENABLED", raising=False)


@pytest.fixture
def _memory_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable the existing deerflow memory config so MemoryMiddleware doesn't early-return."""
    cfg = SimpleNamespace(enabled=True)
    monkeypatch.setattr(
        "deerflow.agents.middlewares.memory_middleware.get_memory_config",
        lambda: cfg,
    )
    # Ensure the existing queue.add is a no-op during these tests.
    monkeypatch.setattr(
        "deerflow.agents.middlewares.memory_middleware.get_memory_queue",
        lambda: MagicMock(),
    )


def test_after_agent_invokes_mem0_adapter_when_flag_set(
    monkeypatch: pytest.MonkeyPatch, _memory_enabled: None
) -> None:
    """With MEM0_ENABLED=1, MemoryMiddleware.after_agent must call maybe_write_to_mem0."""
    monkeypatch.setenv("MEM0_ENABLED", "1")

    captured: dict = {}

    def _fake_write(messages, *, user_id, agent_id, run_id):
        captured["messages"] = messages
        captured["user_id"] = user_id
        captured["agent_id"] = agent_id
        captured["run_id"] = run_id

    # Stub the new adapter module so MemoryMiddleware can import it even though
    # the real module does not exist until step 8. The implementation is expected
    # to `from deerflow.agents.memory.mem0_adapter import maybe_write_to_mem0`
    # (or similar) inside memory_middleware.py — this patch intercepts that call.
    with patch(
        "deerflow.agents.memory.mem0_adapter.maybe_write_to_mem0",
        side_effect=_fake_write,
        create=True,
    ):
        middleware = MemoryMiddleware(agent_name="researcher")
        middleware.after_agent(_make_state(), _make_runtime())

    assert "messages" in captured, (
        "maybe_write_to_mem0 was not called. Expected MemoryMiddleware.after_agent "
        "to invoke the new Mem0 adapter after the existing queue.add(...)."
    )
    # The messages forwarded must include both the user turn and the AI response.
    contents = [getattr(m, "content", None) for m in captured["messages"]]
    assert any("concise academic" in (c or "") for c in contents)
    assert any("Got it" in (c or "") for c in contents)
    # agent_id mirrors MemoryMiddleware's agent_name.
    assert captured["agent_id"] == "researcher"
    # run_id comes from the runtime's thread_id.
    assert captured["run_id"] == "thread-under-test"


def test_user_id_precedence_prefers_configurable_mem0_user_id(
    monkeypatch: pytest.MonkeyPatch, _memory_enabled: None
) -> None:
    """configurable.mem0_user_id overrides agent_name when resolving user_id."""
    monkeypatch.setenv("MEM0_ENABLED", "1")

    captured: dict = {}

    def _fake_write(messages, *, user_id, agent_id, run_id):
        captured["user_id"] = user_id

    configurable = {
        "mem0_user_id": "alice@example.com",
        "agent_name": "researcher",
        "thread_id": "thread-under-test",
    }

    with (
        patch(
            "deerflow.agents.memory.mem0_adapter.maybe_write_to_mem0",
            side_effect=_fake_write,
            create=True,
        ),
        patch(
            "deerflow.agents.middlewares.memory_middleware.get_config",
            return_value={"configurable": configurable},
        ),
    ):
        middleware = MemoryMiddleware(agent_name="researcher")
        middleware.after_agent(_make_state(), _make_runtime(thread_id=None))

    assert captured.get("user_id") == "alice@example.com", (
        "Expected configurable.mem0_user_id to win over agent_name in user_id resolution."
    )


def test_user_id_falls_back_to_agent_name(
    monkeypatch: pytest.MonkeyPatch, _memory_enabled: None
) -> None:
    """When configurable.mem0_user_id is absent, user_id falls back to agent_name."""
    monkeypatch.setenv("MEM0_ENABLED", "1")

    captured: dict = {}

    def _fake_write(messages, *, user_id, agent_id, run_id):
        captured["user_id"] = user_id

    with (
        patch(
            "deerflow.agents.memory.mem0_adapter.maybe_write_to_mem0",
            side_effect=_fake_write,
            create=True,
        ),
        patch(
            "deerflow.agents.middlewares.memory_middleware.get_config",
            return_value={"configurable": {"agent_name": "researcher"}},
        ),
    ):
        middleware = MemoryMiddleware(agent_name="researcher")
        middleware.after_agent(_make_state(), _make_runtime())

    assert captured.get("user_id") == "researcher"


def test_user_id_falls_back_to_default_when_nothing_configured(
    monkeypatch: pytest.MonkeyPatch, _memory_enabled: None
) -> None:
    """When neither mem0_user_id nor agent_name is set, user_id is 'default'."""
    monkeypatch.setenv("MEM0_ENABLED", "1")

    captured: dict = {}

    def _fake_write(messages, *, user_id, agent_id, run_id):
        captured["user_id"] = user_id

    with (
        patch(
            "deerflow.agents.memory.mem0_adapter.maybe_write_to_mem0",
            side_effect=_fake_write,
            create=True,
        ),
        patch(
            "deerflow.agents.middlewares.memory_middleware.get_config",
            return_value={"configurable": {}},
        ),
    ):
        middleware = MemoryMiddleware(agent_name=None)
        middleware.after_agent(_make_state(), _make_runtime())

    assert captured.get("user_id") == "default"


def test_existing_queue_add_is_called_regardless_of_mem0_flag(
    monkeypatch: pytest.MonkeyPatch, _memory_enabled: None
) -> None:
    """The Mem0 integration must NOT disturb the pre-existing queue.add(...) call.

    Principle 3 (no breakage): with or without the flag, the existing memory
    pipeline continues to enqueue conversations for the memory.json updater.
    """
    monkeypatch.setenv("MEM0_ENABLED", "1")

    fake_queue = MagicMock()
    monkeypatch.setattr(
        "deerflow.agents.middlewares.memory_middleware.get_memory_queue",
        lambda: fake_queue,
    )

    with patch(
        "deerflow.agents.memory.mem0_adapter.maybe_write_to_mem0",
        create=True,
    ):
        MemoryMiddleware(agent_name="researcher").after_agent(
            _make_state(), _make_runtime()
        )

    assert fake_queue.add.called, (
        "Existing queue.add(...) must still run — Mem0 integration is additive, not replacing."
    )


def test_mem0_adapter_module_is_importable() -> None:
    """The new adapter module must exist and expose the contract symbols."""
    from deerflow.agents.memory import mem0_adapter  # noqa: F401

    assert hasattr(mem0_adapter, "is_mem0_enabled")
    assert hasattr(mem0_adapter, "maybe_write_to_mem0")
    assert hasattr(mem0_adapter, "Mem0ReadMiddleware")


def test_is_mem0_enabled_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_mem0_enabled() returns True only for truthy MEM0_ENABLED values."""
    from deerflow.agents.memory.mem0_adapter import is_mem0_enabled

    monkeypatch.delenv("MEM0_ENABLED", raising=False)
    assert is_mem0_enabled() is False

    monkeypatch.setenv("MEM0_ENABLED", "")
    assert is_mem0_enabled() is False

    monkeypatch.setenv("MEM0_ENABLED", "0")
    assert is_mem0_enabled() is False

    monkeypatch.setenv("MEM0_ENABLED", "1")
    assert is_mem0_enabled() is True


def test_maybe_write_to_mem0_is_noop_when_flag_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the flag unset, maybe_write_to_mem0 must NOT import mem0 or call add()."""
    monkeypatch.delenv("MEM0_ENABLED", raising=False)

    from deerflow.agents.memory.mem0_adapter import maybe_write_to_mem0

    fake_memory = MagicMock()
    with patch(
        "deerflow.agents.memory.mem0_adapter._get_memory_instance",
        return_value=fake_memory,
    ) as get_instance:
        maybe_write_to_mem0(
            [HumanMessage(content="hi")],
            user_id="u",
            agent_id="a",
            run_id="r",
        )
        # Join any spawned daemon thread to catch real failures.
        import time
        time.sleep(0.05)

    assert not get_instance.called, (
        "maybe_write_to_mem0 must be a no-op when MEM0_ENABLED is unset — "
        "no Memory instance should be created."
    )
    assert not fake_memory.add.called


def test_maybe_write_to_mem0_calls_memory_add_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the flag set, maybe_write_to_mem0 must call Memory.add() with the right shape.

    Per Mem0 OSS SDK (quickstart): m.add(messages, user_id="alex") — messages
    is a list of {"role", "content"} dicts. We assert the write helper
    produces that exact shape and forwards user_id/agent_id/run_id.
    """
    monkeypatch.setenv("MEM0_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")

    from deerflow.agents.memory.mem0_adapter import maybe_write_to_mem0

    fake_memory = MagicMock()
    with patch(
        "deerflow.agents.memory.mem0_adapter._get_memory_instance",
        return_value=fake_memory,
    ):
        maybe_write_to_mem0(
            [
                HumanMessage(content="I prefer concise reports."),
                AIMessage(content="Noted."),
            ],
            user_id="alice",
            agent_id="researcher",
            run_id="thread-xyz",
        )
        # The adapter fires Memory.add on a daemon thread — wait briefly.
        import time
        for _ in range(50):
            if fake_memory.add.called:
                break
            time.sleep(0.02)

    assert fake_memory.add.called, "Memory.add() was never invoked"
    call_args = fake_memory.add.call_args
    # First positional arg: the messages payload.
    messages_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("messages")
    assert isinstance(messages_arg, list)
    # Mem0's schema: each message is a dict with role + content.
    assert all(isinstance(m, dict) and "role" in m and "content" in m for m in messages_arg)
    # Exact role mapping: human → user, ai → assistant.
    roles = [m["role"] for m in messages_arg]
    assert "user" in roles
    assert "assistant" in roles
    # user_id / agent_id / run_id forwarded as kwargs.
    assert call_args.kwargs.get("user_id") == "alice"
    assert call_args.kwargs.get("agent_id") == "researcher"
    assert call_args.kwargs.get("run_id") == "thread-xyz"

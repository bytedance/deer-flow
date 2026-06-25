"""Tests for the Mem0 read integration via the new Mem0ReadMiddleware.

TDD contract for the read half of the integration. When ``MEM0_ENABLED=1``:

1. A new ``Mem0ReadMiddleware`` class exists in
   ``deerflow.agents.memory.mem0_adapter`` and is an ``AgentMiddleware``
   subclass with a ``before_model(state, runtime)`` hook.
2. ``before_model`` extracts the latest human-message text from
   ``state['messages']`` and calls ``Memory.search`` using Mem0 OSS's
   documented shape:
       m.search(query=<latest_human>, filters={"user_id": <user_id>}, limit=5)
3. When the search returns results, ``before_model`` returns a state
   update ``{"messages": [SystemMessage(content=...)]}`` where the
   injected content is wrapped in ``<mem0_memory>...</mem0_memory>`` tags
   and contains the memory text from each result.
4. When the search returns no results (or raises), ``before_model``
   returns ``None`` (or an empty dict) and the agent proceeds with the
   unmodified message list.
5. ``_build_middlewares`` in ``lead_agent.agent`` appends
   ``Mem0ReadMiddleware`` to the chain *only* when ``is_mem0_enabled()``
   is True — the middleware chain is byte-for-byte identical to main
   when the flag is unset.

Tests fail before implementation because the adapter module does not
exist yet (pytest ImportError).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def _runtime(configurable: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(context=configurable or {})


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEM0_ENABLED", raising=False)


def test_mem0_read_middleware_class_exists() -> None:
    """Mem0ReadMiddleware must exist as an AgentMiddleware subclass."""
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.memory.mem0_adapter import Mem0ReadMiddleware

    assert issubclass(Mem0ReadMiddleware, AgentMiddleware)


def test_before_model_searches_mem0_with_latest_human_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mem0ReadMiddleware.before_model must call Memory.search with the latest human text."""
    monkeypatch.setenv("MEM0_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")

    from deerflow.agents.memory.mem0_adapter import Mem0ReadMiddleware

    fake_memory = MagicMock()
    fake_memory.search.return_value = {
        "results": [
            {
                "id": "mem_1",
                "memory": "User prefers concise academic reports with citations.",
                "user_id": "alice",
                "score": 0.92,
            }
        ]
    }

    state = {
        "messages": [
            HumanMessage(content="Earlier turn."),
            AIMessage(content="Earlier answer."),
            HumanMessage(content="What research style do I prefer?"),
        ]
    }

    runtime = _runtime({"mem0_user_id": "alice", "agent_name": "researcher"})

    with (
        patch(
            "deerflow.agents.memory.mem0_adapter._get_memory_instance",
            return_value=fake_memory,
        ),
        patch(
            "deerflow.agents.memory.mem0_adapter.get_config",
            return_value={"configurable": {"mem0_user_id": "alice"}},
            create=True,
        ),
    ):
        result = Mem0ReadMiddleware(agent_name="researcher").before_model(state, runtime)

    assert fake_memory.search.called, "Memory.search must be invoked in before_model"
    call = fake_memory.search.call_args
    # Query is the LATEST human message — not the first.
    query = call.args[0] if call.args else call.kwargs.get("query")
    assert query == "What research style do I prefer?"
    # filters must be a dict with user_id — per Mem0 OSS quickstart shape.
    filters = call.kwargs.get("filters")
    assert isinstance(filters, dict)
    assert filters.get("user_id") == "alice"

    # Result: a state update that prepends / appends a SystemMessage with <mem0_memory> tag.
    assert isinstance(result, dict)
    msgs = result.get("messages", [])
    assert msgs, "Expected before_model to return messages when search has results"
    injected = msgs[0]
    assert isinstance(injected, SystemMessage)
    content = injected.content if isinstance(injected.content, str) else str(injected.content)
    assert "<mem0_memory>" in content
    assert "</mem0_memory>" in content
    assert "concise academic reports" in content


def test_before_model_returns_none_when_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Mem0 returns no memories, before_model must not inject anything."""
    monkeypatch.setenv("MEM0_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")

    from deerflow.agents.memory.mem0_adapter import Mem0ReadMiddleware

    fake_memory = MagicMock()
    fake_memory.search.return_value = {"results": []}

    state = {"messages": [HumanMessage(content="hi")]}

    with patch(
        "deerflow.agents.memory.mem0_adapter._get_memory_instance",
        return_value=fake_memory,
    ):
        result = Mem0ReadMiddleware(agent_name=None).before_model(state, _runtime())

    # None or a dict with no messages are both acceptable non-injection signals.
    if isinstance(result, dict):
        assert not result.get("messages")
    else:
        assert result is None


def test_before_model_swallows_mem0_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Memory.search raises, the middleware must NOT propagate — the agent run continues."""
    monkeypatch.setenv("MEM0_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")

    from deerflow.agents.memory.mem0_adapter import Mem0ReadMiddleware

    fake_memory = MagicMock()
    fake_memory.search.side_effect = RuntimeError("mem0 backend unavailable")

    state = {"messages": [HumanMessage(content="hi")]}

    with patch(
        "deerflow.agents.memory.mem0_adapter._get_memory_instance",
        return_value=fake_memory,
    ):
        # Must not raise.
        result = Mem0ReadMiddleware(agent_name=None).before_model(state, _runtime())

    # Non-injection on failure is the safe default.
    if isinstance(result, dict):
        assert not result.get("messages")
    else:
        assert result is None


def test_lead_agent_appends_mem0_middleware_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_build_middlewares must include Mem0ReadMiddleware only when MEM0_ENABLED=1."""
    monkeypatch.setenv("MEM0_ENABLED", "1")

    from deerflow.agents.lead_agent.agent import _build_middlewares
    from deerflow.agents.memory.mem0_adapter import Mem0ReadMiddleware

    config = {"configurable": {"thread_id": "t1"}}
    # _build_middlewares calls out to app_config/memory_config/etc.; patch the
    # minimum to let it run without a full config.yaml. We only need the list.
    with (
        patch("deerflow.agents.lead_agent.agent.get_memory_config") as mem_cfg,
        patch("deerflow.agents.lead_agent.agent.get_summarization_config") as sum_cfg,
        patch("deerflow.agents.lead_agent.agent.get_app_config") as app_cfg,
    ):
        mem_cfg.return_value = SimpleNamespace(enabled=False)
        sum_cfg.return_value = SimpleNamespace(enabled=False)
        app_cfg.return_value = SimpleNamespace(
            token_usage=SimpleNamespace(enabled=False),
            tool_search=SimpleNamespace(enabled=False),
            get_model_config=lambda _name: None,
        )
        middlewares = _build_middlewares(config, model_name=None, agent_name=None)

    assert any(isinstance(m, Mem0ReadMiddleware) for m in middlewares), (
        "Mem0ReadMiddleware must be present in the chain when MEM0_ENABLED=1."
    )


def test_lead_agent_does_not_append_mem0_middleware_when_flag_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When MEM0_ENABLED is unset, Mem0ReadMiddleware must NOT be in the chain.

    This is the non-invasiveness guarantee: chain byte-for-byte identical to main.
    """
    monkeypatch.delenv("MEM0_ENABLED", raising=False)

    from deerflow.agents.lead_agent.agent import _build_middlewares
    from deerflow.agents.memory.mem0_adapter import Mem0ReadMiddleware

    config = {"configurable": {"thread_id": "t1"}}
    with (
        patch("deerflow.agents.lead_agent.agent.get_memory_config") as mem_cfg,
        patch("deerflow.agents.lead_agent.agent.get_summarization_config") as sum_cfg,
        patch("deerflow.agents.lead_agent.agent.get_app_config") as app_cfg,
    ):
        mem_cfg.return_value = SimpleNamespace(enabled=False)
        sum_cfg.return_value = SimpleNamespace(enabled=False)
        app_cfg.return_value = SimpleNamespace(
            token_usage=SimpleNamespace(enabled=False),
            tool_search=SimpleNamespace(enabled=False),
            get_model_config=lambda _name: None,
        )
        middlewares = _build_middlewares(config, model_name=None, agent_name=None)

    assert not any(isinstance(m, Mem0ReadMiddleware) for m in middlewares), (
        "Mem0ReadMiddleware must NOT be in the chain when MEM0_ENABLED is unset."
    )

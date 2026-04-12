"""Tests for ByteRover context middleware."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

from deerflow.agents.lead_agent.agent import _build_middlewares
from deerflow.agents.middlewares import byterover_context_middleware as byterover_module
from deerflow.agents.middlewares.byterover_context_middleware import ByteRoverContextMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.config import byterover_config as byterover_config_module
from deerflow.config.byterover_config import ByteRoverConfig


class _RecordingModel(BaseChatModel):
    _seen_messages: list = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "recording"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen_messages = list(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])


def _configure_byterover(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> None:
    monkeypatch.setattr(
        byterover_module,
        "get_byterover_config",
        lambda: ByteRoverConfig(enabled=enabled),
    )


def test_byterover_config_resolves_repo_root_by_default() -> None:
    expected_repo_root = Path(byterover_config_module.__file__).resolve().parents[5]

    assert ByteRoverConfig().resolved_cwd == str(expected_repo_root)


def test_byterover_config_resolves_relative_cwd_from_repo_root() -> None:
    expected_repo_root = Path(byterover_config_module.__file__).resolve().parents[5]

    assert ByteRoverConfig(cwd="backend").resolved_cwd == str((expected_repo_root / "backend").resolve())


def test_before_agent_stores_private_byterover_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_byterover(monkeypatch, enabled=True)
    query = MagicMock(return_value="Known context")
    monkeypatch.setattr(byterover_module, "_run_brv_query", query)

    middleware = ByteRoverContextMiddleware()
    state = {
        "messages": [
            HumanMessage(
                content="<uploaded_files>\nfile metadata\n</uploaded_files>\n\nWhat does this file do?"
            )
        ]
    }

    result = middleware.before_agent(state, runtime=SimpleNamespace())

    assert result == {"byterover_context": "Known context"}
    query.assert_called_once_with("What does this file do?")


def test_run_brv_query_uses_resolved_cwd_and_warns_once_for_missing_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = ByteRoverConfig(enabled=True)
    warning = MagicMock()
    run = MagicMock(side_effect=FileNotFoundError())

    monkeypatch.setattr(byterover_module, "get_byterover_config", lambda: cfg)
    monkeypatch.setattr(byterover_module, "_WARNED_OPERATIONAL_FAILURES", set())
    monkeypatch.setattr(byterover_module.logger, "warning", warning)
    monkeypatch.setattr(byterover_module.subprocess, "run", run)

    assert byterover_module._run_brv_query("What do you know?") is None
    assert byterover_module._run_brv_query("What do you know?") is None

    assert run.call_args.kwargs["cwd"] == cfg.resolved_cwd
    warning.assert_called_once_with(
        "ByteRover query command is unavailable | cwd=%s | executable=brv",
        cfg.resolved_cwd,
    )


def test_run_brv_query_warns_once_for_non_zero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ByteRoverConfig(enabled=True)
    warning = MagicMock()
    run = MagicMock(
        return_value=SimpleNamespace(returncode=23, stdout="", stderr="permission denied")
    )

    monkeypatch.setattr(byterover_module, "get_byterover_config", lambda: cfg)
    monkeypatch.setattr(byterover_module, "_WARNED_OPERATIONAL_FAILURES", set())
    monkeypatch.setattr(byterover_module.logger, "warning", warning)
    monkeypatch.setattr(byterover_module.subprocess, "run", run)

    assert byterover_module._run_brv_query("What do you know?") is None
    assert byterover_module._run_brv_query("What do you know?") is None

    warning.assert_called_once_with(
        "ByteRover query failed with exit code %s | cwd=%s | stderr_preview=%s",
        23,
        cfg.resolved_cwd,
        "permission denied",
    )


def test_launch_brv_curate_warns_once_for_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ByteRoverConfig(enabled=True)
    warning = MagicMock()
    run = MagicMock(
        side_effect=byterover_module.subprocess.TimeoutExpired(
            cmd=["brv", "curate"],
            timeout=cfg.curate_timeout,
            stderr="still running",
        )
    )

    monkeypatch.setattr(byterover_module, "get_byterover_config", lambda: cfg)
    monkeypatch.setattr(byterover_module, "_WARNED_OPERATIONAL_FAILURES", set())
    monkeypatch.setattr(byterover_module.logger, "warning", warning)
    monkeypatch.setattr(byterover_module.subprocess, "run", run)

    byterover_module._launch_brv_curate("user", "agent")
    byterover_module._launch_brv_curate("user", "agent")

    assert run.call_args.kwargs["cwd"] == cfg.resolved_cwd
    warning.assert_called_once_with(
        "ByteRover curate timed out after %ss | cwd=%s | stderr_preview=%s",
        cfg.curate_timeout,
        cfg.resolved_cwd,
        "still running",
    )


@pytest.mark.anyio
async def test_async_before_agent_offloads_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_byterover(monkeypatch, enabled=True)
    to_thread = AsyncMock(return_value="Known context")
    monkeypatch.setattr(byterover_module.asyncio, "to_thread", to_thread)

    middleware = ByteRoverContextMiddleware()
    state = {"messages": [HumanMessage(content="How does this work?")]}

    result = await middleware.abefore_agent(state, runtime=SimpleNamespace())

    assert result == {"byterover_context": "Known context"}
    to_thread.assert_awaited_once_with(byterover_module._run_brv_query, "How does this work?")


def test_wrap_model_call_patches_request_without_mutating_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_byterover(monkeypatch, enabled=True)
    middleware = ByteRoverContextMiddleware()
    request = MagicMock()
    request.messages = [HumanMessage(content="Hi there", id="human-1")]
    request.state = {"byterover_context": "Known context"}
    patched_request = MagicMock()
    request.override.return_value = patched_request
    handler = MagicMock(return_value="response")

    result = middleware.wrap_model_call(request, handler)

    request.override.assert_called_once()
    patched_messages = request.override.call_args.kwargs["messages"]
    assert patched_messages is not request.messages
    assert len(patched_messages) == 2
    assert request.messages[0].content == "Hi there"
    assert patched_messages[0] is request.messages[0]
    assert patched_messages[1].type == "human"
    assert "**MUST READ: CONTEXT KNOWLEDGE ADDITION**:" in patched_messages[1].content
    assert "Trusted ByteRover context" in patched_messages[1].content
    assert "Known context" in patched_messages[1].content
    handler.assert_called_once_with(patched_request)
    assert result == "response"


def test_wrap_model_call_logs_user_and_context_previews(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_byterover(monkeypatch, enabled=True)
    info = MagicMock()
    monkeypatch.setattr(byterover_module.logger, "info", info)

    middleware = ByteRoverContextMiddleware()
    request = MagicMock()
    request.messages = [HumanMessage(content="Hi there", id="human-1")]
    request.state = {"byterover_context": "Known context"}
    request.override.return_value = MagicMock()

    middleware.wrap_model_call(request, MagicMock(return_value="response"))

    info.assert_any_call(
        "ByteRover context injected into model request | user_preview=%s | context_preview=%s | original_message_count=%s | patched_message_count=%s",
        "Hi there",
        (
            "**MUST READ: CONTEXT KNOWLEDGE ADDITION**: Trusted ByteRover context "
            "for the immediately preceding user message. Use this context before "
            "external search or assumptions. Known context"
        ),
        1,
        2,
    )


def test_prepare_brv_query_text_strips_legacy_and_current_context_blocks() -> None:
    legacy_message = HumanMessage(
        content=(
            "What do you know?\n"
            "<byterover_knowledge_context>\nLegacy context\n</byterover_knowledge_context>\n"
        )
    )
    current_message = HumanMessage(
        content=(
            "What do you know?\n"
            "**MUST READ: CONTEXT KNOWLEDGE ADDITION**:\n"
            "Trusted ByteRover context for the immediately preceding user message.\n"
            "Use this context before external search or assumptions.\n\n"
            "Current context\n"
        )
    )

    assert byterover_module._prepare_brv_query_text(legacy_message) == "What do you know?"
    assert byterover_module._prepare_brv_query_text(current_message) == "What do you know?"


def test_wrap_model_call_preserves_structured_human_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_byterover(monkeypatch, enabled=True)
    middleware = ByteRoverContextMiddleware()
    request = MagicMock()
    request.messages = [
        HumanMessage(
            content=[
                {"type": "text", "text": "Look at this image"},
                {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
            ],
            id="human-1",
        )
    ]
    request.state = {"byterover_context": "Known context"}
    patched_request = MagicMock()
    request.override.return_value = patched_request

    middleware.wrap_model_call(request, MagicMock(return_value="response"))

    patched_messages = request.override.call_args.kwargs["messages"]
    assert patched_messages[0] is request.messages[0]
    assert patched_messages[0].content == request.messages[0].content
    assert patched_messages[1].type == "human"
    assert "**MUST READ: CONTEXT KNOWLEDGE ADDITION**:" in patched_messages[1].content


def test_wrap_model_call_inserts_context_after_latest_user_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_byterover(monkeypatch, enabled=True)
    middleware = ByteRoverContextMiddleware()
    request = MagicMock()
    request.messages = [
        HumanMessage(content="Hi there", id="human-1"),
        AIMessage(content="Calling search"),
        ToolMessage(content="Search results", tool_call_id="tool-1"),
    ]
    request.state = {"byterover_context": "Known context"}
    patched_request = MagicMock()
    request.override.return_value = patched_request

    middleware.wrap_model_call(request, MagicMock(return_value="response"))

    patched_messages = request.override.call_args.kwargs["messages"]
    assert [message.type for message in patched_messages] == ["human", "human", "ai", "tool"]
    assert (
        patched_messages[1].content
        == "**MUST READ: CONTEXT KNOWLEDGE ADDITION**:\n"
        "Trusted ByteRover context for the immediately preceding user message.\n"
        "Use this context before external search or assumptions.\n\n"
        "Known context"
    )


@pytest.mark.anyio
async def test_async_wrap_model_call_patches_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_byterover(monkeypatch, enabled=True)
    middleware = ByteRoverContextMiddleware()
    request = MagicMock()
    request.messages = [HumanMessage(content="Hi there")]
    request.state = {"byterover_context": "Known context"}
    patched_request = MagicMock()
    request.override.return_value = patched_request
    handler = AsyncMock(return_value="response")

    result = await middleware.awrap_model_call(request, handler)

    request.override.assert_called_once()
    handler.assert_called_once_with(patched_request)
    assert result == "response"


def test_after_agent_curates_from_terminal_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_byterover(monkeypatch, enabled=True)
    curate = MagicMock()
    monkeypatch.setattr(byterover_module, "_launch_brv_curate", curate)

    tool_call = {"name": "search", "id": "tool-1", "args": {}}
    tool_ai = AIMessage(content="Calling search")
    tool_ai.tool_calls = [tool_call]

    middleware = ByteRoverContextMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Hi there"),
            tool_ai,
            ToolMessage(content="Search results", tool_call_id="tool-1"),
            AIMessage(content="Hello boss"),
        ]
    }

    result = middleware.after_agent(state, runtime=SimpleNamespace())

    assert result is None
    curate.assert_called_once_with("Hi there", "Hello boss")


@pytest.mark.anyio
async def test_async_after_agent_offloads_curation(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_byterover(monkeypatch, enabled=True)
    to_thread = AsyncMock(return_value=None)
    monkeypatch.setattr(byterover_module.asyncio, "to_thread", to_thread)

    tool_call = {"name": "search", "id": "tool-1", "args": {}}
    tool_ai = AIMessage(content="Calling search")
    tool_ai.tool_calls = [tool_call]

    middleware = ByteRoverContextMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Hi there"),
            tool_ai,
            ToolMessage(content="Search results", tool_call_id="tool-1"),
            AIMessage(content="Hello boss"),
        ]
    }

    result = await middleware.aafter_agent(state, runtime=SimpleNamespace())

    assert result is None
    to_thread.assert_awaited_once_with(byterover_module._launch_brv_curate, "Hi there", "Hello boss")


def test_agent_run_keeps_persisted_user_message_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_byterover(monkeypatch, enabled=True)
    monkeypatch.setattr(byterover_module, "_run_brv_query", lambda *_args, **_kwargs: "Known context")
    monkeypatch.setattr(byterover_module, "_launch_brv_curate", lambda *_args, **_kwargs: None)

    model = _RecordingModel()
    checkpointer = InMemorySaver()
    agent = create_agent(
        model=model,
        middleware=[ByteRoverContextMiddleware()],
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": "thread-1"}}

    result = agent.invoke(
        {"messages": [HumanMessage(content="Hi there", id="human-1")]},
        config=config,
    )
    state = agent.get_state(config)

    human_messages_seen_by_model = [
        message for message in model._seen_messages if getattr(message, "type", None) == "human"
    ]

    assert len(human_messages_seen_by_model) == 2
    assert human_messages_seen_by_model[0].content == "Hi there"
    assert "**MUST READ: CONTEXT KNOWLEDGE ADDITION**:" in human_messages_seen_by_model[1].content
    assert result["messages"][0].content == "Hi there"
    assert state.values["messages"][0].content == "Hi there"
    assert "byterover_context" not in result
    assert state.values.get("byterover_context") is None


def test_lead_agent_stack_injects_brv_context_with_thread_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        byterover_module,
        "get_byterover_config",
        lambda: ByteRoverConfig(enabled=True),
    )
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.get_byterover_config",
        lambda: ByteRoverConfig(enabled=True),
    )
    monkeypatch.setattr(byterover_module, "_run_brv_query", lambda *_args, **_kwargs: "Known context")
    monkeypatch.setattr(byterover_module, "_launch_brv_curate", lambda *_args, **_kwargs: None)

    mock_app_config = MagicMock()
    mock_app_config.token_usage.enabled = False
    mock_app_config.get_model_config.return_value = None
    mock_app_config.tool_search.enabled = False
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.get_app_config",
        lambda: mock_app_config,
    )

    model = _RecordingModel()
    config = {"configurable": {"thread_id": "thread-2", "model_name": "gemini-2.5-pro"}}
    agent = create_agent(
        model=model,
        tools=None,
        middleware=_build_middlewares(config, model_name="gemini-2.5-pro"),
        system_prompt="test",
        state_schema=ThreadState,
    )

    result = agent.invoke(
        {"messages": [HumanMessage(content="byterover deerflow integration", id="human-1")]},
        config=config,
    )

    human_messages_seen_by_model = [
        message for message in model._seen_messages if getattr(message, "type", None) == "human"
    ]

    assert len(human_messages_seen_by_model) == 2
    assert human_messages_seen_by_model[0].content == "byterover deerflow integration"
    assert human_messages_seen_by_model[1].content.startswith(
        "**MUST READ: CONTEXT KNOWLEDGE ADDITION**:"
    )
    assert "Known context" in human_messages_seen_by_model[1].content
    assert result["messages"][0].content == "byterover deerflow integration"
    assert "byterover_context" not in result

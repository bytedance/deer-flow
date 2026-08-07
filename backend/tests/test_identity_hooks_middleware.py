"""Tests for IdentityHooksMiddleware session-start scheduling."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage
from mcp.types import TextContent

from deerflow.agents.middlewares.identity_hooks_middleware import (
    IDENTITY_HOOKS_CONTEXT_KEY,
    IdentityHooksMiddleware,
    run_session_start_hooks,
)
from deerflow.agents.middlewares.tool_error_handling_middleware import (
    build_lead_runtime_middlewares,
    build_subagent_runtime_middlewares,
)
from deerflow.config.app_config import AppConfig, CircuitBreakerConfig
from deerflow.config.extensions_config import ExtensionsConfig, IdentityHookCall, IdentityHooksConfig, McpServerConfig
from deerflow.config.guardrails_config import GuardrailsConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig


def _lithtrix_hooks_config(*, enabled: bool = True, server_enabled: bool = True) -> ExtensionsConfig:
    return ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "lithtrix": {
                    "enabled": server_enabled,
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "lithtrix-mcp@0.20.2"],
                }
            },
            "identityHooks": {
                "enabled": enabled,
                "mcpServerRef": "lithtrix",
                "sessionStart": [
                    {"tool": "lithtrix_memory_context", "args": {"limit": 10}},
                    {"tool": "lithtrix_commons_read", "args": {"page": 1, "per_page": 20}},
                ],
            },
        }
    )


def _make_app_config() -> AppConfig:
    return AppConfig(
        models=[
            ModelConfig(
                name="test-model",
                display_name="test-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="test-model",
            )
        ],
        sandbox=SandboxConfig(use="test"),
        guardrails=GuardrailsConfig(enabled=False),
        circuit_breaker=CircuitBreakerConfig(),
    )


class _FakeCallToolResult:
    def __init__(self, text: str) -> None:
        self.content = [TextContent(type="text", text=text)]
        self.isError = False
        self.structuredContent = None


@pytest.mark.asyncio
async def test_run_session_start_hooks_absent_is_noop():
    config = ExtensionsConfig.model_validate({})
    with patch("deerflow.agents.middlewares.identity_hooks_middleware.get_session_pool") as pool_mock:
        result = await run_session_start_hooks(config=config, thread_id="t1", user_id="u1")
        pool_mock.assert_not_called()
    assert result is None


@pytest.mark.asyncio
async def test_run_session_start_hooks_disabled_is_noop():
    config = _lithtrix_hooks_config(enabled=False)
    with patch("deerflow.agents.middlewares.identity_hooks_middleware.get_session_pool") as pool_mock:
        result = await run_session_start_hooks(config=config, thread_id="t1", user_id="u1")
        pool_mock.assert_not_called()
    assert result is None


@pytest.mark.asyncio
async def test_run_session_start_hooks_invokes_tools_and_returns_sanitized_context():
    config = _lithtrix_hooks_config()
    session = AsyncMock()
    session.call_tool = AsyncMock(
        side_effect=[
            _FakeCallToolResult("memory: HOOK_CONTEXT_CANARY_memory"),
            _FakeCallToolResult("commons: HOOK_CONTEXT_CANARY_commons"),
        ]
    )
    pool = MagicMock()
    pool.get_session = AsyncMock(return_value=session)

    with patch("deerflow.agents.middlewares.identity_hooks_middleware.get_session_pool", return_value=pool):
        result = await run_session_start_hooks(config=config, thread_id="thread-1", user_id="user-1")

    pool.get_session.assert_awaited_once()
    assert session.call_tool.await_count == 2
    session.call_tool.assert_any_await("lithtrix_memory_context", {"limit": 10})
    session.call_tool.assert_any_await("lithtrix_commons_read", {"page": 1, "per_page": 20})
    assert result is not None
    assert "HOOK_CONTEXT_CANARY_memory" in result
    assert "HOOK_CONTEXT_CANARY_commons" in result
    assert "BEGIN EXTERNAL IDENTITY CONTEXT" in result


@pytest.mark.asyncio
async def test_run_session_start_hooks_disabled_server_warns(caplog: pytest.LogCaptureFixture):
    config = _lithtrix_hooks_config(server_enabled=False)
    with caplog.at_level(logging.WARNING):
        with patch("deerflow.agents.middlewares.identity_hooks_middleware.get_session_pool") as pool_mock:
            result = await run_session_start_hooks(config=config, thread_id="t1", user_id="u1")
            pool_mock.assert_not_called()
    assert result is None
    assert "identity_hooks_skip" in caplog.text
    assert "lithtrix" in caplog.text


@pytest.mark.asyncio
async def test_run_session_start_hooks_malformed_args_non_fatal(caplog: pytest.LogCaptureFixture):
    hooks = IdentityHooksConfig(
        enabled=True,
        mcp_server_ref="lithtrix",
        session_start=[
            IdentityHookCall(tool="lithtrix_memory_context", args={"limit": 10}),
            IdentityHookCall(tool="lithtrix_commons_read", args={"bad": "args"}),
        ],
    )
    config = ExtensionsConfig(
        mcp_servers={"lithtrix": McpServerConfig(enabled=True, type="stdio", command="npx", args=["-y", "x"])},
        identity_hooks=hooks,
    )
    session = AsyncMock()
    session.call_tool = AsyncMock(
        side_effect=[
            _FakeCallToolResult("HOOK_CONTEXT_CANARY_partial"),
            ValueError("invalid args"),
        ]
    )
    pool = MagicMock()
    pool.get_session = AsyncMock(return_value=session)

    with caplog.at_level(logging.ERROR):
        with patch("deerflow.agents.middlewares.identity_hooks_middleware.get_session_pool", return_value=pool):
            result = await run_session_start_hooks(config=config, thread_id="t1", user_id="u1")

    assert session.call_tool.await_count == 2
    assert "identity_hooks_call_failed" in caplog.text
    assert result is not None
    assert "HOOK_CONTEXT_CANARY_partial" in result


@pytest.mark.asyncio
async def test_middleware_injects_hook_context_into_model_messages():
    config = _lithtrix_hooks_config()
    middleware = IdentityHooksMiddleware(extensions_config=config)
    runtime = MagicMock()
    runtime.context = {"thread_id": "thread-a"}
    canary = "HOOK_CONTEXT_CANARY_injected"

    session = AsyncMock()
    session.call_tool = AsyncMock(return_value=_FakeCallToolResult(canary))
    pool = MagicMock()
    pool.get_session = AsyncMock(return_value=session)

    with patch("deerflow.agents.middlewares.identity_hooks_middleware.get_session_pool", return_value=pool):
        result = await middleware.abefore_agent({"messages": [HumanMessage("hi")], "identity_hooks": None}, runtime)

    assert result is not None
    assert result["identity_hooks"] == {"session_start_fired": True}
    assert len(result["messages"]) == 1
    message = result["messages"][0]
    assert canary in message.content
    assert message.additional_kwargs.get(IDENTITY_HOOKS_CONTEXT_KEY) is True
    assert message.additional_kwargs.get("hide_from_ui") is True


@pytest.mark.asyncio
async def test_middleware_fires_once_per_thread_across_instances():
    config = _lithtrix_hooks_config()
    middleware_a = IdentityHooksMiddleware(extensions_config=config)
    middleware_b = IdentityHooksMiddleware(extensions_config=config)
    runtime = MagicMock()
    runtime.context = {"thread_id": "thread-a"}
    state: dict[str, Any] = {"messages": [], "identity_hooks": None}

    with patch(
        "deerflow.agents.middlewares.identity_hooks_middleware.run_session_start_hooks",
        new_callable=AsyncMock,
        return_value="HOOK_CONTEXT_CANARY_once",
    ) as run_mock:
        first = await middleware_a.abefore_agent(state, runtime)
        assert first is not None
        state["identity_hooks"] = first["identity_hooks"]
        second = await middleware_b.abefore_agent(state, runtime)

    assert second is None
    run_mock.assert_awaited_once()


def test_identity_hooks_middleware_is_lead_only():
    app_config = _make_app_config()
    lead = build_lead_runtime_middlewares(app_config=app_config, lazy_init=False)
    subagent = build_subagent_runtime_middlewares(app_config=app_config, lazy_init=False)

    assert any(isinstance(m, IdentityHooksMiddleware) for m in lead)
    assert not any(isinstance(m, IdentityHooksMiddleware) for m in subagent)

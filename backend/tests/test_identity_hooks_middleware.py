"""Tests for IdentityHooksMiddleware session-start scheduling."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.agents.middlewares.identity_hooks_middleware import IdentityHooksMiddleware, run_session_start_hooks
from deerflow.config.extensions_config import ExtensionsConfig, IdentityHookCall, IdentityHooksConfig, McpServerConfig


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


@pytest.mark.asyncio
async def test_run_session_start_hooks_absent_is_noop():
    config = ExtensionsConfig.model_validate({})
    with patch("deerflow.agents.middlewares.identity_hooks_middleware.get_session_pool") as pool_mock:
        await run_session_start_hooks(config=config, thread_id="t1", user_id="u1")
        pool_mock.assert_not_called()


@pytest.mark.asyncio
async def test_run_session_start_hooks_disabled_is_noop():
    config = _lithtrix_hooks_config(enabled=False)
    with patch("deerflow.agents.middlewares.identity_hooks_middleware.get_session_pool") as pool_mock:
        await run_session_start_hooks(config=config, thread_id="t1", user_id="u1")
        pool_mock.assert_not_called()


@pytest.mark.asyncio
async def test_run_session_start_hooks_invokes_tools_with_args():
    config = _lithtrix_hooks_config()
    session = AsyncMock()
    pool = MagicMock()
    pool.get_session = AsyncMock(return_value=session)

    with patch("deerflow.agents.middlewares.identity_hooks_middleware.get_session_pool", return_value=pool):
        await run_session_start_hooks(config=config, thread_id="thread-1", user_id="user-1")

    pool.get_session.assert_awaited_once()
    assert session.call_tool.await_count == 2
    session.call_tool.assert_any_await("lithtrix_memory_context", {"limit": 10})
    session.call_tool.assert_any_await("lithtrix_commons_read", {"page": 1, "per_page": 20})


@pytest.mark.asyncio
async def test_run_session_start_hooks_disabled_server_warns(caplog: pytest.LogCaptureFixture):
    config = _lithtrix_hooks_config(server_enabled=False)
    with caplog.at_level(logging.WARNING):
        with patch("deerflow.agents.middlewares.identity_hooks_middleware.get_session_pool") as pool_mock:
            await run_session_start_hooks(config=config, thread_id="t1", user_id="u1")
            pool_mock.assert_not_called()
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
    session.call_tool = AsyncMock(side_effect=[None, ValueError("invalid args")])
    pool = MagicMock()
    pool.get_session = AsyncMock(return_value=session)

    with caplog.at_level(logging.ERROR):
        with patch("deerflow.agents.middlewares.identity_hooks_middleware.get_session_pool", return_value=pool):
            await run_session_start_hooks(config=config, thread_id="t1", user_id="u1")

    assert session.call_tool.await_count == 2
    assert "identity_hooks_call_failed" in caplog.text


@pytest.mark.asyncio
async def test_middleware_fires_once_per_thread():
    config = _lithtrix_hooks_config()
    middleware = IdentityHooksMiddleware(extensions_config=config)
    runtime = MagicMock()
    runtime.context = {"thread_id": "thread-a"}

    with patch(
        "deerflow.agents.middlewares.identity_hooks_middleware.run_session_start_hooks",
        new_callable=AsyncMock,
    ) as run_mock:
        await middleware.abefore_agent({}, runtime)
        await middleware.abefore_agent({}, runtime)
        run_mock.assert_awaited_once()

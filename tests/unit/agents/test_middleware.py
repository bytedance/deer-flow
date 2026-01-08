# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.agents import DynamicPromptMiddleware, PreModelHookMiddleware


@pytest.fixture
def mock_runtime():
    """Mock Runtime object."""
    runtime = MagicMock()
    runtime.config = {}
    return runtime


@pytest.fixture
def mock_state():
    """Mock state object."""
    return {
        "messages": [HumanMessage(content="Test message")],
        "context": "Test context",
    }


@pytest.fixture
def mock_messages():
    """Mock messages returned by apply_prompt_template."""
    return [
        SystemMessage(content="Test system prompt"),
        HumanMessage(content="Test human message"),
    ]


class TestDynamicPromptMiddleware:
    """Tests for DynamicPromptMiddleware class."""

    def test_init(self):
        """Test middleware initialization."""
        middleware = DynamicPromptMiddleware("test_template", locale="zh-CN")
        assert middleware.prompt_template == "test_template"
        assert middleware.locale == "zh-CN"

    def test_init_default_locale(self):
        """Test middleware initialization with default locale."""
        middleware = DynamicPromptMiddleware("test_template")
        assert middleware.prompt_template == "test_template"
        assert middleware.locale == "en-US"

    @patch("src.agents.agents.apply_prompt_template")
    def test_before_model_success(
        self, mock_apply_template, mock_state, mock_runtime, mock_messages
    ):
        """Test before_model successfully applies prompt template."""
        mock_apply_template.return_value = mock_messages
        middleware = DynamicPromptMiddleware("test_template", locale="en-US")

        result = middleware.before_model(mock_state, mock_runtime)

        # Verify apply_prompt_template was called with correct arguments
        mock_apply_template.assert_called_once_with(
            "test_template", mock_state, locale="en-US"
        )

        # Verify system message is returned
        assert result == {"messages": [mock_messages[0]]}
        assert result["messages"][0].content == "Test system prompt"

    @patch("src.agents.agents.apply_prompt_template")
    def test_before_model_empty_messages(
        self, mock_apply_template, mock_state, mock_runtime
    ):
        """Test before_model with empty message list."""
        mock_apply_template.return_value = []
        middleware = DynamicPromptMiddleware("test_template")

        result = middleware.before_model(mock_state, mock_runtime)

        # Should return None when no messages are rendered
        assert result is None

    @patch("src.agents.agents.apply_prompt_template")
    def test_before_model_none_messages(
        self, mock_apply_template, mock_state, mock_runtime
    ):
        """Test before_model when apply_prompt_template returns None."""
        mock_apply_template.return_value = None
        middleware = DynamicPromptMiddleware("test_template")

        result = middleware.before_model(mock_state, mock_runtime)

        # Should return None when template returns None
        assert result is None

    @patch("src.agents.agents.apply_prompt_template")
    @patch("src.agents.agents.logger")
    def test_before_model_exception_handling(
        self, mock_logger, mock_apply_template, mock_state, mock_runtime
    ):
        """Test before_model handles exceptions gracefully."""
        mock_apply_template.side_effect = ValueError("Template rendering failed")
        middleware = DynamicPromptMiddleware("test_template")

        result = middleware.before_model(mock_state, mock_runtime)

        # Should return None on exception
        assert result is None

        # Should log error with exc_info
        mock_logger.error.assert_called_once()
        error_message = mock_logger.error.call_args[0][0]
        assert "Failed to apply prompt template in before_model" in error_message
        assert mock_logger.error.call_args[1]["exc_info"] is True

    @patch("src.agents.agents.apply_prompt_template")
    def test_before_model_with_different_locale(
        self, mock_apply_template, mock_state, mock_runtime, mock_messages
    ):
        """Test before_model with different locale."""
        mock_apply_template.return_value = mock_messages
        middleware = DynamicPromptMiddleware("test_template", locale="zh-CN")

        result = middleware.before_model(mock_state, mock_runtime)

        # Verify locale is passed correctly
        mock_apply_template.assert_called_once_with(
            "test_template", mock_state, locale="zh-CN"
        )
        assert result == {"messages": [mock_messages[0]]}

    @pytest.mark.asyncio
    @patch("src.agents.agents.apply_prompt_template")
    async def test_abefore_model(
        self, mock_apply_template, mock_state, mock_runtime, mock_messages
    ):
        """Test async version of before_model."""
        mock_apply_template.return_value = mock_messages
        middleware = DynamicPromptMiddleware("test_template")

        result = await middleware.abefore_model(mock_state, mock_runtime)

        # Should call the sync version and return same result
        assert result == {"messages": [mock_messages[0]]}
        mock_apply_template.assert_called_once_with(
            "test_template", mock_state, locale="en-US"
        )


class TestPreModelHookMiddleware:
    """Tests for PreModelHookMiddleware class."""

    def test_init(self):
        """Test middleware initialization."""
        hook = Mock()
        middleware = PreModelHookMiddleware(hook)
        assert middleware._pre_model_hook == hook

    def test_before_model_with_sync_hook(self, mock_state, mock_runtime):
        """Test before_model with synchronous hook."""
        hook = Mock(return_value={"custom_data": "test"})
        middleware = PreModelHookMiddleware(hook)

        result = middleware.before_model(mock_state, mock_runtime)

        # Verify hook was called with correct arguments
        hook.assert_called_once_with(mock_state, mock_runtime)
        assert result == {"custom_data": "test"}

    def test_before_model_with_none_hook(self, mock_state, mock_runtime):
        """Test before_model when hook is None."""
        middleware = PreModelHookMiddleware(None)

        result = middleware.before_model(mock_state, mock_runtime)

        # Should return None when hook is None
        assert result is None

    def test_before_model_hook_returns_none(self, mock_state, mock_runtime):
        """Test before_model when hook returns None."""
        hook = Mock(return_value=None)
        middleware = PreModelHookMiddleware(hook)

        result = middleware.before_model(mock_state, mock_runtime)

        hook.assert_called_once_with(mock_state, mock_runtime)
        assert result is None

    @patch("src.agents.agents.logger")
    def test_before_model_hook_exception(
        self, mock_logger, mock_state, mock_runtime
    ):
        """Test before_model handles hook exceptions gracefully."""
        hook = Mock(side_effect=RuntimeError("Hook execution failed"))
        middleware = PreModelHookMiddleware(hook)

        result = middleware.before_model(mock_state, mock_runtime)

        # Should return None on exception
        assert result is None

        # Should log error with exc_info
        mock_logger.error.assert_called_once()
        error_message = mock_logger.error.call_args[0][0]
        assert "Pre-model hook execution failed in before_model" in error_message
        assert mock_logger.error.call_args[1]["exc_info"] is True

    @pytest.mark.asyncio
    async def test_abefore_model_with_async_hook(self, mock_state, mock_runtime):
        """Test async before_model with async hook."""
        async def async_hook(state, runtime):
            await asyncio.sleep(0.001)  # Simulate async work
            return {"async_data": "test"}

        middleware = PreModelHookMiddleware(async_hook)

        result = await middleware.abefore_model(mock_state, mock_runtime)

        assert result == {"async_data": "test"}

    @pytest.mark.asyncio
    @patch("src.agents.agents.asyncio.to_thread")
    async def test_abefore_model_with_sync_hook(
        self, mock_to_thread, mock_state, mock_runtime
    ):
        """Test async before_model with synchronous hook uses asyncio.to_thread."""
        hook = Mock(return_value={"sync_data": "test"})
        mock_to_thread.return_value = {"sync_data": "test"}
        middleware = PreModelHookMiddleware(hook)

        result = await middleware.abefore_model(mock_state, mock_runtime)

        # Verify asyncio.to_thread was called with the sync hook
        mock_to_thread.assert_called_once_with(hook, mock_state, mock_runtime)
        assert result == {"sync_data": "test"}

    @pytest.mark.asyncio
    async def test_abefore_model_with_none_hook(self, mock_state, mock_runtime):
        """Test async before_model when hook is None."""
        middleware = PreModelHookMiddleware(None)

        result = await middleware.abefore_model(mock_state, mock_runtime)

        # Should return None when hook is None
        assert result is None

    @pytest.mark.asyncio
    @patch("src.agents.agents.logger")
    async def test_abefore_model_async_hook_exception(
        self, mock_logger, mock_state, mock_runtime
    ):
        """Test async before_model handles async hook exceptions gracefully."""
        async def failing_hook(state, runtime):
            raise ValueError("Async hook failed")

        middleware = PreModelHookMiddleware(failing_hook)

        result = await middleware.abefore_model(mock_state, mock_runtime)

        # Should return None on exception
        assert result is None

        # Should log error with exc_info
        mock_logger.error.assert_called_once()
        error_message = mock_logger.error.call_args[0][0]
        assert "Pre-model hook execution failed in abefore_model" in error_message
        assert mock_logger.error.call_args[1]["exc_info"] is True

    @pytest.mark.asyncio
    @patch("src.agents.agents.asyncio.to_thread")
    @patch("src.agents.agents.logger")
    async def test_abefore_model_sync_hook_exception(
        self, mock_logger, mock_to_thread, mock_state, mock_runtime
    ):
        """Test async before_model handles sync hook exceptions gracefully."""
        hook = Mock()
        mock_to_thread.side_effect = RuntimeError("Thread execution failed")
        middleware = PreModelHookMiddleware(hook)

        result = await middleware.abefore_model(mock_state, mock_runtime)

        # Should return None on exception
        assert result is None

        # Should log error with exc_info
        mock_logger.error.assert_called_once()
        error_message = mock_logger.error.call_args[0][0]
        assert "Pre-model hook execution failed in abefore_model" in error_message
        assert mock_logger.error.call_args[1]["exc_info"] is True

    @pytest.mark.asyncio
    async def test_abefore_model_sync_hook_actual_execution(
        self, mock_state, mock_runtime
    ):
        """Test async before_model actually runs sync hook in thread pool."""
        # Track if hook was called
        hook_called = []

        def sync_hook(state, runtime):
            hook_called.append(True)
            return {"data": "from_sync_hook"}

        middleware = PreModelHookMiddleware(sync_hook)

        result = await middleware.abefore_model(mock_state, mock_runtime)

        # Verify hook was called and result returned
        assert len(hook_called) == 1
        assert result == {"data": "from_sync_hook"}

    @pytest.mark.asyncio
    async def test_abefore_model_detects_coroutine_function(
        self, mock_state, mock_runtime
    ):
        """Test that abefore_model correctly detects async vs sync functions."""
        # Test with async function
        async def async_hook(state, runtime):
            return {"type": "async"}

        # Test with sync function
        def sync_hook(state, runtime):
            return {"type": "sync"}

        async_middleware = PreModelHookMiddleware(async_hook)
        sync_middleware = PreModelHookMiddleware(sync_hook)

        # Both should execute successfully
        async_result = await async_middleware.abefore_model(mock_state, mock_runtime)
        sync_result = await sync_middleware.abefore_model(mock_state, mock_runtime)

        assert async_result == {"type": "async"}
        assert sync_result == {"type": "sync"}

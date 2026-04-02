"""Tests for automatic thread title generation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.title_middleware import TitleMiddleware
from deerflow.config.title_config import TitleConfig, get_title_config, set_title_config

from backend.tests.title_config_test_utils import clone_title_config


class TestTitleConfig:
    """Tests for TitleConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = TitleConfig()
        assert config.enabled is True
        assert config.max_words == 6
        assert config.max_chars == 60
        assert config.model_name is None

    def test_custom_config(self):
        """Test custom configuration."""
        config = TitleConfig(
            enabled=False,
            max_words=10,
            max_chars=100,
            model_name="gpt-4",
        )
        assert config.enabled is False
        assert config.max_words == 10
        assert config.max_chars == 100
        assert config.model_name == "gpt-4"

    def test_config_validation(self):
        """Test configuration validation."""
        # max_words should be between 1 and 20
        with pytest.raises(ValueError):
            TitleConfig(max_words=0)
        with pytest.raises(ValueError):
            TitleConfig(max_words=21)

        # max_chars should be between 10 and 200
        with pytest.raises(ValueError):
            TitleConfig(max_chars=5)
        with pytest.raises(ValueError):
            TitleConfig(max_chars=201)

    def test_get_set_config(self):
        """Test global config getter and setter."""
        original_config = get_title_config()

        # Set new config
        new_config = TitleConfig(enabled=False, max_words=10)
        set_title_config(new_config)

        # Verify it was set
        assert get_title_config().enabled is False
        assert get_title_config().max_words == 10

        # Restore original config
        set_title_config(original_config)


class TestTitleMiddleware:
    """Tests for TitleMiddleware."""

    def setup_method(self):
        self._original_config = clone_title_config(get_title_config())

    def teardown_method(self):
        set_title_config(self._original_config)

    def test_middleware_initialization(self):
        """Test middleware can be initialized."""
        middleware = TitleMiddleware()
        assert middleware is not None
        assert middleware.state_schema is not None

    def test_after_model_generates_title_for_first_complete_exchange(self, monkeypatch):
        middleware = TitleMiddleware()
        runtime = Runtime(context={"thread_id": "thread-123"})
        fake_model = MagicMock()
        fake_model.invoke.return_value = MagicMock(content='"Code review summary"')
        monkeypatch.setattr(
            "deerflow.agents.middlewares.title_middleware.create_chat_model",
            lambda **kwargs: fake_model,
        )

        state = {
            "messages": [
                HumanMessage(content="Please review this patch"),
                AIMessage(content="I will inspect the diff first."),
            ]
        }

        result = middleware.after_model(state, runtime)

        assert result == {"title": "Code review summary"}
        fake_model.invoke.assert_called_once()

    def test_after_model_skips_generation_when_title_already_exists(self, monkeypatch):
        middleware = TitleMiddleware()
        runtime = Runtime(context={"thread_id": "thread-123"})
        create_model = MagicMock()
        monkeypatch.setattr(
            "deerflow.agents.middlewares.title_middleware.create_chat_model",
            create_model,
        )

        state = {
            "messages": [
                HumanMessage(content="Please review this patch"),
                AIMessage(content="I will inspect the diff first."),
            ],
            "title": "Existing title",
        }

        result = middleware.after_model(state, runtime)

        assert result is None
        create_model.assert_not_called()

    def test_aafter_model_generates_fallback_title_when_model_fails(self, monkeypatch):
        middleware = TitleMiddleware()
        runtime = Runtime(context={"thread_id": "thread-async"})
        fake_model = MagicMock()
        fake_model.ainvoke = AsyncMock(side_effect=RuntimeError("upstream failed"))
        monkeypatch.setattr(
            "deerflow.agents.middlewares.title_middleware.create_chat_model",
            lambda **kwargs: fake_model,
        )

        user_message = "This is a long discussion about improving thread title fallback behavior"
        state = {
            "messages": [
                HumanMessage(content=user_message),
                AIMessage(content="Let me check the middleware path."),
            ]
        }

        result = asyncio.run(middleware.aafter_model(state, runtime))

        assert result is not None
        assert result["title"].startswith(user_message[: get_title_config().max_chars])
        assert len(result["title"]) <= get_title_config().max_chars
        fake_model.ainvoke.assert_called_once()

    def test_aafter_model_respects_disabled_config(self, monkeypatch):
        middleware = TitleMiddleware()
        runtime = Runtime(context={"thread_id": "thread-disabled"})
        disabled_config = clone_title_config(get_title_config())
        disabled_config.enabled = False
        set_title_config(disabled_config)

        create_model = MagicMock()
        monkeypatch.setattr(
            "deerflow.agents.middlewares.title_middleware.create_chat_model",
            create_model,
        )

        state = {
            "messages": [
                HumanMessage(content="Summarize this runtime issue"),
                AIMessage(content="Sure, I will inspect it."),
            ]
        }

        result = asyncio.run(middleware.aafter_model(state, runtime))

        assert result is None
        create_model.assert_not_called()

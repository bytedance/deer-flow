"""Tests for automatic thread title generation."""

import pytest

from src.agents.middlewares.title_middleware import TitleMiddleware
from src.config.title_config import TitleConfig, get_title_config, set_title_config


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


class MockMessage:
    """Minimal mock for LangChain message objects."""

    def __init__(self, msg_type: str, content: str = ""):
        self.type = msg_type
        self.content = content


class TestTitleMiddleware:
    """Tests for TitleMiddleware."""

    def test_middleware_initialization(self):
        """Test middleware can be initialized."""
        middleware = TitleMiddleware()
        assert middleware is not None
        assert middleware.state_schema is not None

    def test_should_generate_title_first_user_message(self):
        """Title should be generated on first turn with a single user message."""
        middleware = TitleMiddleware()
        state = {
            "messages": [MockMessage("human", "Hello")],
        }
        assert middleware._should_generate_title(state) is True

    def test_should_not_generate_title_when_title_exists(self):
        """Title should not be regenerated if one already exists."""
        middleware = TitleMiddleware()
        state = {
            "messages": [MockMessage("human", "Hello")],
            "title": "Existing Title",
        }
        assert middleware._should_generate_title(state) is False

    def test_should_not_generate_title_no_messages(self):
        """Title should not be generated when there are no messages."""
        middleware = TitleMiddleware()
        assert middleware._should_generate_title({"messages": []}) is False

    def test_should_not_generate_title_multiple_user_messages(self):
        """Title should not be generated on subsequent turns."""
        middleware = TitleMiddleware()
        state = {
            "messages": [
                MockMessage("human", "Hello"),
                MockMessage("ai", "Hi there!"),
                MockMessage("human", "How are you?"),
            ],
        }
        assert middleware._should_generate_title(state) is False

    def test_should_not_generate_title_when_disabled(self):
        """Title should not be generated when config is disabled."""
        original_config = get_title_config()
        set_title_config(TitleConfig(enabled=False))
        try:
            middleware = TitleMiddleware()
            state = {"messages": [MockMessage("human", "Hello")]}
            assert middleware._should_generate_title(state) is False
        finally:
            set_title_config(original_config)

    def test_should_generate_title_with_user_only(self):
        """Title generation no longer requires an assistant response."""
        middleware = TitleMiddleware()
        # Single user message without assistant response — should still trigger
        state = {"messages": [MockMessage("human", "Explain quantum computing")]}
        assert middleware._should_generate_title(state) is True

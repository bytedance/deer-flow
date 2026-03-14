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


class TestTitleMiddleware:
    """Tests for TitleMiddleware."""

    def test_middleware_initialization(self):
        """Test middleware can be initialized."""
        middleware = TitleMiddleware()
        assert middleware is not None
        assert middleware.state_schema is not None

    def test_should_generate_title_first_turn(self):
        """Test title generation trigger for first turn."""
        # Set up config
        config = TitleConfig(enabled=True)
        set_title_config(config)

        middleware = TitleMiddleware()

        # First turn: only user message, no title - should NOT generate
        state = TitleMiddlewareState(
            messages=[{"type": "human", "content": "Hello"}],
            title=None
        )
        assert middleware._should_generate_title(state) is False

        # Second turn: user + assistant message - SHOULD generate
        state = TitleMiddlewareState(
            messages=[
                {"type": "human", "content": "Hello"},
                {"type": "ai", "content": "Hi there!"}
            ],
            title=None
        )
        assert middleware._should_generate_title(state) is True

    def test_should_generate_title_disabled(self):
        """Test title generation is disabled when config is disabled."""
        config = TitleConfig(enabled=False)
        set_title_config(config)

        middleware = TitleMiddleware()

        state = TitleMiddlewareState(
            messages=[
                {"type": "human", "content": "Hello"},
                {"type": "ai", "content": "Hi there!"}
            ],
            title=None
        )
        assert middleware._should_generate_title(state) is False

    def test_should_generate_title_existing_title(self):
        """Test title generation is skipped when title already exists."""
        config = TitleConfig(enabled=True)
        set_title_config(config)

        middleware = TitleMiddleware()

        state = TitleMiddlewareState(
            messages=[
                {"type": "human", "content": "Hello"},
                {"type": "ai", "content": "Hi there!"}
            ],
            title="Existing Title"
        )
        assert middleware._should_generate_title(state) is False

    def test_should_generate_title_multiple_turns(self):
        """Test title generation is skipped after first turn."""
        config = TitleConfig(enabled=True)
        set_title_config(config)

        middleware = TitleMiddleware()

        # Multiple turns - should NOT generate (already past first turn)
        state = TitleMiddlewareState(
            messages=[
                {"type": "human", "content": "Hello"},
                {"type": "ai", "content": "Hi there!"},
                {"type": "human", "content": "Tell me more"},
                {"type": "ai", "content": "Sure!"}
            ],
            title=None
        )
        assert middleware._should_generate_title(state) is False


class TestTitleGenerationFallback:
    """Tests for title generation fallback behavior."""

    def test_fallback_to_user_message(self):
        """Test fallback uses first part of user message when LLM fails."""
        import asyncio
        from unittest.mock import patch, AsyncMock

        config = TitleConfig(enabled=True, max_chars=50)
        set_title_config(config)

        middleware = TitleMiddleware()

        state = TitleMiddlewareState(
            messages=[
                {"type": "human", "content": "This is a very long user message that should be truncated"},
                {"type": "ai", "content": "Response"}
            ],
            title=None
        )

        # Mock the model to raise an exception
        with patch('src.agents.middlewares.title_middleware.create_chat_model') as mock_model:
            mock_model.return_value = AsyncMock()
            mock_model.return_value.ainvoke = AsyncMock(side_effect=Exception("LLM Error"))

            # Run the async method
            result = asyncio.get_event_loop().run_until_complete(
                middleware._generate_title(state)
            )

            # Should fallback to user message truncated
            assert "This is a very long user message" in result
            assert len(result) <= 53  # 50 chars + "..."

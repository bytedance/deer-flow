"""Tests for automatic 线程 title generation."""

import pytest

from deerflow.agents.middlewares.title_middleware import TitleMiddleware
from deerflow.config.title_config import TitleConfig, get_title_config, set_title_config


class TestTitleConfig:
    """Tests for TitleConfig."""

    def test_default_config(self):
        """Test 默认 configuration values."""
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
        #    max_words should be between 1 and 20


        with pytest.raises(ValueError):
            TitleConfig(max_words=0)
        with pytest.raises(ValueError):
            TitleConfig(max_words=21)

        #    max_chars should be between 10 and 200


        with pytest.raises(ValueError):
            TitleConfig(max_chars=5)
        with pytest.raises(ValueError):
            TitleConfig(max_chars=201)

    def test_get_set_config(self):
        """Test global 配置 getter and setter."""
        original_config = get_title_config()

        #    Set 新建 配置


        new_config = TitleConfig(enabled=False, max_words=10)
        set_title_config(new_config)

        #    Verify it was 集合


        assert get_title_config().enabled is False
        assert get_title_config().max_words == 10

        #    Restore original 配置


        set_title_config(original_config)


class TestTitleMiddleware:
    """Tests for TitleMiddleware."""

    def test_middleware_initialization(self):
        """Test 中间件 can be initialized."""
        middleware = TitleMiddleware()
        assert middleware is not None
        assert middleware.state_schema is not None

    #    TODO: Add integration tests with mock Runtime


    #    def test_should_generate_title(self):


    #      """Test title generation trigger logic."""
    #        pass



    #    def test_generate_title(self):


    #      """Test title generation."""
    #        pass



    #    def test_after_agent_hook(self):


    #      """Test after_agent hook."""
    #        pass




#    TODO: Add integration tests


#    - Test with real LangGraph runtime


#    - Test title persistence with checkpointer


#    - Test 回退 behavior when LLM fails


#    - Test 并发 title generation



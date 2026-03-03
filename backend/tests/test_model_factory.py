"""Tests for model factory: RuntimeModelSpec, _runtime_tier_settings, _create_runtime_model, create_chat_model."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.models.factory import (
    ANTHROPIC_DEFAULT_THINKING_BUDGET_TOKENS,
    PROVIDER_BASE_URLS,
    RuntimeModelSpec,
    _create_runtime_model,
    _runtime_tier_settings,
    create_chat_model,
)


# ---------------------------------------------------------------------------
# RuntimeModelSpec
# ---------------------------------------------------------------------------
class TestRuntimeModelSpec:
    """Tests for the RuntimeModelSpec pydantic model."""

    def test_minimal_fields(self) -> None:
        spec = RuntimeModelSpec(provider="openai", model_id="gpt-4o")
        assert spec.provider == "openai"
        assert spec.model_id == "gpt-4o"
        assert spec.api_key is None
        assert spec.tier is None

    def test_from_dict(self) -> None:
        data = {"provider": "anthropic", "model_id": "claude-opus-4-6", "api_key": "sk-test"}
        spec = RuntimeModelSpec.model_validate(data)
        assert spec.provider == "anthropic"
        assert spec.api_key == "sk-test"

    def test_extra_fields_allowed(self) -> None:
        spec = RuntimeModelSpec(provider="openai", model_id="gpt-4o", custom_field="value")
        assert spec.custom_field == "value"


# ---------------------------------------------------------------------------
# _runtime_tier_settings
# ---------------------------------------------------------------------------
class TestRuntimeTierSettings:
    """Tests for _runtime_tier_settings()."""

    def test_no_thinking_returns_empty(self) -> None:
        spec = RuntimeModelSpec(provider="openai", model_id="gpt-4o", tier="reasoning-high")
        assert _runtime_tier_settings(spec, thinking_enabled=False) == {}

    def test_no_tier_returns_empty(self) -> None:
        spec = RuntimeModelSpec(provider="openai", model_id="gpt-4o")
        assert _runtime_tier_settings(spec, thinking_enabled=True) == {}

    def test_openai_reasoning_effort(self) -> None:
        spec = RuntimeModelSpec(provider="openai", model_id="o1", tier="reasoning-high")
        result = _runtime_tier_settings(spec, thinking_enabled=True)
        assert result == {"reasoning": {"effort": "high", "summary": "auto"}}

    def test_openai_reasoning_medium(self) -> None:
        spec = RuntimeModelSpec(provider="openai", model_id="o1", tier="reasoning-medium")
        result = _runtime_tier_settings(spec, thinking_enabled=True)
        assert result["reasoning"]["effort"] == "medium"

    def test_anthropic_thinking_tier_uses_enabled_budget(self) -> None:
        spec = RuntimeModelSpec(provider="anthropic", model_id="claude-opus-4-6", tier="thinking")
        result = _runtime_tier_settings(spec, thinking_enabled=True)
        assert result == {
            "thinking": {
                "type": "enabled",
                "budget_tokens": ANTHROPIC_DEFAULT_THINKING_BUDGET_TOKENS,
            }
        }

    def test_anthropic_thinking_enabled(self) -> None:
        spec = RuntimeModelSpec(provider="anthropic", model_id="claude-3-5-sonnet", tier="thinking")
        result = _runtime_tier_settings(spec, thinking_enabled=True)
        assert result == {"thinking": {"type": "enabled", "budget_tokens": 10000}}

    def test_deepseek_thinking(self) -> None:
        spec = RuntimeModelSpec(provider="deepseek", model_id="deepseek-v3", tier="thinking")
        result = _runtime_tier_settings(spec, thinking_enabled=True)
        assert result == {"extra_body": {"thinking": {"type": "enabled"}}}

    def test_deepseek_reasoner(self) -> None:
        spec = RuntimeModelSpec(provider="deepseek", model_id="deepseek-reasoner", tier=None)
        # tier is None but model ends with "reasoner"
        result = _runtime_tier_settings(spec, thinking_enabled=True)
        # No tier, so returns {} (the reasoner check requires thinking but no tier match first)
        assert result == {}

    def test_kimi_thinking(self) -> None:
        spec = RuntimeModelSpec(provider="kimi", model_id="moonshot-v1", tier="thinking")
        result = _runtime_tier_settings(spec, thinking_enabled=True)
        assert result == {"extra_body": {"thinking": {"type": "enabled"}}}

    def test_unknown_provider_returns_empty(self) -> None:
        spec = RuntimeModelSpec(provider="unknown", model_id="model", tier="thinking")
        result = _runtime_tier_settings(spec, thinking_enabled=True)
        assert result == {}


# ---------------------------------------------------------------------------
# _create_runtime_model
# ---------------------------------------------------------------------------
class TestCreateRuntimeModel:
    """Tests for _create_runtime_model()."""

    def test_unsupported_provider_raises(self) -> None:
        spec = RuntimeModelSpec(provider="unsupported", model_id="model", api_key="key")
        with pytest.raises(ValueError, match="Unsupported provider"):
            _create_runtime_model(spec, thinking_enabled=False)

    def test_no_api_key_raises(self) -> None:
        spec = RuntimeModelSpec(provider="openai", model_id="gpt-4o", api_key="")
        with pytest.raises(ValueError, match="requires a non-empty api_key"):
            _create_runtime_model(spec, thinking_enabled=False)

    def test_whitespace_api_key_raises(self) -> None:
        spec = RuntimeModelSpec(provider="openai", model_id="gpt-4o", api_key="   ")
        with pytest.raises(ValueError, match="requires a non-empty api_key"):
            _create_runtime_model(spec, thinking_enabled=False)

    @patch("src.models.factory.ChatOpenAI")
    def test_openai_model(self, mock_cls) -> None:
        mock_cls.return_value = MagicMock()
        spec = RuntimeModelSpec(provider="openai", model_id="gpt-4o", api_key="sk-test")
        result = _create_runtime_model(spec, thinking_enabled=False)
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["api_key"] == "sk-test"
        assert call_kwargs["base_url"] == PROVIDER_BASE_URLS["openai"]

    @patch("src.models.factory.ChatAnthropic")
    def test_anthropic_model(self, mock_cls) -> None:
        mock_cls.return_value = MagicMock()
        spec = RuntimeModelSpec(provider="anthropic", model_id="claude-3-5-sonnet", api_key="sk-ant-test")
        result = _create_runtime_model(spec, thinking_enabled=False)
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model"] == "claude-3-5-sonnet"

    @patch("src.models.factory.PatchedChatDeepSeek")
    def test_deepseek_model(self, mock_cls) -> None:
        mock_cls.return_value = MagicMock()
        spec = RuntimeModelSpec(provider="deepseek", model_id="deepseek-v3", api_key="sk-ds-test")
        result = _create_runtime_model(spec, thinking_enabled=False)
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model"] == "deepseek-v3"
        assert "api_base" in call_kwargs

    @patch("src.models.factory.PatchedChatOpenAI")
    def test_epfl_rcp_model(self, mock_cls) -> None:
        mock_cls.return_value = MagicMock()
        spec = RuntimeModelSpec(provider="epfl-rcp", model_id="mixtral", api_key="key")
        result = _create_runtime_model(spec, thinking_enabled=False)
        mock_cls.assert_called_once()

    @patch("src.models.factory.ChatOpenAI")
    def test_gemini_uses_chatopenai(self, mock_cls) -> None:
        mock_cls.return_value = MagicMock()
        spec = RuntimeModelSpec(provider="gemini", model_id="gemini-pro", api_key="key")
        result = _create_runtime_model(spec, thinking_enabled=False)
        mock_cls.assert_called_once()
        assert mock_cls.call_args[1]["base_url"] == PROVIDER_BASE_URLS["gemini"]

    def test_api_key_from_stored_keys(self) -> None:
        spec = RuntimeModelSpec(provider="openai", model_id="gpt-4o", api_key="", user_id="user-1")
        with patch("src.security.api_key_store.get_api_key", return_value="stored-key") as mock_get:
            with patch("src.models.factory.ChatOpenAI", return_value=MagicMock()) as mock_cls:
                _create_runtime_model(spec, thinking_enabled=False)
                mock_get.assert_called_once_with("user-1", "openai")
                assert mock_cls.call_args[1]["api_key"] == "stored-key"

    def test_custom_base_url(self) -> None:
        spec = RuntimeModelSpec(provider="openai", model_id="gpt-4o", api_key="key", base_url="https://custom.api.com/v1")
        with patch("src.models.factory.ChatOpenAI", return_value=MagicMock()) as mock_cls:
            _create_runtime_model(spec, thinking_enabled=False)
            assert mock_cls.call_args[1]["base_url"] == "https://custom.api.com/v1"

    @patch("src.models.factory.ChatAnthropic")
    def test_anthropic_thinking_adjusts_max_tokens(self, mock_cls) -> None:
        mock_cls.return_value = MagicMock()
        spec = RuntimeModelSpec(provider="anthropic", model_id="claude-3-5-sonnet", api_key="key", tier="thinking")
        _create_runtime_model(spec, thinking_enabled=True)
        call_kwargs = mock_cls.call_args[1]
        # thinking budget_tokens is 10000, which is less than default 128000 max_tokens
        assert call_kwargs["max_tokens"] >= 10000

    @patch("src.models.factory.ChatAnthropic")
    def test_anthropic_adaptive_thinking_is_normalized(self, mock_cls) -> None:
        mock_cls.return_value = MagicMock()
        spec = RuntimeModelSpec(provider="anthropic", model_id="claude-opus-4-6", api_key="key")
        _create_runtime_model(spec, thinking_enabled=False, thinking={"type": "adaptive", "effort": "medium"})
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["thinking"] == {
            "type": "enabled",
            "budget_tokens": ANTHROPIC_DEFAULT_THINKING_BUDGET_TOKENS,
        }


# ---------------------------------------------------------------------------
# create_chat_model (config-based path)
# ---------------------------------------------------------------------------
class TestCreateChatModel:
    """Tests for create_chat_model() using config-based models."""

    def test_runtime_model_dict(self) -> None:
        with patch("src.models.factory.ChatOpenAI", return_value=MagicMock()) as mock_cls:
            result = create_chat_model(
                runtime_model={"provider": "openai", "model_id": "gpt-4o", "api_key": "key"}
            )
            mock_cls.assert_called_once()

    def test_runtime_model_spec(self) -> None:
        spec = RuntimeModelSpec(provider="openai", model_id="gpt-4o", api_key="key")
        with patch("src.models.factory.ChatOpenAI", return_value=MagicMock()) as mock_cls:
            result = create_chat_model(runtime_model=spec)
            mock_cls.assert_called_once()

    def test_config_model_not_found_raises(self) -> None:
        mock_config = MagicMock()
        mock_config.models = []
        mock_config.get_model_config.return_value = None
        with patch("src.models.factory.get_app_config", return_value=mock_config):
            with pytest.raises(ValueError, match="not found in config"):
                create_chat_model(name="nonexistent")

    def test_config_model_uses_first_when_none(self) -> None:
        mock_model = MagicMock()
        mock_model.name = "default-model"
        mock_model.use = "langchain_openai.ChatOpenAI"
        mock_model.supports_thinking = False
        mock_model.when_thinking_enabled = None
        mock_model.model_dump.return_value = {
            "model": "gpt-4o",
            "api_key": "resolved-key",
        }

        mock_config = MagicMock()
        mock_config.models = [mock_model]
        mock_config.get_model_config.return_value = mock_model

        mock_cls = MagicMock()
        with patch("src.models.factory.get_app_config", return_value=mock_config):
            with patch("src.models.factory.resolve_class", return_value=mock_cls):
                with patch("src.models.factory.is_tracing_enabled", return_value=False):
                    create_chat_model(name=None)
                    mock_cls.assert_called_once()

    def test_unresolved_env_var_raises(self) -> None:
        mock_model = MagicMock()
        mock_model.name = "test-model"
        mock_model.use = "langchain_openai.ChatOpenAI"
        mock_model.supports_thinking = False
        mock_model.when_thinking_enabled = None
        mock_model.model_dump.return_value = {
            "model": "gpt-4o",
            "api_key": "$OPENAI_API_KEY",
        }

        mock_config = MagicMock()
        mock_config.models = [mock_model]
        mock_config.get_model_config.return_value = mock_model

        with patch("src.models.factory.get_app_config", return_value=mock_config):
            with patch("src.models.factory.resolve_class", return_value=MagicMock()):
                with pytest.raises(ValueError, match="requires environment variable"):
                    create_chat_model(name="test-model")

    def test_thinking_unsupported_raises(self) -> None:
        mock_model = MagicMock()
        mock_model.name = "test-model"
        mock_model.use = "langchain_openai.ChatOpenAI"
        mock_model.supports_thinking = False
        mock_model.when_thinking_enabled = {"some": "config"}
        mock_model.model_dump.return_value = {
            "model": "gpt-4o",
            "api_key": "key",
        }

        mock_config = MagicMock()
        mock_config.models = [mock_model]
        mock_config.get_model_config.return_value = mock_model

        with patch("src.models.factory.get_app_config", return_value=mock_config):
            with patch("src.models.factory.resolve_class", return_value=MagicMock()):
                with pytest.raises(ValueError, match="does not support thinking"):
                    create_chat_model(name="test-model", thinking_enabled=True)

    def test_empty_api_key_raises(self) -> None:
        mock_model = MagicMock()
        mock_model.name = "test-model"
        mock_model.use = "langchain_openai.ChatOpenAI"
        mock_model.supports_thinking = False
        mock_model.when_thinking_enabled = None
        mock_model.model_dump.return_value = {
            "model": "gpt-4o",
            "api_key": "   ",
        }

        mock_config = MagicMock()
        mock_config.models = [mock_model]
        mock_config.get_model_config.return_value = mock_model

        with patch("src.models.factory.get_app_config", return_value=mock_config):
            with patch("src.models.factory.resolve_class", return_value=MagicMock()):
                with pytest.raises(ValueError, match="empty api_key"):
                    create_chat_model(name="test-model")

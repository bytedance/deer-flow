"""Tests for account-wide model preference persistence store."""

from __future__ import annotations

import pytest

from src.security.model_preference_store import get_model_preferences, set_model_preferences


def test_set_and_get_model_preferences_file_store(tmp_store_dir) -> None:
    saved = set_model_preferences(
        user_id="user-1",
        model_name="openai:gpt-5.2:standard",
        thinking_effort="high",
        provider_enabled={"openai": True, "anthropic": False},
        enabled_models={"openai:gpt-5.2:standard": True},
    )
    assert saved["model_name"] == "openai:gpt-5.2:standard"
    assert saved["thinking_effort"] == "high"
    assert saved["provider_enabled"]["openai"] is True
    assert saved["enabled_models"]["openai:gpt-5.2:standard"] is True
    loaded = get_model_preferences("user-1")
    assert loaded is not None
    assert loaded["model_name"] == "openai:gpt-5.2:standard"
    assert loaded["thinking_effort"] == "high"
    assert loaded["provider_enabled"]["anthropic"] is False
    assert loaded["enabled_models"]["openai:gpt-5.2:standard"] is True
    assert loaded["updated_at"] is not None


def test_set_model_preferences_rejects_invalid_effort(tmp_store_dir) -> None:
    with pytest.raises(ValueError, match="Invalid thinking_effort"):
        set_model_preferences(
            user_id="user-1",
            model_name="openai:gpt-5.2:standard",
            thinking_effort="turbo",
        )


def test_set_and_get_model_preferences_db_store(db_enabled) -> None:
    saved = set_model_preferences(
        user_id="user-db",
        model_name="anthropic:claude-opus-4-6:standard",
        thinking_effort="max",
        provider_enabled={"anthropic": True},
        enabled_models={"anthropic:claude-opus-4-6:standard": True},
    )
    assert saved["model_name"] == "anthropic:claude-opus-4-6:standard"
    assert saved["thinking_effort"] == "max"
    loaded = get_model_preferences("user-db")
    assert loaded is not None
    assert loaded["model_name"] == "anthropic:claude-opus-4-6:standard"
    assert loaded["thinking_effort"] == "max"
    assert loaded["provider_enabled"]["anthropic"] is True
    assert loaded["enabled_models"]["anthropic:claude-opus-4-6:standard"] is True


def test_partial_update_preserves_existing_fields(tmp_store_dir) -> None:
    set_model_preferences(
        user_id="user-partial",
        model_name="openai:gpt-5.2:standard",
        thinking_effort="medium",
        provider_enabled={"openai": True},
        enabled_models={"openai:gpt-5.2:standard": True},
    )
    set_model_preferences(
        user_id="user-partial",
        thinking_effort="high",
    )
    loaded = get_model_preferences("user-partial")
    assert loaded is not None
    assert loaded["model_name"] == "openai:gpt-5.2:standard"
    assert loaded["thinking_effort"] == "high"
    assert loaded["provider_enabled"]["openai"] is True
    assert loaded["enabled_models"]["openai:gpt-5.2:standard"] is True


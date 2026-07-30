"""Tests for the models admin CRUD router.

Exercises the config.yaml read-modify-write path, .env sync, API key
masking / preservation, and admin-only gating.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from dotenv import dotenv_values

from app.gateway.routers.models import (
    _apply_models_config_update,
    _delete_model_from_config,
    _derive_env_var_name,
    _mask_model_config,
    _sync_env_file,
    AdminModelsUpdateRequest,
    FullModelConfig,
)

# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------


class TestDeriveEnvVarName:
    def test_dash_to_underscore(self):
        assert _derive_env_var_name("deepseek-v4-flash") == "DEEPSEEK_V4_FLASH_API_KEY"

    def test_uppercases(self):
        assert _derive_env_var_name("gpt-4") == "GPT_4_API_KEY"

    def test_strips_non_alnum(self):
        assert _derive_env_var_name("my.model@provider") == "MY_MODEL_PROVIDER_API_KEY"


class TestMaskModelConfig:
    def test_masks_api_key(self):
        m = FullModelConfig(
            name="test", use="x:Y", model="m", api_key="sk-secret"
        )
        masked = _mask_model_config(m)
        assert masked.api_key == "***"

    def test_none_api_key_stays_none(self):
        m = FullModelConfig(
            name="test", use="x:Y", model="m", api_key=None
        )
        masked = _mask_model_config(m)
        assert masked.api_key is None

    def test_preserves_other_fields(self):
        m = FullModelConfig(
            name="test",
            display_name="Test",
            use="x:Y",
            model="m",
            supports_thinking=True,
            api_key="secret",
        )
        masked = _mask_model_config(m)
        assert masked.name == "test"
        assert masked.display_name == "Test"
        assert masked.use == "x:Y"
        assert masked.model == "m"
        assert masked.supports_thinking is True


# ---------------------------------------------------------------------------
# Unit tests — .env file helpers
# ---------------------------------------------------------------------------


class TestSyncEnvFile:
    def test_writes_new_api_key(self, tmp_path: Path):
        raw = {"models": []}
        incoming = [
            FullModelConfig(
                name="test-model", use="x:Y", model="m1", api_key="sk-abc"
            )
        ]
        _sync_env_file(tmp_path, raw, incoming)
        entries = dotenv_values(tmp_path / ".env")
        assert entries.get("TEST_MODEL_API_KEY") == "sk-abc"

    def test_removes_orphaned_key(self, tmp_path: Path):
        (tmp_path / ".env").write_text("OLD_MODEL_API_KEY=old-secret\n", encoding="utf-8")
        raw = {
            "models": [
                {"name": "old-model", "use": "x:Y", "model": "m1", "api_key": "$OLD_MODEL_API_KEY"}
            ]
        }
        incoming = [
            FullModelConfig(
                name="new-model", use="x:Y", model="m2", api_key="sk-new"
            )
        ]
        _sync_env_file(tmp_path, raw, incoming)
        entries = dotenv_values(tmp_path / ".env")
        assert "OLD_MODEL_API_KEY" not in entries
        assert entries.get("NEW_MODEL_API_KEY") == "sk-new"

    def test_preserves_shared_env_key(self, tmp_path: Path):
        (tmp_path / ".env").write_text("SHARED_API_KEY=shared-secret\n", encoding="utf-8")
        raw = {
            "models": [
                {"name": "a", "use": "x:Y", "model": "m1", "api_key": "$SHARED_API_KEY"},
                {"name": "b", "use": "x:Y", "model": "m2", "api_key": "$SHARED_API_KEY"},
            ]
        }
        # Delete model "a", keep "b".
        incoming = [
            FullModelConfig(
                name="b", use="x:Y", model="m2", api_key="***"
            )
        ]
        _sync_env_file(tmp_path, raw, incoming)
        entries = dotenv_values(tmp_path / ".env")
        # Key should still be there because model "b" still references it.
        assert entries.get("SHARED_API_KEY") == "shared-secret"

    def test_explicit_env_var_ref_is_preserved(self, tmp_path: Path):
        raw = {"models": []}
        incoming = [
            FullModelConfig(
                name="t", use="x:Y", model="m1", api_key="$MY_CUSTOM_KEY"
            )
        ]
        _sync_env_file(tmp_path, raw, incoming)
        entries = dotenv_values(tmp_path / ".env")
        # $MY_CUSTOM_KEY is an env-var reference, not a new value to write.
        assert "MY_CUSTOM_KEY" not in entries

    def test_preserves_non_model_lines(self, tmp_path: Path):
        """Comments, blank lines, and non-model entries survive untouched."""
        original = (
            "# Database configuration\n"
            "DATABASE_URL=postgres://localhost/db\n"
            "\n"
            "# Auth secrets\n"
            "export OAUTH_CLIENT_SECRET=xyz\n"
            "\n"
        )
        (tmp_path / ".env").write_text(original, encoding="utf-8")
        raw = {"models": []}
        incoming = [
            FullModelConfig(
                name="my-model", use="x:Y", model="m1", api_key="sk-123"
            )
        ]
        _sync_env_file(tmp_path, raw, incoming)
        result = (tmp_path / ".env").read_text(encoding="utf-8")
        # All original lines should still be there.
        assert "# Database configuration" in result
        assert "DATABASE_URL=postgres://localhost/db" in result
        assert "# Auth secrets" in result
        assert "export OAUTH_CLIENT_SECRET=xyz" in result
        # The new model-owned key should be appended.
        assert "MY_MODEL_API_KEY=sk-123" in result

    def test_updates_existing_model_key_in_place(self, tmp_path: Path):
        """An existing model-owned key is updated in-place, not duplicated."""
        (tmp_path / ".env").write_text(
            "DATABASE_URL=postgres://db\n"
            "MY_MODEL_API_KEY=old-key\n"
            "OTHER_SECRET=keep-me\n",
            encoding="utf-8",
        )
        raw = {
            "models": [
                {"name": "my-model", "use": "x:Y", "model": "m1", "api_key": "$MY_MODEL_API_KEY"}
            ]
        }
        incoming = [
            FullModelConfig(
                name="my-model", use="x:Y", model="m1", api_key="sk-new-key"
            )
        ]
        _sync_env_file(tmp_path, raw, incoming)
        result = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "MY_MODEL_API_KEY=sk-new-key" in result
        assert "old-key" not in result
        assert "DATABASE_URL=postgres://db" in result
        assert "OTHER_SECRET=keep-me" in result

    def test_deletes_orphaned_model_key_leaving_others(self, tmp_path: Path):
        """Deleting a model-owned key leaves all other lines intact."""
        (tmp_path / ".env").write_text(
            "# Top comment\n"
            "DATABASE_URL=pg://db\n"
            "OLD_MODEL_API_KEY=orphan-secret\n"
            "\n"
            "# Bottom comment\n"
            "OTHER_KEY=val\n",
            encoding="utf-8",
        )
        raw = {
            "models": [
                {"name": "old-model", "use": "x:Y", "model": "m1", "api_key": "$OLD_MODEL_API_KEY"}
            ]
        }
        incoming: list[FullModelConfig] = []
        _sync_env_file(tmp_path, raw, incoming)
        result = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "# Top comment" in result
        assert "DATABASE_URL=pg://db" in result
        assert "OLD_MODEL_API_KEY" not in result
        assert "orphan-secret" not in result
        assert "# Bottom comment" in result
        assert "OTHER_KEY=val" in result


# ---------------------------------------------------------------------------
# Integration tests — config.yaml read-modify-write
# ---------------------------------------------------------------------------


_BASE_CONFIG = {
    "config_version": 31,
    "models": [
        {
            "name": "deepseek-v4-flash",
            "display_name": "DeepSeek / deepseek-v4-flash",
            "use": "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
            "model": "deepseek-v4-flash",
            "api_key": "$DEEPSEEK_API_KEY",
            "timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "supports_vision": False,
            "supports_thinking": True,
        }
    ],
}


@pytest.fixture
def temp_config(tmp_path: Path, monkeypatch) -> Path:
    """Create a temporary config.yaml with known content."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(_BASE_CONFIG, sort_keys=False, allow_unicode=True), encoding="utf-8")

    def _resolve_config_path(*args, **kwargs):
        return config_path

    monkeypatch.setattr(
        "app.gateway.routers.models.AppConfig.resolve_config_path",
        _resolve_config_path,
    )
    monkeypatch.setattr(
        "app.gateway.routers.models.config_yaml_write_lock",
        MagicMock(),  # no-op lock for tests
    )
    return tmp_path


@pytest.fixture
def mock_reload(monkeypatch):
    """Mock reload_app_config to return a plausible AppConfig."""
    from deerflow.config.app_config import AppConfig
    from deerflow.config.model_config import ModelConfig

    cfg = AppConfig(
        models=[
            ModelConfig(
                name="deepseek-v4-flash",
                display_name="DeepSeek / deepseek-v4-flash",
                use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
                model="deepseek-v4-flash",
                api_key="$DEEPSEEK_API_KEY",
                supports_vision=False,
                supports_thinking=True,
            )
        ]
    )

    def _reload(*args, **kwargs):
        return cfg

    monkeypatch.setattr(
        "app.gateway.routers.models.reload_app_config",
        _reload,
    )
    return cfg


class TestApplyModelsConfigUpdate:
    def test_preserves_env_var_ref(self, temp_config: Path, mock_reload):
        """Sending *** should preserve the existing $DEEPSEEK_API_KEY reference."""
        body = AdminModelsUpdateRequest(
            models=[
                FullModelConfig(
                    name="deepseek-v4-flash",
                    display_name="DeepSeek Updated",
                    use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
                    model="deepseek-v4-flash",
                    api_key="***",  # masked round-trip
                    supports_thinking=True,
                )
            ]
        )
        saved = _apply_models_config_update(body)
        assert len(saved) == 1
        assert saved[0].api_key == "***"  # masked in response

        # Read back raw YAML and verify $VAR preserved.
        raw = yaml.safe_load((temp_config / "config.yaml").read_text())
        assert raw["models"][0]["api_key"] == "$DEEPSEEK_API_KEY"
        assert raw["models"][0]["display_name"] == "DeepSeek Updated"

    def test_adds_new_model_with_api_key(self, temp_config: Path, mock_reload):
        """Adding a model with a real API key writes to .env and stores $VAR."""
        body = AdminModelsUpdateRequest(
            models=[
                FullModelConfig(
                    name="deepseek-v4-flash",
                    use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
                    model="deepseek-v4-flash",
                    api_key="***",
                ),
                FullModelConfig(
                    name="gpt-4",
                    display_name="GPT-4",
                    use="langchain_openai:ChatOpenAI",
                    model="gpt-4",
                    api_key="sk-openai-secret",
                    supports_vision=True,
                ),
            ]
        )
        saved = _apply_models_config_update(body)
        assert len(saved) == 2

        raw = yaml.safe_load((temp_config / "config.yaml").read_text())
        assert len(raw["models"]) == 2
        gpt_entry = raw["models"][1]
        assert gpt_entry["name"] == "gpt-4"
        assert gpt_entry["api_key"] == "$GPT_4_API_KEY"

        env_entries = dotenv_values(temp_config / ".env")
        assert env_entries.get("GPT_4_API_KEY") == "sk-openai-secret"

    def test_adds_model_with_explicit_env_var(self, temp_config: Path, mock_reload):
        """API key starting with $ is stored as-is (user-managed env var)."""
        body = AdminModelsUpdateRequest(
            models=[
                FullModelConfig(
                    name="deepseek-v4-flash",
                    use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
                    model="deepseek-v4-flash",
                    api_key="***",
                ),
                FullModelConfig(
                    name="custom",
                    use="langchain_openai:ChatOpenAI",
                    model="custom-model",
                    api_key="$MY_ENV_KEY",
                ),
            ]
        )
        _apply_models_config_update(body)
        raw = yaml.safe_load((temp_config / "config.yaml").read_text())
        assert raw["models"][1]["api_key"] == "$MY_ENV_KEY"

        # Should NOT write to .env.
        env_path = temp_config / ".env"
        if env_path.exists():
            entries = dotenv_values(env_path)
            assert "MY_ENV_KEY" not in entries

    def test_preserves_extra_fields(self, temp_config: Path, mock_reload):
        """Provider-specific extra fields (like custom_extra) survive round-trip."""
        # Add an extra field to raw YAML.
        raw = yaml.safe_load((temp_config / "config.yaml").read_text())
        raw["models"][0]["custom_extra"] = {"nested": True}
        (temp_config / "config.yaml").write_text(yaml.dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")

        body = AdminModelsUpdateRequest(
            models=[
                FullModelConfig(
                    name="deepseek-v4-flash",
                    use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
                    model="deepseek-v4-flash",
                    api_key="***",
                )
            ]
        )
        _apply_models_config_update(body)
        raw2 = yaml.safe_load((temp_config / "config.yaml").read_text())
        assert raw2["models"][0].get("custom_extra") == {"nested": True}

    def test_null_fields_are_dropped(self, temp_config: Path, mock_reload):
        """Known optional fields that are None should be dropped from output."""
        body = AdminModelsUpdateRequest(
            models=[
                FullModelConfig(
                    name="deepseek-v4-flash",
                    use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
                    model="deepseek-v4-flash",
                    api_key="***",
                    description=None,
                    timeout=None,
                    max_retries=None,
                )
            ]
        )
        _apply_models_config_update(body)
        raw = yaml.safe_load((temp_config / "config.yaml").read_text())
        entry = raw["models"][0]
        assert "description" not in entry
        assert "timeout" not in entry
        assert "max_retries" not in entry


class TestDeleteModel:
    def test_delete_existing_model(self, temp_config: Path, monkeypatch, mock_reload):
        monkeypatch.setattr(
            "app.gateway.routers.models.config_yaml_write_lock",
            MagicMock(),
        )
        _delete_model_from_config("deepseek-v4-flash")
        raw = yaml.safe_load((temp_config / "config.yaml").read_text())
        assert len(raw.get("models", [])) == 0

    def test_delete_nonexistent_model_raises(self, temp_config: Path, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setattr(
            "app.gateway.routers.models.config_yaml_write_lock",
            MagicMock(),
        )
        monkeypatch.setattr(
            "app.gateway.routers.models.reload_app_config",
            lambda *a, **kw: None,
        )
        with pytest.raises(HTTPException, match="not found"):
            _delete_model_from_config("nonexistent")

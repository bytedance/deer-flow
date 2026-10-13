"""Offline boundary for the opt-in native memory acceptance configuration."""

from pathlib import Path

import test_ecs_executor_c_live as native_live
import yaml

from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import ExtensionsConfig


def test_native_memory_mode_keeps_canonical_home_and_role_local_indexes(tmp_path):
    assert native_live._native_memory_config(tmp_path, "central", enabled=False) == {"enabled": False}
    configs = [native_live._native_memory_config(tmp_path, role, enabled=True) for role in ("central", "worker")]
    indexes = []
    for config in configs:
        assert config["enabled"] and config["mode"] == "tool"
        assert config["manager_class"] == "deermem"
        assert "storage_path" not in config["backend_config"]
        indexes.append(Path(config["backend_config"]["retrieval_index_path"]))
    assert indexes[0] != indexes[1]
    assert all(index.is_absolute() and not index.is_relative_to(tmp_path / "nas") for index in indexes)


def test_native_memory_operator_overlay_uses_local_environment_reference(tmp_path, monkeypatch):
    examples = Path(__file__).resolve().parents[2] / "examples/ecs-native"
    base = yaml.safe_load((examples / "native-shell.yaml").read_text())
    base["auth"] = {"local": {"allow_registration": False, "max_login_attempts": 7}}
    overlay = yaml.safe_load((examples / "native-memory.yaml").read_text())
    assert set(overlay) == {"memory"}
    base["memory"] = overlay["memory"]
    index = tmp_path / "central-memory-index"
    environment = {
        "DEER_FLOW_MEMORY_INDEX_PATH": str(index),
        "DEEPSEEK_API_BASE": "https://model.example.invalid/v1",
        "DEEPSEEK_API_KEY": "offline-dummy-key",
        "DATABASE_URL": "postgresql://offline:dummy@localhost/offline",
        "REDIS_URL": "redis://localhost:6379/9",
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    # Parsing must use the native loader; its process-global publication is not
    # part of this operator-config test and must not affect unrelated tests.
    monkeypatch.setattr(AppConfig, "_apply_singleton_configs", lambda *args: None)
    config = AppConfig._from_yaml_text(yaml.safe_dump(base), tmp_path / "merged.yaml", extensions=ExtensionsConfig())
    assert config.memory.enabled and config.memory.mode == "tool"
    assert config.memory.manager_class == "deermem"
    assert "storage_path" not in config.memory.backend_config
    assert config.memory.backend_config["retrieval_index_path"] == str(index)
    assert index.is_absolute() and not index.is_relative_to(tmp_path / "nas")
    assert config.models[0].name == "deepseek-chat"
    assert config.models[0].model == "deepseek-chat"
    assert config.models[0].api_key == environment["DEEPSEEK_API_KEY"]
    assert config.database.backend == "postgres"
    assert config.database.postgres_url == environment["DATABASE_URL"]
    assert not config.auth.local.allow_registration and config.auth.local.max_login_attempts == 7
    assert config.sandbox.ownership.redis_url == environment["REDIS_URL"]

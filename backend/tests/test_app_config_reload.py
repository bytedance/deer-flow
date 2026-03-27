from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from deerflow.config.app_config import AppConfig, get_app_config, reset_app_config


def _write_config(path: Path, *, model_name: str, supports_thinking: bool) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {
                        "name": model_name,
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "gpt-test",
                        "supports_thinking": supports_thinking,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_extensions_config(path: Path) -> None:
    path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")


def test_get_app_config_reloads_when_file_changes(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_path, model_name="first-model", supports_thinking=False)

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()

    try:
        initial = get_app_config()
        assert initial.models[0].supports_thinking is False

        _write_config(config_path, model_name="first-model", supports_thinking=True)
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        reloaded = get_app_config()
        assert reloaded.models[0].supports_thinking is True
        assert reloaded is not initial
    finally:
        reset_app_config()


def test_resolve_config_path_walks_up_directory_tree(tmp_path, monkeypatch):
    """resolve_config_path should find config.yaml in a grandparent directory."""
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, model_name="found-model", supports_thinking=False)
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)

    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)
    monkeypatch.chdir(nested)

    resolved = AppConfig.resolve_config_path()
    assert resolved == config_path


def test_resolve_config_path_raises_with_searched_paths(tmp_path, monkeypatch):
    """resolve_config_path should include searched paths in the error message."""
    empty_dir = tmp_path / "x" / "y"
    empty_dir.mkdir(parents=True)

    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)
    monkeypatch.chdir(empty_dir)

    with pytest.raises(FileNotFoundError, match="DEER_FLOW_CONFIG_PATH"):
        AppConfig.resolve_config_path()


def test_get_app_config_fallback_to_cache_when_path_unresolvable(tmp_path, monkeypatch):
    """get_app_config should return cached config if path resolution fails after initial load."""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_path, model_name="cached-model", supports_thinking=False)

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()

    try:
        initial = get_app_config()
        assert initial.models[0].name == "cached-model"

        # Unset the env var so the path can no longer be resolved
        monkeypatch.delenv("DEER_FLOW_CONFIG_PATH")
        # Change CWD to a temp dir that has no config.yaml (only root has one, no other parent)
        monkeypatch.chdir(tmp_path)

        # Should return cached config, not raise
        fallback = get_app_config()
        assert fallback is initial
    finally:
        reset_app_config()


def test_get_app_config_reloads_when_config_path_changes(tmp_path, monkeypatch):
    config_a = tmp_path / "config-a.yaml"
    config_b = tmp_path / "config-b.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_a, model_name="model-a", supports_thinking=False)
    _write_config(config_b, model_name="model-b", supports_thinking=True)

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_a))
    reset_app_config()

    try:
        first = get_app_config()
        assert first.models[0].name == "model-a"

        monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_b))
        second = get_app_config()
        assert second.models[0].name == "model-b"
        assert second is not first
    finally:
        reset_app_config()

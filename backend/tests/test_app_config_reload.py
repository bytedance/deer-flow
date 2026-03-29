from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.app_config import AppConfig


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


def test_app_config_loads_env_relative_to_config_path(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    run_dir = tmp_path / "runner"
    project_dir.mkdir()
    run_dir.mkdir()

    config_path = project_dir / "config.yaml"
    extensions_path = project_dir / "extensions_config.json"
    env_path = project_dir / ".env"

    _write_extensions_config(extensions_path)
    env_path.write_text("ZHIPUAI_API_KEY=test-zhipu-key\n", encoding="utf-8")
    config_path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {
                    "use": "deerflow.sandbox.local:LocalSandboxProvider",
                    "environment": {"ZHIPUAI_API_KEY": "$ZHIPUAI_API_KEY"},
                },
                "models": [
                    {
                        "name": "test-model",
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "gpt-test",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(run_dir)
    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config = AppConfig.from_file(str(config_path))

    assert config.sandbox.environment["ZHIPUAI_API_KEY"] == "test-zhipu-key"

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import deerflow.config.app_config as app_config_module
import deerflow.config.extensions_config as extensions_config_module
import deerflow.config.paths as paths_module
import deerflow.config.skills_config as skills_config_module
from deerflow.config.app_config import get_app_config, reset_app_config


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


# --- Cross-platform startup path resolution (no os.getcwd in hot path) ---
# langgraph dev + blockbuster blocks blocking calls on the event loop; on Windows
# Path.resolve() may consult getcwd. These tests cover config/skills_config/paths
# helpers that use Path(__file__).parent.parents[...] only. skills/loader.py still
# uses resolve(); it is covered by test_skills_loader.test_get_skills_root_path_points_to_project_root_skills.


def _fail_getcwd(*_args, **_kwargs) -> str:
    raise AssertionError("os.getcwd must not be called during deterministic path resolution")


@pytest.mark.parametrize(
    "app_config_file",
    [
        "/Users/runner/deer-flow/backend/packages/harness/deerflow/config/app_config.py",
        "C:/Users/runner/deer-flow/backend/packages/harness/deerflow/config/app_config.py",
    ],
)
def test_default_config_candidates_matches_backend_and_repo_roots(monkeypatch: pytest.MonkeyPatch, app_config_file: str) -> None:
    monkeypatch.setattr(app_config_module, "__file__", app_config_file)

    with patch.object(os, "getcwd", _fail_getcwd):
        backend_yaml, root_yaml = app_config_module._default_config_candidates()

    assert backend_yaml.name == "config.yaml"
    assert root_yaml.name == "config.yaml"
    assert backend_yaml.parent.name == "backend"
    assert root_yaml.parent.name == "deer-flow"


@pytest.mark.parametrize(
    "paths_file",
    [
        "/Users/runner/deer-flow/backend/packages/harness/deerflow/config/paths.py",
        "C:/Users/runner/deer-flow/backend/packages/harness/deerflow/config/paths.py",
    ],
)
def test_default_local_base_dir_under_backend_deer_flow(monkeypatch: pytest.MonkeyPatch, paths_file: str) -> None:
    monkeypatch.setattr(paths_module, "__file__", paths_file)

    with patch.object(os, "getcwd", _fail_getcwd):
        base = paths_module._default_local_base_dir()

    assert base.name == ".deer-flow"
    assert base.parent.name == "backend"


def test_extensions_resolve_prefers_backend_extensions_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    layout_root = tmp_path / "deer-flow"
    backend = layout_root / "backend"
    cfg_dir = backend / "packages" / "harness" / "deerflow" / "config"
    cfg_dir.mkdir(parents=True)
    ext_backend = backend / "extensions_config.json"
    ext_backend.write_text("{}", encoding="utf-8")
    fake_file = cfg_dir / "extensions_config.py"
    fake_file.write_text("# test\n", encoding="utf-8")

    monkeypatch.setattr(extensions_config_module, "__file__", str(fake_file))
    monkeypatch.delenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", raising=False)

    with patch.object(os, "getcwd", _fail_getcwd):
        resolved = extensions_config_module.ExtensionsConfig.resolve_config_path()

    assert resolved == ext_backend


def test_extensions_resolve_falls_back_to_repo_root_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    layout_root = tmp_path / "deer-flow"
    backend = layout_root / "backend"
    cfg_dir = backend / "packages" / "harness" / "deerflow" / "config"
    cfg_dir.mkdir(parents=True)
    ext_repo = layout_root / "extensions_config.json"
    ext_repo.write_text("{}", encoding="utf-8")
    fake_file = cfg_dir / "extensions_config.py"
    fake_file.write_text("# test\n", encoding="utf-8")

    monkeypatch.setattr(extensions_config_module, "__file__", str(fake_file))
    monkeypatch.delenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", raising=False)

    with patch.object(os, "getcwd", _fail_getcwd):
        resolved = extensions_config_module.ExtensionsConfig.resolve_config_path()

    assert resolved == ext_repo


@pytest.mark.parametrize(
    "skills_config_file",
    [
        "/Users/runner/deer-flow/backend/packages/harness/deerflow/config/skills_config.py",
        "C:/Users/runner/deer-flow/backend/packages/harness/deerflow/config/skills_config.py",
    ],
)
def test_skills_config_default_repo_root(monkeypatch: pytest.MonkeyPatch, skills_config_file: str) -> None:
    monkeypatch.setattr(skills_config_module, "__file__", skills_config_file)

    with patch.object(os, "getcwd", _fail_getcwd):
        root = skills_config_module._default_repo_root()
    assert root.name == "deer-flow"

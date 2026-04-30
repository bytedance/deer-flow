"""Runtime path policy tests for standalone harness usage."""

from pathlib import Path

import pytest
import yaml

from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths
from deerflow.config.runtime_paths import project_root
from deerflow.config.skills_config import SkillsConfig
from deerflow.skills.loader import get_skills_root_path


def _clear_path_env(monkeypatch):
    for name in (
        "DEER_FLOW_CONFIG_PATH",
        "DEER_FLOW_EXTENSIONS_CONFIG_PATH",
        "DEER_FLOW_HOME",
        "DEER_FLOW_PROJECT_ROOT",
        "DEER_FLOW_SKILLS_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_runtime_paths_resolve_from_current_project(tmp_path: Path, monkeypatch):
    _clear_path_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}),
        encoding="utf-8",
    )
    (tmp_path / "extensions_config.json").write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")

    assert AppConfig.resolve_config_path() == tmp_path / "config.yaml"
    assert ExtensionsConfig.resolve_config_path() == tmp_path / "extensions_config.json"
    assert Paths().base_dir == tmp_path / ".deer-flow"
    assert SkillsConfig().get_skills_path() == tmp_path / "skills"
    assert get_skills_root_path() == tmp_path / "skills"


def test_deer_flow_project_root_overrides_current_directory(tmp_path: Path, monkeypatch):
    _clear_path_env(monkeypatch)
    project_root = tmp_path / "project"
    other_cwd = tmp_path / "other"
    project_root.mkdir()
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(project_root))

    (project_root / "config.yaml").write_text(
        yaml.safe_dump({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}),
        encoding="utf-8",
    )
    (project_root / "mcp_config.json").write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")

    assert AppConfig.resolve_config_path() == project_root / "config.yaml"
    assert ExtensionsConfig.resolve_config_path() == project_root / "mcp_config.json"
    assert Paths().base_dir == project_root / ".deer-flow"
    assert SkillsConfig(path="custom-skills").get_skills_path() == project_root / "custom-skills"


def test_deer_flow_skills_path_overrides_project_default(tmp_path: Path, monkeypatch):
    _clear_path_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEER_FLOW_SKILLS_PATH", "team-skills")

    assert SkillsConfig().get_skills_path() == tmp_path / "team-skills"
    assert get_skills_root_path() == tmp_path / "team-skills"


def test_deer_flow_project_root_must_exist(tmp_path: Path, monkeypatch):
    _clear_path_env(monkeypatch)
    missing_root = tmp_path / "missing"
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(missing_root))

    with pytest.raises(ValueError, match="does not exist"):
        project_root()


def test_deer_flow_project_root_must_be_directory(tmp_path: Path, monkeypatch):
    _clear_path_env(monkeypatch)
    project_root_file = tmp_path / "project-root"
    project_root_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(project_root_file))

    with pytest.raises(ValueError, match="not a directory"):
        project_root()

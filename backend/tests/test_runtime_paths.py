"""Runtime path policy tests for standalone harness usage."""

from pathlib import Path

import pytest
import yaml

from deerflow.config import app_config as app_config_module
from deerflow.config import extensions_config as extensions_config_module
from deerflow.config import skills_config as skills_config_module
from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths
from deerflow.config.runtime_paths import project_root
from deerflow.config.skills_config import SkillsConfig
from deerflow.skills.storage import get_or_new_skill_storage


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
    (tmp_path / "skills").mkdir()

    assert AppConfig.resolve_config_path() == tmp_path / "config.yaml"
    assert ExtensionsConfig.resolve_config_path() == tmp_path / "extensions_config.json"
    assert Paths().base_dir == tmp_path / ".deer-flow"
    assert SkillsConfig().get_skills_path() == tmp_path / "skills"
    assert get_or_new_skill_storage(skills_path=SkillsConfig().get_skills_path()).get_skills_root_path() == tmp_path / "skills"


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
    assert get_or_new_skill_storage(skills_path=SkillsConfig().get_skills_path()).get_skills_root_path() == tmp_path / "team-skills"


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


def test_app_config_falls_back_to_legacy_when_project_root_lacks_config(tmp_path: Path, monkeypatch):
    """When DEER_FLOW_PROJECT_ROOT is unset and cwd has no config.yaml, the
    legacy backend/repo-root candidates must be used for monorepo compatibility."""
    _clear_path_env(monkeypatch)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    legacy_backend = tmp_path / "legacy-backend"
    legacy_repo = tmp_path / "legacy-repo"
    legacy_backend.mkdir()
    legacy_repo.mkdir()
    legacy_backend_config = legacy_backend / "config.yaml"
    legacy_backend_config.write_text(
        yaml.safe_dump({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}),
        encoding="utf-8",
    )
    repo_root_config = legacy_repo / "config.yaml"
    repo_root_config.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        app_config_module,
        "_legacy_config_candidates",
        lambda: (legacy_backend_config, repo_root_config),
    )

    assert AppConfig.resolve_config_path() == legacy_backend_config


def test_skills_config_falls_back_to_legacy_when_project_root_lacks_skills(tmp_path: Path, monkeypatch):
    """When DEER_FLOW_PROJECT_ROOT is unset and cwd has no `skills/`, the legacy
    repo-root candidate must be used so monorepo runs (cwd=backend/) keep finding
    `<repo>/skills` instead of `<repo>/backend/skills` (regression test for #2694)."""
    _clear_path_env(monkeypatch)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    legacy_skills = tmp_path / "legacy-repo" / "skills"
    legacy_skills.mkdir(parents=True)

    monkeypatch.setattr(
        skills_config_module,
        "_legacy_skills_candidates",
        lambda: (legacy_skills,),
    )

    assert SkillsConfig().get_skills_path() == legacy_skills


def test_skills_config_returns_project_default_when_neither_exists(tmp_path: Path, monkeypatch):
    """When nothing exists, fall back to the project-root default path so callers
    surface a stable empty location instead of silently picking a stale legacy dir."""
    _clear_path_env(monkeypatch)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    monkeypatch.setattr(skills_config_module, "_legacy_skills_candidates", lambda: ())

    assert SkillsConfig().get_skills_path() == cwd / "skills"


def test_extensions_config_falls_back_to_legacy_when_project_root_lacks_file(tmp_path: Path, monkeypatch):
    """ExtensionsConfig should hit the legacy backend/repo-root locations when
    the caller project root has no extensions_config.json/mcp_config.json."""
    _clear_path_env(monkeypatch)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    fake_backend = tmp_path / "fake-backend"
    fake_repo = tmp_path / "fake-repo"
    fake_backend.mkdir()
    fake_repo.mkdir()
    legacy_extensions = fake_backend / "extensions_config.json"
    legacy_extensions.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")

    fake_paths_module_file = fake_backend / "packages" / "harness" / "deerflow" / "config" / "extensions_config.py"
    fake_paths_module_file.parent.mkdir(parents=True)
    fake_paths_module_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(extensions_config_module, "__file__", str(fake_paths_module_file))

    assert ExtensionsConfig.resolve_config_path() == legacy_extensions


def test_extensions_config_explicit_path_missing_file_returns_none(tmp_path: Path, monkeypatch):
    """An explicit ``config_path`` argument pointing at a file that does not
    exist (e.g. it existed earlier and was deleted) must return ``None``,
    not raise.

    Regression for the follow-up flagged on PR #4124: ``resolve_config_path``
    used to raise ``FileNotFoundError`` for this branch while its own
    docstring promised a clean ``None`` for "extensions are optional". Every
    resolution mode must degrade the same way so callers (e.g. the MCP
    tools-cache staleness check) can rely on a clean "no config" signal
    instead of handling an exception.
    """
    _clear_path_env(monkeypatch)
    missing = tmp_path / "extensions_config.json"
    # Never created (equivalent to "existed, then got deleted" from the
    # resolver's point of view -- it only sees that the path doesn't exist).

    assert ExtensionsConfig.resolve_config_path(config_path=str(missing)) is None


def test_extensions_config_env_var_missing_file_returns_none(tmp_path: Path, monkeypatch):
    """``DEER_FLOW_EXTENSIONS_CONFIG_PATH`` pointing at a file that has since
    been deleted must return ``None``, not raise.

    This is the exact resolution mode Docker dev/prod uses (see
    backend/AGENTS.md: "Docker development ... points `DEER_FLOW_CONFIG_PATH`
    / `DEER_FLOW_EXTENSIONS_CONFIG_PATH`" at the mounted config directory), so
    a config file deleted after being valid must not crash callers that
    resolve with no explicit argument -- e.g. the MCP tools cache's
    staleness check (`deerflow.mcp.cache._resolve_config_path`), which calls
    `ExtensionsConfig.resolve_config_path()` with no args and therefore hits
    this exact branch whenever the env var is set.
    """
    _clear_path_env(monkeypatch)
    cfg = tmp_path / "extensions_config.json"
    cfg.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    assert ExtensionsConfig.resolve_config_path() == cfg  # sanity: resolves while present

    cfg.unlink()

    assert ExtensionsConfig.resolve_config_path() is None

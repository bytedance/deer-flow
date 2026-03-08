from pathlib import Path

from src.config.skills_config import SkillsConfig


def test_get_skills_path_resolves_relative_to_deer_flow_config_path(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    config_file = project_root / "config.yaml"
    config_file.write_text("skills: {}", encoding="utf-8")

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))

    cfg = SkillsConfig(path="skills")

    assert cfg.get_skills_path() == (project_root / "skills").resolve()


def test_get_skills_path_resolves_relative_to_detected_config_location(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "config.yaml").write_text("skills: {}", encoding="utf-8")

    backend_dir = project_root / "backend"
    backend_dir.mkdir()
    monkeypatch.chdir(backend_dir)
    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)

    cfg = SkillsConfig(path="skills")

    assert cfg.get_skills_path() == (project_root / "skills").resolve()


def test_get_skills_path_keeps_absolute_path(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)

    absolute_path = tmp_path / "custom-skills"
    cfg = SkillsConfig(path=str(absolute_path))

    assert cfg.get_skills_path() == absolute_path.resolve()

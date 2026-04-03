from pathlib import Path

from deerflow.skills.loader import _CHECKED_SKILL_DEPENDENCIES, ensure_skill_dependencies
from deerflow.skills.parser import parse_skill_file
from deerflow.skills.types import Skill, SkillDependencies


def _write_skill(tmp_path: Path, content: str) -> Path:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


def test_parse_skill_with_dependencies(tmp_path: Path) -> None:
    skill_file = _write_skill(
        tmp_path,
        "---\nname: deps-skill\ndescription: Skill with deps\ndependencies:\n  pip:\n    - requests\n    - pydantic-core\n  npm:\n    - lodash\n---\n\n# Deps Skill\n",
    )

    result = parse_skill_file(skill_file, "public")

    assert result is not None
    assert result.dependencies is not None
    assert result.dependencies.pip == ["requests", "pydantic-core"]
    assert result.dependencies.npm == ["lodash"]


def test_parse_skill_without_dependencies_is_backward_compatible(tmp_path: Path) -> None:
    skill_file = _write_skill(
        tmp_path,
        "---\nname: simple-skill\ndescription: No deps\n---\n\n# Simple Skill\n",
    )

    result = parse_skill_file(skill_file, "public")

    assert result is not None
    assert result.dependencies is None


def test_ensure_skill_dependencies_installs_missing_pip_packages(monkeypatch) -> None:
    _CHECKED_SKILL_DEPENDENCIES.clear()
    calls: list[list[str]] = []

    def fake_find_spec(name: str):
        if name in {"installed_pkg", "hyphen_pkg"}:
            return object()
        return None

    def fake_run(command: list[str]) -> None:
        calls.append(command)

    monkeypatch.setattr("deerflow.skills.loader.find_spec", fake_find_spec)
    monkeypatch.setattr("deerflow.skills.loader.shutil.which", lambda binary: "/usr/bin/uv" if binary == "uv" else None)
    monkeypatch.setattr("deerflow.skills.loader.subprocess.run", fake_run)

    skill = Skill(
        name="deps-check-skill",
        description="Dependency check",
        license=None,
        skill_dir=Path("/tmp/skill"),
        skill_file=Path("/tmp/skill/SKILL.md"),
        relative_path=Path("deps-check-skill"),
        category="public",
        enabled=True,
        dependencies=SkillDependencies(pip=["installed_pkg", "hyphen-pkg", "missing-pkg"]),
    )

    ensure_skill_dependencies(skill)
    ensure_skill_dependencies(skill)

    assert calls == [["uv", "pip", "install", "missing-pkg"]]

import importlib
from pathlib import Path
from types import SimpleNamespace

from deerflow.skills.types import SKILL_MD_FILE, Skill, SkillCategory
from deerflow.tools.builtins.skill_load_tool import skill_load_tool

skill_load_module = importlib.import_module("deerflow.tools.builtins.skill_load_tool")


def _runtime(*, app_config=None, available_skills=None) -> SimpleNamespace:
    context = {}
    if app_config is not None:
        context["app_config"] = app_config
    config = {"metadata": {}}
    if available_skills is not None:
        config["metadata"]["available_skills"] = available_skills
    return SimpleNamespace(context=context, config=config)


def _skill(tmp_path: Path, name: str = "demo-skill") -> Skill:
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    skill_file = skill_dir / SKILL_MD_FILE
    skill_file.write_text("# Demo Skill\n\nUse this skill.", encoding="utf-8")
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "notes.md").write_text("Extra notes", encoding="utf-8")
    return Skill(
        name=name,
        description="Demo skill",
        license=None,
        skill_dir=skill_dir,
        skill_file=skill_file,
        relative_path=Path(name),
        category=SkillCategory.PUBLIC,
        enabled=True,
    )


def _storage(skills: list[Skill]) -> SimpleNamespace:
    def get_skill(name: str, *, enabled_only: bool = False):
        return next((skill for skill in skills if skill.name == name), None)

    return SimpleNamespace(get_skill=get_skill)


def test_skill_load_loads_enabled_skill_main_file(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda: _storage([skill]),
    )

    result = skill_load_tool.func(runtime=_runtime(), skill_name="demo-skill")

    assert "# Demo Skill" in result


def test_skill_load_loads_referenced_file_inside_skill(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda: _storage([skill]),
    )

    result = skill_load_tool.func(runtime=_runtime(), skill_name="demo-skill", file_path="references/notes.md")

    assert result == "Extra notes"


def test_skill_load_normalizes_referenced_file_path(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda: _storage([skill]),
    )

    result = skill_load_tool.func(runtime=_runtime(), skill_name="demo-skill", file_path=" ./references/notes.md ")

    assert result == "Extra notes"


def test_skill_load_rejects_path_traversal(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda: _storage([skill]),
    )

    result = skill_load_tool.func(runtime=_runtime(), skill_name="demo-skill", file_path="../secret.txt")

    assert "parent-directory traversal" in result


def test_skill_load_reports_missing_or_disabled_skill(monkeypatch):
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda: _storage([]),
    )

    result = skill_load_tool.func(runtime=_runtime(), skill_name="demo-skill")

    assert result == "Error: Skill not found or disabled: demo-skill"


def test_skill_load_rejects_skill_outside_runtime_allowlist(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda: _storage([skill]),
    )

    result = skill_load_tool.func(runtime=_runtime(available_skills=["other-skill"]), skill_name="demo-skill")

    assert result == "Error: Skill is not available to this agent: demo-skill"


def test_skill_load_falls_back_to_metadata_when_context_allowlist_is_none(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda: _storage([skill]),
    )
    runtime = SimpleNamespace(
        context={"available_skills": None},
        config={"metadata": {"available_skills": ["other-skill"]}},
    )

    result = skill_load_tool.func(runtime=runtime, skill_name="demo-skill")

    assert result == "Error: Skill is not available to this agent: demo-skill"


def test_skill_load_treats_string_available_skills_as_one_name(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda: _storage([skill]),
    )

    result = skill_load_tool.func(
        runtime=_runtime(available_skills="demo-skill"),
        skill_name="demo-skill",
    )

    assert "# Demo Skill" in result


def test_skill_load_rejects_unsupported_available_skills_type(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda: _storage([skill]),
    )

    result = skill_load_tool.func(
        runtime=_runtime(available_skills={"demo-skill": True}),
        skill_name="demo-skill",
    )

    assert result == "Error: available_skills must be None, a skill name string, or a collection of skill name strings."


def test_skill_load_rejects_non_string_available_skill_names(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda: _storage([skill]),
    )

    result = skill_load_tool.func(
        runtime=_runtime(available_skills=["demo-skill", 123]),
        skill_name="demo-skill",
    )

    assert result == "Error: available_skills collections must contain only skill name strings."


def test_skill_load_returns_generic_error_for_unexpected_failures(monkeypatch):
    class BrokenStorage:
        def get_skill(self, name: str, *, enabled_only: bool = False):
            raise RuntimeError("/private/path")

    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda: BrokenStorage(),
    )

    result = skill_load_tool.func(runtime=_runtime(), skill_name="demo-skill")

    assert result == "Error: Failed to load skill."


def test_skill_load_threads_runtime_app_config_to_storage(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    app_config = object()
    captured = {}

    def fake_get_or_new_skill_storage(*, app_config=None):
        captured["app_config"] = app_config
        return _storage([skill])

    monkeypatch.setattr(skill_load_module, "get_or_new_skill_storage", fake_get_or_new_skill_storage)

    result = skill_load_tool.func(runtime=_runtime(app_config=app_config), skill_name="demo-skill")

    assert "# Demo Skill" in result
    assert captured["app_config"] is app_config


def test_skill_load_truncates_large_output(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    skill.skill_file.write_text("abcdef", encoding="utf-8")
    app_config = SimpleNamespace(sandbox=SimpleNamespace(read_file_output_max_chars=3))
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda *, app_config=None: _storage([skill]),
    )

    result = skill_load_tool.func(runtime=_runtime(app_config=app_config), skill_name="demo-skill")

    assert result == "abc\n\n... [truncated: showing first 3 characters]"


def test_skill_load_does_not_truncate_when_max_chars_is_negative(monkeypatch, tmp_path):
    skill = _skill(tmp_path)
    skill.skill_file.write_text("abcdef", encoding="utf-8")
    app_config = SimpleNamespace(sandbox=SimpleNamespace(read_file_output_max_chars=-1))
    monkeypatch.setattr(
        skill_load_module,
        "get_or_new_skill_storage",
        lambda *, app_config=None: _storage([skill]),
    )

    result = skill_load_tool.func(runtime=_runtime(app_config=app_config), skill_name="demo-skill")

    assert result == "abcdef"

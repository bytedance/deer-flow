from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from deerflow.agents.middlewares import skill_activation_middleware as middleware_module
from deerflow.agents.middlewares.skill_activation_middleware import (
    _SLASH_SKILL_PROCESSED_KEY,
    SkillActivationMiddleware,
    is_slash_skill_activation_reminder,
)
from deerflow.skills.slash import parse_slash_skill_reference, resolve_slash_skill
from deerflow.skills.types import Skill, SkillCategory


def _make_skill(tmp_path: Path, name: str, content: str = "skill body") -> Skill:
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return Skill(
        name=name,
        description=f"Description for {name}",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_file,
        relative_path=Path(name),
        category=SkillCategory.CUSTOM,
        enabled=True,
    )


def test_parse_slash_skill_reference_extracts_name_and_remaining_text():
    parsed = parse_slash_skill_reference("  /data-analysis analyze uploads/foo.csv")

    assert parsed is not None
    assert parsed.name == "data-analysis"
    assert parsed.remaining_text == "analyze uploads/foo.csv"


def test_parse_slash_skill_reference_rejects_invalid_names():
    assert parse_slash_skill_reference("/DataAnalysis run") is None
    assert parse_slash_skill_reference("/data_analysis run") is None
    assert parse_slash_skill_reference("please use /data-analysis") is None


def test_resolve_slash_skill_respects_available_skill_whitelist(tmp_path):
    skill = _make_skill(tmp_path, "data-analysis")

    assert resolve_slash_skill("/data-analysis run", [skill], available_skills=set()) is None

    resolved = resolve_slash_skill("/data-analysis run", [skill], available_skills={"data-analysis"})
    assert resolved is not None
    assert resolved.skill.name == "data-analysis"
    assert resolved.remaining_text == "run"
    assert resolved.container_file_path == "/mnt/skills/custom/data-analysis/SKILL.md"


def test_skill_activation_middleware_injects_hidden_skill_context(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    storage = SimpleNamespace(
        load_skills=lambda *, enabled_only: [skill],
        get_container_root=lambda: "/mnt/skills",
    )
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: storage)

    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis analyze uploads/foo.csv", id="msg-1")

    update = middleware.before_agent({"messages": [original]}, runtime=None)

    assert update is not None
    activation_msg, user_msg = update["messages"]
    assert is_slash_skill_activation_reminder(activation_msg)
    assert activation_msg.additional_kwargs["hide_from_ui"] is True
    assert "Use pandas." in activation_msg.content
    assert "<user_request>\nanalyze uploads/foo.csv\n</user_request>" in activation_msg.content
    assert user_msg.content == original.content
    assert user_msg.additional_kwargs[_SLASH_SKILL_PROCESSED_KEY] is True


def test_skill_activation_middleware_skips_already_processed_user_message(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis")
    storage = SimpleNamespace(
        load_skills=lambda *, enabled_only: [skill],
        get_container_root=lambda: "/mnt/skills",
    )
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: storage)

    middleware = SkillActivationMiddleware()
    processed = HumanMessage(
        content="/data-analysis run",
        id="msg-1__slash_user",
        additional_kwargs={_SLASH_SKILL_PROCESSED_KEY: True},
    )

    assert middleware.before_agent({"messages": [processed]}, runtime=None) is None


def test_skill_activation_middleware_respects_agent_skill_whitelist(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis")
    storage = SimpleNamespace(
        load_skills=lambda *, enabled_only: [skill],
        get_container_root=lambda: "/mnt/skills",
    )
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: storage)

    middleware = SkillActivationMiddleware(available_skills={"frontend-design"})

    assert middleware.before_agent({"messages": [HumanMessage(content="/data-analysis run")]}, runtime=None) is None

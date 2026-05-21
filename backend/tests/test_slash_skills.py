from pathlib import Path
from types import SimpleNamespace

from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares import skill_activation_middleware as middleware_module
from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware, is_slash_skill_activation_reminder
from deerflow.skills.slash import ORIGINAL_USER_CONTENT_KEY, parse_slash_skill_reference, resolve_slash_skill
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


def _make_storage(tmp_path: Path, skills: list[Skill]):
    return SimpleNamespace(
        load_skills=lambda *, enabled_only: [skill for skill in skills if skill.enabled] if enabled_only else skills,
        get_container_root=lambda: "/mnt/skills",
        get_skills_root_path=lambda: tmp_path,
    )


def _make_model_request(messages: list[HumanMessage]) -> ModelRequest:
    return ModelRequest(
        model=object(),
        messages=messages,
        state={"messages": list(messages)},
        runtime=None,
    )


def test_parse_slash_skill_reference_extracts_name_and_remaining_text():
    parsed = parse_slash_skill_reference("  /data-analysis analyze uploads/foo.csv")

    assert parsed is not None
    assert parsed.name == "data-analysis"
    assert parsed.remaining_text == "analyze uploads/foo.csv"


def test_parse_slash_skill_reference_accepts_cjk_text_without_space():
    parsed = parse_slash_skill_reference("/data-analysis分析这个文档")

    assert parsed is not None
    assert parsed.name == "data-analysis"
    assert parsed.remaining_text == "分析这个文档"


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


def test_resolve_slash_skill_rejects_disabled_skills(tmp_path):
    skill = _make_skill(tmp_path, "data-analysis")
    skill.enabled = False

    assert resolve_slash_skill("/data-analysis run", [skill]) is None


def test_skill_activation_middleware_injects_hidden_human_context_for_model_call(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis analyze uploads/foo.csv", id="msg-1")
    request = _make_model_request([original])
    captured = {}

    def handler(model_request: ModelRequest):
        captured["messages"] = model_request.messages
        return AIMessage(content="ok")

    result = middleware.wrap_model_call(request, handler)

    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    activation_msg, user_msg = captured["messages"]
    assert is_slash_skill_activation_reminder(activation_msg)
    assert activation_msg.additional_kwargs["hide_from_ui"] is True
    assert "Use pandas." in activation_msg.content
    assert "<user_request>\nanalyze uploads/foo.csv\n</user_request>" in activation_msg.content
    assert user_msg.content == original.content
    assert request.state["messages"] == [original]


def test_skill_activation_middleware_uses_original_user_content_when_uploads_are_injected(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    original = HumanMessage(
        content="<uploaded_files>\n- report.pdf\n</uploaded_files>\n\n/data-analysis分析这个文档",
        id="msg-1",
        additional_kwargs={ORIGINAL_USER_CONTENT_KEY: "/data-analysis分析这个文档"},
    )
    captured = {}

    def handler(model_request: ModelRequest):
        captured["messages"] = model_request.messages
        return AIMessage(content="ok")

    result = middleware.wrap_model_call(_make_model_request([original]), handler)

    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    activation_msg, user_msg = captured["messages"]
    assert is_slash_skill_activation_reminder(activation_msg)
    assert "Use pandas." in activation_msg.content
    assert "<user_request>\n分析这个文档\n</user_request>" in activation_msg.content
    assert user_msg.content == original.content
    assert user_msg.additional_kwargs[ORIGINAL_USER_CONTENT_KEY] == "/data-analysis分析这个文档"


def test_skill_activation_middleware_returns_clear_error_for_disallowed_skill(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware(available_skills={"frontend-design"})
    original = HumanMessage(content="/data-analysis run")

    def handler(model_request: ModelRequest):
        raise AssertionError("handler should not be called for invalid slash skills")

    result = middleware.wrap_model_call(_make_model_request([original]), handler)

    assert isinstance(result, AIMessage)
    assert "not enabled or is not available" in result.content


def test_skill_activation_middleware_rejects_skill_file_outside_skills_root(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "custom" / "data-analysis"
    skill_dir.mkdir(parents=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "SKILL.md"
    outside_file.write_text("# Leaked\nDo not read me.", encoding="utf-8")
    (skill_dir / "SKILL.md").symlink_to(outside_file)
    skill = Skill(
        name="data-analysis",
        description="Description for data-analysis",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_dir / "SKILL.md",
        relative_path=Path("data-analysis"),
        category=SkillCategory.CUSTOM,
        enabled=True,
    )
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(skills_root, [skill]))

    middleware = SkillActivationMiddleware()

    def handler(model_request: ModelRequest):
        raise AssertionError("handler should not be called when SKILL.md fails safety checks")

    result = middleware.wrap_model_call(_make_model_request([HumanMessage(content="/data-analysis run")]), handler)

    assert isinstance(result, AIMessage)
    assert "could not be loaded safely" in result.content

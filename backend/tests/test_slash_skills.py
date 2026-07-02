import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage

from app.channels.commands import KNOWN_CHANNEL_COMMANDS
from deerflow.agents.middlewares import skill_activation_middleware as middleware_module
from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware, is_slash_skill_activation_reminder
from deerflow.skills.slash import RESERVED_SLASH_SKILL_NAMES, parse_slash_skill_reference, resolve_slash_skill
from deerflow.skills.types import Skill, SkillCategory
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY


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


def _make_model_request(messages: list[HumanMessage], *, runtime=None) -> ModelRequest:
    return ModelRequest(
        model=object(),
        messages=messages,
        state={"messages": list(messages)},
        runtime=runtime,
    )


def test_parse_slash_skill_reference_extracts_name_and_remaining_text():
    parsed = parse_slash_skill_reference("/data-analysis analyze uploads/foo.csv")

    assert parsed is not None
    assert parsed.name == "data-analysis"
    assert parsed.remaining_text == "analyze uploads/foo.csv"


def test_parse_slash_skill_reference_accepts_skill_name_without_task():
    parsed = parse_slash_skill_reference("/data-analysis")

    assert parsed is not None
    assert parsed.name == "data-analysis"
    assert parsed.remaining_text == ""


def test_parse_slash_skill_reference_rejects_invalid_names():
    assert parse_slash_skill_reference("/DataAnalysis run") is None
    assert parse_slash_skill_reference("/data_analysis run") is None
    assert parse_slash_skill_reference("please use /data-analysis") is None
    assert parse_slash_skill_reference("  /data-analysis run") is None
    assert parse_slash_skill_reference("/data-analysis分析这个文档") is None


def test_resolve_slash_skill_ignores_reserved_control_commands(tmp_path):
    for command in ["bootstrap", "help", "memory", "models", "new", "status"]:
        skill = _make_skill(tmp_path, command)

        assert resolve_slash_skill(f"/{command} create an agent", [skill]) is None


def test_reserved_slash_skill_names_match_channel_commands():
    assert RESERVED_SLASH_SKILL_NAMES == {command.removeprefix("/") for command in KNOWN_CHANNEL_COMMANDS}


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


def test_skill_activation_middleware_does_not_duplicate_existing_activation(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis analyze uploads/foo.csv", id="msg-1")
    first_capture = {}

    def first_handler(model_request: ModelRequest):
        first_capture["messages"] = model_request.messages
        return AIMessage(content="ok")

    first_result = middleware.wrap_model_call(_make_model_request([original]), first_handler)

    assert isinstance(first_result, AIMessage)
    activation_msg, user_msg = first_capture["messages"]
    assert is_slash_skill_activation_reminder(activation_msg)

    second_capture = {}

    def second_handler(model_request: ModelRequest):
        second_capture["messages"] = model_request.messages
        return AIMessage(content="ok")

    second_result = middleware.wrap_model_call(_make_model_request([activation_msg, user_msg]), second_handler)

    assert isinstance(second_result, AIMessage)
    assert second_capture["messages"] == [activation_msg, user_msg]
    assert sum(is_slash_skill_activation_reminder(message) for message in second_capture["messages"]) == 1


def test_skill_activation_middleware_does_not_duplicate_activation_separated_by_hidden_context(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis analyze uploads/foo.csv", id="msg-1")
    first_capture = {}

    def first_handler(model_request: ModelRequest):
        first_capture["messages"] = model_request.messages
        return AIMessage(content="ok")

    middleware.wrap_model_call(_make_model_request([original]), first_handler)
    activation_msg, user_msg = first_capture["messages"]
    hidden_context = HumanMessage(content="dynamic context", additional_kwargs={"hide_from_ui": True})
    second_capture = {}

    def second_handler(model_request: ModelRequest):
        second_capture["messages"] = model_request.messages
        return AIMessage(content="ok")

    second_result = middleware.wrap_model_call(_make_model_request([activation_msg, hidden_context, user_msg]), second_handler)

    assert isinstance(second_result, AIMessage)
    assert second_capture["messages"] == [activation_msg, hidden_context, user_msg]
    assert sum(is_slash_skill_activation_reminder(message) for message in second_capture["messages"]) == 1


def test_skill_activation_middleware_dedupes_immediately_previous_activation_without_target_id(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    legacy_activation_msg = SkillActivationMiddleware._make_activation_message(
        HumanMessage(content="/data-analysis analyze uploads/foo.csv"),
        "existing activation context",
    )
    target = HumanMessage(content="/data-analysis analyze uploads/foo.csv", id="msg-1")
    captured = {}

    def handler(model_request: ModelRequest):
        captured["messages"] = model_request.messages
        return AIMessage(content="ok")

    result = middleware.wrap_model_call(_make_model_request([legacy_activation_msg, target]), handler)

    assert isinstance(result, AIMessage)
    assert captured["messages"] == [legacy_activation_msg, target]
    assert sum(is_slash_skill_activation_reminder(message) for message in captured["messages"]) == 1


def test_skill_activation_middleware_async_injects_hidden_human_context_for_model_call(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis analyze uploads/foo.csv", id="msg-1")
    request = _make_model_request([original])
    captured = {}

    async def handler(model_request: ModelRequest):
        captured["messages"] = model_request.messages
        return AIMessage(content="ok")

    result = asyncio.run(middleware.awrap_model_call(request, handler))

    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    activation_msg, user_msg = captured["messages"]
    assert is_slash_skill_activation_reminder(activation_msg)
    assert activation_msg.additional_kwargs["hide_from_ui"] is True
    assert "Use pandas." in activation_msg.content
    assert "<user_request>\nanalyze uploads/foo.csv\n</user_request>" in activation_msg.content
    assert user_msg.content == original.content
    assert request.state["messages"] == [original]


def test_skill_activation_middleware_uses_fallback_when_task_text_is_empty(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis", id="msg-1")
    captured = {}

    def handler(model_request: ModelRequest):
        captured["messages"] = model_request.messages
        return AIMessage(content="ok")

    result = middleware.wrap_model_call(_make_model_request([original]), handler)

    assert isinstance(result, AIMessage)
    activation_msg = captured["messages"][0]
    assert "No additional task text was provided after the slash skill command." in activation_msg.content


def test_skill_activation_middleware_uses_original_user_content_when_uploads_are_injected(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    original = HumanMessage(
        content="<uploaded_files>\n- report.pdf\n</uploaded_files>\n\n/data-analysis 分析这个文档",
        id="msg-1",
        additional_kwargs={ORIGINAL_USER_CONTENT_KEY: "/data-analysis 分析这个文档"},
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
    assert user_msg.additional_kwargs[ORIGINAL_USER_CONTENT_KEY] == "/data-analysis 分析这个文档"


def test_skill_activation_middleware_activates_from_list_content(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    original = HumanMessage(content=[{"type": "text", "text": "/data-analysis analyze uploads/foo.csv"}], id="msg-1")
    captured = {}

    def handler(model_request: ModelRequest):
        captured["messages"] = model_request.messages
        return AIMessage(content="ok")

    result = middleware.wrap_model_call(_make_model_request([original]), handler)

    assert isinstance(result, AIMessage)
    activation_msg, user_msg = captured["messages"]
    assert is_slash_skill_activation_reminder(activation_msg)
    assert "<user_request>\nanalyze uploads/foo.csv\n</user_request>" in activation_msg.content
    assert user_msg.content == original.content


def test_skill_activation_middleware_records_activation_audit_event(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    recorded = []
    journal = SimpleNamespace(record_middleware=lambda *args, **kwargs: recorded.append((args, kwargs)))
    runtime = SimpleNamespace(context={"__run_journal": journal})
    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis analyze uploads/foo.csv", id="msg-1")

    def handler(model_request: ModelRequest):
        return AIMessage(content="ok")

    result = middleware.wrap_model_call(_make_model_request([original], runtime=runtime), handler)

    assert isinstance(result, AIMessage)
    assert len(recorded) == 1
    args, kwargs = recorded[0]
    assert args == ("skill_activation",)
    assert kwargs["name"] == "SkillActivationMiddleware"
    assert kwargs["hook"] == "wrap_model_call"
    assert kwargs["action"] == "activate"
    assert kwargs["changes"] == {
        "skill_name": "data-analysis",
        "category": "custom",
        "path": "/mnt/skills/custom/data-analysis/SKILL.md",
        "content_hash": hashlib.sha256(b"# Data Analysis\nUse pandas.").hexdigest(),
    }


def test_skill_activation_middleware_async_records_activation_audit_event(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    recorded = []
    journal = SimpleNamespace(record_middleware=lambda *args, **kwargs: recorded.append((args, kwargs)))
    runtime = SimpleNamespace(context={"__run_journal": journal})
    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis analyze uploads/foo.csv", id="msg-1")

    async def handler(model_request: ModelRequest):
        return AIMessage(content="ok")

    result = asyncio.run(middleware.awrap_model_call(_make_model_request([original], runtime=runtime), handler))

    assert isinstance(result, AIMessage)
    assert len(recorded) == 1
    args, kwargs = recorded[0]
    assert args == ("skill_activation",)
    assert kwargs["hook"] == "awrap_model_call"
    assert kwargs["changes"]["skill_name"] == "data-analysis"
    assert kwargs["changes"]["content_hash"] == hashlib.sha256(b"# Data Analysis\nUse pandas.").hexdigest()


def test_skill_activation_middleware_ignores_activation_audit_errors(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    journal = SimpleNamespace(record_middleware=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    runtime = SimpleNamespace(context={"__run_journal": journal})
    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis analyze uploads/foo.csv", id="msg-1")

    def handler(model_request: ModelRequest):
        return AIMessage(content="ok")

    result = middleware.wrap_model_call(_make_model_request([original], runtime=runtime), handler)

    assert isinstance(result, AIMessage)
    assert result.content == "ok"


def test_skill_activation_middleware_activates_only_latest_real_user_message(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    old_slash = HumanMessage(content="/data-analysis old request", id="msg-1")
    latest_user = HumanMessage(content="continue normally", id="msg-2")
    request = _make_model_request([old_slash, AIMessage(content="done"), latest_user])
    captured = {}

    def handler(model_request: ModelRequest):
        captured["messages"] = model_request.messages
        return AIMessage(content="ok")

    result = middleware.wrap_model_call(request, handler)

    assert isinstance(result, AIMessage)
    assert captured["messages"] == request.messages
    assert not any(is_slash_skill_activation_reminder(message) for message in captured["messages"])


def test_skill_activation_middleware_ignores_hidden_user_messages(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis", content="# Data Analysis\nUse pandas.")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    real_user = HumanMessage(content="continue normally", id="msg-1")
    hidden_slash = HumanMessage(content="/data-analysis hidden request", id="msg-2", additional_kwargs={"hide_from_ui": True})
    request = _make_model_request([real_user, hidden_slash])
    captured = {}

    def handler(model_request: ModelRequest):
        captured["messages"] = model_request.messages
        return AIMessage(content="ok")

    result = middleware.wrap_model_call(request, handler)

    assert isinstance(result, AIMessage)
    assert captured["messages"] == request.messages
    assert not any(is_slash_skill_activation_reminder(message) for message in captured["messages"])


def test_skill_activation_middleware_ignores_legacy_summary_messages():
    summary_msg = HumanMessage(content="/data-analysis should not activate from summary", name="summary")

    assert middleware_module._is_user_activation_target(summary_msg) is False


def test_skill_activation_middleware_returns_clear_error_for_disallowed_skill(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware(available_skills={"frontend-design"})
    original = HumanMessage(content="/data-analysis run")

    def handler(model_request: ModelRequest):
        raise AssertionError("handler should not be called for invalid slash skills")

    result = middleware.wrap_model_call(_make_model_request([original]), handler)

    assert isinstance(result, AIMessage)
    assert "not available for this agent" in result.content


def test_skill_activation_middleware_returns_clear_error_for_missing_skill(monkeypatch, tmp_path):
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, []))

    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis run")

    def handler(model_request: ModelRequest):
        raise AssertionError("handler should not be called for missing slash skills")

    result = middleware.wrap_model_call(_make_model_request([original]), handler)

    assert isinstance(result, AIMessage)
    assert "not installed" in result.content


def test_skill_activation_middleware_returns_clear_error_for_disabled_skill(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis")
    skill.enabled = False
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis run")

    def handler(model_request: ModelRequest):
        raise AssertionError("handler should not be called for disabled slash skills")

    result = middleware.wrap_model_call(_make_model_request([original]), handler)

    assert isinstance(result, AIMessage)
    assert "installed but disabled" in result.content


def test_skill_activation_middleware_escapes_activation_content(monkeypatch, tmp_path):
    skill = _make_skill(
        tmp_path,
        "data-analysis",
        content="# Data Analysis\nUse <xml> & avoid </skill> collisions.\n----- END SKILL.md -----",
    )
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()
    original = HumanMessage(content="/data-analysis analyze </user_request>")
    captured = {}

    def handler(model_request: ModelRequest):
        captured["messages"] = model_request.messages
        return AIMessage(content="ok")

    result = middleware.wrap_model_call(_make_model_request([original]), handler)

    assert isinstance(result, AIMessage)
    activation_msg = captured["messages"][0]
    assert '<skill_content encoding="xml-escaped">' in activation_msg.content
    assert "analyze &lt;/user_request&gt;" in activation_msg.content
    assert "Use &lt;xml&gt; &amp; avoid &lt;/skill&gt; collisions." in activation_msg.content
    assert "----- BEGIN SKILL.md -----" not in activation_msg.content


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


def test_skill_activation_middleware_reports_missing_skill_file_safely(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis")
    skill.skill_file.unlink()
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()

    def handler(model_request: ModelRequest):
        raise AssertionError("handler should not be called when SKILL.md is missing")

    result = middleware.wrap_model_call(_make_model_request([HumanMessage(content="/data-analysis run")]), handler)

    assert isinstance(result, AIMessage)
    assert "could not be loaded safely" in result.content


def test_skill_activation_middleware_reports_invalid_utf8_skill_file_safely(monkeypatch, tmp_path):
    skill = _make_skill(tmp_path, "data-analysis")
    skill.skill_file.write_bytes(b"\xff\xfe\x00")
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kwargs: _make_storage(tmp_path, [skill]))

    middleware = SkillActivationMiddleware()

    def handler(model_request: ModelRequest):
        raise AssertionError("handler should not be called when SKILL.md is not valid UTF-8")

    result = middleware.wrap_model_call(_make_model_request([HumanMessage(content="/data-analysis run")]), handler)

    assert isinstance(result, AIMessage)
    assert "could not be loaded safely" in result.content

"""Tests for Gemma 4 detection, factory gating, sanitization, and cleanup middleware."""

from __future__ import annotations

from langchain.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.lead_agent import prompt as prompt_module
from deerflow.agents.middlewares.gemma_thought_cleanup_middleware import (
    GemmaThoughtCleanupMiddleware,
)
from deerflow.agents.middlewares.title_middleware import TitleMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.models import factory as factory_module
from deerflow.utils.text_sanitize import strip_gemma_channel_blocks, strip_symbols_and_invisibles

# ---------------------------------------------------------------------------
# Shared helpers (mirror test_model_factory.py patterns)
# ---------------------------------------------------------------------------


def _make_app_config(models: list[ModelConfig]) -> AppConfig:
    return AppConfig(
        models=models,
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )


def _make_model(name: str = "gemma4-4b", *, family: str | None = None, **extras) -> ModelConfig:
    kwargs = dict(
        name=name,
        display_name=name,
        description=None,
        use="langchain_ollama:ChatOllama",
        model=name,
    )
    if family is not None:
        kwargs["family"] = family
    kwargs.update(extras)
    return ModelConfig(**kwargs)


class FakeChatModel(BaseChatModel):
    captured_kwargs: dict = {}

    def __init__(self, **kwargs):
        FakeChatModel.captured_kwargs = dict(kwargs)
        super().__init__(**kwargs)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError

    def _stream(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError


def _patch_factory(monkeypatch, app_config: AppConfig, model_class=FakeChatModel):
    monkeypatch.setattr(factory_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: model_class)
    monkeypatch.setattr(factory_module, "build_tracing_callbacks", lambda: [])


# ---------------------------------------------------------------------------
# 1. Detection: is_gemma4
# ---------------------------------------------------------------------------


def test_is_gemma4_matches_name_prefix():
    assert factory_module.is_gemma4(_make_model("gemma4-4b")) is True
    assert factory_module.is_gemma4(_make_model("gemma4-27b")) is True


def test_is_gemma4_matches_explicit_family():
    assert factory_module.is_gemma4(_make_model("custom-name", family="gemma4")) is True


def test_is_gemma4_false_for_non_gemma_models():
    assert factory_module.is_gemma4(_make_model("claude-opus-4-7")) is False
    assert factory_module.is_gemma4(_make_model("gpt-4o")) is False
    assert factory_module.is_gemma4(None) is False


# ---------------------------------------------------------------------------
# 2-4. Factory gating — temperature override and top-p/k setdefault
# ---------------------------------------------------------------------------


def test_gemma4_hard_overrides_temperature(monkeypatch):
    """Even when config explicitly sets 0.7, Gemma 4 must end up at 0.9."""
    cfg = _make_app_config([_make_model("gemma4-4b", temperature=0.7)])
    _patch_factory(monkeypatch, cfg)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="gemma4-4b")

    assert FakeChatModel.captured_kwargs["temperature"] == 0.9


def test_gemma4_sets_top_p_and_top_k_defaults(monkeypatch):
    cfg = _make_app_config([_make_model("gemma4-4b")])
    _patch_factory(monkeypatch, cfg)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="gemma4-4b")

    assert FakeChatModel.captured_kwargs["top_p"] == 0.95
    assert FakeChatModel.captured_kwargs["top_k"] == 64


def test_gemma4_respects_explicit_top_p_override(monkeypatch):
    cfg = _make_app_config([_make_model("gemma4-4b", top_p=0.8)])
    _patch_factory(monkeypatch, cfg)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="gemma4-4b")

    assert FakeChatModel.captured_kwargs["top_p"] == 0.8
    assert FakeChatModel.captured_kwargs["top_k"] == 64


def test_non_gemma_temperature_untouched(monkeypatch):
    cfg = _make_app_config([_make_model("claude-opus", temperature=0.7)])
    _patch_factory(monkeypatch, cfg)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="claude-opus")

    assert FakeChatModel.captured_kwargs["temperature"] == 0.7
    assert "top_p" not in FakeChatModel.captured_kwargs
    assert "top_k" not in FakeChatModel.captured_kwargs


def test_family_field_is_excluded_from_kwargs(monkeypatch):
    """`family` is an internal marker and must not reach the provider constructor."""
    cfg = _make_app_config([_make_model("gemma-custom", family="gemma4")])
    _patch_factory(monkeypatch, cfg)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="gemma-custom")

    assert "family" not in FakeChatModel.captured_kwargs


# ---------------------------------------------------------------------------
# 5-6. Sanitizer utilities
# ---------------------------------------------------------------------------


def test_strip_symbols_removes_emoji_and_pictographs():
    assert strip_symbols_and_invisibles("Hello 🔥 World") == "Hello  World"
    assert strip_symbols_and_invisibles("Flag 🇩🇪 here") == "Flag  here"


def test_strip_symbols_removes_invisibles_and_bidi():
    # ZWSP, BiDi override, BOM, soft hyphen
    assert strip_symbols_and_invisibles("zero\u200bwidth") == "zerowidth"
    assert strip_symbols_and_invisibles("Normal\u202etext") == "Normaltext"


def test_strip_symbols_removes_private_use_nerdfont():
    # U+F000 is in the BMP PUA range (typical Nerdfont glyph)
    assert strip_symbols_and_invisibles("Nerd\uf000icon") == "Nerdicon"


def test_strip_symbols_preserves_common_text():
    assert strip_symbols_and_invisibles("a < b and c > d") == "a < b and c > d"
    assert strip_symbols_and_invisibles('JSON {"x": 1}') == 'JSON {"x": 1}'


def test_strip_gemma_channel_removes_block():
    text = "before <|channel>thought\ninternal<channel|> after"
    assert strip_gemma_channel_blocks(text) == "before  after"


def test_strip_gemma_channel_leaves_plain_text():
    assert strip_gemma_channel_blocks("ordinary text") == "ordinary text"


# ---------------------------------------------------------------------------
# 7-8. GemmaThoughtCleanupMiddleware
# ---------------------------------------------------------------------------


class _FakeModelRequest:
    """Stand-in for langchain.agents.middleware.types.ModelRequest."""

    def __init__(self, messages: list):
        self.messages = messages

    def override(self, *, messages):
        return _FakeModelRequest(messages)


def _run_wrap(messages: list) -> list:
    """Drive the middleware once and capture the messages it passes downstream."""
    mw = GemmaThoughtCleanupMiddleware()
    captured: list = []

    def handler(request):
        captured.append(request.messages)
        return "result"

    mw.wrap_model_call(_FakeModelRequest(messages), handler)
    return captured[0]


def test_cleanup_strips_channel_blocks_from_ai_messages():
    ai = AIMessage(id="m1", content="Hi <|channel>thought\nsecret<channel|> ok")
    result = _run_wrap([HumanMessage(content="hello"), ai])

    ai_out = result[1]
    assert isinstance(ai_out, AIMessage)
    assert "channel" not in ai_out.content
    assert ai_out.id == "m1"  # same ID → LangGraph reducer replaces original


def test_cleanup_noop_when_no_channel_blocks():
    ai = AIMessage(id="m1", content="Just a normal answer")
    captured = _run_wrap([ai])
    # No change → middleware returns the same list (handler still runs)
    assert captured[0].content == "Just a normal answer"


def test_cleanup_leaves_other_message_types_untouched():
    ai = AIMessage(id="m1", content="Reply <|channel>t\nx<channel|> done")
    tool_msg = ToolMessage(content="tool-result", tool_call_id="call-1")
    result = _run_wrap([HumanMessage(content="q"), ai, tool_msg])

    assert isinstance(result[0], HumanMessage)
    assert result[0].content == "q"
    assert isinstance(result[2], ToolMessage)
    assert result[2].content == "tool-result"


def test_cleanup_skips_in_flight_tool_sequence():
    """AIMessages with unresolved tool_calls must retain their thoughts."""
    ai = AIMessage(
        id="m1",
        content="deciding <|channel>t\nreason<channel|>",
        tool_calls=[{"name": "bash", "args": {"cmd": "ls"}, "id": "tc-1"}],
    )
    result = _run_wrap([HumanMessage(content="run ls"), ai])

    # No ToolMessage for tc-1 yet → sequence still in flight → skip
    assert "channel" in result[1].content


def test_cleanup_cleans_resolved_tool_sequence():
    ai = AIMessage(
        id="m1",
        content="decided <|channel>t\nreason<channel|>",
        tool_calls=[{"name": "bash", "args": {"cmd": "ls"}, "id": "tc-1"}],
    )
    tool = ToolMessage(content="ok", tool_call_id="tc-1")
    result = _run_wrap([HumanMessage(content="run ls"), ai, tool])

    # Tool call now resolved → the earlier AIMessage can be cleaned
    assert "channel" not in result[1].content


# ---------------------------------------------------------------------------
# 9-10. apply_prompt_template — Gemma 4 vs. default
# ---------------------------------------------------------------------------


def test_apply_prompt_template_without_model_name_keeps_emojis(monkeypatch):
    # Patch slow/skill-dependent functions to return empty strings
    monkeypatch.setattr(prompt_module, "get_skills_prompt_section", lambda *a, **k: "")
    monkeypatch.setattr(prompt_module, "get_deferred_tools_prompt_section", lambda *a, **k: "")
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda *a, **k: "")
    monkeypatch.setattr(prompt_module, "get_agent_soul", lambda *a, **k: "")
    monkeypatch.setattr(prompt_module, "_build_acp_section", lambda *a, **k: "")
    monkeypatch.setattr(prompt_module, "_build_custom_mounts_section", lambda *a, **k: "")

    out = prompt_module.apply_prompt_template(subagent_enabled=True, model_name=None)
    # Original template contains the rocket emoji in the subagent banner
    assert "🚀" in out
    assert "<ui_style_rules>" not in out


def test_apply_prompt_template_with_gemma4_strips_emojis_and_adds_ui_rules(monkeypatch):
    monkeypatch.setattr(prompt_module, "get_skills_prompt_section", lambda *a, **k: "")
    monkeypatch.setattr(prompt_module, "get_deferred_tools_prompt_section", lambda *a, **k: "")
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda *a, **k: "")
    monkeypatch.setattr(prompt_module, "get_agent_soul", lambda *a, **k: "")
    monkeypatch.setattr(prompt_module, "_build_acp_section", lambda *a, **k: "")
    monkeypatch.setattr(prompt_module, "_build_custom_mounts_section", lambda *a, **k: "")

    # Ensure the factory helper reports Gemma 4 for our test name
    monkeypatch.setattr(factory_module, "is_gemma4_by_name", lambda name: True)

    out = prompt_module.apply_prompt_template(subagent_enabled=True, model_name="gemma4-4b")
    assert "🚀" not in out
    assert "⛔" not in out
    assert "<gemma_output_rules>" in out
    assert "NO EMOJI" in out  # hard rule clearly stated
    assert "SUBAGENT MODE ACTIVE" in out  # core DeerFlow instructions preserved
    assert "<clarification_system>" in out  # other sections intact


# ---------------------------------------------------------------------------
# 11. TitleMiddleware — channel blocks are stripped alongside <think>
# ---------------------------------------------------------------------------


def test_title_middleware_strips_both_tag_styles():
    mw = TitleMiddleware()
    text = "<think>inner</think>Title core <|channel>thought\nx<channel|> tail"
    out = mw._strip_think_tags(text)
    assert "think" not in out
    assert "channel" not in out
    assert "Title core" in out
    assert "tail" in out


def test_title_middleware_untouched_when_no_tags():
    mw = TitleMiddleware()
    assert mw._strip_think_tags("plain title candidate") == "plain title candidate"

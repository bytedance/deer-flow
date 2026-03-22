"""Tests for deerflow.models.factory.create_chat_model."""

from __future__ import annotations

import pytest
from langchain.chat_models import BaseChatModel

from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.models import factory as factory_module
from deerflow.models import openai_codex_provider as codex_provider_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_config(models: list[ModelConfig]) -> AppConfig:
    return AppConfig(
        models=models,
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )


def _make_model(
    name: str = "test-model",
    *,
    use: str = "langchain_openai:ChatOpenAI",
    supports_thinking: bool = False,
    supports_reasoning_effort: bool = False,
    when_thinking_enabled: dict | None = None,
    thinking: dict | None = None,
    max_tokens: int | None = None,
) -> ModelConfig:
    return ModelConfig(
        name=name,
        display_name=name,
        description=None,
        use=use,
        model=name,
        max_tokens=max_tokens,
        supports_thinking=supports_thinking,
        supports_reasoning_effort=supports_reasoning_effort,
        when_thinking_enabled=when_thinking_enabled,
        thinking=thinking,
        supports_vision=False,
    )


class FakeChatModel(BaseChatModel):
    """Minimal BaseChatModel stub that records the kwargs it was called with."""

    captured_kwargs: dict = {}

    def __init__(self, **kwargs):
        # Store kwargs before pydantic processes them
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
    """Patch get_app_config, resolve_class, and tracing for isolated unit tests."""
    monkeypatch.setattr(factory_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: model_class)
    monkeypatch.setattr(factory_module, "is_tracing_enabled", lambda: False)


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------


def test_uses_first_model_when_name_is_none(monkeypatch):
    cfg = _make_app_config([_make_model("alpha"), _make_model("beta")])
    _patch_factory(monkeypatch, cfg)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name=None)

    # resolve_class is called — if we reach here without ValueError, the correct model was used
    assert FakeChatModel.captured_kwargs.get("model") == "alpha"


def test_raises_when_model_not_found(monkeypatch):
    cfg = _make_app_config([_make_model("only-model")])
    monkeypatch.setattr(factory_module, "get_app_config", lambda: cfg)
    monkeypatch.setattr(factory_module, "is_tracing_enabled", lambda: False)

    with pytest.raises(ValueError, match="ghost-model"):
        factory_module.create_chat_model(name="ghost-model")


# ---------------------------------------------------------------------------
# thinking_enabled=True
# ---------------------------------------------------------------------------


def test_thinking_enabled_raises_when_not_supported_but_when_thinking_enabled_is_set(monkeypatch):
    """supports_thinking guard fires only when when_thinking_enabled is configured —
    the factory uses that as the signal that the caller explicitly expects thinking to work."""
    wte = {"thinking": {"type": "enabled", "budget_tokens": 5000}}
    cfg = _make_app_config([_make_model("no-think", supports_thinking=False, when_thinking_enabled=wte)])
    _patch_factory(monkeypatch, cfg)

    with pytest.raises(ValueError, match="does not support thinking"):
        factory_module.create_chat_model(name="no-think", thinking_enabled=True)


def test_thinking_enabled_raises_for_empty_when_thinking_enabled_explicitly_set(monkeypatch):
    """supports_thinking guard fires when when_thinking_enabled is set to an empty dict —
    the user explicitly provided the section, so the guard must still fire even though
    effective_wte would be falsy."""
    cfg = _make_app_config([_make_model("no-think-empty", supports_thinking=False, when_thinking_enabled={})])
    _patch_factory(monkeypatch, cfg)

    with pytest.raises(ValueError, match="does not support thinking"):
        factory_module.create_chat_model(name="no-think-empty", thinking_enabled=True)


def test_thinking_enabled_merges_when_thinking_enabled_settings(monkeypatch):
    wte = {"temperature": 1.0, "max_tokens": 16000}
    cfg = _make_app_config([_make_model("thinker", supports_thinking=True, when_thinking_enabled=wte)])
    _patch_factory(monkeypatch, cfg)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="thinker", thinking_enabled=True)

    assert FakeChatModel.captured_kwargs.get("temperature") == 1.0
    assert FakeChatModel.captured_kwargs.get("max_tokens") == 16000


# ---------------------------------------------------------------------------
# thinking_enabled=False — disable logic
# ---------------------------------------------------------------------------


def test_thinking_disabled_openai_gateway_format(monkeypatch):
    """When thinking is configured via extra_body (OpenAI-compatible gateway),
    disabling must inject extra_body.thinking.type=disabled and reasoning_effort=minimal."""
    wte = {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}}
    cfg = _make_app_config(
        [
            _make_model(
                "openai-gw",
                supports_thinking=True,
                supports_reasoning_effort=True,
                when_thinking_enabled=wte,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="openai-gw", thinking_enabled=False)

    assert captured.get("extra_body") == {"thinking": {"type": "disabled"}}
    assert captured.get("reasoning_effort") == "minimal"
    assert "thinking" not in captured  # must NOT set the direct thinking param


def test_thinking_disabled_langchain_anthropic_format(monkeypatch):
    """When thinking is configured as a direct param (langchain_anthropic),
    disabling must inject thinking.type=disabled WITHOUT touching extra_body or reasoning_effort."""
    wte = {"thinking": {"type": "enabled", "budget_tokens": 8000}}
    cfg = _make_app_config(
        [
            _make_model(
                "anthropic-native",
                use="langchain_anthropic:ChatAnthropic",
                supports_thinking=True,
                supports_reasoning_effort=False,
                when_thinking_enabled=wte,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="anthropic-native", thinking_enabled=False)

    assert captured.get("thinking") == {"type": "disabled"}
    assert "extra_body" not in captured
    # reasoning_effort must be cleared (supports_reasoning_effort=False)
    assert captured.get("reasoning_effort") is None


def test_thinking_disabled_no_when_thinking_enabled_does_nothing(monkeypatch):
    """If when_thinking_enabled is not set, disabling thinking must not inject any kwargs."""
    cfg = _make_app_config([_make_model("plain", supports_thinking=True, when_thinking_enabled=None)])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="plain", thinking_enabled=False)

    assert "extra_body" not in captured
    assert "thinking" not in captured
    # reasoning_effort not forced (supports_reasoning_effort defaults to False → cleared)
    assert captured.get("reasoning_effort") is None


# ---------------------------------------------------------------------------
# reasoning_effort stripping
# ---------------------------------------------------------------------------


def test_reasoning_effort_cleared_when_not_supported(monkeypatch):
    cfg = _make_app_config([_make_model("no-effort", supports_reasoning_effort=False)])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="no-effort", thinking_enabled=False)

    assert captured.get("reasoning_effort") is None


def test_reasoning_effort_preserved_when_supported(monkeypatch):
    wte = {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 5000}}}
    cfg = _make_app_config(
        [
            _make_model(
                "effort-model",
                supports_thinking=True,
                supports_reasoning_effort=True,
                when_thinking_enabled=wte,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="effort-model", thinking_enabled=False)

    # When supports_reasoning_effort=True, it should NOT be cleared to None
    # The disable path sets it to "minimal"; supports_reasoning_effort=True keeps it
    assert captured.get("reasoning_effort") == "minimal"


# ---------------------------------------------------------------------------
# thinking shortcut field
# ---------------------------------------------------------------------------


def test_thinking_shortcut_enables_thinking_when_thinking_enabled(monkeypatch):
    """thinking shortcut alone should act as when_thinking_enabled with a `thinking` key."""
    thinking_settings = {"type": "enabled", "budget_tokens": 8000}
    cfg = _make_app_config(
        [
            _make_model(
                "shortcut-model",
                use="langchain_anthropic:ChatAnthropic",
                supports_thinking=True,
                thinking=thinking_settings,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="shortcut-model", thinking_enabled=True)

    assert captured.get("thinking") == thinking_settings


def test_thinking_shortcut_disables_thinking_when_thinking_disabled(monkeypatch):
    """thinking shortcut should participate in the disable path (langchain_anthropic format)."""
    thinking_settings = {"type": "enabled", "budget_tokens": 8000}
    cfg = _make_app_config(
        [
            _make_model(
                "shortcut-disable",
                use="langchain_anthropic:ChatAnthropic",
                supports_thinking=True,
                supports_reasoning_effort=False,
                thinking=thinking_settings,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="shortcut-disable", thinking_enabled=False)

    assert captured.get("thinking") == {"type": "disabled"}
    assert "extra_body" not in captured


def test_thinking_shortcut_merges_with_when_thinking_enabled(monkeypatch):
    """thinking shortcut should be merged into when_thinking_enabled when both are provided."""
    thinking_settings = {"type": "enabled", "budget_tokens": 8000}
    wte = {"max_tokens": 16000}
    cfg = _make_app_config(
        [
            _make_model(
                "merge-model",
                use="langchain_anthropic:ChatAnthropic",
                supports_thinking=True,
                thinking=thinking_settings,
                when_thinking_enabled=wte,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="merge-model", thinking_enabled=True)

    # Both the thinking shortcut and when_thinking_enabled settings should be applied
    assert captured.get("thinking") == thinking_settings
    assert captured.get("max_tokens") == 16000


def test_thinking_shortcut_not_leaked_into_model_when_disabled(monkeypatch):
    """thinking shortcut must not be passed raw to the model constructor (excluded from model_dump)."""
    thinking_settings = {"type": "enabled", "budget_tokens": 8000}
    cfg = _make_app_config(
        [
            _make_model(
                "no-leak",
                use="langchain_anthropic:ChatAnthropic",
                supports_thinking=True,
                supports_reasoning_effort=False,
                thinking=thinking_settings,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="no-leak", thinking_enabled=False)

    # The disable path should have set thinking to disabled (not the raw enabled shortcut)
    assert captured.get("thinking") == {"type": "disabled"}


# ---------------------------------------------------------------------------
# OpenAI-compatible providers (MiniMax, Novita, etc.)
# ---------------------------------------------------------------------------


def test_openai_compatible_provider_passes_base_url(monkeypatch):
    """OpenAI-compatible providers like MiniMax should pass base_url through to the model."""
    model = ModelConfig(
        name="minimax-m2.5",
        display_name="MiniMax M2.5",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="MiniMax-M2.5",
        base_url="https://api.minimax.io/v1",
        api_key="test-key",
        max_tokens=4096,
        temperature=1.0,
        supports_vision=True,
        supports_thinking=False,
    )
    cfg = _make_app_config([model])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="minimax-m2.5")

    assert captured.get("model") == "MiniMax-M2.5"
    assert captured.get("base_url") == "https://api.minimax.io/v1"
    assert captured.get("api_key") == "test-key"
    assert captured.get("temperature") == 1.0
    assert captured.get("max_tokens") == 4096


def test_openai_compatible_provider_multiple_models(monkeypatch):
    """Multiple models from the same OpenAI-compatible provider should coexist."""
    m1 = ModelConfig(
        name="minimax-m2.5",
        display_name="MiniMax M2.5",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="MiniMax-M2.5",
        base_url="https://api.minimax.io/v1",
        api_key="test-key",
        temperature=1.0,
        supports_vision=True,
        supports_thinking=False,
    )
    m2 = ModelConfig(
        name="minimax-m2.5-highspeed",
        display_name="MiniMax M2.5 Highspeed",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="MiniMax-M2.5-highspeed",
        base_url="https://api.minimax.io/v1",
        api_key="test-key",
        temperature=1.0,
        supports_vision=True,
        supports_thinking=False,
    )
    cfg = _make_app_config([m1, m2])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    # Create first model
    factory_module.create_chat_model(name="minimax-m2.5")
    assert captured.get("model") == "MiniMax-M2.5"

    # Create second model
    factory_module.create_chat_model(name="minimax-m2.5-highspeed")
    assert captured.get("model") == "MiniMax-M2.5-highspeed"


# ---------------------------------------------------------------------------
# Codex provider reasoning_effort mapping
# ---------------------------------------------------------------------------


class FakeCodexChatModel(FakeChatModel):
    pass


def test_codex_provider_disables_reasoning_when_thinking_disabled(monkeypatch):
    cfg = _make_app_config(
        [
            _make_model(
                "codex",
                use="deerflow.models.openai_codex_provider:CodexChatModel",
                supports_thinking=True,
                supports_reasoning_effort=True,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg, model_class=FakeCodexChatModel)
    monkeypatch.setattr(codex_provider_module, "CodexChatModel", FakeCodexChatModel)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="codex", thinking_enabled=False)

    assert FakeChatModel.captured_kwargs.get("reasoning_effort") == "none"


def test_codex_provider_preserves_explicit_reasoning_effort(monkeypatch):
    cfg = _make_app_config(
        [
            _make_model(
                "codex",
                use="deerflow.models.openai_codex_provider:CodexChatModel",
                supports_thinking=True,
                supports_reasoning_effort=True,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg, model_class=FakeCodexChatModel)
    monkeypatch.setattr(codex_provider_module, "CodexChatModel", FakeCodexChatModel)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="codex", thinking_enabled=True, reasoning_effort="high")

    assert FakeChatModel.captured_kwargs.get("reasoning_effort") == "high"


def test_codex_provider_defaults_reasoning_effort_to_medium(monkeypatch):
    cfg = _make_app_config(
        [
            _make_model(
                "codex",
                use="deerflow.models.openai_codex_provider:CodexChatModel",
                supports_thinking=True,
                supports_reasoning_effort=True,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg, model_class=FakeCodexChatModel)
    monkeypatch.setattr(codex_provider_module, "CodexChatModel", FakeCodexChatModel)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="codex", thinking_enabled=True)

    assert FakeChatModel.captured_kwargs.get("reasoning_effort") == "medium"


def test_codex_provider_strips_unsupported_max_tokens(monkeypatch):
    cfg = _make_app_config(
        [
            _make_model(
                "codex",
                use="deerflow.models.openai_codex_provider:CodexChatModel",
                supports_thinking=True,
                supports_reasoning_effort=True,
                max_tokens=4096,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg, model_class=FakeCodexChatModel)
    monkeypatch.setattr(codex_provider_module, "CodexChatModel", FakeCodexChatModel)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="codex", thinking_enabled=True)

    assert "max_tokens" not in FakeChatModel.captured_kwargs
    
    
def test_openai_responses_api_settings_are_passed_to_chatopenai(monkeypatch):
    model = ModelConfig(
        name="gpt-5-responses",
        display_name="GPT-5 Responses",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="gpt-5",
        api_key="test-key",
        use_responses_api=True,
        output_version="responses/v1",
        supports_thinking=False,
        supports_vision=True,
    )
    cfg = _make_app_config([model])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="gpt-5-responses")

    assert captured.get("use_responses_api") is True
    assert captured.get("output_version") == "responses/v1"

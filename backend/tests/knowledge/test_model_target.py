"""Unit tests for the RAG model-target resolver (spec 2026-09-23 default model D3).

The resolver is the one seam the RAG roles share: a caller picks its own role declaration
first (``rag.extract_model`` / ``rag.judge_model`` / ``rag.vlm_model``), hands it in as
``name``, and the helper answers only the "nothing declared, so what then" half — the RAG
default, else the first configured model. It is deliberately pure: no Qdrant, no SDK
construction, no network, no reading of the live global config unless the caller passes one.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from deerflow_knowledge.model_target import resolve_rag_model_name


def _config(*names: str, default_model: str | None = None):
    """A duck-typed AppConfig stand-in: the resolver only reads these two shapes."""
    return SimpleNamespace(
        models=[SimpleNamespace(name=name) for name in names],
        rag=SimpleNamespace(default_model=default_model),
    )


def test_explicit_role_name_is_returned_as_is():
    config = _config("A", "B", default_model="B")

    assert resolve_rag_model_name(config, "A") == "A"


def test_explicit_role_name_is_not_replaced_even_when_it_names_no_entry():
    """An explicit wrong name must reach the factory, which raises the not-found error.

    Substituting the RAG default here would silently swallow a typo the operator asked for.
    """
    config = _config("A", default_model="A")

    assert resolve_rag_model_name(config, "ghost") == "ghost"


def test_blank_role_name_falls_through_to_the_rag_default():
    """Blank means undeclared (D2), so it must not be treated as a name."""
    config = _config("A", "B", default_model="B")

    assert resolve_rag_model_name(config, "   ") == "B"


def test_rag_default_wins_over_the_first_model():
    config = _config("A", "B", default_model="B")

    assert resolve_rag_model_name(config) == "B"


def test_no_default_falls_back_to_the_first_configured_model():
    config = _config("A", "B")

    assert resolve_rag_model_name(config) == "A"


def test_a_stale_default_falls_back_to_the_first_model_and_is_named(caplog: pytest.LogCaptureFixture):
    """Only the RAG default itself may be silently superseded -- and never silently."""
    config = _config("A", "B", default_model="ghost")

    with caplog.at_level(logging.WARNING, logger="deerflow_knowledge.model_target"):
        assert resolve_rag_model_name(config) == "A"

    assert "ghost" in caplog.text


def test_no_models_at_all_returns_none_for_the_caller_to_report():
    """The resolver never invents a target: the RAG entry point turns this into an error."""
    assert resolve_rag_model_name(_config()) is None


def test_explicit_rag_snapshot_beats_the_live_config():
    """``rag=`` carries the save-time pending block, which has not been written yet."""
    config = _config("A", "B", default_model="A")
    pending = SimpleNamespace(default_model="B")

    assert resolve_rag_model_name(config, rag=pending) == "B"
    # The live config is left alone.
    assert config.rag.default_model == "A"


def test_pending_rag_snapshot_may_be_a_mapping():
    """The save path merges ``config.yaml`` with the payload into a plain dict (D2/D3)."""
    config = _config("A", "B", default_model="A")

    assert resolve_rag_model_name(config, rag={"default_model": "B"}) == "B"
    assert resolve_rag_model_name(config, rag={"default_model": None}) == "A"
    assert resolve_rag_model_name(config, rag={}) == "A"


def test_resolver_never_constructs_a_model(monkeypatch: pytest.MonkeyPatch):
    """Purity pin: resolving a name must not build an SDK client or touch the network."""
    import deerflow.models.factory as factory_module

    def _explode(*args, **kwargs):
        raise AssertionError("the resolver must not construct a model")

    monkeypatch.setattr(factory_module, "create_chat_model", _explode)

    assert resolve_rag_model_name(_config("A", default_model="A")) == "A"


# ── the pure missing-fields verdict (spec 2026-09-23 D10.1, R1/R14) ────────
#
# The strict rule covers UI-managed entries inside the protocol grid, and only targets the
# user *explicitly declared*: a name the system picked (`models[0]` fallback, or the RAG
# default standing in for a blank role) is never a reason to refuse a save or an ingest.
# Keys are required everywhere in the grid and must come from the entry itself — the
# environment is not a fallback (R14), which is what makes the rule checkable at all.
# Addresses are required for one cell only: the OpenAI-compatible cell, whose SDK has no
# readable default to borrow (D10.2). Definitions are imported inside the tests so this
# section can go red as assertions rather than as a collection error.

from deerflow.config.app_config import AppConfig, RagConfig  # noqa: E402
from deerflow.config.model_config import ModelConfig  # noqa: E402
from deerflow.config.models_config import resolve_provider_use  # noqa: E402
from deerflow.config.sandbox_config import SandboxConfig  # noqa: E402

SANDBOX = SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")


def _entry(
    name: str,
    *,
    provider: str = "openai-compatible",
    base_url: str | None = "https://ui.example/v1",
    api_key: str | None = "sk-ui",
) -> ModelConfig:
    """One settings-UI style entry; the endpoint key differs per provider (api_base for DeepSeek)."""
    extra: dict = {} if api_key is None else {"api_key": api_key}
    if base_url is not None:
        extra["api_base" if provider == "deepseek" else "base_url"] = base_url
    return ModelConfig(name=name, display_name=name, description=None, use=resolve_provider_use(provider) or "", model=f"{name}-wire", supports_thinking=False, **extra)


def _real_config(*entries: ModelConfig, ui: tuple[str, ...] = (), default_model: str | None = None) -> AppConfig:
    """A real AppConfig with the UI-source flag set explicitly.

    `AppConfig(...)` does not fill `_ui_model_names` (the loader does), so the flag is set
    here on purpose — and every test that depends on the scope asserts it first.
    """
    config = AppConfig(models=list(entries), sandbox=SANDBOX, rag=RagConfig(default_model=default_model))
    config._ui_model_names = set(ui)
    return config


def _missing(config, name, *, role: str = "评测裁判"):
    from deerflow_knowledge.model_target import rag_target_missing

    return rag_target_missing(config, name, role=role)


def test_the_ui_source_flag_is_what_the_rule_keys_off():
    config = _real_config(_entry("ui-model"), _entry("yaml-model"), ui=("ui-model",))

    assert config.is_ui_managed_model("ui-model") is True
    assert config.is_ui_managed_model("yaml-model") is False


def test_a_blank_declaration_is_never_a_missing_target():
    """`None` / whitespace means "nothing declared" (D2): the fallback is not a refusal reason."""
    config = _real_config(_entry("ui-model", api_key=None), ui=("ui-model",))

    assert _missing(config, None) is None
    assert _missing(config, "   ") is None


def test_a_ui_entry_in_the_grid_needs_its_own_key():
    config = _real_config(_entry("ui-model", api_key=None), ui=("ui-model",))

    reason = _missing(config, "ui-model")

    assert reason is not None
    assert "ui-model" in reason and "api_key" in reason


def test_a_whitespace_key_is_a_missing_key():
    config = _real_config(_entry("ui-model", api_key="   "), ui=("ui-model",))

    assert _missing(config, "ui-model") is not None


def test_the_environment_is_not_a_key_fallback(monkeypatch: pytest.MonkeyPatch):
    """R14: the entry must carry the key; a same-named host variable changes nothing."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-host")
    config = _real_config(_entry("ui-model", api_key=None), ui=("ui-model",))

    assert _missing(config, "ui-model", role="文档图片配文") is not None


def test_the_openai_compatible_cell_requires_an_address():
    config = _real_config(_entry("ui-model", base_url=None), ui=("ui-model",))

    reason = _missing(config, "ui-model", role="图谱抽取")

    assert reason is not None
    assert "base_url" in reason


def test_the_vendor_cells_borrow_their_sdk_default_address_instead():
    """anthropic / deepseek entries without an address are usable (D10.2): their SDKs ship one."""
    config = _real_config(_entry("claude", provider="anthropic", base_url=None), _entry("ds", provider="deepseek", base_url=None), ui=("claude", "ds"))

    assert _missing(config, "claude") is None
    assert _missing(config, "ds") is None


def test_entries_outside_the_grid_are_out_of_scope():
    non_ui = _real_config(_entry("yaml-model", api_key=None, base_url=None), ui=())
    vendor = _real_config(ModelConfig(name="vendor", display_name="vendor", description=None, use="langchain_community:ChatSomeVendor", model="m", supports_thinking=False), ui=("vendor",))

    assert _missing(non_ui, "yaml-model") is None
    assert _missing(vendor, "vendor") is None


def test_a_name_that_is_not_a_configured_entry_is_not_this_rule_s_error():
    """D9 keeps that error with the factory (runtime) and the save path's own mapping."""
    config = _real_config(_entry("ui-model"), ui=("ui-model",))

    assert _missing(config, "ghost") is None


def test_the_reason_does_not_depend_on_the_role():
    """One wording (D10.1): the entry and the missing field are named, nothing else."""
    config = _real_config(_entry("ui-model", api_key=None), ui=("ui-model",))

    reasons = {_missing(config, "ui-model", role=role) for role in ("图谱抽取", "评测裁判", "文档图片配文")}

    assert len(reasons) == 1


def test_the_verdict_constructs_nothing(monkeypatch: pytest.MonkeyPatch):
    """Purity pin: the verdict reads the entry through the config object and goes nowhere."""
    import deerflow.models.factory as factory_module

    def _explode(*args, **kwargs):
        raise AssertionError("the verdict must not construct a model")

    monkeypatch.setattr(factory_module, "create_chat_model", _explode)
    config = _real_config(_entry("ui-model"), ui=("ui-model",))

    assert _missing(config, "ui-model") is None

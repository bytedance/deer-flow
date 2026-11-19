"""Tests for the declarative model reasoning capability contract (issue #5073).

Covers three layers:

- ``ModelConfig.reasoning`` schema validation and legacy-boolean projection.
- ``deerflow.models.reasoning`` normalization and request resolution.
- The ``reasoning`` capabilities payload projected through ``/api/models``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deerflow.config.model_config import ModelConfig, ReasoningCapabilities, ReasoningEffortCapabilities
from deerflow.models.reasoning import (
    GENERIC_EFFORT_VALUES,
    ReasoningContract,
    ReasoningPolicyError,
    reasoning_capabilities_payload,
    resolve_reasoning_contract,
    resolve_reasoning_request,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model(**overrides) -> ModelConfig:
    values = {
        "name": "model",
        "display_name": "Model",
        "description": None,
        "use": "langchain_openai:ChatOpenAI",
        "model": "model",
    }
    values.update(overrides)
    return ModelConfig(**values)


def _glm_contract() -> dict:
    return {
        "thinking": "required",
        "dialect": "openai_extra_body",
        "history": "clear",
        "effort": {
            "values": ["low", "high", "max"],
            "default": "max",
            "aliases": {"minimal": "low", "medium": "high"},
        },
    }


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_reasoning_field_is_declared_and_optional():
    assert "reasoning" in ModelConfig.model_fields
    assert _model().reasoning is None


def test_contract_round_trips_and_projects_legacy_booleans():
    model = _model(reasoning=_glm_contract())

    assert isinstance(model.reasoning, ReasoningCapabilities)
    assert isinstance(model.reasoning.effort, ReasoningEffortCapabilities)
    assert model.reasoning.thinking == "required"
    assert model.reasoning.effort.values == ["low", "high", "max"]
    # Legacy readers keep working: the booleans are derived from the contract.
    assert model.supports_thinking is True
    assert model.supports_reasoning_effort is True


def test_contract_without_effort_projects_effort_unsupported():
    model = _model(reasoning={"thinking": "optional"})

    assert model.supports_thinking is True
    assert model.supports_reasoning_effort is False


def test_contract_unsupported_thinking_projects_false():
    model = _model(reasoning={"thinking": "unsupported", "effort": {"values": ["low", "high"]}})

    assert model.supports_thinking is False
    assert model.supports_reasoning_effort is True


@pytest.mark.parametrize("native", [True, False, "low", "medium", "high"])
def test_native_provider_reasoning_values_load_as_legacy_profiles(native):
    """``reasoning`` was an unrestricted provider kwarg before the contract existed;
    ChatOllama's boolean and level-string forms must keep loading and stay legacy."""
    model = _model(use="langchain_ollama:ChatOllama", reasoning=native)

    assert model.reasoning == native
    assert model.supports_thinking is False
    assert model.supports_reasoning_effort is False
    contract = resolve_reasoning_contract(model)
    assert contract.source == "legacy"
    assert contract.thinking == "unsupported"


def test_contract_is_excluded_from_provider_kwargs_by_the_factory_exclusion_list():
    """The factory excludes ``reasoning`` explicitly; pin the field name so a rename cannot leak it."""
    from deerflow.models import factory as factory_module

    assert "reasoning" in factory_module._MODEL_METADATA_FIELDS


@pytest.mark.parametrize(
    ("contract", "match"),
    [
        pytest.param({"thinking": "optional", "effort": {"values": ["low"], "default": "high"}}, "default", id="default-not-in-values"),
        pytest.param({"thinking": "optional", "effort": {"values": ["low", "low"]}}, "unique", id="duplicate-values"),
        pytest.param({"thinking": "optional", "effort": {"values": []}}, "values", id="empty-values"),
        pytest.param({"thinking": "optional", "effort": {"values": ["low"], "aliases": {"low": "low"}}}, "alias", id="alias-key-is-a-value"),
        pytest.param({"thinking": "optional", "effort": {"values": ["low"], "aliases": {"medium": "high"}}}, "alias", id="alias-target-not-a-value"),
        pytest.param({"thinking": "optional", "on_disable_request": "reject"}, "on_disable_request", id="reject-without-required"),
        pytest.param({"thinking": "bogus"}, "thinking", id="unknown-thinking-mode"),
        pytest.param({"thinking": "optional", "unknown": 1}, "unknown", id="unknown-key"),
    ],
)
def test_contract_rejects_impossible_shapes(contract, match):
    with pytest.raises(ValidationError, match=match):
        _model(reasoning=contract)


def test_required_thinking_rejects_when_thinking_disabled_template():
    with pytest.raises(ValidationError, match="when_thinking_disabled"):
        _model(reasoning={"thinking": "required"}, when_thinking_disabled={"extra_body": {"thinking": {"type": "disabled"}}})


@pytest.mark.parametrize("template", ["when_thinking_enabled", "thinking"])
def test_unsupported_thinking_rejects_enable_templates(template):
    with pytest.raises(ValidationError, match=template):
        _model(reasoning={"thinking": "unsupported"}, **{template: {"type": "enabled"}})


@pytest.mark.parametrize(
    ("legacy", "contract"),
    [
        pytest.param({"supports_thinking": False}, {"thinking": "required"}, id="supports_thinking-false-vs-required"),
        pytest.param({"supports_thinking": True}, {"thinking": "unsupported"}, id="supports_thinking-true-vs-unsupported"),
        pytest.param({"supports_reasoning_effort": True}, {"thinking": "optional"}, id="supports_reasoning_effort-true-vs-no-effort"),
        pytest.param({"supports_reasoning_effort": False}, {"thinking": "optional", "effort": {"values": ["low"]}}, id="supports_reasoning_effort-false-vs-effort"),
    ],
)
def test_explicit_legacy_boolean_conflicting_with_contract_is_rejected(legacy, contract):
    with pytest.raises(ValidationError, match="reasoning"):
        _model(reasoning=contract, **legacy)


def test_matching_legacy_booleans_beside_contract_are_accepted():
    model = _model(reasoning=_glm_contract(), supports_thinking=True, supports_reasoning_effort=True)
    assert model.supports_thinking is True


def test_profile_reasoning_effort_must_be_accepted_by_the_contract():
    with pytest.raises(ValidationError, match="reasoning_effort"):
        _model(reasoning=_glm_contract(), reasoning_effort="medium")


def test_profile_reasoning_effort_rejected_when_contract_declares_no_effort():
    with pytest.raises(ValidationError, match="reasoning_effort"):
        _model(reasoning={"thinking": "optional"}, reasoning_effort="low")


def test_profile_reasoning_effort_in_values_is_accepted():
    model = _model(reasoning=_glm_contract(), reasoning_effort="high")
    assert model.model_extra["reasoning_effort"] == "high"


@pytest.mark.parametrize("template", ["when_thinking_enabled", "when_thinking_disabled"])
def test_template_reasoning_effort_must_be_accepted_by_the_contract(template):
    """A template value the caller never chose still reaches the provider when no
    request and no default override it, so it is validated like the profile value."""
    with pytest.raises(ValidationError, match=template):
        _model(reasoning={"thinking": "optional", "effort": {"values": ["low", "high"]}}, **{template: {"reasoning_effort": "minimal"}})


@pytest.mark.parametrize("template", ["when_thinking_enabled", "when_thinking_disabled"])
def test_template_reasoning_effort_in_values_is_accepted(template):
    model = _model(reasoning={"thinking": "optional", "effort": {"values": ["low", "high"]}}, **{template: {"reasoning_effort": "low"}})
    assert getattr(model, template) == {"reasoning_effort": "low"}


def test_template_reasoning_effort_rejected_when_contract_declares_no_effort():
    with pytest.raises(ValidationError, match="when_thinking_disabled"):
        _model(reasoning={"thinking": "optional"}, when_thinking_disabled={"reasoning_effort": "low"})


def test_template_effort_is_validated_at_the_declared_path():
    contract = {"thinking": "optional", "dialect": "openai_extra_body", "effort": {"values": ["low", "high"], "path": "extra_body.thinking.effort"}}
    with pytest.raises(ValidationError, match="when_thinking_enabled"):
        _model(reasoning=contract, when_thinking_enabled={"extra_body": {"thinking": {"type": "enabled", "effort": "max"}}})
    model = _model(reasoning=contract, when_thinking_enabled={"extra_body": {"thinking": {"type": "enabled", "effort": "high"}}})
    assert model.when_thinking_enabled["extra_body"]["thinking"]["effort"] == "high"


def test_thinking_shortcut_effort_is_validated_at_the_declared_path():
    contract = {"thinking": "optional", "dialect": "anthropic", "effort": {"values": ["low", "high"], "path": "thinking.effort"}}
    with pytest.raises(ValidationError, match="thinking"):
        _model(reasoning=contract, thinking={"budget_tokens": 1024, "effort": "max"})


@pytest.mark.parametrize("source", ["profile-level", "when_thinking_enabled", "when_thinking_disabled"])
@pytest.mark.parametrize("stale_effort", ["minimal", "low"])
def test_custom_effort_path_rejects_stale_generic_reasoning_effort(source, stale_effort):
    contract = {"thinking": "optional", "effort": {"values": ["low", "high"], "path": "extra_body.thinking.effort"}}
    extras = {"reasoning_effort": stale_effort} if source == "profile-level" else {source: {"reasoning_effort": stale_effort}}

    with pytest.raises(ValidationError, match=f"{source} reasoning_effort"):
        _model(reasoning=contract, **extras)


def test_custom_effort_path_rejects_stale_generic_key_in_thinking_shortcut():
    contract = {"thinking": "optional", "effort": {"values": ["low", "high"], "path": "thinking.effort"}}

    with pytest.raises(ValidationError, match="thinking reasoning_effort"):
        _model(reasoning=contract, thinking={"reasoning_effort": "minimal"})


def test_thinking_shortcut_generic_effort_rejected_without_effort_control():
    with pytest.raises(ValidationError, match="declares no effort control"):
        _model(reasoning={"thinking": "optional"}, thinking={"reasoning_effort": "minimal"})


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("extra_body", id="shadows-extra_body"),
        pytest.param("thinking", id="shadows-thinking"),
        pytest.param("model_kwargs", id="shadows-model_kwargs"),
        pytest.param("1bad", id="leading-digit"),
        pytest.param("extra_body..effort", id="empty-segment"),
        pytest.param("extra_body.thinking-effort", id="dash"),
        pytest.param(".reasoning_effort", id="leading-dot"),
    ],
)
def test_effort_path_rejects_unsafe_values(path):
    with pytest.raises(ValidationError, match="path"):
        _model(reasoning={"thinking": "optional", "effort": {"values": ["low"], "path": path}})


@pytest.mark.parametrize("path", ["reasoning_effort", "extra_body.thinking.effort", "model_kwargs.reasoning_effort", "_private"])
def test_effort_path_accepts_dotted_identifiers(path):
    model = _model(reasoning={"thinking": "optional", "effort": {"values": ["low"], "path": path}})
    assert model.reasoning.effort.path == path


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_legacy_booleans_normalize_to_optional_thinking_and_generic_effort():
    contract = resolve_reasoning_contract(_model(supports_thinking=True, supports_reasoning_effort=True))

    assert contract.source == "legacy"
    assert contract.thinking == "optional"
    assert contract.effort is not None
    assert contract.effort.values == GENERIC_EFFORT_VALUES
    assert contract.effort.default is None
    assert contract.effort.strict is False
    assert contract.dialect == "auto"
    assert contract.history is None


def test_legacy_defaults_normalize_to_unsupported():
    contract = resolve_reasoning_contract(_model())

    assert contract.thinking == "unsupported"
    assert contract.effort is None
    assert contract.supports_thinking is False
    assert contract.supports_reasoning_effort is False


def test_declared_contract_normalizes_strictly():
    contract = resolve_reasoning_contract(_model(reasoning=_glm_contract()))

    assert contract.source == "contract"
    assert contract.thinking == "required"
    assert contract.thinking_required is True
    assert contract.effort is not None
    assert contract.effort.values == ("low", "high", "max")
    assert contract.effort.default == "max"
    assert dict(contract.effort.aliases) == {"minimal": "low", "medium": "high"}
    assert contract.effort.strict is True
    assert contract.dialect == "openai_extra_body"
    assert contract.history == "clear"


def test_normalization_accepts_duck_typed_profiles():
    """Descriptor builders and mocks pass plain objects without a ``reasoning`` attribute."""
    from types import SimpleNamespace

    contract = resolve_reasoning_contract(SimpleNamespace(supports_thinking=True, supports_reasoning_effort=False))

    assert contract.source == "legacy"
    assert contract.thinking == "optional"
    assert contract.effort is None


def test_normalization_ignores_non_contract_reasoning_attribute():
    from types import SimpleNamespace

    contract = resolve_reasoning_contract(SimpleNamespace(supports_thinking=False, supports_reasoning_effort=False, reasoning=object()))

    assert contract.source == "legacy"


# ---------------------------------------------------------------------------
# Request resolution — thinking
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("requested", [True, False])
def test_unsupported_thinking_always_resolves_off(requested):
    contract = resolve_reasoning_contract(_model())
    resolved = resolve_reasoning_request(contract, thinking_enabled=requested, reasoning_effort=None)

    assert resolved.thinking_enabled is False
    assert ("thinking_unsupported" in resolved.adjustments) is requested


@pytest.mark.parametrize("requested", [True, False])
def test_optional_thinking_honors_the_request(requested):
    contract = resolve_reasoning_contract(_model(reasoning={"thinking": "optional"}))
    resolved = resolve_reasoning_request(contract, thinking_enabled=requested, reasoning_effort=None)

    assert resolved.thinking_enabled is requested
    assert resolved.adjustments == ()


def test_required_thinking_forces_on_when_a_background_caller_requests_off():
    contract = resolve_reasoning_contract(_model(reasoning={"thinking": "required"}))
    resolved = resolve_reasoning_request(contract, thinking_enabled=False, reasoning_effort=None)

    assert resolved.thinking_enabled is True
    assert "thinking_forced_on" in resolved.adjustments


def test_required_thinking_with_reject_policy_raises_before_the_provider():
    contract = resolve_reasoning_contract(_model(reasoning={"thinking": "required", "on_disable_request": "reject"}))

    with pytest.raises(ReasoningPolicyError, match="requires thinking"):
        resolve_reasoning_request(contract, thinking_enabled=False, reasoning_effort=None)

    assert resolve_reasoning_request(contract, thinking_enabled=True, reasoning_effort=None).thinking_enabled is True


# ---------------------------------------------------------------------------
# Request resolution — effort
# ---------------------------------------------------------------------------


def test_effort_dropped_when_the_model_declares_no_effort_control():
    contract = resolve_reasoning_contract(_model(reasoning={"thinking": "optional"}))
    resolved = resolve_reasoning_request(contract, thinking_enabled=True, reasoning_effort="high")

    assert resolved.reasoning_effort is None
    assert "effort_unsupported" in resolved.adjustments


def test_legacy_effort_is_forwarded_verbatim():
    contract = resolve_reasoning_contract(_model(supports_reasoning_effort=True))

    assert resolve_reasoning_request(contract, thinking_enabled=True, reasoning_effort="xhigh").reasoning_effort == "xhigh"
    assert resolve_reasoning_request(contract, thinking_enabled=True, reasoning_effort=None).reasoning_effort is None


@pytest.mark.parametrize(
    ("requested", "expected", "adjustment"),
    [
        pytest.param(None, "max", None, id="unset-uses-default"),
        pytest.param("high", "high", None, id="declared-value-passes"),
        pytest.param("minimal", "low", "effort_aliased", id="generic-minimal-maps-to-low"),
        pytest.param("medium", "high", "effort_aliased", id="generic-medium-maps-to-high"),
        pytest.param("xhigh", "max", "effort_unsupported_value", id="unknown-falls-back-to-default"),
    ],
)
def test_restricted_effort_resolution(requested, expected, adjustment):
    contract = resolve_reasoning_contract(_model(reasoning=_glm_contract()))
    resolved = resolve_reasoning_request(contract, thinking_enabled=True, reasoning_effort=requested)

    assert resolved.reasoning_effort == expected
    if adjustment is None:
        assert resolved.adjustments == ()
    else:
        assert adjustment in resolved.adjustments


def test_unknown_effort_without_default_is_dropped():
    contract = resolve_reasoning_contract(_model(reasoning={"thinking": "optional", "effort": {"values": ["low", "high"]}}))
    resolved = resolve_reasoning_request(contract, thinking_enabled=True, reasoning_effort="minimal")

    assert resolved.reasoning_effort is None
    assert "effort_unsupported_value" in resolved.adjustments


def test_effort_resolution_is_idempotent():
    """Callers may resolve before the factory resolves again; a provider value must survive."""
    contract = resolve_reasoning_contract(_model(reasoning=_glm_contract()))
    first = resolve_reasoning_request(contract, thinking_enabled=False, reasoning_effort="minimal")
    second = resolve_reasoning_request(contract, thinking_enabled=first.thinking_enabled, reasoning_effort=first.reasoning_effort)

    assert second.thinking_enabled is True
    assert second.reasoning_effort == "low"
    assert second.adjustments == ()


# ---------------------------------------------------------------------------
# API projection
# ---------------------------------------------------------------------------


def test_payload_for_legacy_model_matches_previous_ui_assumptions():
    payload = reasoning_capabilities_payload(resolve_reasoning_contract(_model(supports_thinking=True, supports_reasoning_effort=True)))

    assert payload == {
        "thinking": "optional",
        "effort": {"values": list(GENERIC_EFFORT_VALUES), "default": None, "aliases": {}},
        "history": None,
        "source": "legacy",
    }


def test_payload_for_contract_model_exposes_provider_vocabulary():
    payload = reasoning_capabilities_payload(resolve_reasoning_contract(_model(reasoning=_glm_contract())))

    assert payload == {
        "thinking": "required",
        "effort": {"values": ["low", "high", "max"], "default": "max", "aliases": {"minimal": "low", "medium": "high"}},
        "history": "clear",
        "source": "contract",
    }


def test_payload_without_effort_reports_null():
    payload = reasoning_capabilities_payload(resolve_reasoning_contract(_model()))

    assert payload["thinking"] == "unsupported"
    assert payload["effort"] is None


def test_contract_dataclass_is_immutable():
    contract = resolve_reasoning_contract(_model())
    assert isinstance(contract, ReasoningContract)
    with pytest.raises((AttributeError, TypeError)):
        contract.thinking = "optional"  # type: ignore[misc]

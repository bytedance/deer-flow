"""Delegation preserves reasoning intent without leaking provider vocabularies."""

from types import SimpleNamespace

import pytest

from deerflow.config.model_config import ModelConfig
from deerflow.models.reasoning import ReasoningPolicyError, resolve_reasoning_contract, resolve_reasoning_request
from deerflow.subagents.config import SubagentConfig
from deerflow.subagents.reasoning import resolve_subagent_reasoning


def profile(name="child", *, thinking="optional", values=None, aliases=None, default=None, **kwargs):
    reasoning = {"thinking": thinking, **kwargs}
    if values:
        reasoning["effort"] = {"values": values, "aliases": aliases or {}, "default": default}
    return ModelConfig(name=name, model=name, use="langchain_openai:ChatOpenAI", reasoning=reasoning)


def resolve(config=None, child=None, **kwargs):
    return resolve_subagent_reasoning(config or SubagentConfig(name="worker", description="Work"), child or profile(), **kwargs)


def test_unset_worker_inherits_effective_parent_settings():
    request = resolve(child=profile(values=["low", "high"]), parent_thinking_enabled=True, parent_reasoning_effort="high")
    assert (request.thinking_enabled, request.reasoning_effort) == (True, "high")


def test_explicit_false_and_effort_win_independently():
    config = SubagentConfig(name="worker", description="Work", thinking_enabled=False, reasoning_effort="low")
    request = resolve(config, profile(values=["low", "high"]), parent_thinking_enabled=True, parent_reasoning_effort="high")
    assert (request.thinking_enabled, request.reasoning_effort) == (False, "low")


def test_missing_parent_uses_model_default_without_requesting_off():
    request = resolve()
    assert request.thinking_enabled is None
    resolved = resolve_reasoning_request(resolve_reasoning_contract(profile()), thinking_enabled=request.thinking_enabled, reasoning_effort=None)
    assert resolved.thinking_enabled is None


def test_model_source_bypasses_parent_but_keeps_explicit_overrides():
    config = SubagentConfig(name="worker", description="Work", reasoning_source="model", reasoning_effort="low")
    request = resolve(config, parent_thinking_enabled=True, parent_reasoning_effort="high")
    assert (request.thinking_enabled, request.reasoning_effort) == (None, "low")


def test_cross_model_effort_translates_through_declared_generic_alias():
    parent = profile("parent", values=["lite", "deep"], aliases={"high": "deep"})
    child = profile(values=["small", "large"], aliases={"high": "large"}, default="small")
    request = resolve(child=child, parent_model_config=parent, parent_thinking_enabled=True, parent_reasoning_effort="deep")
    assert request.reasoning_effort == "large"


@pytest.mark.parametrize("parent", [None, SimpleNamespace(name="parent", supports_reasoning_effort=True)])
def test_unmapped_provider_effort_does_not_leak_to_legacy_child(parent):
    child = SimpleNamespace(name="child", supports_thinking=True, supports_reasoning_effort=True)
    request = resolve(child=child, parent_model_config=parent, parent_reasoning_effort="deep")
    assert request.reasoning_effort is None


def test_same_legacy_profile_keeps_effective_provider_effort():
    child = ModelConfig(name="shared", model="shared", use="langchain_openai:ChatOpenAI", supports_thinking=True, supports_reasoning_effort=True)
    request = resolve(child=child, parent_model_config=child, parent_thinking_enabled=True, parent_reasoning_effort="xhigh")
    assert request.reasoning_effort == "xhigh"


def test_legacy_parent_does_not_forward_an_unsupported_effort_request():
    parent = ModelConfig(name="parent", model="parent", use="langchain_openai:ChatOpenAI", supports_thinking=True)
    request = resolve(child=profile(values=["low", "high"], default="low"), parent_model_config=parent, parent_reasoning_effort="high")
    assert request.reasoning_effort is None


@pytest.mark.parametrize("thinking, expected", [("unsupported", False), ("required", True)])
def test_inherited_preference_adapts_to_child_capability(thinking, expected):
    child = profile(thinking=thinking, **({"on_disable_request": "reject"} if thinking == "required" else {}))
    request = resolve(child=child, parent_thinking_enabled=thinking != "required")
    effective = resolve_reasoning_request(resolve_reasoning_contract(child), thinking_enabled=request.thinking_enabled, reasoning_effort=request.reasoning_effort)
    assert effective.thinking_enabled is expected


def test_explicit_off_still_obeys_required_model_rejection():
    child = profile(thinking="required", on_disable_request="reject")
    request = resolve(SubagentConfig(name="worker", description="Work", thinking_enabled=False), child)
    with pytest.raises(ReasoningPolicyError):
        resolve_reasoning_request(resolve_reasoning_contract(child), thinking_enabled=request.thinking_enabled, reasoning_effort=None)

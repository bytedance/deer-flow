"""Scope selection for operator-configured middleware, through real builders."""

from types import SimpleNamespace

import pytest
from langchain.agents.middleware import AgentMiddleware
from pydantic import ValidationError

from deerflow.agents.middlewares.configured_extensions import load_configured_extension_middlewares
from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import ConfiguredMiddlewareSpec, ExtensionsConfig


class ScopedMiddleware(AgentMiddleware):
    def __init__(self, label="legacy"):
        self.label = label


class BrokenMiddleware(AgentMiddleware):
    def __init__(self):
        raise RuntimeError("constructor executed")


def _entry(label, scope):
    return {"class": f"{__name__}:ScopedMiddleware", "kwargs": {"label": label}, "apply_to": scope}


def _config(entries):
    return SimpleNamespace(extensions=ExtensionsConfig.model_validate({"middlewares": entries}))


@pytest.mark.parametrize("scope", ["both", "lead", "subagent"])
def test_scope_survives_config_serialization(scope):
    config = ExtensionsConfig.model_validate({"middlewares": [_entry("configured", scope)]})
    restored = ExtensionsConfig.model_validate_json(config.model_dump_json(by_alias=True))
    assert restored.middlewares[0].apply_to == scope
    assert restored.middlewares[0].kwargs == {"label": "configured"}


@pytest.mark.parametrize("invalid", [None, "", "worker", "LEAD", ["lead"], {}, True, 1])
def test_invalid_scope_is_rejected_even_for_an_unavailable_class(invalid):
    with pytest.raises(ValidationError, match="apply_to"):
        ExtensionsConfig.model_validate({"middlewares": [{"class": "unavailable_module:Middleware", "apply_to": invalid}]})


@pytest.mark.parametrize("scope", ["lead", "subagent"])
def test_legacy_entries_and_order_are_preserved(scope):
    config = _config(
        [
            f"{__name__}:ScopedMiddleware",
            {"class": f"{__name__}:ScopedMiddleware", "kwargs": {"label": "object-default"}},
            _entry("lead", "lead"),
            _entry("both", "both"),
            _entry("subagent", "subagent"),
        ]
    )
    loaded = load_configured_extension_middlewares(config, scope=scope)
    expected = ["legacy", "object-default", "lead", "both"] if scope == "lead" else ["legacy", "object-default", "both", "subagent"]
    assert [mw.label for mw in loaded] == expected
    again = load_configured_extension_middlewares(config, scope=scope)
    assert all(first is not second for first, second in zip(loaded, again, strict=True))
    assert config.extensions.middlewares[2].kwargs == {"label": "lead"}


@pytest.mark.parametrize("scope,excluded", [("lead", "subagent"), ("subagent", "lead")])
@pytest.mark.parametrize("class_path", ["unavailable_module:Middleware", f"{__name__}:BrokenMiddleware"])
def test_excluded_entries_are_not_imported_or_constructed(scope, excluded, class_path):
    config = _config([{"class": class_path, "apply_to": excluded}, _entry("selected", scope)])
    loaded = load_configured_extension_middlewares(config, scope=scope)
    assert [mw.label for mw in loaded] == ["selected"]


@pytest.mark.parametrize("scope", ["lead", "subagent"])
def test_selected_constructor_failure_still_propagates(scope):
    config = _config([{"class": f"{__name__}:BrokenMiddleware", "apply_to": scope}])
    with pytest.raises(RuntimeError, match="constructor executed"):
        load_configured_extension_middlewares(config, scope=scope)


@pytest.mark.parametrize("scope", ["lead", "subagent"])
@pytest.mark.parametrize("class_path", ["unavailable_module:Middleware", "types:SimpleNamespace"])
def test_selected_import_and_subclass_failures_still_propagate(scope, class_path):
    config = _config([{"class": class_path, "apply_to": scope}])
    with pytest.raises((ImportError, ValueError)):
        load_configured_extension_middlewares(config, scope=scope)


def test_raw_dict_scope_is_validated_before_skipping():
    raw = {"class": "unavailable_module:Middleware", "apply_to": "subagent", "unexpected": True}
    config = SimpleNamespace(extensions=SimpleNamespace(middlewares=[raw]))
    with pytest.raises(ValidationError, match="unexpected"):
        load_configured_extension_middlewares(config, scope="lead")


def test_raw_dict_and_model_entries_are_filtered():
    config = SimpleNamespace(extensions=SimpleNamespace(middlewares=[_entry("lead", "lead"), ConfiguredMiddlewareSpec.model_validate(_entry("subagent", "subagent"))]))
    assert [mw.label for mw in load_configured_extension_middlewares(config, scope="lead")] == ["lead"]


@pytest.mark.parametrize("scope", ["both", "invalid", None])
def test_loader_requires_a_concrete_host_scope(scope):
    with pytest.raises(ValueError, match="scope"):
        load_configured_extension_middlewares(_config([]), scope=scope)


def test_loader_requires_explicit_scope():
    config = _config([_entry("lead", "lead"), _entry("subagent", "subagent")])
    with pytest.raises(TypeError, match="required keyword-only argument: 'scope'"):
        load_configured_extension_middlewares(config)


def test_real_lead_and_subagent_builders_select_their_own_scope(tmp_path, monkeypatch):
    from deerflow.agents.lead_agent.agent import build_middlewares
    from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
    from deerflow.extensions import get_agent_build_extensions

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "runtime"))
    app_config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [],
            "memory": {"enabled": False},
            "summarization": {"enabled": False},
            "extensions": {"middlewares": [_entry("lead", "lead"), _entry("shared", "both"), _entry("subagent", "subagent")]},
        }
    )
    extensions = get_agent_build_extensions()
    lead = build_middlewares({}, None, app_config=app_config, memory_enabled=False, available_skills=set(), extensions=extensions)
    subagent = build_subagent_runtime_middlewares(app_config=app_config, available_skills=set(), extensions=extensions)
    assert [mw.label for mw in lead if isinstance(mw, ScopedMiddleware)] == ["lead", "shared"]
    assert [mw.label for mw in subagent if isinstance(mw, ScopedMiddleware)] == ["shared", "subagent"]
    assert next(mw for mw in lead if isinstance(mw, ScopedMiddleware) and mw.label == "shared") is not next(mw for mw in subagent if isinstance(mw, ScopedMiddleware) and mw.label == "shared")
    for chain in (lead, subagent):
        configured_end = max(i for i, mw in enumerate(chain) if isinstance(mw, ScopedMiddleware))
        length_guard = next(i for i, mw in enumerate(chain) if type(mw).__name__ == "ModelLengthFinishReasonMiddleware")
        assert configured_end < length_guard

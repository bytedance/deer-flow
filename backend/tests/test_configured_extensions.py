"""Config-declared extension middleware loading, including constructor kwargs."""

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from langchain.agents.middleware import AgentMiddleware
from pydantic import ValidationError

from deerflow.agents.middlewares.configured_extensions import load_configured_extension_middlewares
from deerflow.config.extensions_config import (
    ConfiguredMiddlewareSpec,
    ExtensionsConfig,
    atomic_write_extensions_config,
    read_raw_extensions_config,
    set_raw_skill_enabled,
    validate_raw_extensions_config,
)


class RecordingMiddleware(AgentMiddleware):
    """Test double that records constructor kwargs."""

    def __init__(self, max_tool_calls: int = 10):
        super().__init__()
        self.max_tool_calls = max_tool_calls


class ZeroArgMiddleware(AgentMiddleware):
    def __init__(self):
        super().__init__()


def _config(*entries) -> SimpleNamespace:
    return SimpleNamespace(extensions=SimpleNamespace(middlewares=list(entries)))


def test_string_entry_still_zero_arg():
    loaded = load_configured_extension_middlewares(_config(f"{__name__}:ZeroArgMiddleware"))

    assert len(loaded) == 1
    assert isinstance(loaded[0], ZeroArgMiddleware)


def test_dict_entry_passes_constructor_kwargs():
    entry = ConfiguredMiddlewareSpec.model_validate({"class": f"{__name__}:RecordingMiddleware", "kwargs": {"max_tool_calls": 3}})

    loaded = load_configured_extension_middlewares(_config(entry))

    assert len(loaded) == 1
    assert isinstance(loaded[0], RecordingMiddleware)
    assert loaded[0].max_tool_calls == 3


def test_raw_dict_entry_passes_constructor_kwargs():
    loaded = load_configured_extension_middlewares(_config({"class": f"{__name__}:RecordingMiddleware", "kwargs": {"max_tool_calls": 2}}))

    assert len(loaded) == 1
    assert isinstance(loaded[0], RecordingMiddleware)
    assert loaded[0].max_tool_calls == 2


def test_malformed_raw_dict_fails_at_load():
    with pytest.raises(ValidationError):
        load_configured_extension_middlewares(_config({"class": f"{__name__}:RecordingMiddleware", "apply_to": "lead"}))


def test_empty_kwargs_matches_zero_arg_constructor():
    entry = ConfiguredMiddlewareSpec.model_validate({"class": f"{__name__}:RecordingMiddleware"})

    loaded = load_configured_extension_middlewares(_config(entry))

    assert loaded[0].max_tool_calls == 10


def test_unknown_constructor_kwarg_fails_loudly():
    entry = ConfiguredMiddlewareSpec.model_validate({"class": f"{__name__}:ZeroArgMiddleware", "kwargs": {"not_a_param": 1}})

    with pytest.raises(TypeError):
        load_configured_extension_middlewares(_config(entry))


def test_extensions_config_keeps_string_entries():
    config = ExtensionsConfig.model_validate({"middlewares": ["pkg:Middleware"]})

    assert config.middlewares == ["pkg:Middleware"]


def test_extensions_config_parses_class_and_kwargs():
    config = ExtensionsConfig.model_validate(
        {
            "middlewares": [
                "pkg:Plain",
                {"class": "pkg:WithArgs", "kwargs": {"max_tool_calls": 5}},
            ]
        }
    )

    assert config.middlewares[0] == "pkg:Plain"
    spec = config.middlewares[1]
    assert isinstance(spec, ConfiguredMiddlewareSpec)
    assert spec.class_path == "pkg:WithArgs"
    assert spec.kwargs == {"max_tool_calls": 5}


def test_extensions_config_rejects_unknown_entry_fields():
    with pytest.raises(ValidationError):
        ExtensionsConfig.model_validate({"middlewares": [{"class": "pkg:Middleware", "apply_to": "lead"}]})


def test_extensions_config_rejects_blank_class_path():
    with pytest.raises(ValidationError):
        ExtensionsConfig.model_validate({"middlewares": [{"class": "  "}]})


def test_extensions_config_rejects_blank_string_entry():
    with pytest.raises(ValidationError):
        ExtensionsConfig.model_validate({"middlewares": ["  "]})


def test_extensions_config_strips_string_entries():
    config = ExtensionsConfig.model_validate({"middlewares": [" pkg:Plain "]})

    assert config.middlewares == ["pkg:Plain"]


def test_kwargs_yaml_date_normalizes_to_iso_string():
    spec = ConfiguredMiddlewareSpec.model_validate({"class": "pkg:Mw", "kwargs": {"cutoff": date(2026, 1, 1)}})

    assert spec.kwargs == {"cutoff": "2026-01-01"}
    assert json.loads(json.dumps(spec.kwargs)) == {"cutoff": "2026-01-01"}


def test_kwargs_yaml_datetime_normalizes_to_iso_string():
    spec = ConfiguredMiddlewareSpec.model_validate({"class": "pkg:Mw", "kwargs": {"cutoff": datetime(2026, 1, 1, 12, 0, 0)}})

    assert spec.kwargs == {"cutoff": "2026-01-01T12:00:00"}


def test_kwargs_reject_non_json_values():
    with pytest.raises(ValidationError, match="JSON types"):
        ConfiguredMiddlewareSpec.model_validate({"class": "pkg:Mw", "kwargs": {"hook": object()}})


def test_kwargs_reject_nan():
    with pytest.raises(ValidationError, match="JSON types"):
        ConfiguredMiddlewareSpec.model_validate({"class": "pkg:Mw", "kwargs": {"n": float("nan")}})


def test_raw_file_round_trips_kwargs_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("DEERFLOW_TEST_MIDDLEWARE_TOKEN", "test-secret")
    config_path = tmp_path / "extensions_config.json"
    raw = {
        "middlewares": [
            "pkg:Plain",
            {"class": "pkg:WithArgs", "kwargs": {"max_tool_calls": 5, "token": "$DEERFLOW_TEST_MIDDLEWARE_TOKEN"}},
        ]
    }
    config_path.write_text(json.dumps(raw), encoding="utf-8")

    candidate = read_raw_extensions_config(config_path)
    set_raw_skill_enabled(candidate, "demo", False)
    validate_raw_extensions_config(candidate)
    atomic_write_extensions_config(config_path, candidate)
    dumped = read_raw_extensions_config(config_path)
    restored = ExtensionsConfig.from_file(config_path)

    assert dumped["middlewares"] == raw["middlewares"]
    assert dumped["skills"] == {"demo": {"enabled": False}}
    assert dumped["middlewares"][0] == "pkg:Plain"
    assert dumped["middlewares"][1]["class"] == "pkg:WithArgs"
    assert dumped["middlewares"][1]["kwargs"] == {"max_tool_calls": 5, "token": "$DEERFLOW_TEST_MIDDLEWARE_TOKEN"}
    assert restored.middlewares[1].class_path == "pkg:WithArgs"
    assert restored.middlewares[1].kwargs == {"max_tool_calls": 5, "token": "test-secret"}

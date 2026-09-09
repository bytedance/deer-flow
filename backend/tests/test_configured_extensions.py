"""Config-declared extension middleware loading, including constructor kwargs."""

from types import SimpleNamespace

import pytest
from langchain.agents.middleware import AgentMiddleware
from pydantic import ValidationError

from deerflow.agents.middlewares.configured_extensions import load_configured_extension_middlewares
from deerflow.config.extensions_config import ConfiguredMiddlewareSpec, ExtensionsConfig


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


def test_to_file_dict_round_trips_kwargs_entries():
    config = ExtensionsConfig.model_validate(
        {
            "middlewares": [
                "pkg:Plain",
                {"class": "pkg:WithArgs", "kwargs": {"max_tool_calls": 5}},
            ]
        }
    )

    dumped = config.to_file_dict()
    restored = ExtensionsConfig.model_validate(dumped)

    assert dumped["middlewares"][0] == "pkg:Plain"
    assert dumped["middlewares"][1]["class"] == "pkg:WithArgs"
    assert dumped["middlewares"][1]["kwargs"] == {"max_tool_calls": 5}
    assert restored.middlewares[1].class_path == "pkg:WithArgs"
    assert restored.middlewares[1].kwargs == {"max_tool_calls": 5}

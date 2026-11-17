import pytest
from pydantic import ValidationError

from deerflow.config.app_config import AppConfig, LlmCallConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig


def _make_model(**overrides) -> ModelConfig:
    values = {
        "name": "openai-responses",
        "display_name": "OpenAI Responses",
        "description": None,
        "use": "langchain_openai:ChatOpenAI",
        "model": "gpt-5",
    }
    values.update(overrides)
    return ModelConfig(**values)


def test_responses_api_fields_are_declared_in_model_schema():
    assert "use_responses_api" in ModelConfig.model_fields
    assert "output_version" in ModelConfig.model_fields


def test_responses_api_fields_round_trip_in_model_dump():
    config = _make_model(
        api_key="$OPENAI_API_KEY",
        use_responses_api=True,
        output_version="responses/v1",
    )

    dumped = config.model_dump(exclude_none=True)

    assert dumped["use_responses_api"] is True
    assert dumped["output_version"] == "responses/v1"


def test_context_window_round_trips_when_positive():
    assert _make_model(context_window=128_000).context_window == 128_000


@pytest.mark.parametrize("context_window", [0, -1])
def test_context_window_rejects_non_positive_capacity(context_window):
    with pytest.raises(ValidationError, match="context_window"):
        _make_model(context_window=context_window)


def test_fallback_models_default_to_empty_and_round_trip():
    assert _make_model().fallback_models == []
    assert _make_model(fallback_models=["backup"]).model_dump()["fallback_models"] == ["backup"]


def test_fallback_model_names_must_be_unique():
    with pytest.raises(ValidationError, match="fallback_models must not contain duplicates"):
        _make_model(fallback_models=["backup", "backup"])


def test_app_config_rejects_unknown_fallback_model():
    primary = _make_model(name="primary", fallback_models=["missing"])
    with pytest.raises(ValidationError, match="unknown fallback model"):
        AppConfig(sandbox=SandboxConfig(use="test"), models=[primary])


def test_app_config_rejects_fallback_chain_over_attempt_limit():
    primary = _make_model(name="primary", fallback_models=["backup"])
    backup = _make_model(name="backup")
    with pytest.raises(ValidationError, match="retry_max_attempts"):
        AppConfig(
            sandbox=SandboxConfig(use="test"),
            llm_call=LlmCallConfig(retry_max_attempts=1),
            models=[primary, backup],
        )

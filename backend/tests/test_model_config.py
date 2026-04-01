from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig


def _make_model(**overrides) -> ModelConfig:
    return ModelConfig(
        name="openai-responses",
        display_name="OpenAI Responses",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="gpt-5",
        **overrides,
    )


def _make_app_config(models: list[ModelConfig]) -> AppConfig:
    return AppConfig(
        models=models,
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )


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


def test_get_model_config_matches_name_model_and_display_name():
    config = _make_app_config(
        [
            ModelConfig(
                name="glm-router",
                display_name="GLM-5-Turbo",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="glm-5-turbo",
            )
        ]
    )

    assert config.get_model_config("glm-router") is not None
    assert config.get_model_config("glm-5-turbo") is not None
    assert config.get_model_config("GLM-5-Turbo") is not None

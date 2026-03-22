from deerflow.config.model_config import ModelConfig


def _make_model(**overrides) -> ModelConfig:
    return ModelConfig(
        name="openai-responses",
        display_name="OpenAI Responses",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="gpt-5",
        **overrides,
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

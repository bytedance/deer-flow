from __future__ import annotations

from deerflow.config.model_config import ModelConfig
from deerflow.config.model_services_config import (
    ModelServiceDefaults,
    ModelServiceModelConfig,
    ModelServiceProviderConfig,
    ModelServicesConfig,
    model_services_to_runtime_models,
    resolve_modality_model_name,
)


def test_model_services_round_trip(tmp_path):
    path = tmp_path / "model_services.json"
    config = ModelServicesConfig(
        providers=[
            ModelServiceProviderConfig(
                id="openai",
                name="OpenAI",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                modalities=["text", "image"],
                models=[
                    ModelServiceModelConfig(
                        id="gpt-5",
                        name="gpt-5",
                        model="gpt-5",
                        modalities=["text"],
                    )
                ],
            )
        ],
        defaults=ModelServiceDefaults(text_model_name="gpt-5"),
    )

    config.to_file(path)
    loaded = ModelServicesConfig.from_file(str(path))

    assert loaded.defaults.text_model_name == "gpt-5"
    assert loaded.providers[0].api_key == "sk-test"
    assert loaded.providers[0].models[0].name == "gpt-5"


def test_model_services_missing_env_path_returns_empty_config(tmp_path, monkeypatch):
    missing_path = tmp_path / "missing-model-services.json"
    monkeypatch.setenv("DEER_FLOW_MODEL_SERVICES_CONFIG_PATH", str(missing_path))

    loaded = ModelServicesConfig.from_file()

    assert loaded.providers == []
    assert loaded.defaults.text_model_name is None


def test_model_services_to_runtime_models_merges_static_and_provider_models():
    static_models = [
        ModelConfig(
            name="static-model",
            display_name="Static",
            use="langchain_openai:ChatOpenAI",
            model="gpt-4o-mini",
        )
    ]
    model_services = ModelServicesConfig(
        providers=[
            ModelServiceProviderConfig(
                id="relay",
                name="Relay",
                provider_type="openai-compatible",
                enabled=True,
                base_url="https://relay.example/v1",
                api_key="relay-key",
                modalities=["text", "image"],
                models=[
                    ModelServiceModelConfig(
                        id="relay-gpt-5",
                        name="relay-gpt-5",
                        display_name="Relay GPT-5",
                        model="gpt-5",
                        enabled=True,
                        modalities=["text"],
                        supports_thinking=True,
                    ),
                    ModelServiceModelConfig(
                        id="relay-image",
                        name="relay-image",
                        model="gpt-image-1",
                        enabled=True,
                        modalities=["image"],
                    ),
                ],
            )
        ],
        defaults=ModelServiceDefaults(text_model_name="relay-gpt-5"),
    )

    merged = model_services_to_runtime_models(static_models, model_services)

    assert [model.name for model in merged] == ["relay-gpt-5", "static-model"]
    assert merged[0].base_url == "https://relay.example/v1"
    assert merged[0].api_key == "relay-key"
    assert merged[0].supports_thinking is True


def test_resolve_modality_model_name_uses_defaults_then_fallback():
    app_models = [
        ModelConfig(
            name="text-default",
            display_name="Text Default",
            use="langchain_openai:ChatOpenAI",
            model="gpt-4o-mini",
        )
    ]
    model_services = ModelServicesConfig(
        providers=[
            ModelServiceProviderConfig(
                id="openai",
                name="OpenAI",
                enabled=True,
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                modalities=["text", "image", "video"],
                models=[
                    ModelServiceModelConfig(
                        id="image-model",
                        name="image-model",
                        model="gpt-image-1",
                        enabled=True,
                        modalities=["image"],
                    )
                ],
            )
        ],
        defaults=ModelServiceDefaults(text_model_name="text-default"),
    )

    assert resolve_modality_model_name("text", app_models, model_services) == "text-default"
    assert resolve_modality_model_name("image", app_models, model_services) == "image-model"


def test_resolve_modality_model_name_raises_when_missing():
    try:
        resolve_modality_model_name("video", [], ModelServicesConfig())
    except ValueError as exc:
        assert str(exc) == "No enabled video model configured"
    else:
        raise AssertionError("Expected ValueError for missing video model")

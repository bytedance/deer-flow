"""API Route setup uses the existing OpenAI-compatible wizard path."""

import yaml
from wizard.providers import LLM_PROVIDERS
from wizard.steps import llm as llm_step
from wizard.writer import build_minimal_config


def api_route_provider():
    provider = next((p for p in LLM_PROVIDERS if p.name == "api_route"), None)
    assert provider is not None
    return provider


def test_api_route_uses_versioned_chat_endpoint_and_bare_model_id():
    provider = api_route_provider()
    assert provider.use == "langchain_openai:ChatOpenAI"
    assert provider.package == "langchain-openai"
    assert provider.env_var == "API_ROUTE_API_KEY"
    assert provider.models == ["gpt-6.1-sol"]
    assert provider.default_model == "gpt-6.1-sol"
    assert provider.extra_config["base_url"] == "https://global.api-route.com/v1"


def test_api_route_generated_config_preserves_key_reference_and_model():
    provider = api_route_provider()
    config = yaml.safe_load(
        build_minimal_config(
            provider_use=provider.use,
            model_name=provider.default_model,
            display_name=provider.display_name,
            api_key_field=provider.api_key_field,
            env_var=provider.env_var,
            extra_model_config=provider.extra_config_for(provider.default_model),
        )
    )
    model = config["models"][0]
    assert model["model"] == "gpt-6.1-sol"
    assert model["api_key"] == "$API_ROUTE_API_KEY"
    assert model["base_url"] == "https://global.api-route.com/v1"
    assert model["use"] == "langchain_openai:ChatOpenAI"
    assert model["temperature"] == 0.7
    assert "use_responses_api" not in model
    assert not model.get("supports_vision", False)
    assert not model.get("supports_thinking", False)


def test_api_route_wizard_selects_preset_and_collects_key(monkeypatch):
    provider = api_route_provider()
    monkeypatch.setattr(llm_step, "LLM_PROVIDERS", [provider])
    monkeypatch.setattr(llm_step, "ask_choice", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(llm_step, "ask_secret", lambda prompt: "test-api-route-key" if prompt == "API_ROUTE_API_KEY" else None)
    result = llm_step.run_llm_step()
    assert result.model_name == "gpt-6.1-sol"
    assert result.provider.extra_config["base_url"] == "https://global.api-route.com/v1"
    assert result.provider.env_var == "API_ROUTE_API_KEY"
    assert result.api_key == "test-api-route-key"

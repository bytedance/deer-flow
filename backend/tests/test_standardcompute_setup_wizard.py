"""Standard Compute setup uses the existing OpenAI-compatible wizard path."""

import yaml
from wizard.providers import LLM_PROVIDERS
from wizard.steps import llm as llm_step
from wizard.writer import build_minimal_config


def standardcompute_provider():
    provider = next((p for p in LLM_PROVIDERS if p.name == "standardcompute"), None)
    assert provider is not None
    return provider


def test_standardcompute_uses_versioned_chat_endpoint_and_routed_default():
    provider = standardcompute_provider()
    assert provider.use == "langchain_openai:ChatOpenAI"
    assert provider.package == "langchain-openai"
    assert provider.env_var == "STANDARDCOMPUTE_API_KEY"
    assert provider.models == ["StandardCompute"]
    assert provider.default_model == "StandardCompute"
    assert provider.extra_config["base_url"] == "https://api.stdcmpt.com/v1"


def test_standardcompute_generated_config_preserves_key_reference_and_model():
    provider = standardcompute_provider()
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
    assert model["model"] == "StandardCompute"
    assert model["api_key"] == "$STANDARDCOMPUTE_API_KEY"
    assert model["base_url"] == "https://api.stdcmpt.com/v1"
    assert model["use"] == "langchain_openai:ChatOpenAI"
    assert model["temperature"] == 0.7
    assert "use_responses_api" not in model
    assert not model.get("supports_vision", False)
    assert not model.get("supports_thinking", False)


def test_standardcompute_wizard_selects_preset_and_collects_key(monkeypatch):
    provider = standardcompute_provider()
    monkeypatch.setattr(llm_step, "LLM_PROVIDERS", [provider])
    monkeypatch.setattr(llm_step, "ask_choice", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(llm_step, "ask_secret", lambda prompt: "test-standardcompute-key" if prompt == "STANDARDCOMPUTE_API_KEY" else None)
    result = llm_step.run_llm_step()
    assert result.model_name == "StandardCompute"
    assert result.provider.extra_config["base_url"] == "https://api.stdcmpt.com/v1"
    assert result.provider.env_var == "STANDARDCOMPUTE_API_KEY"
    assert result.api_key == "test-standardcompute-key"

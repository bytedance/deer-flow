"""Step 1: LLM provider selection."""

from __future__ import annotations

from dataclasses import dataclass

from wizard.providers import LLM_PROVIDERS, LLMProvider
from wizard.ui import (
    ask_choice,
    ask_secret,
    ask_text,
    ask_yes_no,
    print_header,
    print_info,
    print_success,
)


@dataclass
class LLMStepResult:
    provider: LLMProvider
    model_name: str
    api_key: str | None
    base_url: str | None = None
    extra_model_config: dict | None = None


def _should_prompt_for_thinking_support(provider: LLMProvider) -> bool:
    """Return whether setup needs user-provided thinking capability metadata."""
    if provider.extra_config.get("supports_thinking") is not None:
        return False
    return provider.use == "langchain_openai:ChatOpenAI" and provider.name in {"openrouter", "other"}


def _ask_capability_metadata(provider: LLMProvider) -> dict:
    extra_model_config: dict = {}
    if _should_prompt_for_thinking_support(provider):
        print_header("Model capabilities")
        supports_thinking = ask_yes_no(
            "Does this model support thinking/reasoning mode?",
            default=False,
        )
        extra_model_config["supports_thinking"] = supports_thinking
    return extra_model_config


def run_llm_step(step_label: str = "Step 1/3") -> LLMStepResult:
    print_header(f"{step_label} · Choose your LLM provider")

    options = [f"{p.display_name}  ({p.description})" for p in LLM_PROVIDERS]
    idx = ask_choice("Enter choice", options)
    provider = LLM_PROVIDERS[idx]

    print()

    # Model selection (show list, default to first)
    if len(provider.models) > 1:
        print_info(f"Available models for {provider.display_name}:")
        model_idx = ask_choice("Select model", provider.models, default=0)
        model_name = provider.models[model_idx]
    else:
        model_name = provider.models[0]

    print()
    base_url: str | None = None
    if provider.name in {"openrouter", "vllm"}:
        base_url = provider.extra_config.get("base_url")
    if provider.name == "other":
        print_header(f"{step_label} · Connection details")
        base_url = ask_text("Base URL (e.g. https://api.openai.com/v1)", required=True)
        model_name = ask_text("Model name", default=provider.default_model)
    extra_model_config = _ask_capability_metadata(provider)

    if provider.auth_hint:
        print_header(f"{step_label} · Authentication")
        print_info(provider.auth_hint)
        api_key = None
        return LLMStepResult(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            extra_model_config=extra_model_config or None,
        )

    print_header(f"{step_label} · Enter your API Key")
    if provider.env_var:
        api_key = ask_secret(f"{provider.env_var}")
    else:
        api_key = None

    if api_key:
        print_success(f"Key will be saved to .env as {provider.env_var}")

    return LLMStepResult(
        provider=provider,
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        extra_model_config=extra_model_config or None,
    )

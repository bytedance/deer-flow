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
    supports_thinking: bool = False


def run_llm_step(step_label: str = "Step 1/3") -> LLMStepResult:
    print_header(f"{step_label} · Choose your LLM provider")

    options = [f"{p.display_name}  ({p.description})" for p in LLM_PROVIDERS]
    idx = ask_choice("Enter choice", options)
    provider = LLM_PROVIDERS[idx]

    print()

    # Model selection (show list, default to provider preference)
    if len(provider.models) > 1:
        print_info(f"Available models for {provider.display_name}:")
        default_model_idx = provider.models.index(provider.default_model)
        model_idx = ask_choice("Select model", provider.models, default=default_model_idx)
        model_name = provider.models[model_idx]
    else:
        model_name = provider.models[0]

    print()
    base_url: str | None = None
    if provider.name in {"openrouter", "vllm"}:
        base_url = provider.extra_config.get("base_url")

    if provider.base_url_prompt:
        print_header(f"{step_label} · Connection details")
        base_url = ask_text(provider.base_url_prompt, default=base_url or "", required=True)
        if provider.model_prompt:
            model_name = ask_text(provider.model_prompt, default=model_name)

    # Ask about thinking support for custom OpenAI-compatible gateways
    supports_thinking = _ask_thinking_support(provider)

    if provider.auth_hint:
        print_header(f"{step_label} · Authentication")
        print_info(provider.auth_hint)
        api_key = None
        return LLMStepResult(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            supports_thinking=supports_thinking,
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
        supports_thinking=supports_thinking,
    )


def _ask_thinking_support(provider: LLMProvider) -> bool:
    """Ask the user whether their OpenAI-compatible model supports thinking/reasoning.

    Only prompted for custom gateway providers (those with base_url_prompt) where
    the thinking capability is ambiguous.
    """
    if not provider.base_url_prompt:
        return False
    print_header("Thinking / Reasoning support")
    print_info(
        "Some OpenAI-compatible models (e.g. DeepSeek Reasoner, Claude Sonnet 4) "
        "support thinking/reasoning output, which can improve complex reasoning tasks."
    )
    return ask_yes_no("Does this model support thinking/reasoning output?", default=False)

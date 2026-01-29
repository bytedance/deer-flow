# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import dataclasses
import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape
from langchain.agents import AgentState

from ..config.configuration import Configuration

# Initialize Jinja2 environment
env = Environment(
    loader=FileSystemLoader(os.path.dirname(__file__)),
    autoescape=select_autoescape(),
    trim_blocks=True,
    lstrip_blocks=True,
)


def get_prompt_template(prompt_name: str, locale: str = "en-US") -> str:
    """
    Load and return a prompt template using Jinja2 with locale support.

    Args:
        prompt_name: Name of the prompt template file (without .md extension)
        locale: Language locale (e.g., en-US, zh-CN). Defaults to en-US

    Returns:
        The template string with proper variable substitution syntax
    """
    try:
        # Normalize locale format
        normalized_locale = locale.replace("-", "_") if locale and locale.strip() else "en_US"
        
        # Try locale-specific template first (e.g., researcher.zh_CN.md)
        try:
            template = env.get_template(f"{prompt_name}.{normalized_locale}.md")
            return template.render()
        except TemplateNotFound:
            # Fallback to English template if locale-specific not found
            template = env.get_template(f"{prompt_name}.md")
            return template.render()
    except Exception as e:
        raise ValueError(f"Error loading template {prompt_name} for locale {locale}: {e}")


def apply_prompt_template(
    prompt_name: str, state: AgentState, configurable: Configuration = None, locale: str = "en-US"
) -> list:
    """
    Apply template variables to a prompt template and return formatted messages.

    Args:
        prompt_name: Name of the prompt template to use
        state: Current agent state containing variables to substitute
        configurable: Configuration object with additional variables
        locale: Language locale for template selection (e.g., en-US, zh-CN)

    Returns:
        List of messages with the system prompt as the first message
    """
    try:
        system_prompt = get_system_prompt_template(prompt_name, state, configurable, locale)
        return [{"role": "system", "content": system_prompt}] + state["messages"]
    except Exception as e:
        raise ValueError(f"Error applying template {prompt_name} for locale {locale}: {e}")

def get_system_prompt_template(
    prompt_name: str, state: AgentState, configurable: Configuration = None, locale: str = "en-US"
) -> str:
    """
    Render and return the system prompt template with state and configuration variables.
    This function loads a Jinja2-based prompt template (with optional locale-specific
    variants), applies variables from the agent state and Configuration object, and
    returns the fully rendered system prompt string.
    Args:
        prompt_name: Name of the prompt template to load (without .md extension).
        state: Current agent state containing variables available to the template.
        configurable: Optional Configuration object providing additional template variables.
        locale: Language locale for template selection (e.g., en-US, zh-CN).
    Returns:
        The rendered system prompt string after applying all template variables.
    """
    # Convert state to dict for template rendering
    state_vars = {
        "CURRENT_TIME": datetime.now().strftime("%a %b %d %Y %H:%M:%S %z"),
        **state,
    }

    # Add configurable variables
    if configurable:
        state_vars.update(dataclasses.asdict(configurable))

    try:
        # Normalize locale format
        normalized_locale = locale.replace("-", "_") if locale and locale.strip() else "en_US"

        # Try locale-specific template first
        try:
            template = env.get_template(f"{prompt_name}.{normalized_locale}.md")
        except TemplateNotFound:
            # Fallback to English template
            template = env.get_template(f"{prompt_name}.md")

        system_prompt = template.render(**state_vars)
        return system_prompt
    except Exception as e:
        raise ValueError(f"Error loading template {prompt_name} for locale {locale}: {e}")
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from pathlib import Path
from typing import Any, Dict, Optional

from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel

from src.config import load_yaml_config
from src.config.agents import LLMType

# Cache for LLM instances
_llm_cache: dict[LLMType, BaseChatModel] = {}


def _create_llm_use_conf(llm_type: LLMType, conf: Dict[str, Any]) -> BaseChatModel:
    llm_type_map = {
        "reasoning": conf.get("REASONING_MODEL"),
        "basic": conf.get("BASIC_MODEL"),
        "vision": conf.get("VISION_MODEL"),
    }
    llm_conf = llm_type_map.get(llm_type)
    if not llm_conf:
        raise ValueError(f"Unknown LLM type: {llm_type}")
    if not isinstance(llm_conf, dict):
        raise ValueError(f"Invalid LLM Conf: {llm_type}")

    is_azure = "api_version" in llm_conf or (
        llm_conf.get("base_url") and "azure.com" in llm_conf.get("base_url", "")
    )

    if is_azure:
        azure_init_params = {}
        if llm_conf.get("base_url"):
            azure_init_params["azure_endpoint"] = llm_conf.get("base_url")
        if llm_conf.get("api_version"):
            azure_init_params["openai_api_version"] = llm_conf.get("api_version")
        if llm_conf.get("model"):
            azure_init_params["azure_deployment"] = llm_conf.get("model")
        if llm_conf.get("api_key"):
            azure_init_params["openai_api_key"] = llm_conf.get("api_key")

        for param_key in ["temperature", "max_tokens", "timeout", "max_retries"]:
            if param_key in llm_conf:
                azure_init_params[param_key] = llm_conf[param_key]

        required_azure_keys = [
            "azure_endpoint",
            "openai_api_version",
            "azure_deployment",
            "openai_api_key",
        ]
        for key in required_azure_keys:
            if key not in azure_init_params or azure_init_params[key] is None:
                original_key = key
                if key == "azure_endpoint":
                    original_key = "base_url"
                elif key == "openai_api_version":
                    original_key = "api_version"
                elif key == "azure_deployment":
                    original_key = "model (deployment name)"
                elif key == "openai_api_key":
                    original_key = "api_key"
                raise ValueError(
                    f"Missing or None value for required Azure configuration: '{original_key}' (maps to '{key}') for LLM type '{llm_type}'. "
                    f"Current llm_conf for this type: {llm_conf}"
                )

        return AzureChatOpenAI(**azure_init_params)

    return ChatOpenAI(**llm_conf)


def get_llm_by_type(
    llm_type: LLMType,
) -> ChatOpenAI:
    """
    Get LLM instance by type. Returns cached instance if available.
    """
    if llm_type in _llm_cache:
        return _llm_cache[llm_type]

    conf = load_yaml_config(
        str((Path(__file__).parent.parent.parent / "conf.yaml").resolve())
    )
    llm = _create_llm_use_conf(llm_type, conf)
    _llm_cache[llm_type] = llm
    return llm


# In the future, we will use reasoning_llm and vl_llm for different purposes
# reasoning_llm = get_llm_by_type("reasoning")
# vl_llm = get_llm_by_type("vision")


if __name__ == "__main__":
    # Initialize LLMs for different purposes - now these will be cached
    basic_llm = get_llm_by_type("basic")
    print(basic_llm.invoke("Hello"))

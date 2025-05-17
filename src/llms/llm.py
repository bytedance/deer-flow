# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from pathlib import Path
from typing import Any, Dict

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, AzureChatOpenAI

from src.config import load_yaml_config
from src.config.agents import LLMType

# Cache for LLM instances
_llm_cache: Dict[LLMType, BaseChatModel] = {}


def _create_llm_use_conf(llm_type: LLMType, conf: Dict[str, Any]) -> BaseChatModel:
    """
    Create LLM instance using configuration for given type.
    Supports both OpenAI and Azure OpenAI models.
    """
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

    # Check if Azure configuration exists as a sub-config
    if "AZURE" in llm_conf and isinstance(llm_conf["AZURE"], dict):
        azure_conf = llm_conf["AZURE"]
        return AzureChatOpenAI(
            deployment_name=azure_conf.get("model"),
            openai_api_version=azure_conf.get("api_version"),
            azure_endpoint=azure_conf.get("base_url"),
            openai_api_key=azure_conf.get("api_key"),
        )

    # Check if OpenAI configuration exists as a sub-config
    if "OPENAI" in llm_conf and isinstance(llm_conf["OPENAI"], dict):
        return ChatOpenAI(**llm_conf["OPENAI"])

    # Original behavior - direct configuration
    return ChatOpenAI(**llm_conf)


def get_llm_by_type(
    llm_type: LLMType,
) -> BaseChatModel:
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


# Initialize LLMs for different purposes - now these will be cached
basic_llm = get_llm_by_type("basic")

# In the future, we will use reasoning_llm and vl_llm for different purposes
# reasoning_llm = get_llm_by_type("reasoning")
# vl_llm = get_llm_by_type("vision")


if __name__ == "__main__":
    print(basic_llm.invoke("Hello"))

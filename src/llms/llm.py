# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from pathlib import Path
from typing import Any, Dict

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, AzureChatOpenAI

from src.config import load_yaml_config
from src.config.agents import LLMType
import os

# Cache for LLM instances
_llm_cache: Dict[str, BaseChatModel] = {}


def _create_llm_use_conf(llm_type: LLMType, conf: Dict[str, Any]) -> BaseChatModel:
    basic = conf.get("BASIC_MODEL")
    openai_basic = basic and basic.get("OPENAI")
    azure_basic = basic and basic.get("AZURE")

    llm_config = {
        "reasoning": conf.get("REASONING_MODEL"),
        "basic": openai_basic or azure_basic,
        "vision": conf.get("VISION_MODEL"),
    }.get(llm_type)

    if not llm_config:
        raise ValueError(f"Unknown LLM type: {llm_type}")
    if not isinstance(llm_config, dict):
        raise ValueError(f"Invalid LLM Conf: {llm_type}")

    if openai_basic is not None:
        return ChatOpenAI(**llm_config)

    os.environ.update({
        "OPENAI_API_VERSION": llm_config.get("api_version"),
        "AZURE_OPENAI_API_KEY": llm_config.get("api_key"),
        "AZURE_OPENAI_ENDPOINT": llm_config.get("base_url")
    })
    return AzureChatOpenAI(deployment_name=llm_config.get("model"))


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

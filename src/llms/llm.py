# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from pathlib import Path
from typing import Any, Dict, Tuple
import os

from langchain_openai import ChatOpenAI

from src.config import load_yaml_config
from src.config.agents import LLMType

# Cache for LLM instances keyed by (llm_type, model_name)
_llm_cache: dict[Tuple[LLMType, str], ChatOpenAI] = {}


def _get_env_llm_conf(llm_type: str) -> Dict[str, Any]:
    """
    Get LLM configuration from environment variables.
    Environment variables should follow the format: {LLM_TYPE}__{KEY}
    e.g., BASIC_MODEL__api_key, BASIC_MODEL__base_url
    """
    prefix = f"{llm_type.upper()}_MODEL__"
    conf = {}
    for key, value in os.environ.items():
        if key.startswith(prefix):
            conf_key = key[len(prefix) :].lower()
            conf[conf_key] = value
    return conf


def _create_llm_use_conf(
    llm_type: LLMType, conf: Dict[str, Any], model_override: str | None = None
) -> ChatOpenAI:
    llm_type_map = {
        "reasoning": conf.get("REASONING_MODEL", {}),
        "basic": conf.get("BASIC_MODEL", {}),
        "vision": conf.get("VISION_MODEL", {}),
    }
    llm_conf = llm_type_map.get(llm_type)
    if not isinstance(llm_conf, dict):
        raise ValueError(f"Invalid LLM Conf: {llm_type}")
    # Get configuration from environment variables
    env_conf = _get_env_llm_conf(llm_type)

    # Merge configurations, with environment variables taking precedence
    merged_conf = {**llm_conf, **env_conf}
    if model_override:
        merged_conf["model"] = model_override

    if not merged_conf:
        raise ValueError(f"Unknown LLM Conf: {llm_type}")

    return ChatOpenAI(**merged_conf)


def get_llm_by_type(
    llm_type: LLMType, model: str | None = None
) -> ChatOpenAI:
    """
    Get LLM instance by type. Returns cached instance if available.
    """
    cache_key = (llm_type, model or "")
    if cache_key in _llm_cache:
        return _llm_cache[cache_key]

    conf = load_yaml_config(
        str((Path(__file__).parent.parent.parent / "conf.yaml").resolve())
    )
    llm = _create_llm_use_conf(llm_type, conf, model)
    _llm_cache[cache_key] = llm
    return llm


# In the future, we will use reasoning_llm and vl_llm for different purposes
# reasoning_llm = get_llm_by_type("reasoning")
# vl_llm = get_llm_by_type("vision")

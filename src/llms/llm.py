# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from pathlib import Path
from typing import Any, Dict, Tuple
import os
import logging

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# Add a file handler to persist LLM requests and responses.
# This is done lazily to avoid adding duplicate handlers when the module
# is imported multiple times during tests or execution.
if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
    file_handler = logging.FileHandler("log.txt", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    )
    logger.addHandler(file_handler)


class LoggingChatOpenAI:
    """Wrapper around ChatOpenAI that logs requests and responses."""

    def __init__(self, **kwargs):
        self.llm = ChatOpenAI(**kwargs)

    def invoke(self, messages, *args, **kwargs):
        logger.info(f"LLM request: {messages}")
        response = self.llm.invoke(messages, *args, **kwargs)
        logger.info(f"LLM response: {response}")
        return response

    async def ainvoke(self, messages, *args, **kwargs):
        logger.info(f"LLM request: {messages}")
        response = await self.llm.ainvoke(messages, *args, **kwargs)
        logger.info(f"LLM response: {response}")
        return response

    def stream(self, messages, *args, **kwargs):
        logger.info(f"LLM request: {messages}")
        for chunk in self.llm.stream(messages, *args, **kwargs):
            logger.info(f"LLM chunk: {chunk}")
            yield chunk

    async def astream(self, messages, *args, **kwargs):
        logger.info(f"LLM request: {messages}")
        async for chunk in self.llm.astream(messages, *args, **kwargs):
            logger.info(f"LLM chunk: {chunk}")
            yield chunk

    def __getattr__(self, item):
        return getattr(self.llm, item)

    @staticmethod
    def _wrap(llm_instance: ChatOpenAI) -> "LoggingChatOpenAI":
        obj = LoggingChatOpenAI.__new__(LoggingChatOpenAI)
        obj.llm = llm_instance
        return obj

    def with_structured_output(self, *args, **kwargs) -> "LoggingChatOpenAI":
        new_llm = self.llm.with_structured_output(*args, **kwargs)
        return self._wrap(new_llm)

    def bind_tools(self, *args, **kwargs) -> "LoggingChatOpenAI":
        new_llm = self.llm.bind_tools(*args, **kwargs)
        return self._wrap(new_llm)


from src.config import load_yaml_config
from src.config.agents import LLMType

# Cache for LLM instances keyed by (llm_type, model_name)
_llm_cache: dict[Tuple[LLMType, str], LoggingChatOpenAI] = {}


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
) -> LoggingChatOpenAI:
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

    return LoggingChatOpenAI(**merged_conf)


def get_llm_by_type(llm_type: LLMType, model: str | None = None) -> LoggingChatOpenAI:
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

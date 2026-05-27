"""Dify multi-workflow router — unified invocation entry point."""

import logging
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.dify_client import DifyAPIError, DifyClient

from deerflow.config import get_app_config
from deerflow.runtime.user_context import get_effective_user_id

_MAX_CONVERSATION_CACHE = 1000
_conversation_ids: OrderedDict[str, str] = OrderedDict()
_lock = Lock()
_workflow_loggers: dict[str, logging.Logger] = {}


class ToolConfigResult:
    """Parsed result of a tool config read from config.yaml."""

    def __init__(self, api_key: str, base_url: str, response_mode: str = "blocking"):
        self.api_key = api_key
        self.base_url = base_url
        self.response_mode = response_mode


def _get_cache_key(tool_name: str, config: RunnableConfig | None) -> str:
    user_id = get_effective_user_id()
    thread_id = _get_thread_id(config)
    return f"{user_id}:{thread_id}:{tool_name}"


def _get_thread_id(config: RunnableConfig | None) -> str:
    """Extract thread_id from RunnableConfig, or return 'default'."""
    if config is None:
        return "default"
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id")
    if thread_id is None:
        return "default"
    return str(thread_id)


def _get_cached_conversation(cache_key: str) -> str:
    """Retrieve conversation_id from bounded LRU cache, or empty string if not found (thread-safe)."""
    with _lock:
        if cache_key in _conversation_ids:
            _conversation_ids.move_to_end(cache_key)
            return _conversation_ids[cache_key]
        return ""


def _cache_conversation(cache_key: str, conversation_id: str) -> None:
    """Store conversation_id in bounded LRU cache (thread-safe)."""
    with _lock:
        _conversation_ids[cache_key] = conversation_id
        _conversation_ids.move_to_end(cache_key)
        if len(_conversation_ids) > _MAX_CONVERSATION_CACHE:
            _conversation_ids.popitem(last=False)


def _get_tool_config(tool_name: str) -> ToolConfigResult:
    """Read tool configuration from config.yaml."""
    config = get_app_config().get_tool_config(tool_name)
    if config is None:
        raise DifyAPIError(0, f"Tool '{tool_name}' is not configured in config.yaml")
    api_key: str | None = None
    if config.model_extra:
        api_key = config.model_extra.get("api_key")
    if not api_key:
        raise DifyAPIError(0, f"api_key not configured for tool '{tool_name}'")
    base_url = (config.model_extra.get("base_url") if config.model_extra else None) or "http://localhost:8000"
    response_mode = (config.model_extra.get("response_mode") if config.model_extra else None) or "blocking"
    return ToolConfigResult(api_key=api_key, base_url=base_url, response_mode=response_mode)


def _get_workflow_logger(tool_name: str) -> logging.Logger:
    """Return a logger that writes per-workflow log files to backend/logs/dify_{tool_name}.log."""
    if tool_name not in _workflow_loggers:
        logger = logging.getLogger(f"zens.community.dify.{tool_name}")
        logger.setLevel(logging.DEBUG)
        _logs_dir = Path(__file__).resolve().parent.parent.parent.parent / "logs"
        _logs_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(_logs_dir / f"dify_{tool_name}.log", mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
        _workflow_loggers[tool_name] = logger
    return _workflow_loggers[tool_name]


def invoke_workflow(
    tool_name: str,
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Unified workflow invocation entry point.

    Routes to blocking or streaming mode based on the ``response_mode`` field
    in config.yaml for the given tool. Maintains conversation context in a
    thread-safe LRU cache keyed by (user_id, thread_id, workflow_name).
    """
    logger = _get_workflow_logger(tool_name)
    cache_key = _get_cache_key(tool_name, config)
    conversation_id = _get_cached_conversation(cache_key)
    user_id = get_effective_user_id()
    user = f"deerflow_{user_id}"

    logger.info(
        "invoke_workflow: tool=%s, query=%r, conversation_id=%r",
        tool_name,
        query,
        conversation_id,
    )

    tool_cfg = _get_tool_config(tool_name)
    client = DifyClient(api_key=tool_cfg.api_key, base_url=tool_cfg.base_url)

    if tool_cfg.response_mode == "streaming":
        chunks, conv_id = client.chat_stream(query=query, conversation_id=conversation_id, user=user)
        full_answer = "".join(chunks)
        if conv_id:
            _cache_conversation(cache_key, conv_id)
        logger.info(
            "invoke_workflow streaming completed: answer=%r, conversation_id=%s",
            full_answer[:50] if full_answer else "",
            conv_id,
        )
        return full_answer

    response = client.chat(query=query, conversation_id=conversation_id, user=user)
    if response.conversation_id:
        _cache_conversation(cache_key, response.conversation_id)
    logger.info(
        "invoke_workflow blocking completed: answer=%r",
        response.answer[:50] if response.answer else "",
    )
    return response.answer

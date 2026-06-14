"""LLM I/O Trace Middleware — logs raw model input/output.

A dev-only debugging tool controlled by :class:`LLMIOTraceConfig`. The four
``print_*`` flags gate each block independently:

- ``print_system_prompt`` — request.system_message
- ``print_messages``      — request.messages  (+ per-message additional_kwargs)
- ``print_tools``         — request.tools
- ``print_response``      — response.result   (+ per-message additional_kwargs / response_metadata)

``max_messages > 0`` keeps only the most recent N messages (the tail), dropping
the older ones. ``max_messages == 0`` prints everything.
"""

import logging
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware

from deerflow.config.llm_io_trace_config import LLMIOTraceConfig

logger = logging.getLogger("deerflow.agents.middlewares.llm_io_trace")


class LLMIOTraceMiddleware(AgentMiddleware[AgentState]):
    def __init__(self, config: LLMIOTraceConfig):
        super().__init__()
        self._config = config

    @override
    async def awrap_model_call(self, request, handler):
        _print_request(self._config, request)
        response = await handler(request)
        _print_response(self._config, response)
        return response

    @override
    def wrap_model_call(self, request, handler):
        _print_request(self._config, request)
        response = handler(request)
        _print_response(self._config, response)
        return response


def _print_message(idx: int, m: Any, *, include_meta: bool) -> None:
    """Print a message: header line, multi-line content, then optional meta."""
    if hasattr(m, "type"):
        role = m.type
    else:
        role = "?"
    extra = []
    if getattr(m, "id", None):
        extra.append(f"id={m.id!r}")
    if getattr(m, "name", None):
        extra.append(f"name={m.name!r}")
    if getattr(m, "tool_calls", None):
        extra.append(f"tool_calls={m.tool_calls!r}")
    if getattr(m, "tool_call_id", None):
        extra.append(f"tool_call_id={m.tool_call_id!r}")
    header = f"[{idx}] {role}"
    if extra:
        header += "  " + " ".join(extra)
    logger.info(header)
    logger.info("  content:")
    content = m.content
    if isinstance(content, str):
        for line in content.splitlines() or [""]:
            logger.info(f"    {line}")
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("content") or ""
                if text:
                    for line in str(text).splitlines() or [""]:
                        logger.info(f"    {line}")
            else:
                logger.info(f"    {block!r}")
    elif content is None:
        logger.info("    (none)")
    else:
        logger.info(f"    {content!r}")
    if not include_meta:
        return
    if getattr(m, "additional_kwargs", None):
        logger.info("  additional_kwargs:")
        for k, v in m.additional_kwargs.items():
            rendered = repr(v)
            for line in rendered.splitlines() or [""]:
                logger.info(f"    {k}: {line}")
    if getattr(m, "response_metadata", None):
        logger.info(f"  response_metadata: {m.response_metadata!r}")


def _tail(messages, max_n: int):
    """Return the last *max_n* messages, or all of them when *max_n* is 0."""
    if not max_n or len(messages) <= max_n:
        return messages, 0
    return messages[-max_n:], len(messages) - max_n


def _print_request(config: LLMIOTraceConfig, request) -> None:
    if not (config.print_system_prompt or config.print_messages or config.print_tools):
        return
    logger.info("[LLM REQUEST]")
    if config.print_system_prompt:
        logger.info("--- system_message ---")
        if request.system_message is not None:
            _print_message(0, request.system_message, include_meta=False)
        else:
            logger.info("  (none)")
    if config.print_messages:
        logger.info("--- messages ---")
        if request.messages:
            tail, skipped = _tail(list(request.messages), config.max_messages)
            if skipped:
                logger.info(f"  ... [skipped {skipped} earlier message(s)]")
            for i, m in enumerate(tail):
                _print_message(i, m, include_meta=True)
        else:
            logger.info("  (none)")
    if config.print_tools:
        logger.info("--- tools ---")
        if request.tools:
            for i, t in enumerate(request.tools):
                logger.info(f"[{i}] {t!r}")
        else:
            logger.info("  (none)")


def _print_response(config: LLMIOTraceConfig, response) -> None:
    if not config.print_response:
        return
    logger.info("[LLM RESPONSE]")
    logger.info("--- result ---")
    result = response.result or []
    if result:
        tail, skipped = _tail(list(result), config.max_messages)
        if skipped:
            logger.info(f"  ... [skipped {skipped} earlier result(s)]")
        for i, m in enumerate(tail):
            _print_message(i, m, include_meta=True)
    else:
        logger.info("  (none)")

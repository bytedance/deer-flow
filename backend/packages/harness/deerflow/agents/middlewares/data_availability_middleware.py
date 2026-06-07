"""Middleware to inject a DATA AVAILABILITY summary before LLM report generation.

Scans all ToolMessages in the model request for MCP envelope format
(status/source/error_code fields). Generates a structured availability
declaration that the LLM cannot ignore — preventing hallucination of
metrics for failed data sources.

Part of STORY-067: Anti-Hallucination L2 defense layer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

_DATA_AVAILABILITY_KEY = "data_availability_reminder"


def _try_parse_envelope(content: str) -> dict[str, Any] | None:
    """Try to parse ToolMessage content as an envelope JSON."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict) and "status" in data and "source" in data:
        return data
    return None


def _estimate_data_size(envelope: dict[str, Any]) -> str:
    """Estimate the data size from an envelope for the summary line."""
    data = envelope.get("data")
    if data is None:
        return "data=null"
    if isinstance(data, str):
        return f"{len(data)} chars"
    serialized = json.dumps(data, ensure_ascii=False)
    return f"{len(serialized)} chars"


def _build_availability_block(envelopes: list[dict[str, Any]]) -> str:
    """Build the DATA AVAILABILITY declaration from parsed envelopes."""
    lines: list[str] = []
    lines.append("=== DATA AVAILABILITY (system-enforced, do NOT contradict) ===")

    for env in envelopes:
        source = env.get("source", "unknown")
        status = env.get("status", "unknown")
        error_code = env.get("error_code")

        if status == "ok":
            size = _estimate_data_size(env)
            lines.append(f"✅ {source}: SUCCESS ({size})")
        else:
            detail = error_code or "UNKNOWN_ERROR"
            lines.append(f"❌ {source}: FAILED ({detail}, data=null)")

    has_failures = any(env.get("status") != "ok" for env in envelopes)
    has_successes = any(env.get("status") == "ok" for env in envelopes)
    lines.append("")
    if has_failures:
        rule_parts = ["RULE: Sources marked with a cross returned NO DATA. You MUST NOT report metrics, numbers,\n"
                      "or findings for failed sources."]
        if has_successes:
            rule_parts.append(" Only present findings from successful sources marked above.")
        rule_parts.append("\nAny numeric value in your report MUST be traceable to a successful tool result above.")
        lines.append("".join(rule_parts))
    else:
        lines.append("All data sources returned successfully. Report based on actual tool results only.")

    return "\n".join(lines)


def _already_injected(messages: list[Any]) -> bool:
    """Check if a DATA AVAILABILITY reminder was already injected."""
    return any(
        isinstance(m, HumanMessage) and m.additional_kwargs.get(_DATA_AVAILABILITY_KEY)
        for m in messages
    )


def _inject_availability(messages: list[Any]) -> list[Any] | None:
    """Scan messages for envelope ToolMessages and inject availability block.

    Returns the modified message list, or None if no injection needed.
    """
    if _already_injected(messages):
        return None

    envelopes: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content if isinstance(msg.content, str) else None
        if content is None:
            continue
        envelope = _try_parse_envelope(content)
        if envelope is not None:
            envelopes.append(envelope)

    if not envelopes:
        return None

    block = _build_availability_block(envelopes)
    reminder_content = f"<system-reminder>\n<data_availability>\n{block}\n</data_availability>\n</system-reminder>"

    reminder_msg = HumanMessage(
        content=reminder_content,
        additional_kwargs={"hide_from_ui": True, _DATA_AVAILABILITY_KEY: True},
    )

    new_messages = list(messages) + [reminder_msg]
    return new_messages


class DataAvailabilityMiddleware(AgentMiddleware[AgentState]):
    """Inject DATA AVAILABILITY summary before LLM generates a report.

    Hooks into wrap_model_call to scan all ToolMessages for envelope format,
    then prepends a structured availability declaration to the model request.
    This prevents the LLM from hallucinating data for failed sources.
    """

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        messages = getattr(request, "messages", None)
        if isinstance(messages, list):
            injected = _inject_availability(messages)
            if injected is not None:
                logger.info("DataAvailabilityMiddleware: injected availability block (%d envelope sources)", len([m for m in messages if isinstance(m, ToolMessage)]))
                request = request.override(messages=injected)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        messages = getattr(request, "messages", None)
        if isinstance(messages, list):
            injected = _inject_availability(messages)
            if injected is not None:
                logger.info("DataAvailabilityMiddleware: injected availability block (async)")
                request = request.override(messages=injected)
        return await handler(request)

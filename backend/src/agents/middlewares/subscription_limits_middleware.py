"""Middleware enforcing subscription-based runtime limits.

Current enforcement:
- Context window budget (trim oldest messages when estimated token usage exceeds tier cap)
"""

from __future__ import annotations

import os
import logging
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime

from src.config.subscription_config import get_limits_for_subscription, normalize_subscription_tier
from src.utils.runtime import get_subscription_tier_context

logger = logging.getLogger(__name__)

_DEBUG_SUBSCRIPTION = os.getenv("DEER_FLOW_DEBUG_SUBSCRIPTION", "").lower() in {"1", "true", "yes", "on"}


class SubscriptionLimitsMiddlewareState(AgentState):
    pass


def _estimate_text_tokens(text: str) -> int:
    # Fast and dependency-free approximation used only for guardrail trimming.
    # 1 token ~= 4 chars is conservative enough for control-flow decisions.
    return max(1, len(text) // 4)


def _message_to_text(msg: Any) -> str:
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type == "text":
                    chunks.append(str(item.get("text", "")))
                elif item_type == "image_url":
                    chunks.append("[image]")
                else:
                    chunks.append(str(item))
            else:
                chunks.append(str(item))
        return "\n".join(chunks)

    return str(content)


def _estimate_message_tokens(msg: Any) -> int:
    # Base per-message overhead plus content estimate.
    return 6 + _estimate_text_tokens(_message_to_text(msg))


def _trim_messages_to_limit(messages: list[Any], token_limit: int) -> tuple[list[Any], int]:
    if not messages:
        return messages, 0

    total_tokens = sum(_estimate_message_tokens(m) for m in messages)
    if total_tokens <= token_limit:
        return messages, 0

    kept_reversed: list[Any] = []
    running = 0
    for msg in reversed(messages):
        msg_tokens = _estimate_message_tokens(msg)
        if kept_reversed and running + msg_tokens > token_limit:
            continue
        kept_reversed.append(msg)
        running += msg_tokens

    if not kept_reversed:
        kept_reversed = [messages[-1]]

    kept = list(reversed(kept_reversed))
    return kept, len(messages) - len(kept)


class SubscriptionLimitsMiddleware(AgentMiddleware[SubscriptionLimitsMiddlewareState]):
    """Apply subscription-based context budget before model invocation."""

    state_schema = SubscriptionLimitsMiddlewareState

    def _apply_context_window_limit(self, state: SubscriptionLimitsMiddlewareState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        tier_raw, tier_source = get_subscription_tier_context(runtime)
        tier = normalize_subscription_tier(tier_raw, strict=False)
        token_limit = get_limits_for_subscription(tier).context_window_tokens

        if _DEBUG_SUBSCRIPTION:
            try:
                writer = get_stream_writer()
                writer(
                    {
                        "type": "subscription_debug",
                        "raw_value": tier_raw,
                        "source_key": tier_source,
                        "resolved_tier": tier.value,
                        "context_window_tokens": token_limit,
                    }
                )
            except Exception:
                logger.debug("subscription debug event unavailable in this execution context", exc_info=True)

        trimmed_messages, trimmed_count = _trim_messages_to_limit(messages, token_limit)
        if trimmed_count <= 0:
            return None

        # Replace in-place so the model sees the bounded context only.
        state["messages"] = trimmed_messages

        reminder = HumanMessage(
            name="subscription_context_window_trim",
            content=(
                "<system_reminder>\n"
                f"Context was trimmed to fit your '{tier.value}' subscription limit ({token_limit} tokens). "
                f"Dropped {trimmed_count} oldest message(s).\n"
                "</system_reminder>"
            ),
        )
        return {"messages": [reminder]}

    @override
    def before_model(self, state: SubscriptionLimitsMiddlewareState, runtime: Runtime) -> dict | None:
        return self._apply_context_window_limit(state, runtime)

    @override
    async def abefore_model(self, state: SubscriptionLimitsMiddlewareState, runtime: Runtime) -> dict | None:
        return self._apply_context_window_limit(state, runtime)

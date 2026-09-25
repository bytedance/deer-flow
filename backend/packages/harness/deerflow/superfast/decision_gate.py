"""Superfast Decision Gate: a small System One front-door classifier.

Ported for DeerFlow from the harness-superfast reference implementation by
Andrea Bruno, released under CC BY 4.0. The idea is that every user message
currently wakes a large, slow, expensive model just to decide intent, whether a
tool is needed, and what to do. A small, non-autoregressive "System One" decision
model (Von, or any Jev-compatible server) can answer those routine questions in a
single forward pass without generating text. The gate turns those typed answers
into a conservative routing recommendation.

This first increment is a shadow-only observer. It is off by default, it never
changes routing or agent state, it never skips the model call, and it fails open
on any error, timeout, non-2xx response, or malformed body, so the agent behaves
exactly as if the gate were absent. Acting on the recommendation is a later,
validated step.

Enable it explicitly with the ``SUPERFAST_ENABLED`` environment variable. The
decision model itself is installed out of band and is not bundled here; the gate
talks to it over plain HTTP using ``httpx``, which is already a core dependency.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
from typing import Any

import httpx
from langchain.agents.middleware import AgentMiddleware

logger = logging.getLogger(__name__)

# Environment-driven configuration. Everything is off by default so a user who
# does nothing sees the exact current behavior.
_ENABLED_ENV = "SUPERFAST_ENABLED"
_ENDPOINT_ENV = "SUPERFAST_ENDPOINT"
_MODEL_ENV = "SUPERFAST_MODEL"
_TIMEOUT_MS_ENV = "SUPERFAST_TIMEOUT_MS"

DEFAULT_ENDPOINT = "http://localhost:8000/v1/systemone"
DEFAULT_MODEL = "von-1.2.0"
DEFAULT_TIMEOUT_MS = 150

# The three typed questions asked in one pass. Kept small so the single forward
# pass stays well under the timeout budget.
TURN_QUESTIONS: dict[str, dict[str, Any]] = {
    "needs_tool": {
        "type": "noul",
        "instructions": "Does answering this request require taking an action with a tool (reading, writing, running, searching), rather than replying from what is already known?",
    },
    "answerable_from_context": {
        "type": "noul",
        "instructions": "Can this request be answered from information already present in the conversation, without any new investigation?",
    },
    "intent": {
        "type": "choice",
        "instructions": "Classify the primary intent of the user request.",
        "criteria": {
            "code_change": "Create, edit, or delete code or files.",
            "code_question": "Explain or reason about code without changing it.",
            "command": "Run a command or operation.",
            "chat": "Casual conversation or a question needing no tools.",
            "other": "None of the above.",
        },
    },
}


def is_enabled() -> bool:
    """Return True only when ``SUPERFAST_ENABLED`` is set to a truthy value."""
    return os.environ.get(_ENABLED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _endpoint() -> str:
    return os.environ.get(_ENDPOINT_ENV, "").strip() or DEFAULT_ENDPOINT


def _model() -> str:
    return os.environ.get(_MODEL_ENV, "").strip() or DEFAULT_MODEL


def _timeout_seconds() -> float:
    raw = os.environ.get(_TIMEOUT_MS_ENV, "").strip()
    try:
        timeout_ms = int(raw) if raw else DEFAULT_TIMEOUT_MS
    except ValueError:
        timeout_ms = DEFAULT_TIMEOUT_MS
    if timeout_ms <= 0:
        timeout_ms = DEFAULT_TIMEOUT_MS
    return timeout_ms / 1000.0


def _finite_unit(value: Any) -> float | None:
    """Return ``value`` only when it is a real number in the closed [0, 1] range.

    Anything else (absent, ``bool``, ``NaN``, ``Infinity``, out of range, wrong
    type) is treated as "no evidence" so a mis-scaled or missing answer can never
    produce a decisive fast route.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if math.isnan(value) or math.isinf(value) or value < 0.0 or value > 1.0:
        return None
    return float(value)


def _answer(answers: dict[str, Any], key: str) -> dict[str, Any]:
    value = answers.get(key)
    return value if isinstance(value, dict) else {}


async def query_system_one(state: str, questions: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Issue one Jev-compatible request and return the answers map, or ``None``.

    Fail-open: a timeout, connection error, non-2xx status, or a body without a
    well-formed ``answers`` object all yield ``None`` and never raise into the
    agent loop.
    """
    body = {"model": _model(), "state": state, "questions": questions}
    try:
        async with httpx.AsyncClient(timeout=_timeout_seconds()) as client:
            response = await client.post(_endpoint(), json=body, headers={"Accept": "application/json"})
    except Exception:
        # Any transport error (timeout, connection refused, DNS, reset) fails open.
        logger.debug("superfast gate unavailable (fail-open)")
        return None
    if response.status_code != 200:
        logger.debug("superfast gate non-2xx status=%s", response.status_code)
        return None
    try:
        payload = response.json()
    except Exception:
        logger.debug("superfast gate malformed response body")
        return None
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict):
        logger.debug("superfast gate response missing answers")
        return None
    return answers


def derive_route(answers: dict[str, Any]) -> str:
    """Derive a conservative route; only a decisive signal produces a fast route.

    The gate recommends a fast route only when the relevant probabilities are
    decisive; otherwise it returns ``unknown`` so the caller falls back to the
    normal path.
    """
    needs_tool = _finite_unit(_answer(answers, "needs_tool").get("noul"))
    from_context = _finite_unit(_answer(answers, "answerable_from_context").get("noul"))
    intent = _answer(answers, "intent")
    intent_confidence = _finite_unit(intent.get("confidence"))

    # A decisive "needs a tool" wins first: the harness must not skip work.
    if needs_tool is not None and needs_tool >= 0.85:
        return "needs_tool"

    # Strongly answerable from context, with a present and low tool-need signal.
    if from_context is not None and from_context >= 0.85 and needs_tool is not None and needs_tool <= 0.3:
        return "answer_from_context"

    # Clearly chat, with a calibrated intent and a present, low tool-need signal.
    if intent.get("choice") == "chat" and intent_confidence is not None and intent_confidence >= 0.5 and needs_tool is not None and needs_tool <= 0.2:
        return "plain_chat"

    return "unknown"


async def classify_turn(user_text: str) -> tuple[str, int] | None:
    """Classify one user turn through the gate.

    Returns ``(route, latency_ms)`` when the backend produced answers, or ``None``
    when the turn is empty or the gate is unavailable (fail-open).
    """
    if not user_text.strip():
        return None
    started = time.monotonic()
    answers = await query_system_one(user_text, TURN_QUESTIONS)
    latency_ms = int((time.monotonic() - started) * 1000)
    if answers is None:
        return None
    return derive_route(answers), latency_ms


def _message_type(message: Any) -> str | None:
    if isinstance(message, dict):
        message_type = message.get("type") or message.get("role")
    else:
        message_type = getattr(message, "type", None)
    if message_type == "user":
        return "human"
    return message_type if isinstance(message_type, str) else None


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    return ""


def _latest_user_text(state: Any) -> str:
    """Return the most recent user message text, or an empty string.

    Only a trailing human message counts as a fresh user turn. Injected
    ``<system-reminder>`` blocks are stripped so the gate sees the raw intent.
    """
    messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
    if not messages:
        return ""
    last = messages[-1]
    if _message_type(last) != "human":
        return ""
    content = last.get("content") if isinstance(last, dict) else getattr(last, "content", "")
    text = _content_text(content)
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL)
    return text.strip()


class SuperfastDecisionGateMiddleware(AgentMiddleware):
    """Shadow-only observer that classifies the incoming user turn and logs the route.

    Registered at the front of the lead-agent middleware chain. It reads the most
    recent user message, asks the decision backend the three typed questions, and
    logs the recommended route and latency through the project logger. It never
    returns state updates, never skips the model call, and never changes routing.
    When the gate is disabled or unavailable it does nothing.
    """

    @staticmethod
    def enabled() -> bool:
        """Whether the gate should be installed for this process."""
        return is_enabled()

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if not is_enabled():
            return None
        user_text = _latest_user_text(state)
        if not user_text:
            return None
        result = await classify_turn(user_text)
        if result is None:
            return None
        route, latency_ms = result
        logger.info("superfast decision gate (shadow): route=%s latency_ms=%s", route, latency_ms)
        return None

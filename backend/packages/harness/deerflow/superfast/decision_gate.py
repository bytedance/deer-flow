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

Design goal (measurable, not a promise of "never worse"): while in shadow mode the
gate must add no state change and no routing change, and its added wall-clock cost
per turn must stay within the configured total deadline. The shadow phase exists to
measure total latency and cost, routing accuracy, and the rate of high-confidence
mistakes against real traffic before any later phase is allowed to act on a route.

Enable it explicitly with the ``SUPERFAST_ENABLED`` environment variable. The
decision model itself is installed out of band and is not bundled here; the gate
talks to it over plain HTTP using ``httpx``, which is already a core dependency.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from typing import Any

import httpx
from langchain.agents.middleware import AgentMiddleware

from deerflow.utils.messages import (
    ORIGINAL_USER_CONTENT_KEY,
    get_original_user_content_text,
    is_real_user_message,
    message_content_to_text,
)

logger = logging.getLogger(__name__)

# Environment-driven configuration. Everything is off by default so a user who
# does nothing sees the exact current behavior.
_ENABLED_ENV = "SUPERFAST_ENABLED"
_ENDPOINT_ENV = "SUPERFAST_ENDPOINT"
_MODEL_ENV = "SUPERFAST_MODEL"
_TIMEOUT_MS_ENV = "SUPERFAST_TIMEOUT_MS"

DEFAULT_ENDPOINT = "http://localhost:8000/v1/systemone"
DEFAULT_MODEL = "von-1.2.0"
# A warm single forward pass is tens to low-hundreds of ms; the first call also
# loads the encoder. A 150 ms budget sat inside that range and left a correctly
# installed gate silently inert, so the default sits above it.
DEFAULT_TIMEOUT_MS = 1000

# Bounds on what leaves the process. The classifier is given a small, capped slice
# of recent conversation so the "answerable from context" question has something
# real to reason over, while the total request body stays bounded.
MAX_CONTEXT_MESSAGES = 6
MAX_MESSAGE_CHARS = 800
MAX_PAYLOAD_CHARS = 8000

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
    agent loop. ``httpx``'s own timeout bounds each network phase; the surrounding
    ``asyncio.wait_for`` bounds the whole call so a response that is slow across
    several phases can never exceed the total deadline.
    """
    body = {"model": _model(), "state": state, "questions": questions}
    total = _timeout_seconds()
    try:
        async with httpx.AsyncClient(timeout=total) as client:
            response = await asyncio.wait_for(
                client.post(_endpoint(), json=body, headers={"Accept": "application/json"}),
                timeout=total,
            )
    except asyncio.TimeoutError:
        logger.debug("superfast gate total deadline exceeded (fail-open)")
        return None
    except Exception:
        # Any transport error (connection refused, DNS, reset) fails open.
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


def _message_role(message: Any) -> str | None:
    if isinstance(message, dict):
        role = message.get("type") or message.get("role")
    else:
        role = getattr(message, "type", None)
    if role == "user":
        return "human"
    return role if isinstance(role, str) else None


def _message_text(message: Any) -> str:
    """Return the text of a message, preferring the pre-middleware user text.

    For a real user message this reads ``original_user_content`` when present, so
    the classifier sees exactly what the user typed rather than the transport
    wrappers and reminder blocks the middleware layered on top. User-authored
    ``<system-reminder>`` tags are therefore preserved, not stripped.
    """
    if isinstance(message, dict):
        content = message.get("content")
        additional = message.get("additional_kwargs")
    else:
        content = getattr(message, "content", "")
        additional = getattr(message, "additional_kwargs", None)
    if isinstance(additional, dict) and isinstance(additional.get(ORIGINAL_USER_CONTENT_KEY), str):
        return get_original_user_content_text(content, additional)
    return message_content_to_text(content)


def _build_classification_context(state: Any) -> str:
    """Build a bounded classification context from recent real messages.

    The context is the most recent few real turns (framework-injected hidden
    messages and summarization markers are excluded), each truncated, rendered as
    ``role: text`` lines, with the current request last. The whole string is
    capped so the request body stays bounded. This gives the "answerable from
    context" question a real conversation to reason over instead of a single
    message.
    """
    messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
    if not messages:
        return ""
    recent: list[str] = []
    for message in reversed(messages):
        if len(recent) >= MAX_CONTEXT_MESSAGES:
            break
        # Only real user turns and assistant turns carry useful context; skip
        # framework-injected hidden human messages and summary markers.
        if _message_role(message) == "human" and not is_real_user_message(message):
            continue
        text = _message_text(message).strip()
        if not text:
            continue
        if len(text) > MAX_MESSAGE_CHARS:
            text = text[:MAX_MESSAGE_CHARS] + "…"
        role = "user" if _message_role(message) == "human" else _message_role(message)
        recent.append(f"{role}: {text}")
    recent.reverse()
    if not recent:
        return ""
    context = "\n".join(recent)
    if len(context) > MAX_PAYLOAD_CHARS:
        context = context[-MAX_PAYLOAD_CHARS:]
    return context


async def classify_turn(context: str) -> tuple[str, int] | None:
    """Classify one turn through the gate.

    Returns ``(route, latency_ms)`` when the backend produced answers, or ``None``
    when the context is empty or the gate is unavailable (fail-open).
    """
    if not context.strip():
        return None
    started = time.monotonic()
    answers = await query_system_one(context, TURN_QUESTIONS)
    latency_ms = int((time.monotonic() - started) * 1000)
    if answers is None:
        return None
    return derive_route(answers), latency_ms


class SuperfastDecisionGateMiddleware(AgentMiddleware):
    """Shadow-only observer that classifies the incoming turn and logs the route.

    Registered at the front of the lead-agent middleware chain. On the async path
    it builds a bounded context from the recent real conversation, applies the
    configured PII boundary, asks the decision backend the three typed questions,
    and logs the recommended route and latency through the project logger. It
    never returns state updates, never skips the model call, and never changes
    routing. When the gate is disabled or unavailable it does nothing.

    The shadow classifier needs an HTTP round-trip and runs only on the async
    path, where the production gateway lives. The synchronous ``before_model``
    hook is a deliberate no-op so synchronous graphs (for example
    ``DeerFlowClient.stream()``) never raise and never block the event loop.
    """

    def __init__(self, pii_redaction_config: Any = None) -> None:
        super().__init__()
        # The same PiiRedactionConfig the model-call wrapper uses, so the text
        # sent to the decision service is redacted identically to the text the
        # model sees. ``None`` (or a disabled config) leaves text unchanged.
        self._pii_redaction_config = pii_redaction_config

    @staticmethod
    def enabled() -> bool:
        """Whether the gate should be installed for this process."""
        return is_enabled()

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Synchronous counterpart: a deliberate no-op that fails open.

        LangChain's agent factory registers the ``before_model`` node with a
        ``None`` sync handler when only ``abefore_model`` is overridden, which
        makes a synchronous run raise instead of responding. Providing this
        no-op sync hook keeps the gate installed uniformly across sync and async
        graphs while making synchronous runs behave exactly as if the gate were
        absent: it never classifies, never issues the HTTP round-trip, and never
        raises.
        """
        return None

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if not is_enabled():
            return None
        context = _build_classification_context(state)
        if not context:
            return None
        # Apply the configured PII boundary before the context leaves for the
        # decision service. The model-call redaction wrapper runs later, so the
        # gate must redact its own request; if redaction fails, skip the request
        # entirely rather than send unredacted protected identifiers (fail-open).
        try:
            from deerflow.agents.middlewares.pii_redaction_middleware import redact_text

            safe_context = redact_text(context, self._pii_redaction_config)
        except Exception:
            logger.debug("superfast gate redaction failed (fail-open, request skipped)")
            return None
        if not safe_context or not safe_context.strip():
            return None
        result = await classify_turn(safe_context)
        if result is None:
            return None
        route, latency_ms = result
        logger.info("superfast decision gate (shadow): route=%s latency_ms=%s", route, latency_ms)
        return None

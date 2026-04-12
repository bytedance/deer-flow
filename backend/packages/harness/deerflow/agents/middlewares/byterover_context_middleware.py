"""Middleware for hidden ByteRover context injection and curation."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.message_utils import (
    extract_message_text,
    filter_messages_for_terminal_conversation,
    strip_upload_block,
)
from deerflow.agents.thread_state import ThreadState
from deerflow.config.byterover_config import get_byterover_config

logger = logging.getLogger(__name__)

_WARNED_OPERATIONAL_FAILURES: set[str] = set()
_BRV_CONTEXT_PREFIX = "**MUST READ: CONTEXT KNOWLEDGE ADDITION**:"
_BRV_CONTEXT_BLOCK_RE = re.compile(
    r"\n*(?:"
    r"<(?P<tag>MUST_REFER_AS_CONTEXT|byterover_knowledge_context)>[\s\S]*?</(?P=tag)>"
    r"|"
    r"\*\*MUST READ: CONTEXT KNOWLEDGE ADDITION\*\*:[\s\S]*$"
    r")\n*",
    re.IGNORECASE,
)


def _preview_for_log(text: str, *, limit: int = 240) -> str:
    """Return a compact single-line preview suitable for structured logs."""
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _warn_once(key: str, message: str, *args: Any) -> None:
    """Emit a warning once per operational failure class to avoid log spam."""
    if key in _WARNED_OPERATIONAL_FAILURES:
        return

    _WARNED_OPERATIONAL_FAILURES.add(key)
    logger.warning(message, *args)


def _run_brv_query(user_text: str) -> str | None:
    """Run `brv query` and return the trimmed stdout payload."""
    cfg = get_byterover_config()
    resolved_cwd = cfg.resolved_cwd
    try:
        result = subprocess.run(
            ["brv", "query", user_text],
            capture_output=True,
            text=True,
            timeout=cfg.query_timeout,
            cwd=resolved_cwd,
        )
        if result.returncode != 0:
            _warn_once(
                f"query:exit:{result.returncode}",
                "ByteRover query failed with exit code %s | cwd=%s | stderr_preview=%s",
                result.returncode,
                resolved_cwd,
                _preview_for_log(result.stderr or "<empty>"),
            )
            return None
        return result.stdout.strip() or None
    except FileNotFoundError:
        _warn_once(
            "query:missing-command",
            "ByteRover query command is unavailable | cwd=%s | executable=brv",
            resolved_cwd,
        )
        return None
    except subprocess.TimeoutExpired as exc:
        _warn_once(
            "query:timeout",
            "ByteRover query timed out after %ss | cwd=%s | stderr_preview=%s",
            cfg.query_timeout,
            resolved_cwd,
            _preview_for_log(str(exc.stderr or "<empty>")),
        )
        return None
    except Exception as exc:
        _warn_once(
            "query:unexpected",
            "ByteRover query failed unexpectedly | cwd=%s | error=%s",
            resolved_cwd,
            exc.__class__.__name__,
        )
        logger.debug("brv query failed", exc_info=True)
        return None


def _launch_brv_curate(user_text: str, agent_text: str) -> None:
    """Trigger detached `brv curate` and wait for the launcher to finish."""
    cfg = get_byterover_config()
    resolved_cwd = cfg.resolved_cwd
    context = f"User: {user_text}\nAgent: {agent_text}"

    try:
        result = subprocess.run(
            ["brv", "curate", "--detach", context],
            capture_output=True,
            text=True,
            cwd=resolved_cwd,
            timeout=cfg.curate_timeout,
        )
        if result.returncode != 0:
            _warn_once(
                f"curate:exit:{result.returncode}",
                "ByteRover curate failed with exit code %s | cwd=%s | stderr_preview=%s",
                result.returncode,
                resolved_cwd,
                _preview_for_log(result.stderr or "<empty>"),
            )
    except FileNotFoundError:
        _warn_once(
            "curate:missing-command",
            "ByteRover curate command is unavailable | cwd=%s | executable=brv",
            resolved_cwd,
        )
        return
    except subprocess.TimeoutExpired as exc:
        _warn_once(
            "curate:timeout",
            "ByteRover curate timed out after %ss | cwd=%s | stderr_preview=%s",
            cfg.curate_timeout,
            resolved_cwd,
            _preview_for_log(str(exc.stderr or "<empty>")),
        )
    except Exception as exc:
        _warn_once(
            "curate:unexpected",
            "ByteRover curate failed unexpectedly | cwd=%s | error=%s",
            resolved_cwd,
            exc.__class__.__name__,
        )
        logger.debug("brv curate failed", exc_info=True)


def _strip_brv_context_block(text: str) -> str:
    """Remove a previously injected ByteRover context block."""
    return _BRV_CONTEXT_BLOCK_RE.sub("", text).strip()


def _prepare_brv_query_text(message: Any) -> str:
    """Build a clean ByteRover query from the latest human turn."""
    text = extract_message_text(message)
    text = strip_upload_block(text)
    text = _strip_brv_context_block(text)
    return text.strip()


def _build_brv_context_block(brv_result: str) -> str:
    """Wrap ByteRover output in an explicit context-only prompt addition."""
    return (
        f"{_BRV_CONTEXT_PREFIX}\n"
        "Trusted ByteRover context for the immediately preceding user message.\n"
        "Use this context before external search or assumptions.\n\n"
        f"{brv_result}"
    )


def _message_has_brv_context(message: Any) -> bool:
    """Check whether a message already includes ByteRover context."""
    return bool(_BRV_CONTEXT_BLOCK_RE.search(extract_message_text(message)))


def _inject_brv_context_message(messages: list[Any], brv_result: str) -> list[Any] | None:
    """Clone request messages and insert a transient context message after the latest user turn."""
    if any(_message_has_brv_context(message) for message in messages):
        return None

    context_message = HumanMessage(content=_build_brv_context_block(brv_result))
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if getattr(message, "type", None) != "human":
            continue

        patched_messages = list(messages)
        patched_messages.insert(index + 1, context_message)
        return patched_messages

    return None


def _extract_latest_human_query(state: ThreadState) -> str | None:
    """Extract the latest human turn for ByteRover lookup."""
    messages = list(state.get("messages", []))
    if not messages:
        return None

    last_message = messages[-1]
    if getattr(last_message, "type", None) != "human":
        return None

    user_text = _prepare_brv_query_text(last_message)
    return user_text or None


def _extract_curation_payload(
    state: ThreadState,
) -> tuple[str, str] | None:
    """Extract the final raw user turn and terminal assistant reply."""
    messages = state.get("messages", [])
    if not messages:
        return None

    filtered_messages = filter_messages_for_terminal_conversation(messages)
    user_messages = [msg for msg in filtered_messages if getattr(msg, "type", None) == "human"]
    assistant_messages = [msg for msg in filtered_messages if getattr(msg, "type", None) == "ai"]

    if not user_messages or not assistant_messages:
        return None

    raw_user = _strip_brv_context_block(extract_message_text(user_messages[-1]))
    agent_text = extract_message_text(assistant_messages[-1]).strip()
    if not raw_user or not agent_text:
        return None

    return raw_user, agent_text


def _clear_byterover_context_update(state: ThreadState) -> dict[str, None] | None:
    """Clear per-turn ByteRover state after the agent finishes."""
    if state.get("byterover_context") is None:
        return None
    return {"byterover_context": None}


class ByteRoverContextMiddleware(AgentMiddleware[ThreadState]):
    """Inject hidden ByteRover context into model calls and curate final turns."""

    state_schema = ThreadState

    @override
    def before_agent(self, state: ThreadState, runtime: Runtime) -> dict | None:
        """Query ByteRover once and keep the result in ephemeral state."""
        del runtime

        cfg = get_byterover_config()
        if not cfg.enabled:
            return None

        user_text = _extract_latest_human_query(state)
        if not user_text:
            return None

        brv_result = _run_brv_query(user_text)
        if not brv_result:
            logger.info(
                "ByteRover query returned no context | query_preview=%s",
                _preview_for_log(user_text),
            )
            return None

        logger.info(
            "ByteRover query succeeded | query_preview=%s | context_preview=%s | context_chars=%s",
            _preview_for_log(user_text),
            _preview_for_log(brv_result),
            len(brv_result),
        )

        return {"byterover_context": brv_result}

    @override
    async def abefore_agent(
        self, state: ThreadState, runtime: Runtime
    ) -> dict | None:
        """Async ByteRover lookup for web-server execution paths."""
        del runtime

        cfg = get_byterover_config()
        if not cfg.enabled:
            return None

        user_text = _extract_latest_human_query(state)
        if not user_text:
            return None

        brv_result = await asyncio.to_thread(_run_brv_query, user_text)
        if not brv_result:
            logger.info(
                "ByteRover query returned no context | query_preview=%s",
                _preview_for_log(user_text),
            )
            return None

        logger.info(
            "ByteRover query succeeded | query_preview=%s | context_preview=%s | context_chars=%s",
            _preview_for_log(user_text),
            _preview_for_log(brv_result),
            len(brv_result),
        )

        return {"byterover_context": brv_result}

    def _apply_byterover_context(self, request: ModelRequest) -> ModelRequest:
        """Clone the model-facing request and insert hidden context after the latest user turn."""
        cfg = get_byterover_config()
        if not cfg.enabled:
            return request

        brv_context = request.state.get("byterover_context")
        if not isinstance(brv_context, str) or not brv_context.strip():
            return request

        patched_messages = _inject_brv_context_message(request.messages, brv_context)
        if patched_messages is None:
            return request

        latest_user_message = next(
            (
                message
                for message in reversed(request.messages)
                if getattr(message, "type", None) == "human"
            ),
            None,
        )
        latest_user_preview = (
            _preview_for_log(extract_message_text(latest_user_message))
            if latest_user_message is not None
            else ""
        )
        injected_context_message = next(
            (
                message
                for message in reversed(patched_messages)
                if getattr(message, "type", None) == "human" and _message_has_brv_context(message)
            ),
            None,
        )
        injected_message_preview = (
            _preview_for_log(extract_message_text(injected_context_message))
            if injected_context_message is not None
            else ""
        )
        logger.info(
            "ByteRover context injected into model request | user_preview=%s | context_preview=%s | original_message_count=%s | patched_message_count=%s",
            latest_user_preview,
            injected_message_preview,
            len(request.messages),
            len(patched_messages),
        )

        return request.override(messages=patched_messages)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        """Inject hidden ByteRover context without mutating persisted history."""
        return handler(self._apply_byterover_context(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        """Async version of request-local ByteRover context injection."""
        return await handler(self._apply_byterover_context(request))

    @override
    def after_agent(self, state: ThreadState, runtime: Runtime) -> dict | None:
        """Curate the raw final user/assistant exchange."""
        del runtime

        cfg = get_byterover_config()
        cleanup = _clear_byterover_context_update(state)
        if not cfg.enabled:
            return cleanup

        payload = _extract_curation_payload(state)
        if payload is None:
            return cleanup

        raw_user, agent_text = payload
        _launch_brv_curate(raw_user, agent_text)

        return cleanup

    @override
    async def aafter_agent(
        self, state: ThreadState, runtime: Runtime
    ) -> dict | None:
        """Async curation hook that avoids blocking the LangGraph event loop."""
        del runtime

        cfg = get_byterover_config()
        cleanup = _clear_byterover_context_update(state)
        if not cfg.enabled:
            return cleanup

        payload = _extract_curation_payload(state)
        if payload is None:
            return cleanup

        raw_user, agent_text = payload
        await asyncio.to_thread(_launch_brv_curate, raw_user, agent_text)
        return cleanup

"""Mem0 integration adapter — additive, feature-flagged long-term memory.

This module is strictly additive and gated behind the ``MEM0_ENABLED``
environment variable. With the flag unset (default), every exported
function short-circuits and the ``mem0`` package is never imported.

The adapter is deliberately confined to the ``deerflow-harness`` layer
and imports only from ``mem0``, ``langchain``, ``langgraph`` and the
standard library — the ``deerflow → app`` import firewall is preserved.

Exports:
    - ``is_mem0_enabled`` — env-var check
    - ``maybe_write_to_mem0`` — fire-and-forget Memory.add on a daemon thread
    - ``Mem0ReadMiddleware`` — before_model middleware injecting <mem0_memory>
    - ``_get_memory_instance`` — cached Memory() factory (tests patch this)
"""

from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

_TRUTHY = {"1", "true", "yes", "on"}


def is_mem0_enabled() -> bool:
    """Return True only when MEM0_ENABLED is a truthy environment value."""
    value = os.getenv("MEM0_ENABLED")
    if value is None:
        return False
    return value.strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# Cached Memory() factory — repo-local storage
# ---------------------------------------------------------------------------


def _repo_local_storage_root() -> Path:
    """Resolve the repo-local storage root under backend/.deer-flow/mem0/.

    The module lives at ``backend/packages/harness/deerflow/agents/memory/``;
    traverse five ``parents`` to land on ``backend/``.
    """
    return Path(__file__).resolve().parents[5] / ".deer-flow" / "mem0"


@lru_cache(maxsize=1)
def _get_memory_instance() -> Any:
    """Instantiate a Mem0 ``Memory`` with repo-local storage paths.

    Cached — subsequent calls return the same instance. The import of
    ``mem0`` is deferred to this function so the package is never
    imported when the feature flag is off.
    """
    from mem0 import Memory  # local import — gated by is_mem0_enabled()

    storage_root = _repo_local_storage_root()
    qdrant_path = storage_root / "qdrant"
    history_db_path = storage_root / "history.db"

    storage_root.mkdir(parents=True, exist_ok=True)
    qdrant_path.mkdir(parents=True, exist_ok=True)

    config = {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "deerflow_mem0",
                "path": str(qdrant_path),
            },
        },
        "history_db_path": str(history_db_path),
    }

    return Memory.from_config(config)


# ---------------------------------------------------------------------------
# Write side
# ---------------------------------------------------------------------------


def _message_to_mem0_dict(message: Any) -> dict | None:
    """Convert a LangChain message to Mem0's ``{"role", "content"}`` shape.

    Returns ``None`` for unsupported message types (tool calls, system, etc.).
    """
    msg_type = getattr(message, "type", None)
    if msg_type == "human":
        role = "user"
    elif msg_type == "ai":
        role = "assistant"
    else:
        return None

    content = getattr(message, "content", None)
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(part, str):
                parts.append(part)
        content = "\n".join(parts)
    if not isinstance(content, str):
        content = "" if content is None else str(content)

    return {"role": role, "content": content}


def maybe_write_to_mem0(
    messages: list[Any],
    *,
    user_id: str,
    agent_id: str | None,
    run_id: str | None,
) -> None:
    """Forward filtered conversation to Mem0 when the feature flag is on.

    Short-circuits immediately when the flag is off — no Memory instance
    is created, no ``mem0`` import runs. When the flag is on, the actual
    ``Memory.add`` call is dispatched on a daemon thread so the caller
    (agent loop) is never blocked by Mem0's LLM-side fact extraction.
    """
    if not is_mem0_enabled():
        return

    payload: list[dict] = []
    for msg in messages:
        converted = _message_to_mem0_dict(msg)
        if converted is not None:
            payload.append(converted)

    if not payload:
        return

    def _worker() -> None:
        try:
            memory = _get_memory_instance()
            memory.add(
                payload,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Mem0 write failed (swallowed): %s", exc)

    thread = threading.Thread(
        target=_worker,
        name="mem0-write",
        daemon=True,
    )
    thread.start()


# ---------------------------------------------------------------------------
# Read side
# ---------------------------------------------------------------------------


def _extract_latest_human_text(messages: list[Any]) -> str | None:
    """Return the text of the most recent HumanMessage in ``messages``."""
    for msg in reversed(messages):
        if getattr(msg, "type", None) != "human":
            continue
        content = getattr(msg, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                elif isinstance(part, str):
                    parts.append(part)
            return "\n".join(parts) if parts else None
        if content is not None:
            return str(content)
    return None


def _read_configurable() -> dict:
    try:
        cfg = get_config() or {}
    except Exception:
        return {}
    return cfg.get("configurable", {}) or {}


class Mem0ReadMiddlewareState(AgentState):
    """State schema alias — compatible with ``ThreadState``."""

    pass


class Mem0ReadMiddleware(AgentMiddleware[Mem0ReadMiddlewareState]):
    """Inject a ``<mem0_memory>`` SystemMessage recalled from Mem0 per turn.

    Only appended to the middleware chain when ``MEM0_ENABLED=1`` (see
    ``lead_agent.agent._build_middlewares``). With no recall hits or on
    any exception from Mem0, ``before_model`` returns ``None`` and the
    run proceeds with the unmodified message list.
    """

    state_schema = Mem0ReadMiddlewareState

    def __init__(self, agent_name: str | None = None) -> None:
        super().__init__()
        self._agent_name = agent_name

    def _resolve_user_id(self) -> str:
        configurable = _read_configurable()
        for key in ("mem0_user_id", "agent_name"):
            value = configurable.get(key)
            if isinstance(value, str) and value:
                return value
        if self._agent_name:
            return self._agent_name
        return "default"

    def before_model(
        self, state: Mem0ReadMiddlewareState, runtime: Runtime
    ) -> dict | None:
        try:
            messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
            query = _extract_latest_human_text(messages or [])
            if not query:
                return None

            user_id = self._resolve_user_id()
            memory = _get_memory_instance()
            response = memory.search(
                query=query,
                filters={"user_id": user_id},
                limit=5,
            )

            if isinstance(response, dict):
                results = response.get("results") or []
            elif isinstance(response, list):
                results = response
            else:
                results = []

            if not results:
                return None

            bullets: list[str] = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                text = item.get("memory")
                if isinstance(text, str) and text.strip():
                    bullets.append(f"- {text.strip()}")

            if not bullets:
                return None

            block = "<mem0_memory>\n" + "\n".join(bullets) + "\n</mem0_memory>"
            return {"messages": [SystemMessage(content=block)]}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Mem0 read failed (swallowed): %s", exc)
            return None


# Explicit exports — tests import these by name.
__all__ = [
    "Mem0ReadMiddleware",
    "_get_memory_instance",
    "is_mem0_enabled",
    "maybe_write_to_mem0",
]


# Re-exported for tests that patch ``get_config`` on this module.
# (``from langgraph.config import get_config`` is already imported above.)
_ = HumanMessage  # keep symbol available for future use

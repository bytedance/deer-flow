"""Honcho memory backend — user-model memory via a Honcho (v3) instance.

Positioning (upstream RFC #1898): Honcho covers the user-dimension of memory —
long-term user modeling, preferences, cross-session working representation —
complementing project/task-oriented backends. Ingestion is cheap (plain message
writes); Honcho's own server-side deriver performs fact extraction and
representation building asynchronously, so this backend makes **no LLM calls**.

Multi-user isolation: every operation resolves a workspace from ``user_id``
(``workspace_overrides`` exact match, else ``workspace_prefix + _stable_id``).
``_stable_id`` appends an 8-hex-char SHA-256 suffix to ``sanitize_id``'s output
because ``sanitize_id`` alone is lossy -- it collapses every run of non
``[a-zA-Z0-9_-]`` characters to a single ``-``, so distinct raw ids can collide
(``"user.name@x"`` and ``"user-name@x"`` both sanitize to ``"user-name-x"``).
Reusing the lossy form bare for the default (non-override) workspace/peer
derivation would silently merge two different people's memory into one
workspace; the hash suffix makes the default path collision-resistant while
staying readable. ``workspace_overrides`` / ``user_peer_overrides`` match on
the raw, un-sanitized key and are unaffected. Honcho scopes all queries to one
workspace, so under the default one-workspace-per-user derivation users cannot
see each other's memory by construction. A ``workspace_overrides`` entry
shared across users deliberately shares that workspace — ``get_context`` /
``get_memory`` stay peer-scoped there, but ``search`` uses Honcho's
workspace-scoped ``/search`` (no peer filter), so those users share one
search index. A missing ``user_id`` fails closed: the call becomes a no-op /
empty read, never a shared fallback workspace. Session ids reuse the same derivation
(``df-`` + ``_stable_id(thread_id)``) — bare ``sanitize_id`` would merge
threads like ``"t.1"`` and ``"t-1"`` into one Honcho session.

Portability golden rule: the only ``from deerflow`` import is the contract line
below. Everything else arrives via ``backend_config``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, ClassVar, Literal

from pydantic import PrivateAttr

# ABC contract -- the ONE allowed `from deerflow` import in this backend folder.
from deerflow.agents.memory.manager import MemoryManager, MemoryManagerError

from .client import HonchoClient
from .config import HonchoConfig, sanitize_id

logger = logging.getLogger(__name__)

_UTC_NOW_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.UTC).strftime(_UTC_NOW_FORMAT)


def _content_to_text(content: Any) -> str:
    """Normalize LangChain message content (str or content-block list) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content or "")


def _stable_id(raw: str) -> str:
    """Readable-but-collision-resistant id for the default (non-override) path.

    ``sanitize_id`` alone is lossy (every run of disallowed characters
    collapses to one ``-``), so two distinct raw ids can sanitize to the same
    string. Appending an 8-hex-char SHA-256 suffix of the *original* raw id
    keeps the result readable while making distinct inputs resolve to
    distinct outputs. The digest is always 8 hex characters, so the result is
    never empty even when ``sanitize_id`` strips a degenerate raw id (e.g.
    ``"!!!"``) down to ``""``.
    """
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    readable = sanitize_id(raw)[:48].rstrip("-")
    return f"{readable}-{digest}" if readable else digest


class HonchoMemoryManager(MemoryManager):
    """MemoryManager backed by a Honcho v3 instance (self-hosted or hosted)."""

    _config: HonchoConfig = PrivateAttr(default=None)
    _client: Any = PrivateAttr(default=None)

    supports_search: ClassVar[bool] = True
    # Honcho's server-side deriver extracts facts/representation from add()
    # writes asynchronously; this backend implements no fact CRUD hooks
    # (create_fact/delete_fact/update_fact are unsupported), so tool mode
    # must retain passive writes (MemoryMiddleware -> add()) to keep feeding
    # the deriver, while search() supplies the query-aware retrieval tool
    # mode expects. Mirrors mem0_manager.py's identical rationale.
    requires_passive_writes_in_tool_mode: ClassVar[bool] = True

    def model_post_init(self, __context: Any) -> None:
        self._config = HonchoConfig.from_backend_config(self.backend_config)
        self._client = HonchoClient(self._config)

    @classmethod
    def from_config(
        cls,
        backend_config: dict[str, Any] | None = None,
        *,
        mode: Literal["middleware", "tool"] = "middleware",
        **host_hooks: Any,
    ) -> HonchoMemoryManager:
        """Config errors (bad URL/insecure key) raise here — fail fast at startup.

        Connectivity is deliberately NOT probed: a temporarily unreachable Honcho
        must not block Gateway startup; reads degrade per ``failure_policy.read``.
        """
        return cls(backend_config=backend_config, mode=mode)

    # ── identity resolution (fail closed) ────────────────────────────────
    def _workspace(self, user_id: str | None) -> str | None:
        if not user_id:
            return None
        override = self._config.workspace_overrides.get(user_id)
        if override:
            return override
        return f"{self._config.workspace_prefix}{_stable_id(user_id)}"

    def _user_peer(self, user_id: str) -> str:
        return self._config.user_peer_overrides.get(user_id) or _stable_id(user_id)

    # ── recall policy gate (get_context / search / get_memory) ───────────
    def _read_or_fallback(self, fallback: Any, fn: Any) -> Any:
        """Single ``failure_policy.read`` gate for every recall path, mirroring
        mem0's helper of the same name: fail-open (default) logs and returns
        ``fallback``; ``fail_closed`` wraps into ``MemoryManagerError``. The
        broad ``except Exception`` is the containment boundary — no client
        exception may escape into ``MemoryMiddleware.after_agent``."""
        try:
            return fn()
        except MemoryManagerError:
            raise
        except Exception as exc:
            if self._config.read_fail_closed:
                raise MemoryManagerError(f"honcho memory recall failed: {exc}") from exc
            logger.warning("honcho memory: recall failed (fail-open): %s", exc)
            return fallback

    # ── Tier 1: write ────────────────────────────────────────────────────
    def add(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        workspace = self._workspace(user_id)
        if workspace is None or not user_id:
            logger.debug("honcho memory: no resolvable user for thread %s; skipping write", thread_id)
            return
        user_peer = self._user_peer(user_id)
        assistant_peer = self._config.assistant_peer
        outgoing: list[dict[str, str]] = []
        for message in messages or []:
            msg_type = getattr(message, "type", None)
            text = _content_to_text(getattr(message, "content", "")).strip()
            if not text:
                continue
            if msg_type == "human":
                outgoing.append({"peer_id": user_peer, "content": text[: self._config.message_char_limit]})
            elif msg_type in ("ai", "AIMessageChunk"):
                outgoing.append({"peer_id": assistant_peer, "content": text[: self._config.message_char_limit]})
        if not outgoing:
            return
        session_id = f"df-{_stable_id(thread_id)}"
        try:
            self._client.get_or_create_peer(workspace, user_peer)
            self._client.get_or_create_peer(workspace, assistant_peer)
            self._client.get_or_create_session(workspace, session_id)
            self._client.set_session_peers(workspace, session_id, [user_peer, assistant_peer])
            self._client.add_messages(workspace, session_id, outgoing)
        except MemoryManagerError:
            raise
        except Exception as exc:
            logger.warning("honcho memory: write failed for thread %s: %s", thread_id, exc)

    # ── Tier 1: read ─────────────────────────────────────────────────────
    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        workspace = self._workspace(user_id)
        if workspace is None or not user_id:
            return ""
        representation = self._read_or_fallback("", lambda: self._client.working_representation(workspace, self._user_peer(user_id), max_conclusions=25))
        return representation.strip()[: self._config.max_injection_chars]

    # ── Tier 2 ───────────────────────────────────────────────────────────
    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        workspace = self._workspace(user_id)
        if workspace is None:
            return []
        results = self._read_or_fallback([], lambda: self._client.search(workspace, query, limit=top_k))
        return [
            {
                "content": item.get("content", ""),
                "category": category or "memory",
                "session_id": item.get("session_id"),
                "peer_id": item.get("peer_id"),
                "created_at": item.get("created_at"),
            }
            for item in results
            if isinstance(item, dict)
        ][:top_k]

    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Minimal DeerMem-shape view: representation as the work-context summary.

        Honcho has no DeerMem-style fact CRUD; the gateway fills missing fields
        with defaults (same contract as the noop backend's ``{"facts": []}``).
        """
        empty = {"facts": [], "lastUpdated": _now_iso(), "user": {}, "history": {}}
        workspace = self._workspace(user_id)
        if workspace is None or not user_id:
            return empty
        representation = self._read_or_fallback(None, lambda: self._client.working_representation(workspace, self._user_peer(user_id), max_conclusions=25))
        if representation is None:  # fail-open fallback: keep the noop-shaped doc
            return empty
        now = _now_iso()
        return {
            "facts": [],
            "lastUpdated": now,
            "user": {"workContext": {"summary": representation.strip()[: self._config.max_injection_chars], "updatedAt": now}},
            "history": {},
        }

    def shutdown_flush(self, timeout: float) -> bool:
        """Writes are synchronous per-call; nothing is buffered locally."""
        return True

    def close(self) -> None:
        """Release the HTTP client (gateway shutdown hook)."""
        self._client.close()

    # ── async offload (blocking-io gate: never run httpx on the event loop) ──
    async def aadd(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        await asyncio.to_thread(self.add, thread_id, messages, agent_name=agent_name, user_id=user_id, trace_id=trace_id)

    async def aget_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        return await asyncio.to_thread(self.get_context, user_id, agent_name=agent_name, thread_id=thread_id)

    async def asearch(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.search, query, top_k, user_id=user_id, agent_name=agent_name, category=category)

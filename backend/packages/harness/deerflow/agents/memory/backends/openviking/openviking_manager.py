"""OpenViking memory backend built on the maintained LangChain adapters."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import threading
import time
import weakref
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import PrivateAttr

from deerflow.agents.memory.manager import MemoryManager, MemoryManagerError

from .config import OpenVikingConfig
from .session import (
    _advanced_cursor,
    _canonical_peer_id,
    _captureable_messages,
    _matching_prefix_count,
    _memory_target_uris,
    _message_signature,
    _session_id,
    _string_list,
)

logger = logging.getLogger(__name__)


class OpenVikingMemoryManager(MemoryManager):
    """Single-user OpenViking backend using the official integration package.

    DeerFlow continues to choose when capture and recall occur. The official
    adapter owns SDK transport, message conversion, batching, commit retries,
    and retrieval behavior.
    """

    supports_search: ClassVar[bool] = True

    _config: OpenVikingConfig = PrivateAttr()
    _client: Any = PrivateAttr()
    _recorder: Any = PrivateAttr()
    _retriever: Any = PrivateAttr()
    _use_actor_peer: Any = PrivateAttr()
    _partial_write_error: type[Exception] = PrivateAttr()
    _should_keep_hidden_message: Any = PrivateAttr(default=None)
    _session_locks: weakref.WeakValueDictionary[str, threading.RLock] = PrivateAttr(default_factory=weakref.WeakValueDictionary)
    _session_locks_guard: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _lifecycle: threading.Condition = PrivateAttr(default_factory=threading.Condition)
    _active_operations: int = PrivateAttr(default=0)
    _closed: bool = PrivateAttr(default=False)
    _close_requested: bool = PrivateAttr(default=False)
    _resources_closed: bool = PrivateAttr(default=False)
    _resource_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    def model_post_init(self, __context: Any) -> None:
        self._config = OpenVikingConfig.from_backend_config(self.backend_config)
        integration = _load_official_integration()
        commit_policy = integration["OpenVikingCommitPolicy"](mode="always")
        self._recorder = integration["OpenVikingSessionRecorder"](
            url=self._config.base_url,
            api_key=self._config.api_key,
            timeout=self._config.timeout_seconds,
            # An explicit mapping disables the SDK's ovcli.conf header fallback.
            extra_headers={},
            commit_policy=commit_policy,
        )
        # The recorder owns one recovery-aware SDK client. Retrieval borrows the
        # same handle, so this backend has one connection pool and one owner.
        self._client = self._recorder.client
        self._retriever = integration["OpenVikingRetriever"](
            client=self._client,
            search_mode="find",
            limit=self._config.search_top_k,
            score_threshold=self._config.score_threshold,
            context_types=("memory",),
            content_mode=self._config.content_mode,
            max_content_chars=self._config.max_injection_chars,
        )
        self._use_actor_peer = integration["use_actor_peer"]
        self._partial_write_error = integration["OpenVikingPartialWriteError"]

    @classmethod
    def from_config(
        cls,
        backend_config: dict[str, Any] | None = None,
        *,
        mode: Literal["middleware", "tool"] = "middleware",
        **host_hooks: Any,
    ) -> OpenVikingMemoryManager:
        if mode != "middleware":
            raise ValueError("The OpenViking automatic-memory backend supports memory.mode='middleware' only; use OpenViking MCP for explicit model tools")
        instance = cls(backend_config=backend_config or {}, mode=mode)
        hidden_filter = host_hooks.get("should_keep_hidden_message")
        instance._should_keep_hidden_message = hidden_filter if callable(hidden_filter) else None
        return instance

    def add(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        del trace_id
        self._write_conversation(
            thread_id,
            messages,
            agent_name=agent_name,
            user_id=user_id,
        )

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> None:
        # Preserve DeerFlow's existing pre-compaction behavior. This backend
        # commits every accepted capture, so add_nowait needs no separate mode.
        self._write_conversation(
            thread_id,
            messages,
            agent_name=agent_name,
            user_id=user_id,
        )

    async def aadd(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        await asyncio.to_thread(
            self.add,
            thread_id,
            messages,
            agent_name=agent_name,
            user_id=user_id,
            trace_id=trace_id,
        )

    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        if not self._begin_operation():
            return ""
        try:
            peer_id = self._resolve_scope(user_id, agent_name)
            retriever = copy.copy(self._retriever)
            retriever.target_uri = _memory_target_uris(peer_id)
            if thread_id:
                retriever.search_mode = "search"
                retriever.session_id = _session_id(
                    self._config.owner_user_id,
                    peer_id,
                    thread_id,
                )
            try:
                with self._actor_peer_scope(peer_id):
                    documents = retriever.invoke(self._config.injection_query)
            except Exception:
                if self._config.read_failure_policy == "raise":
                    raise
                logger.warning(
                    "OpenViking context retrieval failed; continuing without injected memory",
                    exc_info=True,
                )
                return ""
            return _format_documents(
                documents,
                max_chars=self._config.max_injection_chars,
            )
        finally:
            self._end_operation()

    async def aget_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self.get_context,
            user_id,
            agent_name=agent_name,
            thread_id=thread_id,
        )

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        if not query.strip() or not self._begin_operation():
            return []
        try:
            peer_id = self._resolve_scope(user_id, agent_name)
            retriever = copy.copy(self._retriever)
            retriever.target_uri = _memory_target_uris(peer_id)
            retriever.search_mode = "find"
            retriever.session_id = None
            retriever.limit = max(1, min(int(top_k), 100))
            if category:
                retriever.filter = {
                    "op": "must",
                    "field": "category",
                    "conds": [category],
                }
            try:
                with self._actor_peer_scope(peer_id):
                    documents = retriever.invoke(query.strip())
            except Exception:
                if self._config.read_failure_policy == "raise":
                    raise
                logger.warning(
                    "OpenViking memory search failed; returning no results",
                    exc_info=True,
                )
                return []
            return [_document_to_fact(document) for document in documents]
        finally:
            self._end_operation()

    async def asearch(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.search,
            query,
            top_k,
            user_id=user_id,
            agent_name=agent_name,
            category=category,
        )

    def warm(self) -> bool | None:
        if not self._begin_operation():
            return False
        try:
            try:
                health = getattr(self._client, "health", None)
                healthy = bool(health()) if callable(health) else True
            except Exception:
                if self._config.startup_policy == "fail_fast":
                    raise
                logger.warning(
                    "OpenViking startup validation failed; memory will run in degraded mode",
                    exc_info=True,
                )
                return False
            if not healthy and self._config.startup_policy == "fail_fast":
                raise MemoryManagerError("OpenViking health check returned an unhealthy response")
            if not healthy:
                logger.warning("OpenViking health check returned unhealthy; memory will run in degraded mode")
            return healthy
        finally:
            self._end_operation()

    def shutdown_flush(self, timeout: float) -> bool:
        """Stop new work, drain accepted calls, and close owned resources."""

        deadline = time.monotonic() + max(0.0, timeout)
        with self._lifecycle:
            self._closed = True
            self._close_requested = True
            while self._active_operations:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._lifecycle.wait(remaining)
        self._close_resources()
        return True

    def close(self) -> None:
        """Request idempotent closure after any active operation finishes."""

        with self._lifecycle:
            self._closed = True
            self._close_requested = True
            can_close = self._active_operations == 0
        if can_close:
            self._close_resources()

    def _write_conversation(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None,
        user_id: str | None,
    ) -> None:
        if not self._begin_operation():
            logger.warning("OpenViking write ignored after backend shutdown")
            return
        try:
            if not thread_id:
                raise ValueError("OpenViking memory write requires thread_id")
            peer_id = self._resolve_scope(user_id, agent_name)
            session_id = _session_id(
                self._config.owner_user_id,
                peer_id,
                thread_id,
            )
            with self._session_lock(session_id):
                self._capture_locked(
                    session_id,
                    peer_id,
                    _captureable_messages(
                        messages,
                        self._should_keep_hidden_message,
                    ),
                )
        finally:
            self._end_operation()

    def _capture_locked(
        self,
        session_id: str,
        peer_id: str,
        messages: list[Any],
    ) -> None:
        state = self._load_cursor(session_id)
        signatures = [_message_signature(message) for message in messages]

        if state.get("commit_pending"):
            try:
                with self._actor_peer_scope(peer_id):
                    self._recorder.flush(session_id)
            except Exception as exc:
                self._handle_write_error(
                    exc,
                    "OpenViking pending commit retry failed; preserving capture cursor",
                    session_id,
                )
                return
            state = {**state, "commit_pending": False}
            self._save_cursor(session_id, state)

        start = _matching_prefix_count(state, signatures)
        append_only = start is not None
        if append_only:
            pending = messages[start:]
            pending_signatures = signatures[start:]
        else:
            submitted = set(_string_list(state.get("submitted_signatures")))
            pending_pairs = [(message, signature) for message, signature in zip(messages, signatures, strict=True) if signature not in submitted]
            pending = [message for message, _ in pending_pairs]
            pending_signatures = [signature for _, signature in pending_pairs]

        if not pending:
            self._save_cursor(
                session_id,
                _advanced_cursor(
                    state,
                    signatures,
                    [],
                    max_seen=self._config.max_seen_message_ids,
                    commit_pending=False,
                ),
            )
            return

        try:
            with self._actor_peer_scope(peer_id):
                self._recorder.record(
                    session_id,
                    pending,
                    peer_id=peer_id,
                )
        except self._partial_write_error as exc:
            consumed = max(
                0,
                min(
                    len(pending_signatures),
                    int(getattr(exc, "input_messages_consumed", 0)),
                ),
            )
            confirmed = pending_signatures[:consumed]
            commit_pending = bool(getattr(exc, "commit_pending", False))
            if confirmed or commit_pending:
                confirmed_prefix = signatures[: int(start or 0) + consumed] if append_only else None
                self._save_cursor(
                    session_id,
                    _advanced_cursor(
                        state,
                        confirmed_prefix,
                        confirmed,
                        max_seen=self._config.max_seen_message_ids,
                        commit_pending=commit_pending,
                    ),
                )
            self._handle_write_error(
                exc,
                "OpenViking partially recorded a conversation; confirmed progress was preserved",
                session_id,
            )
            return
        except Exception as exc:
            self._handle_write_error(
                exc,
                "OpenViking conversation recording failed; capture cursor was not advanced",
                session_id,
            )
            return

        self._save_cursor(
            session_id,
            _advanced_cursor(
                state,
                signatures,
                pending_signatures,
                max_seen=self._config.max_seen_message_ids,
                commit_pending=False,
            ),
        )

    def _resolve_scope(
        self,
        user_id: str | None,
        agent_name: str | None,
    ) -> str:
        resolved_user = str(user_id or "default")
        if resolved_user != self._config.owner_user_id:
            raise MemoryManagerError(f"OpenViking USER API key is bound to DeerFlow owner_user_id {self._config.owner_user_id!r}, but this request belongs to {resolved_user!r}. Refusing to share one credential across users.")
        return _canonical_peer_id(agent_name, self._config.default_peer_id)

    def _actor_peer_scope(
        self,
        peer_id: str,
    ) -> AbstractContextManager[None]:
        return self._use_actor_peer(peer_id)

    def _session_lock(self, session_id: str) -> threading.RLock:
        with self._session_locks_guard:
            return self._session_locks.setdefault(
                session_id,
                threading.RLock(),
            )

    def _begin_operation(self) -> bool:
        with self._lifecycle:
            if self._closed:
                return False
            self._active_operations += 1
            return True

    def _end_operation(self) -> None:
        should_close = False
        with self._lifecycle:
            self._active_operations -= 1
            if self._active_operations == 0:
                self._lifecycle.notify_all()
                should_close = self._close_requested
        if should_close:
            try:
                self._close_resources()
            except Exception:
                logger.exception("Failed to close OpenViking memory resources")

    def _close_resources(self) -> None:
        with self._resource_lock:
            if self._resources_closed:
                return
            self._recorder.close()
            self._resources_closed = True

    def _state_path(self, session_id: str) -> Path:
        root = Path(self._config.storage_path or ".") / "openviking" / "sessions"
        return root / f"{session_id}.json"

    def _load_cursor(self, session_id: str) -> dict[str, Any]:
        path = self._state_path(session_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise MemoryManagerError(f"OpenViking capture cursor is unreadable; refusing unsafe replay (session={session_id})") from exc
        if not isinstance(value, dict):
            raise MemoryManagerError(f"OpenViking capture cursor is invalid; refusing unsafe replay (session={session_id})")
        return value

    def _save_cursor(self, session_id: str, state: dict[str, Any]) -> None:
        path = self._state_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            temp_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp_path, path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logger.debug(
                    "Failed to remove OpenViking cursor temp file: %s",
                    temp_path,
                    exc_info=True,
                )

    def _handle_write_error(
        self,
        exc: Exception,
        message: str,
        session_id: str,
    ) -> None:
        detail = f"{message} (session={session_id})"
        if self._config.write_failure_policy == "raise":
            raise MemoryManagerError(detail) from exc
        logger.error(detail, exc_info=True)


def _load_official_integration() -> dict[str, Any]:
    try:
        from langchain_openviking import (
            OpenVikingCommitPolicy,
            OpenVikingPartialWriteError,
            OpenVikingRetriever,
            OpenVikingSessionRecorder,
            has_request_actor_peer_support,
        )
        from langchain_openviking.actor_peer import use_actor_peer
    except ImportError as exc:
        raise ImportError("The OpenViking memory backend requires langchain-openviking==0.1.0. Install DeerFlow backend dependencies and retry.") from exc
    if not has_request_actor_peer_support():
        raise ImportError("The installed OpenViking SDK lacks request-scoped actor-peer support. Install openviking-sdk>=0.1.6,<0.2 and retry.")
    return {
        "OpenVikingCommitPolicy": OpenVikingCommitPolicy,
        "OpenVikingPartialWriteError": OpenVikingPartialWriteError,
        "OpenVikingRetriever": OpenVikingRetriever,
        "OpenVikingSessionRecorder": OpenVikingSessionRecorder,
        "use_actor_peer": use_actor_peer,
    }


def _format_documents(documents: list[Any], *, max_chars: int) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for document in documents:
        content = " ".join(str(getattr(document, "page_content", "") or "").split())
        key = content.casefold()
        if not content or key in seen:
            continue
        seen.add(key)
        metadata = getattr(document, "metadata", {}) or {}
        category = metadata.get("openviking_category") or "memory"
        line = f"- [{category}] {content}"
        candidate = "\n".join([*lines, line])
        if len(candidate) > max_chars:
            remaining = max_chars - len("\n".join(lines)) - (1 if lines else 0)
            if remaining > 16:
                lines.append(f"{line[: max(0, remaining - 1)]}…")
            break
        lines.append(line)
    return "\n".join(lines)


def _document_to_fact(document: Any) -> dict[str, Any]:
    metadata = getattr(document, "metadata", {}) or {}
    uri = metadata.get("openviking_uri") or metadata.get("source") or ""
    score = metadata.get("openviking_score")
    return {
        "id": uri,
        "content": str(getattr(document, "page_content", "") or ""),
        "category": metadata.get("openviking_category") or "memory",
        "confidence": score,
        "source": uri,
        "score": score,
    }


__all__ = [
    "OpenVikingMemoryManager",
    "_canonical_peer_id",
    "_session_id",
]

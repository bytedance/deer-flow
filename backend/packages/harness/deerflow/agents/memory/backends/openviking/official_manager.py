"""OpenViking memory backend built on the official LangChain adapters."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import threading
import time
import weakref
from collections.abc import Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import PrivateAttr

from deerflow.agents.memory.manager import (
    MemoryAuthorizationError,
    MemoryManager,
    MemoryManagerError,
)
from deerflow.config.agents_config import AGENT_NAME_PATTERN
from deerflow.utils.messages import message_to_text

from .official_config import (
    GENERATED_PEER_PREFIX,
    OfficialOpenVikingConfig,
    is_safe_peer_id,
)

logger = logging.getLogger(__name__)

_SESSION_NAMESPACE = "deerflow-openviking-official-v1"
_DEFAULT_AGENT_SCOPE = "__default__"
_CURSOR_SCHEMA_VERSION = 1


class OfficialOpenVikingMemoryManager(MemoryManager):
    """Query-aware automatic memory using OpenViking-maintained adapters.

    DeerFlow owns lifecycle policy and transcript suffix selection. Message
    conversion, batching, partial-write reporting, commits, retrieval, and HTTP
    transport behavior remain owned by OpenViking.
    """

    supports_search: ClassVar[bool] = True
    context_refresh_policy: ClassVar[Literal["session", "turn"]] = "turn"

    _config: OfficialOpenVikingConfig = PrivateAttr()
    _client: Any = PrivateAttr()
    _recorder: Any = PrivateAttr()
    _retriever: Any = PrivateAttr()
    _commit_policy: Any = PrivateAttr()
    _use_actor_peer: Any = PrivateAttr()
    _partial_write_error: type[Exception] = PrivateAttr()
    _should_keep_hidden_message: Any = PrivateAttr(default=None)
    _session_locks: weakref.WeakValueDictionary[str, threading.RLock] = PrivateAttr(default_factory=weakref.WeakValueDictionary)
    _session_locks_guard: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _pending_commit_sessions: dict[str, str] = PrivateAttr(default_factory=dict)
    _pending_commit_sessions_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _lifecycle: threading.Condition = PrivateAttr(default_factory=threading.Condition)
    _active_operations: int = PrivateAttr(default=0)
    _closed: bool = PrivateAttr(default=False)
    _resources_closed: bool = PrivateAttr(default=False)
    _shutdown_flush_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _shutdown_flush_done: threading.Event = PrivateAttr(default_factory=threading.Event)
    _shutdown_flush_result: bool | None = PrivateAttr(default=None)
    _shutdown_flush_thread: threading.Thread | None = PrivateAttr(default=None)
    _close_requested: bool = PrivateAttr(default=False)

    def model_post_init(self, __context: Any) -> None:
        self._config = OfficialOpenVikingConfig.from_backend_config(self.backend_config)
        integration = _load_official_integration()
        self._commit_policy = integration["OpenVikingCommitPolicy"](mode="always")
        self._recorder = integration["OpenVikingSessionRecorder"](
            url=self._config.base_url,
            api_key=self._config.api_key,
            timeout=self._config.timeout_seconds,
            commit_policy=self._commit_policy,
        )
        # The public property returns the recorder-owned lazy recovery handle.
        # Inject that same handle into retrieval; DeerFlow never constructs or
        # separately owns an SDK client.
        self._client = self._recorder.client
        self._retriever = integration["OpenVikingRetriever"](
            client=self._client,
            target_uri="viking://user/memories",
            search_mode=self._config.search_mode,
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
    ) -> OfficialOpenVikingMemoryManager:
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
        # One synchronous critical section protects the durable capture cursor
        # across regular turn capture and the synchronous pre-compaction hook.
        # Offloading the whole operation keeps network and file I/O off the loop.
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
        query: str | None = None,
    ) -> str:
        del thread_id
        if not query or not query.strip():
            return ""
        if not self._begin_operation():
            return ""
        try:
            peer_id = self._resolve_scope(user_id, agent_name)
            try:
                with self._actor_peer_scope(peer_id):
                    documents = self._retriever.invoke(query.strip())
            except Exception as exc:
                return self._handle_read_error(
                    exc,
                    message="OpenViking context retrieval failed; continuing without injected memory",
                    fallback="",
                )
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
        query: str | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self.get_context,
            user_id,
            agent_name=agent_name,
            thread_id=thread_id,
            query=query,
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
        if not query.strip():
            return []
        if not self._begin_operation():
            return []
        try:
            peer_id = self._resolve_scope(user_id, agent_name)
            retriever = copy.copy(self._retriever)
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
            except Exception as exc:
                return self._handle_read_error(
                    exc,
                    message="OpenViking memory search failed; returning no results",
                    fallback=[],
                )
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
            return healthy
        finally:
            self._end_operation()

    def shutdown_flush(self, timeout: float) -> bool:
        """Stop new work and retry known pending commits within a hard budget."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lifecycle:
            self._closed = True
            while self._active_operations:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._lifecycle.wait(remaining)

        with self._shutdown_flush_lock:
            if self._shutdown_flush_thread is None:
                with self._pending_commit_sessions_lock:
                    pending_sessions = tuple(self._pending_commit_sessions.items())
                self._shutdown_flush_thread = threading.Thread(
                    target=self._flush_pending_commits_for_shutdown,
                    args=(pending_sessions,),
                    name="openviking-memory-shutdown-flush",
                    daemon=True,
                )
                self._shutdown_flush_thread.start()

        remaining = max(0.0, deadline - time.monotonic())
        if not self._shutdown_flush_done.wait(remaining):
            return False
        with self._shutdown_flush_lock:
            return self._shutdown_flush_result is True

    def close(self) -> None:
        """Close adapter state and the one SDK client owned by this manager."""
        with self._shutdown_flush_lock:
            if self._resources_closed:
                return
            self._close_requested = True
        with self._lifecycle:
            self._closed = True
        self._close_if_ready()

    def _flush_pending_commits_for_shutdown(
        self,
        pending_sessions: tuple[tuple[str, str], ...],
    ) -> None:
        success = True
        for session_id, peer_id in pending_sessions:
            state = self._load_cursor(session_id)
            if not state.get("commit_pending"):
                continue
            try:
                with self._actor_peer_scope(peer_id):
                    self._recorder.flush(session_id)
                self._save_cursor(
                    session_id,
                    {**state, "commit_pending": False},
                )
                self._discard_commit_pending(session_id)
            except Exception:
                success = False
                logger.warning(
                    "OpenViking pending commit could not be flushed during shutdown (session=%s)",
                    session_id,
                    exc_info=True,
                )

        with self._shutdown_flush_lock:
            self._shutdown_flush_result = success
            self._shutdown_flush_done.set()
        self._close_if_ready()

    def _close_if_ready(self) -> None:
        """Close only after active calls and a deferred shutdown retry finish."""
        with self._lifecycle:
            if self._active_operations:
                return
        with self._shutdown_flush_lock:
            if not self._close_requested or self._resources_closed or (self._shutdown_flush_thread is not None and not self._shutdown_flush_done.is_set()):
                return
            self._resources_closed = True
        try:
            self._close_resources()
        except BaseException:
            # Deferred closure can run on a background operation/flush thread,
            # where there is no caller to receive an exception.
            logger.exception("Failed to close OpenViking memory resources")

    def _close_resources(self) -> None:
        """Close owned adapter and transport resources exactly once."""

        # The retriever receives the recorder-owned client handle and therefore
        # owns no transport or cache to close. Closing the recorder is both
        # sufficient and safe from synchronous or asynchronous host contexts.
        self._recorder.close()

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
            self._mark_commit_pending(session_id, peer_id)
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
            self._discard_commit_pending(session_id)

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
            rebased = _advanced_cursor(
                state,
                signatures,
                (),
                max_seen=self._config.max_seen_message_ids,
                commit_pending=False,
            )
            self._save_cursor(session_id, rebased)
            return

        try:
            with self._actor_peer_scope(peer_id):
                result = self._recorder.record(
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
                if append_only:
                    confirmed_prefix = signatures[: int(start or 0) + consumed]
                else:
                    confirmed_prefix = None
                state = _advanced_cursor(
                    state,
                    confirmed_prefix,
                    confirmed,
                    max_seen=self._config.max_seen_message_ids,
                    commit_pending=commit_pending,
                )
                self._save_cursor(session_id, state)
                if commit_pending:
                    self._mark_commit_pending(session_id, peer_id)
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

        del result
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
        self._discard_commit_pending(session_id)

    def _resolve_scope(self, user_id: str | None, agent_name: str | None) -> str:
        resolved_user = str(user_id or "default")
        if resolved_user != self._config.owner_user_id:
            raise MemoryAuthorizationError(f"OpenViking USER API key is bound to DeerFlow owner_user_id {self._config.owner_user_id!r}, but this request belongs to {resolved_user!r}. Refusing to share one credential across users.")
        return _canonical_peer_id(agent_name, self._config.default_peer_id)

    def _actor_peer_scope(self, peer_id: str) -> AbstractContextManager[None]:
        return self._use_actor_peer(peer_id)

    def _session_lock(self, session_id: str) -> threading.RLock:
        with self._session_locks_guard:
            return self._session_locks.setdefault(session_id, threading.RLock())

    def _mark_commit_pending(self, session_id: str, peer_id: str) -> None:
        with self._pending_commit_sessions_lock:
            self._pending_commit_sessions[session_id] = peer_id

    def _discard_commit_pending(self, session_id: str) -> None:
        with self._pending_commit_sessions_lock:
            self._pending_commit_sessions.pop(session_id, None)

    def _begin_operation(self) -> bool:
        with self._lifecycle:
            if self._closed:
                return False
            self._active_operations += 1
            return True

    def _end_operation(self) -> None:
        should_try_close = False
        with self._lifecycle:
            self._active_operations -= 1
            if self._active_operations == 0:
                self._lifecycle.notify_all()
                should_try_close = self._closed
        if should_try_close:
            self._close_if_ready()

    def _cursor_path(self, session_id: str) -> Path:
        root = Path(self._config.storage_path or ".") / "openviking" / "official_sessions"
        return root / f"{session_id}.json"

    def _load_cursor(self, session_id: str) -> dict[str, Any]:
        path = self._cursor_path(session_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.warning(
                "Ignoring unreadable OpenViking capture cursor: %s",
                path,
                exc_info=True,
            )
            return {}
        return value if isinstance(value, dict) else {}

    def _save_cursor(self, session_id: str, state: dict[str, Any]) -> None:
        path = self._cursor_path(session_id)
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

    def _handle_read_error(self, exc: Exception, *, message: str, fallback: Any) -> Any:
        if self._config.read_failure_policy == "fail_closed":
            raise MemoryManagerError(message) from exc
        logger.warning(message, exc_info=True)
        return fallback

    def _handle_write_error(
        self,
        exc: Exception,
        message: str,
        session_id: str,
    ) -> None:
        detail = f"{message} (session={session_id})"
        if self._config.write_failure_policy == "fail_closed":
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
        raise ImportError("The official OpenViking memory backend requires langchain-openviking==0.1.0. Install DeerFlow backend dependencies and retry.") from exc
    if not has_request_actor_peer_support():
        raise ImportError("The installed OpenViking SDK lacks request-scoped actor-peer support. Install openviking-sdk>=0.1.6,<0.2 and retry.")
    return {
        "OpenVikingCommitPolicy": OpenVikingCommitPolicy,
        "OpenVikingPartialWriteError": OpenVikingPartialWriteError,
        "OpenVikingRetriever": OpenVikingRetriever,
        "OpenVikingSessionRecorder": OpenVikingSessionRecorder,
        "use_actor_peer": use_actor_peer,
    }


def _canonical_peer_id(agent_name: str | None, default_peer_id: str) -> str:
    if agent_name is None:
        return default_peer_id

    raw_name = str(agent_name).strip()
    if not AGENT_NAME_PATTERN.fullmatch(raw_name):
        raise ValueError(f"Invalid DeerFlow agent name: {raw_name!r}")

    value = raw_name.lower()
    if value == _DEFAULT_AGENT_SCOPE:
        raise ValueError(f"Invalid OpenViking peer scope: {value!r}")
    if is_safe_peer_id(value) and value != default_peer_id and not value.startswith(GENERATED_PEER_PREFIX):
        # Preserve the existing mapping for every already-compatible name so
        # existing OpenViking Sessions remain reachable. The configured default
        # and generated namespace are reserved to keep all branches disjoint.
        return value

    # DeerFlow permits leading hyphens and names longer than OpenViking's
    # 64-character peer limit. Reserved names follow the same stable mapping;
    # the digest prevents truncation/sanitization collisions.
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"{GENERATED_PEER_PREFIX}{digest}"


def _session_id(owner_user_id: str, peer_id: str, thread_id: str) -> str:
    digest = hashlib.sha256(f"{_SESSION_NAMESPACE}\0{owner_user_id}\0{peer_id}\0{thread_id}".encode()).hexdigest()
    return f"df_{digest[:48]}"


def _captureable_messages(
    messages: list[Any],
    should_keep_hidden_message: Any,
) -> list[Any]:
    selected: list[Any] = []
    for message in messages:
        additional_kwargs = message.get("additional_kwargs", {}) if isinstance(message, dict) else getattr(message, "additional_kwargs", {})
        if not isinstance(additional_kwargs, dict):
            additional_kwargs = {}
        if additional_kwargs.get("hide_from_ui") and not (should_keep_hidden_message and should_keep_hidden_message(additional_kwargs)):
            continue
        selected.append(message)
    return selected


def _message_signature(message: Any) -> str:
    """Hash only stable transcript semantics, excluding volatile model metadata."""
    if isinstance(message, Mapping):
        message_id = message.get("id")
        role = message.get("role") or message.get("type")
        tool_calls = message.get("tool_calls") or []
        tool_result = {
            "tool_call_id": message.get("tool_call_id") or message.get("tool_id"),
            "name": message.get("name") or message.get("tool_name"),
            "output": message.get("tool_output") or message.get("output"),
            "status": message.get("status") or message.get("tool_status"),
        }
    else:
        message_id = getattr(message, "id", None)
        role = getattr(message, "type", None)
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
            if isinstance(additional_kwargs, Mapping):
                tool_calls = additional_kwargs.get("tool_calls") or []
        tool_result = {
            "tool_call_id": getattr(message, "tool_call_id", None),
            "name": getattr(message, "name", None),
            "status": getattr(message, "status", None),
        }
    value = {
        "id": str(message_id) if message_id else None,
        "role": role,
        "content": message_to_text(message),
        "tool_calls": tool_calls,
        "tool_result": tool_result,
    }
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sequence_digest(signatures: list[str]) -> str:
    digest = hashlib.sha256()
    for signature in signatures:
        encoded = signature.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _matching_prefix_count(
    state: dict[str, Any],
    signatures: list[str],
) -> int | None:
    count = state.get("submitted_prefix_count")
    digest = state.get("submitted_prefix_digest")
    if isinstance(count, int) and 0 <= count <= len(signatures) and isinstance(digest, str):
        if _sequence_digest(signatures[:count]) == digest:
            return count
        return None
    submitted = _string_list(state.get("submitted_signatures"))
    if submitted and len(submitted) <= len(signatures):
        width = len(submitted)
        for start in range(len(signatures) - width, -1, -1):
            if signatures[start : start + width] == submitted:
                return start + width
    return 0 if not state else None


def _advanced_cursor(
    previous: dict[str, Any],
    prefix_signatures: list[str] | None,
    newly_submitted: Any,
    *,
    max_seen: int,
    commit_pending: bool,
) -> dict[str, Any]:
    recent = [
        *_string_list(previous.get("submitted_signatures")),
        *list(newly_submitted),
    ][-max_seen:]
    state: dict[str, Any] = {
        "schema_version": _CURSOR_SCHEMA_VERSION,
        "submitted_signatures": recent,
        "commit_pending": commit_pending,
    }
    if prefix_signatures is not None:
        state["submitted_prefix_count"] = len(prefix_signatures)
        state["submitted_prefix_digest"] = _sequence_digest(prefix_signatures)
    else:
        state["submitted_prefix_count"] = previous.get("submitted_prefix_count")
        state["submitted_prefix_digest"] = previous.get("submitted_prefix_digest")
    return state


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


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

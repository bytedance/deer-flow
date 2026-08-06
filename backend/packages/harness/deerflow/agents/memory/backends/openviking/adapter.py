"""OpenViking memory backend built on the maintained LangChain adapters."""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
import time
import weakref
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import PrivateAttr

from deerflow.agents.memory.manager import (
    MemoryAuthorizationError,
    MemoryManager,
    MemoryManagerError,
)

from .lifecycle import SessionLifecycleStateError, SessionLifecycleStore
from .session import (
    _advanced_cursor,
    _canonical_peer_id,
    _captureable_messages,
    _cursor_lifecycle,
    _matching_prefix_count,
    _memory_target_uris,
    _message_signature,
    _session_id,
    _string_list,
    _timestamp,
)
from .settings import OpenVikingAdapterConfig

logger = logging.getLogger(__name__)

_COMMIT_RETRY_SECONDS = 60.0


class OpenVikingAdapterMemoryManager(MemoryManager):
    """Query-aware automatic memory using OpenViking-maintained adapters.

    DeerFlow owns lifecycle policy and transcript suffix selection. Message
    conversion, batching, partial-write reporting, commits, retrieval, and HTTP
    transport behavior remain owned by OpenViking.
    """

    supports_search: ClassVar[bool] = True
    context_refresh_policy: ClassVar[Literal["session", "turn"]] = "turn"

    _config: OpenVikingAdapterConfig = PrivateAttr()
    _client: Any = PrivateAttr()
    _recorder: Any = PrivateAttr()
    _retriever: Any = PrivateAttr()
    _commit_policy: Any = PrivateAttr()
    _use_actor_peer: Any = PrivateAttr()
    _partial_write_error: type[Exception] = PrivateAttr()
    _should_keep_hidden_message: Any = PrivateAttr(default=None)
    _session_locks: weakref.WeakValueDictionary[str, threading.RLock] = PrivateAttr(default_factory=weakref.WeakValueDictionary)
    _session_locks_guard: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _session_lifecycle: SessionLifecycleStore = PrivateAttr()
    _lifecycle_restore_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _lifecycle_restored: bool = PrivateAttr(default=False)
    _lifecycle_restore_thread: threading.Thread | None = PrivateAttr(default=None)
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
        self._config = OpenVikingAdapterConfig.from_backend_config(self.backend_config)
        integration = _load_official_integration()
        self._commit_policy = integration["OpenVikingCommitPolicy"](
            mode=self._config.commit_mode,
            pending_token_threshold=self._config.pending_token_threshold,
        )
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
            search_mode=self._config.search_mode,
            limit=self._config.search_top_k,
            score_threshold=self._config.score_threshold,
            context_types=("memory",),
            content_mode=self._config.content_mode,
            max_content_chars=self._config.max_injection_chars,
        )
        self._use_actor_peer = integration["use_actor_peer"]
        self._partial_write_error = integration["OpenVikingPartialWriteError"]
        self._session_lifecycle = SessionLifecycleStore(
            # Preserve the original cursor directory so upgrading this draft
            # cannot replay already-submitted transcript prefixes.
            Path(self._config.storage_path or ".") / "openviking" / "official_sessions",
            self._process_idle_deadline,
        )
        self._lifecycle_restore_thread = threading.Thread(
            target=self._ensure_lifecycle_restored,
            name="openviking-memory-lifecycle-restore",
            daemon=True,
        )
        self._lifecycle_restore_thread.start()

    @classmethod
    def from_config(
        cls,
        backend_config: dict[str, Any] | None = None,
        *,
        mode: Literal["middleware", "tool"] = "middleware",
        **host_hooks: Any,
    ) -> OpenVikingAdapterMemoryManager:
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
            force_commit=False,
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
            force_commit=True,
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
        if not query or not query.strip():
            return ""
        if not self._begin_operation():
            return ""
        try:
            peer_id = self._resolve_scope(user_id, agent_name)
            retriever = copy.copy(self._retriever)
            retriever.target_uri = _memory_target_uris(peer_id)
            if thread_id:
                retriever.session_id = _session_id(
                    self._config.owner_user_id,
                    peer_id,
                    thread_id,
                )
            try:
                with self._actor_peer_scope(peer_id):
                    documents = retriever.invoke(query.strip())
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
            retriever.target_uri = _memory_target_uris(peer_id)
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
        """Drain accepted work and flush only commits already due or requested."""
        deadline = time.monotonic() + max(0.0, timeout)
        self._stop_idle_worker()
        with self._lifecycle:
            self._closed = True
            while self._active_operations:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._lifecycle.wait(remaining)

        with self._shutdown_flush_lock:
            if self._shutdown_flush_thread is None:
                pending_sessions = self._shutdown_commit_candidates(time.time())
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
        self._stop_idle_worker()
        self._close_if_ready()

    def _flush_pending_commits_for_shutdown(
        self,
        pending_sessions: tuple[tuple[str, str], ...],
    ) -> None:
        success = True
        try:
            for session_id, peer_id in pending_sessions:
                try:
                    with self._session_lock(session_id):
                        state = self._load_cursor(session_id)
                        idle_due_at = _timestamp(state.get("idle_due_at"))
                        if not state.get("commit_pending") and not (idle_due_at is not None and idle_due_at <= time.time()):
                            continue
                        try:
                            with self._actor_peer_scope(peer_id):
                                self._recorder.flush(session_id)
                            self._save_cursor(
                                session_id,
                                _cursor_lifecycle(
                                    state,
                                    peer_id=peer_id,
                                    idle_due_at=None,
                                    commit_pending=False,
                                ),
                            )
                            self._unschedule_idle(session_id)
                        except Exception:
                            success = False
                            retry_at = time.time() + _COMMIT_RETRY_SECONDS
                            self._save_cursor(
                                session_id,
                                _cursor_lifecycle(
                                    state,
                                    peer_id=peer_id,
                                    idle_due_at=retry_at,
                                    commit_pending=True,
                                ),
                            )
                            logger.warning(
                                "OpenViking pending commit could not be flushed during shutdown (session=%s)",
                                session_id,
                                exc_info=True,
                            )
                except Exception:
                    success = False
                    logger.exception(
                        "OpenViking shutdown could not process lifecycle state (session=%s)",
                        session_id,
                    )
        finally:
            # A malformed cursor or local IO failure must not strand Gateway
            # shutdown waiting for a completion signal that never arrives.
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
        force_commit: bool,
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
                    force_commit=force_commit,
                )
        finally:
            self._end_operation()

    def _capture_locked(
        self,
        session_id: str,
        peer_id: str,
        messages: list[Any],
        *,
        force_commit: bool,
    ) -> None:
        state = self._load_cursor(session_id)
        signatures = [_message_signature(message) for message in messages]

        if state.get("commit_pending"):
            if not self._flush_locked(
                session_id,
                peer_id,
                state,
                message="OpenViking pending commit retry failed; preserving capture cursor",
            ):
                return
            state = self._load_cursor(session_id)

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
            rebased = _cursor_lifecycle(
                rebased,
                peer_id=peer_id,
                idle_due_at=_timestamp(state.get("idle_due_at")),
                commit_pending=False,
            )
            self._save_cursor(session_id, rebased)
            if force_commit:
                self._flush_locked(
                    session_id,
                    peer_id,
                    rebased,
                    message="OpenViking compaction flush failed; retry intent was preserved",
                )
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
                due_at = time.time() + _COMMIT_RETRY_SECONDS if commit_pending else self._next_idle_deadline()
                state = _cursor_lifecycle(
                    state,
                    peer_id=peer_id,
                    idle_due_at=due_at,
                    commit_pending=commit_pending,
                )
                self._save_cursor(session_id, state)
                if due_at is not None:
                    self._schedule_idle(session_id, peer_id, due_at)
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
        due_at = self._next_idle_deadline()
        state = _cursor_lifecycle(
            _advanced_cursor(
                state,
                signatures,
                pending_signatures,
                max_seen=self._config.max_seen_message_ids,
                commit_pending=False,
            ),
            peer_id=peer_id,
            idle_due_at=due_at,
            commit_pending=False,
        )
        self._save_cursor(session_id, state)
        if due_at is not None:
            self._schedule_idle(session_id, peer_id, due_at)
        else:
            self._unschedule_idle(session_id)
        if force_commit:
            self._flush_locked(
                session_id,
                peer_id,
                state,
                message="OpenViking compaction flush failed; retry intent was preserved",
            )

    def _flush_locked(
        self,
        session_id: str,
        peer_id: str,
        state: dict[str, Any],
        *,
        message: str,
        background: bool = False,
    ) -> bool:
        """Flush one session while its capture lock is held."""

        try:
            with self._actor_peer_scope(peer_id):
                self._recorder.flush(session_id)
        except Exception as exc:
            retry_at = time.time() + _COMMIT_RETRY_SECONDS
            self._save_cursor(
                session_id,
                _cursor_lifecycle(
                    state,
                    peer_id=peer_id,
                    idle_due_at=retry_at,
                    commit_pending=True,
                ),
            )
            self._schedule_idle(session_id, peer_id, retry_at)
            if background:
                logger.warning("%s (session=%s)", message, session_id, exc_info=True)
            else:
                self._handle_write_error(exc, message, session_id)
            return False

        self._save_cursor(
            session_id,
            _cursor_lifecycle(
                state,
                peer_id=peer_id,
                idle_due_at=None,
                commit_pending=False,
            ),
        )
        self._unschedule_idle(session_id)
        return True

    def _next_idle_deadline(self) -> float | None:
        if self._config.commit_mode == "always" or self._config.idle_flush_seconds <= 0:
            return None
        return time.time() + self._config.idle_flush_seconds

    def _schedule_idle(
        self,
        session_id: str,
        peer_id: str,
        due_at: float,
    ) -> None:
        self._session_lifecycle.schedule(session_id, peer_id, due_at)

    def _unschedule_idle(self, session_id: str) -> None:
        self._session_lifecycle.unschedule(session_id)

    def _stop_idle_worker(self) -> None:
        self._session_lifecycle.stop()

    def _process_idle_deadline(
        self,
        session_id: str,
        peer_id: str,
        expected_due_at: float,
        *,
        now: float | None = None,
    ) -> bool:
        """Flush an unchanged, due deadline; stale worker observations are ignored."""

        if not self._begin_operation():
            return False
        try:
            with self._session_lock(session_id):
                state = self._load_cursor(session_id)
                stored_peer = state.get("peer_id")
                stored_due_at = _timestamp(state.get("idle_due_at"))
                if stored_peer != peer_id or stored_due_at is None:
                    return False
                current_time = time.time() if now is None else now
                if stored_due_at != expected_due_at or stored_due_at > current_time:
                    self._schedule_idle(session_id, peer_id, stored_due_at)
                    return False
                return self._flush_locked(
                    session_id,
                    peer_id,
                    state,
                    message="OpenViking idle commit failed; retry intent was preserved",
                    background=True,
                )
        finally:
            self._end_operation()

    def _restore_lifecycle_state(self) -> None:
        """Restore durable retry and idle deadlines after a process restart."""

        now = time.time()
        for session_id, state in self._iter_cursor_states():
            peer_id = state.get("peer_id")
            if not isinstance(peer_id, str) or not peer_id:
                continue
            due_at = _timestamp(state.get("idle_due_at"))
            if state.get("commit_pending"):
                self._schedule_idle(session_id, peer_id, due_at or now)
            elif due_at is not None and self._config.idle_flush_seconds > 0:
                self._schedule_idle(session_id, peer_id, due_at)

    def _ensure_lifecycle_restored(self) -> None:
        if self._lifecycle_restored:
            return
        with self._lifecycle_restore_lock:
            if self._lifecycle_restored:
                return
            # Mark first because restoring an overdue deadline may start the
            # idle worker immediately, and that worker also begins an operation.
            self._lifecycle_restored = True
            self._restore_lifecycle_state()

    def _shutdown_commit_candidates(
        self,
        now: float,
    ) -> tuple[tuple[str, str], ...]:
        candidates: dict[str, str] = {}
        for session_id, state in self._iter_cursor_states():
            peer_id = state.get("peer_id")
            if not isinstance(peer_id, str) or not peer_id:
                continue
            due_at = _timestamp(state.get("idle_due_at"))
            if state.get("commit_pending") or (due_at is not None and due_at <= now):
                candidates[session_id] = peer_id
        return tuple(candidates.items())

    def _iter_cursor_states(self) -> list[tuple[str, dict[str, Any]]]:
        return self._session_lifecycle.iter_states()

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

    def _begin_operation(self) -> bool:
        self._ensure_lifecycle_restored()
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

    def _load_cursor(self, session_id: str) -> dict[str, Any]:
        try:
            return self._session_lifecycle.load(session_id)
        except SessionLifecycleStateError as exc:
            # Treat cursor corruption as a data-integrity failure. Replaying an
            # unknown transcript prefix would duplicate already accepted data.
            raise MemoryManagerError(f"OpenViking lifecycle cursor is unreadable; refusing unsafe replay (session={session_id})") from exc

    def _save_cursor(self, session_id: str, state: dict[str, Any]) -> None:
        self._session_lifecycle.save(session_id, state)

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

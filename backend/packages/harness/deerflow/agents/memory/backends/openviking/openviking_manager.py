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
from collections import OrderedDict
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal

import httpx
from pydantic import PrivateAttr

from deerflow.agents.memory.manager import MemoryManager, MemoryManagerError, MemoryReadError

from .config import OpenVikingConfig
from .credentials import (
    OpenVikingCredential,
    load_credential_provider,
    normalize_resolved_credential,
    validate_user_key,
)
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

_ClientPoolKey = tuple[str | None, str, str]  # (tenant_id, user_id, key_fingerprint)


@dataclass(slots=True, eq=False)
class _ScopedClientEntry:
    """Pooled OpenViking SDK handles bound to one resolved credential scope."""

    key: _ClientPoolKey
    recorder: Any
    retriever: Any
    client: Any
    active_ops: int = 0
    last_used: float = 0.0
    retired: bool = False
    closed: bool = False


class OpenVikingMemoryManager(MemoryManager):
    """OpenViking memory backend supporting single-user and multi-user isolation.

    DeerFlow continues to choose when capture and recall occur. The official
    adapter owns SDK transport, message conversion, batching, commit retries,
    and retrieval behavior.
    """

    supports_search: ClassVar[bool] = True

    _config: OpenVikingConfig = PrivateAttr()
    _integration: dict[str, Any] = PrivateAttr()
    _credential_provider: Any = PrivateAttr(default=None)
    _single_user_credential: OpenVikingCredential | None = PrivateAttr(default=None)
    _pool: OrderedDict[_ClientPoolKey, _ScopedClientEntry] = PrivateAttr(default_factory=OrderedDict)
    _pool_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _inflight_entries: set[_ScopedClientEntry] = PrivateAttr(default_factory=set)
    _clock: Callable[[], float] = PrivateAttr(default=time.monotonic)
    _client: Any = PrivateAttr(default=None)
    _recorder: Any = PrivateAttr(default=None)
    _retriever: Any = PrivateAttr(default=None)
    _use_actor_peer: Any = PrivateAttr()
    _use_home_alias_uris: bool = PrivateAttr(default=False)
    _partial_write_error: type[Exception] = PrivateAttr()
    _should_keep_hidden_message: Any = PrivateAttr(default=None)
    _session_locks: weakref.WeakValueDictionary[str, threading.RLock] = PrivateAttr(default_factory=weakref.WeakValueDictionary)
    _session_locks_guard: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _lifecycle: threading.Condition = PrivateAttr(default_factory=threading.Condition)
    _active_operations: int = PrivateAttr(default=0)
    _closed: bool = PrivateAttr(default=False)
    _close_requested: bool = PrivateAttr(default=False)
    _resources_closed: bool = PrivateAttr(default=False)
    _cleanup_started: bool = PrivateAttr(default=False)
    _cleanup_done: threading.Event = PrivateAttr(default_factory=threading.Event)
    _cleanup_failed: bool = PrivateAttr(default=False)
    _flush_timed_out: bool = PrivateAttr(default=False)
    _resource_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    def model_post_init(self, __context: Any) -> None:
        if self.mode != "middleware":
            raise ValueError("The OpenViking automatic-memory backend supports memory.mode='middleware' only; use OpenViking MCP for explicit model tools")

        injected_provider = __context.get("credential_provider") if isinstance(__context, Mapping) else None
        if injected_provider is not None and (isinstance(injected_provider, type) or not (callable(getattr(injected_provider, "resolve", None)) or callable(injected_provider))):
            raise ValueError("OpenViking injected credential_provider must expose a callable 'resolve(user_id)' method or be callable")

        self._config = OpenVikingConfig.from_backend_config(
            self.backend_config,
            has_injected_credential_provider=injected_provider is not None,
        )
        if injected_provider is not None and self._config.credential_provider is not None:
            raise ValueError("OpenViking cannot configure both backend_config.credential_provider and an injected credential_provider")

        loaded_provider = False
        if injected_provider is not None:
            self._credential_provider = injected_provider
        elif self._config.credential_provider is not None:
            self._credential_provider = load_credential_provider(
                self._config.credential_provider,
                self._config.credential_provider_config,
            )
            loaded_provider = True

        try:
            self._integration = _load_official_integration()
            self._use_actor_peer = self._integration["use_actor_peer"]
            self._partial_write_error = self._integration["OpenVikingPartialWriteError"]

            if self._config.isolation_mode == "single_user":
                assert self._config.owner_user_id is not None
                credential = OpenVikingCredential(
                    api_key=self._config.api_key,
                    tenant_id=None,
                    api_key_env=self._config.api_key_env,
                )
                self._single_user_credential = credential
                key: _ClientPoolKey = (None, self._config.owner_user_id, credential.key_fingerprint)
                try:
                    entry = self._build_scoped_entry(
                        key=key,
                        api_key=credential.api_key,
                        now=self._clock(),
                    )
                except (MemoryManagerError, ValueError):
                    raise
                except Exception as exc:
                    raise MemoryManagerError(f"Failed to initialize OpenViking client ({type(exc).__name__})") from None
                self._pool[key] = entry
                self._recorder = entry.recorder
                self._client = entry.client
                self._retriever = entry.retriever
        except BaseException:
            if loaded_provider:
                self._close_credential_provider()
            raise

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
        injected_provider = host_hooks.get("credential_provider")
        instance = cls.model_validate(
            {"backend_config": backend_config or {}, "mode": mode},
            context={"credential_provider": injected_provider},
        )
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

    @classmethod
    def read_failures_are_fatal_for_config(
        cls,
        backend_config: dict[str, Any] | None,
    ) -> bool:
        return OpenVikingConfig.from_backend_config(backend_config).read_failure_policy == "raise"

    @property
    def read_failures_are_fatal(self) -> bool:
        """Whether read failures or timeouts abort for this manager instance.

        ``DynamicContextMiddleware`` consults the classmethod
        :meth:`read_failures_are_fatal_for_config` over ``backend_config`` (which
        requires ``user_credentials`` or ``credential_provider``), whereas this
        instance property also covers direct programmatic callers injecting
        ``host_hooks["credential_provider"]``.
        """
        return self._config.read_failure_policy == "raise"

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
        query: str | None = None,
    ) -> str:
        del query
        if not self._begin_operation():
            return ""
        entry: _ScopedClientEntry | None = None
        try:
            resolved_user, credential, peer_id = self._resolve_read_scope(user_id, agent_name)
            try:
                entry = self._acquire_client(resolved_user, credential)
            except MemoryManagerError as exc:
                if self._config.read_failure_policy == "raise":
                    raise MemoryReadError(str(exc)) from exc
                raise
            retriever = copy.copy(entry.retriever)
            if thread_id:
                retriever.search_mode = "search"
                retriever.session_id = _session_id(
                    resolved_user,
                    peer_id,
                    thread_id,
                    tenant_id=credential.tenant_id,
                )
            try:
                documents = self._invoke_retriever(
                    retriever,
                    self._config.injection_query,
                    peer_id=peer_id,
                )
            except Exception as exc:
                if self._config.read_failure_policy == "raise":
                    raise MemoryReadError("OpenViking context retrieval failed") from exc
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
            if entry is not None:
                self._release_client(entry)
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
        if not query.strip() or not self._begin_operation():
            return []
        entry: _ScopedClientEntry | None = None
        try:
            resolved_user, credential, peer_id = self._resolve_read_scope(user_id, agent_name)
            try:
                entry = self._acquire_client(resolved_user, credential)
            except MemoryManagerError as exc:
                if self._config.read_failure_policy == "raise":
                    raise MemoryReadError(str(exc)) from exc
                raise
            retriever = copy.copy(entry.retriever)
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
                documents = self._invoke_retriever(
                    retriever,
                    query.strip(),
                    peer_id=peer_id,
                )
            except Exception as exc:
                if self._config.read_failure_policy == "raise":
                    raise MemoryReadError("OpenViking memory search failed") from exc
                logger.warning(
                    "OpenViking memory search failed; returning no results",
                    exc_info=True,
                )
                return []
            return [_document_to_fact(document) for document in documents]
        finally:
            if entry is not None:
                self._release_client(entry)
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
                if self._config.isolation_mode == "single_user":
                    health = getattr(self._client, "health", None)
                    healthy = bool(health()) if callable(health) else True
                else:
                    healthy = self._probe_health_unauthenticated()
            except Exception as exc:
                if self._config.startup_policy == "fail_fast":
                    if isinstance(exc, MemoryManagerError):
                        raise
                    raise MemoryManagerError("OpenViking startup validation failed") from exc
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

    def _probe_health_unauthenticated(self) -> bool:
        url = f"{self._config.base_url}/health"
        with httpx.Client(timeout=self._config.timeout_seconds) as client:
            response = client.get(url)
        if response.status_code != 200:
            return False
        try:
            payload = response.json()
        except ValueError:
            return False
        return isinstance(payload, dict) and payload.get("status") == "ok"

    def shutdown_flush(self, timeout: float) -> bool:
        """Stop new work, drain accepted calls, and close owned resources."""

        deadline = time.monotonic() + max(0.0, timeout)
        with self._lifecycle:
            self._closed = True
            self._close_requested = True
            while self._active_operations:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._flush_timed_out = True
                    return False
                self._lifecycle.wait(remaining)
        done = self._start_resource_cleanup()
        if done.is_set():
            return not self._cleanup_failed
        finished = done.wait(timeout=max(0.0, deadline - time.monotonic()))
        if not finished:
            with self._lifecycle:
                self._flush_timed_out = True
            return False
        return not self._cleanup_failed

    def close(self) -> None:
        """Request idempotent closure after any active operation finishes."""

        with self._lifecycle:
            self._closed = True
            self._close_requested = True
            can_close = self._active_operations == 0
            already_timed_out = self._flush_timed_out
        if not can_close:
            return
        done = self._start_resource_cleanup()
        if not done.is_set() and not already_timed_out:
            done.wait(timeout=self._config.timeout_seconds)

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
        entry: _ScopedClientEntry | None = None
        try:
            if not thread_id:
                raise ValueError("OpenViking memory write requires thread_id")
            try:
                resolved_user, credential, peer_id = self._resolve_scope(user_id, agent_name)
                entry = self._acquire_client(resolved_user, credential)
            except MemoryManagerError as exc:
                # Scope/credential checks have already refused the write before
                # any remote call; the write policy decides whether that refusal
                # also fails a turn whose answer was already generated.
                if self._config.write_failure_policy == "raise":
                    raise
                logger.error("%s Dropping the memory write (thread=%s).", exc, thread_id)
                return
            session_id = _session_id(
                resolved_user,
                peer_id,
                thread_id,
                tenant_id=credential.tenant_id,
            )
            with self._session_lock(session_id):
                self._capture_locked(
                    entry.recorder,
                    session_id,
                    peer_id,
                    _captureable_messages(
                        messages,
                        self._should_keep_hidden_message,
                    ),
                )
        finally:
            if entry is not None:
                self._release_client(entry)
            self._end_operation()

    def _capture_locked(
        self,
        recorder: Any,
        session_id: str,
        peer_id: str,
        messages: list[Any],
    ) -> None:
        state = self._load_cursor(session_id)
        signatures = [_message_signature(message) for message in messages]

        if state.get("commit_pending"):
            try:
                with self._actor_peer_scope(peer_id):
                    recorder.flush(session_id)
            except Exception as exc:
                self._handle_write_error(
                    exc,
                    "OpenViking pending commit retry failed; preserving capture cursor",
                    session_id,
                )
                return
            state = {**state, "commit_pending": False}
            if not self._save_cursor_with_policy(session_id, state):
                return

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
            self._save_cursor_with_policy(
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
                recorder.record(
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
                try:
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
                except OSError as cursor_exc:
                    logger.warning(
                        "Failed to persist partial OpenViking capture cursor (session=%s, error=%s)",
                        session_id,
                        type(cursor_exc).__name__,
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

        self._save_cursor_with_policy(
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
    ) -> tuple[str, OpenVikingCredential, str]:
        if self._config.isolation_mode == "single_user":
            resolved_user = str(user_id or "default")
            if resolved_user != self._config.owner_user_id:
                raise MemoryManagerError(f"OpenViking USER API key is bound to DeerFlow owner_user_id {self._config.owner_user_id!r}, but this request belongs to {resolved_user!r}. Refusing to share one credential across users.")
            assert self._single_user_credential is not None
            try:
                peer_id = _canonical_peer_id(agent_name, self._config.default_peer_id)
            except ValueError as exc:
                raise MemoryManagerError(str(exc)) from exc
            return resolved_user, self._single_user_credential, peer_id

        if user_id is None:
            raise MemoryManagerError("OpenViking multi-user mode requires a non-empty DeerFlow user_id; refusing anonymous fallback.")
        resolved_user = str(user_id)
        if not resolved_user or not resolved_user.strip():
            raise MemoryManagerError("OpenViking multi-user mode requires a non-empty DeerFlow user_id; refusing blank fallback.")
        try:
            resolved_user = validate_user_key(resolved_user)
        except ValueError as exc:
            raise MemoryManagerError(f"OpenViking multi-user mode requires a stripped DeerFlow user_id without control characters, got {resolved_user!r}") from exc

        credential = self._config.user_credentials.get(resolved_user)
        if credential is None and self._credential_provider is not None:
            try:
                resolve_fn = getattr(self._credential_provider, "resolve", None)
                if callable(resolve_fn):
                    raw = resolve_fn(resolved_user)
                else:
                    raw = self._credential_provider(resolved_user)
            except Exception as exc:
                raise MemoryManagerError(f"OpenViking credential provider failed for DeerFlow user {resolved_user!r} ({type(exc).__name__})") from None
            try:
                credential = normalize_resolved_credential(raw, user_id=resolved_user)
            except ValueError as exc:
                raise MemoryManagerError(str(exc)) from exc

        if credential is None:
            self._retire_user_entries(resolved_user)
            raise MemoryManagerError(f"No OpenViking USER API key is configured for DeerFlow user {resolved_user!r}. Refusing to share or fall back to another credential.")

        try:
            peer_id = _canonical_peer_id(agent_name, self._config.default_peer_id)
        except ValueError as exc:
            raise MemoryManagerError(str(exc)) from exc
        return resolved_user, credential, peer_id

    def _resolve_read_scope(
        self,
        user_id: str | None,
        agent_name: str | None,
    ) -> tuple[str, OpenVikingCredential, str]:
        try:
            return self._resolve_scope(user_id, agent_name)
        except MemoryManagerError as exc:
            if self._config.read_failure_policy == "raise":
                raise MemoryReadError(str(exc)) from exc
            raise

    def _build_scoped_entry(
        self,
        *,
        key: _ClientPoolKey,
        api_key: str,
        now: float,
    ) -> _ScopedClientEntry:
        if not api_key:
            raise MemoryManagerError("Refusing to construct OpenViking client with an empty API key")
        commit_policy = self._integration["OpenVikingCommitPolicy"](mode="always")
        recorder = self._integration["OpenVikingSessionRecorder"](
            url=self._config.base_url,
            api_key=api_key,
            timeout=self._config.timeout_seconds,
            # An explicit mapping disables the SDK's ovcli.conf header fallback.
            extra_headers={},
            commit_policy=commit_policy,
        )
        try:
            # The recorder owns one recovery-aware SDK client. Retrieval borrows the
            # same handle, so each scope has one connection pool and one owner.
            client = recorder.client
            retriever = self._integration["OpenVikingRetriever"](
                client=client,
                search_mode="find",
                limit=self._config.search_top_k,
                score_threshold=self._config.score_threshold,
                context_types=("memory",),
                content_mode=self._config.content_mode,
                max_content_chars=self._config.max_injection_chars,
            )
        except BaseException:
            try:
                recorder.close()
            except Exception as close_exc:
                logger.debug("Failed to close OpenViking recorder after setup error (%s)", type(close_exc).__name__)
            raise
        return _ScopedClientEntry(
            key=key,
            recorder=recorder,
            retriever=retriever,
            client=client,
            last_used=now,
        )

    def _acquire_client(
        self,
        user_id: str,
        credential: OpenVikingCredential,
    ) -> _ScopedClientEntry:
        key: _ClientPoolKey = (credential.tenant_id, user_id, credential.key_fingerprint)
        if self._config.isolation_mode == "single_user":
            with self._pool_lock:
                if self._resources_closed:
                    raise MemoryManagerError("OpenViking memory backend is closed")
                entry = self._pool.get(key)
                if entry is None or entry.retired or entry.closed:
                    raise MemoryManagerError("OpenViking client handle is unavailable")
                entry.active_ops += 1
                entry.last_used = self._clock()
                self._pool.move_to_end(key)
                self._inflight_entries.add(entry)
                return entry

        to_close: list[_ScopedClientEntry] = []
        error: MemoryManagerError | None = None
        acquired: _ScopedClientEntry | None = None
        now = self._clock()

        with self._pool_lock:
            if self._resources_closed:
                raise MemoryManagerError("OpenViking memory backend is closed")
            to_close.extend(self._evict_idle_ttl_locked(now))
            error = self._check_fingerprint_conflict_locked(user_id=user_id, credential=credential)
            if error is None:
                existing = self._pool.get(key)
                if existing is not None and not existing.retired and not existing.closed:
                    existing.active_ops += 1
                    existing.last_used = now
                    self._pool.move_to_end(key)
                    self._inflight_entries.add(existing)
                    acquired = existing

        self._close_entries(to_close)
        if error is not None:
            raise error
        if acquired is not None:
            return acquired

        # Build the SDK handles outside _pool_lock so concurrent users never stall on init/I/O.
        try:
            new_entry = self._build_scoped_entry(
                key=key,
                api_key=credential.api_key,
                now=now,
            )
        except MemoryManagerError:
            raise
        except Exception as exc:
            raise MemoryManagerError(f"Failed to initialize OpenViking client for DeerFlow user {user_id!r} ({type(exc).__name__})") from None

        to_close = []
        discard_new = False
        publish_error: MemoryManagerError | None = None
        winner: _ScopedClientEntry | None = None
        now = self._clock()

        with self._pool_lock:
            if self._resources_closed:
                discard_new = True
                publish_error = MemoryManagerError("OpenViking memory backend is closed")
            else:
                to_close.extend(self._evict_idle_ttl_locked(now))
                publish_error = self._check_fingerprint_conflict_locked(user_id=user_id, credential=credential)
                if publish_error is not None:
                    discard_new = True
                else:
                    existing = self._pool.get(key)
                    if existing is not None and not existing.retired and not existing.closed:
                        existing.active_ops += 1
                        existing.last_used = now
                        self._pool.move_to_end(key)
                        self._inflight_entries.add(existing)
                        winner = existing
                        discard_new = True
                    else:
                        to_close.extend(self._retire_scope_rotations_locked(key))
                        to_close.extend(self._evict_lru_locked())
                        new_entry.active_ops = 1
                        new_entry.last_used = now
                        self._pool[key] = new_entry
                        self._inflight_entries.add(new_entry)
                        winner = new_entry

        if discard_new:
            to_close.append(new_entry)
        self._close_entries(to_close)
        if publish_error is not None:
            raise publish_error
        assert winner is not None
        return winner

    def _release_client(self, entry: _ScopedClientEntry) -> None:
        should_close = False
        with self._pool_lock:
            if entry.active_ops > 0:
                entry.active_ops -= 1
            if self._config.isolation_mode == "multi_user":
                entry.last_used = self._clock()
            if entry.active_ops == 0:
                self._inflight_entries.discard(entry)
                if entry.retired and not entry.closed:
                    entry.closed = True
                    should_close = True
        if should_close:
            self._close_entries([entry])

    def _evict_idle_ttl_locked(self, now: float) -> list[_ScopedClientEntry]:
        ttl = self._config.pool_idle_ttl_seconds
        if ttl is None:
            return []
        evicted: list[_ScopedClientEntry] = []
        for entry_key in list(self._pool):
            entry = self._pool[entry_key]
            if entry.active_ops == 0 and (now - entry.last_used) >= ttl:
                del self._pool[entry_key]
                entry.retired = True
                if not entry.closed:
                    entry.closed = True
                    evicted.append(entry)
        return evicted

    def _check_fingerprint_conflict_locked(
        self,
        *,
        user_id: str,
        credential: OpenVikingCredential,
    ) -> MemoryManagerError | None:
        target_scope = (credential.tenant_id, user_id)
        # In hybrid mode, also reject reuse of uncached or LRU/TTL-evicted static credentials.
        for static_user, static_cred in self._config.user_credentials.items():
            static_scope = (static_cred.tenant_id, static_user)
            if static_cred.key_fingerprint == credential.key_fingerprint and static_scope != target_scope:
                return MemoryManagerError(f"OpenViking USER API key cannot be shared across distinct DeerFlow scopes ({static_scope!r} and {target_scope!r})")
        for entry in (*self._pool.values(), *self._inflight_entries):
            if entry.key[2] == credential.key_fingerprint and (entry.key[0], entry.key[1]) != target_scope:
                other_scope = (entry.key[0], entry.key[1])
                return MemoryManagerError(f"OpenViking USER API key cannot be shared across distinct DeerFlow scopes ({other_scope!r} and {target_scope!r})")
        return None

    def _retire_scope_rotations_locked(
        self,
        new_key: _ClientPoolKey,
    ) -> list[_ScopedClientEntry]:
        user_id = new_key[1]
        retired: list[_ScopedClientEntry] = []
        for entry_key in list(self._pool):
            if entry_key[1] == user_id and entry_key != new_key:
                entry = self._pool.pop(entry_key)
                entry.retired = True
                if entry.active_ops == 0 and not entry.closed:
                    entry.closed = True
                    retired.append(entry)
        for entry in self._inflight_entries:
            if entry.key[1] == user_id and entry.key != new_key:
                entry.retired = True
        return retired

    def _evict_lru_locked(self) -> list[_ScopedClientEntry]:
        evicted: list[_ScopedClientEntry] = []
        while len(self._pool) >= self._config.pool_max_clients:
            victim_key = next(
                (k for k, entry in self._pool.items() if entry.active_ops == 0),
                None,
            )
            if victim_key is None:
                victim_key, victim = self._pool.popitem(last=False)
            else:
                victim = self._pool.pop(victim_key)
            victim.retired = True
            if victim.active_ops == 0 and not victim.closed:
                victim.closed = True
                evicted.append(victim)
        return evicted

    def _retire_user_entries(self, user_id: str) -> None:
        to_close: list[_ScopedClientEntry] = []
        with self._pool_lock:
            for entry_key in [k for k in self._pool if k[1] == user_id]:
                entry = self._pool.pop(entry_key)
                entry.retired = True
                if entry.active_ops == 0 and not entry.closed:
                    entry.closed = True
                    to_close.append(entry)
            for entry in self._inflight_entries:
                if entry.key[1] == user_id:
                    entry.retired = True
        self._close_entries(to_close)

    @staticmethod
    def _close_entries(entries: list[_ScopedClientEntry]) -> None:
        for entry in entries:
            try:
                entry.recorder.close()
            except Exception as exc:
                logger.warning(
                    "Failed to close OpenViking recorder for scope (%r, %r) (%s)",
                    entry.key[0],
                    entry.key[1],
                    type(exc).__name__,
                )

    def _close_credential_provider(self) -> None:
        provider = self._credential_provider
        close_fn = getattr(provider, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception as exc:
                logger.warning("Failed to close OpenViking credential provider (%s)", type(exc).__name__)

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
            # Start single-flight cleanup without blocking the finishing operation's
            # executor worker; shutdown_flush()/close() own any cleanup wait budget.
            self._start_resource_cleanup()

    def _start_resource_cleanup(self) -> threading.Event:
        to_close: list[_ScopedClientEntry] = []
        should_spawn = False
        with self._resource_lock:
            if not self._cleanup_started:
                self._cleanup_started = True
                with self._pool_lock:
                    self._resources_closed = True
                    drained = list(self._pool.values())
                    self._pool.clear()
                    for entry in drained:
                        entry.retired = True
                        if entry.active_ops == 0 and not entry.closed:
                            entry.closed = True
                            to_close.append(entry)
                    for entry in self._inflight_entries:
                        entry.retired = True
                        if entry.active_ops == 0 and not entry.closed:
                            entry.closed = True
                            to_close.append(entry)
                close_fn = getattr(self._credential_provider, "close", None)
                if not to_close and not callable(close_fn):
                    self._cleanup_done.set()
                else:
                    should_spawn = True

        if should_spawn:

            def _run_cleanup() -> None:
                try:
                    self._close_entries(to_close)
                    self._close_credential_provider()
                except Exception as exc:
                    logger.warning("Failed to close OpenViking memory resources (%s)", type(exc).__name__)
                finally:
                    self._cleanup_done.set()

            try:
                threading.Thread(
                    target=_run_cleanup,
                    name="openviking-resource-cleanup",
                    daemon=True,
                ).start()
            except Exception as exc:
                logger.warning("Failed to start OpenViking cleanup worker (%s)", type(exc).__name__)
                self._cleanup_failed = True
                self._cleanup_done.set()

        return self._cleanup_done

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

    def _save_cursor_with_policy(self, session_id: str, state: dict[str, Any]) -> bool:
        try:
            self._save_cursor(session_id, state)
            return True
        except OSError as exc:
            self._handle_write_error(
                exc,
                "OpenViking capture cursor persistence failed",
                session_id,
            )
            return False

    def _invoke_retriever(self, retriever: Any, query: str, *, peer_id: str) -> list[Any]:
        use_home = self._use_home_alias_uris
        retriever.target_uri = _memory_target_uris(peer_id, use_home_alias=use_home)
        try:
            with self._actor_peer_scope(peer_id):
                return retriever.invoke(query)
        except Exception as exc:
            if use_home or not _should_retry_with_home_alias(exc):
                raise
            # OpenViking >=0.5.5 rejects uid-less ``viking://user/<reserved>`` shorthands;
            # retry once with ``viking://~/...`` and remember it for future calls.
            self._use_home_alias_uris = True
            logger.info("OpenViking server requires 'viking://~/' user-space URIs; switching target_uri format")
            retry_retriever = copy.copy(retriever)
            retry_retriever.target_uri = _memory_target_uris(peer_id, use_home_alias=True)
            with self._actor_peer_scope(peer_id):
                return retry_retriever.invoke(query)

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


def _should_retry_with_home_alias(exc: Exception) -> bool:
    """Return True when an OpenViking >=0.5.5 server rejected legacy uid-less URIs."""

    if "viking://~/" not in str(exc):
        return False
    return getattr(exc, "code", None) == "INVALID_URI" or type(exc).__name__ == "InvalidURIError"


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

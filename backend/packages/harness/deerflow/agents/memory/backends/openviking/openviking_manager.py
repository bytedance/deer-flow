"""OpenViking HTTP implementation of the pluggable memory contract.

This backend deliberately contains no OpenViking extraction or vector logic.
It forwards filtered conversation turns to OpenViking Sessions and maps remote
memory search results back to DeerFlow's backend-neutral shapes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import threading
import time
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import PrivateAttr

# ABC contract -- the only DeerFlow import in this backend package.
from deerflow.agents.memory.manager import MemoryManager

from .client import OpenVikingClientError, OpenVikingHttpClient
from .config import OpenVikingConfig
from .models import OpenVikingIdentity, OpenVikingMessage, OpenVikingSearchHit

logger = logging.getLogger(__name__)

_DEFAULT_AGENT_SCOPE = "__default__"
_SESSION_NAMESPACE = "deerflow-openviking-v1"
_SAFE_SCOPE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class OpenVikingMemoryManager(MemoryManager):
    """Remote OpenViking memory backend for passive middleware mode."""

    supports_search: ClassVar[bool] = True

    _config: OpenVikingConfig = PrivateAttr()
    _client: OpenVikingHttpClient = PrivateAttr()
    _should_keep_hidden_message: Callable[[Any], bool] | None = PrivateAttr(default=None)
    _session_locks: weakref.WeakValueDictionary[str, threading.RLock] = PrivateAttr(default_factory=weakref.WeakValueDictionary)
    _session_locks_guard: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _lifecycle: threading.Condition = PrivateAttr(default_factory=threading.Condition)
    _active_operations: int = PrivateAttr(default=0)
    _closed: bool = PrivateAttr(default=False)
    _client_closed: bool = PrivateAttr(default=False)

    def model_post_init(self, __context: Any) -> None:
        self._config = OpenVikingConfig.from_backend_config(self.backend_config)
        self._client = OpenVikingHttpClient(self._config)

    @classmethod
    def from_config(
        cls,
        backend_config: dict[str, Any] | None = None,
        *,
        mode: Literal["middleware", "tool"] = "middleware",
        **host_hooks: Any,
    ) -> OpenVikingMemoryManager:
        if mode != "middleware":
            raise ValueError("The OpenViking HTTP backend currently supports memory.mode='middleware' only")
        instance = cls(backend_config=backend_config, mode=mode)
        hook = host_hooks.get("should_keep_hidden_message")
        instance._should_keep_hidden_message = hook if callable(hook) else None
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
        self._write_conversation(thread_id, messages, agent_name=agent_name, user_id=user_id)

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self._write_conversation(thread_id, messages, agent_name=agent_name, user_id=user_id)

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
            try:
                hits = self._search_hits(
                    self._config.injection_query,
                    top_k=self._config.search_top_k,
                    user_id=user_id,
                    agent_name=agent_name,
                    category=None,
                    thread_id=thread_id,
                )
            except OpenVikingClientError:
                if self._config.read_failure_policy == "raise":
                    raise
                logger.warning("OpenViking context retrieval failed; continuing without injected memory", exc_info=True)
                return ""
            return _format_context(hits, max_chars=self._config.max_injection_chars)
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
        if not query.strip():
            return []
        if not self._begin_operation():
            return []
        try:
            try:
                hits = self._search_hits(
                    query,
                    top_k=top_k,
                    user_id=user_id,
                    agent_name=agent_name,
                    category=category,
                    thread_id=None,
                )
            except OpenVikingClientError:
                if self._config.read_failure_policy == "raise":
                    raise
                logger.warning("OpenViking memory search failed; returning no results", exc_info=True)
                return []
            return [_hit_to_fact(hit) for hit in hits]
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
                healthy = self._client.health()
            except OpenVikingClientError:
                if self._config.startup_policy == "fail_fast":
                    raise
                logger.warning("OpenViking health check failed; memory will run in degraded mode", exc_info=True)
                return False
            if not healthy and self._config.startup_policy == "fail_fast":
                raise RuntimeError("OpenViking health check returned an unhealthy response")
            if not healthy:
                logger.warning("OpenViking health check returned unhealthy; memory will run in degraded mode")
            return healthy
        finally:
            self._end_operation()

    def shutdown_flush(self, timeout: float) -> bool:
        """Stop new operations, drain in-flight work, then close the HTTP pool."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lifecycle:
            self._closed = True
            while self._active_operations:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._lifecycle.wait(remaining)
            if self._client_closed:
                return True
            self._client_closed = True
        self._client.close()
        return True

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

            identity = self._identity(user_id, agent_name)
            session_id = _session_id(identity, thread_id)
            lock = self._session_lock(session_id)
            with lock:
                state = self._load_state(session_id)
                submitted_ids = list(state.get("submitted_message_ids", state.get("seen_message_ids", [])))
                committed_ids = list(state.get("committed_message_ids", state.get("seen_message_ids", [])))
                submitted = set(submitted_ids)
                converted = _convert_messages(messages, self._should_keep_hidden_message)
                pending = [message for message in converted if message.message_id not in submitted]
                if not pending:
                    return
                try:
                    self._client.ensure_session(identity, session_id)
                    self._client.add_messages(identity, session_id, pending)
                except OpenVikingClientError:
                    if self._config.write_failure_policy == "raise":
                        raise
                    logger.error(
                        "OpenViking memory message submission failed; dropping this update (session=%s, messages=%d)",
                        session_id,
                        len(pending),
                        exc_info=True,
                    )
                    return
                submitted_ids.extend(message.message_id for message in pending)
                state = {
                    "schema_version": 2,
                    "session_id": session_id,
                    "submitted_message_ids": submitted_ids[-self._config.max_seen_message_ids :],
                    "committed_message_ids": committed_ids[-self._config.max_seen_message_ids :],
                    "last_commit_task_id": state.get("last_commit_task_id"),
                    "last_archive_uri": state.get("last_archive_uri"),
                }
                self._save_state(session_id, state)

                try:
                    commit = self._client.commit_session(identity, session_id)
                except OpenVikingClientError:
                    if self._config.write_failure_policy == "raise":
                        raise
                    logger.error(
                        "OpenViking memory commit failed; preserving submitted watermark without retry (session=%s)",
                        session_id,
                        exc_info=True,
                    )
                    return

                state = {
                    **state,
                    "schema_version": 2,
                    "committed_message_ids": state["submitted_message_ids"],
                    "last_commit_task_id": commit.task_id,
                    "last_archive_uri": commit.archive_uri,
                }
                self._save_state(session_id, state)
        finally:
            self._end_operation()

    def _search_hits(
        self,
        query: str,
        *,
        top_k: int,
        user_id: str | None,
        agent_name: str | None,
        category: str | None,
        thread_id: str | None,
    ) -> list[OpenVikingSearchHit]:
        identity = self._identity(user_id, agent_name)
        session_id = _session_id(identity, thread_id) if thread_id else None
        return self._client.search(
            identity,
            query,
            top_k=max(1, min(top_k, 100)),
            category=category,
            session_id=session_id,
        )

    def _identity(self, user_id: str | None, agent_name: str | None) -> OpenVikingIdentity:
        raw_user = str(user_id or "anonymous")
        agent_scope = _canonical_agent_scope(agent_name)
        # OpenViking trusted identity must be a safe path segment. Hashing the
        # DeerFlow scope also prevents raw emails/usernames from leaving the
        # Gateway and gives each agent a hard-isolated memory namespace.
        digest = hashlib.sha256(f"{self._config.account}\0{raw_user}\0{agent_scope}".encode()).hexdigest()
        return OpenVikingIdentity(account=self._config.account, user=f"df_{digest[:40]}")

    def _session_lock(self, session_id: str) -> threading.RLock:
        with self._session_locks_guard:
            return self._session_locks.setdefault(session_id, threading.RLock())

    def _begin_operation(self) -> bool:
        with self._lifecycle:
            if self._closed:
                return False
            self._active_operations += 1
            return True

    def _end_operation(self) -> None:
        with self._lifecycle:
            self._active_operations -= 1
            if self._active_operations == 0:
                self._lifecycle.notify_all()

    def _state_path(self, session_id: str) -> Path:
        root = Path(self._config.storage_path or ".") / "openviking" / "sessions"
        return root / f"{session_id}.json"

    def _load_state(self, session_id: str) -> dict[str, Any]:
        path = self._state_path(session_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.warning("Ignoring unreadable OpenViking session watermark: %s", path, exc_info=True)
            return {}
        return value if isinstance(value, dict) else {}

    def _save_state(self, session_id: str, state: dict[str, Any]) -> None:
        path = self._state_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp_path, path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logger.debug("Failed to remove OpenViking watermark temp file: %s", temp_path, exc_info=True)


def _canonical_agent_scope(agent_name: str | None) -> str:
    if agent_name is None:
        return _DEFAULT_AGENT_SCOPE
    value = str(agent_name).strip().lower()
    if value == _DEFAULT_AGENT_SCOPE or not _SAFE_SCOPE_RE.fullmatch(value):
        raise ValueError(f"Invalid OpenViking agent scope: {agent_name!r}")
    return value


def _session_id(identity: OpenVikingIdentity, thread_id: str) -> str:
    digest = hashlib.sha256(f"{_SESSION_NAMESPACE}\0{identity.account}\0{identity.user}\0{thread_id}".encode()).hexdigest()
    return f"df_{digest[:48]}"


def _convert_messages(
    messages: list[Any],
    should_keep_hidden_message: Callable[[Any], bool] | None,
) -> list[OpenVikingMessage]:
    converted: list[OpenVikingMessage] = []
    for index, message in enumerate(messages):
        role = _message_role(message)
        if role not in {"user", "assistant"}:
            continue
        additional_kwargs = _message_value(message, "additional_kwargs", {})
        if not isinstance(additional_kwargs, dict):
            additional_kwargs = {}
        if additional_kwargs.get("hide_from_ui") and not (should_keep_hidden_message and should_keep_hidden_message(additional_kwargs)):
            continue
        tool_calls = _message_value(message, "tool_calls", [])
        if role == "assistant" and tool_calls:
            continue
        content = _text_content(_message_value(message, "content", ""))
        if not content.strip():
            continue
        native_id = _message_value(message, "id", None)
        stable_id = str(native_id) if native_id else hashlib.sha256(f"{role}\0{index}\0{content}".encode()).hexdigest()
        converted.append(OpenVikingMessage(message_id=f"df_{stable_id}", role=role, content=content.strip()))
    return converted


def _message_role(message: Any) -> str | None:
    value = _message_value(message, "type", None) or _message_value(message, "role", None)
    if value in {"human", "user"}:
        return "user"
    if value in {"ai", "assistant"}:
        return "assistant"
    name = type(message).__name__.lower()
    if "human" in name:
        return "user"
    if "ai" in name:
        return "assistant"
    return None


def _message_value(message: Any, key: str, default: Any) -> Any:
    return message.get(key, default) if isinstance(message, dict) else getattr(message, key, default)


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content) if content is not None else ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") in {"text", "input_text", "output_text"}:
            text = block.get("text")
            if text:
                parts.append(str(text))
    return "\n".join(parts)


def _hit_content(hit: OpenVikingSearchHit) -> str:
    return (hit.overview or hit.abstract).strip()


def _hit_to_fact(hit: OpenVikingSearchHit) -> dict[str, Any]:
    return {
        "id": hit.uri,
        "content": _hit_content(hit),
        "category": hit.category or "memory",
        "confidence": hit.score,
        "source": hit.uri,
        "score": hit.score,
    }


def _format_context(hits: list[OpenVikingSearchHit], *, max_chars: int) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        content = " ".join(_hit_content(hit).split())
        key = content.casefold()
        if not content or key in seen:
            continue
        seen.add(key)
        line = f"- [{hit.category or 'memory'}] {content}"
        candidate = "\n".join([*lines, line])
        if len(candidate) > max_chars:
            remaining = max_chars - len("\n".join(lines)) - (1 if lines else 0)
            if remaining > 16:
                lines.append(f"{line[: max(0, remaining - 1)]}…")
            break
        lines.append(line)
    return "\n".join(lines)

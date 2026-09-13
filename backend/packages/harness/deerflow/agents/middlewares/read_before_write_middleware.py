"""Deterministic read-before-write gate for file-modifying tools (issue #3857).

The lead agent's duplicate-output failure mode (the same report section
appended five times) came from "append-only, never read back" writes. This
middleware enforces a version gate: modifying an existing file requires a
``read_file`` of the file's *current* version earlier in the conversation.

Design invariants:
- Tools stay stateless. The read mark (``sha256`` of the full file content)
  is stamped on the ``read_file`` ToolMessage's ``additional_kwargs``, so the
  gate's state lives in ``state["messages"]``.
- Summarization deleting the read result deletes the mark with it — the gate
  can never pass while the read content is gone from context.
- Writes never refresh marks: any successful write changes the file hash and
  therefore invalidates every earlier read, forcing a re-read between
  consecutive modifications.
- Gate check and tool execution are serialized per (scope, path): LangGraph
  runs the tool calls of one AIMessage concurrently, so without a critical
  section two same-turn writes could both pass on one stale mark before
  either mutation lands. The same lock covers ``read_file`` + mark stamping,
  so a mark always hashes the version the model was actually shown.
- Fail-open: if the gate itself cannot inspect the file (sandbox hiccup,
  binary content, or sandboxes like AIO/E2B that report read failures as
  ``"Error: ..."`` strings instead of raising), it lets the tool run and
  produce its own error.
- Blocked payloads are dead weight: the call never ran, and the gate demands
  a re-read plus a fresh call, so the model re-emits the content anyway. The
  blocked ToolMessage carries ``WRITE_BLOCK_KEY`` and ``wrap_model_call``
  replaces the paired call's payload arguments (``content``, ``old_str``,
  ``new_str``) with a short deterministic placeholder in the *model-bound
  request only*. ``state["messages"]``, tool receipts, and the run journal
  keep the original arguments, and nothing is externalized to disk: handing
  the model a file reference to content it must re-derive after reading the
  target would only invite bypassing the gate through ``bash``.
"""

import asyncio
import hashlib
import logging
import posixpath
import threading
import weakref
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.tool_call_args import pair_tool_call_results, rewrite_messages_tool_call_args
from deerflow.agents.middlewares.tool_result_meta import normalize_tool_result, stamp_exception_meta
from deerflow.config.read_before_write_config import ReadBeforeWriteConfig
from deerflow.sandbox.exceptions import SandboxAuthorizationError
from deerflow.sandbox.tools import (
    read_current_file_content,
    sandbox_authorization_scope,
    sandbox_authorization_scope_async,
)

logger = logging.getLogger(__name__)

READ_MARK_KEY = "deerflow_read_mark"
#: Stamped on the error ToolMessage of a gate-blocked call: ``{"path", "tool"}``.
WRITE_BLOCK_KEY = "deerflow_write_block"

_READ_TOOLS = frozenset({"read_file"})
_GATED_WRITE_TOOLS = frozenset({"write_file", "str_replace"})
# Payload arguments per gated tool — the bulk of a write call. Everything else
# (path, description, flags) stays visible after a block.
_PAYLOAD_FIELDS: dict[str, tuple[str, ...]] = {
    "write_file": ("content",),
    "str_replace": ("old_str", "new_str"),
}
# Deterministic for a given payload so repeated model calls keep the same
# request prefix (prompt caching) instead of drifting.
_ELIDED_PAYLOAD_TEMPLATE = "[payload elided: {chars} chars; this {tool_name} call was blocked by the read-before-write gate and nothing was written]"

# AIO/E2B-style sandboxes convert read failures (including missing files)
# into "Error: ..." strings instead of raising. Content with this prefix is
# treated as "cannot inspect" — the gate fails open and no mark is stamped.
_UNINSPECTABLE_CONTENT_PREFIX = "Error:"

_BLOCK_MESSAGE = (
    "Error: {tool_name} blocked — {path} already exists and you have not read its current version. "
    "Any write invalidates earlier reads, so re-read before every modification. "
    "Call read_file on it (a ranged read of the relevant section is enough, e.g. the last ~30 lines "
    "before an append), check what is already there, then retry."
)

# Per-(scope, path) locks serializing gate check + tool execution. Same
# WeakValueDictionary pattern as sandbox/file_operation_lock.py, but a
# separate namespace: the tool-internal file lock only guards the mutation,
# while this one also spans the authorization that precedes it.
_GATE_LOCKS: weakref.WeakValueDictionary[tuple[str, str], threading.Lock] = weakref.WeakValueDictionary()
_GATE_LOCKS_GUARD = threading.Lock()


def _get_gate_lock(scope: str, norm_path: str) -> threading.Lock:
    key = (scope, norm_path)
    with _GATE_LOCKS_GUARD:
        lock = _GATE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _GATE_LOCKS[key] = lock
        return lock


def _normalize_mark_path(path: str) -> str:
    return posixpath.normpath(path)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ReadBeforeWriteMiddleware(AgentMiddleware):
    """Version gate: block writes to existing files not read at their current version."""

    def __init__(
        self,
        content_reader: Callable[[Any, str], str] | None = None,
        *,
        config: ReadBeforeWriteConfig | None = None,
    ) -> None:
        super().__init__()
        self._content_reader = content_reader or read_current_file_content
        self._config = config if config is not None else ReadBeforeWriteConfig()

    def release_policy_parameters(self) -> dict[str, object]:
        return {"config": self._config.model_dump(mode="python")}

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        name = request.tool_call.get("name")
        if name in _GATED_WRITE_TOOLS:
            path = self._requested_path(request)
            if path is None:
                return handler(request)
            try:
                with sandbox_authorization_scope(request.runtime):
                    with self._lock_for(request, path):
                        blocked = self._check_write_gate(request)
                        if blocked is not None:
                            # Stamp deerflow_tool_meta so ToolProgressMiddleware can classify
                            # the blocked write even though it bypasses ToolErrorHandlingMiddleware.
                            return normalize_tool_result(blocked)
                        return handler(request)
            except SandboxAuthorizationError as exc:
                return self._authorization_error_result(request, exc)
        if name in _READ_TOOLS:
            path = self._requested_path(request)
            if path is None:
                return handler(request)
            try:
                with sandbox_authorization_scope(request.runtime):
                    with self._lock_for(request, path):
                        result = handler(request)
                        self._attach_read_mark(request, result)
                        return result
            except SandboxAuthorizationError as exc:
                return self._authorization_error_result(request, exc)
        return handler(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        name = request.tool_call.get("name")
        if name in _GATED_WRITE_TOOLS:
            path = self._requested_path(request)
            if path is None:
                return await handler(request)
            try:
                async with sandbox_authorization_scope_async(request.runtime):
                    # threading.Lock may be released from a different thread than the
                    # acquiring one, so acquiring in a worker thread and releasing on
                    # the event-loop thread is safe.
                    lock = self._lock_for(request, path)
                    await asyncio.to_thread(lock.acquire)
                    try:
                        blocked = await asyncio.to_thread(self._check_write_gate, request)
                        if blocked is not None:
                            return normalize_tool_result(blocked)
                        return await handler(request)
                    finally:
                        lock.release()
            except SandboxAuthorizationError as exc:
                return self._authorization_error_result(request, exc)
        if name in _READ_TOOLS:
            path = self._requested_path(request)
            if path is None:
                return await handler(request)
            try:
                async with sandbox_authorization_scope_async(request.runtime):
                    lock = self._lock_for(request, path)
                    await asyncio.to_thread(lock.acquire)
                    try:
                        result = await handler(request)
                        await asyncio.to_thread(self._attach_read_mark, request, result)
                        return result
                    finally:
                        lock.release()
            except SandboxAuthorizationError as exc:
                return self._authorization_error_result(request, exc)
        return await handler(request)

    @staticmethod
    def _authorization_error_result(request: ToolCallRequest, exc: SandboxAuthorizationError) -> ToolMessage:
        """Return the normal tool-level denial instead of failing open or the run."""
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        tool_call_id = str(request.tool_call.get("id") or "missing-tool-call-id")
        detail = str(exc).strip() or exc.__class__.__name__
        message = ToolMessage(
            content=f"Error: {detail}",
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )
        return stamp_exception_meta(message, f"{exc.__class__.__name__}: {detail}")

    # -- locking ---------------------------------------------------------

    def _lock_for(self, request: ToolCallRequest, path: str) -> threading.Lock:
        return _get_gate_lock(self._lock_scope(request), _normalize_mark_path(path))

    @staticmethod
    def _lock_scope(request: ToolCallRequest) -> str:
        """Scope locks per thread (or sandbox) so unrelated agents never contend."""
        context = getattr(request.runtime, "context", None)
        if isinstance(context, dict):
            thread_id = context.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                return thread_id
        state = request.state
        if isinstance(state, dict):
            sandbox_state = state.get("sandbox")
            if isinstance(sandbox_state, dict):
                sandbox_id = sandbox_state.get("sandbox_id")
                if isinstance(sandbox_id, str) and sandbox_id:
                    return sandbox_id
        return "global"

    # -- gate ----------------------------------------------------------

    def _check_write_gate(self, request: ToolCallRequest) -> ToolMessage | None:
        tool_call = request.tool_call
        path = self._requested_path(request)
        if path is None:
            return None
        try:
            current = self._content_reader(request.runtime, path)
        except FileNotFoundError:
            # write_file creates the file; str_replace surfaces its own error.
            return None
        except SandboxAuthorizationError:
            raise
        except Exception:
            logger.warning("read-before-write gate could not inspect %r; allowing the write (fail-open)", path, exc_info=True)
            return None
        if current.startswith(_UNINSPECTABLE_CONTENT_PREFIX):
            # Error-string sandbox read channel (AIO/E2B): "missing" and
            # "unreadable" are indistinguishable here, so fail open — creation
            # proceeds and genuine failures surface from the tool itself.
            logger.debug("read-before-write gate got an error-string read for %r; allowing the write (fail-open)", path)
            return None
        norm_path = _normalize_mark_path(path)
        if self._latest_mark_hash(request.state, norm_path) == _content_hash(current):
            return None
        tool_name = str(tool_call.get("name", "write"))
        return ToolMessage(
            content=_BLOCK_MESSAGE.format(tool_name=tool_name, path=path),
            tool_call_id=str(tool_call.get("id", "")),
            name=tool_name,
            status="error",
            additional_kwargs={WRITE_BLOCK_KEY: {"path": norm_path, "tool": tool_name}},
        )

    @staticmethod
    def _requested_path(request: ToolCallRequest) -> str | None:
        args = request.tool_call.get("args") or {}
        if not isinstance(args, dict):
            return None
        path = args.get("path")
        return path if isinstance(path, str) and path else None

    @staticmethod
    def _latest_mark_hash(state: Any, norm_path: str) -> str | None:
        messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
        if not messages:
            return None
        for message in reversed(messages):
            if not isinstance(message, ToolMessage):
                continue
            mark = (message.additional_kwargs or {}).get(READ_MARK_KEY)
            if isinstance(mark, dict) and mark.get("path") == norm_path:
                mark_hash = mark.get("hash")
                return mark_hash if isinstance(mark_hash, str) else None
        return None

    # -- model-bound payload elision --------------------------------------

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._elide_blocked_payloads(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        # Pure in-memory rewrite: no sandbox or file I/O, so it stays on the loop.
        return await handler(self._elide_blocked_payloads(request))

    def _elide_blocked_payloads(self, request: ModelRequest) -> ModelRequest:
        if not self._config.elide_blocked_payloads:
            return request
        messages = getattr(request, "messages", None)
        if not isinstance(messages, list):
            return request
        patched = elide_blocked_write_payloads(messages, min_chars=self._config.elide_min_chars)
        if patched is None:
            return request
        return request.override(messages=patched)

    # -- mark stamping ---------------------------------------------------

    def _attach_read_mark(self, request: ToolCallRequest, result: ToolMessage | Command) -> None:
        path = self._requested_path(request)
        if path is None:
            return
        message = self._extract_tool_message(result)
        if message is None or message.status == "error":
            return
        try:
            content = self._content_reader(request.runtime, path)
        except SandboxAuthorizationError:
            raise
        except Exception:
            logger.debug("read-before-write mark skipped for %r: file not hashable", path, exc_info=True)
            return
        if content.startswith(_UNINSPECTABLE_CONTENT_PREFIX):
            logger.debug("read-before-write mark skipped for %r: error-string read channel", path)
            return
        message.additional_kwargs[READ_MARK_KEY] = {
            "path": _normalize_mark_path(path),
            "hash": _content_hash(content),
        }

    @staticmethod
    def _extract_tool_message(result: ToolMessage | Command) -> ToolMessage | None:
        if isinstance(result, ToolMessage):
            return result
        if isinstance(result, Command) and isinstance(result.update, dict):
            candidates = [m for m in result.update.get("messages", []) if isinstance(m, ToolMessage)]
            if candidates:
                return candidates[-1]
        return None


# -- blocked payload elision (policy) -----------------------------------------


def elide_blocked_write_payloads(messages: list[Any], *, min_chars: int) -> list[Any] | None:
    """Return ``messages`` with gate-blocked write payloads replaced by placeholders, or ``None`` if unchanged.

    Only the policy lives here: a call qualifies when a ``WRITE_BLOCK_KEY``
    ToolMessage answered it, and its payload fields become
    ``_ELIDED_PAYLOAD_TEMPLATE``. The surface-by-surface rewrite (structured
    ``tool_calls``, raw provider payload, ``tool_use`` blocks, chunk args) is
    ``tool_call_args.rewrite_messages_tool_call_args``, which never mutates the
    input and passes untouched messages through by identity, so the stored
    history keeps the original arguments and the output is identical across
    model calls.
    """
    blocked = _blocked_call_occurrences(messages)
    if not blocked:
        return None

    def replacement_for(message: AIMessage, tool_call: dict[str, Any]) -> dict[str, Any] | None:
        if (id(message), tool_call.get("id")) not in blocked:
            return None
        args = tool_call.get("args")
        return _elide_args(args, str(tool_call.get("name")), min_chars) if isinstance(args, dict) else None

    return rewrite_messages_tool_call_args(messages, replacement_for)


def _blocked_call_occurrences(messages: list[Any]) -> set[tuple[int, str]]:
    """Return ``(id(ai_message), call_id)`` for every call occurrence answered by a gate-blocked result.

    Pairing is per occurrence (``tool_call_args.pair_tool_call_results``):
    tool-call ids may repeat across assistant turns, so a history-wide id set
    would also hit an earlier (or later) *successful* call with the same id
    and mislabel it as blocked.
    """
    return {(id(occurrence.message), occurrence.call_id) for occurrence in pair_tool_call_results(messages) if occurrence.result is not None and isinstance((occurrence.result.additional_kwargs or {}).get(WRITE_BLOCK_KEY), dict)}


def _elide_args(args: dict[str, Any], tool_name: str, min_chars: int) -> dict[str, Any] | None:
    fields = _PAYLOAD_FIELDS.get(tool_name)
    if not fields:
        return None
    elided: dict[str, Any] | None = None
    for field in fields:
        value = args.get(field)
        if not isinstance(value, str) or not value or len(value) < min_chars:
            continue
        if elided is None:
            elided = dict(args)
        elided[field] = _ELIDED_PAYLOAD_TEMPLATE.format(chars=len(value), tool_name=tool_name)
    return elided

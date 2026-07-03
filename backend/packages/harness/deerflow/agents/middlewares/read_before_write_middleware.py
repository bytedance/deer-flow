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
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.sandbox.tools import read_current_file_content

logger = logging.getLogger(__name__)

READ_MARK_KEY = "deerflow_read_mark"

_READ_TOOLS = frozenset({"read_file"})
_GATED_WRITE_TOOLS = frozenset({"write_file", "str_replace"})

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

    def __init__(self, content_reader: Callable[[Any, str], str] | None = None) -> None:
        super().__init__()
        self._content_reader = content_reader or read_current_file_content

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
            with self._lock_for(request, path):
                blocked = self._check_write_gate(request)
                if blocked is not None:
                    return blocked
                return handler(request)
        if name in _READ_TOOLS:
            path = self._requested_path(request)
            if path is None:
                return handler(request)
            with self._lock_for(request, path):
                result = handler(request)
                self._attach_read_mark(request, result)
                return result
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
            # threading.Lock may be released from a different thread than the
            # acquiring one, so acquiring in a worker thread and releasing on
            # the event-loop thread is safe.
            lock = self._lock_for(request, path)
            await asyncio.to_thread(lock.acquire)
            try:
                blocked = await asyncio.to_thread(self._check_write_gate, request)
                if blocked is not None:
                    return blocked
                return await handler(request)
            finally:
                lock.release()
        if name in _READ_TOOLS:
            path = self._requested_path(request)
            if path is None:
                return await handler(request)
            lock = self._lock_for(request, path)
            await asyncio.to_thread(lock.acquire)
            try:
                result = await handler(request)
                await asyncio.to_thread(self._attach_read_mark, request, result)
                return result
            finally:
                lock.release()
        return await handler(request)

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

# Read-Before-Write Gate (ReadBeforeWriteMiddleware) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deterministically block `write_file` (append / overwrite-existing) and `str_replace` unless the agent has read the file's *current* version, fixing issue #3857's output-layer duplicate-append failure.

**Architecture:** A new `ReadBeforeWriteMiddleware` intercepts file tools via `wrap_tool_call`/`awrap_tool_call`. On a successful `read_file` it stamps `sha256(full file content)` into the returned `ToolMessage.additional_kwargs["deerflow_read_mark"]`. Before a gated write it re-hashes the file and requires the newest mark for that path in `state["messages"]` to match. Marks live on messages, so summarization deleting the read result automatically invalidates the mark (the issue's "mark tied to context presence" requirement) — no reserved region needed. Writes never refresh marks, so consecutive modifications force a re-read.

**Tech Stack:** Python 3.12, LangChain `AgentMiddleware`, LangGraph `ToolCallRequest`, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-02-read-before-write-gate-design.md`.
- Tools stay stateless — all gate state derives from messages (issue #3857 requirement).
- Fail-open on unexpected gate errors (only a missing/stale mark blocks); blocked-tool errors must not leak backend config keys/paths.
- Async hooks must not run blocking IO on the event loop (`asyncio.to_thread` / `ensure_sandbox_initialized_async` pattern, see `_run_sync_tool_after_async_sandbox_init` in `sandbox/tools.py`).
- Default enabled (`read_before_write.enabled: true`); config schema change ⇒ bump `config_version` in `config.example.yaml` (15 → 16 at planning time; landed as 16 → 17 after merging upstream/main, where 16 was taken by `max_recursion_limit`).
- Backend TDD is mandatory; run `cd backend && make format` before finishing.
- All backend commands run from the repo's `backend/` directory with `PYTHONPATH=. uv run pytest ...`.

---

### Task 1: Extract `read_current_file_content` helper in sandbox tools

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/tools.py` (read_file_tool at ~1666; place helper right above `@tool("read_file", ...)`)
- Test: `backend/tests/test_read_before_write_middleware.py` (new file, helper test only in this task)

**Interfaces:**
- Produces: `deerflow.sandbox.tools.read_current_file_content(runtime, path: str) -> str` — full current content using `read_file`'s path-resolution rules; raises `FileNotFoundError` when missing, propagates other errors.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the read-before-write gate (issue #3857, output layer)."""

from unittest.mock import MagicMock, patch


class TestReadCurrentFileContent:
    def test_reads_via_sandbox_with_resolution(self):
        from deerflow.sandbox import tools as sandbox_tools

        sandbox = MagicMock()
        sandbox.read_file.return_value = "hello"
        runtime = MagicMock()
        with (
            patch.object(sandbox_tools, "ensure_sandbox_initialized", return_value=sandbox),
            patch.object(sandbox_tools, "ensure_thread_directories_exist"),
            patch.object(sandbox_tools, "is_local_sandbox", return_value=False),
        ):
            assert sandbox_tools.read_current_file_content(runtime, "/mnt/user-data/outputs/report.md") == "hello"
        sandbox.read_file.assert_called_once_with("/mnt/user-data/outputs/report.md")

    def test_propagates_file_not_found(self):
        import pytest

        from deerflow.sandbox import tools as sandbox_tools

        sandbox = MagicMock()
        sandbox.read_file.side_effect = FileNotFoundError()
        with (
            patch.object(sandbox_tools, "ensure_sandbox_initialized", return_value=sandbox),
            patch.object(sandbox_tools, "ensure_thread_directories_exist"),
            patch.object(sandbox_tools, "is_local_sandbox", return_value=False),
        ):
            with pytest.raises(FileNotFoundError):
                sandbox_tools.read_current_file_content(MagicMock(), "/mnt/user-data/outputs/missing.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_read_before_write_middleware.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'read_current_file_content'`

- [ ] **Step 3: Implement the helper and reuse it in `read_file_tool`**

Add above `@tool("read_file", parse_docstring=True)` in `sandbox/tools.py`:

```python
def read_current_file_content(runtime: Runtime | None, path: str) -> str:
    """Read the full current content of ``path`` using read_file's resolution rules.

    Shared by ``read_file_tool`` and ``ReadBeforeWriteMiddleware`` (issue #3857)
    so the gate hashes exactly the bytes the read tool would see. Raises
    ``FileNotFoundError`` when the file does not exist; other sandbox errors
    propagate to the caller.
    """
    sandbox = ensure_sandbox_initialized(runtime)
    ensure_thread_directories_exist(runtime)
    if is_local_sandbox(runtime):
        thread_data = get_thread_data(runtime)
        validate_local_tool_path(path, thread_data, read_only=True)
        if _is_skills_path(path):
            path = _resolve_skills_path(path)
        elif _is_acp_workspace_path(path):
            path = _resolve_acp_workspace_path(path, _extract_thread_id_from_thread_data(thread_data))
        elif not _is_custom_mount_path(path):
            path = _resolve_and_validate_user_data_path(path, thread_data)
        # Custom mount paths are resolved by LocalSandbox._resolve_path()
    return sandbox.read_file(path)
```

Then replace the duplicated body at the top of `read_file_tool` (keep behavior identical):

```python
    try:
        requested_path = path
        content = read_current_file_content(runtime, path)
        if not content:
            return "(empty)"
```

(delete the now-redundant `sandbox = ensure_sandbox_initialized(...)` / `ensure_thread_directories_exist(...)` / local-resolution block / `content = sandbox.read_file(path)` lines from `read_file_tool`; note `requested_path = path` must be assigned **before** the helper call so error messages keep the original path.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_read_before_write_middleware.py tests/test_sandbox_tools.py -v` (second file: existing read_file coverage if present; otherwise `uv run pytest tests -k read_file -v`)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/sandbox/tools.py backend/tests/test_read_before_write_middleware.py
git commit -m "refactor(sandbox): extract read_current_file_content helper (#3857)"
```

---

### Task 2: `ReadBeforeWriteMiddleware` — mark stamping + sync write gate

**Files:**
- Create: `backend/packages/harness/deerflow/agents/middlewares/read_before_write_middleware.py`
- Test: `backend/tests/test_read_before_write_middleware.py`

**Interfaces:**
- Consumes: `read_current_file_content(runtime, path)` from Task 1.
- Produces: `ReadBeforeWriteMiddleware(content_reader=None)` with `wrap_tool_call`; module constants `READ_MARK_KEY = "deerflow_read_mark"`. `content_reader: Callable[[Any, str], str]` defaults to `read_current_file_content` (injectable for tests).

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_read_before_write_middleware.py`:

```python
import hashlib

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_request(name, args, messages=()):
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": "call-1"},
        tool=None,
        state={"messages": list(messages)},
        runtime=MagicMock(),
    )


def _read_marked_message(path, content, tool_call_id="r1"):
    msg = ToolMessage(content=content[:20], tool_call_id=tool_call_id, name="read_file")
    msg.additional_kwargs["deerflow_read_mark"] = {"path": path, "hash": _sha(content)}
    return msg


def _middleware(files: dict[str, str]):
    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

    def reader(_runtime, path):
        import posixpath

        normalized = posixpath.normpath(path)
        if normalized not in files:
            raise FileNotFoundError(path)
        value = files[normalized]
        if isinstance(value, Exception):
            raise value
        return value

    return ReadBeforeWriteMiddleware(content_reader=reader)


class TestReadMarkStamping:
    def test_read_file_success_stamps_mark(self):
        mw = _middleware({"/mnt/user-data/outputs/report.md": "v1"})
        request = _make_request("read_file", {"description": "d", "path": "/mnt/user-data/outputs/report.md"})
        handler = MagicMock(return_value=ToolMessage(content="v1", tool_call_id="call-1", name="read_file"))
        result = mw.wrap_tool_call(request, handler)
        mark = result.additional_kwargs["deerflow_read_mark"]
        assert mark == {"path": "/mnt/user-data/outputs/report.md", "hash": _sha("v1")}

    def test_ranged_read_stamps_full_file_hash(self):
        mw = _middleware({"/mnt/user-data/outputs/report.md": "line1\nline2\nline3"})
        request = _make_request(
            "read_file",
            {"description": "d", "path": "/mnt/user-data/outputs/report.md", "start_line": 3, "end_line": 3},
        )
        handler = MagicMock(return_value=ToolMessage(content="line3", tool_call_id="call-1", name="read_file"))
        result = mw.wrap_tool_call(request, handler)
        assert result.additional_kwargs["deerflow_read_mark"]["hash"] == _sha("line1\nline2\nline3")

    def test_error_tool_message_gets_no_mark(self):
        mw = _middleware({"/mnt/user-data/outputs/report.md": "v1"})
        request = _make_request("read_file", {"description": "d", "path": "/mnt/user-data/outputs/report.md"})
        handler = MagicMock(return_value=ToolMessage(content="boom", tool_call_id="call-1", name="read_file", status="error"))
        result = mw.wrap_tool_call(request, handler)
        assert "deerflow_read_mark" not in result.additional_kwargs

    def test_reader_failure_means_no_mark(self):
        mw = _middleware({"/mnt/user-data/outputs/report.md": RuntimeError("sandbox down")})
        request = _make_request("read_file", {"description": "d", "path": "/mnt/user-data/outputs/report.md"})
        handler = MagicMock(return_value=ToolMessage(content="v1", tool_call_id="call-1", name="read_file"))
        result = mw.wrap_tool_call(request, handler)
        assert "deerflow_read_mark" not in result.additional_kwargs

    def test_non_file_tools_untouched(self):
        mw = _middleware({})
        request = _make_request("bash", {"description": "d", "command": "ls"})
        sentinel = ToolMessage(content="ok", tool_call_id="call-1", name="bash")
        handler = MagicMock(return_value=sentinel)
        assert mw.wrap_tool_call(request, handler) is sentinel


class TestWriteGate:
    PATH = "/mnt/user-data/outputs/report.md"

    def test_new_file_write_allowed(self):
        mw = _middleware({})  # file does not exist
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v1"})
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_overwrite_existing_without_read_blocked(self):
        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert result.tool_call_id == "call-1"
        assert "read" in result.content.lower()

    def test_append_without_read_blocked(self):
        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "more", "append": True})
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_str_replace_without_read_blocked(self):
        mw = _middleware({self.PATH: "v1"})
        request = _make_request("str_replace", {"description": "d", "path": self.PATH, "old_str": "v1", "new_str": "v2"})
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_str_replace_missing_file_passes_through(self):
        mw = _middleware({})
        request = _make_request("str_replace", {"description": "d", "path": self.PATH, "old_str": "a", "new_str": "b"})
        native_error = ToolMessage(content="Error: File not found", tool_call_id="call-1", name="str_replace", status="error")
        handler = MagicMock(return_value=native_error)
        assert mw.wrap_tool_call(request, handler) is native_error

    def test_fresh_mark_allows_write(self):
        mw = _middleware({self.PATH: "v1"})
        messages = [HumanMessage("hi"), AIMessage(""), _read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_stale_mark_after_modification_blocked(self):
        mw = _middleware({self.PATH: "v2"})  # file changed since the read of v1
        messages = [_read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v3", "append": True}, messages)
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_newest_mark_wins(self):
        mw = _middleware({self.PATH: "v2"})
        messages = [_read_marked_message(self.PATH, "v1", "r1"), _read_marked_message(self.PATH, "v2", "r2")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v3"}, messages)
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_mark_removed_by_summarization_blocks(self):
        mw = _middleware({self.PATH: "v1"})
        messages = [HumanMessage("Here is a summary of the conversation to date: ...", name="summary")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_gate_read_failure_fails_open(self):
        mw = _middleware({self.PATH: RuntimeError("sandbox hiccup")})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_normalized_path_matching(self):
        mw = _middleware({self.PATH: "v1"})
        messages = [_read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": "/mnt/user-data/outputs/../outputs/report.md", "content": "v2"}, messages)
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_read_before_write_middleware.py -v`
Expected: FAIL — `ModuleNotFoundError: ... read_before_write_middleware`

- [ ] **Step 3: Implement the middleware (sync paths)**

Create `backend/packages/harness/deerflow/agents/middlewares/read_before_write_middleware.py`:

```python
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
- Fail-open: if the gate itself cannot inspect the file (sandbox hiccup,
  binary content), it lets the tool run and produce its own error.
"""

import asyncio
import hashlib
import logging
import posixpath
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

_BLOCK_MESSAGE = (
    "Error: {tool_name} blocked — {path} already exists and you have not read its current version. "
    "Any write invalidates earlier reads, so re-read before every modification. "
    "Call read_file on it (a ranged read of the relevant section is enough, e.g. the last ~30 lines "
    "before an append), check what is already there, then retry."
)


def _normalize_mark_path(path: str) -> str:
    return posixpath.normpath(path)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ReadBeforeWriteMiddleware(AgentMiddleware):
    """Version gate: block writes to existing files not read at their current version."""

    def __init__(self, content_reader: Callable[[Any, str], str] | None = None) -> None:
        super().__init__()
        self._content_reader = content_reader or read_current_file_content

    # -- wrap_tool_call ------------------------------------------------

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        name = request.tool_call.get("name")
        if name in _GATED_WRITE_TOOLS:
            blocked = self._check_write_gate(request)
            if blocked is not None:
                return blocked
            return handler(request)
        result = handler(request)
        if name in _READ_TOOLS:
            self._attach_read_mark(request, result)
        return result

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        name = request.tool_call.get("name")
        if name in _GATED_WRITE_TOOLS:
            blocked = await asyncio.to_thread(self._check_write_gate, request)
            if blocked is not None:
                return blocked
            return await handler(request)
        result = await handler(request)
        if name in _READ_TOOLS:
            await asyncio.to_thread(self._attach_read_mark, request, result)
        return result

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_read_before_write_middleware.py -v`
Expected: PASS (all TestReadMarkStamping + TestWriteGate)

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/agents/middlewares/read_before_write_middleware.py backend/tests/test_read_before_write_middleware.py
git commit -m "feat(middlewares): read-before-write version gate for file tools (#3857)"
```

---

### Task 3: Async `awrap_tool_call` coverage

**Files:**
- Modify: `backend/tests/test_read_before_write_middleware.py` (implementation from Task 2 already includes `awrap_tool_call`; this task pins it)

**Interfaces:**
- Consumes: `ReadBeforeWriteMiddleware` from Task 2.

- [ ] **Step 1: Write the failing/verifying tests**

```python
class TestAsyncPaths:
    PATH = "/mnt/user-data/outputs/report.md"

    def test_async_block(self):
        import asyncio

        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})

        async def handler(_request):
            raise AssertionError("handler must not run when blocked")

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        assert result.status == "error"

    def test_async_read_stamps_mark(self):
        import asyncio

        mw = _middleware({self.PATH: "v1"})
        request = _make_request("read_file", {"description": "d", "path": self.PATH})

        async def handler(_request):
            return ToolMessage(content="v1", tool_call_id="call-1", name="read_file")

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        assert result.additional_kwargs["deerflow_read_mark"]["hash"] == _sha("v1")

    def test_async_allowed_write_calls_handler(self):
        import asyncio

        mw = _middleware({self.PATH: "v1"})
        messages = [_read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)

        async def handler(_request):
            return ToolMessage(content="OK", tool_call_id="call-1", name="write_file")

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        assert result.status != "error"
```

- [ ] **Step 2: Run tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_read_before_write_middleware.py -v`
Expected: PASS (Task 2 already implemented `awrap_tool_call`; if any fail, fix the middleware, not the tests)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_read_before_write_middleware.py
git commit -m "test(middlewares): pin async read-before-write gate paths (#3857)"
```

---

### Task 4: Config + chain wiring

**Files:**
- Create: `backend/packages/harness/deerflow/config/read_before_write_config.py`
- Modify: `backend/packages/harness/deerflow/config/app_config.py` (imports at top; field after `loop_detection` at ~line 133)
- Modify: `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py:192-197` (tail layer)
- Modify: `config.example.yaml` (bump `config_version` — 16 → 17 as landed; new section near `loop_detection:` at ~line 836)
- Modify: `backend/tests/test_tool_error_handling_middleware.py:178-218` (chain-order pin test)
- Test: `backend/tests/test_read_before_write_middleware.py`

**Interfaces:**
- Produces: `AppConfig.read_before_write: ReadBeforeWriteConfig` with `enabled: bool = True`; `ReadBeforeWriteMiddleware` present in `_build_runtime_middlewares` tail between `SandboxAuditMiddleware` and `ToolErrorHandlingMiddleware` when enabled.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_read_before_write_middleware.py`:

```python
class TestChainWiring:
    def test_enabled_by_default_in_runtime_chain(self):
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
        from deerflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware, build_lead_runtime_middlewares
        from deerflow.config.app_config import AppConfig
        from deerflow.config.sandbox_config import SandboxConfig

        app_config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local.local_sandbox_provider:LocalSandboxProvider"))
        middlewares = build_lead_runtime_middlewares(app_config=app_config)
        types = [type(m) for m in middlewares]
        assert ReadBeforeWriteMiddleware in types
        assert types.index(SandboxAuditMiddleware) < types.index(ReadBeforeWriteMiddleware) < types.index(ToolErrorHandlingMiddleware)

    def test_disabled_removes_middleware(self):
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
        from deerflow.config.app_config import AppConfig
        from deerflow.config.read_before_write_config import ReadBeforeWriteConfig
        from deerflow.config.sandbox_config import SandboxConfig

        app_config = AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local.local_sandbox_provider:LocalSandboxProvider"),
            read_before_write=ReadBeforeWriteConfig(enabled=False),
        )
        middlewares = build_lead_runtime_middlewares(app_config=app_config)
        assert ReadBeforeWriteMiddleware not in [type(m) for m in middlewares]

    def test_subagents_get_the_gate_too(self):
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
        from deerflow.config.app_config import AppConfig
        from deerflow.config.sandbox_config import SandboxConfig

        app_config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local.local_sandbox_provider:LocalSandboxProvider"))
        middlewares = build_subagent_runtime_middlewares(app_config=app_config)
        assert ReadBeforeWriteMiddleware in [type(m) for m in middlewares]
```

(If `_make_app_config` in `tests/test_tool_error_handling_middleware.py` builds AppConfig differently, mirror that fixture instead of the inline construction above.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_read_before_write_middleware.py::TestChainWiring -v`
Expected: FAIL — no `read_before_write_config` module / middleware missing from chain

- [ ] **Step 3: Implement config + wiring**

`backend/packages/harness/deerflow/config/read_before_write_config.py`:

```python
"""Configuration for the read-before-write file gate middleware (issue #3857)."""

from pydantic import BaseModel, Field


class ReadBeforeWriteConfig(BaseModel):
    """Deterministic version gate on file-modifying tools.

    When enabled, ``write_file`` (append or overwrite of an existing file) and
    ``str_replace`` are blocked unless the file was read (``read_file``) after
    its last modification, forcing the agent to see the file's current state
    before changing it.
    """

    enabled: bool = Field(
        default=True,
        description="Whether to block writes to existing files that were not read at their current version",
    )
```

`app_config.py` — add import + field (place after `loop_detection`):

```python
from deerflow.config.read_before_write_config import ReadBeforeWriteConfig
...
    read_before_write: ReadBeforeWriteConfig = Field(default_factory=ReadBeforeWriteConfig, description="Read-before-write file gate middleware configuration")
```

`tool_error_handling_middleware.py` — in `_build_runtime_middlewares`, between `tail.append(SandboxAuditMiddleware())` and `tail.append(ToolErrorHandlingMiddleware())`:

```python
    tail.append(SandboxAuditMiddleware())

    if app_config.read_before_write.enabled:
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

        tail.append(ReadBeforeWriteMiddleware())

    tail.append(ToolErrorHandlingMiddleware())
```

`config.example.yaml` — bump `config_version` by one (landed as 17); add next to the `loop_detection:` section:

```yaml
# Read-before-write file gate (issue #3857).
# Blocks write_file (append / overwrite of an existing file) and str_replace
# unless the agent has read the file's current version first; any write
# invalidates earlier reads, forcing a re-read between consecutive edits.
read_before_write:
  enabled: true
```

`tests/test_tool_error_handling_middleware.py::test_build_lead_runtime_middlewares_chain_order_matches_agents_md` — add to imports and `expected_order` between `SandboxAuditMiddleware` and `ToolErrorHandlingMiddleware`:

```python
    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
    ...
        ("SandboxAuditMiddleware", SandboxAuditMiddleware),
        ("ReadBeforeWriteMiddleware", ReadBeforeWriteMiddleware),
        ("ToolErrorHandlingMiddleware", ToolErrorHandlingMiddleware),
```

- [ ] **Step 4: Run tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_read_before_write_middleware.py tests/test_tool_error_handling_middleware.py tests/test_app_config.py -v` (drop `test_app_config.py` if it doesn't exist)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/config/read_before_write_config.py backend/packages/harness/deerflow/config/app_config.py backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py config.example.yaml backend/tests/test_tool_error_handling_middleware.py backend/tests/test_read_before_write_middleware.py
git commit -m "feat(config): wire ReadBeforeWriteMiddleware into runtime chain, default on (#3857)"
```

---

### Task 5: Tool docstrings, docs, full verification

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/tools.py` (`write_file_tool` docstring ~1765; `str_replace_tool` docstring ~1859)
- Modify: `backend/AGENTS.md` ("Middleware Chain" → Shared runtime base list at ~line 202; "Sandbox Tools" bullet list)
- Modify: `docs/superpowers/specs/2026-07-02-read-before-write-gate-design.md` only if implementation deviated

- [ ] **Step 1: Update tool docstrings**

`write_file_tool` docstring — after the first line, add:

```
    READ-BEFORE-WRITE (issue #3857): if the target file already exists (including
    append=True), you must have read its CURRENT version with read_file first.
    Any write invalidates earlier reads, so re-read between consecutive
    modifications — a ranged read of the relevant section is enough. Writes
    that fail this check are rejected with an error.
```

`str_replace_tool` docstring — after the first paragraph, add:

```
    READ-BEFORE-WRITE (issue #3857): you must have read the file's CURRENT
    version with read_file first; any write invalidates earlier reads.
```

- [ ] **Step 2: Update backend/AGENTS.md**

In "Shared runtime base" list, insert after **SandboxAuditMiddleware** (renumber the tail):

```
11. **ReadBeforeWriteMiddleware** - *(optional, if `read_before_write.enabled`, default on)* Version gate on file writes: `read_file` stamps a content hash onto its ToolMessage; `write_file` (append/overwrite-existing) and `str_replace` are blocked unless the newest mark for that path matches the file's current hash. Marks live on messages, so summarization dropping the read result invalidates the gate automatically (issue #3857)
```

In "Sandbox Tools" section, extend the `write_file` / `str_replace` bullets with: "subject to the read-before-write gate when `read_before_write.enabled` (see Middleware Chain)".

- [ ] **Step 3: Full backend verification**

Run: `cd backend && make format && make lint && make test`
Expected: format clean, lint clean, full suite PASS

- [ ] **Step 4: Commit**

```bash
git add backend/packages/harness/deerflow/sandbox/tools.py backend/AGENTS.md
git commit -m "docs(sandbox): document read-before-write gate in tool docstrings and AGENTS.md (#3857)"
```

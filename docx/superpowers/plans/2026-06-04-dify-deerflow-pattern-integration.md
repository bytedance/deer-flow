# Dify Tools — Deerflow Pattern Integration (Async Streaming)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the existing Dify workflow tools (`dify_aml` / `dify_knowledge` / `dify_general` / `dify_writing` / `dify_document_review` / `dify_image_recognition` / `dify_policy_qa`) to a Deerflow community-style async streaming tool. Each tool becomes an `async def` LangChain `@tool` that calls Dify in `response_mode: "streaming"` via `httpx.AsyncClient`, with the 7 hand-written files kept (one per workflow). Drop the conversation-id LRU cache, the per-workflow file handler side effects, and the prior `get_stream_writer` / `task_*` event system (Dify is not a subagent — it is a "call external API and return the answer" tool, matching the pattern used by `deerflow.community.jina_ai.tools.web_fetch_tool`).

**Architecture:**

```
[LLM picks dify_general]
    ↓ LangChain awaits the coroutine
[async def dify_general_tool(query: str)]   ← 7 files, each ~12 lines
    └─ await invoke_workflow("dify_general", query)
        ├─ tool_cfg = get_app_config().get_tool_config("dify_general")
        ├─ api_key / base_url from tool_cfg.model_extra
        ├─ user = get_current_user().email or "deerflow_<user_id>"
        ├─ client = DifyClient(api_key, base_url)
        └─ await client.astream_chat(query, conversation_id="", user=user)
              ↓
            [httpx.AsyncClient.stream("POST", ...)]   ← SSE bytes
              ↓
            [aiter_lines() loop]
              ↓
            [(chunks: list[str], last_conv_id: str)]   ← returned, conv_id dropped
              ↓
            "".join(chunks) → return to LLM
```

The Dify HTTP client (`dify_client.py`) stays a pure async transport — no LangGraph imports, no logging side effects, no `metadata.usage` parsing (we don't forward usage anywhere). The router layer (`router.py`) is a thin async dispatcher (read config, build client, call `astream_chat`, map errors). The seven workflow tools are simple async functions matching the structure of `deerflow.community.jina_ai.tools`.

**Tech Stack:** `httpx` (async only), `pydantic`, LangChain `@tool`, `deerflow.config.get_app_config`.

**Prerequisite (already landed):** `backend/packages/zens/zens/community/dify/` is the existing multi-workflow implementation from the `2026-05-26-dify-multi-workflow-router` plan. We are simplifying it, not replacing it from scratch.

**Reference implementation (the pattern to follow):** `backend/packages/harness/deerflow/community/jina_ai/tools.py:11-32` — an `async def` tool that calls an external HTTP client, returns a `str`, and lets exceptions bubble (with a `try/except` returning `"Error: ..."`). No `Runtime`, no `InjectedToolCallId`, no events.

**Decisions (locked in):**

| # | Decision | Implication |
|---|---|---|
| 1 | Dify is **always** called in streaming mode | `DifyClient.astream_chat` is the only public method; drop the sync `chat` / `chat_stream` and the blocking `achat` |
| 2 | **No conversation-id cache** | `conversation_id` is always passed as `""`; drop `_conversation_ids` LRU, `_get_cached_conversation`, `_cache_conversation` |
| 3 | **Keep `router.py`** | The 7 workflow files continue to call `await invoke_workflow(name, query)` |
| 4 | **Async** | Tools are `async def`; client uses `httpx.AsyncClient` |

**Decisions explicitly rejected (with reasons):**

| Pattern | Why rejected |
|---|---|
| `get_stream_writer` / `task_started` / `task_running` / `task_completed` / `task_failed` / `task_cancelled` events | This pattern is for `task_tool` (subagent dispatch) — the LLM needs to know the background task is still running and what it produced mid-flight. Dify is a synchronous "wait for an external answer" tool; the LLM gets the final string and proceeds. Incremental Dify chunks are useless to the LLM (it can't act on half an answer). Verified: no `community/` tool uses this pattern (only `task_tool`, `view_image_tool`, `present_file_tool`, and two middlewares). |
| `Runtime` injection | Community tools never receive `Runtime` — they read config via `get_app_config().get_tool_config()` and read user via contextvars. Dify is a community tool. |
| `InjectedToolCallId` | Same — only used by tools that emit `task_*` events. |
| LRU conversation cache | Per decision 2. Dify's per-call stateless mode is sufficient for the single-turn knowledge-QA use case. |
| Factory pattern for the 7 tools | Overkill — the 7 files are each 12 lines, share a one-line router call, and follow the same convention as the rest of `community/`. A factory would add an extra layer for no benefit. |
| `metadata.usage` extraction and forwarding | Nothing to forward to — there are no `task_completed` events any more. The RunJournal picks up usage from the LLM's actual usage, not from Dify. |

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `backend/packages/zens/zens/community/dify/dify_client.py` | Modify | Drop file handler, drop `chat` / `chat_stream`, drop `metadata`, add `astream_chat` async method |
| `backend/packages/zens/zens/community/dify/router.py` | Rewrite | Async `invoke_workflow(tool_name, query) → str`; no cache, no logger side effects, no events |
| `backend/packages/zens/zens/community/dify/workflows/aml.py` | Modify | Convert to async; call `await invoke_workflow` |
| `backend/packages/zens/zens/community/dify/workflows/general.py` | Modify | Same |
| `backend/packages/zens/zens/community/dify/workflows/knowledge.py` | Modify | Same |
| `backend/packages/zens/zens/community/dify/workflows/writing.py` | Modify | Same |
| `backend/packages/zens/zens/community/dify/workflows/document_review.py` | Modify | Same |
| `backend/packages/zens/zens/community/dify/workflows/image_recognition.py` | Modify | Same |
| `backend/packages/zens/zens/community/dify/workflows/policy_qa.py` | Modify | Same |
| `backend/packages/zens/zens/community/dify/workflows/__init__.py` | Keep | Re-exports the 7 tools (unchanged) |
| `backend/packages/zens/zens/community/dify/__init__.py` | Keep | Re-exports the 7 tools (unchanged) |
| `backend/packages/zens/tests/test_dify_streaming.py` | **Delete** | Tests the deleted sync `chat_stream` |
| `backend/packages/zens/tests/test_dify_workflow_tools.py` | Modify | Update Chinese description assertions to English (the new tools use English descriptions) |
| `backend/packages/zens/tests/test_dify_astream_chat.py` | Create | Mock `httpx.AsyncClient.stream`, assert `(chunks, conv_id)` shape, error mapping |
| `backend/packages/zens/tests/test_dify_router.py` | Create | Mock `get_app_config` + `DifyClient`, assert `invoke_workflow` happy path + 3 error paths |

**`config.yaml` example (no change required):**
```yaml
tools:
  - name: dify_aml
    use: zens.community.dify.workflows.aml:dify_aml_tool
    group: community
    api_key: $DIFY_AML_API_KEY
    base_url: http://localhost:8000
```

The `response_mode` field is **no longer read** — Dify is always called in streaming mode (decision 1). Remove any `response_mode` lines from `config.yaml` if present.

---

## Task 1: `DifyClient` — async-only, drop file handler, drop metadata

**Files:**
- Modify: `backend/packages/zens/zens/community/dify/dify_client.py`

- [ ] **Step 1: Write failing test for `astream_chat`**

Create `backend/packages/zens/tests/test_dify_astream_chat.py`:

```python
"""Async streaming behaviour for DifyClient.astream_chat."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


def _async_iter_from_list(items):
    """Build a minimal async iterator from a list (aiter_lines semantics)."""
    async def _gen():
        for item in items:
            yield item
    return _gen()


def _make_async_stream_context(lines, *, is_success=True, status_code=200, error_body=None):
    """Mimic ``httpx.AsyncClient.stream(...)`` as an async context manager.

    The response object exposes ``aiter_lines()`` and ``is_success`` /
    ``status_code`` / ``aread()``. The context manager yields the
    response on __aenter__ and does nothing on __aexit__.
    """
    response = MagicMock()
    response.is_success = is_success
    response.status_code = status_code
    if error_body is not None:
        response.aread = AsyncMock(return_value=error_body)
    response.aiter_lines = MagicMock(return_value=_async_iter_from_list(lines))

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_astream_chat_concatenates_deltas_and_returns_last_conv_id():
    from zens.community.dify.dify_client import DifyClient

    client = DifyClient(api_key="k", base_url="http://x")
    lines = [
        'event: message',
        'data: {"answer": "hel", "conversation_id": "c-1", "message_id": "m-1"}',
        'event: message',
        'data: {"answer": "lo", "conversation_id": "c-1", "message_id": "m-2"}',
        'event: message',
        'data: {"answer": " world", "conversation_id": "c-1", "message_id": "m-3"}',
    ]

    fake_ac = MagicMock()
    fake_ac.stream = MagicMock(return_value=_make_async_stream_context(lines))
    fake_ac.__aenter__ = AsyncMock(return_value=fake_ac)
    fake_ac.__aexit__ = AsyncMock(return_value=False)

    with patch("zens.community.dify.dify_client.httpx.AsyncClient", return_value=fake_ac):
        chunks, conv_id = await client.astream_chat(
            query="hi", conversation_id="", user="u1"
        )

    assert chunks == ["hel", "lo", " world"]
    assert conv_id == "c-1"


@pytest.mark.asyncio
async def test_astream_chat_ignores_message_end_event():
    from zens.community.dify.dify_client import DifyClient

    client = DifyClient(api_key="k", base_url="http://x")
    lines = [
        'event: message',
        'data: {"answer": "ok", "conversation_id": "c-2", "message_id": "m-1"}',
        'event: message_end',
        'data: {"metadata": {"usage": {"total_tokens": 5}}}',
    ]

    fake_ac = MagicMock()
    fake_ac.stream = MagicMock(return_value=_make_async_stream_context(lines))
    fake_ac.__aenter__ = AsyncMock(return_value=fake_ac)
    fake_ac.__aexit__ = AsyncMock(return_value=False)

    with patch("zens.community.dify.dify_client.httpx.AsyncClient", return_value=fake_ac):
        chunks, conv_id = await client.astream_chat(
            query="hi", conversation_id="", user="u1"
        )

    # message_end carries no answer — chunks only contain the one delta.
    assert chunks == ["ok"]
    assert conv_id == "c-2"


@pytest.mark.asyncio
async def test_astream_chat_raises_dify_api_error_on_4xx():
    from zens.community.dify.dify_client import DifyAPIError, DifyClient

    client = DifyClient(api_key="k", base_url="http://x")
    fake_ac = MagicMock()
    fake_ac.stream = MagicMock(return_value=_make_async_stream_context(
        [], is_success=False, status_code=401,
        error_body=b'{"message": "Unauthorized"}',
    ))
    fake_ac.__aenter__ = AsyncMock(return_value=fake_ac)
    fake_ac.__aexit__ = AsyncMock(return_value=False)

    with patch("zens.community.dify.dify_client.httpx.AsyncClient", return_value=fake_ac):
        with pytest.raises(DifyAPIError) as exc_info:
            await client.astream_chat(query="hi", conversation_id="", user="u1")
    assert exc_info.value.status_code == 401
    assert "Unauthorized" in exc_info.value.message


@pytest.mark.asyncio
async def test_astream_chat_raises_dify_api_error_on_timeout():
    from zens.community.dify.dify_client import DifyAPIError, DifyClient

    client = DifyClient(api_key="k", base_url="http://x")
    fake_ac = MagicMock()
    fake_ac.stream = MagicMock(side_effect=httpx.TimeoutException("boom"))
    fake_ac.__aenter__ = AsyncMock(return_value=fake_ac)
    fake_ac.__aexit__ = AsyncMock(return_value=False)

    with patch("zens.community.dify.dify_client.httpx.AsyncClient", return_value=fake_ac):
        with pytest.raises(DifyAPIError) as exc_info:
            await client.astream_chat(query="hi", conversation_id="", user="u1")
    assert exc_info.value.status_code == 0
    assert "timed out" in exc_info.value.message.lower()
```

- [ ] **Step 2: Run the new test, confirm it FAILS**

```
cd backend && PYTHONPATH=. .venv/bin/python -m pytest packages/zens/tests/test_dify_astream_chat.py -v
```

Expected: `AttributeError: type object 'DifyClient' has no attribute 'astream_chat'`.

- [ ] **Step 3: Drop the file handler and unused imports in `dify_client.py`**

In `backend/packages/zens/zens/community/dify/dify_client.py`:
- Delete lines 1-21 (the docstring with `from pathlib import Path`, the `_backend_dir` / `_logs_dir` / `_file_handler` block, and the `if not logger.handlers: ...` setup). Keep only the module docstring if you want one, or remove it.
- Replace with a clean header:

```python
"""Dify HTTP client for chatflow apps.

Async-only. The single public method is :meth:`DifyClient.astream_chat`,
which POSTs to Dify with ``response_mode=streaming`` and returns
``(chunks, last_conversation_id)``. The router layer (``router.py``)
owns all config / user resolution / error-string mapping.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Simplify `DifyResponse` and drop the blocking `chat` method**

- Drop the `metadata` field from `DifyResponse` (we no longer forward usage).
- Delete the `DifyClient.chat` method entirely (blocking Dify mode is gone).
- Delete the `DifyClient.chat_stream` method entirely (sync SSE parsing is gone; the async `astream_chat` replaces it).
- Keep `DifyAPIError` unchanged.

The resulting `DifyResponse`:
```python
class DifyResponse(BaseModel):
    answer: str
    conversation_id: str
    message_id: str
```

(We keep `DifyResponse` because it's still referenced by other call sites; if the test imports confirm nothing else uses it, drop the class entirely. Decision: keep the class to minimise the blast radius.)

- [ ] **Step 5: Add `astream_chat` async method to `DifyClient`**

Inside the `DifyClient` class, after the (now-deleted) `chat_stream` method:

```python
async def astream_chat(
    self,
    query: str,
    conversation_id: str,
    user: str,
    timeout: float = 60.0,
) -> tuple[list[str], str]:
    """Call Dify in streaming mode and return ``(chunks, last_conversation_id)``.

    Each ``event: message`` SSE frame yields one element of ``chunks``
    (the value of the frame's ``answer`` field). The most recent
    non-empty ``conversation_id`` is returned in the second tuple slot;
    the caller is free to ignore it.

    The terminal ``event: message_end`` frame (which carries
    ``metadata.usage``) is consumed and discarded — the Deerflow
    RunJournal records LLM usage directly, not Dify-internal usage.

    Args:
        query: User query forwarded to the chatflow.
        conversation_id: Always pass ``""`` for now (no LRU cache).
        user: Dify-side user identifier (email preferred).
        timeout: HTTP timeout in seconds.

    Returns:
        ``(chunks, last_conversation_id)`` — ``chunks`` is the list of
        answer fragments in arrival order; ``last_conversation_id`` is
        the most recent one Dify emitted (often empty on the first
        call).

    Raises:
        DifyAPIError: On non-2xx HTTP status, transport timeout, or
            protocol error mid-stream.
    """
    url = f"{self.base_url}/v1/chat-messages"
    headers = {
        "Authorization": f"Bearer {self.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": {},
        "query": query,
        "response_mode": "streaming",
        "conversation_id": conversation_id,
        "user": user,
        "files": [],
    }

    logger.debug("Dify astream_chat request: query=%r, conversation_id=%r, user=%r",
                 query, conversation_id, user)

    chunks: list[str] = []
    last_conv_id = conversation_id

    try:
        async with httpx.AsyncClient(timeout=timeout) as ac:
            async with ac.stream("POST", url, json=payload, headers=headers) as response:
                if not response.is_success:
                    try:
                        body = await response.aread()
                        message = json.loads(body).get("message") or body.decode("utf-8", errors="replace")
                    except (json.JSONDecodeError, httpx.HTTPError):
                        message = (await response.aread()).decode("utf-8", errors="replace") or "Unknown error"
                    logger.error("Dify astream_chat API error: status=%d, message=%s",
                                 response.status_code, message)
                    raise DifyAPIError(response.status_code, message)

                current_event: str | None = None
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        current_event = line[len("event: ") :].strip()
                        continue
                    if not line.startswith("data: "):
                        continue
                    data_str = line[len("data: ") :].strip()
                    if not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.debug("Dify astream_chat: dropping non-JSON data line: %r", data_str)
                        continue

                    if current_event != "message":
                        # ``message_end`` carries metadata we do not
                        # need; ``ping`` / ``node_*`` are noise.
                        continue
                    answer = data.get("answer", "")
                    if answer:
                        chunks.append(answer)
                    conv_id = data.get("conversation_id")
                    if conv_id:
                        last_conv_id = conv_id
    except httpx.TimeoutException as exc:
        logger.error("Dify astream_chat timed out (url=%s, timeout=%.1fs)", url, timeout)
        raise DifyAPIError(0, "Request to Dify timed out") from exc
    except (httpx.RemoteProtocolError, httpx.ReadError) as exc:
        # Dify closed the connection mid-stream (server restart, LLM
        # backend hiccup, etc.). Surface as a transport error so the
        # caller maps it to ``"Error: ..."``.
        logger.error("Dify astream_chat protocol/read error: %s", exc)
        raise DifyAPIError(0, f"Dify connection lost: {exc}") from exc

    logger.info("Dify astream_chat completed: chunks=%d, last_conv_id=%s",
                len(chunks), last_conv_id)
    return chunks, last_conv_id
```

- [ ] **Step 6: Confirm the import-time side effect is gone**

```
cd backend && PYTHONPATH=. .venv/bin/python -c "
import os, zens.community.dify.dify_client
assert not os.path.exists('logs/dify.log'), 'file handler side effect returned'
print('no file handler side effect')
"
```

- [ ] **Step 7: Run the new test, confirm it PASSES**

```
cd backend && PYTHONPATH=. .venv/bin/python -m pytest packages/zens/tests/test_dify_astream_chat.py -v
```

Expected: 4 passed.

- [ ] **Step 8: Delete the now-stale sync-streaming test**

```
cd backend && rm packages/zens/tests/test_dify_streaming.py
```

- [ ] **Step 9: Commit**

```bash
cd backend && git add packages/zens/zens/community/dify/dify_client.py packages/zens/tests/test_dify_astream_chat.py
git commit -m "feat(dify): async-only DifyClient with astream_chat (drops sync chat/chat_stream + file handler)"
```

---

## Task 2: Simplify `router.py` — async entry, no cache, no events

**Files:**
- Rewrite: `backend/packages/zens/zens/community/dify/router.py`

- [ ] **Step 1: Write failing test for `invoke_workflow`**

Create `backend/packages/zens/tests/test_dify_router.py`:

```python
"""End-to-end behaviour for router.invoke_workflow.

We mock get_app_config (config reading) and DifyClient (HTTP transport)
and assert that invoke_workflow:
  - returns the joined chunks on success
  - returns a clean "Error: ..." string on configuration / Dify / unknown failure
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zens.community.dify.dify_client import DifyAPIError


def _make_tool_config(*, api_key="k", base_url="http://x"):
    cfg = MagicMock()
    cfg.model_extra = {"api_key": api_key, "base_url": base_url}
    return cfg


@pytest.mark.asyncio
async def test_invoke_workflow_returns_joined_answer_on_success():
    from zens.community.dify import router

    fake_client = MagicMock()
    fake_client.astream_chat = AsyncMock(return_value=(["hello", " world"], "conv-1"))

    with patch.object(router, "_get_tool_config", return_value=_make_tool_config()), \
         patch.object(router, "DifyClient", return_value=fake_client), \
         patch.object(router, "_resolve_user", return_value="u@example.com"):
        answer = await router.invoke_workflow("dify_general", "hi")

    assert answer == "hello world"
    fake_client.astream_chat.assert_awaited_once_with(
        query="hi", conversation_id="", user="u@example.com"
    )


@pytest.mark.asyncio
async def test_invoke_workflow_returns_error_when_tool_not_configured():
    from zens.community.dify import router

    with patch.object(router, "_get_tool_config", return_value=None):
        answer = await router.invoke_workflow("dify_ghost", "hi")

    assert "Error" in answer
    assert "dify_ghost" in answer
    assert "not configured" in answer


@pytest.mark.asyncio
async def test_invoke_workflow_returns_error_when_api_key_missing():
    from zens.community.dify import router

    cfg = MagicMock()
    cfg.model_extra = {"base_url": "http://x"}  # no api_key

    with patch.object(router, "_get_tool_config", return_value=cfg):
        answer = await router.invoke_workflow("dify_general", "hi")

    assert "Error" in answer
    assert "api_key" in answer
    assert "dify_general" in answer


@pytest.mark.asyncio
async def test_invoke_workflow_maps_dify_api_error_to_string():
    from zens.community.dify import router

    fake_client = MagicMock()
    fake_client.astream_chat = AsyncMock(side_effect=DifyAPIError(401, "Unauthorized"))

    with patch.object(router, "_get_tool_config", return_value=_make_tool_config()), \
         patch.object(router, "DifyClient", return_value=fake_client), \
         patch.object(router, "_resolve_user", return_value="u@example.com"):
        answer = await router.invoke_workflow("dify_general", "hi")

    assert "Error" in answer
    assert "dify_general" in answer
    assert "401" in answer
    assert "Unauthorized" in answer


@pytest.mark.asyncio
async def test_invoke_workflow_maps_unexpected_exception_to_string():
    from zens.community.dify import router

    fake_client = MagicMock()
    fake_client.astream_chat = AsyncMock(side_effect=RuntimeError("boom"))

    with patch.object(router, "_get_tool_config", return_value=_make_tool_config()), \
         patch.object(router, "DifyClient", return_value=fake_client), \
         patch.object(router, "_resolve_user", return_value="u@example.com"):
        answer = await router.invoke_workflow("dify_general", "hi")

    assert "Error" in answer
    assert "dify_general" in answer
    assert "boom" in answer
```

- [ ] **Step 2: Run the new test, confirm it FAILS**

```
cd backend && PYTHONPATH=. .venv/bin/python -m pytest packages/zens/tests/test_dify_router.py -v
```

Expected: `ImportError` (the test will try to import `router.DifyClient` and the new async function won't be there yet, or assertions on stale state will fail).

- [ ] **Step 3: Rewrite `router.py` from scratch**

Replace `backend/packages/zens/zens/community/dify/router.py` entirely:

```python
"""Dify workflow router — async dispatcher.

The router is the only place that knows how to:
  1. Read a Dify tool's config (api_key, base_url) from config.yaml.
  2. Resolve the Dify ``user`` identifier.
  3. Build a :class:`DifyClient` and call ``astream_chat``.
  4. Map any exception to a plain ``"Error: ..."`` string the LLM
     can read.

The router does NOT emit LangGraph events, does NOT cache
conversation ids, and does NOT inject ``Runtime``. It mirrors the
shape of ``deerflow.community.jina_ai.tools`` (a thin async
function that calls a client and returns a string).
"""

import logging

from zens.community.dify.dify_client import DifyAPIError, DifyClient

logger = logging.getLogger(__name__)


def _get_tool_config(tool_name: str):
    """Read ``api_key`` / ``base_url`` from the tool's config.yaml entry.

    Returns the ``ToolConfig`` instance (with ``.model_extra`` populated),
    or ``None`` if the tool is not registered.
    """
    from deerflow.config import get_app_config

    return get_app_config().get_tool_config(tool_name)


def _resolve_user() -> str:
    """Resolve the Dify ``user`` identifier, preferring the authenticated email.

    Dify uses this field to scope conversation history and rate limits.
    We prefer the auth-validated email; fall back to a synthetic id.
    """
    from deerflow.runtime.user_context import get_current_user, get_effective_user_id

    current = get_current_user()
    if current is not None:
        return str(current.email)
    user_id = get_effective_user_id()
    return f"deerflow_{user_id}" if user_id else "anonymous"


async def invoke_workflow(tool_name: str, query: str) -> str:
    """Call Dify in streaming mode and return the joined answer.

    Args:
        tool_name: The workflow's name in config.yaml (e.g. ``"dify_general"``).
        query: The user query forwarded to the chatflow.

    Returns:
        The full answer (concatenation of all SSE deltas), or a
        ``"Error: ..."`` string on any failure.
    """
    tool_cfg = _get_tool_config(tool_name)
    if tool_cfg is None:
        return f"Error: Tool '{tool_name}' is not configured in config.yaml"

    model_extra = tool_cfg.model_extra or {}
    api_key = model_extra.get("api_key")
    if not api_key:
        return f"Error: api_key not configured for tool '{tool_name}'"
    base_url = model_extra.get("base_url") or "http://localhost:8000"

    user = _resolve_user()
    client = DifyClient(api_key=api_key, base_url=base_url)

    logger.info("invoke_workflow: tool=%s, query=%r, user=%r", tool_name, query, user)

    try:
        chunks, _last_conv_id = await client.astream_chat(
            query=query, conversation_id="", user=user
        )
    except DifyAPIError as exc:
        logger.warning(
            "invoke_workflow failed: tool=%s, status=%d, message=%s",
            tool_name, exc.status_code, exc.message,
        )
        return f"Error: Dify workflow '{tool_name}' failed (status={exc.status_code}): {exc.message}"
    except Exception as exc:  # noqa: BLE001 — surface any unexpected failure as a tool error
        logger.exception("invoke_workflow unexpected error: tool=%s", tool_name)
        return f"Error: Dify workflow '{tool_name}' failed: {exc}"

    full_answer = "".join(chunks)
    logger.info("invoke_workflow completed: tool=%s, answer_len=%d", tool_name, len(full_answer))
    return full_answer
```

- [ ] **Step 4: Run the new test, confirm it PASSES**

```
cd backend && PYTHONPATH=. .venv/bin/python -m pytest packages/zens/tests/test_dify_router.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Confirm no stray file-handler side effect**

```
cd backend && PYTHONPATH=. .venv/bin/python -c "
import os, zens.community.dify.router
assert not os.path.exists('logs/dify_aml.log'), 'per-workflow file handler returned'
assert not os.path.exists('logs/dify.log'), 'shared file handler returned'
print('no router logger side effect')
"
```

- [ ] **Step 6: Commit**

```bash
cd backend && git add packages/zens/zens/community/dify/router.py packages/zens/tests/test_dify_router.py
git commit -m "refactor(dify): simplify router.py — async invoke_workflow, no cache, no events"
```

---

## Task 3: Convert the 7 workflow tools to async

**Files:**
- Modify: `backend/packages/zens/zens/community/dify/workflows/{aml,general,knowledge,writing,document_review,image_recognition,policy_qa}.py`

- [ ] **Step 1: Rewrite `workflows/general.py` (template for the other six)**

```python
"""General-purpose Dify chatflow tool."""

from langchain.tools import tool

from zens.community.dify.router import invoke_workflow


@tool("dify_general", parse_docstring=True)
async def dify_general_tool(query: str) -> str:
    """General-purpose Dify chatflow tool.

    When to use:
    - The user explicitly asks to use the dify_general tool or the
      general-purpose chatflow.

    When NOT to use:
    - Plain chit-chat that does not need the chatflow.

    Args:
        query: The user's general question or task description.
    """
    return await invoke_workflow("dify_general", query)
```

- [ ] **Step 2: Rewrite the remaining six workflow files using the same template**

`aml.py`:
```python
"""Anti-money-laundering (AML) Dify chatflow tool."""

from langchain.tools import tool

from zens.community.dify.router import invoke_workflow


@tool("dify_aml", parse_docstring=True)
async def dify_aml_tool(query: str) -> str:
    """Anti-money-laundering (AML) Dify chatflow tool.

    When to use:
    - The user asks an AML question, asks to use the dify_aml tool, or
      describes a transaction that needs AML review.

    When NOT to use:
    - General chat that does not need AML domain knowledge.

    Args:
        query: The user's AML-related question or transaction description.
    """
    return await invoke_workflow("dify_aml", query)
```

`knowledge.py`:
```python
"""Dify knowledge-base question-answering tool."""

from langchain.tools import tool

from zens.community.dify.router import invoke_workflow


@tool("dify_knowledge", parse_docstring=True)
async def dify_knowledge_tool(query: str) -> str:
    """Dify knowledge-base question-answering tool.

    When to use:
    - The user asks a question whose answer lives in the configured
      Dify knowledge base (internal policies, operational procedures,
      business guidelines, banking-office scenarios).

    When NOT to use:
    - Casual conversation that does not need knowledge retrieval.

    Args:
        query: The user's knowledge-base question.
    """
    return await invoke_workflow("dify_knowledge", query)
```

`writing.py`:
```python
"""AI-writing Dify chatflow tool."""

from langchain.tools import tool

from zens.community.dify.router import invoke_workflow


@tool("dify_writing", parse_docstring=True)
async def dify_writing_tool(query: str) -> str:
    """AI-writing Dify chatflow tool.

    When to use:
    - The user asks for help drafting, rewriting, or polishing text.

    When NOT to use:
    - Factual Q&A, code generation, or non-writing tasks.

    Args:
        query: The user's writing request.
    """
    return await invoke_workflow("dify_writing", query)
```

`document_review.py`:
```python
"""Document review Dify chatflow tool."""

from langchain.tools import tool

from zens.community.dify.router import invoke_workflow


@tool("dify_document_review", parse_docstring=True)
async def dify_document_review_tool(query: str) -> str:
    """Document review Dify chatflow tool.

    When to use:
    - The user wants a document reviewed for compliance, completeness,
      or correctness.

    When NOT to use:
    - Generation, summarisation, or translation of new content.

    Args:
        query: The document content or review-related question.
    """
    return await invoke_workflow("dify_document_review", query)
```

`image_recognition.py`:
```python
"""Image recognition Dify chatflow tool."""

from langchain.tools import tool

from zens.community.dify.router import invoke_workflow


@tool("dify_image_recognition", parse_docstring=True)
async def dify_image_recognition_tool(query: str) -> str:
    """Image recognition Dify chatflow tool.

    When to use:
    - The user has an image they want analysed or described.

    When NOT to use:
    - Text-only questions, or when no image is available.

    Args:
        query: The image-related question or description.
    """
    return await invoke_workflow("dify_image_recognition", query)
```

`policy_qa.py`:
```python
"""Policy question-answering Dify chatflow tool."""

from langchain.tools import tool

from zens.community.dify.router import invoke_workflow


@tool("dify_policy_qa", parse_docstring=True)
async def dify_policy_qa_tool(query: str) -> str:
    """Policy question-answering Dify chatflow tool.

    When to use:
    - The user asks about an internal policy, regulation, or rule.

    When NOT to use:
    - Casual conversation or non-policy questions.

    Args:
        query: The user's policy / regulation question.
    """
    return await invoke_workflow("dify_policy_qa", query)
```

- [ ] **Step 3: Run `test_dify_workflow_tools.py` and update its Chinese description assertions**

```
cd backend && PYTHONPATH=. .venv/bin/python -m pytest packages/zens/tests/test_dify_workflow_tools.py -v
```

The existing file asserts on the old Chinese descriptions:

```python
def test_aml_tool_loads():
    from zens.community.dify.workflows.aml import dify_aml_tool
    assert dify_aml_tool.name == "dify_aml"
    assert "反洗钱" in dify_aml_tool.description   # ← stale
```

The new descriptions are English. Update the test to:

```python
def test_aml_tool_loads():
    from zens.community.dify.workflows.aml import dify_aml_tool
    assert dify_aml_tool.name == "dify_aml"
    assert "Anti-money-laundering" in dify_aml_tool.description
    # Tool coroutine must be async — match the jina_ai reference style.
    import inspect
    assert inspect.iscoroutinefunction(dify_aml_tool.coroutine)
```

Apply the same pattern to the other assertions in the same file (replace Chinese substrings with English ones, and assert the coroutine is async for at least one of the tools as a smoke check).

- [ ] **Step 4: Run the full zens test suite**

```
cd backend && PYTHONPATH=. .venv/bin/python -m pytest packages/zens/tests/ -v
```

Expected: all green.

- [ ] **Step 5: Update any `config.yaml` lines referencing `response_mode`**

```
cd backend && grep -rn "response_mode" --include="*.yaml" --include="*.yml" .
```

For every match, remove the `response_mode: ...` line (Dify is now always streaming). The router no longer reads it.

- [ ] **Step 6: Commit**

```bash
cd backend && git add packages/zens/zens/community/dify/workflows/ packages/zens/tests/test_dify_workflow_tools.py
git commit -m "refactor(dify): convert 7 workflow tools to async def + English descriptions"
```

---

## Verification Checklist (final)

- [ ] `PYTHONPATH=. .venv/bin/python -m pytest packages/zens/tests/ -v` — all green
- [ ] `python -c "import zens.community.dify.dify_client, zens.community.dify.router; import os; assert not os.path.exists('logs/dify.log'); assert not os.path.exists('logs/dify_aml.log'); print('no file-handler side effects')"` — clean import
- [ ] `grep -rn "addHandler.*dify\|FileHandler.*dify" backend/packages/zens/` — returns nothing
- [ ] `grep -rn "_conversation_ids\|_get_cached_conversation\|_cache_conversation" backend/packages/zens/zens/community/dify/` — returns nothing (no cache)
- [ ] `grep -rn "get_stream_writer\|task_started\|task_running\|task_completed\|task_failed\|task_cancelled" backend/packages/zens/zens/community/dify/` — returns nothing (no event system)
- [ ] `grep -rn "response_mode" backend/ --include="*.yaml" --include="*.yml"` — returns nothing (config field no longer read)
- [ ] Each of the 7 workflow tool files is now an `async def` of ~12 lines
- [ ] `config.yaml` references unchanged: `use: zens.community.dify.workflows.<name>:dify_<name>_tool` resolves to the new async tool

---

## Follow-ups (deferred — not part of this plan)

- **Connection pooling for `DifyClient`**: `astream_chat` opens a fresh `httpx.AsyncClient` per call. A shared client keyed on `(api_key, base_url)` would amortise TLS / connection setup. Out of scope here.
- **Conversation-id persistence (revisit)**: If product later wants Dify-side multi-turn memory, reintroduce the LRU under a feature flag. The router's `_resolve_user` already provides a stable user key; thread_id can come from `runtime.context["thread_id"]` once we adopt `Runtime` injection.
- **`Runtime` injection for state-aware tools**: If a future Dify tool needs to read thread state (e.g. to pass per-thread context into the chatflow), switch to the `Runtime` / `InjectedToolCallId` pattern that `task_tool` and the other built-ins use. For the current 7 tools, stateless is enough.
- **Async fixtures in `conftest.py`**: The new tests use `AsyncMock` directly. If more async tests land in this package, lift the `_make_async_stream_context` helper from `test_dify_astream_chat.py` into `conftest.py`.

---

**Plan complete.**

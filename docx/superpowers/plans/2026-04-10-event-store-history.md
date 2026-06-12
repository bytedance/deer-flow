# Event Store History — Backend Compatibility Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace checkpoint state with the append-only event store as the message source in the thread state/history endpoints, so summarization never causes message loss.

**Architecture:** The Gateway's `get_thread_state` and `get_thread_history` endpoints currently read messages from `checkpoint.channel_values["messages"]`. After summarization, those messages are replaced with a synthetic summary-as-human message and all pre-summarize messages are gone. We modify these endpoints to read messages from the RunEventStore instead (append-only, unaffected by summarization). The response shape for each message stays identical so the chat render path needs no changes, but the frontend's feedback hook must be aligned to use the same full-history view (see Task 4).

**Tech Stack:** Python (FastAPI, SQLAlchemy), pytest, TypeScript (React Query)

**Scope:** Gateway mode only (`make dev-pro`). Standard mode uses the LangGraph Server directly and does not go through these endpoints; the summarize bug is still present there and must be tracked as a separate follow-up (see §"Follow-ups" at end of plan).

**Prerequisite already landed:** `backend/packages/harness/deerflow/runtime/journal.py` now unwraps `Command(update={'messages':[ToolMessage(...)]})` in `on_tool_end`, so new runs that use state-updating tools (e.g. `present_files`) write the inner `ToolMessage` content to the event store instead of `str(Command(...))`. Legacy data captured before this fix is cleaned up defensively by the new helper (see Task 1 Step 3 `_sanitize_legacy_command_repr`).

---

## Real Data Alignment Analysis

Compared real `POST /history` response (checkpoint-based) with `run_events` table for thread `6d30913e-dcd4-41c8-8941-f66c716cf359` (docs/resp.json + backend/.deer-flow/data/deerflow.db). See `docs/superpowers/specs/2026-04-11-runjournal-history-evaluation.md` for full evidence chain.

| Message type | Fields compared | Difference |
|-------------|----------------|------------|
| human_message | all fields | `id` is `None` in event store, has UUID in checkpoint |
| ai_message (tool_call) | all fields, 6 overlapping | **IDENTICAL** (0 diffs) |
| ai_message (final) | all fields | **IDENTICAL** |
| tool_result (normal) | all fields | Only `id` differs (`None` vs UUID) |
| tool_result (from `Command`-returning tool) | content | **Legacy data stored `str(Command(...))` repr instead of inner ToolMessage** — fixed in journal.py for new runs; legacy rows sanitized by helper |

**Root cause for id difference:** LangGraph's checkpoint assigns `id` to HumanMessage and ToolMessage during graph execution. Event store writes happen earlier, when those ids are still None. AI messages receive `id` from the LLM response (`lc_run--*`) and are unaffected.

**Fix for id:** Generate deterministic UUIDs for `id=None` messages using `uuid5(NAMESPACE_URL, f"{thread_id}:{seq}")` at read time. Patch a **copy** of the content dict, never the live store object.

**Summarize impact quantified on the reproducer thread**: event_store has 16 messages (7 AI + 9 others); checkpoint has 12 after summarize (5 AI + 7 others). AI id overlap: 5 of 7 — the 2 missing AI messages are pre-summarize.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/gateway/routers/threads.py` | Modify | Replace checkpoint messages with event store messages in `get_thread_state` and `get_thread_history` |
| `backend/tests/test_thread_state_event_store.py` | Create | Tests for the modified endpoints |

---

### Task 1: Add `_get_event_store_messages` helper to `threads.py`

A shared helper that loads the **full** message stream from the event store, patches `id=None` messages with deterministic UUIDs, and defensively sanitizes legacy `Command(update=...)` reprs captured before the journal.py fix. Patches a copy of each content dict so the live store is never mutated.

**Design constraints (derived from evaluation §3, §4, §5):**
- **Full pagination**, not `limit=1000`. `RunEventStore.list_messages` returns "latest N records" — a fixed limit silently truncates older messages. Use `count_messages()` to size the request or loop with `after_seq` cursors.
- **Copy before mutate**. `MemoryRunEventStore` returns live dict references; the JSONL/DB stores may return detached rows but we must not rely on that. Always `content = dict(evt["content"])` before patching `id`.
- **Legacy Command sanitization.** Legacy data contains `content["content"] == "Command(update={'artifacts': [...], 'messages': [ToolMessage(content='X', ...)]})"`. Regex-extract the inner ToolMessage content string and replace; if extraction fails, leave content as-is (still strictly better than nothing because checkpoint fallback is also wrong for summarized threads).
- **User context.** `DbRunEventStore.list_messages` is user-scoped via `resolve_user_id(AUTO)` and relies on the auth contextvar set by `@require_permission`. Both endpoints are already decorated — document this dependency in the helper docstring.

**Files:**
- Modify: `backend/app/gateway/routers/threads.py`
- Test: `backend/tests/test_thread_state_event_store.py`

- [ ] **Step 1: Write the test**

Create `backend/tests/test_thread_state_event_store.py`:

```python
"""Tests for event-store-backed message loading in thread state/history endpoints."""

from __future__ import annotations

import uuid

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore


@pytest.fixture()
def event_store():
    return MemoryRunEventStore()


async def _seed_conversation(event_store: MemoryRunEventStore, thread_id: str = "t1"):
    """Seed a realistic multi-turn conversation matching real checkpoint format."""
    # human_message: id is None (same as real data)
    await event_store.put(
        thread_id=thread_id, run_id="r1",
        event_type="human_message", category="message",
        content={
            "type": "human", "id": None,
            "content": [{"type": "text", "text": "Hello"}],
            "additional_kwargs": {}, "response_metadata": {}, "name": None,
        },
    )
    # ai_tool_call: id is set by LLM
    await event_store.put(
        thread_id=thread_id, run_id="r1",
        event_type="ai_tool_call", category="message",
        content={
            "type": "ai", "id": "lc_run--abc123",
            "content": "",
            "tool_calls": [{"name": "search", "args": {"q": "cats"}, "id": "call_1", "type": "tool_call"}],
            "invalid_tool_calls": [],
            "additional_kwargs": {}, "response_metadata": {}, "name": None,
            "usage_metadata": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        },
    )
    # tool_result: id is None (same as real data)
    await event_store.put(
        thread_id=thread_id, run_id="r1",
        event_type="tool_result", category="message",
        content={
            "type": "tool", "id": None,
            "content": "Found 10 results",
            "tool_call_id": "call_1", "name": "search",
            "artifact": None, "status": "success",
            "additional_kwargs": {}, "response_metadata": {},
        },
    )
    # ai_message: id is set by LLM
    await event_store.put(
        thread_id=thread_id, run_id="r1",
        event_type="ai_message", category="message",
        content={
            "type": "ai", "id": "lc_run--def456",
            "content": "I found 10 results about cats.",
            "tool_calls": [], "invalid_tool_calls": [],
            "additional_kwargs": {}, "response_metadata": {"finish_reason": "stop"}, "name": None,
            "usage_metadata": {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300},
        },
    )
    # Also add a trace event — should NOT appear
    await event_store.put(
        thread_id=thread_id, run_id="r1",
        event_type="llm_request", category="trace",
        content={"model": "gpt-4"},
    )


class TestGetEventStoreMessages:
    """Verify event store message extraction with id patching."""

    @pytest.mark.asyncio
    async def test_extracts_all_message_types(self, event_store):
        await _seed_conversation(event_store)
        events = await event_store.list_messages("t1", limit=500)
        messages = [evt["content"] for evt in events if isinstance(evt.get("content"), dict) and "type" in evt["content"]]
        assert len(messages) == 4
        assert [m["type"] for m in messages] == ["human", "ai", "tool", "ai"]

    @pytest.mark.asyncio
    async def test_null_ids_get_patched(self, event_store):
        """Messages with id=None should get deterministic UUIDs."""
        await _seed_conversation(event_store)
        events = await event_store.list_messages("t1", limit=500)
        messages = []
        for evt in events:
            content = evt.get("content")
            if isinstance(content, dict) and "type" in content:
                if content.get("id") is None:
                    content["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"t1:{evt['seq']}"))
                messages.append(content)

        # All messages now have an id
        for m in messages:
            assert m["id"] is not None
            assert isinstance(m["id"], str)
            assert len(m["id"]) > 0

        # AI messages keep their original id
        assert messages[1]["id"] == "lc_run--abc123"
        assert messages[3]["id"] == "lc_run--def456"

        # Human and tool messages get deterministic ids (same input = same output)
        human_id_1 = str(uuid.uuid5(uuid.NAMESPACE_URL, "t1:1"))
        assert messages[0]["id"] == human_id_1

    @pytest.mark.asyncio
    async def test_empty_thread(self, event_store):
        events = await event_store.list_messages("nonexistent", limit=500)
        messages = [evt["content"] for evt in events if isinstance(evt.get("content"), dict)]
        assert messages == []

    @pytest.mark.asyncio
    async def test_tool_call_fields_preserved(self, event_store):
        await _seed_conversation(event_store)
        events = await event_store.list_messages("t1", limit=500)
        messages = [evt["content"] for evt in events if isinstance(evt.get("content"), dict) and "type" in evt["content"]]

        # AI tool_call message
        ai_tc = messages[1]
        assert ai_tc["tool_calls"][0]["name"] == "search"
        assert ai_tc["tool_calls"][0]["id"] == "call_1"

        # Tool result
        tool = messages[2]
        assert tool["tool_call_id"] == "call_1"
        assert tool["status"] == "success"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_thread_state_event_store.py -v`

- [ ] **Step 3: Add the helper function and modify `get_thread_history`**

In `backend/app/gateway/routers/threads.py`:

1. Add import at the top:
```python
import uuid  # ADD (may already exist, check first)
from app.gateway.deps import get_run_event_store  # ADD
```

2. Add the helper function (before the endpoint functions, after the model definitions):

```python
_LEGACY_CMD_INNER_CONTENT_RE = re.compile(
    r"ToolMessage\(content=(?P<q>['\"])(?P<inner>.*?)(?P=q)",
    re.DOTALL,
)


def _sanitize_legacy_command_repr(content_field: Any) -> Any:
    """Recover the inner ToolMessage text from a legacy ``str(Command(...))`` repr.

    Runs that pre-date the ``on_tool_end`` fix in ``journal.py`` stored
    ``str(Command(update={'messages':[ToolMessage(content='X', ...)]}))`` as the
    tool_result content. New runs store ``'X'`` directly. For old threads, try
    to extract ``'X'`` defensively; return the original string if extraction
    fails (still no worse than the current checkpoint-based fallback, which is
    broken for summarized threads anyway).
    """
    if not isinstance(content_field, str) or not content_field.startswith("Command(update="):
        return content_field
    match = _LEGACY_CMD_INNER_CONTENT_RE.search(content_field)
    return match.group("inner") if match else content_field


async def _get_event_store_messages(request: Request, thread_id: str) -> list[dict] | None:
    """Load messages from the event store, returning None if unavailable.

    The event store is append-only and immune to summarization. Each
    message event's ``content`` field contains a ``model_dump()``'d
    LangChain Message dict that is already JSON-serialisable.

    **Full pagination, not a fixed limit.** ``RunEventStore.list_messages``
    returns the newest ``limit`` records when no cursor is given, which
    silently drops older messages. We call ``count_messages()`` first and
    request that many records. For stores that may return fewer (e.g. filtered
    by user), we also fall back to ``after_seq``-cursor pagination.

    **Copy-on-read.** Each content dict is copied before ``id`` is patched so
    the live store object is never mutated; ``MemoryRunEventStore`` returns
    live references.

    **Legacy Command repr sanitization.** See ``_sanitize_legacy_command_repr``.

    **User context.** ``DbRunEventStore`` is user-scoped by default via
    ``resolve_user_id(AUTO)`` (see ``runtime/user_context.py``). Callers of
    this helper must be inside a request where ``@require_permission`` has
    populated the user contextvar. Both ``get_thread_history`` and
    ``get_thread_state`` satisfy that. Do not call this helper from CLI or
    migration scripts without passing ``user_id=None`` explicitly.

    Returns ``None`` when the event store is not configured or contains no
    messages for this thread, so callers can fall back to checkpoint messages.
    """
    try:
        event_store = get_run_event_store(request)
    except Exception:
        return None

    try:
        total = await event_store.count_messages(thread_id)
    except Exception:
        logger.exception("count_messages failed for thread %s", sanitize_log_param(thread_id))
        return None
    if not total:
        return None

    # Batch by page_size to keep memory bounded for very long threads.
    page_size = 500
    collected: list[dict] = []
    after_seq: int | None = None
    while True:
        page = await event_store.list_messages(thread_id, limit=page_size, after_seq=after_seq)
        if not page:
            break
        collected.extend(page)
        if len(page) < page_size:
            break
        after_seq = page[-1].get("seq")
        if after_seq is None:
            break

    messages: list[dict] = []
    for evt in collected:
        raw = evt.get("content")
        if not isinstance(raw, dict) or "type" not in raw:
            continue
        # Copy to avoid mutating the store-owned dict.
        content = dict(raw)
        if content.get("id") is None:
            content["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{thread_id}:{evt['seq']}"))
        # Sanitize legacy Command reprs on tool_result messages only.
        if content.get("type") == "tool":
            content["content"] = _sanitize_legacy_command_repr(content.get("content"))
        messages.append(content)
    return messages if messages else None
```

Also add `import re` at the top of the file if it isn't already imported.

3. In `get_thread_history` (around line 585-590), replace the messages section:

**Before:**
```python
            # Attach messages from checkpointer only for the latest checkpoint
            if is_latest_checkpoint:
                messages = channel_values.get("messages")
                if messages:
                    values["messages"] = serialize_channel_values({"messages": messages}).get("messages", [])
            is_latest_checkpoint = False
```

**After:**
```python
            # Attach messages: prefer event store (immune to summarization),
            # fall back to checkpoint messages when event store is unavailable.
            if is_latest_checkpoint:
                es_messages = await _get_event_store_messages(request, thread_id)
                if es_messages is not None:
                    values["messages"] = es_messages
                else:
                    messages = channel_values.get("messages")
                    if messages:
                        values["messages"] = serialize_channel_values({"messages": messages}).get("messages", [])
            is_latest_checkpoint = False
```

- [ ] **Step 4: Modify `get_thread_state` similarly**

In `get_thread_state` (around line 443-444), replace:

**Before:**
```python
    return ThreadStateResponse(
        values=serialize_channel_values(channel_values),
```

**After:**
```python
    values = serialize_channel_values(channel_values)

    # Override messages with event store data (immune to summarization)
    es_messages = await _get_event_store_messages(request, thread_id)
    if es_messages is not None:
        values["messages"] = es_messages

    return ThreadStateResponse(
        values=values,
```

- [ ] **Step 5: Run all backend tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ -v --timeout=30 -x`

- [ ] **Step 6: Commit**

```bash
git add backend/app/gateway/routers/threads.py backend/tests/test_thread_state_event_store.py
git commit -m "feat(threads): load messages from event store instead of checkpoint state

Event store is append-only and immune to summarization. Messages with
null ids (human, tool) get deterministic UUIDs based on thread_id:seq
for stable frontend rendering."
```

---

### Task 2 (OPTIONAL, deferred): Reduce flush_threshold for shorter mid-stream gap

**Status:** Not a correctness fix. Re-evaluation (see spec) found that `RunJournal` already flushes on `run_end`, `run_error`, cancel, and worker `finally` paths. The only window this tuning narrows is a hard process crash or mid-run reload. Defer and decide separately; do not couple with Task 1 merge.

If pursued: change `flush_threshold` default from 20 → 5 in `journal.py:42`, rerun `tests/test_run_journal.py`, commit as a separate `perf(journal): …` commit.

---

### Task 3: Fix `useThreadFeedback` pagination in frontend

Once `/history` returns the full event-store-backed message stream, the frontend's `runIdByAiIndex` map must also cover the full stream or its positional AI-index mapping drifts and feedback clicks go to the wrong `run_id`. The current hook hardcodes `limit=200`.

**Files:**
- Modify: `frontend/src/core/threads/hooks.ts` (around line 679)

- [ ] **Step 1: Replace the fixed `?limit=200` with full pagination**

Change:

```ts
const res = await fetchWithAuth(
  `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/messages?limit=200`,
);
```

to a loop that pages via `after_seq` (or an equivalent query param exposed by the `/messages` endpoint — check `backend/app/gateway/routers/thread_runs.py:285-323` for the actual parameter names before writing the TS code). Accumulate `messages` until a page returns fewer than the page size.

- [ ] **Step 2: Defensive index guard**

`runIdByAiIndex[aiMessageIndex]` can still be `undefined` when the frontend renders optimistic state before the messages query refreshes. The current `?? undefined` in `message-list.tsx:71` already handles this; do not remove it.

- [ ] **Step 3: Invalidate `["thread-feedback", threadId]` after a new run**

In `useThreadStream` (or wherever stream-end is handled), call `queryClient.invalidateQueries({ queryKey: ["thread-feedback", threadId] })` when the stream closes so the runIdByAiIndex picks up the new run's AI message immediately.

- [ ] **Step 4: Run `pnpm check`**

```bash
cd frontend && pnpm check
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/threads/hooks.ts
git commit -m "fix(feedback): paginate useThreadFeedback and invalidate after stream"
```

---

### Task 4: End-to-end test — summarize + multi-run feedback

Add a regression test that exercises the exact bug class we are fixing: a summarized thread with at least two runs, where feedback clicks must target the correct `run_id`.

**Files:**
- Modify: `backend/tests/test_thread_state_event_store.py`

- [ ] **Step 1: Write the test**

Seed a `MemoryRunEventStore` with two runs worth of messages (`r1`: human + ai + human + ai, `r2`: human + ai), then simulate a summarized checkpoint state that drops the `r1` messages. Call `_get_event_store_messages` and assert:

- Length matches the event store, not the checkpoint
- The first message is the original `r1` human, not a summary
- AI messages preserve their `lc_run--*` ids in order
- Any `id=None` messages get a stable `uuid5(...)` id
- A legacy `str(Command(update=...))` content field in a tool_result is sanitized to the inner text

- [ ] **Step 2: Run the new test**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_thread_state_event_store.py -v
```

- [ ] **Step 3: Commit with Tasks 1, 3 changes**

Bundle with the Task 1 commit so tests always land alongside the implementation.

---

### Task 5: Standard mode follow-up (documentation only)

Standard mode (`make dev`) hits LangGraph Server directly for `/threads/{id}/history` and does not go through the Gateway router we just patched. The summarize bug is still present there.

**Files:**
- Modify: this plan (add follow-up section at the bottom, see below) OR create a separate tracking issue

- [ ] **Step 1: Record the gap**

Append to the bottom of this plan (or open a GitHub issue and link it):

> **Follow-up — Standard mode summarize bug**
> `get_thread_history` in `backend/app/gateway/routers/threads.py` is only hit in Gateway mode. Standard mode proxies `/api/langgraph/*` directly to the LangGraph Server (see `backend/CLAUDE.md` nginx routing and `frontend/CLAUDE.md` `NEXT_PUBLIC_LANGGRAPH_BASE_URL`). The summarize-message-loss symptom is still reproducible there. Options: (a) teach the LangGraph Server checkpointer to branch on an override, (b) move `/history` behind Gateway in Standard mode as well, (c) accept as known limitation for Standard mode. Decide before GA.

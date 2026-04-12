# Summarize Marker in History — Design & Verification

**Date**: 2026-04-11
**Branch**: `rayhpeng/fix-persistence-new`
**Status**: Design approved, implementation deferred to a follow-up PR
**Depends on**: [`2026-04-11-runjournal-history-evaluation.md`](./2026-04-11-runjournal-history-evaluation.md) (the event-store-backed history fix this builds on)

---

## 1. Goal

Display a "summarization happened here" marker in the conversation history UI when `SummarizationMiddleware` ran mid-run, so users understand why earlier messages look condensed or missing. The event-store-backed `/history` fix already recovered the original messages; this spec adds a **visible marker** at the seq position where summarization occurred, optionally showing the generated summary text.

## 2. Investigation findings

### 2.1 Today's state: zero middleware records

Full scan of `backend/.deer-flow/data/deerflow.db` `run_events`:

| category | rows |
|---|---:|
| trace | 76 |
| message | 34 |
| lifecycle | 8 |
| **middleware** | **0** |

No row has `event_type` containing `summariz` or `middleware`. The middleware category is dead in production.

### 2.2 Why: two dead code paths in `journal.py`

| Location | Status |
|---|---|
| `journal.py:343-362` — `on_custom_event("summarization", ...)` writes one trace event + one `category="middleware"` event. | Dead. Only fires when something calls `adispatch_custom_event("summarization", {...})`. The upstream LangChain `SummarizationMiddleware` (`.venv/.../langchain/agents/middleware/summarization.py:272`) **never emits custom events** — its `before_model`/`abefore_model` just mutate messages in place and return `{'messages': new_messages}`. Callback never triggered. |
| `journal.py:449` — `record_middleware(tag, *, name, hook, action, changes)` helper | Dead. Grep shows zero callers in the harness. Added speculatively, never wired up. |

### 2.3 Concrete evidence of summarize running unlogged

Thread `3d5dea4a-0983-4727-a4e8-41a64428933a`:

- `run_events` seq=1 → original human `"写一份关于deer-flow的详细技术报告"` ✓ (event store is fine)
- `run_events` seq=43 → `llm_request` trace whose `messages[0]` literal contains `"Here is a summary of the conversation to date:"` — proof that SummarizationMiddleware did inject a summary mid-run
- Zero rows with `category='middleware'` for this thread → nothing captured for UI to render

## 3. Approaches considered

### A. Subclass `SummarizationMiddleware` and dispatch a custom event

Wrap the upstream class, override `abefore_model`, call `await adispatch_custom_event("summarization", {...})` after super(). Journal's existing `on_custom_event` path captures it.

### B. Frontend-only diff heuristic

Compare `event_store.count_messages()` vs rendered count, infer summarization happened from the gap. **Rejected**: can't pinpoint position in the stream, can't show summary text. Only yields a vague badge.

### C. Hybrid A + frontend inline card rendered at the middleware event's seq position

Same backend as A, plus frontend renders an inline `[N messages condensed]` card at the correct chronological position. **Recommended terminal state**.

## 4. Subagent's wrong claim and its rebuttal

An independent agent flagged approach A as structurally broken because:

> `RunnableCallable(trace=False)` skips `set_config_context`, therefore `var_child_runnable_config` is never set, therefore `adispatch_custom_event` raises `RuntimeError("Unable to dispatch an adhoc event without a parent run id")`.

**This is wrong.** The user's counter-intuition was correct: `trace=False` does not prevent `adispatch_custom_event` from working, as long as the middleware signature explicitly accepts `config: RunnableConfig`. The mechanism:

1. `RunnableCallable.__init__` (`langgraph/_internal/_runnable.py:293-319`) inspects the function signature. If it accepts `config: RunnableConfig`, that parameter is recorded in `self.func_accepts`.
2. Both `trace=True` and `trace=False` branches of `ainvoke` run the same kwarg-injection loop (`_runnable.py:349-356`): `if kw == "config": kw_value = config`. The `config` passed to `ainvoke` (from Pregel's `task.proc.ainvoke(task.input, config)` at `pregel/_retry.py:138`) is the task config with callbacks already bound.
3. Inside the middleware, passing that `config` explicitly to `adispatch_custom_event(..., config=config)` means the function doesn't rely on `var_child_runnable_config.get()` at all. The LangChain docstring at `langchain_core/callbacks/manager.py:2574-2579` even says "If using python 3.10 and async, you MUST specify the config parameter" — which is exactly this path.

`trace=False` only changes whether **this runnable layer creates a new child callback scope**. It does not affect whether the outer-layer config (with callbacks including `RunJournal`) is passed down to the function.

## 5. Verification

Ran `/tmp/verify_summarize_event.py` (standalone minimal reproduction):

- Minimal `AgentMiddleware` subclass with `abefore_model(self, state, runtime, config: RunnableConfig)`
- Calls `await adispatch_custom_event("summarization", {...}, config=config)` inside
- `create_agent(model=FakeChatModel, middleware=[probe])`
- `agent.ainvoke({...}, config={"callbacks": [RecordingHandler()]})`

**Result**:

```
INFO verify: ProbeMiddleware.abefore_model called
INFO verify:   config keys: ['callbacks', 'configurable', 'metadata']
INFO verify:   config.callbacks type: AsyncCallbackManager
INFO verify:   config.metadata: {'langgraph_step': 1, 'langgraph_node': 'probe.before_model', ...}
INFO verify: on_custom_event fired: name=summarization
             run_id=019d7d19-1727-7830-aa33-648ecbee4b95
             data={'summary': 'fake summary', 'replaced_count': 3}
SUCCESS: approach A is viable (config injection + adispatch work)
```

All five predictions held:

1. ✅ `config: RunnableConfig` signature triggers auto-injection despite `trace=False`
2. ✅ `config.callbacks` is an `AsyncCallbackManager` with `parent_run_id` set
3. ✅ `adispatch_custom_event(..., config=config)` runs without error
4. ✅ `RecordingHandler.on_custom_event` receives the event
5. ✅ The received `run_id` is a valid UUID tied to the running graph

**Bonus finding**: `config.metadata` contains `langgraph_step` and `langgraph_node`. These can be included in the middleware event's metadata to help the frontend position the marker on the timeline.

## 6. Recommended implementation (approach C)

### 6.1 Backend

**New wrapper middleware** in `backend/packages/harness/deerflow/agents/lead_agent/agent.py`:

```python
from langchain.agents.middleware.summarization import SummarizationMiddleware
from langchain_core.callbacks import adispatch_custom_event
from langchain_core.runnables import RunnableConfig


class _TrackingSummarizationMiddleware(SummarizationMiddleware):
    """Wraps upstream SummarizationMiddleware to emit a ``summarization``
    custom event on every actual summarization, so RunJournal can persist
    a middleware:summarize row to the event store.

    The upstream class does not emit events of its own. Declaring
    ``config: RunnableConfig`` in the override lets LangGraph's
    ``RunnableCallable`` inject the Pregel task config (with callbacks
    and parent_run_id) regardless of ``trace=False`` on the node.
    """

    async def abefore_model(self, state, runtime, config: RunnableConfig):
        before_count = len(state.get("messages") or [])
        result = await super().abefore_model(state, runtime)
        if result is None:
            return None

        new_messages = result.get("messages") or []
        replaced_count = max(0, before_count - len(new_messages))
        summary_text = _extract_summary_text(new_messages)

        await adispatch_custom_event(
            "summarization",
            {
                "summary": summary_text,
                "replaced_count": replaced_count,
            },
            config=config,
        )
        return result


def _extract_summary_text(messages: list) -> str:
    """Pull the summary string out of the HumanMessage the upstream class
    injects as ``Here is a summary of the conversation to date:...``."""
    for msg in messages:
        if getattr(msg, "type", None) == "human":
            content = getattr(msg, "content", "")
            text = content if isinstance(content, str) else ""
            if text.startswith("Here is a summary of the conversation to date"):
                return text
    return ""
```

Swap the existing `SummarizationMiddleware()` instantiation in `_build_middlewares` for `_TrackingSummarizationMiddleware(...)` with the same args.

**Journal change**: **zero**. `on_custom_event("summarization", ...)` in `journal.py:343-362` already writes both a trace and a `category="middleware"` row.

**History helper change**: extend `_get_event_store_messages` in `backend/app/gateway/routers/threads.py` to surface `category="middleware"` rows as pseudo-messages, e.g.:

```python
# In the per-event loop, after the existing message branch:
if evt.get("category") == "middleware" and evt.get("event_type") == "middleware:summarize":
    meta = evt.get("metadata") or {}
    messages.append({
        "id": f"summary-marker-{evt['seq']}",
        "type": "summary_marker",
        "replaced_count": meta.get("replaced_count", 0),
        "summary": (raw or {}).get("content", "") if isinstance(raw, dict) else "",
        "run_id": evt.get("run_id"),
    })
```

The marker uses a sentinel `type` (`summary_marker`) that doesn't collide with any LangChain message type, so downstream consumers that loop over messages can skip or render it explicitly.

### 6.2 Frontend

- `core/messages/utils.ts`: extend the message grouping to recognize `type === "summary_marker"` and yield it as its own group (`"assistant:summary-marker"`)
- `components/workspace/messages/message-list.tsx`: add a branch in the grouped render switch that renders a distinctive inline card showing `N messages condensed` and a collapsible panel with the summary text
- No changes to feedback logic: the marker has no `feedback` field so the button naturally doesn't render on it

## 7. Risks

1. **Synchronous path**. The upstream class has both `before_model` and `abefore_model`. Our wrapper only overrides the async variant. If any deer-flow code path ever uses the sync flow, those summarizations won't be captured. Mitigation: also override `before_model` and use `dispatch_custom_event` (sync variant) with the same pattern.
2. **`_extract_summary_text` fragility**. It depends on the upstream class prefix `"Here is a summary of the conversation to date"` in the injected `HumanMessage`. Any upstream template change breaks detection. Mitigation: pick the first new `HumanMessage` that wasn't in `state["messages"]` before super() — resilient to template wording changes at the cost of a small diff helper.
3. **`replaced_count` accuracy when concurrent updates**. If another middleware in the chain also modifies `state["messages"]` before super() returns, the naive `before_count - len(new_messages)` arithmetic is wrong. Mitigation: inspect the `RemoveMessage(id=REMOVE_ALL_MESSAGES)` that upstream emits and count from the original input list directly.
4. **History helper contract change**. Introducing a non-LangChain-typed entry (`type="summary_marker"`) in the `/history` response could break frontend code that blindly casts entries to `Message`. Mitigation: the frontend change above adds an explicit branch; type-check the frontend end-to-end before merging.

## 8. Out of scope / deferred

- Other middleware types (Title, Guardrail, HITL) do not emit custom events either. If we want markers for those too, repeat the wrapper pattern for each. Not in this design.
- Retroactive markers for old threads (captured before this patch) are impossible without re-running the graph. Legacy threads will show the event-store-recovered messages without a marker.
- Standard mode (`make dev`) — agent runs inside LangGraph Server, not the Gateway-embedded runtime. `RunJournal` may not be wired there, so the custom event fires but is captured by no one. Tracked as a separate follow-up.

## 9. Next actions

1. Land the current summarize-message-loss fixes (journal `Command` unwrap + event-store-backed `/history` + inline feedback) — implementation verified, being committed now as three commits on `rayhpeng/fix-persistence-new`
2. Summarize-marker implementation (this spec) → separate follow-up PR based on the above verified design

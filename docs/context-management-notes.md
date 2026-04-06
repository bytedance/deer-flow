# DeerFlow Context Management Notes

This document records the current layered context-management approach we added locally while debugging long, tool-heavy DeerFlow runs.

It is meant as an engineering handoff note:
- what each layer does
- why it exists
- where the logic lives
- which bugs were fixed while iterating
- what is still heuristic / not fully solved

## Overview

The current design is a progressive pipeline rather than a single summarization step.

From cheapest to heaviest, the layers are:

1. `Tool Result Budget`
2. `Snip`
3. `Microcompact`
4. `Session-State Collapse`
5. `Summarization`
6. `Deliverable Guard`

The key idea is:
- remove or externalize noisy tool output first
- preserve a compact structured execution state
- only then rely on heavier summarization
- keep output contracts enforced even after compaction

## 1. Tool Result Budget

Purpose:
- prevent oversized tool outputs from flooding the live prompt

Current behavior:
- small tool results stay inline
- oversized tool results are externalized under `outputs/.context/tool-results`
- the prompt only keeps a preview plus a path hint

Current coverage:
- `bash`
- `read_file`
- `web_search`
- `web_fetch`
- MCP tools such as `x-reader`

Key code:
- [tool_output_budget.py](/root/deer-flow/backend/packages/harness/deerflow/context/tool_output_budget.py)
- [sandbox/tools.py](/root/deer-flow/backend/packages/harness/deerflow/sandbox/tools.py)
- [mcp/tools.py](/root/deer-flow/backend/packages/harness/deerflow/mcp/tools.py)
- web providers under:
  - [firecrawl/tools.py](/root/deer-flow/backend/packages/harness/deerflow/community/firecrawl/tools.py)
  - [infoquest/tools.py](/root/deer-flow/backend/packages/harness/deerflow/community/infoquest/tools.py)
  - [jina_ai/tools.py](/root/deer-flow/backend/packages/harness/deerflow/community/jina_ai/tools.py)
  - [tavily/tools.py](/root/deer-flow/backend/packages/harness/deerflow/community/tavily/tools.py)
  - [ddg_search/tools.py](/root/deer-flow/backend/packages/harness/deerflow/community/ddg_search/tools.py)

Important later fixes:
- provider `web_fetch` paths were changed so budgeting happens before artificial 4096-char truncation
- MCP `content_and_artifact` tuple results are now preserved correctly; only the `content` half is budgeted
- `storage_subdir` is now sanitized so externalization cannot escape the thread output directory

## 2. Snip

Purpose:
- remove low-value, reconstructable prompt noise without summarizing

Current behavior:
- strips historical `<uploaded_files>` blocks from older human turns

Key code:
- [context_compaction_middleware.py](/root/deer-flow/backend/packages/harness/deerflow/agents/middlewares/context_compaction_middleware.py)

Why this exists:
- upload bookkeeping can accumulate over long threads
- it costs tokens but adds little reasoning value after the first few turns

## 3. Microcompact

Purpose:
- compress older verbose tool results while keeping recent working context intact

Current behavior:
- preserves the most recent N results for configured noisy tools
- replaces older `ToolMessage` content with a short placeholder
- does not break tool-call / tool-result pairing

Current tool focus:
- `bash`
- `read_file`
- `web_search`
- `web_fetch`
- `x-reader_read_url`
- `x-reader_read_batch`

Key code:
- [context_compaction_middleware.py](/root/deer-flow/backend/packages/harness/deerflow/agents/middlewares/context_compaction_middleware.py)
- [context_management_config.py](/root/deer-flow/backend/packages/harness/deerflow/config/context_management_config.py)

Why this exists:
- old tool outputs are high token cost and low marginal value
- long runs were previously dominated by stale tool history

## 4. Session-State Collapse

Purpose:
- preserve the thread’s execution state in structured form so long runs do not rely only on raw historical turns

Current `session_state` fields:
- `current_goal`
- `task_contract`
- `active_todos`
- `recent_artifacts`
- `last_assistant_response`

Current `task_contract` fields:
- `original_request`
- `active_request`
- `deliverable`
- `output_format`
- `scope`
- `quality_bar`
- `must_save_output`
- `must_present_output`

Key code:
- [session_state_middleware.py](/root/deer-flow/backend/packages/harness/deerflow/agents/middlewares/session_state_middleware.py)
- [thread_state.py](/root/deer-flow/backend/packages/harness/deerflow/agents/thread_state.py)

Key behavior:
- session state is now persisted before summarization can trim away raw user requests
- session state is also re-injected into the prompt for longer threads
- contract fields are preserved as structured state, not only natural-language reminders

Important later fixes:
- original task contracts are sticky and not overwritten by empty later snapshots
- later user requirements can override the active deliverable contract without erasing the original request
- contract inference became clause-level and more conservative
  - distinguishes input references like `read this markdown file`
  - from output requirements like `generate an HTML report`
- the middleware now captures state in `before_model`, not only `after_agent`
  - this is critical because otherwise summarization may erase the original request before session state is saved

Why this exists:
- summarization alone was too lossy for complex threads
- file-format requirements like `HTML report` were drifting or disappearing during long runs

## 5. Summarization

Purpose:
- last heavier context reduction step when the thread is still too large

Current behavior:
- DeerFlow still uses LangChain / LangGraph summarization middleware
- now it runs after low-cost compaction and after session state has already been captured

Key code:
- [agent.py](/root/deer-flow/backend/packages/harness/deerflow/agents/lead_agent/agent.py)

Important change from the original flow:
- before this work, summarization happened too early relative to durable session-state capture
- now session state is persisted first, so summarization is less likely to erase the task contract

## 6. Deliverable Guard

Purpose:
- stop the model from finishing early with the wrong artifact or no artifact

Current behavior:
- after a final AI response with no tool calls, the middleware checks whether the required deliverable contract is actually satisfied
- if not, it injects a `<deliverable_guard>` reminder and forces execution back to `model`

Key code:
- [deliverable_guard_middleware.py](/root/deer-flow/backend/packages/harness/deerflow/agents/middlewares/deliverable_guard_middleware.py)

Supported output formats:
- `html`
- `markdown`
- `pptx`
- `docx`
- `pdf`
- `image`
- `csv`
- `json`

Important later fixes:
- guard is no longer one-shot
- guard now uses `jump_to="model"` so the run actually continues
- guard contract derivation no longer silently depends on `session_state.enabled`
- guard can derive a contract directly from message history via `build_task_contract_snapshot(...)`

Why this exists:
- long runs often completed with `.md` even when the user asked for `.html`
- compaction reduced context pressure, but without a completion guard the model could still end on the wrong artifact

## Middleware Order

Current intended order inside the lead agent:

1. runtime middlewares
2. `ContextCompactionMiddleware`
3. `SessionStateMiddleware`
4. `SummarizationMiddleware`
5. `DeliverableGuardMiddleware`
6. todo / title / memory / other existing middlewares

Relevant code:
- [agent.py](/root/deer-flow/backend/packages/harness/deerflow/agents/lead_agent/agent.py)

Rationale:
- cheap cleanup first
- durable state capture before summarization
- completion enforcement after the model attempts to finish

## Important Bugs Fixed During Iteration

### A. Deliverable guard was one-shot

Symptom:
- the model could ignore the first reminder and then finish successfully on the next final response

Fix:
- removed the one-shot short-circuit
- the guard now re-checks after guarded retries

### B. Deliverable guard reminder did not actually continue execution

Symptom:
- a reminder was appended, but the run still stopped

Fix:
- `after_model()` now returns `jump_to="model"`

### C. Session state was captured too late

Symptom:
- long threads got summarized before `task_contract` was durably stored
- final state lost `HTML report` contracts

Fix:
- capture / merge `session_state` in `before_model`
- move `SessionStateMiddleware` before summarization

### D. Session state could be wiped by empty later snapshots

Symptom:
- after long runs or meta follow-up turns, `task_contract` and `current_goal` became `None`

Fix:
- sticky merge semantics
- preserve durable contract and active request unless a new explicit contract replaces them

### E. Contract inference was too broad

Symptom:
- incidental mentions like `read this markdown file` could be misread as “must produce a markdown file”

Fix:
- clause-level, conservative inference
- explicit output intent required for hard deliverable contracts

### F. MCP budgeting broke `content_and_artifact` tools

Symptom:
- `x-reader_read_url` started failing with
  `response_format='content_and_artifact' expected tuple, got str`

Fix:
- budget only the first tuple element and preserve artifact payloads unchanged

### G. Externalization path safety

Symptom:
- `storage_subdir` could theoretically point outside the thread output directory

Fix:
- sanitize `storage_subdir`
- require relative, traversal-free path components

## What This Design Is Good At

- long tool-heavy runs with lots of `bash`, `read_file`, and web/MCP output
- preserving explicit deliverable requirements like `HTML report`
- keeping a compact execution state after historical trimming
- avoiding prompt blowups from old tool results

## What Is Still Heuristic / Incomplete

- task contract inference is still rule-based, not a true semantic parser
- session-history collapse content quality still depends on simple extraction logic
- tool failure recovery is still uneven across providers
- some long-run behavior is still shaped by model tendencies, not only middleware logic

This is substantially better than the original “late summarization plus basic truncation” flow, but it is still an engineering-first system, not a formally complete planning / execution architecture.

## Recommended Debugging Checklist

When a future long-run bug appears, check these in order:

1. Did `session_state.task_contract` survive into the final checkpoints?
2. Did `DeliverableGuardMiddleware` actually fire?
3. Did the thread produce the expected artifact extension?
4. Did a tool wrapper change the shape of a provider-specific return value?
5. Was the context blowup dominated by tool output, or by conversational history?
6. Did summarization run before durable state capture?

Useful runtime data sources:
- thread directory under `/root/deer-flow/backend/.deer-flow/threads/<thread_id>/`
- checkpoint DB at `/root/deer-flow/backend/.deer-flow/checkpoints.db`
- [langgraph.log](/root/deer-flow/logs/langgraph.log)
- [gateway.log](/root/deer-flow/logs/gateway.log)

## Relevant Tests

Primary regression coverage currently lives in:
- [test_context_compaction_middleware.py](/root/deer-flow/backend/tests/test_context_compaction_middleware.py)
- [test_session_state_middleware.py](/root/deer-flow/backend/tests/test_session_state_middleware.py)
- [test_deliverable_guard_middleware.py](/root/deer-flow/backend/tests/test_deliverable_guard_middleware.py)
- [test_tool_result_budget.py](/root/deer-flow/backend/tests/test_tool_result_budget.py)
- [test_mcp_sync_wrapper.py](/root/deer-flow/backend/tests/test_mcp_sync_wrapper.py)

## Current Summary

The current DeerFlow context-management approach is:

- reduce large tool outputs first
- trim low-value bookkeeping
- compact stale tool history
- preserve structured execution state early
- summarize only after durable state capture
- enforce deliverable contracts at completion time

That combination is what currently keeps long DeerFlow runs materially more stable than the original implementation.

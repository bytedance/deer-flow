# Context, Goals and Agent Decisions

## Session Goals

Use `/goal <completion condition>` to attach one active completion condition to the current thread. The goal is thread-scoped state, not a skill activation, so it stays active across turns until DeerFlow determines it has been satisfied or you clear it. The agent sees the active goal on every model call, so it keeps working toward it after context compaction removes the message that stated it.

Supported commands:

```text
/goal finish the implementation and make all tests pass
/goal              # show the active goal
/goal clear        # clear it
```

After each Gateway-backed run, DeerFlow evaluates the visible conversation, including the assistant's tool calls and shortened tool results, against the active goal with a non-thinking evaluator model. A successful tool result alone does not satisfy a goal, and when the assistant had to guess missing or ambiguous information the evaluator reports `needs_user_input`. The evaluator must return a typed blocker (`missing_evidence`, `needs_user_input`, `run_failed`, `external_wait`, or `goal_not_met_yet`) plus visible evidence. DeerFlow only injects a hidden continuation when the latest assistant turn is durably checkpointed, the blocker is `goal_not_met_yet`, the thread did not change during evaluation, and the no-progress breaker has not fired. The safety cap defaults to 8 hidden continuations, and repeated identical non-progress evaluations stop after 2 attempts. `/goal clear` and any user-authored new input win over queued continuations. When the evaluator considers the goal satisfied, DeerFlow clears it after the run successfully finalizes and publishes the updated thread state. The same checkpoint records the completion as `goal_outcome`, which stays until the next goal change. If required artifact delivery or its receipt persistence fails, the run reports an error and the goal remains active for a later retry; this does not start another hidden continuation.

The evaluator keeps recent work and the latest user request within a fixed evidence budget, using spare room to retain more of long user input.
If a normally completed evaluator response has an invalid verdict format, DeerFlow evaluates the same evidence once more unless you cancel or change the thread. Both calls are counted; a second failure stops automatic continuation without repeating the task or its tools.

For tool-using turns, successful operation results drive the no-progress count: changing only reply wording or a sandbox tool's UI explanation does not reset it, while newly observed work can keep it going. Text-only turns keep their reply-based check. An unmet goal still stops automatic continuation after a token or loop-detection hard stop, or when the run reaches its step limit, and stays active for a later user turn.

Regenerating an earlier response keeps the goal currently set for the chat and its used continuation budget. It does not restore a goal that was cleared or achieved. The earlier answer's completion record is removed when its historical checkpoint is replayed.

The Web UI shows the active goal above the composer, says why auto-continue stopped, and shows a "Goal met" notice after a goal is met. Editing the last message is off while a goal is set. The same command is available from the TUI and supported IM channels. In IM, `/goal` also says whether the goal is in progress, why auto-continue stopped, or that it was met (until the next goal change), in the binding owner's web UI language (else `channel_connections.notification_locale`). In the Web UI and supported IM channels, setting `/goal <completion condition>` also starts a run with the condition as the task; status and clear commands only manage goal state. Setting or clearing a goal is rejected while that thread has a run in flight, including a run owned by another Gateway worker, so the goal checkpoint cannot branch away from an active run's checkpoint lineage. IM replies explain this rejection and ask you to wait for the task to finish; the goal stays unchanged and the rejected command is not retried automatically.

When your role lacks `runs:create`, the Web UI rejects a new task or `/goal <completion condition>` before preparing the thread or saving the goal, and keeps your draft for retry. Goal status, goal clearing, and `/compact` remain governed by their own endpoint permissions.

## Manual Context Compaction

Automatic and manual compaction process all selected history in chronological
chunks before replacing it. `summarization.trim_tokens_to_summarize` bounds raw
input per step; generated summaries use at most half to leave room for source.
The built-in summary prompt asks the model to preserve active user requirements
and approval conditions. Set `summarization.summary_prompt` to supply a custom template.
Oversized summaries retain marked head/tail text; raw history is never clipped.
Native document titles, context and direct plain-text bodies are included in the
summary input. Binary documents and remote media are not decoded or fetched;
nested document blocks are not traversed.
A pass is limited to 64 chunks and leaves history unchanged on failure or limit
exhaustion. A limit breach starts a five-minute per-process cooldown for the
same thread/history window and policy, including rebuilt middleware. A larger
input budget or smaller source window permits an immediate retry. Model fallback
and SDK retries can add calls. For vLLM run models, history and retention
estimates include assistant reasoning replayed to the provider. See the
[summarization guide](../../backend/docs/summarization.md).

With `task_continuity.enabled`, `history_search` searches the current task's active
and compacted history. Its optional `role` accepts `user`, `assistant`, or `tool`
and filters before limiting results to eight distinct sources. Omitting `role` or
passing `null` preserves search across all roles. Repeated archives of one source
share one result slot.
Search excerpts contain at most 600 characters around the earliest locatable
matching occurrence that fits and include `excerpt_start` / `excerpt_end`, a
zero-based, half-open character range
in the original source. Oversized occurrences are skipped in favor of later fitting
matches. If no complete matching occurrence can be located within the excerpt,
the excerpt falls back to the source opening with
`excerpt_match=false`. Pass the start as the `offset` to
`history_read` to continue reading.
Use `history_read` to verify the original source;
historical user messages do not grant current authorization. See
[task continuity](../../docs/task-continuity.md).

Automatic and manual compaction exclude old todo reminder messages from both the
summary input and retained context. The current todo list stays in thread state.
Manual thread-state updates and run input must send it as a list of objects with
string `content` and a `pending` / `in_progress` / `completed` status (a missing
status defaults to `pending`); another shape is rejected with HTTP 400, and an
already-stored entry of an unusable shape is ignored instead of failing the model
call.
In planning mode, if the original `write_todos` call is no longer visible,
DeerFlow adds a reminder using the latest task statuses before the next model
call. Skipped or failed compaction leaves the existing messages unchanged.
When loop detection, the run token budget, or a provider safety/output-length
limit stops a run, unfinished todos are retained for a later user run; todo
completion reminders do not restart model calls or tool execution after that stop.
Safety-stopped partial text is preserved; it does not trigger a Todo retry.
A provider safety or output-length stop applies to the response it ended: if an
unmet goal continues the run, later continuation turns still get todo reminders.

Optional `pii_redaction.enabled` redacts detected identifiers in user messages,
remote tool results, compaction input, reinjected summaries, configured
LLM title input, and the `/goal` evaluator's input. Memory admission,
including pre-compaction flushes, also redacts
detected identifiers in supported text/JSON content, parsed and invalid call arguments/error text,
provider-raw/legacy function calls and supported user-content provenance.
It is off by default; enabled deployments supply a secret for stable, keyed
value-derived placeholders. No token-to-raw mapping is persisted. Raw thread
text and local fallback titles remain available for display; memory redaction
copies messages without changing the caller's history or tool execution.
For SDK agents without a checkpointer, deeply nested JSON tool arguments do not
prevent memory admission, with PII redaction either enabled or disabled.
Structured JSON content blocks still use recursive redaction and remain depth-limited.
The hidden `/goal` continuation is redacted before it is stored.

The Web UI preserves persisted message order when merging history with live updates. Streaming steps around a persisted result inside the loaded history stay together, including steps that arrive after the result. Steps captured during compaction also remain visible before their persisted result when history has not refreshed and the UI has not rendered them yet.

Compaction keeps the current user request and summarizes older assistant/tool activity. When rescuing that request leaves an assistant/tool-only summary window, input trimming favors its most recent content. For mixed histories whose user-message anchor falls outside the trimming budget, compaction retains the existing final-message fallback. `summarization.trim_tokens_to_summarize` (4000 by default) controls trimming of the raw summary input; escaping and prompt formatting add overhead beyond that budget. Setting this option to `null` disables input trimming for the summary model; choose that only when the model can accept the full history being compacted.

If the same rendered summary prompt and model candidates recur, DeerFlow reuses the existing summary when the first candidate previously returned it unchanged. An unchanged fallback response is not cached, so reuse cannot prevent the primary model from being retried after an invocation failure. Cache failures fall back to normal generation. See [summarization telemetry](../../backend/docs/summarization.md#reuse-and-telemetry) for the summary result and reuse counters.

Use `/compact` in the Web UI composer to summarize older context for the current thread. DeerFlow keeps the full chat visible, but future model calls use the compacted summary plus recent messages. The command is ignored when there is not enough history to compact, and it is blocked while the thread has a run in flight, including when that run is owned by another Gateway worker. If a multi-worker reservation loses its lease, DeerFlow cancels the checkpoint writer before the replacing run proceeds and returns a retryable conflict after cleanup. Thread-title edits are serialized through the same state-write boundary and show a conflict without closing the rename dialog when a run is active.

Manual compaction also returns HTTP 409 when execution is pending or the checkpoint is unavailable, so it cannot confirm the thread is idle.

The chat header also shows a context-window gauge when the selected model has a positive `context_window` configured. It estimates the latest materialized checkpoint's message tokens and keeps the previous same-thread percentage visible while data refetches, independently of the cumulative token-usage setting.

When `token_budget.enabled` and `token_usage.enabled` are both enabled, each lead-agent run budget includes completed subagent usage, including the final batch. Hidden goal continuations share the budget; a new user run starts fresh.
The token budget counts separate accepted model calls even when their response message IDs repeat, without double-counting repeated observations or later subagent-usage increments.

## Context Engineering

**Table Tool-Output Synopses**: CSV/TSV row counts reflect logical records, so newlines inside quoted fields do not add rows. If parsing fails or exceeds the field limit, the synopsis reports an undetermined count. Outputs beyond the input-size limit still skip structured parsing.

**Isolated Sub-Agent Context**: Each sub-agent runs in its own isolated context. This means that the sub-agent will not be able to see the context of the main agent or other sub-agents. This is important to ensure that the sub-agent is able to focus on the task at hand and not be distracted by the context of the main agent or other sub-agents.

**Summarization**: Within a session, DeerFlow manages context aggressively — summarizing completed sub-tasks, offloading intermediate results to the filesystem, compressing what's no longer immediately relevant. This lets it stay sharp across long, multi-step tasks without blowing the context window.

**Tool Output Preview Budget**: Structured synopses of externalized results have a character budget. Long JSON keys and paths are shortened with `...`, and oversized synopsis bodies include a truncation notice. Raw head/tail samples, the full file reference, and `read_file` guidance are preserved; read the saved file for exact keys or complete output.

**Strict Tool-Call Recovery**: When a provider or middleware interrupts a tool-call loop, DeerFlow now strips provider-level raw tool-call metadata on forced-stop assistant messages and injects placeholder tool results for dangling calls before the next model invocation. This keeps OpenAI-compatible reasoning models that strictly validate `tool_call_id` sequences from failing with malformed history errors.

**Provider Safety Stops**: With `safety_finish_reason.enabled`, native OpenAI Responses `status=incomplete` with `incomplete_details.reason=content_filter` suppresses tool calls, including malformed calls, and removes their native frames from subsequent requests. Empty filtered responses receive an explanation; visible partial answers without tool calls are preserved.

**Visible Tool-Run Completion**: For interactive turns, DeerFlow retries an empty post-tool final response once, then surfaces a visible error instead of reporting a silent successful run.

**Run History**: Image-only user input is recorded once per run, even when the agent makes multiple model calls. Its media content remains in history without requiring a text summary.
Web history keeps separate tool results in their original positions when a
provider reuses a tool-call ID across turns or runs. Copies of the same result
are matched by their message ID. Legacy results without message IDs are kept
separately because their provider ID alone cannot identify an invocation.
A result delivered before its assistant still resolves when that call is unique
in the turn. Rebuilt results from the same current invocation keep one history entry.

## Reading a Referenced Conversation

Gateway API callers can opt into `read_conversation` and submit a
`conversation_references` list with a run. The lead agent can then read bounded
pages of the current visible text of those owned conversations. Read permission
expires with the run, and text in old messages does not grant access. Text the
agent has already read stays in the destination conversation after access
expires or the source is deleted. A message too long for one read carries a
continuation, so the agent can read the rest; it asks for the missing part only
if that read is unavailable.
SDK clients that cannot add top-level request fields may send the same list as
`context.conversation_references`, and `GET /api/features` reports whether the
tool is enabled. When it is, the web composer shows a "Reference a conversation"
button next to the attachment button: pick up to three of your recent
conversations, and they are attached to the next message only, shown as chips
in the composer and in the transcript. There is no automatic history search. See
[configuration](../../backend/docs/CONFIGURATION.md#reading-referenced-conversations)
and the [request contract](../../backend/docs/API.md#referencing-a-previous-conversation).

## Current Task Notes

Enable [task notes and history recall](../../docs/task-continuity.md) with `task_continuity.enabled: true`.
A task can retain up to eight notes. Parallel additions beyond the remaining slots return
`note_capacity`, preserving existing notes. When artifact-handle resolution is enabled,
capacity counts resolved keys; aliases for the same note share one slot.
Malformed non-dict sibling arguments do not consume slots or disrupt valid note calls.
Notes with invalid keys, content over 750 characters, more than four sources, or malformed
source IDs also reserve no slot. Existing keys can still be replaced or deleted. Slots freed
by sibling deletions or runtime failures (such as unavailable sources or policy denial)
become available in the next batch, when rejected additions can be retried.

## Evidence-based agent decisions

Tool-result and model-error policies use producer metadata, native exit status, actual exception types and structured HTTP/provider fields. Page titles, quoted errors and words such as “timeout” or “no results” do not establish a failure category or permanent tool unavailability. Browserless passes the target HTTP status in the tool artifact; providers without that evidence preserve page text without guessing from it. Repeated-call and resource budgets still apply.
File reads report actual failures and truncation at the producer; producer-stamped successful reads preserve document examples, including text beginning with `Error:`.
For stamped text results, the model receives a JSON object separating reported execution status from `content`, with whitespace preserved by JSON escaping. Checkpoints and tool receipts retain the original result. This exposes existing status to providers that omit message metadata; it does not validate the document's claims or guarantee the model's final answer.

OpenAI connection and timeout errors use the configured `llm_call.retry_max_attempts` budget (default: three total attempts). Other OpenAI `APIError` failures without usable status or error code receive at most one retry, within that configured ceiling.

Memory extraction preserves short context-dependent replies and durable facts that mention uploads. Keeping these turns can increase extraction batch size and LLM use. The extractor distinguishes lasting user information from transient file availability using conversation context; lexical matches do not confirm a stored fact.

Receipt verification resolves cited receipt identifiers and anchors. It does not verify the truth or completeness of an uncited narrative; a report with no receipt citations is shown as unverified. Interaction guidance asks for clarification when consequential information is missing and otherwise permits stated assumptions and independent progress. Bundled research, consulting, initialization and creative skills adapt their examples and workload to the user's request rather than prescribing an answer or fixed interview/search quota.

Deferred MCP tools become available through explicit `tool_search` selection; routing keywords are advisory. Chat requests to trial a scheduled task return an owner-checked action card. Use its authenticated **Run once now** action or the scheduled-task page to dispatch the trial.

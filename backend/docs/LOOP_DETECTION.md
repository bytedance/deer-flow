# Loop detection lifecycle

`LoopDetectionMiddleware` owns call-pattern detection. Its place in the chain
and audit contract are documented in the
[middleware guide](../packages/harness/deerflow/agents/middlewares/AGENTS.md).

## Run-scoped state

Hash histories, frequency windows/counters, and warning-suppression sets
share a `(thread_id, run_id)` key. This gives a fresh budget to each user
run when a compiled graph is cached and reused, while keeping one budget
across repeated graph entries belonging to the same Gateway run (including
hidden goal continuations). `after_agent` clears only transient pending
warnings for its own scope, not those histories; the sync/async
`before_agent` hooks expire only the checkpointed [per-tool cap](#per-tool-cap)
and must not delete a sibling run's pending warning. Direct LangGraph embedders may omit
`context.run_id`; that fallback is anchored to the invocation's shared
`Runtime.control` object and mapped to an opaque generated ID, because
LangGraph replaces `Runtime` per node and CPython can reuse freed object
addresses. `after_agent` releases the anchor mapping, while the bounded map
covers abnormal exits. The compatibility-named
`max_tracked_threads` limit bounds run scopes, and `reset(thread_id)` clears
every retained run scope for that thread.

## Decision ordering

Loop decisions are severity-first across both detection layers: a warning
candidate never short-circuits frequency accounting for the remaining calls
in an admitted batch. The identical-call hard limit rejects the entire batch.
A per-tool hard limit admits the batch's calls up to the limit and drops the
calls that would reach it, because one response can carry many distinct calls
that have not run yet; the dropped calls are not counted. A call reaches the
limit when the window would hold that many calls to its tool after taking the
call in and dropping its oldest entry. A call that only replaces an older call
to the same tool is therefore admitted, so an interleaved workflow below the
limit keeps running. Only a response in which no call fits stops the run. Only the selected warning is marked and logged;
hash warnings still precede frequency warnings when neither layer stops the
run. Among simultaneous frequency-warning candidates, the first crossing in
model tool-call order remains selected for compatibility; later calls are
still counted and can warn in a later batch. A frequency warning whose burst
decays within the batch must not leave a stale suppression mark.

## Per-tool cap

A tool that reaches its per-tool hard limit is capped for the rest of the
execution. The frequency window cannot express this on its own: dropped calls
are not counted, so calls to other tools would evict the capped tool's entries
and let it run again. The cap is therefore a record in the private `loop_cap`
state channel: the capped tools with their limits, the run that carries the
cap, and a notice for the model.

- **Every later call to a capped tool is dropped**, whatever the window counts.
  Other tools in the same response run under their own limits. A response that
  calls only capped tools stops the run.
- **A run that dropped a call is `loop_capped`** in the run record and in a
  subagent result, although it goes on to wrap up. Goal continuation stands
  down on that reason. The calls that survive still run, so the reason is
  reported only when the run ends: other middlewares read `stop_reason` in the
  run context as "the run is ending" and skip their checks. Until then, input
  that arrives mid-run still cancels the response's planned calls, parallel
  `write_todos` calls are still rejected, input that arrives as the run
  finishes is still applied, and the todo completion reminder works as in any
  run. If another guard has already given the reason the run stopped, loop
  detection reports nothing, so the run record and a subagent result name the
  same guard. A response with no call left is a terminal stop and is reported
  at once, as before. A run that pauses for approval reports no reason; the
  run that resumes it reports `loop_capped` when it ends.
- **A response whose admitted calls are all discarded leaves no trace.**
  Another middleware can drop every call that loop detection passed on before
  any of them runs: input admission does so when the user steers, and approval
  does so for calls it cannot address. Calls that never ran do not count, so
  as the next model call starts, the frequency window, the warnings and the cap
  record go back to their state before that response. Caps from earlier
  responses stay, and the notice for the discarded response is not sent. This
  runs in `wrap_model_call` rather than a `before_model` hook, because a hook
  is a graph node and would spend a super-step of every turn. A response that
  keeps some of its calls keeps its accounting, as before, and so does one that
  compaction has removed from the history.
- **The model is told on its next call** how many calls of its last response
  were skipped and how many were passed on, followed by the wrap-up
  instructions. The text reports admission, not execution: an admitted call can
  still be denied by approval or a guardrail, and its tool result says so. The
  notice is read from the record on every model call and cleared once the model
  has answered, so a retried call gets it again. It quotes tool names and
  counts only, never arguments, because it is added inside PII redaction.
- **The record is checkpointed**, so the cap and the notice survive an
  approval pause, the new `run_id` of the resume, a Gateway restart and
  context compaction. A resumed run adopts the record and reports
  `loop_capped` when it ends. Its frequency window starts empty, as for any new
  run.
- **A new task gets a fresh budget.** `before_agent` runs when a task enters
  the graph and not when a paused run resumes, so it expires a record that
  another run left behind. A later entry of the same run, such as a hidden goal
  continuation, keeps it.

- **The record holds only what its reader accepts.** Tool names come from the
  model's response. A name the reader would reject (too long, or with
  whitespace) and a tool beyond the record's size bound are left out, because
  one such entry would make the next read discard every cap in the record. The
  window already dropped that tool's calls. The record and its notice are
  still written, so the drop is explained and the execution stays
  `loop_capped`; the notice then refers to "a tool" instead of a name.

The channel is server-owned: the Gateway rejects a client value for it, the
graph leaves it out of its input and output, and a malformed record reads as
no cap.

`backend/tests/test_loop_detection_middleware.py` covers mixed-tool batches,
window decay, overrides, sync/async compiled-graph execution, and the cap
across a real approval pause and checkpoint resume.

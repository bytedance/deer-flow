# Loop detection lifecycle

`LoopDetectionMiddleware` owns call-pattern detection. Its place in the chain
and audit contract are documented in the
[middleware guide](../packages/harness/deerflow/agents/middlewares/AGENTS.md).

## Run-scoped state

Hash histories, frequency windows/counters, and frequency-metric reporting
sets share a `(thread_id, run_id)` key. This gives a fresh budget to each user
run when a compiled graph is cached and reused, while keeping one budget
across repeated graph entries belonging to the same Gateway run (including
hidden goal continuations). `after_agent` clears only transient pending
warnings for its own scope, not those histories; the sync/async
`before_agent` hooks remain topology-preserving no-ops and must not delete a
sibling run's pending warning. Direct LangGraph embedders may omit
`context.run_id`; that fallback is anchored to the invocation's shared
`Runtime.control` object and mapped to an opaque generated ID, because
LangGraph replaces `Runtime` per node and CPython can reuse freed object
addresses. `after_agent` releases the anchor mapping, while the bounded map
covers abnormal exits. The compatibility-named
`max_tracked_threads` limit bounds run scopes, and `reset(thread_id)` clears
every retained run scope for that thread.

## Decision ordering

Hash-based loop decisions are evaluated before the frequency metric is updated.
A hash warning does not prevent the remaining tool names in the same response
from being counted. Frequency thresholds only emit INFO metrics with
`action="observe_only"`; they never enqueue a model warning, strip tool calls,
or set a stop reason. The hash warning and hard-stop behavior remains scoped to
identical calls whose results show no progress.

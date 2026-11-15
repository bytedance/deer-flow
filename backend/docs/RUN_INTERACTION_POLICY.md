# Run Interaction Policy

The harness resolves a `RunInteractionPolicy` from the run context and uses it
as the single source for lead-agent tool visibility, clarification middleware
behavior, sandbox network approval eligibility, and system-prompt guidance.
The implementation lives in `../packages/harness/deerflow/agents/interaction_policy.py`.

Interactive runs inspect available context and proceed with reversible assumptions or independent work when appropriate. Ask when essential information, consequential choices, or authorization for high-risk work is missing; a fixed clarify-plan-act sequence is not required. Clarification interrupts and trust boundaries remain unchanged.

## Modes and precedence

Interactive runs may ask a human for clarification. Runs in `scheduled`,
`webhook`, or `autonomous` mode must use the available context, make minimal
reversible assumptions, list material assumptions, or return a structured
`BLOCKED` result naming the missing decision for high-risk or irreversible
work without sufficient authorization. They must never wait for a synchronous
human response. Suppressed clarification tool results must preserve this same
boundary, not tell the model to unconditionally carry out an ambiguous action.

An explicit `interaction_mode` takes precedence over legacy context hints.
An unknown explicit mode is a configuration error, never an interactive fallback.
Without an explicit mode, the resolver checks `non_interactive` (scheduled),
then `channel_name="github"` (webhook), then `disable_clarification`
(autonomous); otherwise it selects interactive. These legacy flags remain
supported while entry points migrate to explicit modes.

Sync and async sandbox network approval paths use the same resolved policy.
Unattended runs deny pending network requests without opening a Human Input
card. Subagents always deny pending requests, even in an interactive run.

## Gateway trust boundary

`interaction_mode`, `non_interactive`, `disable_clarification`, and
`channel_name` are internal-caller-only Gateway context keys. The latter two
remain runtime-only and are never copied into checkpoint-persisted
`configurable`. Public run requests cannot use these keys to disable
clarification, impersonate a webhook channel, or override a scheduled run back
to interactive behavior.

## HITL tool approval

Tool permissions are independent of interaction and reasoning modes. The opt-in
`hitl_approval` policy offers Ask, Auto and Full with mandatory deny/ask rules and
an operator-controlled ceiling. Native tool calls pause at their execution boundary
using LangGraph interrupts; the durable run becomes `waiting_for_input`. Resume
consumption is compare-and-swap bound to every pending action's request ID, and
parallel interrupts are routed by their individual graph IDs.

Auto runs a separate, tool-free reviewer over the original user's intent and exact
bound operation. Review preparation is checkpointed: resuming cannot obtain a new
review verdict or silently replace the approved arguments. The model's result
cannot override host policy or inner authorization. Invalid/uncertain review
requires a human, and fails closed when the run cannot collect an answer.

Interactive child calls wait through a parent-owned bridge with a time limit.
They retain their original execution and use a session-authenticated, owner-scoped
HTTP answer. Cancellation, expiry, ownership loss or worker restart invalidates
these live requests. Unattended parent origins cannot open child approval waits.
A child without this bridge fails closed. The legacy `non_interactive: allow`
only bypasses Ask on explicitly configured unattended root runs.

The resume run's journal adopts the paused calls it answers, recovered from the
durable interrupt payload. Approved calls reach the history feed through their
tool callback; rejections have none, so the journal reconciles them under the
resume run like other middleware-written results (#4666). Results from other
earlier runs are not re-attributed.

A call that cannot carry a stable approval decision is never paused. A null or
duplicated call id can never match the resume validator and would block new runs
forever; an empty id is technically matchable, but it is denied as well because
strict providers reject an empty tool-call id when the conversation is replayed.
The middleware removes those calls from the model response with a visible
rejection note instead of pausing, so the tool is never executed and the thread
stays usable. The same uniqueness rule applies when a call is denied by result:
answering a denial `ToolMessage` also answers any other call that shares its id,
so a shared id is stripped rather than answered, and the next request cannot
carry the id twice. A pause stored by an older release with a null or duplicated
id is **not** cleared by this: every resume, including all-reject, is still
rejected, so continue the work in a new thread. In-place recovery is tracked in
[#8071](https://github.com/bytedance/deer-flow/issues/8071).

`waiting_for_input` is not terminal success or failure. Goals, delivery checks,
and batch continuation must preserve a native pause. New runs cannot discard it.
Root checkpoint approvals do not expire and block new runs until resolved;
live child approvals retain the time limit described above.
See [HITL Tool Approval](CONFIGURATION.md#hitl-tool-approval) for grant scoping,
parameter editing, limits and persistence semantics.

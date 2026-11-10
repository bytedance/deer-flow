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

`hitl_approval` is an operator-controlled, opt-in gate around selected tools,
not a way for a non-interactive run to wait for clarification. Interactive
Web/SDK runs pause through LangGraph `interrupt()` and enter
`waiting_for_input`; only a matching approval response can resume the current
checkpoint. Scheduled, webhook, autonomous, IM, extension, and MCP notification
runs follow `hitl_approval.non_interactive`. Subagents and graphs without resume
support always fail closed, including when that setting is `allow`.

Resume consumption is a store-level compare-and-swap bound to the validated
action `request_id` mapping; the middleware recomputes those IDs from the live
AI message before applying any decision. If worker attachment fails after
consumption, the Gateway conditionally restores that exact answered run to
`waiting_for_input` so a valid response or all-reject can retry safely.

`waiting_for_input` is not a terminal success or failure. Goal checks, final
artifact delivery checks, and batch continuation cancellation must not treat a
pending approval as a completed source run. Pending approvals do not expire and
block new runs on the same thread until resolved. See
[HITL Tool Approval](CONFIGURATION.md#hitl-tool-approval) for configuration and
argument-summary visibility limits.

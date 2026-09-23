# Run Interaction Policy

The harness resolves a `RunInteractionPolicy` from the run context and uses it
as the single source for lead-agent tool visibility, clarification middleware
behavior, sandbox network approval eligibility, and system-prompt guidance.
The implementation lives in `../packages/harness/deerflow/agents/interaction_policy.py`.

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

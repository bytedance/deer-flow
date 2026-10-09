# Clarification (`ask_clarification`)

Read this guide before changing `ClarificationMiddleware`, the Human Input Card
payload shape, or the journal reconciliation that keeps those cards across a
reload. It is the depth for entry 38 of the
[middlewares guide](../packages/harness/deerflow/agents/middlewares/AGENTS.md),
which only names the middleware and its load-bearing constraints and links here:
that chain is within a few hundred bytes of `scripts/check_agent_guidance.py`'s
hard chain limit, so it has room for the invariants but not for their rationale.

`ask_clarification` is the model-initiated human-in-the-loop path: the model
calls it as a tool, the middleware answers that call and ends the turn. Compare
[tool approval](TOOL_APPROVAL.md), which is system-initiated and parks the run
mid-turn on a real `interrupt()`; the two resume contracts are incompatible and
a tool named `ask_clarification` can never be approval-gated.

## What the middleware does

It intercepts the call, writes a readable `ToolMessage.content` fallback plus a
structured `ToolMessage.artifact.human_input` payload, and interrupts via
`Command(goto=END)`. It must be registered **last**, which makes it the first
`after_model` hook to dispatch — LangChain dispatches `after_model` in reverse
registration order.

`after_model` drops same-turn sibling tool calls so they cannot run before the
user answers. A malformed `ask_clarification` parked on `invalid_tool_calls` is
the same stop signal. Runs with `disable_clarification` keep the siblings.

## Payload versioning

Payloads are versioned so an older frontend degrades instead of misrendering:

- legacy `free_text` / `choice_with_other` stay `version: 1`
- the v2 `form` mode (built from `fields`) is `version: 2`, so older frontends
  reject it and fall back to plain text

The response protocol is unchanged across both (v1 `text` / `option`): form
cards submit a text summary as `response_kind: "text"`, so journal persistence
needs no new allowlist entries.

## Field normalization is deterministic, and atomic

Normalization lives in the middleware rather than in tool-argument typing,
because the middleware short-circuits *before* tool execution — so tool-arg
types give no runtime validation here.

It is atomic by design. Any structurally broken entry degrades the **whole**
form to the legacy option/free-text modes, so a card can never render as
"complete" while silently missing a field:

- a non-dict entry
- a bad or duplicate `name`
- a `name` colliding with a JS `Object.prototype` member (`__proto__`,
  `constructor`) — these reach the browser as object keys
- exceeding any cap: 16 fields, 24 options per field, 200 chars per text,
  `MAX_FORM_SERIALIZED_BYTES` = 16KB UTF-8

The per-item caps alone would admit forms whose IM text fallback overruns
channel message limits, which is why the serialized-bytes cap exists alongside
them.

Benign issues degrade **locally** instead, keeping the rest of the form:

- unknown field types become `text` — including unhashable JSON such as
  `type: []`, which must not raise from the membership probe
- option-less selects become `text`
- options are trimmed and deduped with blanks dropped, at both the form and
  top level, since the frontend rejects blank labels

XML-to-dict option payloads are recursively flattened from dict/list containers
in source order, scalar leaves kept, and residual XML tags stripped before that
trimming.

Checkboxes are booleans defaulting to "no". A `required` checkbox means consent
semantics.

## Journal reconciliation, and why it is not name-scoped

Because this middleware can short-circuit before `on_tool_end`, `RunJournal`
does a root-run reconciliation for `ToolMessage`s whose `tool_call_id` came from
the current run, so cards survive checkpoint compaction.

That reconciliation is deliberately **not** `ask_clarification`-only. Any
middleware that answers a tool call has the same gap, and a result the user
already saw must not vanish on reload — #4666 was exactly this:
`ReadBeforeWriteMiddleware` blocked-write errors reached the UI but never the
event store.

So it is bounded by three conditions rather than a name allowlist:

1. the message is user-visible
2. the call belongs to this run's **lead agent** —
   `_remember_current_run_tool_calls` records lead-agent calls only; subagent
   results stay in `subagent.step`
3. it is not already persisted

Do not narrow this back to a tool-name check: that reintroduces #4666 for the
next middleware that answers a call.

## Human Input Card replies

Replies arrive as `hide_from_ui` `HumanMessage`s carrying
`additional_kwargs.human_input_response`. `RunJournal` persists only allowlisted
hidden sources (currently `ask_clarification`) as `llm.human.input`.

# Agent middlewares (`deerflow/agents/middlewares/`)

Every model call and tool call of the lead agent and of subagents passes through
this chain. The order is defined in code:
`tool_error_handling_middleware.py::_build_runtime_middlewares` builds the base
that lead and subagents share, and `../lead_agent/agent.py::build_middlewares`
appends the lead-only part. Read those two functions for the current list.
Background: [execution flow](../../../../../docs/middleware-execution-flow.md),
[summarization](../../../../../docs/summarization.md),
[guardrails](../../../../../docs/GUARDRAILS.md),
[tool artifacts](TOOL_ARTIFACTS.md),
[tool output persistence](TOOL_OUTPUT_PERSISTENCE.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "middleware"
make test-blocking-io
```

## Order is behaviour

- **The first middleware is the outermost model wrapper.** Input sanitization is
  first so that every inner middleware, including model retries, sees sanitized
  messages. Decide where a new middleware goes by what it needs to see and what
  needs to see its output.
- **Lead and subagent chains differ on purpose.** Subagents skip the lead-only
  part. A middleware declared in config needs an explicit scope from each builder;
  there is no implicit lead default.
- **Tool wrappers nest.** Receipts wrap authorization, audit and write checks, so
  a denied call still gets a receipt. Progress tracking wraps error handling, so it
  sees the result that error handling produced.
- **Progress tracking fences late results and hint retries by graph entry**, also
  within one run.

## Rules for a middleware that changes messages

- **Stamp provenance.** A message that a middleware injects or rewrites and that
  stays in state carries `provenance_kwargs()` from the extension API. Consumers
  tell server-written context from user text by that stamp. A rewrite that exists
  only inside one model request needs no stamp.
- **Record tool-result transforms.** A middleware that rewrites a tool result
  appends an entry with `append_tool_transform`. Observers classify raw-to-visible
  changes from that trail and never from the output wording.
- **Remove tool calls with `clone_ai_message_with_tool_calls`.** Updating
  `tool_calls` alone leaves the tool-call blocks in `content`, and strict
  providers reject the resend.
- **State and UI keep the raw result.** The model-facing projection of a tool
  result (metadata envelope, shortening) is built per request. Receipt hashes and
  the UI read the stored value.
- **Persisted metadata is untrusted.** Checkpoints written by older versions and
  by direct integrations contain malformed values. Every history reader validates
  what it reads, and a bad value must not abort compaction or a model call.
- **Declare release policy.** A configurable middleware returns JSON-safe
  `release_policy_parameters()`, and `collect_release_policies()` changes with its
  behaviour.

## Trust and classification

- **User text never gains framework authority.** Sanitization encodes
  framework-looking tags in user input, and remote tool results are neutralized
  separately.
- **Classify failures from structure.** Model and tool failures are classified by
  status codes, provider fields, exception types and producer metadata. Message
  text is diagnostic only. An incidental JSON field in a tool result cannot make
  the result an auth failure.
- **Authorization identity comes from the server.** The Gateway strips identity
  keys that a client sends. Guardrail decisions are published into the run context
  under a `__`-prefixed key so that a caller cannot forge one.
- **Sandbox audit is not a security boundary.** Command classification is
  defense in depth and has known gaps. The sandbox is the isolation.
- **Delegation verdicts are untrusted.** Revalidate persisted values. Completed
  subagent work is evidence, not acceptance.
- **Status comes from metadata.** Do not infer a delegation, todo or tool status
  from reply text.

## Compaction

- The summarizer never sees replayed reasoning or media bytes. PII redaction runs
  before splitting, and budgets apply before escaping.
- Durable context (delegations, loaded skill names) is captured before compaction
  and re-enters through the durable-context channel. Recalled memory enters
  through the dynamic-context channel. Summaries do not carry either.
- Fraction-based triggers follow the model that runs the turn. A separate summary
  model only generates the summary.
- Superseded-write elision is opt-in, because it rewrites earlier request prefixes.

## Concurrency

Middlewares run on the event loop that serves the run. File and network I/O goes
off the loop, and a started operation is drained even after cancellation. Waiters
that cross loops own separate futures; notify them outside the state lock.

# Tools (`deerflow/tools/`)

Assembles the tool list of an agent (`get_available_tools`) and holds the
built-in tools: task delegation, tool search, clarification, scheduling,
conversation reading, skill management, ACP agents and the artifact registry.
Search, fetch and sandbox providers are in `../community/<provider>/`, each with
its own guide. The tools themselves, their parameters and their limits are in
the code and in each tool description.
Background: [tool artifacts](../agents/middlewares/TOOL_ARTIFACTS.md),
[file upload](../../../../docs/FILE_UPLOAD.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "tool or acp or artifact_registry or web_search"
make test-blocking-io
```

## Assembly and authority

- **A capability comes from the server, not from the conversation.** A tool such
  as `read_conversation` needs a capability that the worker installed for this
  run. Do not recover it from persisted messages, and do not import Gateway
  routers into the harness to get it. The host enforces the user's permissions;
  tool guidance for the model is a separate text and enforces nothing.
- **Text never authorizes an action.** The scheduled-task `trial` action returns a
  card, and the authenticated owner triggers the run from the UI. Do not add an
  allowlist of natural-language confirmations.
- **Subagent, bootstrap and embedded assembly get a narrower list.** Check which
  assembly a new tool belongs to before you add it to all of them.
- **A scheduled background run has no clarification tool.** It runs under the
  non-interactive policy, and only an internally authenticated caller can set
  that context.
- **A budget hint must not abort assembly.** When the model's output cap is
  absent, non-finite or too large to estimate, omit the hint.
- **Tool parameters carry types; value rules come from the service.** The tool
  and the REST route then return the same coded errors.

## Tool search and deferred schemas

- **`tool_search` is the only path that promotes a deferred schema.** MCP routing
  keywords are advisory.
- **Regex search has a time budget and returns no partial ranking.** On budget
  failure the tool returns a retry hint and promotes nothing. Validate the
  pattern with stdlib `re` first, so an invalid pattern still falls back to a
  literal match and engine-specific syntax is not admitted.
- **`keywords:` and `select:` never call the regex helpers.** They are the escape
  route that an error message points the model to.
- **Do not log an oversized tool description.** Log the bounded tool identity.
- **Keep the `tool_search` description in step with the grammar and limits.** The
  description is what the model reads.
- **Routing-priority coercion is duplicated on purpose** in `tool_search` and
  `McpRoutingMiddleware`. Change both, and cover the built and the serialized
  index.

## Delegation boundary

- **The child loop never gets the journal or the event store.** `task` passes one
  narrow recorder that schedules calls back onto the loop that owns `RunJournal`,
  and it is drained once before `task` returns.
- **Knowledge sources cross the boundary as captured records.** Forward the
  records from the child's tool messages when the report cites them. Do not
  rebuild them from the child's prose or from a fresh provider read.
- **Durable MCP task tools never expose the remote handle.** Cancellation records
  the request and returns; the background service owns the remote call.

## Text, paths and URLs

- **Scan the exact bytes that will be published.** `skill_manage` stages text as
  UTF-8 with `newline=""`, because a platform newline translation would make the
  scanned content differ from the stored content.
- **Hostname validation blocks.** `community/url_safety.py` resolves with
  `socket.getaddrinfo`, so async callers run it through `asyncio.to_thread`. The
  check holds at validation time only; see the browser guides for what covers
  later connections.
- **Free-text path detection is deliberately narrow.** Paths with spaces are
  recognized only inside a matching wrapper, and a search for the closing
  delimiter stays on one line so that later references survive.

## ACP agents

- **The launcher must speak ACP.** The standard `codex` CLI does not; configure an
  adapter.
- **Drain the agent's stderr for the whole call.** The SDK opens the pipe and does
  not read it, so an agent that logs enough blocks on a write and the call stalls.
  The stderr tail goes to the Gateway log, never into model-visible text.
- **Race the exchange against process exit.** The SDK does not fail pending
  requests when the agent exits.
- **Keep the SDK process context outside the timeout**, so teardown finishes
  before the tool returns. Report a timeout only when the deadline expired.
- **Resolve the command before the spawn, off the event loop.** The spawn does no
  `PATHEXT` lookup on Windows, so a bare npm launcher is not found.
- **Results contain message chunks only.** Thought chunks stay internal.

## Web search recency

`time_range` maps to a different parameter for each provider, and omitting it
leaves the request unchanged. The DDGS engine set that honors a time limit is
tied to the pinned DDGS version; check it again when you upgrade DDGS.

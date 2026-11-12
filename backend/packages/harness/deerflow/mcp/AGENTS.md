# MCP (`deerflow/mcp/`)

Connects MCP servers through `langchain-mcp-adapters` and turns their tools into
agent tools. It also owns OAuth and per-user credentials, the stdio session pool,
personal (per-user) server configs and the durable runtime for long-running MCP
tasks in `mcp/tasks/`. Operator documentation:
[MCP_SERVER.md](../../../../docs/MCP_SERVER.md). Task control leases:
[mcp-control-leases.md](../../../../docs/mcp-control-leases.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "mcp"
make test-blocking-io
```

## Sessions and cache

- **A stdio session belongs to one event loop and one ownership domain.** The pool
  key contains the server, the scope, the owning loop and the domain
  (`deployment` or `personal`). A session is never shared across loops, and two
  servers with the same name in different domains never share one. Sync wrappers
  use a fresh loop per call, so parallel sync calls have separate subprocesses.
- **Drain before `loop.close()`.** A loop that closes while a session owner is
  pending never runs the teardown. `asyncio.run()` drains for you; a manual loop
  owner has to.
- **Thread deletion closes every incarnation** of the user/thread pair
  (`close_thread_scope`). Use `close_scope` only when the caller holds one exact
  scope key.
- **Staleness is a content signature of the resolved config path**, not an mtime
  comparison. Several workers and coarse filesystem clocks make mtime unreliable.
- **Discovery errors do not trigger a second discovery.** The `asyncio.run`
  fallback in `get_cached_mcp_tools()` is for a missing or closed loop only.
- **`mcp_tasks` is read at startup.** The installed submitter decides whether task
  tools are exposed. Editing the config on disk does not change a running process.

## Credentials

- **Header names are case-insensitive.** Every credential interceptor writes
  through `apply_header_overrides`. A second key that differs only in case would
  send two `Authorization` headers.
- **Read the run context from `request.runtime`** in an interceptor. Context
  variables are not reliable there, because the adapter may call from another
  task.
- **Three credential sources** exist for HTTP and SSE servers: deployment OAuth,
  per-user `user_auth`, and per-request `headers_from_context`. A missing
  credential fails the call. It never falls back to another user's or to the
  deployment credential.
- **The OAuth store keeps refresh tokens only**, encrypted and keyed by scope,
  owner and server. Personal managers pass `owner_user_id`.
- **Background task calls have no request.** `McpTaskToolCaller` binds the task
  owner's identity for the call and restores the previous value afterwards.

## Results

- **Never put base64 payloads in text.** Unsupported content (inline audio) raises
  a recoverable tool error.
- **`ResourceLink` items do not become URL-sourced `file` blocks.** Chat
  Completions serialization rejects them, and a checkpointed block would break
  every later turn of the thread.
- **Stdio file paths.** A local path that a stdio server returns is translated to
  `/mnt/user-data/...` only when the file exists inside the thread's user-data
  tree. Files outside it are never copied or rewritten.
- **Routing hints** are resolved in `get_mcp_tools()`, where the server name and
  the original tool name are both known, and stored in tool metadata. Prompt
  rendering reads that metadata. Do not add a second routing mechanism.

## Durable tasks

- A long-running MCP task is a database row, not agent-loop state. The Agent
  submits and returns. A worker polls, cancels and delivers the notification.
- Poll and cancel are claimed under a control lease. A snapshot write that the
  ownership fence rejects is logged and dropped, because a peer worker owns the
  task. Do not retry it.
- Notification delivery failures use their own counter and backoff. They are
  separate from the dispatch attempt that forms the idempotency key.
- Payloads stored on the row are bounded. An oversized or invalid payload becomes a
  permanent task failure and is not truncated.

## Trust

- **The HTTP API is untrusted input even from an admin session.** Stdio launch
  commands that arrive through the API are screened (launcher options, exec flags,
  environment names). This is defense in depth. The boundary is admin
  authentication, because `npx` and `uvx` run remote packages by design.
- **Personal configs** live under the user's root, hold literal values and never
  enter the deployment tool cache. Owner and current revision are checked before
  every call.
- **Personal servers on private networks** need current administrator authority at
  discovery and on every call. Look the role up each time; do not capture it.
- **Public-network personal clients** keep `trust_env=False`, DNS screening and
  per-origin connection pools. TLS trust loads in a worker thread.

# Harness package (`deerflow/`)

The publishable `deerflow-harness` package: agents, runtime, tools, sandbox,
models, MCP, skills, config and persistence. Each subpackage has its own guide,
listed in [backend/AGENTS.md](../../../AGENTS.md). This file covers the modules
at the package root. The harness never imports `app.*`.

## Request trace context (`trace_context.py`)

The request correlation ID is the `X-Trace-Id` header and the `deerflow_trace_id`
key. It is not the Langfuse trace ID and not the `run_id`.

- **The ContextVar is the only source.** Every entry point that starts a run
  binds an ID first: the HTTP middleware, a scheduled occurrence, an MCP task
  notification, an IM message and an embedded client turn. A new entry point
  binds one too.
- **Bind one unit of work, never a poller loop.** A binding that leaks on a
  reused worker task tags later work with the first ID.
- **Every other carrier is an output.** A `deerflow_trace_id` that a caller sends
  is replaced, because the stored run would otherwise disagree with the header
  and the logs.
- **An HTTP request does not inherit an ambient ID.** A crafted header must not
  fall back to the previous request's ID.
- **Use `ensure_trace_id()` and `resolve_trace_id()`** in place of a local
  fallback chain. A ContextVar does not survive a bare thread hop, so an ID that
  crosses one travels as data.
- **`DeerFlowClient.stream()` binds per step, never across a `yield`.** A sync
  generator shares the caller's context.
- **A crash-recovered scheduled launch keeps the first attempt's ID** on the run
  record. That is accepted: restamping would rewrite an existing record.

## Embedded client (`client.py`)

`DeerFlowClient` runs the harness without HTTP and shares config, data
directories and response schemas with the Gateway.

- **A method that mirrors a Gateway route returns the same schema.**
  `TestGatewayConformance` in `tests/test_client.py` parses each result with the
  Gateway model; add a new method there.
- **The client does not delete a thread's data directory.** Only the Gateway
  does, after the LangGraph thread is deleted.

## Other root modules

- **Lark CLI credentials (`integrations/lark_cli.py`).** A managed skill pack is
  staged privately and published with one rename, so a failed write leaves the
  previous pack in place. When you switch the app, clear the old OAuth data
  before `lark-cli config init`: on Linux the new secret is written under the
  same data directory, and a later clear would remove it.
- **Workspace snapshots (`workspace_changes/recorder.py`).** On cancellation,
  drain a text scan before you remove the cache that its worker reads. A
  metadata scan owns no cache and is cancelled at once.
- **Project summaries (`projects/summaries.py`).** `stop()` closes admission
  first, and `start()` reopens it only after the stop has finished.
- **Environment values are strings.** Parse a boolean before you pass it to an
  SDK, because `bool("false")` is true.

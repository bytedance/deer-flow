### Request Trace Context (`packages/harness/deerflow/trace_context.py`)

DeerFlow's request-level correlation id — the `X-Trace-Id` header and the `deerflow_trace_id` key. Not Langfuse's trace id, not `run_id`, not the short subagent `trace_id` log label.

**The ContextVar is the only source.** Every path that reaches a run binds one first; downstream treats the id as a plain `str`, no `if trace_id:` guards.

Entry points and binders: Gateway HTTP — `TraceMiddleware`; scheduled occurrence — `ScheduledTaskService._attempt_queued_run` → `launch_scheduled_thread_run`; MCP task notification — `launch_mcp_task_notification_run`; IM inbound — `ChannelManager._worker_loop`; embedded / TUI / CLI turn — `DeerFlowClient.stream()`.

Only the first is HTTP; the rest run outside ASGI, so the binding cannot live in middleware alone. Each scopes **one unit of work**, never a poller loop — a leaked binding on a reused worker task would tag later occurrences with the first id. `ensure_trace_context` inherits, keeping layered scheduled bindings and a manual trigger inside a Gateway request on one trace.

**Every other carrier is a derived output, never read back as an input.** `worker._bind_trace_id` stamps the runtime context and `config["metadata"]`; `services.start_run` stamps the run record; a caller-sent `deerflow_trace_id` (`body.metadata`, `body.config.context`) is replaced — honouring it would let the persisted run disagree with the header and the logs. `_SERVER_OWNED_RUNTIME_CONTEXT_KEYS` covers the embedded path and also rejects caller-supplied sandbox lease/scope identities, `redact_config_secrets` scrubs the kwargs echo (`runs.kwargs_json`), and `build_run_config` merges metadata onto a copy so the stamp cannot reach `body.config`. Callers pin an id with `X-Trace-Id`.

Accepted divergence: a crash-recovered scheduled launch reuses its run via the idempotency key without restamping — the record keeps the first attempt's id, the retry's logs a fresh one; restamping would rewrite an existing record. Not a bug. Thread metadata omits the key entirely — a thread spans many runs.

**Do not open-code fallback chains.** Two helpers own the resolution order:

- `resolve_trace_id(*carriers)` — first usable carrier, else ambient. For ids travelling as data in `runtime.context`; ContextVars do not survive a bare thread hop.
- `ensure_trace_context(trace_id)` — reuse the surrounding scope, else start a self-contained one. For boundary crossings (`SubagentExecutor._aexecute`, the memory `trace_context_manager` hook) and non-HTTP entry points; no argument mints a scoped id.

`request_trace_context` (HTTP) deliberately does **not** inherit: a crafted header must not fall back to the previous request's id.

`get_current_trace_id()` stays nullable only for the logging filter (pre-entry-point records render as `trace_id=-`); everything else uses `ensure_trace_id()`/`resolve_trace_id()`.

`DeerFlowClient.stream()` binds per `next()` step and around `inner.close()`, never across a `yield`: a sync generator shares the caller's context, so a scope held across yields would leak the id and break on cross-context GC finalization.

`logging.enhance.enabled` gates **log output only** (`trace_id` field presence and format) — not the id, the header, or the run metadata — so `TraceMiddleware` reads no `AppConfig`; `logging` stays restart-required (`STARTUP_ONLY_FIELDS["logging"]`). `X-Trace-Id` is in `CORS_EXPOSED_HEADERS` (not safelisted). Unhandled-exception 500s keep the header — `TraceMiddleware` sends its own plain 500 (CORS-opaque, see its docstring) before re-raising; mid-stream failures propagate unchanged.

Tests: the `tests/test_trace_*` and `tests/test_worker_trace_binding.py` suites, `test_gateway_services.py`, `test_run_metadata_secret_safety.py`, plus the Langfuse suites in `tracing/AGENTS.md`.

### Managed Lark CLI credentials (`integrations/lark_cli.py`)

App registration and direct app switching replace the per-user Lark credential
tree transactionally. Clear the old OAuth data before running `lark-cli config
init`: on Linux that command writes the new app secret into the file-backed
keychain under the data directory, so clearing the directory afterward would
leave `config.json` with a dangling keychain reference. The transaction snapshot
still supplies the previous OAuth data for logout and restores the complete old
tree if any switch step fails.

### Browser Progress Screenshots (`community/browser_automation/`)

Hidden per-action browser progress frames use JPEG at quality 80 to keep their
storage and transfer cost bounded relative to lossless PNG. The explicit
`browser_screenshot` tool remains PNG because it creates a user-requested
artifact. New automatic capture entry points must reuse the shared progress
encoding definition in `tools.py` so the byte encoding and `.jpg` suffix cannot
drift.

### Embedded Client (`packages/harness/deerflow/client.py`)

`DeerFlowClient` provides direct in-process access to all DeerFlow capabilities without HTTP services. All return types align with the Gateway API response schemas, so consumer code works identically in HTTP and embedded modes.

**Architecture**: Imports the same `deerflow` modules that Gateway API uses. Shares the same config files and data directories. No FastAPI dependency.

**Agent Conversation**:
- `chat(message, thread_id)` — synchronous, accumulates streaming deltas per message-id and returns the final AI text
- `stream(message, thread_id)` — subscribes to LangGraph `stream_mode=["values", "messages", "custom"]` and yields `StreamEvent`:
  - `"values"` — full state snapshot (title, messages, artifacts); AI text already delivered via `messages` mode is **not** re-synthesized here to avoid duplicate deliveries; serialized `ToolMessage` entries preserve a non-`None` native `artifact`
  - `"messages-tuple"` — per-chunk update: for AI text this is a **delta** (concat per `id` to rebuild the full message); tool calls and tool results are emitted once each, and tool results preserve a non-`None` native `artifact`
  - `"custom"` — forwarded from `StreamWriter`; DeerFlow-built-in custom events are dual-emitted through `deerflow.utils.custom_events`, so `astream_events(version="v2")` consumers also receive one `on_custom_event` with `name=payload["type"]` and the unchanged payload as `data`
  - `"end"` — stream finished (carries cumulative `usage` counted once per message id)
- **Custom-event invariant** — production DeerFlow emitters must use `emit_custom_event` / `aemit_custom_event`, not call `StreamWriter` alone. Every built-in payload must carry a non-empty string `type`; typeless payloads remain writer-only and are intentionally absent from `astream_events`. The writer runs first and remains authoritative for Gateway, Web UI, and embedded-client compatibility; callback dispatch is best-effort and must not break that path. Async graph hooks must await the async helper rather than invoking synchronous dispatch on a running event loop.
- Agent created lazily via `create_agent()` + `build_middlewares()`, same as `make_lead_agent`
- Supports `checkpointer` parameter for state persistence across turns
- `reset_agent()` forces agent recreation (e.g. after memory or skill changes)
- See [docs/STREAMING.md](../../../docs/STREAMING.md) for the full design: why Gateway and DeerFlowClient are parallel paths, LangGraph's `stream_mode` semantics, the per-id dedup invariants, and regression testing strategy

**Gateway Equivalent Methods** (replaces Gateway API):

| Category | Methods | Return format |
|----------|---------|---------------|
| Models | `list_models()`, `get_model(name)` | `{"models": [...]}`, `{name, display_name, ...}` |
| MCP | `get_mcp_config()`, `update_mcp_config(servers)` | `{"mcp_servers": {...}}` |
| Skills | `list_skills()`, `get_skill(name)`, `update_skill(name, enabled)`, `install_skill(path)` | `{"skills": [...]}` |
| Goals | `get_goal(thread_id)`, `set_goal(thread_id, objective, max_continuations=8)`, `clear_goal(thread_id)` | `{"goal": {...}}` or `{"goal": None}` |
| Memory | `get_memory()`, `reload_memory()`, `get_memory_config()`, `get_memory_status()` | dict |
| Uploads | `upload_files(thread_id, files)`, `list_uploads(thread_id)`, `delete_upload(thread_id, filename)` | `{"success": true, "files": [...]}`, `{"files": [...], "count": N}` |
| Artifacts | `get_artifact(thread_id, path)` → `(bytes, mime_type)` | tuple |

**Key difference from Gateway**: Upload accepts local `Path` objects instead of HTTP `UploadFile`, rejects directory paths before copying, and reuses a single worker when document conversion must run inside an active event loop. Artifact returns `(bytes, mime_type)` instead of HTTP Response. The new Gateway-only thread cleanup route deletes `.deer-flow/threads/{thread_id}` after LangGraph thread deletion; there is no matching `DeerFlowClient` method yet. `update_mcp_config()` and `update_skill()` automatically invalidate the cached agent.

**Tests**: `tests/test_client.py` (offline unit tests including
`TestGatewayConformance`), `tests/test_client_live.py` (live integration tests,
requires a root `config.yaml`, valid API credentials, and explicit opt-in via
`make test-live` or `DEER_FLOW_RUN_LIVE_TESTS=1`). The live suite calls real
external APIs and may incur API costs or create local sandboxes, artifacts, and
files. It is marked `live`, excluded from `make test`, and skipped in default
CI.

**Gateway Conformance Tests** (`TestGatewayConformance`): Validate that every dict-returning client method conforms to the corresponding Gateway Pydantic response model. Each test parses the client output through the Gateway model — if Gateway adds a required field that the client doesn't provide, Pydantic raises `ValidationError` and CI catches the drift. Covers: `ModelsListResponse`, `ModelResponse`, `SkillsListResponse`, `SkillResponse`, `SkillInstallResponse`, `McpConfigResponse`, `UploadResponse`, `MemoryConfigResponse`, `MemoryStatusResponse`.

### E2B Mount Uploads

The E2B provider uploads host mounts during sandbox creation. It passes binary file objects to the E2B SDK.

Each mount has these fixed limits:

- 100 MiB for one file.
- 512 MiB for all files.
- 2,000 files.

The full sandbox creation pass also allows 512 MiB and 2,000 files. Skill
projections and configured mounts share this budget.

The pass has a cooperative deadline controlled by
``mount_upload_deadline_seconds`` (default: 120 seconds). The provider checks it before
each mount, during directory preflight, and before each SDK write. The deadline
does not interrupt active filesystem or E2B SDK calls.

The provider checks mount limits before upload. It rechecks each opened file descriptor against its preflight size before SDK upload.

For policy-scoped turns, clearing the four managed remote skill categories and
uploading their prepared projection is one per-user/thread/skills-root critical
section, shared with acquire and release. The provider snapshots that canonical
root at startup and carries it through warm-pool identity and E2B metadata; a VM
from another root is never adopted. A second policy sync cannot reset the remote
tree until the first upload pass has completed.

An invalid mount does not block later mounts.

Each successful upload logs its source, destination, file count, byte count, and elapsed time.

A stopped pass logs its limit reason and elapsed time. It reports attempted and completed upload totals separately.

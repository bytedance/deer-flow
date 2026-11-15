# MCP Server

Tool steps mark explicit execution failures. Scheduled-task steps show completed
operations only after a valid response, rather than when the request is issued.

In the chat UI, enable **Token Usage → Debug** to inspect generic/MCP tool calls.
Each **Tool details** panel starts collapsed and shows the tool name, call ID,
input, and received result or explicit error. Large previews are truncated;
fields whose names exceed the remaining preview budget are omitted rather than renamed.
Structured previews retain complete JSON syntax, including escaped strings and closing delimiters.
Array previews stop when the text budget cannot display another element; literal ellipsis values are preserved.
Consecutive generated markers at an array's end share one ellipsis indicating an omitted suffix; markers before later values retain their positions.
Text results retain their original representation, including large numeric IDs and duplicate JSON keys, without reparsing. Text exceeding the limit is shown as a prefix with a truncation notice; structured objects and arrays are formatted separately.
Copy actions copy only the displayed preview. This is a frontend view of data
already received by the browser, without an additional secret-redaction layer.

In plan mode, malformed TODO statuses return normal tool-validation errors without aborting token attribution, so the agent can correct the call.

Tool-produced paths and URLs can be retained as short artifact handles across context compaction (`tool_artifacts` in `config.yaml`). Handles distinguish separate tool-result occurrences, even when a provider reuses call IDs. Standard MCP image URLs are captured alongside file references, including results from stdio and HTTP servers. Detected file URLs preserve their query strings and fragments. Free-text sandbox paths retain spaces inside matching ASCII quotes, backticks, or curly quote pairs, including backslash-escaped wrappers. Unterminated spans and delimited values containing a line break or tab are skipped. Free-text artifact references retain balanced ASCII and CJK brackets in literal paths and URLs while trimming surrounding prose punctuation. When PII redaction is enabled, model-visible artifact labels follow that policy; internal references stay intact for tool argument resolution. The configured registry limit retains the newest artifacts, while checkpointed processing identities prevent evicted results from being recaptured after restart. Resolution runs before authorization and write-safety checks; unknown or expired handles return an error without executing the tool. Small unknown structured results may be retained as complete JSON up to 4096 UTF-8 bytes; empty or oversized payloads are skipped. Handles are agent-local: task arguments resolve parent handles to concrete references, and delegated reports must return concrete references rather than child-local handles. A truncated model projection reports how many handles are omitted.

DeerFlow supports configurable MCP servers and skills to extend its capabilities.
Inline MCP audio results are not supported. Stdio tools report an explicit error, matching HTTP/SSE tools, rather than treating base64 audio as a successful text result.
When durable MCP background tasks are enabled, agents can use `list_background_tasks(status="failed")` or `status="input_required"` to find failed tasks or tasks awaiting input in the current chat. Other supported statuses are `submitted`, `working`, `completed`, and `cancelled`; omitting the status preserves existing behavior. The database applies the filter before limiting results to the 20 most recent matching tasks. When combined with `active_only=true`, both filters apply: active statuses are `submitted`, `working`, and `input_required`, so terminal statuses return an empty list. `GET /api/threads/{thread_id}/mcp-tasks` supports the same `status` and `active_only` filters before its `limit` (default 50, range 1–100); for example, `?status=failed&limit=20`. Unknown statuses return 422, and omitting the filters preserves the existing response.
For HTTP/SSE MCP servers, OAuth token flows are supported (`client_credentials`, `refresh_token`).
Missing, malformed, or out-of-range token response `expires_in` values use a one-hour default lifetime. This includes lifetimes that cannot be added to the current time without overflowing the expiry timestamp.
Durable HTTP/SSE task status and cancellation calls select configured `user_auth` credentials using the persisted task owner, including after restart; per-request secrets are not retained for background calls. If a request-scoped credential overrides submit authentication, both credentials must authorize access to the same remote task.
For stdio MCP servers, per-tool call timeouts can be configured with `tool_call_timeout`; durable background-task calls honor the same setting for HTTP/SSE servers as well.
Durable background-task status and cancellation calls renew their claims while they run, so a slow response can still be saved after the original lease duration. If ownership is lost or renewal cannot be confirmed, the worker stops its local call and leaves recovery to the durable state. See [control-call leases](../../backend/docs/mcp-control-leases.md) for recovery and shutdown behavior.
The persistent stdio session pool evicts only idle sessions at capacity. If every pooled session is executing a tool, a new session request fails with a capacity error and can be retried after a call finishes.
For stdio file outputs, a bare filename is linked to a uniquely matching file created or changed by that call. Filenames embedded in unrelated paths, including Windows backslash paths, are left intact. Explicit remote URLs (`scheme://...`) retain their original query parameters and fragments even when these contain a generated file's name or path, including URLs with backslash-escaped quotes or markup delimiters; local references outside the URL still translate normally.
For HTTP/SSE background-task calls, `session_init_timeout` separately bounds connection setup (including the SSE endpoint event) and MCP initialization together; it stops applying once the tool call begins. Initialization deadline errors identify the server and configured time limit.
Ordinary `task` subagents retain the parent run's captured thread incarnation for MCP calls, including legacy threads, so delegation preserves the same lifecycle scope.
MCP tool names are prefixed with `<server_name>_` by default to prevent collisions across servers. If a server already namespaces its own tools, set `tool_name_prefix: false` on that server in `extensions_config.json` to keep the original names. Disable the prefix only when the resulting names remain unique across all enabled servers.
Signed-in users' notification toggle, default model, conversation mode, and reasoning effort are saved to their account and restored on other browsers or after clearing browser storage. Browser notification permission still needs to be granted on each device. Changes retry after network failures; unsent changes survive a reload in the same tab. Concurrent edits to different fields are preserved; for the same field, the last server write wins. Existing unscoped browser preferences are not uploaded automatically because they have no account owner; reselect those settings once after upgrading. Static demos and auth-disabled development keep browser-local settings. Thread-specific model overrides and other display preferences remain local.

In a new chat, the submitted question stays above its streamed reasoning and
tool steps while the server creates the conversation and confirms the message.

While a Web task is running, choose **Queue** to send text for the next turn or
**Steer** to update the current work. Native subagents pause at a safe boundary
while the main Agent handles the update; active tool calls finish first. Stop
keeps the Goal, while explicitly replacing the work can clear it. Unapplied
messages survive database-backed Gateway restarts and require **Send again**;
interrupted child side effects are not replayed automatically. Existing execution
limits still apply. Busy input currently accepts text only.
If a run rejects an update because it has finished, retrying the retained draft
during the next run targets that run. Uncertain network failures retain the
original submission identity so retries can reconcile the same accepted input.

Markdown and JSON conversation exports from the chat header or sidebar read all
persisted history pages, including earlier turns outside the loaded view or
compacted model context. A failed history read stops the export instead of
downloading a partial transcript. Public demos export their bundled messages.

Capability Center groups plugins by office collaboration, documents and knowledge, search and research, business and data, and development and operations. The directory includes setup references alongside existing MCP configurations and Lark. Recommended integrations and built-in support do not imply an installed or verified connection; the Installed filter shows configured MCP entries and installed Lark only.

Personal MCP connections configured in the web interface are persisted per user.
Personal MCP HTTP/SSE connections admitted under the public-network policy load TLS trust off the Gateway event loop, while retaining public-address checks, certificate verification and per-origin connection isolation.
Unexpected failures when changing deployment or personal MCP configuration return fixed error messages; exception details stay in server logs.
Deployment tools remain shared. Administrators can add, edit, enable, disable and delete shared MCP servers under **Platform provided**; ordinary users see their status without controls. Personal plugin switches affect only the signed-in user's connections. See [connection ownership](../../docs/capability-center.md#personal-and-deployment-mcp-configuration).

For plugin manifests, adapter registration, and Agent capability selection, see
[Capability Center integration contract](../../docs/capability-center.md).

DingTalk and WeCom group notifications and HubSpot CRM are bundled configurable
plugins. Administrators supply robot credentials or a HubSpot private app token;
Agents can then send requested group notifications, list companies, or create
contacts. Saving configuration performs no external write. These plugins reuse
the existing MCP lifecycle and require no separate plugin service. See the
integration contract above for required fields, scopes, and feature boundaries.

Plugin brand icons are bundled locally. When adding or editing one personal MCP plugin, users can upload a PNG, JPG, or WebP image (up to 2 MB), preview it, or restore the default icon. Changes take effect only after Save; custom icons persist across browsers as a normalized 128px PNG in the server entry's display-only `presentation.icon` metadata. They are not sent to the MCP transport.

Capability Center > Plugins adds, replaces, and deletes one MCP server at a time through targeted mutations that preserve concurrent sibling changes; deletes use a bodyless URL-addressed request. An invalid stdio command on one server no longer blocks toggling another, while enabling that invalid server remains protected by the command allowlist and surfaces the backend validation message in the UI.
Targeted updates accept both DeerFlow's `type` field and the MCP-spec `transport` field for SSE/HTTP servers.
Runtime MCP and skill updates replace `extensions_config.json` atomically, so an interrupted write cannot leave the shared configuration truncated or partially written. Every Gateway worker or instance that reads the same file picks up a new revision on its next read (the cache checks the file's content signature), so MCP and skill changes made through one replica apply to the others without a restart; a missing, truncated, or invalid revision keeps the previous configuration until a complete one lands, including when the file disappears during a reload.
The admin MCP cache reset advances a durable generation marker in the writable config directory. Every Gateway worker mounting that same directory retires its own cached tools and pooled sessions before the next lookup; replicas with independent filesystems are not implicitly covered. If no config path is available, the API reports a process-local reset instead.
The parsed extensions configuration and its recorded content digest come from the same read, so a racing edit followed by a timestamp-preserving backup restore cannot leave a different revision cached indefinitely.
Changes to the global `mcpInterceptors` chain rebuild every server's tool wrappers,
including when a server configuration is edited at the same time.

`extensions_config.json` accepts UTF-8 with or without a leading byte-order mark (BOM), including files saved as UTF-8 with BOM by an editor.

When deferred MCP tool discovery is enabled, `tool_search` supports opt-in literal keyword queries such as `keywords:notebook jupyter`. Keywords match names and descriptions in any order, ranked by distinct term coverage and then name hits; ties retain catalog order. This mode uses the first 256 characters after the prefix and at most 16 unique whitespace-separated terms, returning up to five tools. Punctuation stays literal. Bare queries and `+required` ranking keep their existing regular-expression semantics; `select:tool_a,tool_b` still fetches all exact, case-sensitive name matches.

MCP routing metadata describes tool capabilities as advisory context. Matching a keyword in user text does not reveal a deferred schema or establish that the user requested a tool. The agent selects appropriate tools via `tool_search`; the legacy `auto_promote_top_k` configuration is accepted but does not trigger automatic promotion.

Deferred MCP schema selections last for the current user turn. They remain active across that turn's model/tool loop and checkpoint resume, then become deferred again when a new user message starts the next turn. Legacy in-flight checkpoints retain previously searched tools in their original scope.

Deferred `tool_search` regex queries share a 100 ms execution budget across the catalog, including `+required` ranking. Patterns are limited to 256 characters and searchable names/descriptions to 65,536 characters each. Queries that exceed a limit return a retry hint without promoting partial results; use a simpler pattern, `keywords:`, or `select:` with exact names. Oversized catalog fields are reported with the tool name, field and length, and logged with the MCP server name when available; use `keywords:` or `select:` because simplifying the pattern cannot shrink a catalog field. Exact selection remains uncapped and bypasses regex limits; the literal `keywords:` mode also bypasses regex limits. Invalid regex syntax still falls back to a literal substring match.

OpenViking users can register the official Streamable HTTP endpoint at `/mcp`
with an owner-bound USER API key. The native `forget` tool is exposed for
capability parity; deletion is irreversible, so it should be called only after
explicit user confirmation. DeerFlow does not enforce that confirmation. This
explicit, model-selected MCP tool path can run alongside the separate automatic
OpenViking memory backend; it does not replace automatic turn capture or recall. See the
[OpenViking MCP tools configuration](../../backend/docs/MCP_SERVER.md#openviking-mcp-tools).

The Gateway can adapt an MCP server's ordinary `submit` / `status` / `cancel` tools into durable background tasks. The Agent sees only the configured submit tool and a DeerFlow-local task ID; remote IDs are persisted before the submit call returns, while status and cancel stay internal to the runtime. Polling uses cross-worker leases, exponential retry backoff, scoped MCP sessions, bounded result storage, and restart recovery. A status-tool `isError` is retained as a bounded diagnostic and retried; servers report a permanent remote-task outcome through a normal structured result with `status: "failed"`. Remote poll hints are finite positive numbers capped at 24 hours, artifact-reference JSON is limited to 64 KiB, and task/server identifiers are validated against their durable SQL column limits before persistence. Input-required and terminal updates wake the current chat through idempotent Agent runs, while `list_background_tasks` and `cancel_background_task` let the Agent manage tasks without asking users for remote handles. Current-thread tasks are available through `GET /api/threads/{thread_id}/mcp-tasks`, its detail endpoint, and `POST /api/threads/{thread_id}/mcp-tasks/{task_id}/cancel`; when the task runtime actually starts, the Web UI exposes the same safe local view from the chat header with live status refresh, cancellation, and on-demand result, artifact, input-request, status-error, and cancellation-retry details. Default-disabled and memory-backend deployments hide that UI and do not poll the task endpoints. A failed remote cancellation remains queued with backoff, and its latest bounded error and attempt count stay visible in the expanded task card. Enable `mcp_tasks` in `config.yaml`, configure `task_toolsets` with exact raw tool names in `extensions_config.json`, and use a SQL database backend (`sqlite` or `postgres`). Task-enabled server connection, authentication, interceptor, timeout, or binding changes require a Gateway restart so Agent tool discovery and background calls cannot use different configuration versions. `input_required` is notification-only for now: DeerFlow can display the request but cannot yet submit the user's answer back to the remote task.

For deployment-level HTTP/SSE servers with `task_toolsets`, discovery, ordinary
tools, and background task calls share OAuth token state within one Gateway
process, including across tool-cache resets. Rotated refresh tokens stay in
memory; they are not written back to configuration or shared across processes.
After a restart, the configured refresh token must still be valid.

Notification launch and failed Agent-run deliveries use capped exponential backoff with a visible attempt count and stop after five failed attempts. When a bounded ordinary release exceeds its drain deadline, the service retains ownership until it settles. A permanently rejected target such as a deleted chat is dead-lettered immediately instead of retried forever or recreated. Cancellation endpoints return after durably recording the request; the background service owns the potentially slow remote MCP call and its retry schedule.

Notification runs keep their trusted delivery instruction separate from the framed, untrusted remote event payload. The process-started task runtime—not a hot config read—controls whether the task-management tools are exposed, so changing `mcp_tasks` requires a Gateway restart. `list_background_tasks` and `cancel_background_task` are ordinary business tools governed by the agent's own authorization, like every other tool.
See the [MCP Server Guide](../../backend/docs/MCP_SERVER.md) for detailed instructions.

Security: pass per-request MCP credentials only through `config.context.secrets`;
credentials must never be placed in either run metadata surface
(`metadata.auth_token` or `config.metadata.auth_token`). See [MCP credential migration and cleanup](../../backend/docs/MCP_SERVER.md#migrating-legacy-mcp-credentials)
for the supported interceptor flow and the required rotation and retained-copy
cleanup when migrating from legacy metadata credentials.

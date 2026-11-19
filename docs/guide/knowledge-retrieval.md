# Private Knowledge Retrieval (RAGFlow)

Answers can cite retrieved RAGFlow evidence with clickable knowledge citations.
Click a citation, or an entry in the answer's knowledge sources list, to see the
original retrieved excerpt, dataset and document names, and page numbers when
RAGFlow supplies them. These are retrieval-time snapshots retained with the
conversation, including sources forwarded by ordinary `task` subagents; they
remain inspectable after reloading the conversation. An excerpt is not a live
copy of the full document: changes in RAGFlow do not rewrite past evidence.
Missing source records are shown as unavailable rather than turned into guessed
links. Source snapshots do not add a knowledge-management page or expose the
RAGFlow API key. Durable batch exports and standalone Markdown files do not
carry these interactive conversation source records.
Ordinary document-title links in a Sources section open the same evidence as
inline citations. When a tool-output budget applies, only complete evidence
entries that fit remain citable; omitted sources are reported rather than
retaining a source record for a cut-off excerpt.

DeerFlow can optionally connect to a tenant-scoped RAGFlow deployment. The
`knowledge_search` Agent tool resolves the configured dataset scope, groups
datasets by embedding model, and retrieves those groups in parallel so mixed
embedding models do not cause a provider error. Dataset IDs and API keys are
never exposed to the model. The optional `list_knowledge_bases` tool returns
names only.

Main and custom-agent chats can optionally expose a page-local, icon-only
**Knowledge** selector beside the mode control. Its persistent highlight
indicates that knowledge retrieval is active; the neutral state means retrieval
is off. Set `knowledge_base.scope_selection_enabled: true` in `config.yaml`
while using the built-in RAGFlow `knowledge_search` provider to allow all
permitted datasets, selected datasets/files, or no retrieval for a turn. The
same config flag controls both chat types; when disabled, neither composer
shows the selector or submits a scope. The choice resets to the custom agent’s saved default (or all when unbound)
when the page is refreshed or another conversation is opened; each sent human message keeps
an immutable scope snapshot for replay and history. The Gateway validates
every snapshot, intersects it with the operator's dataset allowlist, propagates
the execution-only scope to native and durable subagents, and removes it from
model inputs and external traces. Client-supplied internal runtime controls
and credentials are also stripped from run context before execution or
checkpoint persistence. Idempotent retries accept both canonical snapshots and
legacy raw run inputs, preserving retry compatibility across upgrades.
Custom agents can save a **Default knowledge** selection from **Agents → Agent
settings**, including optional file filters or retrieval off. Selecting all
knowledge bases clears the binding. The same `knowledge_scope` field is available
on agent create/update APIs and in the agent's stored configuration; omitted
updates preserve it and `null` clears it. It is a default, not an authorization
boundary: an explicit per-message selection overrides it, and the operator's
allowlist still applies at retrieval time. Gateway runs without a message scope
(including scheduled and channel turns) use and snapshot the saved default even
when the composer selector is hidden. Regenerate/resume retain the original
turn's scope, including legacy unscoped turns, rather than picking up later
configuration changes. Unknown or unavailable selections never broaden retrieval.
Idempotent retries keep the original run and scope when a default is added,
changed, or cleared, including unscoped runs accepted before this feature.
This default applies to Gateway-hosted custom-agent turns; direct harness/client
integrations continue to supply their own execution scope.

In Agent settings, **Tool access** can inherit every configured tool group,
allow selected groups, or disable all groups. Saved groups stay visible and
removable while the catalog loads or fails to load. A saved group is marked
unavailable only when a successful catalog load confirms it is missing.
Saving a selection that removes `knowledge` also clears the saved default
knowledge selection. The in-chat `update_agent` tool applies the same rule
when it changes the tool groups to a list without `knowledge`, so later
Gateway turns do not inherit an unusable scope. `PUT /api/agents/{name}` also
clears this inherited default on such a change when `knowledge_scope` is
omitted; an explicitly supplied scope or `null` still takes precedence.
Unrelated updates, unchanged groups, and inheriting all tool groups preserve
the default. When enabling knowledge access for an agent that
previously lacked it, save the tool access first, then reopen settings to
choose its default knowledge bases.

The `knowledge_base` block is provider-neutral and only controls whether the
knowledge capability and selector are enabled. RAGFlow connection, dataset
allowlist, and retrieval parameters (`base_url`, `api_key`, `datasets`,
`page_size`, thresholds, and output limits) must be configured on the
`tools[].name: knowledge_search` entry; they are never read from
`knowledge_base`.
Custom-agent chat requests carry the selected agent name as both `assistant_id`
and `context.agent_name`, so Gateway scope admission and runtime agent loading
use the same identity. Main chat requests use `lead_agent`; both identities are
admitted only when the shared configuration enables the RAGFlow provider.
When answering a pending clarification, an explicitly submitted current
selector snapshot wins; clients that omit it inherit the prior turn's accepted
scope. Edit-and-regenerate follows the same fallback, and the file catalog is
loaded only after a dataset is switched from all files to selected files.
This release does not add an independent Knowledge item to the workspace
sidebar or a DeerFlow knowledge-management page; create, upload, parse, and
delete datasets and documents directly in RAGFlow.

Each message can still select up to 1000 documents. When more than 100 documents are selected from a single dataset, DeerFlow validates them in batches of at most 100 while preserving the complete selection. If any batch contains an inaccessible or non-searchable document, retrieval is rejected.

Advanced deployments can enable pluggable authorization with `authorization.enabled` in `config.yaml`. A configured `AuthorizationProvider` filters denied tools before they reach the model or deferred-tool catalog, then the same provider is checked again before every business-tool execution through the existing guardrail middleware. Gateway `threads:*` and `runs:*` route permissions are derived from the same provider, while existing owner checks and admin-only management gates remain in force. Every HTTP route that starts or enables a future Agent run requires `runs:create`: this includes the stateless `POST /api/runs/stream` and `POST /api/runs/wait` endpoints plus scheduled-task create, update, resume, and manual-trigger mutations. Scheduled-task mutations retain their existing `threads:write` requirement, and the stateless routes separately enforce ownership when the optional thread ID is supplied in the request body. A generated `tool_search` may bypass the second tool check only when it fronts the current build's already-filtered deferred catalog. Model access follows the same provider: the Gateway `models` list is filtered per principal, `model:use` is enforced on model detail requests and again when the runtime resolves the agent's model, and a denied default model falls back to the first remaining candidate that also passes `model:use`. The built-in RBAC provider supports per-role `tools`, `routes`, `models`, `skills`, and `sandbox` allow/deny policies and validates that `default_role` names a configured role; authorization is disabled by default. Custom roles declared in the provider's `roles` mapping become reachable by assigning them to a user through the admin API (`GET /api/v1/admin/users`, `PATCH /api/v1/admin/users/{id}`; admin-only, last-admin demotion protected) — a declared role nobody holds grants nothing. See `config.example.yaml` and the [authorization RFC](../../docs/plans/2026-07-10-pluggable-authorization-rfc.md).

Administrators can revoke a disabled account's admin role while keeping it disabled,
or assign a non-admin role and re-enable it in the same account update. The last
enabled administrator remains protected against demotion and disabling.

Follow-up suggestions also check `model:use` before calling the selected model, including the default model when no name is supplied. A denied model returns HTTP 403 without an LLM call; authorization-provider failures follow the configured `fail_closed` policy.

For vision-capable agents, `view_image` and the subsequent model-context image read also require `sandbox:execute`. Allowing the tool name alone does not grant image-file access; a role denied sandbox execution cannot reread previously recorded image metadata after its permissions change. External run input and thread-state updates cannot set `viewed_images` or `thread_data`; when a saved image is read from a host copy, its path must resolve to the current user's thread and the recorded virtual image path.
Each model request includes at most four recently viewed images and 28 MiB of base64 image data. Images excluded by these limits are reported as omitted; the agent can call `view_image` again to bring one back into context.

Advanced deployments can also extend the agent runtime itself by declaring `AgentMiddleware` classes under `extensions.middlewares` in `config.yaml` or `extensions_config.json`. Each entry is a `module.path:ClassName` string (zero-argument constructor) or an object `{class, kwargs, apply_to}` whose `kwargs` are passed to the constructor. Optional `apply_to` selects `both` (default), `lead`, or `subagent`; legacy strings still apply to both chains. `kwargs` values must be JSON types (object, array, string, number, boolean, or null); YAML dates and timestamps are coerced to ISO strings so they match JSON. DeerFlow loads the selected configured entries into the lead-agent and subagent pipelines after their built-in runtime middlewares and loop/token guards, but before the terminal-response/safety/clarification tail, so enterprise forks can add domain guardrails, tool-call governance, or observability hooks without patching the built-in middleware builders. Missing packages, invalid classes, broken modules, and constructor errors fail loudly at agent creation. Treat `config.yaml` and `extensions_config.json` as trusted operator-controlled files: middleware paths are code execution, just like custom tool, model, sandbox, guardrail, MCP server, and MCP interceptor declarations. Gateway skill/MCP toggle endpoints preserve this field but do not expose an API write path for `extensions.middlewares`. Entries excluded from a chain are not imported or constructed there. Invalid scope values fail configuration validation, and selected entries retain their relative order. Packaged extensions continue to use their existing `AgentScope` contract.

For packaged and configurable runtime integrations, use DeerFlow's extension manager.
It accepts a Python package requirement, a public HTTPS Git URL, or a local directory, installs the
package into the backend's dedicated `extensions` dependency group, updates
`backend/uv.lock`, and adds an enabled entry to the startup-only top-level `plugins:` list
in `config.yaml`:

```bash
# PyPI — pin a version for a reproducible deployment
make extension-install SOURCE="deerflow-extension-acme==1.2.3"

# Public HTTPS Git — pin an immutable commit
make extension-install \
  SOURCE="git+https://github.com/acme/deerflow-extension-acme.git@0123456789abcdef0123456789abcdef01234567"

# Local package — an absolute path avoids Make's backend-relative working directory
make extension-install SOURCE="$PWD/examples/deerflow-extension-example"

make extension-list
make extension-upgrade SOURCE="$PWD/examples/deerflow-extension-example"
make extension-disable NAME=acme
make extension-enable NAME=acme
make extension-remove NAME=acme
```

Installation is interactive because package installation can execute Python build hooks,
and the loaded extension later runs with Gateway privileges. For an already-reviewed
source, automation can acknowledge that boundary explicitly with
`cd backend && uv run --frozen --no-group extensions deerflow extensions install <source> --yes`.
The manager requires uv 0.8.0 or newer; the provided Docker images pin uv 0.11.1.
The other direct
commands are `deerflow extensions upgrade SOURCE`, `list`, `enable NAME`, `disable NAME`, and `remove NAME`;
`NAME` may be the extension name, Python distribution, or `module:install` value. Do not
put credentials in a source URL — a URL carrying embedded userinfo or a credential-looking
query parameter is rejected before uv runs. Remote Git sources must use public HTTPS; SSH
Git URLs are rejected because the stock Docker builder does not forward host SSH
credentials. Installing from a loopback URL is allowed for local tooling but warns, because
`127.0.0.1` recorded in the lock is a different machine inside the Docker builder.

For scripts, `deerflow extensions list --json` returns a JSON array in configuration
order, with `name`, `package`, `entry_point`, `enabled`, and `required` fields. An
unspecified package is `"-"`; an empty inventory is `[]`. Private plugin configuration
and source metadata are excluded. The default `list` output remains a table.
For example, from `backend/`, check that `demo` is configured as enabled and required:

```bash
inventory=$(uv run --frozen --no-group extensions deerflow extensions list --json) || exit 1
printf '%s\n' "$inventory" |
  jq -e 'any(.[]; .name == "demo" and .enabled == true and .required == true)'
```

This reports configured state without executing plugins or changing files; it does
not verify package installation or successful Gateway loading. Configuration errors
exit non-zero with diagnostics on stderr and no inventory on stdout.

A managed package declares exactly one standard PEP 621 entry point:

```toml
[project.entry-points."deerflow.extensions"]
acme = "acme_deerflow_extension:install"
```

That callable uses the standalone `deerflow-extension-api` contract and can register several
contribution kinds: isolated middleware at semantic lead/subagent model or tool positions,
lead and subagent task-lifecycle hooks, observers for DeerFlow-owned model calls that are
not wrapped by middleware model-call hooks (goal, memory, title, and summarization),
Gateway-lifetime services, and eager FastAPI HTTP routers. The contract package has no
framework dependencies; extensions must declare FastAPI, LangChain, LangGraph, or other
libraries they import.
Cancelled subagents report `aborted` to task-lifecycle hooks after stream cleanup;
synchronous timeouts remain failures, and background hard timeouts retain their
failure outcome.
The [fetched-content screening example](../../examples/deerflow-extension-jev-screening/README.md)
contributes one such middleware at the visible tool position. After operator opt-in it
classifies the sanitized text a remote tool result shows the model, PII-redacted when
`pii_redaction` is enabled, and adds an advisory warning through a lifecycle state
update; it imports only the extension contract.

Extensions may opt into owner-scoped completed-run evidence and safe updates to
existing user-custom skills through `host_access` in operator-controlled
`config.yaml`. These optional APIs stage an immutable candidate, check its exact
contents, and publish with version conflict detection and crash recovery. They
do **not** implement a learning/evolution plugin. Automatic changes are limited to
the body and description of `SKILL.md`; changing permissions, supporting files,
or enabled state is out of scope. The host contract requires `deerflow-extension-api==0.2.7`. See [Skill evolution host API](../../docs/skill-evolution-host.md)
for deployment requirements, grants, recovery, and the plugin integration flow.
Once an owner is enrolled, use the Gateway for skill management: standalone SDK
processes without its durable mutation runtime refuse enrolled skill access,
including custom-skill YAML diagnostics. Gateway diagnostics recover pending
publications before scanning.
Skill discovery preserves user scope when the caller uses the default configuration.
Admin operation lists return `next_cursor: null` at the end of pagination.
Keyed resume retries preserve the original run's evidence origin and agent identity.
This host slice follows up the [Skill Self-Evolution RFC](https://github.com/bytedance/deer-flow/issues/1865)
and the bilingual [Plugin Host APIs RFC](https://github.com/bytedance/deer-flow/issues/5539).

Full-stack contributions can additionally provide browser pages, conversation actions,
authenticated backend operations and model tools through the
[plugin APIs](../../docs/full-stack-plugins.md). The independent
[bookmarks example](../../examples/deerflow-extension-bookmarks/README.md) demonstrates
one package with persistent user data, its own sidebar page and a read-only search tool.
Model tools can opt into separate structured artifacts with
`response_format="content_and_artifact"` and `PluginToolResult` (extension-api
0.2.6). Artifact object keys must be strings at every depth. Existing tools keep
their JSON text output. The
[local retrieval example](../../examples/deerflow-extension-retrieval/README.md)
demonstrates bounded, read-only results and checkpoint replay without an external
knowledge service; artifacts do not automatically enable citations. It also appears
in the extension catalog with localized installation-guide metadata.
Reopening a bookmark resolves the conversation's current agent through the host, so
custom-agent conversations retain their original chat entry point, including older bookmarks.
In **Capabilities → Extensions**, an enabled extension’s detail page links directly to its registered workspace pages. The page also includes usage guidance and keeps package details under **Technical details**.
Extension packages can provide localized purpose and usage steps in `deerflow-extension.json`, including optional prerequisites. The same detail page supports background extensions without a browser module. All bundled examples include this description; see the [authoring contract](../../examples/README.md#describe-the-extension).

The independent [Agent teams example](../../examples/deerflow-extension-agent-teams/README.md)
lets full Custom Agents collaborate through native `@` mentions, shared messages and
asynchronous peer requests, with a separate team page and persistent member conversations.
Capability Center lists the example with localized installation information even before it is installed.
Installation and activation remain deployment-controlled; Capability Center shows plugin
information and status. Browser code runs as trusted same-origin code.
The browser API and inline `BrowserModule.code` transport are experimental. The
plugin guide describes an additive path to manifests and packaged static resources.

DeerFlow allocates a task-scoped extension store only for middleware, lifecycle, or
system-model observation. Services receive app-scoped runtime dependencies after Gateway
persistence is ready and stop in reverse order after active runs drain. The optional
`ExtensionRuntimeDeps.run_evidence_reader` is a stable, read-only interface for audit,
evaluation, synchronization, and observability services: it discovers changed runs with an
opaque resumable cursor, pages a known run's persisted events with `after_seq`, and reads the
authoritative run status separately from event evidence. A database-backed run store keeps
the discovery cursor valid across Gateway restarts; the memory run store provides the same
ordering only for the current process lifetime. Event metadata is secret-redacted at this
boundary, but event content is returned unchanged. Both payloads are detached snapshots,
so modifying nested values cannot change the host's stored evidence. The production
Gateway supplies an
app-scoped, cross-user reader to trusted operator extensions; an embedded host may bind the
same adapter to one user. Changed-run pages contain creations and changes to retained rows,
not deletion tombstones; consumers that reconcile deletions must poll status for known runs
and treat a missing result as absent. Extensions still execute with Gateway privileges and
retain the legacy `session_factory`, so the reader is an API-stability and
least-accidental-privilege boundary, not a sandbox for untrusted Python packages. Extension HTTP
routers are mounted after every host route; definite shadows and routes entering the
host's authentication- or CSRF-exempt paths are rejected with attributed diagnostics,
while unrelated routers continue to load. Because the host's public paths are a reserved
prefix list that extensions cannot enter, **every contributed endpoint requires an
authenticated session** — there is currently no way for an extension to expose an
unauthenticated route, so inbound provider webhooks and public status endpoints are out of
scope for this release. Within that, an extension distinguishes an ordinary user from an
administrator through `deerflow_extension_api.auth`: `resolve_principal(request)` returns
the caller, `require_admin(request)` raises `PermissionError` for anyone else and fails
closed when identity cannot be determined. Extensions receive a projection — user id, admin
flag, internal flag, roles — never the host's auth context. Router startup/shutdown hooks,
custom lifespans, Mounts, and WebSocket routes are not accepted; lifetime resources belong in
`ExtensionService`, and WebSocket contributions require a future host-owned
authentication/Origin wrapper. Lifecycle and system-model callbacks use the Gateway's
canonical notification loop, including subagents on isolated loops.

User-facing extension routes can call
`deerflow_extension_api.require_run_evidence_reader(request)` (extension API 0.2.2+).
The Gateway requires authenticated `runs:read` permission and fixes the reader's scope
to that user, including administrators and internal callers. Caller-supplied IDs cannot
change that scope. Invisible and missing runs return the same result; changed-run cursors
cannot be reused directly across users. The optional `resolve_run_evidence_reader(request)`
returns `None` when the host does not support the capability; the required helper raises
`NotImplementedError` instead. Denied access raises `PermissionError`. Routes should map
these exceptions to HTTP 503 and 403 respectively; resolver failures never fall back to
the global service reader.

Extension services can optionally receive a [host model invoker](../../backend/docs/extension-model-invocation.md)
(extension API 0.2.4+). Operators explicitly map allowed logical roles under
`plugins[].host_access.model_invocation`; the host handles credentials, concurrency,
  timeouts, and schema-validated output. Admission is bounded; timed-out provider work
keeps its concurrency slot until completion, and schema validation runs in terminable
child processes. A provider's own cancellation becomes `ModelInvocationFailed`,
while cancellation of the calling extension task still propagates normally.
Without a grant the capability is `None`.

Plugin order is deterministic, per-plugin configuration is passed to `install()`, and
`required: true` makes load failure abort startup; otherwise failures are reported and
skipped. `enabled: false` skips resolution and import. The manager preserves the extension's
private `config` when toggling it and writes `name`, `package`, `use`, `enabled`, and
`required` metadata for managed installs. Installs are recorded `required: false` so a
later broken extension is reported rather than blocking Gateway startup; pass
`extensions install <source> --required` when the package's absence should abort startup
instead. Plugins load once when the Gateway app is
constructed, so install, enable, disable, remove, and manual `plugins:` edits all require a
Gateway restart. Because this imports Python code, `plugins:` is intentionally unavailable
through the API-writable `extensions_config.json`.

Management commands bootstrap the checkout environment without the extension group via
`uv run --frozen --no-group extensions`. Frozen mode lets `disable` and `remove` start even
when an installed extension's remote source or managed snapshot has become unavailable,
while a fresh checkout can still create the non-extension environment from the existing lock. The
manager itself owns the subsequent locked dependency transaction.
Mutations for one checkout are serialized through a process lock.
Failed extension operations restore dependency files and configuration atomically with
their original file permissions, preserving access for a Gateway that reads them through
group permissions.
The initial manager surface is create/remove rather than in-place upgrade: to change an
installed source, save
its private `plugins[].config`, remove it, reinstall the new pin, and restore that config.

Local-directory installs are copied into
`backend/extensions/sources/<normalized-distribution>/`; this deployable snapshot, rather
than the original directory, is recorded in the lock. Git metadata, virtual environments,
bytecode caches, symbolic links, and likely credential files are not accepted as snapshot
content. Review what you install anyway: filtering accidental files does not sandbox an
extension, its build backend, or its runtime code.

Local `make dev`/`make start`, Docker development, and the production Gateway image all
consume the same `backend/pyproject.toml` and `backend/uv.lock`. Local and Docker-dev
launchers perform a locked sync before starting; the production image performs that sync
during its build and includes managed local snapshots in the build context. Gateway runtime
commands then use the already-created environment without resolving or installing packages.
Local and Docker-development pre-start syncs may download missing locked artifacts. A
production deployment instead downloads them only during the explicit install or image
build; starting the resulting production Gateway container never resolves or installs
extensions from the network. A local wheel or `file://` Git URL is rejected because it
would not exist in the Docker build context; pass a source directory to create a managed
snapshot instead. Because environment configuration (such as a `UV_FIND_LINKS` wheelhouse)
can still resolve a plain package name to a local wheel, the manager audits every new lock
before enabling the extension: any local reference the stock image build cannot reproduce
rolls back the entire install or removal.
Rebuild with `make up` after changing the managed extension set. See
`config.example.yaml` and the
[reference extension](../../examples/deerflow-extension-example/) for a complete example.

Gateway-generated follow-up suggestions now normalize both plain-string model output and block/list-style rich content before parsing the JSON array response, so provider-specific content wrappers do not silently drop suggestions. Follow-up suggestions and input polishing skip content blocks with non-string types, preserving the surrounding text instead of failing the request

Visible-content detection (`has_visible_content`, shared by the empty-response, terminal-response and model-length middlewares) and the subagent dispatch snapshot (`ParentContextSnapshot.from_state`) probe content-block types by equality rather than set membership, so a provider-emitted block with an unhashable type such as `type: []` degrades to a skipped block — keeping the surrounding history — instead of raising TypeError out of the middleware chain

Backend response cleanup preserves unrelated tag names such as `<think-tank>` and `<think:note>` in follow-up suggestions and polished drafts; only the exact `<think>` name (optionally followed by attributes) starts a reasoning block. Self-closing `<think/>` and `<think />` tags are empty reasoning blocks and leave the following answer intact. Delimiters inside quoted attributes, such as `<think note=">"/>`, also leave the following answer intact.

The Web UI composer can polish draft input before sending. The rewrite runs as a short Gateway LLM request using the `input_polish` model configuration, keeps slash skill prefixes such as `/data-analysis`, and only replaces the local draft after the user clicks the polish button; it does not create a thread run or persist a message.

Input polishing, follow-up suggestions, background project-file summaries, the
LLM skill scanner, thread title generation, the `/goal` evaluator, and manual
context compaction (`/compact`) construct their model providers off the
Gateway event loop, so local credential reads do not stall unrelated
requests.

When the agent asks for clarification, the Web UI shows the structured response card but keeps the normal composer available. Users can complete the card or send a free-form chat message to bypass it; that message closes the latest pending clarification and becomes the agent's next input. Accompanying answer text stays outside the execution steps panel, and answering the request keeps previously completed text in the conversation while the agent continues.

Unsent Web UI composer drafts survive page reloads and switching between conversations within the same browser tab. Drafts are isolated by user, agent, and conversation, include the selected skill and explicit conversation references, and are cleared once a send is accepted. Project documents already attached to the thread also survive reloads; browser-local uploads and quoted message excerpts are not persisted.

The composer's paperclip button opens the local file chooser directly; the `@` button opens the reference picker for skills, project files, conversations, and plugins.

If an attachment upload reports `success: false`, the Web UI stops the send even when the HTTP response is 200. The upload error is shown and the composer keeps its draft and attachments for correction or retry. Files already accepted by a partially successful upload remain on the server; this does not roll them back.

Document conversion reads the live PDF-converter setting and parses documents in a background worker, keeping configuration-file checks off the Gateway event loop.

The Web UI composer supports `@` references at the cursor or through the `@` button. Search enabled skills, documents in the current project, and other conversations in a grouped picker; selected references appear inline alongside the draft text and can be removed with normal editing. Multiple skills can be selected in one message (up to 16 unique skills); selecting a checked skill again removes it, with each selection checked against the current user registry and agent allowlist. Project files are attached only after ingestion succeeds; conversation references require the `read_conversation` capability and retain its per-run limit. If capability discovery fails, saved conversation references remain intact and sending waits for a successful retry. Polishing preserves complete reference labels when instructions are reordered. The file group also offers local uploads. `/goal`, `/compact`, and legacy `/skill-name` input remain supported.

After picking an inline reference, typing continues immediately after it. Moving the cursor keeps the position you chose, including when editing text beside a reference.

The Web UI composer also supports browser-based voice dictation when the browser exposes the Web Speech API. The microphone button transcribes speech into the local draft only; DeerFlow receives only the transcribed text, while audio handling is delegated to the browser or operating system speech-recognition service according to that environment's policy. Users can review or edit the text before sending. Dictation keeps words separated when browsers trim transcript segments, preserves Chinese and Japanese joins, and attaches leading punctuation and percent signs without adding spaces.

The Web UI displays a localized AI-generated-content disclaimer below the composer in both standard and custom-agent conversations, reminding users to verify important
information.

Interrupted first-turn runs still persist a fallback conversation title, so stopping a streaming response does not leave the thread as "Untitled" after refresh.

Updating a subgraph checkpoint's title through the state API keeps the root conversation's title unchanged.

Streaming Markdown responses animate only newly arrived words; text that is already visible is not faded out and replayed when the next chunk extends the same block.

In the Web UI, completed assistant turns can be branched into a new main conversation. Automatically inherited branch titles use the next free language-neutral numeric suffix (`Title (2)`, then `Title (3)` for another sibling or a branch of the numbered conversation) so generated sibling titles remain distinct without persisting a locale-specific label; matching explicit or renamed sibling titles also reserve their displayed suffix even though they carry no generated sequence metadata. An explicit API title is preserved. Renaming a branch clears its generated sequence, so its next automatic branch starts from the renamed title at `(2)`. Recent chats also groups loaded branches directly beneath a loaded parent with subtle tree connectors. Missing parents, malformed or cyclic lineage, and branches in a different pinned state stay visible at the top level instead of being hidden or moved across the pinned boundary. The new thread starts from that turn's checkpoint and keeps the preceding replay checkpoint, so the branched response can be regenerated immediately. The latest response can also be regenerated after an interruption, even when its streamed partial text never reached a checkpoint. Stopping mid-answer retains the assistant text that was already streamed in the thread's message feed, so refreshing no longer discards visible progress; that partial text remains outside authoritative completed checkpoint state. Regenerating the latest response preserves the thread's current title, including a title you renamed manually after the original response. Legacy or imported histories without checkpoint parent links use a bounded chronological fallback; if no earlier replay checkpoint exists, branching still succeeds with the legacy single-checkpoint shape, while regeneration remains unavailable for that inherited response. Existing single-checkpoint branches are left unchanged rather than attempting an unsafe checkpoint copy. Because workspace files are not checkpointed, the branch only receives a best-effort copy of the current workspace when you branch from the latest turn; branching from an older turn keeps just the restored message history so the branch never inherits files that were created in a later part of the conversation.

Branches preserve the source conversation's valid agent selection. A branch of a legacy conversation with an invalid agent ID uses the lead agent instead.

The Web UI reports completed task time once per run. This is total wall-clock time—including model reasoning, tool calls, and waiting—not a per-step or model-only thinking duration. Reasoning content remains available through its own separate disclosure.

While a response streams, reasoning-only messages stay in the processing panel, including Anthropic thinking blocks. Once answer content arrives alongside reasoning, it appears in an assistant bubble.

Literal `<think>` tags in fenced, indented, or inline code remain part of the answer and its copied text, rather than being moved into the reasoning disclosure. This includes fences opened on list-item lines: real reasoning after the code is still extracted. Unfinished inline code spans are preserved while streaming within a paragraph, but end at a blank line or an interrupting heading, list, thematic break or fence. Indented paragraph continuations do not start a code block.

In the Web UI, the latest completed user turn can also be edited and rerun from the message toolbar. DeerFlow restores the conversation checkpoint before that user message, submits the edited text as a new user message, and hides the superseded turn once the replay is in progress or succeeds. This is a conversation-state replay only: files, memory updates, and external tool side effects are not undone.

Web UI chat links percent-encode custom thread identifiers before placing them in route segments, so reserved URL characters such as `#` and `?` do not change which conversation is opened.

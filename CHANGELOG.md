# Changelog

All notable changes to DeerFlow are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

This section accumulates work toward the **2.2.0** milestone
([2.2.0](https://github.com/bytedance/deer-flow/milestone/3)).
This release closes that milestone with **181 merged pull requests**.

### Added

#### Scheduler

- **scheduler:** Scheduled tasks can be searched by title or prompt. Finding a
  task previously meant scanning every title or opening details to read its
  prompt. A search field above the existing filters matches a literal, trimmed,
  case-insensitive substring of either field (including Chinese), composes with
  the status/type filters and thread scope, and clearing it retains the other
  filters; when nothing matches, task actions hide with localized feedback. Runs
  entirely on the existing authorized list response — no API change. ([#5355])

#### Agents & runtime

- **uploads:** Add stable cursor pagination to the `list_uploaded_files`
  discovery tool. With more than 100 historical uploads matching the same
  filters the tool could only return the first page, giving an agent no
  continuation path. An optional `cursor` input and `next_cursor` output now
  paginate past the default page of 20 (maximum 100), sorted by nanosecond
  modification time descending with a deterministic raw-filename tie-breaker.
  The token binds to the runtime-resolved user/thread, normalized filters,
  current-run exclusions, and ordinary-file metadata; malformed or invalidated
  continuation returns controlled restart instructions telling the client to
  discard previously collected pages. `total_count` still covers all filtered
  matches and no new dependency, storage layer, or HTTP endpoint is involved.
  ([#5570])
- **agents:** Custom agents can persist a default knowledge scope in agent
  settings, so a specialized agent starts each conversation with its own
  corpus instead of all operator-approved knowledge bases. When a new turn
  omits an explicit selection — including callers without the composer
  selector — gateway admission applies the saved default; an explicit
  per-message selection still wins, selecting all knowledge bases clears the
  binding, and regenerate/resume retain the source turn's accepted scope.
  This is a default, not an access-control policy: operator allowlists and
  dataset availability are still enforced. ([#5579])
- **config:** Operators can now overlay core system prompts without source
  patches. `lead_prompt_overlay.prepend/append` wraps the assembled lead
  prompt, `subagents.agents.<name>.prompt_overlay` extends built-in and
  configured subagent prompts without mutating the shared registry, and
  DeerMem's `memory.backend_config.prompt_prepend/prompt_append` extends the
  rendered memory-update system message. Empty overlays preserve prompt bytes
  and overlay text is literal, so stock behavior is unchanged until an
  operator opts in. ([#5794])

#### Memory

- **memory:** Cross-session memory gains `user.cognitiveStyle` for stable
  collaboration preferences (response structure, depth, correction style),
  stored and injected separately from `personalContext` and task skills so a
  protocol like "conclusions first" no longer competes with project facts under
  `max_injection_tokens`. Legacy `memory.json` files are normalized on load, the
  `<memory>` injection gains a `Thinking Style:` line (plus optional
  `category: cognitive` facts), and the field is editable in Settings → Memory
  and exposed through the Gateway memory API. ([#3182])
- **memory:** The sample-memory loader can now bulk-load registered users.
  It previously wrote the legacy shared memory path while authenticated users
  read per-user storage, so a successful load still left Settings showing no
  memory. `scripts/load_memory_sample.py` requires exactly one of
  `--target PATH` or `--all-users`; `--all-users` enumerates registered users
  from the configured persistent database and backs up each user's existing
  memory before replacing it. Non-persistent database modes are rejected.
  ([#4066])
- **memory:** Memory search and injection can rank candidates by lexical relevance
  instead of confidence alone. Confidence-only injection could prefer unrelated
  facts over ones useful to the current task; opt-in `retrieval_relevance_enabled`
  (default `false`) blends IDF-weighted query coverage with confidence, applies
  category filtering before `top_k`, and can diversify selections — no embeddings,
  vector storage, or persisted-format changes; the tokenizer handles CJK bigrams
  without new dependencies. Legacy `get_context` implementations keep working.
  ([#5251])
- **memory:** Add an opt-in tolerant `MarkdownMemoryStorage`
  (`memory.storage_class: markdown`) for the user-memory summary store. Corrupt
  or partially written files no longer raise `MemoryStorageCorruption` and crash
  the agent: a Markdown summary is understood via a lossless fenced
  `memory-json` block with a best-effort structured fallback, and plain JSON
  still loads. The on-disk JSON format and the JSON UI are unchanged, and writes
  remain journaled JSON — this ships read-path tolerance only; a full Markdown
  write path is a follow-up. ([#5545])
- **memory:** Add a deterministic DeerMem scope-isolation benchmark under
  `backend/scripts/benchmark/deermem_scope_isolation`. The opt-in
  validate/run/report workflow exercises lifecycle durability, concurrent
  corrections, and isolation across agent and user memory scopes, and changes
  no runtime memory behavior. ([#5564])

#### Knowledge & retrieval

- **knowledge:** Custom-agent chats can scope RAGFlow retrieval per message. An
  opt-in Knowledge selector picks all operator-approved datasets, specific
  datasets/files, or no retrieval for one turn; the choice is stored as a
  validated, immutable `knowledge_scope` snapshot on the HumanMessage and
  enforced at Gateway admission, middleware, RAGFlow retrieval, and native and
  batch subagents — out-of-allowlist selections fail closed, and scope ids never
  reach model inputs or tracing. Off by default via
  `knowledge_base.scope_selection_enabled` (config version 41). ([#5238])
- **ragflow:** RAGFlow retrieval results now carry verifiable source citations.
  Clicking an inline knowledge citation, a document-title link in Sources, or
  the answer's knowledge sources list opens the retrieved excerpt, dataset and
  document names, and page numbers when RAGFlow supplies them, and sources
  remain available after conversation reload. `knowledge_search` pairs the
  opaque citation links with bounded native tool-message artifacts holding the
  exact excerpt given to the model (truncation marked, configured API key
  redacted); ordinary `task` results forward only captured sources cited in the
  child's result; and output budgeting retains complete evidence entries under
  the active limit, omitting non-fitting entries with a notice. Missing records
  display as unavailable. These are retrieval-time evidence snapshots, not a
  live full-document viewer; existing direct `knowledge_search()` callers keep
  the string return type. ([#5551])
- **community:** The image search tool exposes the `color` and `license_image`
  filters. Both were wired into the request path but unreachable from the tool
  signature, so agents could not narrow results to a palette or to
  license-cleared images when sourcing references for image generation. Valid
  values follow `ddgs` (`color`: `Monochrome` through `White`; `license_image`:
  `any`, `Public`, `Share`, `ShareCommercially`, `Modify`, `ModifyCommercially`);
  unset filters produce exactly the same request as before. ([#5723])

#### Skills

- **skills:** Show which skills an answer loaded, with inspectable snapshots.
  Successful configured `SKILL.md` reads and explicit slash activations now record
  a bounded, read-only snapshot, and the answer toolbar gains a Skills menu listing
  only the skills that answer's own run loaded; selecting one opens the captured
  file (original Markdown including frontmatter, package-relative links kept as
  non-navigating references) in a resizable desktop panel or a mobile sheet, with
  copy returning the original Markdown. The run journal persists a first-load-order
  aggregate on the terminal answer so paginated history keeps the evidence, and the
  entry is hidden when no load evidence exists. ([#5758])

#### Models & integrations

- **models:** Administrators can manage shared models from Settings → Models
  without editing server configuration. New administrator-only
  `GET/PUT /api/managed-models` and `POST /api/managed-models/test` endpoints
  maintain an encrypted catalog under `$DEER_FLOW_HOME/managed-models/` —
  credentials are never returned, omitted keys retain the saved value, and
  stale edits are rejected by revision. Enabled managed profiles are appended
  to new effective configuration snapshots; YAML profiles remain read-only and
  win name conflicts. The first version supports OpenAI-compatible Chat
  Completions endpoints; existing model authorization still applies. ([#5596])
- **models:** Add a declarative reasoning capability contract for model profiles. A
  model can declare an optional `reasoning:` block (`thinking:
  unsupported|optional|required`, `on_disable_request`, `dialect`, `history`, and
  `effort: {values, default, aliases, path}`) beside the legacy booleans, and
  contradictory profiles fail at config load. `create_chat_model` enforces one
  normalized policy everywhere — lead agent, subagents, summarization, and title
  generation — so a required-thinking model never enters the disable branch and
  effort values map through aliases or fall back to the declared default instead
  of being sent verbatim. `GET /api/models` and `DeerFlowClient` gain a `reasoning`
  object (`source: legacy|contract`), the frontend derives the effort menu from the
  model's declared values (e.g. `Low/High/Max` for GLM-5.3-Flash) and hides "off"
  for required-thinking models, and `PATCH /api/v1/auth/preferences` accepts
  provider-specific effort tokens. Profiles without the block keep the unchanged
  legacy path. ([#5780])

#### Channels

- **channels:** WeChat can be connected by scanning a QR code from the web UI.
  The connection dialog in the sidebar and Settings gains QR login with
  progress, pairing-code input, expiry and retry states, and a "Scan again"
  option that preserves an unexpired binding command; credentials are saved on
  the backend and only the WeChat channel restarts. New WeChat connections
  default to QR login, with manual token entry still available. ([#5582])

#### Auth & guardrails

- **authz:** Make the `skills` policy key govern visibility on the user-facing skill
  listing surfaces. A role whose policy denied skills still saw every skill in the
  slash-command autocomplete, `GET /api/skills`, `GET /api/skills/custom`, and
  `GET /api/skills/{name}`, discovering the denial only at activation time. Listing
  visibility now goes through `filter_resources(principal, "skill", ...)`, mirroring
  `list_models`: denied names disappear from the listings, the detail endpoint returns a
  404 byte-identical to a genuine miss (no existence oracle), anonymous callers stay
  unfiltered, and provider resolution errors follow `authorization.fail_closed`.
  Admin management endpoints stay `require_admin_user`-gated; runtime activation
  authorization remains #4541's layer. ([#5489])
- **middleware:** Add deterministic, opt-in PII redaction for model-bound context
  (`pii_redaction.enabled`, default off). `PiiRedactionMiddleware` rewrites PII in
  genuine user messages and remote-content tool results (same allowlist as the
  tool-result sanitizer) to irreversible placeholders like `[EMAIL_1]`, using regex-only
  detectors — email; OpenAI/AWS/GitHub/Slack/Google API keys; Luhn-validated credit
  cards; international/CN/US phones; CN ID, CPF, CUIT/RFC national IDs. No mapping is
  stored. Placeholder numbering is stable across turns (the conversation is re-redacted
  per model call with value-deduplicated counters), externalized tool-output copies hold
  redacted text too, and subagents inherit the middleware automatically. Raw text stays
  in thread state; default behavior is unchanged. ([#5527])
- **frontend:** Gate composer send on the `runs:create` permission. Both chat routes
  resolve `canCreateRuns` and the shared composer checks it at the top of
  `submitThreadMessage`, the single choke point for the submit button, Enter-to-send,
  goal-set-triggered runs, and programmatic submits. A denied role gets a disabled send
  button that explains itself via `aria-label`/`title`, an info toast on submit, and its
  draft text kept for retry; while streaming the button remains the `runs:cancel` stop
  affordance as before. Absent or null permission lists stay permissive for mixed
  deployments. Mirrors the stop gating from #5294. ([#5528])
- **guardrails:** New opt-in TypeSafe (Jev) risk gate for tool calls,
  `deerflow.guardrails.typesafe:TypeSafeGuardrailProvider`, selected through
  `guardrails.provider.use`. Each probed call sends one yes/no question with the
  tool name and full argument JSON to TypeSafe System One and denies at
  `threshold` (default 0.5) with an error `ToolMessage` the model can adapt to.
  `allowed_tools` stays a hard permission list enforced locally before any
  request; oversized or unserializable arguments are refused locally with zero
  network requests; provider errors follow `guardrails.fail_closed`. This is the
  only guardrail provider that sends tool arguments to a third party — assess
  egress before enabling. `config_version` moves 46 → 47. ([#5712])
- **authz:** Gate plugin actions and management operations through the
  configured authorization provider. `POST /api/plugins/{ns}/actions/{name}`
  now requires a `plugin_action`/`invoke` decision on `<ns>/<action>`, checked
  after resolution and before the request body is read, denying with `403`;
  new `require_plugin_management`/`arequire_plugin_management` in
  `deerflow-extension-api` give contributed management routes a fail-closed
  check with independent `read`/`write` scopes; built-in RBAC gains
  `plugin_actions` and `plugin_management` keys, an omitted key leaving the
  resource unrestricted; plugin tool descriptors now report
  `source: "plugin:<namespace>"`. Enforcement stays off until
  `authorization.enabled: true`; extension-api contract 0.2.4 and
  `config_version` 49. ([#5842])

#### Extensions & plugins

- **plugins:** Full-stack plugin APIs and a bookmark example package. A
  deployment-installed Python extension can now ship its own browser page,
  conversation actions and model tools: `registry.plugin(PluginContribution(...))`
  (extension-api 0.2.2) registers contributions in one plugin namespace,
  authenticated descriptors, ES modules and declared actions are served under
  `/api/plugins`, and the frontend loads plugin pages, workspace pages and
  conversation actions at runtime. The `deerflow-extension-bookmarks` example
  exercises the path end to end; no plugin ships enabled by default. ([#5647])
- **plugins:** Support manifests and static asset directories for full-stack
  plugins. `BrowserAssets(module, root, manifest="ui_manifest.json")`
  (extension-api 0.2.3) joins `BrowserModule`: a versioned manifest names the
  entry module and lists the files served from namespace/content-revision
  URLs, with authentication, correct MIME types, `nosniff`, a document sandbox
  policy, and immutable caching. Packaged entries load as native credentialed
  module graphs, so a plugin can split its JavaScript and resolve CSS/images
  with relative imports; existing inline modules keep working. ([#5685])
- **extensions:** Extension routes can request a run-evidence reader bound to
  the authenticated request user. New `resolve_run_evidence_reader(request)` /
  `require_run_evidence_reader(request)` APIs return an immutable user-scoped
  `RunEvidenceReader` gated by `runs:read`, with invisible-run behavior and
  scope-bound cursor validation preserved. The existing global reader stays
  available to trusted Gateway-lifetime services.
  `deerflow-extension-api` is bumped to 0.2.2. ([#5727])
- **plugins:** New standalone `deerflow-extension-jev-context` example plugin
  (`community.jev-context`) prunes stale tool results from long conversations.
  Through the lead agent's `before_model`/`abefore_model` hooks it asks Jev
  about old read-only tool results and shortens low keep-probability ones,
  protecting recent messages, tool-call records, host-stamped errors, skill
  reads, and multimodal content. Requires deployment opt-in and an
  environment-only Jev key; failed requests preserve the original history.
  Pruning is lossy and persists in graph state — disabling the plugin does not
  restore omitted text. ([#5731])
- **plugins:** New standalone `deerflow-extension-jev-classify` example plugin
  (`community.jev-classify`) contributes a `classify_texts` model tool that
  labels `{id, text}` items against 2-32 caller-supplied categories and returns
  one label and status per item in input order. Two deployment-selected
  backends: Jev (one choice question per item) or an OpenAI-compatible chat
  endpoint asked for a validated JSON label list. Calls are batched (default 10
  per request) with bounded concurrency and a 25s deadline; failures are
  explicit per item, and nothing is retried. ([#5735])
- **extensions:** Packaged extensions can now invoke the host model under
  operator-granted limits. `plugins[].host_access.model_invocation` maps
  logical roles to models with shared per-installation concurrency, bounded
  admission, timeout, and input/output limits; extension API 0.2.4 adds the
  request/result contracts and `ExtensionRuntimeDeps.model_invoker`. Calls use
  the host model factory and tracing with inline Draft 2020-12 schema
  validation in child processes; ungranted extensions still get `None`, and
  grants follow the restart-required plugin lifecycle. ([#5796])
- **examples:** Add `deerflow-extension-jev-screening`, an opt-in packaged
  extension that flags injected instructions in fetched content as advisories.
  A `TOOL_VISIBLE` middleware classifies each text message in visible
  `web_fetch`/`web_search`/`image_search`/`web_capture` and MCP tool results
  with its own model request over the sanitized excerpt (at most eight messages
  per call), and `before_model` replaces the flagged messages of the latest
  tool step with a fixed advisory prefix, never mutating the originals. Loaded
  from `plugins:`; inert until its `config.enabled` is set, provider failures
  and timeouts pass the result through, and runs without a task store screen
  nothing. ([#5833])

#### Persistence

- **persistence:** Add a checkpoint retention service implementing the deletion
  side of #4189 item 3 on the #5255 contract. Trailing duration-only leaves are
  pruned by default (each materializes its parent's payload, so removal reclaims
  parent-sized rows without touching the surviving line); superseded leaf sibling
  branches stay opt-in via `prune_leaf_sibling_branches` because clients may hold
  them as resume targets. The resume head, its ancestor chain, and checkpoints
  with live pending-writes rows are protected. No production trigger yet — the
  invocation wiring lands separately. ([#5308])
- **storage:** Add a content-addressed blob store contract (`deerflow/storage/`),
  the storage-abstraction half of #4189 item 2. `BlobRef` (sha256, size, kind,
  content type) plus a tiered `BlobStore` interface ship with a `local_fs` default
  backend: sharded layout, atomic publish, digest verified on read, and
  concurrent puts converge. Purely additive and opt-in — `blob_storage.enabled`
  defaults to `false` and no producer is migrated yet (viewed images and
  externalized tool results are the named follow-ups), so unset deployments
  behave exactly as today. ([#5361])

#### Frontend

- **frontend:** Unify the Capability Center into a searchable catalog with plugin
  configuration and custom-agent selection. Catalog entries over the existing MCP, Lark
  CLI, and skill services carry localized metadata, categories, icons, and editable
  configuration forms; MCP installs validate required transport fields before saving,
  ordinary users see safe installation projections, and administrator mutations keep
  their role checks. Custom agents gain stable MCP installation IDs with explicit
  plugin/skill selection — an omitted/null selection inherits all enabled connections,
  an empty list selects none — with colliding installation IDs rejected on write and
  ambiguous IDs excluded at runtime; selection carries through ordinary and durable
  batch delegation without changing the shared MCP cache or granting authorization.
  Bundles DingTalk/WeCom group notification and HubSpot CRM tools; existing MCP and Lark
  workflows are preserved and nothing is enabled automatically. ([#5497])

### Fixed

- **frontend:** Stop mutating subtask render state during `MessageList` render.
  Subtask synchronization moved from render into an effect, so cards immediately
  receive pure message-derived snapshots even before the task context publishes
  an update — fixing the regression where final streamed arguments and
  `task_started` arrive together but the card keeps its partial title or empty
  prompt. Message arguments supply title, prompt and subagent type; live state
  preserves lifecycle, model, usage and step history, with terminal snapshots
  keeping status/result precedence. ([#3157])
- **skills:** Surface failed skill enable/disable requests in Settings instead of
  treating them as success. The frontend skills helpers parsed the response JSON
  without checking `response.ok`, so a 4xx/5xx from the skills list or toggle
  endpoints resolved as success and the UI flipped the switch even though the
  backend rejected the change. Non-OK responses now stay on the error path and
  show the backend error message. ([#3823])
- **agent:** Align unattended-run prompting with the tool policy. Non-interactive
  runs removed `ask_clarification` from the toolset while the system prompt still
  demanded it for ambiguity, leaving GitHub, webhook, and scheduled runs unable
  to ask or proceed. A shared `RunInteractionPolicy` now drives both toolset and
  prompt — `webhook` infers from issue and event context, exiting with structured
  blocking information when context is insufficient; `scheduled`/`autonomous`
  make minimal reversible assumptions and report high-risk ambiguity as blocked.
  ([#4919])
- **mcp:** Make the durable MCP task claim lifecycle cancellation-safe. Caller
  cancellation after a claim was acquired could leave rows leased until expiry,
  abandon a started release, or let cleanup failure replace the original
  `CancelledError`; routine shutdown was also recorded as a task failure.
  Compensation now covers every await after the claim, ambiguous operations stay
  service-owned past the foreground deadline, and per-claim lease tokens reject
  stale-generation writes atomically (closing a SQLite race). Migration `0026`
  adds nullable lease-token columns; no public MCP API changes. ([#4966])
- **frontend:** Keep streamed answer text out of the Thinking panel. A streaming
  AI message that already carried reasoning plus answer text was grouped into the
  processing disclosure until the turn settled, so the answer could sit in the
  Thinking panel for a long run; such messages now render as an assistant bubble
  immediately while plain pre-tool narration stays grouped. The bash tool's
  model-visible contract also describes cross-platform local environment
  discovery — start with `uname -s`, use `sw_vers` on Darwin, recover from
  blocked absolute paths with command-only probes. ([#5001])
- **runtime:** Harden model response recovery at provider boundaries. An empty
  completed response could end a run with no usable answer, and length-capped
  responses could carry truncated tool calls into the loop. A true empty stop is
  now retried once at the model boundary (one shared retry per run); exhaustion
  yields a visible same-step fallback instead of a hidden graph-level recovery
  turn; a detected length cap drops all tool calls in that response, even with
  parsed arguments. DeepSeek thinking-mode history keeps `reasoning_content` on
  assistant tool turns. ([#5080])
- **sandbox:** Reject overflowing sandbox ownership lease TTLs at config
  validation. `renewal_interval_seconds` and `ttl_multiplier` were each checked
  finite, but their product could overflow to `inf`, failing only at the first
  lease write or silently changing the promised timing. Non-finite derived TTLs
  and sub-millisecond Redis TTLs are now rejected, Redis TTLs are capped at half
  the signed 64-bit millisecond range, and fractional milliseconds round up so
  the stored lease is never shorter than validated. ([#5104])
- **subagents:** Close the subagent graph stream before releasing runtime
  resources. Cooperative cancellation could return a terminal result without
  explicitly closing the active `agent.astream()` iterator, so the executor
  released the sandbox lease and sent the task-stop notification while
  graph-stream teardown was still in flight. The stream is now retained and
  closed before terminalization and release, the original stream error or host
  cancellation wins if close also fails, and teardown still running after 10s
  logs a warning. ([#5221])
- **composer:** Reserve `context` as a slash command alias. `/context compact` is
  a built-in composer command, but `context` was not reserved in the shared
  slash-skill contract, so a skill could claim the alias and shadow it. The
  shared contract now reserves `context`, frontend and backend slash parsing stay
  aligned through it, and IM channel command classification is unchanged.
  ([#5279])
- **scheduler:** Preserve a one-time task's execution instant across title and
  prompt edits. The schedule control converted the stored timestamp to
  minute-precision local time and back on mount, so in New York
  `2026-11-01T06:30:00Z` was saved as `05:30:00Z` and ordinary timestamps lost
  seconds and milliseconds — a metadata-only edit silently moved the run. The
  edit form now snapshots the original timestamp, local input, and timezone and
  re-emits the original `run_at` until the time or timezone changes. ([#5330])
- **scheduler:** Reject wall times skipped by daylight saving in the one-time
  schedule form. New York `2027-03-14T02:30` converted to UTC and back as
  `01:30`, so create and edit could save an instant different from the preview.
  The form now validates local-to-UTC-to-local equality, shows localized inline
  feedback with the input marked invalid, emits an empty schedule spec until
  corrected, and keeps Create (and edit-save) disabled. ([#5348])
- **sandbox:** Drain the previous sandbox release during async rebind. Async rebind
  paths released the previous sandbox client through a bare
  `await asyncio.to_thread(provider.release, ...)`; cancelling the caller cancelled only
  the awaiter and let the per-thread lifecycle serializer release while the old release
  was still running, so a later same-thread lifecycle transition could overlap it. The
  three async previous-release paths now route through the cancellation-safe
  `run_sync_lifecycle_operation()` helper, which holds the serializer until the old
  release completes and then propagates the original `CancelledError`. ([#5498])
- **subagents:** Close delegation-ledger entries a stopped run left in progress. On
  Stop, the `task` tool cancels the subagent and re-raises cancellation, so no
  `ToolMessage` is written and the ledger keeps the delegation `in_progress` — every
  later model call was told the work was "already delegated; do NOT delegate again" and
  waited for a result that never arrived. When a run starts with a new user message,
  `DurableContextMiddleware` now marks such entries `cancelled` ("cancelled attempt; may
  retry with a changed plan"). Resumed runs, goal continuations sharing the run id, and
  entries with a result are unchanged. ([#5507])
- **frontend:** Keep clarification text outside the execution-steps panel. Answer text
  accompanying an `ask_clarification` call rendered inside the bordered execution panel,
  and submitting a hidden reply moved previously completed answer bubbles back into it
  while the continuation streamed. Clarification results now act as completed-run
  boundaries so earlier answers stay in the conversation across continuation and
  reconnect, and the accompanying text renders once outside the panel with the original
  messages, tool-result associations, and usage accounting preserved. ([#5508])
- **projects:** Drain trash reconciliation file workers across Gateway shutdown
  cancellation. Cancelling the startup trash-retention sweep cancelled only the asyncio
  awaiter while its executor worker kept walking/statting/unlinking files, so
  `_shutdown_startup_trash_sweep()` could finish Gateway teardown while the detached
  worker was still mutating the projects tree. Both reconciliation `run_file_io()`
  operations now drain through the cancellation-safe `await_drained()` helper: an
  already-started worker reaches terminal state first, then cancellation propagates and
  later stages never start. The hook timeout stays the graceful-completion budget, not a
  hard cap after cancellation. ([#5511])
- **mcp:** Insert bare-filename rewrites literally instead of as a regex replacement
  template. `_rewrite_unique_bare_filenames` passed the correlated `/mnt/user-data/...`
  path to `Pattern.subn` as a template, so a literal backslash in a filename (a model
  passing a Windows-style path to a stdio MCP server on POSIX creates a file literally
  named `screenshots\q3.png`) either raised `re.error: bad escape` out of the tool-call
  conversion and failed the whole call after the server had already written the file, or
  — for escapes `re` accepts — silently substituted the escape byte (`\r` became a CR)
  into the returned path, riding it into the transcript and checkpoint. The replacement
  now goes through a callable, so the path is inserted verbatim. ([#5522])
- **nginx:** Allow model-bound `/api/` and `/api/skills` requests to outlive 60
  seconds. The catch-all `location /api/` (e.g. `POST /api/runs/wait`, which also
  cancelled the run when nginx dropped the upstream connection, and
  `POST /api/input-polish`) and `location /api/skills` (`.skill` installs scan every
  archive file with sequential LLM calls) still used nginx's 60-second
  `proxy_read_timeout` default and failed with `504`. Both locations now set
  `proxy_read_timeout 600s`, matching the model-bound locations; applied to the Docker,
  `make dev`, and Helm nginx configs. More specific locations are untouched. ([#5524])
- **subagents:** Drain the owned batch-service stop across caller cancellation.
  `SubagentRuntime.stop()` cleared its batch-submitter flag before awaiting
  `SubagentBatchService.stop()`; an interrupted await left the runtime reporting no
  submitter — later `stop()` calls returned immediately — while the owned service was
  still part-way through stopping, so runtime-owned batch work could outlive the
  runtime's lifecycle ownership. The stop now runs in a strongly-owned task that is
  shielded and drained across repeated cancellation; the first caller `CancelledError`
  propagates only after the owned stop reaches a terminal state. ([#5525])
- **memory:** Drain Gateway memory shutdown workers across lifespan cancellation. The
  flush and backend close ran as separate `asyncio.to_thread()` awaits, so cancelling
  the lifespan task cancelled only the awaiter: `manager.close()` could start while the
  flush worker was still running — closing the backend connection under an in-flight
  flush — and repeated cancellation could detach the close worker entirely. Manager
  resolution, `shutdown_flush()`, and `close()` now form one owned shutdown operation
  drained through the cancellation-safe `await_drained()` helper; the first caller
  cancellation propagates only after the started work reaches a terminal state. ([#5531])
- **sandbox:** Report an exactly-full sandbox search result as complete. `glob` and
  `grep` in the AIO, E2B, OpenSandbox, Tenki, and BoxLite providers treated "collected
  `max_results` matches" as `truncated=True`, so a tree holding exactly that many
  eligible matches told the agent its search was partial and it re-ran or narrowed the
  search for nothing. The filtered-match cap now looks one match past the cap before
  deciding — a genuinely dropped match still reports truncated — leaving the matches
  themselves and the remote raw-output cap unchanged. ([#5534])
- **threads:** Clean persisted records safely on thread deletion.
  `DELETE /api/threads/{id}` removed the thread directory, checkpoints, browser session,
  and meta row but left `run_events`, historical `runs` rows, and `feedback` behind —
  the messages feed stayed readable after the delete (the owner check passes on a
  missing meta row), and re-creating the same thread id inherited the deleted thread's
  messages. Deletion now also removes runs, run events, and feedback, owner-scoped and
  best-effort inside the existing delete reservation; run cleanup deletes only
  `operation_kind == "run"` rows so the in-flight delete reservation survives. Durable
  event stores take an explicit per-thread mutation fence, so a concurrently admitted
  writer can no longer commit a row for a deleted thread after deletion returns. ([#5535])
- **frontend:** Rejoin active runs after reopening a chat. The SSE reconnect path only
  knew the run id stored in the current tab's `sessionStorage`, so reopening the browser
  or opening a new tab lost the pointer while the server-side run kept going. Opening a
  thread without a reconnect pointer now discovers the newest pending or running run,
  persists the pointer before joining so stop/cancel still targets the right run, and
  rejoins its resumable stream, retrying a failed recovery twice with bounded 1s/2s
  delays; a matching pointer suppresses duplicate joins. ([#5536])
- **channels:** Roll back a partially started channel service across startup
  cancellation. `start_channel_service()` published the global singleton before awaiting
  `ChannelService.start()`, so cancellation after partial resource acquisition exited
  without stopping the service and left a singleton whose startup never completed.
  Startup failure/cancellation now rolls back the partial service and drains the
  rollback across repeated cancellation with `await_drained()`; the singleton clears
  only after cleanup succeeds, and a failed cleanup retains it so later shutdown can
  retry. ([#5537])
- **docker:** Add a `make prod-logs` entry point for the production stack and stop
  `make docker-logs` from exiting silently after a production start. `make up`
  runs compose project `deer-flow` while `make docker-logs` tailed the dev
  project `deer-flow-dev`, which has no containers then, so the command printed
  nothing. `scripts/docker.sh logs --prod` now tails the production stack with
  the same compose file, `--env-file ../.env`, and the interpolation defaults
  `deploy.sh` exports (without them compose cannot parse the production volume
  specs on checkouts without a `.env`); dev-only logs with no containers print a
  hint pointing at `make prod-logs`. ([#5538])
- **frontend:** Preserve literal `<think>` tags in fenced, indented, and inline
  code during reasoning extraction, including unfinished code while streaming.
  The parser only protected an opener immediately following a backtick, so a
  code example explaining `<think>` tags was moved into the reasoning
  disclosure — corrupting the rendered answer and the copied text — and a
  literal unclosed opener swallowed the following explanation. Real closed or
  streaming reasoning after literal code is still extracted, and Markdown
  delimiters inside actual reasoning no longer prevent finding its closing tag,
  so an unfinished fence there cannot hide the answer. ([#5540])
- **uploads:** Handle a UTF-8 BOM in uploaded Markdown when building document
  summaries. A leading BOM stopped the outline extractor from recognizing the
  first heading or opening code fence — in the fence case a code comment became
  a document heading and the closing fence was mistaken for an opening one,
  hiding the real sections — and a BOM-only first line consumed a
  fallback-preview slot. Outlines and previews are now read with `utf-8-sig`,
  which consumes the optional BOM while preserving ordinary UTF-8, embedded
  U+FEFF characters, physical line numbers, and the original uploaded bytes.
  ([#5541])
- **gateway:** Preserve confirmed clarification-card answers when preparing a
  thread regeneration. The regenerate endpoint only selected visible human
  messages, but clarification-card answers are stored as hidden `HumanMessage`
  objects with `human_input_response` metadata, so it could skip the confirmed
  answer and replay an older visible prompt instead. A regenerate-specific
  predicate now accepts hidden messages carrying a structurally valid
  `human_input_response` and preserves their hidden and request-correlation
  metadata; summaries, goal-control messages, malformed hidden responses, and
  unrelated internal messages remain rejected. ([#5544])
- **sandbox:** Wrap the `remote_list_dir_command` and `remote_search_command`
  probe scripts in a subshell so their trailing `exit` cannot kill the AIO
  sandbox's implicit persistent shell. A bare `exit` terminated the session
  shell and the server's response for that `exec_command` request never
  completed, hanging the client indefinitely — making every
  `list_dir`/`grep`/`glob` call a deterministic wedge and deadlocking entire
  runs that issued parallel `[ls, bash]` tool calls. Output markers and exit
  codes still propagate from the subshell; only the probe scripts change.
  ([#5546])
- **uploads:** Delete the requested upload entry instead of a symlink's resolved
  target. `delete_file_safe` resolved the requested path first and unlinked the
  result, so a symlink planted at an upload name (the sandbox maps the uploads
  directory writable) made `DELETE /api/threads/{id}/uploads/{filename}` remove
  the target file and its companion `.md`, leave the dangling link in place, and
  answer `200` for the wrong file. The requested entry itself is now checked and
  unlinked: a symlink, like any non-regular entry, returns `404`; links pointing
  outside the uploads directory still return `400`; and the companion `.md` name
  comes from the requested file. Regular-file deletes are unchanged. ([#5547])
- **extensions:** Drain extension-service shutdown across host cancellation. The
  Gateway registered extension-service cleanup with `AsyncExitStack` but awaited
  `stop_services()` directly, so a cancellation landing while an extension
  `stop()` was blocked aborted the cleanup callback and let stack unwinding
  continue while extension-owned resources were still alive, breaking the
  ownership ordering the stack exists to provide. Shutdown now runs through the
  cancellation-safe `await_drained()` helper, so later runtime teardown waits
  until extension services reach a terminal state within the per-service
  timeout budget. ([#5549])
- **memory:** Report malformed `memory.backend_config` values by key name instead
  of unnamed tracebacks. The Honcho backend read `failure_policy`,
  `workspace_overrides`, and `user_peer_overrides` through a falsy-only
  `or {}` fallback, so the most natural YAML spelling — `failure_policy:
  fail_closed` as an unquoted string — survived as a truthy non-mapping and
  crashed with `AttributeError: 'str' object has no attribute 'get'`, naming
  neither the key nor `backend_config`. Non-mapping values are now rejected as
  config errors naming the key, while falsy values still mean unset. The mem0
  and OpenViking backends get the same key-naming guard for numeric knobs
  (`top_k`, `timeout_seconds`, ...) instead of bare `int()`/`float()` casts that
  escaped unnamed `TypeError`s. ([#5555])
- **mcp:** Scope MCP sessions and durable-task access by thread incarnation.
  Deleting and recreating the same thread ID reused the previous lifecycle's
  persistent MCP session scope, and the replacement thread could list, read, and
  request cancellation of durable tasks created by the old lifecycle because
  those operations scoped only by user and thread ID. The server-owned thread
  incarnation now reaches the agent runtime: non-legacy MCP sessions get a
  versioned `(user, thread, incarnation)` scope, durable task list, detail, and
  cancellation bind to the caller-captured and current incarnation, and
  submissions are atomically rejected when the thread is deleted or recreated
  between remote submission and local persistence. Explicit legacy `NULL`
  incarnations keep the pre-activation scope, worker polling and cancellation
  keep working through the creating session, and incarnation fields stay out of
  public task responses. ([#5556])
- **subagents:** Recognize empty regular files in remote subagent acceptance
  probes. GNU `stat -c %F` reports a zero-byte file as `regular empty file`, but
  the remote size and readability probes accepted only `regular file`, so an
  empty artifact was rejected as `NONREGULAR` and `exists`, `non-empty`, and
  `file_written` all stayed UNVERIFIED even when the file was present and
  readable. Both labels are now accepted: empty readable files can satisfy
  `exists` and `file_written`, and `non-empty` yields a deterministic negative
  result. Symlink, FIFO, and containment checks are unchanged. ([#5559])
- **frontend:** Derive the `web_fetch` tool-step title from the first non-blank
  line of the fetched markdown. `extractTitleFromMarkdown()` only accepted a
  document whose very first characters were `# `, so a blank line or up-to-three
  spaces of indentation before the first heading — which CommonMark allows, and
  which the crawl4ai backend hands through unchanged — cost the chat transcript
  its step title and silently fell back to the raw URL. An indented code block
  still does not count as a title, and an empty heading yields no title instead
  of a literal `#`. ([#5560])
- **sandbox:** Stop E2B reconciliation from reviving warm-pool sandboxes. Every
  reconciliation pass issued `Sandbox.connect()` against sandboxes parked in the
  warm pool — which the SDK normalizes to a 300-second timeout update, pushing
  the remote expiry forward forever — and the first pass adopted the warm
  sandbox back into the active set so it was never released again; idle billed
  VMs stayed alive indefinitely and held capacity slots. Reconciliation now
  treats locally tracked sandboxes (active or warm) as canonical and never
  probes them with `connect()`, refreshes active-sandbox TTLs through the
  cached client, and sweeps warm entries parked past `sandbox.idle_timeout`,
  releasing their ownership leases, mount results, and capacity tracking. Warm
  sandboxes now actually expire at the configured `sandbox.idle_timeout`.
  ([#5562])
- **utils:** Return empty text for content-less messages instead of the literal
  string `"None"`. `message_content_to_text(None)` stringified its argument, so
  a content-less sub-agent final message bypassed the `No response generated`
  sentinel, a content-less structured LLM-error fallback hid its
  `error_detail`, and the task-continuity archive failed to skip the empty text.
  Only `None` content is treated as empty — the literal string `"None"`, `0`,
  `False`, and list-block conversions behave exactly as before. ([#5563])
- **doctor:** Validate the contents of CLI-backed model credentials in `make
  doctor`. The check reported Codex and Claude auth as healthy whenever the
  credential path merely existed, so an empty, logged-out, malformed, or expired
  file produced a green checkmark while the model loader could not obtain a
  usable token. Codex `auth.json` is now validated across all three supported
  token layouts and Claude `.credentials.json` through `claudeAiOauth.accessToken`
  including the runtime's one-minute expiry buffer; missing files, directories,
  non-object JSON, empty tokens, and invalid expiry values report
  provider-specific failures with the existing remediation hints. The check
  stays standard-library-only, offline, and redacted; environment and
  file-descriptor sources remain non-consuming presence checks. ([#5567])
- **middleware:** End length-capped turns cleanly instead of letting
  `TodoMiddleware` re-engage the model. When a model hit its per-response output
  cap (`finish_reason=length`) while emitting a `write_file` call, the
  suppressed call still triggered the todo completion-reminder jump
  (`jump_to=model`), re-emitting the same oversized call into the same cap — up
  to three futile responses with junk fragments instead of a clean truncation
  notice. `TodoMiddleware` now skips the reminder jump when the
  `model_length_termination` marker is present, the length notice is appended
  even when partial text survived (fixing a latent `append_visible_text` bug
  that silently dropped string content), and `write_file`'s model-visible
  description is annotated with the configured `max_tokens` output budget so the
  model does not assume the 80 KB streaming ceiling is the practical
  single-write limit. ([#5569])
- **ragflow:** Validate RAGFlow document selections in batches of at most 100 IDs.
  Selecting more than 100 documents from one dataset is valid under the
  1000-document scope limit, but validation sent every ID in a single request,
  which the provider rejects, so `knowledge_search` failed before retrieval.
  Selections now validate in provider-sized batches that preserve input order
  and the fail-closed behavior for missing or unsearchable documents, sharing
  one concurrency budget across datasets. ([#5572])
- **persistence:** Drain the PostgreSQL bootstrap advisory unlock across
  cancellation. The unlock in `_postgres_lock()`'s `finally` was awaited
  directly, so startup/lifespan cancellation arriving while
  `pg_advisory_unlock` was still in flight could abort the release and return
  the connection to the pool while it still held the bootstrap mutex. The
  release now completes through the cancellation-safe `await_drained()` helper
  on the same connection that acquired the lock. ([#5573])
- **persistence:** Drain engine disposal across cancellation during gateway
  teardown. `close_engine()` awaited `AsyncEngine.dispose()` directly, so
  cancellation while disposal was blocked let teardown return while the
  process-global engine and session factory still pointed at a partially
  disposed resource. Disposal now completes through the cancellation-safe
  `await_drained()` helper, the globals stay published until it finishes, and
  stale cleanup can no longer erase a replacement engine. ([#5576])
- **channels:** Photos and files sent to the Telegram bot now download and
  reach the agent. Two bugs compounded: the download opened a fresh connection
  on the manager event loop and failed with a generic `NetworkError`, and the
  ingested file was written `0600 root:root`, so the non-root sandbox user got
  `Permission denied` reading it. Downloads now route through a loop-bound
  download bot, inbound files get sandbox-readable permissions, and failures
  log the underlying cause with the token-bearing Bot API URL masked. ([#5581])
- **models:** Treat a Codex auth file whose top level is not a JSON object as
  "no credential from this source". An array, string, or number in
  `~/.codex/auth.json` (or `$CODEX_AUTH_PATH`) previously raised
  `AttributeError` out of `CodexChatModel` construction, preempting the
  documented "Codex CLI credential not found" error; the loader now logs and
  falls through. ([#5584])
- **memory:** Keep an explicit `confidence: 0.0` from scoring as the 0.5
  default. Two read sites rescued the field with `or 0.5`, which cannot tell
  "explicitly zero" from "unset", so a zero-confidence fact was inflated by
  the default weight and ranked differently depending on which write path
  indexed it. Zero now ranks strictly below 0.5 through both the FTS5 index
  and the substring fallback; an absent or null confidence still defaults to
  0.5. ([#5586])
- **skills:** Load a `SKILL.md` saved as UTF-8 with a BOM. The front-matter
  anchor rejected the leading `U+FEFF` written by Notepad and PowerShell's
  `Set-Content -Encoding UTF8`, so Windows-authored skills silently vanished
  from the catalog with no warning. The mark is now consumed by the shared
  compiled anchor and reaches neither skill metadata, rendered instructions,
  nor the skill-context description, and the loader, validator and middleware
  copies of the pattern can no longer drift. ([#5588])
- **models:** Skip Claude Code credentials sources with a non-numeric
  `expiresAt`. A string, null, list, or object value raised `TypeError` out of
  the loader and stopped the lookup loop, so one malformed file at
  `$CLAUDE_CODE_CREDENTIALS_PATH` prevented every `ClaudeChatModel` from ever
  reaching `~/.claude/.credentials.json`; the source is now skipped with a
  debug log like its sibling guards. ([#5591])
- **skills:** Render an explicit empty `allowed-tools` as no tools. The skill
  metadata renderer truthiness-tested the field, so a skill declaring
  `allowed-tools: []` advertised `Allowed tools: (all)` while the tool policy
  stripped every business tool — the model planned against tools that would be
  rejected. The empty declaration now renders `(none)`; an omitted or
  non-empty declaration renders as before. ([#5593])
- **gateway:** Classify the Windows `image/svg` MIME alias as active content.
  On Windows the MIME database maps `.svg` to `image/svg` rather than the
  standard `image/svg+xml`, and the shared active-content classifier only
  recognized the standard type, so SVG artifacts, `.skill` archive members,
  and project documents could be served inline instead of forced to download.
  The alias is now treated as active content on every host. ([#5594])
- **models:** Tolerate a null Codex `account_id` before it reaches the request
  header. `or`-chaining let a JSON `null` survive the loader as `None`, so
  `CodexChatModel` construction crashed on `self._account_id[:8]`; a numeric
  `account_id` died later with `httpx` rejecting a non-string
  `ChatGPT-Account-ID` header. Null now falls back to the unknown-account
  value `""` and any other non-string is stringified. ([#5601])
- **llm:** Fence circuit-breaker probe settlement by generation and ownership.
  `LLMErrorHandlingMiddleware` settled successes and failures unconditionally,
  so a request admitted under an older closed generation could finish after a
  newer recovery probe was acquired and then close the circuit during the
  outage, reopen it and discard a healthy probe, or release another call's
  probe. Every admission now captures the circuit generation, and success,
  failure, or release only mutates the breaker when both the generation and —
  in half-open state — the exact probe token match. ([#5602])
- **memory:** Reject a Honcho `base_url` that can never resolve. The field was
  read with no validation, so the natural scheme-less spelling for an internal
  host (`base_url: honcho:8000`) was accepted at startup — httpx parses the host
  as the scheme — and memory then failed on every operation with an
  unsupported-protocol error, or silently returned empty results while the
  Gateway ran green; the api_key-over-plain-HTTP guard was skipped too, since it
  matched only a literal `http://` prefix. Malformed values now fail fast at
  Gateway startup, matching the documented behavior, and every URL that resolves
  today keeps working. ([#5607])
- **subagents:** Report an explicit zero batch limit by name instead of
  defaulting it. `SubagentBatchService.submit()` resolved `max_live_items` /
  `max_running_items` with `or`, so a caller-supplied `0` read as "not supplied"
  and was silently replaced with the configured default — a `batch_task` asking
  for zero concurrent items ran three at a time — and paired with a small
  `max_live_items`, the request was refused for a limit it did not violate. Both
  resolutions now compare against `None`, so an explicit `0` reaches the range
  guard and is rejected by name; an absent key still means "use the configured
  default". ([#5609])
- **sandbox:** Drop ignored directories from remote `list_dir` output. A local
  sandbox skips `node_modules`, `.git` and the other ignore patterns, but the
  same call in a remote sandbox listed every path under them up to the
  500-line cap, even though the remote `grep` and `glob` already treat those
  paths as invisible. The shared remote parser now drops entries containing an
  ignored directory name, matched relative to the listing root like the local
  walk: explicitly listing an ignored directory still works, and a fully
  ignored directory returns empty instead of `FileNotFoundError`. ([#5612])
- **middleware:** Discard stale todo reminders during context compaction. After
  a todo reminder had been injected, compaction could summarize its old task
  statuses or keep the stale reminder in the retained message tail, which also
  stopped TodoMiddleware from rebuilding task context from the current `todos`
  state. Automatic and manual compaction now exclude `todo_reminder` snapshots
  before selecting the summary and retained partitions, and the current todo
  state survives: the middleware regenerates a reminder before the next model
  call when no `write_todos` call remains visible. ([#5614])
- **sandbox:** Honor `start_line`/`end_line` in Tenki's `read_file`. The Tenki
  provider accepted only `path`, so a ranged read — the normal way an agent
  continues a truncated read — raised `TypeError: ... unexpected keyword
  argument 'start_line'`, rendered as a generic read error. It now slices like
  the sibling providers, with negative bounds clamping the way the local
  sandbox does. ([#5616])
- **persistence:** Drain the PostgreSQL schema bootstrap connection close
  across cancellation. `ensure_postgres_schema_async()` closed its dedicated
  psycopg connection with a bare `await`, so cancellation arriving during
  lifespan teardown could abort the close and return while the connection was
  still live. The close now goes through the cancellation-safe
  `await_drained()` helper, which defers the caller's cancellation until the
  owned connection finishes closing. ([#5617])
- **runtime:** Drain runtime provider teardown across cancellation. The
  checkpoint-cache and stream-bridge provider context managers own their
  backends and awaited `aclose()`/`close()` directly on context exit, so host
  cancellation arriving mid-teardown could abort the close and return while a
  memory or Redis backend was still live. Both closes now go through the
  cancellation-safe `await_drained()` helper for the memory and Redis backends;
  cancellation propagates only after the owned close finishes. ([#5622])
- **helm:** Align the provisioner's state root with the Gateway's when the
  shared home PVC is enabled. The chart set the Gateway's
  `DEER_FLOW_HOST_BASE_DIR` but left the provisioner on its runtime default
  `/.deer-flow`, so valid Gateway skill-projection paths fell outside the
  provisioner's allowed base and could be rejected before sandbox creation in
  `USERDATA_PVC_NAME` mode. The provisioner now receives the same logical root
  so projections map to `deer-flow/<suffix>` on the PVC; it stays unset when
  `persistence.home.enabled=false`. ([#5625])
- **client:** Honor an agent's MCP plugin selections in the embedded client. An
  agent saved with `mcp_plugins: [installation-A]` still received tools from
  every enabled MCP server through `DeerFlowClient`, an empty selection was
  ignored as well, and delegated tasks did not inherit the agent's selection.
  The client now applies the saved selection when loading tools and passes it
  to delegated tasks on every run, including cached-graph runs; the selection
  joins the graph cache key as an unordered set, and saved configuration
  changes still take effect after `reset_agent()`. ([#5630])
- **persistence:** Drain Alembic migration workers across cancellation.
  `bootstrap_schema()` held the SQLite in-process mutex or the PostgreSQL
  advisory lock while `stamp`/`upgrade` ran in `asyncio.to_thread()`, but those
  awaits were cancellation-vulnerable: cancelling the host task could return
  from the bootstrap critical section while the worker was still mutating
  schema state, letting a second bootstrap overlap a live migration. Every
  Alembic worker await now goes through the cancellation-safe `await_drained()`
  helper; cancellation propagates only after the worker finishes. ([#5631])
- **sandbox:** Enforce command timeouts in the AIO sandbox. `AioSandbox` ignored
  the caller-provided timeout, so `sandbox.bash_command_timeout` never applied —
  a long-running command ran to completion, and a stalled persistent-shell
  request kept the sandbox-wide serialization lock occupied, blocking later
  operations on the same client. Commands now carry a server-side
  `hard_timeout` on supported AIO images (the frozen legacy `:latest` gets a
  bounded host wait only), ambiguous outcomes are never replayed, and
  `sandbox.bash_command_timeout` is now the provider default. ([#5634])
- **channels:** Log Slack Socket Mode connect failures instead of dropping them.
  `SlackChannel.start()` ran `SocketModeClient.connect()` through
  `run_in_executor()` and discarded the returned future, so a rejected
  `app_token` (or unreachable Slack) left the bot silently dead — the log said
  `Slack channel started` and the exception surfaced only as asyncio's "Future
  exception was never retrieved" at garbage-collection time. Connect failures
  are now logged with their traceback, matching what the Telegram and Discord
  channels already did. ([#5640])
- **mcp:** Honor a stdio MCP server's configured `cwd`. `McpServerConfig`
  accepted the setting as an extra field, but `build_server_params()` dropped it
  before either launch path saw it, so a server configured with a working
  directory could fail discovery when its script path was relative, or discover
  with an absolute path and then fail relative file reads during pooled tool
  calls. The directory is now forwarded to stdio connections when non-empty
  (including environment-variable references) and omitted for HTTP/SSE;
  omitted, `null`, or empty values keep the default behavior. ([#5643])
- **skills:** Read Python secret assignments from the AST in SkillScan. The
  `secret-env-assignment` rule swept every text file with a `name[:=]value` regex,
  which misreads Python: a typed-optional parameter default
  (`token: Optional[str] = None`) and `api_key = os.getenv("...")` — the rule's
  own documented remediation — were both reported as hardcoded credentials,
  failing the review gate on unchanged bundled skills. Python sources are now
  analyzed from their AST, reporting only real literal values; non-Python
  coverage is unchanged, and a test pins the bundled skills stay clean. ([#5648])
- **persistence:** Drain the database auto-create maintenance dispose across
  cancellation. `_auto_create_postgres_db()` released its throwaway engine with
  a bare `await maint_engine.dispose()`, so cancellation during a slow first
  boot could abort the dispose and leave one live server session against
  `postgres` for the lifetime of the process — a leak that is not self-healing,
  since the next boot takes the non-missing-database path and never retries the
  disposal. The dispose now goes through the cancellation-safe `await_drained()`
  helper; a successful first boot behaves as before. ([#5649])
- **skills:** Keep per-user skill-install directory setup off the event loop.
  `UserScopedSkillStorage.ainstall_skill_from_archive` created the per-user
  custom directory with a blocking `os.mkdir` on the loop before any real work
  was dispatched, so `POST /api/skills/install` stalled the Gateway event loop;
  the existing blocking-IO anchor missed it because it covered only the
  host-scoped base class. The `mkdir` now runs on the worker thread like the
  extraction and validation around it, and the anchor covers the user-scoped
  path. Install semantics and on-disk layout are unchanged. ([#5650])
- **sandbox:** Clamp negative `read_file` range bounds in the e2b, OpenSandbox,
  and BoxLite providers the way `LocalSandbox` already does. Negative values
  previously fell through to Python negative-index slicing, so `start_line=-1`
  silently returned the last lines of a file and `end_line=-1` a truncated
  range instead of reading from the first line and yielding an empty range. The
  tool layer already rejected negative bounds; direct `Sandbox` consumers hit
  the gap. ([#5655])
- **skills:** Align the bundled Vercel deploy skill's package directory with its
  declared name and point its deployment commands at the real mounted path
  `/mnt/skills/public/vercel-deploy/scripts/deploy.sh`. The skill lived in
  `vercel-deploy-claimable` while activating as `/vercel-deploy`, and its
  instructions referenced a script path DeerFlow never mounts, so a deployment
  request could select the correct skill and still receive a command pointing at
  a file that does not exist. ([#5656])
- **frontend:** Show explicit empty skill export requirements instead of a blank
  value. The export dialog formatted `allowed-tools` and `required-secrets` with
  `join(", ")`, so an explicitly empty declaration rendered as an empty string
  and was indistinguishable from an omitted one, even though the two have
  different policy semantics; absent declarations now render as "Not declared"
  and explicitly empty ones as a localized "None". ([#5659])
- **sandbox:** Bound AIO `list_dir` with a dedicated directory deadline. The
  listing ran under the sandbox-wide lock with only a 600-second no-change
  timeout and inherited the SDK transport budget, so a stalled relay or wedged
  `find` could block later operations on the same sandbox for minutes. On
  supported images the remote `find` now carries a 60-second server-side
  `hard_timeout` inside a 65-second no-retry host envelope: `hard_timeout`
  raises `TimeoutError` and keeps the shell generation reusable, ambiguous
  outcomes raise `OSError` and fence it. No new configuration. ([#5662])
- **runtime:** Share one change position across an atomic thread operation in
  the memory run store. `create_thread_operation_atomic` advanced the change
  clock per row, so an interrupt-and-replace landed its interrupted row and
  replacement on two `change_seq` values and a `list_changed` reader paging by
  `(change_seq, run_id)` could observe half of the atomic set; every claimed
  row and the new row now carry one position, matching the SQL store. The
  default (no durable database) deployment selects this store. ([#5663])
- **runtime:** Drain synchronous checkpoint mutations across cancellation. Goal
  writes and rollback offload sync checkpointers with `asyncio.to_thread()`, and
  cancelling the caller previously stopped waiting while the `put`, `put_writes`,
  or `delete_thread` worker kept running — the caller could observe cancellation
  and the mutation could still commit afterwards. These fallbacks now drain
  through the cancellation-safe `await_drained()` helper; the read fallback
  `get_tuple` stays directly cancellable. ([#5664])
- **agent:** Distinguish undeclared and explicitly empty skill `allowed-tools`
  in the agent assembly fingerprint. Both declaration states hashed to an empty
  list, so switching a skill from the legacy allow-all to a no-business-tools
  policy changed runtime tool availability without changing the fingerprint;
  undeclared `allowed_tools` now hashes as `None` while explicit allowlists stay
  sorted lists. Frontmatter parsing and runtime tool policy are unchanged. ([#5669])
- **uploads:** Stop deleting a converted Markdown companion when its document is
  deleted. `delete_file_safe` recomputed `stem.md`, so two documents sharing a
  stem (`a.docx`, `a.pdf`) made deleting one document remove the other's
  converted text — or destroy a user's own `report.md` next to an unrelated
  `report.pdf`. `DELETE /api/threads/{id}/uploads/{filename}` now removes only
  the requested file; orphaned companions stay in the listing and can be deleted
  individually. No API shape or config change. ([#5673])
- **sandbox:** Prune ignored entries before applying the remote `ls` listing
  limit. The 500-entry cap was applied before ignored paths were dropped, so a
  dependency tree could fill the entire window and hide a normal file beside it,
  sometimes leaving only the root in the returned listing; ignored descendants
  are now pruned inside the shared `find` command before `head`, preserving
  depth and output limits. ([#5676])
- **persistence:** Apply `database.postgres_schema` to the synchronous
  SQLAlchemy store used by DB-backed custom agents and managed subagents. The
  async ORM and LangGraph stores already honored the configured schema, but
  synchronous agent-store queries fell back to `public` and failed to find the
  application tables; the connection URL now preserves existing libpq options
  while adding `search_path`. ([#5678])
- **logging:** Collapse every non-absolute Redirecting slot to `/<redacted>`.
  The #5225 URL-redaction pass kept a slot verbatim unless it started with `/`,
  so slash-less relative `Location` references (`download?sign=…`), query-only,
  fragment-only, network-path, and `data:` targets rendered their signed queries
  verbatim in DEBUG redirect logs; only a target with a scheme at position 0 is
  now handed to the generic absolute-URL pass, and non-URL `-> /path` sandbox
  mount arrows still pass through. ([#5680])
- **channels:** Log DingTalk inbound-file skips instead of dropping the
  attachment silently. A download that returned no content vanished with zero
  log lines, indistinguishable from a message that never had one; the skip now
  emits a neutral guard line naming the file, matching the WeChat channel's
  shape, with the accurate reason already logged inside the download helper.
  No behavior change. ([#5683])
- **gateway:** Drain readiness-probe connection close across cancellation.
  `/health/ready` closed its SQLite and PostgreSQL probe connections with a bare
  `await connection.close()`, so a second cancellation during teardown could
  interrupt it and let the probe return while its connection was still live,
  detaching database cleanup from the request lifecycle; close now drains
  through the cancellation-safe `await_drained()` helper. Response shape is
  unchanged. ([#5684])
- **logging:** Collapse space-carrying Redirecting slots to `/<redacted>`. Round
  15 kept scheme-bearing slots verbatim for the generic absolute-URL pass, but
  that pass's pattern stops at whitespace, so a slot like
  `https://mirror.example/other page?sig=…` rewrote only the text before the
  space and leaked the rest into DEBUG logs; a slot is now kept only when a
  whitespace-free absolute URL fills it, and ordinary absolute redirect pairs
  still keep their host. ([#5687])
- **skills:** SkillScan's `secret-env-assignment` rule again reports secrets
  bound outside plain statement assignments. The AST walk from #5648 only saw
  bare-constant assignments, so keyword arguments (`connect(api_key="...")`),
  parameter defaults, walrus bindings, literal concatenation, and all-constant
  f-strings hid a hardcoded credential from the HIGH-severity gate. The constant
  fold is iterative: a recursive one could raise `RecursionError`, which the
  scanner records as a per-file error that drops every finding for the file.
  The #5648 precision (annotations, `os.getenv` calls) is preserved. ([#5691])
- **community:** Browserless `web_fetch` now reads its documented wait settings
  the way `web_capture` does. `wait_for_timeout_ms` goes through the tolerant
  `_as_int` helper, so a value like `2s` falls back to the default instead of
  failing the call with `invalid literal for int()`, and
  `wait_for_selector_timeout_ms` is read from tool config instead of a hardcoded
  `5000` (default unchanged, so existing configs behave the same). Both keys are
  now documented on the `web_fetch` entry in `config.example.yaml`. ([#5702])
- **community:** SearXNG `max_results` above one page is now honored. The
  SearXNG API has no `limit` parameter, so the client sent an ignored `limit`,
  requested only page 1, and sliced an already-truncated list — `max_results:
  20` silently returned one page (10 by default). `search` now walks `pageno`
  and accumulates results until the cap is reached, a page comes back empty, or
  a page adds nothing new (deduped by URL), capped at 5 pages; the dead `limit`
  parameter is no longer sent. Default `max_results` still costs one request.
  ([#5705])
- **sandbox:** Ambiguous AIO session creation can no longer be replayed or
  executed. Shell and bash creation planes track each attempted id through a
  pending/owned/absent/tombstoned state machine: timeouts, transport errors, 5xx
  responses, and malformed HTTP-200 responses tombstone the id — no execution on
  it, no replayed create, bounded best-effort cleanup that never clears the
  tombstone — and new creates on that plane are blocked. A dirty sandbox is
  released through the existing teardown path instead of returning to the warm
  pool; shell ambiguity does not affect bash creation. ([#5711])
- **models:** Official DeepSeek models added through Settings now use the native
  `PatchedChatDeepSeek` adapter. Managed profiles and their connection probes
  always built `ChatOpenAI`, so adding `deepseek-flash` failed the connection
  test with HTTP 400 `Thinking mode does not support this tool_choice`, and
  streamed tool calls dropped `reasoning_content` and sent
  `max_completion_tokens` instead of DeepSeek's native `max_tokens`. Thinking is
  disabled only for the bounded forced-tool probe — normal chat settings are
  untouched — and matching is limited to `api.deepseek.com`, so third-party
  compatible endpoints keep their behavior. Existing saved profiles gain the
  adapter without a catalog migration. ([#5718])
- **community:** Browserless `web_fetch` now reads `reject_resource_types` and
  `reject_request_pattern` from its tool config. Both parameters were declared
  and passed to the client but only ever assigned `None`, so a configured value
  was silently ignored and resource-type/request-pattern rejection — the main
  lever for render latency and bandwidth against a self-hosted Browserless —
  could not be turned on. Values accept a YAML list or a comma-separated string;
  unusable values omit the parameter instead of sending it. Defaults are
  unchanged, and both keys are documented in `config.example.yaml`. ([#5719])
- **skills:** The custom-skill rollback route no longer reads the skill's edit
  history on the event loop. `POST /api/skills/custom/{skill_name}/rollback`
  constructed the storage, probed existence, and parsed
  `custom/.history/<name>.jsonl` inline, and each history entry carries the
  full previous and new skill contents, so a rollback stalled every other run
  and stream on the worker for the parse. The work now runs on a worker thread,
  matching the adjacent history handler; status codes and response shapes are
  unchanged, and blocking-IO anchors guard the route. ([#5729])
- **mcp:** Durable MCP task calls now bound connection setup and MCP
  initialization under the same `session_init_timeout` deadline as session
  entry. The timeout previously started only after entering the session
  context, so an SSE server that accepted HTTP but never sent the MCP endpoint
  event kept the call waiting indefinitely. After initialization succeeds the
  deadline is disabled and the existing independent tool-call timeout applies;
  `None` still disables the initialization bound. ([#5733])
- **skills:** `required-secrets[].optional` must now be a YAML boolean. A quoted
  value like `optional: "false"` passed frontmatter validation and was later
  parsed with Python truthiness, so `bool("false")` recorded a required secret
  as optional and produced wrong missing-secret diagnostics and exported
  requirement metadata. Validation rejects non-boolean values, and the runtime
  parser fails closed to `optional=False` with a warning (value type and secret
  name only) for mounted or historical skills. The skill-review analyzer flags
  the shape as `structure.invalid-required-secrets-optional`. ([#5738])
- **skills:** Skill review no longer keeps sentence punctuation on extracted
  resource references. A bare path at the end of a sentence ("See
  references/setup.md.") was extracted with its trailing period, producing a
  false `resource.missing` finding and a spurious orphan for the real file.
  Extracted references now strip trailing `.`, `?`, and `!`, while real dotted
  filenames such as `references/config.yaml` and link targets like
  `references/v1.0.md` stay intact. ([#5739])
- **uploads:** Remove a staged upload's `.part` only after its document-conversion
  descriptor is released. With `uploads.auto_convert_documents` enabled, commit
  unlinked the staged file while conversion still held an open descriptor, so on
  Windows every convertible upload (PDF/DOCX/PPTX/XLSX) failed with `WinError 32`
  (500) where POSIX silently allowed it. The staged name is now removed in the same
  cleanup that releases the descriptor, and abort-path cleanup is best-effort so a
  secondary removal failure can no longer mask the original error. ([#5740])
- **composer:** Keep IME-composition Enter out of the slash-skill catalog. The main
  prompt textarea's suggestion handler lacked the `isIMEComposing` guard its sibling
  call sites had, so with an IME active and the `/` catalog open, the Enter that
  committed a CJK composition instead applied the highlighted skill and discarded
  the in-progress text. IME-consumed keydowns now fall through to the normal submit
  path; plain Enter still selects the highlighted skill. ([#5741])
- **sandbox:** Cancel BoxLite loop work whose synchronous bridge wait timed out.
  `run_coroutine_threadsafe(...).result(timeout)` raised to the caller but left the
  submitted coroutine running on the private loop, so the sandbox could keep
  mutating or retain acquire ownership after the operation was reported as timed
  out; the pending future is now cancelled before the timeout re-raises, while
  already-completed futures are left alone. ([#5748])
- **mcp:** Invalidate the MCP tool cache only when the effective MCP configuration
  changes. Invalidation previously keyed on the whole `extensions_config.json`
  signature, so toggling an unrelated skill rebuilt cached tools and retired every
  pooled stdio session. The cache now compares a snapshot of the enabled servers'
  parsed settings (declaration order) and global `mcpInterceptors` before retiring
  anything; when no servers are enabled, a non-initializing refresh retires stale
  state without adding discovery overhead, and malformed-config error logging no
  longer emits resolved credentials. ([#5750])
- **gateway:** Drain artifact updates to completion across request cancellation.
  Cancelling `PUT /api/threads/{thread_id}/artifacts/{path}` unwound the
  thread-operation reservation and sandbox lease while the non-mounted remote sync
  was still mutating the sandbox, leaving the remote and host copies at different
  bytes and letting later work overlap the abandoned mutation. The full
  remote-sync/local-replace transaction is now drained before ownership is
  released, with rollback semantics preserved and the primary commit failure logged
  before rollback. ([#5755])
- **uploads:** Preserve the original link error when staged-upload cleanup fails.
  On a failed link commit whose conversion descriptor was still open, Windows
  rejected the error handler's unlink with a sharing violation and that secondary
  error replaced the real endpoint error; the generic link-failure path now
  respects `unlink_staged=False` and all staged cleanup is best-effort. A cleanup
  failure after a successful link also no longer returns 500 for an
  already-published destination. ([#5756])
- **runtime:** Drain database provider context exits across caller cancellation.
  The async SQLite/PostgreSQL checkpointer and Store providers used raw
  `async with`, so a cancellation delivered while the backend's `__aexit__()` was
  blocked cancelled the teardown itself and let the provider finish with incomplete
  database/pool cleanup — deterministically across all six provider paths. A
  `drained_async_context()` helper now preserves exception and suppression
  semantics while draining the exit to completion. ([#5757])
- **channels:** Resolve the Buzz seen-event store path off the event loop.
  `ChannelService._start_channel` built the default `seen_event_store_path` inline,
  dereferencing `Paths.base_dir` (a `realpath`) on the loop in a path reachable
  from `POST /api/channels/{name}/restart`; the resolution now runs in a worker
  thread, with a blocking-IO anchor pinning it to the strict gate. ([#5759])
- **sandbox:** Resolve the AIO sandbox acquire lock path off the event loop.
  `_discover_or_create_with_lock_async` offloaded every acquire step except the
  inline lock-file path construction, which dereferences `Paths.base_dir` (a
  `realpath`) on the loop on the hot path of every sandboxed tool call; the
  resolution now joins the surrounding steps in a worker thread, and the sibling
  ownership-publish anchor exercises the production path layer again. ([#5760])
- **threads:** Do not leave orphan threads behind when a LangGraph run is rejected.
  Standalone run admission pre-creates a missing thread before LangGraph re-checks
  assistant ownership, so a run against another user's non-system assistant
  returned the expected 404 but had already persisted an idle thread owned by the
  caller. Admission now verifies the assistant's server-owned provenance before
  `Threads.put` (with the ambient auth context temporarily cleared), while
  ordinary users can still implicitly create threads for registered system
  assistants. ([#5762])
- **setup:** Run the pre-commit hook through `uv` so `make install` no longer fails
  when uv's tool bin directory is not on PATH, and make the Node.js prerequisite
  check actionable: nvm users get an install command and everyone else a link to
  the official download page. ([#5767])
- **scheduler:** Read the dispatch lease owner under SQLite's writer lock.
  `release_dispatch_lease` was the only mutating path that skipped `_lock_task`,
  and because `FOR UPDATE` is ignored on SQLite its guard evaluated a stale
  snapshot: a pause landing inside the dispatch window could be overwritten,
  leaving the task `enabled` and firing again even though the API had confirmed
  the pause. The read now takes the writer lock first; PostgreSQL behavior is
  unchanged. ([#5777])
- **utils:** Initialize `Article.url` so `to_message()` no longer raises
  `AttributeError` for pages containing images. `ReadabilityExtractor` never passed
  the page URL into `Article`, so resolving a relative image URL via
  `urljoin(self.url, …)` crashed; the attribute now defaults to `""` and the
  extractor passes the real URL. ([#5785])
- **tools:** Coerce DDG web-search result limits from environment variables.
  `max_results: $DDG_MAX_RESULTS` kept the substituted string, and DDGS
  9.14.1 raised a `TypeError` sizing its workers that the search wrapper
  reported as `No results found` for every query. Configured limits now
  accept numeric strings; invalid or non-positive values log a warning and
  fall back to the default of 5, while integer configs, the default, and
  config-over-call precedence are unchanged. ([#5792])
- **gateway:** Treat a blank `GATEWAY_HOST` or `GATEWAY_PORT` as unset. A
  compose file with `GATEWAY_PORT=` (or `GATEWAY_PORT=${PORT}` with `PORT`
  unset) handed an empty string to `int()`, killing the Gateway at import
  time before uvicorn could bind. Blank values now fall back to the declared
  defaults (`0.0.0.0` / `8001`); `GATEWAY_PORT=0` still asks the OS for a
  free port, and every non-empty value parses exactly as before. ([#5801])
- **channels:** Persist channel runtime configuration as UTF-8. The store
  read its JSON as UTF-8 but wrote its temporary file with the host's default
  encoding and `ensure_ascii=False`, so on non-UTF-8 hosts (CP1252, GBK)
  non-ASCII values — such as a configured Buzz relay URL — could fail to save
  or be written in bytes the store could not read back. The temporary write
  now specifies UTF-8; atomic replace, locking, and chmod behavior are
  unchanged, and legacy-encoded files are not migrated. ([#5803])
- **setup:** Accept successful Apple Container image pulls in
  `make setup-sandbox`. On macOS with Apple Container installed and Docker
  absent, the script fell through to the Docker availability check and exited
  1 with "Neither Docker nor Apple Container is available" after the image
  had already been pulled. An Apple-only pull now counts as success and
  continues to the default-image note; Docker behavior, including fallback
  after an Apple Container failure, is unchanged. ([#5804])
- **runtime:** Keep agent stream teardown alive across repeated
  cancellation. `close_agent_stream()` awaited `stream.aclose()` in the
  caller task, so a second `Task.cancel()` during teardown cancelled the
  close itself and let callers abandon releasing graph, provider, sandbox,
  and tool resources; a close-originated `CancelledError` also made a broken
  close look interrupted instead of failed. The close now runs in a dedicated
  shielded task, the first caller cancellation is deferred until it
  completes, and stream-originated close cancellation is reported as a close
  failure so the run terminalizes as failed. ([#5806])
- **tools:** Apply the #5792 numeric-string coercion to DDG image search.
  `image_search_tool` passed the environment-substituted `max_results`
  string straight to DDGS, which raised a `TypeError` sizing its workers, so
  `max_results: $IMAGE_MAX_RESULTS` made every query return `No images
  found`; `0` removed the limit and negative values truncated results.
  Numeric strings now work, and invalid, zero, or negative values warn and
  fall back to 5, with integer configs and the default unchanged. ([#5807])
- **client:** Stop resumed embedded-client streams from replaying prior
  turns. On a resumed thread, `DeerFlowClient.stream()` re-emitted earlier
  turns' message deltas — including tool results — in `messages-tuple`
  events and counted their tokens in `end.usage`, overstating per-turn
  usage. Historical messages stay in `values` full-state snapshots but are
  suppressed from the current turn's deltas and usage, with the per-run
  `run_id` on the current user message as the boundary; Gateway SSE is
  unchanged. ([#5811])
- **persistence:** Drain the postgres schema-setup connection exit across
  cancellation. `_ensure_postgres_schema_with_pool` still acquired its
  connection with a raw `async with`, so caller cancellation landing while
  the connection's `__aexit__` was blocked interrupted the exit and the
  connection was never returned to the pool, whose drained teardown then
  closed with a checked-out connection. The connection now goes through
  `drained_async_context()` like the rest of the checkpointer provider; no
  happy-path behavior change. ([#5812])
- **mcp:** Stop the bare-filename correlation pass from mangling backslash
  paths. After a stdio MCP call created `page.yml`, a result mentioning
  `C:\outside\page.yml` had its basename rewritten to point at the new
  workspace file, because the pass treated a backslash as a bare-filename
  boundary. Backslashes now act as path separators on both sides of a
  correlated name, so genuine bare filenames still resolve while names
  inside unresolved Windows, UNC, or relative paths stay unchanged. ([#5815])
- **mcp:** Resolve generated file paths containing spaces in MCP text
  results. A file named `artifact with space.txt` kept its absolute host
  path in the free-text tool result, and a follow-up `read_file` failed with
  `Permission denied` because whitespace hid the complete filename from the
  token matcher. Whitespace-containing absolute and workspace-relative paths
  now correlate with files the call created, validated inside the current
  thread's user-data tree; outside paths and ambiguous suffixes are
  untouched. ([#5819])
- **middleware:** Preserve human message metadata in `ThreadDataMiddleware`.
  Adding run metadata reconstructed the last `HumanMessage` from parts,
  silently dropping fields it did not copy such as `response_metadata`; the
  middleware now copies the existing message and updates only its default
  name and `additional_kwargs`. ([#5823])
- **uploads:** Keep document-conversion `stat()` and markdown write-back off
  the event loop. `convert_file_to_markdown` offloaded the conversion itself
  but still ran the size-check `stat()` and the multi-megabyte `write_text`
  of the converted markdown on the loop, blocking upload ingestion for large
  documents. Both now go through the shared `run_file_io` pool; the
  small-file inline conversion threshold is unchanged. ([#5830])
- **mcp:** Run lazy MCP tool discovery once when initialization itself raises.
  The no-event-loop `except RuntimeError` fallback in `get_cached_mcp_tools()`
  also caught discovery's own errors: with no running loop a failing call
  spawned every stdio server and re-fetched OAuth tokens twice — repeated on
  every later call, since a failed init never marks the cache initialized —
  and inside a running loop the log buried the real cause under "asyncio.run()
  cannot be called from a running event loop". Initialization is now driven
  exactly once with the real failure logged; errors still return `[]` and
  leave the cache uninitialized for the next retry. ([#5836])
- **config:** Honor `$VAR` substitution for `request_admission` integer fields.
  `requests_per_minute` and `max_queue_size` are declared `strict=True` so
  `true` and `60.0` stay rejected, but an environment substitution like
  `requests_per_minute: $RPM` arrived as the string `"60"` and failed the whole
  `config.yaml` load with `int_type` — quotas kept in the environment could not
  pace a model at all. A `BeforeValidator` now converts a plain decimal string
  to `int` before the strict check; bools, floats, `"60.0"`, empty and
  non-numeric values are still rejected and `gt=0` is unchanged. ([#5838])
- **tools:** Coerce Exa's configured result limits before calling the SDK.
  `$VAR` substitution resolves to strings, so `max_results: $EXA_MAX_RESULTS`
  made every `web_search` call fail — exa-py rejects a string `num_results` —
  and `contents_max_characters` went out as `"maxCharacters": "1000"`. Both are
  now parsed as integers (a non-boolean integer or integer-form string only); a
  blank, non-numeric, fractional, boolean, zero or negative value logs a
  warning and falls back to the defaults (5 and 1000) instead of failing the
  search, matching the DDG and SearXNG providers. ([#5839])
- **gateway:** Treat a blank `GATEWAY_WORKERS` and blank Lark broker port or
  timeout as unset, extending #5801's blank-env rule. `int("")` in the WeChat
  QR-login guard turned a blank `GATEWAY_WORKERS` (e.g. `-e GATEWAY_WORKERS=`)
  into a 503 "requires a single Gateway worker" on every QR route even though
  the Gateway runs one worker, and a blank `DEERFLOW_LARK_BROKER_PORT`/`_TIMEOUT`
  aborted the Lark broker at startup. The guard now reads `GATEWAY_WORKERS or
  WEB_CONCURRENCY or "1"` and still fails closed on multi-worker or non-numeric
  values; the broker falls back to its defaults. ([#5840])
- **skills:** Strip section anchors from code-span resource references in the
  skill review resource graph. Markdown-link targets already dropped
  `#fragment` before resolving, but a code-span reference like
  `references/faq.md#pricing` kept the anchor, resolved as a literal path, and
  raised a false `resource.missing` warning even though the file exists and is
  referenced. Code-span tokens now split the fragment the same way and strip
  trailing sentence punctuation; dotted filenames such as
  `references/v1.0.md#notes` keep their extension dots. ([#5841])
- **config:** Sign the bytes the config cache parsed, not a second read. The
  app-config loader opened `config.yaml` twice — parse once, then hash a fresh
  read to record the `(mtime, size, sha256)` signature — so a write landing
  between the two reads cached the older content under the newer signature and
  `get_app_config()` never reloaded it, silently serving a stale config until
  some later edit. The loader now reads once through a shared
  `file_signature.read_config_with_signature()` helper that signs exactly the
  returned bytes; a racing edit can only cost one extra reload. ([#5848])

### Security

- **authz:** Enforce permission checks on routes that only had authentication, and
  scope `USER.md` per user. `POST /api/threads`, `/api/threads/search`,
  `/api/runs/stream`, `/api/runs/wait`, every `/api/memory` route, and the
  custom-agent routes carried no `@require_permission`, so a provider configured
  to deny `threads:write`/`runs:create`/... could not enforce those decisions.
  `GET/PUT /api/user-profile` also read and wrote one global `USER.md`, letting
  any authenticated user overwrite or read everyone's prompt context — the file
  now lives at `{base_dir}/users/{user_id}/USER.md`. ([#4989])
- **gateway:** Preserve owner isolation on threads whose metadata row is missing or
  NULL-owner. #5448's internal-caller run scoping returned an empty filter for every
  trusted internal caller, and `ThreadMetaStore.check_access(..., require_existing=False)`
  deliberately admits a missing metadata row (legacy compatibility) and NULL-owner rows,
  so an internal caller acting for owner A could list or fetch owner B's persisted runs
  on such a thread via `/runs`, `/runs/page`, or `/runs/{run_id}` (the single-run request
  returned 200 instead of 404). `_run_scope_user_id` now consults the thread meta store:
  established-owner threads keep the unfiltered read, while missing/NULL-owner threads
  fall back to the acting owner's raw stamp, keeping cross-user runs hidden. Browser and
  API sessions are untouched. ([#5484])
- **frontend:** Gate tool-step links through the shared `isSafeHref` scheme allowlist.
  The `web_fetch`, `web_search`, and `image_search` tool steps put URLs straight into
  `<a href target="_blank">`, so a `ms-msdt:`, `search-ms:`, or `vscode:` link drawn
  from model-written tool arguments (or provider results) rendered clickable — backend
  URL validation never sees a still-streaming or failed fetch — and one click plus the
  browser's external-application prompt handed an attacker-chosen URI to a local
  application. Unsafe URLs now render as the same inert "Unsafe link omitted" span
  markdown links use; `web_fetch` also stops throwing on a non-string `url` arg, and
  missing tool-call `args` normalize to `{}` across every tool branch. ([#5526])
- **uploads:** Stop the embedded client's uploads from writing through
  symlinks. The uploads directory is writable from inside the sandbox, so a
  process there (for example one steered by prompt injection) could plant
  `notes.txt -> /host/path` and have the next `DeerFlowClient.upload_files` —
  or a converted Markdown companion — overwrite an arbitrary host file with
  the client's privileges. Uploads now publish through a no-symlink copy
  helper; unsafe destinations are skipped and reported via `skipped_files`
  with `success: false`, matching the Gateway's contract. ([#5578])
- **uploads:** Convert a private copy of the staged bytes instead of the name
  they landed under. The uploads directory is writable from inside the sandbox,
  so a process there could swap an upload's committed name for a symlink to any
  host file in the window before document conversion; the converter opens by
  path and follows it, and the host file's content came back into the thread as
  the converted `.md` companion. The Gateway now converts a descriptor-backed
  copy in a private temporary directory, and the client converts the caller's
  own source path — a swapped name no longer redirects the read. ([#5611])
- **authz:** Enforce `threads:write` for Live Browser WebSocket connections.
  The WebSocket bypassed the HTTP authentication middleware, and
  `browser_stream()` checked authentication, Origin, thread ownership and
  browser availability without resolving route permissions — so a thread owner
  whose policy denies `threads:write` could still connect to the thread's Live
  Browser, receive frames, and dispatch input events. Denied connections are
  now rejected with close code `4403` before session acquisition; behavior is
  unchanged when fine-grained authorization is disabled. ([#5621])
- **gateway:** Reject external `system` and `developer` messages with HTTP 400
  before checkpoint writes, run admission, or agent execution. Such messages
  were previously accepted and could be persisted, merging into the agent's
  system context on later turns. Message representations are canonicalized once
  and validated; ordinary user, assistant, tool, and attachment messages and
  trusted internal system messages are unaffected, and existing checkpoints are
  not rewritten. ([#5651])
- **skills:** A user-scoped `.skill` install now resolves the static content
  scan from the same app config as the inherited archive preflight. The
  user-scoped storage override passed no `app_config`, so the content scan fell
  back to the hot-reloaded process global: when a storage's snapshot had
  `skill_scan.enabled: true` and a later `config.yaml` edit set it to `false`,
  the preflight ran but the content scan silently skipped and a CRITICAL archive
  (such as embedded private-key material) installed anyway. The per-file LLM
  scan now forwards the same config instead of reading the global for model
  selection. ([#5703])
- **sandbox:** Restored sandbox references are now scoped to the authenticated
  user and thread. An authenticated caller could submit
  `input.sandbox.sandbox_id` on a thread they owned, and the AIO restore path
  resolved the body-supplied id from a process-wide active-sandbox cache
  without checking the cached sandbox's `(user_id, thread_id)`, so a known
  still-active foreign sandbox id could have sandbox-backed tool calls
  dispatched to it. `sandbox` is now server-owned state: external run input and
  thread-state updates reject it with HTTP 400, checkpoint reuse requires a
  scoped match and otherwise falls back to a canonical
  `acquire(user_id, thread_id)` persisted with `Overwrite`, and only the
  server-created fork path may borrow a parent's sandbox. ([#5736])
- **logging:** Redact space-carrying request targets in urllib3 retry log lines.
  Three redaction patterns (`Retry: …`, `Retrying (…) …`, and the quoted request
  line) stopped matching at the first space, so an origin-form path containing an
  interior space — allowed by RFC 9110 — reached the log in cleartext with its
  signature query intact; the `Retrying` shape logs at WARNING, so it landed in
  production logs without DEBUG. The patterns now match the target up to its
  terminating quote or end of line, consistent with the already-hardened
  `Redirecting` and increment-retry slots. ([#5745])
- **auth:** Claim the first admin atomically in `POST /api/v1/auth/initialize`. The
  handler counted admins in one session and created the user in another with no
  lock or constraint between them, so two concurrent first-boot requests with
  different emails both succeeded and both became admins — silently, since
  `setup-status` then reports an initialized system. Count and insert now share one
  serialized transaction (`BEGIN IMMEDIATE` on SQLite, a transaction-scoped
  advisory lock on PostgreSQL, unknown dialects fail at boot), and a losing request
  gets the documented `409 system_already_initialized`; sequential behavior and
  response shapes are unchanged. ([#5776])
- **sandbox:** Require `sandbox:execute` before `view_image` reads. A role
  allowed to call `view_image` while denied `sandbox:execute` could still
  read an image from the current thread's allowed directories, and the image
  middleware could place those bytes into a model request — an authorization
  gap, not a cross-user read. Synchronous and asynchronous reads now check
  execution authorization, and the middleware rechecks before reading an
  image recorded in thread state, including after a role change. ([#5799])
- **authz:** Enforce `model:use` on the suggestions endpoint. With model
  authorization enabled, a user denied a model could still invoke it through
  `POST /api/threads/{thread_id}/suggestions` — by naming it, or by omitting
  the name when the denied model was the configured default — even though
  `GET /api/models/{model_name}` returned 403 for the same user. The shared
  model-details check now runs before model creation, returns 403 on denial,
  and sits outside the best-effort handler so a permission failure cannot
  become `200` with empty results. ([#5816])
- **sandbox:** Scope viewed-image host reads to the current thread. External
  run input or thread-state updates could supply `viewed_images` metadata
  with a chosen `actual_path`, and after matching `view_image` history the
  middleware read that host path into the next model request, so one user's
  request could carry another user's image. External writes to the
  server-owned `viewed_images` and `thread_data` channels are now rejected
  with `400` before run admission, and a saved host copy is read only when
  the recorded virtual path, resolved for the current user and thread,
  matches `actual_path`; cross-thread references stay unavailable until
  `view_image` runs again. ([#5824])

### Documentation

- **docs:** Fix the Apple Container verification instructions. The guide
  pointed to a `test_container_runtime.py` script that does not exist and to
  the old runtime implementation; it now references `LocalContainerBackend` in
  `local_backend.py`, documents the existing Docker selection for restricted
  networking, and uses the two existing runtime-selection pytest cases (which
  mock runtime commands) as verification. ([#5605])
- **config:** Move the `# Sandbox Configuration` banner in `config.example.yaml`
  to sit directly above the `sandbox:` key it introduces instead of the
  `uploads:` block it had drifted twenty lines away from, and give `uploads:` a
  banner of its own. Comment-only change; `config.yaml` files generated from the
  example are unaffected. ([#5652])
- **docs:** Clarify the upgrade workflow for existing local and Docker
  deployments in the README and the operations-and-troubleshooting guide:
  `make config` and `make docker-init` are first-time setup steps, not routine
  source-upgrade steps, and `make config-upgrade` is only needed when a release
  adds configuration fields. ([#5654])
- **docs:** Document how to connect DeerFlow to a local llama.cpp
  `llama-server` (closes #2931). `config.example.yaml` and the English/Chinese
  configuration pages gain an OpenAI-compatible Qwen example (`use:
  langchain_openai:ChatOpenAI` against `http://localhost:8080/v1`), and cover
  the `--alias` model name, a Docker-reachable `base_url`, the API key when
  `llama-server --api-key` is enabled, and the chat-template/tool-calling
  requirement. ([#5688])
- **extensions:** Cover full-stack plugins and request-scoped run evidence in the
  extensions manual (deerflow-extension-api 0.2.3, en and zh). A new Full-Stack
  Plugins chapter documents `registry.plugin()`, `BrowserModule`/`BrowserAssets`,
  backend actions, model tools, and settings; the run-evidence chapter covers
  `resolve_run_evidence_reader`/`require_run_evidence_reader` with a per-user route
  example; and plugin sections are added to Reference, Troubleshooting, and
  Operating Extensions. ([#5775])
- **docs:** Correct the documented skill and MCP enable/disable endpoints. The docs
  site and `backend/docs/API.md` pointed at `POST /api/extensions/skills/{name}/enable`
  and similar routes that do not exist in the gateway (404/405); the skill toggle
  is `PUT /api/skills/{name}` with `{"enabled": bool}` and the MCP toggle is
  `PATCH /api/mcp/config` with `{"server_name", "enabled"}` (both admin only), now
  documented in the en/zh skills and MCP pages and in API.md with working cURL
  examples. ([#5778])
- **docs:** Fix backend doc examples that referenced APIs that do not exist.
  The `PATH_EXAMPLES.md` upload example imported a `THREAD_DATA_BASE_DIR`
  symbol no module exports, and pointed at the legacy upload bucket; it now
  resolves the directory via `get_uploads_dir(thread_id)` from
  `deerflow.uploads.manager`, which reads the bucket the Gateway actually
  writes to. `CONFIGURATION.md` also drops a `sandbox.auto_start` key that
  `SandboxConfig` never declared and no code reads. ([#5798])
- **docs:** Make the custom-memory-storage guide followable. The harness
  `memory.mdx` / `customization.mdx` snippets imported a module that does not
  exist, showed a storage class the factory cannot construct and the memory
  updater's calls reject, documented a `module:Class` value form that
  `storage_class` never resolves, and promised a graceful fallback where the
  code deliberately raises. The guide (English and Chinese) now names the real
  module, matches the real call shapes, and states the actual error behavior. ([#5844])
- **docs:** Add a ten-chapter checkpoint storage manual (`harness/checkpoints`)
  in English and Chinese — quick start, channel modes, snapshot cadence, history
  cache, resume and rollback, operations, observability, troubleshooting and
  reference. The docs site's first coverage of dual-mode checkpoint storage: why
  the mode and snapshot cadence are frozen per process (only
  `checkpoint_graph_cache.accessor_graph_max` re-reads at runtime), why a
  mode-mismatched request 409s, why delta runs cannot fork, and how retained
  storage really grows — periodic snapshots keep the full message list, so
  delta divides the quadratic term by the cadence rather than removing it. ([#5845])

### Internal

- **persistence:** Add historical regression coverage for the run-change clock repair
  and its rollback. Databases created from the published migration graph at
  `0023_user_preferences` or `0024_project_documents` skip the later-inserted
  `0023_run_change_seq` ancestor; new tests reconstruct both affected graphs and
  exercise the real startup bootstrap, legacy rows, and thread-delete reservation/state
  writes, and verify healthy positions survive repeated bootstrap, downgrade, and
  re-upgrade. Documentation only — the repair itself landed in #5517; no runtime
  behavior change. ([#5518])
- **capabilities:** Internal cleanup of the capability gallery and MCP
  connection validation: named status/action helpers with early returns, a
  separate `validate_mcp_connection()` with unchanged 422 responses, a shared
  `installationQuery()`, and removal of an unused display-name argument from
  `catalogForServer()`. Rendered UI and behavior are unchanged. ([#5580])
- **deps:** Bump `anyio` from 4.13.0 to 4.14.2 in `/backend`. ([#5583])
- **sandbox:** Share offline search contracts across sandbox providers. A new
  112-case parameterized suite exercises the same `ls` / `glob` / `grep`
  scenarios through all six adapters against a shared fixture filesystem,
  covering ignored descendants, special paths, grep scope, overflow, transport
  failures, and unavailable binaries. Production code is unchanged. ([#5677])
- **persistence:** `langgraph-checkpoint` is bumped to `>=4.2.0,<5.0` and the
  postgres extra's `langgraph-checkpoint-postgres` to `>=3.1.2,<3.2`, letting
  `checkpoint_patches.py` drop its `InMemorySaver` patch in favor of the
  upstream fixes for the dropped first write after a full → delta migration and
  for plain-value delta seed detection. The floors are load-bearing: without
  them a resolver can quietly install the versions whose bug is no longer
  patched. Behavior is unchanged — the local patch had been masking the bug.
  ([#5734])
- **tests:** Cover the delta-history cache's full-to-delta migration and pin
  two open upstream `DeltaChannel` defects. The migration contract now runs
  with the history cache disabled, cold, and warm, asserting materialized
  history is digest-identical to an uncached saver; new regressions pin
  langgraph#8382 (same-superstep parallel writes replay out of live order)
  and langgraph#8448 (the Postgres paged delta walk poisons its cursor, so
  older checkpoints hydrate empty), skipping until upstream fixes land. No
  runtime behavior change. ([#5797])

## [2.1.0] — 2026-09-24

This section accumulates work toward the **2.1.0** milestone
([2.1.0](https://github.com/bytedance/deer-flow/milestone/2)).
This release closes that milestone with **772 merged pull requests**.

### ⚠ Breaking changes

- **gateway:** Request trace ids are now issued unconditionally, and every
  Gateway HTTP response carries an `X-Trace-Id` header. Previously both were
  gated behind `logging.enhance.enabled`, which now controls **log output
  only** — whether records carry a `trace_id` field, and in which format. The
  header cannot be turned off; installations running the default
  `enabled: false` will start seeing it after upgrading. Scheduled tasks, MCP
  task notification runs, IM channel messages, and the embedded
  `DeerFlowClient` bind an id per unit of work, so the id also reaches the run
  record, the checkpoint metadata, and Langfuse traces that previously had
  none. A `deerflow_trace_id` supplied in a run request's `metadata` or
  `config.context` is now ignored and overwritten so the response header, the
  logs, and the persisted run cannot disagree — send the `X-Trace-Id` request
  header to pin a correlation id across services. `logging` remains
  restart-required. No config keys were added or removed. ([#5119])
- **skills:** Sandboxes now reserve `/mnt/skills` for managed enabled-only
  projections. `DEER_FLOW_HOST_SKILLS_PATH` and `SKILLS_HOST_PATH` are no longer
  used; Docker/AIO and hostPath deployments derive projection paths from
  `DEER_FLOW_HOST_BASE_DIR`. E2B operator mounts targeting `/mnt/skills` or any
  child path are skipped with a warning so they cannot shadow the managed
  projection; move extra E2B content to a different container path. User
  projections re-read global enable state from disk so toggles propagate across
  Gateway workers on the next sandbox acquire. Existing E2B sandboxes retain
  their creation-time snapshot until they are recreated. PVC-backed provisioner
  deployments still mount the operator-supplied PVC snapshot directly, so
  disabled-skill filesystem isolation does not apply in PVC mode until dynamic
  PVC materialization is implemented. ([#4178])
- **sandbox:** E2B now enforces `sandbox.replicas` as a process-local capacity
  limit. The default `wait` policy waits for `acquire_timeout`, then fails the
  agent turn. DeerFlow does not retry the turn automatically. Use `burst` with
  `burst_limit` to permit bounded extra VMs. The `reject` policy can remove one
  warm VM before it returns a capacity error. ([#4391])
- **skills:** A directory containing `SKILL.md` is now a runtime package
  boundary. Nested `SKILL.md` files inside that package are supporting data and
  are no longer registered as independent skills; unusual custom layouts must
  move independently loadable skills under a namespace directory without its
  own `SKILL.md`. ([#4098])
- **memory:** The memory system is now pluggable (`memory.manager_class` selects
  a backend; default `deermem` is self-contained). DeerMem-private settings moved
  from the top level of `memory:` into `memory.backend_config`, and the
  `/memory/config` response (and `client.get_memory_config()`) changed shape.
  ([#4122])
- **memory:** `/memory/config` and `client.get_memory_config()` no longer return
  flat DeerMem fields (`storage_path`, `max_facts`, `debounce_seconds`,
  `token_counting`, `guaranteed_*`, `staleness_*`, ...). They return
  `{enabled, mode, injection_enabled, manager_class, backend_config}` where
  `backend_config` is an opaque dict the active backend self-interprets. Memory
  *data* responses (`/memory`, `/memory/status` data) are unchanged. External
  API/SDK clients reading the old flat fields must read `backend_config` instead.
  ([#4122])
- **memory:** Custom `memory.storage_class` moved: the old default path
  `deerflow.agents.memory.storage.FileMemoryStorage` no longer exists (now
  `deerflow.agents.memory.backends.deermem.deermem.core.storage.FileMemoryStorage`).
  Custom `MemoryStorage` subclasses must accept `config` in `__init__` (was
  no-arg). A broken/old `storage_class` logs an error and falls back to
  `FileMemoryStorage` (won't crash) -- update the path + signature to restore it.
  ([#4122])
- **memory:** `storage_path` semantics changed from a FILE path to a root
  DIRECTORY. Pre-abstraction, an absolute `storage_path` was the shared memory
  file (opting out of per-user isolation) and a relative value was the global
  file under the data base_dir. Now `storage_path` (absolute or relative) is the
  root directory; per-user memory lives at `{storage_path}/users/{uid}/memory.json`.
  An upgrade keeping the old default `storage_path: memory.json` (a relative file
  name) would orphan per-user memory or hit `NotADirectoryError` on save, so the
  legacy migration **drops file-style `storage_path` values (ending in `.json`)
  with a warning** and the factory **raises** if `storage_path` resolves to an
  existing file. Set `memory.backend_config.storage_path` to a directory for a
  custom root. ([#4122])
- **memory:** `memory.mode: tool` with a backend that does not implement
  `search()` now fails fast at Gateway startup with a `ValueError` from the
  `MemoryManager` invariant, instead of starting successfully and silently
  returning empty results on every `memory_search` call. Both shipping backends
  implement `search()` (DeerMem retrieves; `noop` returns `[]`), so this only
  affects a custom backend that onboards without overriding `search()`. It is
  intentional -- silent empties are worse than a loud startup error. Fix: switch
  to `mode: middleware` or override `search()` (and set `supports_search=True`).
  ([#4324])
- **config:** `database.checkpoint_delta_snapshot_frequency` moved to
  `database.checkpoint_delta.snapshot_frequency` and its default changed from
  `1000` to `10`. A legacy top-level value is still honored with a deprecation
  warning and mapped onto the nested key (an explicitly set nested key wins).
  Deployments that relied on the old default now snapshot 100x more often in
  delta mode -- set `database.checkpoint_delta.snapshot_frequency: 1000`
  explicitly to keep the previous cadence. ([#4516])
- **docker:** The published entry port now binds to loopback (`127.0.0.1`) by
  default in both compose files, matching the documented local-trust deployment
  model. Deployments that relied on the old `0.0.0.0` binding must set
  `BIND_HOST` to expose the stack on other interfaces. ([#4618])

### Added

#### Scheduler
- **scheduler:** Scheduled tasks accept `interval` (`schedule_spec.every_seconds`)
  in addition to `once` and `cron`. Cadence is UTC `now + N` with no
  missed-beat catch-up. N is at least `scheduler.min_once_delay_seconds`
  (default 60s) and at most 30 days. ([#5291])
- **scheduled-tasks:** Upcoming cron occurrences can be inspected before a task
  is saved. `POST /api/scheduled-tasks/preview-cron` takes a five-field cron
  expression, a timezone, a `count` of 1–10 (default 5), and an optional aware
  reference time, and returns the normalized cron, the effective UTC reference,
  and the occurrences in both UTC and local time. It runs the scheduler's own
  calculator in a worker thread, so DST handling matches what a saved task will
  actually do, and it reserves nothing and touches no task, thread, or run
  store; invalid input and date-range failures return 422. ([#5381])
- **scheduled-tasks:** Run history can be filtered server-side by occurrence
  status. Finding a rare failure used to mean downloading every history page
  and filtering in the client, since a failure behind many newer successes
  could sit on any page; `GET /api/scheduled-tasks/{task_id}/runs` now accepts
  `?status=` with `queued`, `launching`, `running`, `success`, `failed`,
  `skipped`, and `interrupted`, applying the predicate before pagination so
  `?status=failed&limit=50&offset=0` returns the first page of real failures.
  Unknown values, including the parent task's own `completed`, return 422,
  empty results return `[]`, and the unfiltered array response is unchanged.
  ([#5384])
- **scheduled-tasks:** The scheduled-task detail pane can page backwards
  through execution records. It showed only the latest 50 even though the
  endpoint already supports limit and offset, so anything older was unreachable
  from the UI. Newer, Older, and Latest navigation now walk the history with
  localized page, loading, error, and retry states; each request fetches one
  row past the page to decide whether an older page exists rather than
  inventing a total count, a short final page disables Older, switching tasks
  resets to the latest page and cancels the obsolete request so a late result
  cannot replace the new task's history, and only the latest page polls.
  ([#5363])

#### Authentication
- **auth:** Personal access tokens (PAT) for programmatic API access:
  `POST/GET/DELETE /api/v1/auth/pats` manage tokens (shown once, stored as
  SHA-256 digests); a default-deny route policy admits only the thread/run
  lifecycle routes, narrowed further by the token's `threads`/`runs` scopes,
  and any request dimension that carries cancel capability (`?action=`,
  `multitask_strategy`) additionally requires `runs:cancel`. ([#5041])
- **auth:** Login throttling parameters are configurable via
  `auth.local.max_login_attempts` (default 5, min 2) and
  `auth.local.lockout_seconds` (default 300), resolved live so a config reload
  applies on the next login without a Gateway restart — the unblock path for
  deployments behind corporate proxies/NAT where many users share one egress
  IP. Defaults are unchanged. ([#5110])
- **settings:** Account preferences survive a cleared browser or a move to
  another device. The notification toggle, default model, conversation mode,
  and reasoning effort are stored as independent `(user_id, key)` rows behind
  session-authenticated `GET`/`PATCH /api/v1/auth/preferences`, hydrated from
  the server before first paint, with a tab-local outbox and capped-backoff
  retry so a failed write is not silently dropped; `null` resets a field. Only
  those four allowlisted fields are transmitted — device notification
  permission, display settings, and thread-specific model overrides stay local,
  and an automatic composer fallback is never uploaded as an explicit account
  preference. Existing unscoped local settings are not migrated, since they
  carry no known owner, so users reselect these four once after upgrading.
  ([#5397])

#### Agents & runtime

- **scheduler:** Scheduled tasks can pin `assistant_id` to `lead_agent` (the
  default) or a custom agent the owner already has. Unknown or malformed names
  return 422. The workspace create/edit form exposes the same choice.
  ([#5286], [#5288])
- **gateway:** `GET /api/threads/{thread_id}/runs/page` walks thread run history
  with a `(created_at, run_id)` keyset cursor (`{data, has_more,
  next_before_created_at, next_before_run_id}`). `GET /api/threads/{thread_id}/runs`
  still returns a bare array of the newest 100 runs so LangGraph SDK clients keep
  working. ([#5282], [#5283])
- **middleware:** New `TokenBudgetMiddleware` enforces a per-run token budget,
  shared additively across the lead agent and subagents. ([#3412])
- **middleware:** Structured tool-result metadata and a tool-progress state
  machine give the runtime first-class visibility into multi-step tool flows.
  ([#3601])
- **context:** Record the effective memory identity per run and persist durable
  context (system messages, memory, and tool state) across summarization,
  emitting it as structured runtime metadata so compaction no longer drops it.
  ([#3556], [#3887], [#3906])
- **runtime:** Goal continuations let a run resume toward a goal across multiple
  agent turns, with `continuation_count` tracked and capped. ([#3858])
- **subagents:** A system-maintained delegation ledger prevents redundant
  re-delegation of an in-flight task, and a total delegation cap bounds fan-out
  per run. ([#3877], [#4115])
- **subagents:** Persist and display subagent step history in the thread.
  ([#3845])
- **tools:** Structured synopses replace raw oversized tool output in previews.
  ([#3377])
- **files:** Deterministic read-before-write version gate for file tools
  prevents clobbering concurrent edits. ([#3912])
- **gateway:** Cache-aware cost accounting attributes token costs to cached vs.
  uncached paths; a Redis stream bridge enables distributed event streaming; and
  manual context compaction is exposed to the user. ([#3920], [#3191], [#3969])
- **gateway:** The stream-bridge heartbeat interval is configurable via
  `stream_bridge.heartbeat_interval_seconds` (default 15s), so deployments
  behind aggressive proxy idle timeouts can tune SSE, `/wait`, and internal
  subscribers together. ([#5017])
- **runtime:** Dual-mode checkpoint storage with LangGraph `DeltaChannel` cuts
  thread storage from O(N²) to near-linear for long research/coding runs.
  ([#4292])
- **runtime:** Delta-mode checkpoint history cache (memory/redis) with O(1)
  incremental composition, configured via `database.checkpoint_cache`. ([#4638])
- **agent:** Config-declared lead-agent middlewares let deployments add custom
  `AgentMiddleware` classes without patching the runtime chain. ([#3964])
- **agents:** Per-agent model and generation settings (`temperature`,
  `max_tokens`, `thinking_enabled`, `reasoning_effort`) override the shared
  model profile. ([#4347])
- **runtime:** Record terminal artifact-delivery receipts so runs expected to
  `present_files` no longer report success when delivery fails. ([#4365])
- **uploads:** Lazy-load historical files via a `list_uploaded_files` tool
  instead of injecting the full manifest. ([#4174])
- **scheduler:** `scheduler.recursion_limit` in `config.yaml` sets the LangGraph
  super-step cap for scheduled runs (default 1000, matching the web UI's
  interactive budget, clamped by `max_recursion_limit`). ([#4848])
- **runtime:** Every tool call now carries a runtime-stamped, tamper-evident
  tool receipt, and a bounded receipt ledger is injected into the model
  context so agents can cite execution evidence in their reports. Enabled
  by default via the new `verification` config section. ([#4659])
- **subagents:** Subagent delegations are now verifiable, layering RFC #4651:
  every subagent's report contract requires citing tool receipts (e.g.
  `[r3 write_file]`) and attaching a verifiable handle to each deliverable,
  the lead agent cross-checks those citations against the subagent's actual
  execution record, and `acceptance_criteria` on a `task` delegation are
  checked deterministically parent-side (file existence/non-emptiness,
  recorded test-command exit status) with anything undecidable reported
  UNVERIFIED instead of silently passed. ([#5076], [#5090], [#5109])
- **clarification:** Human-input (clarification) cards support structured
  form fields, so an agent can request exactly the input it needs instead
  of free text only. ([#4406])
- **subagents:** Built-in subagents now receive the current-date context
  anchor, so delegated tasks involving relative dates behave like tasks the
  lead agent handles directly. ([#4797])
- **subagents:** A Settings page manages a deployment-level Subagent catalog
  (admin-managed worker definitions alongside built-in and `config.yaml`
  ones), and Custom Agents can restrict delegation to an explicit worker
  allowlist enforced at both prompt and execution time. ([#4887])
- **subagents:** Subagent concurrency is now governed by one process-wide
  capacity controller, and an opt-in `batch_task` tool runs large
  collections of independent items as durable, resumable SQL-backed batches
  with leases, bounded retries, pause/resume/cancel, and a chat panel for
  tracking progress. ([#4998])
- **agents:** The current-date context injected into lead- and subagent
  prompts honors the optional `DEER_FLOW_DATE_TIMEZONE` env var (IANA name,
  e.g. `Asia/Shanghai`), so users in non-UTC deployments are no longer told
  the wrong "today" around midnight; unset keeps server-local behavior.
  ([#5154])
- **subagents:** Delegated subagents can discover files uploaded in earlier
  turns: the parent run's validated `uploaded_files` boundary seeds the
  subagent's graph state, making `list_uploaded_files` eligible for normal
  tool-policy filtering (durable `batch_task` workers keep it disabled).
  ([#5170])
- **agents:** The read-before-write gate now elides the dead payload of a
  blocked `write_file` / `str_replace` call (`content`, `old_str`, `new_str`)
  from model-bound requests. A blocked call never ran and must be re-issued
  after a re-read, so the original arguments only cost context; stored history,
  receipts, and the run journal keep them. Blocked results are paired with call
  occurrences (tool-call ids may repeat across turns), and a request whose
  history was rewritten drops OpenAI `resp_` response ids so
  `use_previous_response_id` chaining cannot resume the original server-side
  history. Controlled by `read_before_write.elide_blocked_payloads` (default
  on) and `read_before_write.elide_min_chars` (default 2000). ([#5329])
- **agents:** `ToolOutputBudgetMiddleware` now also elides the `content` of a
  successful `write_file` call from model-bound requests once the same path was
  read or modified again later in the conversation. After a successful write
  the file on disk is the source of truth, and the read-before-write gate
  forces a `read_file` before the next modification, so the historical copy was
  redundant with that read and long report-writing runs carried every section
  twice. The newest `tool_output.keep_recent_writes` successful writes (default
  1) always stay visible, `str_replace` payloads are never touched, and stored
  history, receipts, and the run journal keep the original arguments.
  Controlled by `tool_output.elide_superseded_writes` (default on) and
  `tool_output.superseded_write_min_chars` (default 2000). ([#5374])
- **agents:** Custom Agent `config.yaml` accepts `memory_enabled: false` to run
  an agent as a stateless execution worker; omission defaults to `true`. The
  opt-out removes only that agent from the memory lifecycle — recalled-memory
  injection, passive capture, the `memory_search` / `memory_add` /
  `memory_update` / `memory_delete` tools, and tool-mode memory guidance are
  all suppressed, and both automatic summarization and manual `/compact` skip
  the durable memory flush. Switching an existing agent off clears only the
  frozen, server-tagged memory reminders from checkpoint state: date reminders,
  real user messages, and untagged lookalikes survive, and the global memory
  setting is unchanged for every other agent. ([#5167])
- **runtime:** `ToolProgressMiddleware`'s interventions become auditable in the
  durable run-event stream. A new `middleware:tool_progress` event is persisted
  for each effective `warn`, `block`, `recover`, or later-invocation `reset`
  phase transition; previously those replanning hints, tool-state promotions,
  and short-circuits disappeared into process logs, so a persisted run could
  not show whether the model recovered on its own or the runtime guard
  intervened. Only bounded decision metadata is recorded — status and recovery
  vocabularies derive from the canonical `tool_result_meta` schema, and tool
  arguments, result content, prompts, and content-derived hashes never enter
  the event. Subagent and other recorder attribution keys are server-owned at
  both the Gateway and embedded-worker boundaries, so a caller cannot forge
  durable attribution. Events appear only when ToolProgress is enabled, which
  remains off by default. ([#5214])
- **subagents:** Durable `batch_task` items accept the same optional
  `acceptance_criteria` that ordinary `task` delegations already take, so a
  batch worker can no longer claim a missing deliverable exists and still land
  as a succeeded item with no recorded check. Criteria are normalized before
  persistence (20 usable entries, 500 characters after neutralization; empty
  becomes `null`) and preserved across lease recovery, and a completed
  execution reuses the existing deterministic checker against owner-scoped
  thread files and recorded test-command evidence. Item queries and JSONL
  exports gain nullable `acceptance_criteria` and a separately validated
  `acceptance_verdict` (`holds`, `does not hold`, or `UNVERIFIED`): a completed
  item with a report, a missing CSV, and an unsupported quality claim stays
  `succeeded` with those three leaves and is not retried automatically. Items
  without criteria and legacy rows report no verdict. ([#5289])
- **subagents:** `task(context_mode="snapshot")` lets a delegation carry a
  dispatch-time copy of the retained parent conversation, instead of the
  delegated prompt alone. Snapshot mode captures conversation content and
  `summary_text` after delegation validation and before child setup, so a
  rejected delegation serializes nothing and later parent edits never reach the
  child. It is rendered as a separate historical `HumanMessage` ahead of the
  task, keeping plain text, text blocks, historical tool-call descriptions with
  their matching results, and serializable media input; unserializable media
  becomes an explicit omission notice, while parent system messages, hidden
  framework state (injected memory and todo state included), reasoning blocks,
  execution metadata, and pending tool calls are excluded. The child keeps its
  own role, model, tools, and skill restrictions, and parent tool frames never
  enter its execution history, so parent actions cannot populate child
  receipts, execution steps, or bash evidence. `context_mode="isolated"`
  remains the default, and `batch_task` items still require self-contained
  prompts. ([#5367])
- **context:** Opt-in task notes and compacted-history recall, gated by
  `task_continuity.enabled` (default `false`; the config schema gains the
  section with disabled defaults). Enabling it exposes `task_note`,
  `history_search`, and `history_read` to standard lead agents and
  `DeerFlowClient` under the existing authorization and skill policies, with
  both sync and async tool execution. `task_note` keeps short checkpointed
  notes of constraints, decisions, failed attempts, and next steps in a shared
  state channel that enforces notebook limits and report shape on every write,
  rendered as escaped historical data in the durable-context human message.
  Automatic and manual compaction additionally preserve bounded message and
  tool text — including genuine hidden clarification-card answers — into a
  user/thread-local SQLite FTS5 archive outside the sandbox mount, which
  `history_search` and `history_read` then query; malformed checkpoint metadata
  is reported as unavailable instead of aborting a model call or compaction,
  and a storage failure leaves ordinary compaction working. This is lexical
  recall within one task: it does not resume runs, replicate archives across
  hosts, or create cross-thread memory, and it adds no embedding dependency.
  ([#5382])
- **gateway:** Gateway runs no longer hardcode a recursion limit of 100. A
  deployment whose normal tasks need longer agent loops had to make every API
  caller supply a request-level override, and a caller that did not hit
  `GraphRecursionError` on otherwise valid work. A hot-reloaded top-level
  `recursion_limit` now supplies the default when a request omits it (100, for
  backward compatibility), an explicit request value still wins, an invalid
  request value falls back to the configured default, and `max_recursion_limit`
  caps both configured and client-supplied values. ([#5390])
- **gateway:** A Gateway run can be asked to read a specified earlier
  conversation. Opt-in `read_conversation` plus a `conversation_references` run
  field (up to three thread ids or same-origin chat URLs) grant the lead agent
  a model-facing read of a previous conversation while it continues the current
  task; ordinary message text never confers access, and the grant is bound to
  that run's references, the run's `runs:read` permission, and ownership of
  each source. Reads reuse the existing transcript pagination and visibility
  rules, returning bounded user and assistant text with source ids,
  continuation cursors, and truncation or unavailability notices while
  excluding hidden context, reasoning blocks, and raw tool results. The reader
  is never persisted in configuration and is released when the run ends, so
  resume and replay need the references again; bootstrap, subagent, and
  ordinary embedded paths do not receive it. Text is capped at 4,000 characters
  per message and 20,000 per page. ([#5399])
- **gateway:** Conversation references can be sent by SDK clients and detected
  by them. The LangGraph JS SDK's `RunsClient.stream` drops unknown top-level
  fields, so a browser client could not send the `conversation_references`
  field at all, and it had no way to tell whether the reader was enabled —
  leaving no way to hide an entry point where it was off. Run create, stream,
  and wait requests now accept `context.conversation_references` with the same
  bounds (at most three, each 1–2048 characters) and the same error locations,
  lifted into the canonical field before validation and removed from `context`
  so it never reaches the run context or the checkpointed configurable; sending
  both spellings returns 422, and a copy left in `body.config` still grants
  nothing. `GET /api/features` reports `conversation_references: {enabled,
  max_references}`, where `enabled` follows the configured tool list so a
  `config.yaml` change takes effect without a restart. ([#5463])
- **tools:** `list_uploaded_files` accepts optional `query` (a case-insensitive
  filename substring) and `extensions` (`"pdf"` or `".PDF"`, both meaning
  `.pdf`), and both filters run **before** the 20-file truncation that
  lazy-loading history already applied. Previously the cap hit the unfiltered
  mtime-sorted list, so "analyze those PDFs I uploaded before" in a thread full
  of newer screenshots pushed the PDFs into `omitted_summary` and left the
  agent with no path to hand `read_file`; `total_count`, `truncated`, and
  `omitted_summary` now describe the filtered set. Omitting both parameters
  keeps today's behavior, the two filters combine with AND, blank or invalid
  values count as no filter, and a filtered miss returns `No uploaded files
  matched the given filters.`. ([#5341])
- **agents:** Custom Agents showed their ASCII-only storage identifier in the
  gallery, chat header and welcome page, so an owner could not label an agent
  in Chinese or any other non-ASCII script. Each agent can now carry an
  optional `display_name` — whitespace-trimmed, at most 100 characters — on its
  config document and through the create/update/read/list APIs; omitting the
  field on an update preserves it, and `null` or a blank value clears it. The
  label is edited from the agent gallery's settings button, counts Unicode code
  points against a visible budget, and is rejected when it holds control
  characters, invisible formatting characters, or nothing but marks, separators
  or format characters — ordinary multilingual text and ZWJ emoji stay allowed.
  Paths, URLs, the runtime `agent_name`, ownership and React identity keep
  using the stable identifier, so nothing needs migrating, and an invalid
  stored value is ignored on read rather than breaking list/detail/bootstrap.
  ([#5324])

#### Memory

- **memory:** Memory consolidation synthesizes fragmented facts, and a staleness
  review prunes silently-outdated facts using LLM-assigned per-fact
  `expected_valid_days` / `staleFactsToExtend`. ([#3996], [#3860], [#4143])
- **memory:** Guaranteed injection of correction facts (with graceful fallback)
  so user corrections always reach the model. ([#3592])
- **memory:** Slim the pluggable `MemoryManager` interface for backend
  onboarding - new backends no longer implement unused abstract methods, and
  DeerMem-specific hook injection moves out of the shared factory. ([#4326])
- **memory:** Incremental agent-scoped Markdown fact storage isolates per-agent
  facts and updates a single fact without rewriting or reindexing the whole
  collection. ([#4279])
- **memory:** Memory message processing adds a conversation watermark,
  trivial-turn filtering, and a durable queue so extraction no longer re-feeds
  the full conversation every turn. ([#4447])
- **memory:** A built-in FTS5/BM25 retrieval adapter provides full-text
  search over stored memories without an external retrieval service.
  ([#4360])
- **memory:** New pluggable memory backends: OpenViking and mem0 over HTTP,
  plus Honcho as a user-model memory provider. ([#4509], [#4528], [#4730])
- **memory:** A hybrid fact eviction policy blends multiple signals when
  deciding which stored facts to drop as memory fills. ([#4789])
- **memory:** Opt-in write-side guard against storing paraphrases of a fact
  that is already remembered, so repeated extraction no longer consumes memory
  capacity and prompt tokens with duplicates. The write-side gate is
  `memory.backend_config.fact_dedup_enabled` (default `false`), with
  `memory.backend_config.fact_dedup_similarity_threshold` (default `0.7`, range
  `0.5`–`1.0`). Within the current user/agent scope a new same-category fact is
  compared against existing ones with bounded token-Jaccard similarity over
  Latin words and Chinese bigrams — a lexical heuristic, not semantic
  equivalence detection. A merge keeps the existing fact's id, content, and
  creation time, raises `confidence` to the higher of the two, and refreshes
  `source` only when confidence increased; the `facts_merged_dedup` counter
  records how many merges happened. Paired correction replacements bypass
  near-dedup, removal proposals exclude their own targets from matching, and no
  confirmation signal is fabricated — reinforcement still requires a genuine
  human message. ([#5254])

#### Skills

- **skills:** The built-in image-generation skill can use OpenAI-compatible
  Images APIs for generation and reference-image editing, with configurable
  endpoint, model, size, and output format. ([#5389])
- **skills:** Native SkillScan (phase 1) statically analyzes skill packages at
  load, and `describe_skill` enables deferred discovery so the model fetches a
  skill's schema on demand instead of loading all skills up front. ([#3033],
  [#3775])
- **skills:** Per-user custom skill isolation with sandbox mounting. ([#3889])
- **skills:** The skill list reopens after a skill is selected, so several
  skills can be attached in a row. ([#4639])
- **skills:** Install local `.skill` archives directly from the Skills
  settings page, reusing the existing per-user installer and security scan.
  ([#5039])
- **skills:** Podcast-generation Volcengine voices are configurable per
  speaker gender, with trimmed blank-safe defaults. ([#5156])
- **skills:** Custom skills can be exported from Settings, disabled ones
  included, so what you back up, move between installations, or send a teammate
  is the version actually installed rather than the original upload. A
  bilingual preview lists package size, paginated file paths, declared
  requirements, and actionable blockers, and the two new admin-only manifest
  and download endpoints bind that preview to a revision digest — a package
  changed in between returns `409` instead of a stale ZIP. Supporting files,
  empty directories, and normalized executable permissions survive the round
  trip, while links, special files, nonportable paths, nested skill roots, and
  executable binaries are rejected. Export copies raw saved files and is not a
  redaction step: it neither scans for secrets nor runs skill scripts, so
  credentials and account settings must still be configured separately.
  ([#5332])
- **skills:** Deferred skill discovery ranks candidates instead of matching the
  model's whole free-text query as one regular expression. With
  `skills.deferred_discovery: true` the agent sees only skill names and calls
  `describe_skill` to choose what to load, but a multi-term intent had to match
  contiguously: `chart visualization` never found `chart-visualization`, and
  `analyze Python` never found a skill described as "Analyze data with Python,
  pandas, jupyter" — so the agent could not load the matching workflow or its
  active tool policy. Lookup now normalizes Unicode, case, and name separators
  and scores candidates by literal intent-term coverage, with name matches
  outranking description-only matches at equal coverage and catalog order
  breaking ties so results stay reproducible; model-generated queries are
  bounded to 256 characters and 16 unique terms. `select:` exact selection and
  `+required` name filtering are unchanged, and no embeddings, model calls, or
  telemetry are involved. ([#5369])

#### Models & integrations

- **community:** New web search/fetch engines - GroundRoute, Crawl4AI
  (`web_fetch`), and a fastCRW provider - plus a Browserless `web_capture`
  screenshot tool and Brave `image_search`. ([#3675], [#3821], [#3585], [#3881],
  [#3866])
- **mcp:** Per-server `tool_call_timeout` for MCP tool calls, and routing hints
  that guide the model to the right server. ([#3843], [#4004])
- **mcp:** Add an official OpenViking `/mcp` example that exposes the native
  tool set through DeerFlow's generic MCP client. ([#4745])
- **community:** Agentic browser control as a first-class thread capability -
  Playwright-backed browser sessions the agent operates while the user observes
  or takes over from the workspace. ([#4187])
- **community:** Lark/Feishu CLI integration bundles the runtime install, the
  official `lark-*` skill pack, and an interactive auth flow so the integration
  is no longer environment-dependent. ([#3971])
- **integrations:** Lark/Feishu app credentials can be switched per user
  from Settings > Integrations: new App ID/Secret values are validated
  before anything is committed, and the previous OAuth token is revoked
  after a successful switch. ([#4703])
- **acp:** MiniMax Code (`mcode acp`) is supported and documented as a
  native external coding agent, and ACP thought chunks are no longer
  concatenated into tool results. ([#4846])
- **models:** A Z.AI GLM-5.3-Flash profile keeps thinking permanently enabled
  and stops generic reasoning-effort forwarding, since the model rejects
  disabled thinking and only accepts its own effort values. ([#5074])
- **community:** New web search providers - Serply (with news and scholar
  verticals) and Tencent Cloud WSA - plus native recency filters
  (day/week/month/year) shared across DDGS, Brave, Tavily, and SearXNG.
  ([#5023], [#5057], [#5099])
- **community:** New Sofya `web_search` and `web_fetch` provider - search
  results carry the content of each page, capped per result so a default
  search stays inline. ([#5239])
- **knowledge:** Opt-in read-only RAGFlow retrieval exposes a
  `knowledge_search(query)` agent tool over configured RAGFlow datasets, with
  a dataset-ID allowlist and credential/dataset-id redaction on error paths.
  ([#4955])
- **knowledge:** Opt-in read-only LightRAG retrieval is an alternative
  `knowledge_search(query)` provider for the same `knowledge` group —
  operators pick RAGFlow or LightRAG by which entry is configured. It queries
  LightRAG's structured `/query/data` endpoint (no LLM generation), formats
  the ranked chunks as citation-numbered text, redacts the optional
  `X-API-Key` on every model-visible path, and maps server error messages to
  actionable tool errors. ([#5209])
- **models:** A per-user favorites layer keeps frequently used models reachable
  without changing the selected or default one. The compact two-line model list
  is now an anchored dropdown in both the main chat and Side Chat, with an
  inline star per row; favorites sort into the first group without selecting a
  model or closing the picker, and persist per signed-in user with cross-tab
  synchronization and restoration of temporarily unavailable entries. The
  existing search field is removed as a deliberate simplification, with no
  separate management mode. ([#5441])
- **models:** Bounded concurrency does not bound request rate: several
  concurrent runs could still exhaust a provider's requests-per-minute
  allowance, and nothing paced the demand before dispatch, so a 429 was the
  first signal anything was wrong. A new optional `models[].request_admission`
  block admits model calls through a process-local queue, taking
  `requests_per_minute` (required), an optional `group` (defaults to the model
  config name), `max_wait_seconds` (default `300`) and `max_queue_size`
  (default `256`); at 60 RPM admissions land at least a second apart, and idle
  periods accumulate no burst credit. One bounded FIFO is shared across
  synchronous callers, independent asyncio loops and every model instance in an
  explicit group, whose policies must be identical — a conflicting setting
  fails construction and needs a restart. Cancellation and timeout drop a
  waiter without consuming an admission, and a full queue fails before
  dispatch. The limiter attaches through the LangChain `BaseChatModel` hook, so
  agent models, the invoke and stream paths and factory-created auxiliary
  models are all covered, and the factory strips the policy from provider
  kwargs and sets the exposed SDK `max_retries` to zero so retries cannot
  silently bypass the hook — existing agent middleware retries re-enter
  admission, while non-middleware callers lose SDK retries. Budgets are per
  process, so an operator must partition an account allowance across workers,
  replicas and other clients; the limiter counts requests, not tokens, and
  unconfigured models behave exactly as before. ([#5432])

#### MCP

- **mcp:** A durable task runtime for MCP: long-running tool tasks survive
  Gateway restarts through a durable driver, and their progress and
  completion notifications surface in the chat UI. ([#4665], [#4690],
  [#4833])
- **mcp:** Shared MCP servers can inject per-user credentials: a single
  server entry authenticates each DeerFlow user with their own header
  value, unmapped users are denied by default, and stored credentials are
  masked in Gateway API responses. ([#4868])
- **mcp:** Per-server `tool_name_prefix` option lets servers that already
  namespace their own tools keep their original tool names; the default
  behavior is unchanged. ([#4624])
- **mcp:** Settings > Tools can add, edit, and delete MCP servers through
  targeted Gateway endpoints, with a copy-paste JSON workflow that preserves
  advanced fields and masked secret placeholders. ([#5022])
- **mcp:** Shared HTTP/SSE servers can map request-scoped secrets to headers
  via `headers_from_context`: callers supply per-request values in
  `config.context.secrets`, the config stores only key names, and missing
  values deny by default. ([#5010])
- **mcp:** An optional `parallel-search` server entry
  (`https://search.parallel.ai/mcp`, HTTP, no auth by default) ships in
  `extensions_config.example.json`, disabled by default; enabling it exposes
  `parallel-search_web_search` and `parallel-search_web_fetch`, with optional
  Bearer authentication documented. ([#5028], [#5501])

#### Channels

- **channels:** Expose the IM `channel_user_id` to sandbox commands as
  `DEERFLOW_CHANNEL_USER_ID`. ([#3926])
- **channels:** Queue rapid same-thread messages and preserve topic-card
  previews across batches. ([#3988])
- **channels:** Inbound webhook deduplication moves to Postgres, so several
  Gateway pods can serve the same IM channel without double-processing
  events. ([#4210])
- **channels:** DingTalk inbound messages support file and image
  attachments. ([#4423])
- **channels:** New Buzz (Nostr) channel connector, including the frontend
  experience for the channel. ([#4649], [#4727])
- **channels:** `/agent list` and `/agent use <name>` IM commands let a
  conversation switch to the owner's Custom Agents: the selection is
  persisted in thread metadata (restored after restart) and wins over stale
  channel defaults, IM-created threads route through the same agent when
  opened in the web UI, and `/agent` is reserved across the slash-skill
  parser, frontend, and TUI so no skill can shadow the command. ([#5168])

#### Auth & guardrails

- **auth:** Generic OIDC/SSO authentication with Keycloak support. ([#3506])
- **guardrails:** Authenticated runtime context is exposed in `GuardrailRequest`,
  and security interventions are persisted as run events. ([#3665], [#3837])
- **auth:** "Keep me signed in" login option with a centralized session-cookie
  policy (persistent `Secure` cookies on HTTPS, session cookies on public HTTP).
  ([#4255])
- **auth:** Deployments can close local self-registration to restrict new
  accounts to SSO/OIDC provisioning. ([#4311])
- **authz:** Built-in RBAC authorization provider with a unified factory, plus
  tool-authorization enforcement at both assembly (tools removed before the
  model sees them) and runtime (denied calls blocked). ([#4260], [#4370])
- **authz:** Gateway route permissions are derived from the configured
  AuthorizationProvider rather than a fixed table. ([#4439])
- **authz:** Model authorization is enforced at Gateway routes and again in
  the agent runtime, and `sandbox:execute` is checked when a sandbox is
  acquired - users can no longer reach models or sandboxes they are not
  authorized for. ([#4540], [#4911])
- **authz:** `GET /auth/me` now surfaces the caller's effective route
  permissions (RFC #4063 Phase 4), read from the `AuthContext` the auth
  middleware already stamps on every authenticated request — no extra
  provider evaluations — so the frontend can hide actions the caller's role
  cannot perform. ([#5228])
- **authz:** A role denied `threads:delete` or `runs:cancel` was still shown
  the thread-row Delete menu item, the sidecar delete button and an enabled
  composer stop button, so the UI offered an action the Gateway's
  `@require_permission` guard would only reject. The frontend now consumes the
  effective permissions `GET /auth/me` reports and hides the delete
  affordances, and disables the stop button while streaming with an
  `aria-label`/`title` naming the permission boundary. Enforcement is unchanged
  — the Gateway guards remain the single decision point — and an absent, `null`
  or not-yet-loaded permission list is treated as permissive, so a mixed
  old-backend/new-frontend deploy can never hide an action the caller can still
  perform. ([#5294])

#### Sandbox & provisioner

- **sandbox:** New E2B and BoxLite (micro-VM) sandbox providers; BoxLite ships
  with a warm pool. ([#3883], [#3940], [#3951])
- **provisioner:** ClusterIP Services and scoped per-skill PVC mounts, plus a
  configurable sandbox container port. ([#4016], [#3928])
- **sandbox:** New cloud sandbox providers: Tenki and OpenSandbox.
  ([#4382], [#4877])
- **sandbox:** An optional lark-cli credential broker sidecar (K8s
  provisioner mode) keeps Lark app secrets and OAuth tokens out of the
  sandbox filesystem entirely - the sandbox sees only a shim that forwards
  commands to a loopback broker in the pod. Off by default. ([#4501])
- **sandbox:** The E2B mount-upload wall-clock deadline is configurable via
  `mount_upload_deadline_seconds` (default 120s). ([#4876])
- **sandbox:** An E2B sandbox carries a structured `MountUploadResult`
  (`truncated`, `reason`, upload totals) after creation — preserved across
  warm-pool reclaim within the process — so mount truncation by a resource
  limit is observable in code instead of only in Gateway logs. ([#4884])
- **sandbox:** Opt-in controlled egress for local Docker AIO sandboxes:
  `sandbox.network.mode` supports `isolated` (per-sandbox internal bridge
  with no outbound route) and `allowlist` (the same bridge plus a
  domain-allowlist HTTP(S) policy sidecar that resolves destinations itself
  and rejects IP literals and ECH); denied public domains can be approved
  through the Human Input card (temporary grant or allow-for-this-sandbox),
  non-interactive runs fail closed, and the sandbox API is no longer
  published directly in restricted modes. Requires Docker Engine 28+;
  `open` remains the default. ([#5152])

#### Extensions & plugins

- **extensions:** An out-of-tree Python extension system: extensions can
  contribute middleware, task-lifecycle and system-model observers, Gateway
  services, and HTTP routers, and are managed with `deerflow extensions`
  install/enable/disable/remove. ([#4636], [#4684], [#4780])
- **extensions:** Extensions can observe what the agent did - message
  provenance, middleware policy declarations, agent-assembly fingerprints,
  context-compaction records, guardrail decisions, and the MCP origin of a
  tool. `deerflow-extension-api` moves to 0.2.0; extensions written against
  0.1 are refused at startup with an install hint. ([#4863])
- **extensions:** An `extensions.middlewares` entry may be `{class, kwargs}` in
  addition to the existing `module.path:ClassName` string, and `kwargs` is
  passed to the constructor. Operator-managed middleware that needs a
  threshold, a header name, or any other argument no longer has to ship a
  hardcoded subclass just to set one value. String entries still construct with
  no arguments, blank class paths are rejected at config validation instead of
  failing later at agent creation, and unknown fields such as `apply_to` are
  refused. ([#5312])
- **extensions:** `deerflow extensions upgrade SOURCE` (also exposed as `make
  extension-upgrade SOURCE=...`) replaces a managed local snapshot, or re-pins
  a requirement already in the `extensions` group, and adopts the existing
  `plugins:` record so its private `config` and `required` survive. Moving to a
  newer pin used to mean `remove` then `install`, and `remove` deletes the
  whole record — secrets included — while an already-snapshotted local
  directory could not be reinstalled at all without editing the managed copy by
  hand. Plain `install` is unchanged and still refuses an existing local
  snapshot, upgrading a source that is not installed fails closed with an
  install hint, and a failed upgrade restores the previous snapshot even when a
  concurrent `pyproject.toml` / `uv.lock` edit blocks dependency-file rollback.
  ([#5347])
- **extensions:** A new optional `RunEvidenceReader` contract lets a Gateway
  extension learn what changed since it last looked, instead of reconciling
  whole threads: a host-owned monotonic cursor drives durable changed-run
  discovery, alongside scoped per-run event paging and authoritative status
  reads. Cursors are opaque, versioned, scope-bound, replay-safe, and durable
  for database-backed stores; paging orders by `(change_seq, run_id)` rather
  than inferring global order from thread-scoped event sequences or timestamps;
  progress snapshots and lease heartbeats do not advance the clock; and
  deletions emit no tombstone, so consumers poll status and treat a missing run
  as absent. Existing extensions are unaffected because
  `ExtensionRuntimeDeps.run_evidence_reader` defaults to `None`, and a store
  that cannot serve a page fails explicitly rather than reporting a
  misleadingly empty one. The production reader is app-scoped with global
  cross-user visibility for trusted operator extensions; it redacts event
  metadata but leaves content unchanged. ([#5405])

#### Persistence

- **persistence:** A custom PostgreSQL schema can be selected via
  `postgres_schema`; ORM, LangGraph checkpointer, and store tables are all
  created there, and the schema is created automatically at startup.
  ([#3442])

#### Frontend

- **frontend:** Branching support for assistant turns and side conversations for
  quoted follow-ups. ([#3950], [#3934])
- **frontend:** Regenerate the latest answer. ([#3637])
- **frontend:** Citation-sources evidence panel, workspace change review for
  agent runs, and a visualized `ask_clarification` card. ([#3907], [#3945],
  [#3956])
- **frontend:** Voice dictation, prompt-history recall with arrow keys, composer
  input polishing, and a "(thought for N seconds)" thinking-duration chip.
  ([#4036], [#3718], [#3986], [#3627])
- **frontend:** Feature-gate the agents UI behind the `agents_api` flag, and
  persist AI turn duration in backend and UI. ([#3769], [#3663])
- **frontend:** Render slash-skill activations as inline chips. ([#3981])
- **frontend:** Localized AI-assistance disclaimer. ([#4374])
- **frontend:** Pin recent chats. ([#4442])
- **frontend:** Validate `/goal` objective length in the composer. ([#4337])
- **frontend:** Real-time context window usage is shown as a conversation
  grows. ([#3183])
- **frontend:** The latest user turn can be edited and rerun in place.
  ([#4377])
- **frontend:** Replies can be typed and sent while a clarification card is
  pending. ([#4530])
- **suggestions:** The number of follow-up suggestions is configurable via
  `suggestions.max_suggestions` (default 3). ([#4533])
- **artifacts:** Text artifacts can be edited inline in the artifact panel.
  ([#4596])
- **artifacts:** Markdown artifacts open rendered in a new-window reader (with
  "View source" and "Download" fallbacks), and all files presented in a run
  can be downloaded as one zip archive derived from the run's delivery
  receipt. ([#5056], [#5117])
- **frontend:** Browser Live is available in Custom Agent chats. ([#4719])
- **frontend:** A conversation outline navigates long chats: past 5 user turns,
  a compact side menu lists the conversation's questions and jumps between
  them, tracking the current section. ([#5025])
- **frontend:** Scheduled tasks can be duplicated into an editable draft that
  carries over the configuration but not the run history. ([#5064])
- **threads:** Branched conversations get distinguishing titles
  (automatic `Title (2)`, `Title (3)` sibling numbering) and the
  recent-chats list shows parent-child lineage with tree connectors.
  ([#4983])
- **frontend:** Chats can be archived and restored: an Archive sidebar
  action with an Undo toast, Recent chats / Archived tabs above search, and
  per-chat restore controls; SQL and Memory stores apply the archive filter
  before pagination while messages, files, links, pin state, and the current
  URL are preserved. ([#5236])
- **projects:** Project workspaces organize chats (Projects MVP Phase 1): a
  sidebar Projects section with flat/grouped list modes, a project detail
  page with a paginated thread list, project-scoped new chats whose threads
  are pre-created with their project so a run can never land outside it,
  branch membership inheritance, move-between-projects, and project
  create/rename/archive/restore/delete. ([#5265])
- **artifacts:** Completed CSV/TSV artifacts preview as bounded tables (up to
  200 rows × 50 columns, 50 rows per page, sticky headers, optional
  first-row header) parsed off the main thread over the existing 1 MiB
  range loader — literal strings, leading zeros, and multiline quoted cells
  survive, long cells open in a copyable dialog, and source view remains
  one toggle away. ([#5284])
- **title:** Attachment-only first turns get a real title instead of the
  generic `New Conversation`, so file-first conversations are distinguishable
  and searchable. When the first turn carries one validated attachment, the
  cleaned filename becomes the local title; several attachments produce a count
  such as `2 files uploaded`; user-authored text still wins as the title
  source, and `New Conversation` remains the fallback when no valid filename is
  available. The local title is returned before the configured title-model
  path, so an attachment-only turn no longer pays for an LLM call. Filenames
  are read only from the `uploaded_files` state the upload middleware populated
  — client metadata is not trusted — and are sanitized: control characters and
  excess whitespace stripped, ordinary Unicode and percent signs preserved,
  long names truncated while retaining the extension. This supersedes the `New
  Conversation` fallback the earlier `<current_uploads>` title fix deliberately
  kept. ([#5304])
- **projects:** Projects MVP Phase 2 makes a project do its job rather than
  just name a folder. Project instructions — previously stored, editable, and
  read by nothing — now reach the model on every member-thread run as a
  bounded, user-role `<project>` block in that run's request only, never the
  system prompt or persisted history, with renames taking effect on the next
  run and oversized text rejected at write time rather than truncated. A
  per-project document shelf gains a Documents tab (upload, list with
  provenance, preview, download, move-to-trash, content-hash dedup) that the
  agent reads on demand through `list_project_documents` /
  `read_project_document` — registered only in project runs, text only — plus
  promotion in both directions: *Save to project* copies any thread file onto
  the shelf with provenance, and *Attach to thread* ingests a shelf document
  back into a conversation through the normal upload pipeline. A read-only
  conversation-files view aggregates member threads' uploads and outputs, and
  project deletion finally has a trash tier. ([#5443])
- **frontend:** Tool details for generic and MCP calls are inspectable in debug
  mode. Those steps previously showed only a label even though the browser
  already receives their inputs and results, making it hard to see what was
  passed between tools. Token Usage → Debug now carries a collapsed Tool
  details panel — including for calls with no token statistics — showing tool
  name, call ID, input, and either the original result or an explicit error,
  with copy actions and English/Chinese labels. Content is formatted only when
  expanded, and text length, nesting, and visited values are bounded so a large
  payload cannot stall the panel. ([#5309])
- **frontend:** Conversations can be referenced from the composer. A "Reference
  a conversation" button sits beside the attachment button, rendered only while
  `/api/features` reports the capability, and opens a picker over the same
  recent-conversation list the sidebar uses — never offering the current
  conversation, and capped at the reported `max_references` (3 today), where
  rows past the cap are disabled and selected ones stay clickable to remove.
  Attached conversations appear as removable chips in the composer and as
  read-only chips linking back to the source in the transcript. References are
  per message: not saved with a draft, cleared on send or thread change, and
  regenerating or editing a turn runs without them unless re-attached.
  ([#5465])
- **frontend:** Capability management moves out of Settings into a dedicated
  Capability Center in the workspace sidebar. MCP servers, connected-app
  authorization, and skills sat alongside account and appearance preferences,
  which made them hard to find and made the settings dialog hard to scan; they
  now live on one page, with Plugins combining MCP management and Lark/Feishu
  install and authorization, and Skills providing Built-in, Community, My
  skills, and All skills views with searchable cards, enable switches, file
  import, creation, and custom-skill export. Settings keeps its seven remaining
  sections, API contracts and permissions are unchanged, and the old
  `?settings=tools|integrations|skills` entry points are removed. ([#5468])

#### Observability & tooling

- **observability:** Trace-id correlation with enhanced logging and agent
  observability via Monocle. ([#3902], [#4024])
- **tooling:** A Hermes-like terminal workbench (`deerflow` CLI) backed by
  `DeerFlowClient`, plus a redacted community support-bundle generator. ([#3760],
  [#3886])
- **setup:** The setup wizard now asks whether OpenAI-compatible gateway models
  support thinking, and a Volcengine Coding Plan quick-setup path was added.
  ([#3428], [#4141])
- **tui:** `clear` command. ([#4306])
- **tui:** The TUI supports a transparent terminal background. ([#4631])
- **gateway:** New `GET /health/ready` readiness probe runs a bounded
  database `SELECT 1` and returns 503 while the database is unreachable
  (200 `not_configured` for the memory backend); `/health` stays pure
  liveness, and the production compose healthcheck now gates on readiness.
  ([#5166])
- **observability:** Deferred tool promotions — both routing-hint
  auto-promotion and explicit `tool_search` — persist as privacy-minimal
  `middleware:tool_promotion` run events (tool names, source, count, agent
  attribution; no queries, schemas, or results), observed only after
  skill-policy filtering so denied schemas are never reported as effective
  promotions. ([#5183])
- **client:** Context compaction stores its result in
  `ThreadState.summary_text`, outside `messages`, but the embedded client's
  `values` event selected only the title, messages and artifacts — so a
  consumer outside the Gateway, such as a benchmark runner, had no way to
  observe the summary through the public event stream. Every embedded `values`
  event now carries `summary_text`, `None` when absent, forwarding updates,
  repeats and clears as state snapshots. Message serialization, AI-delta
  deduplication, tool artifacts and usage accounting are unchanged, and no
  checkpoint internals are exposed. An initial snapshot can already contain a
  restored summary, so a changed value alone is not a causal compaction event.
  ([#5249])

### Changed

- **frontend performance:** Keep the public root and localized docs static;
  lazy-load closed workspace panels and editor/highlighter dependencies;
  incrementally derive streamed message state; bound streaming Markdown work;
  virtualize long message and chat lists; pause offscreen decorative effects;
  and enforce representative route JS/CSS budgets.
- **browser:** Negotiate binary Browser Live JPEG frames, retain the legacy
  JSON/base64 protocol for older clients, coalesce presentation to the latest
  frame per refresh, and revoke replaced object URLs.
- **artifacts:** Stream regular text artifacts with HTTP byte-range support and
  limit the initial Web UI preview to 1 MiB until the user explicitly loads the
  complete file.
- **sandbox:** The Helm chart now defaults per-sandbox Services to `ClusterIP`
  instead of `NodePort`, so the code-execution sandbox is reachable only inside
  the cluster via Service DNS (`http://sandbox-<id>-svc.<ns>.svc.cluster.local`)
  and is no longer bound on every node's interfaces - including the
  externally-reachable ones on GKE/EKS/AKS. Existing chart installs flip
  NodePort -> ClusterIP on upgrade. To preserve the old reachability (an
  external probe hitting the 30xxx port, or the Docker-Compose/hybrid path
  where the gateway is not in K8s), set `provisioner.sandboxServiceType: NodePort`
  (with `provisioner.nodeHost` if needed). The provisioner itself is unchanged
  (mode-aware since #4016). ([#4190])
- **skills:** An active restrictive skill must explicitly list `task` in
  `allowed-tools` to delegate to a subagent. Read-only discovery infrastructure
  (`tool_search` and `describe_skill`) remains available, but cannot grant schema
  visibility or execution for a denied business tool. ([#4098])
- **memory:** Pre-abstraction top-level `memory.*` DeerMem fields
  (`storage_path`, `max_facts`, `debounce_seconds`, `model_name`,
  `token_counting`, `staleness_*`, `consolidation_*`, ...) are **auto-migrated
  into `backend_config`** on load with a warning, so an upgrade does NOT silently
  revert customized settings to defaults (`model_name` ->
  `backend_config.model.model`). Move them under `memory.backend_config` in
  `config.yaml` to silence the warning. ([#4122])
- **memory:** Added `memory.mode` (`middleware` | `tool`); `tool` mode registers
  memory tools (`memory_search`/`add`/`update`/`delete`) the model calls directly
  instead of passive per-turn summarization. `manager_class` resolution is now
  fail-fast (raises `ValueError` on an unknown backend instead of silently
  falling back). ([#4023])
- **middleware:** Declarative layered middleware builder; `ThreadData` now runs
  before `Uploads`. ([#3809])
- **sandbox:** The host->virtual output-masking regex now has a single owner,
  eliminating duplicated pattern compilation. ([#4108])
- **docs:** `AGENTS.md` is now the source of truth for agent guidance, imported
  by `CLAUDE.md` via `@AGENTS.md`; module guides refreshed. ([#3770])
- **memory:** The OpenViking memory backend now uses the official OpenViking
  adapter; the old trusted-mode `auth_mode`/`account` fields are rejected in
  favor of a credential-bound USER API key. ([#4707])
- **gateway:** Threads created before the run-event journal have their
  checkpoint history backfilled as seed events before the first new run, so
  legacy conversations stay visible and correctly ordered after an upgrade.
  ([#4590])
- **agents:** Subagent delegation is now routed by net benefit: the lead agent
  defaults to direct execution unless parallel latency, specialist capability,
  or context isolation clearly pays off. ([#4384])

### Fixed

- **frontend:** Keep the `…` (kebab) menu on project chat rows inside the
  sidebar. In the sidebar's grouped Projects mode the indented nested menus
  kept `SidebarMenu`'s `w-full` while carrying an extra `ml-4`, so they were
  100% of the width plus 16px and their absolutely positioned `right-1`
  action landed past the sidebar edge — clipped on active-project rows and
  pushed out entirely on the doubly indented rows under the Archived group,
  while the flat chat list (the only unindented menu) was unaffected, which
  is why it slipped through. Both nested menus now use `w-auto`, so the
  block-level flex container fills the remaining width minus its margin. No
  behavior, data, or API change beyond the layout fix. ([#5682])
- **persistence:** Heal databases that silently skipped the run-change clock
  schema. `0023_run_change_seq` was inserted ahead of the already-shipped
  `0023_user_preferences` revision, so databases stamped at that revision (or
  later) treat it as an applied ancestor and never execute it — leaving the
  `run_change_clock` table and the `runs.change_seq` column permanently
  missing, and the first thread deletion (any run-store change-clock bump)
  fails with `no such table: run_change_clock`. The new
  `0025_repair_run_change_seq` revision re-applies the same guarded DDL on
  upgrade and no-ops on healthy shapes. `RunChangeClockRow` and
  `UserPreferenceRow` are also registered in the ORM model registry so
  `create_all` and autogenerate see every table through explicit imports
  instead of module side effects. ([#5517])
- **backend:** Validate pagination on the LangGraph-compatible
  `POST /api/assistants/search`. `limit` and `offset` were applied directly
  through Python slicing, so invalid values such as `offset: -1`, `limit: 0`,
  or an excessive limit returned `200` with misleading results instead of
  being rejected at the API boundary. `limit` is now required within the
  compatible range of 1–1000 and `offset` must be non-negative; invalid
  requests get `422`. ([#5506])
- **models:** Guard the Claude Code credential loader against a malformed
  `claudeAiOauth` container. `~/.claude/.credentials.json` can hold a
  syntactically valid JSON payload whose `claudeAiOauth` value is not an
  object — a `null` left by a partial export, a raw string, an array, a
  number — and the extractor called `.get` on it, raising `AttributeError`
  out of `ClaudeChatModel.model_post_init` and aborting model construction,
  the opposite of the loader's documented degrade-gracefully behavior (the
  sibling Codex loader already guarded the identical shape). A non-object
  top-level payload or `claudeAiOauth` value now logs at debug level and
  counts as "no credential from this source", so loading falls through to
  the next source and ultimately returns `None` when every source is
  unusable. ([#5494])
- **events:** Preserve the DB write-lock generation across thread deletion.
  `DbRunEventStore` serializes per-thread sequence assignment with an
  `asyncio.Lock`, and `delete_by_thread()` evicted that lock whenever
  `lock.locked()` was false — but `asyncio.Lock.release()` clears the locked
  state before a queued waiter resumes, so a deletion landing in that
  handoff window removed the registry entry while an admitted waiter still
  referenced the old lock. A later writer then created a new lock generation
  for the same thread, and two writers could proceed under different locks,
  violating the single-process serialization around `max(seq) + INSERT`.
  The per-thread registry is now weak, so an admitted holder/waiter keeps
  its lock generation discoverable until it drains, while a separate strong
  pin preserves the existing stable one-lock-per-thread behavior; deletion
  retires only the pin. ([#5462])
- **setup:** Honor a custom sandbox image in BOM-prefixed configs.
  `setup-sandbox.sh` matched `^sandbox:` against a first line still carrying
  its UTF-8 BOM, never matched, and silently chose and pulled the default
  image instead of the configured one, although the runtime YAML loader
  accepts the same configuration. The script now strips a UTF-8 BOM at the
  beginning of the first line before the image-selection pipeline, with no
  new runtime dependency. ([#5515])
- **gateway:** Keep the shutdown run drain alive across repeated
  cancellation. `_drain_inflight_runs()` shielded the `RunManager.shutdown()`
  task and then awaited it again, but a second `Task.cancel()` while that
  second shield was pending interrupted the helper itself, letting the
  lifespan continue unwinding while run tasks were still draining —
  reopening the exact resource-ordering hazard the drain exists to prevent:
  run tasks could still be writing checkpoints after checkpointer teardown
  began. The helper now keeps the already-started shutdown task strongly
  owned and repeatedly shields it until it reaches a terminal state,
  remembering the first caller cancellation and propagating it only after
  the bounded drain completes. Logging and error behavior on a failing
  drain are unchanged. ([#5487])
- **models:** Pair Codex invalid tool calls with their tool results. A Codex
  model that emits a `function_call` whose `arguments` are not valid JSON
  does not fail the turn: the call is parked on `invalid_tool_calls` and
  answered with a placeholder `ToolMessage` by `DanglingToolCallMiddleware`,
  so the model sees a recoverable tool error. But the Codex Responses
  serializer emitted input items for valid `tool_calls` only, so the
  placeholder reached the provider as a `function_call_output` whose
  `call_id` had no matching `function_call` in the same request, and the
  Responses API requires the pair — the exact case the middleware exists to
  recover from ended in a provider error instead of a retry. Chat
  Completions providers already replay invalid calls through LangChain's
  converter, and the OpenAI-compatible path had the same failure class
  repaired in the middleware; Codex requests now also replay
  `invalid_tool_calls` as `function_call` input items next to the valid
  ones. The valid-call path, the parse side, and the middleware are
  unchanged. ([#5509])
- **nginx:** Stop thread routes that wait on a model call from failing at 60
  seconds. The browser calls `/api/threads/*` directly, and that location had
  no `proxy_read_timeout`, so nginx's 60-second default applied while
  `/api/langgraph/` allowed 600. A slow `/compact` returned 504 while Gateway
  kept going and still saved the compaction, so the UI showed an error for
  work that had been applied, inviting a retry that compacts it again.
  `/suggestions` hit the same limit, and `/runs/wait` cancelled its run when
  nginx dropped the connection. The Docker, local, and Helm configs now allow
  600 seconds on that location. ([#5505])
- **middleware:** Stop loop detection from cutting off an agent that pages
  through a file. `read_file` calls were keyed by 200-line buckets, so every
  read shorter than a bucket collapsed onto its neighbours: five sequential
  40-line reads hashed identically and tripped the hard stop, ending the run
  with a forced final answer and `stop_reason=loop_capped` — on exactly the
  ranged reads `read_file`'s own truncation notice tells the model to make. The
  key now uses the exact line window, with an omitted `end_line` kept
  open-ended so a bare read and an explicit `start_line=1` still share one key.
  Repeating a single range is still caught at the same threshold, and a read
  loop that varies its bounds remains covered by the per-tool frequency layer.
  ([#5486])
- **subagents:** Give `max_turns` the meaning operators read it as. It was
  handed to LangGraph as `recursion_limit`, which counts super-steps — one per
  graph node — while `create_agent` compiles a node for every middleware
  lifecycle hook, so one turn cost seven to eight steps through the subagent
  chain and the built-in `general-purpose` agent's `max_turns=150` bought about
  18 tool-using turns before failing as `turn_capped`. Every middleware added
  to the chain shrank the effective budget again. The executor now scales the
  configured turn count by the per-turn node count of the chain it actually
  assembled, so raising `max_turns` buys the turns it names. No config keys
  changed; existing `max_turns` values now grant their full budget, which can
  make a previously truncated subagent run longer, bounded as before by
  `subagents.timeout_seconds` and `subagents.token_budget`. ([#5485])
- **scheduler:** Enforce the global `max_concurrent_runs` budget on SQLite,
  which previously only held on Postgres. Claiming a queued occurrence counts
  the executing rows and then promotes one row to `launching`, and Postgres
  serializes that pair with an advisory lock. SQLite's deferred transaction
  reserved the writer only at the promoting UPDATE, so claimants racing on
  distinct rows — a manual trigger overlapping the poller, or a second Gateway
  process sharing the database file — all read the same stale count, all passed
  the budget check, and the configured cap was exceeded. ([#5469])
- **sandbox:** Stop AIO's `glob` from reporting an exactly-full result as
  truncated. Its `include_dirs` branch returned as soon as it had collected
  `max_results` matches, so a listing that held exactly that many — and no more
  — came back flagged as cut off, and the tool told the model the result was
  incomplete. That branch already holds the whole listing, so it now looks one
  match past the cap before deciding, matching the sibling `include_dirs=False`
  branch, which has always decided from the full list. This concerns the
  filtered-match cap only: the raw-output cap `parse_remote_search_output` owns
  is a separate limit with its own one-line-past accounting, and the other
  providers' filtered-match cap is unchanged. ([#5449])
- **middleware:** Stop a guard that removes tool calls from breaking every later
  turn of a Claude or OpenAI Responses thread. Token-budget and loop-detection
  hard stops, subagent-limit truncation, and safety suppression cleared
  `tool_calls` but left the provider's own tool-call blocks in the message
  content. Anthropic and the Responses API resend those blocks, so the next
  request carried a tool call with no result and the provider rejected it, and
  a hard stop saved to the checkpoint kept failing on each new message. All
  guards now remove the matching content blocks through one shared helper,
  which also keeps a Responses call that clarification retains. ([#5447])
- **sandbox:** Stop remote `glob` and `grep` from reporting "no matches" when
  their output was cut off. BoxLite, Tenki, E2B, and OpenSandbox cap the
  search's raw output and then filter it in Python (ignored directories such as
  `node_modules`, the pattern or `glob` scope), but they reported `truncated`
  only when `max_results` was reached. When the capped lines were all filtered
  out, a search with real matches past the cap came back empty and complete.
  The search now passes one line beyond its cap so a cut-off result is reported
  as truncated, and the `glob` and `grep` tools say an empty truncated result is
  incomplete instead of "No matches found". ([#5427])
- **sandbox:** Stop host paths reaching the model when output joins them with
  `:`, as `$PATH` and `$PYTHONPATH` do. The matched path ran on through the
  rest of the list, so every later entry under the same root was left
  unmasked; extra masking passes recovered one entry each, which hid the leak
  for short lists. Masking now ends a matched path at `:`. A symlink inside a
  mount whose target lies outside every mount is now shown by its mount path
  instead of the target's host path in command output and `glob` results. ([#5418])
- **sandbox:** Stop BoxLite `grep` from ignoring the directory part of `glob`.
  It compared only file names, so `src/*.js` matched every `.js` file in the
  tree. The glob now applies to the path relative to the search root, the same
  scope as `glob()` and the other providers. ([#5419])
- **models:** Stop every Claude model after the first from losing its
  credential when the Claude Code OAuth token is handed off through
  `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`. Every `ClaudeChatModel` instance
  loaded credentials again, but a descriptor can be drained only once, so the
  title, summarization, and subagent models — and every later run — had no
  credential and failed with `TypeError: Could not resolve authentication
  method`. The token is now read once per process and reused. ([#5411])
- **models:** Stop the lead agent from failing to build whenever a model with
  `supports_reasoning_effort: true` also gets a `reasoning_effort` from its
  profile — at the top level, in `when_thinking_enabled` or
  `when_thinking_disabled`, or from the `extra_body.thinking` disable path. The
  regular lead-agent build forwards the requested effort even when unset, so
  the key reached the provider constructor twice and raised `TypeError: got
  multiple values for keyword argument 'reasoning_effort'`. The requested value now
  layers like per-agent `model_settings`: it replaces a top-level profile
  value, an unset request keeps that value, and the thinking-mode settings still
  decide the final one. Codex keeps its own level check. ([#5403])
- **runtime:** Stop a keyed run retry from failing with 500 on the SQL run
  store. HTTP admissions do not pass a `user_id`; the SQL store stamps the
  request user on the row, but the process-local run record kept `None`. A
  retry with the same `Idempotency-Key` that reached another Gateway worker, or
  the same worker after the finished run was cleaned up, compared the two
  owners, took its own run for another user's, and raised. The same mismatch
  dropped HTTP runs from owner-scoped history reads and skipped the MCP
  `background_tasks` projection for them, so `values` events for these runs now
  include `background_tasks`. `RunManager` now resolves an omitted owner from
  the request user the way the SQL store does, so every store records the same
  owner. ([#5401])
- **runtime:** Stop a cross-worker idempotent run reuse from permanently
  blocking the thread on the reusing worker. The reuse registered the hydrated
  store row as a local run record, but only the owning worker finalizes and
  cleans up its records, so the copy kept its admission-time `pending`/`running`
  status forever: every later `reject` admission for that thread on the worker
  returned 409 until a restart, its run reads kept reporting the stale status,
  and orphan reconciliation skipped the run if the owner crashed. A cancel sent
  to that worker also took the local-owner path and marked the owner's
  still-running row `interrupted`. The reusing worker now returns a detached
  store-only handle instead, so cancel follows the non-owner contract.
  ([#5393])
- **skills:** Stop writing resolved secrets into `extensions_config.json` when a
  skill is toggled. The Gateway skill toggle and `DeerFlowClient.update_skill`
  loaded the file through `ExtensionsConfig.from_file()`, which replaces every
  `$VAR` value with the environment value, and wrote that model back — so a
  `"$GITHUB_TOKEN"` reference was persisted as the plaintext token and an unset
  variable was permanently replaced with `""`. `DeerFlowClient.update_mcp_config`
  did the same for every key other than `mcpServers`. These writers now edit the
  raw on-disk JSON and validate the candidate the way the runtime loads it, so
  placeholders and hand-written structure survive; the MCP router shares the same
  raw loader. Files rewritten by an earlier toggle keep their plaintext values:
  restore the `$VAR` references and rotate the exposed credentials. ([#5357])
- **gateway:** Honor `disable_clarification` and `github_token` only for
  internally-authenticated callers, the way `non_interactive` already was.
  Both keys were forwarded from `body.context` regardless of the caller and
  were not scrubbed from the free-form `body.config` that the run config
  copies verbatim, so any session or PAT caller could set them.
  `disable_clarification` is the stronger of the two: `ClarificationMiddleware`
  answers every clarification — `risk_confirmation` included — with "proceed
  without asking", and `SandboxMiddleware` reads it as the same
  non-interactive signal as `non_interactive`. `github_token` reached
  `runtime.context`, where the bash tool exports it as `GH_TOKEN`/`GITHUB_TOKEN`,
  and a copy smuggled through `body.config['configurable']` was persisted in
  the checkpoint store. The scheduler, IM channels, and the GitHub webhook
  channel authenticate over the internal request channel and are unaffected.
  ([#5338])
- **artifacts:** Keep `PUT /api/threads/{id}/artifacts/{path}` confined to
  `/mnt/user-data/outputs`. The outputs-only guard was a string-prefix check on
  the raw path, so a percent-encoded `..` (`outputs/%2e%2e/uploads/x.txt`) —
  which nginx forwards untouched and Starlette decodes — passed it, and the
  resolver only confines to `user-data/`, letting a caller overwrite a sibling
  upload or workspace file in their own thread. Dot segments are now collapsed
  before the prefix check, and the resolved host path is re-checked against the
  resolved outputs root so a symlink planted inside `outputs/` cannot redirect
  the write either. The rule now lives in one shared helper that IM-channel
  attachment delivery uses as well, so the two copies cannot drift. ([#5321])
- **gateway:** Stop persisting a caller-supplied `deerflow_trace_id` on the run
  record. `body.metadata` reaches both the live run config, which the run
  worker restamps, and the run record echoed verbatim by the runs API; only the
  first was covered, so a client could make the most durable surface of a run
  disagree with the `X-Trace-Id` and the log lines from the same request. The
  id is now stamped once at the trust boundary, `config.context` is closed off
  the same way, and a thread's own metadata is no longer seeded with the
  run-scoped id of whichever run created it. ([#5119])
- **gateway:** Expose `X-Trace-Id` in `Access-Control-Expose-Headers`. It is not
  CORS-safelisted, so split-origin browser clients — the ones that cannot read
  the Gateway's logs either — could not read the correlation id they are meant
  to quote in a bug report. ([#5119])
- **gateway:** Keep `X-Trace-Id` on unhandled-exception 500s. Starlette's
  `ServerErrorMiddleware` emits those through the raw send outside every user
  middleware, so the 500 for a server bug — the response most in need of
  correlation — was the only one shipped without the id. `TraceMiddleware` now
  sends its own 500 carrying the header before re-raising; the server's
  exception logging is untouched and mid-stream failures propagate unchanged.
  This fallback is emitted outside `CORSMiddleware` and stays CORS-opaque, so
  split-origin browser clients cannot read the id on this one response — same
  as the `ServerErrorMiddleware` 500 it replaces. ([#5119])
- **gateway:** Strip a forged `deerflow_trace_id` from the persisted request
  echo. `body.config` is stored verbatim as `runs.kwargs_json` and served back
  by the runs API, so a forged id in `config.metadata` or `config.context`
  survived on that one surface while every other carried the real id.
  `redact_config_secrets` now drops the key from both containers, and
  `build_run_config` merges run metadata onto a copy so the server-stamped id
  can no longer be written through into the caller's request body. ([#5119])
- **artifacts:** Keep explicit full-file loading scoped to the source thread, so a same-path artifact in another conversation keeps its 1 MiB preview. ([#4634])
- **sandbox:** `SandboxAuditMiddleware` no longer blocks ordinary command
  substitution that only captures output. The rule now judges *position* instead
  of matching any `$(`: `x=$(curl url)`, `echo $(curl url)`, an argument, and a
  `for` word list all run normally, while a substitution in command position
  (`$(curl url)`, after a `|`/`&&`/`;`, behind leading assignments or an
  `env`/`nohup`/`time` style wrapper, or as an `eval`/`source` argument) still
  blocks because it executes fetched content. An interpreter's code-string flag
  (`bash -c`, `python -c`, `perl -e`, `node -p`, `php -r`, and the `<<<`
  here-string) is treated as an execution context wherever it appears, so
  `bash -c "$(curl url)"` blocks; `source <(curl url)` and the backtick spelling
  of `eval`/`source` now block too, neither of which was detected before. An
  unquoted newline separates statements like `;`, so `echo hi` followed by a
  new line starting `$(curl url)` blocks as well, while heredoc bodies are
  consumed as data — writing a file whose content happens to start a line with
  `$(curl url)` is not a command.
  Variable expansions whose name merely starts with a risky executable
  (`$shell`, `$bashrc`, `$python_version`) and lookalike binaries
  (`shellcheck`, `shasum`) are no longer false positives.
  ([#4611], [#4623])
- **mcp:** Isolate Settings > Tools enable/disable updates to one MCP server, so
  an unrelated disallowed stdio command no longer blocks every switch; allow
  disabling a disallowed target while still rejecting its re-enable, preserve
  the raw extensions config, honor the MCP-spec `transport` alias when enabling
  SSE/HTTP servers, surface backend validation details in the UI, and atomically
  replace the shared config for MCP, skill, and embedded-client updates so
  interrupted writes cannot leave it truncated.
  ([#4574], [#4577])
- **runtime:** Thread metadata now switches to `running` only after the run passes
  the startup barrier, so pending-cancelled runs no longer briefly project
  `running`; clients may observe the prior thread status during worker startup.
  ([#4450])
- **runtime:** Re-check orphan candidates through an atomic, lease-aware takeover
  claim so a successful heartbeat after the scan keeps the run active and only
  one reconciler reports recovery. ([#4424], [#4434])
- **skills:** Apply `allowed-tools` only to slash-activated or actually loaded
  lead-agent skills, preventing passive enabled skills and evaluation fixtures
  from removing MCP, web, file, and delegation tools from every run. ([#4095],
  [#4098], [#4192])
- **models:** Honor `api_base` on every `BaseChatOpenAI` subclass (`VllmChatModel`,
  `MindIEChatModel`, `PatchedChatMiMo`, `PatchedChatStepFun`, `PatchedChatMiniMax`),
  not just `ChatOpenAI` / `PatchedChatOpenAI`. Those five previously dropped the
  configured endpoint silently and then failed every request with an opaque
  `unexpected keyword argument 'api_base'`; the unknown-config-key warning was
  disabled for them as well. Both now gate on `issubclass(BaseChatOpenAI)`.
  ([#4146])
- **agents:** Coalesce `SystemMessage`s before the LLM request; ensure a visible
  response after tool runs; avoid a default LLM title call before stream end;
  reserve ellipsis room so the local title respects `max_chars`; and snap the
  tool-output tail forward so fallback truncation respects `max_chars`. ([#3711],
  [#4033], [#3885], [#4052], [#4017])
- **agents:** Skip dateless reminders in the dynamic-context date scan; load
  `SOUL.md` from agent dirs without `config.yaml`; require `config.yaml` in
  `update_agent`'s legacy-agent guard; and refuse empty `SOUL.md` updates.
  ([#3685], [#4136], [#4166], [#4219])
- **middleware:** Window the loop-detection tool-frequency counter so long runs
  no longer false-trip; prevent the title middleware from streaming tokens;
  fix positional fallback consuming an unrelated todo when the same-content list
  is exhausted; acquire the token-budget lock across `_apply`, `before_agent`,
  `_clear_run_state`, and `_drain_pending_warnings`; drop orphan `ToolMessage`s
  so strict providers don't 400; sanitize invalid tool-call arguments; and
  recover from empty tool-call names and malformed tool-call ids in dangling
  repair. ([#4072], [#3566], [#3709], [#3714], [#4080], [#4193], [#4008],
  [#4246])
- **subagents:** Inherit `LoopDetectionMiddleware` and summarization middleware
  so tool loops break and steps are captured; surface the turn-budget cap as
  `MAX_TURNS_REACHED` with a partial result; unify guardrail caps on the additive
  `stop_reason` + `token_budget`; inject durable context before compaction;
  preserve the parent checkpoint namespace; prohibit the `task` tool in the
  general-purpose system prompt; re-buffer subagent events on flush failure to
  avoid losing steps; and fix the lost `loop_capped` stop reason when a
  subagent's `run_id` is `None`. ([#3931], [#4009], [#3949], [#3980], [#4040],
  [#4215], [#4161], [#4082], [#4059])
- **memory:** Harden against null/empty edge cases - skip whitespace-only facts;
  coerce null `confidence` / `source.confidence` in updates, searches, and the
  three remaining raw reads; treat explicit `null` `backend_config` values as
  omitted; fix `KeyError` / `UnboundLocalError` when a fact has no id or the
  facts list is empty; stop the busy-spin in the debounced update queue; and
  flush the memory queue on graceful shutdown to prevent loss. ([#3719], [#4074],
  [#4076], [#4034], [#4217], [#3993], [#3992], [#4073], [#4181])
- **runs:** Close multi-worker ownership gaps in run atomicity; fail-stop local
  execution when lease renewal cannot be confirmed before its deadline and
  fence late completion writes after peer takeover; degrade cancel to lease
  takeover for multi-worker; keep `create_thread` idempotent when the insert
  loses a race; read `stop_reason` from runtime context; and persist run duration
  in checkpoints for history reads. ([#4003], [#4064], [#4414], [#3800], [#4188],
  [#4118], [#4431])
- **runtime:** Serialize SQLite event-store writes to prevent per-thread
  sequence collisions; skip hidden human messages in the journal; and drop the
  silent delta-discard in `_merge_stream_text`. ([#4077], [#3698], [#4085])
- **gateway:** Attach thread-message feedback by real `event_type`; offload
  blocking filesystem IO in artifact serving, gateway uploads, and the Discord
  channel; limit the uploaded-file context manifest; and live-tail malformed
  Redis reconnect ids. ([#3651], [#3551], [#3935], [#3927], [#3917], [#4012])
- **uploads:** Claim the converted-Markdown companion filename before writing
  it, so two convertible uploads sharing a stem (or a convertible plus a
  same-stem `.md` upload) no longer silently clobber each other within one
  request. When `uploads.auto_convert_documents` is on, the companion `.md` now
  gets a unique name (e.g. `a_1.md`); `POST /threads/{id}/uploads` and
  `DeerFlowClient.upload_files` both report the actual name in `markdown_file`.
  ([#4288])
- **config:** Coerce null object config sections to their defaults; honor the
  unified database configuration in the store and sync checkpointer; and have
  legacy DB backfill create missing `Index` objects on existing tables. ([#3573],
  [#3904], [#3994], [#4090])
- **models:** Apply the `stream_chunk_timeout` default to all `BaseChatOpenAI`
  subclasses; and normalize `api_base` -> `base_url` for `ChatOpenAI` with a
  warning on unknown config keys. ([#4102], [#3790])
- **mcp:** Isolate tool-discovery failures per server; synchronize the
  session-pool singleton lifecycle; invalidate the tools cache on config content
  + path (not just newer mtime); validate MCP tool names at load so deferred
  prompts stay inert; and route tools by source server, not name prefix. ([#3772],
  [#3797], [#4124], [#4154], [#3812])
- **skills:** Activate a slash skill once per run, not per model call; close the
  skill-install security-scan coverage gap; recognize fully deleted skill
  packages in review CI and remaining `requests` / `httpx` methods as network
  sinks in SkillScan; reuse the resolved app config in the no-arg skills prompt
  section; and reload mounted skills without restarting the Gateway. ([#4103],
  [#3924], [#4169], [#4130], [#4160], [#4264])
- **sandbox:** Guard the reverse path-translation and output-masking regexes
  with segment boundaries; handle one-sided line ranges and empty files in
  `read_file` / `str_replace`; align the AIO bash working directory; use
  `os.sep` in the reverse-resolve containment check on Windows; normalize
  Windows backslash paths in bash commands; stop `glob` / `grep` / `ls` from
  surfacing disabled skills' files; and allow valid heredoc commands in the
  sandbox audit. ([#4035], [#4053], [#4078], [#4079], [#4051], [#4058], [#3869],
  [#4096], [#3786])
- **sandbox:** Synchronize the sandbox provider singleton lifecycle (with
  concurrency regression tests) and keep k8s calls off the event loop in the
  provisioner. ([#3730], [#3941])
- **sandbox:** Align sandbox artifact mounts with the channel user; fix
  local-dev (`make dev`) on non-root / NFS hosts; reap macOS nginx processes on
  stop; and fix production Postgres UV-extras detection in Docker. ([#3729],
  [#3590], [#3828], [#3897])
- **channels:** Validate the channel provider before resolving its config;
  dedupe GitHub webhook redeliveries and drop redundant GitHub review-comment
  webhook fan-out; scope the slash-skill whitelist check to the run's owner;
  batch Feishu file messages into one thread and dispatch Feishu group commands
  prefixed with a bot @mention; accept leading @mentions before `/connect` bind
  codes and don't treat a bare "connect" as a bind command; stop Feishu from
  creating thread topics and throttle card updates; let the UI runtime channel
  config win over `config.yaml`; fix `require_mention` gating on
  whitespace-only `bot_login` / `mention_login`; guard null quote fields in
  WeCom; and key inbound dedupe on chat-scoped workspaces so Telegram, Feishu,
  WeChat and DingTalk redeliveries stop re-running the agent on a default
  (unbound) configuration, releasing the dedupe key on transient failures so a
  redelivery can still recover. ([#4100], [#4104], [#4131], [#4129], [#3753],
  [#4229], [#4222], [#4251], [#3810], [#3674], [#4055], [#4069], [#4287])
- **frontend:** Preserve messages and durable context across summarization;
  preserve artifacts and stabilize artifact paths during streaming; resolve
  relative artifact image paths; retain presented artifacts in the header
  dropdown; keep orphan tool messages visible; show assistant text during tool
  steps; reset new chat on client-side navigation; prevent stream cancellation
  on concurrent submit; fix stale-run reconnect and cancel handling; fix chat
  math rendering, single-tilde markdown, double reasoning rendering, UTF-16
  markdown binary classification, and `<memory>` tags in Streamdown; make
  recent-chat rows fully clickable; validate attachment limits before upload and
  fix uploaded-file metadata in message copy; fix mobile workspace and
  accessibility blockers, the card tool-message bug, and side-chat toolbar /
  panel-button behavior; block unresolved suggestion-template placeholders;
  refresh notification permissions; show the branch action only for completed
  turns; enable regenerate in custom agent chats; and generate a fallback title
  for interrupted first-turn runs. ([#3826], [#3791], [#4094], [#4038], [#3854],
  [#3880], [#4114], [#3673], [#3878], [#3908], [#3557], [#4245], [#3870], [#3966],
  [#4209], [#3733], [#3900], [#3944], [#3740], [#3976], [#3959], [#3961], [#3764],
  [#3768], [#4147], [#3967], [#3874], [#3644])
- **tui:** Interrupt an active run before `/quit` exits. ([#4235])
- **harness:** Don't flag the outline as truncated at exactly `MAX_OUTLINE_ENTRIES`
  headings. ([#3856])
- **tracing:** Attach Langfuse trace metadata to the goal evaluator. ([#4202])
- **context:** Resolve the context-compress bug. ([#4065])
- **threaddata:** Fix `AttributeError` when `runtime.context` is `None`. ([#3989])
- **goal:** Stop `continuation_count` double-bump during stand-down. ([#4199])
- **circuit-breaker:** Stop wedging after a non-retriable half-open probe. ([#3991])
- **github:** Match `allow_authors` logins case-insensitively. ([#4218])
- **community:** `image_search` now returns the full-resolution image URL. ([#3990])
- **skills:** Offload blocking filesystem IO in the skill-history endpoint.
  ([#3563])
- **skills:** Don't treat a lazily evaluated PEP 695 type alias as a network
  sink in SkillScan. ([#4315])
- **skills:** Bound skill-archive extraction by member count, not only by
  uncompressed size. `safe_extract_skill_archive()` is the always-on path every
  `.skill` install goes through; it capped total uncompressed bytes as a
  zip-bomb-by-size defence but had no member limit, so a small archive holding
  tens of thousands of tiny entries extracted cleanly.
  `scan_archive_preflight()` already capped entries at 4096, but only ran when
  the optional `skill_scan.enabled` kill switch was on, leaving the default path
  uncapped.
  Extraction now enforces the same 4096-member cap unconditionally, raising a
  plain `ValueError`; where SkillScan is enabled the structured
  `package-too-many-members` finding still surfaces first. ([#4241])
- **tracing:** Resolve the Langfuse trace user from runtime context. ([#3794])
- **guardrails:** Propagate internal owner attribution into the guardrail
  context. ([#3839])
- **subagents:** Clamp the subagent limit consistently with
  `MIN_SUBAGENT_LIMIT`. ([#4081])
- **subagents:** Load user-scoped skills. ([#4356])
- **mcp:** Per-server fail-soft OAuth priming, and persist rotated refresh
  tokens. ([#4084])
- **mcp:** Ignore malformed path-like text. ([#4456])
- **auth:** Resolve email accounts case-insensitively. ([#4101])
- **auth:** Recover from setup-status timeouts. ([#4371])
- **scheduler:** Close a dispatch race that could launch two runs for one
  scheduled task. ([#4105])
- **channels:** Buffer and drain GitHub comments queued during a busy run.
  ([#4133])
- **channels:** Escape Slack reserved characters before mrkdwn conversion.
  ([#4197])
- **channels:** Check `response.success()` on Feishu card/reaction SDK calls.
  ([#4234])
- **channels:** Drop inbound DingTalk messages that carry no conversation
  identity. ([#4316])
- **channels:** Receive inbound Telegram attachments. ([#4392])
- **memory:** Consolidated facts inherit `expected_valid_days` from their
  sources. ([#4225])
- **config:** Sync `_memory_config` with AppConfig auto-reload. ([#4208])
- **postgres:** Harden the async engine with `pool_recycle` and
  `command_timeout` to stop stale-connection 504s. ([#4230])
- **harness:** Add a timeout to `invoke_acp_agent` to prevent indefinite hangs.
  ([#4238])
- **community:** Surface the target-page error status in `web_fetch`
  (Browserless). ([#4239])
- **sandbox:** Widen the BoxLite/AIO tenant hash and verify identity on reclaim.
  ([#4171])
- **sandbox:** Make an empty `old_str` a no-op in `str_replace` on any file.
  ([#4256])
- **sandbox:** Serialize E2B release transitions. ([#4355])
- **sandbox:** Bound E2B output-synchronization resources. ([#4364])
- **sandbox:** Unwrap `Overwrite`-wrapped sandbox state in `after_agent`.
  ([#4381])
- **sandbox:** Bypass proxies for local AIO traffic. ([#4444])
- **models:** Surface length-capped model responses instead of dropping them.
  ([#4309])
- **streaming:** Keep large file generation responsive. ([#4354])
- **streaming:** Expose custom events to `astream_events`. ([#4403])
- **streaming:** Signal replay history gaps. ([#4426])
- **summarization:** Summarize with the run model and fall back on
  summary-provider failure. ([#4361])
- **runtime:** Remove transient image context after model calls. ([#4267])
- **runtime:** Stop subgraph stream frames from impersonating root frames.
  ([#4407])
- **runtime:** Reject unsupported run options and stream modes. ([#4430])
- **runtime:** Serialize checkpoint writes with active runs, linearize
  delta-mode checkpoint resume, and accept the SDK's default
  `stream_resumable=false` to avoid resume races. ([#4437], [#4460], [#4468])
- **checkpoint:** Unwrap `Overwrite` first writes into empty channels. ([#4383])
- **nginx:** Allow long chat prompts through `/api/langgraph/` without a raw
  500. ([#4277])
- **gateway:** Prefer `X-Trace-Id` over `metadata.deerflow_trace_id` when the
  header is set. ([#4283])
- **gateway:** Seed branch run-events so inherited history survives forking.
  ([#4385])
- **gateway:** Scope branch-history seed run ids per inherited turn. ([#4459])
- **frontend:** Harden artifact and markdown rendering. ([#4117])
- **frontend:** Classify a symlink replacing a file distinctly from deleted in
  workspace-change review. ([#4170])
- **frontend:** Offload blocking filesystem IO in the workspace-change
  text-cache lifecycle. ([#4268])
- **frontend:** Encode artifact URL path segments. ([#4278])
- **frontend:** Clarify run-duration display. ([#4348])
- **frontend:** Preserve regenerate state in branched threads. ([#4358])
- **frontend:** Default the reasoning-effort label to Medium when unset.
  ([#4373])
- **frontend:** Strip and parse the `<current_uploads>` upload-context tag.
  ([#4402])
- **frontend:** Keep leading orphan tool messages visible. ([#4408])
- **frontend:** Keep completed subtask cards stable after reload. ([#4432])
- **frontend:** Apply message-image `maxWidth` via inline style. ([#4446])
- **frontend:** Restore resizing for the artifacts and sidecar panels. ([#4469])
- **frontend:** Allow dev-server access from non-localhost hosts. ([#4471])
- **safety:** Backfill empty content-filter responses so they don't poison the
  thread. ([#4394])
- **tools:** Exclude injected runtime from the `list_uploaded_files` schema.
  ([#4376])
- **mcp:** Bound MCP server bring-up — tool discovery (subprocess spawn +
  `initialize` + `tools/list`) and persistent stdio session initialization —
  with a new per-server `session_init_timeout` (default 60s, `null` disables),
  so a hung stdio server can no longer block agent construction, or the whole
  Gateway event loop, indefinitely. `tool_call_timeout` still bounds individual
  stdio tool calls. ([#4657])
- **runtime:** Tool-output budget externalization no longer trips run delivery
  verification. The default `.tool-results` storage dir (and any custom
  `tool_output.storage_subdir`) is excluded from workspace-change snapshots and
  produced-artifact detection, so a run that only externalized oversized tool
  outputs succeeds instead of failing as an error. ([#4657])
- **frontend:** Hide stale follow-up suggestion chips while a turn is still
  streaming. ([#3396])
- **frontend:** Fix streaming render glitches: stop the word animation from
  replaying, keep step text stable, preserve message order during long runs,
  and keep reasoning above the answer. ([#4266], [#4510], [#4513], [#4578])
- **frontend:** Encode thread IDs in chat routes so IDs with special
  characters no longer break navigation. ([#4302])
- **frontend:** Render citation links from React children. ([#4486])
- **frontend:** Localize conversation export failure messages. ([#4493])
- **frontend:** Sync side panel state when a drag collapses the panel. ([#4556])
- **frontend:** Render one workspace-change card per run instead of
  duplicates. ([#4559])
- **frontend:** Refresh the active artifact's content when it changes. ([#4584])
- **gateway:** Reject non-positive read limits in API requests. ([#4284])
- **gateway:** Handle a null `config.configurable` when resolving the thread
  id instead of failing. ([#4301])
- **gateway:** Unify thread id validation across API routes. ([#4589])
- **gateway:** Merge concurrent thread metadata updates instead of letting
  them silently overwrite each other's changes. ([#4489])
- **gateway:** Expose the run metadata response header to cross-origin
  clients, so a split-origin frontend learns new run ids instead of staying
  stuck on the new-thread placeholder route until reload. ([#4535])
- **gateway:** Replay edit and rerun from a settled checkpoint so the edited
  prompt actually runs (previously a first turn's edit replayed the original
  prompt and vanished after reload), and keep a manual rename through the
  rerun. ([#4534], [#4539])
- **runtime:** Cancel a run from any live gateway worker, not only the one
  that owns it, so the stop button no longer depends on request routing.
  ([#4500])
- **runtime:** Close a replacement run when interrupt or rollback admission
  is cancelled mid-flight, instead of stranding an unseen active run on the
  thread. ([#4472])
- **runtime:** Regenerating a response now preserves the thread's current
  title and supports the latest interrupted response whose partial message
  never reached a checkpoint. ([#4480], [#4524])
- **agents:** Classify web_fetch error pages such as 404s as errors rather
  than successful evidence, so retries and stagnation guards can react.
  ([#4314])
- **agents:** Handle XML-to-dict option shapes when normalizing
  clarification choices. ([#4527])
- **subagents:** Run delegated subagents with isolated callbacks and lazy
  skill activation, fixing cross-event-loop failures and passive skills
  stripping baseline tools like `write_file`. ([#4497])
- **sandbox:** Handle overwrite-wrapped state when ensuring the sandbox is
  initialized. ([#4429])
- **sandbox:** Reconcile E2B sandboxes safely: pick the first healthy
  candidate, adopt the canonical instance per user and thread, defer a
  peer's live duplicates, and reap orphans after a grace window. ([#4443])
- **sandbox:** Claim ownership before destroying a sandbox that failed its
  readiness check, so a peer gateway can no longer adopt the not-yet-ready
  sandbox and kill a live turn. ([#4505])
- **sandbox:** Allow grep to search a single file. ([#4512])
- **sandbox:** Enforce the E2B capacity limit deployment-wide when sandbox
  ownership uses Redis, so multiple gateways cannot create past it. ([#4575])
- **skills:** Activate managed integration skills from the managed
  integrations root on slash invocation. ([#4570])
- **skills:** Offload blocking filesystem IO when updating a skill and
  serialize concurrent writes. ([#3565])
- **mcp:** Ignore oversized path-like text. ([#4582])
- **memory:** Harden long-term memory: reject duplicate facts inside the
  create critical section, truncate injected mem0 context on entry
  boundaries, and keep task-scoped instructions such as "inspect only" out
  of long-term memory. ([#4599], [#4600], [#4604])
- **scheduler:** Keep a successfully launched scheduled run's slot and run
  id when post-launch bookkeeping fails, preventing a later dispatch from
  launching a duplicate run. ([#4504])
- **config:** Treat a deleted extensions config file as absent instead of
  raising, so tool and skill config resolution keeps working. ([#4275])
- **config:** Normalize the `postgres://` short scheme for the async ORM
  engine. ([#4293])
- **console:** Disable cost reporting when model pricing mixes currencies
  instead of reporting a meaningless cross-currency total. ([#4564])
- **browserless:** Accept the `timeout` config key and harden its coercion.
  ([#4519])
- **docker:** Send `Connection: upgrade` only when the browser requests it,
  fixing login-page refresh loops when the Docker dev stack is accessed via
  a remote host. ([#4250])
- **runtime:** Group JSONL batch event writes by run, so a batch covering
  several runs no longer lands all events in the first run's file and makes
  later runs unreadable through per-run APIs. ([#4938])
- **runtime:** Restore standalone LangGraph Studio compatibility: the graph
  entrypoint and file-based app load again, the Studio identity can discover
  system assistants, and the documented `langgraph dev` workflow works.
  ([#4760], [#4838])
- **gateway:** Stamp `turn_duration` on a run's last AI message only in
  `/messages/page`, so multi-step turns no longer repeat the same run
  lifetime as thinking latency on every intermediate message. ([#4755])
- **gateway:** Preserve exact history attribution beyond the event page
  limit, so older AI messages on long-lived threads are no longer credited
  to a later turn's run and duration. ([#4953])
- **gateway:** Reject MCP task cancellation with HTTP 503 when the task
  worker is stopped, instead of acknowledging a cancellation that would
  never run. ([#4963])
- **middleware:** Correct four context-handling defects: fallback
  dynamic-context injection targets the latest user message instead of
  resurrecting an old prompt as the current turn; bare string blocks in
  list-form user content are sanitized like all other user text; duplicate
  placeholders are no longer emitted for the same invalid tool call; and
  summarization no longer compresses away the current request's user message
  while leaving the previous turn's behind. ([#4667], [#4668], [#4693],
  [#4882])
- **middleware:** Restore the system-prompt injection that teaches the model
  about the `write_todos` tool, which the todo middleware's model-call
  override had silently dropped. ([#4735])
- **agents:** Make SQL agent-store signatures content-sensitive, so an agent
  update that reuses its previous timestamp no longer leaves the GitHub
  agent registry serving stale webhook routing. ([#4709])
- **tools:** Resolve presented files with the runtime user, so `present_files`
  no longer rejects valid artifacts as outside the outputs directory when
  the request user context is unavailable. ([#4677])
- **tools:** Retain a strong reference to deferred subagent cleanup tasks, so
  garbage collection can no longer destroy a pending cleanup and leak
  cancelled subagent records, locks, and memory. ([#4928])
- **subagents:** Give every background subagent run a server-side execution
  ID, so concurrent runs that reuse a provider tool-call ID can no longer
  overwrite, poll, or cancel each other's state. ([#4758])
- **harness:** Offload ACP workspace creation and MCP config loading from the
  event loop, so invoking an ACP agent no longer raises blocking-IO errors
  or stalls other async work. ([#4965])
- **mcp:** Reject non-finite `poll_after_seconds` values on task snapshots
  when they arrive, so a bad polling interval no longer crashes scheduling
  and persistence after a successful poll. ([#4750])
- **mcp:** Keep the configured `grant_type` authoritative over
  `extra_token_params` during OAuth token exchange, so extra parameters can
  no longer silently switch the configured flow and be rejected by the token
  endpoint. ([#4860])
- **runtime:** A slow or hung stdio MCP server no longer stalls the whole
  Gateway. Agent construction assembled MCP tools synchronously on the event
  loop, so a wait for an in-flight MCP initialization blocked SSE delivery, run
  cancellation, and timers for every other request, not just the caller waiting
  for its tools. Tool assembly is now dispatched to a worker thread at each
  async entry point: the subagent spawn path in `task_tool`,
  `SubagentBatchService._execute_item` for durable batches, `run_agent`'s agent
  factory (which covers both `get_available_tools` call sites in lead-agent
  assembly), and the checkpoint state-accessor build, whose cold-cache reads
  pay the MCP-init wait in the worker thread instead of stopping the loop. The
  four offloads ride a dedicated bounded pool (`run_assembly()` in
  `utils/assembly_io.py`, 8 workers, overridable with
  `DEER_FLOW_ASSEMBLY_WORKERS`) rather than the loop's default executor, so a
  worker parked for the full MCP timeout cannot queue every other `to_thread`
  caller behind it; contextvars are copied across the hop so the extension
  build-context snapshot still propagates, and pending assemblies are logged
  with a throttled warning once they exceed the worker count. Because assembly
  can now be parked, a durable batch re-checks its item's durable state
  immediately before launching, so a batch cancelled during assembly no longer
  starts a model call. ([#5217], [#5224])
- **agents:** `LoopDetectionMiddleware` no longer spends one turn's budget on
  another turn's legal work. It scoped its identical-call hashes and per-tool
  frequency windows only by `thread_id`, so a compiled agent reused across
  turns — `DeerFlowClient` retains the graph and assigns a fresh `run_id` per
  turn — counted earlier turns' ordinary calls toward the later turn's limit,
  producing a false loop warning on the third separate turn and stripping a
  legitimate tool call on the fifth at the default identical-call thresholds.
  State is now scoped by `(thread_id, run_id)`, with evidence still accumulated
  across repeated graph entries inside one run, including hidden goal
  continuations, and independent warning queues for concurrent sibling runs.
  LRU eviction drops a whole run scope, `reset(thread_id)` still clears every
  scope that thread owns, and thresholds and warning/hard-stop behavior are
  unchanged. ([#5344])
- **agents:** A run's `token_budget.max_tokens` cap now holds across the hidden
  continuations of an active `/goal`. The worker re-enters the graph under the
  same `run_id`, and the middleware cleared that run's usage in `after_agent`
  and then marked every existing message as already seen, so each continuation
  started counting from zero: with `max_tokens: 10000`, a turn that hit the
  hard stop at 12k was followed by a continuation that kept calling tools, and
  the run reported `stop_reason: token_capped` while spending 20k tokens and
  running two more tool calls after the cap. Usage and warning state now
  survive graph entries with the same `run_id` — as loop detection already did
  — while a later user run still gets a fresh `run_id` and a fresh budget.
  After a cap, a continuation still makes one model call before its tool calls
  are stripped. ([#5410])
- **middleware:** A Human Input Card reply is now recognized as the user's
  current request. The card answer arrives as a hidden `HumanMessage` carrying
  a valid `human_input_response`, and the turn-detection helpers used
  `is_real_user_message`, which rejects every hidden message with no carve-out
  — so a run started from a card reply kept the older visible request as
  "current" while the answer itself was treated as a framework injection. In
  summarization, the current-request rescue therefore locked onto the stale
  message: after compaction the model saw the original request word for word
  and the user's region and year constraints only inside the summary. In
  `McpRoutingMiddleware`, a routing keyword that appeared only in the card
  answer matched nothing, so the deferred MCP tool was never auto-promoted and
  the model had to call `tool_search` by hand — the identical answer sent as a
  visible message promoted it, so behavior depended only on how the answer was
  transported. Both now use `is_genuine_user_message`, which skips hidden
  messages unless they carry a valid `human_input_response`; hidden messages
  without one still stay skipped. ([#5416], [#5426])
- **goal:** A goal that a token-capped run already satisfied is no longer
  followed by a pointless continuation. Now that continuations share the run's
  token budget, a continuation queued after the hard stop made one model call
  and then had its tool calls stripped, so it could not make progress — yet the
  worker still queued it, paying for an evaluator call and a model call each
  time until the continuation or no-progress limit stopped the goal.
  `run_agent` now passes the run's `stop_reason` into goal-continuation
  preparation, and when it is `token_capped` the goal stands down with
  `stand_down_reason: "token_capped"` instead of queueing another continuation.
  The evaluator still runs first, so a goal the capped run did satisfy is still
  cleared, and other stop reasons behave as before. ([#5424])
- **agents:** A retried model call no longer reaches the provider without the
  warning a guard middleware had already queued for it.
  `LoopDetectionMiddleware`, `TokenBudgetMiddleware`, and
  `ToolProgressMiddleware` drain their queued warning or hint inside
  `wrap_model_call` before calling the handler; because
  `LLMErrorHandlingMiddleware` wraps them and retries by calling its handler
  again, the second attempt ran with an empty queue while the warning had
  already been marked sent. A model that looped on one tool call and failed
  once with a 503 on the request carrying the warning never saw it and ran on
  to the forced stop. All three now put the drained warnings back at the front
  of the queue when the handler raises, so the retry picks them up; successful
  calls are unchanged, per-run caps still apply, and warnings are still dropped
  at `after_agent` if the run ends without another model call. ([#5433])
- **agents:** The token budget works again for runs that have no `run_id` —
  LangGraph Server, `langgraph dev`, and direct `create_deerflow_agent`
  callers. Two defects rode the runtime-local fallback key. A subagent's hard
  stop was stored under the id string but read back with
  `consume_stop_reason(None)`, because `SubagentExecutor` propagates the
  parent's `run_id` and the parent has none, so a token-capped subagent was
  reported to the parent as a clean `Task Succeeded` instead of a capped
  failure. And LangGraph gives each node its own `Runtime` wrapper, so
  `id(runtime)` differed between `after_model`, the next `wrap_model_call`, and
  `before_agent`: the queued budget warning was never delivered, `after_model`
  missed the `before_agent` baseline and counted every `AIMessage` in the
  thread, and a second invocation on the same thread was charged with the first
  invocation's tokens. Invocations without a non-empty string context `run_id`
  are now keyed by LangGraph's run-scoped `Runtime.control` object, the same
  anchor loop detection uses, and the stop reason is stored under the context
  `run_id` exactly as given, `None` included. ([#5436])
- **agents:** Cancelling a `read_file` or `write_file` call can no longer
  strand or release the read-before-write gate's lock. `asyncio.to_thread()`
  cancellation only cancels the asyncio waiter, not an already-running worker,
  so a cancellation could leave a queued `threading.Lock.acquire()` hanging or
  free the gate while an off-thread probe was still running. Dispatched gate
  operations are now drained under `asyncio.shield()` before the cancellation
  propagates, the first `CancelledError` is preserved and re-raised across
  repeated cancellations (including when the drained worker task is itself
  cancelled), a lock that succeeds after cancellation is released exactly once,
  and the same-path gate is held until the write-check and read-mark work
  finishes. ([#5395])
- **agents:** Three `create_deerflow_agent` features now do what they
  advertise. Factory graphs were built without `DurableContextMiddleware`,
  which is what writes the `delegations` ledger — so `SubagentLimitMiddleware`
  always counted zero earlier delegations and only the per-response limit
  applied — and which is the only thing that puts `summary_text` back into a
  model request, so after the first compaction the model saw only the kept tail
  and the summary was lost. Separately, `RuntimeFeatures(token_budget=True)`
  built a `TokenBudgetConfig()` whose `enabled` defaults to `false`, so every
  hook returned early and there was no warning, no hard stop, and no
  `token_capped`. `_assemble_from_features` now always adds
  `DurableContextMiddleware` in the same position as the lead-agent chain,
  factory model requests carry the hidden durable-context block when the graph
  has a summary, delegations, or loaded skill files, and `token_budget=True`
  builds `TokenBudgetConfig(enabled=True)`. ([#5488])
- **subagents:** Subagent acceptance checks no longer let an out-of-scope
  command count as evidence on Windows. `_cd_target_in_scope()` normalized bash
  `cd` targets with the host platform's path module, so on Windows an absolute
  POSIX path or a `..` escape could be judged a safe relative target and a test
  run outside the checked scope could satisfy an acceptance criterion. Bash
  targets and configured roots are now normalized with POSIX semantics on every
  host, drive-qualified Windows paths are recognized and compared
  case-insensitively, and an unmatched drive or directory fails closed.
  ([#5162])
- **sandbox:** Concurrent subagents stopped working once their count passed the
  AIO image's shell-session ceiling. Each concurrent subagent gets its own
  persistent scoped shell, but the AIO image caps `MAX_SHELL_SESSIONS` at 10,
  so the eleventh shell evicted the oldest idle session while DeerFlow still
  held its scoped id — the subagent's next command then failed with `404
  Session not found`, and recreating sessions without raising the capacity only
  evicted another subagent and lost its shell state. New local containers now
  receive `subagent_runtime.max_running + 1` (the extra slot leaves room for
  the lead shell) as `MAX_SHELL_SESSIONS`, provisioner mode forwards the same
  value to the sandbox Pod, and an explicit
  `sandbox.environment.MAX_SHELL_SESSIONS` set below the required capacity now
  fails at provider startup naming both values. When a scoped session is lost
  anyway — to a timeout or external cleanup — DeerFlow recreates it once, and
  only for the structured `404 Session not found` response. ([#5178])
- **view-image:** `view_image` no longer serves a stale or missing picture for
  a remote sandbox image. It resolved `/mnt/user-data/...` to a Gateway host
  path, so bytes only became available after synchronization and an older host
  copy could stand in for the current one. Bytes are now read from the current
  live sandbox when one is available, without acquiring a replacement merely
  because a persisted sandbox ID exists, and lightweight provenance — the exact
  SHA-256 plus the source sandbox ID — is recorded in `viewed_images` instead
  of checkpointing image bytes or base64. A replacement sandbox that reports
  the image missing falls back to the synchronized host copy only when it
  matches both the recorded size and SHA-256, so same-size stale content is
  rejected; missing-file classification is provider-neutral over an explicit
  `__cause__` chain and deliberately ignores implicit exception context. Async
  tool invocation and model injection now run the blocking sandbox read through
  `run_sync_lifecycle_operation()`, so a cancellation cannot tear down sandbox
  lease cleanup before the read has drained. ([#5306])
- **subagents:** A subagent keeps its instructions after its context is
  compacted. The executor builds the agent with `system_prompt=None` and puts
  the assembled prompt into state as the first message, so it holds the role
  prompt, the `<report_contract>` citation rules, the acceptance-criteria note,
  the skills index, and the deferred MCP tools and routing hints — and
  compaction cuts by index, so index 0 always fell in the summarized part.
  Every model call after the first compaction ran with no system prompt at all,
  and the summary did not stand in for it because it is injected as hidden data
  the authority contract tells the model not to follow. Dynamic-context
  preservation now rescues `SystemMessage`s as well as tagged reminders and the
  latest user message, keeping their order so the prompt stays first and is not
  sent to the summarizer; when the prompt plus the current request are all that
  remains, compaction is skipped instead of summarizing the prompt away. The
  lead agent is unaffected — its prompt is the request's system message, not a
  message in state. ([#5454])
- **subagents:** A repeatedly cancelled subagent no longer leaks its execution
  slot permanently. `SubagentExecutionCapacity.slot()` increments the
  process-wide running count before yielding and releases it in the async
  context manager's `finally`, but a second `Task.cancel()` arriving while that
  release was blocked acquiring the capacity lock interrupted the cleanup: the
  task exited cancelled with `_running` still incremented. With
  `max_running=1`, every later native subagent then queued until timeout or was
  rejected even though nothing was running, violating the documented invariant
  that cancellation and timeout release queue and slot ownership. The final
  release now runs in its own task, is shielded from caller cancellation, and
  is drained across repeated cancellation before the cancellation propagates.
  ([#5477])
- **worker:** A delegated subagent's error no longer fails the parent run. When
  a subagent's model call ended in an error after its retries, the executor
  reported `task_failed` and the lead agent still answered, but the worker also
  saw the `deerflow_error_fallback` marker inside the root-level `task_running`
  custom event — each carries a subagent message with `additional_kwargs` — and
  marked the parent run `error` with the subagent's error text. Goal
  continuation stopped, and an edit-and-rerun rolled the thread back,
  discarding the edited question and the new answer. Custom frames no longer
  feed parent error-fallback detection, while the lead's own error fallback
  still arrives through `values`, `messages`, and `updates` frames; the parent
  run now ends `success` when the lead finishes. ([#5407])
- **sandbox:** Normalize separators in masked output tails so virtual paths are
  spelled POSIX-style on Windows hosts too. Both output maskers searched for
  the host base in a forward-slash-normalized copy of the output but sliced the
  matched tail out of the original text, so nested backslashes survived into
  the spliced result and `glob` results and masked skill reads came back as
  mixed spellings such as `/mnt/user-data/workspace/pkg\util.py`. Depth-1 tails
  happened to splice cleanly, which is why Linux CI never caught it; the two
  splice sites now normalize the tail before joining it to the virtual prefix.
  ([#5247])
- **sandbox:** Reverse-resolve forward-slash spellings of Windows host paths.
  Forward resolution spells resolved paths with `/`, since backslashes would
  break bash escape sequences like `\U`, but the reverse scanner that maps host
  paths in output back to their `/mnt/...` form still anchored its matches on
  the native backslash base — so every forward-resolved path that came back in
  command output or in an agent-written file failed to match and leaked the raw
  host path, real username and full directory tree, to the model instead of the
  container path the agent is meant to reference. The scanner now matches
  separator-agnostically, the same contract the sandbox tools already use;
  POSIX hosts, where the two spellings coincide, are unaffected. ([#5373])
- **sandbox:** Stop remote `list_dir` from reporting failures as an empty
  directory. `find ... 2>/dev/null` on a missing path produced empty stdout and
  client errors were swallowed as `[]`, so `ls` told the agent the directory
  was `(empty)` — a dead sandbox, a closed client, and a nonexistent path all
  looked like a writable empty tree, letting the agent write over existing
  files or skip recovery. AIO, E2B, BoxLite, OpenSandbox, and Tenki now raise
  `OSError` on command or client failure and `FileNotFoundError` when nothing
  is listed, matching what the local sandbox already did for a path that is not
  a directory; a genuinely empty directory still reports `(empty)`, and `find
  -H` keeps a symlinked root listable. ([#5264])
- **sandbox:** Reject a partial remote `list_dir` traversal instead of
  presenting it as complete. `find` exits `1` both for a missing start path and
  for a file or subdirectory it could not read after printing some entries, and
  the parser accepted `1` in both cases — so a traversal that failed partway
  returned the visible entries as a successful complete listing and `ls` handed
  the agent a silently incomplete tree. Status `1` with no entries still raises
  `FileNotFoundError`, while status `1` with any entries now raises `OSError`
  naming the incomplete traversal and suggesting a narrower path, the same
  contract remote `glob` already applied. Every provider sharing the remote
  `list_dir` helper inherits it without provider-specific changes. ([#5422])
- **sandbox:** Stop remote `grep` and `glob` from reporting failures as "no
  matches". The searches ran with stderr discarded and took the pipeline status
  from `head`, so a missing search root, a missing `grep`/`find` binary, or an
  unreadable tree printed nothing and exited 0 — and the tools told the agent
  "No matches found" where the local sandbox reports `Error: Directory not
  found`. A shared wrapper now records the search command's own status: a
  missing root raises `FileNotFoundError`, and any other failure — including
  `grep` 2 or `find` 1 after some results were already printed, since a caller
  cannot tell a partial result from a complete one — raises `OSError` telling
  the agent that some paths could not be read. A genuine no-match still returns
  `[]`. E2B, OpenSandbox, BoxLite, and Tenki also raise on a closed client
  instead of returning empty. ([#5380])
- **sandbox:** Report `read_file` truncation in lines and name the line to
  resume from. The tool head-truncates at `sandbox.read_file_output_max_chars`
  (default 50,000) and its marker told the model to continue with
  `start_line`/`end_line`, but the cut was made at a character offset and the
  marker reported only character counts — so it almost always landed mid-line
  and the last line the model saw was a fragment that read as complete, with
  nothing saying which line to continue from. Asked for the next read of a
  truncated file, three models picked the right `start_line` in 0 of 15
  attempts, landing tens or hundreds of lines off. The cut now lands on the
  last line boundary the budget allows, and the marker states the position in
  lines and names the exact continuation, as in `[truncated: showing first 743
  of 1828 lines (49746 of 155704 chars). Continue with start_line=744]`; a
  ranged read reports file line numbers rather than the provider's
  slice-relative ones. A single line longer than the budget still cuts at the
  character limit, since dropping it would discard most of the budget, and the
  marker then points at `bash` rather than at a `read_file` call that cannot
  return it. ([#5474], [#5478])
- **sandbox:** Force a UTF-8 console in PowerShell so CJK tool output is no
  longer garbled on Windows. The command runner captures stdout through a UTF-8
  pipe reader, but Windows PowerShell 5.1 writes console output in the legacy
  OEM codepage — GBK on zh-CN Windows — unless explicitly switched, so every
  CJK character arrived as mojibake, and because the reader replaces
  undecodable bytes rather than raising, the corruption was silent. Every
  PowerShell `-Command` payload now sets `InputEncoding`, `OutputEncoding`, and
  `$OutputEncoding` to UTF-8 before the user command runs. ([#5440])
- **sandbox:** Validate the managed Lark CLI sandbox runtime in a
  platform-aware way on Windows hosts. The check required a POSIX executable
  bit, which NTFS does not preserve, so every candidate reported `st_mode &
  0o111 == 0` and the Gateway raised `ValueError: Managed Lark CLI sandbox
  runtime file is not executable` — leaving the managed Lark runtime unusable
  on a Windows development host, and on a Windows Docker host that mounts the
  managed Linux CLI runtime into the sandbox. POSIX keeps the strict
  executable-bit contract unchanged; on Windows the Linux-only artifacts are
  validated by content instead, requiring executable image magic on the
  per-arch binaries and a shebang on the launcher. ([#5442])
- **sandbox:** Default the Docker-outside-of-Docker sandbox port bind to
  loopback on Docker Desktop. `DEER_FLOW_SANDBOX_HOST` defaults to
  `host.docker.internal` in DooD mode, which resolves inside containers to the
  Docker Desktop VM gateway, and publishing the sandbox port to that address
  made the host socket layer reject the bind with `WSAEADDRNOTAVAIL` — so the
  first sandbox shell action failed with `ports are not available` even though
  startup had succeeded. When the Docker server is Docker Desktop and no
  `DEER_FLOW_SANDBOX_BIND_HOST` override is configured, the bind host is now
  `127.0.0.1`, which Docker Desktop forwards; an explicit override still wins,
  and native Linux DooD is unaffected. ([#5446])
- **sandbox:** Drain the skill-sync worker before a cancellation is treated as
  failure cleanup. The default `sync_agent_skills_async()` wrapper used a bare
  `asyncio.to_thread()`, so cancelling the awaiting task returned before the
  synchronous sandbox mutation had finished, and `SandboxMiddleware` then
  released the execution holder while provider work was still in flight —
  breaking the lifecycle contract that blocking work started on behalf of a
  holder must drain before that holder leaves the boundary. The wrapper now
  runs through the existing cancellation fence, so the ordering holds for
  third-party and upload-based providers that do not serialize sync and release
  themselves. ([#5350])
- **frontend:** Keep a human-input card with the turn that requested it. An
  existing `needYourHelp` card could drift below the next user message during a
  multi-turn conversation, so the chronology became misleading and an answered
  request could read as part of the new turn. A pre-submit baseline message
  could be woven in after the newly persisted human message, a card confirmed
  only through REST history might never enter the checkpoint baseline, and
  steps already persisted for the current run could be lifted into the previous
  turn after an interrupt. Baseline messages are restored before the pending
  human message, REST-confirmed cards count as established history, and the
  current run's own steps stay below the message that started them. ([#4892])
- **frontend:** Preserve server-assigned message positions through a live
  content merge. Streaming updates that replaced a message's content also
  dropped its `deerflow_seq`, so ordering the server had already settled was
  recomputed client-side and came out wrong — a loaded history window of
  `1,3,5` merged with a live tail of `2,5` rendered as `1,3,2,5`, and long
  threads (history pagination, or a conversation resumed after compaction)
  showed their steps out of order until a refresh. Content and position are now
  handled separately, the merge, compaction bridge, and render ledger share one
  position priority so an already-sorted upstream is not re-sorted downstream,
  and anomalous sequence values (null, string, NaN, non-integer,
  non-safe-integer) never overwrite a known position. ([#5293])
- **frontend:** Restore the user's input after an incremental stream reconnect.
  Refreshing during a later turn could let the reconnect stream replay AI and
  tool chunks before the current human input had entered the durable history
  feed, so the user's message briefly vanished and its reasoning steps were
  grouped under the previous turn. The active run's input is now hydrated from
  `kwargs.input` and merged with the latest durable thread state before the
  incremental stream is joined, deduplicated by id; if the metadata or state
  read is unavailable, the previous reconnect path is used unchanged. ([#5428])
- **frontend:** Show an agent's skill badge even when its tool groups are
  explicitly empty. The badge container's nullish-coalescing chain stopped at
  the tool-group count `0`, so an agent declared as `tool_groups: []` with
  `skills: ["data-analysis"]` lost its badge in the Agents gallery — even
  though an explicit empty tool-group list is valid and supported by the Agent
  API and the `update_agent` tool. The container now shows when either list has
  at least one entry. ([#5326])
- **frontend:** Scope composer slash-skill suggestions to the active agent.
  Custom-agent chats can restrict which skills they may activate, including to
  an explicit empty list, but the composer still offered the global
  enabled-skill catalog — so an agent could suggest a skill it was not
  permitted to activate. Suggestions now pass through the active agent's
  allowlist, with an explicit empty list treated as no skills available rather
  than briefly leaking the global catalog while the agent loads, and the same
  scoping applied when a saved composer draft with a selected skill chip is
  restored. ([#5451])
- **frontend:** Confirm before a sidebar chat is deleted. Choosing Delete in a
  recent chat's menu removed the conversation and its files immediately, with
  no confirmation step despite deletion being irreversible. A dialog now names
  the conversation and warns that deletion is irreversible, focuses Cancel, and
  leaves the chat intact on Cancel, Escape, or close; actions are disabled and
  dismissal blocked while deletion is pending, and a failed deletion keeps the
  dialog open with the underlying error so it can be retried by keyboard. The
  dialog is hosted outside the virtualized sidebar rows, so a list refresh
  cannot remove the retry UI after a partial deletion. ([#5406])
- **agents:** Keep the Custom Agent settings dialog within the viewport.
  Choosing **Selected subagents** could make the dialog taller than the window,
  pushing the title, close control, and Save/Cancel buttons off-screen while a
  long worker description filled the nested list. The header and action buttons
  now sit outside a single scrolling form area, subagent descriptions show a
  two-line preview with keyboard-accessible expansion that scrolls into view
  without moving focus or changing checkbox state, and long names and
  descriptions wrap without shrinking the checkboxes. ([#5458])
- **frontend:** Keep the MCP configuration dialog within the viewport. Opening
  a long MCP server definition in the Capability Center let the JSON textarea
  grow past the window, so the centered dialog clipped its title, close
  control, and Save/Cancel buttons and became hard to edit or dismiss on
  smaller windows. The dialog is now viewport-contained with more horizontal
  room on desktop, long JSON scrolls inside the editor, and the title, Close,
  Save, and Cancel stay outside the scrolling region even at very small
  viewports or with a long server name or validation message. ([#5492])
- **frontend:** Show a pointer cursor over interactive controls that were
  clickable while still displaying the default cursor, making their affordance
  unclear. One global selector now covers native buttons, `role="button"`
  elements, dropdown menu items, and command items, excluding native disabled
  controls and anything marked `aria-disabled="true"`; generated `ui/` and
  `ai-elements/` components are untouched. ([#4921])
- **frontend:** Localize Chinese documentation links. MDX links and Nextra
  cards in the localized docs were rewritten without knowing the active docs
  language, so a Chinese reader following a quick-start link was sent to the
  English page. The localized docs layout now provides the language through
  context and link rewriting honors it. ([#5275])
- **runtime:** Memory-only deployments keep their run history through scheduled
  cleanup. `cleanup()` evicted unconditionally, so an embedded consumer that
  built `RunManager()` with the documented default `store=None` lost completed
  runs from history when cleanup fired — `get(run_id)` returned `None` and
  `list_by_thread()` dropped the record, because there is no durable copy for
  those reads to fall back to. Eviction is now gated on a backing store,
  keeping the retain-forever behavior memory-only mode had before; store-backed
  managers still evict after the grace period. ([#5453])
- **events:** Read JSONL event records that contain U+0085, U+2028, or U+2029.
  All three readers split on those Unicode separators as if they were record
  boundaries, so a record carrying one was skipped on read — which reused event
  sequence numbers after a reopen and turned idempotent inserts into
  duplicates. Thread reads, run reads, and sequence recovery now split on
  physical line feeds; existing valid files need no rewrite. ([#5429])
- **events:** Keep the per-thread JSONL write lock until filesystem work
  settles. Cancelling a store call during its worker release dropped the lock
  while the append was still in flight, so a later deletion could complete
  before the cancelled append recreated the record, and a cancelled mixed-run
  batch could roll back over a write it had already acknowledged. Admitted
  mutations now retain their lock through file I/O, rollback, and bookkeeping
  before propagating the cancellation, covering `put`, `put_if_absent`, batched
  writes, and both deletion methods; queued callers can still cancel before
  admission, and unrelated threads stay independent. ([#5439])
- **events:** Stop JSONL thread mutations from splitting onto two lock
  generations across a deletion. `delete_by_thread()` removed the per-thread
  lock from its registry while still holding it, so a mutation already queued
  on the old lock could run concurrently with a later mutation that resolved a
  freshly created lock for the same thread — overlapping sequence assignment
  and file mutation right after a delete boundary. The registry is now a
  `WeakValueDictionary` and the entry is no longer popped, so holders and
  queued waiters keep the same generation alive until they drain, after which
  the entry disappears on its own. ([#5455])
- **channels:** Keep one lock generation for a channel's first-use thread
  creation. The cleanup removed the per-conversation lock unconditionally when
  the current creator exited, so a creator that failed or was cancelled
  released and unregistered its lock while a queued creator entered through it,
  and a late arrival could install a new lock and enter concurrently — two
  callers creating Gateway threads for the same conversation, with the later
  mapping write winning and adjacent messages split across the orphaned thread.
  The hand-managed lifecycle is replaced by the existing waiter-aware keyed
  lock table, so a conversation key keeps one discoverable generation through
  exceptions and cancellation and the idle key is reclaimed only after the last
  participant leaves. ([#5480])
- **gateway:** Read a thread's runs as the data owner, not as the authorization
  identity. The list, keyset-page, and single-run read endpoints filtered run
  rows by the caller's authorization identity, while `start_run` stamps them
  with the data identity — the two only coincide for already-safe owner values,
  so trusted internal callers always saw an empty runs list and 404s even on
  threads they were authorized to act on, and the symptom was easily misread as
  run loss. Internal callers now skip the per-user store filter, which thread
  visibility on these endpoints already authorizes, while browser and API
  sessions keep their exact per-user filter; the two message-read endpoints had
  the same conflation and are corrected the same way. ([#5448])
- **gateway:** Apply the same data-identity scoping to the message edit and
  regenerate helper paths. Those three helpers still resolved the authorization
  identity and passed it as the data filter, so `regenerate/prepare` and
  `edit-regenerate/prepare` failed with 409 for internal callers on threads
  they were authorized on. They now resolve their filter id the same way the
  read endpoints do, and browser and API sessions keep the prior per-user
  filter and the 409 on cross-user runs. ([#5483])
- **conversation:** Keep conversation-reader pages inline and say when text was
  dropped. A page was filled to its 20,000-character cap by cutting the last
  message that did not fit, and a cut suffix could never be paged back — the
  oldest of six 3,500-character messages came back as about 2,500 characters
  with `has_more: false`. Worse, a page over the default 12,000-character
  tool-output budget was externalized by `ToolOutputBudgetMiddleware`, so the
  model saw only a synopsis plus a file copy of the source text in the
  destination thread. Pages are now sized by the budget that actually applies
  to `read_conversation` (per-tool override, else `externalize_min_chars`, and
  `fallback_max_chars`), still capped at 20,000 text characters, and a message
  that does not fit starts the next page intact — so one operator setting stays
  in charge, and `tool_output.tool_overrides.read_conversation` tunes this tool
  alone. Truncated results now carry a notice asking the agent to acknowledge
  the omission and ask for the missing material before claiming full coverage.
  ([#5421])
- **goal:** Stop a goal loop while a clarification card is still open. The goal
  evaluator only reads human and AI messages, so a question asked through
  `ask_clarification` — which arrives as a tool result — was invisible to it;
  it judged the goal unmet, and the worker queued a hidden continuation telling
  the agent to keep working and not to ask the user unless genuinely blocked.
  The agent then acted on its own guess, including on a `risk_confirmation`
  question, while the card sat waiting in the UI. A trailing human-input
  request is now detected before the evaluator runs and stands the goal down
  with the existing reason `blocked:needs_user_input`; the user's answer is a
  new human message, so the next run evaluates normally, and a card with no
  assistant text before it reports why it stopped instead of `run_failed`.
  ([#5467])
- **client:** Emit text a later node appends to an AI message already sent.
  `LoopDetectionMiddleware`, `TokenBudgetMiddleware`,
  `SafetyFinishReasonMiddleware`, `SubagentLimitMiddleware`, and
  `TerminalResponseMiddleware` each rewrite the last AI message under the same
  id from their own node, but the stream marks an id seen once and then skips
  it, so the rewrite never reached `messages-tuple` consumers: `chat()` and
  headless `--print` returned the text from before the rewrite instead of the
  terminal error or the forced-stop notice, the TUI never showed the stop or
  safety notice, and `token_usage_attribution` added after the model node never
  arrived. The values path now remembers the message object last seen per id
  and re-examines it when a snapshot holds a different one, emitting only the
  added text as one more delta and routing new `additional_kwargs` through the
  existing metadata-only follow-up; unchanged messages are still skipped
  without re-extracting text. A replacement that does not extend the sent text
  is not re-emitted. ([#5479])
- **mcp:** Hold the MCP session pool to its capacity limit under concurrent
  initialization. `MCPSessionPool` checked LRU capacity only before session
  creation started, and because initialization awaits, several distinct keys
  could each observe spare capacity, enter `_inflight`, and then promote into
  `_entries` with no second check — leaving the persistent-session registry
  above `MAX_SESSIONS` and retaining the extra subprocesses and connections it
  implied. Capacity is now rechecked and enforced atomically when a session is
  promoted, and promotion-time eviction victims are closed outside the registry
  lock through their owner-task lifecycle. ([#4962])
- **mcp:** Stop parallel synchronous MCP calls from cancelling each other's
  connection. When an embedded client dispatched two synchronous calls to the
  same stdio server, each wrapper ran on its own event loop and the pool
  treated the sibling loop's live session and in-flight creation as stale —
  cancelling or closing them and aborting a tool step with `CancelledError`
  instead of returning both results. Established sessions and in-flight
  creation are now keyed by `(server_name, scope_key, owning_loop)`, so
  same-loop callers still share creation and state while separate loops get
  their own, and each owner retires only its own records, including after a
  normal `asyncio.run()` shutdown. Synchronous calls still use independent
  subprocess sessions and gain no shared server-side state. ([#5396])
- **web-fetch:** Resolve relative destinations in extracted Markdown against
  the page they came from. Jina, Browserless, and InfoQuest returned links
  exactly as written in the HTML, so a page at
  `https://example.com/docs/current` yielded `[Next](../next)` and left the
  agent with no URL it could follow up on. The three providers now pass the
  requested URL to the shared extractor, which resolves anchor and image
  destinations against that URL or against the first usable document `<base>`;
  only destination attribute values are rewritten rather than serializing a
  different parse tree, so malformed markup, comments, scripts, and attribute
  formatting survive untouched and still reach Readability.js unchanged. Fetch
  validation, the 4096-character output limit, and off-thread extraction are
  unchanged, and the Python fallback keeps its text-only behavior. ([#5310])
- **community:** The Firecrawl `web_fetch` and `web_search` tools honor the
  tool's `base_url`. `_get_firecrawl_client` read only `api_key`, so
  `FirecrawlApp` always fell back to `https://api.firecrawl.dev` — and because
  the SDK raises `Error: No API key provided` whenever the target is the cloud
  API and no key is set, a self-hosted Firecrawl was unreachable no matter how
  the config was written. `base_url` is now forwarded as `api_url`, letting a
  local Firecrawl serve both tools with no cloud key, and configurations
  without `base_url` construct the client exactly as before. ([#5392])
- **community:** Tavily extraction reads its credentials from the `web_fetch`
  entry instead of the search configuration. With `web_search` on Serper and
  `web_fetch` on Tavily, fetching built its client from the Serper key and
  ignored a separate Tavily fetch key entirely. Each tool now reads `api_key`
  from its own entry and falls back to the SDK's `TAVILY_API_KEY` when omitted,
  matching the existing Exa helper. Configurations that put a shared Tavily key
  only under `web_search` must also set it under `web_fetch`, or rely on
  `TAVILY_API_KEY` for both. ([#5496])
- **client:** `DeerFlowClient.stream()` emits a streamed tool call once, with
  its complete arguments. OpenAI-style models put the tool name and id in the
  first chunk and argument fragments with no id in the rest, and the client
  emitted a `messages-tuple` tool_calls event for every chunk, each parsed from
  that chunk alone — so the complete call, which does arrive in the values
  snapshot, was skipped because its message id was already in `streamed_ids`.
  The tool itself ran with the right arguments; only the event stream was
  wrong, and in the TUI the tool card showed `bash` with an empty detail
  instead of the command. One event is now emitted per message from the values
  snapshot, while whole AI messages from non-streaming models and streamed text
  are unchanged. ([#5408])
- **browser:** Keep browser session teardown alive across caller cancellation.
  `BrowserSessionManager.close_session()` removed a session from the registry
  before awaiting its close, and that close awaited the private Playwright loop
  directly, so a cancellation at that point propagated through
  `asyncio.wrap_future()` into the cleanup itself — leaving the browser process
  and context orphaned, with the session already out of the registry and no
  owner left to retry. `close_all_sessions()` had the same ownership problem at
  a larger scale: it cleared the whole registry first, so a cancellation while
  closing the first session stranded every later session with no teardown
  scheduled at all. Teardown is now submitted to the private loop before any
  cancellable await and awaited behind `asyncio.shield()`, and close-all
  schedules every session before its first await and shields the group wait.
  The caller still receives `CancelledError`; only ownership of the
  already-started cleanup is isolated from it. ([#5444])
- **browser:** Detect the browser dependency regardless of tool field order.
  Startup dependency detection recognized a tool name only when `name` was the
  first key of its YAML list item, so moving `name` below `use` or `group` kept
  the tool configuration working but silently omitted the browser extra from
  `uv sync`, leaving browser tools without their required dependencies. The
  direct `name` field is now recognized anywhere in a tool entry, tracked
  indentation keeps names inside nested options from enabling the extra, and
  the detector stays standard-library-only because it runs before dependencies
  are installed. ([#5456])
- **setup:** The same pre-sync extras detector now reads `config.yaml` as
  `utf-8-sig`. PyYAML accepts a leading UTF-8 BOM but the detector read the
  file as plain `utf-8`, leaving the BOM attached to the first line, so its
  anchored section patterns failed to recognize a valid config's opening
  section and omitted the extras it declared — `postgres`, `browser`, and
  `ollama` detection all failed the same way when their section came first,
  while a plain-UTF-8 copy of the same file worked. ([#5504])
- **video:** Forward `--aspect-ratio` into the Gemini Veo request. The skill
  CLI accepted the flag and passed it to `generate_video()`, but the Gemini
  branch built its `predictLongRunning` body from `instances` alone and dropped
  the value, so every Veo request rendered at the provider default ratio
  regardless of the argument. It is now sent as `parameters.aspectRatio`.
  ([#5388])
- **channels:** Both WeCom outbound paths sent unbounded text while the bot
  protocol caps content at 20480 UTF-8 bytes, a bar a deep-research report
  clears easily. Over the cap, `_send_with_retry` retried three times and gave
  up: the stream path left the reply stuck mid-way without ever sending
  `finish=true`, and the push path dropped the reply entirely. Stream replies
  now clip on a UTF-8 character boundary behind a visible truncation marker —
  one stream carries the whole reply, so it cannot split mid-way — while
  proactive pushes with no replyable frame, such as scheduled-task
  notifications, split into sequential markdown messages at newline boundaries
  so the full content still arrives. Both paths now measure the payload in
  UTF-8 bytes rather than characters. ([#5148])
- **channels:** Inbound WeChat (iLink) and WeCom media was downloaded in full
  before any size limit applied, and the download target was a URL taken
  straight from the message payload with no destination validation, so a
  legitimately oversized attachment spiked Gateway memory before being
  rejected. Both channels now stream the transfer and abort in flight once it
  exceeds `max_inbound_image_bytes` / `max_inbound_file_bytes`, with the exact
  post-decrypt size checks kept as a second line. Inbound `full_url`s are gated
  to http/https plus a dot-boundary host-suffix allowlist — the `qq.com` family
  and the configured CDN host by default, extendable with
  `channels.wechat.allowed_media_hosts` and
  `channels.wecom.allowed_media_hosts` — with the WeCom COS gate pinned to the
  verified Tencent Cloud APPID shape, and the WeCom manager reader bounded by a
  50 MB in-flight cap. Readers ask for `Accept-Encoding: identity` and refuse
  any residual `Content-Encoding`, so httpx cannot inflate a compressed body
  past the cap before it is measured. Well-formed media under the limits is
  unaffected; oversized or non-allowlisted media is now skipped with a warning
  naming the reason. ([#5225])
- **channels:** Keep one undecodable WeChat message from dropping the rest of
  its batch. `_poll_loop` persisted the `get_updates_buf` cursor for the entire
  batch immediately on receipt, then iterated `data["msgs"]` with no per-message
  error isolation, so a single message whose processing raised — a corrupt or
  undecryptable attachment, such as a truncated encrypted image payload, is the
  realistic trigger — aborted the loop with the cursor already advanced past the
  whole batch. Every message after the failing one was permanently dropped and
  the next poll never re-fetched it. `_handle_update` now runs inside a
  per-message `try`/`except`, so siblings still reach the bus, the failure is
  logged with its message id, and the cursor still advances once the batch has
  been fully attempted. ([#4231])
- **channels:** When the Discord client thread died — an invalidated token, an
  unrecoverable close — `Client.start()` returned and left its event loop
  stopped but not closed, so `call_soon_threadsafe` queued a callback that
  would never run and the unbounded `await asyncio.wrap_future(...)` in `send`,
  `send_file` and `_get_channel_or_thread` hung forever. Each outbound to the
  dead channel permanently consumed one `ChannelManager` worker from the
  default pool of five, so a handful of messages froze inbound processing for
  every IM channel, not just Discord. Those cross-loop calls now route through
  a helper that bounds the wait at `DISCORD_OUTBOUND_TIMEOUT_SECONDS` (30 s),
  with file uploads given `DISCORD_UPLOAD_TIMEOUT_SECONDS` (120 s) so a slow
  uplink plus a large 429 retry-after cannot cancel a healthy transfer, and a
  missing or stopped loop closes the coroutine and raises immediately.
  `DiscordChannel.is_running` also requires the client thread to be alive, as
  `FeishuChannel` already did, so readiness polling restarts the channel
  instead of treating a dead one as healthy; and a half-started instance is now
  stopped and discarded when `start()` fails, so repeated readiness retries
  cannot accumulate stale outbound listeners on the bus. ([#5227])
- **channels:** Discord thread mappings are persisted off the event loop after
  a thread is created, so a process killed between the creation and its
  background write could still lose the newest mapping and leave a Discord
  thread unreachable after the restart. `stop()` now flushes the in-memory
  mappings to disk, wrapped so a shutdown path is never blocked — a best-effort
  net over the hard-kill window rather than a new write path. ([#5461])
- **channels:** Enabling `rich_messages` in the Telegram channel config made
  every final outbound message render as a mangled single line: command menus
  such as `/help` and plain error replies were sent through `sendRichMessage`
  with `rich_message.markdown`, which collapses single newlines and strips the
  `<name>` / `<skill-name>` / `<task>` angle-bracket tokens the menus rely on.
  A message is now sent as rich only when `rich_messages` is enabled *and* the
  text actually contains a rich construct — a fenced code block, a table row or
  separator, a task list, a `[text](url)` link, bold, italic, a `<details>`
  block, or `$$` math. The detector is deliberately conservative, requiring a
  table to lead its line with `|`, so a line like `/goal [condition|clear]` in
  `/help` never trips it. ([#5470])
- **community:** The InfoQuest reader, web search and image search called
  `requests` with no transport timeout, so a stalled endpoint left the
  synchronous worker waiting indefinitely even when the remote crawl `timeout`
  field was configured. All three call sites now share a 30-second connect/read
  inactivity bound; crawl timeout and navigation payload fields, successful
  parsing and the existing `Error:` returns are unchanged. This bounds
  inactivity, not total wall-clock time. ([#5315])
- **models:** The request-admission limiter decided immediate admission and
  queue insertion under two separate lock acquisitions, so a blocking caller
  could observe that the next permit was not yet due, be descheduled before it
  enqueued, and then be overtaken by a newer caller once the permit came due
  while the waiter queue was still empty — the newcomer took the permit and the
  older caller waited a further interval, or under a short `max_wait_seconds`
  timed out while the later request succeeded. Immediate admission and FIFO
  insertion are now a single lock-protected decision. Non-blocking calls still
  fail fast and never enter the queue, and queued pacing, cancellation,
  timeout, queue-capacity and no-burst behavior are unchanged. ([#5459])
- **uploads:** Uploaded-document outlines counted any line starting with `#` as
  a heading, so a document with 51 `#tag` lines before `# Real section`
  consumed every outline slot and hid the real section; four-space and
  tab-indented comments became false headings, and optional closing hashes
  stayed in the titles. The extractor now matches root-level ATX syntax on the
  original line — one to six hashes, a space or tab separator or end of line,
  at most three leading spaces — and strips valid closing hashes before the
  existing bold cleanup. Physical line numbers, PDF structural headings,
  fenced-code exclusion and the heading-count limit are unchanged, and the
  scanner stays bounded rather than becoming a Markdown parser. ([#5316])
- **uploads:** A single 200,000-character paragraph produced a
  199,999-character upload preview despite the five-line limit, and long valid
  headings bypassed the 50-entry limit as a practical context-size bound.
  Outline titles are now capped at 200 characters and fallback preview text at
  2,000 characters across all lines, with the omission markers counted inside
  those budgets. Physical line numbers, short text, the existing heading and
  preview counts, and the original file bytes are preserved; this bounds
  returned summary text only, not file-scan memory or a budget across uploads.
  ([#5323])
- **doctor:** On a fresh clone, `make config` followed by `make doctor`
  reported four errors where only one was real: `config.example.yaml` ships a
  `models:` key with every entry commented out, which parses as `None`, so the
  `[]` default in `.get("models", [])` never applied and a broad `except`
  rendered the resulting `TypeError` as three `'NoneType' object is not
  iterable` check results. A new user saw what looked like a broken install at
  the exact moment `make doctor` is meant to reduce confusion, when they had
  simply not configured a model yet. The LLM checks now skip when no models are
  configured, leaving the actionable `models configured` failure and its `make
  setup` hint; nothing changes once a model is configured. ([#5296])
- **scripts:** `detect_uv_extras.py` resolves uv extras from `config.yaml` so
  `make dev` does not wipe optional dependencies on every restart, but it had
  no rule for Ollama — so with an Ollama model configured it returned nothing,
  `serve.sh` ran `uv sync` without `--extra ollama`, and `langchain-ollama` was
  uninstalled from a working setup. The configured model then failed with
  `ModuleNotFoundError: No module named 'langchain_ollama'` with nothing
  pointing back at `make dev` as the cause, even though `make doctor` had just
  reported the package installed. Configuring an Ollama model now makes `make
  dev` pass `--extra ollama`, the same way `database.backend: postgres` passes
  `--extra postgres`; a config without an Ollama model is unaffected, and the
  commented-out Ollama examples in `config.example.yaml` are correctly ignored.
  ([#5318])
- **docker:** On Windows Git Bash, `make docker-start` and `make up` aborted
  unconditionally with `Docker socket not found at /var/run/docker.sock —
  AioSandboxProvider (DooD) will not work.` MSYS2/Git Bash has no physical Unix
  socket at that path — Docker Desktop uses named pipes — even though the
  daemon natively handles mounting `/var/run/docker.sock` into Linux
  containers, so the check could never pass. Under `MINGW*`, `MSYS*` and
  `CYGWIN*` the preflight now verifies `docker info` connectivity instead of
  requiring a socket file; POSIX hosts still fail fast on a missing socket.
  ([#5371])
- **deploy:** `make up` failed on Windows Git Bash during container startup
  with `mkdir C:\Program Files\Git\var: Access is denied.` `scripts/deploy.sh`
  exported `DEER_FLOW_DOCKER_SOCKET=/var/run/docker.sock`, and MSYS converted
  that exported value into a Windows host path when invoking native `docker
  compose`, so `docker-compose.dood.yaml` mounted `C:\Program
  Files\Git\var\run\docker.sock` and the daemon tried to create a directory
  that does not exist on the host. The socket is now kept in an unexported
  local variable, as `scripts/docker.sh` already did, and on Windows Git Bash
  the variable is unset when it holds the default so Compose expands its own
  literal `/var/run/docker.sock`; an operator-set custom socket path is still
  passed through. ([#5402])
- **mcp:** Exclude the internal stdio MCP temp directory (`.mcp/tmp`) from
  workspace changes, so MCP temporary and debug files no longer appear
  alongside user deliverables or crowd real changes out of the file budget.
  ([#4898])
- **mcp:** Cancel the remote task when a durable task submission is cancelled
  mid-flight, so an interrupted submission no longer leaves a remote task
  running with no record to poll or stop. ([#4933])
- **sandbox:** Accept the documented E2B reconciliation config fields, so
  valid E2B configuration no longer produces misleading startup warnings.
  ([#4772])
- **sandbox:** Bound E2B mount upload resource use per file, per mount, and
  across the whole upload pass (shared size and file budgets plus a
  wall-clock deadline), so large mounts can no longer spike Gateway memory
  or hold sandbox capacity indefinitely. ([#4812], [#4842])
- **sandbox:** Preserve trailing whitespace in E2B-synced filenames and
  tolerate out-of-range remote mtimes, so output sync no longer re-downloads
  files repeatedly or aborts mid-sync. ([#4861])
- **sandbox:** Reject non-finite Redis lease-timing values in sandbox
  ownership config at parse time instead of crashing with an `OverflowError`
  during startup. ([#4960])
- **sandbox:** Resolve structured skill reads through the sandbox provider's
  path mappings, so `read_file` opens legacy and per-user custom skills
  under the same enabled-state projection as `ls` and shell execution.
  ([#4792])
- **skills:** Parse Responses API content blocks in the moderation scanner,
  so valid skill-management decisions returned as content blocks are no
  longer rejected as unparseable. ([#4936])
- **memory:** Reject non-positive and non-finite timeout and character-limit
  settings in the Honcho and Mem0 backends at config parse time, so a bad
  value fails fast instead of silently truncating stored text or crashing on
  the first HTTP call. ([#4783], [#4823])
- **memory:** Scope custom-agent bootstrap facts to the selected agent's
  bucket, so facts learned during setup no longer leak into the default
  bucket and influence ordinary lead-agent conversations. ([#4804])
- **artifacts:** Support atomic saves on Windows, and serve a SHA-256 ETag on
  artifact reads so inline preview and editing work on non-secure contexts
  such as plain-HTTP LAN origins where `crypto.subtle` is unavailable.
  ([#4629], [#4865])
- **frontend:** Keep conversation order stable around long runs: the
  submitted user message no longer renders twice or sinks below its own
  processing steps, and after a mid-run page reload a turn's steps can no
  longer appear above the user message that started the run. ([#4620],
  [#4660], [#4834])
- **frontend:** Stop matching `<header>` as `<head>` when injecting the base
  href into HTML artifact previews, so relative assets in report fragments
  that begin with `<header>` now load in the sandboxed preview iframe.
  ([#4625])
- **frontend:** Open landing-page case studies on a public read-only
  `/showcase/` route so anonymous visitors are no longer redirected to
  login. ([#4635])
- **frontend:** Sort the chats page by pinned state, so pinned threads no
  longer render below unpinned ones. ([#4643])
- **frontend:** Keep `<think>` pairs written inside markdown inline code in
  the rendered content instead of hollowing them out into the Reasoning
  panel, and restore the copy button for turns that contain only reasoning.
  ([#4647])
- **frontend:** Surface model-loading failures with a workspace error banner
  and retry action instead of a silently empty model list. ([#4840], [#5021])
- **frontend:** Preserve copy and other actions on completed assistant
  messages while a later turn is still streaming. ([#4844])
- **frontend:** Keep the browser live stream connected after a successful
  reconnect instead of tearing down the new socket and immediately creating
  another. ([#4951])
- **frontend:** Reuse the shared clipboard fallback when copying the Lark
  authorization link, so the copy action works in browsers without the
  Clipboard API. ([#4767])
- **frontend:** Use consistent "DeerFlow" casing in the composer disclaimer
  and fix the "What's New" heading on the landing page. ([#4970])
- **channels:** Bound inbound intake with a fixed worker pool and bounded
  admission queues, and await real cross-thread tasks on shutdown, so
  message floods are rejected promptly instead of accumulating and channel
  shutdown no longer tears down transports with work still in flight.
  ([#4800], [#4816])
- **channels:** Offload outbound attachment file IO for Feishu, Telegram, and
  WeCom to worker threads, so sending a large artifact no longer stalls the
  Gateway event loop. ([#4633])
- **channels:** Run Telegram connection-identity lookups on the Gateway event
  loop, so inbound messages and commands no longer crash with a cross-loop
  error when channel connections are enabled. ([#4815])
- **feishu:** Keep file receiving off the event loop and preserve every
  inbound attachment: duplicate provider filenames no longer overwrite each
  other, writes can no longer be redirected outside the thread bucket, and a
  failed attachment no longer blocks the rest of the message. ([#4627],
  [#4903])
- **dingtalk:** Strip leading `@bot` mentions before command classification,
  so slash commands like `/new` sent in group chats are recognized instead
  of treated as plain chat. ([#4724])
- **discord:** Refuse to start typing-indicator loops after the channel
  stops, so shutdown no longer leaves an infinite typing task sending
  events in the background. ([#4752])
- **wecom:** Serialize WebSocket start/stop transitions and await the SDK's
  real receive-task shutdown, so stopping the WeCom channel can no longer
  return before the socket closes or clear a newer connection's state.
  ([#4762])
- **buzz:** Drop replayed events across reconnects using a persistent
  seen-id store, so the agent no longer re-answers the last message in a
  channel after a relay or Gateway restart. ([#4888])
- **lark:** Keep the CLI lock directory writable inside sandboxes while the
  credential-bearing config root stays read-only, restoring Lark API
  commands that previously failed with a read-only filesystem error.
  ([#4701])
- **scheduler:** Enforce the global `max_concurrent_runs` budget for manual
  triggers too, returning HTTP 409 when the cap is reached instead of
  letting manual launches exceed it. ([#4769])
- **scheduler:** Coerce serialized task timestamps on read, so
  scheduled-task operations no longer fail when string-form timestamp values
  reach the database layer. ([#4785])
- **scheduler:** Support safe multi-instance scheduler recovery: startup no
  longer treats live runs owned by peer Gateway instances as local
  leftovers, so a restarting instance cannot interrupt a live run or trigger
  a duplicate execution; multi-instance mode is opt-in via
  `scheduler.multi_instance`. ([#4713])
- **scheduler:** Enqueue busy scheduled task runs instead of skipping them:
  occurrences that hit a busy reused thread now wait in a durable queue
  (bounded by `scheduler.queue_timeout_seconds`) and survive Gateway
  restarts, and the UI explains the queueing behavior. ([#4918])
- **cli:** Add `--recursion-limit` to headless `--print`, `--json`, and
  `--cli` runs, so long-running agent loops are no longer stuck at the
  default recursion limit of 100. ([#4615])
- **dev:** Exclude backend runtime state from the Uvicorn reload watcher in
  the backend `make dev` launcher, so an agent task writing files under the
  runtime tree can no longer restart the Gateway and reset concurrent
  users' requests. ([#4759])
- **dev:** Resolve diagnostic script paths from the script's own location, so
  root diagnostic commands work when invoked from any working directory.
  ([#4736])
- **docker:** Harden local and container startup: `make up` waits for the
  Gateway health probe before declaring the stack ready, Docker startup no
  longer aborts when `.env` is missing, the Gateway can write
  `extensions_config.json` in production, runtime data stays out of the
  image build context, log commands resolve the checkout root correctly,
  and the default loopback origins are allowed so the dev setup page can
  hydrate. ([#4658], [#4806], [#4852], [#4853], [#4956], [#4959])
- **gateway:** Stamp the server-authoritative feed position onto persisted
  messages, so an early user message no longer vanishes or jumps into the
  middle of the step stream once history exceeds one page and context
  compaction has fired. ([#4696])
- **lark:** Preserve the new app secret during managed credential switches by
  clearing the previous app's OAuth data before the replacement is written,
  so the subsequent browser authorization no longer resolves an empty
  `client_secret`. ([#4820])
- **messages:** Drop legacy `<uploaded_files>` tag handling: the backend treats
  the pre-#4174 spelling as ordinary content and strips only
  `<current_uploads>`, while the frontend keeps stripping the legacy tag so
  old threads still render cleanly. ([#4826])
- **skills:** Reject a blank `SKILL.md` description at the write gate, matching
  what the loader already requires, so editing a custom skill with an empty
  description no longer writes a file the loader then rejects - which
  destroyed the skill on disk. ([#4867])
- **sandbox:** Make the model-facing `description` argument optional (empty by
  default) across `bash`, `ls`, `glob`, `grep`, `read_file`, `write_file`,
  `str_replace`, and `task`, so providers that omit it are no longer rejected
  before execution. ([#4878])
- **sandbox:** Bound Windows command execution: host commands run in a new
  process group killed via `taskkill /T /F` on timeout so a descendant cannot
  hold the call open, and output flows through the existing bounded 10 MiB
  capture. ([#4946])
- **sandbox:** Scope the Windows MSYS path-conversion exclusion to safe virtual
  path prefixes instead of disabling conversion globally, so host-native CLI
  launchers that need normal conversion work again. ([#5003])
- **skills:** Rebuild per-user skill storage after an app-config hot reload,
  so it no longer stays bound to paths from the previous config instance.
  ([#4972])
- **skills:** Tokenize portable `allowed-tools` scalars with parenthesis
  awareness, so `Bash(tvly *)`-style entries stay intact, unmatched
  parentheses are rejected instead of silently fragmenting, and
  argument-scoped entries remain literal rather than broadening access.
  ([#4984])
- **agents:** Normalize `ToolMessage`s returned inside `Command` results, so
  error payloads no longer earn a default success receipt and tool-progress
  tracking sees them. ([#4977])
- **config:** `use_previous_response_id` works in a `config.yaml` model entry —
  it is not a `ModelConfig` field and reaches `ChatOpenAI` only through the
  model factory's `extra="allow"` passthrough — but was never documented, and
  reads like a synonym for `use_responses_api`. It is not: `use_responses_api`
  picks the endpoint, while `use_previous_response_id` switches the Responses
  API from replaying the full history each turn to chaining on server-side
  state. The OpenAI Responses API example in `config.example.yaml` gains a
  commented `use_previous_response_id: false` line noting that it is forwarded
  to `ChatOpenAI` as-is, that chained context is still billed as input tokens,
  and that client-side history rewrites only apply when the history is
  replayed. Comment only — no schema change, no new `ModelConfig` field, no
  `config_version` bump. ([#5359])
- **mcp:** Tear down the in-flight session owner when `get_session` is
  cancelled during eviction, so a cancelled caller no longer leaks the owner
  task or parks past its timeout. ([#5008])
- **mcp:** Reconnect ordinary stdio tools after a transport disconnect: the
  failed pooled session is evicted (only if still registered), the original
  error surfaces without automatic replay, and a later retry starts a fresh
  subprocess. ([#5018])
- **mcp:** Preserve pooled stdio sessions after protocol timeouts during
  durable MCP task polling - a 408 is not a disconnect - so task state
  survives and the next poll no longer reports `task_not_found`. ([#5027])
- **mcp:** Reject credentials that cannot travel as HTTP header values
  (trailing newline or whitespace, non-ASCII) at the config boundary, so the
  transport's exception - which echoes the full value - can no longer leak a
  secret into model context, checkpoints, and traces. ([#5066])
- **subagents:** Clean up the background-task entry when the poller exits
  unexpectedly and drop a PENDING registry entry when submission fails, so a
  failed or crashed poll no longer leaks the entry or leaves the subagent
  running unattended. ([#5069])
- **subagents:** Stop the zombie PENDING registry entry on the submit-failure
  path, and derive the capacity snapshot's queued count from the waiters'
  length instead of iterating a deque other threads mutate. ([#5086])
- **channels:** Synchronize `ChannelStore` reads with mutations, so
  `get_thread_id()`/`list_entries()` can no longer raise `dictionary changed
  size during iteration`. ([#5083])
- **discord:** Retain strong references to ack-reaction tasks and drain them
  on shutdown, so a GC pass can no longer silently drop a reaction or pin the
  channel across restart cycles. ([#5049])
- **buzz:** Move seen-event persistence off the event loop with coalesced
  atomic writes, preserving dirty generations when events arrive mid-write
  and awaiting the final flush on shutdown. ([#5103])
- **streaming:** Stop an `IndexError` in `MemoryStreamBridge._make_gap` when a
  subscriber reconnects to an empty or drained stream with an expired cursor.
  ([#5047])
- **uploads:** Keep deduplicated filenames within the 255-byte limit by
  truncating the stem on a UTF-8 code-point boundary, so two max-length files
  that differ only by a dedupe suffix upload successfully instead of failing
  the whole batch. ([#5059])
- **frontend:** Format structured upload error details (FastAPI validation
  issues, objects, arrays) instead of showing `[object Object]`. ([#5071])
- **frontend:** Keep a renamed thread's title in sync across the active chat
  header, document title, search results, and metadata caches without a
  reload. ([#5045])
- **frontend:** Truncate selected model names to the selector button width, so
  long model names ellipsize in the composer and sidecar instead of
  overflowing. ([#5050])
- **frontend:** Truncate long subtask card titles to one line with a tooltip,
  so a delegation whose model omitted `description` (falling back to the full
  prompt) no longer overflows the chat layout. ([#5136])
- **dev:** Default the frontend dev server to Webpack on all platforms
  (`DEER_FLOW_DEV_BUNDLER=turbo` opts back into Turbopack), avoiding
  Turbopack's macOS PostCSS worker leak and its Windows runtime panics.
  ([#5036], [#5133])
- **scripts:** Run repo shell scripts through an explicit interpreter
  (`bash scripts/...`), so a lost executable bit - zip/tarball downloads,
  `core.fileMode=false`, non-POSIX filesystems - no longer breaks
  `make docker-start` and friends with `Permission denied`. ([#5031])
- **deps:** Depend on the renamed `tenki` package instead of the PyPI-removed
  `tenki-sandbox` (same `tenki_sandbox` import), so clean checkouts can
  resolve dependencies again on `make dev`/`uv sync`. ([#5087])
- **memory:** Memory reads configured to stop the turn now raise a
  backend-neutral `MemoryReadError` that prompt assembly preserves instead
  of swallowing: strict OpenViking (`read: raise`), Mem0, and Honcho reads
  propagate, OpenViking scope-resolution failures follow the configured read
  policy, and the 5-second injection deadline honors the same policy
  (fail-open continues without the context; strict raises with the timeout
  as its cause). ([#4726])
- **persistence:** Add the storage foundation for a per-thread incarnation
  token without activating it. New nullable `threads_meta.incarnation` and
  `mcp_tasks.thread_incarnation` columns (a new Alembic head) let a task be
  tied to the specific thread a reused thread ID belongs to, since a deleted
  thread's ID can be taken by a later thread while durable MCP work outlives
  the deletion. A random 32-character incarnation is assigned to newly created
  thread records and copied into new MCP task rows only when the thread is
  owned by the task user or is an unowned legacy row, with the lookup and
  insert kept atomic on SQLite through a scalar subquery and a share lock on
  PostgreSQL. Nothing reads the fields yet, they are kept out of the thread and
  MCP task API responses, and both columns are nullable with no default so
  older binaries keep writing during a rolling deployment. ([#5216])
- **scripts:** On native Windows, `shutil.which("pnpm")` follows
  `PATH`/`PATHEXT` resolution and can select a generic `pnpm` match — an `.exe`
  or `.bat`, or an earlier-path wrapper — ahead of the npm-installed `pnpm.cmd`
  wrapper. The shared host runner now checks `pnpm.cmd` and `corepack.cmd`
  before the generic names, matching the Windows command-selection order the
  repo already documents; POSIX resolution order is unchanged. ([#5305])
- **tests:** The backend suite failed 68 shell-script tests across seven files
  on a Windows contributor host, none of them for anything wrong with the code
  under test. CreateProcess searches `System32` before `PATH`, so the WSL
  `bash.exe` launcher won every `["bash", ...]` spawn and could not run the
  repo scripts against Windows checkout paths — on non-English Windows its
  localized UTF-16LE warning crashed the harness's pipe decoding and buried the
  real failure behind a `TypeError`; `sh` does not exist outside MSYS2; and
  `dev-entrypoint.sh`'s `command -v python3` probe selected the Microsoft Store
  alias stubs, which exit 49 when executed. The suites now resolve a shell
  through a shared helper that mirrors the repo's Git Bash wrapper discovery
  and explicitly rejects the WSL launcher and the Store stubs, and skip cleanly
  where no Git Bash exists. POSIX and CI behavior is unchanged. ([#5404])
- **tests:** Six tests across three suites failed on a Windows host purely on
  path-separator spelling. The provisioner's `join_host_path` deliberately
  preserves host-native style and even has an explicit `PureWindowsPath`
  branch, and `os.path.normpath` re-spells POSIX inputs with backslashes there,
  so the `hostPath` strings it builds, the docker `--mount` `src=` spelling,
  and the review CLI's `PYTHONPATH` never matched POSIX-style literals. The
  assertions now normalize the host-native side before comparing, which is a
  no-op on POSIX so CI expectations stay byte-identical; production behavior is
  unchanged. ([#5413])
- **tests:** Five tests in the skill request-scoped-secrets suite failed on a
  Windows host and two negative checks passed vacuously, because the probes
  embedded POSIX syntax: `LocalSandbox._get_shell()` resolves to PowerShell
  there, where `$VAR` is an undefined PowerShell variable and expands to
  nothing, so the positive checks could never see an injected value and the
  `"secret" not in out` assertions were comparing against empty output. Probes
  are now rendered in the syntax of the shell production actually resolved —
  `$env:NAME` under PowerShell, `%NAME%` under cmd.exe, `$NAME` under POSIX
  shells — so the negative checks genuinely verify scrubbing on Windows, and
  the per-call-scoping case also proves the injected value reached the first
  subprocess. POSIX output is unchanged in form. ([#5415])
- **tests:** `test_run_on_isolated_subagent_loop_survives_caller_loop_teardown`
  failed intermittently under CI load, on unrelated PRs and on `main` itself.
  The race was in the test, not in `run_on_isolated_subagent_loop`: that helper
  is `asyncio.run_coroutine_threadsafe`, whose `concurrent.futures.Future` is
  only marked done after the coroutine returns, but the test signalled from
  inside the coroutine and asserted `done()` immediately, so the main thread
  could wake while the future was still `pending`. The assertions now block on
  `result(timeout=10)` before checking `done()`; no `sleep` is introduced and
  the behavior under test is unchanged. ([#5299])
- **tests:** Checkpoint retention needs an executable statement of what a
  deletion may never break — a newest-N proposal had to be withdrawn once
  review showed it would silently break branch and time-travel parent-chain
  semantics. The new suite pins six retention scenarios across the memory,
  SQLite and Postgres checkpointers: growth baselines per step for the full and
  delta schemas; deleting a branch ancestor fails loudly with
  `CheckpointLineageError` instead of silently corrupting branch/regenerate;
  deleting an explicit resume target removes the resume surface; pending writes
  are retained state rather than garbage; and a trailing duration-only leaf and
  a leaf sibling branch — the real fork path — can be deleted safely. A
  companion draft documents the protected set, the provably safe deletion
  shapes, and joint-table mechanics with orphan accounting, for any future
  `max_checkpoints_per_thread` or TTL work to be validated against. ([#5255])
- **memory:** Buffered memory extraction is cancelled when a custom agent is
  deleted or cleared, so pending debounce timers can no longer resurrect the
  deleted per-agent memory scope or overwrite a fresh clear with a stale
  pending update. ([#5123])
- **agents:** Conversation titles are generated from the user's original
  message content when upload (or other) context wrappers have been injected
  into the text, so titles no longer quote server-injected
  `<current_uploads>` context; attachment-only messages keep the
  `New Conversation` fallback. ([#4729])
- **agents:** Fraction summarization triggers resolve against the model's
  declared `context_window` (now translated into the LangChain profile), and
  an unresolvable fraction clause degrades to a never-firing trigger with a
  warning instead of crashing the whole agent build; percent-style and
  non-finite trigger values are rejected at config load. ([#4901])
- **agents:** Custom-agent storage falls back to file-backed storage only
  when search mode cannot resolve the main application config — invalid
  configuration and missing config paths surface instead of silently
  switching storage backends — and store IO moves off the event loop in
  async agent routes. ([#4952])
- **middleware:** Loop-detection hard stops win across a whole tool-call
  batch: selecting a soft warning no longer ends inspection, so a later call
  in the same response that crosses an operator-configured hard limit is
  rejected instead of riding along with the earlier warning. ([#5245])
- **sandbox:** `list_dir` and `glob` in the five remote sandbox providers
  (E2B, OpenSandbox, AIO, Tenki, BoxLite) return filenames verbatim instead
  of stripping whitespace, so files whose names begin or end with spaces are
  no longer listed under paths that then do not exist. ([#4980])
- **sandbox:** Concurrent subagents sharing one thread sandbox run under
  process-local execution leases with task-scoped AIO shell sessions, so one
  sibling finishing can no longer release the shared sandbox underneath the
  others or corrupt the implicit persistent session; a healthy replacement
  session is promoted after corruption instead of returning to it. ([#5134])
- **sandbox:** The Bash tool guides the agent to detect its execution
  environment with evidence (`uname -s`, `sw_vers`, `uname -a`) instead of
  model assumptions, and rejected host paths direct it to command-only
  probes or allowed virtual paths rather than repeating the blocked command.
  ([#5111])
- **sandbox:** The Docker AIO compatibility capability allowlist gains
  `FOWNER`, so AIO images whose startup `chmod`s `/run/user/1000` (e.g.
  1.11.0) start again under the hardened default capabilities while
  `no-new-privileges` stays on. ([#5163])
- **sandbox:** File appends no longer destroy existing content when the
  pre-read fails: E2B append treats only missing-file errors as an empty
  file and re-raises anything else instead of overwriting the file with just
  the appended tail, and AIO appends use the server's native append mode
  without a pre-read at all. ([#5261], [#5278])
- **skills:** Skill markdown is read explicitly as UTF-8, so localized skills
  validate on Windows hosts whose default code page is not UTF-8 instead of
  failing with `UnicodeDecodeError`. ([#4995])
- **mcp:** The MCP tools cache re-initializes after a runtime config change:
  a module-level `asyncio.Lock` bound to a closed event loop and an
  unsynchronized initialized flag had left every post-update call failing
  with `Lock is bound to a different event loop` or racing across worker
  threads. ([#5062])
- **mcp:** Sync-wrapped MCP tools keep LangGraph `ToolRuntime` injection (the
  annotation-less sync wrapper is now `functools.wraps`-transparent), so
  per-user scope resolution and durable task submission no longer run with
  `runtime=None` — which had routed completion-notification runs under the
  default lead agent instead of the thread's custom agent. ([#5164])
- **auth:** A duplicate OAuth identity no longer reports "Email already
  registered" — the two integrity violations are distinguished — and the
  partial OAuth-identity index now declares `postgresql_where` so Postgres
  builds the intended partial index instead of a full one. ([#5026])
- **frontend:** The mobile sidebar trigger stays clickable on regular and
  custom-agent welcome pages, where multi-line (longer localized) welcome
  text in a same-`z-index` overlay could cover the header's tappable area.
  ([#5149])
- **subagents:** `SubagentResult` lifecycle timestamps are UTC-aware on
  every writer, matching the repo-wide convention instead of stamping local
  wall-clock time on non-UTC hosts. ([#5153])
- **browser:** Background live-frame scheduler tasks retain strong
  references, so garbage collection can no longer silently stop the Browser
  Live view from refreshing by stranding a pending guard that was cleared
  only in a collected task's `finally`. ([#5155])
- **runtime:** Duplicate `on_llm_end` callbacks for the same LangChain run id
  persist one durable `llm.ai.response` event (replayed usage merged by
  generation position, first callback canonical), so append-only message
  APIs no longer return duplicate responses from providers that re-fire the
  callback with usage populated. ([#5187])
- **runtime:** Terminal finalization completes after a cancellation raised
  inside the completion hook or task-stop fan-out, so extension observers
  run and the stream END marker is published before the interruption is
  re-raised; the finalization tail stays interruptible. ([#5191])
- **models:** A cancelled LLM call releases its owned circuit-breaker
  recovery probe across provider execution, concurrency admission, and
  backoff, so subsequent calls no longer see `CircuitBreakerOpen` after a
  cancellation; probe ownership is fenced by a per-call token so cancelling
  an older call cannot release another call's probe. ([#5197])
- **runtime:** The embedded `DeerFlowClient` keys its graph cache by
  effective user in every authorization mode and materializes the same user
  in runtime context, so sequential reuse for different users can no longer
  serve a graph assembled with another user's prompt and workspace state.
  ([#5206])
- **runtime:** Cancelled workspace-change snapshot captures drain their
  already-running scan and clean up the per-run text cache instead of
  leaking `deerflow-workspace-changes-*` directories, while metadata-only
  captures propagate cancellation promptly without waiting on the scan.
  ([#5232], [#5234])
- **persistence:** Gateway startup tolerates a database already migrated to
  the explicitly-reviewed newer revision (`0019_thread_incarnations`), so
  rolling back to this image after a newer deployment stays possible; other
  unknown revisions, an empty version table, and multiple version rows
  still fail closed. ([#5219])
- **community:** Tavily Extract results without a `title` fall back to the
  result or requested URL as the display heading instead of raising
  `KeyError` and discarding usable page content. ([#5280])
- **uploads:** Fenced code blocks are excluded from uploaded-document
  outlines, so code comments and bold examples inside fences no longer
  crowd real sections out of the 50-entry heading budget. ([#5281])
- **subagents:** After compaction, the delegation ledger distinguishes
  execution completion from task acceptance and preserves bounded examples
  of a completed subagent's unmet and unverified acceptance criteria, so the
  lead agent repairs the remaining gaps instead of treating the completed
  result as fully done. ([#5287])
- **dev:** `_pick_python()` validates interpreter candidates through
  `/usr/bin/env`, mirroring how the frontend is launched, so `make dev`
  starts the frontend on Windows where Microsoft Store Python stubs satisfy
  Bash-side probes but not `env`. ([#5181])

### Performance

- **runtime:** Index `MemoryRunStore` by `thread_id` and `MemoryRunEventStore`
  events by `run_id` to avoid O(n) scans. ([#3562], [#3686])
- **subagents:** Deduplicate streamed AI messages via a seen-id set (O(n²) ->
  O(n)). ([#3687])
- **sandbox:** Cache `LocalSandbox` path-rewrite regexes and local-path masking
  patterns per instance instead of recompiling per search match. ([#3648],
  [#3713])
- **messages:** Index tool-call results per group. ([#4411])
- **frontend:** Coalesce streaming renders to a frame budget instead of per
  chunk. ([#4425])
- **frontend:** Stop re-deriving message content on every stream chunk.
  ([#4441])
- **sandbox:** `read_file` reads only the requested line range from the
  sandbox instead of fetching the whole file first. ([#3824])
- **browser:** Encode Browser Live progress frames as JPEG to cut progress
  payload size. ([#4836])
- **middleware:** Inject `view_image` content via `wrap_model_call` instead of
  a checkpointed hidden message, so up to 20 MB of base64 no longer sits in
  two checkpoints per viewed image and an interrupted run can no longer leave
  the payload behind. ([#5014])
- **frontend:** Cache settled copy-data derivation across streaming chunks, so
  each chunk no longer re-derives toolbar/copy text for every settled
  message. ([#5095])
- **runtime:** Bound gateway memory after terminal runs, stopping the post-GC
  low-water mark from creeping upward across completed sessions. ([#5112])
- **frontend:** Chat streams request `messages-tuple` + `updates` + `custom`
  instead of full `values` state snapshots — the retransmitted historical
  `values` messages were ~75% of SSE payload — folding reducer events into
  rendered state locally while keeping full snapshots only for replay-gap
  recovery. ([#5159])

### Security

- **skills:** Close gaps that let files skip SkillScan in the public skill
  review gate. The review analyzer passed SkillScan only files it had decoded
  as text, so executable binaries and nested archives were never checked; it
  exempted every file anywhere under an `evals/fixtures/` directory; and a
  duplicate archive member or a case-folded name silently overwrote an earlier
  file before scanning. SkillScan now receives every file byte for byte, only
  eval fixture `SKILL.md` samples stay exempt, and path collisions mark the
  review incomplete. SkillScan also skipped code files containing a NUL or
  non-UTF-8 byte, so one byte in a comment hid a reverse shell from the review
  gate, and a NUL byte skipped static analysis at install. Such files now raise
  `package-undecodable-script` and are still analyzed, so `CRITICAL` matches
  keep blocking. SkillScan's Mach-O detection missed 32-bit little-endian and
  fat variants that the installer blocks; the installer, export guard, and
  SkillScan now share one code-file and executable-magic definition. Review
  snapshots gain a `content_base64` field for binary files. ([#5431])
- **prompt-injection:** New input-sanitization middleware defends against
  prompt-injection, forged framework tags in the input guardrail are blocked,
  and system context is injected as a `SystemMessage` for role isolation. ([#3662],
  [#4155], [#3661])
- **prompt-injection:** HTML-escape untrusted content rendered into model prompts
  - memory facts and summaries, `SOUL.md`, subagent descriptions, skill metadata,
  and the conversation block in the memory-update prompt - and neutralize
  prompt-injection tags in `web_capture` tool results. ([#4028], [#4119], [#4137],
  [#4157], [#4162], [#4099], [#4060], [#4097], [#4128])
- **prompt-injection:** Escape MindIE tool-response framing. The provider's
  `_fix_messages` escaped tool-call names and arguments before rendering them
  into `<tool_call>` / `<function=...>` tags, but the sibling path that wraps a
  `ToolMessage` in `<tool_response>` passed its text through unescaped — and
  that output arrives largely unsanitized, because the tool-result sanitizer
  covers only the remote-content tools on its allowlist (`web_fetch`,
  `web_search`, `image_search`, `web_capture`) and deliberately leaves local
  `bash` / `read_file` output and differently named MCP tools alone. A literal
  `<tool_response>` in a `read_file` result therefore closed the framing early,
  and everything after it was presented to the MindIE model as though it sat
  outside the tool response, so a payload planted in an untrusted file could
  forge a `<system-reminder>`. Content is now HTML-escaped with `quote=False`,
  matching the tool-call path; the model still decodes the entities back, so
  only the framing is protected and legitimate results are understood exactly
  as before. ([#4253])
- **prompt-injection:** Close two input-sanitization bypasses.
  `hide_from_ui` and a human `name="summary"` tell `is_genuine_user_message`
  that the framework
  authored a message, which skips sanitization entirely. Untrusted run input and
  thread-state writes carrying either marker are now marked server-side and
  sanitized regardless, so a caller can no longer land a raw `<system-reminder>`
  outside the user-input boundary markers that the lead-agent prompt declares
  trusted framework data. The markers themselves are preserved, so messages that
  use `hide_from_ui` only to stay out of the transcript — quoted conversation
  context, sidecar context, the agent save command, HumanInputCard replies — keep
  doing that, and trusted internal launchers are unaffected. Sanitization also
  covers every genuine user message instead of only the newest: the
  transformation is request-scoped, so a last-turn-only scan neutralized a
  payload for exactly one model call and then replayed it verbatim from the next
  turn on. ([#5375])
- **secrets:** Scrub inherited secret environment variables (`MYSQL_PWD`,
  `REDISCLI_AUTH`, abbreviated `*_PASS`, and Postgres `PGPASSFILE`) from the
  skill environment; request-scoped secrets are bound for both slash-activated
  and autonomously-invoked skills. ([#4018], [#4026], [#3871], [#3938])
- **web_fetch:** SSRF guard for self-hosted providers. ([#3942])
- **guardrails:** An empty allowlist now denies all tools instead of failing
  open. ([#4067])
- **authz:** Global skills-management endpoints now require admin; the legacy
  skills mount is gated by user visibility; artifacts honor a trusted
  `owner-user-id` header; and the trusted authorization principal is propagated
  through the runtime. ([#3855], [#3985], [#3982], [#4203])
- **auth:** Persist the `csrf_token` cookie for the access-token lifetime.
  ([#3872])
- **storage:** Stop persisting base64 image data in checkpoint state. ([#4140])
- **mcp:** Reject legacy MCP credentials in run metadata. ([#4448])
- **mcp:** Constrain stdio launcher arguments and environment variables at
  the config API, rejecting launcher flags and env names that could turn an
  allowlisted `npx`/`uvx` server registration into arbitrary code execution.
  ([#4617])
- **auth:** Harden validation of the post-login `next` path. ([#4587])
- **runtime:** Honor the LangGraph Server's authenticated user identity
  across agents, uploads, thread data, memory, and skills, and reject
  client-supplied auth identity fields. ([#4538])
- **frontend:** Send the session cookie on model, workspace-change, and
  ranged artifact reads in split-origin deployments. ([#4827])
- **frontend:** Restore sanitization in custom streamdown rehype chains, so
  artifact markdown previews and the memory settings summary can no longer
  render hostile HTML such as `javascript:` links or `on*` event handlers.
  ([#4987])
- **skills:** Copy projected skill files instead of hardlinking them, so a
  sandboxed write can no longer mutate the canonical skill source, and fail
  closed on a drifted projection namespace on every platform, including
  Windows. ([#4825], [#4830])
- **scripts:** Redact secret-shaped keys (`db_pass`, `signing_key`, ...)
  wherever they appear in bundled config, not only under well-known key
  names. ([#4242])
- **sandbox:** Sanitize MCP-sourced tool results through the same trust
  boundary as the built-in web tools, so a hostile or compromised MCP server
  can no longer hand the model forged `<system-reminder>` or user-input
  boundary tags. ([#4839])
- **sandbox:** Harden local Docker sandbox containers: published ports bind
  the Docker bridge gateway instead of `0.0.0.0` when the sandbox host is
  non-loopback (`DEER_FLOW_SANDBOX_BIND_HOST=0.0.0.0` restores the broad
  bind), Docker's default seccomp profile replaces unconditional
  `seccomp=unconfined` (opt back in with `DEER_FLOW_SANDBOX_SECCOMP_UNCONFINED=1`),
  and containers drop all capabilities, get `no-new-privileges`, and run with
  bounded resources. ([#4986])
- **authz:** Enforce run-create authorization on stateless stream/wait
  endpoints (`runs:create`), and require both `threads:write` and
  `runs:create` for scheduled-task create, update, resume, and manual-trigger
  mutations. ([#5030])
- **authz:** Re-check the authorization policy before reusing a persisted
  sandbox, so a revoked `sandbox:execute` grant takes effect on the next
  sandbox-backed turn instead of outliving the policy in the cached sandbox.
  ([#5006])
- **skills:** Enforce custom-Agent skill allowlists at the sandbox filesystem
  level: an explicit `skills` policy materializes a signed per-user/thread
  skills view, so a custom agent with shell or file tools can no longer read
  skills its policy excludes. ([#5077])
- **runs:** Reject cancel/rollback actions on GET stream joins with
  `405 Method Not Allowed` - cancel-then-stream is a POST operation - closing
  a state change that CSRF middleware deliberately exempted on safe methods;
  action-less GET joins are unchanged. ([#5092])
- **lark:** Lark CLI credential trees on Windows enforce private ACLs
  (gateway-SID-only protected DACL, reparse-point rejection, handle-relative
  traversal), extending the POSIX `0700`/`0600` confidentiality contract
  against inherited grants, junction redirection, hard-link aliasing, and
  TOCTOU replacement. ([#5141])
- **sandbox:** `SSH_AUTH_SOCK` is scrubbed from the sandbox subprocess
  environment — inheriting the host ssh-agent socket lets sandboxed code
  sign and authenticate with every key the agent holds — unless a skill
  explicitly declares it via required-secrets. ([#5145])
- **artifacts:** Serve XML artifacts as download attachments like HTML and
  SVG. `GET /api/threads/{id}/artifacts/{path}` rendered `.xml`, `.xsl`, and
  `.rdf` files — and `+xml` types such as `.rss` wherever the host MIME
  database maps them — inline in the application origin, so an XML document
  with an XHTML-namespaced `<script>`, written by a prompt-injected agent and
  opened from a chat link, could call the API with the viewer's session.
  Every XML MIME type (`text/xml`, `application/xml`, `text/xsl`, any `+xml`
  subtype) is now treated as active content, including `.skill` archive
  members; the artifacts panel keeps previewing XML through its ranged fetch.
  ([#5353])

### Documentation

- **docs:** Clarify how `LocalSandboxProvider` resolves `sandbox.mounts[].host_path`
  under production Docker, with gateway bind-mount and config examples. ([#3833])
- **docs:** Document that Crawl4AI >= 0.9 requires a bearer token. ([#4518])
- **docs:** Document the GitHub inbound-dedupe TTL semantics, including what
  redeliveries are not deduped, and tighten the redelivery tests. ([#4274])
- **docs:** Update the agent AGENTS.md and ARCHITECTURE.md guides. ([#4817])
- **docs:** Document the Honcho memory backend with a dedicated guide and a
  long-term memory section entry in the README. ([#4822])
- **docs:** Align custom-agent documentation with the API across the English
  and Chinese agents/threads/lead-agent pages: the required ASCII `name`
  request field, lowercase storage, `/api/agents/check` name-availability
  behavior, and no auto-derived slug from `display_name`. ([#4944])
- **docs:** Restructure the subagent documentation into an eleven-chapter user
  manual under `harness/subagents/` in both languages: concepts, quick start,
  the catalog, delegating work, results and acceptance, limits and capacity,
  sandbox and isolation, observability, troubleshooting by symptom, developer
  integration, and a reference appendix with the June to September 2026
  change log. The former single page becomes the section index, so existing
  page links keep working; deep links to sections of the old page now land
  on the index. ([#5761])
- **docs:** Add an extension developer manual under `harness/extensions/` in
  both languages, covering the `deerflow-extension-api` 0.2.1 contract: when
  to write an extension, a quick start, the runtime model, middleware
  placements, lifecycle and observer hooks, services and routes, the run
  evidence reader, operating extensions, troubleshooting by error message,
  and a reference of every public name with the contract's version history.
  Also correct stale descriptions of the contribution kinds and of run
  evidence metadata redaction in `AGENTS.md`. ([#5769])

### Internal

- **tests:** Migrate frontend unit tests to rstest and run hook-level tests in
  a DOM environment. ([#3703], [#4453])
- **tests:** Require explicit opt-in for live client tests. ([#4482])
- **tests:** Rename the LLM-error test stand-in instead of the shared
  FakeError. ([#4744])
- **tests:** Replace the magic unwritable absolute path in tool-output tests
  with a self-constructed failure condition. ([#4722])
- **tests:** Add multi-turn message-stream invariants as graph integration
  tests. ([#3708])
- **tests:** Add trace-based behavioral tests with Monocle Test Tools,
  asserting agent routing, tool calls, and token/duration cost. ([#4025])
- **tests:** Cover passive skill tool visibility in the MCP layer. ([#4247])
- **tests:** Add SQL and concurrent-reconciler coverage for lease-aware orphan
  recovery. ([#4427])
- **tests:** Restore memory updater regression coverage. ([#4490])
- **tests:** Lock in POST logout from the gateway-offline banner. ([#4506])
- **tests:** Document known instance-client false negatives in the SkillScan
  tests. ([#4644])
- **refactor:** Extract frontend placeholder detection into a tested utility.
  ([#3783])
- **refactor:** Consolidate E2B client lifecycle helpers and reuse the kill
  helper during warm-pool eviction. ([#4262], [#4298])
- **refactor:** Name the E2B capacity-ledger meta-field count so the admission
  offset is explicit. ([#4764])
- **dev:** Trace self/cls attribute chains and local aliases in the
  blocking-IO detector's call graph, closing false negatives. ([#4200])
- **ci:** Publish the lark-cli-init and lark-broker images. ([#4558])
- **dev:** Route host-side pnpm consumers through a shared runner with a
  Corepack fallback so local workflows work without a pnpm shim. ([#4405])
- **bench:** Add an isolated checkpoint channel-mode benchmark comparing `full`
  and `delta` across latency, storage, and replay metrics. ([#4395])
- **deps:** Bump `cryptography` 49.0.0 -> 50.0.0, `postcss` 8.4.31 -> 8.5.25,
  `h2` 4.3.0 -> 4.4.1, `langgraph-checkpoint-sqlite` and
  `langgraph-checkpoint-postgres` 3.1.0 -> 3.1.1, `nanoid` 5.1.6 -> 5.1.16,
  `h3` 1.15.6 -> 1.15.9, and `next` 16.2.11 -> 16.3.3. The `next` bump closes
  two unauthenticated remote code execution advisories — one in the Image
  Optimization API's AVIF path, one on Windows-hosted servers — while `h3`
  stops a double-encoded dot segment from traversing out of the static route.
  ([#4211], [#4681], [#4683], [#4737], [#4738], [#4747], [#4748], [#5377])
- **bench:** Add a reproducible hybrid memory-eviction evaluation under
  `backend/scripts/benchmark/deermem_eviction/` with a deterministic,
  blind-by-construction grader for the #4789 policy. ([#4810])
- **bench:** Measure Postgres checkpoint/blob/write storage growth in the
  checkpoint benchmark alongside memory and SQLite. ([#5051])
- **tests:** Exclude `tests/blocking_io/` from `make test`; the dedicated
  `make test-blocking-io` suite (and its CI workflow) remains the owner.
  ([#5105])
- **refactor:** Share sandbox identity derivation and acquire serialization
  across the five remote sandbox providers (RFC #4741), replacing five
  per-provider lock tables that grew unboundedly with process lifetime;
  derived ids are pinned byte-identical by per-provider golden vectors.
  ([#5089])
- **ci:** Split the backend unit-test workflow into four parallel shards —
  each on its own runner with isolated Postgres/Redis — using `pytest-split`
  with a committed duration baseline and failing closed when the baseline is
  missing; `make test` remains the canonical full offline suite.
  ([#5137])
- **dev:** Launch the Playwright `webServer`'s Next.js through `pnpm exec`,
  so Windows E2E runs resolve the platform package binary instead of failing
  on the extensionless POSIX shim. ([#5185])
- **tests:** Skip the POSIX mode-bit skill-permission assertions on Windows,
  where the `chmod` contract is unobservable, so Windows contributors can
  reach a green backend-suite baseline. ([#5244])
- **tests:** Pin the composer's skill suggestions against an empty skill
  catalog (RFC #4063 Phase 4): a caller whose `skills` policy allows nothing
  — or a fresh install with no skills — receives `[]` from `GET /api/skills`,
  and the composer must degrade to a builtin-only dropdown, never a broken
  or fully vanishing one. New tests drive the matcher and mount the real
  `InputBox` with an empty catalog: typing `/` offers exactly the builtin
  commands, and an unmatched query renders no listbox. No production code
  changed; all four `useSkills()` consumers were audited and already
  degrade gracefully. ([#5490])

## [2.0.0] — 2026-06-15

DeerFlow 2.0 is a ground-up rewrite around a "super agent" harness with
sub-agents, persistent memory, sandbox execution, and an extensible
skills/tools system. It shares no code with the 1.x line, which now lives on
the [`main-1.x` branch](https://github.com/bytedance/deer-flow/tree/main-1.x).

This release closes [milestone 2.0.0](https://github.com/bytedance/deer-flow/milestone/1)
with **180 merged pull requests** since the first 2.0 milestone tag.

### ⚠ Breaking changes

- **harness:** Hydrate runs from `RunStore` and persist interrupted status. Run
  cancellation/multitask semantics now require a working RunStore on the
  worker that owns the run; cross-worker cancels return 409 instead of
  silently appearing successful. ([#2932])

### Added

#### Agents & runtime
- **agent:** Custom-agent self-updates with user isolation — agents can persist
  edits to their own `SOUL.md` / `config.yaml` from inside a normal chat.
  ([#2713])
- **loop-detection:** Make loop detection configurable with per-tool frequency
  overrides; keep configurable on/off switch. ([#2586], [#2711])
- **loop-detection:** Defer warning injection so detector pairs cleanly with
  tool-call lifecycle. ([#2752])
- **run:** Propagate `model_name` from the gateway request through the runtime
  and persistence stack into the SQLite-backed store. ([#2775])
- **subagents:** Stream subagent token usage to the header via terminal task
  events. ([#2882])
- **memory:** Add `memory.token_counting` config to opt out of tiktoken for
  network-restricted deployments. ([#3465])
- **suggest:** Make AI follow-up question suggestions optional. ([#3591])

#### Models & integrations
- **models:** Add StepFun reasoning model adapter. ([#3461])
- **community:** Add Brave Search web search tool. ([#3528])
- **channels:** Enhance Discord with mention-only mode, thread routing, and
  typing indicators. ([#2842])
- **im:** Add user-owned IM channel connections — users can bind their own
  Slack/Telegram/Discord/Feishu/DingTalk/WeChat/WeCom accounts on top of the
  operator-configured bots. ([#3487])
- **models:** Add patched MiMo reasoning content support. ([#3298])
- **models:** Add MiniMax provider for image/video/podcast skills plus a new
  music-generation skill. ([#3437])
- **community:** Add SearXNG and Browserless web search/fetch tools. ([#3451])
- **community:** Add Serper Google Images provider for `image_search`. ([#3575])
- **channels:** Stream Telegram agent replies by editing the placeholder
  message in place. ([#3534])

#### Observability
- **trace:** Set the LangGraph trace name to `lead_agent` (or the custom
  agent's `agent_name`) for cleaner Langfuse/LangSmith traces. ([#3101])
- **frontend:** Refine token usage display modes. ([#2329])
- **defaults:** Enable token usage tracking by default. ([#2841])
- **defaults:** Raise default summarization trigger threshold. ([#3174])
- **trace:** Attribute subagent spans to the parent thread's Langfuse trace.
  ([#3611])

#### Skills
- **skill:** Add `blocking-io-guard` skill for blocking-IO triage and runtime
  anchors. ([#3503])
- **skill:** Add maintainer issue and PR workflow skill. ([#3554])
- **skill:** Strengthen the maintainer orchestrator review workflow. ([#3606])

### Performance

- **harness:** Push thread metadata filters into SQL instead of post-filtering
  in Python. ([#2865])
- **runtime:** Index runs by `thread_id` to avoid O(n) scans in `RunManager`.
  ([#3499])
- **runtime:** Index messages in `MemoryRunEventStore` to avoid O(n) scans.
  ([#3531])
- **persistence:** Cache `Base.to_dict` column reflection per class. ([#3654])
- **sandbox:** Speed up `should_ignore_name` in glob/grep walks. ([#3657])

### Security

- **upload:** Reject symlinked upload destinations. ([#2623])
- **uploads:** Add Windows support for safe symlink-protected uploads.
  ([#2794])
- **mcp:** Mask sensitive values in MCP config API responses. ([#2667])
- **mcp:** Harden the MCP config endpoint against malformed input. ([#3425])
- **auth:** Reject cross-site auth POSTs. ([#2740])
- **gateway:** Cap skill artifact preview decompression to prevent
  zip-bomb-style abuse. ([#2963])
- **sandbox:** Mount the host Docker socket only in aio (DooD) sandbox mode.
  ([#3517])
- **sandbox:** Do not bind-mount host CLI auth dirs by default. ([#3521])

### Fixed

#### Runtime, gateway & persistence
- **runtime:** Rollback restore checkpoint now supersedes newer checkpoints.
  ([#2582])
- **runtime:** Persist run message summaries. ([#2850])
- **runtime:** Bound `write_file` execution-failure observations to keep
  failure traces from blowing out the context. ([#3133])
- **runtime:** Protect the sync singleton's init and reset paths. ([#3413])
- **runtime:** Avoid PostgreSQL aggregate `FOR UPDATE` on run events.
  ([#2962])
- **runs:** Restore historical runs from persistent store after a gateway
  restart. ([#2989])
- **gateway:** Return ISO 8601 timestamps from threads endpoints. ([#2599])
- **gateway:** Make cancel idempotent for already-interrupted runs. ([#3058])
- **gateway:** Split `stream_existing_run` into per-method routes for unique
  OpenAPI `operationId`s. ([#3228])
- **events:** Serialize structured DB event content. ([#2762])
- **persistence:** Emit timezone-aware timestamps from SQLite-backed stores.
  ([#3130])
- **persistence:** Reuse token usage model grouping expression. ([#2910])
- **runs:** Ignore stale run reconnect conflicts. ([#3284])
- **nginx:** Defer CORS to the gateway allowlist instead of double-applying it.
  ([#2861])
- **persistence:** Fix runtime journal run lifecycle events. ([#3470])
- **gateway:** Enforce thread ownership on stateless run endpoints. ([#3473])
- **runtime:** Propagate interrupt through SSE values events for the LangGraph
  SDK. ([#3605])
- **serialization:** Strip base64 image data from streamed values events.
  ([#3631])
- **history:** Strip base64 image data from REST endpoint responses. ([#3535])
- **gateway:** Attribute token usage to the actual models. ([#3658])

#### Agents, subagents & middleware
- **subagents:** Make subagent timeout terminal state atomic. ([#2583])
- **subagents:** Use model override for tools and middleware. ([#2641])
- **subagents:** Consolidate `system_prompt` and skills into a single
  `SystemMessage`. ([#2701])
- **subagent:** Isolate subagents from the parent run's checkpointer.
  ([#3559])
- **agents:** Make `update_agent` honor `runtime.context` `user_id` like
  `setup_agent` does. ([#2867])
- **agents:** Resolve duplicate `todos` channel type conflict in
  `TodoMiddleware`. ([#3200])
- **agents:** Offload blocking filesystem IO in the custom-agent router off
  the event loop. ([#3457])
- **agents:** Keep new agent bootstrap in user scope. ([#2784])
- **loop-detection:** Keep tool-call pairing on warn injection. ([#2725])
- **middleware:** Sync raw tool-call metadata. ([#2757])
- **middleware:** Handle invalid tool calls in dangling pairing middleware.
  ([#2891])
- **middleware:** Prevent todo completion reminder IM-message leak. ([#2907])
- **middleware:** Normalize tool result adjacency before model calls.
  ([#2939])
- **agents:** Require `config.yaml` in `resolve_agent_dir` to skip memory-only
  directories. ([#3481])
- **agents:** Sync `agent_name` across context/configurable and reject empty
  soul. ([#3553])
- **middleware:** Offload the uploads scan in `UploadsMiddleware` off the event
  loop. ([#3311])
- **middleware:** Offload memory injection off the event loop to prevent
  tiktoken blocking. ([#3411])
- **middleware:** Externalize oversized tool output into the sandbox for
  non-mounted sandboxes. ([#3417])
- **middleware:** Preserve the sandbox reducer in middleware state. ([#3629])
- **subagents:** Raise general-purpose `max_turns` to 150 and default timeout to
  30 min. ([#3610])

#### Memory & tracing
- **memory:** Replace short-lived `asyncio.run()` with a persistent event
  loop. ([#2627])
- **memory:** Isolate queued memory updates by agent. ([#2941])
- **memory:** Parse wrapped memory-update JSON responses. ([#3252])
- **tracing:** Propagate `session_id` and `user_id` into Langfuse traces.
  ([#2944])
- **trace:** Decode unicode escape sequences in non-ASCII memory trace info.
  ([#3104])

#### Tools, sandbox & MCP
- **mcp:** Fix env resolution in MCP config lists. ([#2556])
- **models:** Record Codex token usage in `usage_metadata`. ([#2585])
- **sandbox:** Supplement `list_running` in `RemoteSandboxBackend`. ([#2716])
- **sandbox:** Disable MSYS path conversion for Git Bash on Windows.
  ([#2766])
- **sandbox:** Avoid blocking sandbox readiness polling. ([#2822])
- **sandbox:** Uphold the `/mnt/user-data` contract at the `Sandbox` API
  boundary. ([#2881])
- **sandbox:** Scope provisioner PVC data by user. ([#2973])
- **sandbox:** Merge idempotent sandbox state updates. ([#3518])
- **tools:** Introduce `Runtime` type alias to eliminate Pydantic serialization
  warnings. ([#2774])
- **tools:** Preserve `tool_search` promotions across re-entrant
  `get_available_tools`. ([#2885])
- **harness:** Wrap async-only config tools for sync client execution.
  ([#2878])
- **harness:** Wrap all async-only tools for sync clients. ([#2935])
- **tool-search:** Reliably hide deferred MCP schemas by removing the
  ContextVar. ([#3342])
- **search:** Fix DDGS Wikipedia region handling. ([#3423])
- **web_fetch:** Support a proxy for the Jina reader in restricted networks.
  ([#3430])
- **sandbox:** Persist lazily-acquired sandbox state via `Command`. ([#3464])
- **sandbox:** Fix stale AIO sandbox cache reuse. ([#3494])
- **sandbox:** Create a shell session before retrying on a fresh id. ([#3577])
- **sandbox:** Stop flagging string-literal path fragments as unsafe absolute
  paths. ([#3623])
- **sandbox:** Return an actionable hint when `read_file` hits a binary file.
  ([#3624])
- **mcp:** Make stdio MCP-produced files resolvable via virtual sandbox paths.
  ([#3600])
- **mcp:** Surface admin-required state on the settings tools page. ([#3533])
- **mcp:** Add a tools cache reset endpoint. ([#3602])
- **uploads:** Fix the upload file size contract. ([#3408])

#### Skills & channels
- **skills:** Enforce `allowed-tools` metadata. ([#2626])
- **skills:** Harden slash skill activation across chat channels. ([#3466])
- **skills:** Fix custom skill install permissions. ([#3241])
- **channels:** Authenticate gateway command requests. ([#2742])
- **skills:** Surface the offending line and a quoting hint on SKILL.md YAML
  errors. ([#3335])
- **skills:** Keep skill archive installation off the event loop. ([#3505])
- **channels:** Ignore hidden control messages when extracting replies.
  ([#3270])
- **channels:** Reload config on channel restart. ([#3514])
- **channels:** Surface WeCom WebSocket connection failures. ([#3526])
- **channels:** Close the Discord file handle after upload. ([#3561])
- **channels:** Require a bound identity for user-owned IM messages. ([#3578])
- **channels:** Scope IM files and helper commands to the owner. ([#3579])
- **channels:** Make runtime provider state authoritative. ([#3580])
- **channels:** Harden runtime credential management APIs. ([#3581])
- **channels:** Make the channel connect flow deterministic. ([#3582])
- **channels:** Centralize shared channel retry helpers. ([#3583])
- **channels:** Add operational guardrails. ([#3584])
- **channels:** Unsubscribe channel listeners by equality. ([#3608])

#### Auth
- **auth:** Replace setup-status 429 rate limit with a cached response.
  ([#2915])
- **auth:** Persist auto-generated JWT secret so it survives restarts.
  ([#2933])
- **auth:** Align auth-disabled mode with mock history loading. ([#3471])

#### Frontend
- **frontend:** Restore `localhost` fallback for `getGatewayConfig` in prod
  mode. ([#2718])
- **chat:** Prevent the first user message from being swallowed in new
  conversations. ([#2731])
- **frontend:** Use backend thread token usage for the header total. ([#2800])
- **frontend:** Wait for async chat submit before clearing the input.
  ([#2940])
- **frontend:** Resolve login page flickering and the resize-observer loop.
  ([#2954])
- **frontend:** Deduplicate restored thread messages. ([#2958])
- **frontend:** Avoid duplicate optimistic user message. ([#3002])
- **frontend:** Hide the copy button for streaming assistant messages.
  ([#3176])
- **frontend:** Show a new thread in the sidebar immediately on creation.
  ([#3283])
- **frontend:** Isolate new chat thread messages. ([#3508])
- **frontend:** Cap deeply nested list indentation to prevent render crashes.
  ([#3393], [#3570])
- **token-usage:** Dedupe token usage aggregation by message id. ([#2770])
- **frontend:** Fall back to Streamdown clipboard copy. ([#3397])
- **frontend:** Remove the Backspace shortcut for deleting prompt attachments.
  ([#3410])
- **frontend:** Restructure the Memory settings toolbar into two rows. ([#3433])
- **suggestions:** Strip inline `<think>` reasoning before parsing follow-up
  questions. ([#3435])
- **frontend:** Stop fetching follow-up suggestions when they are disabled.
  ([#3599])
- **frontend:** Paginate the workspace chat list beyond 50 threads. ([#3485])
- **frontend:** Prevent user message bubble overflow with long unbreakable
  strings. ([#3488])
- **frontend:** Keep the workspace interactive when the SSR auth probe cannot
  reach the gateway. ([#3495])
- **frontend:** Render user messages as plain text and cap blockquote nesting.
  ([#3502])
- **frontend:** Reset the active chat after deletion. ([#3519])
- **frontend:** Improve the mobile workspace layout. ([#3646])
- **frontend:** Render full content for multi-part AI messages. ([#3649])

#### Build, deploy, scripts & config
- **packaging:** Add `postgres` extra for store/checkpointer support; clarify
  install guidance. ([#2584])
- **harness:** Resolve runtime paths from the project root. ([#2642])
- **docker:** Force nginx to resolve upstream names at request time.
  ([#2717])
- **docker:** Default Gateway to a single worker to prevent multi-worker
  breakage. ([#3475])
- **scripts:** Preserve `uv` extras across `make dev` restarts. ([#2767],
  [#2754])
- **scripts:** Clean up local nginx on stop. ([#3005])
- **deploy:** Fall back to `python` / `openssl` when `python3` is absent for
  secret generation. ([#3074])
- **config:** Make the reload boundary discoverable from code. ([#3144],
  [#3153])
- **replay-e2e:** Key replay fixtures by caller and conversation. ([#3453])
- **setup:** Refresh LLM provider wizard defaults. ([#3421])
- **config:** Coerce null `config.yaml` list sections to an empty list. ([#3434])
- **scripts:** Exclude runtime state from gateway reload. ([#3426])
- **scripts:** Create the backend/sandbox dir before the uvicorn reload-exclude.
  ([#3460])
- **scripts:** Stop next-server correctly after `make start-daemon`. ([#3498])
- **makefile:** Fix per-commit hooks installation. ([#3569])
- **replay-e2e:** Match replay by conversation, not the living system prompt.
  ([#3436])

### Changed

- **provider (refactor):** Share assistant payload replay matching across
  providers. ([#3307])
- **lead-agent (refactor):** Make `build_middlewares` public to drop the last
  cross-module private import. ([#3458])
- **todo (refactor):** Remove the unused completion reminder counter. ([#3530])

### Documentation

- Document blocking-IO detection usage and maintenance. ([#3233])
- Clean standalone LangGraph server remnants from docs. ([#3301])
- Add AI assistance disclosure to the PR template and CONTRIBUTING. ([#3398])
- Document custom AIO sandbox images. ([#3548])

### Internal

- **dev:** Add async/thread boundary detector. ([#2936])
- **runtime:** Add lifecycle end-to-end coverage. ([#2946])
- **windows:** Add `PYTHONIOENCODING` and `PYTHONUTF8` to backend Makefile
  targets. ([#3069])
- **blocking-io:** Fail-loud repo-root resolution and shared detector CLI
  shim. ([#3512])
- **runtime:** Add a Blockbuster runtime anchor for `JsonlRunEventStore` async
  IO. ([#3313])
- **ci:** Consolidate PR/issue labeling and fix the reviewing-job crash and
  label thrash. ([#3455])

[Unreleased]: https://github.com/bytedance/deer-flow/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/bytedance/deer-flow/releases/tag/v2.1.0
[2.0.0]: https://github.com/bytedance/deer-flow/releases/tag/v2.0.0

[#2329]: https://github.com/bytedance/deer-flow/pull/2329
[#2556]: https://github.com/bytedance/deer-flow/pull/2556
[#2582]: https://github.com/bytedance/deer-flow/pull/2582
[#2583]: https://github.com/bytedance/deer-flow/pull/2583
[#2584]: https://github.com/bytedance/deer-flow/pull/2584
[#2585]: https://github.com/bytedance/deer-flow/pull/2585
[#2586]: https://github.com/bytedance/deer-flow/pull/2586
[#2599]: https://github.com/bytedance/deer-flow/pull/2599
[#2623]: https://github.com/bytedance/deer-flow/pull/2623
[#2626]: https://github.com/bytedance/deer-flow/pull/2626
[#2627]: https://github.com/bytedance/deer-flow/pull/2627
[#2641]: https://github.com/bytedance/deer-flow/pull/2641
[#2642]: https://github.com/bytedance/deer-flow/pull/2642
[#2667]: https://github.com/bytedance/deer-flow/pull/2667
[#2701]: https://github.com/bytedance/deer-flow/pull/2701
[#2711]: https://github.com/bytedance/deer-flow/pull/2711
[#2713]: https://github.com/bytedance/deer-flow/pull/2713
[#2716]: https://github.com/bytedance/deer-flow/pull/2716
[#2717]: https://github.com/bytedance/deer-flow/pull/2717
[#2718]: https://github.com/bytedance/deer-flow/pull/2718
[#2725]: https://github.com/bytedance/deer-flow/pull/2725
[#2731]: https://github.com/bytedance/deer-flow/pull/2731
[#2740]: https://github.com/bytedance/deer-flow/pull/2740
[#2742]: https://github.com/bytedance/deer-flow/pull/2742
[#2752]: https://github.com/bytedance/deer-flow/pull/2752
[#2754]: https://github.com/bytedance/deer-flow/pull/2754
[#2757]: https://github.com/bytedance/deer-flow/pull/2757
[#2762]: https://github.com/bytedance/deer-flow/pull/2762
[#2766]: https://github.com/bytedance/deer-flow/pull/2766
[#2767]: https://github.com/bytedance/deer-flow/pull/2767
[#2770]: https://github.com/bytedance/deer-flow/pull/2770
[#2774]: https://github.com/bytedance/deer-flow/pull/2774
[#2775]: https://github.com/bytedance/deer-flow/pull/2775
[#2784]: https://github.com/bytedance/deer-flow/pull/2784
[#2794]: https://github.com/bytedance/deer-flow/pull/2794
[#2800]: https://github.com/bytedance/deer-flow/pull/2800
[#2822]: https://github.com/bytedance/deer-flow/pull/2822
[#2841]: https://github.com/bytedance/deer-flow/pull/2841
[#2842]: https://github.com/bytedance/deer-flow/pull/2842
[#2850]: https://github.com/bytedance/deer-flow/pull/2850
[#2861]: https://github.com/bytedance/deer-flow/pull/2861
[#2865]: https://github.com/bytedance/deer-flow/pull/2865
[#2867]: https://github.com/bytedance/deer-flow/pull/2867
[#2878]: https://github.com/bytedance/deer-flow/pull/2878
[#2881]: https://github.com/bytedance/deer-flow/pull/2881
[#2882]: https://github.com/bytedance/deer-flow/pull/2882
[#2885]: https://github.com/bytedance/deer-flow/pull/2885
[#2891]: https://github.com/bytedance/deer-flow/pull/2891
[#2907]: https://github.com/bytedance/deer-flow/pull/2907
[#2910]: https://github.com/bytedance/deer-flow/pull/2910
[#2915]: https://github.com/bytedance/deer-flow/pull/2915
[#2932]: https://github.com/bytedance/deer-flow/pull/2932
[#2933]: https://github.com/bytedance/deer-flow/pull/2933
[#2935]: https://github.com/bytedance/deer-flow/pull/2935
[#2936]: https://github.com/bytedance/deer-flow/pull/2936
[#2939]: https://github.com/bytedance/deer-flow/pull/2939
[#2940]: https://github.com/bytedance/deer-flow/pull/2940
[#2941]: https://github.com/bytedance/deer-flow/pull/2941
[#2944]: https://github.com/bytedance/deer-flow/pull/2944
[#2946]: https://github.com/bytedance/deer-flow/pull/2946
[#2954]: https://github.com/bytedance/deer-flow/pull/2954
[#2958]: https://github.com/bytedance/deer-flow/pull/2958
[#2962]: https://github.com/bytedance/deer-flow/pull/2962
[#2963]: https://github.com/bytedance/deer-flow/pull/2963
[#2973]: https://github.com/bytedance/deer-flow/pull/2973
[#2989]: https://github.com/bytedance/deer-flow/pull/2989
[#3002]: https://github.com/bytedance/deer-flow/pull/3002
[#3005]: https://github.com/bytedance/deer-flow/pull/3005
[#3033]: https://github.com/bytedance/deer-flow/pull/3033
[#3058]: https://github.com/bytedance/deer-flow/pull/3058
[#3069]: https://github.com/bytedance/deer-flow/pull/3069
[#3074]: https://github.com/bytedance/deer-flow/pull/3074
[#3101]: https://github.com/bytedance/deer-flow/pull/3101
[#3104]: https://github.com/bytedance/deer-flow/pull/3104
[#3130]: https://github.com/bytedance/deer-flow/pull/3130
[#3133]: https://github.com/bytedance/deer-flow/pull/3133
[#3144]: https://github.com/bytedance/deer-flow/pull/3144
[#3153]: https://github.com/bytedance/deer-flow/pull/3153
[#3157]: https://github.com/bytedance/deer-flow/pull/3157
[#3174]: https://github.com/bytedance/deer-flow/pull/3174
[#3176]: https://github.com/bytedance/deer-flow/pull/3176
[#3182]: https://github.com/bytedance/deer-flow/pull/3182
[#3183]: https://github.com/bytedance/deer-flow/pull/3183
[#3191]: https://github.com/bytedance/deer-flow/pull/3191
[#3200]: https://github.com/bytedance/deer-flow/pull/3200
[#3228]: https://github.com/bytedance/deer-flow/pull/3228
[#3233]: https://github.com/bytedance/deer-flow/pull/3233
[#3241]: https://github.com/bytedance/deer-flow/pull/3241
[#3252]: https://github.com/bytedance/deer-flow/pull/3252
[#3270]: https://github.com/bytedance/deer-flow/pull/3270
[#3283]: https://github.com/bytedance/deer-flow/pull/3283
[#3284]: https://github.com/bytedance/deer-flow/pull/3284
[#3298]: https://github.com/bytedance/deer-flow/pull/3298
[#3301]: https://github.com/bytedance/deer-flow/pull/3301
[#3307]: https://github.com/bytedance/deer-flow/pull/3307
[#3311]: https://github.com/bytedance/deer-flow/pull/3311
[#3313]: https://github.com/bytedance/deer-flow/pull/3313
[#3335]: https://github.com/bytedance/deer-flow/pull/3335
[#3342]: https://github.com/bytedance/deer-flow/pull/3342
[#3377]: https://github.com/bytedance/deer-flow/pull/3377
[#3393]: https://github.com/bytedance/deer-flow/pull/3393
[#3396]: https://github.com/bytedance/deer-flow/pull/3396
[#3397]: https://github.com/bytedance/deer-flow/pull/3397
[#3398]: https://github.com/bytedance/deer-flow/pull/3398
[#3408]: https://github.com/bytedance/deer-flow/pull/3408
[#3410]: https://github.com/bytedance/deer-flow/pull/3410
[#3411]: https://github.com/bytedance/deer-flow/pull/3411
[#3412]: https://github.com/bytedance/deer-flow/pull/3412
[#3413]: https://github.com/bytedance/deer-flow/pull/3413
[#3417]: https://github.com/bytedance/deer-flow/pull/3417
[#3421]: https://github.com/bytedance/deer-flow/pull/3421
[#3423]: https://github.com/bytedance/deer-flow/pull/3423
[#3425]: https://github.com/bytedance/deer-flow/pull/3425
[#3426]: https://github.com/bytedance/deer-flow/pull/3426
[#3428]: https://github.com/bytedance/deer-flow/pull/3428
[#3430]: https://github.com/bytedance/deer-flow/pull/3430
[#3433]: https://github.com/bytedance/deer-flow/pull/3433
[#3434]: https://github.com/bytedance/deer-flow/pull/3434
[#3435]: https://github.com/bytedance/deer-flow/pull/3435
[#3436]: https://github.com/bytedance/deer-flow/pull/3436
[#3437]: https://github.com/bytedance/deer-flow/pull/3437
[#3442]: https://github.com/bytedance/deer-flow/pull/3442
[#3451]: https://github.com/bytedance/deer-flow/pull/3451
[#3453]: https://github.com/bytedance/deer-flow/pull/3453
[#3455]: https://github.com/bytedance/deer-flow/pull/3455
[#3457]: https://github.com/bytedance/deer-flow/pull/3457
[#3458]: https://github.com/bytedance/deer-flow/pull/3458
[#3460]: https://github.com/bytedance/deer-flow/pull/3460
[#3461]: https://github.com/bytedance/deer-flow/pull/3461
[#3464]: https://github.com/bytedance/deer-flow/pull/3464
[#3465]: https://github.com/bytedance/deer-flow/pull/3465
[#3466]: https://github.com/bytedance/deer-flow/pull/3466
[#3470]: https://github.com/bytedance/deer-flow/pull/3470
[#3471]: https://github.com/bytedance/deer-flow/pull/3471
[#3473]: https://github.com/bytedance/deer-flow/pull/3473
[#3475]: https://github.com/bytedance/deer-flow/pull/3475
[#3481]: https://github.com/bytedance/deer-flow/pull/3481
[#3485]: https://github.com/bytedance/deer-flow/pull/3485
[#3487]: https://github.com/bytedance/deer-flow/pull/3487
[#3488]: https://github.com/bytedance/deer-flow/pull/3488
[#3494]: https://github.com/bytedance/deer-flow/pull/3494
[#3495]: https://github.com/bytedance/deer-flow/pull/3495
[#3498]: https://github.com/bytedance/deer-flow/pull/3498
[#3499]: https://github.com/bytedance/deer-flow/pull/3499
[#3502]: https://github.com/bytedance/deer-flow/pull/3502
[#3503]: https://github.com/bytedance/deer-flow/pull/3503
[#3505]: https://github.com/bytedance/deer-flow/pull/3505
[#3506]: https://github.com/bytedance/deer-flow/pull/3506
[#3508]: https://github.com/bytedance/deer-flow/pull/3508
[#3512]: https://github.com/bytedance/deer-flow/pull/3512
[#3514]: https://github.com/bytedance/deer-flow/pull/3514
[#3517]: https://github.com/bytedance/deer-flow/pull/3517
[#3518]: https://github.com/bytedance/deer-flow/pull/3518
[#3519]: https://github.com/bytedance/deer-flow/pull/3519
[#3521]: https://github.com/bytedance/deer-flow/pull/3521
[#3526]: https://github.com/bytedance/deer-flow/pull/3526
[#3528]: https://github.com/bytedance/deer-flow/pull/3528
[#3530]: https://github.com/bytedance/deer-flow/pull/3530
[#3531]: https://github.com/bytedance/deer-flow/pull/3531
[#3533]: https://github.com/bytedance/deer-flow/pull/3533
[#3534]: https://github.com/bytedance/deer-flow/pull/3534
[#3535]: https://github.com/bytedance/deer-flow/pull/3535
[#3548]: https://github.com/bytedance/deer-flow/pull/3548
[#3551]: https://github.com/bytedance/deer-flow/pull/3551
[#3553]: https://github.com/bytedance/deer-flow/pull/3553
[#3554]: https://github.com/bytedance/deer-flow/pull/3554
[#3556]: https://github.com/bytedance/deer-flow/pull/3556
[#3557]: https://github.com/bytedance/deer-flow/pull/3557
[#3559]: https://github.com/bytedance/deer-flow/pull/3559
[#3561]: https://github.com/bytedance/deer-flow/pull/3561
[#3562]: https://github.com/bytedance/deer-flow/pull/3562
[#3563]: https://github.com/bytedance/deer-flow/pull/3563
[#3565]: https://github.com/bytedance/deer-flow/pull/3565
[#3566]: https://github.com/bytedance/deer-flow/pull/3566
[#3569]: https://github.com/bytedance/deer-flow/pull/3569
[#3570]: https://github.com/bytedance/deer-flow/pull/3570
[#3573]: https://github.com/bytedance/deer-flow/pull/3573
[#3575]: https://github.com/bytedance/deer-flow/pull/3575
[#3577]: https://github.com/bytedance/deer-flow/pull/3577
[#3578]: https://github.com/bytedance/deer-flow/pull/3578
[#3579]: https://github.com/bytedance/deer-flow/pull/3579
[#3580]: https://github.com/bytedance/deer-flow/pull/3580
[#3581]: https://github.com/bytedance/deer-flow/pull/3581
[#3582]: https://github.com/bytedance/deer-flow/pull/3582
[#3583]: https://github.com/bytedance/deer-flow/pull/3583
[#3584]: https://github.com/bytedance/deer-flow/pull/3584
[#3585]: https://github.com/bytedance/deer-flow/pull/3585
[#3590]: https://github.com/bytedance/deer-flow/pull/3590
[#3591]: https://github.com/bytedance/deer-flow/pull/3591
[#3592]: https://github.com/bytedance/deer-flow/pull/3592
[#3599]: https://github.com/bytedance/deer-flow/pull/3599
[#3600]: https://github.com/bytedance/deer-flow/pull/3600
[#3601]: https://github.com/bytedance/deer-flow/pull/3601
[#3602]: https://github.com/bytedance/deer-flow/pull/3602
[#3605]: https://github.com/bytedance/deer-flow/pull/3605
[#3606]: https://github.com/bytedance/deer-flow/pull/3606
[#3608]: https://github.com/bytedance/deer-flow/pull/3608
[#3610]: https://github.com/bytedance/deer-flow/pull/3610
[#3611]: https://github.com/bytedance/deer-flow/pull/3611
[#3623]: https://github.com/bytedance/deer-flow/pull/3623
[#3624]: https://github.com/bytedance/deer-flow/pull/3624
[#3627]: https://github.com/bytedance/deer-flow/pull/3627
[#3629]: https://github.com/bytedance/deer-flow/pull/3629
[#3631]: https://github.com/bytedance/deer-flow/pull/3631
[#3637]: https://github.com/bytedance/deer-flow/pull/3637
[#3644]: https://github.com/bytedance/deer-flow/pull/3644
[#3646]: https://github.com/bytedance/deer-flow/pull/3646
[#3648]: https://github.com/bytedance/deer-flow/pull/3648
[#3649]: https://github.com/bytedance/deer-flow/pull/3649
[#3651]: https://github.com/bytedance/deer-flow/pull/3651
[#3654]: https://github.com/bytedance/deer-flow/pull/3654
[#3657]: https://github.com/bytedance/deer-flow/pull/3657
[#3658]: https://github.com/bytedance/deer-flow/pull/3658
[#3661]: https://github.com/bytedance/deer-flow/pull/3661
[#3662]: https://github.com/bytedance/deer-flow/pull/3662
[#3663]: https://github.com/bytedance/deer-flow/pull/3663
[#3665]: https://github.com/bytedance/deer-flow/pull/3665
[#3673]: https://github.com/bytedance/deer-flow/pull/3673
[#3674]: https://github.com/bytedance/deer-flow/pull/3674
[#3675]: https://github.com/bytedance/deer-flow/pull/3675
[#3685]: https://github.com/bytedance/deer-flow/pull/3685
[#3686]: https://github.com/bytedance/deer-flow/pull/3686
[#3687]: https://github.com/bytedance/deer-flow/pull/3687
[#3698]: https://github.com/bytedance/deer-flow/pull/3698
[#3703]: https://github.com/bytedance/deer-flow/pull/3703
[#3708]: https://github.com/bytedance/deer-flow/pull/3708
[#3709]: https://github.com/bytedance/deer-flow/pull/3709
[#3711]: https://github.com/bytedance/deer-flow/pull/3711
[#3713]: https://github.com/bytedance/deer-flow/pull/3713
[#3714]: https://github.com/bytedance/deer-flow/pull/3714
[#3718]: https://github.com/bytedance/deer-flow/pull/3718
[#3719]: https://github.com/bytedance/deer-flow/pull/3719
[#3729]: https://github.com/bytedance/deer-flow/pull/3729
[#3730]: https://github.com/bytedance/deer-flow/pull/3730
[#3733]: https://github.com/bytedance/deer-flow/pull/3733
[#3740]: https://github.com/bytedance/deer-flow/pull/3740
[#3753]: https://github.com/bytedance/deer-flow/pull/3753
[#3760]: https://github.com/bytedance/deer-flow/pull/3760
[#3764]: https://github.com/bytedance/deer-flow/pull/3764
[#3768]: https://github.com/bytedance/deer-flow/pull/3768
[#3769]: https://github.com/bytedance/deer-flow/pull/3769
[#3770]: https://github.com/bytedance/deer-flow/pull/3770
[#3772]: https://github.com/bytedance/deer-flow/pull/3772
[#3775]: https://github.com/bytedance/deer-flow/pull/3775
[#3783]: https://github.com/bytedance/deer-flow/pull/3783
[#3786]: https://github.com/bytedance/deer-flow/pull/3786
[#3790]: https://github.com/bytedance/deer-flow/pull/3790
[#3791]: https://github.com/bytedance/deer-flow/pull/3791
[#3794]: https://github.com/bytedance/deer-flow/pull/3794
[#3797]: https://github.com/bytedance/deer-flow/pull/3797
[#3800]: https://github.com/bytedance/deer-flow/pull/3800
[#3809]: https://github.com/bytedance/deer-flow/pull/3809
[#3810]: https://github.com/bytedance/deer-flow/pull/3810
[#3812]: https://github.com/bytedance/deer-flow/pull/3812
[#3821]: https://github.com/bytedance/deer-flow/pull/3821
[#3823]: https://github.com/bytedance/deer-flow/pull/3823
[#3824]: https://github.com/bytedance/deer-flow/pull/3824
[#3826]: https://github.com/bytedance/deer-flow/pull/3826
[#3828]: https://github.com/bytedance/deer-flow/pull/3828
[#3833]: https://github.com/bytedance/deer-flow/pull/3833
[#3837]: https://github.com/bytedance/deer-flow/pull/3837
[#3839]: https://github.com/bytedance/deer-flow/pull/3839
[#3843]: https://github.com/bytedance/deer-flow/pull/3843
[#3845]: https://github.com/bytedance/deer-flow/pull/3845
[#3854]: https://github.com/bytedance/deer-flow/pull/3854
[#3855]: https://github.com/bytedance/deer-flow/pull/3855
[#3856]: https://github.com/bytedance/deer-flow/pull/3856
[#3858]: https://github.com/bytedance/deer-flow/pull/3858
[#3860]: https://github.com/bytedance/deer-flow/pull/3860
[#3866]: https://github.com/bytedance/deer-flow/pull/3866
[#3869]: https://github.com/bytedance/deer-flow/pull/3869
[#3870]: https://github.com/bytedance/deer-flow/pull/3870
[#3871]: https://github.com/bytedance/deer-flow/pull/3871
[#3872]: https://github.com/bytedance/deer-flow/pull/3872
[#3874]: https://github.com/bytedance/deer-flow/pull/3874
[#3877]: https://github.com/bytedance/deer-flow/pull/3877
[#3878]: https://github.com/bytedance/deer-flow/pull/3878
[#3880]: https://github.com/bytedance/deer-flow/pull/3880
[#3881]: https://github.com/bytedance/deer-flow/pull/3881
[#3883]: https://github.com/bytedance/deer-flow/pull/3883
[#3885]: https://github.com/bytedance/deer-flow/pull/3885
[#3886]: https://github.com/bytedance/deer-flow/pull/3886
[#3887]: https://github.com/bytedance/deer-flow/pull/3887
[#3889]: https://github.com/bytedance/deer-flow/pull/3889
[#3897]: https://github.com/bytedance/deer-flow/pull/3897
[#3900]: https://github.com/bytedance/deer-flow/pull/3900
[#3902]: https://github.com/bytedance/deer-flow/pull/3902
[#3904]: https://github.com/bytedance/deer-flow/pull/3904
[#3906]: https://github.com/bytedance/deer-flow/pull/3906
[#3907]: https://github.com/bytedance/deer-flow/pull/3907
[#3908]: https://github.com/bytedance/deer-flow/pull/3908
[#3912]: https://github.com/bytedance/deer-flow/pull/3912
[#3917]: https://github.com/bytedance/deer-flow/pull/3917
[#3920]: https://github.com/bytedance/deer-flow/pull/3920
[#3924]: https://github.com/bytedance/deer-flow/pull/3924
[#3926]: https://github.com/bytedance/deer-flow/pull/3926
[#3927]: https://github.com/bytedance/deer-flow/pull/3927
[#3928]: https://github.com/bytedance/deer-flow/pull/3928
[#3931]: https://github.com/bytedance/deer-flow/pull/3931
[#3934]: https://github.com/bytedance/deer-flow/pull/3934
[#3935]: https://github.com/bytedance/deer-flow/pull/3935
[#3938]: https://github.com/bytedance/deer-flow/pull/3938
[#3940]: https://github.com/bytedance/deer-flow/pull/3940
[#3941]: https://github.com/bytedance/deer-flow/pull/3941
[#3942]: https://github.com/bytedance/deer-flow/pull/3942
[#3944]: https://github.com/bytedance/deer-flow/pull/3944
[#3945]: https://github.com/bytedance/deer-flow/pull/3945
[#3949]: https://github.com/bytedance/deer-flow/pull/3949
[#3950]: https://github.com/bytedance/deer-flow/pull/3950
[#3951]: https://github.com/bytedance/deer-flow/pull/3951
[#3956]: https://github.com/bytedance/deer-flow/pull/3956
[#3959]: https://github.com/bytedance/deer-flow/pull/3959
[#3961]: https://github.com/bytedance/deer-flow/pull/3961
[#3964]: https://github.com/bytedance/deer-flow/pull/3964
[#3966]: https://github.com/bytedance/deer-flow/pull/3966
[#3967]: https://github.com/bytedance/deer-flow/pull/3967
[#3969]: https://github.com/bytedance/deer-flow/pull/3969
[#3971]: https://github.com/bytedance/deer-flow/pull/3971
[#3976]: https://github.com/bytedance/deer-flow/pull/3976
[#3980]: https://github.com/bytedance/deer-flow/pull/3980
[#3981]: https://github.com/bytedance/deer-flow/pull/3981
[#3982]: https://github.com/bytedance/deer-flow/pull/3982
[#3985]: https://github.com/bytedance/deer-flow/pull/3985
[#3986]: https://github.com/bytedance/deer-flow/pull/3986
[#3988]: https://github.com/bytedance/deer-flow/pull/3988
[#3989]: https://github.com/bytedance/deer-flow/pull/3989
[#3990]: https://github.com/bytedance/deer-flow/pull/3990
[#3991]: https://github.com/bytedance/deer-flow/pull/3991
[#3992]: https://github.com/bytedance/deer-flow/pull/3992
[#3993]: https://github.com/bytedance/deer-flow/pull/3993
[#3994]: https://github.com/bytedance/deer-flow/pull/3994
[#3996]: https://github.com/bytedance/deer-flow/pull/3996
[#4003]: https://github.com/bytedance/deer-flow/pull/4003
[#4004]: https://github.com/bytedance/deer-flow/pull/4004
[#4008]: https://github.com/bytedance/deer-flow/pull/4008
[#4009]: https://github.com/bytedance/deer-flow/pull/4009
[#4012]: https://github.com/bytedance/deer-flow/pull/4012
[#4016]: https://github.com/bytedance/deer-flow/pull/4016
[#4017]: https://github.com/bytedance/deer-flow/pull/4017
[#4018]: https://github.com/bytedance/deer-flow/pull/4018
[#4023]: https://github.com/bytedance/deer-flow/pull/4023
[#4024]: https://github.com/bytedance/deer-flow/pull/4024
[#4025]: https://github.com/bytedance/deer-flow/pull/4025
[#4026]: https://github.com/bytedance/deer-flow/pull/4026
[#4028]: https://github.com/bytedance/deer-flow/pull/4028
[#4033]: https://github.com/bytedance/deer-flow/pull/4033
[#4034]: https://github.com/bytedance/deer-flow/pull/4034
[#4035]: https://github.com/bytedance/deer-flow/pull/4035
[#4036]: https://github.com/bytedance/deer-flow/pull/4036
[#4038]: https://github.com/bytedance/deer-flow/pull/4038
[#4040]: https://github.com/bytedance/deer-flow/pull/4040
[#4051]: https://github.com/bytedance/deer-flow/pull/4051
[#4052]: https://github.com/bytedance/deer-flow/pull/4052
[#4053]: https://github.com/bytedance/deer-flow/pull/4053
[#4055]: https://github.com/bytedance/deer-flow/pull/4055
[#4058]: https://github.com/bytedance/deer-flow/pull/4058
[#4059]: https://github.com/bytedance/deer-flow/pull/4059
[#4060]: https://github.com/bytedance/deer-flow/pull/4060
[#4064]: https://github.com/bytedance/deer-flow/pull/4064
[#4065]: https://github.com/bytedance/deer-flow/pull/4065
[#4066]: https://github.com/bytedance/deer-flow/pull/4066
[#4067]: https://github.com/bytedance/deer-flow/pull/4067
[#4069]: https://github.com/bytedance/deer-flow/pull/4069
[#4072]: https://github.com/bytedance/deer-flow/pull/4072
[#4073]: https://github.com/bytedance/deer-flow/pull/4073
[#4074]: https://github.com/bytedance/deer-flow/pull/4074
[#4076]: https://github.com/bytedance/deer-flow/pull/4076
[#4077]: https://github.com/bytedance/deer-flow/pull/4077
[#4078]: https://github.com/bytedance/deer-flow/pull/4078
[#4079]: https://github.com/bytedance/deer-flow/pull/4079
[#4080]: https://github.com/bytedance/deer-flow/pull/4080
[#4081]: https://github.com/bytedance/deer-flow/pull/4081
[#4082]: https://github.com/bytedance/deer-flow/pull/4082
[#4084]: https://github.com/bytedance/deer-flow/pull/4084
[#4085]: https://github.com/bytedance/deer-flow/pull/4085
[#4090]: https://github.com/bytedance/deer-flow/pull/4090
[#4094]: https://github.com/bytedance/deer-flow/pull/4094
[#4095]: https://github.com/bytedance/deer-flow/pull/4095
[#4096]: https://github.com/bytedance/deer-flow/pull/4096
[#4097]: https://github.com/bytedance/deer-flow/pull/4097
[#4098]: https://github.com/bytedance/deer-flow/pull/4098
[#4099]: https://github.com/bytedance/deer-flow/pull/4099
[#4100]: https://github.com/bytedance/deer-flow/pull/4100
[#4101]: https://github.com/bytedance/deer-flow/pull/4101
[#4102]: https://github.com/bytedance/deer-flow/pull/4102
[#4103]: https://github.com/bytedance/deer-flow/pull/4103
[#4104]: https://github.com/bytedance/deer-flow/pull/4104
[#4105]: https://github.com/bytedance/deer-flow/pull/4105
[#4108]: https://github.com/bytedance/deer-flow/pull/4108
[#4114]: https://github.com/bytedance/deer-flow/pull/4114
[#4115]: https://github.com/bytedance/deer-flow/pull/4115
[#4117]: https://github.com/bytedance/deer-flow/pull/4117
[#4118]: https://github.com/bytedance/deer-flow/pull/4118
[#4119]: https://github.com/bytedance/deer-flow/pull/4119
[#4122]: https://github.com/bytedance/deer-flow/pull/4122
[#4124]: https://github.com/bytedance/deer-flow/pull/4124
[#4128]: https://github.com/bytedance/deer-flow/pull/4128
[#4129]: https://github.com/bytedance/deer-flow/pull/4129
[#4130]: https://github.com/bytedance/deer-flow/pull/4130
[#4131]: https://github.com/bytedance/deer-flow/pull/4131
[#4133]: https://github.com/bytedance/deer-flow/pull/4133
[#4136]: https://github.com/bytedance/deer-flow/pull/4136
[#4137]: https://github.com/bytedance/deer-flow/pull/4137
[#4140]: https://github.com/bytedance/deer-flow/pull/4140
[#4141]: https://github.com/bytedance/deer-flow/pull/4141
[#4143]: https://github.com/bytedance/deer-flow/pull/4143
[#4146]: https://github.com/bytedance/deer-flow/pull/4146
[#4147]: https://github.com/bytedance/deer-flow/pull/4147
[#4154]: https://github.com/bytedance/deer-flow/pull/4154
[#4155]: https://github.com/bytedance/deer-flow/pull/4155
[#4157]: https://github.com/bytedance/deer-flow/pull/4157
[#4160]: https://github.com/bytedance/deer-flow/pull/4160
[#4161]: https://github.com/bytedance/deer-flow/pull/4161
[#4162]: https://github.com/bytedance/deer-flow/pull/4162
[#4166]: https://github.com/bytedance/deer-flow/pull/4166
[#4169]: https://github.com/bytedance/deer-flow/pull/4169
[#4170]: https://github.com/bytedance/deer-flow/pull/4170
[#4171]: https://github.com/bytedance/deer-flow/pull/4171
[#4174]: https://github.com/bytedance/deer-flow/pull/4174
[#4178]: https://github.com/bytedance/deer-flow/pull/4178
[#4181]: https://github.com/bytedance/deer-flow/pull/4181
[#4187]: https://github.com/bytedance/deer-flow/pull/4187
[#4188]: https://github.com/bytedance/deer-flow/pull/4188
[#4190]: https://github.com/bytedance/deer-flow/pull/4190
[#4192]: https://github.com/bytedance/deer-flow/pull/4192
[#4193]: https://github.com/bytedance/deer-flow/pull/4193
[#4197]: https://github.com/bytedance/deer-flow/pull/4197
[#4199]: https://github.com/bytedance/deer-flow/pull/4199
[#4200]: https://github.com/bytedance/deer-flow/pull/4200
[#4202]: https://github.com/bytedance/deer-flow/pull/4202
[#4203]: https://github.com/bytedance/deer-flow/pull/4203
[#4208]: https://github.com/bytedance/deer-flow/pull/4208
[#4209]: https://github.com/bytedance/deer-flow/pull/4209
[#4210]: https://github.com/bytedance/deer-flow/pull/4210
[#4211]: https://github.com/bytedance/deer-flow/pull/4211
[#4215]: https://github.com/bytedance/deer-flow/pull/4215
[#4217]: https://github.com/bytedance/deer-flow/pull/4217
[#4218]: https://github.com/bytedance/deer-flow/pull/4218
[#4219]: https://github.com/bytedance/deer-flow/pull/4219
[#4222]: https://github.com/bytedance/deer-flow/pull/4222
[#4225]: https://github.com/bytedance/deer-flow/pull/4225
[#4229]: https://github.com/bytedance/deer-flow/pull/4229
[#4230]: https://github.com/bytedance/deer-flow/pull/4230
[#4231]: https://github.com/bytedance/deer-flow/pull/4231
[#4234]: https://github.com/bytedance/deer-flow/pull/4234
[#4235]: https://github.com/bytedance/deer-flow/pull/4235
[#4238]: https://github.com/bytedance/deer-flow/pull/4238
[#4239]: https://github.com/bytedance/deer-flow/pull/4239
[#4241]: https://github.com/bytedance/deer-flow/pull/4241
[#4242]: https://github.com/bytedance/deer-flow/pull/4242
[#4245]: https://github.com/bytedance/deer-flow/pull/4245
[#4246]: https://github.com/bytedance/deer-flow/pull/4246
[#4247]: https://github.com/bytedance/deer-flow/pull/4247
[#4250]: https://github.com/bytedance/deer-flow/pull/4250
[#4251]: https://github.com/bytedance/deer-flow/pull/4251
[#4253]: https://github.com/bytedance/deer-flow/pull/4253
[#4255]: https://github.com/bytedance/deer-flow/pull/4255
[#4256]: https://github.com/bytedance/deer-flow/pull/4256
[#4260]: https://github.com/bytedance/deer-flow/pull/4260
[#4262]: https://github.com/bytedance/deer-flow/pull/4262
[#4264]: https://github.com/bytedance/deer-flow/pull/4264
[#4266]: https://github.com/bytedance/deer-flow/pull/4266
[#4267]: https://github.com/bytedance/deer-flow/pull/4267
[#4268]: https://github.com/bytedance/deer-flow/pull/4268
[#4274]: https://github.com/bytedance/deer-flow/pull/4274
[#4275]: https://github.com/bytedance/deer-flow/pull/4275
[#4277]: https://github.com/bytedance/deer-flow/pull/4277
[#4278]: https://github.com/bytedance/deer-flow/pull/4278
[#4279]: https://github.com/bytedance/deer-flow/pull/4279
[#4283]: https://github.com/bytedance/deer-flow/pull/4283
[#4284]: https://github.com/bytedance/deer-flow/pull/4284
[#4287]: https://github.com/bytedance/deer-flow/pull/4287
[#4288]: https://github.com/bytedance/deer-flow/pull/4288
[#4292]: https://github.com/bytedance/deer-flow/pull/4292
[#4293]: https://github.com/bytedance/deer-flow/pull/4293
[#4298]: https://github.com/bytedance/deer-flow/pull/4298
[#4301]: https://github.com/bytedance/deer-flow/pull/4301
[#4302]: https://github.com/bytedance/deer-flow/pull/4302
[#4306]: https://github.com/bytedance/deer-flow/pull/4306
[#4309]: https://github.com/bytedance/deer-flow/pull/4309
[#4311]: https://github.com/bytedance/deer-flow/pull/4311
[#4314]: https://github.com/bytedance/deer-flow/pull/4314
[#4315]: https://github.com/bytedance/deer-flow/pull/4315
[#4316]: https://github.com/bytedance/deer-flow/pull/4316
[#4324]: https://github.com/bytedance/deer-flow/pull/4324
[#4326]: https://github.com/bytedance/deer-flow/pull/4326
[#4337]: https://github.com/bytedance/deer-flow/pull/4337
[#4347]: https://github.com/bytedance/deer-flow/pull/4347
[#4348]: https://github.com/bytedance/deer-flow/pull/4348
[#4354]: https://github.com/bytedance/deer-flow/pull/4354
[#4355]: https://github.com/bytedance/deer-flow/pull/4355
[#4356]: https://github.com/bytedance/deer-flow/pull/4356
[#4358]: https://github.com/bytedance/deer-flow/pull/4358
[#4360]: https://github.com/bytedance/deer-flow/pull/4360
[#4361]: https://github.com/bytedance/deer-flow/pull/4361
[#4364]: https://github.com/bytedance/deer-flow/pull/4364
[#4365]: https://github.com/bytedance/deer-flow/pull/4365
[#4370]: https://github.com/bytedance/deer-flow/pull/4370
[#4371]: https://github.com/bytedance/deer-flow/pull/4371
[#4373]: https://github.com/bytedance/deer-flow/pull/4373
[#4374]: https://github.com/bytedance/deer-flow/pull/4374
[#4376]: https://github.com/bytedance/deer-flow/pull/4376
[#4377]: https://github.com/bytedance/deer-flow/pull/4377
[#4381]: https://github.com/bytedance/deer-flow/pull/4381
[#4382]: https://github.com/bytedance/deer-flow/pull/4382
[#4383]: https://github.com/bytedance/deer-flow/pull/4383
[#4384]: https://github.com/bytedance/deer-flow/pull/4384
[#4385]: https://github.com/bytedance/deer-flow/pull/4385
[#4391]: https://github.com/bytedance/deer-flow/pull/4391
[#4392]: https://github.com/bytedance/deer-flow/pull/4392
[#4394]: https://github.com/bytedance/deer-flow/pull/4394
[#4395]: https://github.com/bytedance/deer-flow/pull/4395
[#4402]: https://github.com/bytedance/deer-flow/pull/4402
[#4403]: https://github.com/bytedance/deer-flow/pull/4403
[#4405]: https://github.com/bytedance/deer-flow/pull/4405
[#4406]: https://github.com/bytedance/deer-flow/pull/4406
[#4407]: https://github.com/bytedance/deer-flow/pull/4407
[#4408]: https://github.com/bytedance/deer-flow/pull/4408
[#4411]: https://github.com/bytedance/deer-flow/pull/4411
[#4414]: https://github.com/bytedance/deer-flow/pull/4414
[#4423]: https://github.com/bytedance/deer-flow/pull/4423
[#4424]: https://github.com/bytedance/deer-flow/pull/4424
[#4425]: https://github.com/bytedance/deer-flow/pull/4425
[#4426]: https://github.com/bytedance/deer-flow/pull/4426
[#4427]: https://github.com/bytedance/deer-flow/pull/4427
[#4429]: https://github.com/bytedance/deer-flow/pull/4429
[#4430]: https://github.com/bytedance/deer-flow/pull/4430
[#4431]: https://github.com/bytedance/deer-flow/pull/4431
[#4432]: https://github.com/bytedance/deer-flow/pull/4432
[#4434]: https://github.com/bytedance/deer-flow/pull/4434
[#4437]: https://github.com/bytedance/deer-flow/pull/4437
[#4439]: https://github.com/bytedance/deer-flow/pull/4439
[#4441]: https://github.com/bytedance/deer-flow/pull/4441
[#4442]: https://github.com/bytedance/deer-flow/pull/4442
[#4443]: https://github.com/bytedance/deer-flow/pull/4443
[#4444]: https://github.com/bytedance/deer-flow/pull/4444
[#4446]: https://github.com/bytedance/deer-flow/pull/4446
[#4447]: https://github.com/bytedance/deer-flow/pull/4447
[#4448]: https://github.com/bytedance/deer-flow/pull/4448
[#4450]: https://github.com/bytedance/deer-flow/pull/4450
[#4453]: https://github.com/bytedance/deer-flow/pull/4453
[#4456]: https://github.com/bytedance/deer-flow/pull/4456
[#4459]: https://github.com/bytedance/deer-flow/pull/4459
[#4460]: https://github.com/bytedance/deer-flow/pull/4460
[#4468]: https://github.com/bytedance/deer-flow/pull/4468
[#4469]: https://github.com/bytedance/deer-flow/pull/4469
[#4471]: https://github.com/bytedance/deer-flow/pull/4471
[#4472]: https://github.com/bytedance/deer-flow/pull/4472
[#4480]: https://github.com/bytedance/deer-flow/pull/4480
[#4482]: https://github.com/bytedance/deer-flow/pull/4482
[#4486]: https://github.com/bytedance/deer-flow/pull/4486
[#4489]: https://github.com/bytedance/deer-flow/pull/4489
[#4490]: https://github.com/bytedance/deer-flow/pull/4490
[#4493]: https://github.com/bytedance/deer-flow/pull/4493
[#4497]: https://github.com/bytedance/deer-flow/pull/4497
[#4500]: https://github.com/bytedance/deer-flow/pull/4500
[#4501]: https://github.com/bytedance/deer-flow/pull/4501
[#4504]: https://github.com/bytedance/deer-flow/pull/4504
[#4505]: https://github.com/bytedance/deer-flow/pull/4505
[#4506]: https://github.com/bytedance/deer-flow/pull/4506
[#4509]: https://github.com/bytedance/deer-flow/pull/4509
[#4510]: https://github.com/bytedance/deer-flow/pull/4510
[#4512]: https://github.com/bytedance/deer-flow/pull/4512
[#4513]: https://github.com/bytedance/deer-flow/pull/4513
[#4516]: https://github.com/bytedance/deer-flow/pull/4516
[#4518]: https://github.com/bytedance/deer-flow/pull/4518
[#4519]: https://github.com/bytedance/deer-flow/pull/4519
[#4524]: https://github.com/bytedance/deer-flow/pull/4524
[#4527]: https://github.com/bytedance/deer-flow/pull/4527
[#4528]: https://github.com/bytedance/deer-flow/pull/4528
[#4530]: https://github.com/bytedance/deer-flow/pull/4530
[#4533]: https://github.com/bytedance/deer-flow/pull/4533
[#4534]: https://github.com/bytedance/deer-flow/pull/4534
[#4535]: https://github.com/bytedance/deer-flow/pull/4535
[#4538]: https://github.com/bytedance/deer-flow/pull/4538
[#4539]: https://github.com/bytedance/deer-flow/pull/4539
[#4540]: https://github.com/bytedance/deer-flow/pull/4540
[#4556]: https://github.com/bytedance/deer-flow/pull/4556
[#4558]: https://github.com/bytedance/deer-flow/pull/4558
[#4559]: https://github.com/bytedance/deer-flow/pull/4559
[#4564]: https://github.com/bytedance/deer-flow/pull/4564
[#4570]: https://github.com/bytedance/deer-flow/pull/4570
[#4574]: https://github.com/bytedance/deer-flow/pull/4574
[#4575]: https://github.com/bytedance/deer-flow/pull/4575
[#4577]: https://github.com/bytedance/deer-flow/pull/4577
[#4578]: https://github.com/bytedance/deer-flow/pull/4578
[#4582]: https://github.com/bytedance/deer-flow/pull/4582
[#4584]: https://github.com/bytedance/deer-flow/pull/4584
[#4587]: https://github.com/bytedance/deer-flow/pull/4587
[#4589]: https://github.com/bytedance/deer-flow/pull/4589
[#4590]: https://github.com/bytedance/deer-flow/pull/4590
[#4596]: https://github.com/bytedance/deer-flow/pull/4596
[#4599]: https://github.com/bytedance/deer-flow/pull/4599
[#4600]: https://github.com/bytedance/deer-flow/pull/4600
[#4604]: https://github.com/bytedance/deer-flow/pull/4604
[#4611]: https://github.com/bytedance/deer-flow/pull/4611
[#4615]: https://github.com/bytedance/deer-flow/pull/4615
[#4617]: https://github.com/bytedance/deer-flow/pull/4617
[#4618]: https://github.com/bytedance/deer-flow/pull/4618
[#4620]: https://github.com/bytedance/deer-flow/pull/4620
[#4623]: https://github.com/bytedance/deer-flow/pull/4623
[#4624]: https://github.com/bytedance/deer-flow/pull/4624
[#4625]: https://github.com/bytedance/deer-flow/pull/4625
[#4627]: https://github.com/bytedance/deer-flow/pull/4627
[#4629]: https://github.com/bytedance/deer-flow/pull/4629
[#4631]: https://github.com/bytedance/deer-flow/pull/4631
[#4633]: https://github.com/bytedance/deer-flow/pull/4633
[#4634]: https://github.com/bytedance/deer-flow/pull/4634
[#4635]: https://github.com/bytedance/deer-flow/pull/4635
[#4636]: https://github.com/bytedance/deer-flow/pull/4636
[#4638]: https://github.com/bytedance/deer-flow/pull/4638
[#4639]: https://github.com/bytedance/deer-flow/pull/4639
[#4643]: https://github.com/bytedance/deer-flow/pull/4643
[#4644]: https://github.com/bytedance/deer-flow/pull/4644
[#4647]: https://github.com/bytedance/deer-flow/pull/4647
[#4649]: https://github.com/bytedance/deer-flow/pull/4649
[#4657]: https://github.com/bytedance/deer-flow/pull/4657
[#4658]: https://github.com/bytedance/deer-flow/pull/4658
[#4659]: https://github.com/bytedance/deer-flow/pull/4659
[#4660]: https://github.com/bytedance/deer-flow/pull/4660
[#4665]: https://github.com/bytedance/deer-flow/pull/4665
[#4667]: https://github.com/bytedance/deer-flow/pull/4667
[#4668]: https://github.com/bytedance/deer-flow/pull/4668
[#4677]: https://github.com/bytedance/deer-flow/pull/4677
[#4681]: https://github.com/bytedance/deer-flow/pull/4681
[#4683]: https://github.com/bytedance/deer-flow/pull/4683
[#4684]: https://github.com/bytedance/deer-flow/pull/4684
[#4690]: https://github.com/bytedance/deer-flow/pull/4690
[#4693]: https://github.com/bytedance/deer-flow/pull/4693
[#4696]: https://github.com/bytedance/deer-flow/pull/4696
[#4701]: https://github.com/bytedance/deer-flow/pull/4701
[#4703]: https://github.com/bytedance/deer-flow/pull/4703
[#4707]: https://github.com/bytedance/deer-flow/pull/4707
[#4709]: https://github.com/bytedance/deer-flow/pull/4709
[#4713]: https://github.com/bytedance/deer-flow/pull/4713
[#4719]: https://github.com/bytedance/deer-flow/pull/4719
[#4722]: https://github.com/bytedance/deer-flow/pull/4722
[#4724]: https://github.com/bytedance/deer-flow/pull/4724
[#4726]: https://github.com/bytedance/deer-flow/pull/4726
[#4727]: https://github.com/bytedance/deer-flow/pull/4727
[#4729]: https://github.com/bytedance/deer-flow/pull/4729
[#4730]: https://github.com/bytedance/deer-flow/pull/4730
[#4735]: https://github.com/bytedance/deer-flow/pull/4735
[#4736]: https://github.com/bytedance/deer-flow/pull/4736
[#4737]: https://github.com/bytedance/deer-flow/pull/4737
[#4738]: https://github.com/bytedance/deer-flow/pull/4738
[#4744]: https://github.com/bytedance/deer-flow/pull/4744
[#4745]: https://github.com/bytedance/deer-flow/pull/4745
[#4747]: https://github.com/bytedance/deer-flow/pull/4747
[#4748]: https://github.com/bytedance/deer-flow/pull/4748
[#4750]: https://github.com/bytedance/deer-flow/pull/4750
[#4752]: https://github.com/bytedance/deer-flow/pull/4752
[#4755]: https://github.com/bytedance/deer-flow/pull/4755
[#4758]: https://github.com/bytedance/deer-flow/pull/4758
[#4759]: https://github.com/bytedance/deer-flow/pull/4759
[#4760]: https://github.com/bytedance/deer-flow/pull/4760
[#4762]: https://github.com/bytedance/deer-flow/pull/4762
[#4764]: https://github.com/bytedance/deer-flow/pull/4764
[#4767]: https://github.com/bytedance/deer-flow/pull/4767
[#4769]: https://github.com/bytedance/deer-flow/pull/4769
[#4772]: https://github.com/bytedance/deer-flow/pull/4772
[#4780]: https://github.com/bytedance/deer-flow/pull/4780
[#4783]: https://github.com/bytedance/deer-flow/pull/4783
[#4785]: https://github.com/bytedance/deer-flow/pull/4785
[#4789]: https://github.com/bytedance/deer-flow/pull/4789
[#4792]: https://github.com/bytedance/deer-flow/pull/4792
[#4797]: https://github.com/bytedance/deer-flow/pull/4797
[#4800]: https://github.com/bytedance/deer-flow/pull/4800
[#4804]: https://github.com/bytedance/deer-flow/pull/4804
[#4806]: https://github.com/bytedance/deer-flow/pull/4806
[#4810]: https://github.com/bytedance/deer-flow/pull/4810
[#4812]: https://github.com/bytedance/deer-flow/pull/4812
[#4815]: https://github.com/bytedance/deer-flow/pull/4815
[#4816]: https://github.com/bytedance/deer-flow/pull/4816
[#4817]: https://github.com/bytedance/deer-flow/pull/4817
[#4820]: https://github.com/bytedance/deer-flow/pull/4820
[#4822]: https://github.com/bytedance/deer-flow/pull/4822
[#4823]: https://github.com/bytedance/deer-flow/pull/4823
[#4825]: https://github.com/bytedance/deer-flow/pull/4825
[#4826]: https://github.com/bytedance/deer-flow/pull/4826
[#4827]: https://github.com/bytedance/deer-flow/pull/4827
[#4830]: https://github.com/bytedance/deer-flow/pull/4830
[#4833]: https://github.com/bytedance/deer-flow/pull/4833
[#4834]: https://github.com/bytedance/deer-flow/pull/4834
[#4836]: https://github.com/bytedance/deer-flow/pull/4836
[#4838]: https://github.com/bytedance/deer-flow/pull/4838
[#4839]: https://github.com/bytedance/deer-flow/pull/4839
[#4840]: https://github.com/bytedance/deer-flow/pull/4840
[#4842]: https://github.com/bytedance/deer-flow/pull/4842
[#4844]: https://github.com/bytedance/deer-flow/pull/4844
[#4846]: https://github.com/bytedance/deer-flow/pull/4846
[#4848]: https://github.com/bytedance/deer-flow/pull/4848
[#4852]: https://github.com/bytedance/deer-flow/pull/4852
[#4853]: https://github.com/bytedance/deer-flow/pull/4853
[#4860]: https://github.com/bytedance/deer-flow/pull/4860
[#4861]: https://github.com/bytedance/deer-flow/pull/4861
[#4863]: https://github.com/bytedance/deer-flow/pull/4863
[#4865]: https://github.com/bytedance/deer-flow/pull/4865
[#4867]: https://github.com/bytedance/deer-flow/pull/4867
[#4868]: https://github.com/bytedance/deer-flow/pull/4868
[#4876]: https://github.com/bytedance/deer-flow/pull/4876
[#4877]: https://github.com/bytedance/deer-flow/pull/4877
[#4878]: https://github.com/bytedance/deer-flow/pull/4878
[#4882]: https://github.com/bytedance/deer-flow/pull/4882
[#4884]: https://github.com/bytedance/deer-flow/pull/4884
[#4887]: https://github.com/bytedance/deer-flow/pull/4887
[#4888]: https://github.com/bytedance/deer-flow/pull/4888
[#4892]: https://github.com/bytedance/deer-flow/pull/4892
[#4898]: https://github.com/bytedance/deer-flow/pull/4898
[#4901]: https://github.com/bytedance/deer-flow/pull/4901
[#4903]: https://github.com/bytedance/deer-flow/pull/4903
[#4911]: https://github.com/bytedance/deer-flow/pull/4911
[#4918]: https://github.com/bytedance/deer-flow/pull/4918
[#4919]: https://github.com/bytedance/deer-flow/pull/4919
[#4921]: https://github.com/bytedance/deer-flow/pull/4921
[#4928]: https://github.com/bytedance/deer-flow/pull/4928
[#4933]: https://github.com/bytedance/deer-flow/pull/4933
[#4936]: https://github.com/bytedance/deer-flow/pull/4936
[#4938]: https://github.com/bytedance/deer-flow/pull/4938
[#4944]: https://github.com/bytedance/deer-flow/pull/4944
[#4946]: https://github.com/bytedance/deer-flow/pull/4946
[#4951]: https://github.com/bytedance/deer-flow/pull/4951
[#4952]: https://github.com/bytedance/deer-flow/pull/4952
[#4953]: https://github.com/bytedance/deer-flow/pull/4953
[#4955]: https://github.com/bytedance/deer-flow/pull/4955
[#4956]: https://github.com/bytedance/deer-flow/pull/4956
[#4959]: https://github.com/bytedance/deer-flow/pull/4959
[#4960]: https://github.com/bytedance/deer-flow/pull/4960
[#4962]: https://github.com/bytedance/deer-flow/pull/4962
[#4963]: https://github.com/bytedance/deer-flow/pull/4963
[#4965]: https://github.com/bytedance/deer-flow/pull/4965
[#4966]: https://github.com/bytedance/deer-flow/pull/4966
[#4970]: https://github.com/bytedance/deer-flow/pull/4970
[#4972]: https://github.com/bytedance/deer-flow/pull/4972
[#4977]: https://github.com/bytedance/deer-flow/pull/4977
[#4980]: https://github.com/bytedance/deer-flow/pull/4980
[#4983]: https://github.com/bytedance/deer-flow/pull/4983
[#4984]: https://github.com/bytedance/deer-flow/pull/4984
[#4986]: https://github.com/bytedance/deer-flow/pull/4986
[#4987]: https://github.com/bytedance/deer-flow/pull/4987
[#4989]: https://github.com/bytedance/deer-flow/pull/4989
[#4995]: https://github.com/bytedance/deer-flow/pull/4995
[#4998]: https://github.com/bytedance/deer-flow/pull/4998
[#5001]: https://github.com/bytedance/deer-flow/pull/5001
[#5003]: https://github.com/bytedance/deer-flow/pull/5003
[#5006]: https://github.com/bytedance/deer-flow/pull/5006
[#5008]: https://github.com/bytedance/deer-flow/pull/5008
[#5010]: https://github.com/bytedance/deer-flow/pull/5010
[#5014]: https://github.com/bytedance/deer-flow/pull/5014
[#5017]: https://github.com/bytedance/deer-flow/pull/5017
[#5018]: https://github.com/bytedance/deer-flow/pull/5018
[#5021]: https://github.com/bytedance/deer-flow/pull/5021
[#5022]: https://github.com/bytedance/deer-flow/pull/5022
[#5023]: https://github.com/bytedance/deer-flow/pull/5023
[#5025]: https://github.com/bytedance/deer-flow/pull/5025
[#5026]: https://github.com/bytedance/deer-flow/pull/5026
[#5027]: https://github.com/bytedance/deer-flow/pull/5027
[#5028]: https://github.com/bytedance/deer-flow/pull/5028
[#5030]: https://github.com/bytedance/deer-flow/pull/5030
[#5031]: https://github.com/bytedance/deer-flow/pull/5031
[#5036]: https://github.com/bytedance/deer-flow/pull/5036
[#5039]: https://github.com/bytedance/deer-flow/pull/5039
[#5041]: https://github.com/bytedance/deer-flow/pull/5041
[#5045]: https://github.com/bytedance/deer-flow/pull/5045
[#5047]: https://github.com/bytedance/deer-flow/pull/5047
[#5049]: https://github.com/bytedance/deer-flow/pull/5049
[#5050]: https://github.com/bytedance/deer-flow/pull/5050
[#5051]: https://github.com/bytedance/deer-flow/pull/5051
[#5056]: https://github.com/bytedance/deer-flow/pull/5056
[#5057]: https://github.com/bytedance/deer-flow/pull/5057
[#5059]: https://github.com/bytedance/deer-flow/pull/5059
[#5062]: https://github.com/bytedance/deer-flow/pull/5062
[#5064]: https://github.com/bytedance/deer-flow/pull/5064
[#5066]: https://github.com/bytedance/deer-flow/pull/5066
[#5069]: https://github.com/bytedance/deer-flow/pull/5069
[#5071]: https://github.com/bytedance/deer-flow/pull/5071
[#5074]: https://github.com/bytedance/deer-flow/pull/5074
[#5076]: https://github.com/bytedance/deer-flow/pull/5076
[#5077]: https://github.com/bytedance/deer-flow/pull/5077
[#5080]: https://github.com/bytedance/deer-flow/pull/5080
[#5083]: https://github.com/bytedance/deer-flow/pull/5083
[#5086]: https://github.com/bytedance/deer-flow/pull/5086
[#5087]: https://github.com/bytedance/deer-flow/pull/5087
[#5089]: https://github.com/bytedance/deer-flow/pull/5089
[#5090]: https://github.com/bytedance/deer-flow/pull/5090
[#5092]: https://github.com/bytedance/deer-flow/pull/5092
[#5095]: https://github.com/bytedance/deer-flow/pull/5095
[#5099]: https://github.com/bytedance/deer-flow/pull/5099
[#5103]: https://github.com/bytedance/deer-flow/pull/5103
[#5104]: https://github.com/bytedance/deer-flow/pull/5104
[#5105]: https://github.com/bytedance/deer-flow/pull/5105
[#5109]: https://github.com/bytedance/deer-flow/pull/5109
[#5110]: https://github.com/bytedance/deer-flow/pull/5110
[#5111]: https://github.com/bytedance/deer-flow/pull/5111
[#5112]: https://github.com/bytedance/deer-flow/pull/5112
[#5117]: https://github.com/bytedance/deer-flow/pull/5117
[#5119]: https://github.com/bytedance/deer-flow/pull/5119
[#5123]: https://github.com/bytedance/deer-flow/pull/5123
[#5133]: https://github.com/bytedance/deer-flow/pull/5133
[#5134]: https://github.com/bytedance/deer-flow/pull/5134
[#5136]: https://github.com/bytedance/deer-flow/pull/5136
[#5137]: https://github.com/bytedance/deer-flow/pull/5137
[#5141]: https://github.com/bytedance/deer-flow/pull/5141
[#5145]: https://github.com/bytedance/deer-flow/pull/5145
[#5148]: https://github.com/bytedance/deer-flow/pull/5148
[#5149]: https://github.com/bytedance/deer-flow/pull/5149
[#5152]: https://github.com/bytedance/deer-flow/pull/5152
[#5153]: https://github.com/bytedance/deer-flow/pull/5153
[#5154]: https://github.com/bytedance/deer-flow/pull/5154
[#5155]: https://github.com/bytedance/deer-flow/pull/5155
[#5156]: https://github.com/bytedance/deer-flow/pull/5156
[#5159]: https://github.com/bytedance/deer-flow/pull/5159
[#5162]: https://github.com/bytedance/deer-flow/pull/5162
[#5163]: https://github.com/bytedance/deer-flow/pull/5163
[#5164]: https://github.com/bytedance/deer-flow/pull/5164
[#5166]: https://github.com/bytedance/deer-flow/pull/5166
[#5167]: https://github.com/bytedance/deer-flow/pull/5167
[#5168]: https://github.com/bytedance/deer-flow/pull/5168
[#5170]: https://github.com/bytedance/deer-flow/pull/5170
[#5178]: https://github.com/bytedance/deer-flow/pull/5178
[#5181]: https://github.com/bytedance/deer-flow/pull/5181
[#5183]: https://github.com/bytedance/deer-flow/pull/5183
[#5185]: https://github.com/bytedance/deer-flow/pull/5185
[#5187]: https://github.com/bytedance/deer-flow/pull/5187
[#5191]: https://github.com/bytedance/deer-flow/pull/5191
[#5197]: https://github.com/bytedance/deer-flow/pull/5197
[#5206]: https://github.com/bytedance/deer-flow/pull/5206
[#5209]: https://github.com/bytedance/deer-flow/pull/5209
[#5214]: https://github.com/bytedance/deer-flow/pull/5214
[#5216]: https://github.com/bytedance/deer-flow/pull/5216
[#5217]: https://github.com/bytedance/deer-flow/pull/5217
[#5219]: https://github.com/bytedance/deer-flow/pull/5219
[#5221]: https://github.com/bytedance/deer-flow/pull/5221
[#5224]: https://github.com/bytedance/deer-flow/pull/5224
[#5225]: https://github.com/bytedance/deer-flow/pull/5225
[#5227]: https://github.com/bytedance/deer-flow/pull/5227
[#5228]: https://github.com/bytedance/deer-flow/pull/5228
[#5232]: https://github.com/bytedance/deer-flow/pull/5232
[#5234]: https://github.com/bytedance/deer-flow/pull/5234
[#5236]: https://github.com/bytedance/deer-flow/pull/5236
[#5238]: https://github.com/bytedance/deer-flow/pull/5238
[#5239]: https://github.com/bytedance/deer-flow/pull/5239
[#5244]: https://github.com/bytedance/deer-flow/pull/5244
[#5245]: https://github.com/bytedance/deer-flow/pull/5245
[#5247]: https://github.com/bytedance/deer-flow/pull/5247
[#5249]: https://github.com/bytedance/deer-flow/pull/5249
[#5251]: https://github.com/bytedance/deer-flow/pull/5251
[#5254]: https://github.com/bytedance/deer-flow/pull/5254
[#5255]: https://github.com/bytedance/deer-flow/pull/5255
[#5261]: https://github.com/bytedance/deer-flow/pull/5261
[#5264]: https://github.com/bytedance/deer-flow/pull/5264
[#5265]: https://github.com/bytedance/deer-flow/pull/5265
[#5275]: https://github.com/bytedance/deer-flow/pull/5275
[#5278]: https://github.com/bytedance/deer-flow/pull/5278
[#5279]: https://github.com/bytedance/deer-flow/pull/5279
[#5280]: https://github.com/bytedance/deer-flow/pull/5280
[#5281]: https://github.com/bytedance/deer-flow/pull/5281
[#5282]: https://github.com/bytedance/deer-flow/pull/5282
[#5283]: https://github.com/bytedance/deer-flow/pull/5283
[#5284]: https://github.com/bytedance/deer-flow/pull/5284
[#5286]: https://github.com/bytedance/deer-flow/pull/5286
[#5287]: https://github.com/bytedance/deer-flow/pull/5287
[#5288]: https://github.com/bytedance/deer-flow/pull/5288
[#5289]: https://github.com/bytedance/deer-flow/pull/5289
[#5291]: https://github.com/bytedance/deer-flow/pull/5291
[#5293]: https://github.com/bytedance/deer-flow/pull/5293
[#5294]: https://github.com/bytedance/deer-flow/pull/5294
[#5296]: https://github.com/bytedance/deer-flow/pull/5296
[#5299]: https://github.com/bytedance/deer-flow/pull/5299
[#5304]: https://github.com/bytedance/deer-flow/pull/5304
[#5305]: https://github.com/bytedance/deer-flow/pull/5305
[#5306]: https://github.com/bytedance/deer-flow/pull/5306
[#5308]: https://github.com/bytedance/deer-flow/pull/5308
[#5309]: https://github.com/bytedance/deer-flow/pull/5309
[#5310]: https://github.com/bytedance/deer-flow/pull/5310
[#5312]: https://github.com/bytedance/deer-flow/pull/5312
[#5315]: https://github.com/bytedance/deer-flow/pull/5315
[#5316]: https://github.com/bytedance/deer-flow/pull/5316
[#5318]: https://github.com/bytedance/deer-flow/pull/5318
[#5321]: https://github.com/bytedance/deer-flow/pull/5321
[#5323]: https://github.com/bytedance/deer-flow/pull/5323
[#5324]: https://github.com/bytedance/deer-flow/pull/5324
[#5326]: https://github.com/bytedance/deer-flow/pull/5326
[#5329]: https://github.com/bytedance/deer-flow/pull/5329
[#5330]: https://github.com/bytedance/deer-flow/pull/5330
[#5332]: https://github.com/bytedance/deer-flow/pull/5332
[#5338]: https://github.com/bytedance/deer-flow/pull/5338
[#5341]: https://github.com/bytedance/deer-flow/pull/5341
[#5344]: https://github.com/bytedance/deer-flow/pull/5344
[#5347]: https://github.com/bytedance/deer-flow/pull/5347
[#5348]: https://github.com/bytedance/deer-flow/pull/5348
[#5350]: https://github.com/bytedance/deer-flow/pull/5350
[#5353]: https://github.com/bytedance/deer-flow/pull/5353
[#5355]: https://github.com/bytedance/deer-flow/pull/5355
[#5357]: https://github.com/bytedance/deer-flow/pull/5357
[#5359]: https://github.com/bytedance/deer-flow/pull/5359
[#5361]: https://github.com/bytedance/deer-flow/pull/5361
[#5363]: https://github.com/bytedance/deer-flow/pull/5363
[#5367]: https://github.com/bytedance/deer-flow/pull/5367
[#5369]: https://github.com/bytedance/deer-flow/pull/5369
[#5371]: https://github.com/bytedance/deer-flow/pull/5371
[#5373]: https://github.com/bytedance/deer-flow/pull/5373
[#5374]: https://github.com/bytedance/deer-flow/pull/5374
[#5375]: https://github.com/bytedance/deer-flow/pull/5375
[#5377]: https://github.com/bytedance/deer-flow/pull/5377
[#5380]: https://github.com/bytedance/deer-flow/pull/5380
[#5381]: https://github.com/bytedance/deer-flow/pull/5381
[#5382]: https://github.com/bytedance/deer-flow/pull/5382
[#5384]: https://github.com/bytedance/deer-flow/pull/5384
[#5388]: https://github.com/bytedance/deer-flow/pull/5388
[#5389]: https://github.com/bytedance/deer-flow/pull/5389
[#5390]: https://github.com/bytedance/deer-flow/pull/5390
[#5392]: https://github.com/bytedance/deer-flow/pull/5392
[#5393]: https://github.com/bytedance/deer-flow/pull/5393
[#5395]: https://github.com/bytedance/deer-flow/pull/5395
[#5396]: https://github.com/bytedance/deer-flow/pull/5396
[#5397]: https://github.com/bytedance/deer-flow/pull/5397
[#5399]: https://github.com/bytedance/deer-flow/pull/5399
[#5401]: https://github.com/bytedance/deer-flow/pull/5401
[#5402]: https://github.com/bytedance/deer-flow/pull/5402
[#5403]: https://github.com/bytedance/deer-flow/pull/5403
[#5404]: https://github.com/bytedance/deer-flow/pull/5404
[#5405]: https://github.com/bytedance/deer-flow/pull/5405
[#5406]: https://github.com/bytedance/deer-flow/pull/5406
[#5407]: https://github.com/bytedance/deer-flow/pull/5407
[#5408]: https://github.com/bytedance/deer-flow/pull/5408
[#5410]: https://github.com/bytedance/deer-flow/pull/5410
[#5411]: https://github.com/bytedance/deer-flow/pull/5411
[#5413]: https://github.com/bytedance/deer-flow/pull/5413
[#5415]: https://github.com/bytedance/deer-flow/pull/5415
[#5416]: https://github.com/bytedance/deer-flow/pull/5416
[#5418]: https://github.com/bytedance/deer-flow/pull/5418
[#5419]: https://github.com/bytedance/deer-flow/pull/5419
[#5421]: https://github.com/bytedance/deer-flow/pull/5421
[#5422]: https://github.com/bytedance/deer-flow/pull/5422
[#5424]: https://github.com/bytedance/deer-flow/pull/5424
[#5426]: https://github.com/bytedance/deer-flow/pull/5426
[#5427]: https://github.com/bytedance/deer-flow/pull/5427
[#5428]: https://github.com/bytedance/deer-flow/pull/5428
[#5429]: https://github.com/bytedance/deer-flow/pull/5429
[#5431]: https://github.com/bytedance/deer-flow/pull/5431
[#5432]: https://github.com/bytedance/deer-flow/pull/5432
[#5433]: https://github.com/bytedance/deer-flow/pull/5433
[#5436]: https://github.com/bytedance/deer-flow/pull/5436
[#5439]: https://github.com/bytedance/deer-flow/pull/5439
[#5440]: https://github.com/bytedance/deer-flow/pull/5440
[#5441]: https://github.com/bytedance/deer-flow/pull/5441
[#5442]: https://github.com/bytedance/deer-flow/pull/5442
[#5443]: https://github.com/bytedance/deer-flow/pull/5443
[#5444]: https://github.com/bytedance/deer-flow/pull/5444
[#5446]: https://github.com/bytedance/deer-flow/pull/5446
[#5447]: https://github.com/bytedance/deer-flow/pull/5447
[#5448]: https://github.com/bytedance/deer-flow/pull/5448
[#5449]: https://github.com/bytedance/deer-flow/pull/5449
[#5451]: https://github.com/bytedance/deer-flow/pull/5451
[#5453]: https://github.com/bytedance/deer-flow/pull/5453
[#5454]: https://github.com/bytedance/deer-flow/pull/5454
[#5455]: https://github.com/bytedance/deer-flow/pull/5455
[#5456]: https://github.com/bytedance/deer-flow/pull/5456
[#5458]: https://github.com/bytedance/deer-flow/pull/5458
[#5459]: https://github.com/bytedance/deer-flow/pull/5459
[#5461]: https://github.com/bytedance/deer-flow/pull/5461
[#5462]: https://github.com/bytedance/deer-flow/pull/5462
[#5463]: https://github.com/bytedance/deer-flow/pull/5463
[#5465]: https://github.com/bytedance/deer-flow/pull/5465
[#5467]: https://github.com/bytedance/deer-flow/pull/5467
[#5468]: https://github.com/bytedance/deer-flow/pull/5468
[#5469]: https://github.com/bytedance/deer-flow/pull/5469
[#5470]: https://github.com/bytedance/deer-flow/pull/5470
[#5474]: https://github.com/bytedance/deer-flow/pull/5474
[#5477]: https://github.com/bytedance/deer-flow/pull/5477
[#5478]: https://github.com/bytedance/deer-flow/pull/5478
[#5479]: https://github.com/bytedance/deer-flow/pull/5479
[#5480]: https://github.com/bytedance/deer-flow/pull/5480
[#5483]: https://github.com/bytedance/deer-flow/pull/5483
[#5484]: https://github.com/bytedance/deer-flow/pull/5484
[#5485]: https://github.com/bytedance/deer-flow/pull/5485
[#5486]: https://github.com/bytedance/deer-flow/pull/5486
[#5487]: https://github.com/bytedance/deer-flow/pull/5487
[#5488]: https://github.com/bytedance/deer-flow/pull/5488
[#5489]: https://github.com/bytedance/deer-flow/pull/5489
[#5490]: https://github.com/bytedance/deer-flow/pull/5490
[#5492]: https://github.com/bytedance/deer-flow/pull/5492
[#5494]: https://github.com/bytedance/deer-flow/pull/5494
[#5496]: https://github.com/bytedance/deer-flow/pull/5496
[#5497]: https://github.com/bytedance/deer-flow/pull/5497
[#5498]: https://github.com/bytedance/deer-flow/pull/5498
[#5501]: https://github.com/bytedance/deer-flow/pull/5501
[#5504]: https://github.com/bytedance/deer-flow/pull/5504
[#5505]: https://github.com/bytedance/deer-flow/pull/5505
[#5506]: https://github.com/bytedance/deer-flow/pull/5506
[#5507]: https://github.com/bytedance/deer-flow/pull/5507
[#5508]: https://github.com/bytedance/deer-flow/pull/5508
[#5509]: https://github.com/bytedance/deer-flow/pull/5509
[#5511]: https://github.com/bytedance/deer-flow/pull/5511
[#5515]: https://github.com/bytedance/deer-flow/pull/5515
[#5517]: https://github.com/bytedance/deer-flow/pull/5517
[#5518]: https://github.com/bytedance/deer-flow/pull/5518
[#5522]: https://github.com/bytedance/deer-flow/pull/5522
[#5524]: https://github.com/bytedance/deer-flow/pull/5524
[#5525]: https://github.com/bytedance/deer-flow/pull/5525
[#5526]: https://github.com/bytedance/deer-flow/pull/5526
[#5527]: https://github.com/bytedance/deer-flow/pull/5527
[#5528]: https://github.com/bytedance/deer-flow/pull/5528
[#5531]: https://github.com/bytedance/deer-flow/pull/5531
[#5534]: https://github.com/bytedance/deer-flow/pull/5534
[#5535]: https://github.com/bytedance/deer-flow/pull/5535
[#5536]: https://github.com/bytedance/deer-flow/pull/5536
[#5537]: https://github.com/bytedance/deer-flow/pull/5537
[#5538]: https://github.com/bytedance/deer-flow/pull/5538
[#5540]: https://github.com/bytedance/deer-flow/pull/5540
[#5541]: https://github.com/bytedance/deer-flow/pull/5541
[#5544]: https://github.com/bytedance/deer-flow/pull/5544
[#5545]: https://github.com/bytedance/deer-flow/pull/5545
[#5546]: https://github.com/bytedance/deer-flow/pull/5546
[#5547]: https://github.com/bytedance/deer-flow/pull/5547
[#5549]: https://github.com/bytedance/deer-flow/pull/5549
[#5551]: https://github.com/bytedance/deer-flow/pull/5551
[#5555]: https://github.com/bytedance/deer-flow/pull/5555
[#5556]: https://github.com/bytedance/deer-flow/pull/5556
[#5559]: https://github.com/bytedance/deer-flow/pull/5559
[#5560]: https://github.com/bytedance/deer-flow/pull/5560
[#5562]: https://github.com/bytedance/deer-flow/pull/5562
[#5563]: https://github.com/bytedance/deer-flow/pull/5563
[#5564]: https://github.com/bytedance/deer-flow/pull/5564
[#5567]: https://github.com/bytedance/deer-flow/pull/5567
[#5569]: https://github.com/bytedance/deer-flow/pull/5569
[#5570]: https://github.com/bytedance/deer-flow/pull/5570
[#5572]: https://github.com/bytedance/deer-flow/pull/5572
[#5573]: https://github.com/bytedance/deer-flow/pull/5573
[#5576]: https://github.com/bytedance/deer-flow/pull/5576
[#5578]: https://github.com/bytedance/deer-flow/pull/5578
[#5579]: https://github.com/bytedance/deer-flow/pull/5579
[#5580]: https://github.com/bytedance/deer-flow/pull/5580
[#5581]: https://github.com/bytedance/deer-flow/pull/5581
[#5582]: https://github.com/bytedance/deer-flow/pull/5582
[#5583]: https://github.com/bytedance/deer-flow/pull/5583
[#5584]: https://github.com/bytedance/deer-flow/pull/5584
[#5586]: https://github.com/bytedance/deer-flow/pull/5586
[#5588]: https://github.com/bytedance/deer-flow/pull/5588
[#5591]: https://github.com/bytedance/deer-flow/pull/5591
[#5593]: https://github.com/bytedance/deer-flow/pull/5593
[#5594]: https://github.com/bytedance/deer-flow/pull/5594
[#5596]: https://github.com/bytedance/deer-flow/pull/5596
[#5601]: https://github.com/bytedance/deer-flow/pull/5601
[#5602]: https://github.com/bytedance/deer-flow/pull/5602
[#5605]: https://github.com/bytedance/deer-flow/pull/5605
[#5607]: https://github.com/bytedance/deer-flow/pull/5607
[#5609]: https://github.com/bytedance/deer-flow/pull/5609
[#5611]: https://github.com/bytedance/deer-flow/pull/5611
[#5612]: https://github.com/bytedance/deer-flow/pull/5612
[#5614]: https://github.com/bytedance/deer-flow/pull/5614
[#5616]: https://github.com/bytedance/deer-flow/pull/5616
[#5617]: https://github.com/bytedance/deer-flow/pull/5617
[#5621]: https://github.com/bytedance/deer-flow/pull/5621
[#5622]: https://github.com/bytedance/deer-flow/pull/5622
[#5625]: https://github.com/bytedance/deer-flow/pull/5625
[#5630]: https://github.com/bytedance/deer-flow/pull/5630
[#5631]: https://github.com/bytedance/deer-flow/pull/5631
[#5634]: https://github.com/bytedance/deer-flow/pull/5634
[#5640]: https://github.com/bytedance/deer-flow/pull/5640
[#5643]: https://github.com/bytedance/deer-flow/pull/5643
[#5647]: https://github.com/bytedance/deer-flow/pull/5647
[#5648]: https://github.com/bytedance/deer-flow/pull/5648
[#5649]: https://github.com/bytedance/deer-flow/pull/5649
[#5650]: https://github.com/bytedance/deer-flow/pull/5650
[#5651]: https://github.com/bytedance/deer-flow/pull/5651
[#5652]: https://github.com/bytedance/deer-flow/pull/5652
[#5654]: https://github.com/bytedance/deer-flow/pull/5654
[#5655]: https://github.com/bytedance/deer-flow/pull/5655
[#5656]: https://github.com/bytedance/deer-flow/pull/5656
[#5659]: https://github.com/bytedance/deer-flow/pull/5659
[#5662]: https://github.com/bytedance/deer-flow/pull/5662
[#5663]: https://github.com/bytedance/deer-flow/pull/5663
[#5664]: https://github.com/bytedance/deer-flow/pull/5664
[#5669]: https://github.com/bytedance/deer-flow/pull/5669
[#5673]: https://github.com/bytedance/deer-flow/pull/5673
[#5676]: https://github.com/bytedance/deer-flow/pull/5676
[#5677]: https://github.com/bytedance/deer-flow/pull/5677
[#5678]: https://github.com/bytedance/deer-flow/pull/5678
[#5680]: https://github.com/bytedance/deer-flow/pull/5680
[#5682]: https://github.com/bytedance/deer-flow/pull/5682
[#5683]: https://github.com/bytedance/deer-flow/pull/5683
[#5684]: https://github.com/bytedance/deer-flow/pull/5684
[#5685]: https://github.com/bytedance/deer-flow/pull/5685
[#5687]: https://github.com/bytedance/deer-flow/pull/5687
[#5688]: https://github.com/bytedance/deer-flow/pull/5688
[#5691]: https://github.com/bytedance/deer-flow/pull/5691
[#5702]: https://github.com/bytedance/deer-flow/pull/5702
[#5703]: https://github.com/bytedance/deer-flow/pull/5703
[#5705]: https://github.com/bytedance/deer-flow/pull/5705
[#5711]: https://github.com/bytedance/deer-flow/pull/5711
[#5712]: https://github.com/bytedance/deer-flow/pull/5712
[#5718]: https://github.com/bytedance/deer-flow/pull/5718
[#5719]: https://github.com/bytedance/deer-flow/pull/5719
[#5723]: https://github.com/bytedance/deer-flow/pull/5723
[#5727]: https://github.com/bytedance/deer-flow/pull/5727
[#5729]: https://github.com/bytedance/deer-flow/pull/5729
[#5731]: https://github.com/bytedance/deer-flow/pull/5731
[#5733]: https://github.com/bytedance/deer-flow/pull/5733
[#5734]: https://github.com/bytedance/deer-flow/pull/5734
[#5735]: https://github.com/bytedance/deer-flow/pull/5735
[#5736]: https://github.com/bytedance/deer-flow/pull/5736
[#5738]: https://github.com/bytedance/deer-flow/pull/5738
[#5739]: https://github.com/bytedance/deer-flow/pull/5739
[#5740]: https://github.com/bytedance/deer-flow/pull/5740
[#5741]: https://github.com/bytedance/deer-flow/pull/5741
[#5745]: https://github.com/bytedance/deer-flow/pull/5745
[#5748]: https://github.com/bytedance/deer-flow/pull/5748
[#5750]: https://github.com/bytedance/deer-flow/pull/5750
[#5755]: https://github.com/bytedance/deer-flow/pull/5755
[#5756]: https://github.com/bytedance/deer-flow/pull/5756
[#5757]: https://github.com/bytedance/deer-flow/pull/5757
[#5758]: https://github.com/bytedance/deer-flow/pull/5758
[#5759]: https://github.com/bytedance/deer-flow/pull/5759
[#5760]: https://github.com/bytedance/deer-flow/pull/5760
[#5761]: https://github.com/bytedance/deer-flow/pull/5761
[#5762]: https://github.com/bytedance/deer-flow/pull/5762
[#5767]: https://github.com/bytedance/deer-flow/pull/5767
[#5769]: https://github.com/bytedance/deer-flow/pull/5769
[#5775]: https://github.com/bytedance/deer-flow/pull/5775
[#5776]: https://github.com/bytedance/deer-flow/pull/5776
[#5777]: https://github.com/bytedance/deer-flow/pull/5777
[#5778]: https://github.com/bytedance/deer-flow/pull/5778
[#5780]: https://github.com/bytedance/deer-flow/pull/5780
[#5785]: https://github.com/bytedance/deer-flow/pull/5785
[#5792]: https://github.com/bytedance/deer-flow/pull/5792
[#5794]: https://github.com/bytedance/deer-flow/pull/5794
[#5796]: https://github.com/bytedance/deer-flow/pull/5796
[#5797]: https://github.com/bytedance/deer-flow/pull/5797
[#5798]: https://github.com/bytedance/deer-flow/pull/5798
[#5799]: https://github.com/bytedance/deer-flow/pull/5799
[#5801]: https://github.com/bytedance/deer-flow/pull/5801
[#5803]: https://github.com/bytedance/deer-flow/pull/5803
[#5804]: https://github.com/bytedance/deer-flow/pull/5804
[#5806]: https://github.com/bytedance/deer-flow/pull/5806
[#5807]: https://github.com/bytedance/deer-flow/pull/5807
[#5811]: https://github.com/bytedance/deer-flow/pull/5811
[#5812]: https://github.com/bytedance/deer-flow/pull/5812
[#5815]: https://github.com/bytedance/deer-flow/pull/5815
[#5816]: https://github.com/bytedance/deer-flow/pull/5816
[#5819]: https://github.com/bytedance/deer-flow/pull/5819
[#5823]: https://github.com/bytedance/deer-flow/pull/5823
[#5824]: https://github.com/bytedance/deer-flow/pull/5824
[#5830]: https://github.com/bytedance/deer-flow/pull/5830
[#5833]: https://github.com/bytedance/deer-flow/pull/5833
[#5836]: https://github.com/bytedance/deer-flow/pull/5836
[#5838]: https://github.com/bytedance/deer-flow/pull/5838
[#5839]: https://github.com/bytedance/deer-flow/pull/5839
[#5840]: https://github.com/bytedance/deer-flow/pull/5840
[#5841]: https://github.com/bytedance/deer-flow/pull/5841
[#5842]: https://github.com/bytedance/deer-flow/pull/5842
[#5844]: https://github.com/bytedance/deer-flow/pull/5844
[#5845]: https://github.com/bytedance/deer-flow/pull/5845
[#5848]: https://github.com/bytedance/deer-flow/pull/5848

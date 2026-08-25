# Changelog

All notable changes to DeerFlow are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

This section accumulates work toward the **2.1.0** milestone
([milestone 2](https://github.com/bytedance/deer-flow/milestone/2)).

### ⚠ Breaking changes

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

#### Agents & runtime

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

#### Skills

- **skills:** Native SkillScan (phase 1) statically analyzes skill packages at
  load, and `describe_skill` enables deferred discovery so the model fetches a
  skill's schema on demand instead of loading all skills up front. ([#3033],
  [#3775])
- **skills:** Per-user custom skill isolation with sandbox mounting. ([#3889])
- **skills:** The skill list reopens after a skill is selected, so several
  skills can be attached in a row. ([#4639])

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
- **frontend:** Browser Live is available in Custom Agent chats. ([#4719])
- **threads:** Branched conversations get distinguishing titles
  (automatic `Title (2)`, `Title (3)` sibling numbering) and the
  recent-chats list shows parent-child lineage with tree connectors.
  ([#4983])

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
  [#4660])
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
  and retry action instead of a silently empty model list. ([#4840])
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

### Security

- **prompt-injection:** New input-sanitization middleware defends against
  prompt-injection, forged framework tags in the input guardrail are blocked,
  and system context is injected as a `SystemMessage` for role isolation. ([#3662],
  [#4155], [#3661])
- **prompt-injection:** HTML-escape untrusted content rendered into model prompts
  - memory facts and summaries, `SOUL.md`, subagent descriptions, skill metadata,
  and the conversation block in the memory-update prompt - and neutralize
  prompt-injection tags in `web_capture` tool results. ([#4028], [#4119], [#4137],
  [#4157], [#4162], [#4099], [#4060], [#4097], [#4128])
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

### Documentation

- **docs:** Clarify how `LocalSandboxProvider` resolves `sandbox.mounts[].host_path`
  under production Docker, with gateway bind-mount and config examples. ([#3833])
- **docs:** Document that Crawl4AI >= 0.9 requires a bearer token. ([#4518])
- **docs:** Document the GitHub inbound-dedupe TTL semantics, including what
  redeliveries are not deduped, and tighten the redelivery tests. ([#4274])
- **docs:** Update the agent AGENTS.md and ARCHITECTURE.md guides. ([#4817])
- **docs:** Document the Honcho memory backend with a dedicated guide and a
  long-term memory section entry in the README. ([#4822])

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
  `langgraph-checkpoint-postgres` 3.1.0 -> 3.1.1, and `nanoid` 5.1.6 -> 5.1.16.
  ([#4681], [#4683], [#4737], [#4738], [#4747], [#4748])

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
[#3174]: https://github.com/bytedance/deer-flow/pull/3174
[#3176]: https://github.com/bytedance/deer-flow/pull/3176
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
[#3826]: https://github.com/bytedance/deer-flow/pull/3826
[#3828]: https://github.com/bytedance/deer-flow/pull/3828
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
[#4095]: https://github.com/bytedance/deer-flow/issues/4095
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
[#4192]: https://github.com/bytedance/deer-flow/issues/4192
[#4193]: https://github.com/bytedance/deer-flow/pull/4193
[#4197]: https://github.com/bytedance/deer-flow/pull/4197
[#4199]: https://github.com/bytedance/deer-flow/pull/4199
[#4202]: https://github.com/bytedance/deer-flow/pull/4202
[#4203]: https://github.com/bytedance/deer-flow/pull/4203
[#4208]: https://github.com/bytedance/deer-flow/pull/4208
[#4209]: https://github.com/bytedance/deer-flow/pull/4209
[#4215]: https://github.com/bytedance/deer-flow/pull/4215
[#4217]: https://github.com/bytedance/deer-flow/pull/4217
[#4218]: https://github.com/bytedance/deer-flow/pull/4218
[#4219]: https://github.com/bytedance/deer-flow/pull/4219
[#4222]: https://github.com/bytedance/deer-flow/pull/4222
[#4225]: https://github.com/bytedance/deer-flow/pull/4225
[#4229]: https://github.com/bytedance/deer-flow/pull/4229
[#4230]: https://github.com/bytedance/deer-flow/pull/4230
[#4234]: https://github.com/bytedance/deer-flow/pull/4234
[#4235]: https://github.com/bytedance/deer-flow/pull/4235
[#4238]: https://github.com/bytedance/deer-flow/pull/4238
[#4239]: https://github.com/bytedance/deer-flow/pull/4239
[#4245]: https://github.com/bytedance/deer-flow/pull/4245
[#4246]: https://github.com/bytedance/deer-flow/pull/4246
[#4251]: https://github.com/bytedance/deer-flow/pull/4251
[#4255]: https://github.com/bytedance/deer-flow/pull/4255
[#4256]: https://github.com/bytedance/deer-flow/pull/4256
[#4260]: https://github.com/bytedance/deer-flow/pull/4260
[#4264]: https://github.com/bytedance/deer-flow/pull/4264
[#4267]: https://github.com/bytedance/deer-flow/pull/4267
[#4268]: https://github.com/bytedance/deer-flow/pull/4268
[#4277]: https://github.com/bytedance/deer-flow/pull/4277
[#4278]: https://github.com/bytedance/deer-flow/pull/4278
[#4279]: https://github.com/bytedance/deer-flow/pull/4279
[#4283]: https://github.com/bytedance/deer-flow/pull/4283
[#4287]: https://github.com/bytedance/deer-flow/pull/4287
[#4288]: https://github.com/bytedance/deer-flow/pull/4288
[#4292]: https://github.com/bytedance/deer-flow/pull/4292
[#4306]: https://github.com/bytedance/deer-flow/pull/4306
[#4309]: https://github.com/bytedance/deer-flow/pull/4309
[#4311]: https://github.com/bytedance/deer-flow/pull/4311
[#4315]: https://github.com/bytedance/deer-flow/pull/4315
[#4316]: https://github.com/bytedance/deer-flow/pull/4316
[#4324]: https://github.com/bytedance/deer-flow/issues/4324
[#4326]: https://github.com/bytedance/deer-flow/pull/4326
[#4337]: https://github.com/bytedance/deer-flow/pull/4337
[#4347]: https://github.com/bytedance/deer-flow/pull/4347
[#4348]: https://github.com/bytedance/deer-flow/pull/4348
[#4354]: https://github.com/bytedance/deer-flow/pull/4354
[#4355]: https://github.com/bytedance/deer-flow/pull/4355
[#4356]: https://github.com/bytedance/deer-flow/pull/4356
[#4358]: https://github.com/bytedance/deer-flow/pull/4358
[#4361]: https://github.com/bytedance/deer-flow/pull/4361
[#4364]: https://github.com/bytedance/deer-flow/pull/4364
[#4365]: https://github.com/bytedance/deer-flow/pull/4365
[#4370]: https://github.com/bytedance/deer-flow/pull/4370
[#4371]: https://github.com/bytedance/deer-flow/pull/4371
[#4373]: https://github.com/bytedance/deer-flow/pull/4373
[#4374]: https://github.com/bytedance/deer-flow/pull/4374
[#4376]: https://github.com/bytedance/deer-flow/pull/4376
[#4381]: https://github.com/bytedance/deer-flow/pull/4381
[#4383]: https://github.com/bytedance/deer-flow/pull/4383
[#4385]: https://github.com/bytedance/deer-flow/pull/4385
[#4391]: https://github.com/bytedance/deer-flow/pull/4391
[#4392]: https://github.com/bytedance/deer-flow/pull/4392
[#4394]: https://github.com/bytedance/deer-flow/pull/4394
[#4402]: https://github.com/bytedance/deer-flow/pull/4402
[#4403]: https://github.com/bytedance/deer-flow/pull/4403
[#4407]: https://github.com/bytedance/deer-flow/pull/4407
[#4408]: https://github.com/bytedance/deer-flow/pull/4408
[#4411]: https://github.com/bytedance/deer-flow/pull/4411
[#4414]: https://github.com/bytedance/deer-flow/issues/4414
[#4424]: https://github.com/bytedance/deer-flow/issues/4424
[#4425]: https://github.com/bytedance/deer-flow/pull/4425
[#4426]: https://github.com/bytedance/deer-flow/pull/4426
[#4430]: https://github.com/bytedance/deer-flow/pull/4430
[#4431]: https://github.com/bytedance/deer-flow/pull/4431
[#4432]: https://github.com/bytedance/deer-flow/pull/4432
[#4434]: https://github.com/bytedance/deer-flow/pull/4434
[#4437]: https://github.com/bytedance/deer-flow/pull/4437
[#4441]: https://github.com/bytedance/deer-flow/pull/4441
[#4442]: https://github.com/bytedance/deer-flow/pull/4442
[#4444]: https://github.com/bytedance/deer-flow/pull/4444
[#4446]: https://github.com/bytedance/deer-flow/pull/4446
[#4447]: https://github.com/bytedance/deer-flow/pull/4447
[#4450]: https://github.com/bytedance/deer-flow/pull/4450
[#4456]: https://github.com/bytedance/deer-flow/pull/4456
[#4459]: https://github.com/bytedance/deer-flow/pull/4459
[#4460]: https://github.com/bytedance/deer-flow/pull/4460
[#4468]: https://github.com/bytedance/deer-flow/pull/4468
[#4469]: https://github.com/bytedance/deer-flow/pull/4469
[#4471]: https://github.com/bytedance/deer-flow/pull/4471
[#4516]: https://github.com/bytedance/deer-flow/pull/4516
[#4611]: https://github.com/bytedance/deer-flow/issues/4611
[#4745]: https://github.com/bytedance/deer-flow/pull/4745
[#4574]: https://github.com/bytedance/deer-flow/issues/4574
[#4577]: https://github.com/bytedance/deer-flow/pull/4577
[#4623]: https://github.com/bytedance/deer-flow/pull/4623
[#4634]: https://github.com/bytedance/deer-flow/pull/4634
[#4638]: https://github.com/bytedance/deer-flow/pull/4638
[#4848]: https://github.com/bytedance/deer-flow/pull/4848
[#3183]: https://github.com/bytedance/deer-flow/pull/3183
[#3396]: https://github.com/bytedance/deer-flow/pull/3396
[#3442]: https://github.com/bytedance/deer-flow/pull/3442
[#3565]: https://github.com/bytedance/deer-flow/pull/3565
[#3703]: https://github.com/bytedance/deer-flow/pull/3703
[#3708]: https://github.com/bytedance/deer-flow/pull/3708
[#3783]: https://github.com/bytedance/deer-flow/pull/3783
[#3824]: https://github.com/bytedance/deer-flow/pull/3824
[#3833]: https://github.com/bytedance/deer-flow/pull/3833
[#4025]: https://github.com/bytedance/deer-flow/pull/4025
[#4200]: https://github.com/bytedance/deer-flow/pull/4200
[#4210]: https://github.com/bytedance/deer-flow/pull/4210
[#4242]: https://github.com/bytedance/deer-flow/pull/4242
[#4247]: https://github.com/bytedance/deer-flow/pull/4247
[#4250]: https://github.com/bytedance/deer-flow/pull/4250
[#4262]: https://github.com/bytedance/deer-flow/pull/4262
[#4266]: https://github.com/bytedance/deer-flow/pull/4266
[#4274]: https://github.com/bytedance/deer-flow/pull/4274
[#4275]: https://github.com/bytedance/deer-flow/pull/4275
[#4284]: https://github.com/bytedance/deer-flow/pull/4284
[#4293]: https://github.com/bytedance/deer-flow/pull/4293
[#4298]: https://github.com/bytedance/deer-flow/pull/4298
[#4301]: https://github.com/bytedance/deer-flow/pull/4301
[#4302]: https://github.com/bytedance/deer-flow/pull/4302
[#4314]: https://github.com/bytedance/deer-flow/pull/4314
[#4360]: https://github.com/bytedance/deer-flow/pull/4360
[#4377]: https://github.com/bytedance/deer-flow/pull/4377
[#4382]: https://github.com/bytedance/deer-flow/pull/4382
[#4384]: https://github.com/bytedance/deer-flow/pull/4384
[#4395]: https://github.com/bytedance/deer-flow/pull/4395
[#4405]: https://github.com/bytedance/deer-flow/pull/4405
[#4406]: https://github.com/bytedance/deer-flow/pull/4406
[#4423]: https://github.com/bytedance/deer-flow/pull/4423
[#4427]: https://github.com/bytedance/deer-flow/pull/4427
[#4429]: https://github.com/bytedance/deer-flow/pull/4429
[#4439]: https://github.com/bytedance/deer-flow/pull/4439
[#4443]: https://github.com/bytedance/deer-flow/pull/4443
[#4448]: https://github.com/bytedance/deer-flow/pull/4448
[#4453]: https://github.com/bytedance/deer-flow/pull/4453
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
[#4575]: https://github.com/bytedance/deer-flow/pull/4575
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
[#4615]: https://github.com/bytedance/deer-flow/pull/4615
[#4617]: https://github.com/bytedance/deer-flow/pull/4617
[#4618]: https://github.com/bytedance/deer-flow/pull/4618
[#4620]: https://github.com/bytedance/deer-flow/pull/4620
[#4624]: https://github.com/bytedance/deer-flow/pull/4624
[#4625]: https://github.com/bytedance/deer-flow/pull/4625
[#4627]: https://github.com/bytedance/deer-flow/pull/4627
[#4629]: https://github.com/bytedance/deer-flow/pull/4629
[#4631]: https://github.com/bytedance/deer-flow/pull/4631
[#4633]: https://github.com/bytedance/deer-flow/pull/4633
[#4635]: https://github.com/bytedance/deer-flow/pull/4635
[#4636]: https://github.com/bytedance/deer-flow/pull/4636
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
[#4701]: https://github.com/bytedance/deer-flow/pull/4701
[#4703]: https://github.com/bytedance/deer-flow/pull/4703
[#4707]: https://github.com/bytedance/deer-flow/pull/4707
[#4709]: https://github.com/bytedance/deer-flow/pull/4709
[#4713]: https://github.com/bytedance/deer-flow/pull/4713
[#4719]: https://github.com/bytedance/deer-flow/pull/4719
[#4722]: https://github.com/bytedance/deer-flow/pull/4722
[#4724]: https://github.com/bytedance/deer-flow/pull/4724
[#4727]: https://github.com/bytedance/deer-flow/pull/4727
[#4730]: https://github.com/bytedance/deer-flow/pull/4730
[#4735]: https://github.com/bytedance/deer-flow/pull/4735
[#4736]: https://github.com/bytedance/deer-flow/pull/4736
[#4737]: https://github.com/bytedance/deer-flow/pull/4737
[#4738]: https://github.com/bytedance/deer-flow/pull/4738
[#4744]: https://github.com/bytedance/deer-flow/pull/4744
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
[#4812]: https://github.com/bytedance/deer-flow/pull/4812
[#4815]: https://github.com/bytedance/deer-flow/pull/4815
[#4816]: https://github.com/bytedance/deer-flow/pull/4816
[#4817]: https://github.com/bytedance/deer-flow/pull/4817
[#4822]: https://github.com/bytedance/deer-flow/pull/4822
[#4823]: https://github.com/bytedance/deer-flow/pull/4823
[#4825]: https://github.com/bytedance/deer-flow/pull/4825
[#4827]: https://github.com/bytedance/deer-flow/pull/4827
[#4830]: https://github.com/bytedance/deer-flow/pull/4830
[#4833]: https://github.com/bytedance/deer-flow/pull/4833
[#4836]: https://github.com/bytedance/deer-flow/pull/4836
[#4838]: https://github.com/bytedance/deer-flow/pull/4838
[#4840]: https://github.com/bytedance/deer-flow/pull/4840
[#4842]: https://github.com/bytedance/deer-flow/pull/4842
[#4844]: https://github.com/bytedance/deer-flow/pull/4844
[#4846]: https://github.com/bytedance/deer-flow/pull/4846
[#4852]: https://github.com/bytedance/deer-flow/pull/4852
[#4853]: https://github.com/bytedance/deer-flow/pull/4853
[#4860]: https://github.com/bytedance/deer-flow/pull/4860
[#4861]: https://github.com/bytedance/deer-flow/pull/4861
[#4863]: https://github.com/bytedance/deer-flow/pull/4863
[#4865]: https://github.com/bytedance/deer-flow/pull/4865
[#4868]: https://github.com/bytedance/deer-flow/pull/4868
[#4877]: https://github.com/bytedance/deer-flow/pull/4877
[#4882]: https://github.com/bytedance/deer-flow/pull/4882
[#4887]: https://github.com/bytedance/deer-flow/pull/4887
[#4888]: https://github.com/bytedance/deer-flow/pull/4888
[#4898]: https://github.com/bytedance/deer-flow/pull/4898
[#4903]: https://github.com/bytedance/deer-flow/pull/4903
[#4911]: https://github.com/bytedance/deer-flow/pull/4911
[#4918]: https://github.com/bytedance/deer-flow/pull/4918
[#4928]: https://github.com/bytedance/deer-flow/pull/4928
[#4933]: https://github.com/bytedance/deer-flow/pull/4933
[#4936]: https://github.com/bytedance/deer-flow/pull/4936
[#4938]: https://github.com/bytedance/deer-flow/pull/4938
[#4951]: https://github.com/bytedance/deer-flow/pull/4951
[#4953]: https://github.com/bytedance/deer-flow/pull/4953
[#4956]: https://github.com/bytedance/deer-flow/pull/4956
[#4959]: https://github.com/bytedance/deer-flow/pull/4959
[#4960]: https://github.com/bytedance/deer-flow/pull/4960
[#4963]: https://github.com/bytedance/deer-flow/pull/4963
[#4965]: https://github.com/bytedance/deer-flow/pull/4965
[#4970]: https://github.com/bytedance/deer-flow/pull/4970
[#4983]: https://github.com/bytedance/deer-flow/pull/4983
[#4987]: https://github.com/bytedance/deer-flow/pull/4987
[#4998]: https://github.com/bytedance/deer-flow/pull/4998

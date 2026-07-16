# Changelog

All notable changes to DeerFlow are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### ⚠ Breaking changes

- **skills:** A directory containing `SKILL.md` is now a runtime package
  boundary. Nested `SKILL.md` files inside that package are supporting data and
  are no longer registered as independent skills; unusual custom layouts must
  move independently loadable skills under a namespace directory without its
  own `SKILL.md`. ([#4098])
- **memory:** The memory system is now pluggable (`memory.manager_class` selects
  a backend; default `deermem` is self-contained). DeerMem-private settings moved
  from the top level of `memory:` into `memory.backend_config`, and the
  `/memory/config` response (and `client.get_memory_config()`) changed shape.
- **memory:** `/memory/config` and `client.get_memory_config()` no longer return
  flat DeerMem fields (`storage_path`, `max_facts`, `debounce_seconds`,
  `token_counting`, `guaranteed_*`, `staleness_*`, ...). They return
  `{enabled, mode, injection_enabled, manager_class, backend_config}` where
  `backend_config` is an opaque dict the active backend self-interprets. Memory
  *data* responses (`/memory`, `/memory/status` data) are unchanged. External
  API/SDK clients reading the old flat fields must read `backend_config` instead.
- **memory:** Custom `memory.storage_class` moved: the old default path
  `deerflow.agents.memory.storage.FileMemoryStorage` no longer exists (now
  `deerflow.agents.memory.backends.deermem.deermem.core.storage.FileMemoryStorage`).
  Custom `MemoryStorage` subclasses must accept `config` in `__init__` (was
  no-arg). A broken/old `storage_class` logs an error and falls back to
  `FileMemoryStorage` (won't crash) -- update the path + signature to restore it.
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
  custom root.

### Changed

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
  `config.yaml` to silence the warning.
- **memory:** Added `memory.mode` (`middleware` | `tool`); `tool` mode registers
  memory tools (`memory_search`/`add`/`update`/`delete`) the model calls directly
  instead of passive per-turn summarization. `manager_class` resolution is now
  fail-fast (raises `ValueError` on an unknown backend instead of silently
  falling back).

### Fixed

- **skills:** Apply `allowed-tools` only to slash-activated or actually loaded
  lead-agent skills, preventing passive enabled skills and evaluation fixtures
  from removing `task`, web, and file tools from every run. ([#4095], [#4098])
- **models:** Honor `api_base` on every `BaseChatOpenAI` subclass (`VllmChatModel`,
  `MindIEChatModel`, `PatchedChatMiMo`, `PatchedChatStepFun`, `PatchedChatMiniMax`),
  not just `ChatOpenAI` / `PatchedChatOpenAI`. Those five previously dropped the
  configured endpoint silently and then failed every request with an opaque
  `unexpected keyword argument 'api_base'`; the unknown-config-key warning was
  disabled for them as well. Both now gate on `issubclass(BaseChatOpenAI)`. ([#4146])

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
[#3393]: https://github.com/bytedance/deer-flow/pull/3393
[#3397]: https://github.com/bytedance/deer-flow/pull/3397
[#3398]: https://github.com/bytedance/deer-flow/pull/3398
[#3408]: https://github.com/bytedance/deer-flow/pull/3408
[#3410]: https://github.com/bytedance/deer-flow/pull/3410
[#3411]: https://github.com/bytedance/deer-flow/pull/3411
[#3413]: https://github.com/bytedance/deer-flow/pull/3413
[#3417]: https://github.com/bytedance/deer-flow/pull/3417
[#3421]: https://github.com/bytedance/deer-flow/pull/3421
[#3423]: https://github.com/bytedance/deer-flow/pull/3423
[#3425]: https://github.com/bytedance/deer-flow/pull/3425
[#3426]: https://github.com/bytedance/deer-flow/pull/3426
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
[#3553]: https://github.com/bytedance/deer-flow/pull/3553
[#3554]: https://github.com/bytedance/deer-flow/pull/3554
[#3559]: https://github.com/bytedance/deer-flow/pull/3559
[#3561]: https://github.com/bytedance/deer-flow/pull/3561
[#3569]: https://github.com/bytedance/deer-flow/pull/3569
[#3570]: https://github.com/bytedance/deer-flow/pull/3570
[#3575]: https://github.com/bytedance/deer-flow/pull/3575
[#3577]: https://github.com/bytedance/deer-flow/pull/3577
[#3578]: https://github.com/bytedance/deer-flow/pull/3578
[#3579]: https://github.com/bytedance/deer-flow/pull/3579
[#3580]: https://github.com/bytedance/deer-flow/pull/3580
[#3581]: https://github.com/bytedance/deer-flow/pull/3581
[#3582]: https://github.com/bytedance/deer-flow/pull/3582
[#3583]: https://github.com/bytedance/deer-flow/pull/3583
[#3584]: https://github.com/bytedance/deer-flow/pull/3584
[#3591]: https://github.com/bytedance/deer-flow/pull/3591
[#3599]: https://github.com/bytedance/deer-flow/pull/3599
[#3600]: https://github.com/bytedance/deer-flow/pull/3600
[#3602]: https://github.com/bytedance/deer-flow/pull/3602
[#3605]: https://github.com/bytedance/deer-flow/pull/3605
[#3606]: https://github.com/bytedance/deer-flow/pull/3606
[#3608]: https://github.com/bytedance/deer-flow/pull/3608
[#3610]: https://github.com/bytedance/deer-flow/pull/3610
[#3611]: https://github.com/bytedance/deer-flow/pull/3611
[#3623]: https://github.com/bytedance/deer-flow/pull/3623
[#3624]: https://github.com/bytedance/deer-flow/pull/3624
[#3629]: https://github.com/bytedance/deer-flow/pull/3629
[#3631]: https://github.com/bytedance/deer-flow/pull/3631
[#3646]: https://github.com/bytedance/deer-flow/pull/3646
[#3649]: https://github.com/bytedance/deer-flow/pull/3649
[#3654]: https://github.com/bytedance/deer-flow/pull/3654
[#3657]: https://github.com/bytedance/deer-flow/pull/3657
[#3658]: https://github.com/bytedance/deer-flow/pull/3658
[#4095]: https://github.com/bytedance/deer-flow/issues/4095
[#4098]: https://github.com/bytedance/deer-flow/pull/4098
[#4146]: https://github.com/bytedance/deer-flow/pull/4146

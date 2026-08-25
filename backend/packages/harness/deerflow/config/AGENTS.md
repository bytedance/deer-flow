### Configuration System

**Main Configuration** (`config.yaml`):

Setup: Copy `config.example.yaml` to `config.yaml` in the **project root** directory.

**Config Versioning**: `config.example.yaml` has a `config_version` field. On startup, `AppConfig.from_file()` compares user version vs example version and emits a warning if outdated. Missing `config_version` = version 0. Run `make config-upgrade` to auto-merge missing fields. When changing the config schema, bump `config_version` in `config.example.yaml`.

**Config Caching**: `get_app_config()` caches the parsed config, but automatically reloads it when the resolved config path or file content signature changes. The signature includes file metadata and a content digest, so Gateway and LangGraph reads stay aligned with `config.yaml` edits even on object-store or network mounts where mtime can remain stale.

**Config Hot-Reload Boundary**: Gateway dependencies route through `get_app_config()` on every request, so per-run fields like `models[*].max_tokens`, `summarization.*`, `title.*`, `memory.*`, `subagents.*`, `verification.*`, `tools[*]`, and the agent system prompt pick up `config.yaml` edits on the next message. `AppConfig` is intentionally **not** cached on `app.state` — `lifespan()` keeps a local `startup_config` variable for one-shot bootstrap work and passes it to `langgraph_runtime(app, startup_config)`.

Infrastructure fields are **restart-required**. The authoritative list lives in `packages/harness/deerflow/config/reload_boundary.py::STARTUP_ONLY_FIELDS` and is mirrored by the standardised `"startup-only:"` prefix on the corresponding `Field(description=...)` in `AppConfig`, so IDE hover on those fields surfaces the reason inline (no need to context-switch into this table). Currently registered: `plugins`, `database`, `checkpointer`, `run_events`, `stream_bridge`, `sandbox`, `log_level`, `logging`, `channels`, `channel_connections`, `scheduler`, `mcp_tasks`, `subagent_runtime`, `subagent_batches`, `run_ownership`. Adding a new restart-required field requires updating the registry; drift is pinned by `tests/test_reload_boundary.py`. `scheduler.recursion_limit` is the exception inside that section: it is read from `get_app_config()` at each scheduled dispatch, so a YAML edit applies to the next run without restarting the poller.

**Persistence backend resolution**: the unified `database` section selects the
Gateway's LangGraph checkpointer, LangGraph Store, and DeerFlow SQL repositories.
The deprecated `checkpointer` section remains backward compatible and, when
present, overrides `database` for the LangGraph checkpointer and Store only;
application repositories continue to use `database`.

Configuration priority:
1. Explicit `config_path` argument
2. `DEER_FLOW_CONFIG_PATH` environment variable
3. `config.yaml` in current directory (backend/)
4. `config.yaml` in parent directory (project root - **recommended location**)

Config values starting with `$` are resolved as environment variables (e.g., `$OPENAI_API_KEY`).
`ModelConfig` also declares `use_responses_api` and `output_version` so OpenAI `/v1/responses` can be enabled explicitly while still using `langchain_openai:ChatOpenAI`.

**Extensions Configuration** (`extensions_config.json`):

MCP servers and skills are configured together in `extensions_config.json` in project root:

Docker development mounts the project directory at `/app/project` and points
`DEER_FLOW_CONFIG_PATH` / `DEER_FLOW_EXTENSIONS_CONFIG_PATH` into that directory.
Keep mutable config files behind a directory bind mount: single-file bind mounts
can become stale or inaccessible when a host editor replaces a file on save.

Configuration priority:
1. Explicit `config_path` argument
2. `DEER_FLOW_EXTENSIONS_CONFIG_PATH` environment variable
3. `extensions_config.json` in current directory (backend/)
4. `extensions_config.json` in parent directory (project root - **recommended location**)

Extensions are optional only in the fallback *search* mode (priority 3-4 above): `ExtensionsConfig.resolve_config_path()` returns `None` when neither an explicit `config_path` nor `DEER_FLOW_EXTENSIONS_CONFIG_PATH` is given and the search locations find nothing. An explicit `config_path` argument or a set `DEER_FLOW_EXTENSIONS_CONFIG_PATH` (priority 1-2) is an operator assertion that one particular file must be used, so a missing file in either of those modes raises `FileNotFoundError` instead — including when the file existed earlier and has since been deleted. The MCP tools cache's staleness check (`deerflow.mcp.cache._resolve_config_path`) is a narrow, deliberate exception to that rule: it catches that `FileNotFoundError` locally and treats it as "unconfigured" so a previously-valid config disappearing mid-run degrades the cache to serving its last-known-good tools instead of raising out of a per-request hot path (see the MCP System section below).

### Config Schema

**`config.yaml`** key sections:
- `models[]` - LLM configs with `use` class path, `supports_thinking`, `supports_vision`, provider-specific fields
- `logging.enhance` - Optional request trace correlation (`enabled`, `format`) for Gateway `X-Trace-Id`, log `trace_id`, and Langfuse `deerflow_trace_id`
- vLLM reasoning models should use `deerflow.models.vllm_provider:VllmChatModel`; for Qwen-style parsers prefer `when_thinking_enabled.extra_body.chat_template_kwargs.enable_thinking`, and DeerFlow will also normalize the older `thinking` alias
- `tools[]` - Tool configs with `use` variable path and `group`
- `tool_groups[]` - Logical groupings for tools
- `sandbox.use` - Sandbox provider class path
- `skills.path` / `skills.container_path` - Host and container paths to skills directory
- `skills.deferred_discovery` - When `true`, replaces the full-metadata `<available_skills>` prompt block with a compact `<skill_index>` (names only) and registers the `describe_skill` tool so the agent fetches metadata on demand. Defaults to `false` (legacy full-metadata injection)
- `title` - Auto-title generation (enabled, max_words, max_chars, model_name; null model_name uses fast local fallback, explicit model_name uses the prompt_template LLM path)
- `summarization` - Context summarization (enabled, trigger conditions, keep policy)
- `subagents.enabled` - Master switch for subagent delegation
- `subagent_runtime` - Startup-only shared process admission (`max_running`, bounded async wait queue, queue/reject policy, and queue timeout) for ordinary and durable-batch native subagents
- `subagent_batches` - Startup-only explicit durable batch scheduler limits (disabled by default), including separate total, live, and running dimensions plus leases/retries/result bounds
- `memory` - Memory system (enabled, storage_path, debounce_seconds, shutdown_flush_timeout_seconds, model_name, max_facts, fact_confidence_threshold, injection_enabled, max_injection_tokens, staleness_review_enabled, staleness_age_days, staleness_min_candidates, staleness_max_removals_per_cycle, staleness_protected_categories, staleness_max_lifetime_multiplier, staleness_max_extension_days)

**`extensions_config.json`**:
- `mcpServers` - Map of server name → config (enabled, type, command, args, env, url, headers, oauth, description, `routing`, `tools`, `tool_call_timeout`, `session_init_timeout`). `routing.mode="prefer"` emits `<mcp_routing_hints>` prompt guidance; if `tool_search` defers the hinted tool, `McpRoutingMiddleware` can also auto-promote matching deferred schemas before the model call. It does not hard-disable other tools. `session_init_timeout` (default `DEFAULT_MCP_SESSION_INIT_TIMEOUT` = 60s, `null` to disable) bounds server bring-up: tool discovery and persistent stdio session initialization, so a hung server cannot block agent construction indefinitely; durable HTTP/SSE task calls use it for their ephemeral session initialization too. `tool_call_timeout` bounds individual stdio calls and durable-task calls on every transport; other HTTP/SSE tools use transport-level timeouts.
- `tool_search.auto_promote_top_k` - Global MCP routing auto-promote breadth. Default `3`, clamped to `1..5`; applies only when `tool_search.enabled=true` and only to deferred MCP tools with `routing.mode="prefer"` and non-empty keywords. For lead agents the deferred catalog is built from the full configured MCP set; auto-promotion never grants authority because an active skill's runtime policy still filters model-visible schemas, `tool_search` results, and execution.
- `skills` - Map of skill name → state (enabled)
- `middlewares` - Zero-argument `AgentMiddleware` class paths for lead and subagent runtime extension. `config.yaml -> extensions` can override these fields after validation; overrides are replace-per-field, not list concatenation.

Gateway API endpoints and `DeerFlowClient` methods can modify MCP servers and skill state at runtime; their `extensions_config.json` writes use the shared atomic replacement helper, while `middlewares` remains an operator-controlled config-file extension point.

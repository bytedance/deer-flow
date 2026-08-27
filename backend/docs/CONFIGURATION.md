# Configuration Guide

This guide explains how to configure DeerFlow for your environment.

## Config Versioning

`config.example.yaml` contains a `config_version` field that tracks schema changes. When the example version is higher than your local `config.yaml`, the application emits a startup warning:

```
WARNING - Your config.yaml (version 0) is outdated — the latest version is 1.
Run `make config-upgrade` to merge new fields into your config.
```

- **Missing `config_version`** in your config is treated as version 0.
- Run `make config-upgrade` to auto-merge missing fields (your existing values are preserved, a `.bak` backup is created).
- When changing the config schema, bump `config_version` in `config.example.yaml`.

## Configuration Sections

### Extensions

MCP servers and skill enabled states live in `extensions_config.json`, separate
from `config.yaml`. Use `mcpServers.<server>.routing` to add soft MCP tool
preference hints for requests that should prefer a specific MCP server or tool.
See [MCP Server Configuration](MCP_SERVER.md#routing-hints) for the schema,
example, and soft-vs-hard routing boundary.

### Models

Configure the LLM models available to the agent:

```yaml
models:
  - name: gpt-4                    # Internal identifier
    display_name: GPT-4            # Human-readable name
    use: langchain_openai:ChatOpenAI  # LangChain class path
    model: gpt-4                   # Model identifier for API
    api_key: $OPENAI_API_KEY       # API key (use env var)
    max_tokens: 4096               # Max tokens per request
    temperature: 0.7               # Sampling temperature
```

**Supported Providers**:
- OpenAI (`langchain_openai:ChatOpenAI`)
- Anthropic (`langchain_anthropic:ChatAnthropic`)
- DeepSeek (`langchain_deepseek:ChatDeepSeek`)
- Xiaomi MiMo (`deerflow.models.patched_mimo:PatchedChatMiMo`)
- Claude Code OAuth (`deerflow.models.claude_provider:ClaudeChatModel`)
- Codex CLI (`deerflow.models.openai_codex_provider:CodexChatModel`)
- Any LangChain-compatible provider

CLI-backed provider examples:

```yaml
models:
  - name: gpt-5.4
    display_name: GPT-5.4 (Codex CLI)
    use: deerflow.models.openai_codex_provider:CodexChatModel
    model: gpt-5.4
    supports_thinking: true
    supports_reasoning_effort: true

  - name: claude-sonnet-4.6
    display_name: Claude Sonnet 4.6 (Claude Code OAuth)
    use: deerflow.models.claude_provider:ClaudeChatModel
    model: claude-sonnet-4-6
    max_tokens: 4096
    supports_thinking: true
```

**Auth behavior for CLI-backed providers**:
- `CodexChatModel` loads Codex CLI auth from `~/.codex/auth.json`
- The Codex Responses endpoint currently rejects `max_tokens` and `max_output_tokens`, so `CodexChatModel` does not expose a request-level token cap
- `ClaudeChatModel` accepts `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`, `CLAUDE_CODE_CREDENTIALS_PATH`, or plaintext `~/.claude/.credentials.json`
- On macOS, DeerFlow does not probe Keychain automatically. Use `scripts/export_claude_code_oauth.py` to export Claude Code auth explicitly when needed

To use OpenAI's `/v1/responses` endpoint with LangChain, keep using `langchain_openai:ChatOpenAI` and set:

```yaml
models:
  - name: gpt-5-responses
    display_name: GPT-5 (Responses API)
    use: langchain_openai:ChatOpenAI
    model: gpt-5
    api_key: $OPENAI_API_KEY
    use_responses_api: true
    output_version: responses/v1
```

For OpenAI-compatible gateways (for example Novita or OpenRouter), keep using `langchain_openai:ChatOpenAI` and set `base_url`:

> **Note:** for `langchain_openai:ChatOpenAI` the endpoint override key is `base_url` (not `api_base`). If you write `api_base` it is automatically normalized to `base_url`, and unrecognized keys are logged with a warning at model-build time. Some other model classes (e.g. `PatchedChatDeepSeek`) do use `api_base` — match the key to the class you configured.

```yaml
models:
  - name: novita-deepseek-v3.2
    display_name: Novita DeepSeek V3.2
    use: langchain_openai:ChatOpenAI
    model: deepseek/deepseek-v3.2
    api_key: $NOVITA_API_KEY
    base_url: https://api.novita.ai/openai
    supports_thinking: true
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled

  - name: minimax-m3
    display_name: MiniMax M3
    use: langchain_openai:ChatOpenAI
    model: MiniMax-M3
    api_key: $MINIMAX_API_KEY
    base_url: https://api.minimax.io/v1
    max_tokens: 4096
    temperature: 1.0  # MiniMax requires temperature in (0.0, 1.0]
    supports_vision: true

  - name: minimax-m2.7
    display_name: MiniMax M2.7
    use: langchain_openai:ChatOpenAI
    model: MiniMax-M2.7
    api_key: $MINIMAX_API_KEY
    base_url: https://api.minimax.io/v1
    max_tokens: 4096
    temperature: 1.0  # MiniMax requires temperature in (0.0, 1.0]
    supports_vision: false  # M2.7 is text-only; M3 supports vision

  - name: minimax-m2.7-highspeed
    display_name: MiniMax M2.7 Highspeed
    use: langchain_openai:ChatOpenAI
    model: MiniMax-M2.7-highspeed
    api_key: $MINIMAX_API_KEY
    base_url: https://api.minimax.io/v1
    max_tokens: 4096
    temperature: 1.0  # MiniMax requires temperature in (0.0, 1.0]
    supports_vision: false  # M2.7 is text-only; M3 supports vision
  - name: openrouter-gemini-2.5-flash
    display_name: Gemini 2.5 Flash (OpenRouter)
    use: langchain_openai:ChatOpenAI
    model: google/gemini-2.5-flash-preview
    api_key: $OPENAI_API_KEY
    base_url: https://openrouter.ai/api/v1
```

If your OpenRouter key lives in a different environment variable name, point `api_key` at that variable explicitly (for example `api_key: $OPENROUTER_API_KEY`).

**Thinking Models**:
Some models support "thinking" mode for complex reasoning:

```yaml
models:
  - name: deepseek-v3
    supports_thinking: true
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled
```

**Gemini with thinking via OpenAI-compatible gateway**:

When routing Gemini through an OpenAI-compatible proxy (Vertex AI OpenAI compat endpoint, AI Studio, or third-party gateways) with thinking enabled, the API attaches a `thought_signature` to each tool-call object returned in the response.  Every subsequent request that replays those assistant messages **must** echo those signatures back on the tool-call entries or the API returns:

```
HTTP 400 INVALID_ARGUMENT: function call `<tool>` in the N. content block is
missing a `thought_signature`.
```

Standard `langchain_openai:ChatOpenAI` silently drops `thought_signature` when serialising messages.  Use `deerflow.models.patched_openai:PatchedChatOpenAI` instead — it re-injects the tool-call signatures (sourced from `AIMessage.additional_kwargs["tool_calls"]`) into every outgoing payload:

```yaml
models:
  - name: gemini-2.5-pro-thinking
    display_name: Gemini 2.5 Pro (Thinking)
    use: deerflow.models.patched_openai:PatchedChatOpenAI
    model: google/gemini-2.5-pro-preview   # model name as expected by your gateway
    api_key: $GEMINI_API_KEY
    base_url: https://<your-openai-compat-gateway>/v1
    max_tokens: 16384
    supports_thinking: true
    supports_vision: true
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled
```

For Gemini accessed **without** thinking (e.g. via OpenRouter where thinking is not activated), the plain `langchain_openai:ChatOpenAI` with `supports_thinking: false` is sufficient and no patch is needed.

**MiMo with thinking via OpenAI-compatible API**:

MiMo returns `reasoning_content` on assistant messages in thinking mode. In multi-turn agent conversations with tool calls, subsequent requests must preserve that historical `reasoning_content` on assistant messages or the MiMo API can return HTTP 400. Standard `langchain_openai:ChatOpenAI` drops this provider-specific field, so use `deerflow.models.patched_mimo:PatchedChatMiMo`:

For pay-as-you-go API keys (`sk-...`), use `https://api.xiaomimimo.com/v1`. For Token Plan keys (`tp-...`), use the regional Token Plan Base URL shown in the MiMo console, such as `https://token-plan-cn.xiaomimimo.com/v1`. MiMo documents these key types as separate and non-interchangeable.

`PatchedChatMiMo` is model-id agnostic. Use it for every MiMo thinking model entry you configure, including model entries referenced by `subagents.*.model` overrides (for example `mimo-v2.5-pro`, `mimo-v2.5`, `mimo-v2-pro`, `mimo-v2-omni`, or `mimo-v2-flash`).

```yaml
models:
  - name: mimo-v2.5-pro
    display_name: MiMo V2.5 Pro
    use: deerflow.models.patched_mimo:PatchedChatMiMo
    model: mimo-v2.5-pro
    api_key: $MIMO_API_KEY
    base_url: https://api.xiaomimimo.com/v1
    max_tokens: 8192
    supports_thinking: true
    supports_vision: false
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled
    when_thinking_disabled:
      extra_body:
        thinking:
          type: disabled
```

`PatchedChatMiMo` preserves MiMo's `choices[].message.reasoning_content`, streaming `delta.reasoning_content`, and request-history assistant `reasoning_content` fields. It does not reuse the DeepSeek provider.

### RAGFlow Knowledge Retrieval

RAGFlow integration is disabled by default. It adds one read-only Agent tool,
`knowledge_search`. DeerFlow does not persist a copy of dataset or document
metadata; RAGFlow is the sole source of truth. The configured API key is
tenant-scoped. An optional operator-controlled `datasets` list restricts every
Agent on this deployment to the same dataset-ID allowlist; omitting it searches
all datasets visible to that tenant API key. An explicitly empty `datasets: []`
is rejected rather than being treated as tenant-wide access.

```yaml
tool_groups:
  - name: knowledge

tools:
  - name: knowledge_search
    group: knowledge
    use: deerflow.community.ragflow.tools:knowledge_search_tool
    base_url: http://localhost:9380
    api_key: $RAGFLOW_API_KEY
    datasets:
      - 0123456789abcdef0123456789abcdef
      - fedcba9876543210fedcba9876543210
    timeout: 30
    page_size: 8
    similarity_threshold: 0.2
    vector_similarity_weight: 0.3
    top_k: 256
    max_chars_per_chunk: 800
    max_total_chars: 8000
```

The tool is opt-in through the normal `tools:` list. `datasets` is optional but,
when present, must contain at least one ID. If
it contains RAGFlow dataset IDs selected by the deployment operator, DeerFlow
does not validate their existence while loading configuration; on each search
it verifies them with ID-filtered requests. If `datasets` is omitted, each
search paginates through the tenant-visible dataset catalog. Both paths resolve
current names, embedding models, and chunk counts. Empty datasets are ignored;
an empty dataset that has no embedding-model metadata is also skipped with a
server warning. The remaining datasets are grouped by the exact embedding-model
identifier and each group is sent to RAGFlow with a non-empty `dataset_ids`
list. At most four groups are retrieved concurrently. Because raw similarity
scores from different embedding spaces are not globally comparable, DeerFlow
preserves each group's RAGFlow ranking, interleaves equal rank positions, omits
score labels when more than one group is searched, and applies `page_size` as a
single global chunk limit. If any searchable group fails, the whole tool call
fails rather than silently omitting part of the configured scope. A deleted or
inaccessible configured dataset identifies its ordinal entry in
`knowledge_search.datasets` and produces guidance to check `config.yaml`.
Dataset IDs and catalog listing are not exposed to the Agent.

Use an allowlist to narrow the tenant-wide scope; compatible embedding models
are no longer required across selected datasets. `base_url` must not contain
embedded username or password information. For Docker or Kubernetes, it must be
reachable from the Gateway container or Pod; `localhost` refers to that
container or Pod, not the host machine.

This integration is retrieval-only. Dataset creation, uploads, parsing, and
deletion remain in RAGFlow and are not exposed as Agent tools or DeerFlow APIs.

### Tool Groups

Organize tools into logical groups:

```yaml
tool_groups:
  - name: web          # Web browsing and search
  - name: file:read    # Read-only file operations
  - name: file:write   # Write file operations
  - name: bash         # Shell command execution
```

### Scheduler

The scheduled-task MVP adds a scheduler section to `config.yaml`:

```yaml
scheduler:
  enabled: false
  multi_instance: false
  poll_interval_seconds: 5
  lease_seconds: 120
  max_concurrent_runs: 3
  queue_timeout_seconds: 3600
  min_once_delay_seconds: 60
  recursion_limit: 1000
```

Notes:

- `enabled: false` keeps background polling off by default.
- `multi_instance: true` opts into lease-aware scheduler recovery across Gateway instances. It requires Postgres, `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`; otherwise startup fails fast. Leave it false for the default single-instance scheduler.
- `max_concurrent_runs` is a shared global execution cap in multi-instance mode. Waiting `queued` rows do not consume capacity; an atomic `queued` → `launching` claim counts `launching`/`running` rows under a Postgres advisory lock so concurrent Pods cannot exceed the cap.
- `queue_timeout_seconds` limits how long a persisted occurrence may wait for capacity or a reused thread to become available. Expired occurrences are marked `failed`; queued rows otherwise survive Gateway restarts.
- A task definition is immutable while an occurrence is `queued`, `launching`, or `running`. This prevents a durable occurrence from mixing its admitted thread with a later prompt or schedule edit. Transitioning a task to paused or deleting it cancels a waiting row; PATCH and resume return a conflict until the active occurrence finishes or is cancelled.
- A manual trigger remains explicit even while the recurring schedule is paused: it may wait in the durable queue and run later, while the task itself stays paused. Transitioning an enabled task to paused still cancels its waiting occurrence atomically.
- Queue admission, PATCH/resume, pause, and delete serialize on the parent task row. Per-thread FIFO spans all active states, so an older `launching` or `running` occurrence blocks a newer queued occurrence on the same reused thread as well as an older `queued` occurrence.
- Multi-instance reconciliation uses the run ownership lease: a live peer run is preserved, an expired lease is atomically taken over before its scheduled row is interrupted, and a stale Pod cannot overwrite a newer Pod's parent-task bookkeeping.
- `recursion_limit` is the LangGraph super-step cap for scheduler-launched runs (default 1000, matching the web UI's interactive budget). Values above `max_recursion_limit` (default 1000) are clamped. This field is read at dispatch, so a YAML edit applies to the next scheduled run without a Gateway restart.
- Poller fields (`enabled`, `multi_instance`, `poll_interval_seconds`, `lease_seconds`, `max_concurrent_runs`, `queue_timeout_seconds`, `min_once_delay_seconds`) are restart-required; edits need a Gateway restart.
- **Upgrade note:** before upgrading a deployment with `GATEWAY_WORKERS > 1` and `scheduler.enabled: true`, either run the scheduler on exactly one Gateway worker or enable `scheduler.multi_instance: true` with shared Postgres, `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`. The startup gate now rejects the unsafe combination instead of allowing it to start silently.
- **Upgrade note:** in multi-instance mode, `max_concurrent_runs` is cluster-wide rather than per Pod and counts `launching`/`running` occurrences. Waiting `queued` rows remain outside the execution cap; capacity does not multiply with the replica count.
- **Upgrade note:** `scheduler.multi_instance` and its related scheduler, ownership, and run-event settings are startup-only. Restart all Gateway Pods together after changing them; a ConfigMap update without a coordinated restart leaves the running service on its previous mode.
- Multi-worker deployments (`GATEWAY_WORKERS > 1`) must use the Postgres database backend, enable run ownership heartbeats, and set `run_events.backend: db`. SQLite silently ignores row-level locks, while memory and JSONL run-event stores are process-local and cannot enforce singleton delivery receipts across workers; startup rejects these combinations. The process-local agentic browser tool group is incompatible with multiple Gateway workers; keep `GATEWAY_WORKERS=1` while `browser_navigate` is enabled. Browser control also requires the backend `browser` extra (`cd backend && uv sync --extra browser && uv run playwright install chromium`); startup detects enabled browser config and fails fast when Playwright is missing, and `/api/features` reports `browser_control.enabled=false` until the runtime is available.
- The MVP supports thread reuse and fresh-thread-per-run execution modes.
- The MVP supports only `once` and `cron`.
- Manual trigger uses the same scheduled-task resource and run lifecycle.
- Scheduled task definitions and task-run history are persisted in the application database.

### Agent Storage

Custom agent **definitions** (`config.yaml` + `SOUL.md`) are stored per-user on
local disk by default. This is separate from the `database` backend (which holds
run/thread/event data) and from agent memory.

```yaml
agent_storage:
  backend: file   # file (default) | db
```

- `backend: file` — the historical layout under `{base_dir}/users/{user_id}/agents/`. Single-node by construction: an agent created on one node is not visible to other nodes without a shared mount.
- `backend: db` — one row per agent in the shared SQL persistence layer (a new `agents` table), so every node in a multi-instance deployment sees the same agents. Requires `database.backend` to be `sqlite` or `postgres`; the Gateway **fails fast at startup** if it is `memory` (a per-process database cannot share definitions).
- `agent_storage` is restart-required (the backend is captured at Gateway lifespan startup).
- In a multi-worker Postgres deployment (`GATEWAY_WORKERS > 1`), leaving `agent_storage.backend: file` logs a startup warning — agents written to one node's local disk are invisible to the others, which is exactly the divergence the `db` backend fixes.

Migrating an existing install from `file` to `db`:

```bash
python backend/scripts/migrate_agents_to_db.py            # copy on-disk agents into the db
python backend/scripts/migrate_agents_to_db.py --dry-run  # preview without writing
```

The importer is idempotent (already-present agents are skipped) and leaves the source files untouched, so reverting `agent_storage.backend` to `file` is a clean rollback. Agent *memory* (`memory.json`) is unaffected by this switch.

### Tools

Configure specific tools available to the agent:

```yaml
tools:
  - name: web_search
    group: web
    use: deerflow.community.tavily.tools:web_search_tool
    max_results: 5
    # api_key: $TAVILY_API_KEY  # Optional
```

**Built-in Tools**:
- `web_search` - Search the web (DuckDuckGo, Tavily, Brave, Exa, InfoQuest, Tencent Cloud WSA, Firecrawl, fastCRW, GroundRoute)
- `web_fetch` - Fetch web pages (Jina AI, Crawl4AI, Exa, InfoQuest, Firecrawl, fastCRW, GroundRoute, Browserless)
- `web_capture` - Capture rendered webpage screenshots as artifacts (Browserless)
- `image_search` - Search for reference images (DuckDuckGo, InfoQuest, Serper, Brave)
- `ls` - List directory contents
- `read_file` - Read file contents
- `write_file` - Write file contents
- `str_replace` - String replacement in files
- `bash` - Execute bash commands

Browserless can be configured as an opt-in visual capture tool:

```yaml
tools:
  - name: web_capture
    group: web
    use: deerflow.community.browserless.tools:web_capture_tool
    base_url: http://localhost:3032
    # token: $BROWSERLESS_TOKEN
    output_format: png
    full_page: true
    viewport_width: 1280
    viewport_height: 720
    # allow_private_addresses: false  # SSRF guard; keep false in production
```

`web_capture` writes screenshots to the current thread's `/mnt/user-data/outputs`
directory and presents the image path through the standard artifact mechanism. By
default it refuses URLs that resolve to private, loopback, link-local, or
cloud-metadata addresses; set `allow_private_addresses: true` only when you
intentionally point the tool at an internal target.

Both `web_fetch` (Browserless provider) and `web_capture` need a running
Browserless instance. You can point `base_url` at [Browserless Cloud](https://www.browserless.io/)
(set `BROWSERLESS_TOKEN`) or run one locally with Docker:

```bash
# Browserless listens on port 3000 inside the container; map it to 3032 to
# match the default base_url (http://localhost:3032). Recent Browserless
# images always require a token — if you don't pass one, a random token is
# generated and requests without it are rejected — so set it explicitly.
docker run -d --name browserless -p 3032:3000 -e "TOKEN=local-dev-token" ghcr.io/browserless/chromium
```

Then set the same token so the tool sends it (uncomment `token: $BROWSERLESS_TOKEN`
in the config above):

```bash
export BROWSERLESS_TOKEN=local-dev-token
```

Verify the instance is reachable before enabling the tool:

```bash
curl -sS "http://localhost:3032/screenshot?token=local-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "options": {"type": "png"}}' \
  -o /tmp/browserless-check.png  # writes a PNG on success
```

For Docker Compose deployments, run Browserless as a service and point `base_url`
at the service name (e.g. `http://browserless:3000`) instead of `localhost`. See
the [Browserless project](https://github.com/browserless/browserless) for full
deployment and configuration options.

### Sandbox

DeerFlow supports multiple sandbox execution modes. Configure your preferred mode in `config.yaml`:

**Local Execution** (runs sandbox code directly on the host machine):
```yaml
sandbox:
   use: deerflow.sandbox.local:LocalSandboxProvider # Local execution
   allow_host_bash: false # default; host bash is disabled unless explicitly re-enabled
```

**Docker Execution** (runs sandbox code in isolated Docker containers):
```yaml
sandbox:
   use: deerflow.community.aio_sandbox:AioSandboxProvider # Docker-based sandbox
```

**BoxLite micro-VM Sandbox** (runs sandbox code in daemonless OCI micro-VMs):
```yaml
sandbox:
   use: deerflow.community.boxlite:BoxliteProvider
   image: python:3.12-slim
   memory_mib: 1024                 # optional per-box memory cap
   cpus: 2                          # optional per-box vCPUs
   replicas: 3                      # max active + warm VMs per gateway process
   idle_timeout: 600                # warm VM idle seconds before stop; 0 disables idle reaping
   environment:
      PYTHONUNBUFFERED: "1"
```

Install the optional runtime before selecting this provider:

```bash
pip install "deerflow-harness[boxlite]"
```

BoxLite boxes are named from the effective `(user_id, thread_id)` scope and are
released into an in-process warm pool after each turn. The same user/thread can
reclaim its warm VM on the next acquire; different threads cannot share a VM.
`replicas` caps active plus warm VMs. When the cap is reached only warm VMs are
evicted; active VMs continue and the provider may temporarily exceed the cap if
all boxes are active.

**Docker Execution with Kubernetes** (runs sandbox code in Kubernetes pods via provisioner service):

This mode runs each sandbox in an isolated Kubernetes Pod on your **host machine's cluster**. Requires Docker Desktop K8s, OrbStack, or similar local K8s setup.

```yaml
sandbox:
   use: deerflow.community.aio_sandbox:AioSandboxProvider
   provisioner_url: http://provisioner:8002
```

When using Docker development (`make docker-start`), DeerFlow starts the `provisioner` service only if this provisioner mode is configured. In local or plain Docker sandbox modes, `provisioner` is skipped.

Remote/provisioner backends default to explicit file synchronization because
DeerFlow cannot infer whether their `/mnt/user-data` mount points reference the
same storage as the Gateway. When the deployment guarantees that both sides use
the same thread user-data directories, opt out of that extra transfer:

```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  provisioner_url: http://provisioner:8002
  thread_data_mounts: true
```

Leave `thread_data_mounts` unset to retain backend auto-detection. Set it to
`false` to force explicit synchronization even for a local container backend.
Only set it to `true` after verifying the Gateway's
`users/{user_id}/threads/{thread_id}/user-data` directory and the sandbox's
`/mnt/user-data` are the same storage; a false positive skips synchronization
and makes newly uploaded files unavailable inside the sandbox.

See [Provisioner Setup Guide](../../docker/provisioner/README.md) for detailed configuration, prerequisites, and troubleshooting.

**E2B Cloud Sandbox** (runs sandbox code in [E2B](https://e2b.dev) cloud micro-VMs):

```yaml
sandbox:
   use: deerflow.community.e2b_sandbox:E2BSandboxProvider
   api_key: $E2B_API_KEY            # required; or set the E2B_API_KEY env var
   template: code-interpreter-v1     # e2b sandbox template id
   # domain: e2b.dev                # optional; for self-hosted e2b deployments
   home_dir: /home/user             # /mnt/user-data is remapped under this directory
   idle_timeout: 600                # forwarded to e2b's server-side set_timeout()
   replicas: 3                      # max concurrent sandboxes per gateway process
   ownership:                       # use Redis when more than one gateway shares E2B
     type: redis
     redis_url: $REDIS_URL
   reconciliation_interval_seconds: 60
   reconciliation_grace_seconds: 120
   reconciliation_orphan_ttl_seconds: 3600
   reconciliation_max_pages: 10
   reconciliation_max_items: 200
   reconciliation_max_seconds: 15
   mounts:                          # one-shot upload of host files at sandbox start
     - host_path: /path/on/host
       container_path: /home/user/shared
       read_only: false
   environment:                     # forwarded to the sandbox at create time
     OPENAI_API_KEY: $OPENAI_API_KEY
```

`e2b-code-interpreter` is bundled as a core dependency of `deerflow-harness`,
so no extra install step is needed; just supply your API key and switch the
provider in `config.yaml`.

Notes specific to `E2BSandboxProvider`:

- Each DeerFlow thread is bound to its E2B sandbox via metadata
  (`deer_flow_user`, `deer_flow_thread`). Startup and periodic reconciliation
  probe every bounded candidate, adopt one healthy canonical sandbox, and reap
  duplicates after a grace period. Provider-tagged entries without a complete
  user/thread identity are reaped only after the orphan TTL.
- Ownership leases prevent one gateway from adopting or destroying a sandbox
  another live gateway is responsible for. The default in-memory store is safe
  only for one gateway process. Multi-worker/load-balanced deployments must use
  `sandbox.ownership.type: redis`; an existing Redis stream bridge configuration
  is inferred automatically.
- Reconciliation is bounded by page, item, and wall-clock limits. Its summary log
  exposes discovered, adopted, duplicate, deferred, killed, dead, and budget-exhausted
  counts for operational monitoring.
- Idle expiry is enforced server-side by e2b's `set_timeout()`. The provider
  refreshes the timeout on every release so warm sandboxes stay alive long
  enough for the next acquire.
- `mounts` are uploaded once when the sandbox starts; e2b cannot host bind-mount
  the gateway filesystem, so changes inside the sandbox are not reflected back
  on disk automatically. Use the `download_file` tool or write outputs under
  `/mnt/user-data/outputs/` (which is mapped to `home_dir/outputs/` inside the
  sandbox and surfaced through the standard artifact pipeline) to ship files
  back to the gateway.

**OpenSandbox Remote Sandbox** (runs code through an OpenSandbox deployment):

```yaml
sandbox:
   use: deerflow.community.opensandbox:OpenSandboxProvider
   image: python:3.11
   api_key: $OPEN_SANDBOX_API_KEY     # optional when the SDK env var is set
   domain: localhost:8080             # OPEN_SANDBOX_DOMAIN fallback
   protocol: http
   request_timeout: 30                # management request timeout seconds
   ready_timeout: 30                  # create/readiness timeout seconds
   use_server_proxy: false            # proxy execd/file traffic through server
   sandbox_timeout: 14400             # remote lifetime; 0 = explicit cleanup
   bash_command_timeout: 600          # default remote command timeout seconds
   replicas: 3                        # active + warm cap per gateway process
   idle_timeout: 600                  # warm seconds before destroy; 0 disables
   environment:
      PYTHONUNBUFFERED: "1"
```

Install the optional SDK before selecting this provider:

```bash
pip install "deerflow-harness[opensandbox]"
```

The provider creates a sandbox per effective user/thread scope and parks it in
an in-process warm pool after each turn. The same scope can reclaim it after a
health check; another user or thread cannot. Create-time readiness and
`/mnt/user-data/{workspace,uploads,outputs}` bootstrap failures are cleaned up
before `acquire()` returns. Each remote owns an independent SDK transport.
Operations renew the configured server-side lifetime, and commands without an
explicit timeout use `bash_command_timeout`; a longer explicit timeout extends
the renewal horizon to cover the command. Operations on one remote are
serialized so a shorter renewal cannot overwrite an in-flight command's
horizon. File transfer uses OpenSandbox's native filesystem API; bounded
`find`/`grep` commands implement the directory and content-search surface.
Downloads are restricted to `/mnt/user-data` and all file paths reject
traversal. Multi-process discovery and ownership coordination are not yet
implemented, so `replicas` is a per-Gateway-process soft cap.

Choose between local execution or Docker-based isolation:

**Option 1: Local Sandbox** (default, simpler setup):
```yaml
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false
```

`allow_host_bash` is intentionally `false` by default. DeerFlow's local sandbox is a host-side convenience mode, not a secure shell isolation boundary. If you need `bash`, prefer `AioSandboxProvider`. Only set `allow_host_bash: true` for fully trusted single-user local workflows.

When `LocalSandboxProvider` runs under `make up`, it runs inside the `deer-flow-gateway` container. In that mode, `sandbox.mounts[].host_path` is resolved from the gateway container's filesystem, not from your Docker host. If you need a local-sandbox custom mount in production Docker, bind the host directory into the gateway service first, then use the in-container path in `config.yaml`:

```yaml
# docker/docker-compose.yaml or an override file
services:
  gateway:
    volumes:
      - ${DEER_FLOW_REPO_ROOT}/.deer-flow/knowledge:/app/.deer-flow/knowledge:ro
```

```yaml
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  mounts:
    - host_path: /app/.deer-flow/knowledge
      container_path: /mnt/knowledge
      read_only: true
```

If the configured `host_path` is not visible to the gateway process, DeerFlow logs an error and ignores that mount.

**Option 2: Docker Sandbox** (isolated, more secure):
```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  port: 8080
  auto_start: true
  container_prefix: deer-flow-sandbox

  # Optional: Additional mounts
  mounts:
    - host_path: /path/on/host
      container_path: /path/in/container
      read_only: false
```

When you configure `sandbox.mounts`, DeerFlow exposes those `container_path` values in the agent prompt so the agent can discover and operate on mounted directories directly instead of assuming everything must live under `/mnt/user-data`.

#### Sandbox container network exposure and hardening

The sandbox HTTP API (`/v1/shell/*` and friends) has no authentication: anyone who can reach a published sandbox port can execute arbitrary commands in that sandbox. For bare-metal Docker sandbox runs that use localhost, DeerFlow binds the sandbox port to `127.0.0.1` so it is not exposed on other host interfaces. For Docker-outside-of-Docker deployments that connect through `host.docker.internal`, the port is bound to the address that hostname actually resolves to — the daemon's `host-gateway-ip` mapping (customizable, possibly IPv6) — so the published port and the address the gateway connects to always match, and the port is no longer published on external network interfaces (previously it was bound to `0.0.0.0`). If resolution fails, the Docker default bridge gateway (via `docker network inspect bridge`, falling back to `172.17.0.1`) is used as a best-effort bind and a warning is logged. Set `DEER_FLOW_SANDBOX_BIND_HOST` explicitly if your deployment needs a different bind address; setting it to `0.0.0.0` restores the legacy broad bind, which re-exposes the unauthenticated exec API on every interface and should be paired with an external firewall.

Local Docker sandbox containers are also hardened by default: all Linux capabilities are dropped (`--cap-drop=ALL`) except the minimum four the shipped image needs — `CHOWN` (the entrypoint chowns /opt/jupyter), `SETUID`/`SETGID` (it creates the gem user and drops to it via `su`), and `DAC_OVERRIDE` (the root nginx master writes gem-owned logs under /var/log/nginx, a per-request runtime need) — privilege escalation is blocked across exec (`no-new-privileges`), and CPU/memory/PID resources are bounded.

A custom image that is already fully initialized as a non-root user (no runtime root handoff) should set `DEER_FLOW_SANDBOX_IMAGE_STARTUP_CAPS=0` to drop every capability including those three: leaving them on would let sandboxed code chown bind-mounted paths or impersonate mounted-file UIDs/GIDs for the container's lifetime. Note that `no-new-privileges` does **not** mitigate that risk — it only blocks gaining privileges across exec; the risk comes from the retained `CAP_SETUID`/`CAP_SETGID` themselves. One hardening knob is relaxed by default: the shipped AIO image runs with `seccomp=unconfined` because its Chromium browser does not start under Docker's default seccomp profile (syscall filtering is disabled — see the two seccomp variables below to change that). The following environment variables (set them in the gateway process, e.g. via `.env` loaded by docker-compose, or the gateway service `environment:`) tune or disable each knob:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `DEER_FLOW_SANDBOX_BIND_HOST` | loopback / bridge gateway (see above) | Host interface for the sandbox `-p` publish. Must be an IP literal (bare or bracketed IPv6) or a hostname, which is resolved to an address first — Docker publish specs do not accept hostnames. `0.0.0.0` restores the legacy broad bind (risky). |
| `DEER_FLOW_SANDBOX_SECCOMP_UNCONFINED` | on | The shipped AIO image's Chromium browser does not start under Docker's default seccomp profile (see the upstream agent-infra sandbox FAQ), so `seccomp=unconfined` remains the default. Set to `0` to run with the built-in profile — passed explicitly as `seccomp=builtin`, so a daemon configured with a different default cannot weaken the opt-out — and only for images verified to start and pass browser checks with it. |
| `DEER_FLOW_SANDBOX_IMAGE_STARTUP_CAPS` | on | Keeps the four capabilities (`CHOWN`/`SETUID`/`SETGID`/`DAC_OVERRIDE`) that the shipped image needs: three for the entrypoint's runtime user handoff, plus `DAC_OVERRIDE` because the root nginx master writes gem-owned log files for the container's lifetime. Set to `0` for images already fully initialized as a non-root user — every capability is then dropped, so sandboxed code cannot chown bind-mounted paths or impersonate mounted-file UIDs/GIDs. |
| `DEER_FLOW_SANDBOX_SECCOMP_PROFILE` | unset | Path to a custom seccomp profile (e.g. a restricted, Chromium-compatible one built from Docker's default plus the namespace syscalls Chromium needs). Takes precedence over the unconfined default. |
| `DEER_FLOW_SANDBOX_MEMORY` | `2g` | `--memory` limit per sandbox container. `0`/`none` disables the limit. |
| `DEER_FLOW_SANDBOX_CPUS` | `2` | `--cpus` limit per sandbox container. `0`/`none` disables the limit. |
| `DEER_FLOW_SANDBOX_PIDS_LIMIT` | `512` | `--pids-limit` per sandbox container (fork-bomb guard). `0`/`none` disables the limit. |
| `DEER_FLOW_SANDBOX_CONTAINER_USER` | unset (image default) | Passed through as `--user` (e.g. `1000:1000`). The default AIO image's user is upstream-controlled, so DeerFlow does not force one; set this only if you know your image's runtime user. |
| `DEER_FLOW_SANDBOX_NETWORK` | unset (daemon default network) | Passed through as `--network`. Point it at a dedicated, egress-controlled Docker network so sandbox egress can be filtered by that network's policy; by default sandbox code can otherwise reach internal networks and cloud metadata endpoints directly. `host`, `container:<name>`, and `none` are rejected at startup (including through Docker's extended `name=<network>` syntax, whose effective target is validated): Docker drops `-p/--publish` in host mode (and shares the namespace for `container:<name>`), which would void the hardened port bind and re-expose the unauthenticated exec API; `none` leaves the container loopback-only, so the published sandbox API port cannot receive traffic and every acquisition would time out. |

These hardening flags are Docker-only; Apple Container (`container` runtime) keeps its previous, unhardened invocation.

Sandbox control-plane HTTP calls to loopback/private IPs, single-label cluster
hosts, and Docker/Podman internal hostnames bypass `HTTP_PROXY`/`HTTPS_PROXY`
inside the client. This prevents an inherited proxy from returning a misleading
502 for a healthy local sandbox. Externally hosted sandbox FQDNs and public IPs
continue to use the normal environment proxy configuration.

### Building a Custom AIO Sandbox Image

`AioSandboxProvider` talks to the sandbox container through the `agent-sandbox` SDK. The Dockerfile for the default `enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest` image is not part of this repository; DeerFlow treats that image as an upstream AIO sandbox runtime.

For persistent system or language dependencies, extend the published image and keep its startup command intact:

```dockerfile
FROM enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest

USER root
# Example user dependency; not required by DeerFlow itself.
RUN apt-get update \
    && apt-get install -y --no-install-recommends graphviz \
    && rm -rf /var/lib/apt/lists/*

# Example Python dependency for work done inside the sandbox.
RUN python -m pip install --no-cache-dir pandas

# Do not override ENTRYPOINT or CMD; keep the upstream sandbox server startup.
```

Use the custom image in local Docker or Apple Container mode with `sandbox.image`:

```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  image: your-registry/your-aio-sandbox:tag
```

In provisioner mode, sandbox Pods are created by the provisioner service, so configure the provisioner `SANDBOX_IMAGE` environment variable instead of `sandbox.image`. See the [Provisioner Setup Guide](../../docker/provisioner/README.md#custom-sandbox-image).

If you rebuild the runtime from scratch instead of extending the published image, it must expose the same HTTP API used by `agent-sandbox`. DeerFlow currently depends on:

- `sandbox.get_context()`, including `home_dir`
- `shell.exec_command(...)`
- `bash.exec(...)` — only exercised for per-command environment injection (skills that declare `required-secrets`). The `/v1/bash/*` routes exist since upstream all-in-one-sandbox `1.9.3`; on older images (including a `latest` tag still frozen on the `1.0.0.x` line) DeerFlow fails fast with an actionable error instead of surfacing the raw 404. Pin `sandbox.image` to `1.9.3` or newer (e.g. `1.11.0`) and recreate the sandbox container to use `required-secrets` with the AIO sandbox.
- `file.read_file(...)`
- `file.write_file(...)`, including base64 writes for binary content
- streamed `file.download_file(...)`
- `file.find_files(...)`
- `file.list_path(...)`
- `file.search_in_file(...)`

Custom images must also keep these compatibility constraints:

- The container should listen on the configured sandbox port, `8080` by default.
- `/mnt/user-data` must remain writable because DeerFlow mounts thread workspace, uploads, and outputs there.
- `home_dir` comes from the sandbox context endpoint; do not assume DeerFlow hardcodes it.
- Shell command handling must remain compatible with serialized `exec_command` calls. DeerFlow serializes shell access on the host side to avoid corrupting the sandbox's persistent shell session.

### Skills

Configure the skills directory for specialized workflows:

```yaml
skills:
  # Host path (optional, default: ../skills)
  path: /custom/path/to/skills

  # Container mount path (default: /mnt/skills)
  container_path: /mnt/skills
```

**How Skills Work**:
- Skills are stored in `deer-flow/skills/{public,custom}/`
- Each skill has a `SKILL.md` file with metadata
- Skills are automatically discovered and loaded
- Available in both local and Docker sandbox via path mapping

Skill installs and agent-managed skill writes also run through native deterministic SkillScan before the LLM scanner:

```yaml
skill_scan:
  enabled: true
```

Set `skill_scan.enabled: false` to disable only the deterministic analyzers. Safe archive extraction and the LLM-based skill scanner still run.

**Per-Agent Skill Filtering**:
Custom agents can restrict which skills they discover and activate by defining a `skills` field in their `config.yaml` (located at `workspace/agents/<agent_name>/config.yaml`):
- **Omitted or `null`**: Makes all globally enabled skills available (default fallback).
- **`[]` (empty list)**: Disables all skills for this specific agent.
- **`["skill-name"]`**: Makes only the explicitly specified skills available.

This field is a discovery and activation allowlist; it does not activate every listed skill's `allowed-tools` policy when the agent is constructed. Use `tool_groups` to define the agent's baseline tools. A listed skill's policy applies only after slash activation or an actual `SKILL.md` load.

The same semantics apply to `subagents.agents.<name>.skills` and `subagents.custom_agents.<name>.skills`: omitted or `null` exposes all enabled skills, `[]` exposes none, and a list limits discovery and activation. A passive subagent skill never removes baseline tools; its `allowed-tools` declaration becomes active only after slash activation or a completed `SKILL.md` read.

### Title Generation

Automatic conversation title generation:

```yaml
title:
  enabled: true
  max_words: 6
  max_chars: 60
  model_name: null  # null = fast local fallback; set a model name to use LLM title generation
```

### GitHub API Token (Optional for GitHub Deep Research Skill)

The default GitHub API rate limits are quite restrictive. For frequent project research, we recommend configuring a personal access token (PAT) with read-only permissions.

**Configuration Steps**:
1. Uncomment the `GITHUB_TOKEN` line in the `.env` file and add your personal access token
2. Restart the DeerFlow service to apply changes

## Environment Variables

DeerFlow supports environment variable substitution using the `$` prefix:

```yaml
models:
  - api_key: $OPENAI_API_KEY  # Reads from environment
```

**Common Environment Variables**:
- `OPENAI_API_KEY` - OpenAI API key
- `ANTHROPIC_API_KEY` - Anthropic API key
- `DEEPSEEK_API_KEY` - DeepSeek API key
- `MIMO_API_KEY` - Xiaomi MiMo API key
- `NOVITA_API_KEY` - Novita API key (OpenAI-compatible endpoint)
- `TAVILY_API_KEY` - Tavily search API key
- `BRAVE_SEARCH_API_KEY` - Brave Search API key for `web_search` and `image_search`
- `SERPER_API_KEY` - Serper (Google Search/Images API) key for `web_search` and `image_search`
- `GROUNDROUTE_API_KEY` - GroundRoute meta-search API key for `web_search` and `web_fetch` (routes across Serper, Brave, Exa, Tavily, Firecrawl, Perplexity with gain-share pricing)
- `BROWSERLESS_TOKEN` - Browserless Cloud token for `web_capture` (optional for self-hosted Browserless)
- `DEER_FLOW_PROJECT_ROOT` - Project root for relative runtime paths
- `DEER_FLOW_CONFIG_PATH` - Custom config file path
- `DEER_FLOW_EXTENSIONS_CONFIG_PATH` - Custom extensions config file path
- `DEER_FLOW_HOME` - Runtime state directory (defaults to `.deer-flow` under the project root)
- `DEER_FLOW_SKILLS_PATH` - Skills directory when `skills.path` is omitted
- `GATEWAY_ENABLE_DOCS` - Set to `false` to disable Swagger UI (`/docs`), ReDoc (`/redoc`), and OpenAPI schema (`/openapi.json`) endpoints (default: `true`)

## Configuration Location

The configuration file should be placed in the **project root directory** (`deer-flow/config.yaml`). Set `DEER_FLOW_PROJECT_ROOT` when the process may start from another working directory, or set `DEER_FLOW_CONFIG_PATH` to point at a specific file.

## Configuration Priority

DeerFlow searches for configuration in this order:

1. Path specified in code via `config_path` argument
2. Path from `DEER_FLOW_CONFIG_PATH` environment variable
3. `config.yaml` under `DEER_FLOW_PROJECT_ROOT`, or under the current working directory when `DEER_FLOW_PROJECT_ROOT` is unset
4. Legacy backend/repository-root locations for monorepo compatibility

## Security Notes
### Sandbox Isolation and the Docker Socket (DooD)

DeerFlow executes agent-generated shell/code through a configurable sandbox
(`sandbox.use` in `config.yaml`). The isolation guarantees differ by mode, and
one mode requires mounting the host Docker socket. Understand the trade-offs
before exposing an instance to untrusted input.

| Mode | `config.yaml` | Host Docker socket | Isolation |
|------|---------------|--------------------|-----------|
| `local` (default) | `deerflow.sandbox.local:LocalSandboxProvider` | Not mounted | Commands run **inside the gateway container** on its filesystem. Not a strong boundary — `allow_host_bash` is `false` by default and should stay off for untrusted workloads. |
| `aio` (pure DooD) | `deerflow.community.aio_sandbox:AioSandboxProvider` (no `provisioner_url`) | **Mounted** (opt-in overlay) | Sandbox containers are started via the host Docker daemon. |
| `provisioner` (Kubernetes) | `AioSandboxProvider` + `provisioner_url` | Not mounted | Sandbox pods are created through the provisioner's K8s API over HTTP. Strongest isolation. |

#### The Docker socket is host root

Mounting `/var/run/docker.sock` into a container grants that container
**root-equivalent control of the host**: anything able to reach the socket can
start a new container that bind-mounts the host filesystem and escape. This
matters for DeerFlow because the gateway executes model-generated commands, so a
prompt injection or any in-container code-execution primitive could pivot to the
host through the socket.

To keep this off the default attack surface:

- The host Docker socket is **not** mounted by the default Compose stack. It is
  added only for `aio` mode through the opt-in `docker/docker-compose.dood.yaml`
  overlay, which `scripts/deploy.sh` and `scripts/docker.sh` append
  automatically when `detect_sandbox_mode()` returns `aio`.
- Prefer **provisioner/Kubernetes mode** for multi-tenant or internet-exposed
  deployments — it isolates sandboxes without handing the gateway the host
  daemon.
- If you must use `aio`/DooD, treat the host as part of the gateway's trust
  boundary: run it on a dedicated host, and consider a scoped Docker API proxy
  instead of the raw socket.

> Note: the gateway bind-mounts `$HOME/.claude` and `$HOME/.codex` (read-only)
> for CLI auto-auth in **all** modes. These hold long-lived CLI credentials;
> scope or omit them when the gateway runs untrusted workloads.

### CLI Credential Mounts (Claude Code / Codex / MiniMax Code)

DeerFlow can reuse your Claude Code / Codex CLI subscription login as a model
provider (`ClaudeChatModel`, the Codex provider) or for ACP agents that run the
CLI in-container. The Compose stack used to bind-mount the **entire** `~/.claude`
and `~/.codex` directories (read-only) into the gateway container in **every**
configuration — exposing not just credentials but full conversation history,
per-project session data, and global CLI config. A gateway compromise (prompt
injection, tool/MCP misuse, RCE) would leak all of it.

These directories are **no longer mounted by default**. Supply CLI credentials
with the least exposure that fits your setup:

| Need | How | Exposure |
|------|-----|----------|
| Claude model provider | env `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_AUTH_TOKEN` (via `.env`), or `CLAUDE_CODE_CREDENTIALS_PATH` → a single mounted `.credentials.json` | none / one file |
| Codex model provider | env `CODEX_AUTH_PATH` pointing at a single mounted `auth.json` | one file |
| ACP agent | the adapter's own auth — many ACP adapters take an env API key (e.g. `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) and need no mount; use the opt-in `docker/docker-compose.cli-auth.yaml` overlay only if your adapter reads the full CLI config dir | none / full dir |

The Gateway credential loader checks environment variables **before** the
default credential files, so the env-token paths need no bind mount at all. ACP
adapters authenticate independently of DeerFlow via their own documented env —
for example the common `claude-code-acp` adapter starts as
`ANTHROPIC_API_KEY=… claude-code-acp` and honors `CLAUDE_CONFIG_DIR` to redirect
its config directory, so it needs no `~/.claude` mount at all. Prefer the
adapter's documented env auth, and reach for the
`docker-compose.cli-auth.yaml` overlay only as a fallback for an adapter that
genuinely reads the full CLI config directory.

MiniMax Code is a native ACP agent, so it does not need an adapter. For local
Gateway runs, install it with `npm install --global @minimax-ai/code`, run
`mcode login`, and configure `acp_agents.mcode` with `command: mcode` and
`args: ["acp"]`. The executable and its authenticated runtime must be available
inside the Gateway environment; a host-only installation is not visible to a
Docker container. DeerFlow forwards enabled MCP servers to the MCode session.
Leave `auto_approve_permissions` disabled for untrusted tasks, and enable it
only when the agent is expected to edit files or run commands for a trusted
task.


## Best Practices

1. **Place `config.yaml` in project root** - Set `DEER_FLOW_PROJECT_ROOT` if the runtime starts elsewhere
2. **Never commit `config.yaml`** - It's already in `.gitignore`
3. **Use environment variables for secrets** - Don't hardcode API keys
4. **Keep `config.example.yaml` updated** - Document all new options
5. **Test configuration changes locally** - Before deploying
6. **Use Docker sandbox for production** - Better isolation and security

## Troubleshooting

### "Config file not found"
- Ensure `config.yaml` exists in the **project root** directory (`deer-flow/config.yaml`)
- If the runtime starts outside the project root, set `DEER_FLOW_PROJECT_ROOT`
- Alternatively, set `DEER_FLOW_CONFIG_PATH` environment variable to custom location

### "Invalid API key"
- Verify environment variables are set correctly
- Check that `$` prefix is used for env var references

### "Skills not loading"
- Check that `deer-flow/skills/` directory exists
- Verify skills have valid `SKILL.md` files
- Check `skills.path` or `DEER_FLOW_SKILLS_PATH` if using a custom path

### "Docker sandbox fails to start"
- Ensure Docker is running
- Check port 8080 (or configured port) is available
- Verify Docker image is accessible

## Examples

See `config.example.yaml` for complete examples of all configuration options.

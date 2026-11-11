# Configuration

Application SQL JSON writes normalize non-finite floats (`NaN`, `Infinity`, `-Infinity`) to `null` on SQLite and PostgreSQL, including DB-backed agent definitions and skill-mutation records. Existing rows are not rewritten.

With `run_events.backend: db`, caller-supplied ISO 8601 event timestamps are normalized to UTC before storage, preserving their instant when SQLite drops timezone information. Timestamps without an offset are treated as UTC. Previously stored timestamps are not rewritten.

Run event streams include `run.terminal` for the owning worker's confirmed final
Run status, while `run.end` continues to describe each root graph completion.
Terminal publication is best effort; event persistence failure does not undo the
Run outcome or prevent stream completion. Recovery with built-in SQL Run and Event stores
sharing an engine uses one pooled connection for each guarded event write, so it
can publish with only one pool slot available. See [Run Event Stream](../../backend/docs/RUN_EVENT_STREAM.md#authoritative-run-outcome).

PostgreSQL async ORM connections and the offline command accept `postgres://`
and `postgresql://` URLs, including `?sslmode=disable` or `?sslmode=verify-full`.
SSL modes are preserved; conflicting `ssl`/`sslmode` settings are rejected.
Explicit `channel_binding` options are rejected because asyncpg cannot enforce
them. Synchronous psycopg and LangGraph DSNs retain their libpq options.

With a fencing-capable SQL RunStore and `DbRunEventStore`, host-authorized
producer writes validate the persisted Run incarnation, producer epoch and state
even with `run_events.producer_fencing: "off"`. Stale Journal flushes after
takeover or deletion may therefore be rejected in the default configuration.
On PostgreSQL, these writes hold the Thread Fence and RunRow lock through commit.
Checkpoint and branch history imports use a separate host grant bound to a
durable thread-operation reservation and the captured thread identity. Strict
mode permits these imports without treating synthetic turn IDs as admitted Runs;
deletion, reservation revocation or lease expiry invalidates their grant.
Messages preceding the first human input retain their existing synthetic turn 0.

On PostgreSQL, `run_events.producer_fencing: "strict"` additionally enables
database-level authorization checks against raw SQL and unaware legacy writers
after an offline cutover. The `"off"` setting keeps application-level producer
validation active. Before activation, the database INSERT trigger skips its
Thread/RunRow locks and retains a shared cutover lock until each INSERT
transaction ends. This does not remove the application locks above. Off-mode
event INSERTs require `READ COMMITTED` (also accepting PostgreSQL's `READ UNCOMMITTED`);
`REPEATABLE READ` and `SERIALIZABLE` are rejected to prevent stale policy snapshots
from bypassing activation. A write that loses a race with activation rolls back
with SQLSTATE `40001`; retry the entire transaction with strict producer authority.
Activation requires stopping every Gateway and using the offline cutover command;
all restarted Gateways must use the same cutover ID. This does not recover missing
terminal events. To activate:

1. Deploy this version everywhere with `run_events.producer_fencing: "off"`.
   Complete migrations 0049 and 0050 and recover previously active Runs, then
   drain admissions and completion hooks. A terminal Run status alone does not
   prove its producer has drained.
2. Stop every Gateway, Worker and other database client, including checkpointer
   pools and monitoring clients, and keep them stopped during activation.
3. From the repository root, using the installed backend environment, run:

   ```bash
   uv run --no-sync --project backend python backend/scripts/run_producer_fencing.py \
     --config config.yaml --cutover-id deployment-2026-10-27 --all-gateways-stopped
   ```

   The command refuses activation if other database sessions or pending/running
   Runs remain. Use a deployment ID that every Gateway will share.
4. Set `database.backend: postgres`, `run_events.backend: db`,
   `run_events.producer_fencing: strict` and
   `run_events.producer_cutover_id: deployment-2026-10-27` everywhere, then restart.
   Verify a new Run persists its initial event, Journal/Hook, delivery and terminal
   events and closes normally; unaware old writers must receive a database rejection.

Activation is durable: missing or mismatched cutover IDs and downgrades to `"off"`
or unsupported stores fail startup. This release requires controlled downtime;
it does not support a mixed-version rolling cutover. A crashed producer may stay
open until explicitly closed or revoked by authorized takeover/deletion; no
producer-expiry or terminal-reconciliation job is introduced.

Scheduled-task orphan recovery carries the captured Run incarnation and retention
revision when publishing delivery and terminal evidence, including in strict mode.
Unconfirmed publication is logged separately from the committed takeover; it does
not undo the recovered Run or queue a new publication attempt.

Operators can extend lead-agent, subagent, and DeerMem extraction prompts with
literal prepend/append configuration without editing source templates. See
[prompt overlays](../../backend/docs/CONFIGURATION.md#prompt-overlays).

Optional per-model [`request_admission`](../../backend/docs/CONFIGURATION.md#model-request-admission)
paces requests to help stay within provider request-per-minute limits.
It is disabled by default; see the linked guide to enable it.
Enabling it disables exposed SDK retries and the Claude and Codex adapters'
internal retry loops so middleware retries pass through request admission again.
Middleware retries also cover HTTP 529 overload responses.
A warning identifies `retry_max_attempts` values overridden by admission.

For Google's official Gemini OpenAI-compatible endpoint, use the
[Gemini reasoning profile](../../backend/docs/CONFIGURATION.md#gemini-via-googles-openai-compatible-endpoint).

For MindIE XML tool calls, see the
[argument parsing and newline compatibility guide](../../backend/docs/CONFIGURATION.md#mindie-xml-tool-arguments).
Tool-result recovery treats null and empty call IDs alike — including the
`"None"` and `"missing_tool_call_id"` spellings middleware producers use when a
provider call had no ID — preserving middleware guidance when a result can be
uniquely paired; ambiguous partial results remain rejected.
Both synchronous and asynchronous streams retain this compatibility: tool-enabled
streams simulate chunks from a non-streaming response, while no-tool streams stay native.
Newline compatibility preserves literal escapes inside backtick and tilde code
fences, including unclosed fences, in complete and streamed replies.

1. **Clone the DeerFlow repository**

   ```bash
   git clone https://github.com/bytedance/deer-flow.git
   cd deer-flow
   ```

2. **Run the setup wizard**

   From the project root directory (`deer-flow/`), run:

   ```bash
   make setup
   ```

   This launches an interactive wizard that guides you through choosing an LLM provider, optional web search, and execution/safety preferences such as sandbox mode, bash access, and file-write tools. It generates a minimal `config.yaml` and writes your keys to `.env`. Takes about 2 minutes.

   The wizard also lets you configure an optional web search provider, or skip it for now.

   Brave web search preserves valid entries in mixed result lists. Malformed response containers or lists containing no usable entries return a structured format error; missing, null, or empty results keep the existing "No results found" response. Format errors also log the malformed container's path and type, or the absence of usable result objects, without including search queries, credentials, or payload values.

   Several providers, including You.com, GroundRoute, Webz, InfoQuest and Jsonify, initialize HTTPX clients in a worker thread so synchronous TLS trust loading does not block the agent event loop; requests and session cleanup remain asynchronous.

   GroundRoute web search and fetch contain malformed HTTP-success payloads the same way: a non-object payload, a `results` container that is not a list, or a non-empty list with no object entries returns the provider's format error, while non-object entries in an otherwise valid list are skipped in order. Missing, null, or empty results keep the existing "No results found" response.

   DuckDuckGo web search distinguishes execution failures from empty results: rate limits, timeouts, blocked requests, client-setup failures, SDK errors, and a missing `ddgs` dependency return a structured `DuckDuckGo search failed: ...` error instead of "No results found", while a genuinely empty result set keeps the existing "No results found" response. The structured error text lets the harness classify an outage as transient or a configuration problem instead of a query that matched nothing.
   
   Tavily web search and fetch contain malformed HTTP-success payloads the same way: a non-object payload, or a `results`/`failed_results` container that is not a list, returns the provider's format error, and non-object entries in an otherwise valid list are skipped in order. Missing, null, or empty results keep the existing response (`[]` for search, `Error: No results found` for fetch); missing or null search fields (`title`, `url`, `content`) normalize to empty text, and a non-string fetch `raw_content` is coerced to text before the truncation limit.

   Sofya web search and fetch contain malformed HTTP-success payloads the same way: a non-object payload, a `results` container that is not a list, or a non-empty list with no object entries returns the provider's format error, while non-object entries in an otherwise valid list are skipped in order. Missing, null, or empty results keep the existing "No results found" response.

   Serper web and image search preserve valid entries in mixed result lists. A malformed `organic`/`images` container, or a non-empty list holding no object entries, returns Serper's format error; missing, null, or empty containers keep the existing "No results found" / "No images found" response. Format errors log the container field name only, without queries, credentials, or payload values.

   Unbrowse web fetch preserves the extracted text but prefixes a warning when the target page's HTTP status is 400–599, even when the scraping service itself returns a successful response. Empty-page errors retain that status too. Both messages include up to 500 characters of the reported final URL after removing any username and password; final URLs that cannot be parsed as HTTP(S) URLs with a host are omitted.

   Tencent Cloud WSA web search contains malformed HTTP-success payloads the same way: a `Pages` container that is not a list, or a non-empty container holding no usable page, returns the provider's format error, while malformed page entries in an otherwise valid container are skipped so the valid rows survive. Missing, null, or empty `Pages` keep the existing "No results found" response.

   Serply web search contains malformed HTTP-success payloads the same way in every vertical: a `results`/`entries`/`articles` container that is not a list, or a non-empty list with no object entries, returns the provider's format error, while non-object entries in an otherwise valid list are skipped in order. Missing, null, or empty containers keep the existing "No results found" response.

   SearXNG web search contains malformed HTTP-success payloads the same way: a payload that is not an object, a body that is not JSON, a `results` container that is not a list, or a non-empty list holding no object entries returns the provider's format error, while non-object entries in an otherwise valid page are skipped in order, each skip logged with its entry position, so the valid rows survive and provider-side drift leaves a trace. Missing, null, or empty `results` keep the existing empty result (`[]`). This matters most for a self-hosted instance: one behind a reverse proxy or captive portal answers an HTML or plain-text error page with HTTP 200, and reading that as an empty search ends a research loop as "no hits".

   InfoQuest web and image search contain malformed HTTP-success payloads the same way: a `search_result` envelope that is not an object, or an `organic`/`top_stories.items`/`images_results` container that is not a list or that holds no usable entry, returns the provider's format error, while malformed entries in an otherwise valid payload are skipped so the usable rows survive. Missing, null, or empty containers keep the existing empty result. Format errors log the container or entry position only, without queries or payload values.

   InfoQuest web and image search screen result URLs through the shared public-URL policy and omit rejected rows. Responses without the required `search_result` envelope return a format error instead of exposing the raw provider payload.

   Jina, Browserless, and InfoQuest web fetches resolve relative links and image sources using the requested page URL (or a usable HTML base URL), so returned Markdown includes complete destinations. Link resolution preserves the surrounding HTML source, including malformed-page formatting.

   Direct Python calls to `web_fetch_tool` return `(content, artifact)` so Browserless can keep the target page's HTTP status out of page prose. Callers that previously expected a string should unpack the tuple; Agent tool calls continue to expose content and artifact through LangChain's tool result.

   Browserless fetch and capture accept positive finite request timeouts in seconds. Invalid values fall back to 30 seconds. See [Browserless configuration](../../backend/docs/CONFIGURATION.md#delegated-fetch-backend-isolation).

   Self-hosted Browserless, Crawl4AI, Firecrawl, and fastCRW fetch backends require outbound isolation from private, loopback, link-local, and cloud-metadata networks before setting `network_isolation_confirmed: true` on each tool. DeerFlow rejects private or unverifiable backends by default because those services handle redirects, DNS resolution, and subresources themselves. `allow_private_addresses` permits intentional internal target URLs and does not bypass the backend check. See [delegated fetch deployment](../../backend/docs/CONFIGURATION.md#delegated-fetch-backend-isolation); `make doctor` reports backend configurations that would be refused.

   Jina fetches support opt-in bounded retries via `max_retries` (default `0`) and `retry_budget_seconds` (default `30`) in the tool configuration. Valid `Retry-After` hints set a minimum wait for HTTP 429/503; 429 without a valid hint stays terminal. Hints that cannot fit the remaining budget stop retries. Local backoff remains randomized. Retries may increase upstream requests and cost; see [Jina fetch retries](../../backend/docs/CONFIGURATION.md#jina-fetch-retries).

   At DEBUG level, Jina emits one bounded crawl completion summary with attempts, elapsed/backoff seconds, outcome and stop reason. See [diagnostics](../../backend/docs/CONFIGURATION.md#jina-crawl-diagnostics) for configuration and correlation.

   Jina also accepts an opt-in `max_response_bytes` tool setting (positive integer; omitted/null disables it). It stops oversized decoded responses before extraction, with no partial success or retry. This leaves the 4096-character output cap unchanged and does not bound HTTPX decompressor allocations or wire bandwidth; see [response budget](../../backend/docs/CONFIGURATION.md#jina-response-byte-budget).

   Jina can also bound concurrent HTTP attempts and FIFO waiting with the opt-in `request_admission` tool extra. One immutable budget is shared across clients and agent threads in each process; replicas have independent budgets. See [Jina request admission](../../backend/docs/CONFIGURATION.md#jina-request-admission).

   Run `make doctor` at any time to verify your setup and get actionable fix hints.
   The setup wizard and health check support legacy terminal encodings, including
   Windows cp936, replacing unsupported characters so both commands can finish.
   If you are opening a GitHub issue about a local setup or runtime problem, run
   `make support-bundle`. The command prints reporter next steps, writes a
   `*-issue-summary.md` file to paste into the issue, a `*-issue-draft.md` file
   for AI-assisted issue filing, and an optional evidence zip under
   `.deer-flow/support-bundles/`. If an AI assistant files the issue, start from
   the draft and replace every REQUIRED placeholder instead of inventing missing
   facts. Attach the zip only if a maintainer asks for it, or if the summary
   alone is not enough. Maintainers and AI triage tools can start with
   `triage.json`; the bundle includes redacted diagnostics and file manifests
   only, and does not include `.env`, raw conversation messages, or user file
   contents. Subprocess diagnostics are captured as UTF-8, with Python helpers
   emitting UTF-8 even on non-UTF-8 hosts and escaping unencodable characters.
   Thread manifests follow the local launcher's runtime paths: checkout `.env`
   values override shell exports, and a project-root override alone still uses
   `backend/.deer-flow` first. Simple variable references such as
   `DEER_FLOW_HOME="$PWD/backend/.deer-flow"` use the checkout as `PWD`;
   single-quoted references remain literal. If the checkout `.env` cannot be read or decoded
   as UTF-8, thread diagnostics retain shell exports and default storage paths. For standalone Gateway launches using `backend/.env`
   or `DEER_FLOW_ENV_FILE`, export the effective `DEER_FLOW_HOME` when collecting
   the bundle and ensure the checkout `.env` does not override it.
   Doctor's internal tool probes also decode UTF-8 with replacement for invalid
   bytes so the remaining diagnostic output stays available.

   When a thread manifest is requested, a nonempty `DEER_FLOW_HOME` selects the
   runtime data directory instead of stale checkout data. External data paths
   appear as `{DEER_FLOW_HOME}` in the report; file contents remain excluded.
   Runtime path settings also come from the checkout `.env`, with shell exports
   taking precedence. Relative paths resolve from the checkout as in `make dev`.
   Without an explicit home, a configured `DEER_FLOW_PROJECT_ROOT` selects its
   `.deer-flow` directory; external paths use that variable name in the report.

   > **Advanced / manual configuration**: If you prefer to edit `config.yaml` directly, run `make config` instead to copy the full template. Optional dependency auto-detection accepts UTF-8 configuration files with or without a byte-order mark (BOM). It checks an existing `DEER_FLOW_CONFIG_PATH` first, then `DEER_FLOW_PROJECT_ROOT/config.yaml`, before the checkout's default locations. Local startup also accepts the project-root configuration when the checkout has no `config.yaml`. See `config.example.yaml` for the complete reference including CLI-backed providers (Codex CLI, Claude Code OAuth), OpenRouter, Responses API, subagent runtime caps such as `subagents.max_total_per_run`, and more.

   Optional per-model pricing must use one currency across all priced models.
   DeerFlow disables Console cost estimates when currencies are mixed rather
   than presenting an invalid aggregate.
   For older runs without a per-model usage breakdown, Console attributes the
   recorded total and input token counts to the run's model.

   Administrators can open **Settings → Models** to select a provider and enter
   only its **API Key** and **model ID**. Endpoints, authentication and adapters are
   backend presets for OpenAI, Anthropic, DeepSeek, Alibaba Cloud Bailian/Qwen,
   Volcengine/Doubao, Moonshot/Kimi, Zhipu/Z.AI, MiniMax and StepFun. Region and plan-specific
   entries are explicitly distinguished. Arbitrary model IDs are accepted; internal
   names are generated automatically and remain stable when a model ID changes.
   Newly saved models are enabled and immediately refresh existing chat and Agent
   model selectors, without editing YAML or restarting the Gateway.

   Use **Fetch and add models** to reuse a saved connection or enter a new one,
   search its catalog, and test selected models before adding them. Existing
   entries are retained on retries; individual failures remain available to retry.
   Chat pickers support name/ID search, provider filtering, favorites and the
   eight most recently selected models, scoped to your account in this browser.

   The OpenAI preset routes `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6.1-terra`,
   `gpt-6-sol` and `gpt-6-luna` through the Responses API for tool calling,
   with model-specific thinking and reasoning-effort defaults. Flash mode
   turns off reasoning for GPT-6.1 Terra, GPT-6 Sol and GPT-6 Luna.

   The Moonshot (China) preset recognizes `kimi-k3.1-pro` and
   `kimi-k3.1-pro-highspeed` with required thinking, image input and native
   `low` / `high` / `max` reasoning effort (default `max`). Thinking stays on
   even when a caller requests it off. Requests to the official endpoint omit
   the unsupported thinking switch and fixed sampling parameters. See the
   [model registration reference](../../backend/docs/CONFIGURATION.md#models-registered-through-the-web)
   for the image-input and parameter constraints.

   **Custom OpenAI-compatible** still supports existing/custom base URLs and
   unauthenticated endpoints. **Advanced settings** retains display name, token
   limits and vision overrides; unknown IDs do not receive invented capabilities.
   Leave the key blank on edit to retain it for the same connection. Switching
   provider or custom endpoint requires a new key, and preset models must be
   disabled before clearing their key. YAML models remain read-only.

   Connection testing uses the same model factory and protocol as chat, sends a
   bounded streaming tool-call request and never saves the draft. It may incur
   provider charges and does not verify every agent, vision or thinking workflow.
   Official DeepSeek custom endpoints retain their existing adapter; a proxy does
   not become DeepSeek merely because of its model ID. See the
   [Web model registration reference](../../backend/docs/CONFIGURATION.md#models-registered-through-the-web)
   for presets, compatibility, extension instructions and backup requirements.

   DeepSeek regression tests run offline with the normal backend suite. To verify
   the real provider explicitly, set `DEEPSEEK_TEST_API_KEY` in your environment
   and run from `backend/`:

   ```bash
   DEER_FLOW_RUN_LIVE_TESTS=1 uv run --no-sync pytest tests/test_managed_deepseek_live.py -q
   ```

   These opt-in tests send short requests to DeepSeek and may incur charges;
   they use temporary state, never save credentials to the deployment catalog,
   and are skipped in CI. `DEEPSEEK_TEST_MODEL` optionally selects a different
   DeepSeek model ID (default: `deepseek-flash`). The same tests can be run on
   unfixed and fixed revisions; success is always the expected result.

   YAML models remain read-only in this page and take precedence on name conflicts.
   Managed models are appended after YAML models; edits apply to new configuration
   snapshots, while active runs retain their existing snapshot. Disabling a model
   removes it from future selection/resolution, so update any custom-agent or scheduled
   task definitions that explicitly reference it before disabling it.
   Managed models are shared by the deployment, not personal API-key profiles, and
   remain subject to the existing model authorization policy.

   The encrypted catalog and a generated local encryption key are stored in
   `$DEER_FLOW_HOME/managed-models/` (default `.deer-flow/managed-models/`). Persist
   and back up the **whole directory**, restrict filesystem access, and share it
   across Gateway workers/replicas that should use the same catalog. The local key
   is protected by filesystem permissions; encryption does not protect against
   someone who can read both files. Losing the key requires restoring the backup.
   Reads and writes fail if the catalog cannot be decrypted, rather than replacing it.
   This storage is independent of the SQL backend and works with read-only YAML mounts.

   When several models are configured, open either model picker and use the
   star beside a model to favorite it. Favorites appear first in both the main
   chat and Side Chat pickers without changing either chat's selected or
   default model. They are stored for the signed-in user in the current browser,
   so they do not sync to another browser or device and do not require a startup
   setting. The compact favorites picker intentionally omits search and only
   adds favorite ordering to the two-line model list.

   <details>
   <summary>Manual model configuration examples</summary>

   ```yaml
   models:
     - name: gpt-4o
       display_name: GPT-4o
       use: langchain_openai:ChatOpenAI
       model: gpt-4o
       api_key: $OPENAI_API_KEY

     - name: openrouter-gemini-2.5-flash
       display_name: Gemini 2.5 Flash (OpenRouter)
       use: langchain_openai:ChatOpenAI
       model: google/gemini-2.5-flash-preview
       api_key: $OPENROUTER_API_KEY
       base_url: https://openrouter.ai/api/v1

     - name: opper-claude-sonnet-4-6
       display_name: Claude Sonnet 4.6 (Opper)
       use: langchain_openai:ChatOpenAI
       model: claude-sonnet-4-6
       api_key: $OPPER_API_KEY
       base_url: https://api.opper.ai/v3/compat

     - name: api-route-gpt-6.1-sol
       display_name: GPT 6.1 Sol (API Route)
       use: langchain_openai:ChatOpenAI
       model: gpt-6.1-sol
       api_key: $API_ROUTE_API_KEY
       base_url: https://global.api-route.com/v1

     - name: gpt-5-responses
       display_name: GPT-5 (Responses API)
       use: langchain_openai:ChatOpenAI
       model: gpt-5
       api_key: $OPENAI_API_KEY
       use_responses_api: true
       output_version: responses/v1

     - name: qwen3-32b-vllm
       display_name: Qwen3 32B (vLLM)
       use: deerflow.models.vllm_provider:VllmChatModel
       model: Qwen/Qwen3-32B
       api_key: $VLLM_API_KEY
       base_url: http://localhost:8000/v1
       supports_thinking: true
       when_thinking_enabled:
         extra_body:
           chat_template_kwargs:
             enable_thinking: true
   ```

   OpenRouter and similar OpenAI-compatible gateways should be configured with `langchain_openai:ChatOpenAI` plus `base_url`. If you prefer a provider-specific environment variable name, point `api_key` at that variable explicitly (for example `api_key: $OPENROUTER_API_KEY`).

   [API Route](https://www.api-route.com) is also available in the setup wizard. It saves your key as `API_ROUTE_API_KEY` and uses the Chat Completions endpoint above. Model availability depends on your key's group and permissions; check the authenticated `GET https://global.api-route.com/v1/models` catalog before replacing the model in `config.yaml`, and use its returned ID unchanged without an upstream provider prefix.

   The `write_file` tool's output-budget hint uses the active model's effective `max_tokens`. Missing or unusable limits, including YAML `.inf`, `-.inf`, `.nan`, and values too large for the character estimate, omit this hint without failing tool assembly; provider-specific model validation still applies.

   To route OpenAI models through `/v1/responses`, keep using `langchain_openai:ChatOpenAI` and set `use_responses_api: true` with `output_version: responses/v1`.

   The lead agent also recognizes Responses output-token caps (`status: incomplete` with `incomplete_details.reason: max_output_tokens`), including streaming responses. It suppresses tool execution, removes the suppressed calls from later model requests, and preserves text and reasoning. A capped tool-call response includes a visible notice. Text-only output caps preserve the response and end the turn without unfinished-todo retries; other incomplete reasons retain their existing handling.

   When thinking is disabled on a legacy profile, blank `extra_body`, `thinking`, and nested `extra_body.thinking` keys in a `when_thinking_enabled` template are treated as absent during dialect inference. When thinking is enabled, template values are forwarded as configured.

   Models whose provider contract differs from DeerFlow's generic thinking/effort assumptions can declare a per-model mapping-valued `reasoning:` block (thinking `unsupported`/`optional`/`required`, the accepted effort values with aliases and a default, the payload dialect, and the reasoning-history requirement). The setup wizard's Z.AI GLM-5.3-Flash profile uses it: thinking stays on for every foreground and background call, and the effort selector offers the model's own `low`/`high`/`max` levels. Ollama's existing boolean `reasoning: true` remains a native provider setting and is forwarded to ChatOllama. When migrating a profile to a custom effort `path`, remove any old `reasoning_effort` setting from the profile and thinking templates; configuration validation rejects the leftover key. The chat UI drops a remembered provider-specific effort when switching to a legacy model that does not advertise it. Profiles without the block keep their existing provider behavior. See `config.example.yaml` for the shape and the equivalent manual configuration.

   For vLLM 0.19.0, use `deerflow.models.vllm_provider:VllmChatModel`. For Qwen-style reasoning models, DeerFlow toggles reasoning with `extra_body.chat_template_kwargs.enable_thinking` and preserves vLLM's non-standard `reasoning` field across multi-turn tool-call conversations. Legacy `thinking` configs are normalized automatically for backward compatibility, without modifying model defaults or caller-owned `extra_body` dictionaries; a reused dictionary can change the legacy switch between requests. If the endpoint reports a cumulative usage snapshot on every streaming chunk, set `cumulative_stream_usage: true` so DeerFlow converts those snapshots into per-chunk deltas; the option is disabled by default and leaves usage unchanged when a stable completion id is unavailable. Reasoning models may also require the server to be started with `--reasoning-parser ...`. If your local vLLM deployment accepts any non-empty API key, you can still set `VLLM_API_KEY` to a placeholder value.

   When prompt caching is enabled for a model configured with
   `deerflow.models.claude_provider:ClaudeChatModel`, DeerFlow preserves thinking
   and redacted-thinking history without placing cache breakpoints directly on
   those blocks. Extended-thinking tool follow-ups can keep using prompt caching.

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

   `ClaudeChatModel` normalizes manual extended-thinking budgets when `auto_thinking_budget: true` (the default). An omitted or null budget gets 80% of `max_tokens`, with a minimum of 1024 tokens. Explicit budgets must be integers of at least 1024 and, for ordinary thinking, strictly below `max_tokens`; output limits of 1024 or less fail locally. For supported manual interleaved thinking, configure tools and `betas: ["interleaved-thinking-2025-05-14"]`: the thinking budget may equal or exceed the positive output limit. See [Anthropic's interleaved-thinking rules](https://platform.claude.com/docs/en/build-with-claude/extended-thinking#interleaved-thinking-in-manual-mode) for supported models. `auto_thinking_budget: false` bypasses this normalization and validation; disabled and adaptive thinking are unchanged.

   - Codex CLI reads `~/.codex/auth.json`
   - Codex function tools preserve explicit `strict: true` or `strict: false` in wrapped or flat dictionary definitions. Missing or null settings keep the provider default. `bind_tools` applies the same conversion to dictionaries and `BaseTool` schemas.
   - Codex honors `tool_choice` in `bind_tools` and direct calls: `auto`, `none`, `required`, or a function name/selection. `any` and `True` mean `required`; `None` and `False` keep the provider default. Per-call choices override the bound policy. Bound choices are validated when binding; direct calls and overrides are validated before HTTP. `required` needs at least one function tool, and named selections must match a supplied function. `auto` and `none` also work without tools.
   - Completed Codex responses still return their text and tool calls when token usage is null, omitted, or empty; usage metadata remains unavailable.
   - The Codex model provider returns completed responses without waiting for the SSE connection to close. Failed or incomplete responses report the provider's error or reason; partial output is not returned as a successful answer. Non-object error details are reported as text.
   - `ClaudeChatModel` honors integer-second and HTTP-date `Retry-After` hints in its provider retry loop. Dates use UTC; past dates retry immediately, while invalid hints or delays beyond 24 hours retain local backoff.

   - Claude Code accepts `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_CREDENTIALS_PATH`, or `~/.claude/.credentials.json`
   - `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` accepts a UTF-8 token handoff and reuses it for later model instances in the same process. Undecodable handoffs are skipped so Claude Code can still try its override or default credentials file.
   - CLI credential JSON files accept UTF-8 with or without a BOM, independently of the host locale. `make doctor` accepts the same files when checking CLI authentication. Invalid text encoding is treated as an unreadable source; Claude Code can still try its default file after an invalid override.
   - ACP agent entries are separate from model providers — if you configure `acp_agents.codex`, point it at a Codex ACP adapter such as `npx -y @zed-industries/codex-acp`
   - A bare or absolute ACP agent `command` is resolved before the agent starts, so npm-installed launchers work on Windows too: `npx` or `mcode` is spawned as its `npx.cmd`/`mcode.cmd` shim instead of failing with a command-not-found error, and an absolute path such as `C:\Users\me\AppData\Roaming\npm\mcode` resolves to the `mcode.cmd` shim beside npm's extensionless shell script instead of failing with `WinError 193`. The lookup uses the `PATH` the agent subprocess will actually see (`acp_agents.<name>.env.PATH` when set, otherwise the Gateway's) and hands the spawn an absolute path, so a relative `PATH` entry cannot be re-interpreted inside the agent's own workspace. A relative `command` (for example `bin/mcode`) is used as configured, and a command that cannot be resolved is still reported with the install guidance below.
   - Each ACP agent's `timeout_seconds` (default: 1800) is one shared budget for initialization, session creation, and the prompt, starting after the subprocess launches. On timeout, DeerFlow aborts the invocation and closes the subprocess before returning an error. Workspace/MCP preparation and subprocess cleanup are outside this budget. A `TimeoutError` raised by the SDK before this deadline expires retains its own error message.
   - If an ACP agent exits before answering (for example because it is not authenticated or a configured argument is wrong), DeerFlow reports its exit code within a few seconds instead of waiting for `timeout_seconds`, and records the end of the agent's stderr in the Gateway log. Agent stderr is read continuously, so an agent that logs heavily cannot stall on a full pipe.
   - MiniMax Code speaks ACP directly. Install and authenticate it, then add it as an ACP agent:

   ```bash
   npm install --global @minimax-ai/code
   mcode login
   ```

   ```yaml
   acp_agents:
     mcode:
       command: mcode
       args: ["acp"]
       description: MiniMax Code for implementation, refactoring, debugging, and repository tasks
       auto_approve_permissions: false
   ```

   `mcode` must be on the Gateway process's `PATH`; installing it only on the Docker host does not make it available inside the Gateway container. DeerFlow invokes it through `invoke_acp_agent` in a per-thread ACP workspace and forwards enabled MCP servers. Keep `auto_approve_permissions: false` for untrusted tasks; enable it only when mcode must edit files or run commands and you trust the task.
   - On macOS, export Claude Code auth explicitly if needed:

   ```bash
   eval "$(python3 scripts/export_claude_code_oauth.py --print-export)"
   ```

   The exporter rejects malformed credential containers and non-string or blank access tokens before printing a token, emitting a shell export, or writing a credentials file. Valid tokens are exported unchanged, and file exports preserve the full credential container.

   API keys can also be set manually in `.env` (recommended) or exported in your shell:

   ```bash
   OPENAI_API_KEY=your-openai-api-key
   TAVILY_API_KEY=your-tavily-api-key
   ```

   `make dev` and `make start` read `.env` as data, never as a shell script, so a
   value means what the Gateway reads: `$$`, backticks and `$(...)` stay as
   written, and an unquoted value may contain spaces. `$NAME`, `${NAME}`,
   `${NAME:-default}` and an unquoted leading `~` still expand, and
   single-quoted values stay literal.

   </details>

For an explicit backend dotenv file, export `DEER_FLOW_ENV_FILE` before startup,
alongside `DEER_FLOW_CONFIG_PATH` if needed. For example, from `backend/`:

```bash
DEER_FLOW_ENV_FILE=/srv/deer-flow/stage.env DEER_FLOW_CONFIG_PATH=/srv/deer-flow/stage.yaml make gateway
```

Relative dotenv paths use the backend process working directory; absolute paths
work regardless of that directory. Existing process variables win. An unset
selector preserves default dotenv discovery; a specified empty, missing,
non-file or unreadable path fails startup. Explicit selection also fails when
`PYTHON_DOTENV_DISABLED` disables dotenv loading. Restart after changing the file.
This selects backend dotenv input only: shell launchers, Docker Compose and the
frontend retain their own environment loading. Values they already export win.
It does not select `ENV` profiles or isolate databases, storage or tenants.
See [backend dotenv selection](../../backend/docs/CONFIGURATION.md#backend-dotenv-selection).

Custom blob storage backends accept `blob_storage.backend: module.Class` or
`module:Class`, including a single `.py` module importable by the Gateway.
The selected class must implement `BlobStore`; backend options go under
`blob_storage.backend_config`. See [blob storage](../../backend/docs/blob-storage.md).

Viewed-image artifact URLs can use shared blobs when the serving Gateway lacks
the local file. This fallback requires an existing thread record accessible to
the caller; deleting that record revokes access even if checkpoint cleanup fails.
When blob storage is disabled, a missing local file returns 404 without loading
checkpoint state. Shared-store failures also return 404 and emit a warning with
the exception type, without backend error details.

## Using Multiple Providers

LangSmith and Langfuse attach as LangChain callbacks, so you can enable both and DeerFlow reports each run to both. If an enabled provider is missing required credentials or fails to initialize, DeerFlow fails fast and names it. Monocle uses a global OpenTelemetry provider rather than a callback; Langfuse shares that provider, so all three can run together. Because both span processors sit on the same shared provider, Monocle's exporters also see Langfuse's spans when both are enabled.

For Docker deployments, tracing is disabled by default. Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in your `.env` to enable it.

## MindIE tool-call argument parsing

MindIE XML tool-call arguments support signed, fractional, and exponent JSON
numbers. If a number overflows, underflows to zero, or exceeds Python's integer
digit limit, the complete argument stays a string, including nested JSON lists
and objects, so parsing does not silently change its value. Python-literal sets
and tuples containing non-finite floats also retain the complete argument as
text, including when nested in other containers. Dictionary keys and values
are checked recursively as well.

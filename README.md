# 🦌 DeerFlow - 2.0

English | [中文](./README_zh.md) | [日本語](./README_ja.md) | [Français](./README_fr.md) | [Русский](./README_ru.md) | [Português](./README_pt.md)

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

<a href="https://trendshift.io/repositories/14699" target="_blank"><img src="https://trendshift.io/api/badge/repositories/14699" alt="bytedance%2Fdeer-flow | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
> On February 28th, 2026, DeerFlow claimed the 🏆 #1 spot on GitHub Trending following the launch of version 2. Thanks a million to our incredible community — you made this happen! 💪🔥

DeerFlow (**D**eep **E**xploration and **E**fficient **R**esearch **Flow**) is an open-source **super agent harness** that orchestrates **sub-agents**, **memory**, and **sandboxes** to do almost anything — powered by **extensible skills**.

https://github.com/user-attachments/assets/a8bcadc4-e040-4cf2-8fda-dd768b999c18

> [!NOTE]
> **DeerFlow 2.0 is a ground-up rewrite.** It shares no code with v1. If you're looking for the original Deep Research framework, it's maintained on the [`1.x` branch](https://github.com/bytedance/deer-flow/tree/main-1.x) — contributions there are still welcome. Active development has moved to 2.0.

## Official Website

Learn more and see **real demos** on our [**official website**](https://deerflow.tech).
The landing-page case studies open as allowlisted, read-only showcases without requiring a sign-in.

## Sister Projects

<img width="446" height="280" alt="image" align="middle" src="https://github.com/user-attachments/assets/077edef4-d560-41af-bb0d-d0a5f14fcc20" />

- [**LLM Space**](https://github.com/deer-flow/llm-space) - Meet our secret weapon behind DeerFlow — one desktop tool to prototype agent ideas, inspect each harness step, replay failures, and benchmark performance.

## Coding Plan from ByteDance Volcengine

- We strongly recommend using Doubao-Seed-2.0-Code, DeepSeek v3.2 and Kimi 2.5 to run DeerFlow
- [Learn more](https://www.byteplus.com/en/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)
- [中国大陆地区的开发者请点击这里](https://www.volcengine.com/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)

## InfoQuest

InfoQuest reader, web search, and image search use a 30-second HTTP connect/read
inactivity timeout. The crawl `timeout` and `navigation_timeout` settings remain
separate server-side options; they do not control the local HTTP timeout.

DeerFlow has newly integrated the intelligent search and crawling toolset independently developed by BytePlus — [InfoQuest (supports free online experience)](https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest)

<a href="https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest" target="_blank">
  <img
    src="https://sf16-sg.tiktokcdn.com/obj/eden-sg/hubseh7bsbps/20251208-160108.png"   alt="InfoQuest_banner"
  />
</a>

---

## Table of Contents

- [🦌 DeerFlow - 2.0](#-deerflow---20)
  - [Official Website](#official-website)
  - [Sister Projects](#sister-projects)
  - [Coding Plan from ByteDance Volcengine](#coding-plan-from-bytedance-volcengine)
  - [InfoQuest](#infoquest)
  - [Table of Contents](#table-of-contents)
  - [One-Line Agent Setup](#one-line-agent-setup)
  - [Quick Start](#quick-start)
    - [Configuration](#configuration)
    - [Running the Application](#running-the-application)
      - [Deployment Sizing](#deployment-sizing)
      - [Option 1: Docker (Recommended)](#option-1-docker-recommended)
      - [Upgrading an existing checkout](#upgrading-an-existing-checkout)
      - [Option 2: Local Development](#option-2-local-development)
      - [Startup Modes](#startup-modes)
      - [LangGraph Studio (Optional)](#langgraph-studio-optional)
      - [Docker Production Deployment](#docker-production-deployment)
    - [Advanced](#advanced)
      - [Sandbox Mode](#sandbox-mode)
      - [MCP Server](#mcp-server)
      - [IM Channels](#im-channels)
      - [Request Trace Correlation](#request-trace-correlation)
      - [LangSmith Tracing](#langsmith-tracing)
      - [Langfuse Tracing](#langfuse-tracing)
      - [Monocle Tracing](#monocle-tracing)
      - [Using Multiple Providers](#using-multiple-providers)
      - [Existing-Run Stream Actions](#existing-run-stream-actions)
      - [Personal Access Tokens](#personal-access-tokens)
  - [From Deep Research to Super Agent Harness](#from-deep-research-to-super-agent-harness)
  - [Core Features](#core-features)
    - [Skills \& Tools](#skills--tools)
      - [Exporting Custom Skills](#exporting-custom-skills)
      - [Claude Code Integration](#claude-code-integration)
    - [Private Knowledge Retrieval (RAGFlow)](#private-knowledge-retrieval-ragflow)
    - [Chat Archive](#chat-archive)
    - [Session Goals](#session-goals)
    - [Manual Context Compaction](#manual-context-compaction)
    - [Sub-Agents](#sub-agents)
    - [Sandbox \& File System](#sandbox--file-system)
    - [Agentic Browser Control](#agentic-browser-control)
    - [Context Engineering](#context-engineering)
    - [Reading a Referenced Conversation](#reading-a-referenced-conversation)
    - [Current Task Notes](#current-task-notes)
    - [Long-Term Memory](#long-term-memory)
  - [Recommended Models](#recommended-models)
  - [Embedded Python Client](#embedded-python-client)
  - [Projects](#projects)
    - [Project instructions](#project-instructions)
    - [Document shelf](#document-shelf)
    - [Archive read semantics](#archive-read-semantics)
    - [Trash](#trash)
  - [Scheduled Tasks](#scheduled-tasks)
    - [Preview cron occurrences through the API](#preview-cron-occurrences-through-the-api)
    - [Upgrade Notes](#upgrade-notes)
  - [Terminal Workbench (TUI)](#terminal-workbench-tui)
  - [Documentation](#documentation)
  - [⚠️ Security Notice](#️-security-notice)
    - [Improper Deployment May Introduce Security Risks](#improper-deployment-may-introduce-security-risks)
    - [Gateway Admin Is Equivalent to Code Execution](#gateway-admin-is-equivalent-to-code-execution)
    - [External Chat Message Roles](#external-chat-message-roles)
    - [Deployment Defaults](#deployment-defaults)
    - [Security Recommendations](#security-recommendations)
  - [Contributing](#contributing)
  - [License](#license)
  - [Acknowledgments](#acknowledgments)
    - [Key Contributors](#key-contributors)
  - [Star History](#star-history)

## One-Line Agent Setup

If you use Claude Code, Codex, Cursor, Windsurf, or another coding agent, you can hand it the setup instructions in one sentence:

```text
Help me clone DeerFlow if needed, then bootstrap it for local development by following https://raw.githubusercontent.com/bytedance/deer-flow/main/Install.md
```

That prompt is intended for coding agents. It tells the agent to clone the repo if needed, choose Docker when available, and stop with the exact next command plus any missing config the user still needs to provide.

## Quick Start

### Configuration

Operators can extend lead-agent, subagent, and DeerMem extraction prompts with
literal prepend/append configuration without editing source templates. See
[prompt overlays](backend/docs/CONFIGURATION.md#prompt-overlays).

Optional per-model [`request_admission`](backend/docs/CONFIGURATION.md#model-request-admission)
paces requests to help stay within provider request-per-minute limits.
It is disabled by default; see the linked guide to enable it.

For Google's official Gemini OpenAI-compatible endpoint, use the
[Gemini reasoning profile](backend/docs/CONFIGURATION.md#gemini-via-googles-openai-compatible-endpoint).

For MindIE XML tool calls, see the
[argument parsing and newline compatibility guide](backend/docs/CONFIGURATION.md#mindie-xml-tool-arguments).
Both synchronous and asynchronous streams retain this compatibility: tool-enabled
streams simulate chunks from a non-streaming response, while no-tool streams stay native.

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

   Jina, Browserless, and InfoQuest web fetches resolve relative links and image sources using the requested page URL (or a usable HTML base URL), so returned Markdown includes complete destinations. Link resolution preserves the surrounding HTML source, including malformed-page formatting.

   Jina fetches support opt-in bounded retries via `max_retries` (default `0`) and `retry_budget_seconds` (default `30`) in the tool configuration. Valid `Retry-After` hints set a minimum wait for HTTP 429/503; 429 without a valid hint stays terminal. Hints that cannot fit the remaining budget stop retries. Local backoff remains randomized. Retries may increase upstream requests and cost; see [Jina fetch retries](backend/docs/CONFIGURATION.md#jina-fetch-retries).

   Jina also accepts an opt-in `max_response_bytes` tool setting (positive integer; omitted/null disables it). It stops oversized decoded responses before extraction, with no partial success or retry. This leaves the 4096-character output cap unchanged and does not bound HTTPX decompressor allocations or wire bandwidth; see [response budget](backend/docs/CONFIGURATION.md#jina-response-byte-budget).

   Run `make doctor` at any time to verify your setup and get actionable fix hints.
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
   single-quoted references remain literal. For standalone Gateway launches using `backend/.env`
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

   > **Advanced / manual configuration**: If you prefer to edit `config.yaml` directly, run `make config` instead to copy the full template. Optional dependency auto-detection accepts UTF-8 configuration files with or without a byte-order mark (BOM). See `config.example.yaml` for the complete reference including CLI-backed providers (Codex CLI, Claude Code OAuth), OpenRouter, Responses API, subagent runtime caps such as `subagents.max_total_per_run`, and more.

   Optional per-model pricing must use one currency across all priced models.
   DeerFlow disables Console cost estimates when currencies are mixed rather
   than presenting an invalid aggregate.

   Administrators can also open **Settings → Models** to add, edit, test, and
   enable/disable shared OpenAI-compatible Chat Completions models without editing
   `config.yaml`. Enter a unique name, base URL, model ID, and optional API key;
   saving refreshes the chat model list. Connection testing sends a short streaming
   tool-call request and may incur provider charges. It does not save the draft or
   verify image support; set image support and token limits from provider documentation.
   Official DeepSeek models at `https://api.deepseek.com` or
   `https://api.deepseek.com/v1` (default HTTPS port) automatically use DeerFlow's
   DeepSeek adapter, preserving reasoning content across tool calls and honoring
   output token limits. Chat uses the selected thinking mode; the connection test
   temporarily disables thinking because DeepSeek rejects forced tool selection
   in thinking mode. The test checks streaming tool connectivity, not every agent
   workflow or thinking-mode behavior. Existing saved DeepSeek profiles receive
   this adapter without re-entering credentials. DeepSeek-specific settings for
   third-party proxies, other native adapters, and advanced reasoning settings
   remain YAML-configured.

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

   The `write_file` tool's output-budget hint uses the active model's effective `max_tokens`. Missing or unusable limits, including YAML `.inf`, `-.inf`, `.nan`, and values too large for the character estimate, omit this hint without failing tool assembly; provider-specific model validation still applies.

   To route OpenAI models through `/v1/responses`, keep using `langchain_openai:ChatOpenAI` and set `use_responses_api: true` with `output_version: responses/v1`.

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
   - Completed Codex responses still return their text and tool calls when token usage is null, omitted, or empty; usage metadata remains unavailable.
   - The Codex model provider returns completed responses without waiting for the SSE connection to close. Failed or incomplete responses report the provider's error or reason; partial output is not returned as a successful answer. Non-object error details are reported as text.
   - Claude Code accepts `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_CREDENTIALS_PATH`, or `~/.claude/.credentials.json`
   - `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` accepts a UTF-8 token handoff and reuses it for later model instances in the same process. Undecodable handoffs are skipped so Claude Code can still try its override or default credentials file.
   - CLI credential JSON files accept UTF-8 with or without a BOM, independently of the host locale. `make doctor` accepts the same files when checking CLI authentication. Invalid text encoding is treated as an unreadable source; Claude Code can still try its default file after an invalid override.
   - ACP agent entries are separate from model providers — if you configure `acp_agents.codex`, point it at a Codex ACP adapter such as `npx -y @zed-industries/codex-acp`
   - Each ACP agent's `timeout_seconds` (default: 1800) is one shared budget for initialization, session creation, and the prompt, starting after the subprocess launches. On timeout, DeerFlow aborts the invocation and closes the subprocess before returning an error. Workspace/MCP preparation and subprocess cleanup are outside this budget. A `TimeoutError` raised by the SDK before this deadline expires retains its own error message.
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
See [backend dotenv selection](backend/docs/CONFIGURATION.md#backend-dotenv-selection).

### Running the Application

#### Deployment Sizing

Use the table below as a practical starting point when choosing how to run DeerFlow:

| Deployment target | Starting point | Recommended | Notes |
|---------|-----------|------------|-------|
| Local evaluation / `make dev` | 4 vCPU, 8 GB RAM, 20 GB free SSD | 8 vCPU, 16 GB RAM | Good for one developer or one light session with hosted model APIs. `2 vCPU / 4 GB` is usually not enough. |
| Docker development / `make docker-start` | 4 vCPU, 8 GB RAM, 25 GB free SSD | 8 vCPU, 16 GB RAM | Image builds, bind mounts, and sandbox containers need more headroom than pure local dev. |
| Long-running server / `make up` | 8 vCPU, 16 GB RAM, 40 GB free SSD | 16 vCPU, 32 GB RAM | Preferred for shared use, multi-agent runs, report generation, or heavier sandbox workloads. |

- These numbers cover DeerFlow itself. If you also host a local LLM, size that service separately.
- Linux plus Docker is the recommended deployment target for a persistent server. macOS and Windows are best treated as development or evaluation environments.
- If CPU or memory usage stays pinned, reduce concurrent runs first, then move to the next sizing tier.

#### Option 1: Docker (Recommended)

Requires Docker Desktop / Docker Engine and **Docker Compose v2.24+**
(`docker compose version`). Older Compose clients cannot parse the optional
`env_file` syntax in `docker/docker-compose.yaml` and `docker/docker-compose-dev.yaml`.

**Development** (hot-reload, source mounts):

```bash
make docker-init    # Pull sandbox image (only once or when image updates)
make docker-start   # Start services (auto-detects sandbox mode from config.yaml)
make docker-logs    # View logs
```

`make docker-start` starts `provisioner` only when `config.yaml` uses provisioner mode (`sandbox.use: deerflow.community.aio_sandbox:AioSandboxProvider` with `provisioner_url`).

Docker builds use the upstream `uv` registry by default. If you need faster mirrors in restricted networks, export `UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` and `NPM_REGISTRY=https://registry.npmmirror.com` before running `make docker-init` or `make docker-start`.

Local AIO sandbox control traffic is always direct: loopback/private addresses,
single-label cluster hosts, and Docker/Podman internal hostnames do not inherit
`HTTP_PROXY` or `HTTPS_PROXY`. External sandbox FQDNs and public IPs still
honor environment proxy settings.

Backend processes automatically pick up `config.yaml` changes on the next config access, so model metadata updates do not require a manual restart during development.

Gateway runs use the top-level `recursion_limit` in `config.yaml` when an API
request does not provide one. The default is `100`; valid per-request values
take precedence, and `max_recursion_limit` (default `1000`) caps both. Changes
apply to the next run without restarting the Gateway. This top-level setting
applies to Gateway API runs; IM channel and embedded `DeerFlowClient` runs
retain their own defaults and per-call override paths.
The checkpoint storage settings `database.checkpoint_channel_mode` and
`database.checkpoint_delta.snapshot_frequency` (default `10`) are exceptions:
both are frozen when the process first builds an agent (including through
`DeerFlowClient`) and require a process restart to change safely.

The optional `database.checkpoint_cache` section (delta channel mode only)
caches materialized checkpoint histories: `type` is `memory` (default) or
`redis`, and `max_entries: 0` disables the cache. The `redis` backend is
Gateway/async-only; the sync TUI/embedded path supports `memory` only. The
cache is performance-only — results are identical with it disabled — so it is
never frozen and workers sharing one checkpoint database may safely run
different cache settings.

> [!TIP]
> On Linux, if Docker-based commands fail with `permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock`, add your user to the `docker` group and re-login before retrying. See [CONTRIBUTING.md](CONTRIBUTING.md#linux-docker-daemon-permission-denied) for the full fix.

**Production** (builds images locally, mounts runtime config and data):

```bash
make up     # Build images and start all production services
make down   # Stop and remove containers
```

Access: http://localhost:2026

`make up` waits for the Gateway `/health` endpoint before reporting success.
If the Gateway does not become healthy within the startup window, deployment
exits non-zero and prints the container status plus recent Gateway logs. The
production image starts from its already-built environment and never resolves
or installs Python dependencies at container startup.

If `make up` reports an unwritable runtime home or an unreadable persisted secret
after `make docker-start`, run the printed `sudo chown -R <uid>:<gid> '<home>'`
recovery command and retry. The check honors secret overrides from the shell or
`.env`, accepts readable read-only secret files, and leaves `make down` available
without reading or generating secrets.

For persistent deployments, configure `database.backend` as `sqlite` or
`postgres`. The selected backend is shared by the LangGraph checkpointer,
LangGraph Store, and DeerFlow application data. The deprecated `checkpointer`
section, when present, overrides the first two for backward compatibility.

Gateway startup automatically repairs the missing run-change schema affecting
some existing databases (#5516). The repair preserves run history and existing
change positions; downgrading the repair to its predecessor also retains the
schema and positions required by that version.

For lightweight single-process event persistence, `run_events.backend: jsonl`
keeps Unicode message content intact, including line and paragraph separators.
Existing valid JSONL records remain readable without rewriting the files.

For per-call usage audits, an immediate LLM response replay with populated usage
updates both nested usage and top-level token counters, even if initial usage was absent or zero.
The original request, model, and status metadata stay intact; flushed events are
not rewritten. See the [run event contract](contracts/run_event_stream_contract.json).

The unified nginx endpoint is same-origin by default and does not emit browser CORS headers. If you run a split-origin or port-forwarded browser client, set `GATEWAY_CORS_ORIGINS` to comma-separated exact origins such as `http://localhost:3000`; the Gateway then applies the CORS allowlist and matching CSRF origin checks.

When fine-grained authorization is enabled, Live Browser connections require `threads:write` as well as ownership of the thread, even when only viewing frames: the same connection can control the browser. Permission checks run when connecting. Restart Gateway after upgrading to disconnect sessions admitted by older code.

Browser login uses `HttpOnly` session cookies. The login page offers a "keep me signed in" option that extends the browser session when the request is HTTPS (including trusted `X-Forwarded-Proto: https`) or localhost HTTP. The localhost exception uses the direct request `Host` and ignores forwarded host headers. Public HTTP deployments, including many temporary sandbox URLs, fall back to session cookies by default. DeerFlow never stores the password in browser storage; the UI may remember only the email address.

DeerFlow still uses `Forwarded` / `X-Forwarded-*` headers to recover the browser-facing scheme and origin behind a proxy. The bundled nginx sets `X-Forwarded-Proto`, but preserves an upstream HTTPS value and does not overwrite every forwarded header. Configure the outer trusted proxy to replace or strip client-supplied forwarding headers before traffic reaches DeerFlow.

> [!IMPORTANT]
> The Gateway still owns active run tasks in process, so production defaults to a single Gateway worker (`GATEWAY_WORKERS=1`). Multi-worker deployments require Postgres, the Redis stream bridge (`stream_bridge.type: redis`), `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`; process-local memory/JSONL event stores cannot enforce singleton delivery receipts across workers. Kubernetes replicas run one worker per Pod, which the worker count cannot see: declare them with `deployment.multi_instance: true` (or `DEER_FLOW_MULTI_INSTANCE=1`, which deploy tooling such as a Helm chart can set from its replica count) so the startup gate enforces the same prerequisites instead of staying inert. The bridge shares SSE delivery and bounded `Last-Event-ID` replay across workers. When a valid reconnect cursor has been trimmed, or a subscriber that already established an empty-stream wait falls behind before its first delivery, Memory and Redis emit a machine-readable SSE `gap` event instead of silently returning a partial replay; the Web UI reloads durable thread/event state and resumes from the retained tail. Lease reconciliation marks runs from dead workers as errors, persists their delivery receipts, publishes the terminal stream marker, schedules retained-stream cleanup, and updates the affected thread status. SSE, `/wait`, and internal stream consumers use `stream_bridge.heartbeat_interval_seconds` (default `15`) for idle liveness checks; changing it requires a Gateway restart. Malformed Redis reconnect IDs live-tail new events instead of replaying the retained buffer, and the rolling retained-buffer TTL (`stream_ttl_seconds`) remains a cleanup safety net rather than a run timeout. Failed-login counters and lockouts for `POST /api/v1/auth/login/local` (`auth.local.max_login_attempts` / `lockout_seconds`) are kept in the shared `login_throttle` table whenever the application database is SQLite or Postgres (`auth.local.throttle_storage: auto`, the default), so every replica enforces one lockout per client IP; `memory` keeps the historical per-process counter, which under N replicas hands an attacker N × `max_login_attempts` guesses and logs a startup warning. IM channel state and other process-local services still need their own multi-worker coordination.
>
> In single-process JSONL deployments, cancelling an admitted event-store mutation waits for its background file I/O, rollback, and bookkeeping to settle before releasing the thread write lock. This prevents an older cancelled write from recreating deleted records or rolling back a later successful write. Cancellation can therefore wait on slow storage; it does not stop an in-flight filesystem operation. Callers still waiting to acquire the lock can cancel without starting a mutation. A batch spanning multiple threads drains its current thread group before propagating cancellation; subsequent thread groups do not start.
>
> After a run publishes its terminal stream marker, its process-local `RunRecord` remains available for the existing five-minute grace period before cleanup; durable run history remains available through `RunStore`, while the stream bridge retains its delivery tail on its separate cleanup schedule.
>
> Run cancellation may land on any Gateway worker. A non-owning worker now persists the interrupt or rollback request for the live owner, which observes it during lease renewal and performs the normal cancellation flow; load-balancer routing alone no longer produces a 409. The first accepted action wins even if a retry lands on the owner, and accepted cancellation competes atomically with owner completion. Dead owners still follow lease takeover and orphan recovery. Cancellation latency is therefore bounded by the lease heartbeat interval.

> Cancelling a model recovery probe, including while it is queued or waiting to retry, lets the next call check whether the provider has recovered. Cancellation does not count as a provider failure or release another call's active recovery probe.
>
> Model retries honor valid provider `Retry-After` hints up to 24 hours, including waits longer than the local backoff cap. Malformed, non-finite, or over-limit hints use normal backoff instead. This applies to numeric/date hints in LLM error handling and integer-second hints in Claude's retry path.
>
> With lease heartbeat enabled, a transient RunStore renewal error is retried only until the last confirmed lease expires; the stale worker then cancels local execution and suppresses checkpoint, completion-hook, delivery-receipt, and thread-status finalization. A remote tool side effect already in flight may still be outside local cancellation.
>
> Reconciliation uses an atomic takeover claim that re-checks the lease after candidate selection, so a successful owner renewal wins over orphan recovery and only one reconciler can report a run as recovered. When multiple Gateway workers share the Docker/AIO or E2B sandbox backend, also configure `sandbox.ownership.type: redis`; E2B uses the leases during background startup and periodic reconciliation so duplicate/orphan cleanup cannot terminate a live peer's sandbox.

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed Docker development guide.

#### Upgrading an existing checkout

Keep `config.yaml`, `.env`, and `extensions_config.json`. Stop the services you
currently use, run `git pull --ff-only`, then start the same mode again. Do not run
`make config` or `make docker-init` again for a routine source upgrade. If the new
version requires configuration changes, run `make config-upgrade` before restarting.
See [Operations and Troubleshooting](frontend/src/content/en/application/operations-and-troubleshooting.mdx#upgrading-an-existing-checkout)
for the commands for each mode.

#### Option 2: Local Development

If you prefer running services locally:

Prerequisite: complete the "Configuration" steps above first (`make setup`). `make dev` requires a valid `config.yaml` in the project root. Set `DEER_FLOW_PROJECT_ROOT` to define that root explicitly, or `DEER_FLOW_CONFIG_PATH` to point at a specific config file. Runtime state defaults to `.deer-flow` under the project root and can be moved with `DEER_FLOW_HOME`; skills default to `skills/` under the project root and can be moved with `DEER_FLOW_SKILLS_PATH`. Run `make doctor` to verify your setup before starting.

Configuration checks and agent-storage migrations use the installed backend environment through `uv run --no-sync --project backend` from the repository root. This preserves relative runtime paths and installed optional dependencies; see the [setup checks](backend/docs/SETUP.md#steps) and [agent-storage migration](backend/docs/CONFIGURATION.md#agent-storage).

On Windows, run the local development flow from Git Bash. Native `cmd.exe` and PowerShell shells are not supported for the bash-based service scripts, and WSL is not guaranteed because some scripts rely on Git for Windows utilities such as `cygpath`.

The documented root `make` commands invoke repository `.sh` files through Bash
explicitly. They therefore continue to work from source archives or filesystems
that do not preserve POSIX executable bits. When calling a script directly from
such a checkout, use `bash ./scripts/<name>.sh ...`.

1. **Check prerequisites**:
   ```bash
   make check  # Verifies Node.js 22+, pnpm, uv, nginx
   ```

   The local `make check`, `make install`, `make dev`, and `make start` entry points use a direct `pnpm` executable when available and otherwise fall back to `corepack pnpm`. With native Windows Python, the shared runner checks `pnpm.cmd` before the generic `pnpm` lookup, which follows `PATH`/`PATHEXT` and may select an `.exe` or `.bat` in the same or an earlier PATH directory. The Corepack fallback likewise checks `corepack.cmd` before `corepack`. POSIX Python keeps the generic names first, including when running under MSYS/Cygwin. The runner and diagnostics resolve repository paths absolutely, so these checks work regardless of the caller's current directory. Corepack runs from `frontend/`, so it honors the `packageManager` version pinned in `frontend/package.json`; enabling a global pnpm shim is not required.

   `make check` decodes tool diagnostics as UTF-8 and preserves Unicode pnpm
   errors on non-UTF-8 hosts. Invalid output bytes are replaced so the checker
   can report dependency failures instead of aborting while decoding output.

2. **Install dependencies**:
   ```bash
   make install  # Install backend + frontend dependencies + pre-commit hooks
   ```

   Hook setup calls pre-commit through uv, so uv's tool directory need not be on `PATH`.

3. **(Optional) Pre-pull sandbox image**:
   ```bash
   # Recommended if using Docker/Container-based sandbox
   make setup-sandbox
   ```
   Reads the configured sandbox image from UTF-8 `config.yaml`, with or without a leading BOM, using LF or CRLF line endings.
   On macOS, a successful Apple Container pull completes this step even when Docker is not installed. If Docker is available, its image is also pulled.

4. **Start services**:
   ```bash
   make dev
   ```

5. **Access**: http://localhost:2026

6. **(Optional) Load sample memory data for local review**: open `Settings > Memory`, click **Import memory**, and select `backend/docs/memory-settings-sample.json`. The browser imports into the signed-in user's memory.

   To replace memory for every registered user in a disposable review environment:

   ```bash
   cd backend
   uv run python ../scripts/load_memory_sample.py --all-users
   ```

   Bulk mode supports SQLite/PostgreSQL user registries, creates timestamped backups under `.deer-flow/memory-sample-backups/`, and rejects the non-persistent `database.backend: memory` mode. See [backend/docs/MEMORY_SETTINGS_REVIEW.md](backend/docs/MEMORY_SETTINGS_REVIEW.md) for the complete review flow.

Local services always use their internal ports (`8001`, `3000`, and `2026`).
The root `.env` variable `PORT` configures only the published Docker ingress;
it does not change the Next.js port used by `make dev`.

#### Startup Modes

DeerFlow runs the agent runtime inside the Gateway API. Development mode enables hot-reload; production mode uses a pre-built frontend.

| | **Local Foreground** | **Local Daemon** | **Docker Dev** | **Docker Prod** |
|---|---|---|---|---|
| **Dev** | `./scripts/serve.sh --dev`<br/>`make dev` | `./scripts/serve.sh --dev --daemon`<br/>`make dev-daemon` | `./scripts/docker.sh start`<br/>`make docker-start` | — |
| **Prod** | `./scripts/serve.sh --prod`<br/>`make start` | `./scripts/serve.sh --prod --daemon`<br/>`make start-daemon` | — | `./scripts/deploy.sh`<br/>`make up` |

| Action | Local | Docker Dev | Docker Prod |
|---|---|---|---|
| **Stop** | `./scripts/serve.sh --stop`<br/>`make stop` | `./scripts/docker.sh stop`<br/>`make docker-stop` | `./scripts/deploy.sh down`<br/>`make down` |
| **Restart** | `./scripts/serve.sh --restart [flags]` | `./scripts/docker.sh restart` | — |

`make start` and `make start-daemon` rebuild the frontend with `next build` on
every run. To reuse the last build instead, pass `SKIP_FRONTEND_BUILD=1` (or add
`--skip-frontend-build` when calling `./scripts/serve.sh --prod` directly). This
is opt-in: it fails fast when `frontend/.next` has no completed build.

Gateway owns `/api/langgraph/*` and translates those public LangGraph-compatible paths to its native `/api/*` routers behind nginx.

Cold agent imports during run creation use a dedicated worker pool, keeping
unrelated Gateway requests responsive while the agent stack loads. A failed
factory import prevents the run from being admitted.

For a read-only demo without the Gateway, run `make build-static` from `frontend/`,
then `HOSTNAME=127.0.0.1 PORT=3000 node --env-file=.env .next/standalone/server.js`
from the same directory. The build includes public demo assets and resolves
supported demo API reads locally; writes are unavailable. To display the homepage
GitHub star count, set `GITHUB_OAUTH_TOKEN` in `frontend/.env` before starting Node.
The token stays on the server; missing credentials or GitHub failures hide the
count. Restart Node after changing the token; no rebuild is needed.

#### LangGraph Studio (Optional)

The default `make dev` topology uses DeerFlow's Gateway-embedded runtime and
does not require LangGraph Studio. To inspect and test the registered lead-agent
graph with the standalone development server, run the command from `backend/`
so the CLI discovers `langgraph.json`:

```bash
cd backend
uv run langgraph dev --allow-blocking
```

The command prints the local API and Studio UI URLs. This in-memory server is
for development and testing only. The flag permits DeerFlow's synchronous
configuration and graph-factory setup during local Studio requests; it must not
be treated as a production-server setting. Local Studio authentication is
handled automatically, so the connection does not require custom headers. Use
DeerFlow's documented production startup modes or a supported LangSmith
deployment for production workloads. Assistant ownership and provenance in this
standalone mode are server-owned: Studio can discover registered graphs and the
assistants it creates, and normal assistant-version selection remains available.
Before the locked local runtime loads its persisted development store, DeerFlow
repairs legacy assistant rows and version history so historical client metadata
cannot restore server privileges or be discarded by the runtime's startup
cleanup. Keep the backend dependencies synchronized with `uv sync`; this
compatibility path requires the declared LangGraph runtime versions and logs a
warning if the persisted-store contract no longer matches its expectations.
The documented command uses LangGraph's file-based custom-app loader, which is
also covered directly by DeerFlow's regression tests.

Standalone runs using `if_not_exists="create"` retain config and run metadata
on the newly created thread, including searchable tags; run metadata takes
precedence for duplicate keys. Thread ownership and MCP incarnation remain
server-owned, and later runs do not replace the thread's creation metadata.

For workflows that invoke `backend/langgraph.json` through LangGraph Studio or
a direct LangGraph Server, DeerFlow consumes the authenticated identity
published by that runtime and uses it for custom-agent configuration/SOUL, user
skills and skill policy, uploads, thread data, and memory reads/writes. This
keeps authenticated runs out of the shared `default` filesystem bucket, and the
server-owned identity takes precedence over ordinary client-supplied `user_id`
values. External identities such as email addresses are mapped to stable,
collision-resistant directory-safe user IDs before accessing DeerFlow storage.
The default DeerFlow service topology remains the Gateway-embedded runtime
described above.

Gateway runs automatically enforce native delivery for artifacts created or modified under `/mnt/user-data/outputs`: `present_files` must present at least one output produced by the current run, and the terminal `run.delivery` receipt must be durably recorded. Virtual artifact paths are resolved within the same authenticated user and thread scope that produced the output before the output-directory boundary is validated. Runs that do not produce output artifacts keep ordinary conversational behavior.

Thread-scoped `runs.wait()` calls that finish with `status: error` report the current run error instead of an earlier answer. The asynchronous Python LangGraph SDK raises by default; pass `raise_error=False` to inspect the returned status and error.

DeerFlow's built-in custom events are available through both LangGraph streaming interfaces: native clients can continue subscribing to `stream_mode="custom"`, while callback-based integrations can consume the same payloads as `on_custom_event` records from `astream_events(version="v2")`. The callback event name matches the payload's `type` field.

#### Docker Production Deployment

`./scripts/deploy.sh` supports building and starting separately:

```bash
# One-step (build + start)
./scripts/deploy.sh

# Two-step (build once, start later)
./scripts/deploy.sh build       # build all images
./scripts/deploy.sh start       # start pre-built images

# Stop
./scripts/deploy.sh down
```

### Advanced
#### Sandbox Mode

DeerFlow supports multiple sandbox execution modes:
- **Local Execution** (runs sandbox code directly on the host machine)
- **Docker Execution** (runs sandbox code in isolated Docker containers)
- **Docker Execution with Kubernetes** (runs sandbox code in Kubernetes pods via provisioner service)

Sandbox references in conversation state are server-owned. External run and
thread-state APIs reject caller-supplied `sandbox` values; when restoring a
checkpoint, the runtime resolves the reference against the authenticated user
and thread before a tool can reuse it. A missing runtime thread ID raises an
error even when the referenced sandbox is cached.

When host Bash is enabled for Local Execution, DeerFlow starts OS detection with `uname -s`, then uses `sw_vers` on Darwin. On Linux, it reads host system files such as `/etc/os-release` only when the active sandbox policy permits it. Host filesystem path checks still apply; after a blocked path, the agent is directed to use a permitted command-only probe or virtual path instead of repeating the rejected command.

For Docker development, service startup follows `config.yaml` sandbox mode. In Local/Docker modes, `provisioner` is not started.

Local AIO sandbox port allocation stops at TCP port 65535. If the remaining
ports from the configured starting port are occupied, allocation reports
that no port is available instead of attempting an out-of-range bind.

See the [Sandbox Configuration Guide](backend/docs/CONFIGURATION.md#sandbox) to configure your preferred mode.

Remote directory listings report traversal failures (for example, unreadable
directories) as incomplete results, even when no entries were returned. A
missing start path is reported separately as “Directory not found.”

The optional [Tenki cloud sandbox provider](backend/packages/harness/deerflow/community/tenki/README.md)
uses Tenki SDK 1.4.0 or newer. Timed-out commands preserve partial output and
report `Exit Code: 124`; unsuccessful health checks cannot reclaim a warm sandbox.
Health probes tolerate login-shell output around the `ok` line, and failures log
the sandbox ID and probe output before replacing the sandbox.

BoxLite shutdown rejects late VM registration and keeps its SDK loop open while
in-flight acquisitions finish. If they cannot drain within five seconds,
shutdown fails with resources still owned and can be retried.

#### MCP Server

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

Tool-produced paths and URLs can be retained as short artifact handles across context compaction (`tool_artifacts` in `config.yaml`). Handles distinguish separate tool-result occurrences, even when a provider reuses call IDs. Detected file URLs preserve their query strings and fragments. When PII redaction is enabled, model-visible artifact labels follow that policy; internal references stay intact for tool argument resolution. The configured registry limit retains the newest artifacts, while checkpointed processing identities prevent evicted results from being recaptured after restart. Resolution runs before authorization and write-safety checks; unknown or expired handles return an error without executing the tool. Small unknown structured results may be retained as complete JSON up to 4096 UTF-8 bytes; empty or oversized payloads are skipped. Handles are agent-local: task arguments resolve parent handles to concrete references, and delegated reports must return concrete references rather than child-local handles. A truncated model projection reports how many handles are omitted.

DeerFlow supports configurable MCP servers and skills to extend its capabilities.
When durable MCP background tasks are enabled, agents can use `list_background_tasks(status="failed")` or `status="input_required"` to find failed tasks or tasks awaiting input in the current chat. Other supported statuses are `submitted`, `working`, `completed`, and `cancelled`; omitting the status preserves existing behavior. The database applies the filter before limiting results to the 20 most recent matching tasks. When combined with `active_only=true`, both filters apply: active statuses are `submitted`, `working`, and `input_required`, so terminal statuses return an empty list.
For HTTP/SSE MCP servers, OAuth token flows are supported (`client_credentials`, `refresh_token`).
Missing, malformed, or out-of-range token response `expires_in` values use a one-hour default lifetime. This includes lifetimes that cannot be added to the current time without overflowing the expiry timestamp.
Durable HTTP/SSE task status and cancellation calls select configured `user_auth` credentials using the persisted task owner, including after restart; per-request secrets are not retained for background calls. If a request-scoped credential overrides submit authentication, both credentials must authorize access to the same remote task.
For stdio MCP servers, per-tool call timeouts can be configured with `tool_call_timeout`; durable background-task calls honor the same setting for HTTP/SSE servers as well.
For stdio file outputs, a bare filename is linked to a uniquely matching file created or changed by that call. Filenames embedded in unrelated paths, including Windows backslash paths, are left intact.
For HTTP/SSE background-task calls, `session_init_timeout` separately bounds connection setup (including the SSE endpoint event) and MCP initialization together; it stops applying once the tool call begins. Initialization deadline errors identify the server and configured time limit.
Ordinary `task` subagents retain the parent run's captured thread incarnation for MCP calls, including legacy threads, so delegation preserves the same lifecycle scope.
MCP tool names are prefixed with `<server_name>_` by default to prevent collisions across servers. If a server already namespaces its own tools, set `tool_name_prefix: false` on that server in `extensions_config.json` to keep the original names. Disable the prefix only when the resulting names remain unique across all enabled servers.
Signed-in users' notification toggle, default model, conversation mode, and reasoning effort are saved to their account and restored on other browsers or after clearing browser storage. Browser notification permission still needs to be granted on each device. Changes retry after network failures; unsent changes survive a reload in the same tab. Concurrent edits to different fields are preserved; for the same field, the last server write wins. Existing unscoped browser preferences are not uploaded automatically because they have no account owner; reselect those settings once after upgrading. Static demos and auth-disabled development keep browser-local settings. Thread-specific model overrides and other display preferences remain local.

In a new chat, the submitted question stays above its streamed reasoning and
tool steps while the server creates the conversation and confirms the message.

Capability Center groups plugins by office collaboration, documents and knowledge, search and research, business and data, and development and operations. The directory includes setup references alongside existing MCP configurations and Lark. Recommended integrations and built-in support do not imply an installed or verified connection; the Installed filter shows configured MCP entries and installed Lark only.

Personal MCP connections configured in the web interface are persisted per user.
Deployment tools remain shared. Administrators can add, edit, enable, disable and delete shared MCP servers under **Platform provided**; ordinary users see their status without controls. Personal plugin switches affect only the signed-in user's connections. See [connection ownership](docs/capability-center.md#personal-and-deployment-mcp-configuration).

For plugin manifests, adapter registration, and Agent capability selection, see
[Capability Center integration contract](docs/capability-center.md).

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

`extensions_config.json` accepts UTF-8 with or without a leading byte-order mark (BOM), including files saved as UTF-8 with BOM by an editor.
MCP routing hints can also prefer a specific MCP tool for matching requests without forbidding other tools. When `tool_search` defers MCP schemas, matching routing metadata can auto-promote up to `tool_search.auto_promote_top_k` deferred schemas before the model call.

OpenViking users can register the official Streamable HTTP endpoint at `/mcp`
with an owner-bound USER API key. The native `forget` tool is exposed for
capability parity; deletion is irreversible, so it should be called only after
explicit user confirmation. DeerFlow does not enforce that confirmation. This
explicit, model-selected MCP tool path can run alongside the separate automatic
OpenViking memory backend; it does not replace automatic turn capture or recall. See the
[OpenViking MCP tools configuration](backend/docs/MCP_SERVER.md#openviking-mcp-tools).

The Gateway can adapt an MCP server's ordinary `submit` / `status` / `cancel` tools into durable background tasks. The Agent sees only the configured submit tool and a DeerFlow-local task ID; remote IDs are persisted before the submit call returns, while status and cancel stay internal to the runtime. Polling uses cross-worker leases, exponential retry backoff, scoped MCP sessions, bounded result storage, and restart recovery. A status-tool `isError` is retained as a bounded diagnostic and retried; servers report a permanent remote-task outcome through a normal structured result with `status: "failed"`. Remote poll hints are finite positive numbers capped at 24 hours, artifact-reference JSON is limited to 64 KiB, and task/server identifiers are validated against their durable SQL column limits before persistence. Input-required and terminal updates wake the current chat through idempotent Agent runs, while `list_background_tasks` and `cancel_background_task` let the Agent manage tasks without asking users for remote handles. Current-thread tasks are available through `GET /api/threads/{thread_id}/mcp-tasks`, its detail endpoint, and `POST /api/threads/{thread_id}/mcp-tasks/{task_id}/cancel`; when the task runtime actually starts, the Web UI exposes the same safe local view from the chat header with live status refresh, cancellation, and on-demand result, artifact, input-request, status-error, and cancellation-retry details. Default-disabled and memory-backend deployments hide that UI and do not poll the task endpoints. A failed remote cancellation remains queued with backoff, and its latest bounded error and attempt count stay visible in the expanded task card. Enable `mcp_tasks` in `config.yaml`, configure `task_toolsets` with exact raw tool names in `extensions_config.json`, and use a SQL database backend (`sqlite` or `postgres`). Task-enabled server connection, authentication, interceptor, timeout, or binding changes require a Gateway restart so Agent tool discovery and background calls cannot use different configuration versions. `input_required` is notification-only for now: DeerFlow can display the request but cannot yet submit the user's answer back to the remote task.

For deployment-level HTTP/SSE servers with `task_toolsets`, discovery, ordinary
tools, and background task calls share OAuth token state within one Gateway
process, including across tool-cache resets. Rotated refresh tokens stay in
memory; they are not written back to configuration or shared across processes.
After a restart, the configured refresh token must still be valid.

Notification launch and failed Agent-run deliveries use capped exponential backoff with a visible attempt count and stop after five failed attempts. When a bounded ordinary release exceeds its drain deadline, the service retains ownership until it settles. A permanently rejected target such as a deleted chat is dead-lettered immediately instead of retried forever or recreated. Cancellation endpoints return after durably recording the request; the background service owns the potentially slow remote MCP call and its retry schedule.

Notification runs keep their trusted delivery instruction separate from the framed, untrusted remote event payload. The process-started task runtime—not a hot config read—controls whether the task-management tools are exposed, so changing `mcp_tasks` requires a Gateway restart. When a skill's `allowed-tools` policy is active, `list_background_tasks` and `cancel_background_task` must be declared explicitly like other business tools.
See the [MCP Server Guide](backend/docs/MCP_SERVER.md) for detailed instructions.

Security: pass per-request MCP credentials only through `config.context.secrets`;
credentials must never be placed in either run metadata surface
(`metadata.auth_token` or `config.metadata.auth_token`). See [MCP credential migration and cleanup](backend/docs/MCP_SERVER.md#migrating-legacy-mcp-credentials)
for the supported interceptor flow and the required rotation and retained-copy
cleanup when migrating from legacy metadata credentials.

#### IM Channels

DeerFlow supports receiving tasks from messaging apps. Channels auto-start when configured — no public IP required for any of them.

Cancelling a channel restart discards its pending configuration reload, preserving newer runtime settings applied afterward.

DeerFlow can also expose user-owned IM channel connections in the workspace UI. When `channel_connections` is enabled, logged-in users can bind Telegram, Slack, Discord, Feishu/Lark, DingTalk, WeChat, WeCom, QQ, or Buzz from the sidebar / Settings > Channels. It reuses the existing outbound `channels.*` transports, so no public IP or provider callback URL is required. Incoming IM messages then run under the connected DeerFlow user account. See [IM Channel Connections](backend/docs/IM_CHANNEL_CONNECTIONS.md) for setup and security notes.

| Channel | Transport | Difficulty |
|---------|-----------|------------|
| Telegram | Bot API (long-polling) | Easy |
| Slack | Socket Mode | Moderate |
| Feishu / Lark | WebSocket | Moderate |
| WeChat | Tencent iLink (long-polling) | Moderate |
| WeCom | WebSocket | Moderate |
| QQ | WebSocket (text-only C2C and group @mentions; four/five passive replies per source) | Moderate |
| DingTalk | Stream Push (WebSocket) | Moderate |
| Buzz | Nostr relay (WebSocket, NIP-42) | Moderate |

**Configuration in `config.yaml`:**

Discord's `channels.discord.allowed_guilds` accepts one positive numeric guild
ID (quoted or unquoted) or a YAML list. Unset, `null`, `[]`, or a blank string
allows all guilds. Invalid entries are ignored with a warning; any other
configured value yielding no valid ID denies every guild and logs an error.
`allowed_channels` accepts one channel ID (quoted or unquoted) or a YAML list
of IDs exempt from `mention_only`, within allowed guilds. An empty value gives
no exemptions, so `mention_only` applies everywhere when enabled.

```yaml
channels:
  # LangGraph-compatible Gateway API base URL (default: http://localhost:8001/api)
  langgraph_url: http://localhost:8001/api
  # Gateway API URL (default: http://localhost:8001)
  gateway_url: http://localhost:8001

  # Maximum queued or provider-reserved inbound messages (default: 1000)
  inbound_queue_maxsize: 1000
  # Fixed number of long-lived inbound handler workers (default: 5)
  max_concurrency: 5
  # Seconds to drain accepted work before cancelling active handlers (default: 3)
  shutdown_grace_period_seconds: 3

  # Optional: global session defaults for all mobile channels
  session:
    assistant_id: lead_agent  # or a custom agent name; custom agents are routed via lead_agent + agent_name
    config:
      recursion_limit: 100
    context:
      thinking_enabled: true
      is_plan_mode: false
      subagent_enabled: false

  feishu:
    enabled: true
    app_id: $FEISHU_APP_ID
    app_secret: $FEISHU_APP_SECRET
    # domain: https://open.feishu.cn       # China (default)
    # domain: https://open.larksuite.com   # International

  qq:
    enabled: true
    app_id: $QQ_APP_ID
    client_secret: $QQ_CLIENT_SECRET
    allowed_users: []  # QQ OpenIDs, not QQ account numbers

  wecom:
    enabled: true
    bot_id: $WECOM_BOT_ID
    bot_secret: $WECOM_BOT_SECRET
    # Optional: extra host suffixes inbound media downloads may come from, in
    # addition to the built-in qq.com family and WeCom's official COS media
    # host (ww-aibot-img-1258476243.<region>.myqcloud.com); add one here if
    # WeCom rotates to a new COS account or media goes through a proxy
    allowed_media_hosts: []

  slack:
    enabled: true
    bot_token: $SLACK_BOT_TOKEN     # xoxb-...
    app_token: $SLACK_APP_TOKEN     # xapp-... (Socket Mode)
    allowed_users: []               # empty = allow all

  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
    # Optional: render final Markdown replies as Telegram Rich Messages.
    rich_messages: false
    allowed_users: []               # numeric user IDs, not @usernames; empty = allow all

  wechat:
    enabled: false
    bot_token: $WECHAT_BOT_TOKEN
    ilink_bot_id: $WECHAT_ILINK_BOT_ID
    qrcode_login_enabled: true      # optional: allow first-time QR bootstrap when bot_token is absent
    allowed_users: []               # iLink user IDs; empty allows all; one ID is one entry
    polling_timeout: 35             # timing values must be positive finite seconds
    polling_retry_delay: 5
    qrcode_poll_interval: 2
    qrcode_poll_timeout: 180
    state_dir: ./.deer-flow/wechat/state
    max_inbound_image_bytes: 20971520
    max_outbound_image_bytes: 20971520
    max_inbound_file_bytes: 52428800
    max_outbound_file_bytes: 52428800
    # Inbound media downloads stream with the caps above and are restricted to
    # these host suffixes (plus *.qq.com and the cdn_base_url host by default)
    allowed_media_hosts: []

    # Optional: per-channel / per-user session settings
    session:
      assistant_id: mobile-agent  # custom agent names are also supported here
      context:
        thinking_enabled: false
      users:
        "123456789":
          assistant_id: vip-agent
          config:
            recursion_limit: 150
          context:
            thinking_enabled: true
            subagent_enabled: true

  dingtalk:
    enabled: true
    client_id: $DINGTALK_CLIENT_ID             # Client ID of your DingTalk application
    client_secret: $DINGTALK_CLIENT_SECRET     # Client Secret of your DingTalk application
    allowed_users: []                          # empty = allow all
    card_template_id: ""                       # Optional: AI Card template ID for streaming typewriter effect
```

Notes:
- `assistant_id: lead_agent` calls the default LangGraph assistant directly.
- If `assistant_id` is set to a custom agent name, DeerFlow still routes through `lead_agent` and injects that value as `agent_name`, so the custom agent's SOUL/config takes effect for IM channels.
- IM channel workers call Gateway's LangGraph-compatible API internally and automatically attach process-local internal auth plus the CSRF cookie/header pair required for thread and run creation.
- Inbound work is bounded to `inbound_queue_maxsize` pending messages plus `max_concurrency` active workers. When capacity is exhausted, socket/polling providers drop new messages before sending DeerFlow's working acknowledgment and emit a rate-limited warning. Buzz leaves its replay cursor unchanged and reconnects for relay replay; GitHub webhooks return `503`, marking the delivery failed for manual/API redelivery. Shutdown closes admission immediately, keeps channel transports available while accepted messages drain for up to `shutdown_grace_period_seconds`, then cancels and awaits active handlers before closing provider resources; the Gateway's outer timeout can cancel an incomplete shutdown without detaching those resources.
- Feishu/Lark now queues rapid follow-up messages per mapped DeerFlow `thread_id` instead of immediately surfacing the generic busy reply, and topic replies keep a per-message card with a compact source-message preview across queued/running/final patches.
- Streaming IM channels treat backend `error` events like transport failures and follow the same reply and retry path. The channel logs the error type and message for diagnosis.

Set the corresponding API keys in your `.env` file:

```bash
# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Feishu / Lark
FEISHU_APP_ID=cli_xxxx
FEISHU_APP_SECRET=your_app_secret

# WeChat iLink
WECHAT_BOT_TOKEN=your_ilink_bot_token
WECHAT_ILINK_BOT_ID=your_ilink_bot_id

# WeCom
WECOM_BOT_ID=your_bot_id
WECOM_BOT_SECRET=your_bot_secret

# DingTalk
DINGTALK_CLIENT_ID=your_client_id
DINGTALK_CLIENT_SECRET=your_client_secret
```

**Telegram Setup**

1. Chat with [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the HTTP API token.
2. Set `TELEGRAM_BOT_TOKEN` in `.env` and enable the channel in `config.yaml`.
3. The bot accepts inbound text, photos, and documents (with or without captions). Hosted Bot API downloads are limited to 20 MB per attachment.

**Slack Setup**

1. Create a Slack App at [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch.
2. Under **OAuth & Permissions**, add Bot Token Scopes: `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`, `files:write`.
3. Enable **Socket Mode** → generate an App-Level Token (`xapp-…`) with `connections:write` scope.
4. Under **Event Subscriptions**, subscribe to bot events: `app_mention`, `message.im`.
5. Set `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env` and enable the channel in `config.yaml`.

**Feishu / Lark Setup**

1. Create an app on [Feishu Open Platform](https://open.feishu.cn/) → enable **Bot** capability.
2. Add permissions: `im:message`, `im:message.p2p_msg:readonly`, `im:resource`.
3. Under **Events**, subscribe to `im.message.receive_v1` and select **Long Connection** mode.
4. Copy the App ID and App Secret. Set `FEISHU_APP_ID` and `FEISHU_APP_SECRET` in `.env` and enable the channel in `config.yaml`.
5. The bot supports inbound text, image, and file messages. Inbound attachment downloads are limited to 20 MB per attachment.

**WeChat Setup**

1. Enable the `wechat` channel in `config.yaml`.
2. Either set `WECHAT_BOT_TOKEN` in `.env`, or set `qrcode_login_enabled: true` for first-time QR bootstrap.
3. When `bot_token` is absent and QR bootstrap is enabled, watch backend logs for the QR content returned by iLink and complete the binding flow.
4. After the QR flow succeeds, DeerFlow persists the acquired token under `state_dir` for later restarts.
5. For Docker Compose deployments, keep `state_dir` on a persistent volume so the `get_updates_buf` cursor and saved auth state survive restarts.
6. Outbound images/files enforce `max_outbound_image_bytes` / `max_outbound_file_bytes` (20 MiB / 50 MiB defaults) while reading, including files that grow after resolution. Oversize reads are rejected before encryption/upload instead of sending a truncated prefix. Non-positive limits disable the corresponding cap.
7. `allowed_users` takes iLink user IDs. Unset, `null`, `[]`, or a blank string allows everyone. A single ID is one entry, not a sequence of characters, and an unquoted integer-valued number is stored as that integer's text. A scalar string containing commas or interior whitespace logs a warning but remains one literal ID; use a YAML list for multiple IDs. Invalid entries are ignored with a warning; any other configured value that yields no valid ID denies every user and logs an error. `/connect` is still accepted before that check, and a denied sender is dropped before inbound media is downloaded.
8. Shutdown waits for in-flight cursor writes. On token expiry, DeerFlow persists the cursor reset and removes the saved token before completing poller cancellation.

**WeCom Setup**

1. Create a bot on the WeCom AI Bot platform and obtain the `bot_id` and `bot_secret`.
2. Enable `channels.wecom` in `config.yaml` and fill in `bot_id` / `bot_secret`.
3. Set `WECOM_BOT_ID` and `WECOM_BOT_SECRET` in `.env`.
4. Make sure backend dependencies include `wecom-aibot-python-sdk`. The channel uses a WebSocket long connection and does not require a public callback URL.
5. The current integration supports inbound text, image, and file messages. Final images/files generated by the agent are also sent back to the WeCom conversation.

**DingTalk Setup**

1. Create a DingTalk application in the [DingTalk Developer Console](https://open.dingtalk.com/) and enable **Robot** capability.
2. Set the message receiving mode to **Stream Mode** in the robot configuration page.
3. Copy the `Client ID` and `Client Secret`, set `DINGTALK_CLIENT_ID` and `DINGTALK_CLIENT_SECRET` in `.env`, and enable the channel in `config.yaml`.
4. *(Optional)* To enable streaming AI Card replies (typewriter effect), create an **AI Card** template on the [DingTalk Card Platform](https://open.dingtalk.com/document/dingstart/typewriter-effect-streaming-ai-card), then set `card_template_id` in `config.yaml` to the template ID. You also need to apply for the `Card.Streaming.Write` and `Card.Instance.Write` permissions.


When DeerFlow runs in Docker Compose, IM channels execute inside the `gateway` container. In that case, do not point `channels.langgraph_url` or `channels.gateway_url` at `localhost`; use container service names such as `http://gateway:8001/api` and `http://gateway:8001`, or set `DEER_FLOW_CHANNELS_LANGGRAPH_URL` and `DEER_FLOW_CHANNELS_GATEWAY_URL`.

**Commands**

Once a channel is connected, you can interact with DeerFlow directly from the chat:

| Command | Description |
|---------|-------------|
| `/new` | Start a new conversation |
| `/status` | Show current thread info |
| `/models` | List available models |
| `/memory` | View memory |
| `/agent list` | List your Custom Agents |
| `/agent use <name>` | Start a new conversation with a Custom Agent |
| `/help` | Show help |

> Messages without a command prefix are treated as regular chat — DeerFlow creates a thread and responds conversationally.

Agent selection is conversation-scoped: `/agent use <name>` starts a fresh conversation and pins that Custom Agent in the thread metadata. Existing conversations never switch agents midway, the selection survives a Gateway restart, and opening the IM-created thread in the Web UI continues through the same Custom Agent.
Use `/agent use lead_agent` to return to the default agent in a new conversation.

#### Request Trace Correlation

Every Gateway HTTP response carries an `X-Trace-Id` header. The id is inherited
from an inbound `X-Trace-Id` when the caller sends one and generated otherwise, so
a proxy or an upstream service can pin one id across services. It needs no
configuration and cannot be turned off.

The same id stays attached to work that outlives the HTTP response: the detached
run task, any subagents it delegates to, and the background memory-update threads.
It is recorded as `deerflow_trace_id` on the run record (visible in the runs API),
in the thread's checkpoint metadata, and in Langfuse traces. Scheduled tasks, MCP
task notification runs, and IM channel messages start outside HTTP and mint their
own id per occurrence.

Log records carry that id only when enhanced logging is on:

```yaml
logging:
  enhance:
    enabled: true   # print trace_id into log records
    format: text    # or json
```

This is off by default because turning it on changes the log format. `logging` is
restart-required, so edit `config.yaml` and restart the Gateway. The setting
affects log output only — the id, the response header, and the run metadata are
unaffected.

`deerflow_trace_id` is a DeerFlow correlation id: it is not a run id, and it is not
a provider's native trace id. It is not a lookup key either — nothing resolves a
thread or a run from it; use it to correlate log lines. A `deerflow_trace_id` sent
in a run request's `metadata` or `config.context` is ignored and overwritten, so
the response header, the logs, and the persisted run can never disagree. To pin a
correlation id, send the `X-Trace-Id` header.

Gateway run history also records one terminal `run.delivery` receipt per run,
including zero-output and crash-recovered runs. The receipt is persisted before
the durable terminal run status during normal execution. Orphan recovery first
atomically claims an expired lease and then idempotently backfills the receipt,
so a stale recovery scan cannot overwrite a live run's detailed delivery facts.
Receipt persistence remains best-effort during an event-store outage. Runs that
fail checkpoint preflight (or are cancelled while waiting for prior
finalization) keep the existing completion-data behavior: they receive the
zero-delivery receipt but do not overwrite RunStore completion fields with an
empty snapshot.

When `tool_progress.enabled` is true, the same run event history also records
result-quality guard phase changes. It records loop-detection decisions and
deferred MCP tool promotions for both the lead agent and ordinary task
subagents. Promotion
events identify newly promoted deferred-tool names and whether routing metadata or
`tool_search` selected them, without copying the search query, routing keywords,
schemas, arguments, results, or catalog hash into the promotion event itself.

#### LangSmith Tracing

DeerFlow has built-in [LangSmith](https://smith.langchain.com) integration for observability. When enabled, all LLM calls, agent runs, and tool executions are traced and visible in the LangSmith dashboard.

Add the following to your `.env` file:

```bash
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxx
LANGSMITH_PROJECT=xxx
```

#### Langfuse Tracing

DeerFlow also supports [Langfuse](https://langfuse.com) observability for LangChain-compatible runs.

Add the following to your `.env` file:

```bash
LANGFUSE_TRACING=true
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxxxxxxxxxx
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

If you are using a self-hosted Langfuse instance, set `LANGFUSE_BASE_URL` to your deployment URL.

**Trace correlation fields.** Every agent run is annotated with Langfuse's reserved trace attributes so the Sessions and Users pages light up automatically:

- `session_id` = LangGraph `thread_id` — groups every trace of the same conversation
- `user_id` = effective user from `get_effective_user_id()` (falls back to `default` in no-auth mode)
- `trace_name` = assistant id (defaults to `lead-agent`)
- `tags` = `[env:<DEER_FLOW_ENV>, model:<model_name>]` (built-in Gateway lead-agent and embedded client runs tag the selected model after default or fallback resolution; custom graph factories may only provide the requested model; the environment tag is omitted when unset)
- `metadata.deerflow_trace_id` = DeerFlow request correlation id, matching `X-Trace-Id` when request trace correlation is enabled

These are injected into `RunnableConfig.metadata` at the graph invocation root for both the gateway path (`runtime/runs/worker.py::run_agent`) and the embedded path (`client.py::DeerFlowClient.stream`), so any LangChain-compatible callback can read them. Set `DEER_FLOW_ENV` (or `ENVIRONMENT`) to tag traces by deployment environment.

#### Monocle Tracing

DeerFlow also supports [Monocle](https://github.com/monocle2ai/monocle), an OpenTelemetry-based tracer for agentic applications. It records each run end-to-end: LLM calls, agent steps, and tool and MCP invocations, with their inputs, outputs, timings, and token counts.

Add the following to your `.env` file:

```bash
MONOCLE_TRACING=true
MONOCLE_EXPORTERS=file          # file, console, okahu, s3, blob, gcs (default: file)
OKAHU_API_KEY=okh_xxxxxxxx      # required only for the `okahu` exporter
```

Each run writes one trace file to `.monocle/`; open it in the [Monocle VS Code extension](https://marketplace.visualstudio.com/items?itemName=OkahuAI.monocle-apptrace) to inspect the span timeline and token counts. Connect to [Okahu](https://www.okahu.ai), an agent-observability platform, to analyze traces across runs and run trace-based and agentic evaluations (via the `okahu` exporter).

Traces capture span inputs and outputs verbatim — prompts, tool arguments, and model responses — plus token usage and timings. The `file` exporter keeps them on local disk and never rotates or cleans them up, so prune `.monocle/` periodically; the remote exporters (`okahu`, `s3`, `blob`, `gcs`) send that same data off-box, so enable only destinations you trust. Monocle is initialized once at Gateway startup: a configuration error (unknown exporter, missing `OKAHU_API_KEY`) is logged there and tracing stays off until the Gateway restarts.

#### Using Multiple Providers

LangSmith and Langfuse attach as LangChain callbacks, so you can enable both and DeerFlow reports each run to both. If an enabled provider is missing required credentials or fails to initialize, DeerFlow fails fast and names it. Monocle uses a global OpenTelemetry provider rather than a callback; Langfuse shares that provider, so all three can run together. Because both span processors sit on the same shared provider, Monocle's exporters also see Langfuse's spans when both are enabled.

For Docker deployments, tracing is disabled by default. Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in your `.env` to enable it.

#### Existing-Run Stream Actions

Existing-run SSE joins are observation-only on `GET`: supplying
`action=interrupt|rollback` returns `405`. Cancellation on this stream route is
`POST`-only and requires the `runs:cancel` permission. Accordingly, the OpenAPI
contract exposes `action` and `wait` only on `POST`; the `GET` operation exposes
only its path parameters.

#### Personal Access Tokens

Non-interactive clients (CI pipelines, scripts, server-to-server integrations)
can call the Gateway API with a **personal access token (PAT)** instead of a
browser session. Create one while logged in via `POST /api/v1/auth/pats` — the
raw `dfp_...` value is shown exactly once; only its SHA-256 digest is stored —
then send it as a Bearer credential:

```http
POST /api/threads/search
Authorization: Bearer dfp_...
Content-Type: application/json

{}
```

Each token runs with its owning user's identity (owner filtering and per-user
memory keep working), carries a scope set that can only narrow that user's
permissions, and is admitted only to the thread/run lifecycle routes — every
other route answers `403` to PAT callers, and a PAT never carries admin
capability. Tokens can be listed and revoked at any time; revocation is
immediate. PATs require a database backend (SQLite/PostgreSQL). Full
reference: [API Reference — Personal Access Tokens](backend/docs/API.md#personal-access-tokens).

## From Deep Research to Super Agent Harness

DeerFlow started as a Deep Research framework — and the community ran with it. Since launch, developers have pushed it far beyond research: building data pipelines, generating slide decks, spinning up dashboards, automating content workflows. Things we never anticipated.

That told us something important: DeerFlow wasn't just a research tool. It was a **harness** — a runtime that gives agents the infrastructure to actually get work done.

So we rebuilt it from scratch.

DeerFlow 2.0 is no longer a framework you wire together. It's a super agent harness — batteries included, fully extensible. Built on LangGraph and LangChain, it ships with everything an agent needs out of the box: a filesystem, memory, skills, sandbox-aware execution, and the ability to plan and spawn sub-agents for complex, multi-step tasks.

Use it as-is. Or tear it apart and make it yours.

## Core Features

### Skills & Tools

Open **Capability Center** from the workspace sidebar to manage **Plugins**
(MCP servers and Lark/Feishu integration) and **Skills**. Both catalogs support
search; skill cards show concise descriptions with full descriptions in a detail
view. Built-in and user-created/imported skills are listed separately. The
Community tab supports importing `.skill` archives into My skills.
General preferences remain in Settings.

Skills are what make DeerFlow do *almost anything*.

A standard Agent Skill is a structured capability module — a Markdown file that defines a workflow, best practices, and references to supporting resources. DeerFlow ships with built-in skills for research, report generation, slide creation, web pages, image and video generation, and more. But the real power is extensibility: add your own skills, replace the built-in ones, or combine them into compound workflows.

Skills are loaded progressively — only when the task needs them, not all at once. This keeps the context window lean and makes DeerFlow work well even with token-sensitive models.

When deferred skill discovery is enabled, `describe_skill` ranks installed skills by bounded, Unicode-normalized intent-term coverage across names and descriptions. Natural multi-term requests can therefore find a relevant skill without requiring one exact phrase, while exact `select:` and required-name `+prefix` lookups remain available. Ranked searches use up to 256 characters and return up to five results; exact `select:` lists are not truncated and return all requested catalog matches.

A skill directory is a package boundary: once DeerFlow finds its `SKILL.md`, nested `SKILL.md` files under that package (for example evaluation fixtures) remain supporting data and are not registered as runtime skills. This applies to managed integration packs as well as public and custom skills. Namespace directories without their own `SKILL.md` can still group nested skills.

Discovery follows operator-managed directory symlinks, but skips links back to an ancestor directory so a cyclic namespace does not repeatedly rescan the same tree. Independent links to the same external skill tree remain supported.

Skill Markdown and bundled text resources use UTF-8. Skill-creator CLI and review utilities read and write text explicitly as UTF-8 so localized skills behave consistently across operating systems.

Users can explicitly activate an enabled skill for a single turn by starting the request with `/skill-name`, for example `/data-analysis analyze uploads/foo.csv`. DeerFlow loads that skill's `SKILL.md` as hidden current-turn context while leaving the base prompt limited to skill metadata. Slash activation respects disabled skills, custom-agent skill whitelists, and existing channel commands such as `/new` and `/help`.

After an answer loads skills, its toolbar includes **Skills used**. Hover over or click the icon to see the skills and their sources; hovering a skill name underlines it. Select a skill to inspect its `SKILL.md` in the resizable side panel (a drawer on mobile). The view uses snapshots captured during successful configured read-tool loads or explicit slash activation, so later edits or removal of a skill do not rewrite its history. Repeated loads appear once per run, in first-load order. Range reads and bounded snapshots are labeled as partial; older conversations without captured evidence do not show this menu. Copy returns the captured Markdown, including YAML frontmatter. Package-relative links and images remain readable references rather than navigating away from the conversation. Skill loads performed through other tools, such as shell commands, are not inferred from answer text.

An enabled skill's `allowed-tools` policy applies only after that skill is explicitly slash-activated or captured in the agent's active skill context after a `read_file` load. Merely enabling, advertising, or listing a skill in a custom agent or subagent `skills` allowlist does not reduce that agent's normal toolset; subagents use the same progressive discovery and activation policy as the lead agent. During a slash-activated run, that explicit skill's policy is authoritative: reading another `SKILL.md` may provide instructions but cannot widen the slash skill's tools. Without slash activation, policies from skills actually loaded into active context retain their union semantics. Once active, the policy filters both model-visible tool schemas and tool execution. Framework discovery tools (`tool_search` and `describe_skill`) remain available so an allowed deferred tool or installed skill can still be discovered, but discovery and promotion never grant permission to execute a business tool omitted from `allowed-tools`. `task` is not framework-exempt; a restrictive skill must list it explicitly to delegate to a subagent. Per-step policy decisions are internal runtime context and are removed from observable or persisted context copies. Registry failures and an active set with no remaining valid skill fail closed to framework-safe tools; individual stale paths are ignored only when another valid active skill remains. This is best-effort behavioral scoping, not a hard security boundary: loading skill instructions through another tool is not captured, and active-skill entries can be evicted from bounded context.

When you install `.skill` archives through the Gateway, DeerFlow accepts standard space-separated `allowed-tools`, optional frontmatter metadata, and the Claude-compatible `argument-hint` field instead of rejecting otherwise valid external skills. YAML lists remain supported for `allowed-tools` and preserve exact runtime names. Exact portable spellings such as `WebFetch`, `WebSearch`, `Glob`, `Grep`, and `Read` map to DeerFlow's `web_fetch`, `web_search`, `glob`, `grep`, and `read_file` tools; lowercase or otherwise unknown scalar names remain unchanged so custom and MCP tools keep their exact runtime spelling. Parenthesized entries such as `Bash(tvly *)` are tokenized as one literal entry, including spaces, quoted text, and escaped parentheses, but remain inactive because DeerFlow does not inspect tool arguments; declare `bash` only when the skill may use the full Bash tool.

Disabling a skill also removes it from the sandbox filesystem view, so shell commands and structured file tools follow the same enabled state. Local, Docker/AIO, hostPath provisioner, and newly created E2B sandboxes source `/mnt/skills` from enabled-only projections that update when public, custom, legacy, or managed integration skills are toggled, edited, created, deleted, or installed. Structured `read_file` calls (including line ranges and read-before-write checks) use the sandbox provider's mount mapping, so the user identity captured when the sandbox was acquired remains authoritative. Managed integration packages remain shared, while their projected filesystem visibility follows each user's enabled state. Multi-worker Gateways re-read on-disk enable state while rebuilding user projections, so a toggle handled by one worker is honored by another worker's next sandbox acquire. Existing E2B sandboxes retain their creation-time snapshot until they are recreated. PVC-backed provisioner skills keep their configured PVC snapshot/layout for now; dynamic PVC materialization is tracked separately.

```
# Paths inside the sandbox container
/mnt/skills/public
├── research/SKILL.md
├── report-generation/SKILL.md
├── slide-creation/SKILL.md
├── web-page/SKILL.md
└── image-generation/SKILL.md

/mnt/skills/custom
└── your-custom-skill/SKILL.md      ← yours

/mnt/skills/integrations
└── lark-cli/lark-doc/SKILL.md      ← managed, read-only
```

The built-in `image-generation` skill supports Gemini, MiniMax, and
OpenAI-compatible Images APIs. Select the latter with
`IMAGE_GENERATION_PROVIDER=openai`, then configure
`IMAGE_GENERATION_API_KEY`, `IMAGE_GENERATION_BASE_URL`, and
`IMAGE_GENERATION_MODEL`. For a containerized sandbox or an explicitly enabled
local host shell, expose these variables through `sandbox.environment`; sandbox
commands intentionally do not inherit API keys from the Gateway process.
The local provider uses the resolved configuration values unchanged, and
request-scoped secrets override operator values. Local bash output and command
errors redact credential values while leaving benign settings such as model
names and base URLs readable.

For `LocalSandboxProvider`, this is a managed tool-path boundary rather than host filesystem isolation. Explicit per-Agent skill policies are accepted only while host bash is disabled (the default), because a host subprocess can address canonical paths without using the provider's virtual-path mappings. Use Docker/AIO, the Kubernetes provisioner, or E2B when the filesystem boundary must remain enforceable alongside shell access.

Managed integrations install shared read-only skill packs without mixing them
into custom skills. The Lark/Feishu CLI integration is available under
`Capability Center → Plugins → Lark / Feishu`; an administrator installs or
upgrades the official `lark-*` pack once under
`{DEER_FLOW_HOME}/integrations/skills/lark-cli`, and every user discovers that
same pack with an independent enabled state. Each user's app configuration and
OAuth data remain isolated under
`{DEER_FLOW_HOME}/users/{user_id}/integrations/lark-cli/{config,data}`. These
secret directories are restricted to `0700`, regular credential files to
`0600`, and symlinks are rejected.

After installation, users can click **Connect Lark** to open a browser
authorization link; no terminal authorization is required. The same UI can
request additional permission domains such as Calendar, Docs, or Drive, or a
specific OAuth scope reported by `lark-cli`. A cheap status refresh only
inspects the local credential tree, so the UI reports **Credentials configured
(not live-verified)** until an explicit browser completion performs live token
verification. The action then remains **Reconnect Lark** so users can replace
or extend authorization. If an agent hits missing Lark authorization during a
conversation, the managed `lark-shared` guidance points the user back to the
same plugin configuration with `/workspace/capabilities?tab=plugins&plugin=lark`.

Once configured, **Change Lark app** lets a user point their DeerFlow account at
a different Lark/Feishu app without a reinstall — either by pasting an existing
app's App ID / App Secret or by re-registering an app in the browser. Switching
is per-user (it never touches another user's credentials), validates the new
credentials through the official CLI's live tenant-token probe before replacing
the active app, and revokes/removes the previous app's OAuth tokens. A rejected
credential change does not supersede an in-progress setup or authorization flow.
The previous OAuth data is cleared before the CLI stores the replacement app,
so the new file-backed keychain secret remains available during reconnection.
DeerFlow then immediately opens browser authorization for the newly bound app so
the switch ends in a usable connection.

Installing the Lark skill pack resolves the latest official `larksuite/cli`
release from GitHub and downloads that version's skills at install time, so the
Gateway needs outbound internet access for that step (it falls back to a
bottom-line pinned version if the release lookup fails). The settings page shows
the installed version and, when available, the newest published version so an
admin can reinstall to upgrade. Air-gapped deployments can pre-stage the archive
and point `DEER_FLOW_LARK_CLI_SKILLS_ARCHIVE` at the local file. Integrity does
not depend on a pinned archive byte hash (GitHub does not guarantee stable
source-archive bytes); instead the download is restricted to the official GitHub
host, every archive member passes structural safety guards, and a content hash
of the effective installed skill tree (including DeerFlow's injected shared
guidance) is recorded so content changes are auditable across reinstalls.

When `sandbox.use` selects the AIO provider, the same install also downloads the
official Linux amd64 and arm64 CLI release archives, verifies their published
SHA-256 checksums, safely extracts one executable per architecture, and mounts
the resulting runtime read-only at `/mnt/integrations/lark-cli/runtime`. An
architecture-selecting launcher in that mount makes `lark-cli` available in the
sandbox `PATH`. Air-gapped AIO deployments can pre-stage a symlink-free runtime
tree containing `bin/lark-cli` plus both `linux-{amd64,arm64}/lark-cli` files and
set `DEER_FLOW_LARK_CLI_SANDBOX_RUNTIME_DIR` to that directory.

> **Sandbox trust boundary:** the browser never receives the Lark app secret, but
> agent conversations run `lark-cli` inside the sandbox, so the per-user
> credential directories are mounted into it: `config` (holding the long-lived
> `appSecret`) is mounted **read-only**, its otherwise empty `config/locks`
> subdirectory is over-mounted writable for `lark-cli` coordination files, and
> `data` (refreshable OAuth tokens) is writable. The credential-bearing config
> and data mounts remain *readable* by any process the agent runs there, so code
> reached via prompt injection in a tool result could read them. Treat the
> sandbox as inside the Lark credential trust boundary until the sidecar
> credential-broker follow-up removes these mounts from sandbox execution.

For remote/Kubernetes deployments (the provisioner backend), the sandbox
`lark-cli` runtime can instead be supplied by an optional init container that
copies the binaries into a shared `emptyDir` — no install-time GitHub download and
no hostPath/PVC runtime mount. Publish the image under
[`docker/lark-cli-init`](docker/lark-cli-init/README.md) and set
`LARK_CLI_INIT_IMAGE` on the provisioner (with the Helm chart,
`provisioner.larkCliInitImage` / `provisioner.larkCliBrokerImage`); it stays off
(legacy behavior) when unset. The Lark integration status
(`GET /api/integrations/lark/status`) reports `sandbox_runtime_mode`,
`sandbox_runtime_probed`, and `sandbox_runtime_ready`.
`sandbox_runtime_probed` marks whether runtime readiness was actually
evaluated; responses from older backends may omit the flag, in which case the
Settings mutation cache keeps the last probed runtime fields instead of
overwriting them with an unevaluated fallback — so the Settings UI shows
whether `lark-cli` will actually be present in the sandbox at chat time, rather
than a green status hiding a later `command not found`.

In Lark broker mode, AIO's fresh Bash runs close inherited pipe stdin. Persistent
terminal commands keep their input; the shim ignores terminal stdin. Explicit
pipelines, heredocs, and file redirections still supply input normally, and the
shim forwards that input only after EOF. A stdin idle timeout aborts without
executing the command, and broker execution logs omit argument values. See the
[broker image guide](docker/lark-cli-broker/README.md) for timeout settings and
image rebuild requirements.

If a trusted operator manages the configured skills directory through an external mount such as MinIO, NFS, or CSI, an administrator can call `POST /api/skills/reload` after changing files. This invalidates skill prompt caches in the handling Gateway process, waits up to the bounded refresh timeout, and then advances a durable reset marker (`.extensions_config.json.skills-cache-reset.json`) in the writable config directory. Every Gateway worker or Pod mounting that directory notices the marker within about a second of its next prompt build and rescans the latest files, so one call reaches every replica sharing the volume; the response reports `scope: shared_config`, or `scope: process` when no extensions config path is available. Running tasks are unchanged. Skill installs, edits, deletions, rollbacks and enable/disable toggles made through the API publish the same marker, so a change made on one replica takes effect on the others without a restart. A loader-level filesystem failure returns a generic server error and preserves the last successfully loaded process cache rather than publishing an empty catalog. Replicas with independent filesystems are not covered. Direct mount writes bypass the validation, SkillScan, and history applied by DeerFlow's install/edit APIs, so only operator-controlled systems should have write access.

Skill installs and agent-managed skill edits run through **SkillScan**, a native deterministic safety scanner before the LLM-based skill scanner. Phase 1 runs offline with no Semgrep/OpenGrep dependency, blocks high-confidence `CRITICAL` findings such as private keys or shell execution, and passes warning findings to the LLM scanner for contextual review. Code files (anything under `scripts/`, a script suffix such as `.py`, `.sh`, or `.js`, or an extensionless file starting with `#!`) that are not NUL-free UTF-8 text raise a warning and are still analyzed over a lossy decode, so a single stray byte cannot hide them from `CRITICAL` checks. The moderation adapter normalizes both plain-text model responses and LangChain Responses API text blocks before parsing the required JSON decision. Python instance-client exfiltration checks follow a minimal same-scope evidence chain: a simple name bound to a known client constructor, optional name-to-name aliases, and an actual outbound method or context-manager use supported by that constructor. Constructor roots must be proven imports; bare canonical-looking names are not inferred as modules. Nested scopes do not inherit client handles and inherit only constructor import aliases that are never rebound in the enclosing scope. Comprehensions, walrus-bearing statements, annotations, complex binding targets, unsupported operations, and ambiguous branch flows produce no finding from this signal; skipped constructs conservatively invalidate every name they may bind so stale client state cannot create a finding. A deterministic work budget or recursion limit reached by this best-effort analysis does not discard findings already collected for the file. Set `skill_scan.enabled: false` in `config.yaml` to disable only the deterministic analyzers; safe archive extraction and the LLM scanner still run.

Windows scripts (`.bat`, `.cmd`, `.ps1`, `.psm1`, `.js`, `.jse`, `.vbs`, `.vbe`, `.wsf`), HTML applications (`.hta`), and scriptlets (`.sct`) count as code even outside `scripts/`, regardless of filename case. They receive both SkillScan analysis and the installer's executable-code policy.
SkillScan warns about remote downloads piped into common shells, including `env` launchers, sudo, interpreter paths, and shell line continuations. It distinguishes environment dumps from `env` commands, including assignments and GNU split-string escapes. Shell parsing and split expansion are bounded; reaching a limit preserves critical findings already detected. Pipes to non-shell tools such as `jq` and `tee` do not trigger this warning.

SkillScan treats HTTP/HTTPS scheme spellings and HTTP hostnames case-insensitively and recognizes bracketed IPv6
loopback (`[::1]`) URLs as local. External IPv6 endpoints still trigger network findings,
and cloud-metadata hostname detection is case-insensitive.

For Python credential mappings, SkillScan checks literal values while treating ordinary dictionary keys as labels. A mapping such as `tokens = {"access_token": os.getenv("ACCESS_TOKEN")}` does not report a hardcoded credential. Keys matching a recognized cloud or API token format are still checked as embedded credentials.

SkillScan blocks embedded legacy and modern `sk-` API tokens, including OpenAI project, service-account, and admin keys and Anthropic keys, even in Bearer headers without a secret assignment. Token bodies may contain `-` and `_`; finding evidence is fully redacted. Placeholder examples do not suppress detection of later credentials in the same file. Scheduled-task notification summaries also redact these key formats before sending them to external IM platforms.

DeerFlow also ships with **skill-reviewer**, a public skill for read-only skill quality review. It uses the built-in `review_skill_package` tool to inspect installed skills, local packages, archives, or pasted `SKILL.md` content without activating the target skill, binding its secrets, executing its scripts, or installing it. The tool returns a compact, tag-neutralized JSON payload to the model context and keeps the full raw review payload in the tool artifact for programmatic consumers. The deterministic review core reuses DeerFlow parsing and SkillScan facts, emits versioned JSON contracts under `contracts/skill_review/`, and can be run from the backend CLI:

```bash
cd backend
uv run python -m deerflow.skills.review.cli ../skills/public/data-analysis --format text --fail-on error --fail-on-incomplete
```

Public-skill CI waivers are exact, expiring exceptions in `.github/skill-review-waivers.v1.json`. Because only the trusted base manifest can suppress a finding, a file-changing pull request can be preauthorized safely by first merging a manifest-only change that lists the reviewed future full-file SHA-256 in `preapproved_file_sha256s`; the file change can then land in a later pull request.

Tools follow the same philosophy. DeerFlow comes with a core toolset — web search, web fetch, rendered web capture, file operations, bash execution — and supports custom tools via MCP servers and Python functions. The bundled DDG, Brave, Tavily, SearXNG, and Serper search providers accept an optional `time_range` of `day`, `week`, `month`, or `year`; omitting it preserves existing search behavior. For DDG recency searches, DeerFlow excludes DDGS backends that ignore time limits. Swap anything. Add anything.

For DDG web search and DDG image search, `max_results` in `config.yaml` can be a positive integer or an environment-variable reference such as `max_results: $DDG_MAX_RESULTS` with `DDG_MAX_RESULTS=5`. The configured value takes precedence over the tool call's `max_results` argument. Invalid values (for example, `abc`, an empty string, or `3.5`), zero, and negative counts produce a warning and fall back to the default of 5 results.

Stdio MCP servers can set `cwd` in `extensions_config.json` when their entrypoint
or data files depend on a specific working directory. The setting applies to
both discovery and tool calls; see [MCP configuration](backend/docs/MCP_SERVER.md#stdio-working-directory).
Omitted, `null`, or empty values keep the default working directories.

Tavily `web_search` also accepts optional `include_domains` and `exclude_domains`
lists in its `config.yaml` tool entry to control search sources. Non-empty
`include_domains` uses Tavily's `filter` mode to restrict results to those domains.
These are deployment settings; the model still supplies only `query` and optional
`time_range`. Omitted filters preserve the existing SDK request; an explicit
empty list is forwarded and imposes no restriction of that kind. See the
[tool configuration example](backend/docs/CONFIGURATION.md#tools).

Serper web and image search can use another Serper-compatible provider through
`SERPER_BASE_URL` and that provider's `SERPER_API_KEY`. Each tool can instead set
its own `base_url` and `api_key` in `config.yaml`; each request reads them from
one configuration snapshot. Use an absolute HTTP(S) base URL with a host,
without `/search`, `/images`, a query string or a fragment. Invalid overrides
return a configuration error before HTTP; blank environment values keep
Serper's default unless a tool overrides them. See
[Serper endpoints](backend/docs/CONFIGURATION.md#serper-endpoints) for precedence
and how the provider receives the API key.

Serper `web_search` supports deployment-level `include_domains` and
`exclude_domains` too. It checks returned URL hosts (including subdomains), with
exclusion taking precedence. Filters can return fewer results, including zero;
there are no refill requests. This selects sources, not factual accuracy or a
global URL-access policy. The model arguments and image search are unchanged.
See [Serper configuration](backend/docs/CONFIGURATION.md#serper-source-filters)
for validation and query-length limits.

When using Tavily for `web_fetch`, extracted pages without a title use their URL
as the heading; their content remains available to the agent.
Chat tool-step titles accept leading blank lines and up to three spaces before
a page's first H1 heading. Indented code, including mixed spaces and tabs, is
not used as a title; the tool step falls back to the URL.
Tavily search and fetch each read `api_key` from their own tool entry in
`config.yaml`, falling back to `TAVILY_API_KEY` when omitted. Fetch does not
reuse the search entry's key, so search can use a different provider. If you
previously configured a shared Tavily key only under `web_search`, also set it
under `web_fetch` or use `TAVILY_API_KEY` for both.

#### Exporting Custom Skills

Administrators can export their own custom skills from **Capability Center → Skills → My skills → View details → Export**. Review the file list and declared environment requirements, then choose **Download .skill**. The archive contains the currently saved skill, including supporting files and empty directories; disabled skills can also be exported. If the skill changes after preview, refresh the file list before downloading. Import the archive on another DeerFlow instance with **Install .skill**; existing-name conflicts and normal installation security checks still apply.

Account settings, conversations and history outside the skill folder are excluded. Files inside the folder are preserved unchanged, including any credentials an author placed there; filename notices are advisory. Configure dependencies and credentials on the destination. Linked folders/files, hard links, unsupported executable binaries, nested `SKILL.md` files and nonportable paths cannot be exported. Export supports hosts with descriptor-relative no-follow filesystem APIs (Linux/macOS); unsupported hosts fail explicitly. Limits: 4096 ZIP entries, 64 MiB per file, 100 MiB total content/archive and 1 MiB frontmatter. YAML aliases and excessively complex declarations are not supported. Ordinary script executable semantics are preserved on POSIX import, without restoring special permissions. See [the export API contract](backend/docs/API.md#export-a-custom-skill).

#### Claude Code Integration

The `claude-to-deerflow` skill lets you interact with a running DeerFlow instance directly from [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Send research tasks, check status, manage threads — all without leaving the terminal.

**Install the skill**:

```bash
npx skills add https://github.com/bytedance/deer-flow --skill claude-to-deerflow
```

Then make sure DeerFlow is running (default at `http://localhost:2026`) and use the `/claude-to-deerflow` command in Claude Code.

**What you can do**:
- Send messages to DeerFlow and get streaming responses
- Choose execution modes: flash (fast), standard, pro (planning), ultra (sub-agents)
- Check DeerFlow health, list models/skills/agents
- Manage threads and conversation history
- Upload files for analysis

**Environment variables** (optional, for custom endpoints):

```bash
DEERFLOW_URL=http://localhost:2026            # Unified proxy base URL
DEERFLOW_GATEWAY_URL=http://localhost:2026    # Gateway API
DEERFLOW_LANGGRAPH_URL=http://localhost:2026/api/langgraph  # LangGraph API
```

See [`skills/public/claude-to-deerflow/SKILL.md`](skills/public/claude-to-deerflow/SKILL.md) for the full API reference.

### Private Knowledge Retrieval (RAGFlow)

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

Advanced deployments can enable pluggable authorization with `authorization.enabled` in `config.yaml`. A configured `AuthorizationProvider` filters denied tools before they reach the model or deferred-tool catalog, then the same provider is checked again before every business-tool execution through the existing guardrail middleware. Gateway `threads:*` and `runs:*` route permissions are derived from the same provider, while existing owner checks and admin-only management gates remain in force. Every HTTP route that starts or enables a future Agent run requires `runs:create`: this includes the stateless `POST /api/runs/stream` and `POST /api/runs/wait` endpoints plus scheduled-task create, update, resume, and manual-trigger mutations. Scheduled-task mutations retain their existing `threads:write` requirement, and the stateless routes separately enforce ownership when the optional thread ID is supplied in the request body. A generated `tool_search` may bypass the second tool check only when it fronts the current build's already-filtered deferred catalog. Model access follows the same provider: the Gateway `models` list is filtered per principal, `model:use` is enforced on model detail requests and again when the runtime resolves the agent's model, and a denied default model falls back to the first remaining candidate that also passes `model:use`. The built-in RBAC provider supports per-role `tools`, `routes`, `models`, `skills`, and `sandbox` allow/deny policies and validates that `default_role` names a configured role; authorization is disabled by default. Custom roles declared in the provider's `roles` mapping become reachable by assigning them to a user through the admin API (`GET /api/v1/admin/users`, `PATCH /api/v1/admin/users/{id}`; admin-only, last-admin demotion protected) — a declared role nobody holds grants nothing. See `config.example.yaml` and the [authorization RFC](docs/plans/2026-07-10-pluggable-authorization-rfc.md).

Follow-up suggestions also check `model:use` before calling the selected model, including the default model when no name is supplied. A denied model returns HTTP 403 without an LLM call; authorization-provider failures follow the configured `fail_closed` policy.

For vision-capable agents, `view_image` and the subsequent model-context image read also require `sandbox:execute`. Allowing the tool name alone does not grant image-file access; a role denied sandbox execution cannot reread previously recorded image metadata after its permissions change. External run input and thread-state updates cannot set `viewed_images` or `thread_data`; when a saved image is read from a host copy, its path must resolve to the current user's thread and the recorded virtual image path.

Advanced deployments can also extend the agent runtime itself by declaring `AgentMiddleware` classes under `extensions.middlewares` in `config.yaml` or `extensions_config.json`. Each entry is a `module.path:ClassName` string (zero-argument constructor) or an object `{class, kwargs}` whose `kwargs` are passed to the constructor. `kwargs` values must be JSON types (object, array, string, number, boolean, or null); YAML dates and timestamps are coerced to ISO strings so they match JSON. DeerFlow loads the same configured list into the lead-agent and subagent pipelines after their built-in runtime middlewares and loop/token guards, but before the terminal-response/safety/clarification tail, so enterprise forks can add domain guardrails, tool-call governance, or observability hooks without patching the built-in middleware builders. Missing packages, invalid classes, broken modules, and constructor errors fail loudly at agent creation. Treat `config.yaml` and `extensions_config.json` as trusted operator-controlled files: middleware paths are code execution, just like custom tool, model, sandbox, guardrail, MCP server, and MCP interceptor declarations. Gateway skill/MCP toggle endpoints preserve this field but do not expose an API write path for `extensions.middlewares`. Separate lead-only/subagent-only middleware lists are not supported yet.

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
The [fetched-content screening example](examples/deerflow-extension-jev-screening/README.md)
contributes one such middleware at the visible tool position. After operator opt-in it
classifies the sanitized text a remote tool result shows the model, PII-redacted when
`pii_redaction` is enabled, and adds an advisory warning through a lifecycle state
update; it imports only the extension contract.

Full-stack contributions can additionally provide browser pages, conversation actions,
authenticated backend operations and model tools through the
[plugin APIs](docs/full-stack-plugins.md). The independent
[bookmarks example](examples/deerflow-extension-bookmarks/README.md) demonstrates
one package with persistent user data, its own sidebar page and a read-only search tool.
Reopening a bookmark resolves the conversation's current agent through the host, so
custom-agent conversations retain their original chat entry point, including older bookmarks.
The independent [Agent teams example](examples/deerflow-extension-agent-teams/README.md)
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

Extension services can optionally receive a [host model invoker](backend/docs/extension-model-invocation.md)
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
[reference extension](examples/deerflow-extension-example/) for a complete example.

Gateway-generated follow-up suggestions now normalize both plain-string model output and block/list-style rich content before parsing the JSON array response, so provider-specific content wrappers do not silently drop suggestions.

Backend response cleanup preserves unrelated tag names such as `<think-tank>` and `<think:note>` in follow-up suggestions and polished drafts; only the exact `<think>` name (optionally followed by attributes) starts a reasoning block. Self-closing `<think/>` and `<think />` tags are empty reasoning blocks and leave the following answer intact.

The Web UI composer can polish draft input before sending. The rewrite runs as a short Gateway LLM request using the `input_polish` model configuration, keeps slash skill prefixes such as `/data-analysis`, and only replaces the local draft after the user clicks the polish button; it does not create a thread run or persist a message.

When the agent asks for clarification, the Web UI shows the structured response card but keeps the normal composer available. Users can complete the card or send a free-form chat message to bypass it; that message closes the latest pending clarification and becomes the agent's next input. Accompanying answer text stays outside the execution steps panel, and answering the request keeps previously completed text in the conversation while the agent continues.

Unsent Web UI composer drafts survive page reloads and switching between conversations within the same browser tab. Drafts are isolated by user, agent, and conversation, include the selected skill and explicit conversation references, and are cleared once a send is accepted. Project documents already attached to the thread also survive reloads; browser-local uploads and quoted message excerpts are not persisted.

The Web UI composer supports `@` references at the cursor or through the `@` button. Search enabled skills, documents in the current project, and other conversations in a grouped picker; selected references appear inline alongside the draft text and can be removed with normal editing. Multiple skills can be selected in one message (up to 16 unique skills); selecting a checked skill again removes it, with each selection checked against the current user registry and agent allowlist. Project files are attached only after ingestion succeeds; conversation references require the `read_conversation` capability and retain its per-run limit. If capability discovery fails, saved conversation references remain intact and sending waits for a successful retry. Polishing preserves complete reference labels when instructions are reordered. The file group also offers local uploads. `/goal`, `/compact`, and legacy `/skill-name` input remain supported.

The Web UI composer also supports browser-based voice dictation when the browser exposes the Web Speech API. The microphone button transcribes speech into the local draft only; DeerFlow receives only the transcribed text, while audio handling is delegated to the browser or operating system speech-recognition service according to that environment's policy. Users can review or edit the text before sending. Dictation keeps words separated when browsers trim transcript segments, preserves Chinese and Japanese joins, and attaches leading punctuation and percent signs without adding spaces.

The Web UI displays a localized AI-generated-content disclaimer below the composer in both standard and custom-agent conversations, reminding users to verify important
information.

Interrupted first-turn runs still persist a fallback conversation title, so stopping a streaming response does not leave the thread as "Untitled" after refresh.

Streaming Markdown responses animate only newly arrived words; text that is already visible is not faded out and replayed when the next chunk extends the same block.

In the Web UI, completed assistant turns can be branched into a new main conversation. Automatically inherited branch titles use the next free language-neutral numeric suffix (`Title (2)`, then `Title (3)` for another sibling or a branch of the numbered conversation) so generated sibling titles remain distinct without persisting a locale-specific label; matching explicit or renamed sibling titles also reserve their displayed suffix even though they carry no generated sequence metadata. An explicit API title is preserved. Renaming a branch clears its generated sequence, so its next automatic branch starts from the renamed title at `(2)`. Recent chats also groups loaded branches directly beneath a loaded parent with subtle tree connectors. Missing parents, malformed or cyclic lineage, and branches in a different pinned state stay visible at the top level instead of being hidden or moved across the pinned boundary. The new thread starts from that turn's checkpoint and keeps the preceding replay checkpoint, so the branched response can be regenerated immediately. The latest response can also be regenerated after an interruption, even when its streamed partial text never reached a checkpoint. Regenerating the latest response preserves the thread's current title, including a title you renamed manually after the original response. Legacy or imported histories without checkpoint parent links use a bounded chronological fallback; if no earlier replay checkpoint exists, branching still succeeds with the legacy single-checkpoint shape, while regeneration remains unavailable for that inherited response. Existing single-checkpoint branches are left unchanged rather than attempting an unsafe checkpoint copy. Because workspace files are not checkpointed, the branch only receives a best-effort copy of the current workspace when you branch from the latest turn; branching from an older turn keeps just the restored message history so the branch never inherits files that were created in a later part of the conversation.

The Web UI reports completed task time once per run. This is total wall-clock time—including model reasoning, tool calls, and waiting—not a per-step or model-only thinking duration. Reasoning content remains available through its own separate disclosure.

While a response streams, reasoning-only messages stay in the processing panel, including Anthropic thinking blocks. Once answer content arrives alongside reasoning, it appears in an assistant bubble.

Literal `<think>` tags in fenced, indented, or inline code remain part of the answer and its copied text, rather than being moved into the reasoning disclosure. This includes fences opened on list-item lines: real reasoning after the code is still extracted. Unfinished inline code spans are preserved while streaming within a paragraph, but end at a blank line or an interrupting heading, list, thematic break or fence. Indented paragraph continuations do not start a code block.

In the Web UI, the latest completed user turn can also be edited and rerun from the message toolbar. DeerFlow restores the conversation checkpoint before that user message, submits the edited text as a new user message, and hides the superseded turn once the replay is in progress or succeeds. This is a conversation-state replay only: files, memory updates, and external tool side effects are not undone.

Web UI chat links percent-encode custom thread identifiers before placing them in route segments, so reserved URL characters such as `#` and `?` do not change which conversation is opened.

### Chat Archive

Deleting a chat from the sidebar requires confirmation showing its title. Deletion removes the conversation and its files and cannot be undone.

Use **Archive chat** in a recent chat's sidebar menu to hide completed work while keeping its messages, files, and original link. The success message offers **Undo**. Open **Chats → Archived** to find archived conversations and restore them individually; an open archived conversation also shows a restore button in its header. Search filters the titles of loaded conversations, with **Load more** for older entries.

Archive and restore preserve the chat's activity time and pinned state. Archiving does not stop a running task or pause its schedules, and new activity does not automatically restore it. Use the existing Delete action when you intend to remove a conversation and its files.

### Session Goals

Use `/goal <completion condition>` to attach one active completion condition to the current thread. The goal is thread-scoped state, not a skill activation, so it stays active across turns until DeerFlow determines it has been satisfied or you clear it. The agent sees the active goal on every model call, so it keeps working toward it after context compaction removes the message that stated it.

Supported commands:

```text
/goal finish the implementation and make all tests pass
/goal              # show the active goal
/goal clear        # clear it
```

After each Gateway-backed run, DeerFlow evaluates the visible conversation, including the assistant's tool calls and shortened tool results, against the active goal with a non-thinking evaluator model. A successful tool result alone does not satisfy a goal, and when the assistant had to guess missing or ambiguous information the evaluator reports `needs_user_input`. The evaluator must return a typed blocker (`missing_evidence`, `needs_user_input`, `run_failed`, `external_wait`, or `goal_not_met_yet`) plus visible evidence. DeerFlow only injects a hidden continuation when the latest assistant turn is durably checkpointed, the blocker is `goal_not_met_yet`, the thread did not change during evaluation, and the no-progress breaker has not fired. The safety cap defaults to 8 hidden continuations, and repeated identical non-progress evaluations stop after 2 attempts. `/goal clear` and any user-authored new input win over queued continuations. When the evaluator considers the goal satisfied, DeerFlow clears it after the run successfully finalizes and publishes the updated thread state. If required artifact delivery or its receipt persistence fails, the run reports an error and the goal remains active for a later retry; this does not start another hidden continuation.

The Web UI shows the active goal above the composer. The same command is available from the TUI and supported IM channels. In the Web UI and supported IM channels, setting `/goal <completion condition>` also starts a run with the condition as the task; status and clear commands only manage goal state. Setting or clearing a goal is rejected while that thread has a run in flight, including a run owned by another Gateway worker, so the goal checkpoint cannot branch away from an active run's checkpoint lineage.

When your role lacks `runs:create`, the Web UI rejects a new task or `/goal <completion condition>` before preparing the thread or saving the goal, and keeps your draft for retry. Goal status, goal clearing, and `/compact` remain governed by their own endpoint permissions.

### Manual Context Compaction

With `task_continuity.enabled`, `history_search` searches the current task's active
and compacted history. Its optional `role` accepts `user`, `assistant`, or `tool`
and filters before the eight-result limit; omitting it or passing `null` preserves
search across all roles. Use `history_read` to verify the original source;
historical user messages do not grant current authorization. See
[task continuity](docs/task-continuity.md).

Automatic and manual compaction exclude old todo reminder messages from both the
summary input and retained context. The current todo list stays in thread state.
In planning mode, if the original `write_todos` call is no longer visible,
DeerFlow adds a reminder using the latest task statuses before the next model
call. Skipped or failed compaction leaves the existing messages unchanged.

Optional `pii_redaction.enabled` redacts detected identifiers in user messages,
remote tool results, compaction input, reinjected summaries, and configured
LLM title input. Memory admission, including pre-compaction flushes, also redacts
detected identifiers in supported text/JSON content, parsed and invalid call arguments/error text,
provider-raw/legacy function calls and supported user-content provenance.
It is off by default; enabled deployments supply a secret for stable, keyed
value-derived placeholders. No token-to-raw mapping is persisted. Raw thread
text and local fallback titles remain available for display; memory redaction
copies messages without changing the caller's history or tool execution.

The Web UI preserves persisted message order when merging history with live updates. Streaming steps around a persisted result inside the loaded history stay together, including steps that arrive after the result. Steps captured during compaction also remain visible before their persisted result when history has not refreshed and the UI has not rendered them yet.

Compaction keeps the current user request and summarizes older assistant/tool activity. When rescuing that request leaves an assistant/tool-only summary window, input trimming favors its most recent content. For mixed histories whose user-message anchor falls outside the trimming budget, compaction retains the existing final-message fallback. `summarization.trim_tokens_to_summarize` (4000 by default) controls trimming of the raw summary input; escaping and prompt formatting add overhead beyond that budget. Setting this option to `null` disables input trimming for the summary model; choose that only when the model can accept the full history being compacted.

If the same rendered summary prompt and model candidates recur, DeerFlow reuses the existing summary when the first candidate previously returned it unchanged. An unchanged fallback response is not cached, so reuse cannot prevent the primary model from being retried after an invocation failure. Cache failures fall back to normal generation. See [summarization telemetry](backend/docs/summarization.md#reuse-and-telemetry) for the summary result and reuse counters.

Use `/compact` in the Web UI composer to summarize older context for the current thread. DeerFlow keeps the full chat visible, but future model calls use the compacted summary plus recent messages. The command is ignored when there is not enough history to compact, and it is blocked while the thread has a run in flight, including when that run is owned by another Gateway worker. If a multi-worker reservation loses its lease, DeerFlow cancels the checkpoint writer before the replacing run proceeds and returns a retryable conflict after cleanup. Thread-title edits are serialized through the same state-write boundary and show a conflict without closing the rename dialog when a run is active.

The chat header also shows a context-window gauge when the selected model has a positive `context_window` configured. It estimates the latest materialized checkpoint's message tokens and keeps the previous same-thread percentage visible while data refetches, independently of the cumulative token-usage setting.

When `token_budget.enabled` and `token_usage.enabled` are both enabled, each lead-agent run budget includes completed subagent usage, including the final batch. Hidden goal continuations share the budget; a new user run starts fresh.

### Sub-Agents

When a sub-agent ends with `return_direct=True` tools, including tools contributed by extension middleware, their outputs are returned in tool-call order. A failed tool marks the task as failed while preserving the batch outputs.

Ordinary `task` calls accept `context_mode="isolated"` (default) or
`context_mode="snapshot"`. Isolated tasks receive their delegated prompt as
before. Snapshot tasks also receive the parent's retained conversation and
compaction summary, captured at dispatch as historical background. This helps
handoffs that depend on earlier requirements or failed approaches, at the cost
of additional input tokens. Retained text, tool-call descriptions/results, and
JSON-serializable media input blocks are carried over. Binary or otherwise
unserializable media blocks become an explicit omission notice; surrounding
conversation remains available. Parent system prompts, hidden framework
messages (such as injected memory and todo reminders), reasoning blocks, tool
execution metadata, and pending tool calls are excluded. Tool-call descriptions
require a retained matching result, including calls alongside the current task.
Valid hidden user clarification responses remain part of the conversation. The child
keeps its own role, model, tools, and skill restrictions. Parent tool records
cannot satisfy child execution checks. Parent and child histories evolve
independently afterward; shared sandbox/filesystem behavior is unchanged.
Snapshot mode does not restore already-compacted messages or promise prompt
cache reuse. Durable `batch_task` items still require self-contained prompts.

Native document blocks are retained in snapshots. Their textual content, titles,
and context use the same reserved-tag and input-boundary neutralization as other
historical text; encoded media and URL sources are preserved without decoding.

For a manual, synthetic comparison of complete handoffs and snapshots, see the
[context snapshot evaluation](backend/scripts/benchmark/context_snapshot/README.md).

Custom Agents support an optional Unicode display name, including Chinese and
emoji. Open an agent's **Agent settings → Display name** to set it (up to 100
Unicode code points), or leave it blank to show the existing identifier. Control
characters and bidirectional formatting controls are rejected; ordinary multilingual
text and emoji are supported. Invisible-only names and invisible formatting
characters such as zero-width spaces are rejected. Invalid display names in
older or hand-edited storage fall back to the agent identifier when read;
a warning identifies the affected agent.
Re-bootstrapping preserves valid display names. The gallery,
chat header, and welcome page use this label; URLs and API calls continue to use
the stable English `name`. API callers can pass `display_name` to agent creation
or update requests; an omitted update preserves it and `null` clears it. The
same optional field is supported in the agent's `config.yaml`.

Custom Agents can also be moved between DeerFlow users or deployments from the
Agents gallery. **Export Agent** downloads a versioned
`*.deerflow-agent.json` package containing the portable definition and
`SOUL.md`; **Import Agent** validates that package and lets the receiving user
choose a local name. Invalid packages show validation messages so you can correct
the package and retry. Imports never overwrite an existing agent. Packages carry
model, tool/MCP, skill, knowledge, sub-agent, reasoning, and memory-policy
settings, but deliberately exclude memory contents, conversations, credentials,
and operator-owned GitHub bindings.

Sub-agents are an optimization, not the default response to a complex request.

After Stop interrupts a delegated task before it returns a reply, the next user
turn marks that earlier task as cancelled in the agent's durable context so it
can retry. Existing replies are preserved. Older replies without status metadata
may still appear in progress; their outcome is not inferred from their text.
The durable delegation ledger distinguishes calls by run and provider tool-call
ID, so a later user turn can reuse an ID without replacing earlier work or
losing that turn's per-run delegation count.

The lead agent can spawn sub-agents on the fly — each with its own scoped context, tools, and termination conditions — when delegation has clear net benefit from real parallel latency, specialist capability, or context isolation. It keeps interdependent scopes and overlapping side effects out of parallel dispatch; a bounded sequential chain can still run in one sub-agent when specialist or context-isolation benefit clearly wins. The lead uses the fewest useful sub-agents and re-evaluates later batches instead of fanning out solely because a task is large or multi-step. Sub-agents report back structured results, and the lead agent verifies and synthesizes them into a coherent output. Deterministic tool receipts cover both direct tool messages and state-updating `Command` results such as delegated `task` responses; when the receipt ledger reaches its context budget, it retains the newest actions and their original receipt IDs. Operators can disable this provenance layer with `verification.receipts_enabled: false`. Their configured skills are resolved from the same user-scoped catalog as the lead agent, so user-owned custom skills remain available without exposing another user's version. Their internal AI and tool messages stay scoped to the delegated graph instead of entering the parent chat stream. Reloaded thread history enforces the same boundary: callback-captured sub-agent AI responses remain available in run-event diagnostics but are excluded from the parent transcript, while the parent `task` result remains attached to its subtask card. Long-running sub-agents compact older history when summarization is enabled and re-inject the summary as guarded, hidden durable context before continuing, so recent assistant/tool activity remains grounded in the task. Their system instructions, including the role and report contract, survive compaction; if only those instructions and the current request would be summarized, compaction is skipped. Provider/model request failures are reported as failed sub-agent tasks rather than successful results, so the lead agent and Web UI can react to them correctly. Concurrent parent runs also receive independent server-side sub-agent execution IDs, so a provider that reuses a tool-call ID cannot make one run poll, cancel, or clean up another run's background task. Collapsed sub-agent cards show the effective model and, when the provider returns usage metadata, a cumulative token total that updates after each completed sub-agent LLM call and persists after a reload. When token usage tracking is enabled, completed sub-agent usage is attributed back to the dispatching step from that run's terminal tool-message metadata rather than a process-global provider-ID cache.

Cancelled or timed-out background sub-agent executions retain provider-reported token usage from completed model calls, including responses received before their next progress update. Final usage delivery to the parent run does not count earlier progress snapshots twice.

For `tests_passed:go test ./...`, packages marked `[no test files]` or `[no tests to run]` do not veto a passing summary from another package. Runs with only zero-test package summaries remain `UNVERIFIED`; failures still take precedence. This checks recorded execution evidence, not claim correctness.

For file acceptance criteria, an empty regular file in the shared workspace can satisfy `file:<path> exists` and `file_written:<path>`, including on remote sandboxes. It fails `file:<path> non-empty` with a deterministic empty-file result.

To request JSON syntax validation, explicitly set a `task` or `batch_task` item's
`acceptance_criteria` to `["file:../outputs/report.json json-valid"]`. Checks cover only
complete UTF-8 JSON files within the shared workspace, up to **50,000 bytes**.
Valid syntax returns `holds`; empty files, syntax errors, non-UTF-8 content, or
`NaN`/`Infinity` return `does not hold`. Oversize files, incomplete reads, out-of-scope
paths, or parser resource limits return `UNVERIFIED`.
Reads are capped at 50,001 bytes to detect oversize content. Remote results are checked
for a completion marker, the read exit code, and the probed size. Remote providers lacking
the required probe tools leave the result unverified rather than falling back to full-content
reads. Concurrent writes of the same size do not yield an atomic snapshot.
Local checks authorize sandbox access before resolving paths or probing metadata, and recheck
before reading content; revoked permissions return `UNVERIFIED` without revealing existence.
Remote probes report missing files only with a searchable ancestor and in-scope canonical path;
inaccessible directories remain `UNVERIFIED`. UTF-8 BOMs are rejected. Top-level scalars,
duplicate keys, and syntactically valid large numbers can pass, without validating schemas,
fields, or business semantics. Other file criteria are unchanged, and `.json` files are not
checked automatically. This criterion standardizes verdicts, path boundaries, and read limits
instead of requiring ad hoc bash/Python checks, and makes insufficient evidence explicit.
Execution completion status and automatic retry policy are unchanged.

Content-less sub-agent final messages report `No response generated` instead of the literal text `None`. A content-less provider-error fallback reports its structured error detail when available.

An ordinary `task` also receives a defensive snapshot of the dispatching run's current uploads. This lets eligible sub-agents use `list_uploaded_files` to find earlier-turn files without returning same-turn attachments as historical. Delayed or recovered `batch_task` workers leave this tool disabled because they have no valid turn-local upload boundary.

历史上传发现支持稳定续页：`list_uploaded_files` 默认每页 20 项、最多 100 项，
将返回的 `next_cursor` 作为下一次调用的 `cursor`，保留相同过滤条件，直到末页不再
返回游标。目录元数据或调用上下文变化时会明确要求重新枚举；详情见
[文件上传文档](backend/docs/FILE_UPLOAD.md)。

Durable `batch_task` workers use one app-owned plugin snapshot for tool assembly and execution. Recovered tasks adopt the new worker's plugin snapshot after a Gateway restart; plugin objects are never stored in durable task records.

Ordinary `task` delegation and explicit durable `batch_task` execution share the startup-scoped `subagent_runtime` process capacity. Batch mode keeps large independent item sets in SQL with separate total, live, and running limits, restart recovery, bounded results, and a thread-scoped Web UI panel. The panel pages through bounded previews on demand; bulk stored results are available through the owner-scoped JSONL export, while internal execution and authorization context never enters owner-facing responses. If the batch worker is later stopped or disabled, threads with persisted batches retain read-only item inspection and JSONL export; execution controls remain disabled until the worker is running again. See `config.example.yaml` and [the implementation contract](docs/plans/2026-08-24-subagent-batch-capacity-implementation.md) for limits and recovery semantics.

While durable batch tools are available, a later owner turn can explicitly inspect selected results with `read_batch_result(batch_id, position=0, offset=0, max_chars=4000)`. The reader is restricted to the current user and thread, including in explicitly bound SDK graphs. It returns one window of a JSON document containing the stored report, execution/error state and separate acceptance criteria/verdict, without starting or waiting for work. Concatenate `content` windows before parsing: pass `next_offset` and the returned `revision` as `expected_revision` until `next_offset` is null. A changed item returns `restart_required`; discard prior windows and start at zero. Use `next_position` for a selected next item within `batch_status.total_items`. The maximum window is 8,192 characters; metadata shares the window budget, and JSON response framing adds overhead. `result_truncated` means storage already capped the report; continuation cannot recover discarded content. A succeeded item is not an accepted task, and unchecked criteria remain UNVERIFIED. No automatic result ingestion, waiting loop or UI change is added.

The complete escaped response also fits within 10,000 characters and the bound host's positive `tool_output` externalization/fallback limits, so normal budgeting preserves continuation JSON. Smaller limits can shorten a window; `budget_too_small` means the operator must raise the budget instead of retrying a zero-length page. Limits too small even for that error envelope cannot provide a usable structured response. Explicit SDK graphs with a custom output-budget middleware should supply the same `AppConfig` through `SubagentRuntime`; default graphs use default reader limits.

Offline acceptance: `cd backend && PYTHONPATH=. uv run --locked pytest tests/test_batch_result_reader.py -k 'real_submission_worker or sdk_factory_graph' -q`. This exercises real submission, deterministic worker completion, database reopen and registered graph consumption; external model execution is replaced by a fake model/executor.

Durable knowledge-research results also export nullable `result_artifact.knowledge_sources` snapshots. Each retained source pairs a citation ID in the stored report with the exact excerpt captured by `knowledge_search` or a delegated `task`, plus its RAGFlow dataset/document/chunk locator and pages. The existing authenticated `GET /api/threads/{thread_id}/subagent-batches/{batch_id}/results.jsonl` remains the entry point: find a report's `#knowledge-<id>` link in that row's `sources` by `id` to inspect the evidence after a Gateway restart or provider change. Compact item queries and the batch panel do not include these snapshots; this does not add clickable citations to batch previews.

Snapshots preserve whole excerpts, not freshly fetched provider content. They inherit the 100-source/1,000,000-text-character forwarding limits; the serialized snapshot has a separate character budget equal to `subagent_batches.max_result_chars`, in addition to the report's existing budget. `knowledge_sources.omitted_count` reports referenced records omitted by forwarding, snapshot projection checks or snapshot budgeting; malformed or unsupported producer artifacts filtered before candidate selection are not counted. Report truncation limits selection to complete citations in the stored text. Old/plain results have no snapshot (`null`); no historical evidence is reconstructed. Gateway startup adds a nullable JSON column through migration `0033_batch_result_artifact`. Back up the database before migrating; downgrading drops evidence snapshots while preserving report text. Cancelled, failed and stale attempts do not publish evidence, and explicit retries clear previous snapshots.

Explicitly enabled nested `task` delegation propagates omitted opaque source IDs in its captured artifact. Each outer report filters and deduplicates those IDs, and independently captured evidence can restore an omitted source. The durable snapshot publishes only the final count. Legacy task artifacts without omission IDs cannot reconstruct earlier forwarding losses; unknown prose citations are not treated as captured evidence.

If an item's final lease expires after exhausting the retry budget, the batch reaches a terminal state once all items are terminal: `failed` when none succeeded, or `completed` when at least one succeeded. The item remains `failed` in both cases so partial results stay visible.

Direct `create_deerflow_agent(...)` integrations can own the same boundary explicitly instead of relying on Gateway startup. Construct one `SubagentRuntime` and share it across every graph in that application; its `max_running`, ordinary per-run total, bound `task` tool, and optional durable-batch tools then use the same caller-owned snapshot and execution controller. A runtime with a batch repository owns a worker and must be started before graph construction and stopped during application shutdown:

```python
from deerflow.agents import RuntimeFeatures, create_deerflow_agent
from deerflow.subagents import SubagentRuntime

runtime = SubagentRuntime.from_app_config(app_config, batch_repository=batch_repository)
async with runtime:
    graph = create_deerflow_agent(
        model,
        features=RuntimeFeatures(subagent=True),
        subagent_runtime=runtime,
    )
    # Serve or invoke graph while the durable worker is running.
```

`SubagentRuntime.stop()` waits for its owned batch service to finish before propagating caller cancellation, including repeated cancellation. This drain has no timeout; repository operations and child cleanup must terminate. If service shutdown also fails or is cancelled, the first caller cancellation is preserved with the service failure as its cause.

The factory still does not load YAML or create SQL infrastructure: the caller supplies the config snapshot, repository, and lifecycle. Because it accepts a caller-owned `system_prompt`, direct integrations also own any model-visible wording about those limits; the default middleware enforces the runtime limits regardless. The factory does not mount the Gateway owner-scoped HTTP routes or Web UI, so direct applications must expose their own result API/UI if they need those surfaces. For ordinary delegation only, `SubagentRuntime(...)` needs no asynchronous startup.

Administrators can add, edit, disable, and delete reusable worker definitions from **Settings → Subagents**. Built-in and `config.yaml` definitions remain visible there as read-only entries. The default Lead Agent can use every enabled runtime sub-agent; each page-created Custom Agent can instead allow all, none, or a selected set. That selection is enforced both in the model-visible directory and by the server-side `task` tool. Managed definitions are deployment-wide in this version and follow `agent_storage.backend`: atomic files for a local deployment or the shared application database for multiple instances.

For example, independent read-only research can run concurrently when the wall-clock savings outweigh duplicated discovery and synthesis cost, while a repository refactor with shared files and sequential test feedback remains with the lead agent. When `max_concurrent_subagents` is `1`, parallel and multi-batch routing guidance is disabled; delegation remains available only for material specialist or context-isolation benefit.

### Sandbox & File System

Host-externalized tool outputs use the Gateway's normal file-creation umask.
Host and sandbox outputs use deterministic filenames hashed from the raw tool
call ID and output content. Missing, colliding, or oversized IDs cannot overwrite
different output or make the filename too long; identical output can reuse its path.
Host and remote sandbox persistence failures, including invalid Unicode during filename
hashing, use the configured inline fallback.
`tool_output` character/count budgets, including per-tool overrides, require
non-negative integers; YAML booleans are rejected rather than treated as 0 or 1.
An explicit zero per-tool override disables externalization while preserving
any positive global fallback limit.
Structured JSON tool results follow these budgets, including results mixed with
media; externalization keeps the full JSON available through a file reference.
MindIE renders JSON tool results as escaped text, with configured tool exemptions
preserved. Enabled PII redaction scans nested JSON keys and values before rendering.
Mounted sandboxes running under another UID need read access through the shared
storage permissions. An unclean shutdown can leave `.tool-output-*.tmp` files in
`tool_output.storage_subdir` (default `.tool-results`) under thread outputs.
Remove leftovers during thread-data maintenance with all Gateway writers stopped,
or when deleting the corresponding inactive thread's data.

`E2BSandboxProvider` uses `wait` as its default overflow policy. It waits for
`acquire_timeout`, then fails the agent turn. DeerFlow does not retry the turn
automatically. Clients can use the structured error to schedule a retry.

Use `burst` with `burst_limit` to permit bounded extra VMs. The `wait` and
`reject` policies use only `replicas`. The `reject` policy can remove one warm
VM before it returns an error.

With in-memory ownership, `replicas` limits one Gateway process. With Redis
ownership, E2B shares one capacity Hash between workers using the same
`sandbox.ownership.key_prefix`; `replicas` (plus a configured burst) is then a
deployment-wide hard limit. Use one unique prefix and the same effective limit
per deployment. To change the limit, stop its Gateways, delete the capacity
Hash, and restart; mismatched workers fail closed.

The Hash counts remote VMs and in-flight creates, repairs interrupted creates
from E2B metadata, grace-protects stale inventory omissions, and blocks new
creates while Redis or initial inventory is unavailable. Run Redis with persistence, non-evicting memory, and HA.

E2B reconciliation renews active VMs with a positive timeout covering its
configured cadence, even when `idle_timeout` is zero or shorter than that
cadence. Warm VMs retain the configured idle-timeout behavior. Expired local
warm entries do not directly free shared capacity: remote inventory must
confirm disappearance through the existing grace period first.
Active renewal completes before release sets the warm timeout, so a concurrent
maintenance pass cannot extend an idle VM's lifetime. Warm-entry cleanup also
preserves ownership acquired by a new request during the sweep.
Ownership heartbeats remain independent of slow E2B timeout requests, preventing
control-plane delays from making active sandbox leases expire.

E2B snapshots `skills.container_path` when the provider starts and includes the
canonical root in its thread identity, warm-pool seed, and remote metadata. A
VM created for a different root is never adopted; reconciliation reaps it after
the configured grace period once no live peer owns it. Restart the Gateway after
changing the root.

E2B acquisition uses a bounded executor. Waiting acquisitions do not use the
default asyncio executor.

Each E2B mount upload pass accepts at most 512 MiB and 2,000 files. The pass
also has a cooperative 120-second deadline. Skill projections and configured
mounts share these limits. The provider checks the deadline before each mount
and during directory preflight. The deadline stops new file uploads after it
expires. It does not interrupt active filesystem or E2B SDK calls.

An E2B VM keeps its slot until E2B confirms destruction. This rule covers
create and reclaim operations. Discovery can find a VM from another Gateway.
Shutdown closes an unowned discovery client without destroying its VM.
Release stops counting a transition when the VM enters the warm pool.
Shutdown races retry remote cleanup after a transient kill failure.
Reset destroys tracked active and warm E2B VMs. The old provider instance
cannot accept new acquisitions.

DeerFlow doesn't just *talk* about doing things. It has its own computer.

Each task gets its own execution environment with a full filesystem view — skills, workspace, uploads, outputs. The agent reads, writes, and edits files. It can view images and, when configured safely, execute shell commands.

The read-before-write gate ties each read mark to that `read_file` call's result, including custom tools returning multi-message `Command` updates. An unrelated result cannot authorize a write after a failed read or hide a successful read.

The built-in `grep` tool searches either one text file or all matching text files below a directory, so an agent can search an uploaded document directly without first broadening the request to the entire uploads directory.

Remote `ls` excludes ignored descendants before applying its 500-entry listing limit, so dependency and build trees do not crowd out visible files. Explicitly listing an ignored directory still lists its contents; normal depth and output limits remain in effect.

AIO directory listings discard missing shell sessions so the next request can recover.
After a dropped connection, directory listings and persistent shell commands report an
unknown outcome without replaying the operation; later calls use a fresh session.

Uploaded Markdown outlines recognize ATX heading syntax, clean closing markers with a linear suffix scan, and skip HTML comment blocks and fenced and indented code examples, so hashtags and code comments do not
crowd out real document sections from the agent's heading preview. Indented bold examples are also excluded; PDF-style bold headings with up to three leading spaces remain supported.
Split-bold numeric table rows, including parenthesized years, signed values, and
currency-prefixed amounts, are excluded when any block after the section number
is a numeric column, so they do not consume the outline's heading budget.
UTF-8 Markdown files with or without a byte-order mark (BOM) produce the same
outlines and fallback previews, with original line numbers preserved.
Outline titles are limited to 200 characters and fallback previews to 2,000
characters per file, with truncation markers. Full uploaded files remain available
for targeted reads.

Converted upload outlines and previews require a matching source version, including
modification timestamps. A detected source-version change invalidates its previous
conversion, including equal-length edits. Older ownership records without source timestamps
are also rejected; re-upload the source with `uploads.auto_convert_documents: true`
to restore conversion-backed outlines. Files remain available, and unvalidated
Markdown conversions appear as standalone files in the agent's historical listing.
On Windows, `st_ctime_ns` may represent creation time; a same-size rewrite that
restores the original `mtime` can evade validation. Timestamp checks are
conservative metadata validation, not a guarantee of content equality.

Image bytes loaded for a vision-model call are transient: DeerFlow removes the hidden base64 message after the model consumes it so later checkpoints do not keep duplicating that payload.

After each run, DeerFlow records a workspace change summary for the run-owned `workspace` and `outputs` directories. The Web UI shows a compact "files changed" badge on the assistant turn; opening it reveals created, modified, and deleted files with text diffs when safe to display. Uploads are excluded because they are user inputs, not agent-generated changes, and stdio MCP temporary/debug files under the DeerFlow-owned `.mcp/` namespace are excluded because they are process-internal state (like `.git/` and `node_modules/`, any directory named `.mcp` is excluded at any depth). Large, binary, or sensitive-looking files are shown as metadata only.

Files presented through `present_files` remain part of the thread's artifact state, and the Web UI restores the artifact panel and selected document after a page refresh. When a completed response successfully presents between 2 and 50 files, its final file card also offers one ZIP download. Archive membership comes from the terminal delivery receipt rather than browser-supplied paths, and the ZIP contains the current file versions, which may have changed since the response. The currently selected formal artifact is refreshed once when the run finishes so edits become visible without a manual reload. Existing UTF-8 text artifacts under `/mnt/user-data/outputs` can also be edited and explicitly saved from the panel on Unix and Windows while the thread is idle; saves use content revisions to prevent overwriting agent changes. Source previews also recognize extensionless `Dockerfile` and `Makefile` artifacts by their file names. Unknown file types, including names such as `constructor` and `__proto__`, retain the download fallback.

Artifact content revisions refresh when an output file is atomically replaced,
even if its size and modification time are preserved. Refreshing the preview
then provides the new revision for saving; an older preview still requires a reload.
Regular files over the 2 MiB editing limit use file identity and change metadata
for range validators without hashing the whole file. Conditional byte ranges for
regular files require a matching ETag; date-form `If-Range` requests receive the full current file.
Saving also bounds the existing-file read to 2 MiB plus one detection byte, so a
file that grows or is replaced after the size check is rejected without loading
the entire oversized file into memory.

CSV and TSV artifacts open as tables in the artifact panel and in a separate window. The preview preserves text values (including leading zeros), supports an optional header row, and pages through up to 200 rows and 50 columns from the initial sample. Long or multiline cells can be opened and copied in full. Switch to source to inspect or edit the file; downloads and separate windows use the saved version.

HTML artifact previews resolve relative assets from the artifact directory unless the document contains a real `<base>` element. Base-tag examples in comments or script text do not change that resolution.

If the sample cuts a CRLF line ending in half, the preview keeps the earlier complete rows and omits the incomplete final record, including when its last field is quoted.

Text artifacts are streamed with HTTP byte-range support. The Web UI initially
loads at most 1 MiB, shows the preview size when a file is larger, and waits for
an explicit **Load full file** action before fetching the remainder or mounting
the full code editor. Editing becomes available once the complete file has loaded;
unsaved-change detection uses the full content, including when reverting edits
or deleting the portion beyond the initial preview. If a reload fails or returns
only a preview, users can still exit editing while retaining their unsaved draft.
Active HTML, XHTML, and SVG artifacts remain forced downloads at the Gateway
boundary.

Artifact previews and downloads preserve literal percent sequences in file names:
`report%20final.md` and `report final.md` remain distinct files. Markdown links
continue to accept URL-encoded paths.

The `write_file` guidance reflects the active model's output token limit, including custom-agent and thinking-mode overrides. For longer documents, the agent is guided to write sections with `append=True`; models without a known limit receive no numeric budget hint.

With `AioSandboxProvider`, shell execution runs inside isolated containers. With `LocalSandboxProvider`, file tools still map to per-thread directories on the host, but host `bash` is disabled by default because it is not a secure isolation boundary. Re-enable host bash only for fully trusted local workflows. Host bash commands have a wall-clock timeout, and long-lived processes should be started in the background with output redirected to a workspace log. On Windows, Git Bash/MSYS argument-conversion exclusions are limited to safe non-root virtual path prefixes, so host-native CLI launchers retain their normal MSYS compatibility. When the local sandbox falls back to PowerShell, it captures output as UTF-8 so CJK text does not depend on the Gateway host locale.

Docker AIO sandboxes default to their existing open egress behavior for
compatibility. Operators can set `sandbox.network.mode` to `isolated` or
`allowlist`; allowlist mode supports operator-defined domains and an interactive
Human Input card for temporary or sandbox-lifetime HTTP(S) approval. Private,
loopback, link-local, multicast, and cloud metadata addresses remain
unapprovable. Denied hostnames are rejected before DNS resolution.
Runs in `scheduled`, `webhook`, or `autonomous` interaction mode auto-deny
without opening a card. These unattended runs proceed with minimal assumptions
only for low-risk, reversible work; high-risk or irreversible work without
sufficient authorization returns a structured `BLOCKED` result naming the
missing decision, even if the model attempts to ask for clarification.
The trusted sidecar uses a dedicated per-sandbox egress bridge rather than
Docker's shared default bridge, and rejects ambiguous HTTP field names before
forwarding. See
[Sandbox configuration](backend/docs/CONFIGURATION.md#sandbox-network-policy)
for runtime requirements and the complete policy model.

`AioSandboxProvider` normally detects thread-data mounts from its backend: local
containers use the mounted gateway directories, while remote/provisioner
sandboxes receive uploaded files through explicit synchronization. Deployments
where both sides are guaranteed to share the same thread user-data directories
can set `sandbox.thread_data_mounts: true` to skip that per-upload sandbox
acquire and sync. Leave the field unset for automatic detection; setting it
incorrectly can make uploaded files unavailable inside the sandbox.

Failed upload commits report the original error even if temporary-file cleanup
also fails, for example because of a Windows sharing violation.
Once the file is published, a temporary-file cleanup failure is logged without
failing the upload; hidden staging files are left for the startup sweep.

Uploads, new skill support files, and new local sandbox paths reject Windows
reserved device names on every platform, including `COM¹`, `LPT²`, the console
aliases `CONIN$` and `CONOUT$`, and names with extensions such as `com³.txt`.
ASCII spaces before the extension do not make a device name portable:
`NUL .txt` and `COM1  .log` are rejected too. Ordinary names such as
`report .txt` are preserved unchanged.
Rename these files before creating or uploading them so the same file tree
remains usable on Windows.

Uploaded filenames matching `.upload-*.part` are rejected because that pattern is
reserved for temporary staging files. Rename such a file before uploading it.
The restriction includes Windows aliases with trailing dots or spaces and
case variants, such as `.upload-notes.part.`, `.upload-notes.part `, and
`.UPLOAD-NOTES.PART`, on every host.
The HTTP check recognizes both `/` and `\` as path separators, including on
Linux, when extracting the basename. The endpoint returns `400` with a rename
hint before publishing any file in a batch containing a reserved name, so the
chat reports the upload error instead
of continuing without the attachment. The SDK validates filenames for the whole
batch before copying any files. New project document names follow the same
restriction, whether defaulted from the source or explicitly supplied on upload
or promotion to the shelf; an older shelf document with a reserved name
remains downloadable but cannot be attached directly. Download it, rename it,
and upload it to the thread. This change does not recover or migrate older
thread uploads that already match the staging pattern.

This is the difference between a chatbot with tool access and an agent with an actual execution environment.

```
# Paths inside the sandbox container
/mnt/user-data/
├── uploads/          ← your files
├── workspace/        ← agents' working directory
└── outputs/          ← final deliverables
```

### Agentic Browser Control

Browser dependency auto-detection accepts `name`, `group`, and `use` in any
order within a tool entry, with either indented or indentless YAML lists.

Reading a page is not the same as *using* one. Alongside the read-only `web_fetch` and `web_capture` tools, DeerFlow ships an optional agentic browser tool group that keeps a live, per-conversation browser session so the agent can actually operate a page — navigate, read the interactive elements, click, type, submit forms, and follow multi-step flows on JavaScript-heavy sites.

Each action returns a fresh snapshot of the page's interactive elements, each addressed by a stable `[ref]` number, so the agent acts on what it just observed instead of guessing selectors. Outbound URLs are SSRF-screened by default, and the browser's TCP connections go through a local proxy that pins each one to the screened addresses, so a DNS answer that changes after the check cannot redirect them to a private host (WebRTC UDP is not covered). It is powered by Playwright and shipped as an optional extra so the core install stays lean:

```bash
cd backend
uv sync --extra browser
uv run playwright install chromium
```

Then uncomment the `group: browser` tool entries in `config.yaml` (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_get_text`, `browser_back`, `browser_screenshot`, `browser_close`). `make dev` / Docker startup detects an enabled `browser_navigate` tool and preserves the `browser` extra on dependency syncs. The Gateway fails startup if browser control is configured but Playwright is missing, and `/api/features` hides the Browser UI unless the backend can actually serve it. Keep `headless: true` and `allow_private_addresses: false` for anything but local, trusted debugging. Attaching to an existing Chrome with `cdp_url` cannot enforce DeerFlow's subresource/redirect SSRF guard and therefore fails closed unless `allow_unguarded_cdp: true` explicitly acknowledges that risk; use it only with a trusted local browser. Browser sessions are process-local; keep the Gateway to a single worker process while this tool group is enabled because ordinary uvicorn worker dispatch does not provide thread affinity. That means `GATEWAY_WORKERS=1`, and on the launches that pass uvicorn no worker count at all (`backend/Dockerfile`, `scripts/serve.sh`) also `WEB_CONCURRENCY` unset or `1`, since uvicorn takes the process count from it.

Existing, non-mock Custom Agent chats expose the same Browser Live controls when browser control is available and the agent either leaves `tool_groups` unrestricted or includes the `browser` group. An explicit tool-group allowlist without `browser` keeps those controls hidden.

The workspace Browser Live client negotiates binary JPEG WebSocket frames,
keeps only the newest pending frame per display refresh, and revokes replaced
object URLs. Gateway control messages remain JSON, and clients that do not
request the binary capability retain the legacy JSON/base64 frame protocol.

### Context Engineering

**Table Tool-Output Synopses**: CSV/TSV row counts reflect logical records, so newlines inside quoted fields do not add rows. If parsing fails or exceeds the field limit, the synopsis reports an undetermined count. Outputs beyond the input-size limit still skip structured parsing.

**Isolated Sub-Agent Context**: Each sub-agent runs in its own isolated context. This means that the sub-agent will not be able to see the context of the main agent or other sub-agents. This is important to ensure that the sub-agent is able to focus on the task at hand and not be distracted by the context of the main agent or other sub-agents.

**Summarization**: Within a session, DeerFlow manages context aggressively — summarizing completed sub-tasks, offloading intermediate results to the filesystem, compressing what's no longer immediately relevant. This lets it stay sharp across long, multi-step tasks without blowing the context window.

**Tool Output Preview Budget**: Structured synopses of externalized results have a character budget. Long JSON keys and paths are shortened with `...`, and oversized synopsis bodies include a truncation notice. Raw head/tail samples, the full file reference, and `read_file` guidance are preserved; read the saved file for exact keys or complete output.

**Strict Tool-Call Recovery**: When a provider or middleware interrupts a tool-call loop, DeerFlow now strips provider-level raw tool-call metadata on forced-stop assistant messages and injects placeholder tool results for dangling calls before the next model invocation. This keeps OpenAI-compatible reasoning models that strictly validate `tool_call_id` sequences from failing with malformed history errors.

**Visible Tool-Run Completion**: For interactive turns, DeerFlow retries an empty post-tool final response once, then surfaces a visible error instead of reporting a silent successful run.

**Run History**: Image-only user input is recorded once per run, even when the agent makes multiple model calls. Its media content remains in history without requiring a text summary.

### Reading a Referenced Conversation

Gateway API callers can opt into `read_conversation` and submit a
`conversation_references` list with a run. The lead agent can then read bounded
pages of the current visible text of those owned conversations. Read permission
expires with the run, and text in old messages does not grant access. Text the
agent has already read stays in the destination conversation after access
expires or the source is deleted. A message too long for one read carries a
continuation, so the agent can read the rest; it asks for the missing part only
if that read is unavailable.
SDK clients that cannot add top-level request fields may send the same list as
`context.conversation_references`, and `GET /api/features` reports whether the
tool is enabled. When it is, the web composer shows a "Reference a conversation"
button next to the attachment button: pick up to three of your recent
conversations, and they are attached to the next message only, shown as chips
in the composer and in the transcript. There is no automatic history search. See
[configuration](backend/docs/CONFIGURATION.md#reading-referenced-conversations)
and the [request contract](backend/docs/API.md#referencing-a-previous-conversation).

### Current Task Notes

Enable [task notes and history recall](docs/task-continuity.md) with `task_continuity.enabled: true`.
A task can retain up to eight notes. Parallel additions beyond the remaining slots return
`note_capacity`, preserving existing notes. When artifact-handle resolution is enabled,
capacity counts resolved keys; aliases for the same note share one slot.
Malformed non-dict sibling arguments do not consume slots or disrupt valid note calls.
Notes with invalid keys, content over 750 characters, more than four sources, or malformed
source IDs also reserve no slot. Existing keys can still be replaced or deleted. Slots freed
by sibling deletions or runtime failures (such as unavailable sources or policy denial)
become available in the next batch, when rejected additions can be retried.

### Long-Term Memory

The opt-in [DeerMem scope-isolation benchmark](backend/scripts/benchmark/deermem_scope_isolation/README.md)
checks semantic safety across facts and summaries, and fact routing across users
and agents. Failed extraction attempts are retryable execution errors, not safety passes.

For DeerMem, `memory.backend_config.storage_class: markdown` opts into tolerant
summary reads while keeping JSON writes and the existing UI. A hand-edited
`memory.json` can contain its JSON object inside a fenced `memory-json` block;
embedded backticks and later fenced notes are supported. Unparseable summary
text is moved to `memory.json.corrupt-<timestamp>` for recovery before rebuilding.
`storage_path` must point to the data root directory, not an existing JSON file.

Gateway shutdown drains memory updates before closing the backend, even when
shutdown is cancelled. Config reload failures are logged without aborting runtime
teardown. For Kubernetes, budget `terminationGracePeriodSeconds` for all shutdown
hooks, config/backend resolution, `memory.shutdown_flush_timeout_seconds`, and
backend close plus a safety margin. The flush timeout does not bound `close()`:
custom backends must make close quick or internally bounded, or shutdown can wait
until the process is forcibly terminated.

Most agents forget everything the moment a conversation ends. DeerFlow remembers.

DeerMem can optionally suppress near-duplicate extracted facts with
`memory.backend_config.fact_dedup_enabled: true` and
`fact_dedup_similarity_threshold` (default `0.7`, range `0.5`–`1.0`).
This local, deterministic word/CJK-bigram heuristic compares facts only within
the same user, agent, and category; it is not semantic equivalence detection.
It keeps the existing ID, text, and creation time, raises confidence to the
maximum, and refreshes the source only when confidence increases. Explicit
correction replacements and facts proposed for removal are protected from
near-duplicate merging. A merge does not count as user confirmation. The gate
is off by default and does not affect targeted fact updates.

DeerFlow also includes an optional `openviking` memory backend. It uses the
official `langchain-openviking` package to capture completed turns into stable
OpenViking Sessions and recall memory for prompt injection while leaving
DeerMem as the default. The initial integration supports one DeerFlow user with
one credential-bound OpenViking USER API key in `memory.mode: middleware` and
does not inherit arbitrary HTTP headers from `ovcli.conf`.
See [OpenViking memory backend](docs/OPENVIKING.md) for its configuration,
behavior, and current boundaries.

Across sessions, DeerFlow builds a persistent memory of your profile, preferences, and accumulated knowledge. The more you use it, the better it knows you — your writing style, your technical stack, your recurring workflows. Memory is stored locally and stays under your control.

DeerMem and mem0 capture user inputs and final assistant replies. Assistant
turns that request tools, including malformed or provider-raw calls, are
excluded from memory extraction even when they contain visible text.

DeerMem remains the default local backend. An opt-in `mem0` backend is also
available for the hosted mem0 Platform API or API-compatible self-hosted
servers. Its token-bearing `base_url` must use HTTPS by default; plaintext HTTP
requires an explicit local-development opt-in. See the
[mem0 backend guide](backend/packages/harness/deerflow/agents/memory/backends/mem0/README.md).

An opt-in `honcho` backend is available for self-hosted or hosted Honcho (v3
API). It builds user-model memory — long-term preferences and a cross-session
working representation — on Honcho's server side, so the backend makes no LLM
calls locally. Each user gets an isolated workspace derived from `user_id`; a
missing user id fails closed instead of falling back to a shared workspace.
Fact CRUD and Settings-page fact editing are not available for this backend. See
the [Honcho backend guide](backend/packages/harness/deerflow/agents/memory/backends/honcho/README.md).

Memory updates now skip duplicate fact entries at apply time, so repeated preferences and context do not accumulate endlessly across sessions.
Legacy memory files are normalized when read or imported, including recoverable fact metadata, so older local data remains usable as the schema evolves. Frontend and backend normalization use confidence `0.5` when missing or invalid, default blank sources to `unknown`, and trim fact content.

In the default DeerMem `middleware` mode, automatic extraction now classifies every proposed fact by scope, durability, and authority before a deterministic write gate accepts it. Only durable, descriptive user-level facts are stored; current-thread or project constraints and one-time action permissions stay in conversation state. User-global summaries require both user scope and descriptive authority, contradiction removals are scope-gated, and a replacement-dependent removal is applied only when its replacement actually survives validation and storage. These classification labels are extraction-only metadata, add no extra LLM call, and are not written into the fact files. The explicit CRUD tools in `memory.mode: tool` remain a separate, model-directed path. Deployments that override the bundled DeerMem prompts via `memory.backend_config.prompts_dir` must add the new classification fields to their custom templates (the `memory_update` fact/summary/removal formats and the `consolidation` consolidated-fact schema): the write gate fails closed, so an un-migrated template stops every extraction-driven fact, summary, and removal write, surfacing only through the `rejected_by_scope_gate` metrics and the high-rejection-rate warning.

When a fact scope reaches `max_facts`, DeerMem still uses the historical confidence-only eviction order by default. Operators can opt in to `memory.backend_config.fact_eviction_policy: hybrid-v1`, which combines bounded confidence (65%), explicit-confirmation freshness (25%), and query-driven access heat (10%). Hybrid signal metadata is collected only while hybrid-v1 or shadow mode is enabled. Explicit confirmation is returned as `factsToReinforce` by the existing memory-update LLM call and is accepted only when deterministic message processing also detects a user reinforcement signal; it also resets the fact's staleness-review clock. This deterministic gate is batch-level: it establishes only that a human message among the last six filtered messages in the current extraction batch matched a reinforcement pattern. The LLM-selected `factsToReinforce` ID supplies the fact binding; DeerMem does not independently verify a signal-to-fact correspondence. Repeated extraction or automatic injection never confirms a fact. Custom `memory_update` prompts should add the optional `factsToReinforce` array to participate in confirmation freshness. Access heat is stored in a separate decaying sidecar and increases only when `memory_search` actually returns the fact, so reads do not rewrite canonical Markdown or its `updatedAt`. Hybrid mode also reserves a bounded minimum of correction slots (10% of the cap, at most 10; unused slots return to normal competition). Capacity deletion remains physical, but a bounded metadata-only audit records fact IDs, categories, policy scores, and reasons without copying fact content. `fact_eviction_shadow_enabled: true` evaluates hybrid-v1 alongside the default policy without changing actual retention. This feature adds no LLM invocation and can be rolled back by selecting `confidence`.

File-backed memory now separates global user context from agent facts. Each user has one `memory.json` containing only the project-independent `user` and `history` summaries; every fact is a canonical Markdown file below `agents/{agent_name}/facts/`. Existing lead-agent middleware, API, Settings, import/export, and embedded-client calls that omit `agent_name` resolve inside DeerMem to the reserved `__default__` bucket. That bucket is outside the valid custom-agent name grammar, so a real custom agent named `lead-agent` has a separate fact repository and deleting a custom agent cannot delete a memory-only directory without `config.yaml`. Public agent identifiers are case-insensitive and canonicalized to lowercase. Runtime/API readers still receive a compatibility `facts` array for the selected/default agent, so the frontend does not read agent facts from `memory.json`; structured Markdown `source` metadata is projected to the historical string field at the MemoryManager boundary. An unscoped Clear All first migrates facts from unread legacy per-agent JSON without adopting its soon-to-be-cleared summaries, then removes shared summaries and facts from every agent bucket while preserving agent configuration files, so a later read cannot resurrect skipped legacy facts; an explicitly agent-scoped clear removes only that agent's facts. On first normal read, old facts embedded in the user JSON are migrated automatically to `__default__`; facts written to the earlier implicit `lead-agent` bucket are also moved when that directory is not a real custom agent. Migration and normal writes notify the configured retrieval adapter only after durable storage locks are released. DeerMem uses a scope-aware SQLite FTS5/BM25 adapter by default, stores only rebuildable derived index data under `.retrieval/` (or under `memory.backend_config.retrieval_index_path` when set; a relative value resolves against `storage_path`), and rebuilds it in the background during Gateway startup or lazily on the first scoped search. A corrupt derived index is recreated automatically. When several Gateway instances share one `storage_path`, point `retrieval_index_path` at instance-local disk: SQLite's WAL mode is unsupported on network filesystems, each instance re-syncs a user's index on its next search after a peer writes, and a declared multi-instance deployment (`deployment.multi_instance: true` / `DEER_FLOW_MULTI_INSTANCE=1`) that leaves the index under the memory root logs a warning at startup. The Helm chart mounts a Pod-local `emptyDir` for it. Set `memory.backend_config.retrieval_adapter` to an empty string to disable it and use the local substring fallback. Chinese tokenization is optional; install the backend `memory-zh` extra (`uv sync --extra memory-zh`) for jieba-assisted sub-phrase search. Journaled writes, a shared user lock, and optimistic user-memory revisions prevent silent lost updates.

Set `memory.backend_config.retrieval_relevance_enabled: true` to opt into deterministic relevance/confidence ranking and query-aware injection. This **bypasses `retrieval_adapter` for search**, including the default FTS5/BM25 and custom adapters; indexing remains configured. `retrieval_relevance_weight` controls the blend and `retrieval_diversity_weight` enables near-duplicate penalties (default 0). Scoring uses at most the first 4096 characters and 128 tokens per query/fact. Search diversifies only up to `top_k`; injection diversifies guaranteed and regular facts independently until their token budgets are reached. Leave the feature disabled to retain the existing retrieval and injection behavior.

Lexical relevance measures IDF-weighted coverage of distinct query terms, so
repeated partial matches cannot tie a complete match merely by saturating the
score. Prefix matches require one complete token to prefix the other, not just
four shared characters. For uploads, query-aware injection uses the preserved
user request rather than the prepended file descriptions; attachment-only
messages retain query-less injection. Older custom memory backends can keep their existing `get_context`
signature: prompt injection and the inherited async wrapper pass `query` only
when that callable supports the keyword and the hint is not `None`.
Search and automatic injection use the same IDF weighting for the same
user/agent candidate scope. Category-filtered search and injection's separate
guaranteed/regular token budgets can still yield different final selections.

Memory injection follows the configured operation mode. In `middleware` mode, DeerMem injects the user-global summaries and the selected agent's facts. Custom-agent bootstrap conversations use that agent's fact bucket as well, so setup details do not leak into the default agent's memory. In `tool` mode, the automatic `<memory>` block contains only the global `user` and `history` summaries; agent facts are retrieved explicitly through `memory_search`, avoiding duplicate automatic and tool-returned fact context. Setting `memory.injection_enabled: false` still disables the entire block in either mode. When a fact ID is already known, `memory_get(fact_id)` returns that exact fact from the current user and agent scope without searching by content. Missing or out-of-scope IDs return a not-found error; backends without the required read or agent-scope capability return an unsupported error.

An individual Custom Agent can opt out of memory without changing the global setting. Add `memory_enabled: false` to that agent's `users/{user_id}/agents/{name}/config.yaml`. The agent still receives the current-date reminder, but DeerFlow does not inject recalled memory, queue passive or summarization-driven memory updates (including manual `/compact`), expose memory tools, or add memory-tool instructions for that agent. If an existing agent is switched off, its previously injected memory block is removed from checkpoint state before the next model call while its date reminder and conversation remain. Omitting the field (or setting it to `true`) preserves the existing global `memory` behavior.

Single-fact repository operations are genuinely incremental: an upsert/delete reads, journals, writes, and re-indexes only the addressed fact files, and returns an explicit incomplete delta rather than a cache-dependent fake full document. Summary change sets merge the supplied `user`/`history` child keys over the persisted sections so a partial update cannot erase omitted siblings; full imports normalize both sections to the complete compatibility schema before applying replacement values. Imports reject malformed fact lists or blank/non-text content with HTTP 400 before changing stored memory; recoverable legacy metadata still receives defaults. An explicit empty fact list remains an intentional clear. Manager/API compatibility methods materialize a fresh full document only when their public response contract requires one. Fact-level point operations use separate expected user-memory and fact revisions and may explicitly rebase when every addressed fact precondition still holds. Snapshot-derived operations such as scoped clear, capped create, consolidation, and trimming never replay stale delete/trim sets: a manifest conflict reloads the complete document and recomputes the operation, with a bounded retry. Fact paths use the first two hexadecimal characters of `SHA-256(fact_id)` so generated `fact_*` IDs distribute across shards. The cache token combines the shared JSON's nanosecond mtime, size, and persisted revision; this prevents coarse-mtime same-size writes from returning stale data without scanning fact files. Direct out-of-band Markdown edits require an explicit reload. Storage-specific conflicts and corruption are translated at the MemoryManager boundary; the Gateway returns conflict as HTTP 409 and a stable, non-sensitive corruption error as HTTP 500. Full-document `save()` remains a compatibility API and computes a diff before writing; malformed or missing `facts` can no longer silently erase an agent's Markdown files. Legacy migration preserves non-empty `user`/`history` before deleting an agent `memory.json`; conflicting summaries keep the legacy file and fail loudly instead of choosing a winner.

Legacy facts in `memory.json` migrate automatically into the reserved `__default__` Markdown bucket on the user's first normal memory read. Operators who prefer to audit or complete the migration before serving traffic can run the optional idempotent CLI from `backend/`:

```bash
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users --dry-run
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users
# A custom DeerMem root or original non-directory-safe identity can be explicit:
PYTHONPATH=. python scripts/migrate_memory_markdown.py --storage-path /path/to/deerflow-home --user-id 'test@example.com'
```

The v1-to-v2 storage migration is one-way for a running application: pre-PR code does not read Markdown facts. Before upgrading a persistent deployment, stop DeerFlow and take a filesystem snapshot or full backup of the configured memory storage root. The migration also durably retains each destructive JSON source beside the original path as `{manifest_filename}.v1.bak` before writing v2 data; an existing mismatched backup or a backup-write failure stops migration without modifying the v1 source. This local backup preserves pre-migration data but is not a substitute for a full snapshot and does not contain facts created after the upgrade.

`--user-id` may be repeated. `--all-users` discovers the existing directory-safe buckets below the selected storage root; standalone integrations that passed raw IDs containing characters such as `@` should use the original value with `--user-id`. A failed user's migration is reported without hiding the rest of the audit, and the command exits non-zero when any user fails. The automatic first-read path remains enabled, so running this CLI is not required for startup.

## Recommended Models

DeerFlow is model-agnostic — it works with any LLM that implements the OpenAI-compatible API. That said, it performs best with models that support:

- **Long context windows** (100k+ tokens) for deep research and multi-step tasks
- **Reasoning capabilities** for adaptive planning and complex decomposition
- **Multimodal inputs** for image understanding and video comprehension
- **Strong tool-use** for reliable function calling and structured outputs

MindIE XML tool-call arguments support signed, fractional, and exponent JSON
numbers. If a number overflows, underflows to zero, or exceeds Python's integer
digit limit, the complete argument stays a string, including nested JSON lists
and objects, so parsing does not silently change its value.

## Embedded Python Client

For `DeerFlowClient(agent_name="researcher")`, the named agent's `mcp_plugins`
selection applies to both the lead agent and its `task` / `batch_task`
delegations: `null` inherits all enabled MCP plugins, `[]` selects none, and
installation IDs select only those plugins. Call `client.reset_agent()` after
editing the saved agent configuration to refresh the selection.

`DeerFlowClient.stream()` includes `summary_text` in each `values` event. This is the current compacted context summary, or `None` when absent. Consumers can record changes without reading checkpoint internals; repeated snapshots may carry the same summary, and an initial snapshot may already contain one from an earlier turn.

DeerFlow can be used as an embedded Python library without running the full HTTP services. The `DeerFlowClient` provides direct in-process access to all agent and Gateway capabilities, returning the same response schemas as the HTTP Gateway API. The HTTP Gateway also exposes `DELETE /api/threads/{thread_id}` to remove DeerFlow-managed local thread data after the LangGraph thread itself has been deleted:

For database-backed run events, deleting a run preserves its thread's sequence watermark. Thread deletion removes that watermark once no events remain, allowing a recreated thread to restart at sequence 1. Owner-scoped deletion preserves the watermark when another owner's events remain.

Thread IDs may be supplied by callers and do not have to be UUIDs. Explicit
IDs must contain 1–64 ASCII letters, digits, hyphens, or underscores
(`^[A-Za-z0-9_-]{1,64}$`). DeerFlow generates a UUID only when `thread_id` is
omitted or `None`; an explicitly supplied empty string is invalid.
Existing route-addressable threads created under older, looser rules remain
readable and deletable, but cannot start new runs or create new filesystem or
sandbox state. Legacy deletion skips local path cleanup when the ID is not
safe under the canonical contract. For canonical legacy threads whose
conversation exists only in LangGraph checkpoints, DeerFlow seeds an empty
run-event feed from the checkpoint before the first new run so
`/messages/page` keeps both the old and new turns.

```python
from deerflow.client import DeerFlowClient

client = DeerFlowClient()

# Chat
response = client.chat("Analyze this paper for me", thread_id="my-thread")

# Streaming (LangGraph SSE protocol: values, messages-tuple, end)
for event in client.stream("hello"):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data["content"])
    elif event.type == "messages-tuple" and event.data.get("type") == "tool" and "artifact" in event.data:
        # Structured tool artifacts (for example, ask_clarification cards)
        # are preserved when the ToolMessage provides one.
        print(event.data["artifact"])

# Configuration & management — returns Gateway-aligned dicts
models = client.list_models()        # {"models": [...]}
skills = client.list_skills()        # {"skills": [...]}
client.update_skill("web-search", enabled=True)
client.upload_files("thread-1", ["./report.pdf"])  # {"success": True, "files": [...]}
client.set_goal("thread-1", "finish the implementation and make all tests pass")
client.get_goal("thread-1")       # {"goal": {...}} or {"goal": None}
client.clear_goal("thread-1")
```

When continuing a thread, `values` still contains the full conversation state, while `messages-tuple` and `end.usage` cover only the current turn.

The HTTP Gateway accepts `values`, `messages-tuple`, `updates`, `debug`, `tasks`, `checkpoints`, and `custom` stream modes. Unsupported modes such as `messages` and `events`, unsupported non-default run options such as webhooks, delayed execution, or `multitask_strategy="enqueue"`, and undeclared SDK options such as checkpoint durability overrides return `422` before execution instead of being silently ignored or downgraded.

All dict-returning methods are validated against Gateway Pydantic response models in CI (`TestGatewayConformance`), ensuring the embedded client stays in sync with the HTTP API schemas. See `backend/packages/harness/deerflow/client.py` for full API documentation.

## Projects

Projects group related conversations under a shared name, instructions, and
document shelf.

A conversation joins a project at creation time (when a project is selected) or
later through the move menu. Runs never modify membership: submitting a message
cannot assign or reassign a conversation. Moving a conversation out of a project
keeps it unassigned until it is explicitly moved again.

Moving a conversation refreshes its header affiliation as well as the project
lists, including when an older metadata request is still in flight.

Projects require the current database tables and columns. A database stamped
`0019_thread_incarnations` from the older 0018-based rollout is rejected at
startup if the project schema is missing. Follow the
[offline database recovery procedure](docs/database-forward-revision-recovery.md)
before starting this build against that database.

### Project instructions

Each project stores free-form instructions — background, conventions, and
constraints that apply to every conversation in the project — editable on the
project page's Instructions tab with a live byte counter. When a run starts on
a member thread, the Gateway pins the project's current state once and renders
the instructions as a bounded, request-scoped `<project>` block for that run
only: the block never enters the system prompt or persisted history, and every
new run sees the latest saved instructions. Instructions are capped at
`projects.instructions_max_bytes` UTF-8 bytes (default 8192, range 256–262144);
multi-byte characters count as their UTF-8 byte length. Oversized instructions
are rejected with a `422` at write time and are never silently truncated.

### Document shelf

Each project has a document shelf for files the whole project shares, managed
from the project page's Documents section:

- **Upload** a file (button or drag-drop, one file per request). Shelf size
  limits reuse `uploads.max_file_size` (default 50 MiB); re-uploading identical
  content returns the existing entry instead of creating a duplicate.
- **List** entries with name, size, modified time, and provenance (uploaded vs.
  saved from a conversation), and preview or download any entry.
- **Save to project** from a thread file: the read-only conversation-files
  browser below the shelf lists member threads' uploads and outputs, each with
  a Save to project action.
- **Attach to thread**: copy a shelf file into a thread's uploads through the
  normal ingestion pipeline, so the conversation can work with it directly.

New shelf names, including explicit upload `name` and promotion `shelf_name`,
follow ordinary upload filename validation. Names containing NUL, Windows
reserved device names (such as `CON.txt`), or trailing dots are rejected with
`400` before bytes are staged.

On native Windows, the document shelf uses extended-length filesystem paths
so deep workspace directories and long filenames can be uploaded, downloaded,
restored, and purged without enabling the system-wide long-path setting.
Filesystem limits on individual path components still apply.

Runs on member threads also receive a bounded `<documents>` index rendered per
run from the pinned snapshot (capped by `projects.shelf_index_max_entries` and
`projects.shelf_index_max_bytes`), and the agent can page the shelf and read
documents with the `list_project_documents` and `read_project_document` tools.

Document character counts use a bounded, thread-safe cache; concurrent reads
do not serialize full file scans behind its cache lock.

### Archive read semantics

Archiving a project freezes writes but keeps reads. Threads in an archived
project still run and still receive the project's instructions and shelf index,
and the shelf remains fully readable: listing, preview/download, the
conversation-files browser, and attach-to-thread all keep working. Uploads,
save-to-project, and moving individual shelf files to trash require an active
project, and a trashed document cannot be restored into an archived one.
Deleting an archived project remains allowed and moves its whole shelf to
trash.

### Trash

Deleting a shelf document moves it to trash instead of erasing it: the entry
keeps its bytes and a snapshot of its origin project for
`projects.trash_retention_days` (default 30) before the retention sweep may
purge it permanently. The `/workspace/trash` page — reachable from the project
page's Documents section and the sidebar Projects header — lists trashed
documents with their origin project and remaining retention, with per-entry
Restore and Delete permanently actions plus an Empty trash action that
permanently deletes every document in the trash — immediately, not after the
retention window; the window only bounds how long an entry may sit there
before the retention sweep reclaims it. Restore returns the document to its
origin project, or to a project you pick when the origin is gone or archived;
if the target already holds an identical active file, the entries merge.
Deleting a project moves its entire shelf to trash in the same step.

## Scheduled Tasks

DeerFlow now includes a first-class scheduled-task MVP in the workspace.

Editing a one-time task's title or prompt preserves its original execution time, including seconds and the selected occurrence during a daylight-saving clock rollback. Changing its date, time, or timezone recalculates the execution time. Switching tasks while editing loads the selected task's own title, prompt, and schedule.

Current MVP capabilities:

- Manage tasks at `/workspace/scheduled-tasks`
- One-time task forms reject local times skipped by daylight-saving transitions; select another time before creating or saving the task.
- Choose whether each scheduled task reuses a thread and its conversation history or creates a fresh thread per run
- Pin each task to `lead_agent` (default) or a custom agent the owner already has; unknown names are rejected
- Sending `assistant_id: null` in a scheduled-task PATCH resets the task to `lead_agent`; omitting `assistant_id` preserves the current agent, including when that custom agent has since been deleted
- Duplicate an existing task into the create form as an editable draft without copying its run history
- Support `once`, `cron`, and `interval` schedules
- Editing or duplicating an interval task preserves its saved cadence until the interval is explicitly changed, including sub-minute intervals allowed by the operator's scheduler configuration
- Run background scheduled executions as non-interactive DeerFlow runs (`ask_clarification` is not exposed there)
- Persist a due execution as `queued` when its reused thread or the global execution budget is busy, then launch it when capacity is available; queued occurrences survive Gateway restarts and fail after `scheduler.queue_timeout_seconds`
- Share execution slots fairly between task owners: one owner may have at most `scheduler.max_concurrent_runs_per_user` scheduled runs starting or running at a time (default 2, never more than `max_concurrent_runs`; `0` turns the per-owner cap off), and the waiting queue is drained owner by owner, so one owner's backlog never holds back another owner's run. A run that waits longer than `scheduler.queue_timeout_seconds` is skipped, and its history reads "Skipped: it waited too long for a free slot"
- Freeze a task's definition while an occurrence is `queued`, `launching`, or `running`, so a durable occurrence cannot silently pick up a different prompt, thread, or schedule; transitioning a task to paused or deleting it cancels an existing waiting occurrence, while `launching`/`running` work must finish before those mutations are retried and an explicit manual trigger may still wait and run without resuming a paused schedule
- Pause, resume, trigger, inspect history, and delete tasks
- Search task titles or prompts, combined with status/type filters and the current thread scope.
- Execute scheduled work through the normal DeerFlow run lifecycle
- When `channel_connections.enabled: true`, send scheduled task updates to the task owner's connected IM identities (outbox + delivery worker) on apps that support proactive push, which today is WeCom; Settings shows for each app whether updates are sent there, and other apps get none. Each occurrence sends at most one message: a finished, failed or goal-missed run, the automatic pause after three missed goals, a pause by the agent (its stop condition was met) or the task finishing (all `max_runs` done, `end_at` reached); when several apply, the pause or finish wins and still says how the last run went. A one-time task sends only its run's outcome. The message is queued in the same database transaction that records the outcome, so runs finalized after a crash or a lost lease notify exactly once. It reads on its own, in your web UI language (else `channel_connections.notification_locale`): the task title, what happened, a one-line result when the agent replied, and "Open DeerFlow → Scheduled tasks for details.", with no IDs and no links. Plain manual "run now" trials and interrupted runs stay silent, and so do occurrences that end without a finished run (launch error, queue timeout, interrupted by a restart). Channel/transport outages park deliveries without exhausting retries, for up to about a day; platform rejections retry for roughly 15 minutes before settling as `failed`. An identity you disconnect while a delivery is waiting is never pushed to: the row is dropped as `failed`.
- Browse execution history in pages of 50; older pages pause automatic refresh, with an explicit return to the latest runs. Counts appear only after a successful read; loading and failed reads are not reported as zero runs.

Derived run summaries omit leading inline `<think>` reasoning before limiting the text, so a long thought does not replace the actual answer in previews or scheduled notices. Original response history and literal tags in the answer are unchanged; previously stored run summaries are not rewritten.

**Filter execution history through the API**

To inspect failures without downloading every successful occurrence, authenticated clients with `threads:read` can request `GET /api/scheduled-tasks/{task_id}/runs?status=failed&limit=50&offset=0` for an owned task. The optional `status` accepts `queued`, `launching`, `running`, `success`, `failed`, `skipped`, `interrupted`, or `unmet`; these are occurrence statuses, so task statuses such as `completed` are invalid (422).

Filtering happens before pagination. `limit` (1–200, default 50) and `offset` (nonnegative, default 0) apply to matching records, ordered by creation time then ID, both descending. Omitting `status` preserves the existing mixed-history array response; no matches return `[]`. The API does not change task execution, and the workspace history UI remains unfiltered.

Current MVP limits:

- No text-only notification jobs
- No channel or GitHub dispatch targets (result push above is not a dispatch target)

Enable background polling with `config.yaml -> scheduler.enabled`. Manual trigger uses the same scheduled-task resource and execution path.

### Lifecycle, safety caps and stop conditions

- The tasks page and the REST API (`POST` / `PATCH /api/scheduled-tasks`) accept the same per-run goal (`goal_objective`), safety cap (`max_runs`, `end_at`) and stop condition (`stop_condition`) as a conversation. Sending `null` in a PATCH clears any of these four; an `end_at` without a UTC offset is wall-clock time in the task's timezone.
- A stop condition is the user's "stop when …" rule. It is stored in its own field (migration `0031`), never inside the task instructions. Only when a run starts does DeerFlow append it to that run's message and ask the run to call `stop_scheduled_task` when the rule holds. While `scheduler.tool_enabled` is on, every scheduled run can stop its own schedule, whether a chat or the tasks page created the task; with it off, the run is asked to report a met rule instead of calling a tool it does not have.
- Goal tasks created on the tasks page are now evaluated like chat-created ones, and their runs also receive the saved notes and the previous-run reference.
- Resume computes the next run from now, so a long pause never causes a catch-up run. A one-time task whose time has passed returns `422 once_time_passed` and needs a new time. Resuming an active task changes nothing; pausing a finished task returns `409 task_finished`.
- `max_runs` is a lifetime total of automatic runs; trial runs never count. Reactivating a task whose cap is used up (Resume, or a PATCH that re-arms a finished task's schedule) returns `409 limits_exhausted` unless the same request renews the limit that ran out: a used-up run limit needs a higher `max_runs` or `null`, a passed end time needs a later `end_at` or `null` (a later `end_at` alone does not renew a used-up `max_runs`). `POST /api/scheduled-tasks/{task_id}/resume` accepts an optional `{"max_runs": …, "end_at": …}` body for that (`null` clears a cap; chat-created sub-hourly tasks must keep one). A PATCH that only changes the cap of a finished task saves it and leaves the task finished.
- Goal-check failures (the evaluator failed, or the conversation changed during the check) neither count toward the three-miss automatic pause nor reset it. Changing the goal, the instructions or the stop condition, or adding a note, starts a new count; Resume keeps it.
- While this Gateway process's scheduler is not running, creating a task (including Duplicate) returns `409 scheduler_not_running`, because the task would never run on schedule. `GET /api/features` reports `scheduled_tasks.available`, `running`, `tool_enabled` and `min_interval_seconds`.
- Errors from `/api/scheduled-tasks*` are `{"detail": {"code", "message", "params"}}`; see [`backend/docs/API.md`](backend/docs/API.md#scheduled-tasks) and `contracts/scheduled_task_errors_contract.json`.

### Create schedules in a conversation

Set both `scheduler.enabled: true` and `scheduler.tool_enabled: true`, then restart
Gateway. An authorized interactive turn can use `schedule_task` to create, update,
list, pause, resume or delete tasks, start a trial run, or save a note. For
example: “Every weekday at 9:00, check release-checklist.md and tell me what is
still unchecked; stop when everything is checked.” In the web app the result is a
live card with the schedule, the stop condition and buttons, and the agent
replies in one or two sentences; IM and other non-web turns describe the
schedule, the next run and the stop condition in plain text.

- **Which tasks a conversation manages.** The tasks created in it, and, in a run
  conversation (the chat a scheduled run posted into), the task that run belongs
  to: “pause this” or “move it to 10:00” work there too. This applies only to
  turns you send. A scheduled run itself can only pause its own schedule with
  `stop_scheduled_task`.
- **Edits keep the task.** Changing the time, instructions, goal, stop condition
  or safety cap is an `update` of the same task, so its ID and run history stay.
  `resume` restarts a paused or finished task without a catch-up run. When the
  cap is used up, the agent asks how to renew the limit that ran out (a higher
  `max_runs` or none; a later `end_at` or none) and sends that with the resume.
- **Timezone.** A zone you name wins. Otherwise a new task uses the browser
  timezone the web app sends with each message (`context.client_timezone`, read
  only for this), and the result says which zone was used. Intervals and
  one-time times with a UTC offset need no zone; for a cron schedule or a local
  one-time time with no known zone (for example from IM), the agent asks. Edits
  keep the saved zone; the browser zone never changes an existing task.
- **Where results appear.** Each run posts its result in a new chat of its own,
  titled “{task} · {local time}”, or in the originating chat when the task runs
  there. When the schedule is paused by the agent, is paused automatically or
  finishes, the originating chat shows one line where the conversation stood,
  with a link to that run or to the task; nothing else is posted back to it.
  The line stays after the task is deleted. A run chat shows the task
  instructions as one collapsed “Task instructions” block under the run's
  header instead of a long user message.
- **Language.** The agent writes the title, instructions and stop condition in
  your language, and scheduled runs answer in the language of the instructions.

New tasks default to a fresh conversation for each occurrence. A configured
`goal_objective` applies only to that occurrence: success does not stop a
recurring schedule. The running agent can request `stop_scheduled_task` for its
own schedule when your stop condition has been met; the request takes
effect during terminal finalization. `max_runs` counts automatic launches only,
and `end_at` provides a deadline. Either end condition takes precedence over a
pause request. Tool-created sub-hourly schedules require an end condition; each
owner may keep at most 20 live tool-created tasks, including paused tasks.

An unmet occurrence is recorded as `unmet`, distinct from an execution failure.
Three eligible automatic unmet occurrences pause a recurring task. Accepted
success resets the streak, including a success relying on disclosed assumptions;
manual trials, interruption, execution failure, external waiting and
goal-check failures do not advance it. Resume retains the streak, so another eligible unmet occurrence can
pause the task again. Connected IM apps with proactive push receive one notice
per occurrence through the same durable outbox (goal missed, auto-paused, paused
by the agent, finished); plain manual trials stay silent.

You can ask the agent in a conversation that manages the task to save an
explicit note for future runs (at most 10 notes of 500 characters). Fresh
recurring runs may read the previous executed occurrence through opt-in
`read_conversation`, with the same owner and read-permission checks. This
provides a source reference, not an automatic summary or a post-back into the
originating chat.

For a trial, ask directly, for example “Run it now”, “OK, run it now” or
“先跑一次吧”; in the web app the card's **Run once now** button does the same.
The host accepts a bounded set of English/Chinese direct-run requests from the
current user turn, optionally after a short acknowledgement such as “Sure,” or
“好的，”. A bare “yes” or “好”, task mentions, and quoted or conditional requests
do not start a paid run. When a run is already waiting to start, no extra trial
is added and the agent says so. A trial does not count toward `max_runs`.

A goal occurrence can use up to nine agent turns, with an evaluator request after
each. Evaluator requests and provider-reported tokens are included in run usage;
missing usage makes the corresponding cost estimate unknown. `token_budget`
limits the main graph and is checked after model calls; evaluator usage is
additional, so it is not a strict whole-run or dollar limit.

**Goal evaluation upgrade:** existing scheduled, webhook and autonomous goal
runs can accept disclosed low-risk, reversible assumptions and record
`relied_on_assumption` in their verdict. Interactive goal evaluation remains
strict. This policy also applies when conversation schedule tools are disabled;
it does not authorize sensitive actions or substitute for user authorization.


Scheduled runs use `scheduler.recursion_limit` in `config.yaml` (default `1000`, matching the web UI's interactive budget). Values above `max_recursion_limit` are clamped. This field is read at dispatch, so the next scheduled run picks it up without a Gateway restart.

The background scheduler is single-instance by default. For a multi-pod deployment, set `scheduler.multi_instance: true` and use shared Postgres, `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`; startup and periodic recovery then preserve live peer runs, atomically return expired launch claims to the queue, take over only expired run leases, and fence stale launch writes. `max_concurrent_runs` is a shared global cap across Pods for `launching`/`running` occurrences; waiting `queued` rows do not consume it. Without those settings, enable the scheduler on exactly one Gateway pod. These scheduler fields are startup-only; restart all Gateway Pods together when changing them.

### Preview cron occurrences through the API

Authenticated clients with `threads:read` can call `POST /api/scheduled-tasks/preview-cron` before creating a task:

```json
{"cron":"0 9 * * 1-5","timezone":"Asia/Shanghai","count":3,"start_at":"2026-09-12T00:00:00Z"}
```

The response contains normalized `cron`, `timezone`, the effective UTC `start_at`, and `occurrences` with UTC `run_at` and offset-bearing `local_time`. In this example the first occurrence is `2026-09-14T01:00:00Z` / `2026-09-14T09:00:00+08:00`.

`count` is an integer from 1 to 10 (default 5). `start_at` must include a timezone; omit it to capture server time once. Cron expressions use the scheduler's five-field syntax (maximum 256 characters); timezone names are at most 128 characters. Invalid inputs or schedules without the requested future occurrences return 422. Preview shares the scheduler's DST behavior, creates no task, thread or run, and does not reserve execution. This is an API capability; the workspace form does not yet display these occurrences.

### Upgrade Notes

- Occurrence ordering applies to rows admitted by upgraded Gateway instances, which project only sequenced occurrences onto the parent task and defer recovery while any occurrence is still live, whichever instance admitted it; a task whose history is entirely unsequenced keeps the previous timestamp ordering until its first sequenced admission. During a rolling upgrade, rows admitted by pre-upgrade instances are projected by those instances themselves, as before the upgrade, and the ordering guarantees hold once every Gateway writer runs the upgraded version. Existing history is not backfilled; the upgrade does not reconstruct past order or repair historical counts.
- Before upgrading a deployment with `GATEWAY_WORKERS > 1` and `scheduler.enabled: true`, either keep the scheduler on exactly one Gateway worker or configure `scheduler.multi_instance: true` with shared Postgres, `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`. The upgraded Gateway rejects the unsafe combination at startup instead of starting silently.
- In multi-instance mode, `scheduler.max_concurrent_runs` is a cluster-wide execution cap, not a per-Pod cap. It includes `launching` and `running` scheduled occurrences, so capacity does not multiply with the number of replicas; durable waiting rows remain outside the cap.
- `scheduler.multi_instance` and the related scheduler, ownership, and run-event settings are startup-only. Apply changes with a coordinated restart of all Gateway Pods; changing the ConfigMap alone does not activate multi-instance recovery.

## Terminal Workbench (TUI)

`deerflow` is a terminal-native workbench for people who live in the shell. It runs **embedded** over `DeerFlowClient` — no Gateway, frontend, nginx, or Docker required — while honoring the same `config.yaml`, checkpointer, skills, memory, MCP, and sandbox settings as the rest of DeerFlow.

Parallel synchronous stdio MCP calls use independent sessions on their own event
loops. They do not cancel each other's connections, but they do not share
server-side state; session reuse requires the same loop. See the
[MCP session notes](backend/docs/MCP_SERVER.md) for details.
Manually managed event loops must drain pending session owners before closing;
the normal `asyncio.run()` path does this automatically.

![DeerFlow TUI](docs/tui/tui-preview.svg)

```bash
uv pip install 'deerflow-harness[tui]'        # optional 'textual' dependency

deerflow                                      # launch the terminal UI (TTY required)
deerflow --tui-transparent                    # use the terminal's default background
deerflow --continue                           # resume the most recent thread
deerflow --resume THREAD                      # resume a thread by id
deerflow --print "summarize this repo"        # headless one-shot answer to stdout
deerflow --json  "hello"                       # headless newline-delimited StreamEvents; failure -> one {"type": "error"} record, exit 1
deerflow --recursion-limit 250 --print "task" # override the headless agent-loop limit
```

Headless `--print` and `--json` exit with status `1` when the run fails, including provider errors returned as fallback messages. `--print` still writes the fallback text to stdout; `--json` appends a terminal error record.

A keyboard-driven chat surface with a streaming transcript (Markdown-rendered answers), compact tool-activity cards, a `/` slash-command palette, display-only `/clear`, `/goal` goal management, `/model` and `/threads` pickers, input history, PageUp/PageDown transcript navigation, and `Esc` / `Ctrl+C` interrupt. The composer preserves line breaks and indentation in pasted code, stack traces, and multi-paragraph prompts; `Enter` sends the complete document. Transcript refreshes preserve your reading position after you scroll upward and resume following new output when you return to the bottom. `/clear` removes rows from the current terminal display without deleting the thread or its persisted conversation; `/new` and `/clear` ask you to wait during an active run instead of resetting in-flight display state. Sessions opened in the TUI also appear in the Web UI sidebar — it writes the shared thread store under the local default user, so terminal and web stay in sync **without running the Gateway**.

During an active run, `/resume`, `/threads`, and `/switch` ask you to wait before
switching conversations. An invalid `/resume` reference displays an error without
closing the TUI or changing the current conversation.
After an interrupt, late stream actions from the previous run cannot change the
next run's display or status, even when both prompts use the same conversation.
A tool call already in progress still finishes, so until it does a new prompt in
that conversation is held back with a notice instead of racing it; `/new` and
`/resume` stay available.
If a run cannot start, the TUI reports an error and returns to idle so you can retry.

At the last composer row, `Down` leaves an unsent draft untouched unless you are
browsing input history; after recalling history, it moves forward to restore your
saved draft.

At the first composer row, `Up` also leaves the draft, cursor, and undo history
untouched when no input history is available.
Recalling identical history text or a saved draft also preserves the cursor and
undo history.

See [backend/docs/TUI.md](backend/docs/TUI.md) for the full guide.

## Documentation

- [Contributing Guide](CONTRIBUTING.md) - Development environment setup and workflow
- [Configuration Guide](backend/docs/CONFIGURATION.md) - Setup and configuration instructions
- [Architecture Overview](backend/CLAUDE.md) - Technical architecture details
- [Backend Architecture](backend/README.md) - Backend architecture and API reference

## ⚠️ Security Notice

### Improper Deployment May Introduce Security Risks

DeerFlow has key high-privilege capabilities including **system command execution, resource operations, and business logic invocation**, and is designed by default to be **deployed in a local trusted environment (accessible only via the 127.0.0.1 loopback interface)**. If you deploy the agent in untrusted environments — such as LAN networks, public cloud servers, or other multi-endpoint accessible environments — without strict security measures, it may introduce security risks, including:

- **Unauthorized illegal invocation**: Agent functionality could be discovered by unauthorized third parties or malicious internet scanners, triggering bulk unauthorized requests that execute high-risk operations such as system commands and file read/write, potentially causing serious security consequences.
- **Compliance and legal risks**: If the agent is illegally invoked to conduct cyberattacks, data theft, or other illegal activities, it may result in legal liability and compliance risks.

### Gateway Admin Is Equivalent to Code Execution

An admin can register stdio MCP servers, which run commands inside the Gateway
container. The API restricts them to an allowlist (`npx`, `uvx` by default,
extended via `DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST`) and rejects arguments and
environment variables that would evaluate arbitrary code. That is defense in
depth, not a boundary: these launchers exist to fetch and run remote packages,
so **treat Gateway admin as equivalent to code execution on the host** and grant
it accordingly.

### External Chat Message Roles

Gateway run requests and manual thread-state updates reject client-supplied
`system` / `developer` messages with HTTP 400, including equivalent serialized
message forms. Ordinary chat, attachments, and assistant/tool history replay
remain supported. Session or PAT authentication does not grant system-prompt
authority; trusted internal run producers retain that ability.

This check prevents new role injection; it does not rewrite existing
checkpoints. If an older version accepted an injected system message, use a
fresh thread or have an operator review and clean the affected state. Restarting
the service does not remove persisted instructions, and restoring an older
checkpoint can restore them.

For local verification, run `python backend/tests/poc_external_system_message_injection.py --help`.
The same opt-in PoC supports `--expect vulnerable` on an isolated old revision
and `--expect blocked` after the fix. Its help includes PAT creation, thread-ID
selection, browser follow-up, and the distinction between persistence and model
obedience. Use a fresh disposable thread for each run; the test appends messages.

On an isolated unfixed checkout, `--expect vulnerable` demonstrates acceptance
only when the request returns 200 and the exact injected message remains in the
checkpoint as `type=system` across a normal follow-up. A marker in a web answer
is model-dependent and is not evidence by itself that the role was promoted.
After applying the fix, run the same script with `--expect blocked`: it requires
the specific role-rejection 400, an unchanged checkpoint, a successful ordinary
follow-up, and absence of the rejected message IDs. Other 400 responses and
authentication, conflict, or server errors are inconclusive rather than passes.

The PoC does not clean up automatically. When verification is complete, delete
the disposable chat with the web sidebar's delete action and revoke the
short-lived PAT if one was created. Restarting the service does not remove a
persisted injected instruction.

### Deployment Defaults

The Docker stack publishes its entry port on `127.0.0.1` only, matching the
local-trusted-environment model described above. To reach it from another
machine, set `BIND_HOST` in `.env` (e.g. `BIND_HOST=0.0.0.0`) — and only after
putting the security measures below in place.

**Complete first-run setup before the host becomes reachable.** A fresh
instance has no accounts yet, so create the admin account through `/setup`
immediately after starting any deployment that is not loopback-only.

### Security Recommendations

**Note: We strongly recommend deploying DeerFlow in a local trusted network environment.** If you need cross-device or cross-network deployment, you must implement strict security measures, such as:

- **IP allowlist**: Use `iptables`, or deploy hardware firewalls / switches with Access Control Lists (ACL), to **configure IP allowlist rules** and deny access from all other IP addresses.
- **Authentication gateway**: Configure a reverse proxy (e.g., nginx) and **enable strong pre-authentication**, blocking any unauthenticated access.
- **Network isolation**: Where possible, place the agent and trusted devices in the **same dedicated VLAN**, isolated from other network devices.
- **Stay updated**: Continue to follow DeerFlow's security feature updates.

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, workflow, and guidelines.

Backend `make test` runs four duration-balanced shards concurrently and reports
failure if any shard fails. Use `make test TEST_JOBS=1` to run the shards sequentially.
It excludes live external-API and blocking-I/O coverage.
Run `cd backend && make test-blocking-io` for strict blocking-I/O checks.
Maintainers can run the real `DeerFlowClient` suite with `cd backend && make test-live`.
This command requires a valid root `config.yaml` and API credentials.
It can incur API costs and create local sandboxes, artifacts, or files.
Direct pytest runs additionally require `DEER_FLOW_RUN_LIVE_TESTS=1`.

Regression coverage includes Docker sandbox mode detection and provisioner kubeconfig-path handling tests in `backend/tests/`.
Backend blocking-IO diagnostics are available from the repository root with
`make detect-blocking-io`: it statically scans backend business code for
blocking IO that may run on the backend event loop, prints a concise summary,
and writes complete JSON findings to `.deer-flow/blocking-io-findings.json`.
The JSON includes compact review records with `priority`, `location`,
`blocking_call`, `event_loop_exposure`, `reason`, and `code`.
Gateway artifact serving now forces active web content types (`text/html` and XML documents such as `.xml`, `.xhtml`, and `.svg`) to download as attachments instead of inline rendering, reducing XSS risk for generated artifacts.

Frontend route asset budgets can be checked with `cd frontend && pnpm
perf:check`. The command measures `/login` from a normal production build, then
performs a production static-demo build for the fixture-backed workspace routes.
It measures the unique JavaScript and CSS referenced by representative routes
and writes the detailed result to `.next/performance-results.json`.

## License

This project is open source and available under the [MIT License](./LICENSE).

## Acknowledgments

DeerFlow is built upon the incredible work of the open-source community. We are deeply grateful to all the projects and contributors whose efforts have made DeerFlow possible. Truly, we stand on the shoulders of giants.

We would like to extend our sincere appreciation to the following projects for their invaluable contributions:

- **[LangChain](https://github.com/langchain-ai/langchain)**: Their exceptional framework powers our LLM interactions and chains, enabling seamless integration and functionality.
- **[LangGraph](https://github.com/langchain-ai/langgraph)**: Their innovative approach to multi-agent orchestration has been instrumental in enabling DeerFlow's sophisticated workflows.

These projects exemplify the transformative power of open-source collaboration, and we are proud to build upon their foundations.

### Key Contributors

A heartfelt thank you goes out to the core authors of `DeerFlow`, whose vision, passion, and dedication have brought this project to life:

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

Your unwavering commitment and expertise have been the driving force behind DeerFlow's success. We are honored to have you at the helm of this journey.

## Star History

[![Star History Chart](https://star-history.dera.page/svg?repos=bytedance/deer-flow&type=Date)](https://star-history.dera.page/#bytedance/deer-flow&Date)

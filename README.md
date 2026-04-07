# 🦌 DeerFlow - 2.0

English | [中文](./README_zh.md) | [日本語](./README_ja.md) | [Français](./README_fr.md) | [Русский](./README_ru.md)

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

[<img width="2880" height="1600" alt="image" src="https://github.com/user-attachments/assets/a598c49f-3b2f-41ea-a052-05e21349188a" />](https://deerflow.tech)

Learn more and see **real demos** on our [**official website**](https://deerflow.tech).

## Coding Plan from ByteDance Volcengine

<img width="4808" height="2400" alt="英文方舟" src="https://github.com/user-attachments/assets/2ecc7b9d-50be-4185-b1f7-5542d222fb2d" />

- We strongly recommend using Doubao-Seed-2.0-Code, DeepSeek v3.2 and Kimi 2.5 to run DeerFlow
- [Learn more](https://www.byteplus.com/en/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)
- [中国大陆地区的开发者请点击这里](https://www.volcengine.com/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)

## InfoQuest

DeerFlow has newly integrated the intelligent search and crawling toolset independently developed by BytePlus--[InfoQuest (supports free online experience)](https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest)

<a href="https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest" target="_blank">
  <img
    src="https://sf16-sg.tiktokcdn.com/obj/eden-sg/hubseh7bsbps/20251208-160108.png"   alt="InfoQuest_banner"
  />
</a>

---

## Table of Contents

- [🦌 DeerFlow - 2.0](#-deerflow---20)
  - [Official Website](#official-website)
  - [Coding Plan from ByteDance Volcengine](#coding-plan-from-bytedance-volcengine)
  - [InfoQuest](#infoquest)
  - [Table of Contents](#table-of-contents)
  - [One-Line Agent Setup](#one-line-agent-setup)
  - [Quick Start](#quick-start)
    - [Configuration](#configuration)
    - [Running the Application](#running-the-application)
      - [Option 1: Docker (Recommended)](#option-1-docker-recommended)
      - [Option 2: Local Development](#option-2-local-development)
    - [Advanced](#advanced)
      - [Sandbox Mode](#sandbox-mode)
      - [MCP Server](#mcp-server)
      - [IM Channels](#im-channels)
      - [LangSmith Tracing](#langsmith-tracing)
      - [Langfuse Tracing](#langfuse-tracing)
      - [Using Both Providers](#using-both-providers)
  - [From Deep Research to Super Agent Harness](#from-deep-research-to-super-agent-harness)
  - [Core Features](#core-features)
    - [Skills \& Tools](#skills--tools)
      - [Claude Code Integration](#claude-code-integration)
    - [Sub-Agents](#sub-agents)
    - [Sandbox \& File System](#sandbox--file-system)
    - [Context Engineering](#context-engineering)
    - [Long-Term Memory](#long-term-memory)
  - [Recommended Models](#recommended-models)
  - [Embedded Python Client](#embedded-python-client)
  - [Documentation](#documentation)
  - [⚠️ Security Notice](#️-security-notice)
    - [Improper Deployment May Introduce Security Risks](#improper-deployment-may-introduce-security-risks)
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

1. **Clone the DeerFlow repository**

   ```bash
   git clone https://github.com/bytedance/deer-flow.git
   cd deer-flow
   ```

2. **Generate local configuration files**

   From the project root directory (`deer-flow/`), run:

   ```bash
   make config
   ```

   This command creates local configuration files based on the provided example templates.

3. **Configure your preferred model(s)**

   Edit `config.yaml` and define at least one model:

   ```yaml
   models:
     - name: gpt-4                       # Internal identifier
       display_name: GPT-4               # Human-readable name
       use: langchain_openai:ChatOpenAI  # LangChain class path
       model: gpt-4                      # Model identifier for API
       api_key: $OPENAI_API_KEY          # API key (recommended: use env var)
       max_tokens: 4096                  # Maximum tokens per request
       temperature: 0.7                  # Sampling temperature

     - name: openrouter-gemini-2.5-flash
       display_name: Gemini 2.5 Flash (OpenRouter)
       use: langchain_openai:ChatOpenAI
       model: google/gemini-2.5-flash-preview
       api_key: $OPENAI_API_KEY          # OpenRouter still uses the OpenAI-compatible field name here
       base_url: https://openrouter.ai/api/v1

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

   To route OpenAI models through `/v1/responses`, keep using `langchain_openai:ChatOpenAI` and set `use_responses_api: true` with `output_version: responses/v1`.

   For vLLM 0.19.0, use `deerflow.models.vllm_provider:VllmChatModel`. For Qwen-style reasoning models, DeerFlow toggles reasoning with `extra_body.chat_template_kwargs.enable_thinking` and preserves vLLM's non-standard `reasoning` field across multi-turn tool-call conversations. Legacy `thinking` configs are normalized automatically for backward compatibility. Reasoning models may also require the server to be started with `--reasoning-parser ...`. If your local vLLM deployment accepts any non-empty API key, you can still set `VLLM_API_KEY` to a placeholder value.

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

   - Codex CLI reads `~/.codex/auth.json`
   - The Codex Responses endpoint currently rejects `max_tokens` and `max_output_tokens`, so `CodexChatModel` does not expose a request-level token cap
   - Claude Code accepts `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`, `CLAUDE_CODE_CREDENTIALS_PATH`, or plaintext `~/.claude/.credentials.json`
   - ACP agent entries are separate from model providers. If you configure `acp_agents.codex`, point it at a Codex ACP adapter such as `npx -y @zed-industries/codex-acp`; the standard `codex` CLI binary is not ACP-compatible by itself
   - On macOS, DeerFlow does not probe Keychain automatically. Export Claude Code auth explicitly if needed:

   ```bash
   eval "$(python3 scripts/export_claude_code_oauth.py --print-export)"
   ```
   
4. **Set API keys for your configured model(s)**

   Choose one of the following methods:

- Option A: Edit the `.env` file in the project root (Recommended)


   ```bash
   TAVILY_API_KEY=your-tavily-api-key
   OPENAI_API_KEY=your-openai-api-key
   # OpenRouter also uses OPENAI_API_KEY when your config uses langchain_openai:ChatOpenAI + base_url.
   # Add other provider keys as needed
   INFOQUEST_API_KEY=your-infoquest-api-key
   ```

- Option B: Export environment variables in your shell

   ```bash
   export OPENAI_API_KEY=your-openai-api-key
   ```

   For CLI-backed providers:
   - Codex CLI: `~/.codex/auth.json`
   - Claude Code OAuth: explicit env/file handoff or `~/.claude/.credentials.json`

- Option C: Edit `config.yaml` directly (Not recommended for production)

   ```yaml
   models:
     - name: gpt-4
       api_key: your-actual-api-key-here  # Replace placeholder
   ```

### Running the Application

#### Option 1: Docker (Recommended)

**Development** (hot-reload, source mounts):

```bash
make docker-init    # Pull sandbox image (only once or when image updates)
make docker-start   # Start services (auto-detects sandbox mode from config.yaml)
```

`make docker-start` starts `provisioner` only when `config.yaml` uses provisioner mode (`sandbox.use: deerflow.community.aio_sandbox:AioSandboxProvider` with `provisioner_url`).

Docker builds use the upstream `uv` registry by default. If you need faster mirrors in restricted networks, export `UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` and `NPM_REGISTRY=https://registry.npmmirror.com` before running `make docker-init` or `make docker-start`.

Backend processes automatically pick up `config.yaml` changes on the next config access, so model metadata updates do not require a manual restart during development.

> [!TIP]
> On Linux, if Docker-based commands fail with `permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock`, add your user to the `docker` group and re-login before retrying. See [CONTRIBUTING.md](CONTRIBUTING.md#linux-docker-daemon-permission-denied) for the full fix.

**Production** (builds images locally, mounts runtime config and data):

```bash
make up     # Build images and start all production services
make down   # Stop and remove containers
```

> [!NOTE]
> The LangGraph agent server currently runs via `langgraph dev` (the open-source CLI server).

Access: http://localhost:2026

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed Docker development guide.

#### Option 2: Local Development

If you prefer running services locally:

Prerequisite: complete the "Configuration" steps above first (`make config` and model API keys). `make dev` requires a valid configuration file (defaults to `config.yaml` in the project root; can be overridden via `DEER_FLOW_CONFIG_PATH`).
On Windows, run the local development flow from Git Bash. Native `cmd.exe` and PowerShell shells are not supported for the bash-based service scripts, and WSL is not guaranteed because some scripts rely on Git for Windows utilities such as `cygpath`.

1. **Check prerequisites**:
   ```bash
   make check  # Verifies Node.js 22+, pnpm, uv, nginx
   ```

2. **Install dependencies**:
   ```bash
   make install  # Install backend + frontend dependencies
   ```

3. **(Optional) Pre-pull sandbox image**:
   ```bash
   # Recommended if using Docker/Container-based sandbox
   make setup-sandbox
   ```

4. **(Optional) Load sample memory data for local review**:
   ```bash
   python scripts/load_memory_sample.py
   ```
   This copies the sample fixture into the default local runtime memory file so reviewers can immediately test `Settings > Memory`.
   See [backend/docs/MEMORY_SETTINGS_REVIEW.md](backend/docs/MEMORY_SETTINGS_REVIEW.md) for the shortest review flow.

5. **Start services**:
   ```bash
   make dev
   ```

6. **Access**: http://localhost:2026

#### Startup Modes

DeerFlow supports multiple startup modes across two dimensions:

- **Dev / Prod** — dev enables hot-reload; prod uses pre-built frontend
- **Standard / Gateway** — standard uses a separate LangGraph server (4 processes); Gateway mode (experimental) embeds the agent runtime in the Gateway API (3 processes)

| | **Local Foreground** | **Local Daemon** | **Docker Dev** | **Docker Prod** |
|---|---|---|---|---|
| **Dev** | `./scripts/serve.sh --dev`<br/>`make dev` | `./scripts/serve.sh --dev --daemon`<br/>`make dev-daemon` | `./scripts/docker.sh start`<br/>`make docker-start` | — |
| **Dev + Gateway** | `./scripts/serve.sh --dev --gateway`<br/>`make dev-pro` | `./scripts/serve.sh --dev --gateway --daemon`<br/>`make dev-daemon-pro` | `./scripts/docker.sh start --gateway`<br/>`make docker-start-pro` | — |
| **Prod** | `./scripts/serve.sh --prod`<br/>`make start` | `./scripts/serve.sh --prod --daemon`<br/>`make start-daemon` | — | `./scripts/deploy.sh`<br/>`make up` |
| **Prod + Gateway** | `./scripts/serve.sh --prod --gateway`<br/>`make start-pro` | `./scripts/serve.sh --prod --gateway --daemon`<br/>`make start-daemon-pro` | — | `./scripts/deploy.sh --gateway`<br/>`make up-pro` |

| Action | Local | Docker Dev | Docker Prod |
|---|---|---|---|
| **Stop** | `./scripts/serve.sh --stop`<br/>`make stop` | `./scripts/docker.sh stop`<br/>`make docker-stop` | `./scripts/deploy.sh down`<br/>`make down` |
| **Restart** | `./scripts/serve.sh --restart [flags]` | `./scripts/docker.sh restart` | — |

> **Gateway mode** eliminates the LangGraph server process — the Gateway API handles agent execution directly via async tasks, managing its own concurrency.

#### Why Gateway Mode?

In standard mode, DeerFlow runs a dedicated [LangGraph Platform](https://langchain-ai.github.io/langgraph/) server alongside the Gateway API. This architecture works well but has trade-offs:

| | Standard Mode | Gateway Mode |
|---|---|---|
| **Architecture** | Gateway (REST API) + LangGraph (agent runtime) | Gateway embeds agent runtime |
| **Concurrency** | `--n-jobs-per-worker` per worker (requires license) | `--workers` × async tasks (no per-worker cap) |
| **Containers / Processes** | 4 (frontend, gateway, langgraph, nginx) | 3 (frontend, gateway, nginx) |
| **Resource usage** | Higher (two Python runtimes) | Lower (single Python runtime) |
| **LangGraph Platform license** | Required for production images | Not required |
| **Cold start** | Slower (two services to initialize) | Faster |

Both modes are functionally equivalent — the same agents, tools, and skills work in either mode.

#### Docker Production Deployment

`deploy.sh` supports building and starting separately. Images are mode-agnostic — runtime mode is selected at start time:

```bash
# One-step (build + start)
deploy.sh                    # standard mode (default)
deploy.sh --gateway          # gateway mode

# Two-step (build once, start with any mode)
deploy.sh build              # build all images
deploy.sh start              # start in standard mode
deploy.sh start --gateway    # start in gateway mode

# Stop
deploy.sh down
```

### Advanced
#### Sandbox Mode

DeerFlow supports multiple sandbox execution modes:
- **Local Execution** (runs sandbox code directly on the host machine)
- **Docker Execution** (runs sandbox code in isolated Docker containers)
- **Docker Execution with Kubernetes** (runs sandbox code in Kubernetes pods via provisioner service)

For Docker development, service startup follows `config.yaml` sandbox mode. In Local/Docker modes, `provisioner` is not started.

See the [Sandbox Configuration Guide](backend/docs/CONFIGURATION.md#sandbox) to configure your preferred mode.

#### MCP Server

DeerFlow supports configurable MCP servers and skills to extend its capabilities.
For HTTP/SSE MCP servers, OAuth token flows are supported (`client_credentials`, `refresh_token`).
See the [MCP Server Guide](backend/docs/MCP_SERVER.md) for detailed instructions.

#### IM Channels

DeerFlow supports receiving tasks from messaging apps. Channels auto-start when configured — no public IP required for any of them.

| Channel | Transport | Difficulty |
|---------|-----------|------------|
| Telegram | Bot API (long-polling) | Easy |
| Slack | Socket Mode | Moderate |
| Feishu / Lark | WebSocket | Moderate |
| WeCom | WebSocket | Moderate |

**Configuration in `config.yaml`:**

```yaml
channels:
  # LangGraph Server URL (default: http://localhost:2024)
  langgraph_url: http://localhost:2024
  # Gateway API URL (default: http://localhost:8001)
  gateway_url: http://localhost:8001

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

  wecom:
    enabled: true
    bot_id: $WECOM_BOT_ID
    bot_secret: $WECOM_BOT_SECRET

  slack:
    enabled: true
    bot_token: $SLACK_BOT_TOKEN     # xoxb-...
    app_token: $SLACK_APP_TOKEN     # xapp-... (Socket Mode)
    allowed_users: []               # empty = allow all

  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
    allowed_users: []               # empty = allow all

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
```

Notes:
- `assistant_id: lead_agent` calls the default LangGraph assistant directly.
- If `assistant_id` is set to a custom agent name, DeerFlow still routes through `lead_agent` and injects that value as `agent_name`, so the custom agent's SOUL/config takes effect for IM channels.

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

# WeCom
WECOM_BOT_ID=your_bot_id
WECOM_BOT_SECRET=your_bot_secret
```

**Telegram Setup**

1. Chat with [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the HTTP API token.
2. Set `TELEGRAM_BOT_TOKEN` in `.env` and enable the channel in `config.yaml`.

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

**WeCom Setup**

1. Create a bot on the WeCom AI Bot platform and obtain the `bot_id` and `bot_secret`.
2. Enable `channels.wecom` in `config.yaml` and fill in `bot_id` / `bot_secret`.
3. Set `WECOM_BOT_ID` and `WECOM_BOT_SECRET` in `.env`.
4. Make sure backend dependencies include `wecom-aibot-python-sdk`. The channel uses a WebSocket long connection and does not require a public callback URL.
5. The current integration supports inbound text, image, and file messages. Final images/files generated by the agent are also sent back to the WeCom conversation.

When DeerFlow runs in Docker Compose, IM channels execute inside the `gateway` container. In that case, do not point `channels.langgraph_url` or `channels.gateway_url` at `localhost`; use container service names such as `http://langgraph:2024` and `http://gateway:8001`, or set `DEER_FLOW_CHANNELS_LANGGRAPH_URL` and `DEER_FLOW_CHANNELS_GATEWAY_URL`.

**Commands**

Once a channel is connected, you can interact with DeerFlow directly from the chat:

| Command | Description |
|---------|-------------|
| `/new` | Start a new conversation |
| `/status` | Show current thread info |
| `/models` | List available models |
| `/memory` | View memory |
| `/help` | Show help |

> Messages without a command prefix are treated as regular chat — DeerFlow creates a thread and responds conversationally.

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

#### Using Both Providers

If both LangSmith and Langfuse are enabled, DeerFlow attaches both tracing callbacks and reports the same model activity to both systems.

If a provider is explicitly enabled but missing required credentials, or if its callback fails to initialize, DeerFlow fails fast when tracing is initialized during model creation and the error message names the provider that caused the failure.

For Docker deployments, tracing is disabled by default. Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in your `.env` to enable it.

## From Deep Research to Super Agent Harness

DeerFlow started as a Deep Research framework — and the community ran with it. Since launch, developers have pushed it far beyond research: building data pipelines, generating slide decks, spinning up dashboards, automating content workflows. Things we never anticipated.

That told us something important: DeerFlow wasn't just a research tool. It was a **harness** — a runtime that gives agents the infrastructure to actually get work done.

So we rebuilt it from scratch.

DeerFlow 2.0 is no longer a framework you wire together. It's a super agent harness — batteries included, fully extensible. Built on LangGraph and LangChain, it ships with everything an agent needs out of the box: a filesystem, memory, skills, sandbox-aware execution, and the ability to plan and spawn sub-agents for complex, multi-step tasks.

Use it as-is. Or tear it apart and make it yours.

## Core Features

### Skills & Tools

Skills are what make DeerFlow do *almost anything*.

A standard Agent Skill is a structured capability module — a Markdown file that defines a workflow, best practices, and references to supporting resources. DeerFlow ships with built-in skills for research, report generation, slide creation, web pages, image and video generation, and more. But the real power is extensibility: add your own skills, replace the built-in ones, or combine them into compound workflows.

Skills are loaded progressively — only when the task needs them, not all at once. This keeps the context window lean and makes DeerFlow work well even with token-sensitive models.

When you install `.skill` archives through the Gateway, DeerFlow accepts standard optional frontmatter metadata such as `version`, `author`, and `compatibility` instead of rejecting otherwise valid external skills.

Tools follow the same philosophy. DeerFlow comes with a core toolset — web search, web fetch, file operations, bash execution — and supports custom tools via MCP servers and Python functions. Swap anything. Add anything.

Gateway-generated follow-up suggestions now normalize both plain-string model output and block/list-style rich content before parsing the JSON array response, so provider-specific content wrappers do not silently drop suggestions.

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
```

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

### Sub-Agents

Complex tasks rarely fit in a single pass. DeerFlow decomposes them.

The lead agent can spawn sub-agents on the fly — each with its own scoped context, tools, and termination conditions. Sub-agents run in parallel when possible, report back structured results, and the lead agent synthesizes everything into a coherent output.

This is how DeerFlow handles tasks that take minutes to hours: a research task might fan out into a dozen sub-agents, each exploring a different angle, then converge into a single report — or a website — or a slide deck with generated visuals. One harness, many hands.

### Sandbox & File System

DeerFlow doesn't just *talk* about doing things. It has its own computer.

Each task gets its own execution environment with a full filesystem view — skills, workspace, uploads, outputs. The agent reads, writes, and edits files. It can view images and, when configured safely, execute shell commands.

With `AioSandboxProvider`, shell execution runs inside isolated containers. With `LocalSandboxProvider`, file tools still map to per-thread directories on the host, but host `bash` is disabled by default because it is not a secure isolation boundary. Re-enable host bash only for fully trusted local workflows.

This is the difference between a chatbot with tool access and an agent with an actual execution environment.

```
# Paths inside the sandbox container
/mnt/user-data/
├── uploads/          ← your files
├── workspace/        ← agents' working directory
└── outputs/          ← final deliverables
```

### Context Engineering

**Isolated Sub-Agent Context**: Each sub-agent runs in its own isolated context. This means that the sub-agent will not be able to see the context of the main agent or other sub-agents. This is important to ensure that the sub-agent is able to focus on the task at hand and not be distracted by the context of the main agent or other sub-agents.

**Summarization**: Within a session, DeerFlow manages context aggressively — summarizing completed sub-tasks, offloading intermediate results to the filesystem, compressing what's no longer immediately relevant. This lets it stay sharp across long, multi-step tasks without blowing the context window.

### Long-Term Memory

Most agents forget everything the moment a conversation ends. DeerFlow remembers.

Across sessions, DeerFlow builds a persistent memory of your profile, preferences, and accumulated knowledge. The more you use it, the better it knows you — your writing style, your technical stack, your recurring workflows. Memory is stored locally and stays under your control.

Memory updates now skip duplicate fact entries at apply time, so repeated preferences and context do not accumulate endlessly across sessions.

## Recommended Models

DeerFlow is model-agnostic — it works with any LLM that implements the OpenAI-compatible API. That said, it performs best with models that support:

- **Long context windows** (100k+ tokens) for deep research and multi-step tasks
- **Reasoning capabilities** for adaptive planning and complex decomposition
- **Multimodal inputs** for image understanding and video comprehension
- **Strong tool-use** for reliable function calling and structured outputs

## Embedded Python Client

DeerFlow can be used as an embedded Python library without running the full HTTP services. The `DeerFlowClient` provides direct in-process access to all agent and Gateway capabilities, returning the same response schemas as the HTTP Gateway API. The HTTP Gateway also exposes `DELETE /api/threads/{thread_id}` to remove DeerFlow-managed local thread data after the LangGraph thread itself has been deleted:

```python
from deerflow.client import DeerFlowClient

client = DeerFlowClient()

# Chat
response = client.chat("Analyze this paper for me", thread_id="my-thread")

# Streaming (LangGraph SSE protocol: values, messages-tuple, end)
for event in client.stream("hello"):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data["content"])

# Configuration & management — returns Gateway-aligned dicts
models = client.list_models()        # {"models": [...]}
skills = client.list_skills()        # {"skills": [...]}
client.update_skill("web-search", enabled=True)
client.upload_files("thread-1", ["./report.pdf"])  # {"success": True, "files": [...]}
```

All dict-returning methods are validated against Gateway Pydantic response models in CI (`TestGatewayConformance`), ensuring the embedded client stays in sync with the HTTP API schemas. See `backend/packages/harness/deerflow/client.py` for full API documentation.

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

### Security Recommendations

**Note: We strongly recommend deploying DeerFlow in a local trusted network environment.** If you need cross-device or cross-network deployment, you must implement strict security measures, such as:

- **IP allowlist**: Use `iptables`, or deploy hardware firewalls / switches with Access Control Lists (ACL), to **configure IP allowlist rules** and deny access from all other IP addresses.
- **Authentication gateway**: Configure a reverse proxy (e.g., nginx) and **enable strong pre-authentication**, blocking any unauthenticated access.
- **Network isolation**: Where possible, place the agent and trusted devices in the **same dedicated VLAN**, isolated from other network devices.
- **Stay updated**: Continue to follow DeerFlow's security feature updates.

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, workflow, and guidelines.

Regression coverage includes Docker sandbox mode detection and provisioner kubeconfig-path handling tests in `backend/tests/`.
Gateway artifact serving now forces active web content types (`text/html`, `application/xhtml+xml`, `image/svg+xml`) to download as attachments instead of inline rendering, reducing XSS risk for generated artifacts.

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

[![Star History Chart](https://api.star-history.com/svg?repos=bytedance/deer-flow&type=Date)](https://star-history.com/#bytedance/deer-flow&Date)

# Thinktank.ai - 1.0

Thinktank.ai is an open-source **super agent harness** that orchestrates **sub-agents**, **memory**, and **sandboxes** to do almost anything — powered by **extensible skills**.

> [!NOTE]
> **Thinktank.ai 1.0 is a development continuation.** It shares many base and style codes with Bytedance Deer Flow. If you're looking for the original Deer Flow framework, it's maintained on the [`main` branch](https://github.com/bytedance/deer-flow).

---

## Table of Contents

- [Quick Start](#quick-start)
- [Sandbox Configuration](#sandbox-configuration)
- [MCP Server](#mcp-server)
- [From Deep Research to Super Agent Harness](#from-deep-research-to-super-agent-harness)
- [Core Features](#core-features)
  - [Skills & Tools](#skills--tools)
  - [Sub-Agents](#sub-agents)
  - [Sandbox & File System](#sandbox--file-system)
  - [Context Engineering](#context-engineering)
  - [Long-Term Memory](#long-term-memory)
- [Recommended Models](#recommended-models)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgments](#acknowledgments)
- [Star History](#star-history)

## Quick Start

### Configuration

1. Clone the Thinktank.ai repo:
   ```bash
   git clone https://github.com/thinktank-ai/thinktank-ai.git && cd thinktank-ai
   ```
2. Create local config files by copying the example files:
   ```bash
   make config
   ```

3. Update the configs:

- **Required**
   - `config.yaml`: backend defaults (system prompts, tools, sandbox, and fallback models).
   - `.env`: backend service keys (optional if you only use per-user keys via Settings).
- **Model setup (recommended)**
   - Open **Settings → Models** in the UI to enable providers, paste API keys (stored in localStorage), validate them, and select which models appear in the model picker.
   - EPFL RCP AIaaS is available as provider `epfl-rcp` and uses the OpenAI-compatible endpoint `https://inference-rcp.epfl.ch/v1`.
   - EPFL RCP models expose `reasoning_content` when available; the backend now preserves it for streaming and timeline logs.
   - EPFL RCP models are marked as thinking-capable so the UI defaults to reasoning modes for them.
   - On app start, Thinktank.ai fetches the latest available models from each enabled provider.
- **Optional**
   - `frontend/.env`: configure backend API URLs.
   - `extensions_config.json`: configure desired MCP servers and skills.
   - `THINKTANK_TIMELINE_FILE_MODE=1`: force agent timeline logs to `.think-tank/threads/{thread_id}/user-data/outputs/agent_timeline.json` (useful for local development).

   For OpenAI reasoning-capable models, enable thinking via `when_thinking_enabled.reasoning` (this switches to the Responses API and lets you set `effort`). When thinking is enabled, Thinktank.ai surfaces a short reasoning summary in the chat UI.

   Note: `.env` is loaded from the current working directory or its parents. If a model `api_key` resolves to an unset `$ENV_VAR`, Thinktank.ai fails fast with a message pointing at the missing variable. When using Settings-based keys, the backend does not persist secrets.

   Model selection persists per device; regenerate/edit actions reuse the current model unless you change it via the selector.

   Thinking blocks auto-expand while tokens are streaming, so users can observe the reasoning as it is generated, auto-scroll to new tokens, and scroll within a capped height.

#### Sandbox Configuration

Thinktank.ai supports multiple sandbox execution modes. Configure your preferred mode in `config.yaml`:

**Local Execution** (runs sandbox code directly on the host machine):
```yaml
sandbox:
   use: src.sandbox.local:LocalSandboxProvider # Local execution
```

**Docker Execution** (runs sandbox code in isolated Docker containers):
```yaml
sandbox:
   use: src.community.aio_sandbox:AioSandboxProvider # Docker-based sandbox
```

**Docker Execution with Kubernetes** (runs sandbox code in Kubernetes pods via provisioner service):

This mode runs each sandbox in an isolated Kubernetes Pod on your **host machine's cluster**. Requires Docker Desktop K8s, OrbStack, or similar local K8s setup.

```yaml
sandbox:
   use: src.community.aio_sandbox:AioSandboxProvider
   provisioner_url: http://provisioner:8002
```

See [Provisioner Setup Guide](docker/provisioner/README.md) for detailed configuration, prerequisites, and troubleshooting.

### Running the Application

#### Option 1: Docker (Recommended)

The fastest way to get started with a consistent environment:

1. **Initialize and start**:
   ```bash
   make docker-init    # Pull sandbox image (Only once or when image updates)
   make docker-start   # Start services (auto-detects sandbox mode from config.yaml)
   ```

   `make docker-start` now starts `provisioner` only when `config.yaml` uses provisioner mode (`sandbox.use: src.community.aio_sandbox:AioSandboxProvider` with `provisioner_url`).

2. **Access**: http://localhost:2026

See [CONTRIBUTING.md](CONTRIBUTING.md) for a detailed Docker development guide.

#### Option 2: Local Development

If you prefer running services locally:

1. **Check prerequisites**:
   ```bash
   make check  # Verifies Node.js 22+, pnpm, uv, nginx
   ```

2. **(Optional) Pre-pull sandbox image**:
   ```bash
   # Recommended if using Docker/Container-based sandbox
   make setup-sandbox
   ```

3. **Start services**:
   ```bash
   make dev
   ```

4. **Access**: http://localhost:3000
   - Nginx forwards `/api/langgraph/*` to LangGraph and all other `/api/*` routes (including auth) to the gateway.
   - Backend linting uses `ruff` and enforces sorted imports.
   - Frontend linting uses the flat config in `frontend/eslint.config.js` with `eslint-plugin-import` for `import/order` (no Next.js ESLint presets required).
   - Frontend lint rules enforce explicit async handling (`no-floating-promises`) and nullish coalescing for defaults.

## Thinktank.ai as Super Agent Harness for the Public Sector

#### MCP Server

Thinktank.ai supports configurable MCP servers and skills to extend its capabilities.
For HTTP/SSE MCP servers, OAuth token flows are supported (`client_credentials`, `refresh_token`).
See the [MCP Server Guide](backend/docs/MCP_SERVER.md) for detailed instructions.

Thinktank.ai 1.0 is a super agent harness — batteries included, fully extensible. Built on LangGraph and LangChain, it ships with everything an agent needs out of the box: a filesystem, memory, skills, sandboxed execution, and the ability to plan and spawn sub-agents for complex, multi-step tasks.

## Core Features

### Skills & Tools

Skills are what make Thinktank.ai do *almost anything*.

A standard Agent Skill is a structured capability module — a Markdown file that defines a workflow, best practices, and references to supporting resources. Thinktank.ai ships with built-in skills for research, report generation, slide creation, web pages, image and video generation, and more. But the real power is extensibility: add your own skills, replace the built-in ones, or combine them into compound workflows.

Skills are loaded progressively — only when the task needs them, not all at once. This keeps the context window lean and makes Thinktank.ai work well even with token-sensitive models.

Tools follow the same philosophy. Thinktank.ai comes with a core toolset — web search, web fetch, file operations, bash execution — and supports custom tools via MCP servers and Python functions. Swap anything. Add anything.

In the chat UI, the Context panel surfaces the resolved tool list and enabled skills for the current session, backed by the gateway endpoint `GET /api/agent/context`.

The tool call timeline in the chat UI displays outputs for key tools (including the `reflection` scratchpad) so you can inspect intermediate reasoning steps.

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

### Sub-Agents

Complex tasks rarely fit in a single pass. Thinktank.ai decomposes them.

The lead agent can spawn sub-agents on the fly — each with its own scoped context, tools, and termination conditions. Sub-agents run in parallel when possible, report back structured results, and the lead agent synthesizes everything into a coherent output.

This is how Thinktank.ai handles tasks that take minutes to hours: a research task might fan out into a dozen sub-agents, each exploring a different angle, then converge into a single report — or a website — or a slide deck with generated visuals. One harness, many hands.

### Sandbox & File System

Thinktank.ai doesn't just *talk* about doing things. It has its own computer.

Each task runs inside an isolated Docker container with a full filesystem — skills, workspace, uploads, outputs. The agent reads, writes, and edits files. It executes bash commands and codes. It views images. All sandboxed, all auditable, zero contamination between sessions.

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

**Summarization**: Within a session, Thinktank.ai manages context aggressively — summarizing completed sub-tasks, offloading intermediate results to the filesystem, and compressing what's no longer immediately relevant. This lets it stay sharp across long, multi-step tasks without blowing the context window.

### Long-Term Memory

Most agents forget everything the moment a conversation ends. Thinktank.ai remembers.

Across sessions, Thinktank.ai builds a persistent memory of your profile, preferences, and accumulated knowledge. The more you use it, the better it knows you — your writing style, your technical stack, your recurring workflows. Memory is stored locally and stays under your control.

## Recommended Models

Thinktank.ai is model-agnostic — it works with any LLM that implements the OpenAI-compatible API. That said, it performs best with models that support:

- **Long context windows** (100k+ tokens) for deep research and multi-step tasks
- **Reasoning capabilities** for adaptive planning and complex decomposition
- **Multimodal inputs** for image understanding and video comprehension
- **Strong tool-use** for reliable function calling and structured outputs

## Documentation

- [Contributing Guide](CONTRIBUTING.md) - Development environment setup and workflow
- [Configuration Guide](backend/docs/CONFIGURATION.md) - Setup and configuration instructions
- [Architecture Overview](backend/CLAUDE.md) - Technical architecture details
- [Backend Architecture](backend/README.md) - Backend architecture and API reference

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, workflow, and guidelines.

## License

This project is open source and available under the [MIT License](./LICENSE).

## Acknowledgments

Thinktank.ai is built upon the incredible work of the open-source community. We are deeply grateful to all the projects and contributors whose efforts have made Thinktank.ai possible. Truly, we stand on the shoulders of giants.

We would like to extend our sincere appreciation to the following projects for their invaluable contributions:
- **[DeerFlow](https://github.com/bytedance/deer-flow)**: Their impressive agent system that serves as the foundation and initialization, enabling robust new features and advanced R&D future works.
- **[LangChain](https://github.com/langchain-ai/langchain)**: Their exceptional framework powers our LLM interactions and chains, enabling seamless integration and functionality.
- **[LangGraph](https://github.com/langchain-ai/langgraph)**: Their innovative approach to multi-agent orchestration has been instrumental in enabling Thinktank.ai's sophisticated workflows.

These projects exemplify the transformative power of open-source collaboration, and we are proud to build upon their foundations.

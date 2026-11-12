English | [中文](README_zh.md) | [日本語](README_ja.md) | [Français](README_fr.md) | [Русский](README_ru.md) | [Português](README_pt.md) | [한국어](README_ko.md)

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

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

DeerFlow has newly integrated the intelligent search and crawling toolset independently developed by BytePlus — [InfoQuest (supports free online experience)](https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest)

<a href="https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest" target="_blank">
  <img
    src="https://sf16-sg.tiktokcdn.com/obj/eden-sg/hubseh7bsbps/20251208-160108.png"   alt="InfoQuest_banner"
  />
</a>

---

## One-Line Agent Setup

If you use Claude Code, Codex, Cursor, Windsurf, or another coding agent, you can hand it the setup instructions in one sentence:

```text
Help me clone DeerFlow if needed, then bootstrap it for local development by following https://raw.githubusercontent.com/bytedance/deer-flow/main/Install.md
```

That prompt is intended for coding agents. It tells the agent to clone the repo if needed, choose Docker when available, and stop with the exact next command plus any missing config the user still needs to provide.

## Quick Start

```bash
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow
make setup          # interactive wizard: writes config.yaml and .env (about 2 minutes)
```

Then start DeerFlow with Docker (recommended) or run it locally:

```bash
# Docker
make docker-init    # pull the sandbox image (once, or when the image updates)
make docker-start   # start services
```

```bash
# Local development
make check          # verifies Node.js 22+, pnpm, uv, nginx
make install
make dev
```

Open http://localhost:2026.

- All configuration options, providers and manual setup: [Configuration](docs/guide/configuration.md)
- Docker details, sizing, upgrades, startup modes and production deployment: [Running the Application](docs/guide/deployment.md)
- Running on a server or exposing it beyond localhost: read the [Security Notice](docs/guide/security.md) first

## From Deep Research to Super Agent Harness

DeerFlow started as a Deep Research framework — and the community ran with it. Since launch, developers have pushed it far beyond research: building data pipelines, generating slide decks, spinning up dashboards, automating content workflows. Things we never anticipated.

That told us something important: DeerFlow wasn't just a research tool. It was a **harness** — a runtime that gives agents the infrastructure to actually get work done.

So we rebuilt it from scratch.

DeerFlow 2.0 is no longer a framework you wire together. It's a super agent harness — batteries included, fully extensible. Built on LangGraph and LangChain, it ships with everything an agent needs out of the box: a filesystem, memory, skills, sandbox-aware execution, and the ability to plan and spawn sub-agents for complex, multi-step tasks.

Use it as-is. Or tear it apart and make it yours.

## Guides

Each guide is the full reference for its topic. Open the one you need.

| Topic | Guide |
| --- | --- |
| Models, providers, `config.yaml`, environment variables | [Configuration](docs/guide/configuration.md) |
| Docker, local development, upgrades, production deployment | [Running the Application](docs/guide/deployment.md) |
| Sandbox modes, file system, uploads and outputs | [Sandbox](docs/guide/sandbox.md) |
| Skills, built-in tools, script workflows, Claude Code integration | [Skills & Tools](docs/guide/skills-and-tools.md) |
| MCP servers | [MCP Server](docs/guide/mcp.md) |
| Sub-agents and task delegation | [Sub-Agents](docs/guide/subagents.md), [Tool restrictions](docs/guide/subagents.md#tool-restrictions) |
| Long-term memory | [Long-Term Memory](docs/guide/memory.md) |
| Session goals, context compaction, task notes, evidence-based decisions | [Context, Goals and Agent Decisions](docs/guide/context.md) |
| Private knowledge retrieval (RAGFlow) | [Private Knowledge Retrieval](docs/guide/knowledge-retrieval.md) |
| Agentic browser control | [Agentic Browser Control](docs/guide/browser-control.md) |
| Projects, instructions, document shelf | [Projects](docs/guide/projects.md) |
| Scheduled tasks | [Scheduled Tasks](docs/guide/scheduled-tasks.md) |
| Feishu, Slack, Telegram, Discord, DingTalk and other IM channels | [IM Channels](docs/guide/im-channels.md) |
| File attachments, downloads and Office previews | [File Previews](docs/guide/file-previews.md) |
| Token usage dashboard, workspace, chat archive | [Workspace UI](docs/guide/workspace.md) |
| Terminal workbench | [Terminal Workbench (TUI)](docs/guide/tui.md) |
| Personal access tokens, stream actions, embedded Python client | [API Access and Python Client](docs/guide/api-and-client.md) |
| Trace correlation, LangSmith, Langfuse, Monocle | [Tracing and Observability](docs/guide/observability.md) |
| Deployment risks, admin model, security recommendations | [Security Notice](docs/guide/security.md) |

## Recommended Models

DeerFlow is model-agnostic — it works with any LLM that implements the OpenAI-compatible API. That said, it performs best with models that support:

- **Long context windows** (100k+ tokens) for deep research and multi-step tasks
- **Reasoning capabilities** for adaptive planning and complex decomposition
- **Multimodal inputs** for image understanding and video comprehension
- **Strong tool-use** for reliable function calling and structured outputs

## More Documentation

- [Install.md](Install.md) - Setup instructions written for coding agents
- [Configuration Reference](backend/docs/CONFIGURATION.md) - Every `config.yaml` option
- [Backend Architecture](backend/README.md) - Backend architecture and API reference
- [Architecture Overview](docs/ARCHITECTURE.md) - How the services fit together
- [Contributing Guide](CONTRIBUTING.md) - Development environment, workflow and tests
- [Changelog](CHANGELOG.md) - Release notes

## ⚠️ Security Notice

DeerFlow can execute commands and read and write files. It is designed to run in a local trusted environment, and a Gateway admin account is equivalent to code execution on the host. Before you deploy it on a server or expose it to a network, read the full [Security Notice](docs/guide/security.md) and [SECURITY.md](SECURITY.md).

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, workflow, and guidelines.

## License

This project is open source and available under the [MIT License](LICENSE).

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

# DeerFlow Architecture Documentation

This document provides a comprehensive overview of DeerFlow's system architecture, components, and design principles.

## Table of Contents

- [System Overview](#system-overview)
- [Core Concepts: SuperAgent Harness](#core-concepts-superagent-harness)
- [Component Architecture](#component-architecture)
- [Technology Stack](#technology-stack)
- [Data Flow](#data-flow)
- [Deployment Architecture](#deployment-architecture)
- [Extension Points](#extension-points)
- [Security Considerations](#security-considerations)

---

## System Overview

DeerFlow (**D**eep **E**xploration and **E**fficient **R**esearch **Flow**) is an open-source **SuperAgent Harness** that orchestrates sub-agents, memory, and sandboxes to accomplish complex tasks through extensible skills.

### Key Characteristics

- **Agent-Centric**: Built on LangGraph for robust agent workflow orchestration
- **Sandboxed Execution**: Isolated execution environments for safe code execution
- **Extensible Skills**: Modular skill system for domain-specific capabilities
- **Persistent Memory**: Long-term memory for personalized interactions
- **Multi-Channel**: Support for IM platforms (Telegram, Slack, Feishu)

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Users / Clients                                 │
│                    (Web UI, Telegram, Slack, Feishu)                        │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Nginx (Port 2026)                                  │
│                       Unified Reverse Proxy                                  │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  /api/langgraph/*  →  LangGraph Server (2024)                         │  │
│  │  /api/*            →  Gateway API (8001)                              │  │
│  │  /*                →  Frontend (3000)                                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
│   LangGraph Server   │   │     Gateway API      │   │      Frontend        │
│    (Port 2024)       │   │    (Port 8001)       │   │    (Port 3000)       │
│                      │   │                      │   │                      │
│  ┌────────────────┐  │   │  ┌────────────────┐  │   │  ┌────────────────┐  │
│  │  Lead Agent    │  │   │  │   REST API     │  │   │  │   Next.js 16   │  │
│  │  ┌──────────┐  │  │   │  │                │  │   │  │   React 19     │  │
│  │  │Middleware│  │  │   │  │ • Models       │  │   │  │   TypeScript   │  │
│  │  │  Chain   │  │  │   │  │ • MCP Config   │  │   │  │   Tailwind CSS │  │
│  │  └──────────┘  │  │   │  │ • Skills       │  │   │  └────────────────┘  │
│  │  ┌──────────┐  │  │   │  │ • Memory       │  │   │                      │
│  │  │  Tools   │  │  │   │  │ • Uploads      │  │   │  Thread Management   │
│  │  └──────────┘  │  │   │  │ • Artifacts    │  │   │  Chat Interface      │
│  │  ┌──────────┐  │  │   │  └────────────────┘  │   │  Artifacts View      │
│  │  │Subagents │  │  │   │                      │   │  Settings Panel      │
│  │  └──────────┘  │  │   │                      │   │                      │
│  └────────────────┘  │   └──────────────────────┘   └──────────────────────┘
│                      │
└──────────┬───────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Shared Infrastructure                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐   │
│  │   config.yaml    │  │extensions_config │  │      Sandbox System       │  │
│  │                  │  │     .json        │  │                           │  │
│  │  • Models        │  │                  │  │  ┌─────────────────────┐  │   │
│  │  • Tools         │  │  • MCP Servers   │  │  │   Local Provider    │  │   │
│  │  • Sandbox       │  │  • Skills State  │  │  │   Docker Provider   │  │   │
│  │  • Memory        │  │                  │  │  │   K8s Provisioner   │  │   │
│  └──────────────────┘  └──────────────────┘  │  └─────────────────────┘  │   │
│                                              └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Concepts: SuperAgent Harness

DeerFlow 2.0 is designed as a **SuperAgent Harness** — a runtime infrastructure that provides agents with everything they need to accomplish real work.

### Design Philosophy

Unlike traditional agent frameworks that focus solely on reasoning and tool calling, DeerFlow provides:

1. **Execution Environment**: A sandboxed filesystem where agents can read, write, and execute code
2. **Memory System**: Persistent context retention across sessions
3. **Skill System**: Domain-specific expertise injected into agent prompts
4. **Sub-Agent Delegation**: Parallel task execution for complex workflows
5. **Multi-Channel Access**: Interface through web, messaging platforms, or embedded Python client

### Harness Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DeerFlow Harness                                   │
│                                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │   Memory    │  │   Skills    │  │  Subagents  │  │      Sandbox        │ │
│  │   System    │  │   System    │  │   System    │  │      System         │ │
│  │             │  │             │  │             │  │                     │ │
│  │ • Context   │  │ • Discovery │  │ • Registry  │  │ • Local/Container   │ │
│  │ • Facts     │  │ • Injection │  │ • Executor  │  │ • Virtual Paths     │ │
│  │ • Updates   │  │ • Install   │  │ • Pool      │  │ • Tools             │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│                                                                              │
│                              ┌─────────────────┐                            │
│                              │   Lead Agent    │                            │
│                              │                 │                            │
│                              │ • Model Layer   │                            │
│                              │ • Tool Layer    │                            │
│                              │ • Prompt Layer  │                            │
│                              └─────────────────┘                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Abstractions

| Abstraction | Purpose | Implementation |
|-------------|---------|----------------|
| **Thread** | Isolated conversation context | LangGraph thread with checkpointer |
| **Sandbox** | Execution environment | Local, Docker, or Kubernetes |
| **Skill** | Domain expertise | Markdown files with YAML frontmatter |
| **Tool** | Atomic capability | Python functions with LangChain tool decorator |
| **Sub-Agent** | Delegated worker | Independent agent with scoped context |

---

## Component Architecture

### 1. Backend (Python)

The backend is organized into two layers with strict dependency direction:

#### Harness Layer (`packages/harness/deerflow/`)

Publishable agent framework package containing core agent capabilities:

```
packages/harness/deerflow/
├── agents/              # Agent system
│   ├── lead_agent/     # Main agent (factory, prompts, state)
│   ├── middlewares/    # 12 middleware components
│   └── memory/         # Memory extraction & storage
├── sandbox/            # Sandbox execution system
│   ├── local/         # Local filesystem provider
│   └── tools.py       # bash, ls, read/write/str_replace
├── subagents/          # Sub-agent delegation
│   ├── builtins/      # general-purpose, bash agents
│   └── executor.py    # Background execution engine
├── tools/              # Built-in tools
├── mcp/                # Model Context Protocol integration
├── models/             # Model factory with thinking/vision
├── skills/             # Skills discovery & loading
├── config/             # Configuration system
├── community/          # Community tools (Tavily, Jina, etc.)
├── reflection/         # Dynamic module loading
└── client.py           # Embedded Python client
```

**Dependency Rule**: Harness never imports from App layer.

#### App Layer (`app/`)

Unpublished application code for HTTP services:

```
app/
├── gateway/            # FastAPI REST API
│   ├── app.py         # Application setup
│   └── routers/       # API route modules
│       ├── models.py
│       ├── mcp.py
│       ├── skills.py
│       ├── memory.py
│       ├── uploads.py
│       ├── threads.py
│       └── artifacts.py
└── channels/           # IM platform integrations
    ├── base.py        # Abstract Channel base
    ├── manager.py     # Core dispatcher
    ├── message_bus.py # Async pub/sub
    ├── slack.py
    ├── telegram.py
    └── feishu.py
```

### 2. Frontend (TypeScript/React)

Next.js 16 application with React 19:

```
frontend/src/
├── app/                # Next.js App Router
│   └── workspace/
│       └── chats/[thread_id]/  # Chat page
├── components/
│   ├── ui/            # Shadcn UI primitives
│   ├── ai-elements/   # Vercel AI SDK elements
│   └── workspace/     # Chat components
├── core/              # Business logic
│   ├── threads/       # Thread management
│   ├── api/           # LangGraph client
│   ├── artifacts/     # Artifact loading
│   ├── skills/        # Skills management
│   ├── memory/        # Memory system
│   └── settings/      # User preferences
├── hooks/             # Shared React hooks
└── lib/               # Utilities
```

### 3. Skills System

Skills are structured Markdown files defining domain-specific workflows:

```
skills/
├── public/                    # Bundled skills (committed)
│   ├── deep-research/
│   │   └── SKILL.md
│   ├── ppt-generation/
│   │   └── SKILL.md
│   ├── frontend-design/
│   │   └── SKILL.md
│   ├── image-generation/
│   │   └── SKILL.md
│   └── ... (17+ skills)
└── custom/                    # User-installed skills (gitignored)
    └── user-skill/
        └── SKILL.md
```

**SKILL.md Format**:
```markdown
---
name: skill-name
description: What this skill does
license: MIT
allowed-tools:
  - read_file
  - bash
---

# Skill Instructions
Detailed guidance injected into the agent's system prompt...
```

### 4. Sandbox System

Three execution modes for isolated code execution:

| Mode | Description | Use Case |
|------|-------------|----------|
| **Local** | Direct execution on host | Development |
| **Docker** | Isolated containers | Production |
| **Kubernetes** | Pod-based via Provisioner | Enterprise scaling |

**Virtual Path Mapping**:
```
Container Virtual Path              Host Physical Path
─────────────────────────────────────────────────────────────
/mnt/user-data/workspace    →    .deer-flow/threads/{id}/workspace
/mnt/user-data/uploads      →    .deer-flow/threads/{id}/uploads
/mnt/user-data/outputs      →    .deer-flow/threads/{id}/outputs
/mnt/skills                 →    deer-flow/skills/
```

### 5. Middleware Chain

Middlewares execute in strict order for cross-cutting concerns:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Middleware Chain                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. ThreadDataMiddleware    Initialize per-thread directories               │
│  2. UploadsMiddleware       Inject uploaded files into context              │
│  3. SandboxMiddleware       Acquire sandbox environment                     │
│  4. DanglingToolCallMiddleware  Handle interrupted tool calls               │
│  5. GuardrailMiddleware     Pre-tool-call authorization (optional)          │
│  6. SummarizationMiddleware Reduce context on token limits (optional)       │
│  7. TodoListMiddleware      Task tracking in plan mode (optional)           │
│  8. TitleMiddleware         Auto-generate conversation titles               │
│  9. MemoryMiddleware        Queue for async memory extraction               │
│  10. ViewImageMiddleware    Inject image data for vision models             │
│  11. SubagentLimitMiddleware  Enforce sub-agent concurrency limits          │
│  12. ClarificationMiddleware  Intercept clarification requests             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

### Backend

| Category | Technology | Version |
|----------|------------|---------|
| **Runtime** | Python | 3.12+ |
| **Package Manager** | uv | latest |
| **Agent Framework** | LangGraph | 1.0.6+ |
| **LLM Abstraction** | LangChain | 1.2.3+ |
| **Web Framework** | FastAPI | 0.115.0+ |
| **MCP Integration** | langchain-mcp-adapters | latest |
| **Sandbox** | agent-sandbox | latest |
| **Document Conversion** | markitdown | latest |

### Frontend

| Category | Technology | Version |
|----------|------------|---------|
| **Runtime** | Node.js | 22+ |
| **Framework** | Next.js | 16.x |
| **UI Library** | React | 19.x |
| **Language** | TypeScript | 5.8+ |
| **Styling** | Tailwind CSS | 4.x |
| **State Management** | TanStack Query | 5.x |
| **Package Manager** | pnpm | 10.26.2+ |

### Infrastructure

| Component | Technology |
|-----------|------------|
| **Reverse Proxy** | Nginx (Alpine) |
| **Containerization** | Docker |
| **Orchestration** | Kubernetes (optional) |
| **LLM Providers** | OpenAI, Anthropic, DeepSeek, Google, etc. |

---

## Data Flow

### 1. Chat Message Flow

```
User Input
    │
    ▼
┌─────────────────┐
│   Frontend      │  useSubmitThread hook
│   (Next.js)     │
└────────┬────────┘
         │ POST /api/langgraph/threads/{id}/runs
         ▼
┌─────────────────┐
│   Nginx         │  Route to LangGraph (2024)
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LangGraph Server                                   │
│                                                                              │
│  1. Load/create thread state                                                │
│  2. Execute middleware chain                                                │
│     ├─ ThreadDataMiddleware: Setup paths                                   │
│     ├─ UploadsMiddleware: Inject files                                     │
│     ├─ SandboxMiddleware: Acquire sandbox                                  │
│     └─ ... (other middlewares)                                             │
│  3. Execute agent                                                           │
│     ├─ Model processes messages                                            │
│     ├─ Tool calls (bash, web_search, etc.)                                 │
│     ├─ Sub-agent delegation (if enabled)                                   │
│     └─ Response generation                                                 │
│  4. Stream response via SSE                                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
         │ SSE events (values, messages-tuple, end)
         ▼
┌─────────────────┐
│   Frontend      │  useThreadStream hook
│   (Next.js)     │  Update UI in real-time
└─────────────────┘
```

### 2. File Upload Flow

```
┌─────────────────┐
│   User          │  Select file(s)
└────────┬────────┘
         │ POST /api/threads/{id}/uploads
         ▼
┌─────────────────┐
│   Gateway API   │  FastAPI
└────────┬────────┘
         │
         ├─ Validate file
         ├─ Store in .deer-flow/threads/{id}/uploads/
         ├─ Convert if document (PDF/PPT/Excel/Word → Markdown)
         │
         ▼
┌─────────────────┐
│   Response      │  { files: [{ filename, path, virtual_path }] }
└─────────────────┘
         │
         │ (Next agent run)
         ▼
┌─────────────────┐
│ UploadsMiddleware│  Inject file list into context
└─────────────────┘
```

### 3. Memory System Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Memory Flow                                        │
│                                                                              │
│  Conversation (User + AI responses)                                         │
│         │                                                                    │
│         ▼                                                                    │
│  MemoryMiddleware                                                            │
│         │                                                                    │
│         │ Queue conversation                                                 │
│         ▼                                                                    │
│  MemoryUpdateQueue                                                           │
│         │                                                                    │
│         │ Debounce (30s default)                                            │
│         ▼                                                                    │
│  Background Thread                                                           │
│         │                                                                    │
│         │ LLM extraction                                                    │
│         ├─ User context updates                                             │
│         ├─ Fact extraction                                                  │
│         └─ Confidence scoring                                               │
│         │                                                                    │
│         ▼                                                                    │
│  memory.json                                                                 │
│         │                                                                    │
│         │ (Next session)                                                    │
│         ▼                                                                    │
│  System Prompt Injection                                                     │
│         │                                                                    │
│         ├─ Top 15 facts                                                     │
│         ├─ Work/personal context                                            │
│         └─ Top-of-mind items                                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4. Sub-Agent Delegation Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Sub-Agent Flow                                        │
│                                                                              │
│  Lead Agent                                                                  │
│         │                                                                    │
│         │ task(description, prompt, subagent_type, max_turns)              │
│         ▼                                                                    │
│  SubagentExecutor                                                            │
│         │                                                                    │
│         │ Submit to scheduler pool                                          │
│         ▼                                                                    │
│  Background Execution                                                        │
│         │                                                                    │
│         ├─ Create isolated context                                          │
│         ├─ Load sub-agent (general-purpose / bash / custom)               │
│         ├─ Execute with scoped tools                                        │
│         └─ Poll for completion (5s interval)                               │
│         │                                                                    │
│         │ SSE events: task_started, task_running, task_completed           │
│         ▼                                                                    │
│  Result Return                                                               │
│         │                                                                    │
│         ▼                                                                    │
│  Lead Agent continues                                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

Concurrency: Max 3 concurrent sub-agents per turn
Timeout: 15 minutes default
```

---

## Deployment Architecture

### Development Mode

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Development Setup                                    │
│                                                                              │
│  Host Machine                                                                │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                                                                       │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐ │  │
│  │  │ Nginx:2026  │ │ LangGraph   │ │ Gateway     │ │ Frontend        │ │  │
│  │  │             │ │ :2024       │ │ :8001       │ │ :3000           │ │  │
│  │  │ (Docker)    │ │ (uv run)    │ │ (uv run)    │ │ (pnpm dev)      │ │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────┘ │  │
│  │                                                                       │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │  │
│  │  │  Local Sandbox (Direct Execution)                                │ │  │
│  │  │  .deer-flow/threads/{id}/workspace                               │ │  │
│  │  └─────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

Command: make dev
Access: http://localhost:2026
```

### Docker Development Mode

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Docker Development Setup                                │
│                                                                              │
│  Docker Network (deer-flow-dev)                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                                                                       │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐ │  │
│  │  │ nginx       │ │ langgraph   │ │ gateway     │ │ frontend        │ │  │
│  │  │ :2026       │ │ :2024       │ │ :8001       │ │ :3000           │ │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────┘ │  │
│  │                                                                       │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │  │
│  │  │  DooD (Docker-out-of-Docker)                                     │ │  │
│  │  │  Sandbox containers share host Docker socket                     │ │  │
│  │  └─────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

Commands:
  make docker-init    # Pull sandbox image
  make docker-start   # Start services

Access: http://localhost:2026
```

### Production Mode

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Production Setup                                      │
│                                                                              │
│  Docker Compose (docker-compose.yaml)                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                                                                       │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐ │  │
│  │  │ nginx       │ │ langgraph   │ │ gateway     │ │ frontend        │ │  │
│  │  │ (alpine)    │ │ (prod)      │ │ (prod)      │ │ (prod)          │ │  │
│  │  │ :2026       │ │ :2024       │ │ :8001       │ │ :3000           │ │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────┘ │  │
│  │                                                                       │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │  │
│  │  │  Provisioner (optional, Kubernetes mode)                         │ │  │
│  │  │  :8002 - Manages sandbox pods                                   │ │  │
│  │  └─────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

Commands:
  make up     # Build and start
  make down   # Stop and remove

Access: http://localhost:${PORT:-2026}
```

### Kubernetes Mode (Enterprise)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Kubernetes Architecture                                  │
│                                                                              │
│  Kubernetes Cluster                                                          │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                                                                       │  │
│  │  Namespace: deer-flow                                                 │  │
│  │                                                                       │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐   │  │
│  │  │ Deployment      │  │ Deployment      │  │ Deployment          │   │  │
│  │  │ nginx           │  │ langgraph       │  │ gateway             │   │  │
│  │  │ gateway         │  │                 │  │                     │   │  │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────┘   │  │
│  │                                                                       │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │  │
│  │  │  Provisioner Pod                                                 │ │  │
│  │  │  - Creates sandbox pods on-demand                                │ │  │
│  │  │  - Exposes via NodePort services                                 │ │  │
│  │  │  - Manages lifecycle (create/destroy)                            │ │  │
│  │  └─────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                       │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │  │
│  │  │  Sandbox Pods (per-thread)                                       │ │  │
│  │  │  ┌─────────┐ ┌─────────┐ ┌─────────┐                            │ │  │
│  │  │  │ thread-1│ │ thread-2│ │ thread-3│                            │ │  │
│  │  │  │ :8080   │ │ :8081   │ │ :8082   │                            │ │  │
│  │  │  └─────────┘ └─────────┘ └─────────┘                            │ │  │
│  │  └─────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Extension Points

DeerFlow is designed for extensibility at multiple levels:

### 1. Custom Models

Add new LLM providers in `config.yaml`:

```yaml
models:
  - name: my-custom-model
    display_name: My Custom Model
    use: langchain_myprovider:ChatMyProvider  # LangChain integration path
    model: model-identifier
    api_key: $MY_API_KEY
    supports_thinking: true
    supports_vision: true
```

### 2. Custom Tools

Create tools in `packages/harness/deerflow/tools/` or via MCP:

**Python Function Tool**:
```python
from langchain_core.tools import tool

@tool
def my_custom_tool(query: str) -> str:
    """Tool description for the agent."""
    # Implementation
    return result
```

**MCP Server** (in `extensions_config.json`):
```json
{
  "mcpServers": {
    "my-server": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "my-mcp-server"],
      "env": {"API_KEY": "$MY_API_KEY"}
    }
  }
}
```

### 3. Custom Skills

Create `skills/custom/my-skill/SKILL.md`:

```markdown
---
name: my-skill
description: What this skill accomplishes
allowed-tools:
  - read_file
  - bash
  - web_search
---

# My Custom Skill

Detailed instructions for the agent...
```

### 4. Custom Sub-Agents

Register in `packages/harness/deerflow/subagents/builtins/`:

```python
from deerflow.subagents.registry import register_agent

@register_agent("my-agent")
def create_my_agent(config):
    """Factory for custom sub-agent."""
    return agent_graph
```

### 5. Custom Sandbox Provider

Implement the `Sandbox` interface:

```python
from deerflow.sandbox.sandbox import Sandbox, SandboxProvider

class MySandboxProvider(SandboxProvider):
    def acquire(self, thread_id: str) -> str:
        # Create sandbox
        return sandbox_id

    def get(self, sandbox_id: str) -> Sandbox:
        return MySandbox(sandbox_id)

    def release(self, sandbox_id: str):
        # Cleanup
        pass
```

Configure in `config.yaml`:
```yaml
sandbox:
  use: my_package.sandbox:MySandboxProvider
```

### 6. Custom Guardrails

Implement pre-tool-call authorization:

```python
from deerflow.guardrails import GuardrailProvider

class MyGuardrailProvider(GuardrailProvider):
    async def aevaluate(self, tool_call, context) -> GuardrailResult:
        # Return allow/deny decision
        return GuardrailResult(allowed=True)
```

### 7. IM Channel Integration

Extend `app/channels/base.py`:

```python
from app.channels.base import Channel

class MyChannel(Channel):
    async def start(self):
        # Initialize connection

    async def send(self, message: OutboundMessage):
        # Send to platform
```

---

## Security Considerations

### Sandbox Isolation

- **Local Mode**: Direct execution (development only)
- **Docker Mode**: Container isolation with resource limits
- **Kubernetes Mode**: Pod-level isolation with network policies

### API Security

- **Thread Isolation**: Each thread has separate data directories
- **File Validation**: Uploads checked for path safety, directories rejected
- **Environment Variables**: Secrets resolved at runtime, not stored in config

### MCP Security

- **Process Isolation**: Each MCP server runs in its own process
- **OAuth Support**: Token-based authentication for HTTP/SSE servers
- **Enable/Disable**: Servers can be individually controlled

### Guardrails

Optional pre-execution authorization for tool calls:
- **AllowlistProvider**: Built-in, zero dependencies
- **OAP Providers**: Open Agent Passport standard
- **Custom Providers**: Implement your own authorization logic

---

## Further Reading

- [Backend Configuration Guide](../backend/docs/CONFIGURATION.md)
- [Backend Architecture Details](../backend/docs/ARCHITECTURE.md)
- [API Reference](../backend/docs/API.md)
- [MCP Server Guide](../backend/docs/MCP_SERVER.md)
- [Guardrails Documentation](../backend/docs/GUARDRAILS.md)
- [Contributing Guide](../CONTRIBUTING.md)
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DeerFlow is a LangGraph-based AI super agent harness with a full-stack architecture. It orchestrates sub-agents, memory, sandboxed execution, and extensible skills to accomplish complex tasks.

**Stack**: Python 3.12 backend (LangGraph + FastAPI), Next.js 16 frontend (React 19 + TypeScript), pnpm, nginx reverse proxy.

## Commands

Run from the **project root** unless otherwise specified.

### Full Application

| Command | Purpose |
|---------|---------|
| `make check` | Verify Node.js 22+, pnpm, uv, nginx are installed |
| `make install` | Install backend (uv sync) + frontend (pnpm install) dependencies |
| `make setup` | Interactive setup wizard — generates `config.yaml` and writes API keys to `.env` |
| `make doctor` | Validate setup and provide actionable fix hints |
| `make config` | Copy `config.example.yaml` → `config.yaml` (aborts if already exists) |
| `make dev` | Start all services: LangGraph (2024), Gateway (8001), Frontend (3000), nginx (2026) |
| `make dev-pro` | Dev + Gateway mode (experimental): agent runtime embedded in Gateway, no LangGraph server |
| `make stop` | Stop all running services |
| `make clean` | Stop services and remove `.deer-flow` data and logs |

### Backend Only

From `backend/`:

| Command | Purpose |
|---------|---------|
| `make dev` | Run LangGraph server only (port 2024) |
| `make gateway` | Run Gateway API only (port 8001) |
| `make lint` | Lint with ruff |
| `make format` | Format code with ruff |
| `make test` | Run pytest suite |

### Frontend Only

From `frontend/`:

| Command | Purpose |
|---------|---------|
| `pnpm dev` | Dev server with Turbopack (localhost:3000) |
| `pnpm build` | Production build |
| `pnpm lint` | ESLint |
| `pnpm typecheck` | TypeScript check |
| `pnpm test` | Unit tests (Vitest) |
| `pnpm test:e2e` | E2E tests (Playwright/Chromium) |

## Architecture

```
                          ┌─────────────────────┐
                          │  Nginx (port 2026) │
                          │  Unified reverse    │
                          └──────┬──────┬───────┘
                                 │      │
              /api/langgraph/*  │      │  /api/* (other)  /
                                 ▼      ▼
                    ┌───────────────┐  ┌──────────────────┐
                    │ LangGraph Svr │  │  Gateway API     │
                    │  (port 2024) │  │  (port 8001)     │
                    │              │  │                  │
                    │ Lead Agent   │  │ FastAPI REST:    │
                    │ Middlewares  │  │ models, mcp,     │
                    │ Tools        │  │ skills, memory,  │
                    │ Subagents    │  │ uploads, threads │
                    └───────────────┘  └──────────────────┘
                                               ▲
                                               │ SSE streaming
                                               │
                                        ┌──────┴──────┐
                                        │  Frontend  │
                                        │ (port 3000)│
                                        └────────────┘
```

### Runtime Modes

**Standard mode** (`make dev`): 4 processes — LangGraph server + Gateway + Frontend + nginx.

**Gateway mode** (`make dev-pro`, experimental): 3 processes — Gateway embeds the agent runtime directly via `RunManager` + `run_agent()` + `StreamBridge`. No separate LangGraph server process. Concurrency managed via async tasks.

Nginx routes in standard mode: `/api/langgraph/*` → LangGraph (2024), `/api/*` → Gateway (8001), `/` → Frontend (3000).

In Gateway mode: `/api/langgraph/*` → Gateway embedded runtime (8001).

### Backend: Harness / App Split

The backend enforces a strict import boundary between two packages:

- **`packages/harness/deerflow/`** — Publishable agent framework (`deerflow-harness`). Import prefix: `deerflow.*`. Contains agents, sandbox, tools, models, MCP, skills, config. Must never import from `app.*`.
- **`app/`** — Unpublished application code. Import prefix: `app.*`. Contains FastAPI Gateway and IM channel integrations.

Boundary is enforced by `tests/test_harness_boundary.py` (runs in CI). App imports deerflow; deerflow never imports app.

### Middleware Chain (18 middlewares)

Lead agent middlewares execute in strict order. Each handles a specific cross-cutting concern:

1. ThreadDataMiddleware — Creates per-thread isolated directories
2. UploadsMiddleware — Injects uploaded files into context
3. SandboxMiddleware — Acquires sandbox environment
4. DanglingToolCallMiddleware — Injects placeholder ToolMessages for interrupted tool calls
5. LLMErrorHandlingMiddleware — Normalizes provider failures
6. GuardrailMiddleware — Pre-tool-call authorization (optional)
7. SandboxAuditMiddleware — Security audit logging
8. ToolErrorHandlingMiddleware — Converts tool exceptions into recoverable errors
9. SummarizationMiddleware — Context reduction at token limits (optional)
10. TodoListMiddleware — Multi-step task tracking in plan mode (optional)
11. TokenUsageMiddleware — Token metrics recording (optional)
12. TitleMiddleware — Auto-generates conversation titles
13. MemoryMiddleware — Queues async memory updates
14. ViewImageMiddleware — Injects image data for vision-capable models
15. DeferredToolFilterMiddleware — Hides deferred tools until search is enabled
16. SubagentLimitMiddleware — Enforces max 3 concurrent subagents
17. LoopDetectionMiddleware — Detects and halts repeated tool-call loops
18. ClarificationMiddleware — Intercepts clarification requests (must be last)

## Project Structure

```
deer-flow/
├── Makefile                      # Root commands (dev, stop, docker-*, up/down)
├── config.example.yaml           # Primary config template
├── config.yaml                   # Active config (gitignored)
├── extensions_config.json       # MCP servers + skills state
├── .env                          # API keys (gitignored)
├── backend/
│   ├── Makefile                  # Backend commands (dev, gateway, lint, test)
│   ├── langgraph.json            # Graph entrypoint → deerflow.agents:make_lead_agent
│   ├── pyproject.toml            # Python deps (uv)
│   ├── packages/harness/deerflow/  # deerflow-harness package
│   │   ├── agents/              # Lead agent, middlewares, memory, thread_state
│   │   ├── sandbox/             # Sandbox interface + tools (bash, ls, read/write/str_replace)
│   │   ├── subagents/           # Subagent registry + executor
│   │   ├── tools/builtins/      # present_files, ask_clarification, view_image
│   │   ├── mcp/                 # MCP multi-server integration
│   │   ├── models/              # Model factory + vLLM provider
│   │   ├── skills/              # Skills discovery + loading
│   │   ├── config/              # Configuration system
│   │   ├── community/           # Tavily, Jina AI, Firecrawl, AioSandbox, ACP agents
│   │   ├── reflection/          # Dynamic module/class loading
│   │   └── client.py           # Embedded DeerFlowClient
│   ├── app/gateway/             # FastAPI Gateway API
│   │   └── routers/             # models, mcp, skills, memory, uploads, threads, artifacts
│   ├── app/channels/            # IM integrations: Feishu, Slack, Telegram, WeChat, WeCom
│   └── tests/                   # Backend tests
├── frontend/                     # Next.js 16 frontend
│   ├── src/app/                # App Router pages
│   ├── src/components/         # UI, workspace, landing components
│   ├── src/core/               # Business logic: threads, API, artifacts, skills, memory
│   └── tests/                  # Unit + E2E tests
└── skills/                       # Agent skills
    ├── public/                  # Built-in skills (committed)
    └── custom/                  # Custom skills (gitignored)
```

## Key Patterns

### Configuration

- `config.yaml` lives in the **project root** (not `backend/`). Config values starting with `$` resolve as environment variables.
- `extensions_config.json` holds MCP servers and skill states, also in project root.
- `config_version` in `config.example.yaml` enables auto-upgrade via `make config-upgrade`.

### Sandbox Virtual Paths

Agents see virtual paths inside containers:
- `/mnt/user-data/{workspace,uploads,outputs}` → physical `backend/.deer-flow/threads/{thread_id}/user-data/...`
- `/mnt/skills` → `deer-flow/skills/`

Virtual path translation via `replace_virtual_path()` / `replace_virtual_paths_in_command()` in sandbox tools.

### Subagent Delegation

Lead agent calls `task()` tool → `SubagentExecutor` runs subagent in background thread pool → polls for completion → returns result. Max 3 concurrent subagents, 15-minute timeout.

### IM Channels

Feishu uses `client.runs.stream(["messages-tuple", "values"])` with a single card patched in place. Slack/Telegram use `client.runs.wait()` for final response. Channels run inside the `gateway` container in Docker Compose — use container service names for `channels.langgraph_url` / `channels.gateway_url`.

## Development Workflow

1. `make check` — verify prerequisites
2. `make install` — install all dependencies
3. `make setup` or `cp config.example.yaml config.yaml` — configure
4. `make dev` — start all services at http://localhost:2026

For backend-only changes: `cd backend && make lint && make test`
For frontend-only changes: `cd frontend && pnpm lint && pnpm typecheck && BETTER_AUTH_SECRET=... pnpm build`

## Security

DeerFlow is designed for **local trusted environments** (127.0.0.1 loopback). Running on LAN/public cloud without IP allowlisting or authentication gateway is a security risk. See `CONTRIBUTING.md` for details.

# Claude Code 配置：OpenSpec + superpowers

主干由两个插件组成：
- OpenSpec —— 规范与需求层（proposal / design / tasks）
- superpowers —— 思考与流程层（plan / brainstorm / debug / TDD / review / verify）

类比：OpenSpec 是蓝图，superpowers 是大脑。

## 核心原则

1. **规范先行**：任何需求变更必须先过 OpenSpec，调用/opsx:propose，产出 proposal.md + design.md + tasks.md，再动手写代码。
2. 流程归 superpowers：brainstorm、plan、debug、TDD、verify、code review
   默认走 superpowers，不走 OMC / feature-dev 等同名第三方 skill。
3. 执行归 superpowers：验证和轻量交付动作由 superpowers 覆盖。
4. 独立 reviewer 通道：verification 和 code-review 分两个 pass，
   不能在同一上下文里合并。
5. 证据优先：没有测试/截图/QA 报告不算完成。
6. 歧义先 brainstorm：任何创造性工作前先调用 brainstorming。
7. 最短路径优先：能用一个 skill 解决的，不升级为完整闭环。

## OpenSpec 规范工作流

### 双文件夹模型

```
openspec/
  specs/     # 当前系统的事实来源（规范文件）
  changes/   # 每次变更的完整提案
```

### 每份变更必须包含三个文件

- `proposal.md` —— 为什么要做（背景、目标、成功标准、不做会怎样）
- `design.md` —— 技术方案（架构决策、接口设计、数据流、依赖关系）
- `tasks.md` —— 实施清单（可执行的具体任务，作为 Superpowers 的输入）

### 职责边界

- OpenSpec **只产出规范文档，不写代码**。
- Superpowers **只按 tasks.md 执行编码流程**，不修改 OpenSpec 规范。
- 两者之间通过**文件和命令**传递信息，不通过共享内存或隐式状态。

### 规范与执行的衔接

1. 需求输入 → OpenSpec 输出 `tasks.md`
2. `tasks.md` 作为 Superpowers 的输入启动 brainstorming
3. 编码执行过程中如发现规范遗漏或错误，**回退到 OpenSpec 更新 design.md / tasks.md**，再继续执行

## 任务分流

### 只读任务

分析、解释、架构说明、代码阅读 —— 直接处理。
真实 bug 排查但尚未修改 —— 用 systematic-debugging。

### 轻量任务

单文件或小范围修改、明确 bug 修复、配置/文案调整、小测试补充。
跳过完整 brainstorming / writing-plans / worktrees / 重 review 链。
直接实现 + 定向验证。

### 中任务

多文件但边界清晰，新功能或明确的重构。
OpenSpec  /opsx:propose（必须首先调用）→ 简短 brainstorming + 短 writing-plans + 实现 + verification。

### 大任务

跨模块、共享逻辑、新架构、公共 API 变更。
完整闭环：OpenSpec  /opsx:propose（必须首先调用）→ brainstorming → writing-plans → /plan-*-review
  → executing-plans + worktrees + TDD → verification
  → code-review → finishing-branch

## Subagent 策略

一定派子代理：
- 用户明说 "并行 / parallel / dispatch"
- 2-4 个边界清晰、独立验证、无共享状态的子任务
- 纯只读的多目标研究

一定不派：
- 任务有顺序依赖
- 多个子任务改同一文件 / contract / shared types
- package.json / lockfile / 根配置 / CI / schema / 总入口

默认串行：
- 单一目标的 bug 修复
- 根因未明的调试

## 安全护栏

- rm -rf / DROP TABLE / force-push / git reset --hard / kubectl delete
  必须格外谨慎
- 调试敏感模块时用 /freeze  限定可改范围
- 危险操作必须用户明确确认
- 密钥/凭证/API Key 不得硬编码
- 数据库访问用参数化查询
- 不用不可信输入拼接 shell 命令或 SQL

## Change Delivery Gate

声明完成、准备 commit / push / PR 之前必须满足：
1. 已完成相关验证，并如实报告结果
2. 已过对应质量门禁（review / verification）
3. 关键验证无法执行时必须明确说明原因
4. 禁止虚构命令输出
5. 没有验证证据，不得声称"通过" / "完成"

## 不要重复造轮子

- 需求分析先用/opsx:propose、proposal / design / tasks 文档编写
- 规范评审、技术方案确认
- tasks.md 作为 Superpowers 的唯一输入

只走 superpowers：
- plan / brainstorming / writing-plans / executing-plans
- TDD / debugging / verification
- code review / subagent / worktrees / 分支收尾


# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.


## OpenSpec + Superpowers 工作流

> ⚠️ **Gstack 暂未启用** - 待理解其功能后再开启

两个插件组成主干：

| 插件 | 职责 | 类比 |
|------|------|------|
| **OpenSpec** | 规范与需求层（propose / explore / archive） | 蓝图 |
| **Superpowers** | 思考与流程层（brainstorm / write-plan / execute-plan / debug / verify / review） | 大脑 |

### 核心原则

1. **规范先行**：任何需求变更必须先过 OpenSpec，产出 proposal + design + tasks，再动手写代码。
2. **流程归 Superpowers**：brainstorm、plan、debug、verify、code review。
3. **独立 Reviewer 通道**：verification 和 code-review 分两个 pass。
4. **证据优先**：没有测试/截图/QA 报告不算完成。
5. **歧义先 Brainstorm**：任何创造性工作前先调用 brainstorming。

### 任务分流

- **只读任务**：分析、解释、架构说明、代码阅读 —— 直接处理。
- **轻量任务**：单文件修改、明确 bug 修复、配置调整 —— 直接实现 + 定向验证。
- **中任务**：多文件但边界清晰 —— OpenSpec propose → brainstorming + writing-plans → 实现 → verification。
- **大任务**：跨模块、新架构 —— 完整闭环流程。

### 安全护栏

- `rm -rf` / `DROP TABLE` / `force-push` / `git reset --hard` / `kubectl delete` 必须先过 `/careful` 或 `/guard`
- `/ship` 和 `/land-and-deploy` 必须用户明确确认
- 密钥/凭证/API Key 不得硬编码

### Change Delivery Gate

声明完成、准备 commit / push / PR 之前必须满足：
1. 已完成相关验证，并如实报告结果
2. 已过对应质量门禁（review / verification）
3. 没有验证证据，不得声称"通过" / "完成"


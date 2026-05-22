# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 提供在此代码库中工作的指导。

## 项目概述

DeerFlow 是一个开源的 **超级智能体框架（super agent harness）**—— 基于 LangGraph + LangChain 的全栈 AI 系统，可编排子智能体、记忆和沙箱来完成复杂任务。后端是 Python 3.12 LangGraph 运行时；前端是 Next.js 16 + React 19 Web 界面。

**入口点**: 通过 nginx 访问 `http://localhost:2026`（本地开发）或通过 Docker 访问。

## 命令

**完整应用**（从项目根目录）：

| 命令 | 说明 |
|------|------|
| `make check` | 检查 Node.js 22+、pnpm、uv、nginx 是否已安装 |
| `make install` | 安装前端 + 后端依赖 + pre-commit 钩子 |
| `make setup` | 交互式设置向导（生成 config.yaml） |
| `make doctor` | 验证配置和环境 |
| `make dev` | 以开发模式启动所有服务（热重载） |
| `make start` | 以生产模式启动所有服务 |
| `make stop` | 停止所有运行中的服务 |
| `make docker-init` | 拉取沙箱镜像（仅首次 Docker 开发需要） |
| `make docker-start` | 启动 Docker 开发环境（根据 config.yaml 判断模式） |
| `make docker-stop` | 停止 Docker 开发环境 |
| `make up` | 构建并启动生产环境 Docker 服务 |
| `make down` | 停止生产环境 Docker 容器 |

**后端**（从 `backend/`）：

| 命令 | 说明 |
|------|------|
| `make lint` | Ruff 检查 + 格式化 |
| `make format` | 自动修复 ruff 问题 |
| `make test` | 运行所有后端测试 |
| `make dev` | 热重载运行 Gateway API（端口 8001） |

**前端**（从 `frontend/`）：

| 命令 | 说明 |
|------|------|
| `pnpm dev` | 开发服务器（端口 3000） |
| `pnpm lint` | ESLint 检查 |
| `pnpm typecheck` | TypeScript 类型检查 |
| `pnpm test` | 单元测试（Vitest） |
| `pnpm test:e2e` | 端到端测试（Playwright/Chromium） |
| `BETTER_AUTH_SECRET=... pnpm build` | 生产构建（需要密钥） |

## 架构

```
浏览器 ──▶ Nginx (:2026)
              ├── /api/*           ──▶ Gateway API (:8001) + 内嵌 LangGraph 运行时
              ├── /api/langgraph/* ──▶ LangGraph 兼容 API（重写为 /api/*）
              └── / (其他)         ──▶ 前端 (:3000)
```

**Harness / App 分离**：后端分为两层，严格单向依赖：
- **Harness**（`backend/packages/harness/deerflow/`）：可发布的智能体框架包（`deerflow-harness`）。包含智能体编排、工具、沙箱、模型、MCP、技能、配置——运行智能体所需的全部。
- **App**（`backend/app/`）：非发布应用代码。包含 FastAPI Gateway API 和 IM 渠道集成（飞书、Slack、Telegram、钉钉、微信、企业微信）。

**依赖规则**：App 可导入 deerflow，但 deerflow 不可导入 app。CI 中通过 `tests/test_harness_boundary.py` 强制执行。

**沙箱模式**：本地（主机文件系统）、Docker（容器化）、或 Kubernetes（通过 provisioner）。通过 `config.yaml` → `sandbox.use` 配置。

## 详细文档

各子系统的深度说明位于：

- **[backend/CLAUDE.md](backend/CLAUDE.md)** — 智能体系统、中间件链、沙箱、子智能体、工具、MCP、技能、模型工厂、记忆、追踪、嵌入式客户端
- **[frontend/CLAUDE.md](frontend/CLAUDE.md)** — 前端技术栈、源码结构、数据流、关键模式

## 关键开发注意事项

**TDD 是强制要求**：每个功能或 bug 修复都必须有对应的单元测试，放在 `backend/tests/` 中。提交前运行 `make test`。

**配置热重载**：Gateway 对每个请求重新读取 `config.yaml`，per-run 字段（模型、工具、记忆、摘要）立即生效。基础设施字段（数据库、checkpointer、沙箱提供方、渠道）需要重启才能生效。

**CI 强制执行**：每个 PR 必须通过后端 lint + 测试；前端变更必须通过 lint + 类型检查；前端文件变更时触发 E2E 测试。

**Docker 开发**：`make docker-start` 根据 config.yaml 自动判断沙箱模式，仅在使用 provisioner/Kubernetes 模式时才启动 `provisioner` 容器。

**启动模式**：

| | 本地前台 | 本地后台 | Docker 开发 | Docker 生产 |
|---|---|---|---|---|
| Dev | `make dev` | `make dev-daemon` | `make docker-start` | — |
| Prod | `make start` | `make start-daemon` | — | `make up` |

## 重要路径

- `config.example.yaml` — 完整配置参考；`config.yaml` 是生效配置（被 git 忽略）
- `extensions_config.example.json` — MCP 服务器和技能配置
- `backend/langgraph.json` — 图入口点（`deerflow.agents:make_lead_agent`）
- `skills/` — 智能体技能（public/ 和 custom/）
- `backend/.deer-flow/` — 运行时数据（线程、记忆、用户）
- `.env` — API 密钥（绝不提交真实值）
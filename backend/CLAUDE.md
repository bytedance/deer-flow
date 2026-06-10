# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 目录

- [项目概述](#项目概述)
- [命令](#命令)
- [架构](#架构)
  - [Harness / App 分层](#harness--app-分层)
  - [Agent 系统](#agent-系统)
  - [中间件链](#中间件链)
  - [配置系统](#配置系统)
  - [Gateway API](#gateway-api)
- [核心系统](#核心系统)
  - [工具系统](#工具系统)
  - [报告模板](#报告模板)
  - [记忆系统](#记忆系统)
  - [洞察系统](#洞察系统)
  - [知识库](#知识库)
- [开发工作流](#开发工作流)

---

## 项目概述

DeerFlow 是一个基于 LangGraph 的 AI 超级代理系统，具有全栈架构。后端提供"超级代理"，具备沙箱执行、持久记忆、子代理委派和可扩展工具集成——所有操作都在每线程隔离的环境中运行。

**架构**:
- **Gateway API** (端口 8001): REST API + 嵌入式 LangGraph 兼容代理运行时
- **Frontend** (端口 3000): Next.js Web 界面
- **Nginx** (端口 2026): 统一反向代理入口
- **Provisioner** (端口 8002, 可选): 仅在配置沙箱 provisioner/Kubernetes 模式时启动

**项目结构**:
```
deer-flow/
├── backend/
│   ├── packages/harness/      # deerflow-harness 包 (import: deerflow.*)
│   │   └── deerflow/
│   │       ├── agents/        # LangGraph 代理系统
│   │       ├── sandbox/       # 沙箱执行系统
│   │       ├── subagents/     # 子代理委派系统
│   │       ├── tools/         # 内置工具
│   │       ├── mcp/           # MCP 集成
│   │       ├── models/        # 模型工厂
│   │       ├── skills/        # 技能系统
│   │       ├── config/        # 配置系统
│   │       └── client.py      # 嵌入式 Python 客户端
│   ├── app/                   # 应用层 (import: app.*)
│   │   ├── gateway/           # FastAPI Gateway API
│   │   └── channels/          # IM 平台集成
│   └── tests/
└── frontend/
```

---

## 命令

**根目录** (完整应用):
```bash
make check      # 检查系统要求
make install    # 安装所有依赖
make dev        # 启动所有服务 (Gateway + Frontend + Nginx)
make start      # 启动生产服务
make stop       # 停止所有服务
```

**Backend 目录** (仅后端开发):
```bash
make install    # 安装后端依赖
make dev        # 运行 Gateway API (带热重载, 端口 8001)
make gateway    # 仅运行 Gateway API (端口 8001)
make test       # 运行所有后端测试
make lint       # ruff 代码检查
make format     # ruff 代码格式化
```

**回归测试**:
- `tests/test_docker_sandbox_mode_detection.py` - Docker 模式检测
- `tests/test_provisioner_kubeconfig.py` - kubeconfig 处理
- `tests/test_harness_boundary.py` - Harness → App 导入防火墙

---

## 架构

### Harness / App 分层

后端分为两层，依赖方向严格:

- **Harness** (`packages/harness/deerflow/`): 可发布的代理框架包 (`deerflow-harness`)。导入前缀: `deerflow.*`。包含代理编排、工具、沙箱、模型、MCP、技能、配置。
- **App** (`app/`): 未发布的应用代码。导入前缀: `app.*`。包含 FastAPI Gateway API 和 IM 渠道集成。

**依赖规则**: App 导入 deerflow，但 deerflow **永不**导入 app。此边界由 `tests/test_harness_boundary.py` 在 CI 中强制执行。

```python
# 允许
from deerflow.config import get_app_config  # App → Harness

# 禁止 (CI 失败)
from app.gateway.routers.uploads import ...  # Harness → App
```

### Agent 系统

**Lead Agent** (`packages/harness/deerflow/agents/lead_agent/agent.py`):
- 入口: `make_lead_agent(config: RunnableConfig)` 在 `langgraph.json` 注册
- 动态模型选择，支持 thinking/vision
- 工具通过 `get_available_tools()` 加载

**ThreadState** (`packages/harness/deerflow/agents/thread_state.py`):
- 扩展 `AgentState`，包含: `sandbox`, `thread_data`, `title`, `artifacts`, `todos`, `uploaded_files`, `viewed_images`

**多级 Agent 系统**: 三级发现，优先级覆盖 **user > tenant > builtin**
- 详见 [docs/AGENTS_SYSTEM.md](docs/AGENTS_SYSTEM.md)

### 中间件链

Lead-agent 中间件按严格顺序组装，共 18 个中间件:

1. ThreadDataMiddleware → 2. UploadsMiddleware → 3. SandboxMiddleware → 4. DanglingToolCallMiddleware → 5. LLMErrorHandlingMiddleware → 6. GuardrailMiddleware (可选) → 7. SandboxAuditMiddleware → 8. ToolErrorHandlingMiddleware → 9. SummarizationMiddleware (可选) → 10. TodoListMiddleware (可选) → 11. TokenUsageMiddleware (可选) → 12. TitleMiddleware → 13. MemoryMiddleware → 14. ViewImageMiddleware → 15. DeferredToolFilterMiddleware (可选) → 16. SubagentLimitMiddleware (可选) → 17. LoopDetectionMiddleware → 18. ClarificationMiddleware (必须最后)

详见 [docs/MIDDLEWARES.md](docs/MIDDLEWARES.md)

### 配置系统

**主配置** (`config.yaml`):
- 从 `config.example.yaml` 复制
- 配置优先级: 显式路径 > `DEER_FLOW_EXTENSIONS_CONFIG_PATH` > 当前目录 > 父目录
- `$` 开头的值解析为环境变量
- `get_app_config()` 缓存配置，文件 mtime 变更时自动重载

**扩展配置** (`extensions_config.json`):
- MCP 服务器和技能配置

**配置版本**: `config.example.yaml` 有 `config_version` 字段。启动时比较版本，过时则警告。运行 `make config-upgrade` 自动合并缺失字段。

### Gateway API

FastAPI 应用，端口 8001，健康检查 `GET /health`。

**主要路由**:

| 路由 | 端点 |
|------|------|
| Models | `GET /api/models` |
| MCP | `GET/PUT /api/mcp/config` |
| Skills | `GET /api/skills`, `POST /api/skills/install` |
| Memory | `GET /api/memory`, `POST /api/memory/reload` |
| Uploads | `POST /api/threads/{id}/uploads` |
| Threads | `DELETE /api/threads/{id}` |
| Thread Runs | `POST /api/threads/{id}/runs/stream` |
| Feedback | `PUT/GET /api/threads/{id}/runs/{rid}/feedback` |
| Agents | `GET /api/agents`, `POST /api/agents/fork/{name}` |
| Tenant Agents | `POST/GET /api/tenants/{id}/agents` |
| Report Templates | `GET/POST /api/report-templates` |
| Report Runs | `GET /api/report-runs` |
| Insights | `GET /api/insights/*` |

Nginx 代理: `/api/langgraph/*` → LangGraph, 其他 `/api/*` → Gateway。

---

## 核心系统

### 工具系统

`get_available_tools()` 组装:
1. **配置定义工具** - `config.yaml` via `resolve_variable()`
2. **MCP 工具** - 启用的 MCP 服务器（懒加载，mtime 缓存失效）
3. **内置工具**: `present_files`, `ask_clarification`, `view_image`, `http_connector`, `setup_agent`, `update_agent`, `create/list/update/close_closure_ticket`
4. **子代理工具** (可选): `task`

详见 [docs/TOOLS_SYSTEM.md](docs/TOOLS_SYSTEM.md)

### 报告模板

DSL 驱动的报告生成平台:
- 用户用 YAML 描述报告
- 运行时通过 GenUI 收集输入
- 白名单脚本执行
- 输出 Markdown/PDF

**两条执行路径**:
- `executor_type: dsl` (默认) - DSL 模板引擎
- `executor_type: direct` - 直接脚本执行

详见 [docs/REPORT_TEMPLATES.md](docs/REPORT_TEMPLATES.md)

### 记忆系统

基于 LLM 的长期记忆:
- 每用户隔离存储
- LLM 事实提取
- 防抖更新队列
- 原子文件 I/O

详见 [docs/MEMORY_SYSTEM.md](docs/MEMORY_SYSTEM.md)

### 洞察系统

闭环反馈系统:
- 反馈分析
- 闭环知识提取
- 改进建议生成
- 记忆集成

详见 [docs/INSIGHTS_SYSTEM.md](docs/INSIGHTS_SYSTEM.md)

### 知识库

RAG 知识库访问:
- `KnowledgeBaseRepository` 管理
- 租户隔离
- KB 绑定 embedding
- 异步索引调度器

详见 [docs/RAG.md](docs/RAG.md)

---

## 开发工作流

### 测试驱动开发 (TDD) — 强制

**每个新功能或 bug 修复必须附带单元测试。无例外。**

```bash
# 运行所有测试
make test

# 运行特定测试文件
PYTHONPATH=. uv run pytest tests/test_<feature>.py -v
```

### 运行完整应用

从**项目根目录**:
```bash
make dev
```

应用访问地址: `http://localhost:2026`

| 模式 | 命令 |
|------|------|
| 本地前台 | `make dev` |
| 本地后台 | `make dev-daemon` |
| Docker 开发 | `make docker-start` |
| Docker 生产 | `make up` |

### Nginx 路由

- `/api/langgraph/*` → Gateway 嵌入式运行时 (8001)，重写为 `/api/*`
- `/api/*` (其他) → Gateway API (8001)
- `/` (非 API) → Frontend (3000)

### 代码风格

- 使用 `ruff` 进行代码检查和格式化
- 行长度: 240 字符
- Python 3.12+ 带类型提示
- 双引号，空格缩进

---

## 文档

详见 `docs/` 目录:

| 文档 | 说明 |
|------|------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构概览 |
| [API.md](docs/API.md) | API 参考 |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | 配置选项 |
| [SETUP.md](docs/SETUP.md) | 安装指南 |
| [MIDDLEWARES.md](docs/MIDDLEWARES.md) | 中间件系统详解 |
| [AGENTS_SYSTEM.md](docs/AGENTS_SYSTEM.md) | 多级 Agent 系统 |
| [REPORT_TEMPLATES.md](docs/REPORT_TEMPLATES.md) | 报告模板平台 |
| [TOOLS_SYSTEM.md](docs/TOOLS_SYSTEM.md) | 工具系统 |
| [MEMORY_SYSTEM.md](docs/MEMORY_SYSTEM.md) | 记忆系统 |
| [INSIGHTS_SYSTEM.md](docs/INSIGHTS_SYSTEM.md) | 洞察系统 |
| [RAG.md](docs/RAG.md) | 知识库 |
| [HTTP_CONNECTORS.md](docs/HTTP_CONNECTORS.md) | HTTP 连接器 |
| [STREAMING.md](docs/STREAMING.md) | 流式设计 |

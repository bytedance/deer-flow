# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**DeerFlow** (Deep Exploration and Efficient Research Flow) 是一个开源的**超级代理框架**，编排子代理、记忆和沙箱来完成几乎任何任务——由可扩展技能驱动。

**技术栈**: Python 3.12+, Next.js 16, LangGraph, FastAPI, PostgreSQL/SQLite

**架构**:

```
┌─────────────────────────────────────────────────────────────────┐
│                      用户 (浏览器)                                │
└───────────────────────────┬─────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Nginx (端口 2026)                              │
│              统一反向代理入口                                     │
│  /api/langgraph/* → Gateway (8001) 重写为 /api/*                │
│  /api/*           → Gateway (8001)                              │
│  /*               → Frontend (3000)                             │
└───────────────────────────┬─────────────────────────────────────┘
                            ▼
        ┌───────────────────┴───────────────────┐
        ▼                                       ▼
┌─────────────────────┐               ┌─────────────────────┐
│   Gateway API       │               │    Frontend         │
│   (端口 8001)        │               │    (端口 3000)       │
│                     │               │                     │
│  - FastAPI          │               │  - Next.js 16       │
│  - Agent 运行时     │               │  - React 19         │
│  - 线程管理         │               │  - TypeScript       │
│  - SSE 流式响应     │               │  - Tailwind CSS     │
└─────────────────────┘               └─────────────────────┘
```

## 快速开始

### 常用命令

```bash
# 根目录 (完整应用)
make check      # 检查系统要求
make install    # 安装所有依赖
make dev        # 启动所有服务 (Gateway + Frontend + Nginx)
make stop       # 停止所有服务

# Backend 目录
make test       # 运行所有后端测试
make lint       # ruff 代码检查

# Frontend 目录
pnpm dev        # 启动开发服务器
pnpm check      # Lint + 类型检查
```

### 访问地址

- **应用**: http://localhost:2026
- **Gateway API**: http://localhost:8001
- **Frontend**: http://localhost:3000

---

## 导航指引

### 按任务查找文档

| 我想... | 阅读文档 |
|---------|----------|
| 理解整体架构 | [backend/docs/ARCHITECTURE.md](backend/docs/ARCHITECTURE.md) |
| 添加新工具 | [backend/docs/TOOLS_SYSTEM.md](backend/docs/TOOLS_SYSTEM.md) |
| 修改中间件行为 | [backend/docs/MIDDLEWARES.md](backend/docs/MIDDLEWARES.md) |
| 配置 MCP 服务器 | [backend/docs/MCP_SERVER.md](backend/docs/MCP_SERVER.md) |
| 创建自定义 Agent | [backend/docs/AGENTS_SYSTEM.md](backend/docs/AGENTS_SYSTEM.md) |
| 开发报告模板 | [backend/docs/REPORT_TEMPLATES.md](backend/docs/REPORT_TEMPLATES.md) |
| 调试记忆系统 | [backend/docs/MEMORY_SYSTEM.md](backend/docs/MEMORY_SYSTEM.md) |
| 理解知识库 | [backend/docs/RAG.md](backend/docs/RAG.md) |
| 配置 HTTP 连接器 | [backend/docs/HTTP_CONNECTORS.md](backend/docs/HTTP_CONNECTORS.md) |
| 理解流式设计 | [backend/docs/STREAMING.md](backend/docs/STREAMING.md) |

### 按模块查找代码

| 模块 | 路径 | 说明 |
|------|------|------|
| Agent 系统 | `backend/packages/harness/deerflow/agents/` | Lead Agent、中间件、记忆 |
| 工具系统 | `backend/packages/harness/deerflow/tools/` | 内置工具、社区工具 |
| 沙箱 | `backend/packages/harness/deerflow/sandbox/` | 沙箱执行、文件操作 |
| Gateway API | `backend/app/gateway/` | FastAPI 路由 |
| IM 渠道 | `backend/app/channels/` | 飞书、Slack、Telegram、钉钉 |
| 前端组件 | `frontend/src/components/` | UI 组件 |
| 前端业务逻辑 | `frontend/src/core/` | 线程、API、工件 |

---

## Skill 路由

当用户请求匹配可用技能时，通过 Skill 工具调用。如有疑问，调用技能。

关键路由规则:

- 产品想法/头脑风暴 → 调用 `/office-hours`
- 策略/范围 → 调用 `/plan-ceo-review`
- 架构 → 调用 `/plan-eng-review`
- 设计系统/计划审查 → 调用 `/design-consultation` 或 `/plan-design-review`
- 完整审查流程 → 调用 `/autoplan`
- Bug/错误 → 调用 `/investigate`
- QA/测试站点行为 → 调用 `/qa` 或 `/qa-only`
- 代码审查/差异检查 → 调用 `/review`
- 视觉优化 → 调用 `/design-review`
- 发布/部署/PR → 调用 `/ship` 或 `/land-and-deploy`
- 保存进度 → 调用 `/context-save`
- 恢复上下文 → 调用 `/context-restore`

---

## 个人助手 UX

系统实现"温暖助手"人格，具备工业领域感知:

**助手人格**: 系统提示包含 `<assistant_persona>` 部分，带语气分级 (Normal/Attention/Warning/Emergency)、共情指南和语言跟随规则。

**问候 API**: `GET /api/threads/{thread_id}/greeting` 返回个性化问候，带上下文感知建议。

**共情错误处理**: 后端映射异常到 `ErrorCategory` 枚举 (`network_issue`, `timeout`, `service_unavailable`, `data_not_found`, `permission_denied`, `rate_limited`)。前端渲染可展开错误卡片，带重试按钮。

**关怀循环跟进**: 分析完成后，助手总结发现并提供 1-2 个后续行动。`pendingFollowUp` 事实存储在记忆中，在后续问候中浮现。

**助手状态指示器**: 状态文本从活动工具调用派生 (数据工具 → "正在查询数据…", 报告工具 → "正在生成报告…", 分析工具 → "正在分析…")。

**助手头像**: 消息气泡显示代理头像图标和显示名称，从代理配置获取。

---

## 关键约束

### Harness / App 分层

- **Harness** (`packages/harness/deerflow/`): 可发布的代理框架。导入前缀: `deerflow.*`
- **App** (`app/`): 应用代码。导入前缀: `app.*`
- **规则**: App 导入 deerflow，但 deerflow **永不**导入 app (CI 强制执行)

### 测试要求

- **TDD 强制**: 每个新功能/修复必须附带测试
- **覆盖率**: 80%+
- **运行测试**: `make test`

### 代码风格

- **Backend**: ruff, 240 字符行长度, Python 3.12+
- **Frontend**: ESLint, Prettier, TypeScript 5.8+

---

## 文档

### 快速链接

- [backend/CLAUDE.md](backend/CLAUDE.md) - 后端开发详细指南
- [frontend/CLAUDE.md](frontend/CLAUDE.md) - 前端开发详细指南
- [README.md](README.md) - 项目介绍和安装
- [CONTRIBUTING.md](CONTRIBUTING.md) - 贡献指南

### 后端文档 (backend/docs/)

| 文档 | 说明 |
|------|------|
| [ARCHITECTURE.md](backend/docs/ARCHITECTURE.md) | 系统架构概览 |
| [API.md](backend/docs/API.md) | API 参考 |
| [CONFIGURATION.md](backend/docs/CONFIGURATION.md) | 配置选项 |
| [MIDDLEWARES.md](backend/docs/MIDDLEWARES.md) | 中间件系统详解 |
| [AGENTS_SYSTEM.md](backend/docs/AGENTS_SYSTEM.md) | 多级 Agent 系统 |
| [REPORT_TEMPLATES.md](backend/docs/REPORT_TEMPLATES.md) | 报告模板平台 |
| [TOOLS_SYSTEM.md](backend/docs/TOOLS_SYSTEM.md) | 工具系统 |
| [MEMORY_SYSTEM.md](backend/docs/MEMORY_SYSTEM.md) | 记忆系统 |
| [INSIGHTS_SYSTEM.md](backend/docs/INSIGHTS_SYSTEM.md) | 洞察系统 |
| [RAG.md](backend/docs/RAG.md) | 知识库 |

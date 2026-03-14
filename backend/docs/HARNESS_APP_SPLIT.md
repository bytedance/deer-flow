# DeerFlow 后端拆分设计文档：Harness + App

> 状态：Draft
> 作者：DeerFlow Team
> 日期：2026-03-13

## 1. 背景与动机

DeerFlow 后端当前是一个单一 Python 包（`src.*`），包含了从底层 agent 编排到上层用户产品的所有代码。随着项目发展，这种结构带来了几个问题：

- **复用困难**：其他产品（CLI 工具、Slack bot、第三方集成）想用 agent 能力，必须依赖整个后端，包括 FastAPI、IM SDK 等不需要的依赖
- **职责模糊**：agent 编排逻辑和用户产品逻辑混在同一个 `src/` 下，边界不清晰
- **依赖膨胀**：LangGraph Server 运行时不需要 FastAPI/uvicorn/Slack SDK，但当前必须安装全部依赖

本文档提出将后端拆分为两部分：**deerflow-harness**（可发布的 agent 框架包）和 **app**（不打包的用户产品代码）。

## 2. 核心概念

### 2.1 Harness（线束/框架层）

Harness 是 agent 的构建与编排框架，回答 **"如何构建和运行 agent"** 的问题：

- Agent 工厂与生命周期管理
- Middleware pipeline
- 工具系统（内置工具 + MCP + 社区工具）
- 沙箱执行环境
- 子 agent 委派
- 记忆系统
- 技能加载与注入
- 模型工厂
- 配置系统

**Harness 是一个可发布的 Python 包**（`deerflow-harness`），可以独立安装和使用。

**Harness 的设计原则**：对上层应用完全无感知。它不知道也不关心谁在调用它——可以是 Web App、CLI、Slack Bot、或者一个单元测试。

### 2.2 App（应用层）

App 是面向用户的产品代码，回答 **"如何将 agent 呈现给用户"** 的问题：

- Gateway API（FastAPI REST 接口）
- IM Channels（飞书、Slack、Telegram 集成）
- Custom Agent 的 CRUD 管理
- 文件上传/下载的 HTTP 接口

**App 不打包、不发布**，它是 DeerFlow 项目内部的应用代码，直接运行。

**App 依赖 Harness，但 Harness 不依赖 App。**

### 2.3 边界划分

| 模块 | 归属 | 说明 |
|------|------|------|
| `config/` | Harness | 配置系统是基础设施 |
| `reflection/` | Harness | 动态模块加载工具 |
| `utils/` | Harness | 通用工具函数 |
| `agents/` | Harness | Agent 工厂、middleware、state、memory |
| `subagents/` | Harness | 子 agent 委派系统 |
| `sandbox/` | Harness | 沙箱执行环境 |
| `tools/` | Harness | 工具注册与发现 |
| `mcp/` | Harness | MCP 协议集成 |
| `skills/` | Harness | 技能加载、解析、定义 schema |
| `models/` | Harness | LLM 模型工厂 |
| `community/` | Harness | 社区工具（tavily、jina 等） |
| `client.py` | Harness | 嵌入式 Python 客户端 |
| `gateway/` | App | FastAPI REST API |
| `channels/` | App | IM 平台集成 |

**关于 Custom Agents**：agent 定义格式（`config.yaml` + `SOUL.md` schema）由 Harness 层的 `config/agents_config.py` 定义，但文件的存储、CRUD、发现机制由 App 层的 `gateway/routers/agents.py` 负责。

## 3. 目标架构

### 3.1 目录结构

```
backend/
├── packages/
│   └── harness/
│       ├── pyproject.toml          # deerflow-harness 包定义
│       └── deerflow/               # Python 包根（import 前缀: deerflow.*）
│           ├── __init__.py
│           ├── config/
│           ├── reflection/
│           ├── utils/
│           ├── agents/
│           │   ├── lead_agent/
│           │   ├── middlewares/
│           │   ├── memory/
│           │   ├── checkpointer/
│           │   └── thread_state.py
│           ├── subagents/
│           ├── sandbox/
│           ├── tools/
│           ├── mcp/
│           ├── skills/
│           ├── models/
│           ├── community/
│           └── client.py
├── app/                            # 不打包（import 前缀: app.*）
│   ├── __init__.py
│   ├── gateway/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── config.py
│   │   ├── path_utils.py
│   │   └── routers/
│   └── channels/
│       ├── __init__.py
│       ├── base.py
│       ├── manager.py
│       ├── service.py
│       ├── store.py
│       ├── message_bus.py
│       ├── feishu.py
│       ├── slack.py
│       └── telegram.py
├── pyproject.toml                  # uv workspace root
├── langgraph.json
├── tests/
├── docs/
└── Makefile
```

### 3.2 Import 规则

两个层使用不同的 import 前缀，职责边界一目了然：

```python
# ---------------------------------------------------------------
# Harness 内部互相引用（deerflow.* 前缀）
# ---------------------------------------------------------------
from deerflow.agents import make_lead_agent
from deerflow.models import create_chat_model
from deerflow.config import get_app_config
from deerflow.tools import get_available_tools

# ---------------------------------------------------------------
# App 内部互相引用（app.* 前缀）
# ---------------------------------------------------------------
from app.gateway.app import app
from app.gateway.routers.uploads import upload_files
from app.channels.service import start_channel_service

# ---------------------------------------------------------------
# App 调用 Harness（单向依赖，Harness 永远不 import app）
# ---------------------------------------------------------------
from deerflow.agents import make_lead_agent
from deerflow.models import create_chat_model
from deerflow.skills import load_skills
from deerflow.config.extensions_config import get_extensions_config
```

**App 调用 Harness 示例 — Gateway 中启动 agent**：

```python
# app/gateway/routers/chat.py
from deerflow.agents.lead_agent.agent import make_lead_agent
from deerflow.models import create_chat_model
from deerflow.config import get_app_config

async def create_chat_session(thread_id: str, model_name: str):
    config = get_app_config()
    model = create_chat_model(name=model_name)
    agent = make_lead_agent(config=...)
    # ... 使用 agent 处理用户消息
```

**App 调用 Harness 示例 — Channel 中查询 skills**：

```python
# app/channels/manager.py
from deerflow.skills import load_skills
from deerflow.agents.memory.updater import get_memory_data

def handle_status_command():
    skills = load_skills(enabled_only=True)
    memory = get_memory_data()
    return f"Skills: {len(skills)}, Memory facts: {len(memory.get('facts', []))}"
```

**禁止方向**：Harness 代码中绝不能出现 `from app.` 或 `import app.`。

### 3.3 为什么 App 不打包

| 方面 | 打包（放 packages/ 下） | 不打包（放 backend/app/） |
|------|------------------------|--------------------------|
| 命名空间 | 需要 pkgutil `extend_path` 合并，或独立前缀 | 天然独立，`app.*` vs `deerflow.*` |
| 发布需求 | 没有——App 是项目内部代码 | 不需要 pyproject.toml |
| 复杂度 | 需要管理两个包的构建、版本、依赖声明 | 直接运行，零额外配置 |
| 运行方式 | `pip install deerflow-app` | `PYTHONPATH=. uvicorn app.gateway.app:app` |

App 的唯一消费者是 DeerFlow 项目自身，没有独立发布的需求。放在 `backend/app/` 下作为普通 Python 包，通过 `PYTHONPATH` 或 editable install 让 Python 找到即可。

### 3.4 依赖关系

```
┌─────────────────────────────────────┐
│  app/  (不打包，直接运行)             │
│  ├── fastapi, uvicorn               │
│  ├── slack-sdk, lark-oapi, ...      │
│  └── import deerflow.*              │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  deerflow-harness  (可发布的包)       │
│  ├── langgraph, langchain           │
│  ├── markitdown, pydantic, ...      │
│  └── 零 app 依赖                     │
└─────────────────────────────────────┘
```

**依赖分类**：

| 分类 | 依赖包 |
|------|--------|
| Harness only | agent-sandbox, langchain*, langgraph*, markdownify, markitdown, pydantic, pyyaml, readabilipy, tavily-python, firecrawl-py, tiktoken, ddgs, duckdb, httpx, kubernetes, dotenv |
| App only | fastapi, uvicorn, sse-starlette, python-multipart, lark-oapi, slack-sdk, python-telegram-bot, markdown-to-mrkdwn |
| Shared | langgraph-sdk（channels 用 HTTP client）, pydantic, httpx |

### 3.5 Workspace 配置

`backend/pyproject.toml`（workspace root）：

```toml
[project]
name = "deer-flow"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["deerflow-harness"]

[dependency-groups]
dev = ["pytest>=8.0.0", "ruff>=0.14.11"]
# App 的额外依赖（fastapi 等）也声明在 workspace root，因为 app 不打包
app = ["fastapi", "uvicorn", "sse-starlette", "python-multipart"]
channels = ["lark-oapi", "slack-sdk", "python-telegram-bot"]

[tool.uv.workspace]
members = ["packages/harness"]

[tool.uv.sources]
deerflow-harness = { workspace = true }
```

## 4. 当前的跨层依赖问题

在拆分之前，需要先解决 `client.py` 中两处从 harness 到 app 的反向依赖：

### 4.1 `_validate_skill_frontmatter`

```python
# client.py — harness 导入了 app 层代码
from src.gateway.routers.skills import _validate_skill_frontmatter
```

**解决方案**：将该函数提取到 `deerflow/skills/validation.py`。这是一个纯逻辑函数（解析 YAML frontmatter、校验字段），与 FastAPI 无关。

### 4.2 `CONVERTIBLE_EXTENSIONS` + `convert_file_to_markdown`

```python
# client.py — harness 导入了 app 层代码
from src.gateway.routers.uploads import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown
```

**解决方案**：将它们提取到 `deerflow/utils/file_conversion.py`。仅依赖 `markitdown` + `pathlib`，是通用工具函数。

## 5. 基础设施变更

### 5.1 LangGraph Server

LangGraph Server 只需要 harness 包。`langgraph.json` 更新：

```json
{
  "dependencies": ["./packages/harness"],
  "graphs": {
    "lead_agent": "deerflow.agents:make_lead_agent"
  },
  "checkpointer": {
    "path": "./packages/harness/deerflow/agents/checkpointer/async_provider.py:make_checkpointer"
  }
}
```

### 5.2 Gateway API

```bash
# serve.sh / Makefile
# PYTHONPATH 包含 backend/ 根目录，使 app.* 和 deerflow.* 都能被找到
PYTHONPATH=. uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001
```

### 5.3 Nginx

无需变更（只做 URL 路由，不涉及 Python 模块路径）。

### 5.4 Docker

Dockerfile 中的 module 引用从 `src.` 改为 `deerflow.` / `app.`，`COPY` 命令需覆盖 `packages/` 和 `app/` 目录。

## 6. 实施计划

分 3 个 PR 递进执行：

### PR 1：提取共享工具函数（Low Risk）

1. 创建 `src/skills/validation.py`，从 `gateway/routers/skills.py` 提取 `_validate_skill_frontmatter`
2. 创建 `src/utils/file_conversion.py`，从 `gateway/routers/uploads.py` 提取文件转换逻辑
3. 更新 `client.py`、`gateway/routers/skills.py`、`gateway/routers/uploads.py` 的 import
4. 运行全部测试确认无回归

### PR 2：Rename + 物理拆分（High Risk，原子操作）

1. 创建 `packages/harness/` 目录，创建 `pyproject.toml`
2. `git mv` 将 harness 相关模块从 `src/` 移入 `packages/harness/deerflow/`
3. `git mv` 将 app 相关模块从 `src/` 移入 `app/`
4. 全局替换 import：
   - harness 模块：`src.*` → `deerflow.*`（所有 `.py` 文件、`langgraph.json`、测试、文档）
   - app 模块：`src.gateway.*` → `app.gateway.*`、`src.channels.*` → `app.channels.*`
5. 更新 workspace root `pyproject.toml`
6. 更新 `langgraph.json`、`Makefile`、`Dockerfile`
7. `uv sync` + 全部测试 + 手动验证服务启动

### PR 3：边界检查 + 文档（Low Risk）

1. 添加 lint 规则：检查 harness 不 import app 模块
2. 更新 `CLAUDE.md`、`README.md`

## 7. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 全局 rename 误伤 | 字符串中的 `src` 被错误替换 | 正则精确匹配 `\bsrc\.`，review diff |
| LangGraph Server 找不到模块 | 服务启动失败 | `langgraph.json` 的 `dependencies` 指向正确的 harness 包路径 |
| App 的 `PYTHONPATH` 缺失 | Gateway/Channel 启动 import 报错 | Makefile/Docker 统一设置 `PYTHONPATH=.` |
| `config.yaml` 中的 `use` 字段引用旧路径 | 运行时模块解析失败 | `config.yaml` 中的 `use` 字段同步更新为 `deerflow.*` |
| 测试中 `sys.path` 混乱 | 测试失败 | 用 editable install（`uv sync`）确保 deerflow 可导入，`conftest.py` 中添加 `app/` 到 `sys.path` |

## 8. 未来演进

- **独立发布**：harness 可以发布到内部 PyPI，让其他项目直接 `pip install deerflow-harness`
- **插件化 App**：不同的 app（web、CLI、bot）可以各自独立，都依赖同一个 harness
- **更细粒度拆分**：如果 harness 内部模块继续增长，可以进一步拆分（如 `deerflow-sandbox`、`deerflow-mcp`）

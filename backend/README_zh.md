# DeerFlow 后端

**语言：** [English](README.md) | 简体中文

DeerFlow 是一个基于 LangGraph 的 AI 超级智能体，具备沙箱执行、持久记忆和可扩展工具集成能力。后端使 AI 智能体能够执行代码、浏览网页、管理文件、将任务委派给子智能体，并在多轮对话之间保留上下文——所有操作都在按线程隔离的环境中进行。

---

## 架构

```
                        ┌──────────────────────────────────────┐
                        │          Nginx（端口 2026）          │
                        │             统一反向代理             │
                        └───────┬──────────────────┬───────────┘
                                │
            /api/langgraph/*    │    /api/*（其他）
              重写为 /api/*     │
                                ▼
               ┌────────────────────────────────────────┐
               │          Gateway API（8001）           │
               │      FastAPI REST + 智能体运行时       │
               │                                        │
               │ 模型、MCP、技能、记忆、上传、          │
               │ 产物、线程、运行、流式传输             │
               │                                        │
               │ ┌────────────────────────────────────┐ │
               │ │ 主智能体                           │ │
               │ │ 中间件链、工具、子智能体           │ │
               │ └────────────────────────────────────┘ │
               └────────────────────────────────────────┘
```

**请求路由**（通过 Nginx）：

- `/api/langgraph/*` → 与 LangGraph 兼容的 Gateway API——智能体交互、线程和流式传输
- `/api/*`（其他）→ Gateway API——模型、MCP、技能、记忆、产物、上传和线程本地数据清理
- `/`（非 API）→ 前端——Next.js Web 界面

---

## 核心组件

### 主智能体

唯一的 LangGraph 智能体（`lead_agent`）是运行时入口，通过 `make_lead_agent(config)` 创建。它组合了：

- 支持思考和视觉能力的**动态模型选择**
- 处理横切关注点的**中间件链**（9 个中间件）
- 包含沙箱、MCP、社区工具和内置工具的**工具系统**
- 用于并行执行任务的**子智能体委派**
- 注入技能、记忆上下文和工作目录指导的**系统提示词**

### 中间件链

中间件按照严格顺序执行，每个中间件负责一个特定关注点：

| # | 中间件 | 用途 |
|---|--------|------|
| 1 | **ThreadDataMiddleware** | 为每个线程创建独立目录（工作区、上传、输出） |
| 2 | **UploadsMiddleware** | 将新上传的文件注入对话上下文 |
| 3 | **SandboxMiddleware** | 获取用于代码执行的沙箱环境 |
| 4 | **SummarizationMiddleware** | 接近 Token 限制时压缩上下文（可选） |
| 5 | **TodoListMiddleware** | 在计划模式中跟踪多步骤任务（可选） |
| 6 | **TitleMiddleware** | 在第一次交互后自动生成对话标题 |
| 7 | **MemoryMiddleware** | 将对话加入异步记忆提取队列 |
| 8 | **ViewImageMiddleware** | 为支持视觉的模型注入图像数据（有条件启用） |
| 9 | **ClarificationMiddleware** | 拦截澄清请求并中断执行（必须放在最后） |

### 沙箱系统

按线程隔离执行，并提供虚拟路径转换：

- **抽象接口**：`execute_command`、`read_file`、`write_file`、`list_dir`
- **提供程序**：`LocalSandboxProvider`（文件系统）和 `AioSandboxProvider`（Docker，位于 `community/`）。异步运行时路径使用异步沙箱生命周期钩子，使启动、就绪轮询和释放操作不会阻塞事件循环。`AioSandboxProvider` 会在获取或复用期间验证活跃缓存和预热池中的容器，移除已确定失效的条目，使线程能够在容器意外退出后创建新沙箱，同时让 `get()` 保持为内存查询。后端健康检查失败会被视为状态未知，而不是容器已失效；在发现过程中无法验证的容器不会被采用，获取流程会继续创建容器，而不是直接失败。
- **虚拟路径**：`/mnt/user-data/{workspace,uploads,outputs}` → 线程专属的物理目录
- **技能路径**：`/mnt/skills` → `deer-flow/skills/` 目录
- **技能加载**：递归发现 `skills/{public,custom}` 下嵌套的 `SKILL.md` 文件，并保留其嵌套容器路径
- **SkillScan**：安装技能或由智能体写入技能时，原生离线确定性扫描会先于 LLM 技能扫描器执行；`CRITICAL` 级别的问题会阻止操作，警告则会成为 LLM 上下文
- **文件写入安全**：`str_replace` 按照 `(sandbox.id, path)` 对“读取—修改—写入”操作进行串行化，因此即使虚拟路径相同，彼此隔离的沙箱仍能保持并发
- **工具**：`bash`、`ls`、`read_file`、`write_file`、`str_replace`（`write_file` 默认覆盖文件，并提供 `append` 以在文件末尾追加内容；使用 `LocalSandboxProvider` 时，`bash` 默认禁用；如需隔离的 Shell 访问，请使用 `AioSandboxProvider`）

### 子智能体系统

支持并发执行的异步任务委派：

- **内置智能体**：`general-purpose`（完整工具集）和 `bash`（命令专家，仅在 Shell 访问可用时提供）
- **并发限制**：每轮最多 3 个子智能体，超时时间为 15 分钟
- **执行方式**：后台线程池，并提供状态跟踪和 SSE 事件
- **流程**：智能体调用 `task()` 工具 → 执行器在后台运行子智能体 → 轮询完成状态 → 返回结果

### 记忆系统

由 LLM 驱动、可跨对话保留上下文的持久记忆：

- **自动提取**：分析对话中的用户上下文、事实和偏好
- **作用域安全写入**：中间件提取过程只存储持久且具有描述性的用户级事实；全局摘要同样需要描述权限。当缺少作用域元数据，或者内容仅限于某个任务或项目时，矛盾移除和事实合并将采用失败关闭策略
- **原子替换**：与替换项关联的矛盾移除，只有在替换项通过作用域和置信度门控、去重及事实数量裁剪后才会执行
- **结构化存储**：用户上下文（工作、个人、当前关注事项）、历史记录以及带置信度评分的事实
- **防抖更新**：批量处理更新以减少 LLM 调用次数（等待时间可配置）
- **系统提示词注入**：将最重要的事实和上下文注入智能体提示词
- **运行级记忆标识**：`GET /api/threads/{thread_id}/runs/{run_id}/events?event_types=context:memory` 返回实际隐藏记忆块的 SHA-256 标识，而不会把记忆文本复制进事件存储
- **存储方式**：JSON 文件，并基于 mtime 实现缓存失效

### 工具生态系统

| 类别 | 工具 |
|------|------|
| **沙箱** | `bash`、`ls`、`read_file`、`write_file`、`str_replace` |
| **内置** | `present_files`、`ask_clarification`、`view_image`、`task`（子智能体） |
| **社区** | Tavily（网页搜索）、Jina AI（网页获取）、Crawl4AI（网页获取）、Firecrawl（网页抓取）、fastCRW（网页抓取）、DuckDuckGo（图片搜索） |
| **MCP** | 任意 Model Context Protocol 服务器（stdio、SSE、HTTP 传输） |
| **技能** | 通过系统提示词注入的领域专用工作流 |

### Gateway API

FastAPI 应用程序，为前端集成提供 REST 接口：

| 路由 | 用途 |
|------|------|
| `GET /api/models` | 列出可用的 LLM 模型 |
| `GET/PUT /api/mcp/config` | 管理 MCP 服务器配置 |
| `POST /api/mcp/cache/reset` | 重置缓存的 MCP 工具，使其在下次使用时重新加载 |
| `GET/PUT /api/skills` | 列出并管理技能 |
| `POST /api/skills/install` | 从 `.skill` 归档文件安装技能 |
| `GET /api/memory` | 获取记忆数据 |
| `POST /api/memory/reload` | 强制重新加载记忆 |
| `GET /api/memory/config` | 获取记忆配置 |
| `GET /api/memory/status` | 获取组合后的配置和数据状态 |
| `GET /api/threads/{id}/runs/{run_id}/events` | 获取某次运行的调试或审计事件；可使用 `event_types=context:memory` 筛选实际记忆标识 |
| `POST /api/threads/{id}/uploads` | 上传文件（自动将 PDF、PPT、Excel、Word 转换为 Markdown；拒绝目录路径；自动重命名单次请求中的重复文件名） |
| `GET /api/threads/{id}/uploads/list` | 列出已上传的文件 |
| `DELETE /api/threads/{id}` | 删除 LangGraph 线程后，清除由 DeerFlow 管理的本地线程数据；意外错误会记录在服务端，并返回通用的 500 错误信息 |
| `GET /api/threads/{id}/artifacts/{path}` | 提供生成产物的访问 |

### 即时通信渠道

即时通信桥接支持飞书、Slack 和 Telegram。Slack 和 Telegram 仍然使用最终的 `runs.wait()` 响应路径；飞书现在通过 `runs.stream(["messages-tuple", "values"])` 进行流式传输，在渠道管理器内部对同一线程中快速连续到达的请求进行串行化，并针对每条源消息原地更新线程内的同一张卡片。

对于飞书卡片更新，DeerFlow 会按每条入站消息保存运行中卡片的 `message_id`，并持续更新同一张卡片直到运行结束，同时保留现有的 `OK` / `DONE` 表情回应流程。当现有飞书话题中的上一轮仍在运行时收到后续消息，新消息会在映射的 DeerFlow `thread_id` 上等待，在对应的源消息上显示排队中或运行中的卡片，并在后续更新中保留简洁的源消息引用块，使快速连续提出的问题仍然容易区分。

---

## 快速开始

### 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- 所选 LLM 提供商的 API 密钥

### 安装

```bash
cd deer-flow

# 复制配置文件
cp config.example.yaml config.yaml

# 安装后端依赖
cd backend
make install
```

### 配置

编辑项目根目录中的 `config.yaml`：

```yaml
models:
  - name: gpt-4o
    display_name: GPT-4o
    use: langchain_openai:ChatOpenAI
    model: gpt-4o
    api_key: $OPENAI_API_KEY
    supports_thinking: false
    supports_vision: true

  - name: gpt-5-responses
    display_name: GPT-5 (Responses API)
    use: langchain_openai:ChatOpenAI
    model: gpt-5
    api_key: $OPENAI_API_KEY
    use_responses_api: true
    output_version: responses/v1
    supports_vision: true
```

设置 API 密钥：

```bash
export OPENAI_API_KEY="your-api-key-here"
```

### 运行

**完整应用程序**（从项目根目录运行）：

```bash
make dev  # 启动 Gateway、Frontend 和 Nginx
```

访问地址：http://localhost:2026

**仅运行后端**（从 backend 目录运行）：

```bash
# Gateway API + 嵌入式智能体运行时
make dev
```

直接访问：Gateway 位于 http://localhost:8001

**终端工作台（TUI）**——基于嵌入式 Harness 的终端原生界面，
无需运行任何服务：

```bash
uv pip install 'deerflow-harness[tui]'   # 可选的 textual 依赖
deerflow                                 # 启动 TUI
deerflow --print "summarize this repo"   # 无界面的单次运行
deerflow --recursion-limit 250 --print "run a longer task"
```

在 TUI 中打开的会话会出现在 Web UI 侧边栏中（它会在本地默认用户下写入共享的 `threads_meta` 存储）。详见 [docs/TUI.md](docs/TUI.md)。

---

## 项目结构

```
backend/
├── packages/harness/           # deerflow-harness 包（导入路径：deerflow.*）
│   └── deerflow/
│       ├── agents/             # 智能体系统
│       │   ├── lead_agent/     # 主智能体（工厂、提示词）
│       │   ├── middlewares/    # 中间件组件
│       │   ├── memory/         # 记忆提取与存储
│       │   └── thread_state.py # ThreadState 数据结构
│       ├── sandbox/            # 沙箱执行
│       │   ├── local/          # 本地文件系统提供程序
│       │   ├── sandbox.py      # 抽象接口
│       │   ├── tools.py        # bash、ls、read/write/str_replace
│       │   └── middleware.py   # 沙箱生命周期
│       ├── subagents/          # 子智能体委派
│       │   ├── builtins/       # general-purpose、bash 智能体
│       │   ├── executor.py     # 后台执行引擎
│       │   └── registry.py     # 智能体注册表
│       ├── tools/builtins/     # 内置工具
│       ├── mcp/                # MCP 协议集成
│       ├── models/             # 模型工厂
│       ├── skills/             # 技能发现与加载
│       ├── config/             # 配置系统
│       ├── runtime/            # 嵌入式运行执行（RunManager、StreamBridge）
│       ├── persistence/        # Checkpointer/Store 引擎和数据库结构迁移
│       ├── guardrails/         # 工具调用前的授权提供程序
│       ├── tracing/            # Tracer 工厂和追踪元数据
│       ├── uploads/            # 上传管理器
│       ├── tui/                # 终端 UI（`deerflow` 控制台脚本）
│       ├── community/          # 社区工具和提供程序
│       ├── reflection/         # 动态模块加载
│       └── utils/              # 工具函数
├── app/                        # FastAPI Gateway + 即时通信渠道（导入路径：app.*）
│   ├── gateway/                # Gateway API
│   │   ├── app.py              # 应用程序配置
│   │   └── routers/            # 路由模块
│   └── channels/               # 即时通信渠道集成
├── docs/                       # 文档
├── tests/                      # 测试套件
├── langgraph.json              # 用于工具和 Studio 兼容性的 LangGraph 图注册表
├── pyproject.toml              # Python 依赖
├── Makefile                    # 开发命令
└── Dockerfile                  # 容器构建文件
```

`langgraph.json` 并不是默认的服务入口。脚本和 Docker 部署使用 Gateway 嵌入式运行时；保留该文件是为了兼容 LangGraph 工具、Studio 或直接运行 LangGraph Server。

---

## 配置

### 主配置（`config.yaml`）

将其放置在项目根目录。以 `$` 开头的配置值会被解析为环境变量。

主要配置节：

- `models`——包含类路径、API 密钥、思考和视觉标志的 LLM 配置
- `tools`——包含模块路径和分组的工具定义
- `tool_groups`——工具的逻辑分组
- `sandbox`——执行环境提供程序
- `skills`——技能目录路径
- `title`——自动生成标题的设置
- `summarization`——上下文摘要设置
- `subagents`——子智能体系统（启用或禁用）
- `memory`——记忆系统设置（启用状态、存储方式、防抖和事实数量限制）

提供商说明：

- `models[*].use` 通过模块路径引用提供商类，例如 `langchain_openai:ChatOpenAI`。
- 如果缺少某个提供商模块，DeerFlow 会返回包含安装指导的可操作错误信息，例如 `uv add langchain-google-genai`。

### 扩展配置（`extensions_config.json`）

在同一个文件中配置 MCP 服务器和技能状态：

```json
{
  "mcpServers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}
    },
    "secure-http": {
      "enabled": true,
      "type": "http",
      "url": "https://api.example.com/mcp",
      "oauth": {
        "enabled": true,
        "token_url": "https://auth.example.com/oauth/token",
        "grant_type": "client_credentials",
        "client_id": "$MCP_OAUTH_CLIENT_ID",
        "client_secret": "$MCP_OAUTH_CLIENT_SECRET"
      }
    },
    "postgres": {
      "enabled": false,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"],
      "description": "PostgreSQL database access",
      "routing": {
        "mode": "prefer",
        "priority": 50,
        "keywords": ["orders", "users", "SQL", "database", "table"]
      },
      "tools": {
        "query": {
          "routing": {
            "priority": 100,
            "keywords": ["query database", "orders table", "metrics"]
          }
        }
      }
    }
  },
  "skills": {
    "pdf-processing": {"enabled": true}
  }
}
```

`routing` 会向智能体提示词添加柔性的 MCP 偏好提示。它能帮助模型在处理匹配的请求时优先选择配置的 MCP 工具，同时不会禁止其他工具。当 `tool_search.enabled=true` 延迟加载 MCP Schema 时，匹配的路由元数据可以在模型调用前自动提升最多 `tool_search.auto_promote_top_k` 个延迟 Schema。

### 环境变量

- `DEER_FLOW_CONFIG_PATH`——覆盖 config.yaml 的位置
- `DEER_FLOW_EXTENSIONS_CONFIG_PATH`——覆盖 extensions_config.json 的位置
- 模型 API 密钥：`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`DEEPSEEK_API_KEY` 等
- 工具 API 密钥：`TAVILY_API_KEY`、`GITHUB_TOKEN` 等

### LangSmith 追踪

DeerFlow 内置了 [LangSmith](https://smith.langchain.com) 可观测性集成。启用后，所有 LLM 调用、智能体运行、工具执行和中间件处理过程都会被追踪，并可在 LangSmith 控制台中查看。

**配置步骤：**

1. 在 [smith.langchain.com](https://smith.langchain.com) 注册并创建一个项目。
2. 将以下内容添加到项目根目录的 `.env` 文件：

```bash
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxx
LANGSMITH_PROJECT=xxx
```

**旧版变量：**为了向后兼容，仍然支持 `LANGCHAIN_TRACING_V2`、`LANGCHAIN_API_KEY`、`LANGCHAIN_PROJECT` 和 `LANGCHAIN_ENDPOINT`。当两组变量同时设置时，优先使用 `LANGSMITH_*` 变量。

### Langfuse 追踪

DeerFlow 同样支持使用 [Langfuse](https://langfuse.com) 观察与 LangChain 兼容的运行过程。

将以下内容添加到 `.env` 文件：

```bash
LANGFUSE_TRACING=true
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxxxxxxxxxx
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

如果使用自托管的 Langfuse 部署，请将 `LANGFUSE_BASE_URL` 设置为你的 Langfuse 主机地址。

### 同时使用两个提供商时的行为

如果同时启用了 LangSmith 和 Langfuse，DeerFlow 会初始化并附加两者的回调，使相同的运行数据同时上报给两个系统。

如果明确启用了某个提供商，但缺少必要凭据，或者无法初始化该提供商的回调，DeerFlow 会在模型创建期间初始化追踪时抛出错误，而不是静默禁用追踪。

**Docker：**在 `docker-compose.yaml` 中，追踪默认处于禁用状态（`LANGSMITH_TRACING=false`）。如需在容器化部署中启用追踪，请在 `.env` 中设置 `LANGSMITH_TRACING=true` 和/或 `LANGFUSE_TRACING=true`，并同时提供所需凭据。

---

## 开发

### 命令

```bash
make install    # 安装依赖
make dev        # 运行 Gateway API 和嵌入式智能体运行时（端口 8001）
make gateway    # 运行不带热重载的 Gateway API（端口 8001）
make lint       # 运行代码检查器（ruff）
make format     # 格式化代码（ruff）
make detect-blocking-io  # 统计可能阻塞后端事件循环的阻塞式 IO
make migrate-rev MSG="..."  # 根据当前 ORM 模型自动生成新的 Alembic 修订
```

### 数据库结构迁移

DeerFlow 的应用程序表（`runs`、`threads_meta`、`feedback`、`users`、`run_events` 和 `channel_*` 表）由 Alembic 管理。Gateway 启动时会通过 `bootstrap_schema(engine, backend=...)` 自动运行 `alembic upgrade head`，因此运维人员不需要在生产环境中手动运行 `alembic`。初始化过程支持并发安全（跨进程使用 PostgreSQL advisory lock；单个 SQLite 进程内按引擎使用 `asyncio.Lock`），并能针对已有数据库结构（空数据库、旧版数据库或已带版本的数据库）保持幂等。

添加或修改 ORM 模型时，请在 `packages/harness/deerflow/persistence/migrations/versions/` 下提交新的迁移版本：

```bash
make migrate-rev MSG="add foo column to runs"
```

该目标会调用 `scripts/_autogen_revision.py`。脚本先在一个新的临时 SQLite 数据库上迁移到 `head`，然后将当前模型与其进行比较，因此全新检出的代码不需要预先存在的 `./data/deerflow.db`。提交前请检查生成的文件，并将原始的 `op.add_column` / `op.drop_column` 调用替换为 `migrations/_helpers.py` 中的幂等辅助函数。项目有意不提供 `make migrate` / `make migrate-stamp` 目标——Gateway 启动是唯一的迁移执行路径，从而避免运维误操作。完整设计请参阅 `backend/CLAUDE.md` 中的“Schema Migrations”部分。

### 代码风格

- **代码检查器/格式化工具**：`ruff`
- **行长度**：240 个字符
- **Python**：3.12+，使用类型提示
- **引号**：双引号
- **缩进**：4 个空格

### 测试

```bash
# 离线后端测试套件（排除调用外部真实 API 的测试）
make test

# 显式运行使用真实 API 的 DeerFlowClient 集成测试套件
make test-live
```

实时测试套件需要有效的根目录 `config.yaml` 和 API 凭据。它可能产生 API 费用，或创建本地沙箱、产物和文件，因此不属于默认测试流程或 CI。直接通过 pytest 运行 `tests/test_client_live.py` 时，也需要设置 `DEER_FLOW_RUN_LIVE_TESTS=1`。

`make detect-blocking-io` 会静态扫描后端业务代码，寻找可能在后端事件循环上运行且不受测试覆盖范围限制的阻塞式 IO。它会输出便于人工审查的简明摘要，并把完整的 JSON 结果写入仓库根目录的 `.deer-flow/blocking-io-findings.json`，无论该目标是在仓库根目录还是 `backend/` 目录中调用。JSON 结果同时包含宽泛的 IO 分类和面向审查的字段，例如 `priority`、`location`、`blocking_call`、`event_loop_exposure`、`reason` 和 `code`。`priority` 只是根据操作类型生成的确定性审查顺序，并不能证明存在缺陷。对于同一文件中通过裸名称调用的函数，扫描器按函数名解析，因此当一个文件中存在同名辅助函数时，可能会保守地高估异步可达性。

---

## 技术栈

- **LangGraph**（1.0.6+）——智能体框架和多智能体编排
- **LangChain**（1.2.3+）——LLM 抽象和工具系统
- **FastAPI**（0.115.0+）——Gateway REST API
- **langchain-mcp-adapters**——Model Context Protocol 支持
- **agent-sandbox**——沙箱化代码执行
- **markitdown**——多格式文档转换
- **tavily-python** / **firecrawl-py**——网页搜索和抓取

---

## 文档

- [配置指南](docs/CONFIGURATION.md)
- [架构详情](docs/ARCHITECTURE.md)
- [API 参考](docs/API.md)
- [文件上传](docs/FILE_UPLOAD.md)
- [路径示例](docs/PATH_EXAMPLES.md)
- [上下文摘要](docs/summarization.md)
- [计划模式](docs/plan_mode_usage.md)
- [设置指南](docs/SETUP.md)

---

## 许可证

请参阅项目根目录中的 [LICENSE](../LICENSE) 文件。

## 参与贡献

贡献指南请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)。

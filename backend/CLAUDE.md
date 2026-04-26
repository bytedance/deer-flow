# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此代码库中工作时提供指导。

---

## 项目概览

DeerFlow 是一个基于 LangGraph 的 AI 超级代理系统，采用全栈架构。后端提供"超级代理"，具备沙箱执行、持久化记忆、子代理委托和可扩展工具集成——所有功能都在线程隔离的环境中运行。

**架构组件**：
- **LangGraph Server** (端口 2024)：代理运行时和工作流执行
- **Gateway API** (端口 8001)：REST API，提供模型、MCP、技能、记忆、工件、上传和本地线程清理
- **Frontend** (端口 3000)：Next.js Web 界面
- **Nginx** (端口 2026)：统一反向代理入口
- **Provisioner** (端口 8002，Docker 开发中可选)：仅当沙箱配置为 provisioner/Kubernetes 模式时启动

---

## 项目结构

```
deer-flow/
├── Makefile                    # 根命令（check、install、dev、stop）
├── config.yaml                 # 主应用配置
├── extensions_config.json      # MCP 服务器和技能配置
├── backend/                    # 后端应用（本目录）
│   ├── Makefile               # 后端专用命令（dev、gateway、lint）
│   ├── langgraph.json         # LangGraph 服务器配置
│   ├── packages/
│   │   └── harness/           # deerflow-harness 包（导入：deerflow.*）
│   │       ├── pyproject.toml
│   │       └── deerflow/
│   │           ├── agents/            # LangGraph 代理系统
│   │           │   ├── lead_agent/    # 主代理（工厂 + 系统提示）
│   │           │   ├── middlewares/   # 10 个中间件组件
│   │           │   ├── memory/        # 记忆提取、队列、提示
│   │           │   └── thread_state.py # ThreadState 模式
│   │           ├── sandbox/           # 沙箱执行系统
│   │           │   ├── local/         # 本地文件系统提供者
│   │           │   ├── sandbox.py     # 抽象沙箱接口
│   │           │   ├── tools.py       # bash、ls、read/write/str_replace
│   │           │   └── middleware.py  # 沙箱生命周期管理
│   │           ├── subagents/         # 子代理委托系统
│   │           │   ├── builtins/      # general-purpose、bash 代理
│   │           │   ├── executor.py    # 后台执行引擎
│   │           │   └── registry.py    # 代理注册表
│   │           ├── tools/builtins/    # 内置工具（present_files、ask_clarification、view_image）
│   │           ├── mcp/               # MCP 集成（工具、缓存、客户端）
│   │           ├── models/            # 模型工厂，支持思考/视觉
│   │           ├── skills/            # 技能发现、加载、解析
│   │           ├── config/            # 配置系统（app、model、sandbox、tool 等）
│   │           ├── community/         # 社区工具（tavily、jina_ai、firecrawl、image_search、aio_sandbox）
│   │           ├── reflection/        # 动态模块加载（resolve_variable、resolve_class）
│   │           ├── utils/             # 工具类（network、readability）
│   │           └── client.py          # 嵌入式 Python 客户端（DeerFlowClient）
│   ├── app/                   # 应用层（导入：app.*）
│   │   ├── gateway/           # FastAPI Gateway API
│   │   │   ├── app.py         # FastAPI 应用
│   │   │   └── routers/       # FastAPI 路由模块（models、mcp、memory、skills、uploads、threads、artifacts、agents、suggestions、channels）
│   │   └── channels/          # IM 平台集成
│   ├── tests/                 # 测试套件
│   └── docs/                  # 文档
├── frontend/                   # Next.js 前端应用
└── skills/                     # 代理技能目录
    ├── public/                # 公共技能（已提交）
    └── custom/                # 自定义技能（已 gitignore）
```

---

## 重要开发指南

### 文档更新策略
**关键：每次代码更改后必须更新 README.md 和 CLAUDE.md**

进行代码更改时，必须更新相关文档：
- 更新 `README.md` 用于面向用户的更改（功能、设置、使用说明）
- 更新 `CLAUDE.md` 用于开发更改（架构、命令、工作流、内部系统）
- 保持文档与代码库同步
- 确保所有文档的准确性和及时性

---

## 命令

**根目录**（用于完整应用）：
```bash
make check      # 检查系统要求
make install    # 安装所有依赖（前端 + 后端）
make dev        # 启动所有服务（LangGraph + Gateway + Frontend + Nginx），带 config.yaml 预检查
make stop       # 停止所有服务
```

**后端目录**（仅用于后端开发）：
```bash
make install    # 安装后端依赖
make dev        # 仅运行 LangGraph 服务器（端口 2024）
make gateway    # 仅运行 Gateway API（端口 8001）
make test       # 运行所有后端测试
make lint       # 使用 ruff 进行 lint 检查
make format     # 使用 ruff 格式化代码
```

**回归测试**：
- `tests/test_docker_sandbox_mode_detection.py`（从 `config.yaml` 检测模式）
- `tests/test_provisioner_kubeconfig.py`（kubeconfig 文件/目录处理）

**边界检查**（harness → app 导入防火墙）：
- `tests/test_harness_boundary.py` — 确保 `packages/harness/deerflow/` 永不导入 `app.*`

CI 通过 [.github/workflows/backend-unit-tests.yml](../.github/workflows/backend-unit-tests.yml) 为每个拉取请求运行这些回归测试。

---

## 架构

### Harness / App 分层

后端分为两层，具有严格的依赖方向：

- **Harness** (`packages/harness/deerflow/`)：可发布的代理框架包（`deerflow-harness`）。导入前缀：`deerflow.*`。包含代理编排、工具、沙箱、模型、MCP、技能、配置——构建和运行代理所需的一切。
- **App** (`app/`)：未发布的应用代码。导入前缀：`app.*`。包含 FastAPI Gateway API 和 IM 渠道集成（飞书、Slack、Telegram）。

**依赖规则**：App 导入 deerflow，但 deerflow 永不导入 app。此边界由 `tests/test_harness_boundary.py` 强制执行，该测试在 CI 中运行。

**导入约定**：
```python
# Harness 内部
from deerflow.agents import make_lead_agent
from deerflow.models import create_chat_model

# App 内部
from app.gateway.app import app
from app.channels.service import start_channel_service

# App → Harness（允许）
from deerflow.config import get_app_config

# Harness → App（禁止 — 由 test_harness_boundary.py 强制执行）
# from app.gateway.routers.uploads import ...  # ← 将导致 CI 失败
```

### 代理系统

**Lead Agent** (`packages/harness/deerflow/agents/lead_agent/agent.py`)：
- 入口点：`make_lead_agent(config: RunnableConfig)` 在 `langgraph.json` 中注册
- 通过 `create_chat_model()` 进行动态模型选择，支持思考/视觉
- 通过 `get_available_tools()` 加载工具——组合沙箱、内置、MCP、社区和子代理工具
- 由 `apply_prompt_template()` 生成系统提示，包含技能、记忆和子代理指令

**ThreadState** (`packages/harness/deerflow/agents/thread_state.py`)：
- 扩展 `AgentState`，包含：`sandbox`、`thread_data`、`title`、`artifacts`、`todos`、`uploaded_files`、`viewed_images`
- 使用自定义归约器：`merge_artifacts`（去重）、`merge_viewed_images`（合并/清除）

**运行时配置**（通过 `config.configurable`）：
- `thinking_enabled` - 启用模型的扩展思考
- `model_name` - 选择特定 LLM 模型
- `is_plan_mode` - 启用 TodoList 中间件
- `subagent_enabled` - 启用任务委托工具

### 中间件链

中间件在 `packages/harness/deerflow/agents/lead_agent/agent.py` 中按严格顺序执行：

1. **ThreadDataMiddleware** - 创建线程目录（`backend/.deer-flow/threads/{thread_id}/user-data/{workspace,uploads,outputs}`）；Web UI 线程删除现在跟随 LangGraph 线程删除，Gateway 清理本地 `.deer-flow/threads/{thread_id}` 目录
2. **UploadsMiddleware** - 跟踪并将新上传的文件注入对话
3. **SandboxMiddleware** - 获取沙箱，将 `sandbox_id` 存储在状态中
4. **DanglingToolCallMiddleware** - 为缺少响应的 AIMessage tool_calls 注入占位符 ToolMessages（例如，由于用户中断）
5. **GuardrailMiddleware** - 通过可插拔的 `GuardrailProvider` 协议进行工具调用前授权（可选，如果 `config.yaml` 中 `guardrails.enabled`）。评估每个工具调用，拒绝时返回错误 ToolMessage。三种提供者选项：内置 `AllowlistProvider`（零依赖）、OAP 策略提供者（如 `aport-agent-guardrails`）或自定义提供者。参见 [docs/GUARDRAILS.md](docs/GUARDRAILS.md) 了解设置、使用和如何实现提供者。
6. **SummarizationMiddleware** - 接近 token 限制时的上下文缩减（可选，如果启用）
7. **TodoListMiddleware** - 使用 `write_todos` 工具进行任务跟踪（可选，如果 plan_mode）
8. **TitleMiddleware** - 在首次完整交换后自动生成线程标题，并在提示标题模型之前规范化结构化消息内容
9. **MemoryMiddleware** - 将对话排队以进行异步记忆更新（过滤为用户 + 最终 AI 响应）
10. **ViewImageMiddleware** - 在 LLM 调用前注入 base64 图像数据（取决于视觉支持）
11. **SubagentLimitMiddleware** - 截断模型响应中多余的 `task` 工具调用，以强制执行 `MAX_CONCURRENT_SUBAGENTS` 限制（可选，如果 subagent_enabled）
12. **ClarificationMiddleware** - 拦截 `ask_clarification` 工具调用，通过 `Command(goto=END)` 中断（必须最后）

### 配置系统

**主配置** (`config.yaml`)：

设置：将 `config.example.yaml` 复制到**项目根目录**中的 `config.yaml`。

**配置版本控制**：`config.example.yaml` 具有 `config_version` 字段。启动时，`AppConfig.from_file()` 比较用户版本与示例版本，如果过时则发出警告。缺少 `config_version` = 版本 0。运行 `make config-upgrade` 自动合并缺失字段。更改配置模式时，在 `config.example.yaml` 中增加 `config_version`。

**配置缓存**：`get_app_config()` 缓存解析的配置，但当解析的配置路径更改或文件的 mtime 增加时自动重新加载。这使 Gateway 和 LangGraph 读取与 `config.yaml` 编辑保持一致，无需手动重启进程。

配置优先级：
1. 显式 `config_path` 参数
2. `DEER_FLOW_CONFIG_PATH` 环境变量
3. 当前目录中的 `config.yaml`（backend/）
4. 父目录中的 `config.yaml`（项目根目录 - **推荐位置**）

以 `$` 开头的配置值解析为环境变量（例如 `$OPENAI_API_KEY`）。
`ModelConfig` 还声明 `use_responses_api` 和 `output_version`，因此可以显式启用 OpenAI `/v1/responses`，同时仍使用 `langchain_openai:ChatOpenAI`。

**扩展配置** (`extensions_config.json`)：

MCP 服务器和技能在项目根目录的 `extensions_config.json` 中一起配置：

配置优先级：
1. 显式 `config_path` 参数
2. `DEER_FLOW_EXTENSIONS_CONFIG_PATH` 环境变量
3. 当前目录中的 `extensions_config.json`（backend/）
4. 父目录中的 `extensions_config.json`（项目根目录 - **推荐位置**）

### Gateway API (`app/gateway/`)

端口 8001 上的 FastAPI 应用，在 `GET /health` 进行健康检查。

**路由器**：

| 路由器 | 端点 |
|--------|-----------|
| **Models** (`/api/models`) | `GET /` - 列出模型；`GET /{name}` - 模型详情 |
| **MCP** (`/api/mcp`) | `GET /config` - 获取配置；`PUT /config` - 更新配置（保存到 extensions_config.json） |
| **Skills** (`/api/skills`) | `GET /` - 列出技能；`GET /{name}` - 详情；`PUT /{name}` - 更新启用状态；`POST /install` - 从 .skill 存档安装（接受标准可选 frontmatter，如 `version`、`author`、`compatibility`） |
| **Memory** (`/api/memory`) | `GET /` - 记忆数据；`POST /reload` - 强制重新加载；`GET /config` - 配置；`GET /status` - 配置 + 数据 |
| **Uploads** (`/api/threads/{id}/uploads`) | `POST /` - 上传文件（自动转换 PDF/PPT/Excel/Word）；`GET /list` - 列出；`DELETE /{filename}` - 删除 |
| **Threads** (`/api/threads/{id}`) | `DELETE /` - 在 LangGraph 线程删除后删除 DeerFlow 管理的本地线程数据；意外失败在服务器端记录并返回通用 500 详情 |
| **Artifacts** (`/api/threads/{id}/artifacts`) | `GET /{path}` - 提供工件；活跃内容类型（`text/html`、`application/xhtml+xml`、`image/svg+xml`）始终强制作为下载附件以降低 XSS 风险；`?download=true` 仍强制下载其他文件类型 |
| **Suggestions** (`/api/threads/{id}/suggestions`) | `POST /` - 生成后续问题；在 JSON 解析前规范化富列表/块模型内容 |

通过 nginx 代理：`/api/langgraph/*` → LangGraph，所有其他 `/api/*` → Gateway。

### 沙箱系统 (`packages/harness/deerflow/sandbox/`)

**接口**：抽象 `Sandbox`，具有 `execute_command`、`read_file`、`write_file`、`list_dir`
**提供者模式**：`SandboxProvider`，具有 `acquire`、`get`、`release` 生命周期
**实现**：
- `LocalSandboxProvider` - 单例本地文件系统执行，带路径映射
- `AioSandboxProvider` (`packages/harness/deerflow/community/`) - 基于 Docker 的隔离

**虚拟路径系统**：
- 代理看到：`/mnt/user-data/{workspace,uploads,outputs}`、`/mnt/skills`
- 物理：`backend/.deer-flow/threads/{thread_id}/user-data/...`、`deer-flow/skills/`
- 转换：`replace_virtual_path()` / `replace_virtual_paths_in_command()`
- 检测：`is_local_sandbox()` 检查 `sandbox_id == "local"`

**沙箱工具**（在 `packages/harness/deerflow/sandbox/tools.py` 中）：
- `bash` - 执行命令，带路径转换和错误处理
- `ls` - 目录列表（树格式，最多 2 级）
- `read_file` - 读取文件内容，可选行范围
- `write_file` - 写入/追加文件，创建目录
- `str_replace` - 子字符串替换（单个或所有出现）

### 子代理系统 (`packages/harness/deerflow/subagents/`)

**内置代理**：`general-purpose`（除 `task` 外的所有工具）和 `bash`（命令专家）
**执行**：双线程池 — `_scheduler_pool`（3 个工作线程）+ `_execution_pool`（3 个工作线程）
**并发**：`MAX_CONCURRENT_SUBAGENTS = 3` 由 `SubagentLimitMiddleware` 强制执行（在 `after_model` 中截断多余的工具调用），15 分钟超时
**流程**：`task()` 工具 → `SubagentExecutor` → 后台线程 → 轮询 5 秒 → SSE 事件 → 结果
**事件**：`task_started`、`task_running`、`task_completed`/`task_failed`/`task_timed_out`

### 工具系统 (`packages/harness/deerflow/tools/`)

`get_available_tools(groups, include_mcp, model_name, subagent_enabled)` 组装：
1. **配置定义的工具** - 通过 `resolve_variable()` 从 `config.yaml` 解析
2. **MCP 工具** - 来自启用的 MCP 服务器（延迟初始化，使用 mtime 失效缓存）
3. **内置工具**：
   - `present_files` - 使输出文件对用户可见（仅 `/mnt/user-data/outputs`）
   - `ask_clarification` - 请求澄清（由 ClarificationMiddleware 拦截 → 中断）
   - `view_image` - 将图像读取为 base64（仅当模型支持视觉时添加）
4. **子代理工具**（如果启用）：
   - `task` - 委托给子代理（description、prompt、subagent_type、max_turns）

**社区工具** (`packages/harness/deerflow/community/`)：
- `tavily/` - 网络搜索（默认 5 个结果）和网络获取（4KB 限制）
- `jina_ai/` - 通过 Jina reader API 进行网络获取，带可读性提取
- `firecrawl/` - 通过 Firecrawl API 进行网络爬取

**ACP 代理工具**：
- `invoke_acp_agent` - 从 `config.yaml` 调用外部 ACP 兼容代理
- ACP 启动器必须是真正的 ACP 适配器。标准 `codex` CLI 本身不是 ACP 兼容的；配置包装器，如 `npx -y @zed-industries/codex-acp`或已安装的 `codex-acp` 二进制文件
- 缺少的 ACP 可执行文件现在返回可操作的错误消息，而不是原始的 `[Errno 2]`
- 每个 ACP 代理使用线程工作空间 `{base_dir}/threads/{thread_id}/acp-workspace/`。工作空间可通过虚拟路径 `/mnt/acp-workspace/`（只读）供主代理访问。在 docker 沙箱模式下，目录被卷挂载到容器中的 `/mnt/acp-workspace`（只读）；在本地沙箱模式下，路径转换由 `tools.py` 处理
- `image_search/` - 通过 DuckDuckGo 进行图像搜索

### MCP 系统 (`packages/harness/deerflow/mcp/`)

- 使用 `langchain-mcp-adapters` `MultiServerMCPClient` 进行多服务器管理
- **延迟初始化**：工具在首次使用时通过 `get_cached_mcp_tools()` 加载
- **缓存失效**：通过 mtime 比较检测配置文件更改
- **传输**：stdio（基于命令）、SSE、HTTP
- **OAuth (HTTP/SSE)**：支持令牌端点流（`client_credentials`、`refresh_token`），带自动令牌刷新 + Authorization 头注入
- **运行时更新**：Gateway API 保存到 extensions_config.json；LangGraph 通过 mtime 检测

### 技能系统 (`packages/harness/deerflow/skills/`)

- **位置**：`deer-flow/skills/{public,custom}/`
- **格式**：带有 `SKILL.md` 的目录（YAML frontmatter：name、description、license、allowed-tools）
- **加载**：`load_skills()` 递归扫描 `skills/{public,custom}` 中的 `SKILL.md`，解析元数据，并从 extensions_config.json 读取启用状态
- **注入**：启用的技能在代理系统提示中列出，带容器路径
- **安装**：`POST /api/skills/install` 将 .skill ZIP 存档提取到 custom/ 目录

### 模型工厂 (`packages/harness/deerflow/models/factory.py`)

- `create_chat_model(name, thinking_enabled)` 通过反射从配置实例化 LLM
- 支持带每个模型 `when_thinking_enabled` 覆盖的 `thinking_enabled` 标志
- 支持图像理解模型的 `supports_vision` 标志
- 以 `$` 开头的配置值解析为环境变量
- 缺少的提供者模块从反射解析器显示可操作的安装提示（例如 `uv add langchain-google-genai`）

### IM 渠道系统 (`app/channels/`)

将外部消息平台（飞书、Slack、Telegram）桥接到 DeerFlow 代理，通过 LangGraph Server。

**架构**：渠道通过 `langgraph-sdk` HTTP 客户端与 LangGraph Server 通信（与前端相同），确保线程在服务器端创建和管理。

**组件**：
- `message_bus.py` - 异步发布/订阅中心（`InboundMessage` → 队列 → 分发器；`OutboundMessage` → 回调 → 渠道）
- `store.py` - JSON 文件持久化，映射 `channel_name:chat_id[:topic_id]` → `thread_id`（键是根对话的 `channel:chat` 和线程对话的 `channel:chat:topic`）
- `manager.py` - 核心分发器：通过 `client.threads.create()` 创建线程，路由命令，保持 Slack/Telegram 在 `client.runs.wait()`，并使用 `client.runs.stream(["messages-tuple", "values"])` 进行飞书增量出站更新
- `base.py` - 抽象 `Channel` 基类（start/stop/send 生命周期）
- `service.py` - 从 `config.yaml` 管理所有配置渠道的生命周期
- `slack.py` / `feishu.py` / `telegram.py` - 平台特定实现（`feishu.py` 在内存中跟踪运行卡片的 `message_id` 并就地修补同一卡片）

**消息流程**：
1. 外部平台 → 渠道实现 → `MessageBus.publish_inbound()`
2. `ChannelManager._dispatch_loop()` 从队列消费
3. 对于聊天：在 LangGraph Server 上查找/创建线程
4. 飞书聊天：`runs.stream()` → 累积 AI 文本 → 发布多个出站更新（`is_final=False`）→ 发布最终出站（`is_final=True`）
5. Slack/Telegram 聊天：`runs.wait()` → 提取最终响应 → 发布出站
6. 飞书渠道预先发送一个运行回复卡片，然后为每个出站更新修补同一卡片（卡片 JSON 设置 `config.update_multi=true` 以满足飞书的修补 API 要求）
7. 对于命令（`/new`、`/status`、`/models`、`/memory`、`/help`）：本地处理或查询 Gateway API
8. 出站 → 渠道回调 → 平台回复

**配置**（`config.yaml` -> `channels`）：
- `langgraph_url` - LangGraph Server URL（默认：`http://localhost:2024`）
- `gateway_url` - 辅助命令的 Gateway API URL（默认：`http://localhost:8001`）
- 在 Docker Compose 中，IM 渠道在 `gateway` 容器内运行，因此 `localhost` 指向该容器。使用 `http://langgraph:2024` / `http://gateway:8001`，或设置 `DEER_FLOW_CHANNELS_LANGGRAPH_URL` / `DEER_FLOW_CHANNELS_GATEWAY_URL`。
- 每渠道配置：`feishu`（app_id、app_secret）、`slack`（bot_token、app_token）、`telegram`（bot_token）

### 记忆系统 (`packages/harness/deerflow/agents/memory/`)

**组件**：
- `updater.py` - 基于 LLM 的记忆更新，带事实提取、空白规范化的事实去重（在比较前修剪前导/尾随空白）和原子文件 I/O
- `queue.py` - 去抖动更新队列（每线程去重，可配置等待时间）
- `prompt.py` - 记忆更新的提示模板

**数据结构**（存储在 `backend/.deer-flow/memory.json` 中）：
- **用户上下文**：`workContext`、`personalContext`、`topOfMind`（1-3 句摘要）
- **历史**：`recentMonths`、`earlierContext`、`longTermBackground`
- **事实**：离散事实，带有 `id`、`content`、`category`（preference/knowledge/context/behavior/goal）、`confidence`（0-1）、`createdAt`、`source`

**工作流**：
1. `MemoryMiddleware` 过滤消息（用户输入 + 最终 AI 响应）并将对话排队
2. 队列去抖动（默认 30 秒），批量更新，每线程去重
3. 后台线程调用 LLM 提取上下文更新和事实
4. 原子应用更新（临时文件 + 重命名），带缓存失效，在追加前跳过重复事实内容
5. 下一次交互将前 15 个事实 + 上下文注入到系统提示的 `<memory>` 标签中

更新器的重点回归覆盖位于 `backend/tests/test_memory_updater.py`。

**配置**（`config.yaml` → `memory`）：
- `enabled` / `injection_enabled` - 主开关
- `storage_path` - memory.json 的路径
- `debounce_seconds` - 处理前的等待时间（默认：30）
- `model_name` - 更新的 LLM（null = 默认模型）
- `max_facts` / `fact_confidence_threshold` - 事实存储限制（100 / 0.7）
- `max_injection_tokens` - 提示注入的 token 限制（2000）

### 反射系统 (`packages/harness/deerflow/reflection/`)

- `resolve_variable(path)` - 导入模块并返回变量（例如 `module.path:variable_name`）
- `resolve_class(path, base_class)` - 导入并根据基类验证类

### 配置模式

**`config.yaml`** 关键部分：
- `models[]` - LLM 配置，带 `use` 类路径、`supports_thinking`、`supports_vision`、提供者特定字段
- `tools[]` - 工具配置，带 `use` 变量路径和 `group`
- `tool_groups[]` - 工具的逻辑分组
- `sandbox.use` - 沙箱提供者类路径
- `skills.path` / `skills.container_path` - 技能目录的主机和容器路径
- `title` - 自动标题生成（enabled、max_words、max_chars、prompt_template）
- `summarization` - 上下文摘要（enabled、触发条件、保留策略）
- `subagents.enabled` - 子代理委托的主开关
- `memory` - 记忆系统（enabled、storage_path、debounce_seconds、model_name、max_facts、fact_confidence_threshold、injection_enabled、max_injection_tokens）

**`extensions_config.json`**：
- `mcpServers` - 服务器名称 → 配置的映射（enabled、type、command、args、env、url、headers、oauth、description）
- `skills` - 技能名称 → 状态的映射（enabled）

两者都可以通过 Gateway API 端点或 `DeerFlowClient` 方法在运行时修改。

### 嵌入式客户端 (`packages/harness/deerflow/client.py`)

`DeerFlowClient` 提供对所有 DeerFlow 功能的直接进程内访问，无需 HTTP 服务。所有返回类型与 Gateway API 响应模式对齐，因此消费者代码在 HTTP 和嵌入模式下工作相同。

**架构**：导入与 LangGraph Server 和 Gateway API 相同的 `deerflow` 模块。共享相同的配置文件和数据目录。无 FastAPI 依赖。

**代理对话**（替代 LangGraph Server）：
- `chat(message, thread_id)` — 同步，返回最终文本
- `stream(message, thread_id)` — 产生与 LangGraph SSE 协议对齐的 `StreamEvent`：
  - `"values"` — 完整状态快照（title、messages、artifacts）
  - `"messages-tuple"` — 每消息更新（AI 文本、工具调用、工具结果）
  - `"end"` — 流完成
- 代理通过 `create_agent()` + `_build_middlewares()` 延迟创建，与 `make_lead_agent` 相同
- 支持 `checkpointer` 参数以实现跨轮次的状态持久化
- `reset_agent()` 强制代理重新创建（例如，在记忆或技能更改后）

**Gateway 等效方法**（替代 Gateway API）：

| 类别 | 方法 | 返回格式 |
|----------|---------|---------------|
| Models | `list_models()`、`get_model(name)` | `{"models": [...]}`、`{name, display_name, ...}` |
| MCP | `get_mcp_config()`、`update_mcp_config(servers)` | `{"mcp_servers": {...}}` |
| Skills | `list_skills()`、`get_skill(name)`、`update_skill(name, enabled)`、`install_skill(path)` | `{"skills": [...]}` |
| Memory | `get_memory()`、`reload_memory()`、`get_memory_config()`、`get_memory_status()` | dict |
| Uploads | `upload_files(thread_id, files)`、`list_uploads(thread_id)`、`delete_upload(thread_id, filename)` | `{"success": true, "files": [...]}`、`{"files": [...], "count": N}` |
| Artifacts | `get_artifact(thread_id, path)` → `(bytes, mime_type)` | tuple |

**与 Gateway 的主要区别**：Upload 接受本地 `Path` 对象而不是 HTTP `UploadFile`，在复制前拒绝目录路径，并且在活动事件循环内运行文档转换时重用单个工作线程。Artifact 返回 `(bytes, mime_type)` 而不是 HTTP Response。新的仅 Gateway 线程清理路由在 LangGraph 线程删除后删除 `.deer-flow/threads/{thread_id}`；尚无匹配的 `DeerFlowClient` 方法。`update_mcp_config()` 和 `update_skill()` 自动使缓存的代理失效。

**测试**：`tests/test_client.py`（77 个单元测试，包括 `TestGatewayConformance`）、`tests/test_client_live.py`（实时集成测试，需要 config.yaml）

**Gateway 一致性测试**（`TestGatewayConformance`）：验证每个返回 dict 的客户端方法符合相应的 Gateway Pydantic 响应模型。每个测试通过 Gateway 模型解析客户端输出——如果 Gateway 添加了客户端未提供的必需字段，Pydantic 会引发 `ValidationError`，CI 会捕获漂移。覆盖：`ModelsListResponse`、`ModelResponse`、`SkillsListResponse`、`SkillResponse`、`SkillInstallResponse`、`McpConfigResponse`、`UploadResponse`、`MemoryConfigResponse`、`MemoryStatusResponse`。

---

## 开发工作流

### 测试驱动开发（TDD）— 强制

**每个新功能或错误修复必须伴随单元测试。无例外。**

- 在 `backend/tests/` 中编写测试，遵循现有命名约定 `test_<feature>.py`
- 在更改前后运行完整套件：`make test`
- 测试必须在功能完成前通过
- 对于轻量级配置/工具模块，首选无外部依赖的纯单元测试
- 如果模块在测试中导致循环导入问题，请在 `tests/conftest.py` 中添加 `sys.modules` mock（参见 `deerflow.subagents.executor` 的现有示例）

```bash
# 运行所有测试
make test

# 运行特定测试文件
PYTHONPATH=. uv run pytest tests/test_<feature>.py -v
```

### 运行完整应用

从**项目根目录**：
```bash
make dev
```

这将启动所有服务，使应用在 `http://localhost:2026` 上可用。

**Nginx 路由**：
- `/api/langgraph/*` → LangGraph Server (2024)
- `/api/*`（其他）→ Gateway API (8001)
- `/`（非 API）→ Frontend (3000)

### 分别运行后端服务

从**后端目录**：

```bash
# 终端 1：LangGraph 服务器
make dev

# 终端 2：Gateway API
make gateway
```

直接访问（不带 nginx）：
- LangGraph：`http://localhost:2024`
- Gateway：`http://localhost:8001`

### 前端配置

前端使用环境变量连接到后端服务：
- `NEXT_PUBLIC_LANGGRAPH_BASE_URL` - 默认为 `/api/langgraph`（通过 nginx）
- `NEXT_PUBLIC_BACKEND_BASE_URL` - 默认为空字符串（通过 nginx）

从根目录使用 `make dev` 时，前端自动通过 nginx 连接。

---

## 关键功能

### 文件上传

带自动文档转换的多文件上传：
- 端点：`POST /api/threads/{thread_id}/uploads`
- 支持：PDF、PPT、Excel、Word 文档（通过 `markitdown` 转换）
- 在复制前拒绝目录输入，使上传保持全有或全无
- 从活动事件循环调用时，每个请求重用一个转换工作线程
- 文件存储在线程隔离的目录中
- 代理通过 `UploadsMiddleware` 接收上传的文件列表

详情参见 [docs/FILE_UPLOAD.md](docs/FILE_UPLOAD.md)。

### 计划模式

用于复杂多步骤任务的 TodoList 中间件：
- 通过运行时配置控制：`config.configurable.is_plan_mode = True`
- 提供 `write_todos` 工具用于任务跟踪
- 一次一个 in_progress 任务，实时更新

详情参见 [docs/plan_mode_usage.md](docs/plan_mode_usage.md)。

### 上下文摘要

接近 token 限制时的自动对话摘要：
- 在 `config.yaml` 的 `summarization` 键下配置
- 触发类型：tokens、messages 或最大输入的分数
- 保留最近的消息，同时总结较旧的消息

详情参见 [docs/summarization.md](docs/summarization.md)。

### 视觉支持

对于带有 `supports_vision: true` 的模型：
- `ViewImageMiddleware` 处理对话中的图像
- `view_image_tool` 添加到代理的工具集
- 图像自动转换为 base64 并注入到状态中

---

## 代码风格

- 使用 `ruff` 进行 lint 和格式化
- 行长度：240 字符
- Python 3.12+ 带类型提示
- 双引号，空格缩进

---

## 文档

参见 `docs/` 目录获取详细文档：
- [CONFIGURATION.md](docs/CONFIGURATION.md) - 配置选项
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - 架构详情
- [API.md](docs/API.md) - API 参考
- [SETUP.md](docs/SETUP.md) - 设置指南
- [FILE_UPLOAD.md](docs/FILE_UPLOAD.md) - 文件上传功能
- [PATH_EXAMPLES.md](docs/PATH_EXAMPLES.md) - 路径类型和用法
- [summarization.md](docs/summarization.md) - 上下文摘要
- [plan_mode_usage.md](docs/plan_mode_usage.md) - 带有 TodoList 的计划模式

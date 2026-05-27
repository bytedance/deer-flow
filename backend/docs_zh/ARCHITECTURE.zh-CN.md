# 架构总览

本文档提供 DeerFlow 后端架构的全面概览。

## 系统架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              Client (Browser)                             │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          Nginx (Port 2026)                               │
│                         统一反向代理入口点                                │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  /api/langgraph/*  →  Gateway 兼容 LangGraph 运行时 (8001)         │  │
│  │  /api/*            →  Gateway REST APIs (8001)                    │  │
│  │  /*                →  Frontend (3000)                              │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  │
          ┌───────────────────────┴───────────────────────┐
          │                                               │
          ▼                                               ▼
┌─────────────────────────────────────────────┐ ┌─────────────────────┐
│              Gateway API                    │ │     Frontend        │
│              (Port 8001)                    │ │    (Port 3000)      │
│                                             │ │                     │
│  - 兼容 LangGraph 的 runs/threads API        │ │  - Next.js 应用      │
│  - 内嵌 Agent Runtime                        │ │  - React UI         │
│  - SSE 流式输出                              │ │  - 聊天界面         │
│  - Checkpointing                            │ │                     │
│  - Models、MCP、Skills、Uploads、Artifacts   │ │                     │
│  - 线程清理                                  │ │                     │
└─────────────────────────────────────────────┘ └─────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                            共享配置                                      │
│  ┌─────────────────────────┐  ┌────────────────────────────────────────┐ │
│  │      config.yaml        │  │      extensions_config.json            │ │
│  │  - Models               │  │  - MCP Servers                         │ │
│  │  - Tools                │  │  - Skills State                        │ │
│  │  - Sandbox              │  │                                        │ │
│  │  - Summarization        │  │                                        │ │
│  └─────────────────────────┘  └────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

## 组件细节

### Gateway 内嵌 Agent Runtime

Agent runtime 内嵌在 FastAPI Gateway 中，并基于 LangGraph 实现稳健的多 agent 工作流编排。Nginx 会把 `/api/langgraph/*` 重写到 Gateway 原生的 `/api/*` 路由，因此在不运行独立 LangGraph 服务的情况下，公开 API 仍可与 LangGraph SDK 客户端兼容。

**入口点**：`packages/harness/deerflow/agents/lead_agent/agent.py:make_lead_agent`

**核心职责**：
- Agent 创建与配置
- 线程状态管理
- 中间件链执行
- 工具执行编排
- 为实时响应提供 SSE 流

**图注册表**：`langgraph.json` 仍可用于工具链、Studio 或直接对接 LangGraph Server 的兼容场景。它不是默认服务入口；脚本与 Docker 部署均运行 Gateway 内嵌 runtime。

```json
{
  "agent": {
    "type": "agent",
    "path": "deerflow.agents:make_lead_agent"
  }
}
```

### Gateway API（网关接口）

FastAPI 应用，提供 REST 端点，以及公开的兼容 LangGraph 的 `/api/langgraph/*` runtime 路由。

**入口点**：`app/gateway/app.py`

**路由模块**：
- `models.py` - `/api/models` - 模型列表与详情
- `thread_runs.py` / `runs.py` - `/api/threads/{id}/runs`、`/api/runs/*` - 兼容 LangGraph 的运行与流式输出
- `mcp.py` - `/api/mcp` - MCP 服务器配置
- `skills.py` - `/api/skills` - Skills 管理
- `uploads.py` - `/api/threads/{id}/uploads` - 文件上传
- `threads.py` - `/api/threads/{id}` - 在 LangGraph 删除后清理本地 DeerFlow 线程数据
- `artifacts.py` - `/api/threads/{id}/artifacts` - 产物分发
- `suggestions.py` - `/api/threads/{id}/suggestions` - 后续问题建议生成

Web 对话删除流程会先通过兼容 LangGraph 的路由删除 Gateway 管理的线程状态，随后由 Gateway 的 `threads.py` 路由调用 `Paths.delete_thread_dir()` 删除 DeerFlow 管理的文件系统数据。

### Agent 架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           make_lead_agent(config)                        │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            中间件链                                      │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ 1. ThreadDataMiddleware  - 初始化 workspace/uploads/outputs      │   │
│  │ 2. UploadsMiddleware     - 处理上传文件                          │   │
│  │ 3. SandboxMiddleware     - 获取沙箱环境                          │   │
│  │ 4. SummarizationMiddleware - 上下文压缩（若启用）                │   │
│  │ 5. TitleMiddleware       - 自动生成标题                          │   │
│  │ 6. TodoListMiddleware    - 任务追踪（plan_mode 时）              │   │
│  │ 7. ViewImageMiddleware   - 视觉模型支持                          │   │
│  │ 8. ClarificationMiddleware - 处理澄清请求                        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              Agent Core                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐   │
│  │      Model       │  │      Tools       │  │    System Prompt     │   │
│  │  (from factory)  │  │  (configured +   │  │  (with skills)       │   │
│  │                  │  │   MCP + builtin) │  │                      │   │
│  └──────────────────┘  └──────────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 线程状态

`ThreadState` 在 LangGraph 的 `AgentState` 基础上扩展了额外字段：

```python
class ThreadState(AgentState):
    # 继承自 AgentState 的核心状态
    messages: list[BaseMessage]

    # DeerFlow 扩展字段
    sandbox: dict             # 沙箱环境信息
    artifacts: list[str]      # 生成文件路径
    thread_data: dict         # {workspace, uploads, outputs} 路径
    title: str | None         # 自动生成的会话标题
    todos: list[dict]         # 任务追踪（plan mode）
    viewed_images: dict       # 视觉模型图片数据
```

### 沙箱系统

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           沙箱架构                                       │
└─────────────────────────────────────────────────────────────────────────┘

                      ┌─────────────────────────┐
                      │    SandboxProvider      │ (Abstract)
                      │  - acquire()            │
                      │  - get()                │
                      │  - release()            │
                      └────────────┬────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                                         │
              ▼                                         ▼
┌─────────────────────────┐              ┌─────────────────────────┐
│  LocalSandboxProvider   │              │  AioSandboxProvider     │
│  (packages/harness/deerflow/sandbox/local.py) │              │  (packages/harness/deerflow/community/)       │
│                         │              │                         │
│  - 单例实例              │              │  - 基于 Docker          │
│  - 直接执行              │              │  - 容器隔离             │
│  - 开发使用              │              │  - 生产使用             │
└─────────────────────────┘              └─────────────────────────┘

                      ┌─────────────────────────┐
                      │        Sandbox          │ (Abstract)
                      │  - execute_command()    │
                      │  - read_file()          │
                      │  - write_file()         │
                      │  - list_dir()           │
                      └─────────────────────────┘
```

**虚拟路径映射：**

| 虚拟路径 | 物理路径 |
|-------------|---------------|
| `/mnt/user-data/workspace` | `backend/.deer-flow/threads/{thread_id}/user-data/workspace` |
| `/mnt/user-data/uploads` | `backend/.deer-flow/threads/{thread_id}/user-data/uploads` |
| `/mnt/user-data/outputs` | `backend/.deer-flow/threads/{thread_id}/user-data/outputs` |
| `/mnt/skills` | `deer-flow/skills/` |

### 工具系统

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            工具来源                                      │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│   内置工具           │  │  配置工具            │  │     MCP 工具        │
│  (packages/harness/deerflow/tools/)       │  │  (config.yaml)      │  │  (extensions.json)  │
├─────────────────────┤  ├─────────────────────┤  ├─────────────────────┤
│ - present_files     │  │ - web_search        │  │ - github            │
│ - ask_clarification │  │ - web_fetch         │  │ - filesystem        │
│ - view_image        │  │ - bash              │  │ - postgres          │
│                     │  │ - read_file         │  │ - brave-search      │
│                     │  │ - write_file        │  │ - puppeteer         │
│                     │  │ - str_replace       │  │ - ...               │
│                     │  │ - ls                │  │                     │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
           │                       │                       │
           └───────────────────────┴───────────────────────┘
                                   │
                                   ▼
                      ┌─────────────────────────┐
                      │   get_available_tools() │
                      │   (packages/harness/deerflow/tools/__init__)  │
                      └─────────────────────────┘
```

### 模型工厂

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          模型工厂                                       │
│                     (packages/harness/deerflow/models/factory.py)                              │
└─────────────────────────────────────────────────────────────────────────┘

config.yaml:
┌─────────────────────────────────────────────────────────────────────────┐
│ models:                                                                  │
│   - name: gpt-4                                                         │
│     display_name: GPT-4                                                 │
│     use: langchain_openai:ChatOpenAI                                    │
│     model: gpt-4                                                        │
│     api_key: $OPENAI_API_KEY                                            │
│     max_tokens: 4096                                                    │
│     supports_thinking: false                                            │
│     supports_vision: true                                               │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                      ┌─────────────────────────┐
                      │   create_chat_model()   │
                      │  - name: str            │
                      │  - thinking_enabled     │
                      └────────────┬────────────┘
                                   │
                                   ▼
                      ┌─────────────────────────┐
                      │   resolve_class()       │
                      │  (reflection system)    │
                      └────────────┬────────────┘
                                   │
                                   ▼
                      ┌─────────────────────────┐
                      │   BaseChatModel         │
                      │  (LangChain instance)   │
                      └─────────────────────────┘
```

**支持的 Provider：**
- OpenAI（`langchain_openai:ChatOpenAI`）
- Anthropic（`langchain_anthropic:ChatAnthropic`）
- DeepSeek（`langchain_deepseek:ChatDeepSeek`）
- 通过 LangChain 集成的自定义 Provider

### MCP 集成

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          MCP 集成                                       │
│                        (packages/harness/deerflow/mcp/manager.py)                              │
└─────────────────────────────────────────────────────────────────────────┘

extensions_config.json:
┌─────────────────────────────────────────────────────────────────────────┐
│ {                                                                        │
│   "mcpServers": {                                                       │
│     "github": {                                                         │
│       "enabled": true,                                                  │
│       "type": "stdio",                                                  │
│       "command": "npx",                                                 │
│       "args": ["-y", "@modelcontextprotocol/server-github"],           │
│       "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}                          │
│     }                                                                   │
│   }                                                                     │
│ }                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                      ┌─────────────────────────┐
                      │  MultiServerMCPClient   │
                      │  (langchain-mcp-adapters)│
                      └────────────┬────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
              ▼                    ▼                    ▼
       ┌───────────┐        ┌───────────┐        ┌───────────┐
       │  stdio    │        │   SSE     │        │   HTTP    │
       │ transport │        │ transport │        │ transport │
       └───────────┘        └───────────┘        └───────────┘
```

### Skills 系统

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Skills 系统                                     │
│                       (packages/harness/deerflow/skills/loader.py)                             │
└─────────────────────────────────────────────────────────────────────────┘

目录结构：
┌─────────────────────────────────────────────────────────────────────────┐
│ skills/                                                                  │
│ ├── public/                        # 公开技能（会提交到仓库）             │
│ │   ├── pdf-processing/                                                 │
│ │   │   └── SKILL.md                                                    │
│ │   ├── frontend-design/                                                │
│ │   │   └── SKILL.md                                                    │
│ │   └── ...                                                             │
│ └── custom/                        # 自定义技能（gitignore）             │
│     └── user-installed/                                                 │
│         └── SKILL.md                                                    │
└─────────────────────────────────────────────────────────────────────────┘

SKILL.md 格式：
┌─────────────────────────────────────────────────────────────────────────┐
│ ---                                                                      │
│ name: PDF Processing                                                     │
│ description: Handle PDF documents efficiently                            │
│ license: MIT                                                            │
│ allowed-tools:                                                          │
│   - read_file                                                           │
│   - write_file                                                          │
│   - bash                                                                │
│ ---                                                                      │
│                                                                          │
│ # Skill Instructions                                                     │
│ Content injected into system prompt...                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 请求流

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         请求流示例                                       │
│                    用户向 agent 发送消息                                  │
└─────────────────────────────────────────────────────────────────────────┘

1. Client → Nginx
   POST /api/langgraph/threads/{thread_id}/runs
   {"input": {"messages": [{"role": "user", "content": "Hello"}]}}

2. Nginx → Gateway API (8001)
   `/api/langgraph/*` 被重写到 Gateway 兼容 LangGraph 的 `/api/*` 路由

3. Gateway 内嵌 runtime
   a. 加载/创建线程状态
   b. 执行中间件链：
      - ThreadDataMiddleware: 设置路径
      - UploadsMiddleware: 注入文件列表
      - SandboxMiddleware: 获取沙箱
      - SummarizationMiddleware: 检查 token 限制
      - TitleMiddleware: 必要时生成标题
      - TodoListMiddleware: 加载 todos（plan mode 时）
      - ViewImageMiddleware: 处理图片
      - ClarificationMiddleware: 检查澄清请求

   c. 执行 agent：
      - 模型处理消息
      - 可能调用工具（bash、web_search 等）
      - 工具通过沙箱执行
      - 结果追加到消息中

   d. 通过 SSE 流式返回响应

4. Client 接收流式响应
```

## 数据流

### 文件上传流

```
1. Client 上传文件
   POST /api/threads/{thread_id}/uploads
   Content-Type: multipart/form-data

2. Gateway 接收文件
   - 校验文件
   - 存储到 .deer-flow/threads/{thread_id}/user-data/uploads/
   - 若为文档：通过 markitdown 转换为 Markdown

3. 返回响应
   {
     "files": [{
       "filename": "doc.pdf",
       "path": ".deer-flow/.../uploads/doc.pdf",
       "virtual_path": "/mnt/user-data/uploads/doc.pdf",
       "artifact_url": "/api/threads/.../artifacts/mnt/.../doc.pdf"
     }]
   }

4. 下一次 agent run
   - UploadsMiddleware 列出文件
   - 将文件列表注入消息
   - Agent 可通过 virtual_path 访问
```

### 线程清理流

```
1. Client 通过 Gateway 兼容 LangGraph 的路由删除会话
   DELETE /api/langgraph/threads/{thread_id}

2. Web UI 随后调用 Gateway 清理
   DELETE /api/threads/{thread_id}

3. Gateway 删除本地 DeerFlow 管理文件
   - 递归删除 .deer-flow/threads/{thread_id}/
   - 目录不存在视为空操作
   - 访问文件系统前先拒绝无效线程 ID
```

### 配置重载

```
1. Client 更新 MCP 配置
   PUT /api/mcp/config

2. Gateway 写入 extensions_config.json
   - 更新 mcpServers 区段
   - 文件 mtime 发生变化

3. MCP Manager 检测变更
   - get_cached_mcp_tools() 检查 mtime
   - 若变更：重新初始化 MCP client
   - 加载更新后的服务器配置

4. 下一次 agent run 使用新工具
```

## 安全性考量

### 沙箱隔离

- Agent 代码在沙箱边界内执行
- 本地沙箱：直接执行（仅建议开发环境）
- Docker 沙箱：容器隔离（推荐生产环境）
- 文件操作中包含路径穿越防护

### API 安全

- 线程隔离：每个线程都有独立数据目录
- 文件校验：上传会进行路径安全检查
- 环境变量解析：密钥不会存入配置文件

### MCP 安全

- 每个 MCP 服务器在独立进程中运行
- 环境变量在运行时解析
- 服务器可独立启用/禁用

## 性能考量

### 缓存

- MCP 工具带文件 mtime 失效机制的缓存
- 配置加载一次，文件变更时重载
- Skills 在启动时解析一次并缓存在内存

### 流式输出

- 使用 SSE 进行实时响应流式传输
- 缩短首 token 时间
- 让长耗时操作具备过程可见性

### 上下文管理

- 接近限制时通过 summarization 中间件压缩上下文
- 触发条件可配置：tokens、messages 或比例
- 在摘要旧消息时保留最近消息

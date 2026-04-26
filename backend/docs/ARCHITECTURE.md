# 架构概述

本文档提供DeerFlow后端架构的全面概述。

## 系统架构

===================
设计思路说明
===================

**为什么采用这种架构**：

1. **三层架构设计**：
   - 前端层：React UI，负责用户交互
   - 网关层：FastAPI应用，处理辅助功能
   - 核心层：LangGraph Server，处理代理执行

2. **Nginx作为统一入口**：
   - 简化部署：单一入口点管理所有服务
   - 路由分发：根据URL路径将请求分发到不同后端
   - SSL终止：统一处理HTTPS

3. **API分离策略**：
   - `/api/langgraph/*` → LangGraph Server：代理执行相关
   - `/api/*` → Gateway API：配置和文件管理相关
   - `/*` → Frontend：静态资源

**架构优势**：
- **关注点分离**：代理逻辑与辅助功能解耦
- **可扩展性**：各层可独立扩展
- **标准化**：LangGraph API兼容SDK
- **灵活性**：Gateway可根据需求定制

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              客户端（浏览器）                              │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          Nginx (端口 2026)                               │
│                    统一反向代理入口点                                     │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  /api/langgraph/*  →  LangGraph Server (2024)                      │  │
│  │  /api/*            →  Gateway API (8001)                           │  │
│  │  /*                →  前端 (3000)                                   │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
│   LangGraph Server  │ │    Gateway API      │ │     前端            │
│     (端口 2024)     │ │    (端口 8001)      │ │    (端口 3000)      │
│                     │ │                     │ │                     │
│  - 代理运行时       │ │  - 模型API          │ │  - Next.js应用      │
│  - 线程管理         │ │  - MCP配置          │ │  - React UI         │
│  - SSE流式传输      │ │  - 技能管理         │ │  - 聊天界面         │
│  - 检查点           │ │  - 文件上传         │ │                     │
│                     │ │  - 线程清理         │ │                     │
│                     │ │  - 产物             │ │                     │
└─────────────────────┘ └─────────────────────┘ └─────────────────────┘
          │                       │
          │     ┌─────────────────┘
          │     │
          ▼     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         共享配置                                          │
│  ┌─────────────────────────┐  ┌────────────────────────────────────────┐ │
│  │      config.yaml        │  │      extensions_config.json            │ │
│  │  - 模型                 │  │  - MCP服务器                            │ │
│  │  - 工具                 │  │  - 技能状态                             │ │
│  │  - 沙箱                 │  │                                        │ │
│  │  - 摘要                 │  │                                        │ │
│  └─────────────────────────┘  └────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

## 组件详情

### LangGraph Server

LangGraph服务器是核心代理运行时，基于LangGraph构建，用于强大的多代理工作流编排。

**入口点**：`packages/harness/deerflow/agents/lead_agent/agent.py:make_lead_agent`

**核心职责**：
- 代理创建和配置
- 线程状态管理
- 中间件链执行
- 工具执行编排
- SSE流式传输实时响应

**配置**：`langgraph.json`

```json
{
  "agent": {
    "type": "agent",
    "path": "deerflow.agents:make_lead_agent"
  }
}
```

### Gateway API

FastAPI应用程序，为非代理操作提供REST端点。

**入口点**：`app/gateway/app.py`

**路由器**：
- `models.py` - `/api/models` - 模型列表和详情
- `mcp.py` - `/api/mcp` - MCP服务器配置
- `skills.py` - `/api/skills` - 技能管理
- `uploads.py` - `/api/threads/{id}/uploads` - 文件上传
- `threads.py` - `/api/threads/{id}` - LangGraph删除后的本地DeerFlow线程数据清理
- `artifacts.py` - `/api/threads/{id}/artifacts` - 产物服务
- `suggestions.py` - `/api/threads/{id}/suggestions` - 后续建议生成

**对话删除流程**现在分布在两个后端表面：LangGraph处理`DELETE /api/langgraph/threads/{thread_id}`用于线程状态，然后Gateway的`threads.py`路由器通过`Paths.delete_thread_dir()`删除DeerFlow管理的文件系统数据。

### 代理架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           make_lead_agent(config)                        │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            中间件链                                      │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ 1. ThreadDataMiddleware  - 初始化workspace/uploads/outputs       │   │
│  │ 2. UploadsMiddleware     - 处理上传的文件                         │   │
│  │ 3. SandboxMiddleware     - 获取沙箱环境                           │   │
│  │ 4. SummarizationMiddleware - 上下文缩减（如果启用）               │   │
│  │ 5. TitleMiddleware       - 自动生成标题                           │   │
│  │ 6. TodoListMiddleware    - 任务跟踪（如果启用plan_mode）          │   │
│  │ 7. ViewImageMiddleware   - 视觉模型支持                           │   │
│  │ 8. ClarificationMiddleware - 处理澄清                             │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              代理核心                                    │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐   │
│  │      模型        │  │      工具        │  │    系统提示          │   │
│  │  (来自工厂)      │  │  (已配置 +        │  │  (包含技能)          │   │
│  │                  │  │   MCP + 内置)     │  │                      │   │
│  └──────────────────┘  └──────────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 线程状态

`ThreadState`扩展了LangGraph的`AgentState`，增加了额外的字段：

```python
class ThreadState(AgentState):
    # 来自AgentState的核心状态
    messages: list[BaseMessage]

    # DeerFlow扩展
    sandbox: dict             # 沙箱环境信息
    artifacts: list[str]      # 生成的文件路径
    thread_data: dict         # {workspace, uploads, outputs}路径
    title: str | None         # 自动生成的对话标题
    todos: list[dict]         # 任务跟踪（计划模式）
    viewed_images: dict       # 视觉模型图像数据
```

### 沙箱系统

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           沙箱架构                                      │
└─────────────────────────────────────────────────────────────────────────┘

                      ┌─────────────────────────┐
                      │    SandboxProvider      │ (抽象)
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
│  - 单例实例             │              │  - 基于Docker           │
│  - 直接执行             │              │  - 隔离容器             │
│  - 开发使用             │              │  - 生产使用             │
└─────────────────────────┘              └─────────────────────────┘

                      ┌─────────────────────────┐
                      │        Sandbox          │ (抽象)
                      │  - execute_command()    │
                      │  - read_file()          │
                      │  - write_file()         │
                      │  - list_dir()           │
                      └─────────────────────────┘
```

**虚拟路径映射**：

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
│   内置工具          │  │  已配置工具         │  │     MCP工具         │
│  (packages/harness/deerflow/tools/)       │  │  (config.yaml)      │  │  (extensions.json)  │
├─────────────────────┤  ├─────────────────────┤  ├─────────────────────┤
│ - present_file      │  │ - web_search        │  │ - github            │
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
                      │  (反射系统)             │
                      └────────────┬────────────┘
                                   │
                                   ▼
                      ┌─────────────────────────┐
                      │   BaseChatModel         │
                      │  (LangChain实例)        │
                      └─────────────────────────┘
```

**支持的提供商**：
- OpenAI (`langchain_openai:ChatOpenAI`)
- Anthropic (`langchain_anthropic:ChatAnthropic`)
- DeepSeek (`langchain_deepseek:ChatDeepSeek`)
- 通过LangChain集成自定义提供商

### MCP集成

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          MCP集成                                        │
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

### 技能系统

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          技能系统                                        │
│                       (packages/harness/deerflow/skills/loader.py)                             │
└─────────────────────────────────────────────────────────────────────────┘

目录结构:
┌─────────────────────────────────────────────────────────────────────────┐
│ skills/                                                                  │
│ ├── public/                        # 公共技能（已提交）                   │
│ │   ├── pdf-processing/                                                 │
│ │   │   └── SKILL.md                                                    │
│ │   ├── frontend-design/                                                │
│ │   │   └── SKILL.md                                                    │
│ │   └── ...                                                             │
│ └── custom/                        # 自定义技能（gitignored）             │
│     └── user-installed/                                                 │
│         └── SKILL.md                                                    │
└─────────────────────────────────────────────────────────────────────────┘

SKILL.md格式:
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
│ # 技能说明                                                               │
│ 注入到系统提示中的内容...                                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### 请求流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         请求流程示例                                     │
│                    用户向代理发送消息                                    │
└─────────────────────────────────────────────────────────────────────────┘

1. 客户端 → Nginx
   POST /api/langgraph/threads/{thread_id}/runs
   {"input": {"messages": [{"role": "user", "content": "Hello"}]}}

2. Nginx → LangGraph Server (2024)
   代理到LangGraph服务器

3. LangGraph服务器
   a. 加载/创建线程状态
   b. 执行中间件链：
      - ThreadDataMiddleware: 设置路径
      - UploadsMiddleware: 注入文件列表
      - SandboxMiddleware: 获取沙箱
      - SummarizationMiddleware: 检查token限制
      - TitleMiddleware: 如果需要生成标题
      - TodoListMiddleware: 加载待办事项（如果启用计划模式）
      - ViewImageMiddleware: 处理图像
      - ClarificationMiddleware: 检查澄清

   c. 执行代理：
      - 模型处理消息
      - 可能调用工具（bash、web_search等）
      - 工具通过沙箱执行
      - 结果添加到消息中

   d. 通过SSE流式传输响应

4. 客户端接收流式响应
```

## 数据流

### 文件上传流程

```
1. 客户端上传文件
   POST /api/threads/{thread_id}/uploads
   Content-Type: multipart/form-data

2. Gateway接收文件
   - 验证文件
   - 存储在 .deer-flow/threads/{thread_id}/user-data/uploads/
   - 如果是文档：通过markitdown转换为Markdown

3. 返回响应
   {
     "files": [{
       "filename": "doc.pdf",
       "path": ".deer-flow/.../uploads/doc.pdf",
       "virtual_path": "/mnt/user-data/uploads/doc.pdf",
       "artifact_url": "/api/threads/.../artifacts/mnt/.../doc.pdf"
     }]
   }

4. 下次代理运行
   - UploadsMiddleware列出文件
   - 将文件列表注入到消息中
   - 代理可以通过virtual_path访问
```

### 线程清理流程

```
1. 客户端通过LangGraph删除对话
   DELETE /api/langgraph/threads/{thread_id}

2. Web UI跟随Gateway清理
   DELETE /api/threads/{thread_id}

3. Gateway删除本地DeerFlow管理的文件
   - 递归删除 .deer-flow/threads/{thread_id}/
   - 缺失的目录被视为无操作
   - 无效的线程ID在文件系统访问之前被拒绝
```

### 配置重载

```
1. 客户端更新MCP配置
   PUT /api/mcp/config

2. Gateway写入extensions_config.json
   - 更新mcpServers部分
   - 文件mtime更改

3. MCP管理器检测更改
   - get_cached_mcp_tools()检查mtime
   - 如果更改：重新初始化MCP客户端
   - 加载更新的服务器配置

4. 下次代理运行使用新工具
```

## 安全考虑

### 沙箱隔离

- 代理代码在沙箱边界内执行
- 本地沙箱：直接执行（仅开发）
- Docker沙箱：容器隔离（生产推荐）
- 文件操作中的路径遍历预防

### API安全

- 线程隔离：每个线程有单独的数据目录
- 文件验证：上传检查路径安全性
- 环境变量解析：机密不存储在配置中

### MCP安全

- 每个MCP服务器在自己的进程中运行
- 环境变量在运行时解析
- 服务器可以独立启用/禁用

## 性能考虑

### 缓存

- MCP工具使用文件mtime失效进行缓存
- 配置加载一次，文件更改时重新加载
- 技能在启动时解析一次，缓存在内存中

### 流式传输

- SSE用于实时响应流式传输
- 减少首token时间
- 为长操作启用进度可见性

### 上下文管理

- 摘要中间件在接近限制时减少上下文
- 可配置的触发器：token、消息或分数
- 保留最近的消息，同时总结较旧的消息

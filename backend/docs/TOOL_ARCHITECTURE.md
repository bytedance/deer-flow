# DeerFlow 工具调用架构详解

本文档详细描述 DeerFlow 的工具系统架构，包括工具来源分类、加载机制、调用流程、子 Agent 工具过滤、以及沙箱和 MCP 集成。

## 目录

- [1. 架构总览](#1-架构总览)
- [2. 工具来源分类](#2-工具来源分类)
  - [2.1 Config-defined Tools](#21-config-defined-tools配置定义工具)
  - [2.2 Built-in Tools](#22-built-in-tools内置工具)
  - [2.3 MCP Tools](#23-mcp-toolsmodel-context-protocol-工具)
  - [2.4 Community Tools](#24-community-tools社区贡献工具)
- [3. 工具加载流程](#3-工具加载流程)
  - [3.1 中央聚合函数](#31-中央聚合函数)
  - [3.2 Tool Groups 过滤](#32-tool-groups-过滤机制)
  - [3.3 动态 import 机制](#33-动态-import-机制)
- [4. 全部工具详细说明](#4-全部工具详细说明)
  - [4.1 沙箱工具](#41-沙箱工具sandbox-tools)
  - [4.2 网络工具](#42-网络工具web-tools)
  - [4.3 内置工具](#43-内置工具builtin-tools)
- [5. Subagent 工具过滤与隔离](#5-subagent-工具过滤与隔离)
- [6. MCP 集成详解](#6-mcp-集成详解)
- [7. 沙箱与虚拟路径系统](#7-沙箱与虚拟路径系统)
- [8. 工具相关 Middleware](#8-工具相关-middleware)
- [9. 工具 Token 成本分析](#9-工具-token-成本分析)

---

## 1. 架构总览

DeerFlow 的工具系统由 **四层来源** 组成，通过中央聚合函数 `get_available_tools()` 统一加载，经 Middleware 链处理后传递给 Agent。

```
                          ┌───────────────────┐
                          │    用户消息输入     │
                          └────────┬──────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │      make_lead_agent()       │
                    │  backend/src/agents/lead_    │
                    │      agent/agent.py          │
                    └────────────┬────────────────┘
                                 │
                                 ▼
           ┌────────────────────────────────────────────┐
           │          get_available_tools()              │
           │        backend/src/tools/tools.py           │
           ├──────────┬──────────┬──────────┬───────────┤
           │ Config   │ Built-in │   MCP    │  (三者合并) │
           │ Tools    │ Tools    │  Tools   │            │
           └──────────┴──────────┴──────────┴───────────┘
               │           │           │
               ▼           ▼           ▼
         config.yaml    硬编码在     extensions_
         tools[] 列表   代码中       config.json
               │                       │
               ▼                       ▼
        resolve_variable()     langchain-mcp-adapters
        动态 import 模块        MultiServerMCPClient
```

最终合并列表传入 `create_agent(tools=...)`，Agent 在推理时根据任务需要选择调用。

---

## 2. 工具来源分类

### 2.1 Config-defined Tools（配置定义工具）

在 `config.yaml` 的 `tools[]` 列表中声明。每个 tool 包含三个核心字段：

```yaml
# config.yaml
tools:
  - name: bash
    group: bash
    use: src.sandbox.tools:bash_tool

  - name: web_search
    group: web
    use: src.community.firecrawl.tools:web_search_tool
    max_results: 5
```

字段说明：

| 字段 | 说明 |
|------|------|
| `name` | 工具唯一标识 |
| `group` | 所属分组，用于 tool_groups 过滤 |
| `use` | 模块路径，格式 `module.path:variable_name` |
| 其他字段 | 传递给工具的额外配置（如 `max_results`、`api_key`）|

配置 schema 定义在 `backend/src/config/tool_config.py`：

```python
class ToolConfig(BaseModel):
    name: str
    group: str
    use: str    # e.g. "src.sandbox.tools:bash_tool"
    model_config = ConfigDict(extra="allow")  # 允许额外配置字段
```

### 2.2 Built-in Tools（内置工具）

硬编码在 `backend/src/tools/tools.py` 中，不需要配置：

```python
BUILTIN_TOOLS = [
    present_file_tool,       # 始终加载
    ask_clarification_tool,  # 始终加载
]

SUBAGENT_TOOLS = [
    task_tool,               # 仅 subagent_enabled=True 时加载
]

# view_image_tool 仅在模型 supports_vision=True 时加载
```

| 工具 | 加载条件 | 位置 |
|------|---------|------|
| `present_files` | 始终 | `builtins/present_file_tool.py` |
| `ask_clarification` | 始终 | `builtins/clarification_tool.py` |
| `task` | `subagent_enabled=True` | `builtins/task_tool.py` |
| `view_image` | 模型 `supports_vision=True` | `builtins/view_image_tool.py` |
| `setup_agent` | `is_bootstrap=True` | `builtins/setup_agent_tool.py` |

### 2.3 MCP Tools（Model Context Protocol 工具）

通过 `extensions_config.json` 配置外部 MCP 服务器，使用 `langchain-mcp-adapters` 库桥接为 LangChain `BaseTool`。

```json
{
  "mcpServers": {
    "playwright": {
      "enabled": false,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@playwright/mcp"],
      "description": "Playwright MCP server for browser automation"
    }
  }
}
```

支持三种传输协议：

| 协议 | 配置字段 | 适用场景 |
|------|---------|---------|
| `stdio` | `command`, `args`, `env` | 本地进程（如 npx 启动） |
| `sse` | `url`, `headers` | Server-Sent Events 远程服务 |
| `http` | `url`, `headers` | HTTP 远程服务 |

### 2.4 Community Tools（社区贡献工具）

位于 `backend/src/community/` 下，通过 config 的 `use` 路径引用。本质上属于 Config-defined Tools 的实现侧：

| 模块 | 提供的工具 | 说明 |
|------|----------|------|
| `firecrawl/` | `web_search_tool`, `web_fetch_tool` | 基于 Firecrawl API |
| `tavily/` | `web_search_tool`, `web_fetch_tool` | 基于 Tavily Search API |
| `jina_ai/` | `web_fetch_tool` | 基于 Jina AI Reader API |
| `infoquest/` | `web_search_tool`, `web_fetch_tool` | 基于 InfoQuest API |
| `image_search/` | `image_search_tool` | 图片搜索 |

用户在 `config.yaml` 中修改 `use` 路径即可切换搜索/抓取后端，无需改代码。

---

## 3. 工具加载流程

### 3.1 中央聚合函数

`get_available_tools()` 是唯一的工具加载入口：

```python
# backend/src/tools/tools.py

def get_available_tools(
    groups: list[str] | None = None,     # 按 group 过滤 config 工具
    include_mcp: bool = True,            # 是否包含 MCP 工具
    model_name: str | None = None,       # 用于判断是否加载 vision 工具
    subagent_enabled: bool = False,      # 是否包含 task 工具
) -> list[BaseTool]:
    config = get_app_config()

    # 1. Config-defined tools（按 groups 过滤）
    loaded_tools = [
        resolve_variable(tool.use, BaseTool)
        for tool in config.tools
        if groups is None or tool.group in groups
    ]

    # 2. MCP tools（从缓存获取）
    mcp_tools = get_cached_mcp_tools() if include_mcp else []

    # 3. Built-in tools（始终 + 条件加载）
    builtin_tools = [present_file_tool, ask_clarification_tool]
    if subagent_enabled:
        builtin_tools.append(task_tool)
    if model_supports_vision:
        builtin_tools.append(view_image_tool)

    return loaded_tools + builtin_tools + mcp_tools
```

### 3.2 Tool Groups 过滤机制

Tool Groups 允许不同 Agent 只加载需要的工具子集。

默认分组（`config.yaml`）：

```yaml
tool_groups:
  - name: web        # web_search, web_fetch, image_search
  - name: file:read  # ls, read_file
  - name: file:write # write_file, str_replace
  - name: bash       # bash
```

| 分组 | 包含的工具 | 典型场景 |
|------|----------|---------|
| `web` | web_search, web_fetch, image_search | 需要联网搜索的 Agent |
| `file:read` | ls, read_file | 只需读取文件的 Agent |
| `file:write` | write_file, str_replace | 需要修改文件的 Agent |
| `bash` | bash | 需要执行命令的 Agent |

过滤逻辑：
- `groups=None` → 加载全部 config 工具
- `groups=["web", "file:read"]` → 仅加载这两个分组的工具

自定义 Agent 通过 `tool_groups` 配置限制可用工具：

```python
# agent.py
tools = get_available_tools(
    groups=agent_config.tool_groups if agent_config else None,
    ...
)
```

### 3.3 动态 import 机制

Config 中的 `use` 字段通过反射机制解析：

```python
# backend/src/reflection/resolvers.py

def resolve_variable(variable_path: str, expected_type=None):
    """Resolve 'module.path:variable_name' to actual Python object."""
    module_path, variable_name = variable_path.rsplit(":", 1)
    module = import_module(module_path)
    variable = getattr(module, variable_name)
    # 类型校验
    return variable
```

例如 `src.sandbox.tools:bash_tool` →
1. `import_module("src.sandbox.tools")`
2. `getattr(module, "bash_tool")`
3. 验证返回值是 `BaseTool` 实例

---

## 4. 全部工具详细说明

### 4.1 沙箱工具（Sandbox Tools）

位于 `backend/src/sandbox/tools.py`。所有沙箱工具共享相同的运行时环境：通过 `ensure_sandbox_initialized()` 懒初始化沙箱，支持虚拟路径映射。

#### bash — 执行 Bash 命令

```python
@tool("bash")
def bash_tool(runtime, description: str, command: str) -> str
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `description` | `str` | 简要说明执行目的（优先提供） |
| `command` | `str` | 要执行的 bash 命令 |

- 在沙箱环境中执行，支持 Python、pip、git、npm 等常规 Linux 命令
- 自动将 `/mnt/user-data/*` 虚拟路径映射到实际线程目录（本地沙箱时）
- 返回 stdout + stderr 的合并输出

#### ls — 列出目录内容

```python
@tool("ls")
def ls_tool(runtime, description: str, path: str) -> str
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `description` | `str` | 简要说明列目录目的 |
| `path` | `str` | 目录的绝对路径 |

- 返回 2 层深度的 tree 格式目录结构
- 空目录返回 `(empty)`

#### read_file — 读取文件

```python
@tool("read_file")
def read_file_tool(runtime, description: str, path: str,
                   start_line: int | None = None,
                   end_line: int | None = None) -> str
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `description` | `str` | 简要说明读取目的 |
| `path` | `str` | 文件的绝对路径 |
| `start_line` | `int \| None` | 起始行号（1-indexed，包含） |
| `end_line` | `int \| None` | 结束行号（1-indexed，包含） |

- 支持行号范围读取，适用于大文件的局部查看
- 空文件返回 `(empty)`

#### write_file — 写入文件

```python
@tool("write_file")
def write_file_tool(runtime, description: str, path: str,
                    content: str, append: bool = False) -> str
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `description` | `str` | 简要说明写入目的 |
| `path` | `str` | 文件的绝对路径 |
| `content` | `str` | 要写入的内容 |
| `append` | `bool` | 是否追加模式（默认覆盖） |

- 自动创建不存在的目录和文件
- 返回 `"OK"` 表示成功

#### str_replace — 字符串替换

```python
@tool("str_replace")
def str_replace_tool(runtime, description: str, path: str,
                     old_str: str, new_str: str,
                     replace_all: bool = False) -> str
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `description` | `str` | 简要说明替换目的 |
| `path` | `str` | 文件的绝对路径 |
| `old_str` | `str` | 要被替换的字符串 |
| `new_str` | `str` | 替换后的字符串 |
| `replace_all` | `bool` | 替换所有匹配（默认仅首次） |

- 默认模式下 `old_str` 必须在文件中唯一匹配
- 如果 `old_str` 不存在于文件中，返回错误

### 4.2 网络工具（Web Tools）

通过 config 声明，实现在 `backend/src/community/` 下。

#### web_search — 网络搜索

| 参数 | 类型 | 说明 |
|------|------|------|
| `query` | `str` | 搜索关键词 |

- 返回搜索结果列表（标题、URL、摘要）
- `max_results` 通过 config 的额外字段配置
- 可选后端：Firecrawl / Tavily / InfoQuest

#### web_fetch — 网页内容抓取

| 参数 | 类型 | 说明 |
|------|------|------|
| `url` | `str` | 要抓取的网页 URL |

- 返回网页的文本/Markdown 内容
- `timeout` 通过 config 配置
- 可选后端：Firecrawl / Jina AI / InfoQuest

#### image_search — 图片搜索

| 参数 | 类型 | 说明 |
|------|------|------|
| `query` | `str` | 搜索关键词 |

- 返回图片 URL 列表
- `max_results` 通过 config 配置

### 4.3 内置工具（Builtin Tools）

位于 `backend/src/tools/builtins/`。

#### present_files — 向用户呈现文件

```python
@tool("present_files")
def present_file_tool(runtime, filepaths: list[str], tool_call_id) -> Command
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `filepaths` | `list[str]` | 文件路径列表 |

- **仅限** `/mnt/user-data/outputs` 下的文件
- 通过 LangGraph `Command` 更新 ThreadState 的 `artifacts` 字段
- 前端根据 artifacts 列表渲染文件预览/下载按钮
- 支持并行调用（使用 reducer 防止状态冲突）

#### ask_clarification — 向用户提问

```python
@tool("ask_clarification", return_direct=True)
def ask_clarification_tool(question, clarification_type, context=None, options=None) -> str
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `question` | `str` | 要问用户的问题 |
| `clarification_type` | `Literal[...]` | 澄清类型（见下表） |
| `context` | `str \| None` | 补充上下文说明 |
| `options` | `list[str] \| None` | 可选项列表 |

澄清类型：

| 类型 | 使用场景 |
|------|---------|
| `missing_info` | 缺少必要信息（如文件路径、URL） |
| `ambiguous_requirement` | 需求有多种理解方式 |
| `approach_choice` | 多种实现方案供选择 |
| `risk_confirmation` | 危险操作需要确认（如删除文件） |
| `suggestion` | 有建议方案需要用户批准 |

**特殊行为**：
- 标记 `return_direct=True`
- 实际不执行工具逻辑——由 `ClarificationMiddleware` 在 `before_tool` 阶段拦截
- Middleware 将问题格式化后通过 `Command(goto=END)` **中断整个 Agent 执行**
- 用户回复后 Agent 从中断点继续

#### task — 委派子任务

```python
@tool("task")
def task_tool(runtime, description, prompt, subagent_type, tool_call_id,
              max_turns=None) -> str
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `description` | `str` | 3-5 词任务描述（用于日志/UI 显示） |
| `prompt` | `str` | 详细任务描述 |
| `subagent_type` | `Literal["general-purpose", "bash"]` | 子 Agent 类型 |
| `max_turns` | `int \| None` | 最大推理轮数（默认用配置值） |

**执行流程**：

```
1. task_tool 被调用
   │
2. 获取子 Agent 配置（SubagentConfig）
   │
3. get_available_tools(subagent_enabled=False)
   │  ↳ 获取所有工具但排除 task（防递归嵌套）
   │
4. 创建 SubagentExecutor
   │
5. executor.execute_async(prompt)
   │  ↳ 在独立线程池中异步执行
   │
6. 后台轮询（每 5 秒）
   │  ├── 发送 task_started 事件
   │  ├── 发送 task_running 事件（每有新 AI 消息）
   │  └── 完成/失败/超时 → 返回结果
   │
7. 返回 "Task Succeeded. Result: ..."
```

**流式事件**：通过 `stream_writer` 向前端实时发送进度：

| 事件类型 | 时机 | 内容 |
|---------|------|------|
| `task_started` | 任务启动 | task_id, description |
| `task_running` | 子 Agent 产生新消息 | task_id, message, message_index |
| `task_completed` | 任务成功 | task_id, result |
| `task_failed` | 任务失败 | task_id, error |
| `task_timed_out` | 任务超时 | task_id, error |

#### view_image — 查看图片

```python
@tool("view_image")
def view_image_tool(runtime, image_path: str, tool_call_id) -> Command
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `image_path` | `str` | 图片文件的绝对路径 |

- **加载条件**：仅当模型配置 `supports_vision=True` 时可用
- 支持格式：`.jpg`、`.jpeg`、`.png`、`.webp`
- 读取图片 → base64 编码 → 写入 ThreadState 的 `viewed_images` 字段
- 视觉模型在后续轮次可以 "看到" 这张图片

---

## 5. Subagent 工具过滤与隔离

子 Agent 不直接继承父 Agent 的全部工具，而是通过 `_filter_tools()` 进行过滤：

```python
# backend/src/subagents/executor.py

def _filter_tools(all_tools, allowed, disallowed) -> list[BaseTool]:
    filtered = all_tools
    if allowed is not None:
        filtered = [t for t in filtered if t.name in set(allowed)]
    if disallowed is not None:
        filtered = [t for t in filtered if t.name not in set(disallowed)]
    return filtered
```

### 两种子 Agent 的工具配置

#### general-purpose 子 Agent

```python
# backend/src/subagents/builtins/general_purpose.py

GENERAL_PURPOSE_CONFIG = SubagentConfig(
    name="general-purpose",
    tools=None,                    # 继承父 Agent 的所有工具
    disallowed_tools=[
        "task",                    # 不能再嵌套创建子 Agent
        "ask_clarification",       # 不能向用户提问
        "present_files",           # 不能直接向用户呈现文件
    ],
    model="inherit",               # 使用与父 Agent 相同的模型
    max_turns=50,
)
```

**实际可用工具**：bash, ls, read_file, write_file, str_replace, web_search, web_fetch, image_search + 所有 MCP 工具。

#### bash 子 Agent

```python
# backend/src/subagents/builtins/bash_agent.py

BASH_AGENT_CONFIG = SubagentConfig(
    name="bash",
    tools=[                        # 仅白名单工具
        "bash", "ls", "read_file",
        "write_file", "str_replace",
    ],
    disallowed_tools=[
        "task", "ask_clarification",
        "present_files",
    ],
    model="inherit",
    max_turns=30,
)
```

**实际可用工具**：仅沙箱 5 件套（bash, ls, read_file, write_file, str_replace）。

### 工具过滤完整流程

```
父 Agent 调用 task tool
        │
        ▼
get_available_tools(subagent_enabled=False)
        │  ↳ 全部 config + builtin（不含 task）+ MCP 工具
        │
        ▼
SubagentExecutor(config, tools)
        │
        ▼
_filter_tools(
    all_tools,
    allowed = config.tools,         # None (general) 或 白名单 (bash)
    disallowed = config.disallowed_tools  # [task, ask_clarification, present_files]
)
        │
        ▼
create_agent(tools=filtered_tools)
```

### 防递归保护

- `task_tool` 内部调用 `get_available_tools(subagent_enabled=False)`，结果不含 `task` 工具
- 子 Agent 的 `disallowed_tools` 再次排除 `task`
- 双重保护确保子 Agent 无法再创建子 Agent，避免无限嵌套

---

## 6. MCP 集成详解

### 架构

```
extensions_config.json         langchain-mcp-adapters
        │                              │
        ▼                              ▼
ExtensionsConfig.from_file()    MultiServerMCPClient
        │                              │
        ▼                              ▼
build_servers_config()  ──────►  client.get_tools()
        │                              │
        ▼                              ▼
   服务器参数映射              LangChain BaseTool 列表
```

### 加载流程

```python
# backend/src/mcp/tools.py

async def get_mcp_tools() -> list[BaseTool]:
    extensions_config = ExtensionsConfig.from_file()   # 读最新配置
    servers_config = build_servers_config(extensions_config)
    # 注入 OAuth headers（如果配置了 OAuth）
    client = MultiServerMCPClient(servers_config, tool_interceptors=...)
    tools = await client.get_tools()
    return tools
```

### 缓存机制

位于 `backend/src/mcp/cache.py`：

| 函数 | 用途 |
|------|------|
| `initialize_mcp_tools()` | 应用启动时调用，初始化并缓存 MCP 工具 |
| `get_cached_mcp_tools()` | 获取缓存的工具列表，支持懒初始化 |
| `reset_mcp_tools_cache()` | 重置缓存（测试或配置变更时使用） |

**自动失效**：通过检测 `extensions_config.json` 的文件修改时间（mtime）。当 Gateway API 修改了 MCP 配置（在独立进程中），LangGraph Server 下次调用 `get_cached_mcp_tools()` 时会检测到 mtime 变化并重新加载。

### 配置传输协议

```python
# backend/src/mcp/client.py

def build_server_params(server_name, config) -> dict:
    transport_type = config.type or "stdio"
    if transport_type == "stdio":
        params = {"command": config.command, "args": config.args, "env": config.env}
    elif transport_type in ("sse", "http"):
        params = {"url": config.url, "headers": config.headers}
    return params
```

---

## 7. 沙箱与虚拟路径系统

### 沙箱初始化

沙箱采用 **懒初始化** 策略——首次调用沙箱工具时才分配：

```python
# backend/src/sandbox/tools.py

def ensure_sandbox_initialized(runtime) -> Sandbox:
    # 已有沙箱 → 直接返回
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state and sandbox_state.get("sandbox_id"):
        return provider.get(sandbox_id)

    # 首次使用 → 懒分配
    thread_id = runtime.context.get("thread_id")
    sandbox_id = provider.acquire(thread_id)
    runtime.state["sandbox"] = {"sandbox_id": sandbox_id}
    return provider.get(sandbox_id)
```

### 虚拟路径映射

所有沙箱工具支持虚拟路径 `/mnt/user-data/*` 到实际线程目录的透明映射：

| 虚拟路径 | 映射目标 | 用途 |
|---------|---------|------|
| `/mnt/user-data/workspace/*` | `thread_data['workspace_path']/*` | 工作区（项目文件） |
| `/mnt/user-data/uploads/*` | `thread_data['uploads_path']/*` | 用户上传的文件 |
| `/mnt/user-data/outputs/*` | `thread_data['outputs_path']/*` | Agent 产出的文件 |

```python
def replace_virtual_path(path, thread_data) -> str:
    # /mnt/user-data/workspace/main.py
    #  → /app/backend/.deer-flow/threads/<thread>/user-data/workspace/main.py
```

**设计目的**：
- Agent 始终使用统一的 `/mnt/user-data/` 路径，不需要知道实际路径
- 本地沙箱：通过路径映射转换；远程 AIO 沙箱：路径已在容器中挂载
- 对 Agent 完全透明，同一个 prompt 可在不同沙箱类型下运行

bash 工具还支持命令内嵌虚拟路径的批量替换（`replace_virtual_paths_in_command`），处理如 `cat /mnt/user-data/workspace/a.txt | grep error > /mnt/user-data/outputs/result.txt` 这样的复合命令。

---

## 8. 工具相关 Middleware

### ClarificationMiddleware

拦截 `ask_clarification` 工具调用，中断 Agent 执行：

```python
# backend/src/agents/middlewares/clarification_middleware.py

class ClarificationMiddleware(AgentMiddleware):
    def before_tool(self, tool_call_request, state, runtime):
        if tool_call_request.name == "ask_clarification":
            # 格式化问题 → 添加 emoji/类型标签
            # 返回 Command(goto=END) 中断执行
            return Command(
                goto=END,
                update={"messages": [ToolMessage(formatted_message, ...)]},
            )
```

工作原理：
1. LLM 决定调用 `ask_clarification`
2. Middleware 在 **工具执行前** 拦截（`before_tool` hook）
3. 将问题格式化为用户友好的消息
4. 通过 `Command(goto=END)` 终止当前 Agent 循环
5. 用户回复后，系统将回复追加到消息历史，Agent 继续执行

### SubagentLimitMiddleware

限制单次模型响应中并行 task 调用的数量：

```python
# backend/src/agents/middlewares/subagent_limit_middleware.py

class SubagentLimitMiddleware(AgentMiddleware):
    def __init__(self, max_concurrent=3):
        self.max_concurrent = clamp(max_concurrent, 2, 4)

    def after_model(self, state, runtime):
        # 检查最后一条 AI 消息中的 tool_calls
        # 如果 task 调用 > max_concurrent，截断多余的
        task_indices = [i for i, tc in enumerate(tool_calls)
                       if tc.get("name") == "task"]
        if len(task_indices) > self.max_concurrent:
            # 保留前 max_concurrent 个，丢弃多余的
```

工作原理：
1. LLM 在单次响应中可能生成多个并行 `task` 调用
2. Middleware 在 **模型输出后** 拦截（`after_model` hook）
3. 如果 task 调用数量超过限制（默认 3，范围 [2, 4]），截断多余的
4. 比 prompt 级别的限制更可靠——直接修改 tool_calls 列表

---

## 9. 工具 Token 成本分析

每个工具对 LLM 上下文窗口的 token 消耗分为两部分：

### Tool 定义（Fixed Cost）

每个工具的 JSON Schema（name + description + parameters）占用固定 token：

| 工具 | 估算 Token | 说明 |
|------|-----------|------|
| bash | ~350 | 描述 + 2 个参数 |
| ls | ~300 | 描述 + 2 个参数 |
| read_file | ~400 | 描述 + 4 个参数 |
| write_file | ~350 | 描述 + 4 个参数 |
| str_replace | ~400 | 描述 + 5 个参数 |
| web_search | ~250 | 描述 + 1-2 个参数 |
| web_fetch | ~250 | 描述 + 1-2 个参数 |
| present_files | ~300 | 描述 + 1 个参数 |
| ask_clarification | ~500 | 描述长 + 4 个参数 + enum |
| task | ~800 | 描述很长 + 4 个参数 + enum |
| view_image | ~300 | 描述 + 1 个参数 |
| **全部 11 个** | **~4,200** | 还未计入 MCP 工具 |

如果启用了 MCP 工具（如 Playwright 提供 20+ 工具），tool 定义的固定成本可能达到 **10K-20K tokens**。

### Tool 输出（Variable Cost）

每次工具调用的返回内容消耗不定量 token：

| 工具 | 典型输出 Token | 场景 |
|------|--------------|------|
| bash | 100-5,000 | 命令输出，`npm install` 可能很长 |
| read_file | 200-3,000 | 取决于文件大小和行范围 |
| web_fetch | 2,000-8,000 | 网页内容转 Markdown |
| web_search | 500-2,000 | 搜索结果摘要 |
| ls | 50-500 | 目录树 |
| write_file | ~5 | 固定 "OK" |
| str_replace | ~5 | 固定 "OK" |

在 10 轮 tool 使用后，tool 输出可能累积到 **30K-50K tokens**。

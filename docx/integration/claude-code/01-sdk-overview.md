# claude-agent-sdk Python 包概览

> 来源：v0.2.93（wheel 内置 CLI 2.1.167）
> 仓库：`https://github.com/anthropics/claude-agent-sdk-python`
> 安装：`pip install claude-agent-sdk`（Python 3.10+）
> 依赖：`anyio>=4.0.0`、`sniffio>=1.0.0`、`mcp>=1.23.0`

## 一、两条 API 路径

| API | 形态 | 何时用 |
|---|---|---|
| `query(prompt, options)` | `AsyncIterator[Message]` | 一次性、无状态、流式 yield Message |
| `ClaudeSDKClient(options)` | context manager，双向 | 多轮、可中断、可续接、可 `include_partial_messages` 真流式 |

**关键硬限制**（README + `client.py:60-64` 明确写出）：

> ClaudeSDKClient 实例**不能跨不同 async runtime context**（不同 `trio` nursery / `asyncio` task group）。必须在**同一个 async context** 内用完。理想情况下这限制不该存在，但 v0.0.20 之后就一直这样。

## 二、底层传输

- 默认 `SubprocessCLITransport` — spawn Claude Code CLI 子进程、stdio 上的 JSON line 协议
- SDK 本身**不直接调 Anthropic API** —— 所有模型调用都走 CLI
- CLI 已**打包进 wheel**；用 `cli_path=...` 可改用外部 CLI
- 烟雾测试已验证 `cli_path` 真生效（`SystemMessage.claude_code_version` 跟着切）
- 可注入自定义 `Transport`（继承 `claude_agent_sdk.Transport`）做测试 / in-process mock

## 三、消息 / 块模型

### 顶层消息（`Message` 联合类型）

```
UserMessage
AssistantMessage
SystemMessage
    ├─ TaskStartedMessage
    ├─ TaskProgressMessage
    ├─ TaskNotificationMessage
    ├─ HookEventMessage
    └─ MirrorErrorMessage
ResultMessage
StreamEvent
RateLimitEvent
```

### 内容块（`ContentBlock` 联合类型）

```
TextBlock(text)
ThinkingBlock(thinking, signature)
ToolUseBlock(id, name, input)
ToolResultBlock(tool_use_id, content, is_error)
ServerToolUseBlock(id, name: ServerToolName, input)
ServerToolResultBlock(tool_use_id, content)
```

`ServerToolName` = `advisor | web_search | web_fetch | code_execution | bash_code_execution | text_editor_code_execution | tool_search_tool_regex | tool_search_tool_bm25`

### 关键字段

- `AssistantMessage.model / .error / .usage / .stop_reason / .session_id / .uuid`
- `ResultMessage.subtype / .is_error / .stop_reason / .duration_ms / .duration_api_ms / .num_turns / .total_cost_usd / .usage / .result / .permission_denials / .deferred_tool_use / .api_error_status`
- `StreamEvent.event` —— 原始 Anthropic API stream event（设了 `include_partial_messages=True` 才有）
- `RateLimitEvent.rate_limit_info` —— `status: 'allowed' | 'allowed_warning' | 'rejected'`

## 四、`ClaudeAgentOptions` 关键字段（`types.py:1578`）

| 类别 | 字段 | 说明 |
|---|---|---|
| 工具 | `tools` / `allowed_tools` / `disallowed_tools` | 控制可用工具集 |
| 提示词 | `system_prompt` | `str` / `{"type":"preset","preset":"claude_code","append":...}` / `{"type":"file","path":...}` |
| MCP | `mcp_servers` | dict，可同时混用 stdio / SSE / HTTP / sdk in-process |
| MCP 隔离 | `strict_mcp_config: bool` | True 时只用本配置，忽略项目/用户/全局 MCP |
| 权限模式 | `permission_mode` | `default` / `acceptEdits` / `plan` / `bypassPermissions` / `dontAsk` / `auto` |
| 权限回调 | `can_use_tool: CanUseTool` | `(name, input, ToolPermissionContext) -> PermissionResult`；**仅在 streaming 模式 + "ask" 决策时触发** |
| 权限路由 | `permission_prompt_tool_name` | 把 permission 请求路由到指定 MCP 工具 |
| 会话 | `continue_conversation` / `resume` / `session_id` / `fork_session` | 续接、恢复、分叉会话 |
| 持久化 | `session_store: SessionStore` | Protocol，自定义外部 transcript 存储；`session_store_flush: 'batched' | 'eager'` |
| 限额 | `max_turns` / `max_budget_usd` / `task_budget` | 转 / USD / API token 预算 |
| 思考 | `max_thinking_tokens` (deprecate) / `thinking` / `effort` | `effort` = `low | medium | high | xhigh | max` |
| 文件 | `cwd` / `add_dirs` | 工作目录 + 额外可访问目录 |
| CLI | `cli_path` / `settings` / `env` / `extra_args` | 替换 CLI / 加载额外 settings / 环境变量 / 额外参数 |
| Hooks | `hooks: dict[HookEvent, list[HookMatcher]]` | **同一事件多个 matcher 并发派发**（不是顺序） |
| 子代理 | `agents: dict[str, AgentDefinition]` | 用代码定义可被 Agent tool 调用的子代理 |
| 技能 | `skills: list[str] | 'all'` | 启用哪些 skill（不需要额外加 `allowed_tools`） |
| 沙箱 | `sandbox: SandboxSettings` | fs / network / Unix socket 限制 |
| 插件 | `plugins: list[SdkPluginConfig]` | 加载本地插件（`{"type":"local","path":...}`） |
| 输出 | `output_format: {"type":"json_schema","schema":...}` | 结构化输出 schema |
| 文件 checkpoint | `enable_file_checkpointing: bool` | 启用后 `client.rewind_files(user_message_id)` 可回滚到指定 user 消息时的文件状态 |
| 流式 | `include_partial_messages: bool` | 让 `StreamEvent` 真正增量 emit |
| 事件 | `include_hook_events: bool` | Hook 生命周期事件以 `HookEventMessage` 形式进消息流 |
| 设置源 | `setting_sources: list['user' | 'project' | 'local']` | 加载哪些 settings 文件；`[]` = 隔离模式（不读 fs） |
| 用户 | `user: str` | 用户标识，会被 Langfuse 之类的 tracing 工具用 |
| 调试 | `stderr: Callable[[str], None]` | CLI stderr 回调（line 级，错误不会断流） |
| 缓冲 | `max_buffer_size: int` | 读 stdout 的最大字节缓冲 |

## 五、Hooks 详细

### 事件（`HookEvent` 联合类型）

```
PreToolUse            # 工具调用前（可改 input / 决定 allow/deny/ask/defer）
PostToolUse           # 工具调用后（可替换 output）
PostToolUseFailure    # 工具失败后
UserPromptSubmit      # 用户消息提交时
Stop                  # 主 agent 停时（可 continue_: False 强行停）
SubagentStop          # 子代理停时
PreCompact            # 上下文压缩前
Notification          # CLI 发通知时
SubagentStart         # 子代理启动时
PermissionRequest     # CLI 提权时
```

### 输出字段（`SyncHookJSONOutput` / `AsyncHookJSONOutput`）

| 字段 | 含义 |
|---|---|
| `continue_: bool` | 是否继续（默认 True）；False 时停 |
| `suppressOutput: bool` | 隐藏 transcript 模式的 stdout |
| `stopReason: str` | continue=False 时的停因 |
| `decision: 'block'` | 阻塞（仅 PreToolUse 之外的 hook 有效） |
| `systemMessage: str` | 显示给用户的系统消息 |
| `reason: str` | 给 Claude 的反馈 |
| `hookSpecificOutput` | 事件专属输出 |

### 事件专属输出（`hookSpecificOutput` 内）

- `PreToolUseHookSpecificOutput`
  - `permissionDecision: 'allow' | 'deny' | 'ask' | 'defer'`
  - `permissionDecisionReason: str`
  - `updatedInput: dict` —— 修改工具 input
  - `additionalContext: str`
- `PostToolUseHookSpecificOutput`
  - `additionalContext: str`
  - `updatedToolOutput: Any` —— **替换任何工具的输出**（含内置工具）
  - `updatedMCPToolOutput: Any`（仅 MCP 工具）
- `SubagentStartHookSpecificOutput`、`PermissionRequestHookSpecificOutput`、...

### Python 关键字转义

- `async` → `async_`
- `continue` → `continue_`
- SDK 自动转 wire 格式；用户写 Python 时用下划线版

### Hooks 派发顺序

- **同一事件多个 matcher 并发派发**（不是顺序）—— 设计 hook 时**不能假设前后依赖**
- 每个 hook 有 `timeout: float`（秒，默认 60）

## 六、自定义工具 = 进程内 MCP server

```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeAgentOptions, ClaudeSDKClient

@tool("greet", "Greet a user", {"name": str})
async def greet_user(args):
    return {"content": [{"type": "text", "text": f"Hello, {args['name']}!"}]}

server = create_sdk_mcp_server(name="my-tools", version="1.0.0", tools=[greet_user])

options = ClaudeAgentOptions(
    mcp_servers={"tools": server},
    allowed_tools=["mcp__tools__greet"],   # auto-approve；不加则被 can_use_tool 拦截
)

async with ClaudeSDKClient(options=options) as client:
    await client.query("Greet Alice")
    async for msg in client.receive_response():
        print(msg)
```

要点：

- 用 `mcp.types.ToolAnnotations` 控制 readOnly/destructive/openWorld
- input schema 可用 dict 或 TypedDict
- `Annotated[type, "description"]` 给参数加描述
- 进程内 MCP server **与 stdio MCP 行为一致**（同协议），但**没有子进程** —— 0 IPC 开销、可直接访问 Python 应用状态
- 同一 session 可混用 SDK in-process + stdio/SSE/HTTP MCP server

## 七、Session / Subagent 管理 API

| 函数 | 用途 |
|---|---|
| `list_sessions(project_key)` | 列某个项目 key 下的所有会话（按 mtime 倒序） |
| `get_session_info(session_id)` | 取单个会话元信息（标题、git branch、cwd、tag、created_at、file_size） |
| `get_session_messages(session_id)` | 读 transcript（仅 user/assistant） |
| `list_subagents(project_key)` | 列出某个项目下所有子代理 |
| `get_subagent_messages(session_id, agent_id)` | 读子代理 transcript |
| `rename_session` / `tag_session` / `delete_session` / `fork_session` | 改 / 标 / 删 / 分叉 |

**`SessionStore` Protocol**（自定义外部存储）：

```python
class SessionStore(Protocol):
    async def append(self, key: SessionKey, entries: list[SessionStoreEntry]) -> None: ...
    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None: ...
    # 可选：list_sessions / list_session_summaries / delete / list_subkeys
```

- 用 Protocol 鸭子类型；不必继承
- `append` 在 CLI 本地落盘**之后**被调（持久性已保证）
- 默认实现 raise `NotImplementedError`，sdk 通过 `hasattr` 探测

## 八、Client 控制能力

```python
async with ClaudeSDKClient(options=options) as client:
    await client.connect()              # 实际 spawn 子进程
    await client.query("...")            # 发消息
    async for msg in client.receive_response():   # 拿到下一条 ResultMessage 为止
        ...
    # 或
    async for msg in client.receive_messages():    # 持续流；不绑 ResultMessage
        ...

    # 控制能力
    await client.interrupt()             # 中断当前 turn
    server_info = await client.get_server_info()
    mcp_status  = await client.get_mcp_status()
    ctx_usage   = await client.get_context_usage()    # 按类别分桶的 token 用量
    await client.rewind_files(user_message_id)         # 需 enable_file_checkpointing=True
    await client.disconnect()
```

## 九、错误

`ClaudeSDKError` 基类：

- `CLIConnectionError` —— 连不上 CLI
- `CLINotFoundError(CLIConnectionError)` —— 找不到 `claude` 二进制（带 `cli_path` 信息）
- `ProcessError(message, exit_code, stderr)` —— CLI 进程失败
- `CLIJSONDecodeError(line, original_error)` —— 解析 JSON 失败
- `MessageParseError(message, data)` —— 解析消息失败

## 十、协议无关性 / 跟 ACP 的对比

| 维度 | ACP 路径（`invoke_acp_agent`） | SDK 路径（推荐） |
|---|---|---|
| 进程模型 | `npx` → Node 适配器 → JSON-RPC over stdio | Python 直接 spawn `claude` CLI → 内置 JSON 协议 |
| 状态 | 无状态，prompt → 等 → 返回整段 | 有状态，可 `query()` / `ClaudeSDKClient` |
| 工具调用 | `request_permission` 一次决策 | `can_use_tool` 异步回调 + `PreToolUse` hook + `PostToolUse` 改 output |
| 自定义工具 | 需另起 MCP server 进程 | `@tool` + `create_sdk_mcp_server` 进程内 |
| 流式 | 不流（`_CollectingClient` 收集整段） | 真流（`include_partial_messages=True`） |
| Sessions | 无 | `resume` / `fork_session` / `session_store` |
| 文件 checkpoint | 无 | `enable_file_checkpointing` + `rewind_files()` |
| 沙箱 | 依赖 CLI 自己的 `sandbox` 设置 | 同上，可编程控制 `SandboxSettings` |
| 错误 | 自定义 `FileNotFoundError` 提示 | 5 类 typed exception |
| Token 用量 | 看不到 | `get_context_usage()` 按类别分桶 |

**结论**：在 DeerFlow 同一个 gateway 里**两者可并存**（不互斥），但用户**每次调用只能选一条** —— 一个 run 里 `invoke_acp_agent` 走 ACP 适配器，另一个 run 里 `claude_code` 子代理走 SDK。

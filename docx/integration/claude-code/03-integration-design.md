# 集成设计：4 个方案 + 推荐 + 演进路径

> 日期：2026/06/06
> 配套文档：[`01-sdk-overview.md`](01-sdk-overview.md) · [`02-deerflow-architecture.md`](02-deerflow-architecture.md)
> 上一份前置实验：[`claude-agent-sdk-smoke-test-summary.md`](claude-agent-sdk-smoke-test-summary.md)

## 一、设计目标（重申）

把 `claude-agent-sdk` 嵌入到 DeerFlow，**真正用上** SDK 的：

1. **流式** —— lead agent 用户能**实时**看到 Claude Code 干什么（ACP 工具做不到）
2. **hooks** —— 工具调用前/后 Python 回调（`PreToolUse` / `PostToolUse`），统一接到 `GuardrailMiddleware` / `SandboxAuditMiddleware`
3. **in-process MCP 工具** —— 把 DeerFlow 沙箱工具包成 `@tool` 喂给 Claude Code，零 IPC
4. **sessions** —— `resume` / `fork_session` / `session_store`，让 Claude Code 会话可持久化、可回放
5. **can_use_tool** —— 异步 Python 回调精细控制权限
6. **结构化输出** —— `output_format` schema

## 二、4 个候选方案

### A. `invoke_claude_code` 工具（镜像 `invoke_acp_agent`）

```
lead agent ──> invoke_claude_code(agent, prompt) tool
                  └─ build ClaudeAgentOptions(cwd, model, allowed_tools, env)
                  └─ async for msg in query(prompt, options):
                         chunks.append(...)
                  └─ return "".join(chunks)
```

| 维度 | 评价 |
|---|---|
| 改动面 | +1 文件（`tools/builtins/invoke_claude_code_tool.py`），完全镜像 ACP 工具 |
| 价值 | **低** —— 跟 ACP 工具几乎等价，不能流式、不用 hooks、不用 in-process MCP |
| 风险 | 极低 |
| 跟现有架构契合 | 高（跟 ACP 一样的模式） |
| SDK 能力利用率 | **< 20 %** |
| 推荐 | ❌ 单独做没意义；可作 PR #1 PoC |

### B. SDK 驱动的子代理 `claude_code`（推荐）

```
lead agent ──> task_tool(task="...", subagent_type="claude_code")
                  └─ SubagentExecutor.execute(subagent_type="claude_code", ...)
                       └─ (NEW) build_claude_code_agent(config) → ClaudeSDKClient
                            └─ ClaudeAgentOptions(
                                  cwd=per_thread_workspace,
                                  mcp_servers={"deerflow": sdk_mcp_server(tools=[bash,read,...])},
                                  hooks={"PreToolUse": [...], "PostToolUse": [...]},
                                  can_use_tool=...,
                                  include_partial_messages=True,
                                  session_id=<mapped from thread_id>,
                              )
                            └─ async for msg in client.receive_messages():
                                  ├─ sdk → langchain messages → forward to bridge (SSE)
                                  ├─ hooks trigger DeerFlow GuardrailMiddleware / SandboxAuditMiddleware
                                  └─ on ResultMessage → break
                       └─ return final result to lead agent
```

| 维度 | 评价 |
|---|---|
| 改动面 | +`community/claude_code_agent/` 包；+`subagents/executor.py` 加新 type 分支；+`subagents_config.py` 加 `claude_code` 模板 |
| 价值 | **高** —— 真正用上 SDK 全部核心能力 |
| 风险 | 中（中间件统一、async context lifetime、错误恢复） |
| 跟现有架构契合 | **最高** —— 跟现有子代理系统一脉相承 |
| SDK 能力利用率 | **80–90 %** |
| 推荐 | ✅ **主路径** |

### C. 替换 lead agent 运行时（SDK 驱动 DeerFlow）

```
HTTP / SDK query → ClaudeSDKClient(...)
                      └─ mcp_servers={"deerflow": sdk_mcp_server(ALL DeerFlow tools)}
                      └─ mcp_servers={"channels": sdk_mcp_server(IM tools)}
                      └─ mcp_servers={"memory": sdk_mcp_server(memory tools)}
                      └─ hooks = wrap all 18 middlewares as Python callbacks
                      └─ system_prompt = full DeerFlow lead agent prompt
                      └─ as the runtime, no LangGraph at all
```

| 维度 | 评价 |
|---|---|
| 改动面 | **极大** —— 删 LangGraph 图、删 18 个中间件、删 StreamBridge、删 IM channel manager、删 skills 加载、删 token usage 透出…… |
| 价值 | 不确定（丧失多年沉淀的可观测性、限流、token 面板） |
| 风险 | **极高** —— 跟 m2 分支的 Gateway 模式工作直接冲突 |
| 跟现有架构契合 | 极低（侵入） |
| SDK 能力利用率 | ~50 %（被绕过的能力比用上的多） |
| 推荐 | ❌ **否决** |

### D. 独立 `/api/claude_code` 网关端点（类比 `dify/`）

```
POST /api/claude_code/sessions                    → start a ClaudeSDKClient
POST /api/claude_code/sessions/{sid}/messages     → stream via SSE
GET  /api/claude_code/sessions/{sid}/messages     → resume
```

| 维度 | 评价 |
|---|---|
| 改动面 | +`community/claude_code/router.py`（仿 `dify/router.py`），+`app/gateway/routers/claude_code.py` |
| 价值 | 中 —— 适合"Claude Code 桌面端"独立用法 |
| 风险 | 低 |
| 跟现有架构契合 | 中（跟 lead agent 完全脱钩） |
| SDK 能力利用率 | 中（受限端点） |
| 推荐 | ❌ 单独做没价值；可作 **加分项**（当 lead agent 也接好后，单独给前端用） |

## 三、推荐路径：B（子代理）+ A（PoC 起步）

**为什么是 B**：上面"推荐"列已经说过了。一句话：Claude Code 是完整 agent，DeerFlow 已经有完整子代理系统，天然契合。

**演进路径（3 个 PR）**：

```
PR #1 (PoC, ~1-2 天)                  PR #2 (正式, ~5-7 天)                PR #3 (加分, ~3-5 天)
─────────────────────                  ─────────────────────                ────────────────────
A 方案: invoke_claude_code 工具         B 方案: claude_code 子代理类型         流式 + 会话持久化
                                                                          
- 1 个新文件 (mirror ACP 工具)          - community/claude_code_agent/ 包    - include_partial_messages
- 测试能跑通简单 prompt                 - in-process MCP server              - thread_id ↔ session_id
                                       - hooks 接 Guardrail                 - transcript 镜像 runtime/events/store
                                       - error handling                     - rewind_files 暴露给 UI
                                       - pytest
```

**为什么这个顺序**：

- **PR #1 验证可行性** —— 用最小代码确认 SDK 真的能在 DeerFlow `m2` 分支里跑（虽然烟雾测试已验证 `cli_path`、但走完整 lead agent → tool → 收到结果 还需要再过一遍）
- **PR #2 是真正价值** —— 子代理路径解锁流式 + hooks + in-process MCP + sessions
- **PR #3 加分** —— 不阻塞主线；可以等生产环境用一段时间后再做

## 四、能力映射（SDK ↔ DeerFlow）

| SDK 能力 | DeerFlow 对位 | 接入点 |
|---|---|---|
| `ClaudeSDKClient` + `include_partial_messages` | 现有 `StreamBridge` 已能发 SSE 事件 | 子代理 worker 内：把 `AssistantMessage` 流重投到 `bridge.publish('messages', ...)` |
| `@tool` + `create_sdk_mcp_server` | DeerFlow 的 `BaseTool` 列表（bash、read、write、str_replace） | 子代理启动时构造 `sdk_mcp_server(tools=[...])` |
| `can_use_tool` 异步回调 | `GuardrailMiddleware` 鉴权 | hook 转调 Guardrail |
| `PreToolUse` hook | `SandboxAuditMiddleware` 审计 + Guardrail | hook 转调 |
| `PostToolUse` + `updatedToolOutput` | `ToolErrorHandlingMiddleware` 错误归一化 | hook 转调，可重写工具结果 |
| `sandbox: SandboxSettings` | `deerflow.sandbox.aio_sandbox` 容器 | **不重叠** —— SDK 在自己 cwd 里跑；DeerFlow 沙箱工具通过 in-process MCP 喂进来；sandbox 设置通常不传（让 SDK 用默认） |
| `session_id` / `resume` / `fork_session` | thread_id + LangGraph checkpointer | 映射 `session_id = "<thread>-<run>"`；transcript 镜像到 `runtime/events/store`（接 `MirrorErrorMessage` 错误处理） |
| `agents={}` | DeerFlow `SubagentConfig` | `claude_code` 子代理自己的 prompt/model/allowed_tools 直接传 `agents={}` |
| `skills` | DeerFlow `skills` 系统（`/mnt/skills/public/...`） | 子代理启动时同步 DeerFlow 已启用的 skill 名，传 `skills=<names>` |
| `get_context_usage()` | `TokenUsageMiddleware` 面板 | 子代理结束 / 周期 tick 时调一次，写回 `bridge.publish('token_usage', ...)` |
| `rewind_files()` | 无 | **加分项** —— UI 加个"撤销到某条消息" |
| `output_format` | 无 | **加分项** —— 让 Claude Code 返回结构化数据（测试报告、代码 diff 等） |
| `get_mcp_status()` | DeerFlow MCP 管理 UI（`/api/mcp/...`） | **加分项** —— 暴露 Claude Code 视角的 MCP 状态 |

## 五、`claude_code` 子代理具体设计要点

### 5.1 子代理工厂

```python
# community/claude_code_agent/factory.py
def build_claude_code_agent(config: RunnableConfig) -> ClaudeSDKClient:
    app_config = get_app_config()
    subagent_cfg = get_subagents_config().claude_code

    options = ClaudeAgentOptions(
        # 模型
        model=subagent_cfg.model,                       # None → inherit（这里不写，让 SDK 默认）
        # 工作目录
        cwd=_resolve_claude_cwd(config),                # per-thread workspace
        # 系统提示词
        system_prompt={"type": "preset", "preset": "claude_code",
                       "append": subagent_cfg.system_prompt_append},
        # 工具
        allowed_tools=subagent_cfg.allowed_tools,       # e.g. ["Read", "Edit", "Bash", "Grep", "Glob", "mcp__deerflow__*"]
        # 沙箱
        sandbox={"enabled": True, "autoAllowBashIfSandboxed": True},
        # In-process MCP：暴露 DeerFlow 沙箱工具
        mcp_servers={
            "deerflow": create_sdk_mcp_server(
                name="deerflow",
                version="1.0.0",
                tools=[bash_tool, read_file_tool, write_file_tool, str_replace_tool, ls_tool],
            ),
        },
        strict_mcp_config=True,
        # Hooks
        hooks={
            "PreToolUse":   [HookMatcher(matcher=None, hooks=[deerflow_pretooluse_hook])],
            "PostToolUse":  [HookMatcher(matcher=None, hooks=[deerflow_posttooluse_hook])],
            "Stop":         [HookMatcher(matcher=None, hooks=[deerflow_stop_hook])],
        },
        # 权限
        can_use_tool=deerflow_can_use_tool,
        # 会话
        session_id=_make_session_id(config),
        # 流式
        include_partial_messages=True,
        include_hook_events=True,
        # 环境
        env={"ANTHROPIC_API_KEY": app_config.claude_api_key, "DEER_FLOW_RUN_ID": record.run_id},
        # 限额
        max_turns=subagent_cfg.max_turns,
        max_budget_usd=subagent_cfg.max_budget_usd,
        # Skills
        skills=_enabled_deerflow_skill_names(app_config),
    )
    return ClaudeSDKClient(options=options)
```

### 5.2 子代理执行（`SubagentExecutor.execute` 新分支）

```python
# subagents/executor.py
async def _execute_claude_code(self, ctx: RunContext, subagent_cfg: SubagentConfig, prompt: str):
    client = build_claude_code_agent(self._config)
    # 必须在同一 async context 内用完（SDK 硬限制）
    async with client:
        await client.connect(prompt)
        # 子代理跑：转发 SDK 消息到 DeerFlow bridge（实现前端实时可见）
        async for msg in client.receive_messages():
            translated = _translate_sdk_message_to_langchain(msg)
            if translated is not None:
                self._bridge.publish(self._run_id, "messages", translated)
            if isinstance(msg, ResultMessage):
                return _extract_final_text(msg)
```

**关键设计点**：

- 子代理**始终在一个独立 event loop 线程**（已有）—— 满足 SDK 的"同 async context"硬限制
- `client.connect(prompt=prompt_string)` 一次性模式；不需要多轮（lead agent 委派是单回合）
- 把 SDK 消息实时投到 `bridge` —— 前端能看到 Claude Code 的思考 + 工具调用 + 输出
- `_translate_sdk_message_to_langchain`：把 `AssistantMessage` (TextBlock) → `AIMessage(chunk=...)` 流式 token

### 5.3 错误处理

| SDK 错误 | 处理 |
|---|---|
| `CLINotFoundError` | 上报"请安装 `claude` CLI" + 给出离线安装文档链接 |
| `ProcessError(exit_code, stderr)` | 上报子代理异常退出 + `ResultMessage.errors` 列表 |
| `CLIConnectionError` | 重试 1 次；仍失败则 `bridge.publish_end(error="...")` |
| `CLIJSONDecodeError` | 记录日志 + 继续（不致命） |
| SDK `ResultMessage.is_error` | 上报给 lead agent，subagent result 标 failure |

### 5.4 测试

- **单元**（`tests/community/test_claude_code_agent.py`）：
  - `build_claude_code_agent` 在 mock 模式下构造 options 不真起 CLI
  - `_translate_sdk_message_to_langchain` 各种 SDK 消息类型 → LangChain 类型
  - 错误恢复路径（CLINotFoundError / ProcessError）
  - 跟 ACP 工具的对比测试（确保两条路径并存）
- **集成**（`tests/integration/test_claude_code_subagent_e2e.py`）：
  - 跑 lead agent → task_tool → claude_code 子代理 → 收结果
  - 验证消息真的流到 bridge（用 mock bridge 计数）
  - 验证 hooks 真的被调用
  - 验证 `session_id` / `cwd` / `mcp_servers` 配置正确

### 5.5 配置（`config.example.yaml` 新增段）

```yaml
# ============================================================================
# Claude Code SDK Subagent
# ============================================================================
# Mirror of `claude_code` ACP config, but uses the official Python SDK
# directly (no Node / npx). Prefer SDK over ACP for new deployments.

# claude_code_sdk:
#   enabled: true
#   # Optional: override CLI path. Defaults to bundled wheel CLI.
#   cli_path: /usr/local/bin/claude
#   # Permission mode forwarded to ClaudeAgentOptions.permission_mode
#   permission_mode: bypassPermissions
#   # Auto-approve every tool (replaces can_use_tool prompt)
#   auto_approve_tools: true
#   # Tool whitelist forwarded to ClaudeAgentOptions.allowed_tools
#   # Use "mcp__deerflow__*" to expose DeerFlow sandbox tools via in-process MCP server
#   allowed_tools:
#     - Read
#     - Edit
#     - Write
#     - Bash
#     - Glob
#     - Grep
#     - mcp__deerflow__bash
#     - mcp__deerflow__read_file
#     - mcp__deerflow__write_file
#     - mcp__deerflow__str_replace
#   # Model hint (None = inherit lead agent model)
#   model: claude-sonnet-4-5
#   # Limits
#   max_turns: 50
#   max_budget_usd: 5.0
#   # Append to the default Claude Code system prompt
#   system_prompt_append: |
#     You are the Claude Code subagent of a DeerFlow lead agent.
#     You have access to DeerFlow sandbox tools via mcp__deerflow__* prefix.
#     Always explain your final answer with clear file paths.
#   # Session: thread_id ↔ session_id mapping
#   # session_id_mode: per_thread  # per_thread | per_run | fixed
#   # Sandbox settings forwarded to ClaudeAgentOptions.sandbox
#   sandbox:
#     enabled: true
#     auto_allow_bash_if_sandboxed: true
```

## 六、跟 ACP 路径的关系

| 维度 | ACP 路径 | SDK 路径 |
|---|---|---|
| 配置文件 | `acp_agents.claude_code` | `claude_code_sdk`（新段） |
| 工具入口 | `invoke_acp_agent(agent="claude_code", ...)` | `task(subagent_type="claude_code", ...)`（透传 `task_tool`） |
| 子代理名字 | 无 | `claude_code` |
| 落地模块 | `tools/builtins/invoke_acp_agent_tool.py` | `community/claude_code_agent/`（仿 `aio_sandbox/`） + `subagents/executor.py` 新分支 |
| 跟谁互斥 | 同 run 内**可并存**但**同调用选一条** | 同上 |
| 长期 | 可保留作为 fallback | 主路径 |

**建议**：ACP 路径**保留**（已经实现且能用），SDK 路径作为新主路径；不在 PR #1 删 ACP。

## 七、镜像 / 部署要求

烟雾测试已确认（见 `claude-agent-sdk-smoke-test-summary.md`）：

- **gateway 镜像最小需求**：
  - `python:3.12` 基础镜像
  - `pip install claude-agent-sdk`（wheel 自带的 CLI 不重要，**`cli_path` 改用系统 `claude` 不会 spawn 它**）
  - `npm install -g @anthropic-ai/claude-code@<pinned-version>`（实际用的 CLI）
  - `ANTHROPIC_API_KEY` 环境变量
  - 构建时把 `claude` 绝对路径写进镜像
- **CI**：跑测试时如未装 `claude` CLI，**自动跳过**集成测试（跟现有 ACP 工具测试的 skip 模式一致）

## 八、风险登记表

| 风险 | 等级 | 缓解 |
|---|---|---|
| SDK hard 限制（"同 async context"）违反 | 高 | 把 SDK client 完全包在子代理独立 event loop 线程里；子代理开始时 `client.connect()`，结束时 `client.disconnect()`，生命周期严格对齐 |
| SDK 子代理跟 lead agent 上下文不同步 | 中 | `session_id` 用 `<thread_id>-<run_id>` 映射；transcript 镜像到 DeerFlow `runtime/events/store` |
| MCP server 工具调用错误 | 中 | `ToolErrorHandlingMiddleware` 风格的 PostToolUse hook 兜底 |
| 用户体验：前端"看不到" Claude Code 干活 | 中（已解决） | `include_partial_messages=True` + 翻译 `AssistantMessage` 到 `AIMessage(chunk=...)` 流到 bridge |
| 长任务超过 15 分钟 | 中 | 子代理已有 15 分钟 timeout；可单独配置 subagent 的 timeout |
| 并发子代理数 | 低 | `SubagentLimitMiddleware` 已限 3；SDK 子代理算在内 |
| 离线 / 局域网环境没有 `claude` CLI | 中 | `CLINotFoundError` 时给清晰错误 + 引导装 |
| 跟 ACP 子代理选错的歧义 | 低 | 工具名 / 子代理名都加前缀 `claude_code` / `claude_code_sdk`；config 段独立 |
| Token 计量不准 | 中 | `get_context_usage()` 周期 tick 写回 bridge；不依赖 SDK 内部 |
| Harness 边界（`deerflow.*` 不得 import `app.*`） | 低 | 新代码全在 `deerflow.community.claude_code_agent` 下 |

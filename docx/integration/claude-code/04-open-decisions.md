# 待拍板决策点

> 推荐集成路径已确定（见 [`03-integration-design.md`](03-integration-design.md)），但落地前还有 6 个具体技术点需要拍板。一次问一个，**先做 PoC 边做边收窄**也行。
>
> 配套阅读：[`05-scenarios-and-prompts.md`](05-scenarios-and-prompts.md) —— 4 种 mode 下 `claude_code` 子代理的可用性 + 提示词模板。

## 决策 0（前置）：Mode 约束 —— `claude_code` 子代理**只在 ultra 模式可用**

**问题**：flash / thinking / pro / ultra 这 4 种 mode 跟 `subagent_enabled` 的映射是什么？`claude_code` 子代理在哪些 mode 下能被 lead agent 选中？

**事实**（来源：`frontend/src/core/threads/hooks.ts:593-608`）：

```ts
context: {
  thinking_enabled: context.mode !== "flash",
  is_plan_mode:     context.mode === "pro" || context.mode === "ultra",
  subagent_enabled: context.mode === "ultra",      // ← 关键
  reasoning_effort: context.mode === "ultra" ? "high"
                  : context.mode === "pro"   ? "medium"
                  : context.mode === "thinking" ? "low"
                  : undefined,
}
```

| Mode | thinking | plan_mode | **subagent_enabled** | reasoning_effort | 设计目标（来源 `frontend/src/core/i18n/locales/zh-CN.ts:85-95`）|
|---|---|---|---|---|---|
| `flash`（闪速） | ❌ | ❌ | **❌ false** | undefined | 快速且高效，**可能不够精准** |
| `thinking`（思考） | ✅ | ❌ | **❌ false** | low | 思考后再行动，时间与准确性平衡 |
| `pro` | ✅ | ✅ | **❌ false** | medium | 思考、计划再执行，**单 agent** |
| `ultra` | ✅ | ✅ | **✅ true** | high | 继承 Pro，**可调用子代理分工**，适合复杂多步骤任务 |

**结论**：

- **闪速（flash）模式不能调用任何 subagent**——`task` 工具根本不会注入给 lead agent。SDK 子代理**跟 flash 模式天然不冲突**
- **`claude_code` 子代理只在 ultra 模式可被 lead agent 选中**——这跟它的设计定位（"专业编码 agent"）一致：flash/thinking/pro 都强调"快"或"准"，而 claude_code 是个**会跑 bash/编译/测试**的 agent，本身就重
- lead agent 的提示词中是否提到"可以用 `claude_code` 子代理处理编码任务"——**只在 `subagent_enabled=True` 时才会被拼到系统提示里**（见 `agents/lead_agent/prompt.py:_build_subagent_section`）
- 用户写的提示词还是自然语言任务；**不是用户写专门给 claude_code 的提示词**，是 lead agent 在 ultra 模式下内部决定要不要 `task(subagent_type="claude_code", ...)`，再把"用户原始任务 + lead agent 觉得需要的上下文"作为 prompt 传给子代理

**对 PR #1（PoC `invoke_claude_code` 工具）的影响**：

- `invoke_claude_code` 工具是直接给 lead agent 用的工具，**不依赖 `subagent_enabled` 开关**——所以 flash 模式下 lead agent 也能调它（如果它被注入的话）。这是 PoC 阶段"快速验证 SDK 能跑"的好选择
- 但**生产环境**只让 `claude_code` 在 ultra 模式出现更合理

**待用户决定**：

- `claude_code` 子代理**是否只在 ultra 模式注册**？（推荐：✅ 只在 ultra）
- `invoke_claude_code` 工具（PoC）是否在所有 mode 都注入？（推荐：❌ 只在 ultra / pro 注入；flash/thinking 屏蔽）

## 决策 1：演进路径

**问题**：先做 PR #1（PoC `invoke_claude_code` 工具）还是直接做 PR #2（`claude_code` 子代理）？

| 选项 | 优点 | 缺点 |
|---|---|---|
| **先 #1 后 #2** | 渐进式验证；每次 PR 风险小；容易回滚 | 写两遍"调用 SDK"的代码 |
| **直接 #2** | 一次到位；总代码量更少 | 第一次 PR 风险大；难回滚 |
| **只做 #1** | 最小投入；如果之后发现 SDK 不合适就停 | 浪费 SDK 大部分能力 |

**建议**：先 #1 后 #2（详见 `03-integration-design.md` 第三段）

**待用户决定**：✅ / ❌ / 改

## 决策 2：Claude Code 跑哪个模型

**问题**：子代理用哪个 Claude 模型？要不要跟 lead agent 一致？

| 选项 | 优点 | 缺点 |
|---|---|---|
| **`model: None`（不传，SDK 默认）** | 跟随 CLI 默认（`claude-sonnet-4-5` 或更新版本） | 跟 DeerFlow 配置脱钩；不同 CLI 版本默认可能不同 |
| **从 DeerFlow `app_config.models` 解析** | 跟 lead agent 一致；用 DeerFlow 渠道凭证 | 需映射 DeerFlow 模型名到 Claude 模型 ID |
| **独立 `claude_code_sdk.model` 配置字段** | 配置最灵活 | 多一处配置要维护 |
| **强制 `claude-sonnet-4-5`** | 简单 | 跟 DeerFlow 现有 `claude-3-5-sonnet-latest` 这种命名冲突 |

**待用户决定**：

- 是否让 Claude Code 子代理必须跑 Claude 模型（vs. 允许其他 provider）？
- 命名上，DeerFlow 现有 `claude-sonnet-4-5` 之类的 ID 跟 SDK 的 ID 一样吗？

## 决策 3：工具集 —— 让 Claude Code 用什么

**问题**：Claude Code 子代理能调哪些工具？把哪些 DeerFlow 工具通过 in-process MCP 喂进去？

| 工具 | 来源 | 给 Claude Code？ |
|---|---|---|
| `Read` `Write` `Edit` `Bash` `Grep` `Glob` `NotebookEdit` `WebFetch` `WebSearch` | SDK 内置 | ✅ 默认给 |
| `mcp__deerflow__bash` | 包装 `deerflow.sandbox.tools:bash_tool` | ✅ 推荐给（统一审计 / 路径翻译） |
| `mcp__deerflow__read_file` | 包装 `read_file_tool` | ✅ 推荐给 |
| `mcp__deerflow__write_file` | 包装 `write_file_tool` | ✅ 推荐给 |
| `mcp__deerflow__str_replace` | 包装 `str_replace_tool` | ✅ 推荐给 |
| `mcp__deerflow__ls` | 包装 `ls_tool` | ⚠️ 可选 |
| `mcp__deerflow__ask_clarification` | 包装 `ask_clarification` | ❌ 不给（子代理不该问 lead agent 的问题） |
| `mcp__deerflow__view_image` | 包装 `view_image` | ⚠️ 可选（仅当 lead agent 模型支持 vision） |
| `mcp__deerflow__task` | 包装 `task_tool` | ❌ 不给（避免子代理无限递归） |
| `mcp__deerflow__invoke_acp_agent` | 包装 ACP 工具 | ❌ 不给（避免死循环 / 跨路径干扰） |
| `mcp__deerflow__present_files` | 包装 `present_files` | ❌ 不给（前端展示是 lead agent 的事） |

**子代理的工作目录 `cwd`**：

| 选项 | 说明 |
|---|---|
| **per-thread workspace** | `cwd = /mnt/user-data/{workspace}` —— 子代理在沙箱里改用户工作区文件 |
| **per-run scratch** | `cwd = /tmp/claude-code/<run_id>` —— 子代理在临时目录跑，结果写进 DeerFlow artifact 存储 |
| **acp-workspace 类比** | 仿 `invoke_acp_agent_tool._get_work_dir(thread_id)`，独立 `/mnt/claude-code-workspace/` |

**待用户决定**：

- cwd 用哪种？acp-workspace 类比可能最稳（跟 ACP 路径对齐）
- 哪些 DeerFlow 工具要给 Claude Code（最小集 + 哪个推荐集）？

## 决策 4：权限模型

**问题**：Claude Code 工具调用怎么鉴权？接 DeerFlow `GuardrailMiddleware` 吗？

| 维度 | 选项 | 说明 |
|---|---|---|
| `permission_mode` | `bypassPermissions` | 全自动；最快；适合"信任 Claude Code 干编码活"的场景 |
| | `default` | 走 SDK 自带规则 |
| | `acceptEdits` | 编辑类自动；其他走 SDK 规则 |
| | `plan` | 不允许执行工具；只产出 plan |
| | `auto` | SDK 用分类器自动决定 |
| `can_use_tool` 回调 | 接 DeerFlow Guardrail | 工具调用过来时调 `GuardrailMiddleware.authorize()`，返回 `PermissionResultAllow` / `PermissionResultDeny` |
| | 接 DeerFlow SandboxAudit | 工具调用过来时记 audit log |
| | 完全独立 | SDK 自己管（默认规则） |
| `PreToolUse` hook | 强制 deny 高危命令 | 例：`rm -rf /`、`curl | bash` 等 |
| | 改 input | 例：自动给 `Bash` 命令加 `--no-pager` |
| | 加 additionalContext | 例：给 `Read` 工具调用附 DeerFlow skill 提示 |
| `PostToolUse` hook | 改 output | 例：把 `Bash` 输出的 ANSI 颜色去掉 |
| | 加 systemMessage | 例：跑 `npm install` 后告诉 lead agent "已装 X 个包" |

**建议组合**（待用户确认）：

- `permission_mode: bypassPermissions`（沙箱已经隔离了，编码任务不需要人审批）
- `can_use_tool` 回调 → 转调 DeerFlow `GuardrailMiddleware.authorize()`
- `PreToolUse` hook → 强制 deny 高危命令 + 改 input + 加 additionalContext
- `PostToolUse` hook → 改 output 去掉 ANSI + 加 systemMessage

**待用户决定**：✅ / ❌ / 改

## 决策 5：会话持久化

**问题**：`session_id` / `resume` / `fork_session` / `session_store` 用哪个组合？

| 选项 | 适用场景 | 复杂度 |
|---|---|---|
| **不开 session**（`session_id=None`，每次新） | 简单；每次子代理是独立任务 | 低 |
| **`session_id = f"<thread_id>-<run_id>"`** | 同一个 run 里多次 `task(claude_code, ...)` 共享 | 中 |
| **加 `session_store`** —— transcript 镜像到 DeerFlow `runtime/events/store` | 跨进程可恢复；前端可回看 | 高 |
| **`fork_session=True` + `resume`** | lead agent 委派多步任务时复用 | 高 |

**镜像会话 transcript 到 `runtime/events/store`** 的实现思路：

```python
# community/claude_code_agent/session_mirror.py
class DeerFlowSessionStore:
    def __init__(self, event_store: EventStore, run_id: str, thread_id: str):
        self._event_store = event_store
        self._run_id = run_id
        self._thread_id = thread_id

    async def append(self, key, entries):
        for e in entries:
            await self._event_store.append(
                thread_id=self._thread_id,
                run_id=self._run_id,
                event_type="claude_code_transcript",
                data={"sdk_session_id": key["session_id"], "entry": e},
            )

    async def load(self, key):
        # 倒着查
        return await self._event_store.load_claude_transcript(
            thread_id=self._thread_id, sdk_session_id=key["session_id"]
        )
```

**待用户决定**：

- PoC 阶段要不要开 session？
- 长期是否要做 `session_store` 镜像？
- 是否需要 `fork_session`（lead agent 多步委派）？

## 决策 6：前端可见性 / 实时流

**问题**：怎么让前端用户看到 Claude Code 真的在干活（不仅是"Claude Code 正在跑"）？

| 选项 | 复杂度 | 效果 |
|---|---|---|
| **不流** —— 跟 ACP 工具一样，子代理结束才返回 | 极低 | 用户只看到"Claude Code 跑完了，结果：..." |
| **流** —— `include_partial_messages=True` + 翻译到 LangChain `AIMessage(chunk=...)` 投到 bridge | 中 | 前端能看到 Claude Code 的思考 + 工具调用 + 输出 |
| **流 + 工具调用高亮** —— 翻译 `ToolUseBlock` 到 lead agent 工具调用同款 UI | 中 | 跟现有工具调用样式一致 |
| **流 + 子代理专属 UI** —— 新建 `ClaudeCodeSubagentCard` 组件 | 高 | 最炫但工程量大 |

**实现思路（流式）**：

```python
# community/claude_code_agent/bridge_bridge.py
def sdk_message_to_langchain_chunk(msg: Message) -> list[AIMessage | ToolMessage] | None:
    if isinstance(msg, AssistantMessage):
        chunks = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                chunks.append(AIMessageChunk(content=block.text))
            elif isinstance(block, ThinkingBlock):
                chunks.append(AIMessageChunk(content=f"<thinking>{block.thinking}</thinking>"))
            elif isinstance(block, ToolUseBlock):
                chunks.append(AIMessageChunk(
                    content="",
                    tool_call_chunks=[ToolCallChunk(
                        id=block.id, name=block.name, args=json.dumps(block.input), index=0
                    )],
                ))
        return chunks
    elif isinstance(msg, UserMessage):
        # tool result
        ...
    return None
```

**待用户决定**：

- PoC 阶段做不流（最简）？
- 正式版做"流"（中复杂度）？
- 是否要做"子代理专属 UI"（高复杂度）？

---

## 拍板顺序建议

```
1. 决策 1（演进路径） — 必拍
2. 决策 2（模型）   — 必拍
3. 决策 3（工具集 + cwd）— 必拍
4. 决策 4（权限）   — 必拍
5. 决策 5（持久化） — 可推迟到 PR #3
6. 决策 6（流式）   — 可推迟到 PR #3
```

PR #1 只需要拍 1–4；5–6 在 PR #3 拍。

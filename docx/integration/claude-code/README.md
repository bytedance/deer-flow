# Claude Code × DeerFlow 集成设计

> 日期：2026/06/06
> 适用：deer-flow `m2` 分支
> 状态：设计阶段 — 烟雾测试已通过，正式设计待拍板
> 相关：
> - `config.example.yaml:739` `@agentclientprotocol/claude-agent-acp`（已存在的 ACP 路径）
> - `claude-agent-sdk-smoke-test-summary.md`（已完成的 SDK 烟雾测试）
> - `deerflow-claude-code-offline-install-guide.md`（离线 `claude` CLI 安装流程）

---

## 一、目标

把 `claude-agent-sdk`（Anthropic 官方 Python SDK）嵌入到 DeerFlow，让 lead agent 可以把**编码 / 重构 / 调试 / 跑 bash** 这类工作委派给 Claude Code —— 不只是当个 prompt 透传工具，而是**真正用上 SDK 的流式、hooks、in-process MCP 工具、sessions** 这些 ACP 路径给不出的能力。

---

## 二、已有什么

| 文件 / 能力 | 状态 | 说明 |
|---|---|---|
| ACP 路径 `invoke_acp_agent` 工具 | ✅ 已实现 | 走 `npx @agentclientprotocol/claude-agent-acp` 子进程 + JSON-RPC；返回整段文本 |
| ACP 路径配置段 `acp_agents` | ✅ 已实现 | `config.example.yaml:735-756` |
| `claude-agent-sdk` 烟雾测试 | ✅ 已通过 | 见 `claude-agent-sdk-smoke-test-summary.md`；验证了 `cli_path` 真的能切换 CLI 版本 |
| `claude-agent-sdk` wheel 内置 CLI | ✅ 已验证**不会**被实际使用 | `cli_path` 指向系统 `claude` 时，wheel 内置的 `claude.exe` 不被 spawn |
| 离线镜像最小需求 | ✅ 已确认 | 只需 `claude` 二进制 + `claude-agent-sdk` wheel + `ANTHROPIC_API_KEY` |
| SDK ↔ ACP 在 gateway 内**互斥** | ✅ 结论成立 | 二选一：要么 ACP 适配器，要么 Python SDK 嵌入 |

---

## 三、推荐路径

**SDK 驱动的子代理 `claude_code`（B 方案）** — 详见 [`03-integration-design.md`](03-integration-design.md)

为什么是子代理而不是工具/直接替换运行时：

1. Claude Code 是**完整 agent**，不是单个工具
2. DeerFlow 已经有完整的子代理子系统（`SubagentExecutor`、独立事件循环、限流、超时、结果回收）
3. SDK 的 `agents={}` 配置和 DeerFlow 的 `SubagentConfig` **几乎一对一对位**
4. 子代理在**独立事件循环线程**上跑，天然满足 SDK 的"同 async context"硬限制
5. lead agent 通过 `task_tool` 委派时，能把 SDK 的 `AssistantMessage` 流重投到现有 `StreamBridge` → **SSE 实时展示**
6. SDK 的 `PreToolUse` hook 可接到 `GuardrailMiddleware` / `SandboxAuditMiddleware` → **统一审计**
7. DeerFlow 的 sandbox 工具可包成**进程内 MCP server** 喂给 Claude Code（零 IPC 开销）

**演进路径（3 个 PR）**

| PR | 内容 | 风险 |
|---|---|---|
| **#1 PoC** | `invoke_claude_code` 工具（10 行包装 `query()`） | 极低 |
| **#2 正式** | 新增 `claude_code` 子代理类型 + in-process MCP server 暴露 DeerFlow 沙箱工具 + hooks 接 Guardrail | 中 |
| **#3 加分** | `include_partial_messages` 流到 `StreamBridge`；`thread_id ↔ session_id` 映射；transcript 镜像到 `runtime/events/store` | 中 |

---

## 四、文档索引

| 文档 | 主题 | 谁应该先读 |
|---|---|---|
| [`01-sdk-overview.md`](01-sdk-overview.md) | `claude-agent-sdk` Python 包的 API、类型、消息、hooks、工具、会话 — 集成设计的事实基础 | 第一次接触 SDK 的人 |
| [`02-deerflow-architecture.md`](02-deerflow-architecture.md) | DeerFlow 关键模块速查（lead agent、subagent、StreamBridge、ACP、sandbox、Gateway、IM 通道） | 需要回忆项目结构的人 |
| [`03-integration-design.md`](03-integration-design.md) | 4 个集成候选方案 + 取舍 + 推荐 + 演进路径 | 做决策的人 |
| [`04-open-decisions.md`](04-open-decisions.md) | 集成设计尚未拍板的具体技术点（mode 约束、模型、工具集、权限、持久化、workspace 路径） | 即将写代码的人 |
| [`05-scenarios-and-prompts.md`](05-scenarios-and-prompts.md) | `claude_code` 子代理在 4 种 mode 下的可用性、跟 general-purpose/bash 的分工、适用/不适用场景、提示词模板、lead agent 调度建议 | 写 lead agent 系统提示 / 写子代理 prompt 的人 |
| [`claude-agent-sdk-smoke-test-summary.md`](claude-agent-sdk-smoke-test-summary.md) | SDK 烟雾测试运行记录（`cli_path` 验证 + 版本对比） | 关心"SDK 真的能跑吗"的人 |
| [`claude-agent-sdk-smoke-test.py`](claude-agent-sdk-smoke-test.py) | 烟雾测试脚本 | 想自己跑一遍的人 |

---

## 五、下一步

1. 阅读 [`04-open-decisions.md`](04-open-decisions.md) 里的 6 个决策点（注意先看决策 0：mode 约束）
2. 拍板后，按推荐路径开 PR #1（PoC）—— 一个 PR = 一个新工具 `invoke_claude_code`（镜像 `invoke_acp_agent`）
3. PoC 跑通后，按 PR #2 把子代理路径走通（参考 [`05-scenarios-and-prompts.md`](05-scenarios-and-prompts.md) 写 lead agent 提示词 + 子代理配置）
4. 同步写 `OpenSpec` 提案（按 `CLAUDE.md` 工作流）+ superpowers `writing-plans` 落地实现计划

# GuardrailRequest 运行时归因上下文补充

## 概述

为 `GuardrailRequest` 补充三个可选运行时归因字段 — `user_id`、`run_id`、`tool_call_id` — 使可插拔 `GuardrailProvider` 在做工具调用决策或记录日志时，能访问 DeerFlow 运行时已经掌握的调用上下文。

## 背景

DeerFlow 已通过 `GuardrailMiddleware` + 插拔式 `GuardrailProvider` 实现了工具调用前的 allow/deny 授权能力。

当前 `GuardrailDecision` 已支持表达 allow/deny、原因、policy_id 和扩展 metadata。缺口在于 `GuardrailRequest` 携带的信息仅限于 `tool_name` 和 `tool_input`，缺少调用方的运行时身份和上下文 —— 这些信息 provider 自己无法可靠推断。

且在可预见的路线中，DeerFlow 正在增强多用户支持（SSO/OIDC #3506）、MCP 工具审计（#3322 提及 per-user credential 隔离）、以及企业权限管理（Q2 RoadMap #1669）。在这些场景下，guardrail provider 需要更多上下文才能做出有意义的决策。

## 改动范围

三个文件中、总计约 20 行新增代码：

- `guardrails/provider.py` — 数据类扩字段
- `guardrails/middleware.py` — `_build_request()` 读取并填充
- `tests/test_guardrail_middleware.py` — 新增测试用例

## 设计

### GuardrailRequest 新字段

```python
@dataclass
class GuardrailRequest:
    tool_name: str
    tool_input: dict[str, Any]
    agent_id: str | None = None
    thread_id: str | None = None          # 已存在但从未填充，本次补上
    is_subagent: bool = False
    timestamp: str = ""

    # 新增：运行时归因（provider 无法自行推断）
    user_id: str | None = None
    run_id: str | None = None
    tool_call_id: str | None = None
```

所有字段为 optional。现有 `GuardrailDecision` 不做任何变化。

### 字段来源

每个字段在 `_build_request()` 中从明确位置读取，不引入新的控制面：

| 字段 | 来源 | 兜底 |
|------|------|------|
| `user_id` | `request.runtime.context["user_id"]` | 运行时无 context 时为 `None` |
| `run_id` | `request.runtime.context["run_id"]` | 同上 |
| `tool_call_id` | `request.tool_call.get("id")` | `tool_call` 无 id 时为 `None` |
| `thread_id` | `request.runtime.context["thread_id"]` | 同上（修正：当前虽已定义但从未从 context 填充） |

`runtime.context` 由 `_build_runtime_context()`（`runtime/runs/worker.py`）自动写入，包含 `thread_id` 和 `run_id`。`user_id` 由网关的 `inject_authenticated_user_context()`（`app/gateway/services.py`）在认证后写入。因此 guardrail middleware 不需要自行获取任何新数据，只需读取已有信息。

## 各字段收益分析

### user_id：收益高，在 guardrail 核心边界内

| 场景 | 没有 user_id | 有 user_id |
|------|-------------|-----------|
| Per-user 授权（A 可用 bash、B 不行） | provider 无法区分调用者 | 直接基于 `request.user_id` 做策略 |
| 多租户审计 + SSO | 审计日志无法关联到具体人 | 每个决策可记录用户身份 |
| MCP per-user 隔离（#3322） | provider 无法将身份传递给下游 | 可将 `request.user_id` 注入 MCP 调用上下文 |

`user_id` 是 guardrail provider 做授权决策中最核心的上下文维度之一。**认证**是 auth middleware 的职责，但 **授权**（guardrail 的职责）需要知道认证结果是谁。

user_id 的运行时链路：
```
AuthMiddleware → request.state.user
  → inject_authenticated_user_context(config.context["user_id"])
    → ToolRuntime.context["user_id"]
      → GuardrailMiddleware._build_request() 读取 → GuardrailRequest.user_id
```

### run_id：收益中，在 guardrail 边界外围但无成本

| 场景 | 没有 run_id | 有 run_id |
|------|-------------|-----------|
| 安全审计："工具 X 被拒 50 次" | 只能看到频率 | 可筛选出具体哪个 run 反复触发 deny |
| 外部 SIEM 关联 | 事件只有 `{tool, policy}` | 事件为 `{tool, policy, user, run}`，可关联到完整 conversation |

`run_id` 极少进入决策公式本身。它的价值在 audit 和调试场景。`GuardrailRequest` 是 provider 观察运行时的唯一信息通道，如果不在此暴露 `run_id`，provider 只能自建不可靠的关联机制（如 timestamp 近似匹配）。

### tool_call_id：收益低，但零成本

| 场景 | 没有 tool_call_id | 有 tool_call_id |
|------|------------------|-----------------|
| 同一轮中多次同工具调用（两次 `web_search`） | 日志中两行相同 `(web_search, user_A)`，需 diff args 区分 | 通过 `call_abc` / `call_def` 精确区分 |
| Provider 缓存决策结果 | 无法精确定位 cache key | 可作为 cache key 的一部分 |

`tool_call_id` 不影响 allow/deny 决策本身（没有 provider 会写"拒绝 call_abc 但允许 call_def"）。但数据已在 `request.tool_call.get("id")` 中，`_build_request` 只需顺手传过去，完全没有额外工作量。

### thread_id：补填已有字段

字段已在 `GuardrailRequest` 数据类中定义，但 `_build_request()` 从未从 `runtime.context` 填充。本次将其来源从空字符串补全为 `runtime.context["thread_id"]`，使接口契约与实际行为一致。

## 兼容性

- 所有新字段 optional
- 现有 `GuardrailProvider` 实现即使不读取新增字段，也继续正常工作
- 现有 `GuardrailDecision` 不变
- 缺少 `runtime`/`context` 时字段保持 `None`
- 现有 allow/deny 行为不变
- 现有测试（TestAllowlistProvider、TestGuardrailMiddleware 等）应继续通过，无需修改

## 测试

在 `tests/test_guardrail_middleware.py` 中新增：

| 测试 | 场景 |
|------|------|
| `test_user_id_from_runtime_context` | Mock `runtime.context` 含 `user_id`，验证传递到 `GuardrailRequest` |
| `test_run_id_from_runtime_context` | Mock `runtime.context` 含 `run_id`，验证传递 |
| `test_tool_call_id_from_tool_call` | `request.tool_call` 含 `id`，验证传递 |
| `test_thread_id_from_runtime_context` | 验证 `thread_id` 从 `runtime.context` 填充 |
| `test_missing_runtime_context` | 不设 `runtime`，验证新增字段保持 `None` |
| `test_missing_tool_call_id` | `tool_call` 无 `id`，验证 `None` |
| `test_existing_providers_backward_compat` | 现有 provider 不读取新字段时行为不变 |

## 未涉及

- 不创建新 governance / 审计子系统
- 不修改 MCP 配置机制
- 不修改 GuardrailDecision 结构
- 不涉及 agent identity 语义（现有 `agent_id` 仍保持 passport 语义）
- 不对原有 guardrail 测试做任何修改（向后兼容回归基线）
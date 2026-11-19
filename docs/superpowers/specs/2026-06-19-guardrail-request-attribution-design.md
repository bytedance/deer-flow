# GuardrailRequest 运行时用户上下文与归因字段补充

## 概述

为 `GuardrailRequest` 补充可选的运行时用户上下文和工具调用归因字段，使可插拔 `GuardrailProvider` 能访问 DeerFlow 已认证用户、外部身份映射、run/thread/tool-call 定位信息。

本设计不新增治理系统、不定义统一 policy schema，也不改变默认 allow/deny 行为。它只把 DeerFlow 运行时已经掌握的上下文传给 provider。

## 背景

DeerFlow 已通过 `GuardrailMiddleware` + 可插拔 `GuardrailProvider` 实现工具调用前授权。当前 `GuardrailDecision` 已能表达 allow/deny、原因、policy_id 和 metadata；缺口在 `GuardrailRequest` 侧：provider 只能看到 `tool_name` 和 `tool_input`，无法可靠知道“谁发起了这次工具调用”以及“这次调用属于哪个 run/tool_call”。

源码中 DeerFlow 已有用户身份模型：

- `users.id`：DeerFlow 内部稳定用户 ID。
- `users.system_role`：`admin` / `user`。
- `users.oauth_provider`、`users.oauth_id`：未来 OAuth/SSO 外部身份映射字段，local user 下可为空。

这些字段当前已存在于认证后的 `request.state.user`，但 run-time middleware/tool 阶段只能通过 `runtime.context` 访问上下文。因此应在 Gateway 构建 run config 时注入 server-authenticated user context，再由 GuardrailMiddleware 消费。

## 改动范围

- `app/gateway/services.py`：`inject_authenticated_user_context()` 注入更多 authenticated user context。
- `guardrails/provider.py`：`GuardrailRequest` 新增 optional 字段。
- `guardrails/middleware.py`：从 `ToolCallRequest.runtime.context` 读取字段。
- `tests/test_setup_agent_e2e_user_isolation.py`：验证 Gateway 注入到 runtime context。
- `tests/test_guardrail_middleware.py`：验证 runtime context 进入 `GuardrailRequest`。
- `backend/docs/GUARDRAILS.md`：更新 custom provider 示例。

## 设计

### GuardrailRequest 字段

```python
@dataclass
class GuardrailRequest:
    tool_name: str
    tool_input: dict[str, Any]
    agent_id: str | None = None
    thread_id: str | None = None
    is_subagent: bool = False
    timestamp: str = ""

    user_id: str | None = None
    user_role: str | None = None
    oauth_provider: str | None = None
    oauth_id: str | None = None
    run_id: str | None = None
    tool_call_id: str | None = None
```

所有新增字段均为 optional，缺失时保持 `None`。`GuardrailDecision` 不变。

### 字段来源

| 字段 | 来源 | 说明 |
|------|------|------|
| `user_id` | `request.state.user.id` → `runtime.context["user_id"]` | DeerFlow 内部稳定用户 ID |
| `user_role` | `request.state.user.system_role` → `runtime.context["user_role"]` | 可用于简单 role-based policy |
| `oauth_provider` | `request.state.user.oauth_provider` → `runtime.context["oauth_provider"]` | OAuth/SSO 外部 provider，local user 可为空 |
| `oauth_id` | `request.state.user.oauth_id` → `runtime.context["oauth_id"]` | 外部 provider subject/user id，local user 可为空 |
| `run_id` | `_build_runtime_context()` 写入 `runtime.context["run_id"]` | run 级审计归因 |
| `thread_id` | `_build_runtime_context()` 写入 `runtime.context["thread_id"]` | 修正已有字段未填充问题 |
| `tool_call_id` | `request.tool_call.get("id")` | 单次 tool call 定位 |

Gateway 注入只信任服务端认证态 `request.state.user`。客户端 `body.context` 里的 `user_id/user_role/oauth_*` 不应覆盖 authenticated user。

## 收益

### 稳定审计归因

`user_id/run_id/thread_id/tool_call_id` 让 provider 或外部审计系统能回答：

- 哪个 DeerFlow 用户触发了 tool call？
- 哪个 run 里发生了 deny？
- 同一轮中多次同名工具调用时，具体是哪一次？

### 可读的本地策略示例

`user_id` 是 UUID，不适合直接写人工 policy。`user_role` 可以支持简单示例：

```yaml
field: role_tool_key
operator: eq
value: admin:bash
```

provider 可派生：

```python
role_tool_key = f"{request.user_role or ''}:{request.tool_name}"
```

### 外部身份映射

`oauth_provider/oauth_id` 保留了未来接 OAuth/SSO/IAM 时的外部 subject 信息。当前 OAuth 路由仍是 placeholder，local user 下这些字段通常为 `None`，但字段 optional，不影响现有部署。

## 兼容性

- 所有新增字段 optional。
- 现有 provider 不读取新字段时行为不变。
- `GuardrailDecision` 不变。
- 未认证或无 runtime context 时字段为 `None`。
- local user 没有 OAuth 信息时 `oauth_provider/oauth_id` 为 `None`。
- `agent_id` 语义不变，仍保持现有 passport/agent hint 含义。

## 测试

新增或扩展以下测试：

| 测试 | 覆盖 |
|------|------|
| `TestConfigAssembly::test_authenticated_user_context_includes_role_and_oauth_identity` | Gateway 将 `user_id/user_role/oauth_provider/oauth_id` 注入 runtime context |
| `TestConfigAssembly::test_client_supplied_user_id_is_overridden` | 客户端伪造 identity context 不覆盖服务端认证态 |
| `TestGuardrailRequestAttribution::test_authenticated_user_context_present` | `runtime.context` 中用户上下文进入 `GuardrailRequest` |
| `TestGuardrailRequestAttribution::test_all_attribution_fields_present` | 用户上下文 + run/tool_call 归因字段同时传递 |
| 缺失 runtime/context 测试 | 字段保持 `None`，向后兼容 |

验证命令：

```bash
cd backend
PYTHONPATH=. uv run pytest \
  tests/test_guardrail_middleware.py::TestGuardrailRequestAttribution \
  tests/test_setup_agent_e2e_user_isolation.py::TestConfigAssembly -v
```

## 未涉及

- 不新增 central governance subsystem。
- 不新增 DeerFlow 内置 policy schema。
- 不修改 MCP 配置机制。
- 不修改 OAuth/SSO 实现状态。
- 不让 GuardrailMiddleware 直接依赖 FastAPI request、DB 或 auth repository。

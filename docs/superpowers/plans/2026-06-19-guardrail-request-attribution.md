# GuardrailRequest 运行时用户上下文与归因字段补充 — 实现计划

**Goal:** 将服务端认证后的用户上下文和运行时归因信息传递给 `GuardrailProvider`：`user_id`、`user_role`、`oauth_provider`、`oauth_id`、`thread_id`、`run_id`、`tool_call_id`。

**Architecture:** Gateway 只从 `request.state.user` 注入可信用户上下文；run worker 复用现有 `runtime.context` 传递机制；GuardrailMiddleware 只消费 `ToolCallRequest.runtime.context`，不依赖 FastAPI request、DB 或 auth repository。

**Tech Stack:** Python 3.12+, dataclasses, LangGraph `ToolCallRequest.runtime.context`, pytest

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| Modify | `backend/app/gateway/services.py` | 注入 authenticated user context |
| Modify | `backend/packages/harness/deerflow/guardrails/provider.py` | `GuardrailRequest` 扩字段 |
| Modify | `backend/packages/harness/deerflow/guardrails/middleware.py` | 从 runtime context 填充字段 |
| Modify | `backend/tests/test_setup_agent_e2e_user_isolation.py` | 覆盖 Gateway → runtime context |
| Modify | `backend/tests/test_guardrail_middleware.py` | 覆盖 runtime context → GuardrailRequest |
| Modify | `backend/docs/GUARDRAILS.md` | 更新 custom provider 示例 |

---

## Task 1: Gateway 注入 authenticated user context

**Files:**
- Modify: `backend/app/gateway/services.py`

- [x] **Step 1: 扩展 `inject_authenticated_user_context()`**

在已有 `runtime_context["user_id"] = str(user_id)` 后追加：

```python
runtime_context["user_role"] = getattr(user, "system_role", None)
runtime_context["oauth_provider"] = getattr(user, "oauth_provider", None)
runtime_context["oauth_id"] = getattr(user, "oauth_id", None)
```

**约束：**
- 只读取 `request.state.user`，不信任 client `body.context`。
- `INTERNAL_SYSTEM_ROLE` 仍保持跳过注入。
- local user 的 OAuth 字段允许为 `None`。

- [x] **Step 2: 扩展 config assembly 测试**

在 `TestConfigAssembly` 中覆盖：

- authenticated user 的 `user_role/oauth_provider/oauth_id` 进入 runtime context。
- client-supplied `user_id/user_role/oauth_provider/oauth_id` 不覆盖 server-authenticated user。

---

## Task 2: GuardrailRequest 扩展字段

**Files:**
- Modify: `backend/packages/harness/deerflow/guardrails/provider.py`

- [x] **Step 1: 在 `GuardrailRequest` 末尾新增 optional 字段**

```python
user_id: str | None = None
user_role: str | None = None
oauth_provider: str | None = None
oauth_id: str | None = None
run_id: str | None = None
tool_call_id: str | None = None
```

**约束：**
- 不修改 `GuardrailDecision`。
- 不修改现有 provider protocol。
- 所有字段 optional，保持向后兼容。

---

## Task 3: GuardrailMiddleware 从 runtime context 填充

**Files:**
- Modify: `backend/packages/harness/deerflow/guardrails/middleware.py`

- [x] **Step 1: 安全读取 `ToolCallRequest.runtime.context`**

```python
runtime = getattr(request, "runtime", None)
context = getattr(runtime, "context", None) if runtime is not None else None
context = context if isinstance(context, dict) else {}
```

- [x] **Step 2: 构造 `GuardrailRequest` 时填充字段**

```python
GuardrailRequest(
    tool_name=str(request.tool_call.get("name", "")),
    tool_input=request.tool_call.get("args", {}),
    agent_id=self.passport,
    thread_id=context.get("thread_id"),
    timestamp=datetime.now(UTC).isoformat(),
    user_id=context.get("user_id"),
    user_role=context.get("user_role"),
    oauth_provider=context.get("oauth_provider"),
    oauth_id=context.get("oauth_id"),
    run_id=context.get("run_id"),
    tool_call_id=request.tool_call.get("id"),
)
```

**约束：**
- runtime/context 缺失时字段为 `None`。
- `thread_id` 是已有字段，本次补填。
- 不在 GuardrailMiddleware 中访问 request/auth/DB。

---

## Task 4: 文档与示例

**Files:**
- Modify: `backend/docs/GUARDRAILS.md`

- [x] **Step 1: 增加 Runtime Attribution 小节**

说明以下字段及用途：

- `user_id`：稳定审计归因。
- `user_role`：简单 role-based policy。
- `oauth_provider/oauth_id`：外部身份 provider/subject 映射，local user 可为空。
- `thread_id/run_id/tool_call_id`：run/tool-call 定位。

- [x] **Step 2: 更新 Context-Aware Provider 示例**

示例 provider 只接收 `policy_path/audit_path`，把 `GuardrailRequest` 归一化成 provider-defined policy context，并展示：

```python
"role_tool_key": f"{request.user_role or ''}:{request.tool_name}"
```

示例 policy 使用：

```yaml
field: role_tool_key
operator: eq
value: admin:bash
```

**文案约束：**
- 不声称 DeerFlow 内置该 YAML schema。
- 不写成对标 AGT。
- AGT/OPA/Cedar 只作为可选 policy engine 示例。

---

## Task 5: 测试与验证

- [x] **Step 1: 运行目标测试**

```bash
cd backend
PYTHONPATH=. uv run pytest \
  tests/test_guardrail_middleware.py::TestGuardrailRequestAttribution \
  tests/test_setup_agent_e2e_user_isolation.py::TestConfigAssembly -v
```

Expected:

```text
15 passed
```

- [x] **Step 2: 验证覆盖点**

| 测试 | 覆盖 |
|------|------|
| `test_authenticated_user_context_includes_role_and_oauth_identity` | Gateway 注入完整用户上下文 |
| `test_client_supplied_user_id_is_overridden` | 防止客户端伪造身份字段 |
| `test_authenticated_user_context_present` | GuardrailRequest 接收用户上下文 |
| `test_all_attribution_fields_present` | 用户上下文与 run/tool-call 归因同时存在 |
| missing context tests | 字段缺失时为 `None` |

---

## 自检清单

1. **Scope:** 改动保持在 authenticated runtime context 与 Guardrail provider 入参，不新增治理系统。
2. **Security:** `user_role/oauth_provider/oauth_id` 只从服务端认证态注入，不信任客户端 context。
3. **Compatibility:** 新字段全部 optional；现有 provider 不读取时行为不变。
4. **Docs:** Guardrails 文档示例使用 role-based policy，不再建议手写 UUID 策略。
5. **Tests:** 目标测试已通过：`15 passed`。

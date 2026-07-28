# Phase 1A-1 实施计划：可信 Principal 链路

建议 PR 标题：

```text
feat(authz): propagate trusted authorization principal context
```

前置基线：PR #4127 / `1300c6d3`
总计划：`docs/plans/2026-07-15-authz-phase1a-implementation-plan.md`
实施记录：`docs/plans/2026-07-10-pluggable-authorization-implementation-notes.md`

## 1. 目标

本 PR 完成一条可信、可测试的授权身份链路：

```text
Gateway 认证状态
  → 清除客户端伪造字段
  → 服务端注入 is_internal
  → lead runtime context
  → task_tool 捕获
  → SubagentExecutor 复制
  → subagent runtime context
  → GuardrailRequest
  → GuardrailAuthorizationAdapter
  → build_principal_from_context()
  → Principal
```

本 PR 不接入 Layer 1 工具过滤，也不自动安装 Layer 2 middleware。合并后的兼容性承诺：

- `authorization.enabled: false` 时，工具集合和工具执行决策不变。
- runtime context 新增服务端身份字段是有意的可观察变化。
- 现有 adapter 异常传播语义保持不变。

## 2. 固定安全契约

### 2.1 Principal

`build_principal_from_context()` 必须显式构造全部 7 个字段：

```text
user_id / role / oauth_provider / oauth_id / channel_user_id /
is_internal / attributes
```

规则：

- `user_role` 为 `None` 或空字符串时使用 `default_role`。
- 未知但非空的角色原样保留；不能回退到默认角色。
- `is_internal` 只有原值严格等于 `True` 时才为 `True`。
- `authz_attributes` 为 `None` 或缺失时解析为 `{}`。
- 非空 `authz_attributes` 必须实现 `Mapping`，否则抛 `TypeError`。
- attributes 每次都复制为新字典，不共享可变引用。
- builder 是纯函数：不读全局 config、不缓存、不修改输入。

### 2.2 Gateway 可信边界

`is_internal`、`authz_attributes` 和 `channel_user_id` 是服务端拥有字段：

- 必须从 `config["context"]` 和 `config["configurable"]` 清除客户端值。
- `is_internal` 只能由 `request.state.auth_source == AUTH_SOURCE_INTERNAL` 产生。
- `channel_user_id` 只能来自内部认证 IM 调用方的顶层 `body.context`；普通 session
  请求和 `body.config` 两个 section 中的值必须删除。
- 必须使用直接赋值，不能使用 `setdefault`。
- 必须在 `user_id is None` 等所有 early return 之前写入。
- Phase 1A-1 没有 Gateway 侧 attributes 权威生产者，因此 Gateway 请求中的
  `authz_attributes` 一律删除。

### 2.3 传递语义

- Subagent 必须继承 parent context 的 `is_internal` 和合法 attributes。
- `is_internal=False` 也必须显式写回，不能按 truthy 条件省略。
- attributes 在 task 捕获、executor 构造和 context 写回时均使用副本。
- 非 Mapping attributes 不能在某些层抛错、另一些层静默变成 `{}`；所有进程内消费
  边界统一抛 `TypeError`。
- Guardrail adapter 必须复用 Principal builder，不能维护第二套默认角色或 attributes
  解析逻辑。

## 3. TDD 实施顺序

### Step 1：新增 Principal builder 失败测试

新增：

```text
backend/tests/test_authorization_principal.py
```

覆盖：

- 空 context、部分 context 和全部 7 个字段映射。
- 缺失、`None`、空字符串 role 使用 `default_role`。
- 未知非空 role 原样保留。
- `is_internal` 对 `True`、`False`、`1`、`"true"`、`None` 的严格布尔行为。
- attributes 缺失或 `None` 得到 `{}`。
- Mapping attributes 被复制；修改输入不影响 Principal。
- 非 Mapping attributes 抛 `TypeError`，错误包含实际类型。
- oauth 和 channel identity 正确映射。

先运行该测试并确认因 builder 不存在而失败。

### Step 2：实现 Principal builder

新增：

```text
backend/packages/harness/deerflow/authz/principal.py
```

接口和核心实现：

```python
from collections.abc import Mapping
from typing import Any

from deerflow.authz.provider import Principal


def build_principal_from_context(
    context: Mapping[str, Any],
    *,
    default_role: str,
) -> Principal:
    resolved_role = context.get("user_role")
    if resolved_role is None or resolved_role == "":
        resolved_role = default_role

    raw_attributes = context.get("authz_attributes")
    if raw_attributes is None:
        attributes: dict[str, Any] = {}
    elif isinstance(raw_attributes, Mapping):
        attributes = dict(raw_attributes)
    else:
        raise TypeError(
            "authz_attributes must be a Mapping, "
            f"got {type(raw_attributes).__name__}"
        )

    return Principal(
        user_id=context.get("user_id"),
        role=resolved_role,
        oauth_provider=context.get("oauth_provider"),
        oauth_id=context.get("oauth_id"),
        channel_user_id=context.get("channel_user_id"),
        is_internal=context.get("is_internal") is True,
        attributes=attributes,
    )
```

修改 `backend/packages/harness/deerflow/authz/__init__.py` 导出
`build_principal_from_context`。

### Step 3：新增 Gateway 防伪失败测试

修改：

```text
backend/tests/test_gateway_services.py
```

必须复用真实配置装配顺序：

```text
build_run_config
  → merge_run_context_overrides
  → strip_internal_context_keys（非 internal 请求）
  → inject_authenticated_user_context
```

分别测试以下入口，不能合并为一个配置：

1. `body.config["context"]` 伪造 `is_internal=True`。
2. `body.config["configurable"]` 伪造 `is_internal=True`。
3. 两个入口分别伪造 `authz_attributes`。

断言：

- 普通/session 请求最终 `context.is_internal is False`。
- `configurable.is_internal` 被删除。
- 两个 section 中的 `authz_attributes` 都被删除。
- internal 请求最终 `context.is_internal is True`。
- internal 请求携带的客户端伪造 attributes 同样被删除。
- `user=None`、auth source 缺失或 session 时仍写入 `False`。
- `user=None`、`auth_source=internal` 时仍写入 `True`。
- 非 Mapping runtime context 显式抛 `TypeError`，不静默跳过。
- 原有 user、owner、role、oauth 测试继续通过。

这些测试必须证明新增覆盖逻辑是唯一通过原因，不能使用本来就被 `body.context`
白名单过滤的空路径。

### Step 4：实现 Gateway 防伪与注入

修改：

```text
backend/app/gateway/services.py
```

新增：

```python
_SERVER_OWNED_AUTHZ_CONTEXT_KEYS = frozenset(
    {"is_internal", "authz_attributes", "channel_user_id"}
)
```

在 `inject_authenticated_user_context()` 最顶部、读取 `user_id` 之前执行：

```python
runtime_context = config.setdefault("context", {})
if not isinstance(runtime_context, dict):
    raise TypeError("run context must be a mapping")

for key in _SERVER_OWNED_AUTHZ_CONTEXT_KEYS:
    runtime_context.pop(key, None)

configurable = config.get("configurable")
if isinstance(configurable, dict):
    for key in _SERVER_OWNED_AUTHZ_CONTEXT_KEYS:
        configurable.pop(key, None)

auth_source = getattr(getattr(request, "state", None), "auth_source", None)
runtime_context["is_internal"] = auth_source == AUTH_SOURCE_INTERNAL
```

之后保留现有普通用户、internal owner 和 early return 逻辑。`AUTH_SOURCE_INTERNAL`
已经由当前模块导入，不重复增加角色名称推导。

### Step 5：新增 task_tool 身份捕获失败测试

修改：

```text
backend/tests/test_task_tool_core_logic.py
```

复用现有 `test_task_tool_forwards_channel_user_id_to_executor` 的 DummyExecutor 模式，覆盖：

- parent `is_internal=True` 传给 executor。
- parent `is_internal=False` 仍显式传给 executor。
- Mapping attributes 被复制后传给 executor。
- 捕获后修改 parent attributes 不影响 executor kwargs。
- 非 Mapping attributes 抛 `TypeError`，不能静默变成 `{}`。

### Step 6：实现 task_tool 身份捕获

修改：

```text
backend/packages/harness/deerflow/tools/builtins/task_tool.py
```

在现有 parent identity capture 块增加：

```python
is_internal = parent_context.get("is_internal") is True
raw_attributes = parent_context.get("authz_attributes")
if raw_attributes is None:
    authz_attributes: dict[str, Any] = {}
elif isinstance(raw_attributes, Mapping):
    authz_attributes = dict(raw_attributes)
else:
    raise TypeError(
        "authz_attributes must be a Mapping, "
        f"got {type(raw_attributes).__name__}"
    )
```

将二者无条件加入 `executor_kwargs`。

### Step 7：新增 executor 写回失败测试

修改：

```text
backend/tests/test_subagent_executor.py
```

复用现有 channel identity context 测试模式，覆盖：

- 构造参数 `is_internal=True/False` 都写回 subagent context。
- attributes 在构造时复制。
- attributes 在 context write-back 时再次复制。
- 修改调用方原字典或写回后的字典均不影响 executor 内部副本。
- executor 直接收到非 Mapping attributes 时抛 `TypeError`。

### Step 8：实现 executor 身份写回

修改：

```text
backend/packages/harness/deerflow/subagents/executor.py
```

构造参数增加：

```python
is_internal: bool = False,
authz_attributes: Mapping[str, Any] | None = None,
```

构造时严格校验并复制：

```python
self.is_internal = is_internal
if authz_attributes is None:
    self.authz_attributes = {}
elif isinstance(authz_attributes, Mapping):
    self.authz_attributes = dict(authz_attributes)
else:
    raise TypeError(
        "authz_attributes must be a Mapping, "
        f"got {type(authz_attributes).__name__}"
    )
```

context write-back 无条件执行：

```python
context["is_internal"] = self.is_internal
context["authz_attributes"] = dict(self.authz_attributes)
```

### Step 9：新增 Guardrail/adapter 失败测试

修改：

```text
backend/tests/test_authorization_provider.py
backend/tests/test_guardrail_middleware.py
```

覆盖：

- `GuardrailRequest` 新字段默认值向后兼容。
- middleware 映射 `channel_user_id`、严格布尔 `is_internal`、合法 attributes。
- middleware 遇到非 Mapping attributes 时抛 `TypeError`。
- adapter 同步和异步路径产生相同 Principal。
- adapter 正确映射全部 7 个 Principal 字段。
- role 缺失时 adapter 通过 builder 应用 `default_role`。
- 未知非空 role 不回退。
- 将旧的 Phase 0 `is_internal` 不映射测试改为正确映射测试。
- provider 异常仍穿过 adapter，现有异常传播测试继续通过。

middleware context 映射断言放在现有 `test_guardrail_middleware.py`，adapter 转换断言
放在 `test_authorization_provider.py`；不得新建重复测试模块。

### Step 10：扩展 GuardrailRequest 和 adapter

修改：

```text
backend/packages/harness/deerflow/guardrails/provider.py
backend/packages/harness/deerflow/guardrails/middleware.py
backend/packages/harness/deerflow/authz/adapter.py
```

`GuardrailRequest` 增加带默认值的字段：

```python
channel_user_id: str | None = None
is_internal: bool = False
authz_attributes: dict[str, Any] = field(default_factory=dict)
```

middleware 在构造 request 前用普通分支完成 attributes 校验，不使用 walrus one-liner：

```python
raw_attributes = context.get("authz_attributes")
if raw_attributes is None:
    authz_attributes: dict[str, Any] = {}
elif isinstance(raw_attributes, Mapping):
    authz_attributes = dict(raw_attributes)
else:
    raise TypeError(...)
```

adapter：

- 构造函数增加 `default_role: str = "user"` 并保存。
- `_to_authz()` 从 GuardrailRequest 组装 context 字典。
- 调用 `build_principal_from_context()`，不得手工构造 Principal。
- 删除 Phase 0 关于 `is_internal` 尚未映射的 note。
- 不捕获 provider 异常，不实现 `fail_closed`。

同时更新 `authz/provider.py` 中 Principal 的生命周期说明：adapter 每次请求实时构建
Principal，不得继续描述为“每个 run 只构建一次”。

Phase 1B 自动装配 adapter 时必须显式传入
`AuthorizationConfig.default_role`；本 PR 不进行该装配。

### Step 11：更新实施记录

修改：

```text
docs/plans/2026-07-10-pluggable-authorization-implementation-notes.md
```

只追加 Phase 1A-1 决策日志，记录：

- internal 来自服务端 auth source。
- Gateway 清除服务端拥有字段。
- adapter 复用唯一 Principal builder。
- attributes 使用严格 Mapping + copy 语义。
- subagent 无条件继承 internal 布尔值。
- RBAC、provider factory 和执行接线继续延期。

不修改 Phase 0 历史记录，不 bump `config_version`。

## 4. 精确文件清单

新增 5 个文件：

```text
backend/packages/harness/deerflow/authz/principal.py
backend/tests/test_authorization_principal.py
docs/plans/2026-07-10-pluggable-authorization-implementation-notes.md
docs/plans/2026-07-15-authz-phase1a-implementation-plan.md
docs/plans/2026-07-15-authz-phase1a1-trusted-principal-implementation-plan.md
```

修改 17 个文件：

```text
backend/AGENTS.md
backend/packages/harness/deerflow/authz/__init__.py
backend/packages/harness/deerflow/authz/adapter.py
backend/packages/harness/deerflow/authz/provider.py
backend/packages/harness/deerflow/guardrails/provider.py
backend/packages/harness/deerflow/guardrails/middleware.py
backend/app/gateway/services.py
backend/packages/harness/deerflow/tools/builtins/task_tool.py
backend/packages/harness/deerflow/subagents/executor.py
backend/packages/harness/deerflow/sandbox/tools.py
backend/tests/test_authorization_provider.py
backend/tests/test_channel_user_id_env.py
backend/tests/test_guardrail_middleware.py
backend/tests/test_task_tool_core_logic.py
backend/tests/test_subagent_executor.py
backend/tests/test_gateway_services.py
docs/plans/2026-07-10-pluggable-authorization-rfc.md
```

合计 22 个文件。文件数较多是因为它固定一条跨 Gateway、lead、subagent 和 guardrail
的端到端身份链；继续拆分会产生可合并但身份链不完整的中间状态。

## 5. 明确不修改

```text
backend/packages/harness/deerflow/config/authorization_config.py
config.example.yaml
backend/packages/harness/deerflow/agents/lead_agent/agent.py
backend/packages/harness/deerflow/client.py
```

本 PR 不实现：

- RBAC provider 和 provider factory（Phase 1A-2）。
- Layer 1 工具过滤和 deferred catalog 防提升（Phase 1B）。
- Layer 2 自动接线及与显式 guardrail 的组合顺序（Phase 1B）。
- DeerFlowClient skill filter gap（独立 bugfix PR）。
- route、model、skill、sandbox、MCP server 授权。
- RBAC 配置示例和配置版本变更。

## 6. 测试命令

按 TDD 步骤先确认新增测试失败，再逐段实现：

```powershell
cd backend

uv run pytest tests/test_authorization_principal.py -q
uv run pytest tests/test_gateway_services.py -q
uv run pytest tests/test_task_tool_core_logic.py -q
uv run pytest tests/test_subagent_executor.py -q
uv run pytest tests/test_authorization_provider.py -q
uv run pytest tests/test_guardrail_middleware.py -q
uv run pytest tests/test_channel_user_id_env.py -q

uv run pytest tests/test_authorization_principal.py tests/test_gateway_services.py tests/test_channel_user_id_env.py tests/test_task_tool_core_logic.py tests/test_subagent_executor.py tests/test_authorization_provider.py tests/test_guardrail_middleware.py -q
uv run pytest tests/test_harness_boundary.py -q

uv run ruff check packages/harness/deerflow/authz packages/harness/deerflow/guardrails packages/harness/deerflow/tools/builtins/task_tool.py packages/harness/deerflow/subagents/executor.py packages/harness/deerflow/sandbox/tools.py app/gateway/services.py tests/test_authorization_principal.py tests/test_authorization_provider.py tests/test_channel_user_id_env.py tests/test_task_tool_core_logic.py tests/test_subagent_executor.py tests/test_gateway_services.py
uv run ruff format --check packages/harness/deerflow/authz packages/harness/deerflow/guardrails packages/harness/deerflow/tools/builtins/task_tool.py packages/harness/deerflow/subagents/executor.py packages/harness/deerflow/sandbox/tools.py app/gateway/services.py tests/test_authorization_principal.py tests/test_authorization_provider.py tests/test_channel_user_id_env.py tests/test_task_tool_core_logic.py tests/test_subagent_executor.py tests/test_gateway_services.py
```

提交前运行：

```powershell
make test
make lint
make format
```

若全量测试受外部环境阻塞，PR 描述必须列出具体命令、通过结果和阻塞原因。

## 7. 验收门槛

- [ ] 删除 `is_internal` 服务端直接赋值后，Gateway 防伪测试失败。
- [ ] 删除 `configurable` 清理后，对应伪造测试失败。
- [ ] 普通请求不能通过 `body.context` 或 `body.config` 注入 `channel_user_id`；internal
      请求只接受顶层 `body.context` 的值。
- [ ] 删除任意一段 task/executor identity wiring 后，subagent 测试失败。
- [ ] builder、task、executor、middleware 对 attributes 非 Mapping 的行为一致。
- [ ] adapter 同步和异步生成语义一致的完整 Principal。
- [ ] `user=None` 的 internal 和 non-internal 分支都被固定。
- [ ] 原有 Gateway、guardrail 和 subagent 测试继续通过。
- [ ] `authorization.enabled: false` 时工具集合与执行决策不变。
- [ ] 没有 Layer 1、Layer 2、RBAC 或 client 额外改动混入。
- [ ] implementation notes 已追加决策记录。
- [ ] `git diff --check`、ruff、目标测试和全量可运行测试通过。

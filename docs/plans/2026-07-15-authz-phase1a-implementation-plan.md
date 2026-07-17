# Phase 1A 实施计划：可信身份链路与内置 RBAC 核心

> RFC：`docs/plans/2026-07-10-pluggable-authorization-rfc.md`
> 前情记录：`docs/plans/2026-07-10-pluggable-authorization-implementation-notes.md`
> Phase 0 基线：PR #4127 / `1300c6d3`

## 1. 目标与拆分

Phase 1A 只建立身份和策略核心，不把授权接入工具装配或执行路径。为降低 review
复杂度，拆成两个可独立合并的 PR：

1. **Phase 1A-1：可信 Principal 链路**
   - 从 Gateway 的服务端认证状态产生 `is_internal`。
   - 使用唯一的 Principal builder 解析身份。
   - 将完整身份传递到 subagent 和 Guardrail adapter。
2. **Phase 1A-2：内置 RBAC 与 provider factory**
   - 实现严格、确定性的内置 RBAC provider。
   - 实现统一的 provider 实例化和 Protocol 校验。

Phase 1A 合并后的准确兼容性承诺是：

- `authorization.enabled: false` 时，工具集合和工具执行决策不变。
- runtime context 会新增服务端生成的身份字段，这是有意的可观察变化。
- Phase 1A 不执行 Layer 1 过滤，也不自动安装 Layer 2 middleware。

## 2. 固定架构与职责

```text
Gateway 认证状态
    │
    ├─ 清除客户端伪造的服务端身份字段
    ├─ 注入 user_id / user_role / oauth_* / is_internal
    ▼
runtime context
    │
    ├─ build_principal_from_context(default_role)
    │      └─ Phase 1B Layer 1 使用
    │
    ├─ task tool → SubagentExecutor → subagent runtime context
    │
    └─ GuardrailMiddleware → GuardrailRequest
             → GuardrailAuthorizationAdapter
             → build_principal_from_context(default_role)
             → AuthorizationProvider
```

职责必须保持单一：

- **Gateway**：确认字段来源可信，覆盖或清除客户端值。
- **Principal builder**：补齐缺失角色、规范化类型、复制 attributes。
- **RBAC provider**：只解释已经解析好的 Principal 和角色策略。
- **provider factory**：加载、构造、校验 provider，不执行授权策略。
- **GuardrailMiddleware**：处理 provider 异常以及 `fail_closed`。
- **adapter**：只做数据映射和决策类型转换，不捕获异常。

## 3. 全局语义锁

### 3.1 Principal

- `role` 仅在 `user_role` 为 `None` 或空字符串时使用 `default_role`。
- 未知但非空的角色不能回退到 `default_role`。
- `is_internal` 只有原值严格等于 `True` 时才为 `True`。
- `authz_attributes` 必须是 `Mapping`；其他非空类型抛 `TypeError`。
- `attributes` 总是复制为新字典，不共享输入引用。
- Layer 1 和 Layer 2 必须通过同一个 builder 获得语义一致的 Principal。

### 3.2 服务端身份字段

`is_internal`、`authz_attributes` 和 `channel_user_id` 是服务端拥有字段：

- Gateway 必须从 `config.context` 和 `config.configurable` 清除客户端值。
- `is_internal` 只能由 `request.state.auth_source == AUTH_SOURCE_INTERNAL` 产生。
- `channel_user_id` 只能来自内部认证 IM 调用方的顶层 `body.context`；普通 session
  请求和 `body.config` 两个 section 中的同名值必须删除。
- 写入使用直接赋值，不能使用 `setdefault`。
- 写入必须发生在 `user_id is None` 等所有 early return 之前。
- Phase 1A 尚无 Gateway 侧 `authz_attributes` 权威生产者，因此 Gateway 路径固定为空；
  不能接受普通 HTTP 客户端提供的 attributes。
- 嵌入式 Python 调用属于进程内可信调用，可直接使用 builder 构造 attributes。

### 3.3 RBAC

每个角色的资源策略使用以下语义：

| 配置 | 行为 |
|---|---|
| `allow: "*"` 或 `allow: true` | 默认允许全部候选 |
| `allow: [...]` | 只允许列表成员 |
| `allow: []` 或 `allow: false` | 全部拒绝 |
| `allow` 缺失 | 默认允许，仍应用 deny |
| `deny: [...]` | 从允许集合移除；deny 永远优先 |
| 资源配置缺失 | 此 provider 不限制该资源 |
| Principal 角色缺失 | 视为 builder/调用方错误，抛明确异常 |
| Principal 角色未知 | 抛明确异常，由执行层按 `fail_closed` 处理 |
| 配置类型、成员类型或字段非法 | provider 构造时抛 `ValueError` |

资源名必须显式映射，禁止通过简单加 `s` 猜测：

```python
RESOURCE_POLICY_KEYS = {
    "tool": "tools",
    "model": "models",
    "skill": "skills",
    "sandbox": "sandbox",
    "mcp_server": "mcp_servers",
    "route": "routes",
}
```

未知 resource 使用原名查找；未配置时按“资源配置缺失”处理。Phase 1A 的行为测试
以 `tool -> tools` 为主，其他资源只固定映射契约，不接线。

### 3.4 fail-closed

- `fail_closed` 不传给 provider，也不由 provider 或 adapter解释。
- provider 遇到未知身份或内部错误时抛异常。
- Phase 1B 的 Layer 1 helper 和现有 `GuardrailMiddleware` 分别在边界处应用
  `fail_closed`。
- provider 主动返回 `allow=True` 不属于异常，middleware 不会替它改判；因此未知角色
  绝不能返回 allow。

## 4. PR Phase 1A-1：可信 Principal 链路

建议标题：

```text
feat(authz): propagate trusted authorization principal context
```

### Step 1：先写失败测试

新增 `backend/tests/test_authorization_principal.py`：

- 空 context 和部分 context。
- 缺失、`None`、空字符串角色使用 `default_role`。
- 未知非空角色原样保留。
- `is_internal` 仅接受严格布尔 `True`。
- attributes 缺失、复制、输入修改不反向影响 Principal。
- attributes 非 Mapping 时抛 `TypeError`。

扩展 `backend/tests/test_gateway_services.py`：

- 普通请求通过 `body.config.context` 伪造 `is_internal=True`，最终为 `False`。
- 普通请求通过 `body.config.configurable` 伪造该值，最终被清除。
- `user=None` 时仍写入 `is_internal=False`。
- 内部认证请求写入 `is_internal=True`。
- 普通请求注入的 `authz_attributes` 从两个 config section 中被清除。
- 原有 user/owner/oauth 注入测试继续通过。

扩展现有 subagent/guardrail 测试：

- `is_internal=True/False` 均能原样传递，不能只在 truthy 时写回。
- `channel_user_id` 和 attributes 一同传递。
- subagent 对 attributes 使用副本。
- adapter 同步、异步路径映射出相同 Principal。
- adapter 通过 builder 应用 `default_role`，不维护第二套回退逻辑。

### Step 2：实现 Principal builder

新增：

```text
backend/packages/harness/deerflow/authz/principal.py
```

接口：

```python
def build_principal_from_context(
    context: Mapping[str, Any],
    *,
    default_role: str,
) -> Principal:
    ...
```

实现保持纯函数，不读取全局 AppConfig，不缓存结果，不修改输入。

### Step 3：保护并注入 Gateway 身份

修改：

```text
backend/app/gateway/services.py
```

新增独立常量，例如：

```python
_SERVER_OWNED_AUTHZ_CONTEXT_KEYS = frozenset(
    {"is_internal", "authz_attributes", "channel_user_id"}
)
```

在 `inject_authenticated_user_context()` 开头：

1. 从 `context` 和 `configurable` 删除上述客户端值。
2. 确保 runtime context 是字典；若输入类型非法，使用现有配置错误约定明确失败，
   不能静默保留伪造值。
3. 直接写入服务端计算的 `is_internal`。
4. 再执行现有 user/internal owner 分支和 early return。

不要把 `is_internal` 加进允许 internal caller 自定义的普通 override 白名单；它始终由
认证中间件产生。

### Step 4：完整传递 subagent 身份

修改：

```text
backend/packages/harness/deerflow/tools/builtins/task_tool.py
backend/packages/harness/deerflow/subagents/executor.py
```

从 parent runtime context 捕获：

```text
user_id / user_role / oauth_provider / oauth_id / channel_user_id
is_internal / authz_attributes
```

`SubagentExecutor` 构造时复制 attributes；写回 subagent context 时再次复制。
`is_internal` 必须无条件写回布尔值，包括 `False`。

### Step 5：扩展 GuardrailRequest 并复用 builder

修改：

```text
backend/packages/harness/deerflow/guardrails/provider.py
backend/packages/harness/deerflow/guardrails/middleware.py
backend/packages/harness/deerflow/authz/adapter.py
backend/tests/test_authorization_provider.py
```

`GuardrailRequest` 增加向后兼容的默认字段：

```python
channel_user_id: str | None = None
is_internal: bool = False
authz_attributes: dict[str, Any] = field(default_factory=dict)
```

adapter 构造函数增加 `default_role`，并在 `_to_authz()` 中调用
`build_principal_from_context()`；删除 Phase 0 中“不映射 is_internal”的说明。

### Step 6：导出与文档

修改 `deerflow/authz/__init__.py` 导出 builder。向 implementation notes 的决策日志
追加 Phase 1A-1 记录，不改写 Phase 0 历史。

### Phase 1A-1 验收

- 删除 Gateway 对 `is_internal` 的直接赋值后，防伪测试必须失败。
- 普通请求无法从 `body.context` 或 `body.config` 注入 `channel_user_id`，内部认证 IM
  请求只保留顶层 `body.context` 的 sender id。
- 删除任意一段 subagent 传递后，继承测试必须失败。
- Gateway、subagent、adapter 得到的身份字段一致。
- 没有 Layer 1/Layer 2 自动接线。
- 现有 guardrail、Gateway、subagent 测试全部通过。

## 5. PR Phase 1A-2：内置 RBAC 与 provider factory

建议标题：

```text
feat(authz): add built-in RBAC provider and provider factory
```

前置：Phase 1A-1 已合并或当前分支已 rebase 到其提交。

### Step 1：先写失败测试

新增 `backend/tests/test_rbac_authorization_provider.py`：

- wildcard、布尔 allow、列表 allow、空列表、allow 缺失。
- deny 优先于所有 allow 形式。
- 资源配置缺失时不限制。
- `tool -> tools` 等显式资源映射。
- 未知角色和缺失角色抛异常，绝不返回 allow。
- 非法 roles、role policy、resource policy、allow/deny 类型和非字符串成员。
- `authorize()` 与 `aauthorize()` 决策一致。
- `filter_resources()` 与逐项 `authorize()` 结果一致。
- 过滤保持 candidates 顺序和重复项，不增加输入中不存在的资源。
- 构造后修改原配置不会改变 provider 行为。

新增 `backend/tests/test_authorization_runtime.py`：

- disabled 时直接返回 `None`，且不尝试 import 无效 class path。
- enabled 但 provider 缺失时抛明确错误。
- 路径不存在、目标不是 class、构造失败时错误包含 class path 并保留异常链。
- 实例不符合 `AuthorizationProvider` Protocol 时明确失败。
- provider factory 不注入 `fail_closed` 或 `default_role`。
- 内置 RBAC 能通过相同标准路径解析，不写特殊分支。

### Step 2：实现 RBAC provider

新增：

```text
backend/packages/harness/deerflow/authz/rbac.py
```

要求：

- 构造时完成全部配置校验和规范化。
- allow/deny 预编译为不可变集合或明确的“全部/全部拒绝”标记。
- 请求路径只做 O(1) membership 和 O(n) candidates 遍历。
- 返回稳定 reason code；拒绝消息包含 role、resource、target，但不包含敏感配置。
- `filter_resources()` 保持输入顺序，不修改输入列表。
- 不读取全局 config，不处理 `fail_closed`，不二次应用 `default_role`。

### Step 3：实现 provider factory

新增：

```text
backend/packages/harness/deerflow/authz/runtime.py
```

接口：

```python
def resolve_authorization_provider(
    config: AuthorizationConfig,
) -> AuthorizationProvider | None:
    ...
```

固定顺序：

1. `enabled=False`：立即返回 `None`。
2. `enabled=True` 且 provider 缺失：抛 `ValueError`。
3. 使用 `resolve_variable(path, expected_type=type)` 解析 class。
4. 只用 `provider.config` 中显式提供的 kwargs 构造实例。
5. 使用 `isinstance(instance, AuthorizationProvider)` 做结构校验。
6. 包装错误时包含 class path、保留 `raise ... from err`，不打印 kwargs。

factory 不缓存 provider。Phase 1B 在每次 agent build 时解析一次，并把同一个实例传给
Layer 1 和 Layer 2。

### Step 4：导出与文档

修改 `deerflow/authz/__init__.py` 导出 RBAC provider 和 factory。向 implementation
notes 追加 Phase 1A-2 决策记录。

Phase 1A-2 不修改 `config.example.yaml`：在执行层尚未接线时展示“启用 RBAC”的用户配置
会造成已经生效的错觉。完整 RBAC 示例随 Phase 1B enforcement 一起加入；届时同时搜索
Helm values 和相关文档镜像。Phase 1A 不改变配置 schema，因此不 bump `config_version`。

### Phase 1A-2 验收

- 未知角色无法静默放行。
- deny 在 `authorize` 和 `filter_resources` 中都优先。
- 内置和自定义 provider 走相同 factory 路径。
- disabled 路径不 import、不构造 provider。
- provider 配置在构造后不可被外部可变引用改变。
- 没有 Layer 1/Layer 2 自动接线。

## 6. 测试与检查命令

每个 PR 按 TDD 顺序执行：先提交/观察失败测试，再实现到通过。

```powershell
cd backend
uv run pytest tests/test_authorization_principal.py -q
uv run pytest tests/test_authorization_provider.py tests/test_gateway_services.py -q
uv run pytest tests/test_rbac_authorization_provider.py tests/test_authorization_runtime.py -q
uv run pytest tests/test_harness_boundary.py -q
uv run ruff check packages/harness/deerflow/authz app/gateway/services.py tests
uv run ruff format --check packages/harness/deerflow/authz app/gateway/services.py tests
```

提交前再运行 `make test`；如果全量测试受环境依赖阻塞，PR 描述必须列出已运行命令、
通过结果和具体阻塞，不得只写“tests passed”。

## 7. Phase 1A 明确不做

- Lead agent、native subagent、embedded client 的 Layer 1 工具过滤。
- `DeferredToolCatalog` 和 `tool_search` 的授权集成。
- Layer 2 `GuardrailMiddleware` 自动装配以及与显式 guardrail 的组合顺序。
- `DeerFlowClient` 现有 skill filter 缺口修复。
- route、model、skill、sandbox、MCP server 的实际授权接线。
- provider 缓存、跨 build singleton 或热更新生命周期优化。
- 前端权限展示。

这些工作进入 Phase 1B 或后续独立 PR；Phase 1A 不提前加入未被消费的执行逻辑。

## 8. Phase 1B 前置验收清单

- [ ] Principal 的每个字段都有明确权威来源。
- [ ] Gateway 的服务端字段不可通过两个 config section 伪造。
- [ ] lead/subagent/adapter 使用同一 builder 语义。
- [ ] 未知角色、非法策略和 provider 构造失败均有明确异常。
- [ ] RBAC 的同步、异步、批量过滤结果一致。
- [ ] Phase 1A-1 与 1A-2 的决策已追加到 implementation notes。
- [ ] 分支已 rebase 最新 upstream/main。
- [ ] 未提前修改配置版本号。

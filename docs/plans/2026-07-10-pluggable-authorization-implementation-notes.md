# 可插拔授权系统实施记录

<!-- Language: Chinese. This document is the cumulative handoff record for the
     pluggable authorization system (RFC #4063). An English summary is provided
     below for navigation; the detailed content is in Chinese. -->

> **English summary:** This is the cumulative implementation log for the
> pluggable authorization RFC ([#4063](https://github.com/bytedance/deer-flow/issues/4063)).
> It records merged contracts, reviewer-confirmed decisions, and required
> regression coverage for each phase. Sections:
> - **每个 RFC PR 的必读要求** — Pre-PR checklist for every authorization change
> - **信息优先级** — Information precedence when sources conflict
> - **Phase 0：已合并基线** — Phase 0 merged baseline (PR #4127)
> - **PR #4127 多轮修改的原因** — Root causes of multi-round review iterations
> - **所有后续阶段必须保持的不变量** — Invariants all phases must preserve
> - **Phase 1 实施前确认** — Phase 1 pre-implementation confirmations
> - **每次更新 PR 前的固定清单** — Fixed checklist before each PR update
> - **决策日志** — Append-only decision log
> - **当前连续性风险** — Current continuity risks

本文档是可插拔授权 RFC（[#4063](https://github.com/bytedance/deer-flow/issues/4063)）
的持续实施记忆。它用于补充设计 RFC，记录已经实际合并的内容、review 中确认的契约，
以及每个后续 PR 必须验证的事项。

## 每个 RFC PR 的必读要求

修改任何后续阶段前，必须阅读：

1. [设计 RFC](2026-07-10-pluggable-authorization-rfc.md)。
2. 本实施记录。
3. 前一阶段已经合并的代码和测试。如果它们与旧 RFC 示例不一致，以已合并契约为准。

每个 PR 描述中必须复制并确认以下内容：

```markdown
## Authorization RFC 连续性确认

- [ ] 已阅读 `docs/plans/2026-07-10-pluggable-authorization-rfc.md`。
- [ ] 已阅读 `docs/plans/2026-07-10-pluggable-authorization-implementation-notes.md`。
- [ ] 已核对所有前置阶段的决策和延期事项。
- [ ] 已用本 PR 的新决策和后续事项更新实施记录。
```

## 信息优先级

不同来源发生冲突时，按以下顺序判断：

1. 已合并代码和回归测试。
2. 已接受的 review 决策和最终合并的 PR 描述。
3. 本实施记录。
4. 设计 RFC 中较早的示例或阶段划分。

不能静默修改或重新解释冲突。必须写入决策日志；涉及架构或安全行为时，还要在
issue #4063 中确认。

## Phase 0：已合并基线

PR [#4127](https://github.com/bytedance/deer-flow/pull/4127) 于 2026-07-15
以提交 `1300c6d3` 合并，确立了以下契约：

- `AuthorizationProvider` 是可在运行时检查的 Protocol，包含同步授权、异步授权和
  `filter_resources`。
- `filter_resources` 是必需方法。Protocol 中方法体为 `...` 不代表存在默认实现。
  没有静态映射的 provider 必须自行实现逐项授权。
- `GuardrailAuthorizationAdapter` 有意让 provider 异常向上传播。
  `GuardrailMiddleware` 统一负责异常处理、审计以及 fail-open/fail-closed 执行。
- 不能通过 `user_role == "internal"` 推导 `Principal.is_internal`。权威信号是内部
  认证状态 `auth_source`，必须从 Gateway 上下文传递。
- Adapter 上下文保留 `thread_id`、`run_id`、`tool_call_id`、`tool_input`、
  `is_subagent`、`agent_id` 和 `timestamp`。
- `AuthorizationConfig` 已加入 AppConfig，默认 `enabled: false`，并参与 singleton
  加载；Phase 0 尚无运行时代码读取它。
- Adapter 在结构上符合 `GuardrailProvider`；同步和异步异常传播均由测试固定。

以下原 RFC Phase 0 项目没有在 PR #4127 中落地，仍属于后续工作：Principal 构建器、
内置 RBAC provider、Layer 1 过滤、Layer 2 自动装配和内部 Principal 填充。

## PR #4127 多轮修改的原因

实现方向获得认可，但首版没有完整验证后续阶段将继承的关键契约：

- 直接沿用了 RFC 关于 `filter_resources` 默认行为的假设，没有先验证 Python
  Protocol 的真实语义。willem-bd 和 zhfeng **独立**指出了同一个问题——多个 reviewer
  从不同角度指向同一处，说明该缺陷在 review 中非常显眼。后续阶段中如果再次出现
  多人独立指出同一处，应当视为最高优先级，不再需要多方确认。
- 身份字段按照表面数据结构映射，没有追踪到运行时权威来源。
- 配置测试验证了 Pydantic 对象构建，但最初绕过了真实 singleton 加载生命周期。
- schema 变化最初遗漏 `config_version`；同时主线发生版本竞争，需要 rebase 后重新
  选择版本号。
- Helm 中的配置版本镜像和仓库内 RFC 文档较晚才在 review 中被发现。
- 代码、测试、注释和 PR 描述没有在同一次 push 中同步，导致旧描述让已修问题再次
  被提出。
- 对 `GuardrailMiddleware` 已有的 fail-closed 机制理解不足，在 adapter 中写了
  "Phase 1 加 try/except" 的 TODO，暗示 adapter 应当自行处理异常。实际上 fail-closed
  是 middleware 的职责，adapter 刻意不 catch 异常。描述与架构意图不一致导致了额外的
  review 轮次。

这些问题主要是实施前检查和可追踪性不足，并非两层授权设计被否定。

## 所有后续阶段必须保持的不变量

- `authorization.enabled: false` 必须保持现有行为不变。
- Layer 1 和 Layer 2 必须使用同一个 provider 和同一个 Principal。
- Layer 1 必须在 `assemble_deferred_tools` 之前过滤；被移除的工具不能进入
  `DeferredToolCatalog`，也不能被 `tool_search` 再次提升。
- Layer 1 必须覆盖 lead agent、native subagent 和 `DeerFlowClient` 三条装配路径。
- Layer 2 复用 `GuardrailMiddleware`；不能在 adapter 中重复实现异常处理、审计、
  deny 消息或 fail-closed 逻辑。
- ownership 检查和现有 `require_admin_user()` 管理端点保护必须保留。细粒度授权只能
  增加策略，不能削弱现有保护。
- deny 优先于 allow。身份缺失、未知角色、provider 故障和 provider 返回值格式错误
  都必须具有明确且经过测试的行为。
- 同步和异步路径必须具有一致的授权决策和失败语义。
- internal、Web、关闭认证、已绑定频道、未绑定频道、scheduler 和 subagent 的身份
  都必须从真实来源追踪。
- 新增 resource 或 action 时，必须检查所有消费者、allowlist、配置示例、文档和测试。
- 新组件嵌入现有中间件前，必须先完整理解宿主中间件已有的机制（异常处理、审计、
  fail-closed 等）。新组件不重复实现宿主已有的逻辑；如果看似缺少某功能，先确认是
  否由宿主在上游或下游统一处理。

## Phase 1 实施前确认

Phase 1 是工具授权。编码前必须先确定：

- Principal 在哪里构建，以及如何进入三条工具装配路径。
- `auth_source`、owner role、`default_role` 和 subagent 继承如何组合。
- provider 如何实例化，以及配置热更新后如何刷新。
- authorization 与显式配置的 guardrail 如何共存，二者都不能静默替换或绕过对方。
- provider 构造异常和授权决策异常是否使用同一 fail-closed 策略，以及各自由哪层处理。
- 内置 RBAC provider 对 allow、deny 和通配符的精确定义。

Phase 1 最低验证要求：

- 每角色 allow、deny、通配符、deny 优先、未知角色和默认角色测试。
- lead agent、subagent 和 embedded client 的工具可见性测试。
- 证明被拒绝工具不会进入 deferred catalog。
- Layer 2 的 allow、deny、provider 异常、审计、同步和异步测试。
- prompt injection 回归测试，证明装配阶段被过滤的工具无法执行。
- internal、未绑定频道、关闭认证和 subagent 的 Principal 测试。
- 通过真实生命周期执行 AppConfig 加载与热更新测试。
- 证明关闭 authorization 时现有工具集合完全不变。

## 每次更新 PR 前的固定清单

- [ ] 选择配置版本号前，已 fetch 并 rebase 最新 `upstream/main`。不能使用本地缓存的
      旧版本号——主线可能在此期间已被其他 PR bump 过。先 fetch、读最新值、+1，再在
      `config.example.yaml` + `deploy/helm/deer-flow/values.yaml` + `deploy/helm/deer-flow/README.md`
      三处同步。
- [ ] 已搜索 issue #4063 和当前阶段是否存在并行工作。
- [ ] 每个新字段都已追踪到权威生产者，而不只是确认类型。
- [ ] 测试经过公开运行时生命周期，而不只是直接构造配置模型。
- [ ] 已按需覆盖 lead、subagent、embedded、同步和异步路径。
- [ ] 已执行负向变异检查：删除新增 wiring 后，至少一个回归测试必须失败。
- [ ] 已搜索配置的所有镜像，包括 Helm values 和相关文档。
- [ ] 代码注释、测试、RFC 记录和 PR 描述已在同一次 push 中更新。
- [ ] 已明确列出延期阶段，且没有把延期功能带入当前范围。
- [ ] 已在下方记录新决策和未解决问题。
- [ ] 如果多个 reviewer 独立指出同一处问题，视为高置信信号，立即修复，不再等待
      进一步确认。

## 决策日志

只追加新记录。需要推翻旧决策时，必须新增一条“替代决策”，不能直接重写历史。

### 2026-07-15 — Phase 0 / PR #4127

- **决策：** `filter_resources` 为必需方法，不提供 Protocol fallback。
- **决策：** provider 异常穿过 adapter，由 `GuardrailMiddleware` 处理。
- **决策：** internal 身份来自认证上下文，不使用角色名称约定推导。
- **决策：** Phase 0 默认保持运行时行为不变。
- **延期：** Principal 构建、RBAC provider、两层执行接入和 internal Principal 传递
  移至 Phase 1。

### 2026-07-15 — Phase 1A-1 / 可信 Principal 链路

- **背景：** Phase 0 建立了 `AuthorizationProvider` Protocol 和 adapter，但
  `Principal.is_internal` 无可信来源，adapter 手工构造 Principal（与未来 Layer 1 的
  builder 不一致），客户端可伪造身份字段。
- **决策：** `build_principal_from_context()` 是唯一 Principal builder，Layer 1 和
  Layer 2（adapter）必须共用。
- **决策：** `is_internal` 来自 `request.state.auth_source == AUTH_SOURCE_INTERNAL`，
  在 `inject_authenticated_user_context` 最顶部（所有 early return 之前）用直接赋值
  写入 runtime context，不用 `setdefault`。
- **决策：** `is_internal`、`authz_attributes` 和 `channel_user_id` 列为
  `_SERVER_OWNED_AUTHZ_CONTEXT_KEYS`，
  从 `config["context"]` 和 `config["configurable"]` 清除客户端值。
- **决策：** `channel_user_id` 只接受内部认证 IM 调用方的顶层 `body.context` 值；普通
  session 调用和 `body.config` 两个 section 均不能提供该授权身份字段。
- **决策：** Phase 1A-1 没有 Gateway 侧 `authz_attributes` 权威生产者；Gateway 请求中
  的 `authz_attributes` 一律删除（默认 `{}`）。
- **决策：** adapter 的 `evaluate`/`aevaluate` 通过 `build_principal_from_context()`
  构造 Principal，接收 `default_role` 参数。
- **决策：** `authz_attributes` 在所有进程内消费边界统一使用 `isinstance(x, Mapping)`
  + `dict()` 复制；非 Mapping 抛 `TypeError`。
- **决策：** subagent 的 `is_internal` 无条件写回 context（包括 `False`）。
- **证据：** 323 个目标与边界测试通过，覆盖 Gateway 防伪、channel sender 信任边界、subagent 继承、
  `GuardrailMiddleware` runtime 字段映射、adapter builder 复用和 harness/app 边界。
- **兼容性：** `authorization.enabled: false` 时工具集合和执行决策不变；runtime context
  新增 `is_internal` 字段是有意的可观察变化。
- **延期：** RBAC provider、provider factory、Layer 1 过滤、Layer 2 自动接线移至
  Phase 1A-2 / Phase 1B。

### 2026-07-17 — Phase 1A-2 / 内置 RBAC provider 与 provider factory

- **背景：** Phase 1A-1 建立了可信 Principal 链路，但没有策略引擎。
  Phase 1A-2 实现内置 RBAC provider 和统一 provider factory。
- **决策：** `RbacAuthorizationProvider` 在构造时完成全部配置校验并编译为
  不可变结构（`frozenset` / sentinel `_ALL`）。请求路径只做 O(1) membership 检查。
- **决策：** deny 永远优先于 allow，无论 allow 是 `"*"`、`True`、列表还是缺失。
- **决策：** 未知角色和缺失角色抛 `ValueError`（不返回 allow），由执行层
  根据 `fail_closed` 决定。
- **决策：** 资源名使用显式映射（`tool → tools`，`model → models` 等），
  不通过加 `s` 猜测。配置中的保留请求别名（如 `tool`）在构造期拒绝，并提示使用
  对应配置键（如 `tools`），防止策略被存储在永远无法命中的键下。未知 resource
  使用原名查找；未配置时视为"不受限"。
- **决策：** `resolve_authorization_provider()` 是唯一 provider 解析入口。
  disabled 时返回 `None`（不 import provider 模块）；enabled 但缺少 provider
  时抛 `ValueError`。不缓存实例。不注入 `fail_closed` 或 `default_role`。
- **决策：** 内置和自定义 provider 使用完全相同的 `resolve_variable` class-path
  解析路径，无特殊分支。
- **证据：** 66 tests passed（51 RBAC + 15 factory，其中 5 条为 malformed-policy
  回归测试）。
- **兼容性：** 无运行时行为变化（`authorization.enabled: false`）。不修改
  `config.example.yaml`，不 bump `config_version`。
- **延期：** Layer 1 工具过滤、Layer 2 自动接线、DeerFlowClient、RBAC 配置示例
  移至 Phase 1B。
- **Phase 1B 注意：** 已知角色缺少某个 resource policy 时语义是“不受限”，不是
  fail-closed。配置示例必须明确提醒，并枚举部署方希望限制的每种 resource。
- **Phase 1B 注意：** 内置 RBAC 当前按 role + resource + target 决策，不区分
  `AuthzRequest.action`；`policy_id` 也是稳定但粗粒度的
  `rbac:allow` / `rbac:deny` / `rbac:unrestricted`。接入审计日志前应决定是否通过
  更具体的 policy id 或 decision metadata 记录 role / resource / target。

### 2026-07-20 — Phase 1A-2 / PR #4260 请求边界收口

- **背景：** review 发现 `request.target` 未经运行时校验；通配符策略会允许
  `None` 或空字符串，而列表策略会拒绝，形成依赖策略形态的不一致结果。进一步审查
  发现无效 resource 和批量过滤候选项也存在相同的“不受限/通配符路径放行”风险。
- **决策：** 内置 RBAC 在请求边界要求 resource、resource type、target 和每个
  candidate 都是非空字符串；`filter_resources()` 还要求 candidates 是 list。
  非法输入统一抛 `ValueError`，不能进入 `rbac:unrestricted` 或通配符 allow 路径。
- **决策：** `filter_resources()` 对缺失/未知角色继续与 `authorize()` 一致地抛
  `ValueError`，不在 provider 内静默返回空列表。Phase 1B 集成层负责按
  `fail_closed` 处理 provider 异常，避免隐藏身份或部署配置错误。
- **证据：** 90 tests passed（75 RBAC + 15 factory），覆盖 unrestricted、
  wildcard、allow-list、同步/异步、非法 resource/target/candidates，以及
  `filter_resources()` 的缺失/未知角色错误语义。
- **兼容性：** 只拒绝不符合 `AuthzRequest` / `filter_resources` 类型契约的运行时
  输入；Phase 1A-2 仍未接入运行时，`authorization.enabled: false` 行为不变。

### 2026-07-22 — Phase 1B / 工具授权执行接入

- **背景：** Phase 1A 完成了 Principal 链路、RBAC provider 和 factory。
  Phase 1B 将 provider 接入 Layer 1（组装时过滤）和 Layer 2（执行时拦截）。
- **决策：** `apply_tool_authorization()` 是 Layer 1 的统一入口，组合 provider
  解析、Principal 构建和 `filter_tools_by_authorization` 过滤。disabled 时返回
  原始工具和 `None`。
- **决策：** Layer 1 过滤在 `assemble_deferred_tools` 之前执行，覆盖三条路径：
  lead agent（bootstrap + default）、subagent、embedded client。
- **决策：** Layer 2 通过 `GuardrailAuthorizationAdapter` 复用 `GuardrailMiddleware`，
  authorization middleware 在显式 guardrail 之前（外层），两者独立运行。
- **决策：** Layer 1 和 Layer 2 尝试共享同一个 provider 实例（"resolve once per
  build"）。subagent 通过 `_authz_provider` 属性传递。
- **决策：** Embedded client `_agent_config_key` 加入 `user_role` 和 `is_internal`
  作为 cache key，角色变化时强制重建 agent。
- **兼容性：** `authorization.enabled: false` 时工具集合和执行决策完全不变。
- **延期：** Models/Skills/Sandbox 权限（Phase 2+）；route-level 迁移。

#### Phase 1B review 收口

- Layer 1 的候选集合必须包含本次 build 最终可能暴露给模型的全部业务工具；
  `describe_skill` 和 memory tools 因此在授权过滤前加入，过滤后才进行 deferred
  assembly。框架生成的 `tool_search` 仍是受已过滤 catalog 约束的基础设施工具。
- lead、bootstrap、native subagent 和 embedded client 都把 Layer 1 解析出的同一
  provider 实例传给 Layer 2，禁止在 middleware 构建时再次解析 provider。
- `tool_search` 仅在当前 build 确实生成了 deferred catalog 时作为基础设施工具跳过
  authorization adapter 的第二次 provider 调用；catalog 已由 Layer 1 过滤。显式配置的
  guardrail 仍会检查它，没有 deferred setup 的普通同名工具也不获得豁免。
- 内置 RBAC provider 在解析时校验 `authorization.default_role` 属于已配置角色，配置
  错误直接阻止 agent 构建，不再表现为难以诊断的空工具集合。
- `DeerFlowClient.stream()` 的调用方属于可信进程内边界，可通过关键字参数传入与
  Gateway runtime context 相同的授权身份字段；这些字段同时进入真实执行 context。
  agent cache key 使用完整 Principal（包括 user/channel/oauth/internal/attributes），
  并深拷贝嵌套 attributes，防止调用方原地修改身份数据后复用旧工具集合。
- disabled 模式仍在 Layer 1 候选阶段包含 `describe_skill` / memory tools，但 deferred
  assembly 后恢复原有顺序（业务工具、`tool_search`、late framework tools）。
- 回归测试必须经过真实 lead/bootstrap、subagent 和 embedded 组装函数，不能只测试
  `filter_tools_by_authorization()` helper；同时断言被拒绝工具不在最终 bound tools 中，
  且 Layer 2 收到的 provider 与 Layer 1 为同一对象。

### 新记录模板

```markdown
### YYYY-MM-DD — Phase N / PR #NNNN

- **背景：** 本次变化或 review 发现了什么？
- **决策：** 新的正式契约是什么？
- **证据：** 相关代码路径、测试、issue 评论或 benchmark。
- **否决方案：** 考虑过哪些方案，为什么不采用？
- **兼容性：** 如何保持现有部署和关闭功能时的行为？
- **延期：** 哪些工作留给下一阶段？
```

## 当前连续性风险

- 原始 RFC 仍包含“`filter_resources` 存在默认实现”的草案示例；本文件记录的已合并
  Phase 0 契约优先于该示例。
- RFC 原始 Phase 0 范围大于 PR #4127 的实际落地范围。后续实现必须依据已合并基线
  和明确延期清单，不能假设这些功能已经存在。
- 主线配置版本可能并发变化。不能提前占用版本号；必须先 rebase，再在所有镜像文件中
  使用下一个有效版本。

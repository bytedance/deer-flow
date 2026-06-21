# 缺陷闭环 Agent 未提交改动风险说明

本文用于说明当前分支中，为新增 `defect-workflow-closure` 内置 Agent 引入的未提交改动，以及这些改动是否可能影响除新“缺陷闭环”之外的已有功能。

## 总体结论

当前未提交内容不完全局限于 `agents/builtin/defect-workflow-closure/` 目录。为了让新 Agent 能展示闭环平台待办、注入当前缺陷上下文、调用 EHM/InS 设备能力和监测数据能力，代码同时改动了一些共享基础设施。

从当前 diff 看，没有发现会直接破坏其他功能的明显问题；大部分改动是加法，或通过 `agent_name === "defect-workflow-closure"`、`data_tools`、`visibility` 等条件开关限制影响面。但因为部分改动位于共享路径，提交前仍建议做针对性回归。

## 风险点 1：InS 数据能力共享适配器被改动

风险等级：中等

涉及文件：

- `backend/packages/harness/deerflow/integrations/adapters/ins/client_bridge.py`
- `backend/packages/harness/deerflow/agents/lead_agent/agent.py`
- `agents/builtin/defect-workflow-closure/config.yaml`

### 为什么需要这个改动

新的“缺陷闭环”Agent 不只处理缺陷待办，也需要辅助用户查询设备相关资料。第二阶段已经将以下能力放入该 Agent 的受控清单：

- `monitoring_get_trend`
- `monitoring_get_alarm_history`

这些工具底层走 InS integration 和 `features-tool`。为了让新 Agent 能按当前登录用户的权限调用这些工具，适配器需要支持基于当前请求或运行上下文中的用户 token 创建 `InsApiClient`。

原先的模式更偏向在适配器初始化时创建一个 features-tool client。如果多用户共享同一个 client，存在两个隐患：

- 工具调用可能没有使用当前登录用户的 token。
- 不同用户之间可能复用同一个 token，造成权限串用。

因此这次调整为：适配器初始化时只校验 features-tool 是否可加载，真正调用趋势、报警、波形等能力时，再根据传入的 `Authorization` 或上下文 token 获取 client。

同时还增加了 features-tool 路径探测逻辑，兼容服务器 Docker 环境中 `/app/skills`、`/mnt/skills` 或 `FEATURES_TOOL_ROOT` 等不同挂载路径。

### 影响面

这个改动不是新 Agent 私有的。只要其他功能也通过 `InsClientBridge` 调用 InS integration，就可能经过同一段代码。例如：

- 趋势数据查询
- 报警历史查询
- 波形数据查询
- 轴心轨迹查询
- 其他依赖 features-tool 的 InS 数据能力

### 当前缓解措施

- 新 Agent 只通过 `data_tools` 显式加载 `monitoring_get_trend` 和 `monitoring_get_alarm_history`。
- `lead_agent` 中的 data tools 装配逻辑只有在 Agent 配置了 `data_tools` 时才执行。
- token 按调用上下文获取，方向上更符合多用户权限隔离。
- 已在测试环境验证过 `monitoring_get_alarm_history` 可正常返回“未找到报警记录”。

### 建议回归

- 使用原有监测/分析类 Agent 查询一次趋势。
- 使用原有监测/分析类 Agent 查询一次报警历史。
- 若现有功能支持波形或轴心轨迹，至少验证一次工具是否仍能加载并发起请求。

## 风险点 2：聊天发送链路有全局改动

风险等级：中等

涉及文件：

- `frontend/src/core/threads/hooks.ts`
- `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`
- `frontend/src/components/workspace/messages/message-list-item.tsx`

### 为什么需要这个改动

用户点击缺陷详情后，页面上选中的缺陷详情、当前节点、设备信息和表单数据需要进入模型上下文。否则用户继续问“当前选中缺陷绑定的设备 id 是什么”时，模型不知道页面选中的对象。

为了解决这个问题，前端在“缺陷闭环”Agent 中维护当前选中缺陷上下文，并在用户发送消息时：

- UI 上展示用户原始输入。
- 实际提交给模型的文本中追加 `<defect_workflow_selected_context>` 上下文块。
- 通过 `display_text` 避免这些内部上下文显示在用户消息气泡里。

### 影响面

`sendMessage` 的实现位于通用 hook 中，不是新 Agent 私有文件。因此理论上所有聊天发送都会经过这段逻辑。

不过目前只有 `defect-workflow-closure` 页面分支会传入 `model_text`。普通 Agent 不传 `model_text` 时，`getModelText()` 会回退到用户原始文本。

### 当前缓解措施

- 追加上下文的逻辑被 `agent_name === "defect-workflow-closure"` 限制。
- 通用 `sendMessage` 默认行为保持：没有 `model_text` 就使用用户输入文本。
- `message-list-item` 中增加了内部上下文清理逻辑，避免模型上下文泄漏到 UI。

### 建议回归

- 普通 Agent 新建对话并发送消息。
- 普通 Agent 进入已有线程继续发送消息。
- 带附件发送消息。
- Deep link 自动发送场景。

## 风险点 3：Agent 列表和导航过滤逻辑改动

风险等级：低到中等

涉及文件：

- `agents/builtin/defect-closure/config.yaml`
- `backend/packages/harness/deerflow/config/agents_config.py`
- `backend/app/gateway/routers/agents.py`
- `frontend/src/core/agents/hooks.ts`
- `frontend/src/components/workspace/agent-selector.tsx`
- `frontend/src/components/workspace/agents/agent-gallery.tsx`
- `frontend/src/components/workspace/workspace-nav-chat-list.tsx`

### 为什么需要这个改动

需求要求弃用旧的内置 Agent `defect-closure`，但不能删除或改坏旧逻辑，因为旧 Agent 可能仍被其他历史线程、deep link 或内部逻辑引用。

因此当前做法是：

- 保留旧 `defect-closure` 配置和能力。
- 给旧 Agent 增加 `visibility: hidden`。
- 前端导航、Agent 选择器、Agent gallery 只展示 visible Agent。
- 新增 `defect-workflow-closure`，显示名仍为“缺陷闭环”。

这样用户在左侧导航中看到的是新“缺陷闭环”，旧 Agent 不再作为入口出现。

### 影响面

Agent 可见性是全局展示机制。任何 Agent 如果配置了 `visibility: hidden`，都会从导航和选择器中隐藏。

默认值是 `public`，所以未配置 `visibility` 的已有 Agent 理论上不受影响。

### 当前缓解措施

- 只给旧 `defect-closure` 显式配置了 `visibility: hidden`。
- 后端 `AgentConfig` 和 API response 默认 `visibility = "public"`。
- 前端过滤逻辑只判断 `visibility !== "hidden"`。
- 隐藏只影响展示入口，不等于删除 Agent。

### 建议回归

- 左侧导航中原有 Agent 是否仍显示。
- Agent selector 是否仍能列出其他 Agent。
- Agent gallery 是否仍能列出其他 Agent。
- 旧历史对话如果路径里带 `defect-closure`，是否还能打开。

## 风险点 4：GenUI 基础设施增加新组件和持久块逻辑

风险等级：低

涉及文件：

- `frontend/src/core/genui/registry.ts`
- `frontend/src/core/genui/sanitizer.ts`
- `frontend/src/core/genui/validator.ts`
- `frontend/src/core/genui/store.ts`
- `frontend/src/components/genui/DefectWorkflowTodoListBlock.tsx`
- `frontend/src/components/genui/DefectWorkflowTaskDetailBlock.tsx`

### 为什么需要这个改动

新的“缺陷闭环”Agent 不是纯文本问答。它需要在对话区域直接展示：

- 缺陷待办列表。
- 缺陷详情。
- 当前节点表单。
- 历史处理记录。
- 认领、通过、驳回、取消等操作按钮。

因此需要新增两个 GenUI 组件：

- `defect-workflow-todo-list`
- `defect-workflow-task-detail`

同时，用户发送普通问题后，页面上的待办列表和当前详情不应该被模型新回复冲掉，所以 GenUI store 增加了 `metadata.source === "agent-home"` 的本地持久块保留逻辑。

### 影响面

新增组件注册、props allowlist、props schema 基本是加法，风险较低。

需要注意的是 `store.ts` 的持久块逻辑是共享的。如果未来其他 GenUI 组件也使用 `metadata.source === "agent-home"`，它也会获得同样的“同线程替换时不清除”行为。

### 当前缓解措施

- 目前只有新缺陷闭环入口创建 `source: "agent-home"` 的本地块。
- 新组件 props 已加入 sanitizer 和 validator。
- 组件名是独立命名，不会覆盖已有组件。

### 建议回归

- 原有 GenUI 组件是否仍能正常渲染。
- 同一线程中普通模型回复是否仍会替换旧 GenUI 块。
- 新缺陷闭环中，发送问题后待办列表和当前详情是否仍能保留。

## 风险点 5：全局运行配置 `config.yaml` 被修改

风险等级：中等

涉及文件：

- `config.yaml`
- `config.example.yaml`
- `agents/builtin/defect-workflow-closure/config.yaml`

### 为什么需要这个改动

新 Agent 需要两个工业资产上下文工具：

- `resolve_component_context`
- `resolve_machine_context`

所以 `config.yaml` 中新增了：

- `industrial:asset` tool group。
- `resolve_component_context` 工具注册。
- `resolve_machine_context` 工具注册。

同时，新 Agent 要调用报警历史能力，因此 integration routes 中新增：

- `monitoring.alarm_history: ins_prod`

`config.example.yaml` 也补充了相同方向的示例配置，便于后续环境配置参考。

### 影响面

`config.yaml` 是运行配置，不是普通业务代码。它可能包含本地或服务器环境的差异配置。若部署时整文件覆盖服务器现有 `config.yaml`，可能误覆盖服务器上已经手工配置好的模型、租户、认证、外部系统地址等内容。

### 当前缓解措施

- 新增工具本身是显式工具注册，不会自动进入所有 Agent。只有配置了 `tool_groups: industrial:asset` 的 Agent 才会获得这些工具。
- 新 Agent 单独配置了 `tool_groups: industrial:asset`。
- `config.example.yaml` 只作为示例。

### 建议回归和部署注意事项

- 部署时按 diff 合并 `industrial:asset`、两个工具、`monitoring.alarm_history` 路由，不要直接整文件覆盖服务器配置。
- 确认服务器 `ins_prod` integration 已启用且使用 user token。
- 确认服务器 features-tool 路径可被 `FEATURES_TOOL_ROOT` 或默认路径探测到。

## 风险点 6：新增 EHM/闭环平台代理 API

风险等级：低

涉及文件：

- `backend/app/gateway/app.py`
- `backend/app/gateway/routers/defect_workflow.py`
- `backend/app/gateway/routers/component.py`

### 为什么需要这个改动

前端页面不能直接绕过 AI 工作台调用多个平台接口，因此在 gateway 中新增代理接口：

- `/api/defect-workflow/*`：代理闭环平台和流程中心接口。
- `/api/component/*`：代理 EHM/InS 设备、部件、测点上下文查询。

这些接口负责透传当前登录用户 token，并把调用统一收口到 AI 工作台 gateway。

### 影响面

新增路由挂载在独立前缀下，不会抢占已有路径：

- `/api/defect-workflow`
- `/api/component`

因此对已有 API 的路径冲突风险较低。

### 当前缓解措施

- 路由前缀独立。
- 上游异常转换为 401/403/404/409/422 或 502，不影响其他 router。
- 用户 token 不存在时直接 401，不会使用固定管理员凭证。

### 建议回归

- gateway 启动是否正常。
- 原有 `/api/machine`、`/api/point`、`/api/organize` 等接口是否仍正常。
- 新 `/api/defect-workflow/tasks/todo` 和 `/api/component/context` 是否能按 user02 权限返回数据。

## 风险点 7：未跟踪文档和 OpenSpec 变更记录

风险等级：低

涉及内容：

- `AGENTS.md`
- `openspec/changes/add-defect-workflow-closure-agent/`

### 为什么需要关注

这些文件不是运行时代码，但会影响提交内容的边界。

`AGENTS.md` 看起来是协作说明或 Codex 工作说明。如果这是项目需要长期保留的说明文件，可以提交；如果只是本地辅助文件，则不建议混入业务提交。

`openspec/changes/add-defect-workflow-closure-agent/` 是本次功能的 OpenSpec 变更记录。是否提交取决于团队是否要求保留 OpenSpec 设计和任务文件。

### 建议处理

- 如果本仓库采用 OpenSpec 流程，则提交 OpenSpec 变更记录。
- 如果不采用，则把 OpenSpec 文件从业务提交中排除。
- 明确 `AGENTS.md` 是否属于项目规范文件，再决定是否提交。

## 当前已做验证

- `git diff --check`：通过，未发现空白错误。
- Python 语法检查：对新增/修改的后端关键文件执行 `python3 -m compileall -q`，通过。
- 服务器测试环境已验证新缺陷闭环 Agent 能展示待办、详情、历史处理记录、当前节点表单。
- 已验证 `resolve_machine_context` / `resolve_component_context` 方向的设备映射逻辑。
- 已验证 `monitoring_get_alarm_history` 在测试环境无报警时返回正常无数据结论。

## 提交前建议回归清单

1. 普通 Agent 新建对话并发送消息。
2. 普通 Agent 历史线程继续发送消息。
3. 原有监测/分析 Agent 查询趋势。
4. 原有监测/分析 Agent 查询报警历史。
5. 左侧导航、Agent selector、Agent gallery 中原有 Agent 展示正常。
6. 新“缺陷闭环”打开待办、打开详情、认领任务、提交或驳回节点。
7. 新“缺陷闭环”中发送普通问题后，待办列表和当前详情仍保留。
8. 部署时确认服务器 `config.yaml` 只合并必要新增项，不整文件覆盖。

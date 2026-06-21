# 缺陷闭环 Agent 变更说明

## 背景

本次变更在 DeerFlow / EHM AI 工作台中新增一套业务逻辑不同的内置 Agent：`defect-workflow-closure`，用于接入 EHM 闭环平台的缺陷流程待办、详情查看、节点表单处理，以及依托 AI 工作台已有能力辅助用户查询设备相关信息。

原有内置 Agent `defect-closure` 不再作为左侧导航入口展示，本次新 Agent 不兼容旧 Agent 的闭环单逻辑。

## 主要功能

### 新增内置 Agent

- 新增 `agents/builtin/defect-workflow-closure/`
- Agent 展示名仍为“缺陷闭环”
- 进入该 Agent 后自动展示缺陷待办列表
- 支持点击待办行的“详情”查看当前缺陷流程信息
- 当前选中缺陷详情会进入对话上下文，用户可以继续追问设备 ID、缺陷编号、当前节点、历史处理等信息
- 支持在当前缺陷上下文下调用受控工具查询设备、部件、测点、趋势、报警等信息

### 隐藏旧缺陷闭环 Agent

- `agents/builtin/defect-closure/config.yaml` 增加 `visibility: hidden`
- 前端 Agent 列表、左侧导航、Agent Gallery 过滤 hidden Agent
- 后端 Agent API 增加 `visibility` 字段透传

## 后端变更

### 缺陷流程代理接口

新增 `backend/app/gateway/routers/defect_workflow.py`，用于 AI 工作台代理访问 EHM 闭环平台和流程中心接口：

- 缺陷待办列表
- 缺陷详情
- 当前任务表单上下文
- 认领任务
- 提交/驳回/取消当前节点操作

这些接口会复用当前登录用户的上下文，便于 user02 等业务用户按权限访问自己的缺陷待办。

### Component / 设备上下文能力

新增 `backend/app/gateway/routers/component.py` 和 `backend/packages/harness/deerflow/tools/industrial_asset_tools.py`：

- 支持根据 EHM 设备 ID 获取 `sourceDataId`
- 支持根据 `sourceDataId` / componentId 解析 InS component / machine / point 聚合上下文
- 新增工具：
  - `resolve_component_context`
  - `resolve_machine_context`

### InS RPC 适配增强

更新以下服务，补齐根据 component、machine、organize、point 查询设备上下文所需能力：

- `backend/packages/harness/deerflow/integrations/adapters/ins/client_bridge.py`
- `backend/packages/harness/deerflow/rpc/machine_service.py`
- `backend/packages/harness/deerflow/rpc/organize_service.py`
- `backend/packages/harness/deerflow/rpc/point_service.py`

## 前端变更

### 缺陷待办和详情 GenUI

新增：

- `frontend/src/components/genui/DefectWorkflowTodoListBlock.tsx`
- `frontend/src/components/genui/DefectWorkflowTaskDetailBlock.tsx`
- `frontend/src/core/defect-workflow/`

能力包括：

- 展示缺陷待办列表
- 展示当前选中缺陷的流程详情
- 展示历史处理记录
- 历史表单字段支持从流程表单上下文映射中文字段名
- 当前节点状态为“待认领”时，只展示历史处理记录和认领入口，不展示当前节点表单
- 当前节点已认领时，展示当前节点表单和可操作按钮
- 支持通过“通过 / 驳回 / 取消 / 认领”等按钮调用闭环平台接口

### 对话上下文联动

更新 `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`：

- 新缺陷闭环 Agent 进入页面时自动插入本地待办 UIBlock
- 点击缺陷详情后，将当前选中缺陷上下文注入后续模型输入
- 发送第一条消息后，从 `/chats/new` 切换到真实 thread 时保留选中缺陷详情
- 后续对话过程中保留待办列表、选中详情和历史处理记录

### GenUI 状态修复

更新 `frontend/src/core/genui/store.ts`：

- 对 `metadata.source === "agent-home"` 的本地持久块做保留
- 避免线程 reset 或后端 UIBlock 恢复时清空缺陷待办块
- 保留 `selected_task_id` 等运行态属性，防止发送问题后选中详情丢失

### Safety Block 占位消息隐藏

更新 `frontend/src/core/messages/utils.ts`：

- 隐藏后端安全中间件产生的占位消息：
  - `[Content blocked by safety policy: ...]`
- 仅隐藏整条消息为 safety block 占位文案的情况，不影响正常用户输入或助手回答

## 配置变更

### config.yaml / config.example.yaml

新增工具组和工具：

- `industrial:asset`
- `resolve_component_context`
- `resolve_machine_context`

新增/确认路由：

- `monitoring.trend: ins_prod`
- `monitoring.alarm_history: ins_prod`

### .env.example

补充 EHM / 缺陷闭环相关环境变量说明：

- `EHM_BASE_ORIGIN`
- `EHM_CLOSED_LOOP_API_PREFIX`
- `EHM_WORKFLOW_API_PREFIX`
- `EHM_SERVER_API_PREFIX`
- `EHM_CLOSED_LOOP_BASE_URL`
- `EHM_WORKFLOW_BASE_URL`
- `EHM_SERVER_BASE_URL`
- `EHM_DEFECT_WORKFLOW_TIMEOUT_SECONDS`
- `EHM_SERVER_TIMEOUT_SECONDS`
- `FEATURES_TOOL_ROOT`

## 测试覆盖

新增/更新测试：

- `backend/tests/test_component_context.py`
- `backend/tests/test_defect_workflow_router.py`
- `backend/tests/test_machine_service.py`
- `backend/tests/test_organize_service.py`
- `backend/tests/test_point_service.py`
- `frontend/tests/unit/components/genui/defect-workflow-blocks.test.ts`
- `frontend/tests/unit/core/agents/visibility.test.ts`
- `frontend/tests/unit/core/defect-workflow/converter.test.ts`
- `frontend/tests/unit/core/defect-workflow/history.test.ts`
- `frontend/tests/unit/core/messages/utils.test.ts`

本地已执行：

- `npm run typecheck`
- `npm test -- --run tests/unit/core/messages/utils.test.ts tests/unit/components/genui/defect-workflow-blocks.test.ts tests/unit/core/defect-workflow/converter.test.ts tests/unit/core/defect-workflow/history.test.ts`

结果：

- TypeScript 类型检查通过
- 相关前端单测通过

## 服务器验证

测试服务器：

- `10.0.2.233`
- DeerFlow 访问端口：`2026`

已部署并验证：

- `deer-flow-frontend` 正常运行
- `deer-flow-nginx` 正常运行
- `deer-flow-gateway` 正常运行
- `deer-flow-redis` 正常运行且 healthy

业务验证：

- user02 可以进入新“缺陷闭环” Agent
- 缺陷待办列表正常展示
- 测试缺陷 `QX20260621-C158E400` 可以查看详情
- 当前节点“待认领”时不展示当前节点表单，只展示历史处理记录和认领入口
- 发送问题后，缺陷待办、选中详情、历史处理记录仍保留
- 模型可以基于当前选中缺陷上下文回答设备 ID：`2067266200919998465`
- safety block 占位消息不再显示

工具验证：

- `monitoring_get_trend`
  - `machine_id=260617151001913`
  - `measurement_point_id=2606171510019130003`
  - 接口正常调用，测试点位暂无趋势数据，返回空数据符合预期
- `monitoring_get_alarm_history`
  - 测试环境无报警，返回无报警记录符合预期

## 风险和注意事项

- `config.yaml` 属于全局配置文件，本次确认只新增工业资产工具组、上下文解析工具和报警历史路由，没有引入密钥。
- InS 适配器和 machine / organize / point RPC 服务被增强，属于共享能力，后续合并前建议保留相关单测作为回归门槛。
- 新缺陷闭环 Agent 使用受控工具清单，不自动开放所有已有工具，避免 Agent 能力边界过宽。
- `.playwright-cli/` 是本地页面验证产物，不应提交。
- `AGENTS.md` 是项目协作说明文件，不属于本次功能必需项，是否提交需单独确认。

## ADDED Requirements

### Requirement: 系统提供统一的 Run 生命周期状态枚举

系统 SHALL 在 `deerflow.shared.status` 模块中提供唯一的 RunStatus 枚举，作为 agent run 和 report run 的共同状态来源。

RunStatus SHALL 包含以下值：
- `pending` — 已创建，等待执行
- `running` — 执行中
- `success` — 成功完成（终态）
- `failed` — 执行失败（终态，需结合 failure_category 子分类）
- `cancelled` — 用户取消（终态）

历史状态值 `error`、`timeout`、`interrupted` SHALL 通过 `canonical_run_status()` 函数自动映射为 `failed`。

#### Scenario: 所有模块使用同一 RunStatus

- **WHEN** `runtime/runs/`、`report_templates/` 或 gateway 代码引用 RunStatus
- **THEN** 它们从 `deerflow.shared.status` 导入，而非各自定义

#### Scenario: 历史状态自动映射

- **WHEN** 外部系统或旧版 API 返回 `"error"`、`"timeout"` 或 `"interrupted"` 作为 run 状态
- **THEN** `canonical_run_status()` 将其映射为 `RunStatus.failed`
- **AND** 发出 `DeprecationWarning`

### Requirement: 统一拼写 "cancelled"

系统 SHALL 在所有模块中使用 "cancelled"（双 l）作为取消状态的规范拼写。

任何使用 "canceled"（单 l）的代码 SHALL 被视为需要修正的漂移。

#### Scenario: report_templates 使用 "cancelled"

- **WHEN** report run 被取消
- **THEN** 其状态值为 `"cancelled"` 而非 `"canceled"`

#### Scenario: 存量 "canceled" 数据兼容读取

- **WHEN** 读取旧的 `status.json` 文件，其中包含 `"canceled"`
- **THEN** 系统将其识别为 cancelled 状态，不影响状态机判定

### Requirement: Run 失败必须填充 failure_category 和 failed_layer

当 RunStatus 为 `failed` 时，系统 SHALL 同时填充：
- `failure_category`: 失败分类（`execution_failed` / `upload_failed` / `external_dependency_unavailable`）
- `failed_layer`: 失败发生的架构层（`runtime` / `gateway` / `external`）

#### Scenario: 外部依赖不可用失败

- **WHEN** 模型 API 调用失败或 MCP Server 不可达导致 run 失败
- **THEN** `failure_category` 为 `"external_dependency_unavailable"`
- **AND** `failed_layer` 为 `"external"`

#### Scenario: Agent 执行逻辑异常

- **WHEN** Agent 工具调用或推理逻辑异常导致 run 失败
- **THEN** `failure_category` 为 `"execution_failed"`
- **AND** `failed_layer` 为 `"runtime"`

#### Scenario: 文件上传失败

- **WHEN** 文件上传或转换异常导致 run 失败
- **THEN** `failure_category` 为 `"upload_failed"`
- **AND** `failed_layer` 为 `"gateway"`

### Requirement: Gateway API 响应包含失败分类

系统 SHALL 在 Run 详情 API 响应中包含 `failure_category` 和 `failed_layer` 字段。

前端 SHALL 根据 `failure_category` 展示不同的用户提示和可恢复动作。

#### Scenario: Run 详情 API 返回失败分类

- **WHEN** 查询一个 failed 状态的 run 详情
- **THEN** 响应 JSON 中包含 `failure_category` 和 `failed_layer` 字段

#### Scenario: 前端根据失败分类展示不同提示

- **WHEN** 前端渲染一个 failed 状态的 run
- **THEN** 根据 `failure_category` 展示对应的用户提示文案和恢复建议（重试/重新上传/等待后重试）

### Requirement: 前端使用统一状态类型

系统 SHALL 在前端 `core/models/status.ts` 中维护与后端一致的 RunStatus、RunFailureCategory、FailedLayer、UploadStatus、ArtifactStatus 类型定义。

其他模块（包括 report-templates）SHALL 从 `@/core/models/status` 导入状态类型，而非重复定义。

#### Scenario: report-templates 不重复定义 RunStatus

- **WHEN** `core/report-templates/types.ts` 需要引用报告运行状态
- **THEN** 它从 `@/core/models/status` 导入 `RunStatus`
- **AND** 不存在独立的 `ReportRunStatus` 类型定义

#### Scenario: 前后端状态值一致

- **WHEN** 对比前端 status.ts 和后端 shared/status.py 的状态值
- **THEN** 每个状态值（pending/running/success/failed/cancelled）完全一致

### Requirement: 状态映射一致性有回归测试覆盖

系统 SHALL 对以下场景有自动化回归测试：

- RunStatus 的 5 个规范值（pending/running/success/failed/cancelled）解析正确
- canonical_run_status() 的历史值映射（error/timeout/interrupted → failed）
- "canceled" 拼写不在 report_templates 代码中出现
- failure_category 和 failed_layer 在所有失败路径中正确填充
- 前后端状态值对应一致

#### Scenario: CI 检测状态漂移

- **WHEN** 某处代码新增了独立的 RunStatus 定义
- **THEN** 测试或 lint 规则发出警告

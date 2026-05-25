## Why

当前 thread、run、upload、artifact 的生命周期状态定义分散在至少 4 处（`shared/status.py`、`runtime/runs/schemas.py`、`report_templates/records.py`、`report_templates/runtime/state.py`），存在重复定义和拼写不一致（"canceled" vs "cancelled"）。`shared/status.py` 的规范枚举未被运行时实际引用，`RunFailureCategory` 和 `FailedLayer` 只在部分路径填充。前端 `report-templates/types.ts` 独立定义状态类型，未复用中心 `status.ts`。ISSUE-01 基线已定版，现在必须让状态语义真正统一。

## What Changes

- 合并 `shared/status.py` 和 `runtime/runs/schemas.py` 的 RunStatus，使 `shared/status.py` 成为唯一权威来源
- 统一 "canceled" → "cancelled" 拼写（report_templates 侧 **BREAKING**）
- report_templates 模块的 `RunStatus = Literal[...]` 替换为 `from deerflow.shared.status import RunStatus`
- 在所有 Run 失败路径中填充 `failure_category` 和 `failed_layer`
- Gateway 运行状态 API 响应中包含 `failure_category` 和 `failed_layer` 字段
- 前端 `report-templates/types.ts` 的 `ReportRunStatus` 改为引用中心 `status.ts`
- 添加状态映射一致性、失败语义和拼写规范的回归测试

## Capabilities

### New Capabilities

- `unified-lifecycle-status`: thread、run、upload、artifact 的统一生命周期状态枚举，包含失败分类和分层错误语义

### Modified Capabilities

<!-- None — existing spec capabilities are not changing in their requirements -->

## Impact

- 后端：`shared/status.py`、`runtime/runs/schemas.py`、`runtime/runs/worker.py`、`runtime/runs/manager.py`、`report_templates/records.py`、`report_templates/runtime/state.py`、`app/gateway/services.py`、`app/gateway/routers/thread_runs.py`
- 前端：`core/models/status.ts`（可能微调）、`core/report-templates/types.ts`、`core/report-templates/api.ts`、相关状态展示组件
- 测试：新增 `test_unified_status_enums.py` 扩展、`test_report_template_status.py`
- **BREAKING**: report_templates 中 "canceled" 改为 "cancelled"，需同步更新所有引用该值的代码和数据库记录

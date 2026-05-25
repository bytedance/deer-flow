## 1. 合并 RunStatus 为单一权威来源

- [x] 1.1 将 `canonical_run_status()` 和 `_RUN_STATUS_DEPRECATED_MAP` 从 `runtime/runs/schemas.py` 移至 `shared/status.py`
- [x] 1.2 在 `shared/status.py` 的 RunStatus 中保留 `error`/`timeout`/`interrupted` 弃用成员（与 runtime 版一致）
- [x] 1.3 更新 `runtime/runs/schemas.py` 改为从 `deerflow.shared.status` 导入 RunStatus 和 canonical_run_status
- [x] 1.4 更新所有 `from deerflow.runtime.runs.schemas import RunStatus` 导入路径（如 tests/test_run_manager.py）
- [x] 1.5 更新 `shared/__init__.py` 导出 canonical_run_status、RunFailureCategory、FailedLayer

## 2. 统一 "canceled" → "cancelled" 拼写

- [x] 2.1 将 `report_templates/records.py` 的 `RunStatus = Literal[..., "canceled"]` 改为导入 shared RunStatus
- [x] 2.2 将 `report_templates/runtime/state.py` 的 `RunStatus = Literal[..., "canceled"]` 改为导入 shared RunStatus
- [x] 2.3 在 `report_templates/runtime/state.py` 的状态读取中兼容 "canceled" → "cancelled" 映射
- [x] 2.4 更新所有 report_templates 模块中使用 `Literal["canceled"]` 的硬编码引用

## 3. 填充所有 Run 失败路径的 failure_category 和 failed_layer

- [x] 3.1 在 `app/gateway/services.py` 的 `_create_run()` 中，外部服务异常捕获时设置 `failure_category="external_dependency_unavailable"` + `failed_layer="external"`
- [x] 3.2 在 `runtime/runs/worker.py` 的通用异常捕获路径中填充 `failure_category="execution_failed"` + `failed_layer="runtime"`（当前部分路径缺省）
- [x] 3.3 验证 upload 失败路径已正确设置 `failure_category="upload_failed"` + `failed_layer="gateway"`

## 4. Gateway API 响应包含失败分类字段

- [x] 4.1 在 run detail API 响应 schema 中添加 `failure_category` 和 `failed_layer` 字段
- [x] 4.2 确认 `runtime/runs/manager.py` 的 `RunRecord` 已存储这些字段，API 响应可直接透出

## 5. 前端统一状态类型

- [x] 5.1 删除 `report-templates/types.ts` 中的 `ReportRunStatus`，改为从 `@/core/models/status` 导入 `RunStatus`
- [x] 5.2 更新 report-templates 中所有引用 `ReportRunStatus` 的组件和 hooks
- [x] 5.3 确认前端展示 "canceled" → "cancelled" 拼写后，所有 UI 文案和比较逻辑正确

## 6. 回归测试

- [x] 6.1 扩展 `tests/test_unified_status_enums.py`：增加 canonical_run_status 映射测试、"canceled" 兼容性测试
- [x] 6.2 新增 `tests/test_report_template_status.py`：验证 report run 状态使用 shared RunStatus、"canceled" 字面量不存在
- [x] 6.3 新增前端测试：验证 report-templates 类型从 status.ts 导入、"canceled" 不在代码中
- [x] 6.4 运行 `make test` 全量回归，确认无破坏

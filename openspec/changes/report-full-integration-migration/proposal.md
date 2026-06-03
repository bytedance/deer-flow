# Report Full Integration Migration

## Why

AI报告（daily/weekly/monthly/trend/diagnosis）目前存在三条数据获取路径并存的问题：DSL模板平台桥接、旧 `_ins_provider.py` 直连、以及硬编码 fallback 路径。前一个 `report-integration-migration` 变更声称完成了迁移但关键布线没有落地——DSL 模板没有声明 `provider: platform`、schema 没有 `provider` 字段、`data_runner` 没有注入 `USE_PLATFORM`。同时 Agent SOUL.md 中保留了复杂的 DSL/fallback 双轨降级逻辑。本质上是架构迁了一半，现在需要一步到位：全部走 integrations 层，清除一切降级和旧路径。

## What Changes

- **新增 `DataStep.provider` 字段到 schema**：`DataStep` 模型新增可选的 `provider` 字段，支持 `"platform"` / `"ins"` / `"demo"` / `"http"`，同时放宽 `ConfigDict(extra="forbid")` 或仅对此字段放行
- **`data_runner` 注入 `USE_PLATFORM` env**：`run_script()` 新增 `provider` 参数，当值为 `"platform"` 时向 subprocess env 注入 `USE_PLATFORM=true`
- **所有 builtin 报告模板 DSL 声明 `provider: platform`**：daily-equipment / weekly-equipment / monthly-equipment / trend-equipment / diagnosis-fault 五个模板的 `data_steps` 统一加 `provider: platform`
- **移除旧直连路径**：删除 `skills/custom/data-analyst/scripts/_ins_provider.py` 中的 KPI 聚合逻辑（已在 `kpi_aggregator.py` 中有副本），sync wrapper 改为直接 raise 明确错误；`_data_provider_impls.py` 中的 `InsDailyProvider` / `InsWeeklyProvider` / `InsMonthlyProvider` 标记为 removed
- **移除 Agent SOUL.md 中的降级逻辑**：ai-report--daily / ai-report--weekly / ai-report--monthly 三个 Agent 的 SOUL.md 移除 DSL/fallback 双轨决策代码，只保留 integrations 平台的 DSL 路径
- **修复 `_platform_bridge.py` 数据转换**：`_transform_canonical_to_script_shape` 当前返回全空占位（KPI 全 None、hourly 全 0），改为正确映射 capability + action 输出到脚本期望的结构 **BREAKING**：旧 `_ins_provider.py` 直连路径不再可用，未配置 `integrations.enabled: true` 和 `ins_prod` 系统的部署将无法生成报告

## Capabilities

### New Capabilities

- `dsl-provider-field`: DSL `DataStep` schema 新增 `provider` 字段，validator 接受 `"platform"` / `"ins"` / `"demo"` / `"http"` 四个值，`data_runner` 根据 `provider` 值向 subprocess env 注入对应环境变量
- `agent-soul-simplification`: 移除 ai-report--daily/weekly/monthly 三个 Agent SOUL.md 中的 DSL/fallback 双轨降级逻辑，Agent 只保留 integrations 平台 DSL 路径，不再渲染"正在使用兼容模式生成报告"提示

### Modified Capabilities

- `report-script-platform-bridge`（来自 report-integration-migration）：修复 `_transform_canonical_to_script_shape` 返回空占位的问题，改为返回真实 KPI 数据
- `equipment-report-data-provider`（已有 spec）：数据获取强制走 integrations 层，移除 `_ins_provider.py` demo fallback 路径

## Impact

- **修改文件**：`report_templates/schema.py`（DataStep +provider）、`report_templates/runtime/data_runner.py`（run_script +provider、run_data_steps_and_transforms 传参）、5 个 builtin DSL YAML、3 个 Agent SOUL.md、`_platform_bridge.py`（数据转换修复）、`_ins_provider.py`（sync wrapper raise error）、`_data_provider_impls.py`（移除 InS provider 注册）
- **删除代码**：`_ins_provider.py` 聚合函数体（保留 stub + 错误信息）、Agent SOUL.md 中的 fallback 章节
- **依赖**：前一个 `report-integration-migration` 变更中已完成的 CLI action 模式、kpi_aggregator、query 批量参数等基础设施
- **风险**：中高 — 没有回滚路径（旧直连路径的 sync wrapper 已经 raise error，移除后不可恢复）。需要 end-to-end 烟雾测试验证真实 InS 环境下报告能正常生成

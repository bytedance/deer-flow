# Report Integration Migration

## Why

AI 报告（daily/weekly/monthly）的数据获取仍然通过 `skills/custom/data-analyst/scripts/_ins_provider.py` 直连 InS API。该路径在 Phase 3 已被标记为废弃（所有 sync wrapper 直接 `raise HttpProviderError`），导致报告数据获取完全依赖尚未完善的 `_platform_bridge.py` → CLI → 集成层路径。当前桥接层的 `_transform_canonical_to_script_shape` 返回全空占位数据（KPI 全 None、hourly 全 0），报告功能实际不可用。

根本问题是职责归属不清：KPI 聚合逻辑（`_KPI_FEATURE_MAP`、`_aggregate_trend_to_kpi`）既不属于"平台通用数据获取"，也不属于"报告业务组装"，而是 InS 数据模型的**业务解释规则**——它理解 `position_types`、`endpoint_series`、`alarm_thresholds` 这些 InS 特有概念。需要建立三层分离：平台通用能力 / 系统特有计算 / 报告业务组装，彻底消除对旧直连路径的依赖。

## Scope

**In-scope**: `query_daily.py`、`query_weekly.py`、`query_monthly.py` 三个报告脚本的平台桥接路径修复。

**Out-of-scope（本次不迁移）**:

- `query_trend.py` — 模板已标记 `provider: platform`，但脚本不读 `USE_PLATFORM`，仍走 `_data_provider_impls.fetch_with_fallback()` 路径。趋势报告的数据模型（time_series per metric + forecast）与 KPI 聚合模式差异较大，需单独设计
- `query_fault_context.py` — 模板已标记 `provider: platform`，但脚本同样不读 `USE_PLATFORM`，走 `_data_provider_impls` 的 `fault_context` source。诊断报告涉及 operations/alarms/work_orders/maintenance_records 多源数据，需独立迁移
- 上述两个脚本当前在 `USE_PLATFORM=true` 环境下会 fallback 到 demo/synthetic 数据，不会报错但也不会返回真实数据

## What Changes

- **新增 KPI 聚合函数库**：在 `deerflow/integrations/adapters/ins/` 下新增 `kpi_aggregator.py`，将 `_ins_provider.py` 中的 KPI 推导逻辑（`_KPI_FEATURE_MAP`、`_aggregate_trend_to_kpi`、`_hourly_runtime_rate`、`_fetch_kpi_for_equipment`）迁移为纯函数模块。该模块是 adapter 的内部知识，不作为独立能力键暴露
- **CLI 新增 action 模式**：`cli.py` 新增 `--action` 参数（与 `--capability` 互斥），支持 `aggregate_kpi` / `select_points` 等系统特有计算操作。action 不走 CapabilityRouter，直接调用 adapter 内部的纯函数。报告脚本通过 subprocess CLI 调用 action，保持进程隔离
- **扩展基础能力 Query 参数**：扩展 `TrendQuery` / `AlarmHistoryQuery` 支持多设备批量查询（`equipment_ids`、`eq_type`），避免报告脚本在循环中多次调用单个 capability
- **完善报告脚本平台桥接**：更新 `query_daily.py` / `query_weekly.py` / `query_monthly.py` 的 platform bridge 路径——调用基础能力（`monitoring.trend`、`monitoring.alarm_history`）获取原始数据，再调用 CLI action（`aggregate_kpi`）做 KPI 聚合，脚本自身负责报告结构组装（current + compare + output JSON）
- **builtin 报告模板已声明 provider**：builtin 报告模板的 DSL `data_steps` 已声明 `provider: platform`，`data_runner.py` 已注入 `USE_PLATFORM=true`。本次工作不需要新增模板配置，而是修复模板已触发但桥接层返回空数据的问题
- **消除旧路径依赖**：删除 `skills/custom/data-analyst/scripts/_ins_provider.py` 中的废弃聚合代码（保留为 deprecated stub），`_data_provider_impls.py` 中依赖旧 InS client 的 provider 标记为 removed

## Capabilities

### New Capabilities

- `ins-kpi-aggregator`: InS KPI 聚合函数库。在 `deerflow/integrations/adapters/ins/kpi_aggregator.py` 中提供纯函数：`aggregate_trend_to_kpi()`（6 种推导方法：mean/max/runtime_rate/downtime_count/alarm_count/thickness_loss）、`select_points_for_kpi()`（component tree 遍历 + position_type/endpoint_series 过滤）、`hourly_runtime_rate()`（24-bucket 小时开机率）、`aggregate_equipment_kpis()`（多设备批量聚合）。复用现有 `kpi_map.py` 的 `_KPI_FEATURE_MAP`，不新增数据源
- `cli-action-mode`: CLI action 模式。`cli.py` 新增 `--action` 参数（`aggregate_kpi` / `select_points`），与 `--capability` 互斥。action 不走 CapabilityRouter，直接初始化 adapter 后调用 `kpi_aggregator` 纯函数。输出 JSON 格式与 capability 模式一致（`{"ok": true, "data": ...}`）
- `report-script-platform-bridge`: 报告脚本平台桥接。更新 `query_daily.py` / `query_weekly.py` / `query_monthly.py` 的 platform bridge 路径：调用 `monitoring.trend` 获取原始趋势 → 调用 CLI `--action aggregate_kpi` 做 KPI 聚合 → 脚本自身组装报告结构。更新 builtin 报告模板 YAML 的 `data_steps` 统一加 `provider: platform`

### Modified Capabilities

- `ins-adapter`: 扩展 adapter 公开 `kpi_aggregator` 模块供 CLI action 调用。adapter 新增 `get_aggregator()` 方法返回 aggregator 实例，CLI action 模式通过该方法获取聚合函数
- `canonical-models`: 扩展 `TrendQuery` / `AlarmHistoryQuery` 支持批量参数（`equipment_ids: tuple[str, ...]`、`eq_type: str`），使基础能力可一次返回多设备数据

## Impact

- **新增模块**: `deerflow/integrations/adapters/ins/kpi_aggregator.py`（约 400 行纯函数，从 `_ins_provider.py` 提取）
- **修改模块**: `deerflow/integrations/cli.py`（+`--action` 参数分支）、`deerflow/integrations/adapters/ins/adapter.py`（+`get_aggregator()` 方法）、`deerflow/integrations/models/queries.py`（`TrendQuery` / `AlarmHistoryQuery` +批量字段）、`skills/custom/data-analyst/scripts/query_daily.py` / `query_weekly.py` / `query_monthly.py`（platform 路径重写）、`skills/custom/data-analyst/scripts/_platform_bridge.py`（+`call_action()` 函数）
- **修改配置**: 无新增模板配置（`provider: platform` 已存在于 daily/weekly/monthly/trend 模板）。仅需修复桥接层数据转换逻辑
- **删除代码**: `skills/custom/data-analyst/scripts/_ins_provider.py` 中的聚合函数体（保留 stub + deprecated 标记）、`_data_provider_impls.py` 中的旧 InS provider
- **向后兼容**: 报告脚本的 CLI 参数格式不变，输出 JSON shape 不变，仅数据获取路径切换。未启用 integrations 的租户不受影响
- **无新增能力键路由**: `config.yaml` routes 不增加 `report.*` 条目，复用现有 `monitoring.trend` / `monitoring.alarm_history` 路由
- **风险**: 中 — KPI 聚合逻辑迁移需要端到端数据一致性验证

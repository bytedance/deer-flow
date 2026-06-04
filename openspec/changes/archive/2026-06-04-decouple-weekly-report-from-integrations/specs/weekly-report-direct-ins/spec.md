## ADDED Requirements

### Requirement: InsWeeklyProvider 直接调用 _ins_provider

`_data_provider_impls.py` SHALL 注册 `InsWeeklyProvider` 作为 `"weekly"` source 的 `"ins"` 模式 provider。`InsWeeklyProvider.fetch()` SHALL 直接调用 `_ins_provider._async_fetch_daily_series_payload()` 获取 7 天数据，不再经过 `_platform_bridge` subprocess CLI。

#### Scenario: fetch 返回 daily_entries 格式

- **WHEN** `InsWeeklyProvider.fetch(week_start="2026-05-11", equipment_ids=["RM-001"], kpi_keys=["runtime_rate"], eq_type="rotating_machinery")` 被调用
- **THEN** 返回的 `ProviderResult.data` 包含 `{"daily_entries": [...]}`，其中 `daily_entries` 有 7 个元素，每个包含 `date`、`kpis`、`kpi_units`、`alarms` 字段
- **AND** `ProviderResult.data_source` 等于 `"ins"`
- **AND** 调用过程中未启动任何 subprocess 或 docker exec

#### Scenario: features-tool 不可用时抛出错误

- **WHEN** `InsWeeklyProvider.fetch(...)` 被调用且 `_FEATURES_TOOL_AVAILABLE` 为 `False`
- **THEN** 抛出 `HttpProviderError("features-tool not available: ...")` 
- **AND** 不生成任何合成数据或 demo fallback

#### Scenario: InS API 调用失败时抛出错误

- **WHEN** `InsWeeklyProvider.fetch(...)` 被调用且 InS API 返回错误
- **THEN** 抛出 `HttpProviderError`
- **AND** 调用方 `query_weekly.py` 将其渲染为 `{"error": "HttpProviderError: ..."}` 并在 stdout 输出

### Requirement: _ins_provider fetch_daily_series_payload 恢复可用

`_ins_provider.py` 中 `fetch_daily_series_payload` 函数 SHALL 恢复为实际实现，移除当前的 `NotImplementedError`。其 SHALL 同步包装 `_async_fetch_daily_series_payload`，返回 `list[dict[str, Any]]` 格式的日级数据列表。

#### Scenario: 连续 7 天数据复用单个 InsApiClient

- **WHEN** `fetch_daily_series_payload(start_date="2026-05-11", day_count=7, equipment_ids=["RM-001"], kpi_keys=["runtime_rate"], eq_type="rotating_machinery")` 被调用
- **THEN** 只创建一个 `InsApiClient` 实例和一个 `components_cache`
- **AND** 7 天数据在同一个 event loop 中协程式拉取
- **AND** 返回包含 7 个 `{date, kpis, kpi_units, alarms}` 元素的列表

### Requirement: _platform_bridge.py 从 report skills 中移除

`skills/custom/daily-report/scripts/_platform_bridge.py`、`skills/custom/weekly-report/scripts/_platform_bridge.py`、`skills/custom/monthly-report/scripts/_platform_bridge.py` SHALL 被删除。`_data_provider_impls.py` 中所有对 `_platform_bridge` 的 import SHALL 被移除。

#### Scenario: _platform_bridge 不再被 import

- **WHEN** 周报 query 脚本运行时 import `_data_provider_impls`
- **THEN** 该模块不 import `_platform_bridge`，不启动任何 subprocess

### Requirement: Provider 注册模式统一为 ins

`_data_providers.py` 中 `PLATFORM_SOURCES` 常量 SHALL 被移除。`daily`、`weekly`、`monthly` 三个 source 的默认模式 SHALL 为 `"ins"`（而非 `"platform"`）。`DEER_FLOW_DATA_PROVIDER` 环境变量对这三个 source SHALL 不生效。

#### Scenario: get_provider 默认返回 ins 模式

- **WHEN** `get_provider("weekly")` 被调用且 `DEER_FLOW_DATA_PROVIDER` 未设置
- **THEN** 返回 `InsWeeklyProvider` 实例
- **AND** `list_registered()["weekly"]` 等于 `["ins"]`

#### Scenario: DEER_FLOW_DATA_PROVIDER 被忽略

- **WHEN** `DEER_FLOW_DATA_PROVIDER=demo` 被设置且 `get_provider("weekly")` 被调用
- **THEN** 仍然返回 `InsWeeklyProvider` 实例（env var 对 weekly source 无影响）

### Requirement: 日报和月报同步迁移

日报 skill 的 `PlatformDailyProvider` SHALL 被 `InsDailyProvider`（调用 `_ins_provider._async_fetch_payload`）替换。月报 skill 同样处理。三条 report skill 的数据获取模式 SHALL 保持一致。

#### Scenario: 日报使用直接 InS 路径

- **WHEN** `query_daily.py` 运行时调用 `get_provider("daily")`
- **THEN** 返回的 provider 直接调用 `_ins_provider` 而非 `_platform_bridge`
- **AND** 输出 JSON 仍包含 `"data_source": "ins"` 和 `"data_notes": []`

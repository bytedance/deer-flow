## Why

周报功能（`weekly-report` skill）当前通过 `_platform_bridge.py` → subprocess CLI → `deerflow.integrations.cli` 的链路获取数据，整个调用链涉及 docker exec、integration registry、CapabilityRouter、InsAdapter 等大量中间层，而实际上这些中间层最终只是调用 features-tool 的 `InsApiClient` 获取原始趋势数据再做 KPI 聚合。`_ins_provider.py` 中已有完整的直接 InS 调用实现（KPI 特征映射、测点选择、趋势聚合、事件拉取），但其公开 API 被人为设为 `NotImplementedError` 强制走 integrations 路径。本变更恢复直接路径，使周报技能自包含，不再依赖 integrations 子系统。

## What Changes

- **BREAKING**: 移除 `_data_provider_impls.py` 中的 `PlatformWeeklyProvider`（及其对 `_platform_bridge` 的依赖）
- 新增 `InsWeeklyProvider`，直接调用 `_ins_provider._async_fetch_daily_series_payload` 获取 7 天日级数据
- 恢复 `_ins_provider.py` 中 `fetch_daily_series_payload` 公开函数（当前为 `NotImplementedError`）
- 同样适用于 `daily-report` 和 `monthly-report` skill（一并处理，统一架构）
- 移除周报对 integrations CLI subprocess 的依赖，不再需要 docker exec 桥接
- 删除 `_platform_bridge.py`（周报、日报、月报都不再使用）

## Capabilities

### New Capabilities
- `weekly-report-direct-ins`: 周报 skill 直接通过 `_ins_provider.py` 调用 InS API，不再经过 integrations 平台桥接

### Modified Capabilities
- `equipment-report-data-provider`: 将 `Ins{Daily,Weekly,Monthly}Provider` 的实现从 platform bridge 模式切换为直接 InS 调用模式；`data_source` 字段保持 `"ins"` 不变；输出 schema 不变

## Impact

- `skills/custom/weekly-report/scripts/_data_provider_impls.py` — 替换 Provider 实现
- `skills/custom/weekly-report/scripts/_ins_provider.py` — 恢复 `fetch_daily_series_payload` 公开函数
- `skills/custom/daily-report/scripts/` — 同步改为直接 InS 路径
- `skills/custom/monthly-report/scripts/` — 同步改为直接 InS 路径
- `skills/custom/*/scripts/_platform_bridge.py` — 删除
- `backend/packages/harness/deerflow/integrations/` — 不再作为报告数据获取路径（但 integrations 子系统本身保留给其他用途）
- 不再依赖 docker exec / subprocess CLI 桥接

## Why

当前AI报告（日报/周报/月报）中旋转机组和往复机组的"告警事件"数据为空占位（`"alarms": []`），导致报告缺失设备真实事件信息。需要通过8K/9K的`getMachineDrops`接口获取设备启停机、报警、预警、偏差报警等事件数据，填充到报告中，使运维人员能够在报告中直接查看设备事件流水。

## What Changes

- 在`_ins_provider.py`中新增`get_machine_drops`调用，从8K (`/ins-os-view/sg8kData/getMachineDrops`)和9K (`/ins-os-view/sg9kData/getMachineDrops`)接口获取设备事件数据
- 扩展`_async_fetch_payload`和`_async_fetch_daily_series_payload`，在拉取趋势数据的同时拉取设备事件，填充`alarms`字段
- 事件类型映射：1=主报警, 2=预报警, 3=启停机, 14=预警, 15=偏差报警（8K额外支持4-13,16-18）
- 仅当`eq_type`为`rotating_machinery`或`reciprocating_machinery`时触发事件拉取；其他设备类型保持`"alarms": []`

## Capabilities

### New Capabilities
- `machine-event-data-fetch`: 从InS-OS 8K/9K接口获取设备事件数据（getMachineDrops），返回事件列表并注入报告payload的alarms字段

### Modified Capabilities
- `equipment-report-data-provider`: `_ins_provider.py`的`_async_fetch_payload`和`_async_fetch_daily_series_payload`返回的`alarms`字段从空列表改为真实事件列表

## Impact

- **`skills/custom/data-analyst/scripts/_ins_provider.py`**: 新增`_fetch_machine_drops`异步方法，修改`_async_fetch_payload`和`_async_fetch_daily_series_payload`中的alarms组装逻辑
- **`skills/custom/data-analyst/scripts/daily_kpi.py`**: `_build_kpi_summary`和相关逻辑已支持alarms字段，无需修改
- **`skills/custom/data-analyst/scripts/weekly_kpi.py`**: 同上，已支持alarm_table
- **`skills/custom/data-analyst/scripts/monthly_kpi.py`**: 同上，已支持major_events和alarm相关字段
- **报告模板DSL** (`agents/builtin/report-templates/{daily,weekly,monthly}-equipment/default.yaml`): 无需修改，现有section已配置alarm数据源
- **AI报告智能体SOUL** (`agents/builtin/ai-report--{daily,weekly,monthly}/SOUL.md`): 无需修改，不涉及交互流程变更

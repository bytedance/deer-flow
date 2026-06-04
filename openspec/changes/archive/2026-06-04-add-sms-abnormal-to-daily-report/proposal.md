## Why

日报当前仅包含 InS 趋势数据和机器报警（`get_machine_drops`），完全未接入 SMS（设备异常统计与评估系统）的异常事件数据。旋转机组的异常研判（abnormal-judgment--rotating）已经深度使用 SMS 的 `abnormal.list` + `abnormal.detail`，但日报中无法看到这些 SMS 侧跟踪的异常——用户必须分别打开日报和异常研判才能获得完整画像，信息割裂。

## What Changes

- 在日报数据获取链路中新增 SMS 异常数据源，为旋转机组补充 SMS 侧的异常事件统计
- 新增 `sms_abnormal_count` 等 KPI，展示当日新增/待处理异常数量、最高严重等级、事件类型分布
- 日报 DSL 模板（`daily-equipment`）中为旋转机组类型新增"异常排行"或"异常概览"章节
- 数据获取通过 Python 脚本直连 SMS API（复用 `query_abnormal_detail.py` 的认证和请求模式，新增批量统计脚本）

## Capabilities

### New Capabilities

- `daily-report-sms-abnormal`: 日报数据获取链路支持从 SMS 拉取异常事件统计（按设备、按严重等级、按事件类型），作为日报 KPI 和异常章节的数据源
- `sms-abnormal-stats-script`: 新增 `/mnt/skills/custom/daily-report/scripts/query_sms_abnormal.py`，按日期范围和设备列表批量查询 SMS 异常统计

### Modified Capabilities

<!-- No existing spec modifies its requirements. This is a pure addition. -->

## Impact

- **技能脚本**：`skills/custom/daily-report/scripts/` 新增 `query_sms_abnormal.py`；`_report_common.py` 新增 KPI 注册（`sms_abnormal_count`, `sms_abnormal_max_level` 等）；`_data_providers.py` 新增 `SmsAbnormalProvider` 或在 `InsDailyProvider` 中增加 SMS 调用
- **DSL 模板**：`agents/builtin/report-templates/daily-equipment/default.yaml` 新增 SMS 异常相关 data_step 和 section
- **后端**：无需修改——SMS 的 `abnormal.list` API 已通过 Gateway 暴露（`GET /api/abnormal/list`），脚本层直接调用
- **Agent SOUL**：`ai-report--daily/SOUL.md` 无需修改（通过 DSL 模板驱动）

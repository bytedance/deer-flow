## Why

日报性能优化（`daily-report-perf-optimization`）已完成并验证：直执行路径、InS 并发拉取、组织树透传、SMS 异步化、性能埋点基线等优化使日报生成从多步 bash 脚本编排简化为单次 `report_direct_execute` 调用。但周报和月报仍停留在旧模式——Agent 通过 bash 逐脚本调用（`query_weekly.py` → `weekly_kpi.py` → `query_sms_abnormal.py` → `export_report.py`），没有复用日报的优化成果。这导致：

1. **性能差距**：周报/月报的 InS 数据拉取是串行的（每台设备逐个请求），大量设备时耗时线性增长；日报已实现 Semaphore 限流并发 + 跨调用缓存。
2. **冗余组织树查询**：周报/月报 Agent 仍需调用 `list_equipment.py` 获取 KPI 目录，日报已改为静态映射 + 前端透传。
3. **SMS 同步阻塞**：周报/月报的 SMS 查询是 Agent 编排的独立步骤，失败会阻塞主流程；日报已将 SMS 移入 KPI 脚本内部异步获取。
4. **无可观测性**：周报/月报没有性能埋点，无法定位瓶颈。
5. **架构不一致**：同一报告平台内，日报走直执行、周报/月报走 bash 编排，增加维护成本。

## What Changes

- 将周报和月报的 Skill 脚本（`query_weekly.py` / `weekly_kpi.py` / `query_monthly.py` / `monthly_kpi.py`）接入直执行路径，复用 `DirectReportExecutor` 的 stdout 契约和 `report_direct_execute` 工具编排。
- 从日报 Skill 复制 `_perf.py` 到周报和月报 Skill，并在各脚本的关键节点（InS 拉数、KPI 计算、SMS 查询、导出）接入埋点。
- 从日报 `_ins_client.py` 复制并发模式（`asyncio.Semaphore` + `asyncio.gather` + `_get_slim_components_cached`）到周报和月报的 `_ins_client.py`。
- 周报/月报 `query_*.py` 新增 `--equipment-meta` 参数，消费前端透传的设备元数据，跳过内部组织树查询。
- 周报/月报 `_report_common.py` 新增 `get_kpi_catalog(eq_type)` 静态 KPI 目录函数。
- 将 SMS 异步获取（方案 B）从日报复制到周报/月报的 `*_kpi.py`：新增 `_fetch_sms_direct` + `_sms_kpi` 辅助函数，在 `compute()` 内通过 `ThreadPoolExecutor` 并发获取。
- 周报/月报 `export_report.py` 新增 SMS 异常监测章节渲染。
- 更新周报/月报 `SOUL.md`：Round 1.5 改用静态 KPI 映射，Round 2 回调改为调用 `report_direct_execute`（含 `equipment_meta` 透传），删除逐脚本 bash 编排步骤。
- 更新 `executor.py` 的 `SCRIPT_MAP` 确认 weekly/monthly 路径正确（已存在）。
- 补充周报/月报直执行路径的单元测试。

## Capabilities

### New Capabilities

- `weekly-report-direct-execution`: 周报切换到 `report_direct_execute` 直执行路径，包括脚本 `--equipment-meta` 参数、静态 KPI 目录、InS 并发、SMS 异步化、性能埋点接入。
- `monthly-report-direct-execution`: 月报切换到 `report_direct_execute` 直执行路径，同上。

### Modified Capabilities

- `builtin-report-direct-executor`: 确认 `SCRIPT_MAP` 中 weekly/monthly 条目完整，`execute()` 正确传递 `equipment_meta` 和 `REPORT_RUN_ID` 环境变量。
- `weekly-report-skill`: `query_weekly.py` 新增 `--equipment-meta` 参数和并发 InS 拉取；`weekly_kpi.py` 新增 SMS 异步获取和性能埋点；`_report_common.py` 新增 `get_kpi_catalog`；`_ins_client.py` 新增 Semaphore 并发和缓存。
- `monthly-report-skill`: 同上，对应 `query_monthly.py` 和 `monthly_kpi.py`。

## Impact

- **Skill 脚本**：`skills/custom/weekly-report/scripts/` 和 `skills/custom/monthly-report/scripts/` 下的 `_perf.py`（新增）、`_ins_client.py`、`_report_common.py`、`query_*.py`、`*_kpi.py`、`export_report.py`。
- **Agent 配置**：`agents/builtin/ai-report--weekly/SOUL.md` 和 `agents/builtin/ai-report--monthly/SOUL.md`（Round 1.5 + Round 2 重写）。
- **后端执行器**：`executor.py` 已支持 weekly/monthly（`SCRIPT_MAP` 已有条目），无需新增路由；需确认 `equipment_meta` 和 `REPORT_RUN_ID` 透传对 weekly/monthly 同样生效。
- **测试**：`backend/tests/` 下新增周报/月报直执行测试，复用日报测试模式。
- **兼容性**：周报/月报的 `query_*.py` 新增参数为可选（向后兼容），现有 DSL 路径不受影响。

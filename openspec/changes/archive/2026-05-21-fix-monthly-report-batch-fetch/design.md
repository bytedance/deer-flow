## Context

`query_monthly.py` 的 `fetch_month_with_provenance()` 当前逐日循环调用 `query_daily.fetch_day_with_provenance()`，每月产生 28-31 次独立 InS API 调用。每次调用都经过 `InsDailyProvider` → `_ins_provider.fetch_daily_payload()` → `_async_fetch_payload(period_kind="day", ...)` 完整链路，每个 daily 调用创建独立的 HTTP 客户端和 InS session。

周报 (`query_weekly.py`) 在 commit `bffaf04e` 中已完成同样的优化：`fetch_week_with_provenance()` 直接调用 `_ins_provider.fetch_daily_series_payload(start_date, day_count=7, ...)` 单次批量拉取 7 天数据，复用单一 InS 客户端/session。

`_ins_provider.fetch_daily_series_payload()` 已存在且可用，它调用 `_async_fetch_daily_series_payload()` 在同一个 asyncio session 内对多天数据做并行拉取，返回 `list[dict]`（每日一个 entry，shape 与 `fetch_daily_payload` 返回值一致）。

月报的下游聚合逻辑（week_buckets 分桶、加权聚合、环比/同比对比、demo maintenance/improvement_tracking）已经成熟，仅需替换数据获取层的实现方式。

## Goals / Non-Goals

**Goals:**
- 将月报数据拉取从 28-31 次独立 InS 调用改为 1 次批量调用
- 与周报保持一致的批量拉取模式，复用 `fetch_daily_series_payload`
- 保持现有输出 contract 不变（`monthly_data.json` shape 完全兼容）
- 保持 `fetch_month()` / `fetch_month_with_provenance()` 公共 API 签名不变

**Non-Goals:**
- 不修改 `_ins_provider.py` 的批量接口（已存在且可用）
- 不修改 `monthly_kpi.py`、`export_report.py`、`report_scripts.yaml`
- 不接入真实 CMMS 数据（maintenance/improvement_tracking 继续使用 demo 桩）
- 不修改 DSL 模板层的月报模板

## Decisions

### Decision 1: 直接使用 `_ins_provider.fetch_daily_series_payload` 替代逐日循环

**选择**：`fetch_month_with_provenance()` 调用 `_ins_provider.fetch_daily_series_payload(start_date=month_start, day_count=day_count, ...)` 一次性获取全月每日数据，返回 `list[dict]` 后原地转换为现有的 `daily_entries` 格式。

**替代方案**：
- **方案 B**：使用 `InsMonthlyProvider` → `fetch_monthly_payload(month_start, month_end, ...)` → `_async_fetch_payload(period_kind="range", ...)`。这个路径返回的是整个月范围的聚合 KPI（单次 range 查询），不返回每日粒度数据。月报需要每日粒度来构建 week_buckets 和 day_count 加权聚合，所以这个路径不适合。
- **方案 C**：保持逐日循环但复用单一 HTTP 客户端。这需要在 `query_monthly.py` 中管理 InS session 生命周期，增加了复杂度但收益有限（仍需 28-31 次网络往返）。

**选择理由**：`fetch_daily_series_payload` 是已验证的路径（周报在用），返回每日粒度数据，单次批量调用，代码改动最小。

### Decision 2: `_load_query_daily` 完全移除

**选择**：移除 `_load_query_daily()` 函数及其在 `fetch_month_with_provenance()` 中的调用。compare 分支（`build_result()` 中对 `previous_month`/`previous_year_month` 的 `fetch_month_with_provenance()` 调用）自动享受同样的批量优化，无需额外处理。

**理由**：`fetch_month_with_provenance()` 是 `build_result()` 中 current 和 compare 两个分支的统一入口，修改一处即覆盖全部。

### Decision 3: 数据格式无需转换 — 批量返回值与现有 `daily_entries` 格式一致

**数据格式对照**：

| 字段 | 逐日路径 `_async_fetch_payload(day)` | 批量路径 `_async_fetch_daily_series_payload` | 月报当前提取 |
|------|--------------------------------------|----------------------------------------------|-------------|
| `kpis` | `aggregated_kpis` (L729) | `aggregated_kpis` (L820) | `day_payload.get("kpis", {})` |
| `kpi_units` | `_kpi_units_for(kpi_keys)` (L727) | `_kpi_units_for(kpi_keys)` (L821) | `day_payload.get("kpi_units", {})` |
| `alarms` | `[]` (L733) | `[]` (L822) | `day_payload.get("alarms", [])` |
| `hourly_runtime_rate` | `_hourly_runtime_rate(...)` (L732) | 不返回 | 月报不使用 |

两个路径底层调用同一个 `_fetch_kpi_for_equipment()`（`_ins_provider.py:698`），KPI 计算逻辑完全一致。批量路径返回的 `[{date, kpis, kpi_units, alarms}, ...]` 与月报内部 `daily_entries` 的构造结果**字段对字段一致**，**无需任何格式转换**。

周报 (`query_weekly.py`) 也是同样的模式 —— 直接消费 `fetch_daily_series_payload` 的返回值，三者的数据格式处理完全对齐。

**选择**：`fetch_month_with_provenance()` 用 `_load_ins_provider()` 替换 `_load_query_daily()`，单行调用 `ins.fetch_daily_series_payload(...)` 替换整个逐日循环。

## Risks / Trade-offs

- **Risk**: 全月数据量可能很大（30天 × 多设备 × 多 KPI），单次 HTTP 响应可能超时或超内存 → **Mitigation**: `_ins_provider` 已有 `max_response_bytes` 限制和超时配置；月报的 `max_output_bytes` 在 registry 中设为 100MB，足够容纳
- **Risk**: `fetch_daily_series_payload` 当前只在周报（7天）路径验证过，全月（28-31天）可能触发边界情况 → **Mitigation**: 该函数接受任意 `day_count`，内部实现为范围查询；月报测试覆盖 28/29/30/31 天月份

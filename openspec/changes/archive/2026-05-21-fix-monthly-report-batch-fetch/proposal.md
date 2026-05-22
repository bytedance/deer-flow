## Why

月报 (`query_monthly.py`) 的 `fetch_month_with_provenance()` 逐日循环调用 `query_daily.fetch_day_with_provenance()`，每月产生 28-31 次独立的 InS API 调用。周报在 commit `bffaf04e` 中已完成同样的批量拉取优化（用 `fetch_daily_series_payload` 替代逐日循环），月报是唯一尚未优化的报告类型。每次逐日调用都会创建/销毁 HTTP 客户端和 InS session，导致月报生成耗时过长、容易因单日网络波动而整体失败。

## What Changes

- **月报数据拉取改用批量接口**：`fetch_month_with_provenance()` 从逐日循环 `query_daily.fetch_day_with_provenance()` 改为调用 `_ins_provider.fetch_daily_series_payload(start_date, day_count, ...)`，单次批量请求覆盖全月天数
- **复用单一 InS 客户端**：参照周报优化，在一个 session 内完成全部数据拉取
- **保留现有聚合逻辑**：week_buckets 分桶、加权聚合、环比/同比对比等下游逻辑不变，仅替换数据获取层
- **维护/改进跟踪数据保持 demo 桩**：`_demo_maintenance()` / `_demo_improvement_tracking()` 继续提供占位数据，待后续接入真实 CMMS

## Capabilities

### New Capabilities
- `monthly-batch-fetch`: 月报通过 `fetch_daily_series_payload` 批量拉取全月每日 KPI 数据，替代逐日独立 InS 调用

### Modified Capabilities
<!-- No existing spec-level requirements change — implementation detail only -->

## Impact

- 受影响文件：`skills/custom/data-analyst/scripts/query_monthly.py`
- 不影响：`monthly_kpi.py`、`export_report.py`、`report_scripts.yaml`、下游 DSL 模板
- 不涉及 API 变更、不涉及前端变更
- 测试需更新：`test_ai_report_monthly_pipeline.py` 中的 mock 策略需与新的批量调用路径对齐

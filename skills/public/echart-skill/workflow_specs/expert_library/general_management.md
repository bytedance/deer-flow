# General Management Analyst

Use this expert when the domain is ambiguous or the user needs an executive-level operating report.

## Mission

Turn raw business data into a conclusion-first management view:

- What changed?
- Where did it change?
- Why is it likely changing?
- What should management do next?

## Required Analysis Views

1. **Business scope**
   - Identify table/file purpose, reporting period, granularity, and likely owner.
   - Separate facts from assumptions.

2. **Core KPI scan**
   - Identify 1-3 primary metrics.
   - Calculate total, average, median, min/max, latest period, and period change.

3. **Trend**
   - Latest period vs previous period.
   - Growth or decline direction and magnitude.
   - Whether change is broad-based or isolated.

4. **Structure**
   - Break down by the strongest available dimensions.
   - Identify concentration, long tail, and weak segments.

5. **Anomaly and risk**
   - Find spikes, drops, missing data, extreme values, duplicate records.
   - Distinguish data quality issues from business issues.

6. **Attribution**
   - Attribute metric changes to dimensions when date + metric + dimension exist.
   - Explain top positive and negative drivers.

## Cross Analysis Matrix

- Time x top dimension: identify whether change is broad-based or concentrated in a period/segment.
- Primary metric x secondary metric: compare result metrics with quality metrics, such as revenue vs margin or traffic vs conversion.
- Segment x segment: cross the strongest two dimensions to expose hidden concentration or offsetting effects.
- Anomaly x data source: check whether abnormal movement is caused by business activity or source/collection issues.

## Anomaly Patterns

- Metric moves sharply while related volume/quality metrics stay flat.
- Total improves while a strategically important segment declines.
- One segment contributes disproportionate change compared with its base size.
- Missing periods, duplicated identifiers, or sudden category explosion.
- Rank order changes abruptly without clear business explanation.

## Deep Attribution Paths

1. KPI change -> time contribution -> top positive/negative period.
2. KPI change -> dimension contribution -> top positive/negative segment.
3. Segment change -> secondary dimension -> specific driver cell.
4. Driver cell -> quality check: margin, conversion, retention, exception, or data quality where available.
5. Final explanation must separate confirmed cause, likely cause, and unresolved hypothesis.

## Evidence Requirements

- Every conclusion needs a number, comparison, rank, or contribution.
- If date fields are unavailable, do not claim trend.
- If dimensions are unavailable, do not claim root cause.
- If data volume is small, state that conclusions are directional.

## Report Sections

1. 管理层摘要
2. 核心结论
3. 数据范围与口径
4. KPI 表现
5. 趋势与对比
6. 结构拆解
7. 异常与风险
8. 归因判断
9. 行动建议

## Dashboard Modules

- KPI cards
- Trend chart
- Dimension breakdown
- City sales/volume map when metadata contains city geography and a sales, amount, quantity, or transaction metric; follow `workflow_specs/dashboard_modules/city_sales_map.md`
- Top drivers table
- Risk/anomaly cards
- Data quality note

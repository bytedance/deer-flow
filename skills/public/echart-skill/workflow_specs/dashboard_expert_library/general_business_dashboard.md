# General Business Dashboard Expert

Use this dashboard expert for ambiguous business data, executive monitoring, general operations, and cross-domain dashboards.

## Dashboard Mission

Create a decision-oriented operating surface that shows current status, trend direction, segment contribution, risks, and data limitations. The dashboard should help a manager decide where to inspect next, not merely list charts.

## Required Modules

1. **KPI summary**
   - Purpose: show core metric level and recent status.
   - Data needed: one or more numeric metrics and optional baseline period.
   - Card: KPI cards with metric label, value, delta when baseline exists, and scope note.

2. **Trend and comparison**
   - Purpose: show direction, volatility, and recent change.
   - Data needed: date/time field + primary metric.
   - Chart recipe: `references/examples/line-simple.md` or area/line recipe.

3. **Ranking/contribution**
   - Purpose: show top contributors and concentration.
   - Data needed: categorical dimension + primary metric.
   - Chart recipe: `references/examples/bar-simple.md`.

4. **Structure/composition**
   - Purpose: show mix across a small number of categories.
   - Data needed: categorical dimension + metric.
   - Chart recipe: `references/examples/pie-simple.md` only when categories are few; otherwise use bar.

5. **Cross-analysis**
   - Purpose: expose hidden segment differences.
   - Data needed: two dimensions + metric.
   - Chart recipe: stacked bar, heatmap, or grouped bar recipe selected from `references/examples/INDEX.md`.

6. **Anomaly/attribution**
   - Purpose: flag unusual changes and driver segments.
   - Data needed: date, metric, and at least one split dimension.
   - Module: alert cards + driver table or contribution bar.

7. **Data quality and scope note**
   - Purpose: state what the dashboard can and cannot prove.
   - Required visible note: data range, grain, metric aggregation, missing fields, and caveats.

## Interaction Model

- Filters: time, primary segment, secondary segment, geography when present.
- Drill-down dimensions: top contributing dimension, geography, product/category, channel/source.
- Comparison controls: current vs previous period when a date field exists.
- Tooltip content: metric value, share, rank, comparison value when available.
- Export/download behavior: dashboard PDF export and individual chart download.
- Theme behavior: page-level theme switch that updates all surfaces and charts.

## Geographic Rules

- City field detection: use metadata, field names, and sample values.
- Metric selection: prefer user-stated metric, then sales/amount/revenue, then quantity/order count.
- When triggered, read `workflow_specs/dashboard_modules/city_sales_map.md`.
- Fallback when coordinates or map coverage are insufficient: visible data-gap card + city ranking bar.

## Diagnostic Modules

- Cross-analysis matrix: time x primary segment, primary segment x geography, metric x quality indicator.
- Anomaly scan: spikes/drops, missing periods, concentration shifts, denominator changes.
- Attribution path: metric change -> time period -> top positive/negative segment -> secondary split.
- Data-gap cards: missing baseline, missing denominator, missing geography, missing quality indicator.

## Layout Guidance

- Header and title rules: title must come from prompt/table/fields and remain domain-neutral when industry is not proven.
- KPI row: 3-5 cards.
- Primary charts row: trend + ranking/contribution.
- Segment/geography row: structure + city map when triggered.
- Diagnostic row: cross-analysis + anomaly/attribution + data quality.
- Responsive behavior: preserve chart heights and avoid cards inside cards.

## Chart Recipe Requirements

- Trend: `references/examples/line-simple.md`
- Ranking/contribution: `references/examples/bar-simple.md`
- Structure: `references/examples/pie-simple.md` or bar fallback.
- Map: `workflow_specs/dashboard_modules/city_sales_map.md` then `references/examples/geo-map-scatter.md`
- Cross-analysis: choose from `references/examples/INDEX.md`.
- Fallback: `references/examples/bar-simple.md`

## Validation Checklist

- Title is traceable to prompt/table/fields.
- At least 6 analytical modules are present when data supports them.
- Triggered city map module is present or has explicit fallback.
- Every chart cites its recipe context.
- Dashboard includes business interpretation cards, not only charts.
- No unsupported KPI or industry concept is invented.

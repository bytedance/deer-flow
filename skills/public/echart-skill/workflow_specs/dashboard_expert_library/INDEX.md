# Dashboard Expert Library Index

Use this index before creating any enterprise dashboard.

This library is dedicated to dashboards. Do not use report experts as the primary dashboard planning source. Report experts explain a written narrative; dashboard experts design operating surfaces, module hierarchy, filters, chart evidence, diagnostics, and validation checks.

## Selection Protocol

1. Inspect the user request, table/file names, column names, sample values, metadata, and desired operating cadence.
2. Match one primary dashboard expert and optional supporting experts using the trigger terms below.
3. Read the full Markdown file for every selected dashboard expert before planning layout or charts.
4. Use the selected experts' `Dashboard Mission`, `Required Modules`, `Interaction Model`, `Diagnostic Modules`, and `Validation Checklist` to build the dashboard.
5. If no expert strongly matches, use `general_business_dashboard.md`.
6. Do not select `DASHBOARD_EXPERT_TEMPLATE.md`; it is only a schema for custom dashboard experts.

## Mandatory Dashboard Expert Loop

Every selected dashboard expert must run this loop:

1. **Define the operating decision**
   - Who will use the dashboard?
   - What decision should they make after looking at it?
   - What refresh cadence and comparison period are appropriate?

2. **Build the KPI and module tree**
   - KPI cards first, then trend, structure, geographic/segment modules, cross-analysis, anomaly/attribution, and data quality notes.
   - Do not start by choosing chart types.

3. **Select chart recipes**
   - For every chart, read the closest `references/examples/*.md` recipe before writing the ECharts option.
   - If a map module is triggered, read `workflow_specs/dashboard_modules/city_sales_map.md`.

4. **Design interactions**
   - Decide filters, drill-down dimensions, hover/tooltips, time comparison controls, and chart download/export behavior.
   - Page-level theme switching is mandatory when a theme toggle exists.

5. **Validate depth and truthfulness**
   - Title must be evidence-based.
   - Business dashboards need at least 6 analytical modules when data supports them.
   - Missing triggered modules, especially city maps, are blocking failures unless a visible data-gap fallback is shown.

## Expert Catalog

| Expert | File | Use When |
|--------|------|----------|
| General Business Dashboard Expert | `general_business_dashboard.md` | Ambiguous business data, general operations, executive monitoring |
| Sales & E-commerce Dashboard Expert | `sales_ecommerce_dashboard.md` | Sales tables, orders, GMV, products, categories, regions, stores, customers |
| Traffic & Growth Dashboard Expert | `traffic_growth_dashboard.md` | Traffic, acquisition, conversion, funnel, retention, campaign growth |

## Trigger Terms

### Sales & E-commerce Dashboard

`sales`, `order`, `amount`, `revenue`, `gmv`, `paid`, `product`, `sku`, `category`,
`channel`, `store`, `city`, `region`, `quantity`, `销量`, `销售`, `订单`, `商品`,
`品类`, `渠道`, `门店`, `城市`, `区域`, `金额`, `交易额`, `销售额`, `GMV`

### Traffic & Growth Dashboard

`traffic`, `visit`, `visitor`, `pv`, `uv`, `session`, `click`, `ctr`, `conversion`,
`retention`, `funnel`, `campaign`, `source`, `page`, `访问`, `点击`, `转化`, `留存`,
`漏斗`, `渠道`, `投放`

### General Business Dashboard

`dashboard`, `经营`, `运营`, `监控`, `看板`, `分析面板`, `overview`, `summary`,
or when no stronger expert matches.

## Custom Dashboard Expert Contract

To add a custom dashboard expert:

1. Copy `DASHBOARD_EXPERT_TEMPLATE.md` to a new file in this folder.
2. Fill every required section.
3. Add the new expert to the Expert Catalog.
4. Add trigger terms that distinguish it from existing experts.
5. Keep dashboard judgement in Markdown. Do not implement expert selection or modules as Python rules.

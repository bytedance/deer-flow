# City Sales Map Dashboard Module

Use this module when a dashboard dataset or metadata contains city-level geography and a sales, volume, or transaction metric.

This is a workflow specification for the Agent. Do not implement this as a fixed Python renderer. Python/SQL may only be used to inspect metadata, query evidence, calculate coordinates when available, and validate the final HTML.

## Trigger Conditions

Add this module when all conditions are met:

1. The user asks for a dashboard, operating monitor, sales dashboard, regional dashboard, or city distribution view.
2. Metadata, schema, sample values, or field names indicate city-level geography.
3. At least one metric can represent sales, volume, or transaction scale.

This module is a blocking requirement when triggered. The final dashboard must not omit it silently.

City field candidates:

- English: `city`, `city_name`, `buyer_city`, `store_city`, `shop_city`, `delivery_city`, `shipping_city`, `location_city`, `geo_city`
- Chinese: `城市`, `地市`, `市`, `收货城市`, `发货城市`, `门店城市`, `店铺城市`, `客户城市`, `用户城市`, `配送城市`

Metric candidates, in priority order:

1. User-specified metric in the prompt.
2. Sales amount: `销售额`, `交易额`, `成交额`, `GMV`, `金额`, `实付金额`, `收入`, `revenue`, `sales`, `amount`, `paid_amount`
3. Sales volume: `销量`, `销售量`, `件数`, `数量`, `订单量`, `quantity`, `qty`, `units`, `orders`

If both amount and volume exist, prefer amount for commercial performance dashboards and volume for inventory/fulfillment dashboards. If unclear, show one map for the primary metric and mention that the other metric can be added as a toggle or secondary ranking.

## Required Chart Recipe Context

Before writing the map option, read the chart recipe Markdown completely:

- Preferred: `references/examples/geo-map-scatter.md`
- Alternative when stronger effect emphasis is needed: `references/examples/effectScatter-map.md`
- Fallback if geographic coordinates or map coverage are insufficient: `references/examples/bar-simple.md`

Do not create the ECharts map from memory when these recipes exist.

## Evidence Query Pattern

Create one evidence table for the chart:

- Dimensions: normalized city name.
- Metric: `SUM(metric)` for additive sales/volume fields, or `COUNT(*)` only when no additive metric exists and the user accepts count as a fallback.
- Filters: inherit dashboard filters such as time, channel, product, customer segment, store, or region.
- Sorting: descending by metric.
- Limit: normally top 30-50 cities to keep the map readable.

The final dashboard module must state the statistical scope in plain language, for example:

`统计口径：本地图按城市汇总销售额，城市来自收货城市字段，销售额为实付金额求和；当前未接入门店经纬度，因此使用城市级坐标展示。`

Do not show SQL in the dashboard body.

## Visualization Contract

Use `geo + effectScatter` by default:

- `geo.map`: `china` when cities span multiple provinces.
- `series.type`: `effectScatter`
- `series.coordinateSystem`: `geo`
- Point value format: `[lng, lat, metric]`
- Tooltip: city name + metric label + formatted value.
- `visualMap`: enabled when the metric range is wide.
- Bubble size: should scale with the metric, but must stay readable; use min/max bounds.
- Chart title: use the real metric name, such as `城市销售额分布` or `城市销量分布`.
- The final HTML should contain `geo`, `effectScatter`, `coordinateSystem: 'geo'` or the equivalent JSON option, and an inlined local map script such as `china.js`.

If local map coverage or city coordinates are not available:

1. Show a dashboard data-gap note: `当前数据有城市字段，但缺少可用经纬度/本地地图覆盖，暂用城市排行柱图展示。补充城市坐标或门店地址后可升级为地图。`
2. Use a ranked bar chart fallback generated from `references/examples/bar-simple.md`.
3. Do not silently drop the city module.
4. The fallback chart title must make the substitution explicit, such as `城市销售额排行（地图坐标待补充）`.

## Layout Guidance

- Place this module in the geographic/segment row, usually after trend and core KPI cards.
- Recommended size: 2 columns wide when the dashboard grid has 3-4 columns; otherwise full width on small screens.
- Pair the map with one compact insight card explaining top city concentration and whether the distribution is concentrated or balanced.
- If the dashboard already has a province map, the city map should add detail rather than duplicate it. Use province map for macro distribution and city map for operational hotspots.

## Interpretation Guidance

The module should answer:

- Which cities contribute the most sales or volume?
- Is the distribution concentrated in a few cities?
- Are there cities with high volume but low amount, or high amount but low volume when both metrics exist?
- What extra data would explain the pattern: store count, channel mix, campaign spend, inventory, logistics capacity, weather, holidays, or local events?

Do not claim causality from the city map alone. If external or operational drivers are not present, say what data is needed to verify the cause.

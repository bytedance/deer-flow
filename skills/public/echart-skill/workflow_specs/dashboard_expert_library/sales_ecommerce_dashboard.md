# Sales & E-commerce Dashboard Expert

Use this dashboard expert for sales tables, orders, GMV, revenue, products, categories, channels, stores, cities, customers, and e-commerce operations.

## Dashboard Mission

Help sales, operations, or management users identify sales status, trend changes, contribution drivers, geographic hotspots, product/category mix, and risks. The dashboard must explain whether sales movement is driven by amount, order count, units, price/AOV, product mix, channel, geography, or data quality.

## Required Modules

1. **Sales KPI summary**
   - Purpose: show commercial scale and current status.
   - Data needed: sales amount/GMV/revenue/paid amount, order ID or order count, quantity, optional customer ID.
   - Card: GMV/sales amount, orders, units, AOV/ASP when calculable.

2. **Sales trend**
   - Purpose: show sales direction and volatility.
   - Data needed: date field + sales amount or quantity.
   - Chart recipe: `references/examples/line-simple.md`.

3. **Product/category contribution**
   - Purpose: identify top products/categories and concentration risk.
   - Data needed: product/category + sales metric.
   - Chart recipe: `references/examples/bar-simple.md`.

4. **Channel/region structure**
   - Purpose: show sales mix by channel, region, store, or platform.
   - Data needed: channel/region/store dimension + sales metric.
   - Chart recipe: bar/stacked bar selected from `references/examples/INDEX.md`.

5. **City sales/volume map**
   - Purpose: show city-level sales hotspots and geographic imbalance.
   - Data needed: city field + sales amount, GMV, revenue, quantity, or orders.
   - Required module: read `workflow_specs/dashboard_modules/city_sales_map.md`.

6. **Cross-analysis**
   - Purpose: reveal hidden segment problems.
   - Data needed: category x region, channel x category, city x category, or product x channel.
   - Chart recipe: grouped/stacked bar or heatmap from `references/examples/INDEX.md`.

7. **Anomaly and attribution**
   - Purpose: identify abnormal sales changes and top drivers.
   - Data needed: date + metric + split dimensions.
   - Module: alert cards + positive/negative driver table.

8. **Data quality and scope note**
   - Purpose: prevent false commercial conclusions.
   - Required visible note: date range, sales metric, grain, missing cost/margin/refund/customer fields.

## Interaction Model

- Filters: date range, product/category, channel, region/city, store, customer segment when available.
- Drill-down dimensions: product -> category, region -> city, channel -> product, city -> category.
- Comparison controls: current period vs previous period; same period last year if sufficient history exists.
- Tooltip content: sales amount, quantity/orders, share, rank, and comparison when available.
- Export/download behavior: export dashboard PDF and download charts.
- Theme behavior: page-level theme toggle.

## Geographic Rules

- City field detection: city, buyer_city, store_city, delivery_city, 收货城市, 门店城市, 城市, 地市.
- Metric selection: user metric -> sales/GMV/amount/revenue -> quantity/units/orders.
- When triggered, read `workflow_specs/dashboard_modules/city_sales_map.md`.
- Fallback when coordinates or map coverage are insufficient: city ranking bar with visible note.

## Diagnostic Modules

- Cross-analysis matrix: category x city, channel x category, region/city x product, time x channel.
- Anomaly scan: sales spike/drop, rank changes, concentration jump, amount up while quantity down, quantity up while amount down.
- Attribution path: sales change = order/volume effect + price/AOV effect + mix effect + geography/channel effect.
- Data-gap cards: missing cost/margin, missing refund, missing order ID/customer ID, missing city coordinates.

## Layout Guidance

- Header and title rules: use neutral sales title unless data or user names a specific industry/product.
- KPI row: sales amount, orders, quantity, AOV, active products/customers if calculable.
- Primary charts row: sales trend + category/product contribution.
- Segment/geography row: channel/region breakdown + city map.
- Diagnostic row: cross-analysis + anomaly/attribution + data quality note.
- Responsive behavior: map and cross-analysis modules should span wider columns.

## Chart Recipe Requirements

- Trend: `references/examples/line-simple.md`
- Ranking/contribution: `references/examples/bar-simple.md`
- Structure: `references/examples/pie-simple.md` only for few categories; otherwise bar.
- Map: `workflow_specs/dashboard_modules/city_sales_map.md` then `references/examples/geo-map-scatter.md`
- Cross-analysis: choose grouped/stacked bar or heatmap from `references/examples/INDEX.md`.
- Fallback: `references/examples/bar-simple.md`

## Validation Checklist

- Title is traceable to prompt/table/fields and does not invent an industry such as white liquor.
- At least 6 analytical modules are present when data supports them.
- City map module appears when city + sales/volume metrics exist.
- Every chart cites its recipe context.
- Dashboard includes interpretation cards for top drivers and risks.
- No margin, refund, retention, or target achievement claim appears unless supported by fields or user definitions.

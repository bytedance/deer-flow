# Dashboard Workflow

Use this workflow when handling `/dashboard`, `/db`, `/仪表盘`, or any request for an interactive business dashboard.

## Principle

The Agent designs the dashboard. Python should not generate the final dashboard from a fixed renderer.
Use Python only to query data, calculate metrics, and validate standalone HTML.

## Required Steps

1. **Define the dashboard job**
   - Identify target user: executive, analyst, operator, growth, finance, sales, etc.
   - Identify operating cadence: real-time, daily, weekly, monthly, campaign review.
   - Identify the primary decision the dashboard should support.
   - Define the dashboard title from the user request, table/file name, and actual fields. Do not invent a product, brand, or industry label that is not present in the data or prompt.
   - Title rule: if the user uploads a sales table and does not name a specific industry, use a neutral title such as `销售数据经营 Dashboard`, `销售表现分析 Dashboard`, or `<表名> Dashboard`. Never infer a narrow category such as white liquor, cosmetics, SaaS, or apparel unless the data contains that category or the user says it.

2. **Infer industry and KPI tree**
   - Read `workflow_specs/dashboard_expert_library/INDEX.md`.
   - Select one primary dashboard expert and optional supporting experts from the dashboard expert library.
   - Read the selected expert Markdown files completely.
   - Build KPI groups from selected expert files, not from hardcoded Python rules.
   - Convert selected experts' `Cross Analysis Matrix`, `Anomaly Patterns`, and `Deep Attribution Paths` into dashboard diagnostic modules.
   - Build a KPI tree before choosing charts.
   - Avoid chart collections without a business hierarchy.

3. **Plan layout**
   - First row: KPI summary and key status.
   - Second row: trend and comparison.
   - Third row: structure/segment breakdown.
   - Diagnostic area: anomalies, funnel, retention, attribution, or drill-down tables where relevant.
   - Include at least one cross-analysis module and one anomaly/attribution module when data supports them.
   - Put filters where users expect them: time, channel, region, product, user segment.
   - If metadata, schema, or sample values contain a city field and a sales/volume/transaction metric, read `workflow_specs/dashboard_modules/city_sales_map.md` completely and include its map module unless the user explicitly excludes geography.
   - Minimum depth for business dashboards: include at least 6 analytical modules when data supports them: KPI cards, trend, ranking/contribution, structure/composition, geographic city module when triggered, cross-analysis, anomaly/attribution, and data quality/scope note.
   - A dashboard with only 2-3 charts is incomplete unless the dataset truly has too few fields; in that case, show a data limitation note and explain which missing fields prevent deeper analysis.

4. **Query evidence**
   - Use DuckDB/SQL/Python to produce the exact data arrays needed by charts.
   - Keep query logic auditable; include key SQL in comments or appendix when appropriate.
   - For every chart, first read the selected chart recipe from `references/examples/*.md`, then generate the option from the recipe and evidence table. Dashboard charts are not written from memory.

5. **Author standalone HTML**
   - Read `workflow_specs/html_templates/dashboard_light.html` completely and use it as the dashboard shell.
   - Use `workflow_specs/visual_templates/light.md` or `dark.md` only as visual direction; do not use Markdown visual notes as the final HTML shell.
   - Read `workflow_specs/dashboard_runtime_quality.md` completely and apply its runtime quality gate.
   - Inline ECharts and required local JS/CSS assets.
   - Do not depend on a Python dashboard renderer.
   - The Agent writes the HTML, layout, chart options, and narrative cards.
   - Validate with `scripts/validate_chart.py`.

## Dashboard Content Patterns

Dashboard modules are defined by the selected dashboard expert files in
`workflow_specs/dashboard_expert_library/`.

For each selected expert:

- Use its `Dashboard Modules` section as candidate modules.
- Use its `Core Metrics` section for KPI cards.
- Use its `Required Data Checks` section to create explicit data-gap notes.
- Use its `Cross Analysis Matrix` section for heatmaps, segmented bars, scatter plots, or comparison matrices.
- Use its `Anomaly Patterns` section for alert cards and abnormal segment markers.
- Use its `Deep Attribution Paths` section for driver trees, waterfall charts, and drill-down tables.
- Use its `Report Questions` section to decide which insight cards are worth showing.
- Use its `Interaction Model`, `Layout Guidance`, `Chart Recipe Requirements`, and `Validation Checklist` to drive dashboard behavior and final checks.

## Geographic City Module

When city-level geography is detected in metadata, schema, or sample values:

1. Read `workflow_specs/dashboard_modules/city_sales_map.md`.
2. Select the real city field and the real sales/volume/transaction metric from the user data.
3. Read the chart recipe Markdown required by that module, normally `references/examples/geo-map-scatter.md`.
4. Generate the city map chart one chart at a time, then assemble it into the dashboard shell.
5. If coordinates or map coverage are insufficient, show a data-gap note and use the ranked bar fallback from `references/examples/bar-simple.md`.
6. If the final dashboard does not contain either a rendered city map (`geo` + `effectScatter`) or the explicit ranked-bar fallback plus data-gap note, the dashboard fails validation and must be regenerated.

This module is optional only when:

- The user explicitly says not to include geography.
- The city field is present but no meaningful metric exists and count fallback would be misleading.
- All city values are unusable after inspection; in that case the dashboard must show a data quality note.

If no dashboard expert strongly matches, select `general_business_dashboard.md` and build:

- KPI cards
- trend chart
- dimension breakdown
- top drivers table
- risk/anomaly cards
- data quality note

## Visual Rules

- Read and apply `workflow_specs/html_templates/dashboard_light.html` as the default HTML dashboard shell.
- Read `workflow_specs/visual_templates/light.md` by default as supplemental visual direction.
- Read and apply the dark spec only when requested or when the context is command-center/monitoring, then adapt the dashboard shell tokens without weakening its structure.
- Keep UI dense, formal, and readable. This is an operating surface, not a marketing page.
- Do not put cards inside cards.
- Use stable grid dimensions so charts and labels do not shift layout.
- Include insight cards only when they contain specific numbers or clear business interpretation.
- The generated CSS must visibly implement the dashboard shell: background, surface, typography, borders, chart panel spacing, KPI card hierarchy, semantic colors, toolbar, diagnostic panel, print rules, and responsive behavior.
- Theme switching must be page-level, not chart-only: the HTML root or dashboard root must toggle `data-theme`, and CSS tokens must update page background, header, toolbar, cards, charts, diagnostics, buttons, and toasts.
- Before returning, inspect the HTML/CSS and confirm it does not look like unstyled default HTML.

## Validation Rules

Before returning:

- Read and apply `workflow_specs/dashboard_runtime_quality.md`.
- Generated HTML must be standalone.
- ECharts and map assets must be inlined when used.
- Dashboard controller code must be inlined if interactive controls are used.
- No runtime external loaders are allowed: no `script.src = https`, no `fetch(https)`, no injected CDN script tags.
- No invalid global declarations are allowed: use `window.dashboardCharts = []`, never `var window.dashboardCharts = []`.
- No `color-mix()`, `oklch()`, `oklab()`, `lab()`, or `lch()` in dashboard CSS when PDF export uses html2canvas.
- Map bootstrap must rely on inlined map JS registration; do not reference `chinaGeoJSON` unless it is explicitly defined in the same HTML.
- The chosen HTML shell and visual direction file must have been read and translated into CSS tokens/classes.
- The title must be traceable to the user prompt, table/file name, or actual data fields. If it contains a specific industry/product term, that term must exist in the prompt or evidence.
- The dashboard must include the minimum analytical depth modules unless the data lacks required fields, and any skipped module must have a visible data-gap reason.
- If city geography and sales/volume metrics are present, the final HTML must include the city map module or the documented fallback. Missing the module is a blocking failure.
- The dashboard must include at least one business interpretation card when data supports it; it cannot be only charts.
- The dashboard should not stop at KPI totals; it must include cross-analysis, anomaly, or attribution diagnostics when the required fields exist.
- Run `python scripts/validate_chart.py <output.html>` when an HTML dashboard is produced.
- Browser automation is optional. The mandatory no-browser gate is `python scripts/validate_chart.py <output.html>`, which must catch forbidden URL assets, iframe/object/embed usage, runtime self-load/navigation patterns, custom JS syntax errors, PDF-incompatible CSS, missing controller/export/download pieces, and map registration issues.
- When browser automation is available, use it only as an extra smoke test through `file://`: no page errors, no console errors, expected chart canvas count, map canvas when triggered, empty external script list, working PDF export, and working chart download.

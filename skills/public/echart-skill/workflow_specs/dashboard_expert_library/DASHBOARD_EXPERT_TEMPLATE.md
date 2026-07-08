# Dashboard Expert Name

Use this dashboard expert for: `<business domain, dashboard users, tables, metrics, operating scenarios>`.

This is a template for custom dashboard experts. Do not select this file directly. Copy it to a new Markdown file, fill every section, and register the new file in `INDEX.md`.

## Dashboard Mission

State what operating decision this dashboard helps the user make. Define the target user, cadence, and the dashboard's decision scope.

## Required Modules

List the modules that must appear when data supports them. Include the business purpose, chart type, and minimum data fields.

1. **KPI summary**
   - Purpose:
   - Data needed:
   - Chart/card:

2. **Trend and comparison**
   - Purpose:
   - Data needed:
   - Chart recipe:

3. **Segment or structure breakdown**
   - Purpose:
   - Data needed:
   - Chart recipe:

4. **Cross-analysis**
   - Purpose:
   - Data needed:
   - Chart recipe:

5. **Anomaly or attribution**
   - Purpose:
   - Data needed:
   - Chart recipe:

6. **Data quality and scope note**
   - Purpose:
   - Required visible note:

## Interaction Model

- Filters:
- Drill-down dimensions:
- Comparison controls:
- Tooltip content:
- Export/download behavior:
- Theme behavior:

## Geographic Rules

- City field detection:
- Metric selection:
- When triggered, read `workflow_specs/dashboard_modules/city_sales_map.md`.
- Fallback when coordinates or map coverage are insufficient:

## Diagnostic Modules

- Cross-analysis matrix:
- Anomaly scan:
- Attribution path:
- Data-gap cards:

## Layout Guidance

- Header and title rules:
- KPI row:
- Primary charts row:
- Segment/geography row:
- Diagnostic row:
- Responsive behavior:

## Chart Recipe Requirements

For every chart, specify the recipe that must be read from `references/examples/*.md`.

- Trend:
- Ranking/contribution:
- Structure:
- Map:
- Cross-analysis:
- Fallback:

## Validation Checklist

- Title is traceable to prompt/table/fields.
- At least 6 analytical modules are present when data supports them.
- Triggered city map module is present or has explicit fallback.
- Every chart cites its recipe context.
- Dashboard includes business interpretation cards, not only charts.
- No unsupported KPI or industry concept is invented.

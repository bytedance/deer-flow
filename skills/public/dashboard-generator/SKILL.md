---
name: dashboard-generator
description: This skill should be used when the user wants to create an interactive dashboard, a full-page analytics board, a BI report page, a multi-chart view, or a data visualization page with multiple charts and KPIs. Use this skill whenever the user mentions dashboards, analytics boards, BI views, multi-chart pages, report pages, or wants to display multiple metrics and charts together in a single page, even if they don't explicitly ask for a "dashboard." This is different from chart-visualization which generates a single chart image — dashboard-generator produces a complete, self-contained interactive HTML page.
dependency:
  python: ">=3.10"
---

# Dashboard Generator Skill

This skill generates complete, interactive HTML dashboards from structured data. Unlike single-chart visualization (chart-visualization), it produces a self-contained HTML page with multiple charts, KPI cards, data tables, filters, and responsive layouts — all powered by Apache ECharts.

## Core Capabilities

- **Multi-chart dashboard layout** — grid (12-column), tabs, or sidebar navigation
- **KPI summary cards** with formatting (currency, number, percent) and trend indicators
- **Interactive filters** — dropdown selects and date range pickers with client-side filtering
- **Responsive design** — adapts to desktop and tablet viewports
- **Self-contained single HTML file** — inline Apache ECharts, no server required
- **Multi-source data** — supports CSV/Excel files via DuckDB or pre-processed JSON
- **Theme presets** — light, dark, and corporate

## When to Use This Skill

**Always load this skill when:**

- User wants a dashboard, analytics board, BI view, or multi-chart page
- User wants to display multiple metrics and charts together
- User mentions "dashboard", "report page", "analytics view", "KPI board", or "overview page"
- User asks to visualize an entire dataset with multiple perspectives at once
- A single chart (chart-visualization) is not sufficient for the user's needs

## Workflow

### Step 1: Understand Requirements

Identify the following from the user's request:

| Input | Description | Required |
|-------|-------------|----------|
| **Data source** | Path(s) to CSV/Excel files under `/mnt/user-data/uploads/` or inline data | Yes |
| **Dashboard goal** | What business question the dashboard answers | Yes |
| **Key metrics / KPIs** | Which numbers matter most | No |
| **Charts needed** | What visualizations to include | Yes |
| **Layout** | `grid` (default), `tabs`, or `sidebar` | No |
| **Theme** | `light` (default), `dark`, or `corporate` | No |
| **Title** | Dashboard title | No |

> You don't need to check the folder under `/mnt/user-data`

### Step 2: Create Dashboard Spec

Create a JSON spec file in `/mnt/user-data/workspace/` describing the dashboard structure:

```json
{
  "title": "Sales Dashboard Q4 2024",
  "theme": "light",
  "layout": "grid",
  "data_source": {
    "files": ["/mnt/user-data/uploads/sales.csv"],
    "sql": "SELECT DATE_TRUNC('month', order_date) as month, region, product_name, SUM(revenue) as revenue, COUNT(*) as orders FROM sales GROUP BY month, region, product_name ORDER BY month"
  },
  "kpis": [
    {"label": "Total Revenue", "value_sql": "SELECT SUM(revenue) FROM sales", "format": "currency"},
    {"label": "Orders", "value_sql": "SELECT COUNT(*) FROM sales", "format": "number"},
    {"label": "Avg Order", "value_sql": "SELECT AVG(revenue) FROM sales", "format": "currency"},
    {"label": "Regions", "value_sql": "SELECT COUNT(DISTINCT region) FROM sales", "format": "number"}
  ],
  "charts": [
    {
      "id": "revenue_trend",
      "title": "Monthly Revenue",
      "type": "area",
      "x": "month",
      "y": ["revenue"],
      "position": {"row": 1, "col": 1, "width": 8}
    },
    {
      "id": "region_pie",
      "title": "Revenue by Region",
      "type": "donut",
      "x": "region",
      "y": ["revenue"],
      "position": {"row": 1, "col": 2, "width": 4}
    },
    {
      "id": "top_products",
      "title": "Top 10 Products",
      "type": "bar",
      "x": "product_name",
      "y": ["revenue"],
      "limit": 10,
      "position": {"row": 2, "col": 1, "width": 12}
    }
  ],
  "filters": [
    {"field": "region", "type": "select", "label": "Region"}
  ]
}
```

### Step 3: Run Data Preparation (optional)

If the data source is CSV/Excel with SQL in the spec, extract data first via the data-analysis skill:

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales.csv \
  --action query \
  --sql "SELECT ..." \
  --output-file /mnt/user-data/workspace/dashboard-data.json
```

### Step 4: Generate the Dashboard

```bash
python /mnt/skills/public/dashboard-generator/scripts/generate.py \
  --spec-file /mnt/user-data/workspace/dashboard-spec.json \
  --output-file /mnt/user-data/outputs/sales-dashboard.html
```

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--spec-file` | Yes | Path to the dashboard spec JSON file |
| `--output-file` | Yes | Path to output HTML file |
| `--data-file` | No | Pre-processed data JSON (alternative to SQL in spec) |
| `--theme` | No | Override theme: `light`, `dark`, `corporate` |

> [!NOTE]
> Do NOT read the Python file, just call it with the parameters.

## Chart Types

| Type | Use Case | Required Fields |
|------|----------|-----------------|
| `line` | Trends over time | `x`, `y` (array of field names) |
| `area` | Cumulative / stacked trends | `x`, `y` |
| `bar` | Horizontal comparison | `x`, `y` |
| `column` | Vertical comparison | `x`, `y` |
| `pie` | Part-to-whole | `x`, `y` |
| `donut` | Part-to-whole (ring) | `x`, `y` |
| `scatter` | Correlation | `x`, `y` |
| `treemap` | Hierarchical proportions | `x`, `y` |
| `radar` | Multi-dimensional comparison | `x`, `y` |
| `funnel` | Process stages | `x`, `y` |
| `table` | Raw data table | `columns` (array of field names) |

## Layout Options

### Grid Layout (default)

12-column grid system. `width` controls column span (1–12).

```json
{
  "layout": "grid",
  "charts": [
    {"id": "chart1", "position": {"row": 1, "col": 1, "width": 12}},
    {"id": "chart2", "position": {"row": 2, "col": 1, "width": 6}},
    {"id": "chart3", "position": {"row": 2, "col": 2, "width": 6}}
  ]
}
```

### Tab Layout

Charts organized into tabbed sections.

```json
{
  "layout": "tabs",
  "tabs": [
    {"label": "Overview", "charts": ["revenue_trend", "region_pie"]},
    {"label": "Details", "charts": ["top_products", "raw_table"]}
  ]
}
```

## Theme Presets

| Theme | Description |
|-------|-------------|
| `light` | Clean white background, subtle borders, professional palette (default) |
| `dark` | Dark background (#1a1a2e), vibrant chart colors, reduced eye strain |
| `corporate` | Blue-toned, enterprise feel, conservative palette |

## Complete Example

User uploads `sales_2024.xlsx` and says: "Create a sales dashboard showing revenue trends, top products, and regional breakdown."

### Step 1: Inspect the data

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales_2024.xlsx \
  --action inspect
```

### Step 2: Create the dashboard spec

Save to `/mnt/user-data/workspace/sales-dashboard-spec.json`:

```json
{
  "title": "Sales Dashboard 2024",
  "theme": "light",
  "layout": "grid",
  "data_source": {
    "files": ["/mnt/user-data/uploads/sales_2024.xlsx"],
    "sql": "SELECT DATE_TRUNC('month', order_date) as month, region, product_name, SUM(revenue) as revenue, COUNT(*) as orders FROM Orders GROUP BY month, region, product_name ORDER BY month"
  },
  "kpis": [
    {"label": "Total Revenue", "value_sql": "SELECT SUM(revenue) FROM Orders", "format": "currency"},
    {"label": "Orders", "value_sql": "SELECT COUNT(*) FROM Orders", "format": "number"},
    {"label": "Avg Order", "value_sql": "SELECT AVG(revenue) FROM Orders", "format": "currency"}
  ],
  "charts": [
    {
      "id": "revenue_trend",
      "title": "Monthly Revenue",
      "type": "area",
      "x": "month",
      "y": ["revenue"],
      "position": {"row": 1, "col": 1, "width": 8}
    },
    {
      "id": "region_split",
      "title": "Revenue by Region",
      "type": "donut",
      "x": "region",
      "y": ["revenue"],
      "position": {"row": 1, "col": 2, "width": 4}
    },
    {
      "id": "top_products",
      "title": "Top 10 Products",
      "type": "bar",
      "x": "product_name",
      "y": ["revenue"],
      "limit": 10,
      "position": {"row": 2, "col": 1, "width": 12}
    }
  ]
}
```

### Step 3: Generate the dashboard

```bash
python /mnt/skills/public/dashboard-generator/scripts/generate.py \
  --spec-file /mnt/user-data/workspace/sales-dashboard-spec.json \
  --output-file /mnt/user-data/outputs/sales-dashboard.html
```

### Step 4: Share the result

Use `present_files` to share `/mnt/user-data/outputs/sales-dashboard.html`.

## Output Handling

After generation:

- The HTML file is fully self-contained — open in any browser, no server needed
- Share the file with the user using `present_files`
- Suggest iterative refinements: add charts, change theme, adjust layout
- If the user wants a single chart, use the `chart-visualization` skill instead

## Notes

- Generated HTML uses inline Apache ECharts — no internet required
- For large datasets (100K+ rows), aggregation is handled via DuckDB before rendering
- All data is embedded in the HTML file — be mindful of file size with very large datasets
- Supports Chinese and English UI — auto-detected from the dashboard title language

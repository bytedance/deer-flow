---
name: ai-graphs
description: Use this skill when the user wants to create interactive data dashboards and visualizations from uploaded CSV/Excel files. Generates ECharts-based charts, metric cards, and multi-chart dashboards rendered in a TipTap canvas editor. Supports 21+ chart types with data sourced from uploaded files.
allowed-tools:
  - bash
  - read_file
  - write_file
  - present_files
---

# AI Graphs Skill

## CRITICAL RULES — READ FIRST

1. **DO NOT generate PNG/SVG/image files.** DO NOT use the `chart-visualization` skill or `generate.js`. All visualizations are interactive ECharts rendered in the browser.
2. **Your ONLY output is a TipTap JSON file** written to `/mnt/user-data/outputs/dashboard.json`. The frontend renders this as an interactive dashboard with live ECharts charts.
3. **All chart data MUST come from SQL queries** on the uploaded files. NEVER invent or hallucinate data.
4. **ALWAYS call `present_files`** after writing the dashboard so the frontend can load it.
5. **NEVER use Node.js scripts** to generate charts. Use ONLY the Python `generate.py` script in this skill.

## Overview

You are a data visualization expert. Your job is to analyze user-uploaded data (CSV/Excel) and produce interactive ECharts dashboards using the `generate.py` script. The dashboard is a TipTap JSON file stored in the sandbox. The frontend renders it as a canvas with draggable chart blocks and metric cards.

**The user can also edit the dashboard directly in the TipTap editor.** Before updating, always `read_file` the dashboard to see the current state (including any user edits).

## Workflow

### Step 1: Inspect Uploaded Data

```bash
python /mnt/skills/public/ai-graphs/scripts/generate.py \
  --files /mnt/user-data/uploads/data.csv \
  --action inspect
```

This shows table schemas, column types, row counts, and sample data.

### Step 2: Generate Dashboard

After inspecting, build a **plan** JSON and pass it to the script:

```bash
python /mnt/skills/public/ai-graphs/scripts/generate.py \
  --files /mnt/user-data/uploads/data.csv \
  --action generate \
  --output /mnt/user-data/outputs/dashboard.json \
  --plan '{
    "title": "Sales Dashboard",
    "metrics": [
      {"label": "Total Revenue", "sql": "SELECT SUM(revenue) FROM data", "format": "$"},
      {"label": "Total Orders", "sql": "SELECT COUNT(*) FROM data"},
      {"label": "Avg Order Value", "sql": "SELECT ROUND(AVG(revenue), 2) FROM data", "format": "$"}
    ],
    "charts": [
      {
        "title": "Monthly Revenue Trend",
        "type": "line",
        "sql": "SELECT DATE_TRUNC('\''month'\'', order_date)::VARCHAR as month, ROUND(SUM(revenue), 2) as total_rev FROM data GROUP BY 1 ORDER BY 1"
      },
      {
        "title": "Revenue by Category",
        "type": "bar",
        "sql": "SELECT category, ROUND(SUM(revenue), 2) as total FROM data GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
      },
      {
        "title": "Category Distribution",
        "type": "pie",
        "sql": "SELECT category, COUNT(*) as count FROM data GROUP BY 1 ORDER BY 2 DESC LIMIT 6"
      }
    ]
  }'
```

### Step 3: Present the Dashboard

```bash
present_files ["/mnt/user-data/outputs/dashboard.json"]
```

### Step 4: Update Existing Dashboard

When the user asks for changes, you can either:

**Option A**: Read the current dashboard, modify the JSON, and write it back:
```bash
read_file /mnt/user-data/outputs/dashboard.json
```
Then use `write_file` to update it.

**Option B**: Re-generate with an updated plan:
```bash
python /mnt/skills/public/ai-graphs/scripts/generate.py \
  --files /mnt/user-data/uploads/data.csv \
  --action generate \
  --output /mnt/user-data/outputs/dashboard.json \
  --plan '{ ... updated plan ... }'
```

Then call `present_files` again.

### Querying Data Directly

To run a SQL query and see results (useful for exploring data before building the plan):

```bash
python /mnt/skills/public/ai-graphs/scripts/generate.py \
  --files /mnt/user-data/uploads/data.csv \
  --action query \
  --sql "SELECT category, SUM(revenue) as total FROM data GROUP BY 1 ORDER BY 2 DESC"
```

This returns results as a JSON array-of-arrays (the `dataset.source` format).

## Plan Format

The `--plan` JSON has this structure:

```json
{
  "title": "Dashboard Title",
  "metrics": [
    {
      "label": "Display Label",
      "sql": "SELECT single_value FROM ...",
      "format": "$",
      "change_sql": "SELECT percentage_change FROM ..."
    }
  ],
  "charts": [
    {
      "title": "Chart Title",
      "type": "line",
      "sql": "SELECT x_col, y_col FROM ... GROUP BY ..."
    }
  ]
}
```

### Metric Fields

| Field | Required | Description |
|-------|----------|-------------|
| `label` | yes | Display name |
| `sql` | yes | Query returning a single value |
| `format` | no | `"$"` for currency, `"%"` for percentage |
| `change_sql` | no | Query returning a percentage change value |

### Chart Fields

| Field | Required | Description |
|-------|----------|-------------|
| `title` | yes | Chart heading |
| `type` | yes | Chart type (see below) |
| `sql` | yes | Query returning data rows |
| `options` | no | Extra ECharts options to merge |

### Supported Chart Types

| Type | SQL Pattern | Best For |
|------|------------|----------|
| `line` | `SELECT x, y1, y2 FROM ...` | Time series, trends |
| `area` | `SELECT x, y1, y2 FROM ...` | Accumulated trends |
| `bar` / `column` | `SELECT category, value FROM ...` | Categorical comparison |
| `horizontal_bar` | `SELECT category, value FROM ...` | Many categories |
| `stacked_bar` | `SELECT x, y1, y2 FROM ...` | Part-to-whole across categories |
| `pie` / `donut` | `SELECT label, value FROM ...` | Part-to-whole (max 6-8 slices) |
| `scatter` | `SELECT x, y FROM ...` | Correlations |
| `radar` | `SELECT label, dim1, dim2, ... FROM ...` | Multi-dimensional (3-8 axes) |
| `funnel` | `SELECT stage, value FROM ...` | Process stages |
| `heatmap` | `SELECT x, y, value FROM ...` | 2D density |
| `gauge` | `SELECT label, value FROM ...` | Single KPI |
| `treemap` | `SELECT name, value FROM ...` | Hierarchical data |
| `sankey` | `SELECT source, target, value FROM ...` | Flow between nodes |

## SQL Guidelines

- Table names match the uploaded file name (without extension). E.g., `sales_2024.csv` → table `sales_2024`
- Use `::VARCHAR` to cast dates for chart x-axis labels
- Use `ROUND()` for decimal values
- Combine insights with CTEs when possible
- Limit categories to 10 (bar) or 6-8 (pie) — group rest into "Other"
- Do NOT run more than 3 queries before generating

## Dashboard Composition

Aim for:
1. **Metric cards** (3-6) — Key KPIs at top
2. **Primary chart** — Main insight (time series or top-N)
3. **Supporting charts** (2-4) — Different views of the data

## Complete Example

User uploads `sales_2024.csv` and asks: "Analyze my sales data"

### 1. Inspect

```bash
python /mnt/skills/public/ai-graphs/scripts/generate.py \
  --files /mnt/user-data/uploads/sales_2024.csv \
  --action inspect
```

### 2. Generate

```bash
python /mnt/skills/public/ai-graphs/scripts/generate.py \
  --files /mnt/user-data/uploads/sales_2024.csv \
  --action generate \
  --output /mnt/user-data/outputs/dashboard.json \
  --plan '{
    "metrics": [
      {"label": "Total Revenue", "sql": "SELECT SUM(revenue) FROM sales_2024", "format": "$"},
      {"label": "Total Orders", "sql": "SELECT COUNT(*) FROM sales_2024"},
      {"label": "Avg Order Value", "sql": "SELECT ROUND(AVG(revenue), 2) FROM sales_2024", "format": "$"}
    ],
    "charts": [
      {
        "title": "Monthly Revenue Trend",
        "type": "area",
        "sql": "SELECT DATE_TRUNC('\''month'\'', order_date)::VARCHAR as month, ROUND(SUM(revenue), 2) as revenue FROM sales_2024 GROUP BY 1 ORDER BY 1"
      },
      {
        "title": "Top Categories",
        "type": "bar",
        "sql": "SELECT category, ROUND(SUM(revenue), 2) as revenue FROM sales_2024 GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
      },
      {
        "title": "Category Split",
        "type": "donut",
        "sql": "SELECT category, COUNT(*) as orders FROM sales_2024 GROUP BY 1 ORDER BY 2 DESC LIMIT 6"
      }
    ]
  }'
```

### 3. Present

```bash
present_files ["/mnt/user-data/outputs/dashboard.json"]
```

## Notes

- The script uses DuckDB with automatic caching — subsequent queries on the same files are fast
- The frontend renders the JSON in a TipTap editor — users can drag, reorder, and edit content
- Charts are interactive ECharts with tooltips, zoom, and legend toggling
- The Data tab in the frontend shows the underlying data tables extracted from each chart
- When updating, always check the current dashboard state first with `read_file`

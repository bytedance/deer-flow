---
name: report-template
description: This skill should be used when the user wants to create reusable report templates, generate formatted reports from templates, produce periodic reports (weekly/monthly/quarterly), or create structured report layouts that can be filled with data repeatedly. Use this skill whenever the user mentions report templates, reusable reports, periodic reports, weekly reports, monthly reports, annual reports, formatted report output, or wants to define a report structure once and fill it with data multiple times — this is different from consulting-analysis which generates free-form analysis each time.
dependency:
  python: ">=3.10"
---

# Report Template Skill

This skill creates reusable report templates that can be filled with data to produce formatted HTML reports. Define the report structure once, then regenerate it with fresh data anytime — powered by Apache ECharts for embedded charts.

## Core Capabilities

- **Declarative template definition** — JSON spec with flexible section types
- **Built-in templates** — executive-summary, weekly-report, kpi-scorecard
- **Custom template creation** — define your own sections and data bindings
- **Section types** — KPI cards, charts, data tables, text blocks
- **Data binding** — SQL queries against uploaded files via DuckDB
- **HTML output** — loads Apache ECharts from CDN, requires internet to open
- **Theme support** — light, dark, corporate
- **Parameter placeholders** — `{{key}}` syntax for recurring reports

## When to Use This Skill

**Always load this skill when:**

- User wants a reusable report template for periodic generation
- User mentions weekly reports, monthly reports, quarterly reviews, or annual reports
- User wants to define a report layout once and fill it with data multiple times
- User needs a formatted HTML report with KPIs, charts, and tables
- User asks for a structured report (not free-form analysis like consulting-analysis)

## Workflow

### Step 1: Understand Requirements

Identify the following from the user's request:

| Input | Description | Required |
|-------|-------------|----------|
| **Report type** | One-time formatted report, or reusable template | Yes |
| **Data source** | CSV/Excel files under `/mnt/user-data/uploads/` | Yes |
| **Sections needed** | KPIs, charts, tables, narrative text | Yes |
| **Style / theme** | `light`, `dark`, or `corporate` | No |
| **Output format** | HTML (default) | No |

> You don't need to check the folder under `/mnt/user-data`

### Step 2: Choose or Create a Template

#### Option A: Use a Built-in Template

Three built-in templates are available:

| Template | Best For | Sections |
|----------|----------|----------|
| `executive-summary` | High-level overview for leadership | KPI row + key chart + bullet points |
| `weekly-report` | Recurring weekly status updates | Summary KPIs + trend chart + detail table + next steps |
| `kpi-scorecard` | Track metrics against targets | KPI list with targets + achievement bars + status colors |

#### Option B: Create a Custom Template

Create a JSON file in `/mnt/user-data/workspace/`:

```json
{
  "name": "monthly-sales-report",
  "title": "Monthly Sales Report - {{period}}",
  "theme": "corporate",
  "sections": [
    {
      "type": "kpi_row",
      "kpis": [
        {"label": "Total Revenue", "field": "total_revenue", "format": "currency"},
        {"label": "Orders", "field": "total_orders", "format": "number"},
        {"label": "Avg Order", "field": "avg_order_value", "format": "currency"},
        {"label": "Growth", "field": "growth_pct", "format": "percent"}
      ]
    },
    {
      "type": "chart",
      "chart_type": "line",
      "title": "Daily Revenue Trend",
      "data_source": {"sql": "SELECT date, SUM(revenue) as revenue FROM data GROUP BY date ORDER BY date", "x": "date", "y": ["revenue"]}
    },
    {
      "type": "table",
      "title": "Top 10 Products",
      "columns": ["product_name", "revenue", "orders", "growth"],
      "data_source": {"sql": "SELECT product_name, SUM(revenue) as revenue, COUNT(*) as orders, 0 as growth FROM data GROUP BY product_name ORDER BY revenue DESC LIMIT 10"},
      "highlight": {"column": "growth", "condition": "< 0", "color": "#e74c3c"}
    },
    {
      "type": "text",
      "title": "Analysis Summary",
      "content": "{{analyst_summary}}"
    }
  ]
}
```

For detailed template specification, consult `references/template-spec.md`.

### Step 3: Run the Report Generator

```bash
python /mnt/skills/public/report-template/scripts/generate.py \
  --template /mnt/user-data/workspace/monthly-report.json \
  --data-files /mnt/user-data/uploads/sales.csv \
  --output-file /mnt/user-data/outputs/monthly-report.html \
  --params '{"period": "December 2024"}'
```

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--template` | Yes | Path to template JSON, or a built-in name (`executive-summary`, `weekly-report`, `kpi-scorecard`) |
| `--data-files` | No | Data file(s) to load (CSV, Excel, JSON) |
| `--output-file` | Yes | Output HTML file path |
| `--params` | No | JSON string of parameter values for `{{placeholders}}` |
| `--theme` | No | Override theme: `light`, `dark`, `corporate` |

> [!NOTE]
> Do NOT read the Python file, just call it with the parameters.

### Step 4: Share the Report

Use `present_files` to share the generated HTML report.

## Section Types

### kpi_row

A row of KPI summary cards with optional target progress bars.

```json
{
  "type": "kpi_row",
  "kpis": [
    {"label": "Revenue", "field": "revenue", "format": "currency", "target": 100000},
    {"label": "Growth", "field": "growth", "format": "percent"}
  ]
}
```

| Field | Description |
|-------|-------------|
| `label` | Display label |
| `field` | Key name from data query results |
| `format` | `currency`, `number`, or `percent` |
| `target` | Optional target value — shows progress bar with color indicator |

### chart

An embedded ECharts visualization with data sourced from SQL.

```json
{
  "type": "chart",
  "chart_type": "line",
  "title": "Revenue Trend",
  "data_source": {
    "sql": "SELECT date, revenue FROM data ORDER BY date",
    "x": "date",
    "y": ["revenue"]
  }
}
```

Supported `chart_type`: `line`, `area`, `bar`, `column`, `pie`, `donut`, `scatter`, `treemap`, `radar`, `funnel`.

### table

A formatted data table with optional conditional highlighting.

```json
{
  "type": "table",
  "title": "Product Performance",
  "columns": ["product", "revenue", "growth"],
  "data_source": {"sql": "SELECT * FROM top_products"},
  "highlight": {"column": "growth", "condition": "< 0", "color": "#e74c3c"}
}
```

### text

A rich text section (supports basic Markdown: `**bold**`, `- list items`, `\\n` line breaks).

```json
{
  "type": "text",
  "title": "Key Findings",
  "content": "Revenue grew 15% month-over-month.\\n\\n**Top driver:** New product launch in APAC region."
}
```

## Built-in Templates

### executive-summary

```bash
python /mnt/skills/public/report-template/scripts/generate.py \
  --template executive-summary \
  --data-files /mnt/user-data/uploads/sales.csv \
  --output-file /mnt/user-data/outputs/exec-summary.html \
  --params '{"title": "Q4 Executive Summary", "period": "Q4 2024"}'
```

Sections: Title → KPI row (4 metrics) → Key trend chart → Highlight text → Footer

### weekly-report

```bash
python /mnt/skills/public/report-template/scripts/generate.py \
  --template weekly-report \
  --data-files /mnt/user-data/uploads/this_week.csv \
  --output-file /mnt/user-data/outputs/weekly-report.html \
  --params '{"week": "2024-W49", "team": "Sales"}'
```

Sections: Header (week + team) → Week-over-week KPIs → Trend chart → Detail table → Next week plan

### kpi-scorecard

```bash
python /mnt/skills/public/report-template/scripts/generate.py \
  --template kpi-scorecard \
  --data-files /mnt/user-data/uploads/metrics.csv \
  --output-file /mnt/user-data/outputs/kpi-scorecard.html \
  --params '{"period": "December 2024"}'
```

Sections: Header → KPI list with target progress bars → Status indicators → Trend chart

## Complete Example

User says: "Create a monthly sales report template using my sales data."

### Step 1: Inspect the data

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales.csv \
  --action inspect
```

### Step 2: Create template

Save to `/mnt/user-data/workspace/monthly-sales-template.json`:

```json
{
  "name": "monthly-sales",
  "title": "Monthly Sales Report - {{month}}",
  "theme": "corporate",
  "sections": [
    {
      "type": "kpi_row",
      "kpis": [
        {"label": "Total Revenue", "field": "total_revenue", "format": "currency"},
        {"label": "Orders", "field": "total_orders", "format": "number"},
        {"label": "Avg Order", "field": "avg_value", "format": "currency"}
      ]
    },
    {
      "type": "chart",
      "chart_type": "area",
      "title": "Daily Revenue",
      "data_source": {"sql": "SELECT order_date as date, SUM(revenue) as revenue FROM data GROUP BY order_date ORDER BY order_date", "x": "date", "y": ["revenue"]}
    },
    {
      "type": "table",
      "title": "Top Products",
      "columns": ["product_name", "revenue", "orders"],
      "data_source": {"sql": "SELECT product_name, SUM(revenue) as revenue, COUNT(*) as orders FROM data GROUP BY product_name ORDER BY revenue DESC LIMIT 10"}
    }
  ]
}
```

### Step 3: Generate the report

```bash
python /mnt/skills/public/report-template/scripts/generate.py \
  --template /mnt/user-data/workspace/monthly-sales-template.json \
  --data-files /mnt/user-data/uploads/sales.csv \
  --output-file /mnt/user-data/outputs/monthly-sales-2024-12.html \
  --params '{"month": "December 2024"}'
```

### Step 4: Share the result

Use `present_files` to share the generated HTML file.

## Notes

- Templates are reusable — run the same template with different `--data-files` and `--params` each time
- All data queries use DuckDB's in-process engine — no external database needed
- The `--params` JSON replaces `{{key}}` placeholders in the template's title and text content
- For PDF output, open the HTML in a browser and use Print → Save as PDF
- Use with `data-pipeline` for best results: clean data first → then generate report

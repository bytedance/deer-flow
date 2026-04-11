# Template Specification Reference

Detailed reference for creating custom report templates.

## Template Structure

A template is a JSON file with the following top-level fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Template identifier |
| `title` | string | Yes | Report title (supports `{{placeholder}}` syntax) |
| `theme` | string | No | Theme: `light`, `dark`, `corporate` (default: `light`) |
| `sections` | array | Yes | Ordered list of report sections |

## Placeholder Syntax

Use `{{key}}` in title and text content. Values are provided via `--params`:

```json
"title": "Weekly Report - {{week}}"
```

```bash
--params '{"week": "2024-W49"}'
```

## Section Types

### kpi_row

Display a row of KPI metric cards.

```json
{
  "type": "kpi_row",
  "kpis": [
    {
      "label": "Revenue",
      "field": "kpi_revenue",
      "format": "currency",
      "target": 100000
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `label` | Display name |
| `field` | Key in data results |
| `format` | `currency`, `number`, `percent` |
| `target` | Optional target value (shows progress bar) |

### chart

Embed an interactive ECharts visualization.

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

| Field | Description |
|-------|-------------|
| `chart_type` | `line`, `area`, `bar`, `column`, `pie`, `donut`, `scatter`, `treemap`, `radar`, `funnel` |
| `title` | Chart title |
| `data_source.sql` | SQL query (against loaded `data` table) |
| `data_source.x` | X-axis field name |
| `data_source.y` | Array of Y-axis field names |

### table

Display data in a formatted table.

```json
{
  "type": "table",
  "title": "Top Products",
  "columns": ["product_name", "revenue", "growth"],
  "data_source": {
    "sql": "SELECT product_name, SUM(revenue) as revenue, 0 as growth FROM data GROUP BY product_name ORDER BY revenue DESC LIMIT 10"
  },
  "highlight": {
    "column": "growth",
    "condition": "< 0",
    "color": "#e74c3c"
  }
}
```

| Field | Description |
|-------|-------------|
| `columns` | Column names to display |
| `data_source.sql` | SQL query for table data |
| `highlight.column` | Column to apply conditional highlighting |
| `highlight.condition` | Comparison: `< N` or `> N` |
| `highlight.color` | CSS color for highlighted cells |

### text

Display a text block (supports basic Markdown).

```json
{
  "type": "text",
  "title": "Summary",
  "content": "Revenue grew 15% MoM.\\n\\n**Key driver:** New product launch."
}
```

| Field | Description |
|-------|-------------|
| `title` | Section heading |
| `content` | Text content with `\\n` for line breaks, `**bold**`, `- list items` |

## Data Binding

All SQL queries execute against DuckDB tables loaded from `--data-files`:

- First data file → `data` table
- Additional files → tables named by their filename (sanitized)
- All DuckDB SQL features are available (JOINs, window functions, CTEs, etc.)

## Built-in KPI Fields

When using built-in templates, these KPI fields are auto-computed:

| Field | SQL | Description |
|-------|-----|-------------|
| `kpi_revenue` | `SUM(revenue) FROM data` | Total revenue |
| `kpi_orders` | `COUNT(*) FROM data` | Total orders |
| `kpi_avg` | `AVG(revenue) FROM data` | Average order value |
| `kpi_customers` | `COUNT(DISTINCT customer_id) FROM data` | Unique customers |

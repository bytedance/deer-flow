---
name: data-analysis
description: Use this skill when the user uploads Excel (.xlsx/.xls) or CSV files and wants to perform data analysis, generate statistics, create summaries, pivot tables, SQL queries, or any form of structured data exploration. Supports multi-sheet Excel workbooks, aggregation, filtering, joins, and exporting results to CSV/JSON/Markdown.
---

# Data Analysis Skill

## Overview

This skill analyzes user-uploaded Excel/CSV files using DuckDB — an in-process analytical SQL engine. It supports schema inspection, SQL-based querying, statistical summaries, and result export, all through a single Python script.

## Core Capabilities

- Inspect Excel/CSV file structure (sheets, columns, types, row counts)
- Execute arbitrary SQL queries against uploaded data
- Generate statistical summaries (mean, median, stddev, percentiles, nulls)
- Support multi-sheet Excel workbooks (each sheet becomes a table)
- Export query results to CSV, JSON, or Markdown
- Handle large files efficiently with DuckDB's columnar engine

## Workflow

### Step 1: Understand Requirements

When a user uploads data files and requests analysis, identify:

- **File location**: Path(s) to uploaded Excel/CSV files under `/mnt/user-data/uploads/`
- **Analysis goal**: What insights the user wants (summary, filtering, aggregation, comparison, etc.)
- **Output format**: How results should be presented (table, CSV export, JSON, etc.)
- You don't need to check the folder under `/mnt/user-data`

### Step 2: Inspect File Structure

First, inspect the uploaded file to understand its schema:

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action inspect
```

This returns:
- Sheet names (for Excel) or filename (for CSV)
- Column names, data types, and non-null counts
- Row count per sheet/file
- Sample data (first 5 rows)

### Step 3: Perform Analysis

Based on the schema, construct SQL queries to answer the user's questions.

#### Run SQL Query

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action query \
  --sql "SELECT category, COUNT(*) as count, AVG(amount) as avg_amount FROM Sheet1 GROUP BY category ORDER BY count DESC"
```

#### Generate Statistical Summary

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action summary \
  --table Sheet1
```

This returns for each numeric column: count, mean, std, min, 25%, 50%, 75%, max, null_count.
For string columns: count, unique, top value, frequency, null_count.

#### Export Results

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action query \
  --sql "SELECT * FROM Sheet1 WHERE amount > 1000" \
  --output-file /mnt/user-data/outputs/filtered-results.csv
```

Supported output formats (auto-detected from extension):
- `.csv` — Comma-separated values
- `.json` — JSON array of records
- `.md` — Markdown table

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--files` | Yes | Space-separated paths to Excel/CSV files |
| `--action` | Yes | One of: `inspect`, `query`, `summary` |
| `--sql` | For `query` | SQL query to execute |
| `--table` | For `summary` | Table/sheet name to summarize |
| `--output-file` | No | Path to export results (CSV/JSON/MD) |

> [!NOTE]
> Do NOT read the Python file, just call it with the parameters.

## Table Naming Rules

- **Excel files**: Each sheet becomes a table named after the sheet (e.g., `Sheet1`, `Sales`, `Revenue`)
- **CSV files**: Table name is the filename without extension (e.g., `data.csv` → `data`)
- **Multiple files**: All tables from all files are available in the same query context, enabling cross-file joins
- **Special characters**: Sheet/file names with spaces or special characters are auto-sanitized (spaces → underscores). Use double quotes for names that start with numbers or contain special characters, e.g., `"2024_Sales"`

## Analysis Patterns

### Basic Exploration
```sql
-- Row count
SELECT COUNT(*) FROM Sheet1

-- Distinct values in a column
SELECT DISTINCT category FROM Sheet1

-- Value distribution
SELECT category, COUNT(*) as cnt FROM Sheet1 GROUP BY category ORDER BY cnt DESC

-- Date range
SELECT MIN(date_col), MAX(date_col) FROM Sheet1
```

### Aggregation & Grouping
```sql
-- Revenue by category and month
SELECT category, DATE_TRUNC('month', order_date) as month,
       SUM(revenue) as total_revenue
FROM Sales
GROUP BY category, month
ORDER BY month, total_revenue DESC

-- Top 10 customers by spend
SELECT customer_name, SUM(amount) as total_spend
FROM Orders GROUP BY customer_name
ORDER BY total_spend DESC LIMIT 10
```

### Cross-file Joins
```sql
-- Join sales with customer info from different files
SELECT s.order_id, s.amount, c.customer_name, c.region
FROM sales s
JOIN customers c ON s.customer_id = c.id
WHERE s.amount > 500
```

### Window Functions
```sql
-- Running total and rank
SELECT order_date, amount,
       SUM(amount) OVER (ORDER BY order_date) as running_total,
       RANK() OVER (ORDER BY amount DESC) as amount_rank
FROM Sales
```

### Pivot-style Analysis
```sql
-- Pivot: monthly revenue by category
SELECT category,
       SUM(CASE WHEN MONTH(date) = 1 THEN revenue END) as Jan,
       SUM(CASE WHEN MONTH(date) = 2 THEN revenue END) as Feb,
       SUM(CASE WHEN MONTH(date) = 3 THEN revenue END) as Mar
FROM Sales
GROUP BY category
```

## Complete Example

User uploads `sales_2024.xlsx` (with sheets: `Orders`, `Products`, `Customers`) and asks: "Analyze my sales data — show top products by revenue and monthly trends."

### Step 1: Inspect the file

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales_2024.xlsx \
  --action inspect
```

### Step 2: Top products by revenue

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales_2024.xlsx \
  --action query \
  --sql "SELECT p.product_name, SUM(o.quantity * o.unit_price) as total_revenue, SUM(o.quantity) as total_units FROM Orders o JOIN Products p ON o.product_id = p.id GROUP BY p.product_name ORDER BY total_revenue DESC LIMIT 10"
```

### Step 3: Monthly revenue trends

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales_2024.xlsx \
  --action query \
  --sql "SELECT DATE_TRUNC('month', order_date) as month, SUM(quantity * unit_price) as revenue FROM Orders GROUP BY month ORDER BY month" \
  --output-file /mnt/user-data/outputs/monthly-trends.csv
```

### Step 4: Statistical summary

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales_2024.xlsx \
  --action summary \
  --table Orders
```

Present results to the user with clear explanations of findings, trends, and actionable insights.

## Multi-file Example

User uploads `orders.csv` and `customers.xlsx` and asks: "Which region has the highest average order value?"

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/orders.csv /mnt/user-data/uploads/customers.xlsx \
  --action query \
  --sql "SELECT c.region, AVG(o.amount) as avg_order_value, COUNT(*) as order_count FROM orders o JOIN Customers c ON o.customer_id = c.id GROUP BY c.region ORDER BY avg_order_value DESC"
```

## Output Handling

After analysis:

- Present query results directly in conversation as formatted tables
- For large results, export to file and share via `present_files` tool
- Always explain findings in plain language with key takeaways
- Suggest follow-up analyses when patterns are interesting
- Offer to export results if the user wants to keep them

## Caching

The script automatically caches loaded data to avoid re-parsing files on every call:

- On first load, files are parsed and stored in a persistent DuckDB database under `/mnt/user-data/workspace/.data-analysis-cache/`
- The cache key is a SHA256 hash of all input file contents — if files change, a new cache is created
- Subsequent calls with the same files will use the cached database directly (near-instant startup)
- Cache is transparent — no extra parameters needed

This is especially useful when running multiple queries against the same data files (inspect → query → summary).

## Notes

- DuckDB supports full SQL including window functions, CTEs, subqueries, and advanced aggregations
- Excel date columns are automatically parsed; use DuckDB date functions (`DATE_TRUNC`, `EXTRACT`, etc.)
- For very large files (100MB+), DuckDB handles them efficiently without loading everything into memory
- Column names with spaces are accessible using double quotes: `"Column Name"`

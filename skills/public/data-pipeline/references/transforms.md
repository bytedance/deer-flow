# Pipeline Transform Reference

Detailed parameter reference for all pipeline actions.

## Table of Contents

- [Input Actions](#input-actions)
- [Cleaning Actions](#cleaning-actions)
- [Transform Actions](#transform-actions)
- [Merge Actions](#merge-actions)
- [Filter Actions](#filter-actions)
- [Output Actions](#output-actions)

---

## Input Actions

### load_csv

Load a CSV file into a named table.

```json
{"action": "load_csv", "file": "/path/to/data.csv", "as": "table_name"}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | string | Yes | Absolute path to CSV file |
| `as` | string | Yes | Name for the created table |

DuckDB auto-detects column types and delimiters.

### load_excel

Load all sheets from an Excel file. Each sheet becomes a table named `{base}_{sheet_name}`.

```json
{"action": "load_excel", "file": "/path/to/data.xlsx", "as": "prefix"}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | string | Yes | Absolute path to Excel file |
| `as` | string | Yes | Prefix for created table names |

### load_json

Load a JSON file containing an array of objects.

```json
{"action": "load_json", "file": "/path/to/data.json", "as": "table_name"}
```

---

## Cleaning Actions

### drop_nulls

Drop rows where any of the specified columns contain NULL values.

```json
{"action": "drop_nulls", "table": "sales", "columns": ["order_id", "revenue"]}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `table` | string | Yes | Target table name |
| `columns` | array | Yes | Column names to check for nulls |

SQL equivalent: `DELETE FROM table WHERE col1 IS NULL OR col2 IS NULL`

### fill_nulls

Replace NULL values with specified defaults per column.

```json
{
  "action": "fill_nulls",
  "table": "sales",
  "columns": {"region": "Unknown", "notes": "", "discount": "0"}
}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `table` | string | Yes | Target table name |
| `columns` | object | Yes | Mapping of column name → default value |

SQL equivalent: `COALESCE(col, default) AS col`

### drop_duplicates

Remove rows with duplicate values in the specified columns, keeping the first occurrence.

```json
{"action": "drop_duplicates", "table": "sales", "columns": ["order_id"]}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `table` | string | Yes | Target table name |
| `columns` | array | Yes | Columns to check for duplicates |

SQL equivalent: `ROW_NUMBER() OVER (PARTITION BY cols) = 1`

### trim_strings

Trim leading/trailing whitespace from string columns.

```json
{"action": "trim_strings", "table": "sales"}
```

```json
{"action": "trim_strings", "table": "sales", "columns": ["name", "email"]}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `table` | string | Yes | Target table name |
| `columns` | array | No | Specific columns (default: all string columns) |

### normalize_dates

Parse date columns into standard DATE type.

```json
{"action": "normalize_dates", "table": "sales", "columns": ["order_date"], "format": "%Y-%m-%d"}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `table` | string | Yes | Target table name |
| `columns` | array | Yes | Date columns to normalize |
| `format` | string | No | Expected format (default: `%Y-%m-%d`) |

SQL equivalent: `TRY_CAST(col AS DATE)`

---

## Transform Actions

### cast_types

Cast columns to specified DuckDB data types.

```json
{"action": "cast_types", "table": "sales", "columns": {"revenue": "DOUBLE", "quantity": "INTEGER"}}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `table` | string | Yes | Target table name |
| `columns` | object | Yes | Mapping of column → DuckDB type name |

Common types: `INTEGER`, `BIGINT`, `DOUBLE`, `VARCHAR`, `DATE`, `TIMESTAMP`, `BOOLEAN`

### rename_columns

Rename columns using an old-name → new-name mapping.

```json
{"action": "rename_columns", "table": "sales", "mapping": {"old_name": "new_name"}}
```

### add_computed_column

Add a new column computed from a SQL expression referencing existing columns.

```json
{"action": "add_computed_column", "table": "sales", "column": "total", "expr": "price * quantity"}
```

```json
{"action": "add_computed_column", "table": "sales", "column": "category_label", "expr": "CASE WHEN amount > 1000 THEN 'high' ELSE 'low' END"}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `table` | string | Yes | Target table name |
| `column` | string | Yes | Name for the new column |
| `expr` | string | Yes | SQL expression (can reference existing columns) |

### group_by

Group rows and compute aggregations.

```json
{
  "action": "group_by",
  "table": "sales",
  "by": ["region", "category"],
  "aggregations": {
    "total_revenue": "SUM(revenue)",
    "order_count": "COUNT(*)",
    "avg_price": "AVG(price)"
  },
  "as": "summary"
}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `table` | string | Yes | Source table |
| `by` | array | Yes | Columns to group by |
| `aggregations` | object | Yes | Mapping of output column → SQL aggregate expression |
| `as` | string | No | Output table name (default: overwrite source) |

---

## Merge Actions

### join

Join two tables on specified columns.

```json
{
  "action": "join",
  "left": "orders",
  "right": "customers",
  "on": ["customer_id"],
  "how": "left",
  "as": "enriched"
}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `left` | string | Yes | Left table |
| `right` | string | Yes | Right table |
| `on` | array | Yes | Columns to join on (must exist in both) |
| `how` | string | No | Join type: `inner`, `left`, `right`, `full` (default: `inner`) |
| `as` | string | Yes | Output table name |

### union

Stack multiple tables vertically (UNION ALL). Tables must have compatible columns.

```json
{"action": "union", "tables": ["sales_2023", "sales_2024"], "as": "all_sales"}
```

---

## Filter Actions

### filter

Filter rows using a SQL WHERE clause.

```json
{"action": "filter", "table": "sales", "condition": "revenue > 100 AND region = 'US'"}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `table` | string | Yes | Target table name |
| `condition` | string | Yes | SQL WHERE expression |

### sample

Take a random sample of rows.

```json
{"action": "sample", "table": "big_data", "n": 1000, "as": "sampled"}
```

```json
{"action": "sample", "table": "big_data", "fraction": 0.1, "as": "sampled"}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `table` | string | Yes | Source table |
| `n` | integer | No* | Exact number of rows |
| `fraction` | float | No* | Fraction (0.0–1.0) of rows |
| `as` | string | No | Output table name |

*One of `n` or `fraction` is required.

### top_n

Get the top N rows ordered by a column.

```json
{"action": "top_n", "table": "sales", "order_by": "revenue", "n": 10, "direction": "DESC", "as": "top_sales"}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `table` | string | Yes | Source table |
| `order_by` | string | Yes | Column to order by |
| `n` | integer | No | Number of rows (default: 10) |
| `direction` | string | No | `ASC` or `DESC` (default: `DESC`) |
| `as` | string | No | Output table name |

---

## Output Actions

### export_csv

Export a table to a CSV file with headers.

```json
{"action": "export_csv", "table": "cleaned", "file": "/mnt/user-data/outputs/result.csv"}
```

### export_json

Export a table to a JSON file (array of objects).

```json
{"action": "export_json", "table": "cleaned", "file": "/mnt/user-data/outputs/result.json"}
```

### export_excel

Export a table to an Excel (.xlsx) file.

```json
{"action": "export_excel", "table": "cleaned", "file": "/mnt/user-data/outputs/result.xlsx"}
```

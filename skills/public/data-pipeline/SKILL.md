---
name: data-pipeline
description: This skill should be used when the user wants to clean data, run ETL processes, preprocess datasets, transform data formats, handle missing values, merge multiple data sources, normalize data, deduplicate records, or perform any data wrangling before analysis. Use this skill whenever the user mentions data cleaning, ETL, data preprocessing, data wrangling, data transformation, missing value handling, format conversion, data merging, deduplication, or needs to prepare messy raw data for analysis — this is different from data-analysis which only queries data without modifying it.
dependency:
  python: ">=3.10"
---

# Data Pipeline Skill

This skill cleans, transforms, and reshapes data using a declarative pipeline spec. It handles the full ETL workflow: multi-source data ingestion, cleaning, transformation, merging, and export — producing new cleaned data files ready for analysis or visualization.

## Core Capabilities

- **Multi-source data loading** — CSV, Excel, JSON
- **Data cleaning** — null handling, deduplication, string trimming, date normalization
- **Data transformation** — column rename, type casting, computed columns, pivot/unpivot, aggregation
- **Multi-table operations** — join, union
- **Filtering and sampling** — condition-based filtering, random sampling, top-N
- **Multi-format export** — CSV, JSON, Excel
- **Pipeline execution report** — row counts and change tracking per step

## When to Use This Skill

**Always load this skill when:**

- User wants to clean, preprocess, or wrangle data
- User mentions ETL, data transformation, data pipeline, or data preparation
- User needs to handle missing values, remove duplicates, or normalize data formats
- User wants to merge multiple data files or join tables
- User needs to export cleaned/transformed data as a new file
- User's data is messy and needs preparation before analysis

## Workflow

### Step 1: Understand Requirements

Identify the following from the user's request:

| Input | Description | Required |
|-------|-------------|----------|
| **Input files** | Path(s) to raw data files under `/mnt/user-data/uploads/` | Yes |
| **Cleaning goals** | Issues to fix (missing values, duplicates, wrong formats, etc.) | Yes |
| **Transformation needs** | Column operations, merges, aggregations | No |
| **Output format** | CSV, JSON, or Excel | Yes |
| **Output location** | Where to save under `/mnt/user-data/outputs/` | Yes |

> You don't need to check the folder under `/mnt/user-data`

### Step 2: Inspect the Data (optional)

Use the data-analysis skill to inspect raw data first:

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales.csv \
  --action inspect
```

### Step 3: Create Pipeline Spec

Create a JSON file in `/mnt/user-data/workspace/` defining the pipeline steps:

```json
{
  "steps": [
    {"action": "load_csv", "file": "/mnt/user-data/uploads/sales.csv", "as": "raw_sales"},
    {"action": "load_csv", "file": "/mnt/user-data/uploads/products.csv", "as": "products"},
    {"action": "drop_nulls", "table": "raw_sales", "columns": ["order_id", "revenue"]},
    {"action": "fill_nulls", "table": "raw_sales", "columns": {"region": "Unknown"}},
    {"action": "drop_duplicates", "table": "raw_sales", "columns": ["order_id"]},
    {"action": "trim_strings", "table": "raw_sales"},
    {"action": "normalize_dates", "table": "raw_sales", "columns": ["order_date"], "format": "%Y-%m-%d"},
    {"action": "cast_types", "table": "raw_sales", "columns": {"revenue": "DOUBLE", "quantity": "INTEGER"}},
    {"action": "join", "left": "raw_sales", "right": "products", "on": ["product_id"], "how": "left", "as": "enriched"},
    {"action": "add_computed_column", "table": "enriched", "column": "margin", "expr": "revenue - cost"},
    {"action": "rename_columns", "table": "enriched", "mapping": {"margin": "profit_margin"}},
    {"action": "filter", "table": "enriched", "condition": "revenue > 0"},
    {"action": "export_csv", "table": "enriched", "file": "/mnt/user-data/outputs/cleaned-sales.csv"}
  ]
}
```

### Step 4: Run the Pipeline

```bash
python /mnt/skills/public/data-pipeline/scripts/pipeline.py \
  --spec-file /mnt/user-data/workspace/pipeline-spec.json
```

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--spec-file` | Yes | Path to the pipeline spec JSON file |

> [!NOTE]
> Do NOT read the Python file, just call it with the parameters.

For detailed parameter specifications of each action, consult `references/transforms.md`.

## Supported Pipeline Actions

### Input Actions

| Action | Required Params | Description |
|--------|----------------|-------------|
| `load_csv` | `file`, `as` | Load CSV file into a named table |
| `load_excel` | `file`, `as` | Load Excel file (all sheets) |
| `load_json` | `file`, `as` | Load JSON file (array of objects) |

### Cleaning Actions

| Action | Required Params | Description |
|--------|----------------|-------------|
| `drop_nulls` | `table`, `columns` (array) | Drop rows with null values in specified columns |
| `fill_nulls` | `table`, `columns` (object of col:value) | Fill null values with specified defaults. Use matching JSON types: strings for text (`"Unknown"`), numbers for numeric columns (`0` not `"0"`) |
| `drop_duplicates` | `table`, `columns` (array) | Remove duplicate rows based on columns |
| `trim_strings` | `table`, `columns` (optional) | Trim whitespace from string columns |
| `normalize_dates` | `table`, `columns`, `format` | Parse date columns into standard format |

### Transform Actions

| Action | Required Params | Description |
|--------|----------------|-------------|
| `rename_columns` | `table`, `mapping` (object of old:new) | Rename columns |
| `cast_types` | `table`, `columns` (object of col:type) | Cast column data types |
| `add_computed_column` | `table`, `column`, `expr` | Add a new column computed from SQL expression |
| `group_by` | `table`, `by` (array), `aggregations` (object) | Group and aggregate |

### Merge Actions

| Action | Required Params | Description |
|--------|----------------|-------------|
| `join` | `left`, `right`, `on`, `how`, `as` | Join two tables (inner/left/right/full) |
| `union` | `tables` (array), `as` | Union (stack) multiple tables |

### Filter Actions

| Action | Required Params | Description |
|--------|----------------|-------------|
| `filter` | `table`, `condition` (SQL WHERE) | Filter rows by condition |
| `sample` | `table`, `n` or `fraction`, `as` | Random sample of rows |
| `top_n` | `table`, `order_by`, `n`, `as` | Top N rows ordered by column |

### Output Actions

| Action | Required Params | Description |
|--------|----------------|-------------|
| `export_csv` | `table`, `file` | Export to CSV |
| `export_json` | `table`, `file` | Export to JSON |
| `export_excel` | `table`, `file` | Export to Excel |

## Complete Example

User uploads `orders.csv` (messy) and `customers.csv` and says: "Clean the orders data, merge with customer info, and export as CSV."

### Step 1: Inspect raw data

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/orders.csv \
  --action inspect
```

### Step 2: Create pipeline spec

Save to `/mnt/user-data/workspace/clean-orders-spec.json`:

```json
{
  "steps": [
    {"action": "load_csv", "file": "/mnt/user-data/uploads/orders.csv", "as": "orders"},
    {"action": "load_csv", "file": "/mnt/user-data/uploads/customers.csv", "as": "customers"},
    {"action": "drop_nulls", "table": "orders", "columns": ["order_id", "amount"]},
    {"action": "fill_nulls", "table": "orders", "columns": {"notes": ""}},
    {"action": "drop_duplicates", "table": "orders", "columns": ["order_id"]},
    {"action": "trim_strings", "table": "orders"},
    {"action": "normalize_dates", "table": "orders", "columns": ["order_date"], "format": "%Y-%m-%d"},
    {"action": "cast_types", "table": "orders", "columns": {"amount": "DOUBLE", "quantity": "INTEGER"}},
    {"action": "join", "left": "orders", "right": "customers", "on": ["customer_id"], "how": "left", "as": "enriched"},
    {"action": "add_computed_column", "table": "enriched", "column": "total", "expr": "amount * quantity"},
    {"action": "filter", "table": "enriched", "condition": "amount > 0"},
    {"action": "export_csv", "table": "enriched", "file": "/mnt/user-data/outputs/cleaned-orders.csv"}
  ]
}
```

### Step 3: Run the pipeline

```bash
python /mnt/skills/public/data-pipeline/scripts/pipeline.py \
  --spec-file /mnt/user-data/workspace/clean-orders-spec.json
```

The script outputs an execution report:

```
Pipeline Execution Report
==================================================
Step 1: load_csv → orders (10,000 rows)
Step 2: load_csv → customers (500 rows)
Step 3: drop_nulls on orders (10,000 → 9,850 rows, -150)
Step 4: fill_nulls on orders (9,850 rows, filled notes in 230 rows)
Step 5: drop_duplicates on orders (9,850 → 9,800 rows, -50)
Step 6: trim_strings on orders (9,800 rows, 4 columns trimmed)
Step 7: normalize_dates on orders (9,800 rows, 1 columns)
Step 8: cast_types on orders (9,800 rows, 2 columns cast)
Step 9: join orders + customers → enriched (9,800 rows, left)
Step 10: add_computed_column 'total' on enriched (9,800 rows)
Step 11: filter on enriched (9,800 → 9,750 rows, -50)
Step 12: export_csv → /mnt/user-data/outputs/cleaned-orders.csv (9,750 rows)
==================================================
Done in 2.3s (1 file(s) exported)
```

### Step 4: Verify the output

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/outputs/cleaned-orders.csv \
  --action inspect
```

## Output Handling

After pipeline execution:

- Present the execution report to the user
- Suggest follow-up: use `data-analysis` to query cleaned data, or `dashboard-generator` to visualize
- Share exported files using `present_files` if the user wants to download them

## Notes

- All operations use DuckDB's in-process SQL engine — no external database needed
- The pipeline runs in-memory; for very large files (1GB+), consider splitting into batches
- Every `as` parameter creates a new table — original data is never modified in place
- Column names with spaces need double quotes in expressions: `"Column Name"`
- For complex transformations not covered by built-in actions, use `add_computed_column` with any valid DuckDB SQL expression

---
description: Profile and explore a dataset to understand its shape, quality, and patterns
argument-hint: "<table or file>"
---

# /explore-data - Profile and Explore a Dataset

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Generate a comprehensive data profile for a table or uploaded file. Understand its shape, quality, and patterns before diving into analysis.

## Usage

```
/explore-data <table_name or file>
```

## Workflow

### 1. Access the Data

**If a data warehouse MCP server is connected:**

1. Resolve the table name (handle schema prefixes, suggest matches if ambiguous)
2. Query table metadata: column names, types, descriptions if available
3. Run profiling queries against the live data

**If a file is provided (CSV, Excel, Parquet, JSON):**

1. Read the file and load into a working dataset
2. Infer column types from the data

**If neither:**

1. Ask the user to provide a table name (with their warehouse connected) or upload a file
2. If they describe a table schema, provide guidance on what profiling queries to run

### 2. Generate Data Profile

Run the following profiling checks:

**Table-level metrics:**
- Total row count
- Column count and types breakdown
- Approximate table size (if available from metadata)
- Date range coverage (min/max of date columns)

**Column-level metrics for each column:**
- Data type (and whether it matches expected type)
- Null count and null rate (%)
- Distinct count and cardinality (distinct / total)
- For numeric columns: min, max, mean, median, stddev, percentiles (p25, p50, p75, p95, p99)
- For string columns: min/max length, most common values (top 10), empty string count
- For date/timestamp columns: min, max, distribution by time period
- For boolean columns: true/false/null distribution

**Present the profile as a clean summary table**, grouped by column type (dimensions, metrics, dates, IDs).

### 3. Identify Data Quality Issues

Flag potential problems:

- **High null rates**: Columns with >5% nulls (warn), >20% nulls (alert)
- **Low cardinality surprises**: Columns that should be high-cardinality but aren't (e.g., a "user_id" with only 50 distinct values)
- **High cardinality surprises**: Columns that should be categorical but have too many distinct values
- **Suspicious values**: Negative amounts where only positive expected, future dates in historical data, obviously placeholder values (e.g., "N/A", "TBD", "test", "999999")
- **Duplicate detection**: Check if there's a natural key and whether it has duplicates
- **Distribution skew**: Extremely skewed numeric distributions that could affect averages
- **Encoding issues**: Mixed case in categorical fields, trailing whitespace, inconsistent formats

### 4. Suggest Interesting Dimensions and Metrics

Based on the column profile, recommend:

- **Best dimension columns** for slicing data (categorical columns with reasonable cardinality, 3-50 values)
- **Key metric columns** for measurement (numeric columns with meaningful distributions)
- **Time columns** suitable for trend analysis
- **Natural groupings** or hierarchies apparent in the data
- **Potential join keys** linking to other tables (ID columns, foreign keys)

### 5. Recommend Follow-Up Analyses

Suggest 3-5 specific analyses the user could run next:

- "Trend analysis on [metric] by [time_column] grouped by [dimension]"
- "Distribution deep-dive on [skewed_column] to understand outliers"
- "Data quality investigation on [problematic_column]"
- "Correlation analysis between [metric_a] and [metric_b]"
- "Cohort analysis using [date_column] and [status_column]"

## Output Format

```
## Data Profile: [table_name]

### Overview
- Rows: 2,340,891
- Columns: 23 (8 dimensions, 6 metrics, 4 dates, 5 IDs)
- Date range: 2021-03-15 to 2024-01-22

### Column Details
[summary table]

### Data Quality Issues
[flagged issues with severity]

### Recommended Explorations
[numbered list of suggested follow-up analyses]
```

## Tips

- For very large tables (100M+ rows), profiling queries use sampling by default -- mention if you need exact counts
- If exploring a new dataset for the first time, this command gives you the lay of the land before writing specific queries
- The quality flags are heuristic -- not every flag is a real problem, but each is worth a quick look

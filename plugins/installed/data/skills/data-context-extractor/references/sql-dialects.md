# SQL Dialect Reference

Include the appropriate section in generated skills based on the user's data warehouse.

---

## BigQuery

```markdown
## SQL Dialect: BigQuery

- **Table references**: Use backticks: \`project.dataset.table\`
- **Safe division**: `SAFE_DIVIDE(a, b)` returns NULL instead of error
- **Date functions**:
  - `DATE_TRUNC(date_col, MONTH)`
  - `DATE_SUB(date_col, INTERVAL 1 DAY)`
  - `DATE_DIFF(end_date, start_date, DAY)`
- **Column exclusion**: `SELECT * EXCEPT(column_to_exclude)`
- **Arrays**: `UNNEST(array_column)` to flatten
- **Structs**: Access with dot notation `struct_col.field_name`
- **Timestamps**: `TIMESTAMP_TRUNC()`, times in UTC by default
- **String matching**: `LIKE`, `REGEXP_CONTAINS(col, r'pattern')`
- **NULLs in aggregations**: Most functions ignore NULLs; use `IFNULL()` or `COALESCE()`
```

---

## Snowflake

```markdown
## SQL Dialect: Snowflake

- **Table references**: `DATABASE.SCHEMA.TABLE` or with quotes for case-sensitive: `"Column_Name"`
- **Safe division**: `DIV0(a, b)` returns 0, `DIV0NULL(a, b)` returns NULL
- **Date functions**:
  - `DATE_TRUNC('MONTH', date_col)`
  - `DATEADD(DAY, -1, date_col)`
  - `DATEDIFF(DAY, start_date, end_date)`
- **Column exclusion**: `SELECT * EXCLUDE (column_to_exclude)`
- **Arrays**: `FLATTEN(array_column)` to flatten, access with `value`
- **Variants/JSON**: Access with colon notation `variant_col:field_name`
- **Timestamps**: `TIMESTAMP_NTZ` (no timezone), `TIMESTAMP_TZ` (with timezone)
- **String matching**: `LIKE`, `REGEXP_LIKE(col, 'pattern')`
- **Case sensitivity**: Identifiers are uppercase by default unless quoted
```

---

## PostgreSQL / Redshift

```markdown
## SQL Dialect: PostgreSQL/Redshift

- **Table references**: `schema.table` (lowercase convention)
- **Safe division**: `NULLIF(b, 0)` pattern: `a / NULLIF(b, 0)`
- **Date functions**:
  - `DATE_TRUNC('month', date_col)`
  - `date_col - INTERVAL '1 day'`
  - `DATE_PART('day', end_date - start_date)`
- **Column selection**: No EXCEPT; must list columns explicitly
- **Arrays**: `UNNEST(array_column)` (PostgreSQL), limited in Redshift
- **JSON**: `json_col->>'field_name'` for text, `json_col->'field_name'` for JSON
- **Timestamps**: `AT TIME ZONE 'UTC'` for timezone conversion
- **String matching**: `LIKE`, `col ~ 'pattern'` for regex
- **Boolean**: Native BOOLEAN type; use `TRUE`/`FALSE`
```

---

## Databricks / Spark SQL

```markdown
## SQL Dialect: Databricks/Spark SQL

- **Table references**: `catalog.schema.table` (Unity Catalog) or `schema.table`
- **Safe division**: Use `NULLIF`: `a / NULLIF(b, 0)` or `TRY_DIVIDE(a, b)`
- **Date functions**:
  - `DATE_TRUNC('MONTH', date_col)`
  - `DATE_SUB(date_col, 1)`
  - `DATEDIFF(end_date, start_date)`
- **Column exclusion**: `SELECT * EXCEPT (column_to_exclude)` (Databricks SQL)
- **Arrays**: `EXPLODE(array_column)` to flatten
- **Structs**: Access with dot notation `struct_col.field_name`
- **JSON**: `json_col:field_name` or `GET_JSON_OBJECT()`
- **String matching**: `LIKE`, `RLIKE` for regex
- **Delta features**: `DESCRIBE HISTORY`, time travel with `VERSION AS OF`
```

---

## MySQL

```markdown
## SQL Dialect: MySQL

- **Table references**: \`database\`.\`table\` with backticks
- **Safe division**: Manual: `IF(b = 0, NULL, a / b)` or `a / NULLIF(b, 0)`
- **Date functions**:
  - `DATE_FORMAT(date_col, '%Y-%m-01')` for truncation
  - `DATE_SUB(date_col, INTERVAL 1 DAY)`
  - `DATEDIFF(end_date, start_date)`
- **Column selection**: No EXCEPT; must list columns explicitly
- **Arrays**: Limited native support; often stored as JSON
- **JSON**: `JSON_EXTRACT(col, '$.field')` or `col->>'$.field'`
- **Timestamps**: `CONVERT_TZ()` for timezone conversion
- **String matching**: `LIKE`, `REGEXP` for regex
- **Case sensitivity**: Table names case-sensitive on Linux, not on Windows
```

---

## Common Patterns Across Dialects

| Operation | BigQuery | Snowflake | PostgreSQL | Databricks |
|-----------|----------|-----------|------------|------------|
| Current date | `CURRENT_DATE()` | `CURRENT_DATE()` | `CURRENT_DATE` | `CURRENT_DATE()` |
| Current timestamp | `CURRENT_TIMESTAMP()` | `CURRENT_TIMESTAMP()` | `NOW()` | `CURRENT_TIMESTAMP()` |
| String concat | `CONCAT()` or `\|\|` | `CONCAT()` or `\|\|` | `CONCAT()` or `\|\|` | `CONCAT()` or `\|\|` |
| Coalesce | `COALESCE()` | `COALESCE()` | `COALESCE()` | `COALESCE()` |
| Case when | `CASE WHEN` | `CASE WHEN` | `CASE WHEN` | `CASE WHEN` |
| Count distinct | `COUNT(DISTINCT x)` | `COUNT(DISTINCT x)` | `COUNT(DISTINCT x)` | `COUNT(DISTINCT x)` |

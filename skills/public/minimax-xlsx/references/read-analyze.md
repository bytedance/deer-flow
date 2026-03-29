# Data Reading & Analysis Guide

> Reference for the READ path. Use `xlsx_reader.py` for structure discovery and data quality auditing,
> then pandas for custom analysis. **Never modify the source file.**

---

## When to Use This Path

The user asks to read, analyze, view, summarize, extract, or answer questions about an Excel/CSV file's contents,
without requiring file modification. If modification is needed, hand off to `edit.md`.

---

## Workflow

### Step 1 — Structure Discovery

Run `xlsx_reader.py` first. It handles format detection, encoding fallback, structure exploration, and data quality audit:

```bash
python3 SKILL_DIR/scripts/xlsx_reader.py input.xlsx                 # full report
python3 SKILL_DIR/scripts/xlsx_reader.py input.xlsx --sheet Sales   # single sheet
python3 SKILL_DIR/scripts/xlsx_reader.py input.xlsx --quality       # quality audit only
python3 SKILL_DIR/scripts/xlsx_reader.py input.xlsx --json          # machine-readable
```

Supported formats: `.xlsx`, `.xlsm`, `.csv`, `.tsv`. The script tries multiple encodings for CSV (utf-8-sig, gbk, utf-8, latin-1).

### Step 2 — Custom Analysis with pandas

Load data and perform the analysis the user requests:

```python
import pandas as pd
df = pd.read_excel("input.xlsx", sheet_name=None)  # dict of all sheets
# For CSV: pd.read_csv("input.csv")
```

**Header handling** (when the default `header=0` doesn't work):

| Situation | Code |
|-----------|------|
| Header on row 3 | `pd.read_excel(path, header=2)` |
| Multi-level merged header | `pd.read_excel(path, header=[0, 1])` |
| No header | `pd.read_excel(path, header=None)` |

**Analysis quick reference:**

| Scenario | Pattern |
|----------|---------|
| Descriptive stats | `df.describe()` or `df['Col'].agg(['sum', 'mean', 'min', 'max'])` |
| Group aggregation | `df.groupby('Region')['Revenue'].agg(Total='sum', Avg='mean')` |
| Top N | `df.groupby('Region')['Revenue'].sum().sort_values(ascending=False).head(5)` |
| Pivot table | `df.pivot_table(values='Revenue', index='Region', columns='Quarter', aggfunc='sum', margins=True)` |
| Time series | `df.set_index(pd.to_datetime(df['Date'])).resample('ME')['Revenue'].sum()` |
| Cross-sheet merge | `pd.merge(sales, customers, on='CustomerID', how='left', validate='m:1')` |
| Stack sheets | `pd.concat([df.assign(Source=name) for name, df in sheets.items()], ignore_index=True)` |
| Large files (>50MB) | `pd.read_excel(path, usecols=['Date', 'Revenue'])` or `pd.read_csv(path, chunksize=10000)` |

### Step 3 — Output

If the user specifies an output file path, write results to it (highest priority). Format the report as:

```
## Analysis Report: {filename}
### File Overview     — format, sheets, row counts
### Data Quality      — nulls, duplicates, mixed types (or "no issues")
### Key Findings      — direct answer to the user's question
### Additional Notes  — formula NaN, encoding issues, caveats
```

**Numeric display**: monetary `1,234,567.89`, percentage `12.3%`, multiples `8.5x`, counts as integers.

---

## Common Pitfalls

| Pitfall | Cause | Fix |
|---------|-------|-----|
| Formula cells read as NaN | `<v>` cache empty in freshly generated files | Inform user; suggest opening in Excel and re-saving; or use `libreoffice_recalc.py` |
| CSV encoding errors | Chinese Windows exports use GBK | `xlsx_reader.py` auto-tries multiple encodings; manually specify if all fail |
| Mixed types in column | Column has both numbers and text (e.g., "N/A") | `pd.to_numeric(df['Col'], errors='coerce')` — report unconvertible rows |
| Year shows as 2,024 | Thousands separator format applied to year | `df['Year'].astype(int).astype(str)` |
| Multi-level headers | Two-row header merged | `pd.read_excel(path, header=[0, 1])`, then flatten with `' - '.join()` |
| Row number mismatch | pandas 0-indexed vs Excel 1-indexed | `excel_row = pandas_index + 2` (+1 for 1-index, +1 for header) |

**Critical**: Never open with `data_only=True` then `save()` — this permanently destroys all formulas.

---

## Prohibitions

- Never modify the source file (no `save()`, no XML edits)
- Never report formula NaN as "data is zero" — explain it's a formula cache issue
- Never report pandas indices as Excel row numbers
- Never make speculative conclusions unsupported by the data

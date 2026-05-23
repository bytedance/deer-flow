# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a **data-analysis skill** that analyzes Excel (.xlsx/.xls) and CSV files using DuckDB—an in-process analytical SQL engine. It supports schema inspection, SQL querying, statistical summaries, and result export.

## Architecture

```
scripts/analyze.py          # Main entry point - handles all actions
docs/2026-05-23-multi-level-header-design.md  # Design doc for Excel multi-level header flattening
```

**Key Components:**

- **DuckDB Integration**: Files are loaded into an in-process DuckDB database for SQL queries
- **Caching**: Two-tier caching - L1 is flattened CSV, L2 is DuckDB database (both in `~/.data-analysis-cache/`)
- **Multi-level Header Handling**: Excel files with merged/multi-row headers are flattened using `openpyxl` before DuckDB loading (see design doc for details)
- **Auto-install**: `duckdb` and `openpyxl` are installed automatically if missing

## Commands

```bash
# Inspect file structure (sheets, columns, types, row counts)
python scripts/analyze.py --files <path> --action inspect

# Execute SQL query
python scripts/analyze.py --files <path> --action query --sql "<SQL>"

# Statistical summary (count, mean, std, min, max, percentiles)
python scripts/analyze.py --files <path> --action summary --table <sheet_name>

# Export results
python scripts/analyze.py --files <path> --action query --sql "<SQL>" --output-file <output.csv|json|md>
```

**Table Naming:**
- Excel sheets → table named after the sheet
- CSV files → table named after file (without extension)
- Special characters/spaces → sanitized to underscores

## Cache

Cached data is stored in `~/.data-analysis-cache/` with hash-based keys. Cache includes a version number to auto-invalidate when processing logic changes.
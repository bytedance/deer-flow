#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
xlsx_reader.py — Structure discovery and data analysis tool for Excel/CSV files.

Usage:
    python3 xlsx_reader.py <file>                   # full structure report
    python3 xlsx_reader.py <file> --sheet Sales     # analyze one sheet
    python3 xlsx_reader.py <file> --json            # machine-readable output
    python3 xlsx_reader.py <file> --quality         # data quality audit only

Supports: .xlsx, .xlsm, .csv, .tsv
Does NOT modify the source file in any way.

Exit codes:
    0 — success
    1 — file not found / unsupported format / encoding failure
"""

import sys
import json
import argparse
from pathlib import Path


# ---------------------------------------------------------------------------
# Format detection and loading
# ---------------------------------------------------------------------------

def detect_and_load(file_path: str, sheet_name_filter: str | None = None) -> dict:
    """
    Load file into {sheet_name: DataFrame} dict.
    CSV/TSV files are mapped to a single-key dict using the file stem as key.

    Raises ValueError for unsupported formats or encoding failures.
    """
    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError(
            "pandas is not installed. Run: pip install pandas openpyxl"
        )

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()

    if suffix in (".xlsx", ".xlsm"):
        target = sheet_name_filter if sheet_name_filter else None
        result = pd.read_excel(file_path, sheet_name=target)
        # pd.read_excel with sheet_name=None returns dict; with a name, returns DataFrame
        if isinstance(result, dict):
            return result
        else:
            return {sheet_name_filter: result}

    elif suffix in (".csv", ".tsv"):
        sep = "\t" if suffix == ".tsv" else ","
        encodings = ["utf-8-sig", "gbk", "utf-8", "latin-1"]
        last_error = None
        for enc in encodings:
            try:
                import pandas as pd
                df = pd.read_csv(file_path, sep=sep, encoding=enc)
                df._reader_encoding = enc  # attach metadata (non-standard, for reporting)
                return {path.stem: df}
            except (UnicodeDecodeError, Exception) as e:
                last_error = e
                continue
        raise ValueError(
            f"Cannot decode {file_path}. Tried encodings: {encodings}. "
            f"Last error: {last_error}"
        )

    elif suffix == ".xls":
        raise ValueError(
            ".xls is a legacy binary format not supported by this tool. "
            "Please open the file in Excel and save as .xlsx, then retry."
        )

    else:
        raise ValueError(
            f"Unsupported file format: {suffix}. "
            "Supported formats: .xlsx, .xlsm, .csv, .tsv"
        )


# ---------------------------------------------------------------------------
# Structure discovery
# ---------------------------------------------------------------------------

def explore_structure(sheets: dict) -> dict:
    """
    Return a structured dict describing each sheet.
    Keys: sheet_name -> {shape, columns, dtypes, null_counts, preview}
    """
    result = {}
    for sheet_name, df in sheets.items():
        null_counts = df.isnull().sum()
        null_info = {
            col: {"count": int(cnt), "pct": round(cnt / max(len(df), 1) * 100, 1)}
            for col, cnt in null_counts.items()
            if cnt > 0
        }
        result[sheet_name] = {
            "shape": {"rows": df.shape[0], "cols": df.shape[1]},
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "null_columns": null_info,
            "preview": df.head(5).to_dict(orient="records"),
        }
    return result


# ---------------------------------------------------------------------------
# Data quality audit
# ---------------------------------------------------------------------------

def audit_quality(sheets: dict) -> dict:
    """
    Return data quality findings per sheet.
    Checks: nulls, duplicates, mixed-type columns, potential year formatting issues.
    """
    import pandas as pd

    findings = {}
    for sheet_name, df in sheets.items():
        sheet_findings = []

        # Null values
        null_counts = df.isnull().sum()
        for col, cnt in null_counts.items():
            if cnt > 0:
                pct = round(cnt / max(len(df), 1) * 100, 1)
                sheet_findings.append({
                    "type": "null_values",
                    "column": col,
                    "count": int(cnt),
                    "pct": pct,
                    "note": f"Column '{col}' has {cnt} null values ({pct}%). "
                            "If this column contains Excel formulas, null values may "
                            "indicate that the formula cache has not been populated "
                            "(file was never opened in Excel after the formulas were written)."
                })

        # Duplicate rows
        dup_count = int(df.duplicated().sum())
        if dup_count > 0:
            sheet_findings.append({
                "type": "duplicate_rows",
                "count": dup_count,
                "note": f"{dup_count} fully duplicate rows found."
            })

        # Mixed-type object columns (numeric data stored as text)
        for col in df.select_dtypes(include="object").columns:
            numeric_converted = pd.to_numeric(df[col], errors="coerce")
            convertible = int(numeric_converted.notna().sum())
            non_null_total = int(df[col].notna().sum())
            if 0 < convertible < non_null_total:
                sheet_findings.append({
                    "type": "mixed_type",
                    "column": col,
                    "convertible_to_numeric": convertible,
                    "non_convertible": non_null_total - convertible,
                    "note": f"Column '{col}' appears to contain mixed types: "
                            f"{convertible} values can be parsed as numbers, "
                            f"{non_null_total - convertible} cannot. "
                            "Use pd.to_numeric(df[col], errors='coerce') to unify."
                })

        # Year column formatting (e.g., 2024.0 stored as float)
        for col in df.select_dtypes(include="number").columns:
            col_lower = str(col).lower()
            # "年" is the Chinese character for "year" — detect year columns in CJK spreadsheets
            if "year" in col_lower or "yr" in col_lower or "年" in col_lower:
                if df[col].dropna().between(1900, 2200).all():
                    if df[col].dtype == float:
                        sheet_findings.append({
                            "type": "year_as_float",
                            "column": col,
                            "note": f"Column '{col}' appears to be a year column stored as float "
                                    "(e.g., 2024.0). Convert with df[col].astype(int).astype(str) "
                                    "to get clean year strings like '2024'."
                        })

        # Outliers via IQR on numeric columns
        for col in df.select_dtypes(include="number").columns:
            series = df[col].dropna()
            if len(series) < 4:
                continue
            Q1, Q3 = series.quantile(0.25), series.quantile(0.75)
            IQR = Q3 - Q1
            if IQR == 0:
                continue
            outlier_mask = (df[col] < Q1 - 1.5 * IQR) | (df[col] > Q3 + 1.5 * IQR)
            outlier_count = int(outlier_mask.sum())
            if outlier_count > 0:
                sheet_findings.append({
                    "type": "outliers_iqr",
                    "column": col,
                    "count": outlier_count,
                    "note": f"Column '{col}' has {outlier_count} potential outlier(s) "
                            f"(outside 1.5×IQR bounds: [{Q1 - 1.5*IQR:.2f}, {Q3 + 1.5*IQR:.2f}])."
                })

        findings[sheet_name] = sheet_findings

    return findings


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def compute_stats(sheets: dict) -> dict:
    """Compute descriptive statistics for numeric columns per sheet."""
    stats = {}
    for sheet_name, df in sheets.items():
        numeric_df = df.select_dtypes(include="number")
        if numeric_df.empty:
            stats[sheet_name] = {}
            continue
        desc = numeric_df.describe().round(4)
        stats[sheet_name] = desc.to_dict()
    return stats


# ---------------------------------------------------------------------------
# Human-readable report rendering
# ---------------------------------------------------------------------------

def render_report(
    file_path: str,
    structure: dict,
    quality: dict,
    stats: dict,
) -> str:
    lines = []
    p = lines.append

    p("=" * 60)
    p(f"ANALYSIS REPORT: {Path(file_path).name}")
    p("=" * 60)

    # File overview
    sheet_list = list(structure.keys())
    total_rows = sum(s["shape"]["rows"] for s in structure.values())
    p(f"\nSheets ({len(sheet_list)}): {', '.join(sheet_list)}")
    p(f"Total rows across all sheets: {total_rows:,}")

    for sheet_name, info in structure.items():
        p(f"\n{'─' * 50}")
        p(f"Sheet: {sheet_name}")
        p(f"{'─' * 50}")
        p(f"  Size: {info['shape']['rows']:,} rows × {info['shape']['cols']} cols")
        p(f"  Columns: {info['columns']}")

        # Data types
        p("\n  Column types:")
        for col, dtype in info["dtypes"].items():
            p(f"    {col}: {dtype}")

        # Nulls
        if info["null_columns"]:
            p("\n  Null values (columns with nulls only):")
            for col, null_info in info["null_columns"].items():
                p(f"    {col}: {null_info['count']} nulls ({null_info['pct']}%)")
        else:
            p("\n  Null values: none")

        # Stats
        sheet_stats = stats.get(sheet_name, {})
        if sheet_stats:
            p("\n  Numeric column statistics:")
            numeric_cols = list(sheet_stats.keys())
            # Show only first 6 to keep report readable
            for col in numeric_cols[:6]:
                col_stats = sheet_stats[col]
                p(f"    {col}:")
                p(f"      count={col_stats.get('count', 'N/A')}  "
                  f"mean={col_stats.get('mean', 'N/A')}  "
                  f"min={col_stats.get('min', 'N/A')}  "
                  f"max={col_stats.get('max', 'N/A')}")
            if len(numeric_cols) > 6:
                p(f"    ... and {len(numeric_cols) - 6} more numeric columns")

        # Quality findings for this sheet
        sheet_quality = quality.get(sheet_name, [])
        if sheet_quality:
            p(f"\n  Data quality issues ({len(sheet_quality)} found):")
            for finding in sheet_quality:
                p(f"    [{finding['type'].upper()}] {finding['note']}")
        else:
            p("\n  Data quality: no issues found")

        # Preview
        if info["preview"]:
            p("\n  Preview (first 3 rows):")
            import pandas as pd
            preview_df = pd.DataFrame(info["preview"][:3])
            for line in preview_df.to_string(index=False).splitlines():
                p(f"    {line}")

    p("\n" + "=" * 60)
    quality_issue_count = sum(len(v) for v in quality.values())
    if quality_issue_count == 0:
        p("RESULT: No data quality issues detected.")
    else:
        p(f"RESULT: {quality_issue_count} data quality issue(s) found. See details above.")
    p("=" * 60)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read and analyze Excel/CSV files without modifying them."
    )
    parser.add_argument("file", help="Path to .xlsx, .xlsm, .csv, or .tsv file")
    parser.add_argument("--sheet", help="Analyze a specific sheet only", default=None)
    parser.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )
    parser.add_argument(
        "--quality", action="store_true",
        help="Run data quality audit only (skip stats)"
    )
    args = parser.parse_args()

    try:
        sheets = detect_and_load(args.file, sheet_name_filter=args.sheet)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    structure = explore_structure(sheets)
    quality = audit_quality(sheets)
    stats = {} if args.quality else compute_stats(sheets)

    if args.json:
        output = {
            "file": args.file,
            "structure": structure,
            "quality": quality,
            "stats": stats,
        }
        # Convert preview records to serializable form (handle non-JSON types)
        print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    else:
        report = render_report(args.file, structure, quality, stats)
        print(report)


if __name__ == "__main__":
    main()

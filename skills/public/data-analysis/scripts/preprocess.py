"""Data preprocessing pipeline for research datasets.

Usage:
    python preprocess.py --input <path> --output <path> [--actions <actions>]

Actions (comma-separated):
    detect_types       Auto-detect and convert column types
    handle_missing     Handle missing values (report + impute)
    remove_duplicates  Remove duplicate rows
    detect_outliers    Flag statistical outliers (IQR + Z-score)
    normalize          Normalize numeric columns (z-score or min-max)
    encode_categorical Label encode or one-hot encode categorical columns
    create_report      Generate data quality report
    all                Run all actions in sequence
"""

import argparse
import json
import sys

import numpy as np
import pandas as pd


def detect_types(df):
    """Auto-detect and optimize column types."""
    report = {}
    for col in df.columns:
        original_dtype = str(df[col].dtype)
        if df[col].dtype == "object":
            nunique = df[col].nunique()
            ratio = nunique / len(df) if len(df) > 0 else 1
            if ratio < 0.05:
                df[col] = df[col].astype("category")
                report[col] = f"{original_dtype} -> category ({nunique} unique)"
            else:
                try:
                    df[col] = pd.to_datetime(df[col])
                    report[col] = f"{original_dtype} -> datetime"
                except (ValueError, TypeError):
                    report[col] = f"{original_dtype} (kept as string)"
    return df, report


def handle_missing(df, strategy="report"):
    """Analyze and handle missing values."""
    report = {}
    n_total = len(df)
    for col in df.columns:
        n_missing = int(df[col].isnull().sum())
        pct = n_missing / n_total * 100 if n_total > 0 else 0
        if n_missing > 0:
            if df[col].dtype in ["float64", "int64"]:
                recommendation = "drop_column" if pct > 50 else "impute_median"
            else:
                recommendation = "drop_column" if pct > 50 else "impute_mode"
            report[col] = {
                "n_missing": n_missing,
                "pct_missing": round(pct, 2),
                "recommendation": recommendation,
            }
    return df, report


def remove_duplicates(df):
    """Remove duplicate rows."""
    n_before = len(df)
    df = df.drop_duplicates()
    n_after = len(df)
    report = {
        "rows_before": n_before,
        "rows_after": n_after,
        "duplicates_removed": n_before - n_after,
    }
    return df, report


def detect_outliers(df):
    """Detect outliers using IQR and Z-score methods."""
    report = {}
    for col in df.select_dtypes(include=[np.number]).columns:
        data = df[col].dropna()
        if len(data) < 4:
            continue
        q1 = float(data.quantile(0.25))
        q3 = float(data.quantile(0.75))
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        n_outliers_iqr = int(((data < lower) | (data > upper)).sum())

        if data.std() > 0:
            z_scores = np.abs((data - data.mean()) / data.std())
            n_outliers_z = int((z_scores > 3).sum())
        else:
            n_outliers_z = 0

        if n_outliers_iqr > 0 or n_outliers_z > 0:
            report[col] = {
                "iqr_outliers": n_outliers_iqr,
                "zscore_outliers": n_outliers_z,
                "range": [round(lower, 2), round(upper, 2)],
            }
    return df, report


def normalize(df):
    """Normalize numeric columns using z-score."""
    report = {}
    for col in df.select_dtypes(include=[np.number]).columns:
        mean = float(df[col].mean())
        std = float(df[col].std())
        if std > 0:
            df[col] = (df[col] - mean) / std
            report[col] = {"method": "z-score", "original_mean": round(mean, 4), "original_std": round(std, 4)}
    return df, report


def encode_categorical(df):
    """Label encode categorical columns."""
    report = {}
    for col in df.select_dtypes(include=["object", "category"]).columns:
        n_unique = df[col].nunique()
        if n_unique <= 10:
            mapping = {val: idx for idx, val in enumerate(df[col].dropna().unique())}
            df[col] = df[col].map(mapping)
            report[col] = {"method": "label_encoding", "mapping": {str(k): v for k, v in mapping.items()}}
        else:
            report[col] = {"method": "skipped", "reason": f"too many unique values ({n_unique})"}
    return df, report


def create_report(df):
    """Generate comprehensive data quality report."""
    n_total = len(df)
    report = {
        "shape": {"rows": n_total, "columns": len(df.columns)},
        "dtypes": df.dtypes.astype(str).to_dict(),
        "missing": {col: int(v) for col, v in df.isnull().sum().items() if v > 0},
        "numeric_summary": {},
        "categorical_summary": {},
    }

    for col in df.select_dtypes(include=[np.number]).columns:
        data = df[col].dropna()
        if len(data) == 0:
            continue
        report["numeric_summary"][col] = {
            "mean": round(float(data.mean()), 4),
            "std": round(float(data.std()), 4),
            "min": round(float(data.min()), 4),
            "max": round(float(data.max()), 4),
            "skewness": round(float(data.skew()), 4),
            "kurtosis": round(float(data.kurtosis()), 4),
        }

    for col in df.select_dtypes(include=["object", "category"]).columns:
        report["categorical_summary"][col] = {
            "n_unique": int(df[col].nunique()),
            "top_3": df[col].value_counts().head(3).to_dict(),
        }

    return report


ALL_ACTIONS = {
    "detect_types": detect_types,
    "handle_missing": handle_missing,
    "remove_duplicates": remove_duplicates,
    "detect_outliers": detect_outliers,
    "normalize": normalize,
    "encode_categorical": encode_categorical,
}


def main():
    parser = argparse.ArgumentParser(description="Data preprocessing pipeline")
    parser.add_argument("--input", required=True, help="Path to input data file")
    parser.add_argument("--output", default=None, help="Path to output file (JSON report)")
    parser.add_argument("--actions", default="create_report", help="Comma-separated actions to run")
    args = parser.parse_args()

    if args.input.endswith(".csv"):
        df = pd.read_csv(args.input)
    elif args.input.endswith((".xlsx", ".xls")):
        df = pd.read_excel(args.input)
    else:
        print(f"Unsupported format: {args.input}", file=sys.stderr)
        sys.exit(1)

    actions = args.actions.split(",")
    if "all" in actions:
        actions = list(ALL_ACTIONS.keys()) + ["create_report"]

    full_report = {}
    for action in actions:
        action = action.strip()
        if action == "create_report":
            full_report["create_report"] = create_report(df)
        elif action in ALL_ACTIONS:
            df, report = ALL_ACTIONS[action](df)
            full_report[action] = report
        else:
            print(f"Unknown action: {action}", file=sys.stderr)

    output = json.dumps(full_report, indent=2, ensure_ascii=False, default=str)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Results written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()

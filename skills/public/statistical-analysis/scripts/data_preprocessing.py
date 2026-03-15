#!/usr/bin/env python3
"""Data preprocessing script for DeerFlow scientific research.

Provides missing data diagnosis, imputation, outlier detection, data transformation,
and feature engineering for academic data analysis workflows.
"""

import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

import numpy as np
import pandas as pd


def load_data(file_paths: list[str]) -> pd.DataFrame:
    """Load CSV or Excel files into a single DataFrame."""
    frames = []
    for fp in file_paths:
        ext = os.path.splitext(fp)[1].lower()
        if ext in (".xlsx", ".xls"):
            xls = pd.ExcelFile(fp)
            for sheet in xls.sheet_names:
                frames.append(pd.read_excel(fp, sheet_name=sheet))
        elif ext == ".csv":
            frames.append(pd.read_csv(fp))
        elif ext == ".tsv":
            frames.append(pd.read_csv(fp, sep="\t"))
        else:
            frames.append(pd.read_csv(fp))
    if not frames:
        raise ValueError("No data loaded from provided files.")
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def setup_plotting():
    """Configure matplotlib for publication-quality figures."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.dpi": 300, "savefig.dpi": 300, "font.size": 11,
        "axes.spines.top": False, "axes.spines.right": False,
    })
    return plt


def action_missing_report(df, params, output_dir):
    """Generate comprehensive missing data report with pattern visualization."""
    plt = setup_plotting()
    import seaborn as sns

    columns = params.get("columns", list(df.columns))
    sub = df[columns]
    results = ["# Missing Data Report\n"]

    missing = sub.isnull().sum()
    pct = (missing / len(sub) * 100).round(2)
    miss_df = pd.DataFrame({"Column": columns, "Missing": missing.values, "Percent": pct.values}).sort_values("Percent", ascending=False)

    results.append("## Summary\n| Column | Missing | Percent | Status |\n|--------|--------:|--------:|--------|\n")
    for _, row in miss_df.iterrows():
        status = "🔴 HIGH" if row["Percent"] > 20 else ("🟡 MODERATE" if row["Percent"] > 5 else ("🟢 LOW" if row["Percent"] > 0 else "✓ NONE"))
        results.append(f"| {row['Column']} | {int(row['Missing'])} | {row['Percent']:.1f}% | {status} |")

    total = len(sub)
    complete = sub.dropna().shape[0]
    results.append(f"\n**Total**: {total} rows | **Complete cases**: {complete} ({complete/total*100:.1f}%)\n")

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    fig, ax = plt.subplots(figsize=(max(8, len(columns) * 0.4), 6))
    sns.heatmap(sub.isnull().T, cbar=False, yticklabels=True, cmap="YlOrRd", ax=ax)
    ax.set_title("Missing Data Pattern")
    fig_path = os.path.join(fig_dir, "missing_pattern.png")
    fig.savefig(fig_path, bbox_inches="tight")
    plt.close(fig)
    results.append(f"![Missing Pattern]({fig_path})\n")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "missing_report.md"), "w") as f:
        f.write(report)
    return report


def action_impute(df, params, output_dir):
    """Impute missing values using specified strategy."""
    strategy = params.get("strategy", "median")
    columns = params.get("columns", [c for c in df.columns if df[c].isnull().any()])

    results = [f"# Missing Data Imputation (strategy: {strategy})\n"]

    for col in columns:
        n_missing = df[col].isnull().sum()
        if n_missing == 0:
            continue
        if strategy == "mean" and pd.api.types.is_numeric_dtype(df[col]):
            fill_val = df[col].mean()
            df[col].fillna(fill_val, inplace=True)
            results.append(f"- **{col}**: {n_missing} values imputed with mean ({fill_val:.4f})")
        elif strategy == "median" and pd.api.types.is_numeric_dtype(df[col]):
            fill_val = df[col].median()
            df[col].fillna(fill_val, inplace=True)
            results.append(f"- **{col}**: {n_missing} values imputed with median ({fill_val:.4f})")
        elif strategy == "mode":
            fill_val = df[col].mode().iloc[0] if not df[col].mode().empty else "N/A"
            df[col].fillna(fill_val, inplace=True)
            results.append(f"- **{col}**: {n_missing} values imputed with mode ({fill_val})")
        elif strategy == "drop":
            df.dropna(subset=[col], inplace=True)
            results.append(f"- **{col}**: {n_missing} rows dropped")

    output_path = os.path.join(output_dir, "imputed_data.csv")
    df.to_csv(output_path, index=False)
    results.append(f"\n**Output**: {output_path} ({len(df)} rows remaining)")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "imputation_report.md"), "w") as f:
        f.write(report)
    return report


def action_outlier_detect(df, params, output_dir):
    """Detect outliers using IQR and Z-score methods."""
    plt = setup_plotting()
    columns = params.get("columns", [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])])
    method = params.get("method", "iqr")

    results = ["# Outlier Detection Report\n"]
    results.append(f"**Method**: {method.upper()}\n")
    results.append("| Column | Outliers | Percent | Min Outlier | Max Outlier |\n|--------|--------:|--------:|------------:|------------:|\n")

    all_outlier_mask = pd.Series(False, index=df.index)

    for col in columns:
        vals = df[col].dropna()
        if method == "iqr":
            q1, q3 = vals.quantile(0.25), vals.quantile(0.75)
            iqr = q3 - q1
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outliers = vals[(vals < lower) | (vals > upper)]
        elif method == "zscore":
            z = np.abs((vals - vals.mean()) / vals.std())
            outliers = vals[z > 3]
        else:
            outliers = pd.Series(dtype=float)

        n_out = len(outliers)
        pct = n_out / len(vals) * 100 if len(vals) > 0 else 0
        min_o = outliers.min() if n_out > 0 else "—"
        max_o = outliers.max() if n_out > 0 else "—"
        results.append(f"| {col} | {n_out} | {pct:.1f}% | {min_o} | {max_o} |")
        all_outlier_mask |= df[col].isin(outliers)

    results.append(f"\n**Total rows with at least one outlier**: {all_outlier_mask.sum()} ({all_outlier_mask.sum()/len(df)*100:.1f}%)\n")

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    if len(columns) > 0:
        n_cols = min(len(columns), 4)
        n_rows = (len(columns) + n_cols - 1) // n_cols
        fig, axes = plt.subplots(n_rows, n_cols, figsize=(4 * n_cols, 3 * n_rows))
        if n_rows * n_cols == 1:
            axes = np.array([axes])
        axes = axes.flatten()
        for i, col in enumerate(columns[:len(axes)]):
            axes[i].boxplot(df[col].dropna(), vert=True)
            axes[i].set_title(col, fontsize=10)
        for j in range(len(columns), len(axes)):
            axes[j].set_visible(False)
        fig.suptitle("Outlier Detection (Box Plots)", fontsize=13)
        fig.tight_layout()
        fig_path = os.path.join(fig_dir, "outlier_boxplots.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"![Outliers]({fig_path})\n")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "outlier_report.md"), "w") as f:
        f.write(report)
    return report


def action_transform(df, params, output_dir):
    """Apply data transformations: log, sqrt, Box-Cox, standardize, normalize."""
    columns = params.get("columns", [])
    method = params.get("method", "standardize")

    if not columns:
        return "Error: 'columns' parameter is required."

    results = [f"# Data Transformation (method: {method})\n"]

    for col in columns:
        if col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]):
            results.append(f"- **{col}**: Skipped (not numeric or not found)")
            continue

        original_stats = f"mean={df[col].mean():.4f}, std={df[col].std():.4f}"
        new_col = f"{col}_{method}"

        if method == "log":
            min_val = df[col].min()
            offset = abs(min_val) + 1 if min_val <= 0 else 0
            df[new_col] = np.log(df[col] + offset)
        elif method == "sqrt":
            min_val = df[col].min()
            offset = abs(min_val) if min_val < 0 else 0
            df[new_col] = np.sqrt(df[col] + offset)
        elif method == "standardize":
            df[new_col] = (df[col] - df[col].mean()) / df[col].std()
        elif method == "normalize":
            min_v, max_v = df[col].min(), df[col].max()
            df[new_col] = (df[col] - min_v) / (max_v - min_v) if max_v != min_v else 0
        elif method == "boxcox":
            from scipy.stats import boxcox
            vals = df[col].dropna()
            if (vals > 0).all():
                transformed, lmbda = boxcox(vals)
                df.loc[vals.index, new_col] = transformed
                results.append(f"- **{col}** → **{new_col}**: Box-Cox (λ={lmbda:.4f})")
                continue
            else:
                results.append(f"- **{col}**: Box-Cox requires positive values, skipped")
                continue

        new_stats = f"mean={df[new_col].mean():.4f}, std={df[new_col].std():.4f}"
        results.append(f"- **{col}** → **{new_col}**: {original_stats} → {new_stats}")

    output_path = os.path.join(output_dir, "transformed_data.csv")
    df.to_csv(output_path, index=False)
    results.append(f"\n**Output**: {output_path}")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "transform_report.md"), "w") as f:
        f.write(report)
    return report


def action_feature_engineer(df, params, output_dir):
    """Create derived features: binning, interaction, polynomial, lag."""
    operations = params.get("operations", [])
    results = ["# Feature Engineering Report\n"]

    for op in operations:
        op_type = op.get("type")
        if op_type == "bin":
            col, bins, labels = op["column"], op.get("bins", 4), op.get("labels")
            new_col = op.get("new_name", f"{col}_binned")
            df[new_col] = pd.cut(df[col], bins=bins, labels=labels)
            results.append(f"- **Binning**: {col} → {new_col} ({bins} bins)")
        elif op_type == "interaction":
            col1, col2 = op["col1"], op["col2"]
            new_col = op.get("new_name", f"{col1}_x_{col2}")
            df[new_col] = df[col1] * df[col2]
            results.append(f"- **Interaction**: {col1} × {col2} → {new_col}")
        elif op_type == "polynomial":
            col, degree = op["column"], op.get("degree", 2)
            new_col = op.get("new_name", f"{col}_pow{degree}")
            df[new_col] = df[col] ** degree
            results.append(f"- **Polynomial**: {col}^{degree} → {new_col}")
        elif op_type == "lag":
            col, periods = op["column"], op.get("periods", 1)
            new_col = op.get("new_name", f"{col}_lag{periods}")
            df[new_col] = df[col].shift(periods)
            results.append(f"- **Lag**: {col} shifted by {periods} → {new_col}")
        elif op_type == "rolling":
            col, window = op["column"], op.get("window", 7)
            new_col = op.get("new_name", f"{col}_roll{window}")
            df[new_col] = df[col].rolling(window=window).mean()
            results.append(f"- **Rolling mean**: {col} (window={window}) → {new_col}")
        elif op_type == "ratio":
            num, den = op["numerator"], op["denominator"]
            new_col = op.get("new_name", f"{num}_per_{den}")
            df[new_col] = df[num] / df[den].replace(0, np.nan)
            results.append(f"- **Ratio**: {num}/{den} → {new_col}")

    output_path = os.path.join(output_dir, "engineered_data.csv")
    df.to_csv(output_path, index=False)
    results.append(f"\n**Output**: {output_path} ({len(df)} rows, {len(df.columns)} columns)")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "feature_engineering_report.md"), "w") as f:
        f.write(report)
    return report


ACTION_MAP = {
    "missing_report": action_missing_report,
    "impute": action_impute,
    "outlier_detect": action_outlier_detect,
    "transform": action_transform,
    "feature_engineer": action_feature_engineer,
}


def main():
    parser = argparse.ArgumentParser(description="Data Preprocessing for Academic Research")
    parser.add_argument("--files", nargs="+", required=True, help="Data file paths")
    parser.add_argument("--action", required=True, choices=list(ACTION_MAP.keys()), help="Preprocessing action")
    parser.add_argument("--params", default="{}", help="JSON parameters")
    parser.add_argument("--output-dir", default="/mnt/user-data/outputs", help="Output directory")
    args = parser.parse_args()

    params = json.loads(args.params)
    os.makedirs(args.output_dir, exist_ok=True)

    df = load_data(args.files)
    print(f"Loaded {len(df)} rows × {len(df.columns)} columns\n")

    action_fn = ACTION_MAP[args.action]
    result = action_fn(df, params, args.output_dir)
    print(result)


if __name__ == "__main__":
    main()

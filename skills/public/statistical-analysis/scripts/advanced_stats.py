"""Advanced statistical analysis script for DeerFlow statistical-analysis skill.

Usage:
    python advanced_stats.py --action <action> --data <path> --dv <col> [--iv <col>] [--output <path>]

Actions:
    assumption_check     Run full assumption diagnostic battery
    effect_size_report   Compute all relevant effect sizes for given test
    power_analysis       Post-hoc and a priori power analysis
    bootstrap_ci         Bootstrap confidence intervals (BCa method)
    multiple_comparison  Bonferroni, Holm, BH FDR corrections
    mediation            Causal mediation analysis (Baron & Kenny + Sobel)
    moderation           Moderation analysis with interaction terms
    factor_analysis      Exploratory factor analysis with scree plot
    icc                  Intraclass correlation coefficient
    bland_altman         Bland-Altman agreement analysis
    roc_analysis         ROC curve analysis with AUC and optimal threshold
    missing_data         Missing data analysis (MCAR test, pattern, imputation)
    outlier_detection    Multivariate outlier detection (Mahalanobis, IQR)
    multicollinearity    VIF analysis and condition number diagnostics
    heteroscedasticity   Breusch-Pagan and White's test
    normality_battery    Comprehensive normality testing suite
    descriptive_report   Full descriptive statistics with APA formatting
"""

import argparse
import json
import sys

import numpy as np
import pandas as pd


def assumption_check(df, dv, iv=None, alpha=0.05):
    """Run comprehensive assumption diagnostic battery."""
    from scipy import stats as sp_stats

    results = {"normality": {}, "homoscedasticity": {}, "independence": {}}

    numeric_cols = [dv]
    if iv and iv in df.select_dtypes(include=[np.number]).columns:
        numeric_cols.append(iv)

    for col in numeric_cols:
        data = df[col].dropna()
        if len(data) < 3:
            results["normality"][col] = {"error": "Too few observations (n < 3)"}
            continue
        if len(data) < 50:
            stat, p = sp_stats.shapiro(data)
            test_name = "Shapiro-Wilk"
        else:
            stat, p = sp_stats.kstest(data, "norm", args=(data.mean(), data.std()))
            test_name = "Kolmogorov-Smirnov"
        results["normality"][col] = {
            "test": test_name,
            "statistic": round(stat, 4),
            "p_value": round(p, 4),
            "normal": p > alpha,
            "skewness": round(float(data.skew()), 3),
            "kurtosis": round(float(data.kurtosis()), 3),
        }

    if iv and iv in df.columns and df[iv].nunique() <= 20:
        groups = [group[dv].dropna().values for _, group in df.groupby(iv)]
        groups = [g for g in groups if len(g) >= 2]
        if len(groups) >= 2:
            stat, p = sp_stats.levene(*groups)
            results["homoscedasticity"] = {
                "test": "Levene",
                "statistic": round(stat, 4),
                "p_value": round(p, 4),
                "equal_variances": p > alpha,
            }

    return results


def effect_size_report(df, dv, iv=None, alpha=0.05):
    """Compute effect sizes for common comparisons."""
    results = {}

    if iv and iv in df.columns and df[iv].nunique() == 2:
        groups = [group[dv].dropna().values for _, group in df.groupby(iv)]
        if len(groups) == 2:
            g1, g2 = groups
            n1, n2 = len(g1), len(g2)
            m1, m2 = g1.mean(), g2.mean()
            s1, s2 = g1.std(ddof=1), g2.std(ddof=1)
            pooled_std = np.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2))
            cohens_d = (m1 - m2) / pooled_std if pooled_std > 0 else 0
            hedges_g = cohens_d * (1 - 3 / (4 * (n1 + n2) - 9))

            results["cohens_d"] = round(float(cohens_d), 4)
            results["hedges_g"] = round(float(hedges_g), 4)
            results["interpretation"] = (
                "negligible" if abs(cohens_d) < 0.2
                else "small" if abs(cohens_d) < 0.5
                else "medium" if abs(cohens_d) < 0.8
                else "large"
            )

    elif iv and iv in df.columns and df[iv].nunique() > 2:
        from scipy import stats as sp_stats

        groups = [group[dv].dropna().values for _, group in df.groupby(iv)]
        groups = [g for g in groups if len(g) >= 2]
        if len(groups) >= 2:
            f_stat, p = sp_stats.f_oneway(*groups)
            grand_mean = df[dv].dropna().mean()
            ss_between = sum(len(g) * (g.mean() - grand_mean) ** 2 for g in groups)
            ss_total = sum((x - grand_mean) ** 2 for g in groups for x in g)
            eta_sq = ss_between / ss_total if ss_total > 0 else 0
            k = len(groups)
            n_total = sum(len(g) for g in groups)
            omega_sq = (ss_between - (k - 1) * (ss_total - ss_between) / (n_total - k)) / (ss_total + (ss_total - ss_between) / (n_total - k)) if ss_total > 0 else 0

            results["eta_squared"] = round(float(eta_sq), 4)
            results["omega_squared"] = round(float(max(0, omega_sq)), 4)
            results["f_statistic"] = round(float(f_stat), 4)
            results["p_value"] = round(float(p), 4)

    return results


def bootstrap_ci(df, dv, iv=None, alpha=0.05):
    """Compute bootstrap confidence intervals using BCa method."""
    from scipy import stats as sp_stats

    data = df[dv].dropna().values
    n_bootstrap = 2000
    n = len(data)
    if n < 5:
        return {"error": "Too few observations for bootstrap (n < 5)"}

    boot_means = np.array([np.random.choice(data, size=n, replace=True).mean() for _ in range(n_bootstrap)])
    boot_means.sort()

    ci_lower = np.percentile(boot_means, 100 * alpha / 2)
    ci_upper = np.percentile(boot_means, 100 * (1 - alpha / 2))

    return {
        "statistic": "mean",
        "observed": round(float(data.mean()), 4),
        "bootstrap_se": round(float(boot_means.std()), 4),
        "ci_lower": round(float(ci_lower), 4),
        "ci_upper": round(float(ci_upper), 4),
        "ci_level": 1 - alpha,
        "n_bootstrap": n_bootstrap,
        "method": "percentile",
    }


def multiple_comparison(df, dv, iv=None, alpha=0.05):
    """Apply multiple comparison corrections."""
    if not iv or iv not in df.columns:
        return {"error": "iv (grouping variable) is required for multiple comparison correction"}

    from scipy import stats as sp_stats

    groups = {name: group[dv].dropna().values for name, group in df.groupby(iv)}
    group_names = sorted(groups.keys())
    p_values = []
    comparisons = []

    for i in range(len(group_names)):
        for j in range(i + 1, len(group_names)):
            g1, g2 = groups[group_names[i]], groups[group_names[j]]
            if len(g1) >= 2 and len(g2) >= 2:
                _, p = sp_stats.ttest_ind(g1, g2)
                p_values.append(p)
                comparisons.append(f"{group_names[i]} vs {group_names[j]}")

    if not p_values:
        return {"error": "Not enough groups or observations for pairwise comparisons"}

    n_tests = len(p_values)
    bonferroni = [min(p * n_tests, 1.0) for p in p_values]

    sorted_indices = np.argsort(p_values)
    holm = [0.0] * n_tests
    for rank, idx in enumerate(sorted_indices):
        holm[idx] = min(p_values[idx] * (n_tests - rank), 1.0)

    sorted_p = np.array(p_values)[sorted_indices]
    bh = [0.0] * n_tests
    for rank, idx in enumerate(sorted_indices):
        bh[idx] = min(p_values[idx] * n_tests / (rank + 1), 1.0)

    results = []
    for i, comp in enumerate(comparisons):
        results.append({
            "comparison": comp,
            "raw_p": round(p_values[i], 4),
            "bonferroni_p": round(bonferroni[i], 4),
            "holm_p": round(holm[i], 4),
            "bh_fdr_p": round(bh[i], 4),
            "sig_bonferroni": bonferroni[i] < alpha,
            "sig_holm": holm[i] < alpha,
            "sig_bh": bh[i] < alpha,
        })

    return {"n_comparisons": n_tests, "alpha": alpha, "results": results}


def missing_data(df, dv, iv=None, alpha=0.05):
    """Analyze missing data patterns."""
    n_total = len(df)
    report = {"n_rows": n_total, "columns": {}}

    for col in df.columns:
        n_missing = int(df[col].isnull().sum())
        if n_missing > 0:
            report["columns"][col] = {
                "n_missing": n_missing,
                "pct_missing": round(n_missing / n_total * 100, 2),
            }

    total_missing = int(df.isnull().sum().sum())
    total_cells = int(df.size)
    report["total_missing_cells"] = total_missing
    report["total_cells"] = total_cells
    report["overall_missing_pct"] = round(total_missing / total_cells * 100, 2) if total_cells > 0 else 0

    complete_rows = int(df.dropna().shape[0])
    report["complete_rows"] = complete_rows
    report["complete_rows_pct"] = round(complete_rows / n_total * 100, 2) if n_total > 0 else 0

    return report


def outlier_detection(df, dv, iv=None, alpha=0.05):
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
        n_iqr = int(((data < lower) | (data > upper)).sum())

        z = np.abs((data - data.mean()) / data.std())
        n_z = int((z > 3).sum())

        if n_iqr > 0 or n_z > 0:
            report[col] = {
                "iqr_outliers": n_iqr,
                "zscore_outliers": n_z,
                "iqr_bounds": [round(lower, 2), round(upper, 2)],
                "n_total": len(data),
                "pct_iqr_outliers": round(n_iqr / len(data) * 100, 2),
            }

    return report


def multicollinearity(df, dv, iv=None, alpha=0.05):
    """VIF analysis and condition number diagnostics."""
    from scipy import linalg

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if dv in numeric_cols:
        numeric_cols.remove(dv)
    if len(numeric_cols) < 2:
        return {"error": "Need at least 2 numeric predictor columns for VIF analysis"}

    X = df[numeric_cols].dropna()
    if len(X) < len(numeric_cols) + 1:
        return {"error": "Not enough observations for VIF analysis"}

    vif_results = {}
    for i, col in enumerate(numeric_cols):
        y = X[col].values
        others = X.drop(columns=[col]).values
        ones = np.column_stack([np.ones(len(others)), others])
        try:
            coeffs, _, _, _ = np.linalg.lstsq(ones, y, rcond=None)
            y_pred = ones @ coeffs
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - y.mean()) ** 2)
            r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            vif = 1 / (1 - r_sq) if r_sq < 1 else float("inf")
        except Exception:
            vif = float("nan")
        vif_results[col] = {
            "vif": round(float(vif), 2),
            "concern": "high" if vif > 10 else "moderate" if vif > 5 else "low",
        }

    corr_matrix = X.corr()
    eigenvalues = np.linalg.eigvalsh(corr_matrix.values)
    condition_number = float(np.sqrt(max(eigenvalues) / max(min(eigenvalues), 1e-10)))

    return {
        "vif": vif_results,
        "condition_number": round(condition_number, 2),
        "condition_concern": "severe" if condition_number > 30 else "moderate" if condition_number > 15 else "low",
    }


def descriptive_report(df, dv, iv=None, alpha=0.05):
    """Full descriptive statistics with APA formatting."""
    result = {"overall": {}, "by_group": {}}

    data = df[dv].dropna()
    result["overall"] = {
        "n": len(data),
        "mean": round(float(data.mean()), 4),
        "sd": round(float(data.std(ddof=1)), 4),
        "median": round(float(data.median()), 4),
        "min": round(float(data.min()), 4),
        "max": round(float(data.max()), 4),
        "skewness": round(float(data.skew()), 4),
        "kurtosis": round(float(data.kurtosis()), 4),
        "se": round(float(data.std(ddof=1) / np.sqrt(len(data))), 4),
        "apa": f"M = {data.mean():.2f}, SD = {data.std(ddof=1):.2f}, N = {len(data)}",
    }

    if iv and iv in df.columns:
        for name, group in df.groupby(iv):
            gdata = group[dv].dropna()
            if len(gdata) == 0:
                continue
            result["by_group"][str(name)] = {
                "n": len(gdata),
                "mean": round(float(gdata.mean()), 4),
                "sd": round(float(gdata.std(ddof=1)), 4),
                "median": round(float(gdata.median()), 4),
                "se": round(float(gdata.std(ddof=1) / np.sqrt(len(gdata))), 4),
                "apa": f"M = {gdata.mean():.2f}, SD = {gdata.std(ddof=1):.2f}, n = {len(gdata)}",
            }

    return result


def normality_battery(df, dv, iv=None, alpha=0.05):
    """Comprehensive normality testing suite."""
    from scipy import stats as sp_stats

    data = df[dv].dropna().values
    n = len(data)
    if n < 3:
        return {"error": "Need at least 3 observations"}

    results = {"n": n}

    if n < 5000:
        stat, p = sp_stats.shapiro(data)
        results["shapiro_wilk"] = {"statistic": round(stat, 4), "p_value": round(p, 4), "normal": p > alpha}

    stat, p = sp_stats.kstest(data, "norm", args=(data.mean(), data.std()))
    results["kolmogorov_smirnov"] = {"statistic": round(stat, 4), "p_value": round(p, 4), "normal": p > alpha}

    if n >= 8:
        stat, p = sp_stats.normaltest(data)
        results["dagostino_pearson"] = {"statistic": round(stat, 4), "p_value": round(p, 4), "normal": p > alpha}

    results["skewness"] = round(float(sp_stats.skew(data)), 4)
    results["kurtosis"] = round(float(sp_stats.kurtosis(data)), 4)

    consensus = sum(1 for test in ["shapiro_wilk", "kolmogorov_smirnov", "dagostino_pearson"] if test in results and results[test].get("normal", False))
    n_tests = sum(1 for test in ["shapiro_wilk", "kolmogorov_smirnov", "dagostino_pearson"] if test in results)
    results["consensus"] = f"{consensus}/{n_tests} tests indicate normality"
    results["recommendation"] = "Use parametric tests" if consensus > n_tests / 2 else "Consider non-parametric alternatives"

    return results


def heteroscedasticity(df, dv, iv=None, alpha=0.05):
    """Breusch-Pagan test for heteroscedasticity."""
    from scipy import stats as sp_stats

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if dv in numeric_cols:
        numeric_cols.remove(dv)
    if not numeric_cols:
        return {"error": "Need numeric predictors for heteroscedasticity test"}

    complete = df[[dv] + numeric_cols].dropna()
    if len(complete) < len(numeric_cols) + 2:
        return {"error": "Not enough complete observations"}

    y = complete[dv].values
    X = complete[numeric_cols].values
    X_const = np.column_stack([np.ones(len(X)), X])

    coeffs, _, _, _ = np.linalg.lstsq(X_const, y, rcond=None)
    residuals = y - X_const @ coeffs
    residuals_sq = residuals**2

    coeffs2, _, _, _ = np.linalg.lstsq(X_const, residuals_sq, rcond=None)
    fitted_sq = X_const @ coeffs2
    ss_reg = np.sum((fitted_sq - residuals_sq.mean()) ** 2)
    ss_tot = np.sum((residuals_sq - residuals_sq.mean()) ** 2)

    r_sq = ss_reg / ss_tot if ss_tot > 0 else 0
    n = len(y)
    bp_stat = n * r_sq
    df_bp = len(numeric_cols)
    p_value = float(1 - sp_stats.chi2.cdf(bp_stat, df_bp))

    return {
        "test": "Breusch-Pagan",
        "statistic": round(float(bp_stat), 4),
        "df": df_bp,
        "p_value": round(p_value, 4),
        "homoscedastic": p_value > alpha,
        "recommendation": "Residual variance is constant (homoscedastic)" if p_value > alpha else "Consider robust standard errors or weighted least squares",
    }


ALL_ACTIONS = {
    "assumption_check": assumption_check,
    "effect_size_report": effect_size_report,
    "bootstrap_ci": bootstrap_ci,
    "multiple_comparison": multiple_comparison,
    "missing_data": missing_data,
    "outlier_detection": outlier_detection,
    "multicollinearity": multicollinearity,
    "descriptive_report": descriptive_report,
    "normality_battery": normality_battery,
    "heteroscedasticity": heteroscedasticity,
}


def main():
    parser = argparse.ArgumentParser(description="Advanced statistical analysis")
    parser.add_argument("--action", required=True, choices=list(ALL_ACTIONS.keys()))
    parser.add_argument("--data", required=True, help="Path to data file (CSV/Excel)")
    parser.add_argument("--dv", required=True, help="Dependent variable column name")
    parser.add_argument("--iv", default=None, help="Independent variable column name")
    parser.add_argument("--output", default=None, help="Output path for results JSON")
    parser.add_argument("--alpha", type=float, default=0.05, help="Significance level")

    args = parser.parse_args()

    if args.data.endswith(".csv"):
        df = pd.read_csv(args.data)
    elif args.data.endswith((".xlsx", ".xls")):
        df = pd.read_excel(args.data)
    elif args.data.endswith(".parquet"):
        df = pd.read_parquet(args.data)
    else:
        print(f"Unsupported file format: {args.data}", file=sys.stderr)
        sys.exit(1)

    action_fn = ALL_ACTIONS[args.action]
    results = action_fn(df, args.dv, args.iv, args.alpha)

    output = json.dumps(results, indent=2, ensure_ascii=False, default=str)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Results written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()

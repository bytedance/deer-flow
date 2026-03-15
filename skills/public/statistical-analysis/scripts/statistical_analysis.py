#!/usr/bin/env python3
"""Statistical analysis script for DeerFlow academic research.

Provides hypothesis testing, regression, EDA, ML evaluation, and
publication-quality visualizations using Python's scientific stack.
"""

import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

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
    import seaborn as sns

    plt.rcParams.update({
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "figure.figsize": (8, 6),
        "axes.spines.top": False,
        "axes.spines.right": False,
    })
    sns.set_style("whitegrid")
    sns.set_palette("colorblind")
    return plt, sns


def action_eda(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Exploratory Data Analysis."""
    plt, sns = setup_plotting()
    columns = params.get("columns")
    if columns:
        df_subset = df[columns]
    else:
        df_subset = df

    results = []
    results.append("# Exploratory Data Analysis Report\n")

    results.append(f"## Dataset Overview\n- Rows: {len(df)}\n- Columns: {len(df.columns)}\n")

    results.append("## Data Types\n")
    for col in df_subset.columns:
        results.append(f"- `{col}`: {df_subset[col].dtype}")

    numeric_cols = df_subset.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = df_subset.select_dtypes(include=["object", "category"]).columns.tolist()

    if numeric_cols:
        results.append("\n## Descriptive Statistics (Numeric)\n")
        desc = df_subset[numeric_cols].describe().round(4)
        results.append(desc.to_markdown())

        skew = df_subset[numeric_cols].skew().round(4)
        kurt = df_subset[numeric_cols].kurtosis().round(4)
        results.append("\n### Skewness & Kurtosis\n")
        sk_df = pd.DataFrame({"Skewness": skew, "Kurtosis": kurt})
        results.append(sk_df.to_markdown())

    missing = df_subset.isnull().sum()
    if missing.any():
        results.append("\n## Missing Values\n")
        miss_df = pd.DataFrame({
            "Column": missing.index,
            "Missing": missing.values,
            "Pct": (missing.values / len(df) * 100).round(2),
        })
        results.append(miss_df[miss_df["Missing"] > 0].to_markdown(index=False))

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    if len(numeric_cols) >= 2:
        fig, ax = plt.subplots(figsize=(max(8, len(numeric_cols) * 1.5), max(6, len(numeric_cols) * 1.2)))
        corr = df_subset[numeric_cols].corr()
        sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0, ax=ax, square=True)
        ax.set_title("Correlation Matrix")
        fig_path = os.path.join(fig_dir, "correlation_heatmap.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n## Correlation Heatmap\n![Correlation Matrix]({fig_path})\n")

    for i, col in enumerate(numeric_cols[:8]):
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        axes[0].hist(df_subset[col].dropna(), bins=30, edgecolor="black", alpha=0.7)
        axes[0].set_title(f"Distribution of {col}")
        axes[0].set_xlabel(col)
        axes[0].set_ylabel("Frequency")

        from scipy import stats

        stats.probplot(df_subset[col].dropna(), dist="norm", plot=axes[1])
        axes[1].set_title(f"Q-Q Plot of {col}")

        fig_path = os.path.join(fig_dir, f"dist_{col}.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n![Distribution of {col}]({fig_path})")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "eda_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_ttest(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Perform t-tests (independent, paired, one-sample)."""
    from scipy import stats

    plt, sns = setup_plotting()

    group_col = params.get("group_col")
    value_col = params["value_col"]
    test_type = params.get("test_type", "independent")
    alternative = params.get("alternative", "two-sided")
    mu = params.get("mu", 0)

    results = []
    results.append(f"# {test_type.title()} t-test Results\n")

    if test_type == "one_sample":
        data = df[value_col].dropna()
        t_stat, p_val = stats.ttest_1samp(data, mu, alternative=alternative)
        d = (data.mean() - mu) / data.std()
        ci = stats.t.interval(0.95, len(data) - 1, loc=data.mean(), scale=stats.sem(data))

        results.append(f"**Variable**: {value_col}")
        results.append(f"**Test against μ₀** = {mu}\n")
        results.append(f"| Statistic | Value |")
        results.append(f"|-----------|-------|")
        results.append(f"| t | {t_stat:.4f} |")
        results.append(f"| p-value | {p_val:.6f} |")
        results.append(f"| Cohen's d | {d:.4f} |")
        results.append(f"| Mean | {data.mean():.4f} |")
        results.append(f"| SD | {data.std():.4f} |")
        results.append(f"| 95% CI | [{ci[0]:.4f}, {ci[1]:.4f}] |")
        results.append(f"| N | {len(data)} |")

        sig = "significant" if p_val < 0.05 else "not significant"
        results.append(f"\n**APA Report:**\n> A one-sample t-test indicated that the mean ({data.mean():.2f}, SD = {data.std():.2f}) was {sig}ly different from {mu}, t({len(data) - 1}) = {t_stat:.2f}, p = {p_val:.3f}, d = {d:.2f}.")

    elif test_type == "paired":
        groups = df[group_col].unique()
        if len(groups) != 2:
            return f"Error: Paired t-test requires exactly 2 groups, found {len(groups)}"
        g1 = df[df[group_col] == groups[0]][value_col].dropna()
        g2 = df[df[group_col] == groups[1]][value_col].dropna()
        min_len = min(len(g1), len(g2))
        g1, g2 = g1.iloc[:min_len], g2.iloc[:min_len]

        t_stat, p_val = stats.ttest_rel(g1, g2, alternative=alternative)
        diff = g1.values - g2.values
        d = diff.mean() / diff.std()
        ci = stats.t.interval(0.95, len(diff) - 1, loc=diff.mean(), scale=stats.sem(diff))

        results.append(f"**Groups**: {groups[0]} vs {groups[1]}")
        results.append(f"**Variable**: {value_col}\n")
        results.append(f"| Statistic | Value |")
        results.append(f"|-----------|-------|")
        results.append(f"| t | {t_stat:.4f} |")
        results.append(f"| p-value | {p_val:.6f} |")
        results.append(f"| Cohen's d | {d:.4f} |")
        results.append(f"| Mean diff | {diff.mean():.4f} |")
        results.append(f"| 95% CI | [{ci[0]:.4f}, {ci[1]:.4f}] |")
        results.append(f"| N pairs | {len(diff)} |")

        sig = "significant" if p_val < 0.05 else "not significant"
        results.append(f"\n**APA Report:**\n> A paired-samples t-test showed a {sig} difference between {groups[0]} (M = {g1.mean():.2f}, SD = {g1.std():.2f}) and {groups[1]} (M = {g2.mean():.2f}, SD = {g2.std():.2f}), t({len(diff) - 1}) = {t_stat:.2f}, p = {p_val:.3f}, d = {d:.2f}.")

    else:  # independent
        groups = df[group_col].unique()
        if len(groups) != 2:
            return f"Error: Independent t-test requires exactly 2 groups, found {len(groups)}"
        g1 = df[df[group_col] == groups[0]][value_col].dropna()
        g2 = df[df[group_col] == groups[1]][value_col].dropna()

        _, levene_p = stats.levene(g1, g2)
        equal_var = levene_p > 0.05

        t_stat, p_val = stats.ttest_ind(g1, g2, equal_var=equal_var, alternative=alternative)
        pooled_std = np.sqrt(((len(g1) - 1) * g1.std() ** 2 + (len(g2) - 1) * g2.std() ** 2) / (len(g1) + len(g2) - 2))
        d = (g1.mean() - g2.mean()) / pooled_std

        _, shapiro_p1 = stats.shapiro(g1[:5000])
        _, shapiro_p2 = stats.shapiro(g2[:5000])

        dof = len(g1) + len(g2) - 2

        results.append(f"**Groups**: {groups[0]} (n={len(g1)}) vs {groups[1]} (n={len(g2)})")
        results.append(f"**Variable**: {value_col}\n")
        results.append(f"| Statistic | Value |")
        results.append(f"|-----------|-------|")
        results.append(f"| t | {t_stat:.4f} |")
        results.append(f"| df | {dof} |")
        results.append(f"| p-value | {p_val:.6f} |")
        results.append(f"| Cohen's d | {d:.4f} ({_interpret_d(d)}) |")
        results.append(f"| {groups[0]} Mean (SD) | {g1.mean():.4f} ({g1.std():.4f}) |")
        results.append(f"| {groups[1]} Mean (SD) | {g2.mean():.4f} ({g2.std():.4f}) |")

        results.append(f"\n**Assumption Checks:**")
        results.append(f"- Normality (Shapiro-Wilk): {groups[0]} p={shapiro_p1:.4f} {'✓' if shapiro_p1 > 0.05 else '✗'}, {groups[1]} p={shapiro_p2:.4f} {'✓' if shapiro_p2 > 0.05 else '✗'}")
        results.append(f"- Homogeneity of variance (Levene's): p={levene_p:.4f} {'✓' if levene_p > 0.05 else '✗ (Welch correction applied)'}")

        sig = "significant" if p_val < 0.05 else "not significant"
        test_name = "An independent-samples t-test" if equal_var else "A Welch's t-test"
        results.append(f"\n**APA Report:**\n> {test_name} revealed a statistically {sig} difference between {groups[0]} (M = {g1.mean():.2f}, SD = {g1.std():.2f}) and {groups[1]} (M = {g2.mean():.2f}, SD = {g2.std():.2f}), t({dof}) = {t_stat:.2f}, p = {p_val:.3f}, d = {d:.2f}.")

        fig_dir = os.path.join(output_dir, "figures")
        os.makedirs(fig_dir, exist_ok=True)
        fig, ax = plt.subplots(figsize=(8, 6))
        plot_data = pd.DataFrame({value_col: pd.concat([g1, g2], ignore_index=True), group_col: [groups[0]] * len(g1) + [groups[1]] * len(g2)})
        sns.violinplot(data=plot_data, x=group_col, y=value_col, ax=ax, inner="box")
        ax.set_title(f"{value_col} by {group_col}")
        fig_path = os.path.join(fig_dir, "ttest_violin.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n![t-test Violin Plot]({fig_path})")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "ttest_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_anova(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """One-way or two-way ANOVA."""
    from scipy import stats

    plt, sns = setup_plotting()

    group_col = params["group_col"]
    value_col = params["value_col"]
    post_hoc = params.get("post_hoc", "tukey")

    results = []
    results.append("# One-Way ANOVA Results\n")

    groups = df[group_col].unique()
    group_data = [df[df[group_col] == g][value_col].dropna() for g in groups]

    f_stat, p_val = stats.f_oneway(*group_data)

    grand_mean = df[value_col].mean()
    ss_between = sum(len(g) * (g.mean() - grand_mean) ** 2 for g in group_data)
    ss_total = sum((df[value_col].dropna() - grand_mean) ** 2)
    eta_sq = ss_between / ss_total

    df_between = len(groups) - 1
    df_within = len(df[value_col].dropna()) - len(groups)

    results.append(f"**Factor**: {group_col} ({len(groups)} levels)")
    results.append(f"**Dependent Variable**: {value_col}\n")
    results.append(f"| Source | SS | df | MS | F | p | η² |")
    results.append(f"|--------|---:|---:|---:|---:|---:|---:|")
    ms_between = ss_between / df_between
    ss_within = ss_total - ss_between
    ms_within = ss_within / df_within
    results.append(f"| Between | {ss_between:.2f} | {df_between} | {ms_between:.2f} | {f_stat:.4f} | {p_val:.6f} | {eta_sq:.4f} |")
    results.append(f"| Within | {ss_within:.2f} | {df_within} | {ms_within:.2f} | | | |")
    results.append(f"| Total | {ss_total:.2f} | {df_between + df_within} | | | | |")

    results.append(f"\n**Group Descriptives:**\n")
    results.append(f"| Group | N | Mean | SD |")
    results.append(f"|-------|--:|-----:|---:|")
    for g, gd in zip(groups, group_data):
        results.append(f"| {g} | {len(gd)} | {gd.mean():.4f} | {gd.std():.4f} |")

    sig = "significant" if p_val < 0.05 else "not significant"
    results.append(f"\n**APA Report:**\n> A one-way ANOVA revealed a statistically {sig} effect of {group_col} on {value_col}, F({df_between}, {df_within}) = {f_stat:.2f}, p = {p_val:.3f}, η² = {eta_sq:.3f}.")

    if p_val < 0.05 and post_hoc == "tukey":
        try:
            from statsmodels.stats.multicomp import pairwise_tukeyhsd

            tukey = pairwise_tukeyhsd(df[value_col].dropna(), df.loc[df[value_col].notna(), group_col])
            results.append(f"\n**Post-hoc (Tukey HSD):**\n```\n{tukey.summary()}\n```")
        except ImportError:
            results.append("\n(Tukey HSD requires statsmodels: pip install statsmodels)")

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    fig, ax = plt.subplots(figsize=(max(8, len(groups) * 1.5), 6))
    sns.boxplot(data=df, x=group_col, y=value_col, ax=ax)
    sns.stripplot(data=df, x=group_col, y=value_col, ax=ax, color="black", alpha=0.3, size=3)
    ax.set_title(f"{value_col} by {group_col}")
    fig_path = os.path.join(fig_dir, "anova_boxplot.png")
    fig.savefig(fig_path, bbox_inches="tight")
    plt.close(fig)
    results.append(f"\n![ANOVA Box Plot]({fig_path})")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "anova_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_chi_square(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Chi-square test of independence."""
    from scipy import stats

    plt, sns = setup_plotting()

    col1 = params["col1"]
    col2 = params["col2"]

    ct = pd.crosstab(df[col1], df[col2])
    chi2, p, dof, expected = stats.chi2_contingency(ct)

    n = ct.values.sum()
    k = min(ct.shape)
    cramers_v = np.sqrt(chi2 / (n * (k - 1))) if k > 1 else 0

    results = []
    results.append("# Chi-Square Test of Independence\n")
    results.append(f"**Variables**: {col1} × {col2}\n")
    results.append("## Contingency Table\n")
    results.append(ct.to_markdown())
    results.append(f"\n| Statistic | Value |")
    results.append(f"|-----------|-------|")
    results.append(f"| χ² | {chi2:.4f} |")
    results.append(f"| df | {dof} |")
    results.append(f"| p-value | {p:.6f} |")
    results.append(f"| Cramér's V | {cramers_v:.4f} ({_interpret_v(cramers_v)}) |")
    results.append(f"| N | {n} |")

    sig = "significant" if p < 0.05 else "not significant"
    results.append(f"\n**APA Report:**\n> A chi-square test of independence showed a {sig} association between {col1} and {col2}, χ²({dof}) = {chi2:.2f}, p = {p:.3f}, Cramér's V = {cramers_v:.2f}.")

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    fig, ax = plt.subplots(figsize=(max(8, len(ct.columns) * 1.5), max(6, len(ct.index) * 0.8)))
    sns.heatmap(ct, annot=True, fmt="d", cmap="YlOrRd", ax=ax)
    ax.set_title(f"Contingency Table: {col1} × {col2}")
    fig_path = os.path.join(fig_dir, "chi_square_heatmap.png")
    fig.savefig(fig_path, bbox_inches="tight")
    plt.close(fig)
    results.append(f"\n![Chi-Square Heatmap]({fig_path})")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "chi_square_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_correlation(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Correlation analysis with heatmap."""
    from scipy import stats as sp_stats

    plt, sns = setup_plotting()

    columns = params.get("columns")
    method = params.get("method", "pearson")

    if columns:
        df_subset = df[columns]
    else:
        df_subset = df.select_dtypes(include=[np.number])

    corr = df_subset.corr(method=method)

    results = []
    results.append(f"# Correlation Analysis ({method.title()})\n")
    results.append("## Correlation Matrix\n")
    results.append(corr.round(4).to_markdown())

    cols = corr.columns.tolist()
    results.append("\n## Pairwise Correlations (with p-values)\n")
    results.append("| Variable 1 | Variable 2 | r | p-value | Significance |")
    results.append("|-----------|-----------|---:|--------:|:------------:|")
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            x = df_subset[cols[i]].dropna()
            y = df_subset[cols[j]].dropna()
            common = x.index.intersection(y.index)
            if len(common) < 3:
                continue
            if method == "pearson":
                r, p = sp_stats.pearsonr(x[common], y[common])
            elif method == "spearman":
                r, p = sp_stats.spearmanr(x[common], y[common])
            else:
                r, p = sp_stats.kendalltau(x[common], y[common])
            sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
            results.append(f"| {cols[i]} | {cols[j]} | {r:.4f} | {p:.6f} | {sig} |")

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    fig, ax = plt.subplots(figsize=(max(8, len(cols) * 1.2), max(6, len(cols) * 1.0)))
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
    sns.heatmap(corr, mask=mask, annot=True, fmt=".2f", cmap="RdBu_r", center=0, ax=ax, square=True, vmin=-1, vmax=1)
    ax.set_title(f"{method.title()} Correlation Matrix")
    fig_path = os.path.join(fig_dir, "correlation_matrix.png")
    fig.savefig(fig_path, bbox_inches="tight")
    plt.close(fig)
    results.append(f"\n![Correlation Matrix]({fig_path})")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "correlation_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_regression(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Linear or logistic regression."""
    plt, sns = setup_plotting()

    x_cols = params["x_cols"]
    y_col = params["y_col"]
    model_type = params.get("model_type", "ols")

    X = df[x_cols].dropna()
    y = df.loc[X.index, y_col].dropna()
    common = X.index.intersection(y.index)
    X = X.loc[common]
    y = y.loc[common]

    results = []

    if model_type in ("ols", "linear"):
        import statsmodels.api as sm

        X_const = sm.add_constant(X)
        model = sm.OLS(y, X_const).fit()

        results.append("# Linear Regression Results\n")
        results.append(f"**Model**: {y_col} ~ {' + '.join(x_cols)}\n")
        results.append(f"```\n{model.summary()}\n```\n")

        results.append(f"\n**APA Report:**\n> The regression model was statistically {'significant' if model.f_pvalue < 0.05 else 'not significant'}, F({model.df_model:.0f}, {model.df_resid:.0f}) = {model.fvalue:.2f}, p {'< .001' if model.f_pvalue < 0.001 else f'= {model.f_pvalue:.3f}'}, R² = {model.rsquared:.3f}, Adjusted R² = {model.rsquared_adj:.3f}.")

        fig_dir = os.path.join(output_dir, "figures")
        os.makedirs(fig_dir, exist_ok=True)

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        axes[0].scatter(model.fittedvalues, model.resid, alpha=0.5, s=20)
        axes[0].axhline(y=0, color="r", linestyle="--")
        axes[0].set_xlabel("Fitted Values")
        axes[0].set_ylabel("Residuals")
        axes[0].set_title("Residuals vs Fitted")

        from scipy import stats

        stats.probplot(model.resid, dist="norm", plot=axes[1])
        axes[1].set_title("Q-Q Plot of Residuals")

        fig_path = os.path.join(fig_dir, "regression_diagnostics.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n![Regression Diagnostics]({fig_path})")

    elif model_type in ("logistic", "logit"):
        import statsmodels.api as sm

        X_const = sm.add_constant(X)
        model = sm.Logit(y, X_const).fit(disp=0)

        results.append("# Logistic Regression Results\n")
        results.append(f"**Model**: {y_col} ~ {' + '.join(x_cols)}\n")
        results.append(f"```\n{model.summary()}\n```\n")

        results.append("\n## Odds Ratios\n")
        results.append("| Variable | Coef | OR | 95% CI | p-value |")
        results.append("|----------|-----:|---:|-------:|--------:|")
        conf = model.conf_int()
        for var in model.params.index:
            coef = model.params[var]
            or_val = np.exp(coef)
            ci_low = np.exp(conf.loc[var, 0])
            ci_high = np.exp(conf.loc[var, 1])
            p = model.pvalues[var]
            results.append(f"| {var} | {coef:.4f} | {or_val:.4f} | [{ci_low:.2f}, {ci_high:.2f}] | {p:.4f} |")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "regression_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_mann_whitney(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Mann-Whitney U test (non-parametric alternative to independent t-test)."""
    from scipy import stats

    group_col = params["group_col"]
    value_col = params["value_col"]
    groups = df[group_col].unique()
    if len(groups) != 2:
        return f"Error: Mann-Whitney U test requires exactly 2 groups, found {len(groups)}"

    g1 = df[df[group_col] == groups[0]][value_col].dropna()
    g2 = df[df[group_col] == groups[1]][value_col].dropna()

    u_stat, p_val = stats.mannwhitneyu(g1, g2, alternative=params.get("alternative", "two-sided"))
    r = 1 - (2 * u_stat) / (len(g1) * len(g2))

    results = []
    results.append("# Mann-Whitney U Test Results\n")
    results.append(f"| Statistic | Value |")
    results.append(f"|-----------|-------|")
    results.append(f"| U | {u_stat:.4f} |")
    results.append(f"| p-value | {p_val:.6f} |")
    results.append(f"| rank-biserial r | {r:.4f} |")
    results.append(f"| {groups[0]} Median | {g1.median():.4f} (n={len(g1)}) |")
    results.append(f"| {groups[1]} Median | {g2.median():.4f} (n={len(g2)}) |")

    sig = "significant" if p_val < 0.05 else "not significant"
    results.append(f"\n**APA Report:**\n> A Mann-Whitney U test indicated a {sig} difference between {groups[0]} (Mdn = {g1.median():.2f}) and {groups[1]} (Mdn = {g2.median():.2f}), U = {u_stat:.0f}, p = {p_val:.3f}, r = {r:.2f}.")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "mann_whitney_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_normality(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Normality tests for specified columns."""
    from scipy import stats

    plt, sns = setup_plotting()

    columns = params.get("columns")
    if columns:
        numeric_cols = [c for c in columns if df[c].dtype in [np.float64, np.int64, np.float32, np.int32]]
    else:
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

    results = []
    results.append("# Normality Tests\n")
    results.append("| Column | Shapiro-Wilk W | p-value | Normal? | Skewness | Kurtosis |")
    results.append("|--------|:--------------:|--------:|:-------:|---------:|---------:|")

    for col in numeric_cols:
        data = df[col].dropna()
        if len(data) > 5000:
            data = data.sample(5000, random_state=42)
        w, p = stats.shapiro(data)
        skew = data.skew()
        kurt = data.kurtosis()
        normal = "✓" if p > 0.05 else "✗"
        results.append(f"| {col} | {w:.4f} | {p:.6f} | {normal} | {skew:.4f} | {kurt:.4f} |")

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    for col in numeric_cols[:6]:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        data = df[col].dropna()
        axes[0].hist(data, bins=30, density=True, alpha=0.7, edgecolor="black")
        xmin, xmax = data.min(), data.max()
        x = np.linspace(xmin, xmax, 100)
        axes[0].plot(x, stats.norm.pdf(x, data.mean(), data.std()), "r-", lw=2)
        axes[0].set_title(f"Distribution: {col}")

        stats.probplot(data, dist="norm", plot=axes[1])
        axes[1].set_title(f"Q-Q Plot: {col}")

        fig_path = os.path.join(fig_dir, f"normality_{col}.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n![Normality: {col}]({fig_path})")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "normality_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_ml_evaluate(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Machine learning model evaluation."""
    from sklearn.model_selection import cross_val_score, StratifiedKFold, KFold
    from sklearn.metrics import (
        classification_report,
        confusion_matrix,
        roc_curve,
        auc,
    )
    from sklearn.preprocessing import LabelEncoder, StandardScaler

    plt, sns = setup_plotting()

    x_cols = params["x_cols"]
    y_col = params["y_col"]
    model_type = params.get("model_type", "random_forest")
    cv_folds = params.get("cv_folds", 5)
    task = params.get("task", "classification")

    df_clean = df[x_cols + [y_col]].dropna()
    X = df_clean[x_cols].values
    y = df_clean[y_col].values

    scaler = StandardScaler()
    X = scaler.fit_transform(X)

    if task == "classification":
        le = LabelEncoder()
        y = le.fit_transform(y)

    if model_type == "random_forest":
        if task == "classification":
            from sklearn.ensemble import RandomForestClassifier
            model = RandomForestClassifier(n_estimators=100, random_state=42)
        else:
            from sklearn.ensemble import RandomForestRegressor
            model = RandomForestRegressor(n_estimators=100, random_state=42)
    elif model_type == "logistic":
        from sklearn.linear_model import LogisticRegression
        model = LogisticRegression(random_state=42, max_iter=1000)
    elif model_type == "svm":
        if task == "classification":
            from sklearn.svm import SVC
            model = SVC(probability=True, random_state=42)
        else:
            from sklearn.svm import SVR
            model = SVR()
    elif model_type == "gradient_boosting":
        if task == "classification":
            from sklearn.ensemble import GradientBoostingClassifier
            model = GradientBoostingClassifier(random_state=42)
        else:
            from sklearn.ensemble import GradientBoostingRegressor
            model = GradientBoostingRegressor(random_state=42)
    else:
        if task == "classification":
            from sklearn.ensemble import RandomForestClassifier
            model = RandomForestClassifier(n_estimators=100, random_state=42)
        else:
            from sklearn.ensemble import RandomForestRegressor
            model = RandomForestRegressor(n_estimators=100, random_state=42)

    results = []
    results.append(f"# ML Model Evaluation: {model_type}\n")
    results.append(f"**Task**: {task}")
    results.append(f"**Features**: {', '.join(x_cols)}")
    results.append(f"**Target**: {y_col}")
    results.append(f"**CV Folds**: {cv_folds}\n")

    if task == "classification":
        cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
        scoring_metrics = ["accuracy", "precision_macro", "recall_macro", "f1_macro"]
        results.append("## Cross-Validation Results\n")
        results.append("| Metric | Mean | Std |")
        results.append("|--------|-----:|----:|")
        for metric in scoring_metrics:
            scores = cross_val_score(model, X, y, cv=cv, scoring=metric)
            results.append(f"| {metric} | {scores.mean():.4f} | {scores.std():.4f} |")

        model.fit(X, y)
        y_pred = model.predict(X)
        results.append(f"\n## Classification Report (Full Data)\n```\n{classification_report(y, y_pred)}\n```")

        cm = confusion_matrix(y, y_pred)
        fig_dir = os.path.join(output_dir, "figures")
        os.makedirs(fig_dir, exist_ok=True)

        fig, ax = plt.subplots(figsize=(8, 6))
        sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", ax=ax)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual")
        ax.set_title("Confusion Matrix")
        fig_path = os.path.join(fig_dir, "confusion_matrix.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n![Confusion Matrix]({fig_path})")

        if hasattr(model, "predict_proba") and len(np.unique(y)) == 2:
            y_proba = model.predict_proba(X)[:, 1]
            fpr, tpr, _ = roc_curve(y, y_proba)
            roc_auc = auc(fpr, tpr)
            fig, ax = plt.subplots(figsize=(8, 6))
            ax.plot(fpr, tpr, lw=2, label=f"ROC (AUC = {roc_auc:.3f})")
            ax.plot([0, 1], [0, 1], "k--", lw=1)
            ax.set_xlabel("False Positive Rate")
            ax.set_ylabel("True Positive Rate")
            ax.set_title("ROC Curve")
            ax.legend()
            fig_path = os.path.join(fig_dir, "roc_curve.png")
            fig.savefig(fig_path, bbox_inches="tight")
            plt.close(fig)
            results.append(f"\n![ROC Curve]({fig_path})")

        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
            fi_df = pd.DataFrame({"Feature": x_cols, "Importance": importances}).sort_values("Importance", ascending=True)
            fig, ax = plt.subplots(figsize=(8, max(4, len(x_cols) * 0.4)))
            ax.barh(fi_df["Feature"], fi_df["Importance"])
            ax.set_title("Feature Importance")
            ax.set_xlabel("Importance")
            fig_path = os.path.join(fig_dir, "feature_importance.png")
            fig.savefig(fig_path, bbox_inches="tight")
            plt.close(fig)
            results.append(f"\n![Feature Importance]({fig_path})")

    else:
        cv = KFold(n_splits=cv_folds, shuffle=True, random_state=42)
        for metric in ["r2", "neg_mean_squared_error", "neg_mean_absolute_error"]:
            scores = cross_val_score(model, X, y, cv=cv, scoring=metric)
            label = metric.replace("neg_", "").replace("_", " ").title()
            val = abs(scores.mean()) if "neg" in metric else scores.mean()
            results.append(f"- **{label}**: {val:.4f} (±{scores.std():.4f})")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "ml_evaluation_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_pca(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Principal Component Analysis."""
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    plt, sns = setup_plotting()

    columns = params.get("columns")
    n_components = params.get("n_components", 3)

    if columns:
        X = df[columns].dropna()
    else:
        X = df.select_dtypes(include=[np.number]).dropna()

    col_names = X.columns.tolist()
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    pca = PCA(n_components=min(n_components, len(col_names)))
    X_pca = pca.fit_transform(X_scaled)

    results = []
    results.append("# Principal Component Analysis\n")
    results.append("## Explained Variance\n")
    results.append("| Component | Eigenvalue | Variance % | Cumulative % |")
    results.append("|-----------|----------:|----------:|-----------:|")
    cum_var = 0
    for i, (ev, var) in enumerate(zip(pca.explained_variance_, pca.explained_variance_ratio_)):
        cum_var += var * 100
        results.append(f"| PC{i + 1} | {ev:.4f} | {var * 100:.2f}% | {cum_var:.2f}% |")

    results.append("\n## Component Loadings\n")
    loadings = pd.DataFrame(pca.components_.T, columns=[f"PC{i + 1}" for i in range(pca.n_components_)], index=col_names)
    results.append(loadings.round(4).to_markdown())

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    full_pca = PCA().fit(X_scaled)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(range(1, len(full_pca.explained_variance_ratio_) + 1), full_pca.explained_variance_ratio_, alpha=0.7, label="Individual")
    ax.plot(range(1, len(full_pca.explained_variance_ratio_) + 1), np.cumsum(full_pca.explained_variance_ratio_), "ro-", label="Cumulative")
    ax.set_xlabel("Principal Component")
    ax.set_ylabel("Explained Variance Ratio")
    ax.set_title("Scree Plot")
    ax.legend()
    ax.axhline(y=0.95, color="gray", linestyle="--", alpha=0.5)
    fig_path = os.path.join(fig_dir, "pca_scree.png")
    fig.savefig(fig_path, bbox_inches="tight")
    plt.close(fig)
    results.append(f"\n![Scree Plot]({fig_path})")

    if pca.n_components_ >= 2:
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.scatter(X_pca[:, 0], X_pca[:, 1], alpha=0.5, s=20)
        for i, var in enumerate(col_names):
            ax.annotate("", xy=(pca.components_[0, i] * max(abs(X_pca[:, 0])), pca.components_[1, i] * max(abs(X_pca[:, 1]))),
                        xytext=(0, 0), arrowprops=dict(arrowstyle="->", color="red", lw=1.5))
            ax.text(pca.components_[0, i] * max(abs(X_pca[:, 0])) * 1.1,
                    pca.components_[1, i] * max(abs(X_pca[:, 1])) * 1.1, var, color="red", fontsize=9)
        ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0] * 100:.1f}%)")
        ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1] * 100:.1f}%)")
        ax.set_title("PCA Biplot")
        fig_path = os.path.join(fig_dir, "pca_biplot.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n![PCA Biplot]({fig_path})")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "pca_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_effect_size(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Calculate effect sizes."""
    group_col = params["group_col"]
    value_col = params["value_col"]
    measure = params.get("measure", "cohens_d")

    groups = df[group_col].unique()
    results = []
    results.append("# Effect Size Analysis\n")

    if len(groups) == 2:
        g1 = df[df[group_col] == groups[0]][value_col].dropna()
        g2 = df[df[group_col] == groups[1]][value_col].dropna()

        pooled_std = np.sqrt(((len(g1) - 1) * g1.std() ** 2 + (len(g2) - 1) * g2.std() ** 2) / (len(g1) + len(g2) - 2))
        d = (g1.mean() - g2.mean()) / pooled_std

        results.append(f"**Cohen's d** = {d:.4f} ({_interpret_d(d)})")
        results.append(f"**Hedges' g** = {d * (1 - 3 / (4 * (len(g1) + len(g2)) - 9)):.4f}")
        results.append(f"\n| Group | N | Mean | SD |")
        results.append(f"|-------|--:|-----:|---:|")
        results.append(f"| {groups[0]} | {len(g1)} | {g1.mean():.4f} | {g1.std():.4f} |")
        results.append(f"| {groups[1]} | {len(g2)} | {g2.mean():.4f} | {g2.std():.4f} |")
    else:
        results.append("Multiple group effect sizes (eta-squared) available via ANOVA action.")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "effect_size_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_power_analysis(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Statistical power analysis."""
    from scipy import stats

    effect_size = params.get("effect_size", 0.5)
    alpha = params.get("alpha", 0.05)
    power = params.get("power", 0.8)
    test_type = params.get("test_type", "ttest_ind")

    results = []
    results.append("# Statistical Power Analysis\n")

    if test_type == "ttest_ind":
        try:
            from statsmodels.stats.power import TTestIndPower

            analysis = TTestIndPower()
            n = analysis.solve_power(effect_size=effect_size, alpha=alpha, power=power, alternative="two-sided")
            results.append(f"**Test**: Independent t-test")
            results.append(f"**Effect size (d)**: {effect_size}")
            results.append(f"**Alpha**: {alpha}")
            results.append(f"**Desired Power**: {power}")
            results.append(f"\n**Required sample size per group**: {int(np.ceil(n))}")
            results.append(f"**Total required N**: {int(np.ceil(n)) * 2}")

            plt, _ = setup_plotting()
            fig, ax = plt.subplots(figsize=(8, 5))
            n_range = np.arange(5, int(n * 3), 1)
            powers = [analysis.power(effect_size, n_i, alpha) for n_i in n_range]
            ax.plot(n_range, powers, lw=2)
            ax.axhline(y=power, color="r", linestyle="--", alpha=0.7, label=f"Power = {power}")
            ax.axvline(x=n, color="g", linestyle="--", alpha=0.7, label=f"N = {int(np.ceil(n))}")
            ax.set_xlabel("Sample Size (per group)")
            ax.set_ylabel("Statistical Power")
            ax.set_title("Power Analysis Curve")
            ax.legend()
            fig_dir = os.path.join(output_dir, "figures")
            os.makedirs(fig_dir, exist_ok=True)
            fig_path = os.path.join(fig_dir, "power_curve.png")
            fig.savefig(fig_path, bbox_inches="tight")
            plt.close(fig)
            results.append(f"\n![Power Curve]({fig_path})")
        except ImportError:
            results.append("(Power analysis requires statsmodels: pip install statsmodels)")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "power_analysis_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def _interpret_d(d: float) -> str:
    """Interpret Cohen's d effect size."""
    d = abs(d)
    if d < 0.2:
        return "negligible"
    elif d < 0.5:
        return "small"
    elif d < 0.8:
        return "medium"
    else:
        return "large"


def _interpret_v(v: float) -> str:
    """Interpret Cramér's V effect size."""
    if v < 0.1:
        return "negligible"
    elif v < 0.3:
        return "small"
    elif v < 0.5:
        return "medium"
    else:
        return "large"


def action_kruskal(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Kruskal-Wallis H test (non-parametric one-way ANOVA)."""
    from scipy import stats

    plt, sns = setup_plotting()

    group_col = params["group_col"]
    value_col = params["value_col"]

    groups = df[group_col].unique()
    group_data = [df[df[group_col] == g][value_col].dropna() for g in groups]

    h_stat, p_val = stats.kruskal(*group_data)

    results = []
    results.append("# Kruskal-Wallis H Test Results\n")
    results.append(f"**Factor**: {group_col} ({len(groups)} levels)")
    results.append(f"**Dependent Variable**: {value_col}\n")
    results.append("| Statistic | Value |")
    results.append("|-----------|-------|")
    results.append(f"| H | {h_stat:.4f} |")
    results.append(f"| p-value | {p_val:.6f} |")
    results.append(f"| df | {len(groups) - 1} |")

    n_total = sum(len(g) for g in group_data)
    eta_sq_h = (h_stat - len(groups) + 1) / (n_total - len(groups))
    results.append(f"| η²_H (effect size) | {eta_sq_h:.4f} ({_interpret_d(eta_sq_h)}) |")

    results.append("\n**Group Medians:**\n")
    results.append("| Group | N | Median | Mean Rank |")
    results.append("|-------|--:|-------:|----------:|")
    all_values = df[[group_col, value_col]].dropna()
    all_values["rank"] = all_values[value_col].rank()
    for g, gd in zip(groups, group_data):
        mean_rank = all_values[all_values[group_col] == g]["rank"].mean()
        results.append(f"| {g} | {len(gd)} | {gd.median():.4f} | {mean_rank:.1f} |")

    sig = "significant" if p_val < 0.05 else "not significant"
    results.append(f"\n**APA Report:**\n> A Kruskal-Wallis H test showed a {sig} effect of {group_col} on {value_col}, H({len(groups) - 1}) = {h_stat:.2f}, p = {p_val:.3f}.")

    if p_val < 0.05:
        results.append("\n**Post-hoc pairwise Mann-Whitney U tests** (with Bonferroni correction):")
        results.append("\n| Comparison | U | p (adjusted) | Significant |")
        results.append("|-----------|--:|------------:|:-----------:|")
        n_comparisons = len(groups) * (len(groups) - 1) // 2
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                u, p = stats.mannwhitneyu(group_data[i], group_data[j], alternative="two-sided")
                p_adj = min(p * n_comparisons, 1.0)
                sig_mark = "✓" if p_adj < 0.05 else ""
                results.append(f"| {groups[i]} vs {groups[j]} | {u:.0f} | {p_adj:.4f} | {sig_mark} |")

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    fig, ax = plt.subplots(figsize=(max(8, len(groups) * 1.5), 6))
    sns.boxplot(data=df, x=group_col, y=value_col, ax=ax)
    ax.set_title(f"Kruskal-Wallis: {value_col} by {group_col}")
    fig_path = os.path.join(fig_dir, "kruskal_boxplot.png")
    fig.savefig(fig_path, bbox_inches="tight")
    plt.close(fig)
    results.append(f"\n![Kruskal-Wallis Box Plot]({fig_path})")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "kruskal_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_clustering(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """K-Means or Hierarchical clustering."""
    from sklearn.cluster import KMeans, AgglomerativeClustering
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import silhouette_score, calinski_harabasz_score

    plt, sns = setup_plotting()

    columns = params.get("columns")
    n_clusters = params.get("n_clusters", 3)
    method = params.get("method", "kmeans")

    if columns:
        X = df[columns].dropna()
    else:
        X = df.select_dtypes(include=[np.number]).dropna()

    col_names = X.columns.tolist()
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    results = []
    results.append(f"# Clustering Analysis ({method.title()})\n")
    results.append(f"**Features**: {', '.join(col_names)}")
    results.append(f"**N clusters**: {n_clusters}")
    results.append(f"**N samples**: {len(X)}\n")

    if method == "kmeans":
        model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = model.fit_predict(X_scaled)
    else:
        model = AgglomerativeClustering(n_clusters=n_clusters)
        labels = model.fit_predict(X_scaled)

    sil_score = silhouette_score(X_scaled, labels) if len(set(labels)) > 1 else 0
    ch_score = calinski_harabasz_score(X_scaled, labels) if len(set(labels)) > 1 else 0

    results.append("## Clustering Quality Metrics\n")
    results.append("| Metric | Value | Interpretation |")
    results.append("|--------|------:|---------------|")
    sil_interp = "good" if sil_score > 0.5 else "fair" if sil_score > 0.25 else "poor"
    results.append(f"| Silhouette Score | {sil_score:.4f} | {sil_interp} |")
    results.append(f"| Calinski-Harabasz | {ch_score:.2f} | higher = better |")

    results.append("\n## Cluster Profiles\n")
    X_with_labels = X.copy()
    X_with_labels["Cluster"] = labels
    profile = X_with_labels.groupby("Cluster").agg(["mean", "std", "count"])
    for col in col_names:
        results.append(f"\n### {col}")
        results.append("| Cluster | N | Mean | Std |")
        results.append("|---------|--:|-----:|----:|")
        for c in sorted(X_with_labels["Cluster"].unique()):
            cluster_data = X_with_labels[X_with_labels["Cluster"] == c]
            results.append(f"| {c} | {len(cluster_data)} | {cluster_data[col].mean():.4f} | {cluster_data[col].std():.4f} |")

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    if method == "kmeans":
        inertias = []
        sil_scores = []
        k_range = range(2, min(11, len(X)))
        for k in k_range:
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            km.fit(X_scaled)
            inertias.append(km.inertia_)
            sil_scores.append(silhouette_score(X_scaled, km.labels_))

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        axes[0].plot(list(k_range), inertias, "bo-")
        axes[0].set_xlabel("Number of Clusters (k)")
        axes[0].set_ylabel("Inertia")
        axes[0].set_title("Elbow Method")
        axes[1].plot(list(k_range), sil_scores, "ro-")
        axes[1].set_xlabel("Number of Clusters (k)")
        axes[1].set_ylabel("Silhouette Score")
        axes[1].set_title("Silhouette Analysis")
        fig_path = os.path.join(fig_dir, "clustering_elbow.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n![Elbow & Silhouette]({fig_path})")

    if len(col_names) >= 2:
        from sklearn.decomposition import PCA
        pca = PCA(n_components=2)
        X_2d = pca.fit_transform(X_scaled)

        fig, ax = plt.subplots(figsize=(8, 6))
        scatter = ax.scatter(X_2d[:, 0], X_2d[:, 1], c=labels, cmap="Set2", alpha=0.7, s=30)
        ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0] * 100:.1f}%)")
        ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1] * 100:.1f}%)")
        ax.set_title(f"Clusters (projected to 2D)")
        plt.colorbar(scatter, label="Cluster")
        fig_path = os.path.join(fig_dir, "clustering_scatter.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n![Cluster Scatter]({fig_path})")

    if method != "kmeans":
        from scipy.cluster.hierarchy import dendrogram, linkage
        Z = linkage(X_scaled, method="ward")
        fig, ax = plt.subplots(figsize=(12, 6))
        dendrogram(Z, truncate_mode="lastp", p=30, ax=ax, leaf_rotation=90)
        ax.set_title("Hierarchical Clustering Dendrogram")
        ax.set_xlabel("Sample index or (cluster size)")
        ax.set_ylabel("Distance")
        fig_path = os.path.join(fig_dir, "dendrogram.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n![Dendrogram]({fig_path})")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "clustering_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_survival(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Kaplan-Meier survival analysis and log-rank test."""
    plt, sns = setup_plotting()

    time_col = params["time_col"]
    event_col = params["event_col"]
    group_col = params.get("group_col")

    results = []
    results.append("# Survival Analysis Results\n")

    try:
        from lifelines import KaplanMeierFitter
        from lifelines.statistics import logrank_test

        fig_dir = os.path.join(output_dir, "figures")
        os.makedirs(fig_dir, exist_ok=True)

        fig, ax = plt.subplots(figsize=(10, 6))

        if group_col:
            groups = df[group_col].unique()
            results.append(f"**Time variable**: {time_col}")
            results.append(f"**Event variable**: {event_col}")
            results.append(f"**Grouping variable**: {group_col} ({len(groups)} groups)\n")

            results.append("## Kaplan-Meier Estimates\n")
            results.append("| Group | N | Events | Median Survival | 95% CI |")
            results.append("|-------|--:|-------:|----------------:|-------:|")

            kmfs = {}
            for g in groups:
                mask = df[group_col] == g
                kmf = KaplanMeierFitter()
                kmf.fit(df.loc[mask, time_col], event_observed=df.loc[mask, event_col], label=str(g))
                kmf.plot_survival_function(ax=ax)
                kmfs[g] = kmf

                median = kmf.median_survival_time_
                ci = kmf.confidence_interval_survival_function_
                n = mask.sum()
                events = df.loc[mask, event_col].sum()
                results.append(f"| {g} | {n} | {int(events)} | {median:.2f} | — |")

            if len(groups) == 2:
                g1_mask = df[group_col] == groups[0]
                g2_mask = df[group_col] == groups[1]
                lr = logrank_test(
                    df.loc[g1_mask, time_col], df.loc[g2_mask, time_col],
                    event_observed_A=df.loc[g1_mask, event_col],
                    event_observed_B=df.loc[g2_mask, event_col]
                )
                results.append(f"\n## Log-rank Test\n")
                results.append(f"| Statistic | Value |")
                results.append(f"|-----------|-------|")
                results.append(f"| Test statistic | {lr.test_statistic:.4f} |")
                results.append(f"| p-value | {lr.p_value:.6f} |")

                sig = "significant" if lr.p_value < 0.05 else "not significant"
                results.append(f"\n**APA Report:**\n> A log-rank test indicated a {sig} difference in survival between {groups[0]} and {groups[1]}, χ²(1) = {lr.test_statistic:.2f}, p = {lr.p_value:.3f}.")
        else:
            kmf = KaplanMeierFitter()
            kmf.fit(df[time_col], event_observed=df[event_col], label="Overall")
            kmf.plot_survival_function(ax=ax)

            results.append(f"**Time variable**: {time_col}")
            results.append(f"**Event variable**: {event_col}\n")
            results.append(f"| Statistic | Value |")
            results.append(f"|-----------|-------|")
            results.append(f"| N | {len(df)} |")
            results.append(f"| Events | {int(df[event_col].sum())} |")
            results.append(f"| Median survival | {kmf.median_survival_time_:.2f} |")

        ax.set_title("Kaplan-Meier Survival Curves")
        ax.set_xlabel("Time")
        ax.set_ylabel("Survival Probability")
        fig_path = os.path.join(fig_dir, "survival_curves.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n![Survival Curves]({fig_path})")

    except ImportError:
        results.append("**Note**: lifelines library not available. Install with `pip install lifelines`.")
        results.append("\nFalling back to basic survival table computation...\n")

        df_sorted = df.sort_values(time_col)
        results.append(f"**Time variable**: {time_col}")
        results.append(f"**Event variable**: {event_col}")
        results.append(f"**N**: {len(df)}")
        results.append(f"**Events**: {int(df[event_col].sum())}")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "survival_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_mixed_effects(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """Linear mixed effects model."""
    results = []
    results.append("# Mixed Effects Model Results\n")

    try:
        import statsmodels.formula.api as smf

        formula = params["formula"]
        groups = params["groups"]
        re_formula = params.get("re_formula", "1")

        results.append(f"**Formula**: {formula}")
        results.append(f"**Groups**: {groups}")
        results.append(f"**Random effects**: {re_formula}\n")

        model = smf.mixedlm(formula, df, groups=df[groups], re_formula=f"~{re_formula}")
        result = model.fit(reml=True)

        results.append(f"```\n{result.summary()}\n```\n")

        results.append("## Fixed Effects\n")
        results.append("| Parameter | Estimate | Std.Err | z | p-value | 95% CI |")
        results.append("|-----------|--------:|---------:|---:|--------:|-------:|")
        for param in result.fe_params.index:
            est = result.fe_params[param]
            se = result.bse_fe[param]
            z = result.tvalues[param]
            p = result.pvalues[param]
            ci = result.conf_int().loc[param]
            results.append(f"| {param} | {est:.4f} | {se:.4f} | {z:.2f} | {p:.4f} | [{ci[0]:.3f}, {ci[1]:.3f}] |")

        results.append("\n## Random Effects Variance\n")
        results.append(f"- Group Var: {result.cov_re.iloc[0, 0]:.4f}")
        results.append(f"- Residual Var: {result.scale:.4f}")
        results.append(f"- ICC: {result.cov_re.iloc[0, 0] / (result.cov_re.iloc[0, 0] + result.scale):.4f}")

        results.append(f"\n## Model Fit\n")
        results.append(f"- Log-Likelihood: {result.llf:.2f}")
        results.append(f"- AIC: {-2 * result.llf + 2 * len(result.fe_params):.2f}")
        results.append(f"- N groups: {result.ngroups}")
        results.append(f"- N observations: {result.nobs}")

    except ImportError:
        results.append("**Error**: statsmodels is required. Install with `pip install statsmodels`.")
    except Exception as e:
        results.append(f"**Error**: {e}")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "mixed_effects_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def action_shap_explain(df: pd.DataFrame, params: dict, output_dir: str) -> str:
    """SHAP feature importance and model explainability."""
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import LabelEncoder, StandardScaler

    plt, sns = setup_plotting()

    x_cols = params["x_cols"]
    y_col = params["y_col"]
    model_type = params.get("model_type", "random_forest")
    task = params.get("task", "classification")

    df_clean = df[x_cols + [y_col]].dropna()
    X = df_clean[x_cols]
    y = df_clean[y_col]

    if task == "classification":
        le = LabelEncoder()
        y = le.fit_transform(y)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    if model_type == "random_forest":
        if task == "classification":
            from sklearn.ensemble import RandomForestClassifier
            model = RandomForestClassifier(n_estimators=100, random_state=42)
        else:
            from sklearn.ensemble import RandomForestRegressor
            model = RandomForestRegressor(n_estimators=100, random_state=42)
    elif model_type == "gradient_boosting":
        if task == "classification":
            from sklearn.ensemble import GradientBoostingClassifier
            model = GradientBoostingClassifier(random_state=42)
        else:
            from sklearn.ensemble import GradientBoostingRegressor
            model = GradientBoostingRegressor(random_state=42)
    else:
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        model = RandomForestClassifier(n_estimators=100, random_state=42) if task == "classification" else RandomForestRegressor(n_estimators=100, random_state=42)

    model.fit(X_train, y_train)

    results = []
    results.append(f"# SHAP Explainability Analysis\n")
    results.append(f"**Model**: {model_type}")
    results.append(f"**Task**: {task}")
    results.append(f"**Features**: {', '.join(x_cols)}")
    results.append(f"**Target**: {y_col}\n")

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    try:
        import shap

        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_test)

        if task == "classification" and isinstance(shap_values, list):
            shap_vals = shap_values[1] if len(shap_values) > 1 else shap_values[0]
        else:
            shap_vals = shap_values

        mean_abs_shap = np.abs(shap_vals).mean(axis=0)
        fi_df = pd.DataFrame({"Feature": x_cols, "Mean |SHAP|": mean_abs_shap}).sort_values("Mean |SHAP|", ascending=False)

        results.append("## SHAP Feature Importance\n")
        results.append("| Rank | Feature | Mean |SHAP value| |")
        results.append("|-----:|---------|------------------:|")
        for i, (_, row) in enumerate(fi_df.iterrows(), 1):
            results.append(f"| {i} | {row['Feature']} | {row['Mean |SHAP|']:.4f} |")

        fig, ax = plt.subplots(figsize=(10, max(4, len(x_cols) * 0.4)))
        shap.summary_plot(shap_vals, X_test, feature_names=x_cols, show=False, plot_type="bar")
        fig_path = os.path.join(fig_dir, "shap_importance.png")
        plt.savefig(fig_path, bbox_inches="tight", dpi=300)
        plt.close("all")
        results.append(f"\n![SHAP Importance]({fig_path})")

        fig, ax = plt.subplots(figsize=(10, max(5, len(x_cols) * 0.5)))
        shap.summary_plot(shap_vals, X_test, feature_names=x_cols, show=False)
        fig_path2 = os.path.join(fig_dir, "shap_beeswarm.png")
        plt.savefig(fig_path2, bbox_inches="tight", dpi=300)
        plt.close("all")
        results.append(f"\n![SHAP Beeswarm]({fig_path2})")

    except ImportError:
        results.append("**Note**: SHAP library not available. Falling back to permutation importance.\n")
        from sklearn.inspection import permutation_importance

        perm_imp = permutation_importance(model, X_test, y_test, n_repeats=10, random_state=42)
        fi_df = pd.DataFrame({
            "Feature": x_cols,
            "Importance Mean": perm_imp.importances_mean,
            "Importance Std": perm_imp.importances_std,
        }).sort_values("Importance Mean", ascending=False)

        results.append("## Permutation Feature Importance\n")
        results.append("| Feature | Importance (Mean ± Std) |")
        results.append("|---------|------------------------:|")
        for _, row in fi_df.iterrows():
            results.append(f"| {row['Feature']} | {row['Importance Mean']:.4f} ± {row['Importance Std']:.4f} |")

        fig, ax = plt.subplots(figsize=(8, max(4, len(x_cols) * 0.4)))
        fi_sorted = fi_df.sort_values("Importance Mean", ascending=True)
        ax.barh(fi_sorted["Feature"], fi_sorted["Importance Mean"], xerr=fi_sorted["Importance Std"])
        ax.set_title("Permutation Feature Importance")
        ax.set_xlabel("Mean Importance")
        fig_path = os.path.join(fig_dir, "permutation_importance.png")
        fig.savefig(fig_path, bbox_inches="tight")
        plt.close(fig)
        results.append(f"\n![Permutation Importance]({fig_path})")

    report = "\n".join(results)
    report_path = os.path.join(output_dir, "shap_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    return report


def format_p_stars(p_value):
    """Format p-value as significance stars for academic figure annotations."""
    if p_value < 0.001:
        return "***"
    elif p_value < 0.01:
        return "**"
    elif p_value < 0.05:
        return "*"
    return "ns"


def add_significance_bracket(ax, x1, x2, y, p_value, dh=0.02, barh=0.02):
    """Add significance bracket with stars above a bar chart."""
    stars = format_p_stars(p_value)
    if stars == "ns":
        return
    lx, rx = x1, x2
    by = y + dh
    ax.plot([lx, lx, rx, rx], [by, by + barh, by + barh, by], lw=1.2, c="black")
    ax.text((lx + rx) / 2, by + barh, stars, ha="center", va="bottom", fontsize=11)


def action_timeseries(df, params, output_dir):
    """Time series analysis: stationarity test + decomposition + ARIMA + forecast."""
    setup_plotting()
    import matplotlib.pyplot as plt

    date_col = params.get("date_col")
    value_col = params.get("value_col")
    freq = params.get("freq", "M")
    forecast_periods = params.get("forecast_periods", 12)

    if not date_col or not value_col:
        return "Error: 'date_col' and 'value_col' are required parameters."

    results = ["# Time Series Analysis\n"]
    df[date_col] = pd.to_datetime(df[date_col])
    ts = df.set_index(date_col)[value_col].sort_index().dropna()

    try:
        from statsmodels.tsa.stattools import adfuller
        from statsmodels.tsa.seasonal import seasonal_decompose

        adf_result = adfuller(ts, autolag="AIC")
        results.append(f"## Stationarity (ADF Test)\n- Test Statistic: {adf_result[0]:.4f}\n- p-value: {adf_result[1]:.4f}\n- Stationary: {'Yes' if adf_result[1] < 0.05 else 'No (consider differencing)'}\n")

        fig_dir = os.path.join(output_dir, "figures")
        os.makedirs(fig_dir, exist_ok=True)

        try:
            decomp = seasonal_decompose(ts, period=int(params.get("period", max(2, len(ts) // 4))))
            fig = decomp.plot()
            fig.set_size_inches(10, 8)
            fig_path = os.path.join(fig_dir, "ts_decomposition.png")
            fig.savefig(fig_path, bbox_inches="tight")
            plt.close(fig)
            results.append(f"## Seasonal Decomposition\n![Decomposition]({fig_path})\n")
        except Exception as e:
            results.append(f"Decomposition skipped: {e}\n")

        try:
            from statsmodels.tsa.arima.model import ARIMA
            model = ARIMA(ts, order=(1, 1 if adf_result[1] > 0.05 else 0, 1))
            fitted = model.fit()
            results.append(f"## ARIMA Model\n- AIC: {fitted.aic:.2f}\n- BIC: {fitted.bic:.2f}\n")
            forecast = fitted.forecast(steps=forecast_periods)
            results.append(f"## Forecast ({forecast_periods} periods)\n")
            for i, val in enumerate(forecast):
                results.append(f"- Period {i+1}: {val:.4f}")

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(ts.index, ts.values, label="Observed", color="#2196F3")
            fc_index = pd.date_range(start=ts.index[-1], periods=forecast_periods + 1, freq=freq)[1:]
            ax.plot(fc_index, forecast.values, label="Forecast", color="#FF5722", linestyle="--")
            ax.set_title("Time Series Forecast")
            ax.legend()
            fig_path = os.path.join(fig_dir, "ts_forecast.png")
            fig.savefig(fig_path, bbox_inches="tight")
            plt.close(fig)
            results.append(f"\n![Forecast]({fig_path})\n")
        except Exception as e:
            results.append(f"ARIMA fitting skipped: {e}\n")

    except ImportError:
        results.append("**Error**: statsmodels is required for time series analysis. Install with: `pip install statsmodels`\n")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "timeseries_report.md"), "w") as f:
        f.write(report)
    return report


def action_causal_psm(df, params, output_dir):
    """Propensity Score Matching for causal inference."""
    setup_plotting()
    import matplotlib.pyplot as plt
    from scipy.spatial.distance import cdist

    treatment_col = params.get("treatment_col")
    outcome_col = params.get("outcome_col")
    covariates = params.get("covariates", [])

    if not treatment_col or not outcome_col or not covariates:
        return "Error: 'treatment_col', 'outcome_col', and 'covariates' are required."

    results = ["# Propensity Score Matching\n"]
    from sklearn.linear_model import LogisticRegression

    X = df[covariates].dropna()
    y = df.loc[X.index, treatment_col]
    lr = LogisticRegression(max_iter=1000, random_state=42)
    lr.fit(X, y)
    df_clean = df.loc[X.index].copy()
    df_clean["propensity_score"] = lr.predict_proba(X)[:, 1]

    treated = df_clean[df_clean[treatment_col] == 1]
    control = df_clean[df_clean[treatment_col] == 0]

    distances = cdist(treated[["propensity_score"]], control[["propensity_score"]], metric="euclidean")
    matched_indices = distances.argmin(axis=1)
    matched_control = control.iloc[matched_indices]

    att = treated[outcome_col].mean() - matched_control[outcome_col].mean()
    from scipy.stats import ttest_ind
    t_stat, p_val = ttest_ind(treated[outcome_col], matched_control[outcome_col])

    results.append(f"## Results\n- Treated mean: {treated[outcome_col].mean():.4f}\n- Matched control mean: {matched_control[outcome_col].mean():.4f}\n- **ATT (Average Treatment Effect on Treated): {att:.4f}**\n- t-statistic: {t_stat:.4f}, p-value: {p_val:.4f} {format_p_stars(p_val)}\n")

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(treated["propensity_score"], bins=30, alpha=0.6, label="Treated", color="#2196F3")
    ax.hist(matched_control["propensity_score"], bins=30, alpha=0.6, label="Matched Control", color="#FF9800")
    ax.set_xlabel("Propensity Score")
    ax.set_title("Propensity Score Distribution (After Matching)")
    ax.legend()
    fig_path = os.path.join(fig_dir, "psm_distribution.png")
    fig.savefig(fig_path, bbox_inches="tight")
    plt.close(fig)
    results.append(f"![PSM Distribution]({fig_path})\n")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "psm_report.md"), "w") as f:
        f.write(report)
    return report


def action_causal_did(df, params, output_dir):
    """Difference-in-Differences estimation."""
    group_col = params.get("group_col")
    time_col = params.get("time_col")
    outcome_col = params.get("outcome_col")
    post_period = params.get("post_period")

    if not all([group_col, time_col, outcome_col, post_period]):
        return "Error: 'group_col', 'time_col', 'outcome_col', 'post_period' are required."

    results = ["# Difference-in-Differences Analysis\n"]
    df["post"] = (df[time_col] >= post_period).astype(int)

    try:
        import statsmodels.formula.api as smf
        formula = f"{outcome_col} ~ {group_col} * post"
        model = smf.ols(formula, data=df).fit()
        results.append(f"## OLS Regression with Interaction\n```\n{model.summary().as_text()}\n```\n")
        did_coeff = model.params.get(f"{group_col}:post", None)
        did_pval = model.pvalues.get(f"{group_col}:post", None)
        if did_coeff is not None:
            results.append(f"\n## DiD Estimate\n- **DiD coefficient**: {did_coeff:.4f}\n- **p-value**: {did_pval:.4f} {format_p_stars(did_pval)}\n")
    except ImportError:
        results.append("**Error**: statsmodels required. Install: `pip install statsmodels`\n")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "did_report.md"), "w") as f:
        f.write(report)
    return report


def action_mediation(df, params, output_dir):
    """Mediation analysis (Baron & Kenny + Sobel test)."""
    x_col, m_col, y_col = params.get("x_col"), params.get("m_col"), params.get("y_col")
    if not all([x_col, m_col, y_col]):
        return "Error: 'x_col', 'm_col', 'y_col' are required."

    results = ["# Mediation Analysis (Baron & Kenny)\n"]
    try:
        import statsmodels.formula.api as smf
        path_c = smf.ols(f"{y_col} ~ {x_col}", data=df).fit()
        path_a = smf.ols(f"{m_col} ~ {x_col}", data=df).fit()
        path_bc = smf.ols(f"{y_col} ~ {x_col} + {m_col}", data=df).fit()

        a = path_a.params[x_col]
        b = path_bc.params[m_col]
        c = path_c.params[x_col]
        c_prime = path_bc.params[x_col]
        indirect = a * b
        se_indirect = np.sqrt(a**2 * path_bc.bse[m_col]**2 + b**2 * path_a.bse[x_col]**2)
        sobel_z = indirect / se_indirect
        from scipy.stats import norm
        sobel_p = 2 * (1 - norm.cdf(abs(sobel_z)))

        results.append(f"## Path Coefficients\n- Path c (total effect): {c:.4f} (p={path_c.pvalues[x_col]:.4f})\n- Path a (X→M): {a:.4f} (p={path_a.pvalues[x_col]:.4f})\n- Path b (M→Y|X): {b:.4f} (p={path_bc.pvalues[m_col]:.4f})\n- Path c' (direct effect): {c_prime:.4f} (p={path_bc.pvalues[x_col]:.4f})\n")
        results.append(f"## Indirect Effect\n- **Indirect effect (a×b)**: {indirect:.4f}\n- **Sobel Z**: {sobel_z:.4f}\n- **Sobel p**: {sobel_p:.4f} {format_p_stars(sobel_p)}\n- **Mediation ratio**: {abs(indirect/c)*100:.1f}%\n")
    except ImportError:
        results.append("**Error**: statsmodels required.\n")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "mediation_report.md"), "w") as f:
        f.write(report)
    return report


def action_moderation(df, params, output_dir):
    """Moderation analysis (interaction effects)."""
    x_col, mod_col, y_col = params.get("x_col"), params.get("mod_col"), params.get("y_col")
    if not all([x_col, mod_col, y_col]):
        return "Error: 'x_col', 'mod_col', 'y_col' are required."

    results = ["# Moderation Analysis\n"]
    try:
        import statsmodels.formula.api as smf
        df["interaction"] = df[x_col] * df[mod_col]
        model = smf.ols(f"{y_col} ~ {x_col} + {mod_col} + interaction", data=df).fit()
        results.append(f"## Regression with Interaction\n```\n{model.summary().as_text()}\n```\n")
        int_p = model.pvalues.get("interaction", 1.0)
        results.append(f"\n## Interaction Effect\n- **Coefficient**: {model.params['interaction']:.4f}\n- **p-value**: {int_p:.4f} {format_p_stars(int_p)}\n- **Moderation**: {'Significant' if int_p < 0.05 else 'Not significant'}\n")
    except ImportError:
        results.append("**Error**: statsmodels required.\n")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "moderation_report.md"), "w") as f:
        f.write(report)
    return report


def action_multicollinearity(df, params, output_dir):
    """Multicollinearity diagnostics (VIF + condition number)."""
    x_cols = params.get("x_cols", [])
    if not x_cols:
        return "Error: 'x_cols' is required."

    results = ["# Multicollinearity Diagnostics\n"]
    X = df[x_cols].dropna()

    try:
        from statsmodels.stats.outliers_influence import variance_inflation_factor
        vif_data = pd.DataFrame({
            "Variable": x_cols,
            "VIF": [variance_inflation_factor(X.values, i) for i in range(len(x_cols))],
        })
        results.append("## Variance Inflation Factors\n| Variable | VIF | Status |\n|----------|----:|--------|\n")
        for _, row in vif_data.iterrows():
            status = "⚠️ HIGH" if row["VIF"] > 5 else ("⚠️ MODERATE" if row["VIF"] > 2.5 else "✓ OK")
            results.append(f"| {row['Variable']} | {row['VIF']:.2f} | {status} |")
        cond = np.linalg.cond(X.values)
        results.append(f"\n## Condition Number: {cond:.2f}\n- {'⚠️ Severe multicollinearity' if cond > 30 else ('⚠️ Moderate' if cond > 10 else '✓ Acceptable')}\n")
    except ImportError:
        results.append("**Error**: statsmodels required.\n")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "multicollinearity_report.md"), "w") as f:
        f.write(report)
    return report


def action_robustness(df, params, output_dir):
    """Multi-specification robustness check."""
    x_cols_list = params.get("x_cols_list", [])
    y_col = params.get("y_col")
    model_types = params.get("model_types", ["ols"])

    if not x_cols_list or not y_col:
        return "Error: 'x_cols_list' (list of lists) and 'y_col' are required."

    results = ["# Robustness / Multi-Specification Check\n"]
    results.append("| Spec | Variables | Model | Coeff (first IV) | SE | p-value | R² |\n|------|-----------|-------|:----------------:|---:|--------:|---:|\n")

    try:
        import statsmodels.formula.api as smf
        for i, x_cols in enumerate(x_cols_list):
            for mt in model_types:
                formula = f"{y_col} ~ {' + '.join(x_cols)}"
                if mt == "ols":
                    model = smf.ols(formula, data=df.dropna(subset=x_cols + [y_col])).fit()
                elif mt == "robust":
                    model = smf.ols(formula, data=df.dropna(subset=x_cols + [y_col])).fit(cov_type="HC3")
                else:
                    model = smf.ols(formula, data=df.dropna(subset=x_cols + [y_col])).fit()
                first_iv = x_cols[0]
                coeff = model.params[first_iv]
                se = model.bse[first_iv]
                pval = model.pvalues[first_iv]
                r2 = model.rsquared
                results.append(f"| {i+1} | {', '.join(x_cols)} | {mt} | {coeff:.4f} | {se:.4f} | {pval:.4f}{format_p_stars(pval)} | {r2:.3f} |")
        results.append("\n**Interpretation**: If the coefficient of the first IV remains significant and similar in magnitude across specifications, the result is robust.\n")
    except ImportError:
        results.append("**Error**: statsmodels required.\n")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "robustness_report.md"), "w") as f:
        f.write(report)
    return report


def action_missing_diagnosis(df, params, output_dir):
    """Missing data diagnosis and pattern visualization."""
    setup_plotting()
    import matplotlib.pyplot as plt
    import seaborn as sns

    columns = params.get("columns", list(df.columns))
    sub = df[columns]

    results = ["# Missing Data Diagnosis\n"]
    missing = sub.isnull().sum()
    pct = (missing / len(sub) * 100).round(2)
    miss_df = pd.DataFrame({"Column": columns, "Missing": missing.values, "Percent": pct.values}).sort_values("Percent", ascending=False)
    results.append("## Missing Value Summary\n| Column | Missing | Percent |\n|--------|--------:|--------:|\n")
    for _, row in miss_df.iterrows():
        flag = " ⚠️" if row["Percent"] > 5 else ""
        results.append(f"| {row['Column']} | {int(row['Missing'])} | {row['Percent']:.1f}%{flag} |")
    results.append(f"\n**Total rows**: {len(sub)} | **Complete cases**: {sub.dropna().shape[0]} ({sub.dropna().shape[0]/len(sub)*100:.1f}%)\n")

    fig_dir = os.path.join(output_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    fig, ax = plt.subplots(figsize=(max(8, len(columns) * 0.5), 6))
    sns.heatmap(sub.isnull().T, cbar=False, yticklabels=True, cmap="YlOrRd", ax=ax)
    ax.set_title("Missing Data Pattern")
    ax.set_xlabel("Observation Index")
    fig_path = os.path.join(fig_dir, "missing_pattern.png")
    fig.savefig(fig_path, bbox_inches="tight")
    plt.close(fig)
    results.append(f"## Missing Pattern Heatmap\n![Missing Pattern]({fig_path})\n")

    report = "\n".join(results)
    with open(os.path.join(output_dir, "missing_diagnosis_report.md"), "w") as f:
        f.write(report)
    return report


ACTION_MAP = {
    "eda": action_eda,
    "ttest": action_ttest,
    "anova": action_anova,
    "chi_square": action_chi_square,
    "correlation": action_correlation,
    "regression": action_regression,
    "mann_whitney": action_mann_whitney,
    "kruskal": action_kruskal,
    "normality": action_normality,
    "ml_evaluate": action_ml_evaluate,
    "pca": action_pca,
    "clustering": action_clustering,
    "survival": action_survival,
    "mixed_effects": action_mixed_effects,
    "shap_explain": action_shap_explain,
    "effect_size": action_effect_size,
    "power_analysis": action_power_analysis,
    "timeseries": action_timeseries,
    "causal_psm": action_causal_psm,
    "causal_did": action_causal_did,
    "mediation": action_mediation,
    "moderation": action_moderation,
    "multicollinearity": action_multicollinearity,
    "robustness": action_robustness,
    "missing_diagnosis": action_missing_diagnosis,
}


def main():
    parser = argparse.ArgumentParser(description="Statistical Analysis for Academic Research")
    parser.add_argument("--files", nargs="+", required=True, help="Data file paths")
    parser.add_argument("--action", required=True, choices=list(ACTION_MAP.keys()), help="Analysis action")
    parser.add_argument("--params", default="{}", help="JSON parameters for the action")
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

---
name: statistical-analysis
description: Use this skill when the user needs to perform statistical analysis beyond basic SQL queries. Covers hypothesis testing (t-test, ANOVA, chi-square, Mann-Whitney), regression modeling (linear, logistic, mixed effects), exploratory data analysis (EDA), correlation analysis, survival analysis, Bayesian analysis, machine learning model evaluation (cross-validation, ROC/AUC, SHAP), and academic-grade visualization (matplotlib/seaborn). Trigger on queries like "run a t-test", "regression analysis", "statistical significance", "EDA", "model evaluation", "ANOVA", or any request requiring inferential statistics, advanced modeling, or publication-quality figures.
---

# Statistical Analysis Skill

## Overview

This skill extends the basic `data-analysis` skill (DuckDB/SQL) with comprehensive statistical analysis capabilities. It uses Python's scientific computing stack (NumPy, SciPy, Pandas, Scikit-learn, Statsmodels) to perform hypothesis testing, regression modeling, machine learning evaluation, and academic-grade visualization.

## When to Use This Skill

**Always load this skill when:**

- User needs hypothesis testing (t-test, ANOVA, chi-square, etc.)
- User needs regression analysis (linear, logistic, mixed effects)
- User wants exploratory data analysis (EDA) with visualizations
- User needs machine learning model evaluation (ROC/AUC, cross-validation)
- User needs publication-quality statistical figures
- User asks about statistical significance, effect sizes, or confidence intervals
- User needs correlation analysis, factor analysis, or PCA

**Use `data-analysis` skill instead when:**
- User only needs SQL queries, basic aggregation, or data export
- No statistical inference or modeling is required

## Core Capabilities

| Category | Methods |
|---------|---------|
| **Descriptive Statistics** | Mean, median, mode, std, skewness, kurtosis, percentiles |
| **Hypothesis Testing** | t-test (one/two/paired), ANOVA (one-way/two-way), chi-square, Mann-Whitney U, Wilcoxon, Kruskal-Wallis, Fisher's exact |
| **Correlation** | Pearson, Spearman, Kendall, partial correlation, correlation matrix |
| **Regression** | Linear, multiple, polynomial, logistic, ordinal, Poisson, ridge, lasso |
| **Advanced Modeling** | Mixed effects, survival analysis (Kaplan-Meier, Cox), SEM, time series |
| **ML Evaluation** | Cross-validation, ROC/AUC, precision-recall, confusion matrix, SHAP |
| **Effect Size** | Cohen's d, eta-squared, Cramér's V, odds ratio |
| **Visualization** | Distribution plots, correlation heatmaps, regression plots, forest plots |
| **Multiple Comparisons** | Bonferroni, Holm, Benjamini-Hochberg (FDR), Tukey HSD |

## Workflow

### Step 1: Understand the Analysis Request

Identify:
- **Data source**: Uploaded file path or inline data
- **Research question**: What the user wants to learn from the data
- **Variables**: Independent variables (IVs), dependent variables (DVs), covariates
- **Analysis type**: Descriptive, inferential, predictive, or exploratory
- **Output needs**: Tables, figures, APA-format reports

### Step 1.5: Analytical Thinking Framework

Before running ANY test, design the right analysis strategy based on the research question:

**Research Question → Method Selection**:

| DV Type | IV Type | Design | Recommended Test |
|---------|---------|--------|-----------------|
| Continuous | Categorical (2 groups) | Independent | Independent t-test (or Mann-Whitney if non-normal) |
| Continuous | Categorical (2 groups) | Paired | Paired t-test (or Wilcoxon if non-normal) |
| Continuous | Categorical (3+ groups) | Independent | One-way ANOVA (or Kruskal-Wallis) |
| Continuous | Continuous | — | Pearson/Spearman correlation → Linear regression |
| Continuous | Mixed | — | Multiple regression / ANCOVA |
| Categorical | Categorical | — | Chi-square / Fisher's exact |
| Count | Categorical/Continuous | — | Poisson / Negative binomial regression |
| Binary | Categorical/Continuous | — | Logistic regression |
| Time-to-event | Categorical/Continuous | — | Kaplan-Meier / Cox PH |
| Continuous | Continuous (time) | Repeated measures | Mixed effects / GEE |

**Analysis Design Checklist** (complete BEFORE running any test):
1. What is the specific research question?
2. What is the DV? What type? (continuous/categorical/count/time-to-event)
3. What are the IVs? What types?
4. Are there confounders to control?
5. Is the data independent, paired, or clustered?
6. What is the sample size? Sufficient? (run `power_analysis` if uncertain)
7. What assumptions does the planned test require?

### Step 1.7: Data Quality Audit

Before ANY analysis, run a systematic data quality assessment across 7 dimensions:

| Dimension | What to Check | Red Flags |
|-----------|--------------|-----------|
| **Completeness** | % missing per column, missing patterns | >5% missing in key variable |
| **Validity** | Value ranges, impossible values | Age < 0, Percentage > 100 |
| **Uniqueness** | Duplicate rows, duplicate IDs | Unexpected duplicates |
| **Consistency** | Same entity, different values across columns | Contradictory records |
| **Accuracy** | Outliers (IQR/Z-score), data entry errors | Values >3 SD from mean |
| **Timeliness** | Date ranges, temporal gaps | Missing time periods |
| **Distribution** | Skewness, kurtosis, multimodality | Extreme skew > |2| |

**Missing Data Strategy**:
- **MCAR** (Missing Completely At Random): Listwise deletion acceptable if <5%
- **MAR** (Missing At Random): Multiple imputation (MICE) recommended
- **MNAR** (Missing Not At Random): Sensitivity analysis required; consider selection models

Run EDA with missing data focus:
```bash
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/data.csv \
  --action eda \
  --output-dir /mnt/user-data/outputs
```
Review the missing value analysis and outlier detection output before proceeding.

### Step 2: Install Dependencies (if needed)

```bash
pip install numpy pandas scipy scikit-learn statsmodels matplotlib seaborn pingouin
```

### Step 2.5: Assumption Diagnostics

Before running any parametric test, systematically verify its assumptions:

**Normality** → Shapiro-Wilk (n<50) or K-S test (n≥50) + Q-Q plot
- Normal ✓ → proceed
- Non-normal ✗ → transform (log/sqrt/Box-Cox), use non-parametric alternative, or invoke CLT if n>30

**Homogeneity of Variance** → Levene's test + residual plots
- Homogeneous ✓ → proceed
- Heterogeneous ✗ → Welch's t-test / Welch's ANOVA / robust standard errors

**Independence** → Study design check + Durbin-Watson (for regression)
- Independent ✓ → proceed
- Non-independent ✗ → mixed effects / GEE / clustered SE

**Linearity & Multicollinearity** (for regression) → residual vs. fitted plot + VIF values
- VIF > 5 → remove collinear predictors or use regularization (ridge/lasso)

**Rule**: Always report assumption check results alongside the main analysis. If assumptions are violated, report BOTH parametric and non-parametric results for transparency.

### Step 3: Perform Analysis

Use the analysis script:

```bash
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/data.csv \
  --action [ACTION] \
  --params '[JSON_PARAMS]' \
  --output-dir /mnt/user-data/outputs
```

**Available Actions:**

| Action | Description | Key Parameters |
|--------|-------------|----------------|
| `eda` | Exploratory Data Analysis | `columns` (optional) |
| `ttest` | t-test (one/two/paired) | `group_col`, `value_col`, `test_type`, `alternative` |
| `anova` | One-way / Two-way ANOVA | `group_col`, `value_col`, `factors` (for two-way) |
| `chi_square` | Chi-square test | `col1`, `col2` |
| `correlation` | Correlation matrix | `columns`, `method` (pearson/spearman/kendall) |
| `regression` | Linear/Logistic regression | `x_cols`, `y_col`, `model_type` |
| `mann_whitney` | Mann-Whitney U test | `group_col`, `value_col` |
| `kruskal` | Kruskal-Wallis test | `group_col`, `value_col` |
| `survival` | Kaplan-Meier / Cox PH | `time_col`, `event_col`, `group_col` |
| `pca` | Principal Component Analysis | `columns`, `n_components` |
| `clustering` | K-Means / Hierarchical | `columns`, `n_clusters`, `method` |
| `ml_evaluate` | ML model evaluation | `x_cols`, `y_col`, `model_type`, `cv_folds` |
| `kruskal` | Kruskal-Wallis H test | `group_col`, `value_col` |
| `clustering` | K-Means / Hierarchical clustering | `columns`, `n_clusters`, `method` |
| `survival` | Kaplan-Meier / Log-rank test | `time_col`, `event_col`, `group_col` |
| `mixed_effects` | Linear mixed effects model | `formula`, `groups`, `re_formula` |
| `shap_explain` | SHAP feature explainability | `x_cols`, `y_col`, `model_type`, `task` |
| `effect_size` | Effect size calculation | `group_col`, `value_col`, `measure` |
| `normality` | Normality tests | `columns` |
| `power_analysis` | Statistical power analysis | `effect_size`, `alpha`, `power`, `n_groups` |

**Advanced Actions** (use bash inline scripts if not in the Python script):

| Action | Description | Key Parameters |
|--------|-------------|----------------|
| `timeseries` | Time series (ADF, ARIMA, decomposition, forecast) | `date_col`, `value_col`, `freq`, `forecast_periods` |
| `causal_psm` | Propensity Score Matching | `treatment_col`, `outcome_col`, `covariates` |
| `causal_did` | Difference-in-Differences | `group_col`, `time_col`, `outcome_col`, `post_period` |
| `mediation` | Mediation analysis (Baron & Kenny + Sobel) | `x_col`, `m_col`, `y_col` |
| `moderation` | Moderation / interaction effects | `x_col`, `mod_col`, `y_col` |
| `multicollinearity` | VIF analysis + condition number | `x_cols` |
| `robustness` | Multi-specification robustness check | `x_cols_list`, `y_col`, `model_types` |
| `missing_diagnosis` | MCAR/MAR analysis + missing pattern heatmap | `columns` |

### Step 4: Interpret Results (4-Layer Framework)

For every statistical result, provide a 4-layer interpretation:

| Layer | Question | What to Report |
|:-----:|----------|---------------|
| 1 | **Statistical significance** | Test statistic + p-value: "The difference was significant (p = .003)" |
| 2 | **Effect size & practical significance** | Effect size + meaning: "Medium effect (d = 0.65), ~12% improvement" |
| 3 | **Confidence & precision** | CI: "95% CI [0.32, 0.98] excludes zero → reliable effect" |
| 4 | **Substantive meaning** | Plain language: "The intervention reduces dropout by ~1 in 8 students" |

**Rules**:
- NEVER report only p-values — always include effect sizes and CIs
- For non-significant results: distinguish "no effect" from "insufficient power"
- For large samples (n > 10,000): focus on effect size — statistical significance is nearly guaranteed
- Always generate APA-format reporting string

### Step 4.5: Sensitivity & Robustness Analysis

Top-tier journals require demonstrating that results are NOT artifacts of specific choices. Run at least 2 of these:

| Type | Description | Reporting Pattern |
|------|-------------|------------------|
| **Alternative specifications** | Same analysis with different models (OLS vs. robust SE vs. mixed) | "Results robust to alternative specifications (Table S1)" |
| **Subsample analysis** | Re-run on subsamples (by group, excluding outliers) | "Effect holds across all subgroups (Table S2)" |
| **Alternative measures** | Different operationalizations of the same construct | "Consistent across alternative measures" |
| **Winsorization** | Trim extremes at 1%/99% and re-run | "After winsorizing, results remain significant" |
| **Imputation comparison** | Listwise deletion vs. multiple imputation | "Imputation did not materially change estimates" |
| **Placebo/falsification** | Test a deliberately false hypothesis | "Placebo tests confirm effect is not spurious" |

## Detailed Usage Examples

### Exploratory Data Analysis (EDA)

```bash
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/data.csv \
  --action eda \
  --output-dir /mnt/user-data/outputs
```

Output:
- Summary statistics table
- Distribution plots for numeric columns
- Correlation heatmap
- Missing value analysis
- Outlier detection (IQR method)

### Hypothesis Testing: Independent t-test

```bash
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/experiment.csv \
  --action ttest \
  --params '{"group_col": "treatment", "value_col": "score", "test_type": "independent", "alternative": "two-sided"}' \
  --output-dir /mnt/user-data/outputs
```

Output:
```
=== Independent Samples t-test ===
t-statistic: 3.45
p-value: 0.0012
Cohen's d: 0.78 (medium-large effect)
95% CI for mean difference: [1.23, 4.56]
Group means: Control=12.3 (SD=3.1), Treatment=15.8 (SD=3.4)

Assumption Checks:
  Normality (Shapiro-Wilk): Control p=0.34 ✓, Treatment p=0.21 ✓
  Homogeneity of variance (Levene's): p=0.56 ✓

APA Report:
  An independent-samples t-test revealed a statistically significant 
  difference between the treatment group (M=15.8, SD=3.4) and the 
  control group (M=12.3, SD=3.1), t(58)=3.45, p=.001, d=0.78.
```

### One-Way ANOVA

```bash
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/data.csv \
  --action anova \
  --params '{"group_col": "group", "value_col": "performance", "post_hoc": "tukey"}' \
  --output-dir /mnt/user-data/outputs
```

### Linear Regression

```bash
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/data.csv \
  --action regression \
  --params '{"x_cols": ["age", "education", "experience"], "y_col": "salary", "model_type": "ols"}' \
  --output-dir /mnt/user-data/outputs
```

### Chi-Square Test

```bash
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/survey.csv \
  --action chi_square \
  --params '{"col1": "gender", "col2": "preference"}' \
  --output-dir /mnt/user-data/outputs
```

### Correlation Matrix with Heatmap

```bash
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/data.csv \
  --action correlation \
  --params '{"columns": ["var1", "var2", "var3", "var4"], "method": "pearson"}' \
  --output-dir /mnt/user-data/outputs
```

### ML Model Evaluation

```bash
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/data.csv \
  --action ml_evaluate \
  --params '{"x_cols": ["feature1", "feature2", "feature3"], "y_col": "target", "model_type": "random_forest", "cv_folds": 5, "task": "classification"}' \
  --output-dir /mnt/user-data/outputs
```

Output:
- Cross-validation scores (accuracy, precision, recall, F1)
- ROC curve and AUC
- Confusion matrix
- Feature importance (SHAP values if available)

### PCA (Dimensionality Reduction)

```bash
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/data.csv \
  --action pca \
  --params '{"columns": ["var1", "var2", "var3", "var4", "var5"], "n_components": 3}' \
  --output-dir /mnt/user-data/outputs
```

### Power Analysis

```bash
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/data.csv \
  --action power_analysis \
  --params '{"effect_size": 0.5, "alpha": 0.05, "power": 0.8, "test_type": "ttest_ind"}' \
  --output-dir /mnt/user-data/outputs
```

## Visualization Styles

All figures are generated in publication-quality format:

**Academic Style Defaults:**
- Font: serif (Times New Roman style) for publication
- DPI: 300 (suitable for journal submission)
- Color palette: colorblind-friendly (seaborn "colorblind" or "Set2")
- Figure format: PNG (default) and SVG/PDF (for LaTeX)
- Axes: labeled with units, tick marks outside
- Legend: placed to avoid data occlusion

**Available Figure Types:**
| Figure | Generated By |
|--------|-------------|
| Distribution plots (histogram + KDE) | `eda` |
| Box plots / Violin plots | `ttest`, `anova` |
| Correlation heatmap | `correlation` |
| Scatter + regression line | `regression` |
| Residual plots | `regression` |
| Q-Q plots | `normality` |
| ROC curves | `ml_evaluate` |
| Confusion matrix | `ml_evaluate` |
| Feature importance (bar) | `ml_evaluate` |
| Kaplan-Meier curves | `survival` |
| PCA scree plot + biplot | `pca` |
| Dendrogram | `clustering` |

### Visualization Narrative Strategy

Top-tier figures don't display data — they tell a story. Design your figure sequence as a visual narrative:

**The 4-Figure Narrative Arc** (for a typical research paper):

| Figure # | Narrative Role | Best Chart Type |
|:--------:|---------------|----------------|
| Fig. 1 | **Context + Framework** | Conceptual diagram / study design schematic |
| Fig. 2 | **Main Finding** | Bar chart with significance brackets, line chart with CI bands |
| Fig. 3 | **Mechanism / Why** | Heatmap, interaction plot, mediation diagram |
| Fig. 4 | **Robustness / Depth** | Ablation results, subgroup analysis, sensitivity checks |

**Chart Selection by Insight Type**:

| Insight | Best Chart | Avoid |
|---------|-----------|-------|
| "X > Y" | Bar chart + error bars + significance brackets | Pie chart |
| "X increases with Y" | Scatter + regression line + CI band | Bar chart |
| "Trend over time" | Line chart + shaded CI | Bar chart per time point |
| "Distribution shape" | Violin / Raincloud plot | Histogram alone |
| "Part-to-whole" | Stacked bar (absolute) or 100% stacked | 3D pie |
| "Many-variable comparison" | Heatmap + hierarchical clustering | Table of numbers |
| "Model performance" | ROC curve / Residual plot | Single accuracy number |
| "Group patterns" | Small multiples (faceted plots) | One cluttered plot |

**Anti-patterns**: No 3D charts (distort perception). No dual y-axes (use facets). No rainbow colormaps (perceptually non-uniform). No truncated y-axis without indication.

**Publication standards**: 300+ DPI, axis labels ≥ 8pt in print, max 7 colors with colorblind-safe palette, SVG/PDF for vector, annotate significance directly on plots (* p<.05, ** p<.01, *** p<.001), always show uncertainty (CI/error bars).

## APA-Format Reporting

Each test automatically generates an APA-format text report:

**t-test:**
> An independent-samples t-test revealed a statistically significant difference, t(df) = X.XX, p = .XXX, d = X.XX.

**ANOVA:**
> A one-way ANOVA revealed a significant effect of [IV] on [DV], F(df1, df2) = X.XX, p = .XXX, η² = X.XX.

**Chi-square:**
> A chi-square test of independence showed a significant association, χ²(df) = X.XX, p = .XXX, Cramér's V = X.XX.

**Regression:**
> The regression model was statistically significant, F(df1, df2) = X.XX, p < .001, R² = .XX.

**Correlation:**
> There was a significant positive/negative correlation, r(N) = .XX, p = .XXX.

## Integration with Other Skills

- **data-analysis**: Use for initial data exploration (SQL), then this skill for statistical inference
- **chart-visualization**: Use for specialized chart types (Sankey, treemap, etc.) beyond statistical plots
- **academic-writing**: Pass APA-format reports directly into manuscript sections
- **consulting-analysis**: Use statistical results to support consulting-grade analysis

## Output Files

All outputs are saved to `/mnt/user-data/outputs/`:
- `statistical_report.md` — Full analysis report with tables and APA text
- `figures/` — All generated plots (PNG + SVG)
- `results.json` — Machine-readable results for downstream use

Use `present_files` to share outputs with the user.

## Advanced Methods

### Causal Inference

When the user asks about causation (not just association), recommend appropriate causal methods:

| Method | When to Use | Key Requirement |
|--------|------------|----------------|
| **Propensity Score Matching (PSM)** | Observational data, selection bias | Many covariates available |
| **Difference-in-Differences (DiD)** | Before/after with treatment/control | Parallel trends assumption |
| **Instrumental Variables (IV)** | Endogeneity / omitted variable bias | Valid instrument |
| **Regression Discontinuity (RDD)** | Treatment assigned by threshold | Sharp or fuzzy cutoff |
| **Interrupted Time Series (ITS)** | Policy intervention effects | Sufficient pre/post observations |

Always: state causal assumptions explicitly, test assumption validity, report sensitivity to violations, distinguish "causal effect" from "association" in language.

### Time Series Analysis

| Step | Action | Tools |
|------|--------|-------|
| 1 | Visualize + decompose (trend + seasonal + residual) | `statsmodels.tsa.seasonal_decompose` |
| 2 | Stationarity test (ADF + KPSS) | `statsmodels.tsa.stattools` |
| 3 | If non-stationary → differencing | `pandas.diff()` |
| 4 | ACF/PACF → identify AR(p), MA(q) orders | `statsmodels.tsa.stattools` |
| 5 | Fit ARIMA(p,d,q) / SARIMA / Prophet | `statsmodels.tsa.arima` |
| 6 | Residual diagnostics (Ljung-Box test) | `statsmodels.stats.diagnostic` |
| 7 | Forecast with confidence intervals | `model.forecast()` |
| 8 | Granger causality (if multiple series) | `grangercausalitytests` |

### Feature Engineering

| Technique | When to Use | Example |
|-----------|------------|---------|
| Binning | Continuous → categorical for subgroup analysis | Age → age groups |
| Interaction terms | Synergistic effects between variables | X₁ × X₂ |
| Log/sqrt transform | Right-skewed distributions | log(income) |
| Standardization | Variables on different scales | Z-score: (x-μ)/σ |
| Lag features | Temporal dependencies | Yₜ₋₁, Yₜ₋₂ |
| Rolling statistics | Smoothing noisy time series | 7-day moving average |
| Ratio/proportion | Normalize by a denominator | Revenue per employee |
| Domain-specific | Field-specific transformations | BMI, TF-IDF |

### Analysis Reproducibility Documentation

After completing any analysis, generate a reproducibility report including:

```markdown
## Analysis Reproducibility Report
- **Environment**: Python X.X, pandas==X.X, scipy==X.X, statsmodels==X.X
- **Data**: Source, rows (raw → cleaned), columns, missing data handling, outlier treatment
- **Pipeline**: Data loading → Quality audit → Missing data → Assumptions → Primary analysis → Sensitivity
- **Key Decisions**: [Decision] → [Justification] (e.g., "Used Mann-Whitney: normality violated, Shapiro-Wilk p=0.003")
- **Random Seeds**: All random processes used seed = 42
```

Save to `/mnt/user-data/outputs/reproducibility_report.md` and present with `present_files`.

## Notes

- Always check assumptions before running parametric tests (normality, homoscedasticity)
- If assumptions are violated, suggest non-parametric alternatives
- Report effect sizes alongside p-values (p-values alone are insufficient)
- For multiple comparisons, always apply correction (Bonferroni or FDR)
- Use 95% confidence intervals for all estimates
- For large datasets (>10,000 rows), statistical significance is almost guaranteed — focus on effect sizes
- When the user doesn't specify a significance level, use α = 0.05

# DeerFlow 数据分析能力大师级强化提示词

---

## 你的角色

你是一位融合以下三重身份的顶级数据科学方法论架构师：

1. **Nature/Science 统计审稿人**：精通审稿中最常见的统计问题——p-hacking、多重比较未校正、因果混淆、过拟合、样本量不足。你知道顶级期刊对数据分析的标准远超"跑了正确的检验"。
2. **Tukey-Box-Cox 级别的 EDA 大师**：深信"让数据说话"——在任何假设检验之前，必须通过系统化的探索性分析充分理解数据的分布、结构、异常和关系。
3. **Tufte 级别的可视化哲学家**：理解可视化不是"展示数据"而是"讲述发现"——每张图都应该揭示一个洞见，而非仅仅渲染数据点。

---

## 项目当前状态精准诊断

### 现有能力矩阵（三大技能）

| 技能 | 行数 | 核心能力 | 能力深度 |
|------|:----:|---------|:-------:|
| `data-analysis` | 218 | DuckDB/SQL 查询、schema 检查、统计摘要、CSV/Excel/JSON 导出 | ⭐⭐⭐ |
| `statistical-analysis` | 299 + 1031行脚本 | 17 种统计动作、APA 报告、学术可视化（matplotlib/seaborn 300DPI） | ⭐⭐⭐⭐ |
| `chart-visualization` | 64 + 26 个参考 | 26 种图表类型（Node.js AntV 引擎）、时间序列/比较/占比/关系/地图/层级 | ⭐⭐⭐⭐ |

### 精确差距分析：从"能用"到"顶级教授水平"

| # | 缺失维度 | 影响 | 当前状态 | 顶级水平要求 |
|---|---------|:---:|---------|------------|
| 1 | **分析思维框架** | 致命 | 零 — 只有"跑检验"，没有"怎么思考" | 基于研究问题设计分析策略，而非盲目选检验 |
| 2 | **数据质量评估** | 致命 | EDA 中有基础缺失值检测 | 系统化 7 维数据质量审计 |
| 3 | **假设诊断流程** | 高 | 提及"检查假设"但无流程 | 每个检验前的系统化假设检验决策树 |
| 4 | **缺失数据策略** | 高 | 零 | MCAR/MAR/MNAR 诊断 + 多重填补 |
| 5 | **因果推断方法** | 高 | 零 | DiD, PSM, IV, RDD 等准实验方法 |
| 6 | **时间序列分析** | 高 | 零 | 平稳性检验、ARIMA、季节性分解、Granger 因果 |
| 7 | **特征工程** | 中 | 零 | 从原始数据创造有意义的特征 |
| 8 | **模型选择决策树** | 中 | 零 — 用户自己选方法 | 根据数据类型/研究问题/假设自动推荐方法 |
| 9 | **敏感性分析** | 高 | 零 | 多规范/多子样本/多模型验证结果稳健性 |
| 10 | **可视化叙事** | 中 | 图表类型丰富但无"讲故事"策略 | 用可视化构建数据叙事弧线 |
| 11 | **分析可复现性** | 中 | 零 | 完整的分析流水线文档 |
| 12 | **三技能协同编排** | 高 | Lead Agent 有路由规则但无深度编排 | data-analysis → statistical-analysis → chart-visualization 的流水线编排 |

---

## 实施方案：12 项数据分析大师级能力注入

### ===== 能力 1：分析思维框架 =====

**实施位置**：在 `statistical-analysis/SKILL.md` 的 Workflow Step 1 后新增

```markdown
### Step 1.5: Analytical Thinking Framework

Before running ANY test, apply this decision framework to design the right analysis strategy:

**The Research Question → Analysis Strategy Mapping**:

| Research Question Type | Examples | Recommended Approach |
|----------------------|---------|---------------------|
| **Association** | "Is X related to Y?" | Correlation → Regression |
| **Difference** | "Do groups differ on Y?" | t-test / ANOVA / non-parametric |
| **Prediction** | "Can we predict Y from X₁...Xₙ?" | Regression / ML models |
| **Structure** | "What latent patterns exist?" | PCA / Factor Analysis / Clustering |
| **Causation** | "Does X cause Y?" | Experimental design / Causal inference (DiD, PSM, IV) |
| **Change over time** | "How does Y evolve?" | Time series / Longitudinal / Growth models |
| **Survival** | "How long until event?" | Kaplan-Meier / Cox regression |

**The Analysis Design Checklist** (complete BEFORE running any test):
1. What is the specific research question?
2. What is the dependent variable (DV)? What type is it? (continuous/categorical/count/time-to-event)
3. What are the independent variables (IVs)? What types?
4. Are there confounders that must be controlled?
5. Is the data independent, paired, or clustered?
6. What is the sample size? Is it sufficient? (run power analysis if uncertain)
7. What assumptions does the planned test require? (normality, homoscedasticity, independence, linearity)

**Automatic Method Recommendation**: Based on the answers above, recommend the optimal method:

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
```

### ===== 能力 2：系统化数据质量审计 =====

**实施位置**：在 `statistical-analysis/SKILL.md` 的 EDA 部分扩展

```markdown
### Step 1.7: Data Quality Audit (7 Dimensions)

Before ANY analysis, run a systematic data quality assessment:

| Dimension | What to Check | Red Flags |
|-----------|--------------|-----------|
| **Completeness** | % missing per column, missing patterns (MCAR/MAR/MNAR) | >5% missing in key variable |
| **Validity** | Value ranges, impossible values, logical constraints | Age < 0, Percentage > 100 |
| **Uniqueness** | Duplicate rows, duplicate IDs | Unexpected duplicates |
| **Consistency** | Same entity, different values across columns/tables | Contradictory records |
| **Accuracy** | Outliers (IQR/Z-score), data entry errors | Values >3 SD from mean |
| **Timeliness** | Date ranges, temporal gaps, stale data | Missing periods |
| **Distribution** | Skewness, kurtosis, multimodality, zero-inflation | Extreme skew > |2| |

**Missing Data Strategy**:

| Pattern | Diagnosis Test | Strategy |
|---------|---------------|----------|
| MCAR (Missing Completely At Random) | Little's MCAR test | Listwise deletion acceptable if <5% |
| MAR (Missing At Random) | Compare missingness patterns across groups | Multiple imputation (MICE) recommended |
| MNAR (Missing Not At Random) | Domain knowledge + sensitivity analysis | Sensitivity analysis required; consider Heckman model |

```bash
# Missing data analysis
python /mnt/skills/public/statistical-analysis/scripts/statistical_analysis.py \
  --files /mnt/user-data/uploads/data.csv \
  --action eda \
  --params '{"focus": "missing_data"}' \
  --output-dir /mnt/user-data/outputs
```

Report: missing % per column, missing patterns heatmap, Little's MCAR test if applicable.
```

### ===== 能力 3：假设诊断决策树 =====

```markdown
### Step 2.5: Assumption Diagnostics Workflow

Before running any parametric test, systematically check its assumptions:

**Assumption Check Flow for Parametric Tests**:

```
Step 1: Normality
  ├─ Shapiro-Wilk test (n < 50) or K-S test (n ≥ 50)
  ├─ Q-Q plot visual inspection
  ├─ Skewness & Kurtosis values
  │
  ├─ Normal ✓ → proceed to Step 2
  └─ Non-normal ✗ → Options:
       ├─ Transform (log, sqrt, Box-Cox)
       ├─ Use non-parametric alternative
       └─ If n > 30, invoke CLT (state this explicitly)

Step 2: Homogeneity of Variance
  ├─ Levene's test
  ├─ Residual plots
  │
  ├─ Homogeneous ✓ → proceed
  └─ Heterogeneous ✗ → Use Welch's t-test / Welch's ANOVA / robust SE

Step 3: Independence
  ├─ Study design check (between vs. within subjects)
  ├─ Durbin-Watson test (for regression residuals)
  │
  ├─ Independent ✓ → proceed
  └─ Non-independent ✗ → Use mixed effects / GEE / clustered SE

Step 4 (for regression): Linearity & Multicollinearity
  ├─ Residual vs. fitted plot (linearity)
  ├─ VIF values (multicollinearity, threshold VIF > 5)
  │
  ├─ OK ✓ → proceed
  └─ Violated ✗ → Transform, remove collinear predictors, or use regularization
```

**Rule**: Always report assumption check results alongside the main analysis. If assumptions are violated, report BOTH the parametric and non-parametric results.
```

### ===== 能力 4：因果推断方法库 =====

```markdown
### Advanced: Causal Inference Methods

When the user asks about causation (not just association), recommend and implement appropriate causal methods:

| Method | When to Use | Key Requirement | Implementation |
|--------|------------|----------------|----------------|
| **Propensity Score Matching (PSM)** | Observational data with treatment/control | Many covariates, selection bias | `sklearn` + `statsmodels` |
| **Difference-in-Differences (DiD)** | Before/after with treatment/control group | Parallel trends assumption | OLS with interaction term |
| **Instrumental Variables (IV)** | Endogeneity / omitted variable bias | Valid instrument (relevance + exclusion) | `linearmodels.iv` |
| **Regression Discontinuity (RDD)** | Treatment assigned by threshold on running variable | Sharp or fuzzy cutoff | Local polynomial regression |
| **Interrupted Time Series (ITS)** | Policy intervention effects over time | Sufficient pre/post observations | Segmented regression |

**Causal inference reporting requirements**:
- State causal assumptions explicitly
- Test assumption validity where possible (e.g., parallel trends test for DiD, balance check for PSM)
- Report sensitivity to assumption violations (Rosenbaum bounds for PSM)
- Distinguish "causal effect" from "association" in language
```

### ===== 能力 5：时间序列分析 =====

```markdown
### Advanced: Time Series Analysis

| Step | Action | Tools |
|------|--------|-------|
| 1. Visualization | Plot raw series, decompose (trend + seasonal + residual) | `statsmodels.tsa.seasonal_decompose` |
| 2. Stationarity | ADF test + KPSS test | `statsmodels.tsa.stattools` |
| 3. Differencing | If non-stationary, apply d-th order differencing | `pandas.diff()` |
| 4. ACF/PACF | Identify AR(p) and MA(q) orders | `statsmodels.tsa.stattools` |
| 5. Model fitting | ARIMA(p,d,q) / SARIMA / Prophet | `statsmodels.tsa.arima` |
| 6. Diagnostics | Ljung-Box test on residuals, residual ACF | `statsmodels.stats.diagnostic` |
| 7. Forecasting | Out-of-sample prediction with confidence intervals | `model.forecast()` |
| 8. Granger causality | Test if X Granger-causes Y | `statsmodels.tsa.stattools.grangercausalitytests` |
```

### ===== 能力 6：敏感性与稳健性分析 =====

```markdown
### Step 4.5: Sensitivity & Robustness Analysis

Top-tier journals require demonstrating that results are NOT artifacts of specific analytical choices. Run at least 3 of these:

| Type | Description | How to Report |
|------|-------------|--------------|
| **Alternative model specifications** | Run the same analysis with different models (OLS vs. robust SE vs. mixed effects) | "Results are robust to alternative specifications (Table S1)" |
| **Subsample analysis** | Re-run on subsamples (by gender, by time period, excluding outliers) | "The effect holds across all subgroups (Table S2)" |
| **Alternative variable operationalizations** | Use different measures of the same construct | "Results are consistent across alternative measures" |
| **Winsorization / trimming** | Trim extreme values at 1%/99% and re-run | "After winsorizing at the 1st/99th percentile, results remain significant" |
| **Multiple imputation comparison** | Compare results with listwise deletion vs. MICE imputation | "Imputation did not materially change the estimates" |
| **Placebo / falsification tests** | Test a deliberately false hypothesis that should NOT be significant | "Placebo tests confirm the effect is not spurious" |

**Report**: Compile all robustness checks into a Supplementary Table with consistent formatting.
```

### ===== 能力 7：可视化叙事策略 =====

**实施位置**：在 `statistical-analysis/SKILL.md` 的可视化部分扩展 + `chart-visualization` SKILL.md 增强

```markdown
### Visualization Narrative Strategy

Top-tier figures don't just display data — they tell a story. Design your figure sequence as a visual narrative:

**The 4-Figure Narrative Arc** (for a typical research paper):

| Figure # | Narrative Role | Chart Type | Example |
|:--------:|---------------|-----------|---------|
| Fig. 1 | **Context + Framework** | Conceptual diagram / study design | "Here's the problem and our approach" |
| Fig. 2 | **Main Finding** | The one plot that captures your core result | Bar chart with significance brackets, line chart with CI bands |
| Fig. 3 | **Mechanism / Why** | Plot that explains the underlying mechanism | Heatmap, interaction plot, mediation diagram |
| Fig. 4 | **Robustness / Depth** | Supplementary evidence supporting the main finding | Ablation results, subgroup analysis, sensitivity checks |

**Chart Selection by Insight Type**:

| Insight You Want to Show | Best Chart Type | Avoid |
|-------------------------|----------------|-------|
| "X is higher than Y" | Bar chart with error bars + significance brackets | Pie chart |
| "X increases with Y" | Scatter + regression line with CI band | Bar chart |
| "Trend over time" | Line chart with shaded CI | Bar chart per time point |
| "Distribution shape" | Violin plot or Raincloud plot | Histogram (less informative) |
| "Part-to-whole" | Stacked bar (absolute) or 100% stacked bar (proportional) | 3D pie chart |
| "Comparison across many variables" | Heatmap with hierarchical clustering | Table of numbers |
| "Model performance" | ROC curve (classification) / Residual plot (regression) | Single accuracy number |
| "Group-level patterns" | Small multiples (faceted plots) | One cluttered plot |

**Publication Figure Aesthetic Standards**:
- Resolution: 300 DPI minimum (600 DPI for line art)
- Font size: Axis labels ≥ 8pt in final printed size
- Colors: Maximum 7 colors; use colorblind-safe palettes (viridis, cividis, Set2)
- Aspect ratio: Typically 3:2 or 4:3; wide landscape for time series
- White space: Generous margins; avoid visual clutter
- Annotations: Add statistical significance directly on the plot (* p<.05, ** p<.01, *** p<.001)
- Error representation: Always show uncertainty (CI bands, error bars, bootstrapped distributions)
- Export formats: SVG/PDF for vector graphics (LaTeX/Illustrator), PNG for web

**Anti-patterns**:
- ❌ 3D charts (distort perception)
- ❌ Dual y-axes (misleading — use faceted plots instead)
- ❌ Bar charts for continuous distributions (use violin/box/density)
- ❌ Truncated y-axis without clear indication
- ❌ Rainbow color maps (perceptually non-uniform)
```

### ===== 能力 8：特征工程指南 =====

```markdown
### Advanced: Feature Engineering for Research

| Technique | When to Use | Example |
|-----------|------------|---------|
| **Binning** | Continuous → categorical for subgroup analysis | Age → age groups |
| **Interaction terms** | Two variables have synergistic effects | X₁ × X₂ |
| **Polynomial features** | Non-linear relationships | X, X², X³ |
| **Log/sqrt transform** | Right-skewed distributions | log(income), sqrt(count) |
| **Standardization** | Variables on different scales need comparison | Z-score: (x-μ)/σ |
| **Lag features** | Temporal dependencies | Yₜ₋₁, Yₜ₋₂ |
| **Rolling statistics** | Smoothing noisy time series | 7-day moving average |
| **Dummy encoding** | Categorical → numeric for regression | One-hot encoding |
| **Ratio/proportion** | Normalize by a meaningful denominator | Revenue per employee |
| **Domain-specific** | Field-specific transformations | BMI from height+weight, TF-IDF from text |
```

### ===== 能力 9：分析可复现性文档 =====

```markdown
### Analysis Reproducibility Documentation

After completing any analysis, generate a reproducibility report:

```markdown
## Analysis Reproducibility Report

### Environment
- Python version: X.X.X
- Key packages: pandas==X.X, scipy==X.X, statsmodels==X.X, scikit-learn==X.X

### Data
- Source: [file name and description]
- Rows: N (after cleaning: N')
- Columns: K
- Missing data handling: [strategy used]
- Outlier treatment: [strategy used]

### Analysis Pipeline
1. Data loading and inspection
2. Data quality audit (7 dimensions)
3. Missing data diagnosis and handling
4. Assumption checks
5. Primary analysis: [method]
6. Sensitivity analyses: [list]
7. Visualization generation

### Key Decisions and Justifications
| Decision | Justification |
|----------|--------------|
| Used Mann-Whitney instead of t-test | Normality violated (Shapiro-Wilk p = 0.003) |
| Excluded 3 outliers | Beyond 3 SD from mean, confirmed as data entry errors |
| Applied Bonferroni correction | 5 pairwise comparisons |

### Random Seeds
- All random processes used seed = 42
```
```

### ===== 能力 10：三技能协同编排 =====

**实施位置**：在 Lead Agent `<academic_research>` 的跨技能协同部分新增

```markdown
**Data Analysis Pipeline** (multi-skill orchestration):

**Standard Pipeline**: data-analysis → statistical-analysis → chart-visualization
```
Turn 1: Load & Explore
  ├── data-analysis: inspect schema, run summary statistics
  └── data-analysis: SQL queries for initial exploration

Turn 2: Quality & Transform
  ├── statistical-analysis: data quality audit (7 dimensions)
  ├── statistical-analysis: assumption checks
  └── statistical-analysis: handle missing data, outliers, transformations

Turn 3: Analyze (parallel subagents)
  ├── Subagent 1: statistical-analysis → primary hypothesis tests
  ├── Subagent 2: statistical-analysis → sensitivity/robustness checks
  └── Subagent 3: statistical-analysis → exploratory/secondary analyses

Turn 4: Visualize & Report
  ├── chart-visualization: publication-quality figures
  ├── statistical-analysis: APA-format results text
  └── Synthesize into coherent analysis report
```
```

### ===== 能力 11：结果解释框架 =====

```markdown
### Results Interpretation Framework

For every statistical result, provide a 4-layer interpretation:

| Layer | Question | Example |
|:-----:|----------|---------|
| 1 | **Statistical significance** | "The difference was statistically significant (p = .003)" |
| 2 | **Effect size & practical significance** | "The effect was medium-sized (d = 0.65), equivalent to a 12% improvement" |
| 3 | **Confidence & precision** | "The 95% CI [0.32, 0.98] does not include zero, suggesting a reliable effect" |
| 4 | **Substantive meaning** | "This means that the intervention reduces dropout rates by approximately 1 in 8 students" |

**Rules**:
- NEVER report only p-values — always include effect sizes and CIs
- For non-significant results, distinguish "no effect" from "insufficient power to detect an effect"
- Use plain language alongside statistical notation: "t(58) = 3.45, p = .001" + "patients in the treatment group improved significantly more"
- For large samples (n > 10,000), focus on effect size — statistical significance is almost guaranteed
```

### ===== 能力 12：高级统计脚本扩展 =====

**实施位置**：在 `statistical-analysis/SKILL.md` 的 Available Actions 表中新增

```markdown
**Additional Actions (Advanced)**:

| Action | Description | Key Parameters |
|--------|-------------|----------------|
| `timeseries` | Time series analysis (ADF, ARIMA, decomposition, forecast) | `date_col`, `value_col`, `freq`, `forecast_periods` |
| `causal_psm` | Propensity Score Matching | `treatment_col`, `outcome_col`, `covariates`, `n_matches` |
| `causal_did` | Difference-in-Differences | `group_col`, `time_col`, `outcome_col`, `post_period` |
| `mediation` | Mediation analysis (Baron & Kenny + Sobel test) | `x_col`, `m_col`, `y_col` |
| `moderation` | Moderation analysis (interaction effects) | `x_col`, `mod_col`, `y_col` |
| `multicollinearity` | VIF analysis + condition number | `x_cols` |
| `robustness` | Multi-specification robustness check | `x_cols_list`, `y_col`, `model_types` |
| `missing_diagnosis` | MCAR/MAR analysis + missing pattern visualization | `columns` |
```
```

---

## 实施位置总表

| # | 能力 | 实施文件 | 位置 | 方式 |
|---|------|---------|------|------|
| 1 | 分析思维框架 | `statistical-analysis/SKILL.md` | Step 1 后 | 新增 Step 1.5 |
| 2 | 数据质量审计 | `statistical-analysis/SKILL.md` | Step 1.5 后 | 新增 Step 1.7 |
| 3 | 假设诊断决策树 | `statistical-analysis/SKILL.md` | Step 2 后 | 新增 Step 2.5 |
| 4 | 因果推断方法库 | `statistical-analysis/SKILL.md` | Notes 前 | 新增 Advanced 区 |
| 5 | 时间序列分析 | `statistical-analysis/SKILL.md` | Notes 前 | 新增 Advanced 区 |
| 6 | 敏感性分析 | `statistical-analysis/SKILL.md` | Step 4 后 | 新增 Step 4.5 |
| 7 | 可视化叙事 | `statistical-analysis/SKILL.md` + `chart-visualization/SKILL.md` | 可视化部分 | 扩展 |
| 8 | 特征工程 | `statistical-analysis/SKILL.md` | Notes 前 | 新增 Advanced 区 |
| 9 | 分析可复现性 | `statistical-analysis/SKILL.md` | Notes 前 | 新增 |
| 10 | 三技能编排 | `prompt.py` `<academic_research>` | 跨技能协同 | 新增路径 |
| 11 | 结果解释框架 | `statistical-analysis/SKILL.md` | Step 4 扩展 | 替换 |
| 12 | 高级统计动作 | `statistical-analysis/SKILL.md` | Actions 表 | 扩展 |

## Lead Agent 提示词配套增强

在 `<academic_research>` 段落中新增第 10 条规则：

```
**10. Master-Level Data Analysis (Always Apply for Data Analysis Tasks)**

When performing data analysis for academic research:
- Design analysis strategy BEFORE running tests: Research Question → DV/IV types → Method selection
- Run systematic data quality audit (completeness, validity, outliers, distributions) before any analysis
- Check ALL statistical assumptions with diagnostic tests; if violated, use robust alternatives
- Report 4-layer interpretation: significance + effect size + CI + substantive meaning
- NEVER report p-values alone — always include effect sizes and confidence intervals
- Run at least 2 sensitivity/robustness checks for every primary finding
- Orchestrate the full pipeline: data-analysis (SQL explore) → statistical-analysis (test) → chart-visualization (publish figures)
- Generate analysis reproducibility documentation for every analysis session
- For causal questions, explicitly state causal assumptions and recommend appropriate causal methods (PSM, DiD, IV, RDD)
- Design visualization as narrative: 4-figure arc (context → main finding → mechanism → robustness)
```

## 约束条件

1. `statistical-analysis/SKILL.md` 总长度控制在 600 行以内（当前 299 行，可用空间 ~300 行）
2. 新增的 Advanced actions（时间序列、因果推断等）在 SKILL.md 中描述调用方式；对应的 Python 实现需要用户在脚本中补充或使用 bash 内联脚本
3. 可视化叙事部分同时增强 `chart-visualization/SKILL.md` 和 `statistical-analysis/SKILL.md`
4. 三技能编排通过 Lead Agent 的子 Agent 模式实现，需要 subagent_enabled = true
5. 所有新增内容以示例驱动，每项能力至少 1 个具体示例

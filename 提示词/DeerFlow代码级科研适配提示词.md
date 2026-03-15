# DeerFlow 代码级科研功能深度适配提示词

---

## 项目代码全景诊断

经过完整梳理项目的所有代码（`prompt.py` 694 行 / `statistical_analysis.py` 1442 行 / `academic_pptx.py` 677 行 / `analyze.py` 565 行 / 11 个中间件 / 28 个技能 SKILL.md），前几轮的全部提示词优化已在**提示词层**（SKILL.md + prompt.py `<academic_research>` 17 条规则）达到了极致。

但提示词层的优化有其天然上限——**提示词能"教"Agent 怎么做，但不能改变 Agent "能"做什么**。以下差距只有通过修改 Python 代码才能弥合：

### 代码层关键差距

| # | 差距 | 影响 | 当前状态 | 需要的代码修改 |
|---|------|:---:|---------|-------------|
| 1 | **statistical_analysis.py 缺少 SKILL.md 中新增的高级动作** | 致命 | SKILL.md 列出了 `timeseries`/`causal_psm`/`causal_did`/`mediation`/`moderation`/`multicollinearity`/`robustness`/`missing_diagnosis` 8 个高级动作，但脚本中无对应实现 | 在 `statistical_analysis.py` 中实现这 8 个动作 |
| 2 | **学术图表缺少统计标注** | 高 | 图表没有显著性标注（`*`/`**`/`***`）、没有误差棒 CI、没有效应量标注 | 在绘图函数中添加统计标注功能 |
| 3 | **PPT 脚本缺少"断言-证据"模板** | 高 | 只支持 content（bullet points）类型，不支持 assertion-evidence（全句标题+视觉证据）类型 | 在 `academic_pptx.py` 中新增 `assertion_evidence` 幻灯片类型 |
| 4 | **数据分析脚本缺少与统计脚本的流水线连接** | 中 | `analyze.py`（DuckDB）和 `statistical_analysis.py`（pandas）完全独立 | 添加 `analyze.py --action export_for_stats` 导出 pandas-ready CSV |
| 5 | **缺少科研专用的数据预处理脚本** | 中 | 无自动化的缺失值处理、异常值检测、数据变换脚本 | 新增 `data_preprocessing.py` 脚本 |
| 6 | **Subagent 超时对科研任务不够友好** | 中 | bash agent 默认 5 分钟，对复杂统计分析/模型训练可能不够 | 在 `config.yaml` 的 subagent 配置中为科研任务建议更长超时 |
| 7 | **记忆系统对科研上下文的事实抽取不够精准** | 中 | `FACT_EXTRACTION_PROMPT` 对科研分类有定义但缺少示例 | 在 `memory/prompt.py` 的 `FACT_EXTRACTION_PROMPT` 中添加科研事实抽取示例 |
| 8 | **Lead Agent 的 description 路由有时不够精确** | 低 | 纯靠 SKILL.md 的 description 文本匹配 | 可通过优化 description 关键词覆盖度来改善（无需改代码逻辑） |

---

## 你的角色

你是一位精通 DeerFlow 架构的**科研工程实施专家**，掌握以下技术栈：
- **LangGraph + LangChain**：Agent 状态机编排、中间件链、工具注册
- **Python 科学计算**：NumPy/SciPy/Pandas/Statsmodels/Scikit-learn/Lifelines/PyMC
- **python-pptx**：PowerPoint 编程式生成
- **DuckDB**：in-process SQL 分析引擎

你的任务：实施代码级修改，使提示词层已设计好的科研能力（17 条规则 + 9 个技能 SKILL.md）在代码执行层真正"落地"。

---

## 实施方案：8 项代码级修改

### ===== 修改 1：statistical_analysis.py 新增 8 个高级统计动作 =====

**文件**：`skills/public/statistical-analysis/scripts/statistical_analysis.py`
**类型**：在 ACTION_MAP 中新增函数

需要实现的 8 个函数：

```python
def action_timeseries(df, params, output_dir):
    """时间序列分析：ADF 检验 + 季节性分解 + ARIMA 拟合 + 预测"""
    # 参数：date_col, value_col, freq, forecast_periods

def action_causal_psm(df, params, output_dir):
    """倾向得分匹配"""
    # 参数：treatment_col, outcome_col, covariates, n_matches

def action_causal_did(df, params, output_dir):
    """双重差分"""
    # 参数：group_col, time_col, outcome_col, post_period

def action_mediation(df, params, output_dir):
    """中介分析（Baron & Kenny + Sobel 检验）"""
    # 参数：x_col, m_col, y_col

def action_moderation(df, params, output_dir):
    """调节效应分析（交互项）"""
    # 参数：x_col, mod_col, y_col

def action_multicollinearity(df, params, output_dir):
    """多重共线性诊断（VIF + 条件数）"""
    # 参数：x_cols

def action_robustness(df, params, output_dir):
    """多规范稳健性检查"""
    # 参数：x_cols_list (list of lists), y_col, model_types

def action_missing_diagnosis(df, params, output_dir):
    """缺失数据诊断 + 模式可视化"""
    # 参数：columns
```

每个函数需要：
1. 参数验证 + 清晰的错误消息
2. 结果输出为 Markdown 报告 + JSON
3. 学术级图表（300 DPI，色盲友好配色）
4. 添加到 `ACTION_MAP` 字典

### ===== 修改 2：统计图表增加学术标注 =====

**文件**：`skills/public/statistical-analysis/scripts/statistical_analysis.py`
**类型**：增强现有绘图函数

在现有的 `action_ttest`、`action_anova` 等函数的图表中添加：
- **显著性括号标注**：在柱状图上方画 bracket + `*`/`**`/`***` 
- **误差棒**：均值 ± SE 或 95% CI
- **效应量注释**：在图表角落标注 Cohen's d 或 η²

新增辅助函数：
```python
def add_significance_bracket(ax, x1, x2, y, p_value):
    """在图表上添加显著性括号和星号标注"""
    
def format_p_stars(p_value):
    """p < .001 → '***', p < .01 → '**', p < .05 → '*', else 'ns'"""
```

### ===== 修改 3：academic_pptx.py 新增断言-证据幻灯片类型 =====

**文件**：`skills/public/academic-ppt/scripts/academic_pptx.py`
**类型**：在幻灯片类型处理中新增 `assertion_evidence`

```python
# JSON 计划中的新类型
{
    "type": "assertion_evidence",
    "assertion": "Our method outperforms all baselines by 4+ points across all metrics",
    "figure_path": "/mnt/user-data/outputs/figures/comparison.png",
    "caption": "Figure 2: Performance comparison on benchmark datasets",
    "notes": "As you can see in this chart..."
}
```

实现要点：
- assertion 作为标题，使用 24-28pt 完整句（而非 topic label）
- figure 居中占据幻灯片 60-70% 面积
- caption 在底部，12-14pt 灰色
- 无 bullet points

### ===== 修改 4：数据分析 → 统计分析流水线连接 =====

**文件**：`skills/public/data-analysis/scripts/analyze.py`
**类型**：新增 `export_for_stats` action

```python
def action_export_for_stats(con, table_map, params, output_file):
    """将 DuckDB 查询结果导出为 pandas-ready CSV，供 statistical_analysis.py 消费"""
    sql = params.get("sql", f"SELECT * FROM {params['table']}")
    result = con.execute(sql).fetchdf()
    export_path = output_file or "/mnt/user-data/workspace/stats_input.csv"
    result.to_csv(export_path, index=False)
    return f"Exported {len(result)} rows to {export_path} for statistical analysis"
```

### ===== 修改 5：新增数据预处理脚本 =====

**文件**：`skills/public/statistical-analysis/scripts/data_preprocessing.py`（新建）
**类型**：全新脚本

功能：
- `--action missing_report`：生成缺失值报告（百分比 + 模式可视化）
- `--action impute`：多重填补（MICE）或简单填补（均值/中位数/众数）
- `--action outlier_detect`：IQR + Z-score + Isolation Forest 异常值检测
- `--action transform`：log/sqrt/Box-Cox/标准化/归一化
- `--action feature_engineer`：分箱/交互项/多项式/滞后特征

CLI：
```bash
python data_preprocessing.py --files <path> --action <action> --params '{}' --output-dir /mnt/user-data/outputs
```

### ===== 修改 6：记忆系统科研事实抽取示例 =====

**文件**：`backend/src/agents/memory/prompt.py`
**类型**：在 `FACT_EXTRACTION_PROMPT` 中添加示例

在 Categories 列表的 `research`/`literature`/`experiment`/`writing_progress` 条目中，各添加 1 个具体抽取示例：

```
- research: ...
  Example: {"content": "User is studying attention mechanisms for mathematical reasoning, targeting NeurIPS 2026", "category": "research", "confidence": 0.9}
- literature: ...
  Example: {"content": "User has read and cited Vaswani et al. 2017 (Attention Is All You Need) as foundational reference", "category": "literature", "confidence": 0.9}
- experiment: ...
  Example: {"content": "User's CalcFormer model achieved 91.3% accuracy on GSM8K with seed=42, using AdamW lr=1e-4", "category": "experiment", "confidence": 0.95}
- writing_progress: ...
  Example: {"content": "User has completed Introduction and Related Work sections of their NeurIPS paper, targeting 8-page format", "category": "writing_progress", "confidence": 0.9}
```

### ===== 修改 7：Subagent 超时建议 =====

**文件**：`config.yaml`（配置建议，不修改代码逻辑）
**类型**：在 `subagents` 部分添加注释建议

```yaml
subagents:
  timeout_seconds: 900  # Default 15 minutes
  agents:
    general-purpose:
      timeout_seconds: 1800  # 30 min for complex multi-step tasks
      # For scientific computing tasks (statistical analysis, model training),
      # consider increasing to 3600 (1 hour) if needed
    bash:
      timeout_seconds: 600  # 10 min for command execution
      # For long-running scripts (statistical_analysis.py with large datasets),
      # consider increasing to 1200 (20 min)
```

### ===== 修改 8：SKILL.md description 关键词优化 =====

**文件**：各科研 SKILL.md 的 YAML frontmatter description
**类型**：增加触发关键词覆盖

对 9 个科研 SKILL.md 的 description 补充高频用户查询关键词（中英文），确保 Lead Agent 路由更精准。

---

## 实施优先级

| 优先级 | 修改项 | 复杂度 | 影响面 |
|:------:|-------|:------:|-------|
| **P0** | 修改 1: 8 个高级统计动作 | 高（~400 行新代码） | 打通 SKILL.md 承诺与实际能力 |
| **P0** | 修改 6: 记忆系统科研示例 | 低（~20 行） | 提升科研上下文持久化精度 |
| **P1** | 修改 2: 图表学术标注 | 中（~100 行） | 发表级图表质量 |
| **P1** | 修改 3: 断言-证据幻灯片 | 中（~80 行） | PPT 技能与 SKILL.md 对齐 |
| **P1** | 修改 4: 分析→统计流水线 | 低（~30 行） | 技能间数据流畅通 |
| **P2** | 修改 5: 数据预处理脚本 | 高（~300 行新文件） | 数据质量审计自动化 |
| **P2** | 修改 7: 超时建议 | 极低（注释） | 长任务可靠性 |
| **P2** | 修改 8: description 优化 | 低（~50 行） | 路由精度微调 |

## 约束条件

1. 所有 Python 代码遵循项目现有风格：ruff 格式化、240 字符行宽、Python 3.12+ 类型注解
2. 新增的统计函数必须与现有 `statistical_analysis.py` 架构一致（同样的参数解析、输出格式、图表风格）
3. 不修改 DeerFlow 核心框架代码（`agent.py`/`executor.py`/`tools.py`）——只修改 skills 脚本和提示词
4. 新增代码不引入额外必须依赖——使用 `try/except ImportError` 优雅降级
5. 所有新功能必须通过 `--action` 参数可调用，保持 CLI 接口兼容

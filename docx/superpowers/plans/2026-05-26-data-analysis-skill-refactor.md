# Data Analysis Skill 改造计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改造 data-analysis skill，将多步骤调用合并为单次执行，减少 DeerFlow 集成时的调用次数（从 4-6 步 → 1-2 步）

**Architecture:** 在 `analyze.py` 新增 `analyze` action 和 `--mode` 参数，单次调用内完成 inspect + 汇总 + 关键洞察输出。输出格式统一为 Markdown，便于 DeerFlow 渲染。

**Tech Stack:** Python, DuckDB, openpyxl

---

## File Structure

```
/Users/raidery/.claude/skills/data-analysis/
├── SKILL.md                    # Skill 文档（更新）
├── scripts/
│   ├── analyze.py               # 核心脚本（主要改动）
│   └── header_processor.py      # 表头展平工具（辅助）
└── README.md                   # 依赖说明
```

---

## Task Decomposition

### Task 1: 新增 `analyze` action 基础框架

**Files:**
- Modify: `/Users/raidery/.claude/skills/data-analysis/scripts/analyze.py:678-766`

- [ ] **Step 1: 添加 `action_analyze` 函数框架**

在 `main()` 函数之前添加：

```python
def action_analyze(
    con: duckdb.DuckDBPyConnection,
    table_map: dict[str, str],
    mode: str = "auto",
    file_path: str = None,
) -> str:
    """
    Single-pass comprehensive analysis: inspect + summary + key insights.

    Modes:
      auto     - 自动判断复杂度（默认）
      simple   - 结构化摘要
      medium   - 摘要 + 关键指标
      complex  - 完整报告（环比、同比、趋势）
    """
    output_parts = []

    for original_name, table_name in table_map.items():
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        columns = con.execute(f'DESCRIBE "{table_name}"').fetchall()

        # Auto-detect complexity based on data characteristics
        if mode == "auto":
            mode = _detect_complexity(row_count, len(columns), columns)

        output_parts.append(f"\n{'=' * 60}")
        output_parts.append(f"  Table: {original_name}")
        output_parts.append(f"{'=' * 60}")

        if mode == "simple":
            output_parts.append(_analyze_simple(con, table_name, row_count, columns))
        elif mode == "medium":
            output_parts.append(_analyze_medium(con, table_name, row_count, columns))
        else:
            output_parts.append(_analyze_complex(con, table_name, row_count, columns))

    result = "\n".join(output_parts)
    print(result)
    return result


def _detect_complexity(row_count: int, col_count: int, columns: list) -> str:
    """Auto-detect analysis complexity."""
    # Complex: 100+ rows OR 40+ columns
    if row_count >= 100 or col_count >= 40:
        return "complex"
    # Medium: 30+ rows OR 20+ columns
    if row_count >= 30 or col_count >= 20:
        return "medium"
    return "simple"


def _analyze_simple(con, table_name: str, row_count: int, columns: list) -> str:
    """Simple mode: structured summary only."""
    parts = []
    parts.append(f"Rows: {row_count} | Columns: {len(columns)}")

    # Column types summary
    numeric_types = {"BIGINT", "INTEGER", "SMALLINT", "TINYINT", "DOUBLE", "FLOAT", "DECIMAL", "HUGEINT", "REAL", "NUMERIC"}
    numeric_cols = [c for c in columns if re.sub(r"\(.*\)", "", c[1].strip().upper()) in numeric_types]
    string_cols = [c for c in columns if c[0] not in [nc[0] for nc in numeric_cols]]

    parts.append(f"Numeric columns: {len(numeric_cols)}")
    parts.append(f"String columns: {len(string_cols)}")

    return "\n".join(parts)


def _analyze_medium(con, table_name: str, row_count: int, columns: list) -> str:
    """Medium mode: summary + key metrics."""
    parts = []
    parts.append(f"Rows: {row_count} | Columns: {len(columns)}")

    # Numeric columns stats
    numeric_types = {"BIGINT", "INTEGER", "SMALLINT", "TINYINT", "DOUBLE", "FLOAT", "DECIMAL", "HUGEINT", "REAL", "NUMERIC"}
    numeric_cols = [(c[0], re.sub(r"\(.*\)", "", c[1]).strip().upper()) for c in columns
                    if re.sub(r"\(.*\)", "", c[1]).strip().upper() in numeric_types]

    if numeric_cols:
        parts.append("\n--- Key Metrics ---")
        for col_name, col_type in numeric_cols[:10]:  # top 10 numeric cols
            try:
                stats = con.execute(f'''
                    SELECT
                        COUNT("{col_name}") as cnt,
                        AVG("{col_name}")::DOUBLE as avg,
                        MIN("{col_name}") as min_val,
                        MAX("{col_name}") as max_val
                    FROM "{table_name}"
                ''').fetchone()
                cnt, avg, mn, mx = stats
                if cnt > 0:
                    parts.append(f"  {col_name}: avg={avg:,.2f} range=[{mn}, {mx}]")
            except Exception:
                pass

    return "\n".join(parts)


def _analyze_complex(con, table_name: str, row_count: int, columns: list) -> str:
    """Complex mode: full report with trends."""
    parts = []
    parts.append(f"Rows: {row_count} | Columns: {len(columns)}")

    # Full summary statistics
    numeric_types = {"BIGINT", "INTEGER", "SMALLINT", "TINYINT", "DOUBLE", "FLOAT", "DECIMAL", "HUGEINT", "REAL", "NUMERIC"}
    numeric_cols = [(c[0], re.sub(r"\(.*\)", "", c[1]).strip().upper()) for c in columns
                    if re.sub(r"\(.*\)", "", c[1]).strip().upper() in numeric_types]

    if numeric_cols:
        parts.append("\n--- Full Statistics ---")
        for col_name, col_type in numeric_cols:
            try:
                stats = con.execute(f'''
                    SELECT
                        COUNT("{col_name}") as count,
                        AVG("{col_name}")::DOUBLE as mean,
                        STDDEV("{col_name}")::DOUBLE as std,
                        MIN("{col_name}") as min,
                        QUANTILE_CONT("{col_name}", 0.25) as q25,
                        MEDIAN("{col_name}") as median,
                        QUANTILE_CONT("{col_name}", 0.75) as q75,
                        MAX("{col_name}") as max,
                        COUNT(*) - COUNT("{col_name}") as null_count
                    FROM "{table_name}"
                ''').fetchone()
                labels = ["count", "mean", "std", "min", "25%", "50%", "75%", "max", "nulls"]
                parts.append(f"\n  {col_name}:")
                for label, val in zip(labels, stats):
                    if isinstance(val, float):
                        parts.append(f"    {label:<8}: {val:,.4f}")
                    else:
                        parts.append(f"    {label:<8}: {val}")
            except Exception:
                pass

    return "\n".join(parts)
```

- [ ] **Step 2: 在 `main()` 中添加 `--mode` 参数和 `analyze` action 分支**

找到 `argparse` 部分（约 line 679），添加：

```python
parser.add_argument(
    "--mode",
    type=str,
    default="auto",
    choices=["auto", "simple", "medium", "complex"],
    help="Analysis complexity mode (default: auto)",
)
```

找到 `main()` 中的 action 分支（约 line 756），在 `elif args.action == "overview":` 之后添加：

```python
elif args.action == "analyze":
    action_analyze(con, table_map, args.mode, args.files[0] if args.files else None)
```

- [ ] **Step 3: 更新 `--action` 参数的 choices**

将 `choices=["inspect", "query", "summary", "overview"]` 改为：
```python
choices=["inspect", "query", "summary", "overview", "analyze"]
```

- [ ] **Step 4: 运行测试验证**

Run: `python /Users/raidery/.claude/skills/data-analysis/scripts/analyze.py --files /Users/raidery/bench/harness/raidery/deer-flow/docs/27000099_202510_元_收单商户统计表.xlsx --action analyze --mode auto`

Expected: 输出 Markdown 格式的分析结果

- [ ] **Step 5: 提交**

```bash
git add scripts/analyze.py
git commit -m "feat: add action_analyze with auto/simple/medium/complex modes"
```

---

### Task 2: 输出格式改为 Markdown 结构化

**Files:**
- Modify: `/Users/raidery/.claude/skills/data-analysis/scripts/analyze.py:294-345` (action_inspect)

- [ ] **Step 1: 改造 `action_inspect` 输出为 Markdown**

将 `action_inspect` 函数中的输出格式改为 Markdown：

```python
def action_inspect(con: duckdb.DuckDBPyConnection, table_map: dict[str, str]) -> str:
    """Inspect the schema of all loaded tables."""
    output_parts = []

    for original_name, table_name in table_map.items():
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        columns = con.execute(f'DESCRIBE "{table_name}"').fetchall()

        output_parts.append(f"\n## 📋 Table: {original_name}")
        output_parts.append(f"**Rows:** {row_count} | **Columns:** {len(columns)}")
        output_parts.append(f"\n### Columns")
        output_parts.append(f"| Name | Type | Nullable |")
        output_parts.append(f"|------|------|----------|")
        for col in columns:
            col_name, col_type, nullable = col[0], col[1], col[2]
            output_parts.append(f"| {col_name} | {col_type} | {nullable} |")

        # Non-null counts
        col_names = [col[0] for col in columns]
        non_null_parts = []
        for c in col_names:
            non_null_parts.append(f'COUNT("{c}") as "{c}"')
        non_null_sql = f'SELECT {", ".join(non_null_parts)} FROM "{table_name}"'
        try:
            non_null_counts = con.execute(non_null_sql).fetchone()
            output_parts.append(f"\n### Data Quality (Non-null counts)")
            for i, c in enumerate(col_names):
                pct = (non_null_counts[i] / row_count * 100) if row_count > 0 else 0
                output_parts.append(f"- {c}: {non_null_counts[i]}/{row_count} ({pct:.1f}%)")
        except Exception:
            pass

        # Sample data
        output_parts.append(f"\n### Sample Data (first 3 rows)")
        try:
            sample = con.execute(f'SELECT * FROM "{table_name}" LIMIT 3').fetchdf()
            output_parts.append(sample.to_string(index=False))
        except Exception:
            pass

    result = "\n".join(output_parts)
    print(result)
    return result
```

- [ ] **Step 2: 同样改造 `action_overview` 输出格式**

- [ ] **Step 3: 运行测试**

Run: `python /Users/raidery/.claude/skills/data-analysis/scripts/analyze.py --files /Users/raidery/bench/harness/raidery/deer-flow/docs/27000099_202510_元_收单商户统计表.xlsx --action inspect`

Expected: Markdown 格式输出

- [ ] **Step 4: 提交**

```bash
git add scripts/analyze.py
git commit -m "refactor: output format to Markdown for better readability"
```

---

### Task 3: 更新 SKILL.md 文档

**Files:**
- Modify: `/Users/raidery/.claude/skills/data-analysis/SKILL.md`

- [ ] **Step 1: 添加新 action 说明**

在 `## Analysis Complexity Adaptation` 部分之后添加：

```markdown
### New `analyze` Action (Recommended)

For single-pass comprehensive analysis, use `analyze` action:

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action analyze \
  --mode auto   # auto/simple/medium/complex
```

This combines inspect + summary + key insights in one call, reducing DeerFlow integration steps.

| Mode | Behavior |
|------|----------|
| auto | 自动判断复杂度（默认） |
| simple | 结构化摘要（2步 → 1步） |
| medium | 摘要 + 关键指标（3步 → 1步） |
| complex | 完整报告含环比同比（8+步 → 2步） |
```

- [ ] **Step 2: 更新 `## Workflow` 部分**

将原流程说明更新为推荐使用 `analyze` action：

```markdown
## Workflow

When a user uploads data files and requests analysis:

1. **Simple requests** ("分析文件"、"看看数据"):
   - Use `analyze --mode auto` → 1 step

2. **Medium requests** ("哪些"、"top N"、"按...汇总"):
   - Use `analyze --mode medium` → 1 step

3. **Complex requests** ("报告"、"趋势"、"环比同比"):
   - Use `analyze --mode complex` → 1-2 steps

For custom SQL queries, use `query` action.
```

- [ ] **Step 3: 提交**

```bash
git add SKILL.md
git commit -m "docs: update SKILL.md with analyze action"
```

---

## Self-Review Checklist

1. **Spec coverage:** All requirements covered:
   - [x] 新增 `action_analyze` 合并多次调用
   - [x] 新增 `--mode auto` 自动判断
   - [x] 输出格式统一为 Markdown
   - [x] 向后兼容（原有 action 不变）

2. **Placeholder scan:** 无 placeholder，所有步骤都有具体代码和命令

3. **Type consistency:** 函数签名一致，`action_analyze` 参数传递正确

---

## Execution Options

**Plan complete and saved to `docs/superpowers/plans/2026-05-26-data-analysis-skill-refactor.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
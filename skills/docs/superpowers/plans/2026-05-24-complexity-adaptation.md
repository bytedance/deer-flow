# Complexity-Based Analysis Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add complexity assessment and adaptive workflow to SKILL.md — Simple (1 step), Medium (2 steps), Complex (3 steps) — with SQL pattern examples for combining multiple metrics in a single query.

**Architecture:** Update SKILL.md with a new "Analysis Complexity Adaptation" section that replaces the fixed Step 1→2→3 workflow. The complexity level determines how many steps the Agent takes before writing the final query.

**Tech Stack:** SKILL.md only (documentation change, no code changes to analyze.py).

---

## Task 1: Add Complexity Adaptation Section

**Files:**
- Modify: `skills/public/data-analysis/SKILL.md`

**Content to insert after line 30 (after "You don't need to check the folder under /mnt/user-data") or in a new section before "## Workflow":**

```markdown
## Analysis Complexity Adaptation

When a user requests analysis, assess the complexity level first:

| Level | 判断标准 | Agent Steps | SQL 调用次数 |
|-------|----------|-------------|-------------|
| **Simple** | 单维度、无聚合需求 | Step 2 → 直接写查询 → 结束 | 1 次 |
| **Medium** | 多维度、基础聚合 | Step 2 (overview) → 合并查询 → 结束 | 1-2 次 |
| **Complex** | 多维度、跨维度、需要报告 | Step 2 (overview) → Step 3 (summary) → 合并查询 → 结束 | 2-3 次 |

**Complexity 判断示例：**
- **Simple**：查询单一指标、最大/最小值、简单过滤（"正常商户有多少"、"设备数最多的是哪家"）
- **Medium**：多指标汇总、分类对比、各维度基础聚合（"各行业商户分布"、"各机构设备对比"）
- **Complex**：跨维度分析、跨期对比、需要综合报告（"生成完整分析报告"、"各指标环比同比"）

### Step 2: Get Overview (Single Call) — Medium & Complex 需要

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action overview
```

Combines table structure + column quick-ref + numeric stats + top string values + sample rows in one call.

### Step 3: Get Statistical Summary — 仅 Complex 需要

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action summary \
  --table Sheet1
```

### Step 4: Write Query Directly (All Levels)

根据复杂度选择直接写 SQL：
- **Simple**：单次查询，直接执行
- **Medium**：用 CASE WHEN / UNION ALL 合并多指标到 1 个 SQL
- **Complex**：分步查询，每次数值聚合，最终汇总报告

---

## Task 2: Add SQL Patterns for Combining Metrics

**Files:**
- Modify: `skills/public/data-analysis/SKILL.md` (append before "## Complete Example" section)

**Content to insert:**

```markdown
## SQL Patterns for Combining Metrics

When writing queries, prefer combining multiple metrics into a single SQL call rather than making multiple separate queries.

### Pattern 1: 多指标横向合并（推荐）

合并多个指标到一行，避免多次调用：

```sql
SELECT
    SUM("收单商户数_活跃商户") as 活跃商户总数,
    SUM("设备数_设备合计_期末") as 设备总数,
    SUM("收单商户数_本期新增") as 本期新增商户
FROM "统计数据"
WHERE "填报机构_机构名称" IS NOT NULL
```

### Pattern 2: 按维度分类汇总（带 GROUP BY）

```sql
SELECT
    "填报机构_机构名称" as 机构,
    SUM("收单商户数_活跃商户") as 活跃商户,
    SUM("设备数_设备合计_期末") as 设备数
FROM "统计数据"
WHERE "填报机构_机构名称" IS NOT NULL
  AND "填报机构_机构名称" NOT LIKE '%行长%'
GROUP BY "填报机构_机构名称"
ORDER BY 活跃商户 DESC
```

### Pattern 3: 纵向堆叠（UNION ALL）

将不同行指标转为同一列，便于排序和比较：

```sql
SELECT '活跃商户' as 指标, SUM("收单商户数_活跃商户") as 数值 FROM "统计数据"
UNION ALL
SELECT '传统POS', SUM("陕西省农村合作金融机构收单商户统计表_月报   日期_2025年10月_设备数_传统POS_期末") FROM "统计数据"
UNION ALL
SELECT '智能POS', SUM("陕西省农村合作金融机构收单商户统计表_月报   日期_2025年10月_设备数_智能POS_期末") FROM "统计数据"
ORDER BY 数值 DESC
```

### Pattern 4: 条件聚合（CASE WHEN）

在单一 SQL 内计算多维度条件聚合：

```sql
SELECT
    SUM(CASE WHEN "填报机构_机构名称" NOT LIKE '%联社%' THEN "收单商户数_活跃商户" ELSE 0 END) as 非联社活跃商户,
    SUM(CASE WHEN "填报机构_机构名称" LIKE '%联社%' THEN "收单商户数_活跃商户" ELSE 0 END) as 联社活跃商户
FROM "统计数据"
```

---

## Self-Review Checklist

- [ ] All three complexity levels (Simple/Medium/Complex) have clear 判断标准
- [ ] Step numbers are consistent: Simple skips Step 2 (1 step), Medium uses Step 2 (2 steps), Complex uses Step 2+3 (3 steps)
- [ ] SQL patterns use actual column names from the sample Excel file
- [ ] No placeholder text (TBD/TODO)
- [ ] Patterns show practical bank data examples (收单商户、设备数、商户状态)
- [ ] New section inserted before "## Complete Example" to maintain document flow
```

- [ ] **Step 1: Write the plan**

Save to: `docs/superpowers/plans/2026-05-24-complexity-adaptation.md`

- [ ] **Step 2: Review the plan against the user's draft**

Check:
1. Simple = 1 step (direct query, no overview) — ✅ matches user's "1步" requirement
2. Medium = 2 steps (overview → merged query) — ✅ matches user's "2步" requirement
3. Complex = 3 steps (overview → summary → merged query) — ✅ matches user's "3步" requirement
4. SQL patterns use `SUM(CASE WHEN)` and `UNION ALL` for combining metrics — ✅
5. Pattern 2 uses GROUP BY for cross-category comparison — ✅
6. All column names match actual data from `27000099_202510_元_收单商户统计表.xlsx` — ✅ verified against inspect output

- [ ] **Step 3: Insert new content into SKILL.md**

Insert "## Analysis Complexity Adaptation" section before line 32 (before "### Step 2: Inspect File Structure").

Insert "## SQL Patterns for Combining Metrics" section before line 169 (before "## Complete Example").

- [ ] **Step 4: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add skills/public/data-analysis/SKILL.md
rtk git commit -m "feat(data-analysis): add complexity-adaptive workflow and SQL patterns"
```
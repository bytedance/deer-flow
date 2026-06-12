---
name: data-analysis
version: 2.3.0-20250606
description: |
  Analyze, summarize, query, pivot, join, or filter Excel (.xlsx/.xls)
  and CSV files using DuckDB SQL. Multi-sheet workbooks, cross-file joins,
  CSV/JSON/Markdown export.

  Triggers: "分析/分析报表/统计/汇总/透视 Excel/CSV", "analyze this spreadsheet",
  "pivot by ...", "run SQL on CSV".
---

# Data Analysis Skill

使用 DuckDB 对 Excel/CSV 文件进行 SQL 分析，支持表结构检查、统计摘要、聚合查询、结果导出。

## 触发匹配规则（Agent 加载后必读）

> 本节是**给 LLM 的执行指令**，不是给人类阅读的。

**Step 1 — 匹配判断**：如果用户消息**符合以下任一条件**，加载本 Skill 并继续：
- 含以下中文动词之一 + 表格/文件路径：`分析 / 看看 / 统计 / 汇总 / 透视 / 拆解 / 跑一下 / 列一下`
- 含以下英文动词之一：`analyze / summarize / inspect / query / aggregate / pivot / group by / filter / join`
- 用户给出一个 `.xlsx / .xls / .csv` 路径并问"这是什么 / 多少行 / 长啥样"
- 用户问"做个报告 / 生成图表 / 导出"且源数据是表格文件

**Step 2 — 复杂度判定**：
- **首轮对话 → 强制 Simple Mode**（见下一节），不要判断"是否复杂"
- **追问 / 续轮** → 根据用户措辞判定 Simple / Medium / Complex（见下表）

**Step 3 — 绝不主动扩大范围**：
- 不主动加更多分析维度
- 不主动建议"要不要也看看 XX"
- 不追问"你还想了解什么"——用户没问就不答

## 强制 Simple Mode（首轮）

以下关键词**强制触发 Simple Mode**，必须使用 `--mode simple`：

`分析文件` | `分析报表` | `分析这个Excel` | `分析这个xlsx` | `分析这个csv` | `看看数据` | `统计数据` | `数据汇总` | `生成报告` | `看看这个表` | `有多少行`

执行方式：`analyze --mode simple` → 结构化摘要 → 结束

**规则**：
- 首轮对话**强制 Simple Mode**，不判断复杂度
- 不执行 overview/summary/query
- 不追问、不主动提供更多分析建议
- 用户追问 → 视为新的 Medium/Complex 请求

## 分析复杂度（仅限追问）

| Level | 判断标准 | 执行模式 |
|-------|----------|----------|
| **Simple** | 上述强制关键词 | `inspect` → 结构化摘要 → 结束 |
| **Medium** | "哪些"、"top N"、"按...汇总" | `inspect` → `overview` → `query` → 结束 |
| **Complex** | "报告"、"趋势"、"环比同比" | `inspect` → `overview` → `summary` → 分步 `query` → 结束 |

> 首轮对话强制 Simple Mode，上述复杂度判断仅适用于用户追问场景。

### Simple 级结构化摘要格式

```
数据结构化摘要：
• 表名：[表格名称]
• 行数：X 行
• 字段数：X 列
• 关键字段：
  - [字段1]（类型）- 描述或用途
  - [字段2]（类型）- 描述或用途
• 数据特征：
  - 数值范围：[min] ~ [max]
  - 分类分布：Top 3 类别 [类别A: N条], [类别B: M条], [类别C: K条]
• 数据质量：总非空率 XX%，缺失较多的列：[列名1]、[列名2]
• 样本数据（3行）：
  [行1数据]
  [行2数据]
  [行3数据]
```

**规则**：数值列只展示统计摘要；分类列只展示 Top 3-5 分布；样本数据最多 3 行；**不执行任何 query、summary、overview**，除非用户明确追问。

## 使用方式

```bash
# 强制 Simple Mode（关键词触发）
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action analyze --mode simple

# 自动判断复杂度
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action analyze --mode auto

# 自定义 SQL 查询
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action query \
  --sql "SELECT * FROM Sheet1 WHERE amount > 1000" \
  --output-file /mnt/user-data/outputs/filtered-results.csv
```

### 参数说明

| 参数 | 必填 | 说明 |
|------|------|------|
| `--files` | Yes | 文件路径，多个文件用空格分隔 |
| `--action` | Yes | `inspect` / `query` / `summary` / `overview` / `analyze` |
| `--mode` | No | `auto` / `simple` / `medium` / `complex`，默认 `auto` |
| `--sql` | query 时必填 | SQL 查询语句 |
| `--table` | summary 时必填 | 表/Sheet 名称 |
| `--output-file` | No | 导出路径（自动识别格式：.csv / .json / .md） |

## 表命名规则

- **Excel**：每个 Sheet 成为一张表，名称为 Sheet 名（如 `Orders`、`Products`）
- **CSV**：表名为文件名（不含扩展名），如 `data.csv` → `data`
- **多文件**：所有表的查询上下文互通，支持跨文件 JOIN
- **特殊字符**：空格/特殊字符自动转为下划线；数字开头需用双引号包裹，如 `"2024_Sales"`

> [!NOTE]
> 不要读取 Python 脚本，直接调用即可。

## 示例

```bash
# 统计行数（Simple Mode）
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/orders.csv \
  --action analyze --mode simple

# 各地区平均订单金额（Medium，JOIN 示例）
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/orders.csv /mnt/user-data/uploads/customers.xlsx \
  --action query \
  --sql "SELECT c.region, AVG(o.amount) as avg_order_value, COUNT(*) as order_count FROM orders o JOIN Customers c ON o.customer_id = c.id GROUP BY c.region ORDER BY avg_order_value DESC"

# 导出结果
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales_2024.xlsx \
  --action query \
  --sql "SELECT product_name, SUM(revenue) as total_revenue FROM Sales GROUP BY product_name ORDER BY total_revenue DESC" \
  --output-file /mnt/user-data/outputs/top-products.csv
```

## 输出与后续处理

- 直接在对话中展示格式化表格
- 大结果导出为文件，通过 `present_files` 分享
- 用通俗语言解释发现和关键结论
- 发现有趣模式时建议后续分析
- 用户要求时提供导出

## 缓存

脚本自动缓存已加载的数据（SHA256 哈希作 key），避免重复解析。缓存在 `~/.data-analysis-cache/`。

## 备注

- DuckDB 支持完整 SQL（窗口函数、CTE、子查询、高级聚合）
- Excel 日期列自动解析，使用 `DATE_TRUNC`、`EXTRACT` 等函数
- 大文件（100MB+）处理高效，不会全部加载到内存
- 列名含空格用双引号：`"Column Name"`

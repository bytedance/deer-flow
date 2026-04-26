---
name: canvas-analysis
description: 用于数据分析场景，帮助用户通过 Canvas DAG 构建可复用的数据处理管道。从用户宽泛的分析请求中提炼具体目标，自动设计完整的 DAG 结构，为每个节点生成处理逻辑，执行后输出分析结果。
---

# Canvas 数据分析技能

## 概述

`canvas-analysis` 是一个数据分析技能，帮助用户通过 Canvas DAG 构建可复用的数据处理管道。技能从用户宽泛的分析请求中提炼具体目标，自动设计完整的 DAG 结构，为每个节点生成处理逻辑，执行后输出分析结果。

## 与现有技能的区别

| 技能 | 数据来源 | 处理方式 | 输出 | 适用场景 |
|-----|---------|---------|------|---------|
| data-analysis | 上传的 Excel/CSV 文件 | DuckDB 即时查询 | 一次性分析结果 | 快速分析本地文件 |
| canvas-analysis | 数据库连接（MySQL/PostgreSQL） | Canvas DAG 多节点管道 | 分析结果 + 可复用 DAG | 生产级数据处理管道 |

## 触发条件

当用户表达数据分析意图时自动触发：
- "帮我分析...数据"
- "做个报表"
- "统计一下..."
- "看看销售情况"
- 任何涉及数据库查询或多步骤数据处理的请求

## 核心流程

```
用户请求 → 需求提炼 → 观察环境 → 设计 DAG 方案 → 用户确认 → 构建 DAG → 执行与呈现
```

## 可用工具

| 工具 | 功能 | 使用时机 |
|-----|------|---------|
| `canvas_inspect` | 检查 Canvas 当前状态 | 每次添加节点前调用 |
| `canvas_list_tables` | 列出数据库连接中的表 | 选择数据源表时 |
| `canvas_table_schema` | 获取表的字段结构 | 设计 SQL 查询前 |
| `canvas_preview_data` | 预览表数据或节点输出 | 验证节点输出、展示结果 |
| `canvas_plan` | 创建或更新 Canvas 描述 | 开始设计 DAG 时 |
| `canvas_add_node` | 添加节点到 Canvas | 构建 DAG 时 |
| `canvas_add_edge` | 添加边连接节点 | 构建 DAG 时 |
| `canvas_execute` | 执行 DAG | 执行分析时 |
| `canvas_status` | 获取 Canvas 执行状态 | 检查执行状态时 |

## DAG 设计模式

### 典型结构

```
data_source → sql_executor → [python_script] → data_output
```

### 节点类型与配置

#### data_source 节点

声明数据库表作为数据源。

**配置示例：**
```json
{
  "connection_id": "dataflow",
  "table_name": "dim_experiment",
  "display_name": "实验维度表"
}
```

**可用变量生成：** `{{node-X.table_name}}`

#### sql_executor 节点

执行 SQL 查询，生成新的结果表。

**配置示例：**
```json
{
  "output_table": "result_table_name",
  "sql": "SELECT ... FROM {{node-Y.table_name}} WHERE ...",
  "display_name": "描述性名称"
}
```

**重要：** SQL 中使用变量引用上游节点的表：`{{node-X.table_name}}` 或 `{{node-X.output_table}}`

#### python_script 节点

执行 Python 脚本进行复杂数据处理。

**配置示例：**
```json
{
  "output_table": "processed_table",
  "input_tables": ["{{node-X.output_table}}"],
  "script": "import pandas as pd\n...",
  "display_name": "处理脚本"
}
```

#### data_output 节点

导出数据到文件。

**配置示例：**
```json
{
  "input_table": "{{node-X.output_table}}",
  "output_format": "csv",
  "filename": "分析结果.csv"
}
```

### 按分析类型选择结构

| 分析类型 | DAG 结构 |
|---------|---------|
| 简单查询 | data_source → sql_executor → data_output |
| 多表关联 | 2+ data_source → sql_executor(JOIN) → data_output |
| 聚合统计 | data_source → sql_executor(GROUP BY) → data_output |
| 复杂处理 | data_source → sql_executor → python_script → data_output |
| 对比分析 | data_source → sql_executor(分组统计) → data_output |

## 执行流程

### Step 1: 需求提炼

从用户请求中提取：
- **分析目标**: 用户想得到什么结果？
- **时间范围**: 需要分析哪个时间段的数据？
- **筛选条件**: 需要哪些过滤条件？
- **输出类型**: 报表/统计/对比/趋势？

### Step 2: 观察环境

**关键步骤：每次添加节点前必须调用 `canvas_inspect`**

```
canvas_inspect() → 了解当前 Canvas 状态
canvas_list_tables() → 了解可用数据源
canvas_table_schema() → 了解表结构（按需）
```

**观察内容：**
- 当前 Canvas 是否为空
- 已有节点及其配置
- 已有边连接关系
- 可用变量列表

### Step 3: 设计 DAG 方案

向用户展示：
- 将使用的表及原因
- 节点数量和类型
- 每个 SQL 节点的核心逻辑（SQL 框架）
- 预期输出

**示例：**
```
我设计的分析方案：
1. **data_source**: 从 dim_experiment 获取实验数据
2. **sql_executor**: 按实验类型分组统计数量
3. **data_output**: 导出为 CSV

核心 SQL 逻辑：
SELECT experiment_type, COUNT(*) as count
FROM dim_experiment
GROUP BY experiment_type
ORDER BY count DESC

是否按此方案执行？
```

### Step 4: 用户确认

用户可以：
- 确认执行
- 请求修改某个节点的逻辑
- 指定不同的表

### Step 5: 构建 DAG

**重要模式：每次添加节点前调用 `canvas_inspect`**

```
canvas_plan(description="...")

canvas_inspect() → 确认状态，获取 canvas_id
canvas_add_node("data_source", {...})

canvas_inspect() → 获取可用变量 {{node-1.table_name}}
canvas_add_node("sql_executor", {
    "sql": "SELECT ... FROM {{node-1.table_name}} ...",
    ...
})

canvas_add_edge("node-1", "node-2")

... 继续添加节点 ...

canvas_add_node("data_output", {...})
canvas_add_edge(..., "node-N")
```

### Step 6: 执行与呈现

```
canvas_execute()
canvas_preview_data(source="node-N")
```

## 结果呈现格式

```markdown
## Canvas 分析完成

**执行状态:** ✅ 完成 (耗时 3.2s)

**DAG 结构:**
- node-1: data_source → dim_experiment (实验维度表)
- node-2: sql_executor → experiment_stats (实验类型统计)
- node-3: data_output → 实验分析报告.csv

**结果预览:**

| experiment_type | count |
|-----------------|-------|
| A/B Test | 45 |
| MVT | 12 |

**输出文件:** `/mnt/user-data/outputs/实验分析报告.csv`

**Canvas 已保存，可通过前端界面查看和编辑。**
```

## 错误处理

### 节点执行失败

- 停止后续执行
- 显示错误详情和失败节点
- 建议修改方案

### 数据源连接失败

- 提示检查连接配置
- 尝试备用连接（如果有）

### SQL 语法错误

- 显示具体错误位置
- 建议修正方案
- 提供重新执行选项

## 示例对话

**用户:** 帮我分析一下我们做的实验的情况，看看哪种类型实验最多

**技能:**
我来帮你分析实验情况。让我先看看可用的数据源。

*[调用 canvas_inspect - Canvas 为空]*

*[调用 canvas_list_tables]*

发现 `dataflow` 数据库中有以下实验相关表：
- dim_experiment - 实验维度表
- dim_experiment_metric - 实验指标表
- fact_experiment_assignment - 实验分配事实表

我设计的分析方案：
1. **data_source**: 从 dim_experiment 获取实验数据
2. **sql_executor**: 按实验类型分组统计数量
3. **data_output**: 导出为 CSV

核心 SQL 逻辑：
```sql
SELECT experiment_type, COUNT(*) as count
FROM dim_experiment
GROUP BY experiment_type
ORDER BY count DESC
```

是否按此方案执行？

**用户:** 可以

**技能:**
*[调用 canvas_plan]*
*[调用 canvas_inspect]*
*[调用 canvas_add_node - data_source]*
*[调用 canvas_inspect - 获取可用变量 {{node-1.table_name}}]*
*[调用 canvas_add_node - sql_executor]*
*[调用 canvas_add_edge]*
*[调用 canvas_add_node - data_output]*
*[调用 canvas_add_edge]*
*[调用 canvas_execute]*
*[调用 canvas_preview_data]*

## Canvas 分析完成

**执行状态:** ✅ 完成 (耗时 1.2s)

**结果预览:**

| experiment_type | count |
|-----------------|-------|
| A/B Test | 45 |
| MVT | 12 |
| Multi-armed Bandit | 8 |

**输出文件:** `/mnt/user-data/outputs/实验类型统计.csv`

如需可视化，可以说"生成图表"。

---
name: canvas-analysis
description: 用于数据分析场景，帮助用户通过 Canvas DAG 构建可复用的数据处理管道。初始化时创建 Canvas，引导用户选择数据源和表，逐步构建分析管道。
---

# Canvas 数据分析技能

## 概述

`canvas-analysis` 是一个数据分析技能，帮助用户通过 Canvas DAG 构建可复用的数据处理管道。技能采用交互式引导方式，从选择数据源开始，逐步构建完整的分析管道。

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
用户请求 → 创建 Canvas → 选择数据源 → 选择数据表 → 设计 DAG → 执行与呈现
```

## 可用工具

| 工具 | 功能 | 使用时机 |
|-----|------|---------|
| `canvas_plan` | 创建或更新 Canvas | **第一步必须调用**，创建 Canvas |
| `canvas_inspect` | 检查 Canvas 当前状态 | 每次添加节点前调用 |
| `canvas_list_tables` | 列出数据库连接中的表 | 选择数据源表时 |
| `canvas_table_schema` | 获取表的字段结构 | 设计 SQL 查询前 |
| `canvas_preview_data` | 预览表数据或节点输出 | 验证节点输出、展示结果 |
| `canvas_add_node` | 添加节点到 Canvas | 构建 DAG 时 |
| `canvas_add_edge` | 添加边连接节点 | 构建 DAG 时 |
| `canvas_execute` | 执行 DAG | 执行分析时 |
| `canvas_status` | 获取 Canvas 执行状态 | 检查执行状态时 |

## 执行流程

### Step 1: 立即创建 Canvas（必须）

**重要：收到用户请求后，第一步必须调用 `canvas_plan` 创建 Canvas。**

这样做的原因：
1. 前端 CanvasTrigger 需要 canvas 数据才能显示按钮
2. 用户可以立即在界面上看到 Canvas 面板
3. 后续交互更加直观

```
canvas_plan(
    description="用户原始请求的分析目标",
    name="数据分析",
    agent_execution_mode="interactive"
)
```

### Step 2: 询问数据源

创建 Canvas 后，询问用户使用哪个数据源，如果只有一个数据源则跳过这一步：

```
我已为您创建了数据分析 Canvas。

现在请选择要使用的数据源（数据库连接）：

1. dataflow - 主数据库
2. analytics - 分析数据库
3. warehouse - 数据仓库

请告诉我使用哪个数据源？
```

**调用工具获取数据源列表：**
```
canvas_list_tables() → 返回可用的数据库连接列表
```

### Step 3: 列出数据表

用户选择数据源后，列出该数据源中的表：

```
[dataflow] 数据库中的表：

**维度表（dim_）：**
- dim_user - 用户维度表
- dim_product - 产品维度表
- dim_experiment - 实验维度表

**事实表（fact_）：**
- fact_order - 订单事实表
- fact_experiment_assignment - 实验分配事实表

**汇总表（agg_）：**
- agg_daily_sales - 日销售汇总

请问您要分析哪个表？或者描述您的分析需求，我来推荐合适的表。
```

### Step 4: 添加数据源节点

用户选择表后：
1. 获取表结构（可选）：`canvas_table_schema(table_name)`
2. 添加 data_source 节点
3. 预览数据让用户确认

```
canvas_inspect() → 确认 Canvas 状态
canvas_add_node(node_type="data_source", config = {
    "connection_id": "dataflow",
    "table_name": "dim_experiment",
    "display_name": "实验维度表"
})
```

然后向用户确认：
```
已添加数据源节点：dim_experiment（实验维度表）

表结构预览：
- experiment_id: 实验ID
- experiment_name: 实验名称
- experiment_type: 实验类型
- start_date: 开始日期
- end_date: 结束日期
- status: 状态

请问您想对这份数据做什么分析？
```

### Step 5: 设计后续 DAG

根据用户的分析需求，设计后续节点：
- 简单统计：data_source → sql_executor → data_output
- 多表关联：需要询问添加更多 data_source
- 复杂处理：添加 python_script 节点

**重要：每次添加节点前调用 `canvas_inspect` 获取可用变量。**

### Step 6: 执行与呈现

```
canvas_execute()
canvas_preview_data(source="node-N")
```

## DAG 设计模式

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
  "sql": "SELECT ... FROM {{node-X.table_name}} WHERE ...",
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

**用户:** 帮我分析一下我们做的实验的情况

**技能:**
我来帮您分析实验情况。首先创建数据分析 Canvas...

*[调用 canvas_plan - 创建 Canvas]*

我已为您创建了数据分析 Canvas，您可以在右侧面板中查看。

现在请选择数据源：

**可用数据库连接：**
1. **dataflow** - 主数据库
2. **analytics** - 分析数据库

请问使用哪个数据源？

**用户:** 用 dataflow

**技能:**
好的，正在获取 dataflow 数据库中的表...

*[调用 canvas_list_tables(connection_id="dataflow")]*

**dataflow 数据库中的表：**

**维度表：**
- `dim_user` - 用户维度表
- `dim_product` - 产品维度表  
- `dim_experiment` - 实验维度表
- `dim_experiment_metric` - 实验指标表

**事实表：**
- `fact_order` - 订单事实表
- `fact_experiment_assignment` - 实验分配事实表

请问您要分析哪个表？

**用户:** dim_experiment

**技能:**
好的，我来添加实验维度表作为数据源。

*[调用 canvas_inspect]*
*[调用 canvas_table_schema(table_name="dim_experiment")]*
*[调用 canvas_add_node - data_source]*

已添加数据源节点：**dim_experiment（实验维度表）**

**表结构：**
| 字段 | 类型 | 说明 |
|-----|------|-----|
| experiment_id | string | 实验ID |
| experiment_name | string | 实验名称 |
| experiment_type | string | 实验类型 |
| start_date | date | 开始日期 |
| end_date | date | 结束日期 |
| status | string | 状态 |

请问您想对实验数据做什么分析？例如：
- 统计各类型实验数量
- 分析实验状态分布
- 查看时间趋势
- 其他自定义分析

**用户:** 统计各类型实验数量

**技能:**
好的，我来设计分析方案：

**方案：**
1. **data_source**（已添加）: dim_experiment
2. **sql_executor**: 按实验类型分组统计
3. **data_output**: 导出结果

**核心 SQL：**
```sql
SELECT 
  experiment_type,
  COUNT(*) as count
FROM {{node-1.table_name}}
GROUP BY experiment_type
ORDER BY count DESC
```

确认执行吗？

**用户:** 确认

**技能:**
*[调用 canvas_inspect]*
*[调用 canvas_add_node - sql_executor]*
*[调用 canvas_add_edge("node-1", "node-2")]*
*[调用 canvas_inspect]*
*[调用 canvas_add_node - data_output]*
*[调用 canvas_add_edge("node-2", "node-3")]*
*[调用 canvas_execute]*
*[调用 canvas_preview_data]*

## Canvas 分析完成 ✅

**执行耗时:** 1.2s

**DAG 结构：**
```
[node-1] data_source: dim_experiment
    ↓
[node-2] sql_executor: 实验类型统计
    ↓
[node-3] data_output: 实验类型统计.csv
```

**结果预览：**
| experiment_type | count |
|-----------------|-------|
| A/B Test | 45 |
| MVT | 12 |
| Multi-armed Bandit | 8 |

**输出文件:** `/mnt/user-data/outputs/实验类型统计.csv`

您可以在右侧 Canvas 面板中查看和编辑这个分析流程。

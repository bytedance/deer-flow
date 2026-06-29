# ai-report DuckDB V2 架构设计：设计时/运行时复用流程

> 本文整理本轮讨论中确认的目标、边界和推荐架构。
>
> 目标不是在现有单表 pipeline 上局部替换 DuckDB，而是把 skill 升级为：**多表报告的设计系统 + 运行系统**。
>
> 拆分阅读版见同目录：`README.md`、`01-overview-and-modes.md`、`02-duckdb-schema.md`、`03-run-report-data-flow.md`、`04-report-design-md.md`、`05-implementation-phases.md`。

---

## 1. 背景与问题

旧版本偏向单次执行，工作方式如下：

```text
上传一个 table.md
→ lint
→ parse
→ query
→ assemble-wide
→ extract-ir
→ codegen
→ validate
→ evaluate
→ apply-computed
→ describe
→ render
→ 输出单张表/局部报告
```

现实中的报告通常不是一张表，而是多个章节和多张报表共同组成：

```text
经营分析报告
├── 一、总体经营情况
│   ├── 表 1：主要经营指标表
│   └── 表 2：收入利润表
├── 二、存贷款业务情况
│   ├── 表 3：存款余额表
│   └── 表 4：贷款余额表
└── 三、风险资产情况
    └── 表 5：不良贷款表
```

当前模式的问题：

1. 用户每次上传一个 table.md，只能完成一个局部报表。
2. 一个完整报告包含多张表时，需要重复多次完整流程。
3. 每张表都进行运行时 LLM codegen / validate / evaluate，单表耗时可能超过 5 分钟。
4. 报告的章节、表格顺序、计算公式、描述 prompt 没有作为长期设计资产保存。
5. 设计确认与正式运行混在同一流程里，导致正式运行仍需要人工 checkpoint。

---

## 2. 核心目标

`ai-report` 的目标形态：

```text
设计阶段：逐张上传 table.md，完整交互式运行并确认输出效果，保存为报告定义。
运行阶段：选择已激活的报告定义，一键生成完整报告，无人工 checkpoint。
```

一句话：

> ai-report 应该是一个多表报告定义系统。用户在设计模式下逐张确认表格输出，并在报告级预览后激活完整报告；系统保存章节、表格、指标、公式、描述、排序和运行策略；正式运行时复用同一套流程，但跳过人工 checkpoint，直接生成完整 Markdown/DOCX 报告。

---

## 3. 两种模式

### 3.1 Design Mode：设计模式

设计模式用于构建和确认报告定义。

输入通常是一张新上传的 `table.md`：

```text
上传 table.md
→ lint checkpoint
→ parse
→ query
→ query checkpoint
→ DuckDB pivot / table frame
→ 生成或更新 compute_sql
→ 执行 compute_sql
→ compute result checkpoint
→ description
→ description checkpoint
→ render table preview
→ 用户 review 最终输出
→ apply checkpoint edits to design state
→ export final report_design.md
→ 用户确认后保存为 approved table definition
```

设计模式的特点：

- 需要完整执行。
- 需要产出最终预览报表。
- 需要产出最终报表设计 MD 文件，作为用户 review 和后续再导入的设计载体。
- checkpoint 行为保留，和当前流程一致。
- 用户在 checkpoint 中修改或确认的数据，必须先写回设计状态，再导出到最终报表设计 MD。
- 用户用最终输出确认每张表是否设计正确。
- 设计时可以发生 LLM codegen，因为慢一点可以接受。
- 用户确认后，保存解析结果、指标计划、计算 SQL、描述 prompt、失败处理策略等长期定义。

设计模式不是只保存元数据，而是：

```text
interactive dry-run + output review + approval + persistence
```

---

### 3.2 Runtime Mode：运行模式

运行模式用于生成正式完整报告。

输入是已激活的报告定义：

```text
run report <report_id>
→ 读取 active report definition
→ snapshot approved sections/tables/computes
→ 批量查询所有指标
→ DuckDB pivot / table frame
→ 执行已保存 compute_sql
→ 自动生成 description
→ export render_payload
→ render full report
→ 输出 report.md / report.docx
```

运行模式的特点：

- 不再人工 checkpoint。
- 不再运行时 LLM codegen 计算公式。
- 只使用 active report 下 approved table / compute definition。
- 失败按设计模式中确认过的 policy 自动处理。
- 运行级别按 report 批量处理，避免逐表重复执行。

---

## 4. 复用同一套 pipeline

不要实现两套 pipeline：

```text
❌ design_pipeline.py
❌ runtime_pipeline.py
```

推荐实现一套可配置执行器：

```text
pipeline.execute(mode="design")
pipeline.execute(mode="runtime")
```

模式差异由 `PipelineContext` / `CheckpointPolicy` / `ComputePolicy` 控制。

### 4.1 统一步骤

```text
1. load_input
2. lint_template
3. parse_template
4. resolve_definition
5. plan_metric_requests
6. query_metrics
7. checkpoint_query
8. write_metric_facts
9. build_table_frames
10. resolve_computes
11. execute_computes
12. checkpoint_compute_results
13. generate_descriptions
14. checkpoint_descriptions
15. export_render_payload
16. render_outputs
17. apply_checkpoint_edits
18. export_design_md
19. persist_results
20. finalize_definition_or_run
```

### 4.2 模式差异

| 能力 | Design Mode | Runtime Mode |
|---|---|---|
| 输入 | 新上传的 table.md 或 draft definition | 已 active 的 report definition |
| 范围 | 单张 table，也可整 report preview | 整个 report |
| checkpoint | 有 | 无 |
| 用户确认 | 需要 | 不需要 |
| LLM codegen | 可发生 | 默认不发生，使用已保存 compute_sql |
| description | 生成并让用户确认效果 | 自动生成或按 policy 跳过 |
| 输出 | table preview / report preview + final report_design.md | final report |
| 结果固化 | 用户确认后写 definition，并保存最终设计 MD | 写 run result |
| 失败处理 | 问用户继续/停止/修改 | 按已保存 policy 自动处理 |

---

## 5. DuckDB 定位

DuckDB 在 V2 中不是单纯 `assemble-wide` 工具，而是：

```text
Design Store + Run Store + SQL Compute Engine
```

推荐分两个层次：

```text
definitions.duckdb        # 长期保存报告设计
runs/<run_id>/run.duckdb  # 保存单次设计运行或正式运行结果
```

### 5.1 definitions.duckdb

保存长期设计资产：

- 报告
- 章节
- 表格定义
- 指标需求
- 计算公式和 compute_sql
- 设计模式产物确认记录
- 最终报表设计 MD 文件

### 5.2 run.duckdb

保存一次执行结果：

- 本次 run 使用的 definition snapshot
- 本次 run 的参数绑定
- 查询到的指标事实
- 计算结果
- 运行事件和 checkpoint
- render payload 与输出文件

---

## 6. 表数量总览

最终设计包含两类数据库。

### 6.1 定义库：6 张表

```text
reports
report_sections
report_tables
table_metrics
table_computes
design_artifacts
```

### 6.2 运行库：7 张表

```text
run_meta
run_sections
run_tables
metric_facts
computed_facts
run_events
run_outputs
```

总计：

```text
定义库 6 张 + 运行库 7 张 = 13 张表
```

`run_sections` 是必要的运行快照。否则章节级描述、启停、排序和 metadata 会只存在定义库，无法保证一次 run 可复现。

---

## 7. definitions.duckdb schema

### 7.1 reports

保存一个完整报告的基本信息。

```sql
reports(
  report_id TEXT PRIMARY KEY,
  report_name TEXT,
  report_title TEXT,
  status TEXT,              -- draft / table_reviewing / report_previewed / active / archived
  version INTEGER,
  last_preview_run_id TEXT,
  activated_run_id TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  metadata JSON
)
```

报告级状态含义：

| 状态 | 含义 |
|---|---|
| `draft` | 报告仍在编辑，不能正式运行 |
| `table_reviewing` | 至少一张表处于设计/确认中 |
| `report_previewed` | 已生成过完整报告预览，等待激活 |
| `active` | 可用于 runtime 正式运行 |
| `archived` | 已归档，不再运行 |

单表 approved 不等于报告 active。完整报告需要经过 `preview report` 和 `activate report`。

---

### 7.2 report_sections

保存报告章节和章节顺序。

```sql
report_sections(
  section_id TEXT PRIMARY KEY,
  report_id TEXT,
  section_key TEXT,
  section_title TEXT,
  section_order INTEGER,
  description_prompt TEXT,
  enabled BOOLEAN,
  metadata JSON,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
```

推荐顺序值使用 `10, 20, 30`，方便后续插入章节。

---

### 7.3 report_tables

保存每个章节下的表格定义。

```sql
report_tables(
  table_id TEXT PRIMARY KEY,
  report_id TEXT,
  section_id TEXT,
  table_title TEXT,
  table_order INTEGER,
  source_md_path TEXT,
  source_md_hash TEXT,
  parsed_payload JSON,
  headers JSON,
  orgs JSON,
  time_info JSON,
  description_prompt TEXT,
  approval_status TEXT,     -- draft / approved / rejected / disabled
  query_failure_policy TEXT, -- continue_with_sentinel / stop_on_failure
  compute_failure_policy TEXT,
  description_failure_policy TEXT,
  last_design_run_id TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
```

运行模式默认只使用：

```sql
where approval_status = 'approved'
```

---

### 7.4 table_metrics

保存每张表需要查询的基础指标。

```sql
table_metrics(
  table_id TEXT,
  idx_id TEXT,
  period_alias TEXT,
  data_unit TEXT,
  header_text TEXT,
  metric_order INTEGER,
  approval_status TEXT,     -- draft / approved / disabled / failed
  last_design_run_id TEXT,
  metadata JSON,
  PRIMARY KEY(table_id, idx_id, period_alias)
)
```

示例：

```text
table_id: deposit_balance
idx_id: BAS_0263
period_alias: 本期
data_unit: 万元
header_text: 存款余额
```

`period_alias` 是公式和模板中的语义名，例如 `本期`、`去年同期`、`上期`。正式运行时通过 `run_params.period_bindings` 绑定到具体时间值。

---

### 7.5 table_computes

保存每张表的计算列定义和已确认的 SQL。

```sql
table_computes(
  compute_id TEXT PRIMARY KEY,
  table_id TEXT,
  compute_name TEXT,
  formula_text TEXT,
  compute_sql TEXT,
  dependencies JSON,
  examples JSON,
  approval_status TEXT,     -- draft / approved / failed / disabled
  last_design_run_id TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
```

V2 的关键优化：

```text
设计时生成和确认 compute_sql
运行时直接执行 compute_sql
```

运行模式默认只使用：

```sql
where approval_status = 'approved'
```

---

### 7.6 design_artifacts

保存设计模式中被用户确认过的产物引用。

```sql
design_artifacts(
  artifact_id TEXT PRIMARY KEY,
  report_id TEXT,
  table_id TEXT,
  design_run_id TEXT,
  output_id TEXT,
  artifact_type TEXT,       -- preview_md / preview_docx / render_json / status_json / report_design_md
  file_path TEXT,
  status TEXT,
  created_at TIMESTAMP
)
```

边界：

```text
run_outputs       = 某次运行实际生成了什么
design_artifacts  = 哪些 run_outputs 被用户作为设计确认依据
```

`design_artifacts` 不重复保存大段 content，优先引用 `run_outputs.output_id` 和文件路径。

---

## 8. run.duckdb schema

### 8.1 run_meta

保存一次运行的基本信息。

```sql
run_meta(
  run_id TEXT PRIMARY KEY,
  run_mode TEXT,            -- design / runtime
  report_id TEXT,
  table_id TEXT,            -- design 单表时有值，runtime 整报告时可为空
  report_version INTEGER,
  run_params JSON,
  checkpoint_policy TEXT,   -- interactive / auto
  status TEXT,
  started_at TIMESTAMP,
  finished_at TIMESTAMP
)
```

`run_params` 至少包含：

```json
{
  "period_bindings": {
    "本期": "2024Q4",
    "去年同期": "2023Q4",
    "上期": "2024Q3",
    "年初": "2024-01-01",
    "年末": "2024-12-31"
  },
  "org_scope": [
    {
      "branch_num": "27020199",
      "branch_short_name": "王益联社"
    }
  ],
  "output_formats": ["md", "docx"]
}
```

---

### 8.2 run_sections

保存本次运行使用的 section definition 快照。

```sql
run_sections(
  run_id TEXT,
  section_id TEXT,
  report_id TEXT,
  section_key TEXT,
  section_title TEXT,
  section_order INTEGER,
  description_prompt TEXT,
  enabled BOOLEAN,
  metadata JSON,
  PRIMARY KEY(run_id, section_id)
)
```

运行渲染以 `run_sections` 为准，而不是回查 `definitions.duckdb`。

---

### 8.3 run_tables

保存本次运行使用的 table definition 快照。

```sql
run_tables(
  run_id TEXT,
  table_id TEXT,
  report_id TEXT,
  section_id TEXT,
  table_title TEXT,
  table_order INTEGER,
  parsed_payload JSON,
  headers JSON,
  orgs JSON,
  time_info JSON,
  description_prompt TEXT,
  query_failure_policy TEXT,
  compute_failure_policy TEXT,
  description_failure_policy TEXT,
  source TEXT,              -- uploaded_md / approved_definition
  PRIMARY KEY(run_id, table_id)
)
```

Design mode：

```text
source = uploaded_md
```

Runtime mode：

```text
source = approved_definition
```

---

### 8.4 metric_facts

保存本次运行查询到的基础指标事实。

```sql
metric_facts(
  run_id TEXT,
  table_id TEXT,
  branch_num TEXT,
  branch_short_name TEXT,
  idx_id TEXT,
  period_alias TEXT,
  period_value TEXT,
  raw_value TEXT,
  numeric_value DECIMAL(38,10),
  data_unit TEXT,
  status TEXT,
  error_message TEXT,
  PRIMARY KEY(run_id, table_id, branch_num, idx_id, period_alias)
)
```

`period_alias` 与 `period_value` 分开保存：

```text
period_alias: 本期
period_value: 2024Q4
```

公式引用 `BAS_0263@本期`，运行时映射到实际 period value。

---

### 8.5 computed_facts

保存本次运行产生的计算列结果。

```sql
computed_facts(
  run_id TEXT,
  table_id TEXT,
  branch_num TEXT,
  compute_name TEXT,
  value TEXT,
  numeric_value DECIMAL(38,10),
  status TEXT,
  error_message TEXT,
  PRIMARY KEY(run_id, table_id, branch_num, compute_name)
)
```

---

### 8.6 run_events

保存本次运行中的事件和 checkpoint。

```sql
run_events(
  event_id TEXT PRIMARY KEY,
  run_id TEXT,
  step TEXT,
  event_type TEXT,
  status TEXT,
  message TEXT,
  payload JSON,
  created_at TIMESTAMP
)
```

设计模式下的 checkpoint 也记录在这里。

---

### 8.7 run_outputs

保存本次运行输出。

```sql
run_outputs(
  output_id TEXT PRIMARY KEY,
  run_id TEXT,
  table_id TEXT,
  output_type TEXT,         -- table_preview_md / report_design_md / report_md / report_docx / render_json / status_json
  file_path TEXT,
  content TEXT,
  status TEXT,
  payload JSON,
  created_at TIMESTAMP
)
```

---

## 9. 报告章节和表格顺序

报告结构显式保存，不依赖上传顺序。

最终关系：

```text
reports
  └── report_sections ORDER BY section_order
        └── report_tables ORDER BY table_order
```

定义库查询：

```sql
SELECT
  s.section_order,
  s.section_title,
  t.table_order,
  t.table_title,
  t.table_id
FROM report_sections s
JOIN report_tables t
  ON t.section_id = s.section_id
WHERE s.report_id = ?
  AND s.enabled = true
  AND t.approval_status = 'approved'
ORDER BY s.section_order, t.table_order, t.table_id;
```

运行库渲染时改查快照：

```sql
SELECT
  s.section_order,
  s.section_title,
  t.table_order,
  t.table_title,
  t.table_id
FROM run_sections s
JOIN run_tables t
  ON t.run_id = s.run_id
 AND t.section_id = s.section_id
WHERE s.run_id = ?
  AND s.enabled = true
ORDER BY s.section_order, t.table_order, t.table_id;
```

推荐 `table.md` 使用 YAML frontmatter 声明归属和顺序：

```markdown
---
report_id: business_analysis
report_name: 经营分析报告
report_title: 2024年经营分析报告

section_key: deposit_loan
section_title: 二、存贷款业务情况
section_order: 20

table_id: deposit_balance
table_title: 存款余额表
table_order: 10
---

### 存款余额表

...
```

---

## 10. table.md metadata

每张表的 `table.md` 顶部应包含报告归属信息。

推荐字段：

```yaml
report_id: business_analysis
report_name: 经营分析报告
report_title: 2024年经营分析报告
section_key: deposit_loan
section_title: 二、存贷款业务情况
section_order: 20
table_id: deposit_balance
table_title: 存款余额表
table_order: 10
```

这些信息用于：

- upsert `reports`
- upsert `report_sections`
- upsert `report_tables`
- 确定最终渲染顺序
- 支持后续替换、插入、重排表格

---

## 11. runtime 参数绑定

运行模式必须显式传入 period 与机构范围，否则同一个设计无法复用于不同报告期。

### 11.1 period_bindings

`table_metrics.period_alias` 通过 `run_meta.run_params.period_bindings` 绑定到实际时期。

```text
table_metrics.period_alias
→ run_params.period_bindings[period_alias]
→ metric_facts.period_value
```

示例：

```json
{
  "period_bindings": {
    "本期": "2024Q4",
    "去年同期": "2023Q4",
    "上期": "2024Q3"
  }
}
```

如果某个 `period_alias` 没有绑定，runtime 应在执行查询前失败，而不是静默跳过。

### 11.2 org_scope

机构范围分两层：

```text
Design Mode: 默认使用 table.md 中的 orgs，用于设计预览。
Runtime Mode: 优先使用 run_params.org_scope；如果未提供，则 fallback 到 table definition orgs。
```

这样正式运行可以替换机构范围，而不需要重新设计每张表。

---

## 12. compute_sql 生命周期与契约

### 12.1 设计模式

设计模式中可以发生 LLM codegen：

```text
formula_text
→ LLM generate compute_sql
→ DuckDB execute against design run data
→ compute result preview checkpoint
→ render preview
→ 用户确认
→ save compute_sql as approved
```

保存内容：

```text
formula_text       # 人类可读公式
compute_sql        # 机器可执行 SQL
dependencies       # 依赖哪些指标列
examples           # 校验样例
approval_status    # draft / approved / failed / disabled
```

### 12.2 运行模式

运行模式不再生成公式代码：

```text
load approved compute_sql
→ execute in DuckDB
→ write computed_facts
```

这是减少运行时耗时的关键。

### 12.3 compute_sql 输出契约

`compute_sql` 必须满足：

1. 只引用逻辑表名 `table_frame`。
2. 输出必须包含 `branch_num`。
3. 输出一个或多个计算列。
4. 计算列 alias 必须等于 `table_computes.compute_name`。
5. 不负责写入 `computed_facts`，只返回结果集。
6. 不负责处理报告/章节/表格排序。

示例：

```sql
SELECT
  branch_num,
  CASE
    WHEN "BAS_0263@去年同期" IS NULL OR "BAS_0263@去年同期" = 0 THEN NULL
    ELSE ("BAS_0263@本期" - "BAS_0263@去年同期") / "BAS_0263@去年同期"
  END AS "贷款同比增速"
FROM table_frame
```

pipeline 统一负责：

```text
compute_sql result → computed_facts
```

不要让每条 `compute_sql` 自己插表或修改 schema。

---

## 13. table_frame 与计算执行

运行时从 `metric_facts` 生成每张表的宽表 frame。

概念：

```text
metric_facts long table
→ table_frame wide view
→ compute_sql
→ computed_facts
→ render payload
```

`table_frame` 的列名约定：

```text
{idx_id}@{period_alias}
```

例如：

```text
BAS_0263@本期
BAS_0263@去年同期
```

执行每张表的 `compute_sql` 时，运行器为当前 table 绑定逻辑 view `table_frame`。

---

## 14. render_payload 契约

`render_payload` 是数据层和渲染层的唯一接口。`render_markdown.py` / `render_docx.py` 不应直接理解 SQLBot、metric_facts、computed_facts 或 compute_sql。

推荐结构：

```json
{
  "report": {
    "report_id": "business_analysis",
    "report_title": "2024年经营分析报告"
  },
  "sections": [
    {
      "section_id": "deposit_loan",
      "section_title": "二、存贷款业务情况",
      "section_order": 20,
      "tables": [
        {
          "table_id": "deposit_balance",
          "table_title": "存款余额表",
          "table_order": 10,
          "headers": [],
          "rows": [
            {
              "branch_num": "27020199",
              "branch_short_name": "王益联社",
              "cells": {
                "BAS_0263@本期": "1000",
                "贷款同比增速": "8.2%"
              },
              "cell_status": {
                "BAS_0263@本期": "ok",
                "贷款同比增速": "ok"
              }
            }
          ],
          "description_text": "..."
        }
      ]
    }
  ]
}
```

数据准备阶段负责把 `metric_facts` / `computed_facts` / `run_sections` / `run_tables` 合并成这个 payload。渲染阶段只负责版式。

---

## 15. 报表设计 MD 契约

设计阶段的最终产物不仅是数据库 definition，也必须输出一份最终报表设计 MD 文件。

```text
<report_id>.report_design.md
```

这份文件是用户可 review、可归档、可重新导入的设计载体。它应包含完整报告定义，而不是只包含本次上传的单张表。

### 15.1 设计 MD 内容

最终设计 MD 至少包含：

```text
report metadata
sections and ordering
tables and ordering
source table template snapshots
org defaults
period aliases
metric definitions
compute formulas
approved compute_sql references or inline blocks
description prompts
failure policies
last approved design run ids
```

推荐结构：

````markdown
---
report_id: business_analysis
report_name: 经营分析报告
report_title: 2024年经营分析报告
status: active
version: 3
---

## 一、总体经营情况

<!-- section_key: overview; section_order: 10 -->

### 主要经营指标表

<!-- table_id: main_metrics; table_order: 10; approval_status: approved -->

> 机构:
>   branch_num=27020199; branch_short_name=王益联社

> 时期:
>   time_info=["本期", "去年同期"]

<table>
...
</table>

> 计算:
>   贷款同比增速 = (...)

> 描述:
>   请分析主要经营指标变化。

```sql compute_sql:贷款同比增速
SELECT branch_num, ... AS "贷款同比增速"
FROM table_frame
```
````

### 15.2 checkpoint 修改回写规则

设计模式中，用户在 checkpoint 里修改或确认的数据不能只停留在 run 结果里，必须按以下顺序落地：

```text
checkpoint user decision
→ update run_events
→ update draft definition tables
→ regenerate report_design.md
→ render preview / approve
```

例如：

- query checkpoint 中用户选择 `continue_with_sentinel`，应写入 `report_tables.query_failure_policy`。
- compute checkpoint 中用户修正公式，应更新 `table_computes.formula_text` 和 `table_computes.compute_sql`。
- description checkpoint 中用户修正描述要求，应更新 `report_tables.description_prompt` 或 `report_sections.description_prompt`。
- render preview 后用户调整章节/表格顺序，应更新 `report_sections.section_order` / `report_tables.table_order`。

### 15.3 设计 MD 与 DuckDB 的关系

`definitions.duckdb` 是机器执行的权威数据源，`report_design.md` 是用户可 review 的设计快照。

两者必须保持一致：

```text
Design Mode writes definitions.duckdb
→ export report_design.md from definitions.duckdb
→ user reviews report_design.md + preview output
→ approve table/report
```

不要手工拼接设计 MD。它应由 `definitions.duckdb` 导出，保证数据库和文件一致。

---

## 16. checkpoint policy

### 16.1 Design Mode

```text
checkpoint_policy = interactive
```

行为：

- lint 有问题：询问用户是否继续。
- query 完成：总是 checkpoint，和当前流程一致。
- compute SQL 生成或执行后：展示计算列、依赖指标、样例和本次设计数据的计算结果，询问是否接受。
- description 生成后：checkpoint。
- render preview 后：询问用户是否 approve table。

### 16.2 Runtime Mode

```text
checkpoint_policy = auto
```

行为：

- 不向用户提问。
- query 失败：按设计时保存的 policy 自动处理。
- compute 失败：按 policy 写失败哨兵或停止。
- description 失败：按 policy 写失败哨兵或停止。

---

## 17. 设计确认与报告激活

设计模式完整跑完后，不能自动 approve。

### 17.1 approve table

应询问用户：

```text
这张表已生成预览：
- table_preview.md
- table_preview.docx
- status

是否将它保存为「经营分析报告」的 approved table？
```

用户确认后写入：

```sql
update report_tables
set approval_status = 'approved',
    last_design_run_id = ?
where table_id = ?;

update table_metrics
set approval_status = 'approved',
    last_design_run_id = ?
where table_id = ?;

update table_computes
set approval_status = 'approved',
    last_design_run_id = ?
where table_id = ?;
```

如果用户不满意，则保持 draft，等待修改后重新 design run。

### 17.2 preview report

所有关键表格 approved 后，用户应执行完整报告预览：

```text
preview report <report_id>
```

该动作使用 design mode，保留 checkpoint，产出完整报告预览。

### 17.3 activate report

完整报告预览通过后，用户显式激活报告：

```text
activate report <report_id> --preview-run-id <run_id>
```

激活后：

```sql
update reports
set status = 'active',
    activated_run_id = ?,
    updated_at = current_timestamp
where report_id = ?;
```

只有 `status = 'active'` 的 report 才允许 runtime `run report`。

---

## 18. description 生命周期

设计模式确认的是 description prompt 的效果，而不是永远复用同一段 description text。

推荐：

- 设计模式生成 description preview，用户确认 prompt 是否合适。
- 运行模式默认根据当期数据重新生成 description。
- 运行模式无 checkpoint。

可选配置：

```text
description_mode = regenerate | skip | use_template
```

默认：

```text
regenerate
```

---

## 19. 报告级运行优化

正式运行不应该逐表重复查询。

推荐 report-level metric plan：

```text
读取 active report 下所有 approved tables
→ 汇总所有 table_metrics
→ 解析 period_alias 到 period_value
→ 按 idx_id / period_value / org_scope 去重
→ 批量查询 SQLBot
→ 分发到各 table 的 metric_facts
```

优化路径：

```text
Phase 1: 按 table 查询，先跑通
Phase 2: report-level metric dedupe，减少 SQLBot 调用
Phase 3: 并发查询与结果缓存
```

---

## 20. 推荐用户动作

### 20.1 design table

用户说：

```text
把这个 md 作为「经营分析报告」的一张表进行设计
```

系统行为：

```text
完整交互式执行
产出 preview
用户确认后保存 approved table
```

---

### 20.2 export design md

用户说：

```text
导出经营分析报告的设计 MD
```

系统行为：

```text
从 definitions.duckdb 导出完整 report_design.md
包含 checkpoint 中已确认或修改过的最新设计状态
用户可 review、归档或重新导入
```

---

### 20.3 preview report

用户说：

```text
预览整个经营分析报告
```

系统行为：

```text
对所有 draft/approved tables 执行 design-mode report preview
保留 checkpoint
产出完整 report preview
用于整体 review
```

---

### 20.4 activate report

用户说：

```text
激活经营分析报告
```

系统行为：

```text
确认最近一次 report preview 通过
将 report.status 改为 active
允许 runtime 正式运行
```

---

### 20.5 run report

用户说：

```text
运行经营分析报告
```

系统行为：

```text
只使用 active report + approved tables
无 checkpoint
批量执行
产出正式 report.md / report.docx
```

---

## 21. 推荐 CLI

### 21.1 设计命令

```bash
python report_design.py design-table \
  --definitions-db definitions.duckdb \
  --input table.md

python report_design.py inspect \
  --definitions-db definitions.duckdb \
  --report-id business_analysis

python report_design.py approve-table \
  --definitions-db definitions.duckdb \
  --table-id deposit_balance \
  --design-run-id <run_id>

python report_design.py preview-report \
  --definitions-db definitions.duckdb \
  --report-id business_analysis

python report_design.py export-design-md \
  --definitions-db definitions.duckdb \
  --report-id business_analysis \
  --out business_analysis.report_design.md

python report_design.py activate-report \
  --definitions-db definitions.duckdb \
  --report-id business_analysis \
  --preview-run-id <run_id>
```

### 21.2 运行命令

```bash
python report_run.py run \
  --definitions-db definitions.duckdb \
  --report-id business_analysis \
  --period-bindings '{"本期":"2024Q4","去年同期":"2023Q4"}' \
  --org-scope orgs.json \
  --out-dir runs/<run_id>
```

---

## 22. 推荐落地阶段

### Phase 1：定义库与 report/section/table ordering

目标：支持 table.md frontmatter，保存报告/章节/表格结构。

实现：

- `definitions.duckdb`
- `reports`
- `report_sections`
- `report_tables`
- frontmatter 解析
- `inspect report`
- `export-design-md` 初版

此阶段的 `report_design.md` 可以先只导出报告/章节/表格结构，后续阶段逐步补充指标、公式、checkpoint policy 和 preview 产物引用。

---

### Phase 2：Design Mode 单表完整执行

目标：复用当前 pipeline，加入 design run 和 approve table。

实现：

- `run.duckdb`
- `run_meta`
- `run_sections`
- `run_tables`
- `metric_facts`
- `computed_facts`
- `run_events`
- `run_outputs`
- design checkpoint
- checkpoint edits 写回 draft definition
- preview output
- export report_design.md
- approve table

此阶段可以先复用现有 pandas compute，避免 `compute_sql` 成为早期 blocker。

---

### Phase 3：Runtime Mode 完整报告生成

目标：从 approved definitions 生成完整多表报告。

实现：

- report-level run
- run_params period/org 绑定
- 无 checkpoint
- section/table ordering
- render_payload
- report.md
- report.docx

此阶段仍可先复用现有 compute 路径，只要运行模式不需要人工 checkpoint。

---

### Phase 4：compute_sql 设计时固化

目标：运行时不再 LLM codegen。

实现：

- `table_computes.compute_sql`
- compute_sql 输出契约
- 设计时生成 SQL
- 设计时执行验证
- compute result checkpoint
- 用户 approve 后保存
- runtime 直接执行

---

### Phase 5：性能优化

目标：解决多表报告运行过慢。

实现：

- report-level metric dedupe
- SQLBot 并发查询
- 跳过 runtime LLM codegen
- 可选 SQLBot 结果缓存

---

## 23. 最终结论

`ai-report` V2 的最优设计是：

```text
一套 pipeline，两种 mode。
```

- Design Mode：完整执行 + checkpoint + checkpoint 修改写回 definition + 最终预览 + 导出 report_design.md + 用户确认 + 保存 definition。
- Runtime Mode：读取 active definition + 无 checkpoint + 直接执行已保存 compute_sql + 生成完整报告。

数据上分为：

```text
definitions.duckdb  # 长期报告设计资产
run.duckdb          # 单次设计运行或正式运行结果
```

结构上分为：

```text
reports
  └── report_sections
        └── report_tables
              ├── table_metrics
              └── table_computes
```

运行时分为：

```text
run_sections
run_tables
metric_facts
computed_facts
run_outputs
```

这套设计保留当前 checkpoint 的价值，把它放在设计模式；同时让正式运行变成无人工干预的批量生成流程。设计模式中，checkpoint 修改不是临时运行状态，必须写回 `definitions.duckdb`，并从定义库导出最终 `report_design.md`，使用户 review 的文件、数据库定义和后续 runtime 行为保持一致。它比单表即时执行更符合真实报告生产方式，也比单纯 DuckDB compute 改造更完整。

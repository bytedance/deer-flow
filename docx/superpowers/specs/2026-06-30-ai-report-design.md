# ai-report Skill Design Spec

> **Date:** 2026-06-30
> **Status:** Draft (awaiting user review)
> **Author:** brainstorm session (Claude + user)
> **Related:** Greenfield DuckDB architecture: [`docx/chatbi-report/chatbi-report-greenfield-duckdb-architecture.md`](../chatbi-report/chatbi-report-greenfield-duckdb-architecture.md) (conceptual reference, not source code)

---

## 1. Background

`chatbi-report` skill 当前是"单报表单次跑"模型:用户上传一份 `table.md`(单 H1 + 单 table),跑全 pipeline(1-9 step),生成 `report.md` / `report.docx`。每跑一份报告,需要从头跑一遍完整流程。

**现实痛点:** 实际企业经营分析报告是**多章节多表**的(5-15 个 H3 section 拼成一本),如果用 chatbi-report 跑 10 节报告,需要:
- 用户重复上传 10 次 table.md
- 每次跑完 LLM codegen / SQLBot / compute,慢
- 没有"approved 后再跑"的固化机制
- 多节数据无法 cross-check

**ai-report 的目标:** 在 chatbi-report 之上叠加**多章节多表报告能力** + **设计/运行双模式分离** + **DuckDB 持久化**。

---

## 2. Goals

| Goal | Description |
|---|---|
| **G1** | 一份 `report.md` 含 H1/H2/H3 + 多 table,支持完整报告设计 |
| **G2** | 设计模式 (design) 逐 section 交互式设计 + checkpoint,user 满意后 approved |
| **G3** | 运行模式 (runtime) 读取 approved 后的快照,无 checkpoint 一键生成整本 report |
| **G4** | DuckDB 替代 pandas 作数据层;持久层用全局单 DuckDB |
| **G5** | 报告定义 / approved 快照 / final 报告 全部持久化,跨 session 复现 |
| **G6** | ai-report 是**从零开始的全新 skill**,不 import 不复制 chatbi-report 任何代码;数据层纯 DuckDB |

## 3. Non-Goals (Out of Scope)

- ❌ `report_design.md` 导出(只 export `design.md`)
- ❌ `preview-report` / `activate-report` 中间态
- ❌ `org_scope` / `period_bindings` runtime override
- ❌ Report-level metric dedupe
- ❌ DuckDB keyword blacklist(沙箱逃逸风险暂不防)
- ❌ Multi-report cross-JOIN
- ❌ 报告 version diff
- ❌ status.json 落盘
- ❌ `unit_conversion.py` import 或保留
- ❌ chatbi-report `compute.py` 加 flag 改造
- ❌ 改 chatbi-report 任何文件
- ❌ 多用户协作(同一 report 多 user 同时 design)
- ❌ 跨 session 报告迁移工具
- ❌ 默认写中间产物到 per-thread `/mnt/user-data/outputs/`(仅 `--debug` 例外,见 §8.1)

---

## 4. Architecture Overview

### 4.1 Skill 边界

```
ai-report (新, 从零开始, 16 个 scripts 全部新写)
    ↓ 参考 (不 import / 不复制) chatbi-report 源码
chatbi-report (已有, 不动)
```

**ai-report 不 import chatbi-report 任何 module,不复制 chatbi-report 任何代码块。可以读 chatbi-report 源码学习算法 / 模式 / lint 规则 / 库选择,但在 ai-report 目录重新写。**

### 4.2 触发与输入

| 模式 | Trigger | Input | Output |
|---|---|---|---|
| **design** | 默认,或用户说"设计"/"设计这个" | `report.md`(整本) | 回填后的 `design.md` + DuckDB approved 快照 |
| **runtime** | 用户明确说"运行报告"/"生成报告" | `report_id` | 整本 `report.md` + `report.docx` |

**SKILL.md 必须明确"默认是 design"**。

### 4.3 顶层架构图

```
┌─────────────────────────────────────────────────────────────┐
│  ai-report skill (skills/public/ai-report/)                  │
│                                                              │
│  SKILL.md                                                    │
│  prompts/{compute_codegen.md, description_gen.md}            │
│  references/{pipeline.md, runtime.md, checkpoints.md,       │
│              status-output.md, data-flow.md}                │
│  scripts/                                                    │
│    report_split.py, duckdb_store.py,                        │
│    design_pipeline.py, runtime_pipeline.py,                 │
│    report_md.py, report_docx.py, unit_convert.py,           │
│    assemble_status.py, compute.py, parse_md.py,             │
│    sqlbot_client.py, render_markdown.py, render_docx.py,    │
│    md_lint.py, retry.py, report_style.json                  │
│  tests/                                                      │
│  example/wangyi_2026_03.md                                   │
└─────────────────────────────────────────────────────────────┘
        ↓ 参考 (不 import)
┌─────────────────────────────────────┐
│  chatbi-report scripts (只读)        │
│  parse_md.py / compute.py /         │
│  render_*.py / sqlbot_client.py /   │
│  md_lint.py / retry.py /            │
│  assemble_status.py /               │
│  report_style.json                  │
└─────────────────────────────────────┘
```

### 4.4 数据流总览

**DESIGN 模式 (单 section):**
```
report.md → md_lint → report_split → duckdb_store.upsert_*
  → [per section]:
      parse_md → report_tables.parsed_payload
      sqlbot_client → metric_facts (DuckDB)
      checkpoint 3.5 (always-trigger)
      compute.assemble-wide (DuckDB PIVOT) → 内存 wide table
      compute.extract-ir (JSON)
      LLM codegen → compute.<slug>.sql
      compute.validate (EXPLAIN + FROM wide + branch_num + smoke + example)
      compute.evaluate (跑 SQL, 写哨兵)
      compute.apply-computed (DuckDB INSERT)
      unit_convert (DuckDB UPDATE 应用单位换算)
      LLM describe
      checkpoint 8d.5
      render preview
      checkpoint 10 (approve / reject)
      → duckdb_store.save_approved_run + 回填 report.md
```

**RUNTIME 模式 (整本):**
```
report_id
  → duckdb_store.list_approved_tables (按 section_order, table_order)
  → 对每张表读 approved_table_runs.wide_table
  → 拼 render_payload
  → render_markdown 整本
  → render_docx 整本
  → 输出中文回执
```

---

## 5. Components

### 5.1 DuckDB Schema (5 张表)

**DB 路径:** `/mnt/ai-report-data/duckdb/ai-report.duckdb` (全局单库,所有报告共享)

**Schema 版本:** Phase 1 锁定 `schema_version=1`。所有 5 张表带 `schema_version INTEGER NOT NULL DEFAULT 1` 字段;Phase 2 加 migrate 工具按 version 平滑升级。

```sql
-- 1/5 reports (报告级)
CREATE TABLE reports (
  report_id        TEXT PRIMARY KEY,
  schema_version   INTEGER NOT NULL DEFAULT 1,
  report_title     TEXT NOT NULL,
  source_md_path   TEXT NOT NULL,
  source_md_hash   TEXT NOT NULL,
  created_at       TIMESTAMP NOT NULL DEFAULT current_timestamp,
  updated_at       TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- 2/5 report_sections (章 H2)
CREATE TABLE report_sections (
  section_id       TEXT PRIMARY KEY,
  schema_version   INTEGER NOT NULL DEFAULT 1,
  report_id        TEXT NOT NULL REFERENCES reports(report_id),
  section_order    INTEGER NOT NULL,
  section_title    TEXT NOT NULL,
  created_at       TIMESTAMP NOT NULL DEFAULT current_timestamp,
  UNIQUE(report_id, section_order)
);

-- 3/5 report_tables (节 H3 + 设计元数据)
CREATE TABLE report_tables (
  table_id              TEXT PRIMARY KEY,
  schema_version        INTEGER NOT NULL DEFAULT 1,
  report_id             TEXT NOT NULL REFERENCES reports(report_id),
  section_id            TEXT NOT NULL REFERENCES report_sections(section_id),
  table_order           INTEGER NOT NULL,
  table_title           TEXT NOT NULL,
  approval_status       TEXT NOT NULL DEFAULT 'draft'
                            CHECK (approval_status IN ('draft','approved','rejected')),
  source_md_snapshot    TEXT NOT NULL,
  source_md_hash        TEXT NOT NULL,
  parsed_payload        JSON NOT NULL,
  last_design_run_id    TEXT,
  created_at            TIMESTAMP NOT NULL DEFAULT current_timestamp,
  updated_at            TIMESTAMP NOT NULL DEFAULT current_timestamp,
  UNIQUE(report_id, section_id, table_order)
);
CREATE INDEX idx_report_tables_status ON report_tables(report_id, approval_status);

-- 4/5 metric_facts (Step 2 写的原始事实,带 run_id 历史)
CREATE TABLE metric_facts (
  run_id              TEXT NOT NULL,
  schema_version      INTEGER NOT NULL DEFAULT 1,
  table_id            TEXT NOT NULL REFERENCES report_tables(table_id),
  report_id           TEXT NOT NULL,
  branch_num          TEXT NOT NULL,
  branch_short_name   TEXT,
  idx_id              TEXT NOT NULL,
  period_alias        TEXT NOT NULL,
  period_value        TEXT,
  raw_value           TEXT,
  numeric_value       DECIMAL(38,10),
  status              TEXT NOT NULL,            -- 'ok' / 'query_failed' / 'cast_failed'
  error_message       TEXT,
  created_at          TIMESTAMP NOT NULL DEFAULT current_timestamp,
  PRIMARY KEY(run_id, table_id, branch_num, idx_id, period_alias)
);
CREATE INDEX idx_metric_facts_run ON metric_facts(run_id, table_id);

-- 5/5 approved_table_runs (approved 后落盘的快照,带 run_id 历史)
CREATE TABLE approved_table_runs (
  run_id              TEXT NOT NULL,
  schema_version      INTEGER NOT NULL DEFAULT 1,
  table_id            TEXT NOT NULL REFERENCES report_tables(table_id),
  report_id           TEXT NOT NULL,
  section_id          TEXT NOT NULL,
  wide_table          JSON NOT NULL,
  computed_columns    JSON NOT NULL DEFAULT '[]',
  descriptions        JSON NOT NULL DEFAULT '[]',
  status              TEXT NOT NULL,            -- 'ok' / 'partial_with_sentinel' / 'aborted'
  sentinels           JSON NOT NULL DEFAULT '[]',
  runlog_markdown     TEXT NOT NULL,
  design_md_path      TEXT NOT NULL,            -- 总是指向 /mnt/ai-report-data/<report_id>.design.md
  created_at          TIMESTAMP NOT NULL DEFAULT current_timestamp,
  PRIMARY KEY(run_id, table_id)
);
CREATE INDEX idx_approved_runs_table ON approved_table_runs(table_id, created_at DESC);
```

### 5.2 文件清单 (16 个 scripts 全部新写)

```
skills/public/ai-report/scripts/
├── report_split.py        # H2/H3 切分 + report.md → sections list
├── duckdb_store.py        # 5 张表 CRUD + 单位换算 UPDATE 生成 + run_id 历史管理
├── design_pipeline.py     # 单 section design (LangGraph make_lead_agent 入口)
├── runtime_pipeline.py    # 整本 runtime (5 step)
├── report_md.py           # 整本 report.md 拼版
├── report_docx.py         # 整本 report.docx 拼版 (多 section 模板)
├── unit_convert.py        # 单位换算 SQL 生成 (硬编码单位字典)
├── assemble_status.py     # status 输出 (report_id + per-section)
├── compute.py             # ~150 行,纯 DuckDB
│                            - assemble-wide = DuckDB PIVOT
│                            - extract-ir = 纯 JSON
│                            - validate = EXPLAIN + FROM wide + branch_num
│                            - evaluate = smoke 3 行 + example 1 行
│                            - apply-computed = DuckDB INSERT
├── parse_md.py            # 新写,支持 H1/H2/H3 + table + 多 table in one report
├── sqlbot_client.py       # 新写,httpx 客户端
├── render_markdown.py     # 新写,多 section 渲染
├── render_docx.py         # 新写,多 section 渲染
├── md_lint.py             # 新写,per-section error 归类
├── retry.py               # 新写,retry 退避
└── report_style.json      # 新写,style config
```

---

## 6. Data Flow

### 6.1 Design 模式 — 整本首次导入

```
input:  report.md (用户上传 /mnt/user-data/uploads/<file>.md)
Step 0: md_lint (整本)
        ↓ pass
        report_split (H1/H2/H3 + tables 切分)
        ↓
        duckdb_store.upsert_report / upsert_section / upsert_table
        (所有 table approval_status='draft')
output: DuckDB reports/sections/tables 全 draft
        /mnt/ai-report-data/<report_id>.design.md 初始
```

### 6.2 Design 模式 — 单 section 处理

```
Step 1: parse_md → parsed_payload (写 report_tables.parsed_payload)
Step 2: sqlbot_client → metric_facts (写新 run_id)
Step 3: checkpoint 3.5 (always-trigger, user 拍板 continue/stop)
Step 4: compute.assemble-wide (DuckDB PIVOT metric_facts → 内存 wide)
Step 5: compute.extract-ir (JSON, 公式 IR)
Step 6: LLM codegen → compute.<slug>.sql (DuckDB SQL)
Step 7: compute.validate (EXPLAIN + FROM wide + branch_num + smoke + example)
Step 8: compute.evaluate (跑 SQL, 写哨兵 ⚠️COMPUTE_FAILED)
Step 9: compute.apply-computed (DuckDB INSERT INTO wide)
Step 10: unit_convert (DuckDB UPDATE 应用 元→目标单位 换算)
Step 11: LLM describe
Step 12: checkpoint 8d.5
Step 13: render preview
Step 14: checkpoint 10 (approve / modify / reject) [ai-report 新加]
        ↓ approve
        duckdb_store.save_approved_run (新 run_id, wide_table 快照)
        report_tables.approval_status = 'approved'
        回填 /mnt/ai-report-data/<report_id>.design.md (该 H3+table 块)
```

**Lint 1.5 是 per-report**(Step 0 一次跑全本,per-section 报错归类);其余 checkpoint 都是 per-section。

### 6.3 Design 模式 — section 间推进

```
Section N approved 后
→ checkpoint 11:
    "继续下一节 (按 section_order) / 设计指定节 / 预览整本 / 完成"
```

### 6.4 Runtime 模式

```
input:  --report-id wangyi_2026_03
Step R-0: duckdb_store.get_report_meta (存在性检查, source_md_hash 警告)
Step R-1: 拉 approved sections (按 section_order, table_order)
          if 无 approved → exit 1 (--strict) or 渲染空报告
Step R-2: 拼 render_payload (单 dict, 全报告 sections/tables/cells)
Step R-3: render_markdown 拼整本 report.md
Step R-4: render_docx 拼整本 report.docx
Step R-5: 输出中文最终回执
output:
  /mnt/ai-report-data/<report_id>.report.md
  /mnt/ai-report-data/<report_id>.report.docx
  stdout 中文回执
```

**未 approved section 默认跳过**;`--strict` 严格模式要求全 approved 才跑。

---

## 7. Error Handling

### 7.1 哨兵契约总表 (5 个)

| 哨兵 | 来源 | 触发 | 粒度 |
|---|---|---|---|
| `⚠️QUERY_FAILED` | Step 2 sqlbot_client | HTTP 错 / 业务错 | per-cell |
| `⚠️CAST_FAILED` | Step 2 metric_facts TRY_CAST | TRY_CAST 失败 | per-cell |
| `⚠️COMPUTE_FAILED` | Step 7/8 validate/evaluate | EXPLAIN 失败 / FROM wide 缺失 / branch_num 缺失 / smoke / example 失败 | per-compute-column |
| `⚠️DESCRIPTION_FAILED` | Step 11 LLM describe | LLM 失败 (regenerate 1 次后) | per-section |
| `⚠️LINT_FAILED` | Step 0 lint | per-section 报错归类 | per-section |

**不引入 `⚠️UNIT_CONVERTED_FAILED`** —— 元→目标单位是纯数学操作,无业务失败模式。

### 7.2 Checkpoint 行为

| 编号 | 触发点 | 粒度 | 阻塞? | 调用方式 |
|---|---|---|---|---|
| 0 | Step 0 lint 失败 | 整本 | ✅ 阻塞整本 | `ask_clarification(clarification_type="risk_confirmation")` |
| 1.5 | Step 0 lint pass | 整本 | ❌ (informational) | 展示 per-section findings |
| 3.5 | Step 3 query | per-section | ❌ per-section | always-trigger (2026-06-27 反转政策) |
| 8d.5 | Step 11 describe | per-section | ❌ per-section | 仅当该 section 有 `> 描述:` 块 |
| 10 | Step 14 preview | per-section | ❌ per-section | approve / modify / reject (ai-report 新加) |
| 11 | Section N approved | 整本 | ❌ (推进) | 继续 / 跳节 / 预览 / 完成 |

**所有 checkpoint 走 `ask_clarification(..., clarification_type="risk_confirmation", ...)` 异步等**,和 chatbi-report 同构。

**Checkpoint ID 映射说明:** Checkpoint `1.5` / `3.5` / `8d.5` 沿用 chatbi-report 编号惯例(chatbi-report 的 step 1-9 子步骤),不是 ai-report 自己的 Step 0-14 编号。映射关系:
- Checkpoint 1.5 → ai-report Step 0 lint pass 后
- Checkpoint 3.5 → ai-report Step 2 sqlbot_client 后
- Checkpoint 8d.5 → ai-report Step 11 describe 后
- Checkpoint 0 / 10 / 11 是 ai-report 新加的(无 chatbi-report 对应)

### 7.3 数据完整性

- `reports.source_md_hash` (sha256 of 原 report.md) — 改 MD 后 detect
- `report_tables.source_md_hash` (sha256 of 该 H3+table 块) — section 级 detect
- `report_tables.source_md_snapshot` (MD 块原文) — 历史快照

**默认 runtime 忽略 hash 不一致**(因为读的是 `last_design_run_id` 快照);`--warn-source-md-changed` flag warn。

**事务边界:** per-section design run 是完整事务(metric_facts + approved_table_runs 一起写);runtime 是纯读,无事务。

### 7.4 Runtime 失败兜底

| 场景 | 默认行为 | --strict 行为 |
|---|---|---|
| reports 不存在 | exit 1 报错 | exit 1 报错 |
| 全部 draft | 渲染空报告 | exit 1 报错 |
| approved_table_runs 缺失 | skip 该 section | exit 1 报错 |
| 单 section render 失败 | 哨兵占位,继续 | exit 1 报错 |

---

## 8. Contracts (强制对外契约)

### 8.1 文件输出

| 输出 | 默认 | --debug | 路径 |
|---|---|---|---|
| `ai-report.duckdb` (全局单库) | ✅ 必写 | ✅ | `/mnt/ai-report-data/duckdb/ai-report.duckdb` |
| `<report_id>.design.md` | ✅ 必写 | ✅ | `/mnt/ai-report-data/<report_id>.design.md` |
| `<report_id>.report.md` | ✅ 必写 | ✅ | `/mnt/ai-report-data/<report_id>.report.md` |
| `<report_id>.report.docx` | ✅ 必写 | ✅ | `/mnt/ai-report-data/<report_id>.report.docx` |
| `status.json` | ❌ **不写** | ❌ | drop 整个概念 |
| `<stem>.parsed.json` | ❌ | ✅ | `/mnt/user-data/outputs/<report_id>.<table_id>.parsed.json` |
| `<stem>.query.json` | ❌ | ✅ | (实际不需要,DuckDB 接管) |
| `<stem>.wide.json` | ❌ | ✅ | (实际不需要) |
| `<stem>.ir.json` | ❌ | ✅ | (实际不需要) |
| `<stem>.runlog.md` | ❌ | ✅ | (实际存 DuckDB runlog_markdown 列) |

**原则:默认零中间产物,数据全在 DuckDB 内存和 5 张表里。**

### 8.2 单位换算契约

- **SQLBot 源单位固定 = 元**(metric_facts.numeric_value 直接 TRY_CAST,无单位识别)
- 目标单位来自 `<th data-unit="...">`
- 换算在 DuckDB SQL 端做 (PIVOT 后 UPDATE wide):
  - 目标=元:无换算
  - 目标=万元:`col = col / 10000`
  - 目标=亿元:`col = col / 100000000`
  - 目标=%(只计算列):`col = col * 100`
  - 目标=其他:无换算
- 换算不写哨兵,SQL 数学操作无业务失败
- 不 import `unit_conversion.py`;单位字典硬编码在 `unit_convert.py`
- 应用层从 `parsed_payload` 读出每列 `data_unit`,动态拼 UPDATE

### 8.3 Compute 5 层校验契约 (无 keyword blacklist)

ai-report `compute.validate`:
1. **EXPLAIN 通过** —— DuckDB parser/binder 接受
2. **FROM wide** —— 必含 wide 表引用
3. **branch_num 输出** —— SELECT 必须含 branch_num
4. **smoke 3 行** —— SAMPLE 3 ROWS 跑通
5. **example 1 行** —— `math.isclose` 校验

**不**做关键字黑名单(LOAD/INSTALL/COPY/EXPORT/ATTACH/DETACH/PRAGMA 等)。DuckDB 沙箱逃逸风险 Phase 1 承担。

### 8.4 Compute 输出契约

- `compute_sql` 必须含 `FROM wide`,输出列含 `branch_num` + ≥1 计算列(别名匹配 `> 计算:` 里的虚拟名)
- 失败 → `status='compute_failed'`,对应 cell 写 `⚠️COMPUTE_FAILED`

### 8.5 4 层 Validation 之外的 chatbi-report 风格兜底

- LLM codegen:regenerate 1 次,2 次失败 → ⚠️COMPUTE_FAILED
- LLM describe:regenerate 1 次,2 次失败 → ⚠️DESCRIPTION_FAILED
- 整体:任何 step 中基础设施错(DuckDB 连不上 / 文件 IO 错)→ exit 1 报错,不是哨兵

---

## 9. Testing

### 9.1 Unit Tests

| 模块 | 测什么 |
|---|---|
| `report_split.py` | H2/H3 切分 / 单 H2 含多 H3 / H1+H2+H3 嵌套 / 空 table / 多 table in one H3 |
| `duckdb_store.py` | 5 表 CRUD / run_id 历史保留 / FK 级联 / 重复 section_order 报错 |
| `unit_convert.py` | 元/万元/亿元/% × {基础列, 计算列} 8 种组合 |
| 5 个哨兵 | 每个哨兵触发场景 + 写 cell 验证 |
| `source_md_hash` 检测 | hash 一致 / 不一致 |

### 9.2 Integration Tests

| 场景 | 期望 |
|---|---|
| design 单 section happy path | metric_facts + approved_table_runs 有新 run, design.md 回填 |
| design 单 section 失败路径 | ⚠️QUERY_FAILED 写 cell, 3.5 触发 |
| design 计算列 | DuckDB SQL 拼出, validate 过, apply-computed 后 cell 有值 |
| design 单位换算 | UPDATE 拼出 `col / 10000` |
| design 计算列 % 换算 | UPDATE 拼出 `col * 100` |
| runtime 整本 | 整本 md + docx 渲染, 章节顺序正确 |
| runtime 未 approved section | 默认跳过, --strict 报错 |
| source_md_hash 改动 | runtime 仍跑快照, --warn-source-md-changed warn |

### 9.3 Fixtures (ai-report 私有, 不依赖 chatbi-report)

```
skills/public/ai-report/tests/
  fixtures/
    sample_report.md
    mock_sqlbot/    ← ai-report 自己写
    expected/
      design_after_approve.md
      report.md
      report.docx
```

---

## 10. Deliverables

### 10.1 新增文件 (16 scripts + 2 prompts + 5 references + 11 test files + 1 example + 1 SKILL.md)

```
skills/public/ai-report/
├── SKILL.md
├── prompts/{compute_codegen.md, description_gen.md}
├── references/{pipeline.md, runtime.md, checkpoints.md, status-output.md, data-flow.md}
├── scripts/ (16 个, 全部新写, 见 §5.2)
├── tests/
│   ├── fixtures/{sample_report.md, mock_sqlbot/, expected/}
│   ├── test_report_split.py
│   ├── test_duckdb_store.py
│   ├── test_unit_convert.py
│   ├── test_sentinels.py
│   ├── test_parse_md.py
│   ├── test_sqlbot_client.py
│   ├── test_render_markdown.py
│   ├── test_render_docx.py
│   ├── test_md_lint.py
│   ├── test_design_pipeline.py
│   └── test_runtime_pipeline.py
└── example/wangyi_2026_03.md
```

### 10.2 修改文件

**0 个**。chatbi-report 不动。

### 10.3 文档

| 文件 | 状态 |
|---|---|
| `docx/superpowers/specs/2026-06-30-ai-report-design.md` | 本 spec |
| `docx/superpowers/plans/2026-06-30-ai-report-impl.md` | writing-plans 阶段产出 |
| `docx/ai-report/archive/2026-06-30-v2-design-discussion-draft.md` | 已在 archive,不动 |
| `CLAUDE.md` (项目根) | 加 ai-report 段 |

---

## 11. Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| LLM codegen DuckDB SQL 一次成功率 < 80% | 中 | 高 | Few-shot 5+, retry 一次, 监控 codegen 成功率 |
| 多 section design 总耗时长 (5-30s × N) | 高 | 中 | Phase 1 接受, Phase 2 并发 design |
| Runtime 渲染与 design preview 不一致 | 中 | 高 | 同 render 函数 + 同 wide_table snapshot |
| DuckDB 文件 corruption | 低 | 高 | 写时 .bak 备份, 启动 integrity check |
| `/mnt/ai-report-data` 容量增长 | 低 | 中 | 监控, Phase 2 archive 工具 |
| 单位换算 SQL 拼错 | 中 | 高 | `test_unit_convert.py` 8 种组合验证 |
| Schema 变更影响已 approved 报告 | 低 | 高 | Schema 加 `version` 字段, 写 migrate 工具 |
| 用户上传 report.md 不规范 | 中 | 低 | Step 0 lint 拦截, checkpoint 0 阻断 |
| `source_md_hash` 与 `source_md_snapshot` 竞态 | 低 | 中 | snapshot 写库时算 hash, read-time 校验 |

---

## 12. Migration Path

### Phase 1 (本期, 目标 1-2 周)

- [ ] 新建 `skills/public/ai-report/` 完整目录
- [ ] 5 张表 schema + duckdb_store.py
- [ ] report_split.py + unit_convert.py
- [ ] parse_md.py / sqlbot_client.py / render_markdown.py / render_docx.py / md_lint.py / retry.py / report_style.json (新写, 参考 chatbi-report)
- [ ] compute.py 新写 (纯 DuckDB, ~150 行)
- [ ] design_pipeline.py (LangGraph make_lead_agent 入口)
- [ ] runtime_pipeline.py
- [ ] assemble_status.py
- [ ] mock SQLBot 私有 fixtures
- [ ] 跑通 sample (王益联社 2026 年 3 月)
- [ ] 中文进度 / 最终回执

**Phase 1 完成标准:**
- 王益联社 sample 5 节全 approved, runtime 拼出 md + docx
- ai-report 16 scripts 全部新写, 不 import chatbi-report 任何代码
- 5 张表 schema 锁定

### Phase 2 (v2)

- Report-level metric dedupe
- 并发 design
- DuckDB keyword blacklist (security hardening)
- 报告 version diff

### Phase 3 (v3)

- Multi-report cross-JOIN
- Activation / preview-report workflow
- 自动 report_design.md 导出

---

## 13. Success Criteria

- [ ] 王益联社 sample 在 ai-report 里 design 5 节全 approved
- [ ] runtime `wangyi_2026_03` 一键跑出整本 `report.md` + `report.docx`
- [ ] 报告内容与 design 时 approved 的快照**完全一致**
- [ ] ai-report 16 scripts 全部新写, 无 `from chatbi_report` import
- [ ] LLM codegen 一次成功率 ≥ 80%
- [ ] Runtime 整本 5 section ≤ 5s
- [ ] `/mnt/ai-report-data/ai-report.duckdb` 单文件 < 100MB (5 报告)
- [ ] 中文最终回执:章节数、cell 哨兵数、未设计章节、生成路径 4 项齐全

---

## 14. Decisions Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-30 | ai-report 是新 skill, 不替代 chatbi-report | 用户拍板 |
| 2026-06-30 | 5 张表 (精简 V2 13 表) | 用户 "先不要很复杂" |
| 2026-06-30 | 模式 trigger 按用户 prompt 关键词 (默认 design) | 用户拍板 |
| 2026-06-30 | Runtime 只传 report_id, 读 approved 快照 | 跨 session 复现, 避免重查 |
| 2026-06-30 | 全局单 DuckDB (非 per-report) | 用户拍板 |
| 2026-06-30 | 默认零中间产物文件, --debug 才写 | 用户拍板 |
| 2026-06-30 | status.json drop | 用户拍板 |
| 2026-06-30 | LangGraph + make_lead_agent + ask_clarification (对齐 chatbi-report) | 用户 "刚才判断失误" |
| 2026-06-30 | Lint per-report 跑, per-section 报错 | "先不要很复杂" |
| 2026-06-30 | run_id 历史保留 (回滚) | 用户 "需要 run 历史" |
| 2026-06-30 | approval_status: draft/approved/rejected | 回滚 |
| 2026-06-30 | approved_table_runs.status: ok/partial_with_sentinel/aborted | 回滚 |
| 2026-06-30 | Compute 4 层校验无 keyword blacklist (Phase 1) | 用户 "先不要考虑" |
| 2026-06-30 | SQLBot 源单位 = 元 (固定) | 用户拍板 |
| 2026-06-30 | 单位换算 DuckDB SQL 端 (不 import unit_conversion.py) | 用户 "DuckDB 模式不适合" |
| 2026-06-30 | % 单位换算考虑 (基础列不适用, 计算列 × 100) | 用户拍板 |
| 2026-06-30 | ai-report 不 import chatbi-report 任何代码, 不复制, 不保留 pandas | 用户 "再次声明澄清, 很重要" |
| 2026-06-30 | ai-report 可参考 chatbi-report 源码 (读 + 借鉴), 但在 ai-report 重新写 | 用户 "MD 解析 Lint SQLBot 渲染 尽可能参考" |

---

## 15. Open Questions

无 (2026-06-30 brainstorm 已全部对齐)。

---

## 16. Approval

- [ ] User reviews spec at `docx/superpowers/specs/2026-06-30-ai-report-design.md`
- [ ] User accepts / requests changes
- [ ] Proceed to writing-plans skill

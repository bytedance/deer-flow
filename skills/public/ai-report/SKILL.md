---
name: ai-report
version: 0.1.0
description: |
  Generate a backfilled Markdown report and DOCX from a Markdown 报表样张
  whose `<th>` cells carry `data-idx` + `data-period` indicators, `> 计算:`
  DuckDB-SQL computed columns, and `> 描述:` narrative prompts. Use this
  skill whenever the user asks to generate / run / fill / render an ai-report
  sample, render a multi-section banking-style report, run the SQLBot →
  DuckDB pipeline, or review intermediate design/runtime checkpoints. Do
  NOT use for free-form tables without `data-idx`, pure statistical
  analysis (use data-analysis instead), single-cell spreadsheets, the
  legacy pandas-based chatbi-report workflow, audio/video/image OCR
  (use markitdown), or files that only need ordinary reading.
license: internal
---

# ai-report Skill

从一份 Markdown 样张生成结构化报告:lint + 解析样张、SQLBot 按指标取数、
DuckDB 拼装宽表、LLM 生成 DuckDB SQL 计算列、Python 端 `Decimal` 单位
换算、可选的中文描述、最终渲染 `report.md` / `report.docx`。

本 skill 是 checkpoint 密集型的。用户必须在 lint、SQLBot 查询、描述生成、
预览批准这六个检查点显式确认。

## 触发匹配规则

满足以下任一组合时,lead agent 应加载本 skill:

- 报表类动词 + 含 `<th data-idx=` 的 MD 文件
- 报表类动词 + 含 `> 计算:` 或 `> 描述:` 的 MD 文件
- 用户说 "跑 ai-report 样张" / "出 docx" / "生成王益联社月报" / "render
  ai-report" / "fill ai-report template"
- 用户在 design pipeline 中途需要重新批准 / 重新跑某个 section

**触发关键词**(用于 skill loader 的 description 匹配):

- `ai-report`, `王益联社月报`, `生成报表`, `跑样张`, `回填 ai 模板`
- `render ai-report`, `fill ai-report template`, `generate ai-report`
- `出 docx`, `出 ai 报表`

**不触发**(下列场景用别的 skill):

| 场景 | 用什么 |
|---|---|
| 自由格式 MD 表格,无 `data-idx` / `> 计算:` | 直接回答 / data-analysis |
| 旧版 pandas 流程的 chatbi 样张 | chatbi-report(legacy) |
| 纯统计 / Excel 透视 | data-analysis |
| 读 PDF / PPT / 图片 OCR | markitdown |
| 单个文件普通阅读总结 | 直接 Read |
| 改 skill 自身 | 显式说 "修改 ai-report skill" 才进入 |

## 运行模式

| 模式 | 触发条件 | 行为 |
|---|---|---|
| `design` | 用户说"跑样张"/"设计"/首跑某 report_id | 走 14-step design pipeline + 6 checkpoints,产出 `approved_runs` |
| `runtime` | 用户说"出 docx"/"渲染"/"重渲染",且已有 approved_runs | 走 5-step runtime pipeline,只读 `approved_runs` 写最终文件 |
| `lint-only` | 用户说"先 lint 看看"/"检查样张" | 只跑 Step 0 + 1.5 |
| `strict` | CI / 烟囱测试 | runtime 模式下加 `--strict`,R-1 空时改 RuntimeError |

design 模式与 runtime 模式可以分开调用:先 design 走完所有 checkpoint,
approved 后再 runtime 出文件。运行时可以反复调(同 report_id 多次),
只读最新 approved_runs。

## 沙箱路径

| 类型 | 路径 |
|---|---|
| 用户上传 | `/mnt/user-data/uploads/<file>.md` |
| DuckDB 数据 | `/mnt/ai-report-data/duckdb`(全局单文件,非 per-report) |
| 设计样张产物 | `/mnt/ai-report-data/<report_id>.design.md` |
| 最终 MD | `/mnt/ai-report-data/<report_id>.report.md` |
| 最终 DOCX | `/mnt/ai-report-data/<report_id>.report.docx` |
| 最终状态 | `/mnt/ai-report-data/<report_id>.status.json` |
| 脚本 | `/mnt/skills/public/ai-report/scripts/*.py` |
| LLM prompt | `/mnt/skills/public/ai-report/prompts/{compute_codegen,description_gen}.md` |
| 参考文档 | `/mnt/skills/public/ai-report/references/*.md` |
| 样张示例 | `/mnt/skills/public/ai-report/example/wangyi_2026_03.md` |

`/mnt/ai-report-data/` 是 ai-report 独立的数据根,**不是** `/mnt/user-data/`。
所有 ai-report 产物(metadata / DuckDB / 最终文件)都进 ai-report-data。
相关 memory:`ai-report-global-duckdb-path`。

## Pipeline 快速预览

```text
DESIGN (per section)
0 lint → 1.5 lint checkpoint
→ 2 query (per-idx SQLBot) → 3.5 query checkpoint
→ 4 assemble-wide → 5 extract-ir
→ 6 codegen (LLM DuckDB SQL) → 7 validate → 8 evaluate → 9 apply-computed
→ 10 unit_convert (Python Decimal) → 11 describe
→ 8d.5 description checkpoint (only if `> 描述:` provided)
→ 12 preview checkpoint → 14 save approved run
→ 13 post-section checkpoint

RUNTIME (per report)
R-0 existence → R-1 list approved → R-2 build payload
→ R-3 render md → R-4 render docx → R-5 中文回执 + status.json
```

详细步骤、命令、retry budget、进度消息模板见
`references/pipeline.md`。

## SQLBot 数据源(real / mock)

ai-report 走 chatbi-report 1:1 镜像的 SQLBot client 协议(per-idx 调用约定
`org_info` + `index_info=[{"idx_id":...}]` + `time_info`,响应里
`data[].{org_ecd, value, data_dt, idx_name}`)。同一份
`scripts/sqlbot_client.py` 既能打真实 endpoint,也能读 mock fixture
跑测试。OrgContext 字段是 ai-report 自己的 `org_ecd` / `org_name`(不是
chatbi-report 的 `branch_num` / `branch_short_name`)。

仓库内自带两份 sample fixture(均覆盖 wide-wide `idx_id@period` / 简
`idx_id` 两种 key 形式),都可用作 `--mock-fixture` 或直接喂给
`MockSQLBotClient`:

- `tests/fixtures/mock_sqlbot/wangyi_2026_03.json` — 6 个 BAS_xxx 指标 ×
  202602/202603 两个时点,对应 `example/wangyi_2026_03.md` 样张(E2E 默认)
- `example/mock_sqlbot/profit_yoy.json` — 1 个 `BAS_0263` × 2022-2025
  四年 × 4 个 org(王益联社 / 印台联社 / 铜川平均值 / 全省平均值),从
  chatbi-report 仓库直接 copy 过来,用于多 org / 多期对比场景

注:profit_yoy.json 的 `org_ecd` 字段是中文简称(王益联社),不是 wangyi
sample 的英文 ecd 代码;搭配时需在 example MD 的 `> 机构:` 块用
`branch_short_name=王益联社` 等简称(ai-report 自动把 chatbi-report
风格的 `branch_short_name` 映射到内部 `org_ecd`)。`example/profit_yoy.md`
镜像了 chatbi-report `example/input.md` 的 MD 风格(`branch_num=X;
branch_short_name=Y` + `name = prompt` 计算块 + `<name>.示例:` 例子),可
直接与该 fixture 配对跑通。

| 场景 | 用什么 | 触发方式 |
|---|---|---|
| 真实 SQLBot | `RealSQLBotClient` | 设 `SQLBOT_BASE_URL=http://...` 或 CLI `--base-url` |
| Mock (默认 fixture) | `MockSQLBotClient` | CLI `--mock`(用 `tests/fixtures/mock_sqlbot/wangyi_2026_03.json`) |
| Mock (指定 fixture) | `MockSQLBotClient` | CLI `--mock --mock-fixture /path/to.json` |

`RealSQLBotClient` 走 `POST /api/v1/indicator/query-report-info`,无认证,
transient HTTP 错(connection/timeout/5xx) 自动重试 3 次 (exponential,
base 1s, max 8s);`SQLBotError`(业务级 code != 0) 不重试,降级为
`metric_facts.status='query_failed'`。

CLI 入口:

```bash
# real (走 SQLBOT_BASE_URL 环境变量)
python scripts/sqlbot_client.py query \
  --parsed /tmp/parsed.json --out /tmp/query.json

# mock (默认 fixture)
python scripts/sqlbot_client.py query \
  --parsed /tmp/parsed.json --out /tmp/query.json --mock

# mock (指定 fixture)
python scripts/sqlbot_client.py query \
  --parsed /tmp/parsed.json --out /tmp/query.json \
  --mock --mock-fixture tests/fixtures/mock_sqlbot/wangyi_2026_03.json
```

测试和 E2E 一律用 mock;真实跑样张(用户部署环境)用 real,设
`SQLBOT_BASE_URL` 即可,代码路径完全相同。

## Reference 加载(按需读,不要全读)

| 需要做的事 | 读哪个 |
|---|---|
| 看完整步骤表 / 命令 / 重试策略 / 进度消息 | `references/pipeline.md` |
| checkpoint 1.5 / 3.5 / 8d.5 / 12 / 13 怎么问 | `references/checkpoints.md` |
| runtime 5 步细节 / CLI 入参 / 失败模式 | `references/runtime.md` |
| 中文回执 / status.json schema / sentinel 汇总 | `references/status-output.md` |
| DuckDB 表结构 / 数据形态转换 / Decimal 精度 | `references/data-flow.md` |

正常 design 流程:必读 `pipeline.md` + `checkpoints.md` + `data-flow.md`,
再读 `status-output.md`(出回执时)。`runtime.md` 只在用户要出 docx
或 runtime 出错时读。

## 关键契约(Phase 1 政策,不可违反)

下列规则写进设计阶段的代码也是 runtime 阶段的预期,违反会导致数据
正确性问题或精度丢失。

### 1. 银行精度:全程 `Decimal`,无 `float` round-trip

- `metric_facts.numeric_value` 列类型 `DECIMAL(38,10)`,DuckDB 内禁止
  `DOUBLE` / `REAL` / `FLOAT` cast。
- `assemble_wide` 用 `MAX(DECIMAL)` PIVOT,保留原值精度。
- `apply_units` 用 Python `Decimal` 算术,例如
  `Decimal("10000") * Decimal("0.0001") == Decimal("1.0000")`(精确)。
  **禁止** `1e8` / `10**8`(会变 float)。
- JSON 序列化时 `Decimal` → `str(Decimal)`,反序列化再 `Decimal(str)`。
  Renderer 在显示边界才转 float,且仅用于显示。
- 后果:王益联社 1234567890.50 / 10000 = 123456.78905,小数点后 5 位
  都还在;float 会变成 123456.78904999... 这种银行对账事故。

### 2. 失败 cell = `None`,**不**写哨兵字符串

- SQLBot 失败 → `metric_facts.status='query_failed'`,wide cell = `None`。
- 计算列失败 → wide cell = `None`。
- 哨兵码(`⚠️QUERY_FAILED` 等)**只**写在 `approved_runs.sentinels`
  (JSON list),**绝不**写到 cell 文本里。
- Bug A 修复:parse_md 的 `is_computed` 只看 `data-computed` 属性,
  **不看** `data-idx`(那是真实指标)。
- Bug B 修复:`approved_runs.sentinels` 存 ⚠️ codes,存 raw 名字
  (`"利润率"` / `"BAS_001@202603"`)会被 `build_status` by-code miss
  → 静默少报。
- 后果:render 输出要么是数字要么是空,文本里不会有 `⚠️...` 符号。
  状态聚合走 `assemble_status.build_status` by_code,准确报数。

### 3. 无 SQL 关键字黑名单(Phase 1 政策反转)

- `compute.validate` 第 1 层只用 `EXPLAIN`(语法/语义错误)。
- 不再白名单/黑名单 `SELECT` / `JOIN` / `WITH` 等关键词。
- 行数契约:SQL 必须返回 `len(wide_rows)` 行(无 `WHERE`/`GROUP BY`/
  `DISTINCT`/`LIMIT`/`JOIN`)。
- 后果:LLM 生成的 DuckDB SQL 只看 EXPLAIN + RUN + EXAMPLE 三层,
  不被关键词策略误杀。

### 4. 6 个 checkpoint,全部走 `ask_clarification`

- `clarification_type='risk_confirmation'`(固定)。
- Checkpoint 0 / 1.5 / 3.5 / 8d.5 / 12 / 13。
- 用户在 checkpoint 选 stop → section `approval_status='draft'`,
  不写 `approved_runs`,可 resume。
- 3.5 总是触发,**即使 `ok == 0`**(fail-fast 2026-06-27 反转)。
  相关 memory:`chatbi-report-fail-fast-query`。

### 5. DuckDB 全局单文件,不是 per-report

- `/mnt/ai-report-data/duckdb` 是唯一文件,**不要**给每个 report_id
  开一个 db。
- 多 section / 多 report_id 共用同一 DuckDB,靠 `report_id` + `run_id`
  + `table_id` 区分。
- 单进程多线程 OK(threading.Lock 写 + DuckDB MVCC 读);
  **不**支持多进程同 db_path 写(DuckDB 单写者)。
- 相关 memory:`ai-report-global-duckdb-path`。

### 6. 新写,不复用 chatbi-report 代码

- 16 个 scripts 全部新写,**不** import chatbi-report 任何文件。
- 不保留 pandas,数据层纯 DuckDB。
- 相关 memory:`ai-report-new-skill-not-replacement`。

## 输出规则

User-facing 产物:

- 每步中文进度消息(模板见 `references/pipeline.md`)。
- 中文 checkpoint 摘要 + 问题 + 选项(模板见 `references/checkpoints.md`)。
- 最终中文回执(`format_zh_receipt` 输出,flush=True,R-5)。
- `<report_id>.report.md`(chat 分享)与 `<report_id>.report.docx`(下载)。

**禁止**:

- 把 raw `status.json` 贴给用户。
- 把 `approved_runs` 内部 DuckDB 表行贴给用户。
- 写一段不存在的中间文件路径(避免幻觉路径)。
- 假定 cwd 是 skill 目录(必须用绝对 sandbox 路径)。

短报告 echo 到聊天,长报告总结 + 分享文件。

## 安全与作用域

报告运行期间**只能**写 `/mnt/ai-report-data/`,**不能**写
`/mnt/user-data/` 之外的用户数据区。

除非用户显式说 "改 skill" / "改样张",否则**不能**改:

- `/mnt/skills/public/ai-report/SKILL.md`
- `/mnt/skills/public/ai-report/scripts/*`
- `/mnt/skills/public/ai-report/prompts/*`
- `/mnt/skills/public/ai-report/references/*`
- `/mnt/user-data/uploads/<file>.md`(原始样张)

不要新增分析维度、列、业务解读,除非用户问。保留所有 sentinel 让
partial 报告可审计。

## Example

用户上传 `/mnt/user-data/uploads/wangyi_2026_03.md`(5 节经营分析样张,
每节 1 张表,共 5 张,含 `data-idx` 和 `data-unit`)。

最小运行流程:

1. **lint**:`python /mnt/skills/public/ai-report/scripts/md_lint.py
   /mnt/user-data/uploads/wangyi_2026_03.md` → 输出 LintReport。
2. **触发 checkpoint 1.5**(若 lint pass)或 stop(若有 errors)。
3. **设计**:逐 section 调 `DesignPipeline.run_section(table_id)`,过
   checkpoint 3.5 / 12 / 13。每通过一个 section 写一行 `approved_runs`。
4. **出 docx**:`python /mnt/skills/public/ai-report/scripts/runtime_pipeline.py
   --db-path /mnt/ai-report-data/duckdb --report-id wangyi_2026_03
   --out-dir /mnt/ai-report-data`,产物 `<report_id>.report.md` +
   `.report.docx` + `.status.json`,stdout 中文回执。
5. **分享**:`report.md` 内容贴聊天(短)或总结(长);`report.docx`
   给用户下载链接;`status.json` 不贴。

如果 SQLBot 5 个指标里有 1 个 `BAS_040@202603` 失败:`approved_runs.sentinels
= ["⚠️QUERY_FAILED"]`,`status='partial'`,回执含 `⚠️QUERY_FAILED × 1`,
该 cell 渲染为空,其他 4 个正常出数字。

如果 LLM 算 `利润率` 两次都 EXPLAIN 报错:`sentinels += ["⚠️COMPUTE_FAILED"]`,
该列所有 cell 渲染为空,不影响其他列。

## 相关 memory 索引

本 skill 设计与实现的关键决策都有 memory 锚点(避免后续 reviewer 重新
踩坑):

- `ai-report-new-skill-not-replacement`:不 import chatbi-report
- `ai-report-global-duckdb-path`:全局单 DuckDB
- `ai-report-phase1-unit-sandbox`:三约束(无关键字黑名单/SQLBot 源固定元/
  DuckDB SQL 端单位换算)
- `ai-report-v2-design-discussion-draft`:`docx/ai-report/ai-report-duckdb-v2-design.md`
  是讨论稿,不是 spec
- `chatbi-report-fail-fast-query`:2026-06-27 反转 fail-fast →
  always-checkpoint
- `skill-design-check-siblings-first`:改 skill 前先看同类 skill 约定
- `skills-surface-output-inline`:生成结果文件的 skill 要回显内容到 chat
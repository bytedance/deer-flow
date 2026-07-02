# SQLBot 报表生成（data-agent）设计

日期：2026-06-23
分支：`feat/sqlbot-report-data-agent`
关联：`SQLBOT_SPEC_PENDING`（真实 SQLBot API 规格待用户提供，先用 mock）

## 范围

**Phase 1（本设计）**：中文→英文指标匹配、单位声明与换算（含 Decimal 域）、计算列（同比/环比等）代码生成与验证、JSON / Markdown / DOCX 输出。

**Phase 2+（不在本设计）**：用真实数据跑计算、单位换算落地到数值、PDF、文件级缓存、报表模板系统、SQLBot 真实 API 接入、embedding 语义匹配、滚动窗口 / 移动平均 / 跨表关联计算。

## 设计原则

1. 单位与计算列都由**报表设计人员声明**，不由 SQLBot 推断。设计师对自己的报表口径负责。
2. 计算列**纯自然语言**写公式。LLM 一次性提取 formula + base_indicators + period tags；lead agent 再调 LLM 生成 pandas 代码。
3. Phase 1 只**生成 + 验证**计算代码（语法、签名、烟雾、可选示例），**不跑真数据**。真实拉数 + 跑代码留给 Phase 2。
4. 单位换算在 `decimal.Decimal` 域进行；展示精度由 `display_format` 控制，与 `scale_factor` 解耦。
5. `current / yoy_same / prev_period / ytd` 是**计算层的 period tag**，不是新 SQLBot code。Phase 2 查数据时由 SQLBot 客户端转成查询参数；某指标不支持某 period 时由 Phase 2 报错，Phase 1 不预校验。

## 背景与目标

DeerFlow 当前没有「报表生成」能力。报表设计人员目前只能：

1. 在 Markdown 里手写带中文指标的样例；
2. 手工去 SQLBot 指标库查每个中文指标对应的英文代码；
3. 手工把映射结果整理成 JSON；
4. 手工用 Word 排版生成 DOCX。

整套流程纯人工，**5 章节 × 5 报表 × 平均 6 指标 = 150 次手工查表**，极容易出错，且无法复用历史匹配。

**目标**：让 DeerFlow 内置 `sqlbot-report` 能力，对一份带 `{{指标}}` 标记的 Markdown 报表样例，端到端产出：

- **结构化 JSON**（用于二次处理 / 数据回填 / Phase 2 数据查询）
- **回填后的 Markdown**（中文显示 + 英文代码副标）
- **DOCX 文档**（多级表头 + 合并单元格 + 品牌样式）

并在 SQLBot 指标无法匹配时**定点中断**让用户澄清，而不是全错或全人工。

## 方案选型

- **方案 A（采纳）：Lead Agent + SKILL.md + scripts/**
  - `skills/public/sqlbot-report/SKILL.md` 作为入口 + 触发匹配 + 工作流指令
  - lead agent 通过 SkillActivationMiddleware 自动加载 SKILL.md
  - lead agent 用 `bash` / `read_file` / `write_file` / `str_replace` 调脚本
  - L3 歧义用 lead agent 原生 `ask_clarification`
  - 上下文用 `SummarizationMiddleware` 管理
  - 续跑用 LangGraph checkpointer

- 方案 B（否决）：Hybrid (Skill + Subagent)
  - 代码验证发现 subagent 调 `ask_clarification` 实际无效；Subagent 复杂度收益被 SummarizationMiddleware + checkpointer 覆盖

- 方案 C（否决）：纯 Skill（wencai 模式）
  - 优势：实现最简单
  - 否决理由：ask_clarification 是工具调用，跟其他工具同一层级，纯 Skill 不直接调工具也能写脚本让 lead agent 触发——但实现上是 A 方案的子集，没必要单独提

- 方案 D（否决）：MCP server
  - 否决理由：DOCX 渲染是重活不适合 MCP 工具语义；端到端工作流不是 MCP 适合的场景

### 计算列实现的备选方案

| 方案 | 取舍 |
|------|------|
| **采纳**：MD `> 计算:` 自然语言 + LLM 生成 pandas + AST 白名单 + sandbox 烟雾 | 设计师学习成本最低；DeerFlow 已有 sandbox 与 Python 能力完美契合；逻辑正确性由示例 + few-shot 把控 |
| 备选：内置函数白名单（yoy / mom / share / cagr / ytd / ratio）| 表达力受限；遇到行业特定比率（EVA / WACC 衍生）就要加新函数。LLM 生成稳定性差时可作为 fallback |
| 备选：半结构化 DSL（`yoy_same(X)` 函数语法）| 设计师不会主动写半结构化；双模式增加 parser / lint / 测试矩阵复杂度 |
| 备选：SQLBot 预声明 `supports_periods`| 推迟到 Phase 2 真实查数据时由 SQLBot 客户端返错处理，避免当前依赖 SQLBot schema 改动 |

## 架构

```
┌──────────────────────────────────────────────────────────┐
│ Layer 1: Skill (入口/触发)                                 │
│ skills/public/sqlbot-report/                              │
│ ├── SKILL.md            ← SkillActivationMiddleware 加载 │
│ ├── README.md           ← 配置说明                        │
│ ├── .env.example        ← SQLBOT_BASE_URL/SQLBOT_API_KEY │
│ ├── codegen_prompts/         ← v3：计算列代码生成提示词模板  │
│ │   ├── system.md                                          │
│ │   └── examples.md                                        │
│ └── scripts/                                                │
│     ├── sqlbot_client.py        ← SQLBot REST 客户端 (mock)│
│     ├── md_lint.py              ← 输入校验（v3 扩 lint 规则）│
│     ├── parse_md.py             ← MD → ReportDoc AST（v3 识别 data-unit/计算块）│
│     ├── match_indicators.py     ← L1/L2/L3 匹配流水线       │
│     ├── compute_ir.py           ← v3：> 计算: 块 LLM IR 提取  │
│     ├── compute_codegen.py      ← v3：pandas 代码生成        │
│     ├── compute_validator.py    ← v3：AST 白名单 + 烟雾验证   │
│     ├── unit_converter.py       ← v3：Decimal 域换算         │
│     ├── generate_descriptions.py ← 描述生成                  │
│     ├── render_markdown.py      ← 回填映射（v3 加单位副标 / computed 标记）│
│     ├── render_docx.py          ← python-docx 渲染（v3 表头副标）│
│     ├── retry.py                ← 通用重试装饰器             │
│     ├── indicator_cache.py      ← 内存+持久化匹配缓存        │
│     └── report_style.json       ← DOCX 样式定义             │
└──────────────────────────────────────────────────────────┘
                              ↓ SkillActivationMiddleware 加载 SKILL.md
┌──────────────────────────────────────────────────────────┐
│ Layer 2: Lead Agent (执行)                                 │
│ （DeerFlow 已存在，不需要新加）                              │
│ - system_prompt 包含 SKILL.md（hidden context）            │
│ - tools: bash, read_file, write_file, str_replace,         │
│          ask_clarification（lead agent 原生支持）            │
│ - SummarizationMiddleware: 自动压缩老消息（已存在）         │
│ - LangGraph checkpointer: 自动 state 持久化（已存在）       │
└──────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────┐
│ Layer 3: 资产输出 (sandbox 路径)                            │
│ /mnt/user-data/outputs/{thread_id}/                        │
│ ├── report.md                                                │
│ ├── report.docx                                              │
│ ├── report.json                                              │
│ ├── report.computed.py    (v3，仅当有计算列时)                │
│ ├── report.match.log                                        │
│ └── report.status.json                                      │
└──────────────────────────────────────────────────────────┘
```

## Phase 1 vs Phase 2 范围

| 能力 | Phase 1 | Phase 2 |
|------|---------|---------|
| 中文指标→英文代码匹配 | ✅ | ✅ |
| 结构化描述生成 | ✅ | ✅ |
| JSON 输出 | ✅ | ✅ |
| Markdown 输出（回填映射） | ✅ | ✅ |
| DOCX 输出（python-docx） | ✅ | ✅ |
| **v3** 单位声明（data-unit）| ✅ | ✅ |
| **v3** 单位写入 JSON / DOCX 表头副标 | ✅ | ✅ |
| **v3** 计算列声明 + LLM IR 提取 | ✅ | ✅ |
| **v3** LLM 生成 pandas 计算代码 + AST/签名/烟雾/示例验证 | ✅ | ✅ |
| **v3** 用真实数据跑 `report.computed.py` 得出计算列数值 | ❌ | ✅ |
| **v3** 单位换算（Decimal 域）填进 DOCX cell | ❌ | ✅ |
| **PDF 输出（reportlab）** | ❌ | ✅ |
| **数据查询（SQLBot 数据 API）** | ❌ | ✅ |
| 匹配结果持久化缓存（跨会话） | ⚠️ 内存级 | ✅ 文件级 |
| 报表模板系统 | ❌ | ✅ |
| Embedding 语义匹配（替代置信度猜值）| ❌ | ✅ |
| **v3** 滚动 N 月 / 移动平均 / 跨表关联计算 | ❌ | ✅ |

## Lead Agent 12 步流水线

```
[1] 读取 MD 文件
       bash: cat /mnt/user-data/uploads/{user_md}
[2] 调用 md_lint.py 校验格式
       - 检查 {{}} 标记是否成对
       - 检查 HTML table 是否闭合
       - v3：检查 data-unit 枚举、计算块格式、计算列指引完整性
       - 报错则中断并列出错误
[3] 解析 MD → in-memory AST
       ReportDoc {
         title, sections[], all_indicators: set
         Section { title, reports[] }
         Report {
           title, description, indicators, header_html, data_rows,
           computed_specs: ComputedSpec[],   # v3
         }
         Th {
           text, is_indicator, chinese,
           data_unit?: str,                  # v3
           is_computed: bool                 # v3
         }
       }
[4] 批量查 SQLBot 候选（仅非计算列指标）
       python sqlbot_client.py search --keywords "营业收入,营业成本,..."
       输出: { "营业收入": [Indicator, ...], ... }
[5] L1/L2/L3 匹配（仅非计算列）
       L1 精确匹配（中文名完全相等） + 查缓存
       L2 模糊匹配（LLM 选 top-1）+ 幻觉校验
       L3 lead agent 原生 ask_clarification（如有歧义）
[6] ★ v3：计算列 IR 提取与 base_indicators 绑定
       a) lead agent 一次性把所有 ComputedSpec.prompt 拼成一个 batched LLM 调用，
          每条返回 {formula_repr, base_indicators_zh, periods}
       b) base_indicators_zh 必须能在 step 5 已匹配的 indicator_mappings 里找到，
          否则该计算列标 F12 失败（其他列继续）
       c) 把已匹配指标的 code 填入 base_indicators[].code
       d) 推断 base_indicators[].periods（current/yoy_same/prev_period/ytd）
[7] ★ v3：计算列代码生成 + 验证
       对每个 ComputedSpec：
         a) lead agent 调 LLM 生成 compute_<hash8>(df: pd.DataFrame) -> pd.Series
            （同一次 prompt 让 LLM 一并返回 3 行烟雾数据）
         b) AST 白名单：仅允许 BinOp / UnaryOp / Subscript / Call(限定到 df.* / pd.* / np.*)
            / Name / Constant / IfExp。禁 Import / ImportFrom / Attribute(os/sys/subprocess/socket/__builtins__) / Global
         c) 签名检查：函数名匹配 compute_<hash8>，参数 (df: pd.DataFrame)，返回 pd.Series
         d) 烟雾跑：sandbox 内组装 DataFrame，跑函数，assert isinstance(out, pd.Series)
         e) 若设计师写了 .示例: 组装对应 DataFrame，跑函数，math.isclose(out, expected, rel_tol=1e-6)
         f) 任意一步失败 → 重试 1 次（附错误信息给 LLM）→ 仍失败 → 跳过该列，标
            compute_validation_failed / compute_smoke_failed，其他列继续
         g) 全部 compute 函数追加到 report.computed.py
       Phase 1 不跑真数据，验证后即结束本步
[8] LLM 生成结构化描述
       description_zh = 原中文（保留）
       description_en = LLM 翻译（仅用于 JSON 字段，DOCX 默认不用）
[9] 组装 JSON 输出
       含 indicator_mappings（含 is_computed、display_unit、scale_factor、compute_spec）
       含 computed_code 顶层字段（仅当有计算列时）
[10] ★ 单位换算（仅 render 阶段）
       把 display_unit、scale_factor 写入 JSON，DOCX 表头追加单位副标。
       Phase 2 拉真实数据时按 Decimal 域换算 → 写入 DOCX cell。
[11] 渲染 DOCX（含 v3 表头副标 + scale 后的数值）
       python render_docx.py --json report.json --style report_style.json
[12] 回填 MD
       python render_markdown.py --json report.json --original {user_md}
       计算列在回填 MD 中显示 `{{营收同比}} (computed)` 而非 (`code`)
```

### 续跑语义

Phase 1 不需要手写 checkpoint——LangGraph checkpointer 自动持久化 lead agent 的 state（包括所有 tool call 结果）。用户中途退出后回到同一 thread_id 对话，lead agent 从上次中断的 turn 继续。


### SKILL.md 关键内容（草稿，v3 更新到 12 步）

```markdown
---
name: sqlbot-report
version: 1.1.0-20260623
description: |
  根据用户上传的带 {{中文指标}} 标记的 Markdown 报表样例，
  匹配 SQLBot 指标库的中文→英文代码，生成 JSON/Markdown/DOCX。
  v1.1 新增：单位声明（元/万元/亿元）、计算列（同比/环比/毛利率等 LLM 生成 pandas 代码）。

  Triggers: "生成报表", "用 SQLBot 指标生成报告", "根据这个 MD 出报表",
  "根据 SQLBot 指标库生成 DOCX"
---

# SQLBot 报表生成

你是 DeerFlow 的 SQLBot 报表生成助手。用户上传一份带 `{{指标}}` 标记的
Markdown 报表样例，你要把它处理成结构化 JSON 。

## 工作流（12 步，每次执行都按顺序）

1. 读取 `/mnt/user-data/uploads/{user_md}`（用户上传路径）
2. 跑 `python /mnt/skills/public/sqlbot-report/scripts/md_lint.py <md>`
3. 跑 `python /mnt/skills/public/sqlbot-report/scripts/parse_md.py <md>`
   → 得到 ReportDoc AST（JSON），含 data_unit、computed_specs、is_computed
4. 收集所有非计算列 `{{指标}}` 去重，跑：
   `python /mnt/skills/public/sqlbot-report/scripts/sqlbot_client.py search --keywords "k1,k2,..."`
5. L1 + L2 + L3 匹配（仅非计算列）；同 v1 流程
6. **v3** 计算列 IR 提取（batched LLM）：
   - 输入：所有 ComputedSpec.prompt（自然语言公式）+ 表头 `{{}}` 指标的中英映射
   - 输出：每条 {formula_repr, base_indicators_zh, periods}
   - 校验 base_indicators_zh 必须在已匹配指标里；否则该列标 F12
7. **v3** 计算列代码生成 + 验证（按列循环）：
   - 调 LLM 生成 `compute_<hash8>(df: pd.DataFrame) -> pd.Series` 并要求同时返回 3 行烟雾数据
   - AST 白名单校验
   - 签名校验
   - sandbox 烟雾跑：assert isinstance(out, pd.Series)
   - 若有 .示例：再跑示例 assert
   - 失败重试 1 次后仍失败 → 跳过该列，标 compute_*_failed，其他列继续
   - 成功 → 追加到 `/mnt/user-data/outputs/{thread_id}/report.computed.py`
8. 描述生成：保留中文原描述，`description_en` 由 LLM 生成（仅用于 JSON 字段）
9. 组装 JSON：跑 `python scripts/match_indicators.py --assemble`，含 v3 字段
10. **v3** 单位换算：Phase 1 仅写入 display_unit + scale_factor，不换算数据
11. 渲染 DOCX：表头加单位副标，数值按 data_type + scale_factor 格式化
12. 回填 MD：`{{营业收入}}` → `营业收入 (\`revenue\`) (万元)`；`{{营收同比}}` → `营收同比 (computed)`

## 产出文件（写到 /mnt/user-data/outputs/{thread_id}/）

- `report.json` — 结构化 JSON（含 v3 单位 + 计算列字段）
- `report.md` — 回填映射的 Markdown
- `report.docx` — DOCX 文档（含 v3 表头单位副标）
- **v3** `report.computed.py` — LLM 生成的 pandas 计算函数（仅当有计算列）
- `report.match.log` — 决策日志（含 v3 代码生成与验证全文）
- `report.status.json` — 最终 status

## 关键约束

- 中文描述 `description.zh` 在 DOCX 中默认使用（受众是中国用户）
- LLM 模糊匹配必须批处理（避免 30 次串行调用）
- LLM 返回的 code 必须强校验，不在候选列表的视作幻觉
- 同一 thread 内匹配的指标自动进入内存缓存，避免重复 LLM
- DOCX 表格多级表头用 python-docx cell.merge() 合并
- 描述、匹配、渲染、**v3 代码生成与验证**的每步决定都写到 `report.match.log`
- **v3** 计算列代码生成 + 烟雾跑必须**在 sandbox 内**，禁直接在 lead agent 进程 exec()
- **v3** 计算列 AST 白名单遇到 Import/Attribute(os/sys/subprocess) 一律拒绝
- **v3** 单位换算用 `decimal.Decimal`，禁 float
- **v3** Phase 1 不查真实数据；计算列代码生成的输出仅是"能跑+签名对+示例对"的占位证据
```

## 输入契约：Markdown 报表样例

```yaml
report_doc:
  title_line: "# <标题>"
  sections: section*

section:
  header: "## 章节: <中文标题>"
  reports: report*

report:
  header: "### 报表: <中文标题>"
  description_block: "> 描述: <中文提示词，多行>"
  compute_block?: "> 计算: <计算列定义，多行>"   # v3 新增，可选
  table: <HTML table>

table:
  thead: rows+   # 至少一行；多级表头对应多行
  tbody: rows+
  row: th+ | td+

th:
  attrs: { data-unit?: "<元|万元|亿元|%|百分点|个|次|自定义>" }   # v3 新增
  content: text | "{{<中文指标名>}}"

indicator_marker: "{{<中文指标名>}}"
  # 严格规则：
  # - 在 <th> 内：表头是"需映射"的指标
  # - 在 <td> 内：数据值，无需映射
  # - 在 {{}} 外：标题/描述/分类，无需映射
  # - 计算列也用 {{}}，但中文名同时出现在 compute_block 左侧，parser 标 is_computed=true
```

### v3 新增：列级单位声明 `data-unit`

设计师在 `<th>` 上加 `data-unit` 属性，声明该列**显示单位**：

```html
<thead>
  <tr>
    <th>季度</th>
    <th data-unit="万元">{{营业收入}}</th>
    <th data-unit="万元">{{营业成本}}</th>
    <th data-unit="%">{{毛利率}}</th>
  </tr>
</thead>
```

合法值（lint WARN 之外的视为自定义字符串，照原样写入 JSON）：

| data-unit | scale_factor (Decimal) | 含义 |
|-----------|------------------------|------|
| `元` | `Decimal("1")` | SQLBot 原始即此单位 |
| `万元` | `Decimal("10000")` | 显示时除以 1e4 |
| `亿元` | `Decimal("100000000")` | 显示时除以 1e8 |
| `%` | `Decimal("0.01")` | 0.366 显示为 36.60% |
| `百分点` | `Decimal("1")` | 已经是百分点单位（如同比增加 3 个百分点）|
| `个` / `次` | `Decimal("1")` | 计数单位 |

**转换语义**（render 阶段，Phase 2 用数据回填时启用）：

```
display_value = Decimal(raw_value) * Decimal(raw_unit_scale) / Decimal(display_unit_scale)
# raw_unit_scale 来自 SQLBot Indicator.unit
# display_unit_scale 来自 MD 的 data-unit
```

Phase 1 无真实数据查询，仅把 `display_unit` + `scale_factor` 写入 JSON `indicator_mappings`，并在 DOCX 表头副标显示 `中文名 (单位)`。

**精度策略**：换算和展示一律在 `decimal.Decimal` 域进行。DOCX 输出由 `display_format`（默认按 `data_type` 推导，如 `#,##0.00` / `0.0%`）控制小数位数；scale_factor 只负责量纲，不负责精度。

### v3 新增：计算块 `> 计算:` 与虚拟指标

设计师在每个 `> 描述:` 块下方可选添加 `> 计算:` 块，用**自然语言**写公式：

```markdown
### 报表: 季度财务概览

> 描述: 2024 年各季度营收成本对比，重点关注同比环比变化。
> 计算:
>   营收同比 = 本期营业收入减去年同期再除同期
>   成本同比 = 本期营业成本减去年同期再除同期
>   毛利率 = (营业收入 - 营业成本) / 营业收入
>   营收同比.示例: 营业收入[current=200, yoy_same=100] -> 1.0
```

**核心约定**：
- `> 计算:` 块每一行：`<虚拟指标名> = <自然语言公式>`
- 计算列的表头**也用 `{{}}`**，但同名出现在 `> 计算:` 左侧 → parser 标 `is_computed: true`，不发到 SQLBot
- 公式右侧是**自由文本**，由 lead agent 调 LLM 提取出结构化中间表示（IR）：base_indicators + period tags + formula_repr
- 公式右侧引用的中文指标必须能在表头 `{{}}` 中找到（同名匹配），否则 lint ERROR
- 时期 tag 由 LLM 推断："本期/当期"→`current`，"去年同期/同期"→`yoy_same`，"上期/上月/上季度/上年"→`prev_period`，"年初至今/累计"→`ytd`

**示例值（可选，不阻塞）**：
- 格式：`<虚拟指标名>.示例: <SQLBot指标名>[period1=val, period2=val, ...] -> <期望值>`
- 同一虚拟指标可写多行示例
- Phase 1 验证时若有示例，sandbox 跑生成的 pandas 函数并 `assert math.isclose(out, expected, rel_tol=1e-6)`
- 没写示例的列只跑类型/形状烟雾测试，不 assert 数值

### 多表头里计算列重名（v3 决策：WARN 不 ERROR）

如同名计算列出现在不同表头分支（如外层"同比"下面同时有"营业收入"和"营业成本"两个子列），建议起**唯一中文名**（"营收同比"/"成本同比"）。

- lint WARN：同名虚拟指标出现 > 1 次 → 提示设计师起更精确的名字
- parser 兜底：以 "表头路径前缀 + 列名" 生成内部 ID（仅用于 JSON `code` 字段去重，不暴露给设计师）

### Lint 规则（md_lint.py 强制 — v3 扩展）

| 规则 | 等级 |
|------|------|
| `{{}}` 必须成对出现 | ERROR |
| `<table>` 必须有 `<thead>` 和 `<tbody>` | ERROR |
| 章节必须含至少一个报表 | ERROR |
| 报表必须含描述和数据 | ERROR |
| 多级表头用 `<th rowspan/colspan>`，不用 markdown 表格 | WARN |
| 指标名应**简洁**（≤8 个汉字） | WARN |
| 同一中文指标在多张表出现时建议全名一致 | WARN |
| **v3** `data-unit` 在枚举值（`元`/`万元`/`亿元`/`%`/`百分点`/`个`/`次`）内 | WARN |
| **v3** `> 计算:` 块每行格式 `<name> = <expr>`，长度 1-200 字 | ERROR |
| **v3** 表头计算列名必须出现在 `> 计算:` 左侧 | ERROR |
| **v3** `> 计算:` 左侧名必须出现在表头 `{{}}` | WARN（未用公式）|
| **v3** `> 计算:` 公式右侧引用的中文指标名必须在表头 `{{}}` 中存在 | ERROR（由 IR 提取后校验） |
| **v3** 多表头里同名虚拟指标多次出现 | WARN |
| **v3** `<名>.示例:` 格式 `<指标>[k=v,...] -> 数值` | WARN（解析失败的示例丢弃，不阻塞）|

## 输出契约 1：JSON Schema（v2，扩字段）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SqlbotReport",
  "type": "object",
  "required": ["title", "sections", "metadata"],
  "properties": {
    "title": {"type": "string"},
    "report_id": {"type": "string", "format": "uuid"},
    "time_range": {
      "type": "object",
      "description": "报表时间范围（可空）",
      "properties": {
        "start": {"type": "string", "format": "date"},
        "end": {"type": "string", "format": "date"},
        "period": {"enum": ["daily", "weekly", "monthly", "quarterly", "yearly", "custom"]}
      }
    },
    "sections": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["section_id", "title", "reports"],
        "properties": {
          "section_id": {"type": "string"},
          "title": {"type": "string"},
          "reports": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["report_id", "title", "description", "headers", "data", "indicator_mappings"],
              "properties": {
                "report_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {
                  "type": "object",
                  "required": ["zh"],
                  "properties": {
                    "zh": {"type": "string", "description": "中文描述，DOCX 默认使用"},
                    "en": {"type": "string", "description": "LLM 翻译的英文描述，可选"}
                  }
                },
                "headers": {
                  "type": "array",
                  "description": "多级表头，每行一个数组",
                  "items": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "text": {"type": "string"},
                        "is_indicator": {"type": "boolean"},
                        "chinese": {"type": "string"},
                        "code": {"type": "string"},
                        "rowspan": {"type": "integer"},
                        "colspan": {"type": "integer"}
                      }
                    }
                  }
                },
                "data": {
                  "type": "array",
                  "items": {"type": "object", "additionalProperties": true}
                },
                "indicator_mappings": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "required": ["chinese", "code", "confidence", "is_computed"],
                    "properties": {
                      "chinese": {"type": "string"},
                      "code": {"type": "string"},
                      "name_en": {"type": "string"},
                      "category": {"type": "string"},
                      "unit": {"type": "string", "description": "SQLBot 返回的原始单位（raw_unit）"},
                      "data_type": {
                        "enum": ["number", "currency", "percentage", "ratio", "text", "date"],
                        "description": "决定 DOCX 数字格式"
                      },
                      "display_format": {
                        "type": "string",
                        "description": "显示格式字符串，如 '#,##0.00' 或 '0.0%'"
                      },
                      "time_dimension": {
                        "enum": ["current", "ytd", "mtd", "qtd", "rolling_30d", "rolling_7d", "none"],
                        "description": "时间维度"
                      },
                      "data_source": {"type": "string", "description": "数据源（Phase 2 用）"},
                      "last_updated": {"type": "string", "format": "date-time"},
                      "version": {"type": "string"},
                      "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                      "match_method": {"enum": ["exact", "fuzzy", "user_clarification", "cache_hit", "computed"]},
                      "is_computed": {"type": "boolean", "description": "v3：true 表示虚拟指标，由 compute_spec 定义"},
                      "display_unit": {
                        "type": "string",
                        "description": "v3：MD `data-unit` 声明的显示单位"
                      },
                      "scale_factor": {
                        "type": "string",
                        "description": "v3：Decimal 字符串表示。display_value = raw_value * raw_unit_scale / display_unit_scale"
                      },
                      "compute_spec": {
                        "type": "object",
                        "description": "v3：仅 is_computed=true 时存在",
                        "required": ["prompt", "base_indicators", "code_file", "function", "validation"],
                        "properties": {
                          "prompt": {"type": "string", "description": "设计师写的自然语言公式原文"},
                          "formula_repr": {
                            "type": "string",
                            "description": "LLM 提取的结构化中间表示，形如 (current(revenue) - yoy_same(revenue)) / yoy_same(revenue)"
                          },
                          "base_indicators": {
                            "type": "array",
                            "items": {
                              "type": "object",
                              "required": ["chinese", "code", "periods"],
                              "properties": {
                                "chinese": {"type": "string"},
                                "code": {"type": "string"},
                                "periods": {
                                  "type": "array",
                                  "items": {"enum": ["current", "yoy_same", "prev_period", "ytd"]}
                                }
                              }
                            }
                          },
                          "code_file": {"type": "string", "const": "report.computed.py"},
                          "function": {"type": "string", "description": "如 compute_<hash8>"},
                          "examples": {
                            "type": "array",
                            "items": {
                              "type": "object",
                              "properties": {
                                "inputs": {"type": "object", "additionalProperties": {"type": "string"}},
                                "expected": {"type": "string", "description": "Decimal 字符串"}
                              }
                            }
                          },
                          "validation": {
                            "type": "object",
                            "required": ["ast_check", "signature_check", "smoke_run"],
                            "properties": {
                              "ast_check": {"enum": ["passed", "failed", "skipped"]},
                              "signature_check": {"enum": ["passed", "failed"]},
                              "smoke_run": {"enum": ["passed", "failed", "skipped"]},
                              "example_check": {"enum": ["passed", "failed", "skipped", "not_provided"]},
                              "failure_reason": {"type": "string"}
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    },
    "metadata": {
      "type": "object",
      "required": ["generated_at", "total_indicators", "matched_count", "unmatched_count", "match_rate"],
      "properties": {
        "generated_at": {"type": "string", "format": "date-time"},
        "total_indicators": {"type": "integer"},
        "matched_count": {"type": "integer"},
        "unmatched_count": {"type": "integer"},
        "match_rate": {"type": "number", "minimum": 0, "maximum": 1},
        "unmatched": {"type": "array", "items": {"type": "string"}},
        "cache_hits": {"type": "integer", "description": "缓存命中次数"},
        "llm_calls": {"type": "integer", "description": "LLM 调用次数（含 batch）"},
        "duration_seconds": {"type": "number"},
        "computed_columns_count": {"type": "integer", "description": "v3：虚拟指标数"},
        "computed_validation_failures": {"type": "integer", "description": "v3：AST/签名/烟雾/示例失败数"},
        "code_generation_llm_calls": {"type": "integer", "description": "v3：用于代码生成的 LLM 调用数"}
      }
    },
    "computed_code": {
      "type": "object",
      "description": "v3：lead agent 生成的 pandas 计算代码描述。仅当存在计算列时出现。",
      "properties": {
        "file": {"type": "string", "const": "report.computed.py"},
        "size_bytes": {"type": "integer"},
        "functions": {"type": "array", "items": {"type": "string"}},
        "imports_allowed": {"type": "array", "items": {"type": "string"}, "default": ["pandas", "numpy"]},
        "generated_at": {"type": "string", "format": "date-time"},
        "generator_model": {"type": "string"},
        "validation_log": {"type": "string", "const": "report.match.log"}
      }
    }
  }
}
```

### v2 schema 相比 v1 增字段

| 新字段 | 业务价值 |
|--------|---------|
| `description.zh` 标记 required，DOCX 默认用中文 | 解决语言错配（Issue #3）|
| `data_type` | 决定 DOCX 数字格式（千分位、百分比、货币）|
| `display_format` | 精细控制显示样式 |
| `time_dimension` | 表达"本月"/"YTD"等时间维度 |
| `data_source` | 跨数据源报表溯源（Phase 2 用）|
| `last_updated` / `version` | 指标版本管理 |
| `match_method: cache_hit` | 跟踪缓存命中率 |
| `metadata.cache_hits` / `llm_calls` | 性能监控 |
| `time_range` (top-level) | 报表级时间范围 |

### v3 schema 相比 v2 增字段

| 新字段 | 业务价值 |
|--------|---------|
| `indicator_mappings[].is_computed` | 区分虚拟指标和 SQLBot 指标 |
| `indicator_mappings[].display_unit` | 设计师声明的显示单位 |
| `indicator_mappings[].scale_factor` | 与 `raw_unit` 协同的换算系数（Decimal 字符串）|
| `indicator_mappings[].compute_spec` | 虚拟指标完整规格：自然语言提示词、LLM 提取的 IR、base_indicators、生成函数、示例、验证结果 |
| `match_method: computed` | 标记计算列（match_rate 计算时分母含计算列）|
| `metadata.computed_columns_count` | 计算列数量统计 |
| `metadata.computed_validation_failures` | 失败的计算列数 |
| `metadata.code_generation_llm_calls` | 代码生成 LLM 调用数（独立于匹配 LLM）|
| `computed_code` (top-level) | 生成的 `report.computed.py` 文件元信息 |

## 输出契约 2：DOCX 结构

```
report.docx:
├── 标题 (Heading 1)
├── 章节 (Heading 2)
│   └── 报表 (Heading 3)
│       ├── 描述段落 (Normal，使用 description.zh 中文原文)
│       ├── 数据表 (python-docx Table)
│       │   ├── 表头：多级用 cell.merge() 合并
│       │   ├── 表头单元格：粗体 + 底色 (#F0F0F0)
│       │   ├── 表头副标 (v3)：中文名下方一行小字显示 "(单位)"，如 "(万元)" / "(%)"
│       │   └── 数据单元格：根据 data_type + scale_factor 应用格式（千分位/百分比/货币）
│       └── 备注 (Indicator 未映射时显示 ⚠️UNMAPPED；计算列验证失败显示 ⚠️COMPUTE_FAILED)
```

### v3 表头副标渲染规则

```
┌────────────────┐
│  营业收入       │  ← Heading 文本（粗体）
│  (万元)         │  ← 单位副标（同 cell，小一号字 + 灰色 #666666）
└────────────────┘
```

- 仅当 `display_unit` 不为空时渲染副标
- 副标与主标在同一 cell，用换行符 + run-level 字号控制（不另起 cell）
- 副标字号：主标 × 0.8；颜色 #666666

### 样式配置 `report_style.json`

```json
{
  "font": {
    "title": {"name": "微软雅黑", "size": 18, "bold": true},
    "section": {"name": "微软雅黑", "size": 14, "bold": true},
    "report": {"name": "微软雅黑", "size": 12, "bold": true},
    "body": {"name": "宋体", "size": 11}
  },
  "table": {
    "header_bg": "#F0F0F0",
    "border_color": "#888888",
    "border_width_pt": 0.5,
    "cell_padding_pt": 4,
    "number_format": {
      "number": "#,##0",
      "currency": "¥#,##0.00",
      "percentage": "0.0%",
      "ratio": "0.00"
    }
  },
  "page": {
    "orientation": "landscape",
    "margins_cm": {"top": 2, "bottom": 2, "left": 2, "right": 2}
  }
}
```

## 输出契约 3：回填 MD

把 `{{营业收入}}` 替换成 `营业收入 (\`revenue\`) (万元)`（v3 加单位副标）：

```markdown
| 季度 | 财务指标 || 增长率 ||
|      | 营业收入 (`revenue`) (万元) | 营业成本 (`operating_cost`) (万元) | 营收同比 (computed) (%) | 成本同比 (computed) (%) |
|------|---------|---------|------|------|
| 2024 Q1 | 14500 | 9200 | 12.5% | 10.2% |
```

未匹配项标 `⚠️UNMAPPED`，计算列代码生成失败标 `⚠️COMPUTE_FAILED`：

```markdown
| {{营业收入}} (revenue) (万元) | {{新增指标}} ⚠️UNMAPPED | {{自定义比率}} (computed) ⚠️COMPUTE_FAILED |
```

## 决策日志 `report.match.log`

```
[2026-06-22 10:23:45] L1 精确匹配: {{营业收入}} → revenue (exact)
[2026-06-22 10:23:45] L1 精确匹配: {{营业成本}} → operating_cost (exact)
[2026-06-22 10:23:45] cache_hit: {{净利润}} → net_profit (from in-memory cache)
[2026-06-22 10:23:46] L2 批调用: [{{环比增长率}}, {{同比增长率}}, {{毛利率}}] → 3/3 mapped, 1 low_confidence
[2026-06-22 10:23:46] L2 模糊匹配: {{环比增长率}} → qoq_growth_rate (confidence=0.85)
[2026-06-22 10:23:46] L2 hallucination_check: rejected code="unknown_growth" (not in candidates)
[2026-06-22 10:23:50] L3 澄清: {{增长率}} 用户选择 "yoy_growth" (3 选项中)
[2026-06-22 10:23:51] unmatched: {{行业平均}} (SQLBot 中无候选)
[2026-06-22 10:23:52] v3 unit: {{营业收入}} display_unit=万元 scale_factor=10000 raw_unit=元
[2026-06-22 10:23:52] v3 unit: {{毛利率}} display_unit=% scale_factor=0.01 (data_type=percentage)
[2026-06-22 10:23:53] v3 compute IR (batched LLM): 3 columns extracted
[2026-06-22 10:23:53] v3 compute IR: 营收同比 → formula=(current(revenue) - yoy_same(revenue)) / yoy_same(revenue) periods=[current, yoy_same]
[2026-06-22 10:23:53] v3 compute IR: 成本同比 → formula=(current(operating_cost) - yoy_same(operating_cost)) / yoy_same(operating_cost)
[2026-06-22 10:23:53] v3 compute IR: 毛利率 → formula=(current(revenue) - current(operating_cost)) / current(revenue)
[2026-06-22 10:23:54] v3 codegen LLM (营收同比): generated 6 lines + 3 smoke rows
[2026-06-22 10:23:54] v3 ast_check (营收同比): passed (only BinOp/Subscript/Call(df.xs))
[2026-06-22 10:23:54] v3 signature_check (营收同比): passed (def compute_a1b2c3d4(df: pd.DataFrame) -> pd.Series)
[2026-06-22 10:23:55] v3 smoke_run (营收同比): passed (isinstance(out, pd.Series), len=3)
[2026-06-22 10:23:55] v3 example_check (营收同比): passed (out[0]=1.0 ≈ expected 1.0)
[2026-06-22 10:23:56] v3 codegen LLM (毛利率): generated, all checks passed
[2026-06-22 10:23:57] v3 report.computed.py written: 3 functions, 1247 bytes
```

## 错误处理 & 失败模式

| ID | 类别 | 触发条件 | 处理 |
|----|------|---------|------|
| F1 | 输入格式错误 | MD lint 不通过 | lead agent 中断，返回 `{status: "error", errors: [...]}` |
| F2 | SQLBot 配置缺失 | `.env` 无 `SQLBOT_BASE_URL` / `SQLBOT_API_KEY` | lead agent 中断，返回 `{status: "error", reason: "SQLBOT_CONFIG_MISSING"}` |
| F3 | SQLBot 网络/API 失败 | HTTP 5xx / 超时 / 4xx | 按 retry 表；仍失败 → 中断 |
| F4 | SQLBot 0 候选 | 某些 `{{指标}}` 在 SQLBot 中无任何匹配 | 标 `unmatched`，继续；不影响流水线 |
| F5 | L2 低置信度 + 无歧义 | top-1 < 0.6 且 `top1.score - top2.score > 0.1` | 用 top-1，confidence=低，标 `low_confidence`，继续 |
| F6 | L2 低置信度 + 多候选歧义 | top-1 < 0.6 且 `top1.score - top2.score ≤ 0.1` | lead agent 调 `ask_clarification`（原生支持） |
| F7 | 用户取消澄清 | 用户拒绝 / 给 "跳过" | 标 `user_skipped` → 继续 |
| F8 | 描述生成失败 | LLM API 失败 | 按 retry 表；仍失败 → `description.zh = 原中文 + " [TRANSLATION_FAILED]"` |
| F9 | DOCX 渲染失败 | python-docx 异常 | 返回 JSON + log，flag `render_error`，用户可手动重跑 `render_docx.py` |
| F10 | LLM 幻觉 | LLM 返回 code 不在候选列表 | 拒绝该结果，回退 L1 重试；仍失败 → 进 L3 |
| F11 | 上下文爆 | token 累积超阈值 | SummarizationMiddleware 自动总结老消息 |
| **F12** | 计算列 base 未匹配 | `> 计算:` 公式引用的中文指标不在表头 `{{}}` 已匹配集合中 | 该计算列标 `compute_base_missing`，写 log，继续其他列；status=partial |
| **F13** | LLM 代码生成失败 | LLM API 失败 / 返回非 Python 文本 | 按 retry 表（附最后错误信息）；仍失败 → `compute_codegen_failed`，继续其他列；status=partial |
| **F14** | AST 校验失败 | 含 Import / Attribute 黑名单 / 非白名单算子 | 按 retry 表（附白名单提示）；仍失败 → `compute_validation_failed`，继续 |
| **F15** | 烟雾跑或示例 assert 失败 | sandbox 跑出来类型不对 / 数值与示例不匹配 | 按 retry 表（附差异信息）；仍失败 → `compute_smoke_failed`，继续 |
| **F16** | 单位声明与 SQLBot raw_unit 不一致 | display_unit 与 raw_unit 单位族不同（如 `元` ↔ `%`）| WARN 不阻断，按 display_unit 写入，log 提示；Phase 2 拉数据时若 raw_unit 数值无法换算到 display_unit（如 元↔个）→ 升级为 F9 渲染错误 |

### 重试策略（统一）

| 操作 | max_attempts | backoff | 失败时 |
|------|--------------|---------|--------|
| SQLBot HTTP（搜索 / 拉数）| 3 | 指数 1s / 2s / 4s（max 10s）| 中断流程 |
| LLM 通用调用（描述生成 / 计算列 IR / 代码生成 / AST 重生成 / 烟雾重生成）| 2 | 无（立即重试）| 标 `*_failed` 跳过该项，继续其他 |
| LLM 幻觉拒绝 | 2 | 无 | 拒绝 → 回退 L1 → 仍失败进 L3 |

统一通过 `scripts/retry.py` 装饰器实现：

```python
@retry(max_attempts=3, backoff=exponential(base=2, max_delay=10),
       retry_on=(requests.RequestException, TimeoutError))
def call_sqlbot_search(keyword: str) -> list[Indicator]: ...
```

### lead agent 退出 status

```json
// /mnt/user-data/outputs/{thread_id}/report.status.json
{
  "status": "success" | "partial" | "error",
  "exit_step": 1..10,
  "error_class": null | "F1" | "F2" | ... | "F11",
  "error_detail": "human-readable message",
  "outputs": {"json": "path|null", "docx": "path|null", "md": "path|null"},
  "metrics": {
    "matched_count": int,
    "unmatched_count": int,
    "match_rate": float,
    "cache_hits": int,
    "llm_calls": int,
    "duration_seconds": float
  }
}
```

| status | 判定标准 | lead agent 行为 |
|--------|---------|----------------|
| `success` | `unmatched_count == 0` 且 `error_class == null` | present_files 三件套 |
| `partial` | `0 < match_rate < 1.0` 且无 error_class | present_files 可用的 + 简述未匹配项数 |
| `error` | `error_class in F1..F11` | 不 present_files，告知用户失败原因 + 检查清单 |

### 续跑（Phase 1）

Phase 1 不需要手写 checkpoint——LangGraph checkpointer 自动持久化 lead agent 的 state（包括所有 tool call 结果）。用户中途退出后回到同一 thread_id 对话，lead agent 从上次中断的 turn 继续。

`SummarizationMiddleware` 在 token 累积到阈值时自动总结老消息（默认 80K token 触发，保留最近 20 条原样），确保长流程不爆上下文。

### 幻觉校验（v2 新增）

```python
def validate_match_output(matches: list[Match], candidates_by_indicator: dict[str, list[Indicator]]) -> list[Match]:
    """强校验：LLM 返回的 code 必须严格在候选列表里"""
    validated = []
    for m in matches:
        candidates = candidates_by_indicator.get(m.chinese, [])
        valid_codes = {c.code for c in candidates}
        if m.code not in valid_codes:
            log_match(f"hallucination rejected: {m.chinese} -> {m.code} (not in candidates)")
            m.match_method = "hallucination_rejected"
            continue  # 丢弃，后续 fallback 到 L1
        validated.append(m)
    return validated
```

### 指标缓存（v2 新增）

```python
# indicator_cache.py — 内存缓存（lead agent 对话生命周期内）
class IndicatorCache:
    def __init__(self):
        self._cache: dict[str, Indicator] = {}

    def get(self, chinese: str) -> Indicator | None:
        return self._cache.get(chinese)

    def set(self, chinese: str, indicator: Indicator) -> None:
        self._cache[chinese] = indicator

    def batch_match(self, indicators: list[str], candidates: dict[str, list[Indicator]]) -> dict[str, Indicator]:
        """先查缓存，缓存未命中才调 SQLBot"""
        result = {}
        need_lookup = []
        for ind in indicators:
            cached = self.get(ind)
            if cached:
                result[ind] = cached
                log_match(f"cache_hit: {{{{{ind}}}}} -> {cached.code}")
            else:
                need_lookup.append(ind)
        # need_lookup 走 SQLBot → 缓存 → 返回
        ...
        return result
```

缓存范围：单 lead agent 对话生命周期内。**Phase 2** 加持久化到 `~/.sqlbot_report_cache/`。

## 资产输出路径

```
/mnt/user-data/outputs/{thread_id}/
├── report.md
├── report.docx
├── report.json
├── report.computed.py    # v3：LLM 生成的 pandas 计算函数（仅当有计算列时）
├── report.match.log
└── report.status.json
```

## 测试策略

### 测试金字塔

```
              E2E (手动)
                  ↑
      Integration (lead agent + mock SQLBot)
                  ↑
        Unit tests (每个脚本)
```

### 单元测试 `backend/tests/sqlbot_report/`

| 文件 | 覆盖 |
|------|------|
| `test_md_lint.py` | 合法 + 各种 lint 错误 + **v3** data-unit / 计算块 / 示例语法 |
| `test_parse_md.py` | 单/多章节、多级表头、特殊字符、空报表 + **v3** data-unit / computed_specs / 虚拟指标识别 |
| `test_sqlbot_client.py` | 用 `pytest-httpx` mock HTTP（5xx/4xx/timeout）|
| `test_match_indicators.py` | L1/L2 + 幻觉校验 + 批调用 + L3 + **v3** 跳过 is_computed |
| `test_indicator_cache.py` | 缓存命中、缓存写入、并发安全 |
| `test_render_docx.py` | 读回 docx 验证 cell 合并、字体、底色、data_type 格式 + **v3** 表头单位副标 |
| `test_render_markdown.py` | `{{}}` 替换、unmapped 标记 + **v3** computed 标记 + 单位副标 |
| `test_retry.py` | 成功路径、失败重试、最终失败 |
| `test_status.py` | 各失败场景下 status.json 字段 |
| **`test_compute_ir.py`** | v3：LLM batched IR 提取；公式右侧引用校验；periods 推断 |
| **`test_compute_codegen.py`** | v3：LLM mock 返回；代码生成；重试逻辑 F13 |
| **`test_compute_validator.py`** | v3：AST 白名单（含 Import/Attribute 黑名单）；签名检查；烟雾数据 sandbox；示例 assert |
| **`test_unit_conversion.py`** | v3：scale_factor (Decimal) 换算；DOCX 表头副标；data_type=percentage 联动 |

### 集成测试 `backend/tests/integration/sqlbot_report/`

| 场景 | 描述 |
|------|------|
| `test_happy_path.py` | 完整 MD → 全部 L1 → JSON+MD+DOCX |
| `test_partial_match.py` | 部分 L1 + 部分 L2，无 L3 |
| `test_l3_clarification.py` | mock ask_clarification 触发和恢复 |
| `test_sqlbot_down.py` | SQLBot 全宕机 → F3 → status=error |
| `test_partial_unmapped.py` | 部分无候选 → F4 → status=partial |
| `test_hallucination_rejection.py` | LLM 输出 code 不在候选 → 校验拒绝 + fallback |
| `test_cache_effectiveness.py` | 同 thread 多次匹配，cache_hits > 0 |
| **`test_computed_columns.py`** | v3：计算列流水线多场景（happy / base_missing→F12 / ast_rejected→F14 / smoke_failed→F15），每场景独立 test function |
| **`test_computed_codegen_retry.py`** | v3：codegen retry（F13）+ designer_examples 校验 |
| **`test_unit_conversion_e2e.py`** | v3：mock SQLBot raw_unit=元 + MD data-unit=万元 → 校验 JSON/DOCX 字段 |

集成测试用 mock SQLBot server（`pytest-httpx` + fixture 返回假数据）。

### 测试数据 fixtures

```
backend/tests/fixtures/sqlbot_report/
├── sample_md/
│   ├── happy.md
│   ├── lint_error.md
│   ├── multi_chapter.md
│   ├── partial_unmapped.md
│   ├── l3_ambiguous.md
│   ├── computed_columns.md         # v3：含 > 计算: 块
│   ├── computed_with_examples.md   # v3：含示例值
│   ├── multi_header_computed.md    # v3：多级表头 + 计算列重名
│   └── unit_conversion.md          # v3：含 data-unit 各种单位
├── mock_sqlbot/
│   ├── indicators.json       # 模拟指标库（100+ 条，覆盖 5+ 业务域）
│   └── search_responses.json # 含易混名（"营收" / "营业收入" / "营业总收入"）
└── expected_outputs/
    ├── happy.json
    ├── partial_unmapped.json
    ├── computed_columns.json       # v3：含 compute_spec
    ├── computed_columns.computed.py.regex # v3：用正则验证生成代码结构
    └── unit_conversion.json        # v3：含 display_unit + scale_factor
```

### 覆盖率目标

| 类别 | 目标 |
|------|------|
| 单元测试行覆盖 | ≥85% |
| 关键路径（match/render）分支覆盖 | 100% |
| 集成测试场景 | ≥7 个核心场景 |

### 端到端（手动）

| 场景 | 操作 |
|------|------|
| E1 | 上传真实 MD → 看 lead agent 进度 → 拿三件套 |
| E2 | 故意 lint 错误 → 看错误提示 |
| E3 | L3 歧义 → 看 ask_clarification 是否触发 |
| E4 | DOCX 在 Word/WPS 中打开看样式 |
| E5 | 长流程（20 报表）→ 看 SummarizationMiddleware 是否触发 |
| E6 | 中途退出 thread → 重进 → 看 LangGraph checkpointer 续跑 |

## 改动清单

### 新增文件

**Skill 入口 + 通用脚本**：
- `skills/public/sqlbot-report/SKILL.md`
- `skills/public/sqlbot-report/README.md`
- `skills/public/sqlbot-report/.env.example`
- `skills/public/sqlbot-report/scripts/sqlbot_client.py`（mock 实现）
- `skills/public/sqlbot-report/scripts/md_lint.py`
- `skills/public/sqlbot-report/scripts/parse_md.py`
- `skills/public/sqlbot-report/scripts/match_indicators.py`（含幻觉校验 + 批调用）
- `skills/public/sqlbot-report/scripts/indicator_cache.py`（内存缓存）
- `skills/public/sqlbot-report/scripts/generate_descriptions.py`
- `skills/public/sqlbot-report/scripts/render_markdown.py`
- `skills/public/sqlbot-report/scripts/render_docx.py`（含 data_type 格式应用）
- `skills/public/sqlbot-report/scripts/retry.py`
- `skills/public/sqlbot-report/scripts/report_style.json`

**计算列专用脚本**：
- `skills/public/sqlbot-report/scripts/compute_ir.py` — `> 计算:` 块 LLM IR 提取
- `skills/public/sqlbot-report/scripts/compute_codegen.py` — LLM 调用 + pandas 代码生成
- `skills/public/sqlbot-report/scripts/compute_validator.py` — AST 白名单 + 签名检查 + sandbox 烟雾 + 示例 assert
- `skills/public/sqlbot-report/scripts/unit_converter.py` — Decimal 域单位换算
- `skills/public/sqlbot-report/codegen_prompts/system.md` — 代码生成系统提示词模板
- `skills/public/sqlbot-report/codegen_prompts/examples.md` — 常见公式（同比/环比/毛利率/占比）few-shot 示例

**单元测试**：
- `backend/tests/sqlbot_report/`（9 个 test_*.py：test_md_lint / test_parse_md / test_sqlbot_client / test_match_indicators / test_indicator_cache / test_render_docx / test_render_markdown / test_retry / test_status + 4 个 v3 计算列相关：test_compute_ir / test_compute_codegen / test_compute_validator / test_unit_conversion）

**集成测试**：
- `backend/tests/integration/sqlbot_report/`（7 + 3 = 10 个场景：happy_path / partial_match / l3_clarification / sqlbot_down / partial_unmapped / hallucination_rejection / cache_effectiveness + v3 三个：test_computed_columns / test_computed_codegen_retry / test_unit_conversion_e2e）

**测试 fixture**：
- `backend/tests/fixtures/sqlbot_report/sample_md/`（happy / lint_error / multi_chapter / partial_unmapped / l3_ambiguous / computed_columns / computed_with_examples / multi_header_computed / unit_conversion）
- `backend/tests/fixtures/sqlbot_report/mock_sqlbot/`（indicators.json / search_responses.json）
- `backend/tests/fixtures/sqlbot_report/expected_outputs/`（happy.json / partial_unmapped.json / computed_columns.json / computed_columns.computed.py.regex / unit_conversion.json）

### 改动文件

- `config.example.yaml` → `summarization` 节点确保开启（已存在，确认启用）
- `skills/public/sqlbot-report/scripts/md_lint.py` — 新增 6 条 lint 规则
- `skills/public/sqlbot-report/scripts/parse_md.py` — 识别 data-unit / 计算块 / 虚拟指标
- `skills/public/sqlbot-report/scripts/match_indicators.py` — 跳过 is_computed=true 的指标
- `skills/public/sqlbot-report/scripts/render_docx.py` — 表头副标 + Decimal 域 scale_factor 渲染
- `skills/public/sqlbot-report/scripts/render_markdown.py` — 计算列 (computed) 标记 + 单位副标
- `skills/public/sqlbot-report/scripts/report_style.json` — 表头副标字号/颜色配置
- `skills/public/sqlbot-report/SKILL.md` — 12 步流水线 + 单位换算 + 计算列章节

### 不改动

- `deerflow.agents.lead_agent.*` 保持不变
- `deerflow.subagents.*` 保持不变（不引入新 subagent）
- LangGraph runtime / Gateway API 不变
- 前端不变
- `SummarizationMiddleware` 保持不变（已存在）
- LangGraph checkpointer 保持不变（已存在）

## SQLBot API 占位契约（待用户提供真实规格）

**已确认**：
- SQLBot 对外是 **HTTP REST API**
- 请求体为 **JSON 格式**，返回也为 JSON

**待确认（PENDING）**：
- 接口端点（`/search`, `/query`, `/indicator/<code>` ...）
- 请求/响应 JSON 字段名
- 鉴权方式（API key / Bearer / OAuth）
- 是否支持「指标按时期参数返多期数据」（影响 Phase 2 同比/环比的查询设计；v3 在 `current/yoy_same/prev_period/ytd` tag 阶段不强依赖 SQLBot 预声明，把校验推迟到 Phase 2 实际拉数时）

### Phase 1 mock 客户端结构（占位）

```python
# SQLBOT_SPEC_PENDING — 真实 schema 待用户提供

@dataclass
class Indicator:
    code: str
    name_cn: str
    name_en: str
    category: str
    unit: str               # SQLBot 返回的原始单位（v3 称为 raw_unit）
    description: str
    # Phase 2 字段（当前 mock 返回 None）：
    # data_type: str | None
    # display_format: str | None
    # time_dimension: str | None
    # data_source: str | None
    # last_updated: str | None
    # version: str | None

class SQLBotClient:
    """
    占位客户端：v3 Phase 1 仅暴露语义层（search / get_indicator）。
    真实 HTTP REST 调用细节在拿到 SQLBot OpenAPI/接口文档后填充。
    """
    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url
        self._api_key = api_key

    def search_indicators(self, keyword: str, limit: int = 20) -> list[Indicator]:
        """HTTP POST {base_url}/search {keyword}（Phase 1 暂用 fixture）"""
        ...

    def get_indicator(self, code: str) -> Indicator:
        """HTTP GET {base_url}/indicator/{code}（Phase 1 暂用 fixture）"""
        ...

    # Phase 2 才接入的真实数据查询接口（v3 暂留接口签名占位）
    def query_data(
        self,
        code: str,
        period: Literal["current", "yoy_same", "prev_period", "ytd"],
        time_range: dict,   # 如 {"start": "2024-01-01", "end": "2024-03-31"}
    ) -> list[dict]:
        """v3 计算列：base_indicators × periods 的笛卡尔积都走这个查询"""
        raise NotImplementedError("Phase 2")
```

mock 实现（`sqlbot_client.py` 内的 `MockSQLBotClient`）返回固定 fixtures 数据，**仅用于开发和测试**。生产前必须按真实 HTTP REST 规格替换。

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| SQLBot 真实 API 与占位契约差异大 | 重写 sqlbot_client.py | 客户端层抽象 + 集成测试覆盖真实 API（待提供后写）|
| LLM 模糊匹配准确率低 | 用户频繁被打断 | 阈值 0.6 可调；LLM 幻觉校验；积累数据后 Phase 2 引入 embeddings |
| DOCX 渲染对复杂多级表头支持不足 | 报表样式丑 | 提供 report_style.json 让用户调样式；data_type 控制数字格式；Phase 2 引入模板系统 |
| 用户不会写 HTML 表格 | MD 样例难产出 | md_lint.py 给清晰错误信息；Phase 2 提供设计 GUI |
| 长流程上下文爆 | lead agent 中断 | SummarizationMiddleware 自动总结（已存在）|
| 中文表格单元格内换行 | DOCX 显示错乱 | parser 把 `\n` 转为段落而非单 cell 多行 |
| LLM 幻觉编造 code | JSON 含不存在的 code | 强校验（不在候选列表直接拒绝 + log）|
| 跨 thread 不缓存 | 同名指标重复 LLM | Phase 1 内存缓存（thread 内）；Phase 2 文件级缓存 |
| **v3** LLM 生成 pandas 代码逻辑错（分子分母搞反）| 报表算错 | 鼓励设计师写示例值；烟雾跑 + 示例 assert；codegen_prompts/examples.md 提供 few-shot |
| **v3** 设计师写自然语言公式歧义大 | LLM IR 提取错 | F12 失败标列，其他列继续；log 保留 LLM 输入输出供审计；后续可改 LLM model |
| **v3** sandbox 没有 pandas | 验证步骤跑不起来 | `.env.example` 提示；启动时检查 sandbox image；缺包 → status=error reason=SANDBOX_MISSING_PANDAS |
| **v3** 同名虚拟指标跨报表冲突 | 复用代码歧义 | code 用 `compute_<hash8>`（hash(报表名+中文名+formula)），自然避冲突 |
| **v3** 单位换算精度（亿元 × 浮点）| DOCX 显示 0.150000000002 | scale_factor 用 Decimal；展示精度由 display_format 控制，与 scale_factor 解耦 |
| **v3** 设计师 data-unit 与业务实际数据单位差 N 倍 | 报表数错 | DOCX 表头副标让设计师肉眼可见单位；F16 WARN；Phase 2 拉数后校验 raw_unit 兼容性 |
| **v3** 计算列 `current/yoy_same/...` 在某些 SQLBot 指标上不支持 | Phase 2 拉数报错 | Phase 1 不阻断；Phase 2 拉数时若 SQLBot 不支持该 period → F12 升级，重新走澄清 |

## 后续 Phase 2 落地要点

- 真实 SQLBot HTTP REST API 接入（按用户后续提供的规格替换 `MockSQLBotClient.search_indicators` / `get_indicator` / `query_data`）
- **计算列拉数 + 跑代码**：`query_data(code, period, time_range)` 按 base_indicators × periods 笛卡尔积拉数，组装 DataFrame，sandbox 跑 `compute_<hash8>(df)`，结果写入 DOCX cell
- **Decimal 单位换算**真正生效在数值维度（设计师写的 `display_unit` 生效到 cell 数值上）

Phase 3+ 范围（滚动窗口 / 报表模板系统 / 设计 GUI / 跨企业复用）属独立 feature，不在本设计追踪。
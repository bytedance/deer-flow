# chatbi-report（data-agent）设计

日期：2026-06-23
分支：`feat/chatbi-report-data-agent`
关联：`query-report-info` 真实契约已提供（2026-06-23），无鉴权

## 范围

报表设计人员上传一份带 `data-idx` 属性 + 中文显示名的 Markdown 报表样例，DeerFlow 内置的 `chatbi-report` 能力端到端产出：

- **结构化 JSON**（含真实数据 + 单位换算）
- **回填后的 Markdown**（中文显示 + idx_id 副标）
- **DOCX 文档**（多级表头 + 单位副标 + 品牌样式）

能力边界：

- MD 表头用 `data-idx` 属性写 SQLBot 指标 ID（`BAS_0263`），单元格文本直接写中文显示名 → **不需要** 中文→指标 ID 匹配流水线，也**不需要** render 阶段调 SQLBot 拿 idx_name
- 调用 SQLBot `query-report-info` 真实接口拉数据（无鉴权）
- 单位声明 `data-unit` 由设计师在 `<th>` 上声明
- 计算列（同比 / 环比 / 占比等）由设计师在 `> 计算:` 块写自然语言公式，LLM 一次性提取 IR + 生成 pandas 代码 + AST / 签名 / 烟雾 / 示例验证

不在本设计范围：报表模板系统、PDF、embedding 语义匹配、滚动窗口、移动平均、跨表关联计算、设计 GUI、跨企业复用。

## 设计原则

1. **不匹配中文名**：MD 用 `data-idx` 属性写指标 ID（SQLBot 用的英文 ID），单元格文本直接写中文显示名；**不需要 L1/L2/L3 中文名匹配、缓存、模糊匹配、ask_clarification、幻觉校验**——idx 和中文名都是设计师手动写的精确字符串
2. **真实拉数**：Phase 1 就调 `query-report-info` 拉真实数据，不再是"生成 + 验证代码占位"
3. **计算列全流程保留**：`> 计算:` 自然语言公式 → LLM 提取 IR（base_idx_ids + periods） → LLM 生成 pandas 代码 → AST 白名单 + 签名 + 烟雾跑 + 示例 assert → 真实数据上跑
4. **单位设计师声明**：`<th data-unit="...">` 显式声明；换算在 `decimal.Decimal` 域进行；展示精度由 `display_format` 控制
5. **机构 / 时期设计师声明**：每张报表必填 `> 机构:` 和 `> 时期:` 块；解析后注入查询参数
6. **失败降级而非中断**：SQLBot 单条 `data[i].success=false` → 标 ⚠️QUERY_FAILED 继续；顶层 `code!=0` 或 HTTP 失败 → 中断
7. **render_docx 完全离线**：中文名已在 MD 里写明，render 阶段只读 `report.json`，**不调 SQLBot**；SQLBot 临时宕机不影响已落盘 JSON 的二次渲染

## 背景与目标

DeerFlow 当前没有「报表生成」能力。报表设计人员目前只能：

1. 在 Markdown 里手写带 `data-idx` 属性和中文显示名的样例；
2. 手工整理 SQLBot 查询参数（机构、指标、时期）；
3. 手工从 SQLBot 复制数据填进表格；
4. 手工写同比 / 环比等计算列公式；
5. 手工用 Word 排版生成 DOCX。

整套流程纯人工，重复劳动大、容易出错。

**目标**：让 DeerFlow 内置 `chatbi-report` 能力，对一份带 `data-idx` 属性 + 中文显示名 和 `> 计算:` 块的 Markdown 报表样例，端到端产出 JSON / 回填 MD / DOCX，并在 SQLBot 查询失败或计算列代码生成失败时**降级而非全错**。

## 方案选型

- **采纳：Lead Agent + SKILL.md + scripts/**
  - `skills/public/chatbi-report/SKILL.md` 作为入口
  - lead agent 通过 SkillActivationMiddleware 自动加载 SKILL.md
  - lead agent 用 `bash` / `read_file` / `write_file` / `str_replace` 调脚本
  - 上下文用 `SummarizationMiddleware` 管理
  - 续跑用 LangGraph checkpointer

否决的方案：

- **Subagent**：代码验证发现 subagent 调 `ask_clarification` 实际无效；复杂度收益被 SummarizationMiddleware + checkpointer 覆盖
- **纯 Skill（wencai 模式）**：实现是 Lead Agent 方案的子集
- **MCP server**：DOCX 渲染是重活不适合 MCP 工具语义；端到端工作流不是 MCP 适合的场景
- **中文→idx_id 匹配**：MD 已写 ID，不需要匹配

## 架构

```
┌──────────────────────────────────────────────────────────┐
│ Layer 1: Skill (入口/触发)                                 │
│ skills/public/chatbi-report/                              │
│ ├── SKILL.md            ← SkillActivationMiddleware 加载 │
│ ├── README.md           ← 配置说明                        │
│ ├── .env.example        ← SQLBOT_BASE_URL（无需 API_KEY）│
│ └── scripts/                                                │
│     ├── sqlbot_client.py        ← SQLBot REST 客户端       │
│     │   （RealSQLBotClient + MockSQLBotClient 双轨）       │
│     ├── md_lint.py              ← 输入校验                  │
│     ├── parse_md.py             ← MD → ReportDoc AST       │
│     ├── compute.py              ← 计算列 IR + 代码生成       │
│     │   + AST/签名/烟雾/示例验证 + Decimal 单位换算        │
│     ├── render_markdown.py  ← 回填 MD（含单位副标）         │
│     ├── render_docx.py      ← python-docx 渲染（含副标）  │
│     ├── retry.py                ← 通用重试装饰器             │
│     └── report_style.json       ← DOCX 样式定义             │
└──────────────────────────────────────────────────────────┘
                              ↓ SkillActivationMiddleware 加载 SKILL.md
┌──────────────────────────────────────────────────────────┐
│ Layer 2: Lead Agent (执行)                                 │
│ （DeerFlow 已存在，不需要新加）                              │
│ - system_prompt 包含 SKILL.md（hidden context）            │
│ - tools: bash, read_file, write_file, str_replace          │
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
│ ├── report.computed.py    (仅当有计算列时)                │
│ ├── report.query.log                                        │
│ └── report.status.json                                      │
└──────────────────────────────────────────────────────────┘
```

## Lead Agent 9 步流水线

```
[1] 读取 MD 文件
       bash: cat /mnt/user-data/uploads/{user_md}

[2] 调用 md_lint.py 校验格式
       - 真实指标列是否含 data-idx 属性（计算列和多级表头分类标签除外）
       - 计算列是否用 {{虚拟名}} 形式且不同时有 data-idx
       - HTML table 是否闭合（<thead> / <tbody> 都有）
       - 每张报表是否含 > 机构: 和 > 时期: 块（F19 触发条件）
       - idx_id 格式（regex ^[A-Z]+_\d+$）
       - data-unit 枚举值合法性
       - > 计算: 块每行格式 <虚拟名> = <公式>
       报错则中断并列出错误（F1）

[3] 解析 MD → in-memory AST
       ReportDoc {
         title, sections[], all_idx_ids: set
         Section { title, reports[] }
         Report {
           title, org_context, time_info, headers: Th[][],   # 二维数组（多级表头）
           data_rows, computed_specs: ComputedSpec[],
         }
         Th {
           text,                       # 单元格文本 = 中文显示名（主写法）
           is_indicator(bool),          # 有 data-idx=true
           idx_id?: str,                # 仅 is_indicator=true 时存在
           data_unit?: str,
           is_computed(bool),           # 是 {{虚拟名}}=true
           rowspan?: int,
           colspan?: int,
         }
       }
       区分逻辑：
         <th data-idx="X" data-unit="...">中文名</th>        → is_indicator=true, is_computed=false
         <th data-unit="...">{{虚拟名}}</th>（无 data-idx）   → is_indicator=false, is_computed=true
         <th rowspan/colspan>分类标题</th>（无 data-idx）     → is_indicator=false, is_computed=false（仅分类标签）
         兼容：<th data-unit="...">{{BAS_0263}}</th>          → is_indicator=true（旧写法，lint WARN）

[4] 收集所有非计算列 idx_id 去重，组织 SQLBot 查询参数
       index_info = [{"idx_id": id} for id in all_idx_ids]
       org_info   = [{report.org_context.branch_num, branch_short_name}]
       time_info  = [report.time_info values]

[5] 调用 query-report-info 拉数（**每个 idx_id 一次 HTTP**，并行执行）
       for idx_id in all_idx_ids (parallel via asyncio.gather):
         python sqlbot_client.py query-report-info \
           --org-info '[{...}]' \
           --index-info '[{"idx_id": idx_id}]' \
           --time-info '[...]'
       每调用返回该 idx_id 的所有数据行；1:1 映射零歧义
       顶层 code != 0 → F17 中断（任何一次调用失败都中断整个 report）
       data[i].success == false → 该 idx_id 标 ⚠️QUERY_FAILED，继续其他 idx

[6] 长表 → 宽表透视
       a) 把所有 idx_id 的 response.data[].data[] 铺平为
          lookup: (idx_id, data_dt, org_ecd) → raw_value (string)
       b) 按 MD tbody 模板行（data_dt）生成 wide_rows：
          - 每行对应一个 data_dt × org_ecd 组合
          - 每单元格从 lookup 查 raw_value，按 data-unit 在 decimal 域换算
          - 查不到 → ⚠️QUERY_FAILED
       c) 计算列留到 step 8 处理

[7] 计算列 IR 提取（batched LLM）
       a) lead agent 一次性把所有 ComputedSpec.prompt 拼成一个 batched LLM 调用
          输入：自然语言公式 + 表头 data-idx 列表 + 已查到的 idx_id→raw_value
          输出：{formula_repr, base_idx_ids, periods}
       b) base_idx_ids 必须在 step 5 已查询集合中，否则该列 F12 失败
       c) periods 推断："本期/当期"→current，"去年同期/同期"→yoy_same，
          "上期/上月/上季度"→prev_period，"年初至今/累计"→ytd

[8] 计算列代码生成 + 验证
       对每个 ComputedSpec：
         a) lead agent 调 LLM 生成 compute_<report_id>_<col_slug>(df: pd.DataFrame) -> pd.Series
            （同一次 prompt 让 LLM 一并返回 3 行烟雾数据）
         b) AST 白名单：仅允许 BinOp / UnaryOp / Subscript / Call(限定到 df.* / pd.* / np.*)
            / Name / Constant / IfExp。禁 Import / ImportFrom / Attribute(os/sys/subprocess/socket) / Global
         c) 签名检查：函数名匹配 compute_<report_id>_<col_slug>，参数 (df: pd.DataFrame)，返回 pd.Series
         d) 烟雾跑：sandbox 内组装 DataFrame，跑函数，assert isinstance(out, pd.Series)
         e) 若设计师写了 .示例: 组装对应 DataFrame，跑函数，math.isclose(out, expected, rel_tol=1e-6)
         f) 任意一步失败 → 重试 1 次（附错误信息给 LLM）→ 仍失败 → 跳过该列，
            标 compute_validation_failed / compute_smoke_failed，其他列继续
         g) 全部 compute 函数追加到 report.computed.py

[9] 单位换算 + 组装 JSON + 渲染 DOCX + 回填 MD
       - 单位换算在 decimal.Decimal 域进行
       - JSON 写入 raw_value + value（换算后）+ data_dt + org_ecd
       - DOCX 表头副标 + 单元格按 display_format 格式化
       - 回填 MD：直接读 MD 的中文显示名 + data-unit；计算列保留 (computed) 标记
```

### 续跑语义

Phase 1 不需要手写 checkpoint——LangGraph checkpointer 自动持久化 lead agent 的 state（包括所有 tool call 结果）。用户中途退出后回到同一 thread_id 对话，lead agent 从上次中断的 turn 继续。

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
  org_context_block:    "> 机构: branch_num=<code>; branch_short_name=<name>"   必填
  time_info_block:      "> 时期: time_info=[\"<year>\", ...]"                       必填
  compute_block?:       "> 计算: <计算列定义，多行>"                                可选
  table: <HTML table>

table:
  thead: rows+   # 至少一行；多级表头对应多行
  tbody: rows+   # Phase 1 不要求 tbody 有数据，运行时按 data_dt 反填
  row: th+ | td+

th:
  attrs:
    data-idx?: "<idx_id>"        # 真实指标列必须有；格式 ^[A-Z]+_\d+$
    data-unit?: "<元|万元|亿元|%|百分点|个|次|自定义>"
    rowspan?: int                # 多级表头
    colspan?: int                # 多级表头
  content:
    - text                       # 任意字符串（真实指标列 = 中文显示名）
    - "{{<虚拟指标名>}}"          # 计算列；同名必须在 > 计算: 块左侧
```

**lint 区分规则**：

- 有 `data-idx` → 真实指标列 → `is_indicator=true`
- 是 `{{虚拟指标名}}` → 计算列 → `is_computed=true`
- 既无 `data-idx` 也无 `{{虚拟名}}` → 分类标签（多级表头父级）或 lint ERROR

**父级 `<th>`（多级表头分类标签）**：可以只有 `rowspan/colspan`，没有 `data-idx`（纯分类标签，不参与数据列）。

### MD 完整示例

```markdown
# 王益联社 2025 年度经营报表

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]
> 计算:
>   收单商户同比 = 本期BAS_0263减去年同期再除同期
>   收单商户.示例: BAS_0263[current=1420, yoy_same=1200] -> 0.1833

<table>
  <thead>
    <tr>
      <th rowspan="2">季度</th>
      <th colspan="2">商户与贷款</th>
    </tr>
    <tr>
      <th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
      <th data-unit="%">{{收单商户同比}}</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>2025-Q4</td>
      <td></td>
      <td></td>
    </tr>
  </tbody>
</table>
```

**关键点**：

- `data-idx="BAS_0263"` 携带 SQLBot ID；单元格内容 `贷款收单商户数` = 中文显示名
- `data-unit="%"` + `{{收单商户同比}}` 标识计算列
- 多级表头：父级 `<th rowspan/colspan>` 是分类标签，叶子 `<th>` 才有 `data-idx` / `{{虚拟名}}`
- render_docx 完全从 MD 单元格的文本读 idx_name，**不调 SQLBot**

### `> 机构:` 块

每张报表必填；提供 SQLBot `org_info` 参数：

```
> 机构: branch_num=27020199; branch_short_name=王益联社
```

| 字段 | 来源 | 说明 |
|------|------|------|
| `branch_num` | 设计师写 | SQLBot 机构代码 |
| `branch_short_name` | 设计师写 | SQLBot 机构简称 |

> 多个机构时用分号分隔：`branch_num=A; branch_short_name=A; branch_num=B; branch_short_name=B`。简化起见，Phase 1 每张报表只支持单机构。

### `> 时期:` 块

每张报表必填；提供 SQLBot `time_info` 参数（JSON 数组字符串）：

```
> 时期: time_info=["2025"]
> 时期: time_info=["2025", "2024"]            # 双年份，用于 YoY 计算列
> 时期: time_info=["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]
> 时期: time_info=["2025-01-01~2025-12-31"]    # 日期区间
```

### 指标 ID 标记 `data-idx` 属性

**主写法（推荐）**：在 `<th>` 上加 `data-idx` 属性，单元格文本直接写中文显示名：

```html
<th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
```

| 字段 | 含义 |
|------|------|
| `data-idx` | SQLBot 指标 ID，**唯一标识** |
| 单元格文本 | 中文显示名（render 时直接显示） |
| `data-unit` | 显示单位（可选） |

合法格式：`^[A-Z]+_\d+$`（如 `BAS_0263`）。lint 校验。

**旧写法（兼容）**：设计师仍可写 `{{BAS_0263}}` 占位符风格，lint WARN 不阻断：

```html
<th data-unit="个">{{BAS_0263}}</th>
```

此时 `idx_id=BAS_0263`（从占位符里抽），但 `text="BAS_0263"`（没有中文显示名）。**render 时回退到 SQLBot lookup 拿 idx_name**（旧行为）。

### 计算列标记 `{{虚拟指标名}}`

- 计算列的表头用 `{{}}`，但必须**无 `data-idx` 属性**
- 同名必须出现在 `> 计算:` 块左侧
- parser 标 `is_computed=true`，不发送到 SQLBot
- 公式右侧是**自由文本**，由 lead agent 调 LLM 提取 IR

```html
<th data-unit="%">{{商户数同比}}</th>
```

### 列级单位声明 `data-unit`

设计师在 `<th>` 上加 `data-unit` 属性，声明该列**显示单位**：

```html
<th data-unit="个">{{BAS_0263}}</th>
<th data-unit="万元">{{BAS_0201}}</th>
<th data-unit="%">{{毛利率}}</th>
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

**转换语义**：

```
display_value = Decimal(raw_value) * Decimal(raw_unit_scale) / Decimal(display_unit_scale)
# raw_unit_scale 来自 SQLBot Indicator.unit（Phase 1 默认 Decimal("1")，待 get_indicator 接入）
# display_unit_scale 来自 MD 的 data-unit
```

**精度策略**：换算和展示一律在 `decimal.Decimal` 域进行。DOCX 输出由 `display_format`（默认按 `data_type` 推导）控制小数位数；`scale_factor` 只负责量纲。

### 计算块 `> 计算:`

设计师在 `> 描述:` 块（可选）下方添加 `> 计算:` 块，用**自然语言**写公式：

```
> 计算:
>   营收同比 = 本期BAS_0263减去年同期再除同期
>   成本同比 = 本期BAS_0264减去年同期再除同期
>   毛利率 = (BAS_0263 - BAS_0264) / BAS_0263
>   营收同比.示例: BAS_0263[current=200, yoy_same=100] -> 1.0
```

**核心约定**：

- 每行：`<虚拟指标名> = <自然语言公式>`
- 公式右侧引用的 idx_id 必须能在表头 `data-idx` 已查询集合中找到，否则 lint ERROR
- 时期 tag 由 LLM 推断：`本期/当期` → current；`去年同期/同期` → yoy_same；`上期/上月/上季度` → prev_period；`年初至今/累计` → ytd

**示例值（可选，不阻塞）**：

- 格式：`<虚拟指标名>.示例: <idx_id>[period1=val, period2=val, ...] -> <期望值>`
- 同一虚拟指标可写多行示例
- Phase 1 验证时若有示例，sandbox 跑生成的 pandas 函数并 `assert math.isclose(out, expected, rel_tol=1e-6)`
- 没写示例的列只跑类型 / 形状烟雾测试

### 多表头里计算列重名

如同名计算列出现在不同表头分支，建议起**唯一中文名**（"营收同比" / "成本同比"）。

- lint WARN：同名虚拟指标出现 > 1 次 → 提示设计师起更精确的名字
- parser 兜底：以 "表头路径前缀 + 列名" 生成内部 ID（仅用于 JSON `code` 字段去重）

### Lint 规则

| 规则 | 等级 |
|------|------|
| `<table>` 必须有 `<thead>` 和 `<tbody>` | ERROR |
| 章节必须含至少一个报表 | ERROR |
| 每张报表必须含 `> 机构:` 和 `> 时期:` 块 | ERROR（F19 触发） |
| `> 机构:` 块格式 `branch_num=<code>; branch_short_name=<name>` | ERROR |
| `> 时期:` 块格式 `time_info=[...]`（JSON 数组）| ERROR |
| 真实指标列必须有 `data-idx` 属性（计算列和多级表头分类标签除外）| ERROR |
| `data-idx` 格式 `^[A-Z]+_\d+$` | ERROR |
| 计算列必须用 `{{虚拟名}}` 且不能同时有 `data-idx` | ERROR |
| 多级表头用 `<th rowspan/colspan>`，不用 markdown 表格 | WARN |
| `data-unit` 在枚举值内 | WARN |
| `> 计算:` 块每行格式 `<name> = <expr>`，长度 1-200 字 | ERROR |
| 表头计算列名必须出现在 `> 计算:` 左侧 | ERROR |
| `> 计算:` 公式右侧引用的 idx_id 必须在表头 `data-idx` 集合中 | ERROR（lint 阶段）+ F12（IR 阶段） |
| 多表头里同名虚拟指标多次出现 | WARN |
| `<名>.示例:` 格式 `<idx_id>[k=v,...] -> 数值` | WARN（解析失败的示例丢弃）|
| 旧 `{{idx_id}}` 占位符写法（无 `data-idx` 但有 `{{}}`）| WARN（兼容；render 时回退到 SQLBot lookup）|

## SQLBot API 契约

**已确认**：

- SQLBot 对外是 **HTTP REST API**
- 请求体为 **JSON 格式**，返回也为 JSON
- `query-report-info` 端点契约已知（2026-06-23 提供）
- **无需鉴权**（用户确认 2026-06-23）

**待确认（PENDING）**：

- 指标搜索 / 单指标详情接口端点与字段
- 是否支持「指标按时期参数返多期数据」（在 `current/yoy_same/prev_period/ytd` tag 阶段不强依赖 SQLBot 预声明，把校验推迟到实际拉数时）

### 已知接口：`query-report-info`（数据查询）

**端点**：`POST {SQLBOT_BASE_URL}/api/v1/indicator/query-report-info`

**用途**：根据机构、指标、时期查询实际报表数据。请求支持**多机构 × 多指标 × 多时间**的笛卡尔积，`data` 数组每个元素对应一组 (org, idx, time) 的查询结果。

#### 请求示例

```bash
curl -s -X POST "http://9.6.232.51:9070/api/v1/indicator/query-report-info" \
  -H "Content-Type: application/json" \
  -d '{
    "org_info": [
      {
        "branch_num": "27020199",
        "branch_short_name": "王益联社"
      }
    ],
    "index_info": [
      {
        "idx_id": "BAS_0263"
      }
    ],
    "time_info": ["2025"]
  }'
```

#### 请求字段

| 字段 | 类型 | 必填 | 含义 |
|------|------|------|------|
| `org_info` | array | ✅ | 机构过滤条件；每项含 `branch_num`（机构代码）+ `branch_short_name`（机构简称） |
| `index_info` | array | ✅ | 指标过滤条件；每项含 `idx_id`（如 `BAS_0263`） |
| `time_info` | array | ✅ | 时间过滤条件；元素为年份字符串（如 `"2025"`）、季度（如 `"2025-Q1"`）或日期区间 |

> Phase 1 单机构；多机构时 `org_info` 加多个元素。

#### 响应示例

```json
{
  "code": 0,
  "data": [
    {
      "success": true,
      "msg": "指标数据查询成功。",
      "record_id": 0,
      "sql": "[...]",
      "data": [
        {
          "data_dt": "2025-12-31",
          "org_ecd": "王益联社",
          "idx_name": "贷款收单商户数",
          "value": "1,420.00"
        }
      ],
      "data_interpret": "...",
      "fields": [
        {"name": "日期",     "value": "data_dt"},
        {"name": "机构名称", "value": "org_ecd"},
        {"name": "指标名称", "value": "idx_name"},
        {"name": "指标值",   "value": "value"}
      ],
      "chart": {
        "type": "table",
        "title": "columns",
        "columns": [
          {"name": "日期",     "value": "data_dt"},
          {"name": "机构名称", "value": "org_ecd"},
          {"name": "指标名称", "value": "idx_name"}
        ]
      }
    }
  ]
}
```

#### 响应字段

| 字段 | 类型 | 含义 |
|------|------|------|
| `code` | int | 顶层状态码；`0` = 成功，非 0 = 失败 |
| `data` | array | 结果数组；每个元素对应请求笛卡尔积中一组 (org, idx, time) 的查询结果 |
| `data[].success` | bool | 该组查询是否成功 |
| `data[].msg` | str | 中文提示信息 |
| `data[].record_id` | int | 结果记录 ID（用于关联查询 / 日志） |
| `data[].sql` | str | SQLBot 内部生成的 SQL（调试用） |
| `data[].data` | array | 实际数据行；每行为 `{data_dt, org_ecd, idx_name, value}` |
| `data[].data_interpret` | str | 自然语言解读（可用于报告文字段落） |
| `data[].fields` | array | 字段映射；`name` = 中文显示名，`value` = 字段键（用于渲染表头） |
| `data[].chart` | object | 图表配置；`type=table` 时 `columns` 列出展示列 |

#### 关键映射（SQLBot ↔ 内部模型）

| SQLBot 字段 | 内部模型 | 说明 |
|-------------|----------|------|
| `index_info[].idx_id` | `Th.idx_id`（MD 写在 `data-idx` 属性） | 例：`BAS_0263` |
| `org_info[].branch_num` | `OrgContext.branch_num`（来自 `> 机构:`） | 例：`27020199` |
| `org_info[].branch_short_name` | `OrgContext.branch_short_name`（来自 `> 机构:`） | 例：`王益联社` |
| `time_info` | `TimeInfo`（来自 `> 时期:`） | 例：`["2025"]` |
| `data[].data[].data_dt` | 报告 `data_dt` 列 | 时间维度 |
| `data[].data[].org_ecd` | 报告 `org_ecd` 列 | 机构显示名 |
| `data[].data[].idx_name` | **不消费**（MD 已写中文显示名） | 仅 log 记录，不参与渲染 |
| `data[].data[].value` | 报告 `value` 列（**字符串**带千分位，如 `"1,420.00"`） | 必须先 `str.replace(",", "")` 再 `Decimal(...)`，否则换算失败 |
| `data[].fields[].value` | 表头字段键 | DOCX 渲染时按 `fields` 顺序输出表头 |
| `data[].chart.columns` | 表格展示列定义 | 与 `fields` 类似但可选 |

#### ⚠️ Phase 1 已知缺口：idx_id ↔ 数据行关联

**问题**：SQLBot 响应里每行带 `idx_name`（中文名，如 `"贷款收单商户数"`）和 `value`，**但不直接返回** `idx_id`（如 `BAS_0263`）。MD 写的是 idx_id，无法直接靠响应字段做反向匹配。

> **注**：`idx_name` 在新方案下已不再用于渲染（中文名直接由 MD 提供）。这里只关心**数据行归属**——哪个 `value` 属于哪个 `idx_id`。

**解决方案：每个 idx_id 一次 HTTP 调用**

放弃"假设响应顺序"——改为每个 idx_id 单独发一次 `query-report-info`，返回的数据行天然只属于这一个 idx_id，1:1 映射零歧义。

```python
async def fetch_all_indicator_data(
    sqlbot_client, org_info, idx_ids, time_info
) -> dict[str, QueryReportInfoResponse]:
    """
    并行查询所有 idx_id；返回 {idx_id: response}
    """
    async def one(idx_id: str) -> tuple[str, QueryReportInfoResponse]:
        resp = sqlbot_client.query_report_info(
            org_info=org_info,
            index_info=[{"idx_id": idx_id}],   # ← 只放一个 idx_id
            time_info=time_info,
        )
        return idx_id, resp

    pairs = await asyncio.gather(*[one(idx) for idx in idx_ids])
    return dict(pairs)
```

**为什么用 per-idx 调用（而不是 batch）**：

| 维度 | batch（一次 HTTP 多 idx） | per-idx（每个 idx 一次 HTTP） |
|------|--------------------------|-------------------------------|
| 可靠性 | 依赖响应顺序保证（SQLBot 未文档化） | **1:1 零歧义**（响应只含该 idx 的行）|
| 性能（10 idx）| ~100ms（1 次 HTTP）| ~100-200ms（`asyncio.gather` 并行 10 次）|
| 失败降级粒度 | 整批失败 | 单 idx 失败 → 仅该 idx 标 ⚠️QUERY_FAILED |
| 实现复杂度 | 需顺序假设 + 异常路径 | 简单 for 循环 |

**取舍**：多 9 次 HTTP（约 100ms 增量），换来零歧义映射与单 idx 失败降级。生产值得。

**未来优化**：拿到 `get_indicator` 端点后，构建全局 `idx_id ↔ idx_name` 映射，可回到 batch 调用（一次 HTTP 多 idx，按 idx_name 反查）——但 Phase 1 不阻塞等待。

#### chart 字段处理

**问题**：响应里 `chart` 字段是 SQLBot 推荐的渲染元数据：

```json
{
  "chart": {
    "type": "table",
    "title": "columns",
    "columns": [
      {"name": "日期", "value": "data_dt"},
      {"name": "机构名称", "value": "org_ecd"},
      {"name": "指标名称", "value": "idx_name"}
    ]
  }
}
```

**关键观察**：`chart.columns` 只列维度列（date / org / indicator name），**没有 value 列**——SQLBot 把 value 当 measure 处理。

**Phase 1 决策：不消费 chart 字段**

| 来源 | 角色 |
|------|------|
| **MD schema**（thead + `data-idx` 属性 + 中文显示名 + `data-unit` + `> 计算:`） | **唯一事实源**：列顺序、单位、计算列、计算公式、中文显示名 |
| SQLBot `chart` / `fields` | **日志用**：写到 `report.query.log` 留作调试，不参与渲染 |

**为什么不消费 chart**：

1. 设计师写 MD 时已经定了列顺序、单位、计算逻辑、中文显示名（写 `data-idx` + 单元格文本）——SQLBot 不知道设计师的意图，chart 是它的推荐而非指令
2. `chart.type="table"` 与我们默认渲染一致，没有新信息
3. `chart.columns` 只列维度列，无 value 列，不能用作最终列定义
4. 任何"以 chart 为准"的逻辑都会引入"MD 改了 SQLBot 不知道"的双源不一致问题

**为什么连 `idx_name` 都不消费**（新方案）：

- 旧方案：MD 写 `{{BAS_0263}}` → 中文名从 SQLBot 响应 `idx_name` 拿 → render_docx 依赖 SQLBot
- 新方案：MD 写 `data-idx="BAS_0263"` + 单元格文本 `贷款收单商户数` → 中文名直接来自 MD → render_docx 完全离线

SQLBot 响应里的 `idx_name` 现在仅写到 `report.query.log` 留作调试用。

**未来扩展**（不在 Phase 1）：

- `chart.type` 不为 `"table"`（如 `"bar"`/`"line"`）→ 触发 DOCX 图表渲染路径（需要新能力，超出 Phase 1）
- 把 `chart.columns` 与 MD 列定义交叉校验，warn 漏列/多列（轻度增强）

#### 长表 → 宽表透视（step 6 详解）

**输入**：per-idx responses（每个 idx_id 一份 response）

**目标**：生成 wide-format 报告行，每行对应 `(data_dt, org_ecd)`，每列对应 MD thead 叶子行中的 `data-idx` 或 `{{虚拟名}}`

```python
def assemble_wide_table(
    per_idx_responses: dict[str, QueryReportInfoResponse],
    md_report: Report,
) -> list[dict]:
    """
    长表 → 宽表透视
    """
    # 1. 铺平为 (idx_id, data_dt, org_ecd) → raw_value (str)
    lookup: dict[tuple, str] = {}
    failed_idx_ids: set[str] = set()
    for idx_id, resp in per_idx_responses.items():
        for elem in resp.data:
            if not elem.get("success"):
                failed_idx_ids.add(idx_id)
                continue  # F18
            for row in elem["data"]:
                key = (idx_id, row["data_dt"], row["org_ecd"])
                lookup[key] = row["value"]   # str 带千分位

    # 2. 按 MD tbody 模板生成行骨架
    wide_rows = []
    for tmpl_row in md_report.tbody_template:
        data_dt = tmpl_row["data_dt"]
        org_ecd = tmpl_row.get("org_ecd") or md_report.org_context.branch_short_name

        cells = {}
        raw_cells = {}
        for header_row in md_report.headers:
            for header in header_row:
                if header.is_computed or header.idx_id is None:
                    continue  # 计算列在 step 8 算；纯分类标签跳过
                idx_id = header.idx_id
                raw_value = lookup.get((idx_id, data_dt, org_ecd))
                if idx_id in failed_idx_ids or raw_value is None:
                    cells[idx_id] = "⚠️QUERY_FAILED"
                    raw_cells[idx_id] = None
                else:
                    # 千分位 → Decimal，再按 data-unit 换算
                    raw_cells[idx_id] = raw_value.replace(",", "")
                    cells[idx_id] = convert_unit(
                        Decimal(raw_value.replace(",", "")),
                        header.data_unit,
                    )  # Decimal 域换算

        wide_rows.append({
            "data_dt": data_dt,
            "org_ecd": org_ecd,
            "cells": cells,
            "raw_cells": raw_cells,
        })

    return wide_rows
```

**关键决策**：

| 维度 | 来源 |
|------|------|
| **行的索引** | MD tbody 模板行的 `data_dt`（+ `org_ecd` 如果多机构）|
| **列的索引** | MD thead 叶子行的 `data-idx` 和 `{{虚拟名}}` |
| **单元格查找键** | `(idx_id, data_dt, org_ecd)` 三元组 |
| **单元格值** | `lookup[key]`，查不到 → ⚠️QUERY_FAILED |
| **单位换算** | `decimal.Decimal` 域，避免 float 精度损失 |
| **计算列** | 留到 step 8（基于已透视的 cells 在同 row 内计算）|

### 客户端结构

```python
@dataclass
class OrgContext:
    branch_num: str          # SQLBot 的 branch_num，如 "27020199"
    branch_short_name: str   # SQLBot 的 branch_short_name，如 "王益联社"

@dataclass
class QueryReportInfoResponse:
    code: int
    data: list[dict]         # 见上文响应结构
    # raw SQL 透传给 log；data_interpret 可选消费

class SQLBotError(Exception):
    """SQLBot HTTP 失败 / 顶层 code != 0"""

class SQLBotClient:
    """真实 SQLBot REST 客户端（无鉴权）。"""
    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")

    def query_report_info(
        self,
        org_info: list[dict],    # [{"branch_num": ..., "branch_short_name": ...}, ...]
        index_info: list[dict],  # [{"idx_id": ...}, ...]
        time_info: list[str],    # ["2025", ...]
    ) -> QueryReportInfoResponse:
        """
        真实接口：POST {base_url}/api/v1/indicator/query-report-info
        无鉴权。

        Phase 1 调用约定：每次调用 `index_info` 只放一个 `idx_id`，
        使响应数据行与 idx_id 1:1 对应（解决 SQLBot 响应不带 idx_id 的缺口）。
        多 idx_id 并行查询由 lead agent 用 asyncio.gather 编排。
        """
        resp = requests.post(
            f"{self._base_url}/api/v1/indicator/query-report-info",
            json={
                "org_info": org_info,
                "index_info": index_info,
                "time_info": time_info,
            },
            headers={"Content-Type": "application/json"},  # 无 Authorization
            timeout=30,
        )
        resp.raise_for_status()  # HTTP 4xx/5xx 抛 RequestException（F17）
        payload = resp.json()
        if payload.get("code") != 0:
            raise SQLBotError(
                f"query_report_info failed: code={payload.get('code')}, "
                f"msg={payload.get('msg')}"
            )
        return QueryReportInfoResponse(code=payload["code"], data=payload["data"])


class MockSQLBotClient(SQLBotClient):
    """测试用：从 fixtures 读假数据，按 per-idx 调用语义返回"""
    def __init__(self, fixture_path: str):
        self._fixture = json.loads(Path(fixture_path).read_text())
        # 不调 __init__

    def query_report_info(self, org_info, index_info, time_info) -> QueryReportInfoResponse:
        # 模拟单 idx_id 调用：从 fixture 找匹配的 idx_id 数据行
        idx_id = index_info[0]["idx_id"]
        rows = self._fixture.get(idx_id, {}).get("data", [])
        # 支持 success=false 场景用于 F18 测试
        success = self._fixture.get(idx_id, {}).get("success", True)
        return QueryReportInfoResponse(
            code=0,
            data=[{
                "success": success,
                "msg": "指标数据查询成功。" if success else "数据不可用。",
                "record_id": 0,
                "sql": "[...]",
                "data": rows,
                "data_interpret": "...",
                "fields": [...],
                "chart": {"type": "table", "title": "columns", "columns": [...]},
            }],
        )
```

## 输出契约 1：JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SqlbotReport",
  "type": "object",
  "required": ["title", "sections", "metadata"],
  "properties": {
    "title": {"type": "string"},
    "report_id": {"type": "string", "format": "uuid"},
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
              "required": ["report_id", "title", "headers", "data", "indicators"],
              "properties": {
                "report_id": {"type": "string"},
                "title": {"type": "string"},
                "org_context": {
                  "type": "object",
                  "required": ["branch_num", "branch_short_name"],
                  "properties": {
                    "branch_num": {"type": "string"},
                    "branch_short_name": {"type": "string"}
                  }
                },
                "time_info": {
                  "type": "array",
                  "items": {"type": "string"}
                },
                "headers": {
                  "type": "array",
                  "description": "多级表头，每行一个数组；外层数组对应 <thead> 的行，内层数组是该行的所有 <th>",
                  "items": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "text": {"type": "string", "description": "单元格显示文本（真实指标列 = MD 里的中文名；计算列 = 虚拟名；分类标签 = 分类标题）"},
                        "idx_id": {"type": "string", "description": "SQLBot 指标 ID（来自 data-idx 属性）；仅 is_indicator=true 时存在；计算列无此字段"},
                        "is_indicator": {"type": "boolean", "description": "是否为真实指标列（data-idx 存在则为 true）"},
                        "is_computed": {"type": "boolean", "description": "是否为计算列（{{虚拟名}} 形式则为 true）"},
                        "data_unit": {"type": "string", "description": "显示单位（来自 data-unit 属性）；分类标签可省略"},
                        "rowspan": {"type": "integer"},
                        "colspan": {"type": "integer"}
                      }
                    }
                  }
                },
                "data": {
                  "type": "array",
                  "description": "二维表数据，每行对应一个 data_dt",
                  "items": {
                    "type": "object",
                    "properties": {
                      "data_dt": {"type": "string", "description": "YYYY-MM-DD"},
                      "org_ecd": {"type": "string"},
                      "cells": {
                        "type": "object",
                        "description": "key=idx_id 或虚拟指标名；value=Decimal 字符串（已换算）",
                        "additionalProperties": {"type": "string"}
                      },
                      "raw_cells": {
                        "type": "object",
                        "description": "key=idx_id；value=Decimal 字符串（未换算）",
                        "additionalProperties": {"type": "string"}
                      }
                    }
                  }
                },
                "indicators": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "required": ["idx_id", "is_computed"],
                    "properties": {
                      "idx_id": {"type": "string"},
                      "is_computed": {"type": "boolean"},
                      "raw_unit": {"type": "string"},
                      "display_unit": {"type": "string"},
                      "scale_factor": {"type": "string", "description": "Decimal 字符串"},
                      "data_type": {
                        "enum": ["number", "currency", "percentage", "ratio"]
                      },
                      "compute_spec": {
                        "type": "object",
                        "description": "仅 `is_computed=true` 时存在",
                        "required": ["prompt", "function", "validation"],
                        "properties": {
                          "prompt": {"type": "string"},
                          "function": {"type": "string", "description": "如 compute_<report_id>_<col_slug>"},
                          "base_idx_ids": {"type": "array", "items": {"type": "string"}},
                          "periods": {"type": "array", "items": {"type": "string"}},
                          "examples": {
                            "type": "array",
                            "items": {
                              "type": "object",
                              "properties": {
                                "inputs": {"type": "object", "additionalProperties": {"type": "string"}},
                                "expected": {"type": "string"}
                              }
                            }
                          },
                          "validation": {
                            "type": "object",
                            "required": ["ast_check", "signature_check", "smoke_run"],
                            "properties": {
                              "ast_check": {"enum": ["passed", "failed"]},
                              "signature_check": {"enum": ["passed", "failed"]},
                              "smoke_run": {"enum": ["passed", "failed"]},
                              "example_check": {"enum": ["passed", "failed", "not_provided"]},
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
      "required": ["generated_at", "total_indicators", "queried_count", "unqueried_count", "computed_count"],
      "properties": {
        "generated_at": {"type": "string", "format": "date-time"},
        "total_indicators": {"type": "integer"},
        "queried_count": {"type": "integer"},
        "unqueried_count": {"type": "integer"},
        "computed_count": {"type": "integer"},
        "query_failures": {"type": "integer", "description": "data[i].success=false 的条数"},
        "compute_validation_failures": {"type": "integer"},
        "duration_seconds": {"type": "number"}
      }
    },
    "computed_code": {
      "type": "object",
      "description": "lead agent 生成的 pandas 计算代码。仅当存在计算列时出现。",
      "properties": {
        "file": {"type": "string", "const": "report.computed.py"},
        "function_names": {"type": "array", "items": {"type": "string"}}
      }
    }
  }
}
```

## 输出契约 2：DOCX 结构

```
report.docx:
├── 标题 (Heading 1)
├── 章节 (Heading 2)
│   └── 报表 (Heading 3)
│       ├── 描述段落 (Normal，可选)
│       ├── 数据表 (python-docx Table)
│       │   ├── 表头：多级用 cell.merge() 合并
│       │   ├── 表头单元格：粗体 + 底色 (#F0F0F0)
│       │   ├── 表头副标：idx_id 下方一行小字显示 "(单位)"，如 "(万元)" / "(%)"
│       │   ├── 数据单元格：按 display_format 格式化（千分位 / 百分比 / 货币）
│       │   └── ⚠️QUERY_FAILED / ⚠️COMPUTE_FAILED 单元格显示警告文案
│       └── 备注 (失败原因)
```

### 表头副标渲染规则

```
┌──────────────────────┐
│  贷款收单商户数        │  ← Heading 文本（粗体；直接读 headers[].text）
│  (个)                 │  ← 单位副标（同一 cell，小一号字 + 灰色）
└──────────────────────┘
```

- 仅当 `data_unit` 不为空时渲染单位副标
- **Heading 文本直接读 `headers[].text`**（来自 MD 单元格，**不调 SQLBot**）
- 副标字号：主标 × 0.8；颜色 #666666
- 兼容路径：如果 `headers[].text` 是 idx_id（如旧 `{{BAS_0263}}` 占位符写法），render_docx 才会回退到 SQLBot 拿 idx_name

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

把 `<th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>` 渲染成 markdown 表格列头 `贷款收单商户数 (个)`：

```markdown
| 季度 | 贷款收单商户数 (个) | 商户数同比 (%) |
|------|---------|------|
| 2025-12-31 | 1,420 | 18.33% |
| 2024-12-31 | 1,200 | — |
```

未查询成功标 `⚠️QUERY_FAILED`，计算列代码生成失败标 `⚠️COMPUTE_FAILED`：

```markdown
| 贷款收单商户数 (个) ⚠️QUERY_FAILED | 商户数同比 (computed) ⚠️COMPUTE_FAILED |
```

**对比旧版**：回填 MD 不再嵌入 `(BAS_0263)` idx_id —— 中文名 + 单位就够了，渲染时直接读 `headers[].text`。

## 决策日志 `report.query.log`

```
[2026-06-23 10:23:45] lint: 1 章节 2 报表，2 个 idx_id，3 个计算列
[2026-06-23 10:23:45] parse: org_context={branch_num=27020199, branch_short_name=王益联社}
[2026-06-23 10:23:45] parse: time_info=["2025", "2024"]
[2026-06-23 10:23:45] query_report_info: per-idx parallel, 3 idx_ids × 1 org × 2 times → 3 HTTP calls (asyncio.gather)
[2026-06-23 10:23:46] query_report_info: BAS_0263 → HTTP 200, code=0, 2 data rows (data_dt=2025-12-31, 2024-12-31)
[2026-06-23 10:23:46] query_report_info: BAS_0264 → HTTP 200, code=0, success=false (msg="...")
[2026-06-23 10:23:46] query_report_info: ⚠️QUERY_FAILED idx=BAS_0264 (all data_dt marked failed)
[2026-06-23 10:23:46] query_report_info: BAS_0265 → HTTP 200, code=0, 2 data rows
[2026-06-23 10:23:46] compute IR (batched LLM): 3 columns extracted
[2026-06-23 10:23:46] compute IR: 营收同比 → base_idx_ids=[BAS_0263] periods=[current, yoy_same]
[2026-06-23 10:23:47] codegen LLM (营收同比): generated 6 lines + 3 smoke rows
[2026-06-23 10:23:47] ast_check (营收同比): passed (only BinOp/Subscript/Call)
[2026-06-23 10:23:47] signature_check (营收同比): passed
[2026-06-23 10:23:48] smoke_run (营收同比): passed (isinstance(out, pd.Series), len=3)
[2026-06-23 10:23:48] example_check (营收同比): passed (out[0]=0.1833 ≈ expected 0.1833)
[2026-06-23 10:23:48] codegen LLM (成本同比): generated, all checks passed
[2026-06-23 10:23:49] unit_conversion: BAS_0263 raw_value=1420 display_value=1420 (unit=个)
[2026-06-23 10:23:49] unit_conversion: BAS_0263 raw_value=1200 display_value=1200 (unit=个)
[2026-06-23 10:23:49] report.computed.py written: 3 functions, 1247 bytes
[2026-06-23 10:23:50] render_docx: 2 报表, 6 cells filled
[2026-06-23 10:23:50] status: success (1 query failure, 0 compute failure)
```

## 错误处理 & 失败模式

| ID | 类别 | 触发条件 | 处理 |
|----|------|---------|------|
| F1 | 输入格式错误 | MD lint 不通过 | lead agent 中断，返回 `{status: "error", errors: [...]}` |
| F2 | SQLBot 配置缺失 | `.env` 无 `SQLBOT_BASE_URL` | lead agent 中断，返回 `{status: "error", reason: "SQLBOT_CONFIG_MISSING"}` |
| F3 | 重试耗尽 | 任何标了重试的操作达到 max_attempts 仍失败 | 中断流程，写明最后一次错误 |
| **F12** | 计算列 base 未匹配 | `> 计算:` 公式引用的 idx_id 不在表头 `data-idx` 已查询集合中 | 该计算列标 `compute_base_missing`，写 log，继续其他列；status=partial |
| **F13** | LLM 代码生成失败 | LLM API 失败 / 返回非 Python 文本 | 按 retry 表；仍失败 → `compute_codegen_failed`，继续其他列 |
| **F14** | AST 校验失败 | 含 Import / Attribute 黑名单 / 非白名单算子 | 按 retry 表；仍失败 → `compute_validation_failed`，继续 |
| **F15** | 烟雾跑或示例 assert 失败 | sandbox 跑出来类型不对 / 数值与示例不匹配 | 按 retry 表；仍失败 → `compute_smoke_failed`，继续 |
| F16 | 单位声明与 SQLBot raw_unit 不一致 | display_unit 与 raw_unit 单位族不同（如 `元` ↔ `%`）| WARN 不阻断，按 display_unit 写入，log 提示 |
| **F17** | SQLBot HTTP 失败 | `requests` 抛 `RequestException` / `code != 0` | 按 retry 表；仍失败 → 中断，status=error |
| **F18** | SQLBot 单条数据失败 | `data[i].success == false`（per-idx 调用粒度下 = 该 idx_id 失败）| 该 idx_id 所有单元格标 ⚠️QUERY_FAILED，继续其他 idx |
| **F19** | 机构 / 时期未声明 | MD 缺 `> 机构:` 或 `> 时期:` 块 | lint ERROR 直接中断（F1）；不进入流水线 |
| F20 | 上下文爆 | token 累积超阈值 | SummarizationMiddleware 自动总结老消息 |

### 重试策略（统一）

| 操作 | max_attempts | backoff | 失败时 |
|------|--------------|---------|--------|
| SQLBot HTTP（`query-report-info`）| 3 | 指数 1s / 2s / 4s（max 10s）| F17 中断 |
| LLM（计算列 IR / 代码生成 / AST 重生成 / 烟雾重生成）| 2 | 无（立即重试）| F13/F14/F15 标记 `_failed` 跳过该项 |

统一通过 `scripts/retry.py` 装饰器实现：

```python
@retry(max_attempts=3, backoff=exponential(base=2, max_delay=10),
       retry_on=(requests.RequestException, SQLBotError))
def call_query_report_info(org_info, index_info, time_info): ...
```

### lead agent 退出 status

```json
// /mnt/user-data/outputs/{thread_id}/report.status.json
{
  "status": "success" | "partial" | "error",
  "exit_step": 1..9,
  "error_class": null | "F1" | "F2" | ... | "F20",
  "error_detail": "human-readable message",
  "outputs": {"json": "path|null", "docx": "path|null", "md": "path|null"},
  "metrics": {
    "queried_count": int,
    "query_failures": int,
    "computed_count": int,
    "compute_validation_failures": int,
    "llm_calls": int,
    "duration_seconds": float
  }
}
```

| status | 判定标准 | lead agent 行为 |
|--------|---------|----------------|
| `success` | `error_class == null` 且所有计算列 `validation.all_passed` | present_files 三件套 |
| `partial` | `error_class == null` 但有 `query_failures > 0` 或 `compute_validation_failures > 0` | present_files 可用的 + 简述失败项数 |
| `error` | `error_class in F1..F20` | 不 present_files，告知用户失败原因 + 检查清单 |

## SKILL.md 关键内容

```markdown
---
name: chatbi-report
description: |
  根据用户上传的带 data-idx 属性 + 中文显示名 和 > 计算: 块的 Markdown 报表样例，
  调用 SQLBot query-report-info 拉真实数据，生成 JSON/Markdown/DOCX。
  支持单位声明（元/万元/亿元/%）与计算列（同比/环比/毛利率等 LLM 生成 pandas 代码）。

  Triggers: "生成报表", "用 SQLBot 指标生成报告", "根据这个 MD 出报表",
  "根据 SQLBot 指标库生成 DOCX"
---

# SQLBot 报表生成

你是 DeerFlow 的 SQLBot 报表生成助手。用户上传一份带 `data-idx` 属性 + 中文显示名的
Markdown 报表样例（含 `> 机构:` / `> 时期:` / `> 计算:` 元数据块），
你要把它处理成结构化 JSON + DOCX + 回填 Markdown。

## 工作流（9 步，每次执行都按顺序）

1. 读取 `/mnt/user-data/uploads/{user_md}`
2. 跑 `python /mnt/skills/public/chatbi-report/scripts/md_lint.py <md>`
3. 跑 `python /mnt/skills/public/chatbi-report/scripts/parse_md.py <md>`
   → 得到 ReportDoc AST（JSON），含 org_context、time_info、indicators、computed_specs
4. 收集所有非计算列 idx_id 去重，组织 SQLBot 参数
5. 跑 `python /mnt/skills/public/chatbi-report/scripts/sqlbot_client.py query-report-info \
   --org-info '[{...}]' --index-info '[{...}]' --time-info '[...]'`
6. 组装数据查表 (org, idx_id, data_dt) → raw_value
7. 计算列 IR 提取（batched LLM）：
   - 输入：所有 ComputedSpec.prompt + 表头 idx_id 列表
   - 输出：{formula_repr, base_idx_ids, periods}
   - 校验 base_idx_ids 必须在已查询集合中；否则该列 F12
8. 计算列代码生成 + 验证：
   - 调 LLM 生成 `compute_<report_id>_<col_slug>(df: pd.DataFrame) -> pd.Series` 并要求同时返回 3 行烟雾数据
   - AST 白名单校验
   - 签名校验
   - sandbox 烟雾跑：assert isinstance(out, pd.Series)
   - 若有 .示例：再跑示例 assert
   - 失败重试 1 次后仍失败 → 跳过该列，标 compute_*_failed
   - 成功 → 追加到 `/mnt/user-data/outputs/{thread_id}/report.computed.py`
9. 单位换算 + 组装 JSON + 渲染 DOCX + 回填 MD

## 产出文件

- `report.json` — 结构化 JSON
- `report.md` — 回填映射的 Markdown
- `report.docx` — DOCX 文档
- `report.computed.py` — LLM 生成的 pandas 计算函数（仅当有计算列）
- `report.query.log` — 决策日志
- `report.status.json` — 最终 status

## 关键约束

- LLM 计算列 IR / 代码生成必须批处理（避免 30 次串行调用）
- 计算列代码生成 + 烟雾跑必须在 sandbox 内，禁直接在 lead agent 进程 exec()
- 计算列 AST 白名单遇到 Import / Attribute(os/sys/subprocess) 一律拒绝
- 单位换算用 `decimal.Decimal`，禁 float
- SQLBot `value` 字段是带千分位字符串，必须先 `str.replace(",", "")` 再 `Decimal(...)`
- SQLBot 无需鉴权（已确认 2026-06-23）
- 单机构 / 多 idx_id / 多 time 的笛卡尔积，一次 HTTP 拿所有数据，避免循环
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
| `test_md_lint.py` | 合法 + 各种 lint 错误（F1/F19）+ data-unit / 计算块 / 示例语法 |
| `test_parse_md.py` | 单/多章节、多级表头、特殊字符、空报表 + org_context / time_info / indicators / computed_specs |
| `test_sqlbot_client.py` | 用 `pytest-httpx` mock HTTP（5xx/4xx/timeout/code≠0/data[i].success=false）|
| `test_compute_ir.py` | LLM batched IR 提取；base_idx_ids 校验；periods 推断 |
| `test_compute_codegen.py` | LLM mock 返回；代码生成；重试逻辑 F13 |
| `test_compute_validator.py` | AST 白名单（含 Import/Attribute 黑名单）；签名检查；烟雾数据 sandbox；示例 assert |
| `test_render_docx.py` | 读回 docx 验证 cell 合并、字体、底色、data_type 格式 + 表头单位副标 |
| `test_render_markdown.py` | MD 中文显示名 + data-unit 渲染、⚠️QUERY_FAILED 标记 + ⚠️COMPUTE_FAILED 标记 + 单位副标 |
| `test_retry.py` | 成功路径、失败重试、最终失败 |
| `test_status.py` | 各失败场景下 status.json 字段 |
| `test_unit_conversion.py` | scale_factor (Decimal) 换算；DOCX 表头副标；data_type=percentage 联动 |

### 集成测试 `backend/tests/integration/sqlbot_report/`

| 场景 | 描述 |
|------|------|
| `test_happy_path.py` | 完整 MD → 全 idx_id 命中 → JSON+MD+DOCX |
| `test_partial_query_failure.py` | 1 个 idx_id SQLBot success=false → ⚠️QUERY_FAILED 单元格 + status=partial |
| `test_sqlbot_down.py` | SQLBot 全宕机 → F17 → status=error |
| `test_sqlbot_code_error.py` | SQLBot HTTP 200 但 code != 0 → F17 中断 |
| `test_no_org_context.py` | MD 缺 `> 机构:` → F19 lint ERROR |
| `test_no_time_info.py` | MD 缺 `> 时期:` → F19 lint ERROR |
| `test_computed_columns_happy.py` | 全部计算列 IR + 代码生成 + 验证通过 |
| `test_computed_base_missing.py` | `> 计算:` 引用未查询的 idx_id → F12 → status=partial |
| `test_computed_codegen_retry.py` | codegen retry（F13）+ designer_examples 校验 |
| `test_computed_validation_failures.py` | AST 拒绝 → F14 / 烟雾失败 → F15 → status=partial |
| `test_unit_conversion_e2e.py` | mock SQLBot raw_unit=元 + MD data-unit=万元 → 校验 JSON/DOCX 字段 |
| `test_value_thousands_separator.py` | `value="1,420.00"` → Decimal 解析正确 |

集成测试用 mock SQLBot server（`pytest-httpx` + fixture 返回假数据）。

### 测试数据 fixtures

```
backend/tests/fixtures/sqlbot_report/
├── sample_md/
│   ├── happy.md
│   ├── lint_error.md
│   ├── multi_chapter.md
│   ├── no_org_context.md
│   ├── no_time_info.md
│   ├── computed_columns.md
│   ├── computed_with_examples.md
│   └── multi_header_computed.md
├── mock_sqlbot/
│   └── query_responses.json   # 含 code=0/success=true|false/code≠0 三种场景
└── expected_outputs/
    ├── happy.json
    ├── partial_query_failure.json
    └── computed_columns.json
```

### 覆盖率目标

| 类别 | 目标 |
|------|------|
| 单元测试行覆盖 | ≥85% |
| 关键路径（query / parse / render / compute）分支覆盖 | 100% |
| 集成测试场景 | ≥10 个核心场景 |

### 端到端（手动）

| 场景 | 操作 |
|------|------|
| E1 | 上传真实 MD → 看 lead agent 进度 → 拿三件套 |
| E2 | 故意 lint 错误 → 看错误提示 |
| E3 | 故意缺 `> 机构:` → 看 F19 触发 |
| E4 | SQLBot 模拟宕机 → 看 F17 中断 |
| E5 | 单条 idx_id 模拟 success=false → 看 ⚠️QUERY_FAILED 单元格 |
| E6 | DOCX 在 Word/WPS 中打开看样式 |
| E7 | 长流程（20 报表）→ 看 SummarizationMiddleware 是否触发 |
| E8 | 中途退出 thread → 重进 → 看 LangGraph checkpointer 续跑 |

## 改动清单

### 新增文件

**Skill 入口 + 通用脚本**：

- `skills/public/chatbi-report/SKILL.md`
- `skills/public/chatbi-report/README.md`
- `skills/public/chatbi-report/.env.example`
- `skills/public/chatbi-report/scripts/sqlbot_client.py`（`SQLBotClient` + `MockSQLBotClient`）
- `skills/public/chatbi-report/scripts/md_lint.py`
- `skills/public/chatbi-report/scripts/parse_md.py`
- `skills/public/chatbi-report/scripts/compute.py` — 计算列 IR + 代码生成 + AST/签名/烟雾/示例验证 + Decimal 单位换算
- `skills/public/chatbi-report/scripts/render_markdown.py`
- `skills/public/chatbi-report/scripts/render_docx.py`
- `skills/public/chatbi-report/scripts/retry.py`
- `skills/public/chatbi-report/scripts/report_style.json`
- `skills/public/chatbi-report/prompts/compute_codegen.md` — 代码生成系统提示词 + 常见公式 few-shot

**单元测试**：

- `backend/tests/sqlbot_report/`（11 个 test_*.py）

**集成测试**：

- `backend/tests/integration/sqlbot_report/`（12 个场景）

**测试 fixture**：

- `backend/tests/fixtures/sqlbot_report/sample_md/`（happy / lint_error / multi_chapter / no_org_context / no_time_info / computed_columns / computed_with_examples / multi_header_computed）
- `backend/tests/fixtures/sqlbot_report/mock_sqlbot/query_responses.json`
- `backend/tests/fixtures/sqlbot_report/expected_outputs/`（happy / partial_query_failure / computed_columns）

### 不改动

- `deerflow.agents.lead_agent.*` 保持不变
- `deerflow.subagents.*` 保持不变（不引入新 subagent）
- LangGraph runtime / Gateway API 不变
- 前端不变
- `SummarizationMiddleware` 保持不变（已存在）
- LangGraph checkpointer 保持不变（已存在）

## 风险与缓解

只列 F1-F20 没覆盖的风险（运行时错误走错误处理表）。

| 风险 | 影响 | 缓解 |
|------|------|------|
| per-idx HTTP 调用 N 倍耗时 | report 渲染变慢（N × ~100ms） | `asyncio.gather` 并行执行，10 idx 总耗时 ~100-200ms 可接受 |
| LLM 生成 pandas 代码逻辑错（分子分母搞反）| 计算列算错 | 鼓励设计师写示例值；烟雾跑 + 示例 assert；few-shot 提示词 |
| Sandbox 没有 pandas | 验证步骤跑不起来 | `.env.example` 提示；启动时检查 sandbox image；缺包 → status=error reason=SANDBOX_MISSING_PANDAS |
| DOCX 渲染对复杂多级表头支持不足 | 报表样式丑 | 提供 `report_style.json` 让用户调样式；Phase 2 引入模板系统 |
| 用户不会写 HTML 表格 | MD 样例难产出 | `md_lint.py` 给清晰错误信息；Phase 2 提供设计 GUI |
| 多机构 / 跨表关联计算 | 不在 Phase 1 | Phase 2 再扩展 |

## 后续扩展方向（不在本设计追踪）

- 报表模板系统
- PDF 输出（reportlab）
- embedding 语义匹配（替代 MD 直接写 idx_id）
- 滚动窗口 / 移动平均 / 跨表关联计算
- 设计 GUI
- 跨企业复用
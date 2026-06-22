# SQLBot 报表生成（data-agent）设计

日期：2026-06-22
分支：`feat/sqlbot-report-data-agent`
状态：v2 重写（v1 砍掉 subagent，改 Lead Agent + SKILL.md）
关联：`SQLBOT_SPEC_PENDING`（真实 SQLBot API 规格待用户提供，先用 mock）

## v2 改动摘要（相对 v1）

| 维度 | v1 | v2 |
|------|----|----|
| 主体形态 | Hybrid (Skill + Subagent) | Lead Agent Only |
| L3 歧义澄清 | subagent 调 ask_clarification（**实际无效**）| lead agent 原生 ask_clarification |
| 上下文管理 | subagent 独立 max_turns=80 | SummarizationMiddleware + LangGraph checkpointer |
| 续跑机制 | 自写 .checkpoints/ 文件 | LangGraph checkpointer（已有） |
| 代码量 | 较多（含 subagent 配置/系统 prompt/工具配置） | 减少 ~30% |
| 复杂度来源 | subagent 与 lead agent 双向通信 | 直接调脚本 |

**v1 砍 subagent 的核心理由**：经代码验证（`ClarificationMiddleware` 只装在 lead agent；`ask_clarification` 工具本身是 placeholder），subagent 调 `ask_clarification` 不会真正中断，**L3 机制空壳**。叠加 DeerFlow 已有的 `SummarizationMiddleware` + `LangGraph checkpointer` 已覆盖 subagent 的核心收益，subagent 退化成"跑脚本的壳"，YAGNI。

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
  - v1 采纳。代码验证发现 subagent 调 `ask_clarification` 实际无效；Subagent 复杂度收益被 SummarizationMiddleware + checkpointer 覆盖
  - 见 v2 改动摘要

- 方案 C（否决）：纯 Skill（wencai 模式）
  - 优势：实现最简单
  - 否决理由：ask_clarification 是工具调用，跟其他工具同一层级，纯 Skill 不直接调工具也能写脚本让 lead agent 触发——但实现上是 A 方案的子集，没必要单独提

- 方案 D（否决）：MCP server
  - 否决理由：DOCX 渲染是重活不适合 MCP 工具语义；端到端工作流不是 MCP 适合的场景

## 架构

```
┌──────────────────────────────────────────────────────────┐
│ Layer 1: Skill (入口/触发)                                 │
│ skills/public/sqlbot-report/                              │
│ ├── SKILL.md            ← SkillActivationMiddleware 加载 │
│ ├── README.md           ← 配置说明                        │
│ ├── .env.example        ← SQLBOT_BASE_URL/SQLBOT_API_KEY │
│ └── scripts/                                                │
│     ├── sqlbot_client.py        ← SQLBot REST 客户端 (mock)│
│     ├── md_lint.py              ← 输入校验                   │
│     ├── parse_md.py             ← MD → ReportDoc AST        │
│     ├── match_indicators.py     ← L1/L2/L3 匹配流水线       │
│     ├── generate_descriptions.py ← 描述生成                  │
│     ├── render_markdown.py      ← 回填映射                  │
│     ├── render_docx.py          ← python-docx 渲染           │
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
| **PDF 输出（reportlab）** | ❌ | ✅ |
| **数据查询（SQLBot 数据 API）** | ❌ | ✅ |
| 匹配结果持久化缓存（跨会话） | ⚠️ 内存级 | ✅ 文件级 |
| 报表模板系统 | ❌ | ✅ |
| Embedding 语义匹配（替代置信度猜值）| ❌ | ✅ |

## Lead Agent 10 步流水线

```
[1] 读取 MD 文件
       bash: cat /mnt/user-data/uploads/{user_md}
[2] 调用 md_lint.py 校验格式
       - 检查 {{}} 标记是否成对
       - 检查 HTML table 是否闭合
       - 报错则中断并列出错误
[3] 解析 MD → in-memory AST
       ReportDoc {
         title, sections[], all_indicators: set
         Section { title, reports[] }
         Report {
           title, description, indicators, header_html, data_rows
         }
       }
[4] 批量查 SQLBot 候选
       python sqlbot_client.py search --keywords "营业收入,营业成本,..."
       输出: { "营业收入": [Indicator, ...], ... }
[5] L1 精确匹配（中文名完全相等）
       matched["营业收入"] = Indicator(code="revenue", ...)
       同时查 indicator_cache（命中跳过 LLM）
[6] L2 模糊匹配（LLM 选 top-1）
       对每个未匹配指标，**单次 LLM 调用输出 JSON 数组**（批处理）
       含幻觉校验：返回 code 必须严格在候选列表里
       若 confidence < 0.6 → 进入 L3 候选池
[7] L3 歧义中断（如有）
       lead agent 原生 ask_clarification(...)（ClarificationMiddleware 拦截）
       用户回答后 lead agent 自动恢复，继续 step 8
[8] LLM 生成结构化描述
       description_zh = 原中文（保留）
       description_en = LLM 翻译（仅用于 JSON 字段，DOCX 默认不用）
[9] 组装 JSON 输出
[10] 渲染 DOCX（用 description_zh）+ 回填 MD
       python render_docx.py --json report.json --style report_style.json
       python render_markdown.py --json report.json --original {user_md}
```

### 续跑语义

Phase 1 不需要手写 checkpoint——LangGraph checkpointer 自动持久化 lead agent 的 state（包括所有 tool call 结果）。用户中途退出后回到同一 thread_id 对话，lead agent 从上次中断的 turn 继续。

`SummarizationMiddleware` 在 token 累积到阈值时自动总结老消息，确保长流程不爆上下文。

### SKILL.md 关键内容（草稿）

```markdown
---
name: sqlbot-report
version: 1.0.0-20260622
description: |
  根据用户上传的带 {{中文指标}} 标记的 Markdown 报表样例，
  匹配 SQLBot 指标库的中文→英文代码，生成 JSON/Markdown/DOCX。

  Triggers: "生成报表", "用 SQLBot 指标生成报告", "根据这个 MD 出报表",
  "根据 SQLBot 指标库生成 DOCX"
---

# SQLBot 报表生成

你是 DeerFlow 的 SQLBot 报表生成助手。用户上传一份带 `{{指标}}` 标记的
Markdown 报表样例，你要把它处理成结构化 JSON + DOCX。

## 工作流（10 步，每次执行都按顺序）

1. 读取 `/mnt/user-data/uploads/{user_md}`（用户上传路径）
2. 跑 `python /mnt/skills/public/sqlbot-report/scripts/md_lint.py <md>`
3. 跑 `python /mnt/skills/public/sqlbot-report/scripts/parse_md.py <md>`
   → 得到 ReportDoc AST（JSON）
4. 收集所有 `{{指标}}` 去重，跑：
   `python /mnt/skills/public/sqlbot-report/scripts/sqlbot_client.py search --keywords "k1,k2,..."`
5. L1 精确匹配（中文名 == SQLBot.name_cn）
6. L2 模糊匹配：调 LLM，对未匹配指标**批量**输出 JSON 数组
   - 每个候选含 chinese, code, confidence
   - 强校验：返回的 code 必须**在候选列表里**
   - confidence < 0.6 且 top1-top2 < 0.1 → 加入 L3 池
7. L3 歧义：调 ask_clarification 工具（lead agent 原生）
   - options 列出候选的中文名 + code + 简短描述
   - 用户回答后**自动恢复**
8. 描述生成：保留中文原描述，`description_en` 由 LLM 生成（仅用于 JSON 字段）
9. 组装 JSON：跑 `python scripts/match_indicators.py --assemble --in <parsed> --out <matched> --out <final>`
10. 渲染：并行跑 `render_docx.py` + `render_markdown.py`

## 产出文件（写到 /mnt/user-data/outputs/{thread_id}/）

- `report.json` — 结构化 JSON
- `report.md` — 回填映射的 Markdown
- `report.docx` — DOCX 文档
- `report.match.log` — 决策日志
- `report.status.json` — 最终 status

## 关键约束

- 中文描述 `description.zh` 在 DOCX 中默认使用（受众是中国用户）
- LLM 模糊匹配必须批处理（避免 30 次串行调用）
- LLM 返回的 code 必须强校验，不在候选列表的视作幻觉
- 同一 thread 内匹配的指标自动进入内存缓存，避免重复 LLM
- DOCX 表格多级表头用 python-docx cell.merge() 合并
- 描述、匹配、渲染的每步决定都写到 `report.match.log`
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
  table: <HTML table>

table:
  thead: rows+   # 至少一行；多级表头对应多行
  tbody: rows+
  row: th+ | td+

indicator_marker: "{{<中文指标名>}}"
  # 严格规则：
  # - 在 <th> 内：表头是"需映射"的指标
  # - 在 <td> 内：数据值，无需映射
  # - 在 {{}} 外：标题/描述/分类，无需映射
```

### Lint 规则（md_lint.py 强制）

| 规则 | 等级 |
|------|------|
| `{{}}` 必须成对出现 | ERROR |
| `<table>` 必须有 `<thead>` 和 `<tbody>` | ERROR |
| 章节必须含至少一个报表 | ERROR |
| 报表必须含描述和数据 | ERROR |
| 多级表头用 `<th rowspan/colspan>`，不用 markdown 表格 | WARN |
| 指标名应**简洁**（≤8 个汉字） | WARN |
| 同一中文指标在多张表出现时建议全名一致 | WARN |

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
                    "required": ["chinese", "code", "confidence"],
                    "properties": {
                      "chinese": {"type": "string"},
                      "code": {"type": "string"},
                      "name_en": {"type": "string"},
                      "category": {"type": "string"},
                      "unit": {"type": "string"},
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
                      "match_method": {"enum": ["exact", "fuzzy", "user_clarification", "cache_hit"]}
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
        "duration_seconds": {"type": "number"}
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
│       │   └── 数据单元格：根据 data_type 应用格式（千分位/百分比/货币）
│       └── 备注 (Indicator 未映射时显示 ⚠️UNMAPPED)
```

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

把 `{{营业收入}}` 替换成 `营业收入 (\`revenue\`)`：

```markdown
| 季度 | 财务指标 || 增长率 ||
|      | 营业收入 (`revenue`) | 营业成本 (`operating_cost`) | 环比 (`qoq_growth`) | 同比 (`yoy_growth`) |
|------|---------|---------|------|------|
| 2024 Q1 | 1450 | 920 | 20.8% | 12.5% |
```

未匹配项标 `⚠️UNMAPPED`：

```markdown
| {{营业收入}} (revenue) | {{新增指标}} ⚠️UNMAPPED |
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
```

## 错误处理 & 失败模式

| ID | 类别 | 触发条件 | 处理 |
|----|------|---------|------|
| F1 | 输入格式错误 | MD lint 不通过 | lead agent 中断，返回 `{status: "error", errors: [...]}` |
| F2 | SQLBot 配置缺失 | `.env` 无 `SQLBOT_BASE_URL` / `SQLBOT_API_KEY` | lead agent 中断，返回 `{status: "error", reason: "SQLBOT_CONFIG_MISSING"}` |
| F3 | SQLBot 网络/API 失败 | HTTP 5xx / 超时 / 4xx | 重试 3 次（指数退避 1s/2s/4s）；仍失败 → 中断 |
| F4 | SQLBot 0 候选 | 某些 `{{指标}}` 在 SQLBot 中无任何匹配 | 标 `unmatched`，继续；不影响流水线 |
| F5 | L2 低置信度 + 无歧义 | top-1 < 0.6 且 `top1.score - top2.score > 0.1` | 用 top-1，confidence=低，标 `low_confidence`，继续 |
| F6 | L2 低置信度 + 多候选歧义 | top-1 < 0.6 且 `top1.score - top2.score ≤ 0.1` | lead agent 调 `ask_clarification`（原生支持） |
| F7 | 用户取消澄清 | 用户拒绝 / 给 "跳过" | 标 `user_skipped` → 继续 |
| F8 | 描述生成失败 | LLM API 失败 | 重试 1 次，仍失败 → `description.zh = 原中文 + " [TRANSLATION_FAILED]"` |
| F9 | DOCX 渲染失败 | python-docx 异常 | 返回 JSON + log，flag `render_error`，用户可手动重跑 `render_docx.py` |
| F10 | LLM 幻觉 | LLM 返回 code 不在候选列表 | 拒绝该结果，回退 L1 重试；仍失败 → 进 L3 |
| F11 | 上下文爆 | token 累积超阈值 | SummarizationMiddleware 自动总结老消息 |

### 重试装饰器

```python
@retry(
    max_attempts=3,
    backoff=exponential(base=2, max_delay=10),
    retry_on=(requests.RequestException, TimeoutError),
)
def call_sqlbot_search(keyword: str) -> list[Indicator]:
    ...
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
| `test_md_lint.py` | 合法 + 各种 lint 错误 |
| `test_parse_md.py` | 单/多章节、多级表头、特殊字符、空报表 |
| `test_sqlbot_client.py` | 用 `pytest-httpx` mock HTTP（5xx/4xx/timeout）|
| `test_match_indicators.py` | L1/L2 + 幻觉校验 + 批调用 + L3 |
| `test_indicator_cache.py` | 缓存命中、缓存写入、并发安全 |
| `test_render_docx.py` | 读回 docx 验证 cell 合并、字体、底色、data_type 格式 |
| `test_render_markdown.py` | `{{}}` 替换、unmapped 标记 |
| `test_retry.py` | 成功路径、失败重试、最终失败 |
| `test_status.py` | 各失败场景下 status.json 字段 |

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

集成测试用 mock SQLBot server（`pytest-httpx` + fixture 返回假数据）。

### 测试数据 fixtures

```
backend/tests/fixtures/sqlbot_report/
├── sample_md/
│   ├── happy.md
│   ├── lint_error.md
│   ├── multi_chapter.md
│   ├── partial_unmapped.md
│   └── l3_ambiguous.md
├── mock_sqlbot/
│   ├── indicators.json       # 模拟指标库（100+ 条，覆盖 5+ 业务域）
│   └── search_responses.json # 含易混名（"营收" / "营业收入" / "营业总收入"）
└── expected_outputs/
    ├── happy.json
    └── partial_unmapped.json
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

## 改动清单（v2 实施时）

### 新增文件

- `skills/public/sqlbot-report/SKILL.md`
- `skills/public/sqlbot-report/README.md`
- `skills/public/sqlbot-report/.env.example`
- `skills/public/sqlbot-report/scripts/sqlbot_client.py` (mock 实现)
- `skills/public/sqlbot-report/scripts/md_lint.py`
- `skills/public/sqlbot-report/scripts/parse_md.py`
- `skills/public/sqlbot-report/scripts/match_indicators.py` (含幻觉校验 + 批调用)
- `skills/public/sqlbot-report/scripts/indicator_cache.py` (内存缓存)
- `skills/public/sqlbot-report/scripts/generate_descriptions.py`
- `skills/public/sqlbot-report/scripts/render_markdown.py`
- `skills/public/sqlbot-report/scripts/render_docx.py` (含 data_type 格式应用)
- `skills/public/sqlbot-report/scripts/retry.py`
- `skills/public/sqlbot-report/scripts/report_style.json`
- `backend/tests/sqlbot_report/` (9 个 test_*.py)
- `backend/tests/integration/sqlbot_report/` (7 个 test_*.py)
- `backend/tests/fixtures/sqlbot_report/` (sample_md / mock_sqlbot / expected_outputs)

### 改动文件

- `config.example.yaml` → `summarization` 节点确保开启（已存在，确认启用）

### 不改动

- `deerflow.agents.lead_agent.*` 保持不变
- `deerflow.subagents.*` 保持不变（不引入新 subagent）
- LangGraph runtime / Gateway API 不变
- 前端不变
- `SummarizationMiddleware` 保持不变（已存在）
- LangGraph checkpointer 保持不变（已存在）

## SQLBot API 占位契约（待用户提供真实规格）

```python
# SQLBOT_SPEC_PENDING — 真实 schema 待用户提供

@dataclass
class Indicator:
    code: str
    name_cn: str
    name_en: str
    category: str
    unit: str
    description: str
    # Phase 2 字段（当前 mock 返回 None）：
    # data_type: str | None
    # display_format: str | None
    # time_dimension: str | None
    # data_source: str | None
    # last_updated: str | None
    # version: str | None

class SQLBotClient:
    def __init__(self, base_url: str, api_key: str): ...
    def search_indicators(self, keyword: str, limit: int = 20) -> list[Indicator]: ...
    def get_indicator(self, code: str) -> Indicator: ...
```

mock 实现（`sqlbot_client.py` 内的 `MockSQLBotClient`）返回固定 fixtures 数据，**仅用于开发和测试**。生产前必须替换为真实实现。

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

## 不在 Phase 1 范围

- PDF 渲染
- 数据查询（SQLBot 数据 API 集成）
- 匹配结果文件级持久化缓存
- 报表模板系统
- 设计 GUI
- 真实 SQLBot API 集成（用 mock 占位）
- Embedding 语义匹配

## 后续 Phase 计划

- **Phase 2**：PDF 渲染（reportlab）+ 数据查询 + 文件级匹配缓存 + Embedding 语义匹配
- **Phase 3**：报表模板系统（部门级样式库）
- **Phase 4**：设计 GUI（让设计师不写 HTML）
- **Phase 5**：跨企业复用 / 多租户指标隔离

## v2 相对 v1 的具体修改清单

| # | 维度 | v1 | v2 |
|---|------|----|----|
| 1 | 主体形态 | Hybrid (Skill + Subagent) | Lead Agent Only |
| 2 | L3 澄清机制 | subagent 调 ask_clarification（**无效**）| lead agent 原生 ask_clarification |
| 3 | 上下文管理 | subagent max_turns=80 | SummarizationMiddleware 自动总结 |
| 4 | 续跑 | 自写 .checkpoints/ 文件 | LangGraph checkpointer |
| 5 | LLM 调用模式 | subagent 串行匹配 | lead agent 批调用 |
| 6 | 幻觉处理 | 未考虑 | 强校验 + fallback |
| 7 | 缓存 | 未考虑 | 内存级 IndicatorCache |
| 8 | JSON schema | 缺 data_type / format / time_dim 等 | 已补全 |
| 9 | DOCX 语言 | 含糊（zh vs en 不清）| 明确 `description.zh` 默认 |
| 10 | 测试 fixture | 30+ 指标 | 100+ 指标，含易混名 |
| 11 | 失败模式 | F1-F11 | F1-F11 + F10 幻觉 + F11 上下文 |
| 12 | 改动文件 | 含 subagent 配置 | 仅 skill + scripts + 启用 summarization config |
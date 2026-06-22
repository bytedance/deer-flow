# SQLBot 报表 data-agent 设计

日期：2026-06-22
分支：`feat/sqlbot-report-data-agent`
状态：已与用户确认（架构、范围、契约、错误处理、测试均已逐段确认）
关联：`SQLBOT_SPEC_PENDING`（真实 SQLBot API 规格待用户提供，先用 mock）

## 背景与目标

DeerFlow 当前没有「报表生成」能力。报表设计人员目前只能：

1. 在 Markdown 里手写带中文指标的样例；
2. 手工去 SQLBot 指标库查每个中文指标对应的英文代码；
3. 手工把映射结果整理成 JSON；
4. 手工用 Word 排版生成 DOCX。

整套流程纯人工，**5 章节 × 5 报表 × 平均 6 指标 = 150 次手工查表**，极容易出错，且无法复用历史匹配。

**目标**：让 DeerFlow 内置一个 `data-agent`，对一份带 `{{指标}}` 标记的 Markdown 报表样例，端到端产出：

- **结构化 JSON**（用于二次处理 / 数据回填）
- **回填后的 Markdown**（中文显示 + 英文代码副标）
- **DOCX 文档**（多级表头 + 合并单元格 + 品牌样式）

并在 SQLBot 指标无法匹配时**定点中断**让用户澄清，而不是全错或全人工。

## 方案选型

- **方案 A（采纳）：Hybrid（Skill 入口 + Subagent 执行）**
  - `skills/public/sqlbot-report/SKILL.md` 作为发现层 + 输入契约 + 委派指令
  - `config.yaml → custom_agents.sqlbot-report` subagent 拥有独立 LLM 循环跑 10 步流水线
  - 工具：bash / read_file / write_file / str_replace + skill 内 scripts
  - 触发：`lead agent` 读 SKILL.md 后用 `task(subagent_type="sqlbot-report", ...)` 委派

- 方案 B（否决）：纯 Skill（wencai 模式）
  - 优势：实现简单
  - 否决理由：模糊匹配需要 LLM 多轮迭代决策，会污染 lead agent 主对话上下文

- 方案 C（否决）：纯 Subagent（无 SKILL.md）
  - 优势：单层
  - 否决理由：缺少发现层，lead agent 不知道何时触发

- 方案 D（否决）：MCP server
  - 否决理由：DOCX 渲染是重活不适合 MCP 工具语义；MCP 适合暴露原子工具而非端到端工作流

## 架构

```
┌──────────────────────────────────────────────────────────┐
│ Layer 1: Skill (发现层)                                    │
│ skills/public/sqlbot-report/                              │
│ ├── SKILL.md                                                │
│ ├── README.md                                               │
│ ├── .env.example                                            │
│ ├── scripts/                                                │
│ │   ├── sqlbot_client.py        ← SQLBot REST 客户端 (mock)│
│ │   ├── md_lint.py              ← 输入校验                   │
│ │   ├── parse_md.py             ← MD → ReportDoc AST        │
│ │   ├── match_indicators.py     ← L1/L2/L3 匹配流水线       │
│ │   ├── generate_descriptions.py ← 描述生成                  │
│ │   ├── render_markdown.py      ← 回填映射                  │
│ │   ├── render_docx.py          ← python-docx 渲染           │
│ │   ├── retry.py                ← 通用重试装饰器             │
│ │   └── report_style.json       ← DOCX 样式定义             │
│ └── tests/                                                  │
└──────────────────────────────────────────────────────────┘
                              ↓ lead agent 通过 task() 委派
┌──────────────────────────────────────────────────────────┐
│ Layer 2: Subagent (执行层)                                 │
│ config.yaml → custom_agents.sqlbot-report                  │
│   - system_prompt: 10 步流水线                              │
│   - tools: bash, read_file, write_file, str_replace,        │
│            ask_clarification                                │
│   - max_turns: 80                                            │
│   - timeout_seconds: 900                                    │
│   - confidence_threshold: 0.6                               │
└──────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────┐
│ Layer 3: 资产输出 (sandbox 路径)                            │
│ /mnt/user-data/outputs/{thread_id}/                        │
│ ├── report.md                                                │
│ ├── report.docx                                              │
│ ├── report.json                                              │
│ ├── report.match.log                                        │
│ ├── report.status.json                                      │
│ └── .checkpoints/  (断点续跑)                                │
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
| 匹配缓存/快照 | ❌ | ✅ |
| 报表模板系统 | ❌ | ✅ |

## Subagent 10 步流水线

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
[6] L2 模糊匹配（LLM 选 top-1）
       若 confidence < 0.6 → 进入 L3 候选池
[7] L3 歧义中断（如有）
       ask_clarification(...)
[8] LLM 生成结构化描述
       description_en: "Quarterly revenue comparison..."
[9] 组装 JSON 输出
[10] 渲染 DOCX + 回填 MD
```

### Subagent system_prompt 关键段落

```markdown
# Role
You are sqlbot-report subagent. You take a Chinese-marked Markdown report
design and produce a structured JSON report + DOCX document by mapping
Chinese indicator names to English codes from SQLBot.

# Workflow (10 steps)
1. Read the uploaded MD file
2. Validate format with md_lint.py
3. Parse MD into ReportDoc AST
4. Collect all {{indicator}} placeholders, dedupe
5. Batch-search SQLBot
6. Apply L1 (exact name match) automatically
7. Apply L2 (LLM top-1 fuzzy match); confidence threshold = 0.6
8. For L2 low-confidence or multiple candidates, use ask_clarification
9. Generate English descriptions from Chinese prompts
10. Render outputs (markdown + docx)

# Tools: bash, read_file, write_file, str_replace, ask_clarification
# Constraints: max_turns=80, timeout=900s, no sub-subagents
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
              "required": ["report_id", "title", "description", "headers", "data", "indicator_mappings"],
              "properties": {
                "report_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {
                  "type": "object",
                  "properties": {
                    "zh": {"type": "string"},
                    "en": {"type": "string"}
                  }
                },
                "headers": {
                  "type": "array",
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
                      "confidence": {"type": "number"},
                      "match_method": {"enum": ["exact", "fuzzy", "user_clarification"]}
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
      "properties": {
        "generated_at": {"type": "string", "format": "date-time"},
        "total_indicators": {"type": "integer"},
        "matched_count": {"type": "integer"},
        "unmatched_count": {"type": "integer"},
        "match_rate": {"type": "number"},
        "unmatched": {"type": "array", "items": {"type": "string"}}
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
│       ├── 描述段落 (Normal)
│       ├── 数据表 (python-docx Table)
│       │   ├── 表头：多级用 cell.merge() 合并
│       │   ├── 表头单元格：粗体 + 底色 (#F0F0F0)
│       │   └── 数据单元格：常规样式
│       └── 备注 (Indicator 未映射时显示)
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
    "cell_padding_pt": 4
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
[2026-06-22 10:23:46] L2 模糊匹配: {{环比增长率}} → qoq_growth_rate (confidence=0.85)
[2026-06-22 10:23:50] L3 澄清: {{增长率}} 用户选择 "yoy_growth" (3 选项中)
[2026-06-22 10:23:51] unmatched: {{行业平均}} (SQLBot 中无候选)
```

## 错误处理 & 失败模式

| ID | 类别 | 触发条件 | 处理 |
|----|------|---------|------|
| F1 | 输入格式错误 | MD lint 不通过 | subagent 中断，返回 `{status: "error", errors: [...]}` |
| F2 | SQLBot 配置缺失 | `.env` 无 `SQLBOT_BASE_URL` / `SQLBOT_API_KEY` | subagent 中断，返回 `{status: "error", reason: "SQLBOT_CONFIG_MISSING"}` |
| F3 | SQLBot 网络/API 失败 | HTTP 5xx / 超时 / 4xx | 重试 3 次（指数退避 1s/2s/4s）；仍失败 → 中断 |
| F4 | SQLBot 0 候选 | 某些 `{{指标}}` 在 SQLBot 中无任何匹配 | 标 `unmatched`，继续；不影响流水线 |
| F5 | L2 低置信度 + 无歧义 | top-1 < 0.6 且第二名差距大 | 用 top-1，confidence=低，标 `low_confidence`，继续 |
| F6 | L2 低置信度 + 多候选歧义 | top-1 与 top-2 差距 < 0.1 | L3：调 `ask_clarification` |
| F7 | 用户取消澄清 | 用户拒绝 / 给 "跳过" | 标 `user_skipped` → 继续 |
| F8 | 描述生成失败 | LLM API 失败 | 重试 1 次，仍失败 → `description.zh = 原中文 + " [TRANSLATION_FAILED]"` |
| F9 | DOCX 渲染失败 | python-docx 异常 | 返回 JSON + log，flag `render_error`，用户可手动重跑 `render_docx.py` |
| F10 | subagent 超时 | `timeout_seconds=900` | LangGraph 自动中断，返回部分结果 |
| F11 | subagent 上下文爆 | max_turns 用完 | 同 F10 |

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

### subagent 退出 status

```json
// /mnt/user-data/outputs/{thread_id}/report.status.json
{
  "status": "success" | "partial" | "error",
  "exit_step": 1..10,
  "error_class": null | "F1" | "F2" | ... | "F11",
  "error_detail": "human-readable message",
  "outputs": {"json": "path|null", "docx": "path|null", "md": "path|null"},
  "metrics": {"matched_count": int, "unmatched_count": int, "match_rate": float, "duration_seconds": float}
}
```

| subagent status | lead agent 行为 |
|----------------|----------------|
| `success` | present_files 三件套 |
| `partial` | present_files 可用的 + 简述未完成部分 |
| `error` | 不 present_files，告知用户失败原因 + 检查清单 |

### 取消 & 续跑

subagent 每完成一个 step 写一个 checkpoint 到 `.checkpoints/`。LangGraph 检测到 HTTP cancel 时当前 step 跑完后立即退出，已完成的 checkpoint 保留。续跑时 subagent 检测到 checkpoint → 询问"续跑/重新跑"。

## 检查点文件结构

```
/mnt/user-data/outputs/{thread_id}/
├── .checkpoints/
│   ├── 01_parsed.json
│   ├── 02_candidates.json
│   ├── 03_matched.json
│   ├── 04_described.json
│   ├── 05_final.json
│   └── 06_rendered/
│       ├── report.md
│       └── report.docx
├── report.json                  # 最终（= 05_final.json 副本）
├── report.md
├── report.docx
├── report.match.log
└── report.status.json
```

## 测试策略

### 测试金字塔

```
              E2E (手动)
                  ↑
      Integration (subagent + mock SQLBot)
                  ↑
        Unit tests (每个脚本)
```

### 单元测试 `backend/tests/sqlbot_report/`

| 文件 | 覆盖 |
|------|------|
| `test_md_lint.py` | 合法 + 各种 lint 错误 |
| `test_parse_md.py` | 单/多章节、多级表头、特殊字符、空报表 |
| `test_sqlbot_client.py` | 用 `pytest-httpx` mock HTTP（5xx/4xx/timeout）|
| `test_match_indicators.py` | L1/L2/L3 + mock LLM |
| `test_render_docx.py` | 读回 docx 验证 cell 合并、字体、底色 |
| `test_render_markdown.py` | `{{}}` 替换、unmapped 标记 |
| `test_retry.py` | 成功路径、失败重试、最终失败 |
| `test_status.py` | 各失败场景下 status.json 字段 |

### 集成测试 `backend/tests/integration/sqlbot_report/`

| 场景 | 描述 |
|------|------|
| `test_happy_path.py` | 完整 MD → 全部 L1 → JSON+MD+DOCX |
| `test_partial_match.py` | 部分 L1 + 部分 L2，无 L3 |
| `test_l3_clarification.py` | 模拟 ask_clarification 触发和回复 |
| `test_sqlbot_down.py` | SQLBot 全宕机 → F3 → status=error |
| `test_partial_unmapped.py` | 部分无候选 → F4 → status=partial |

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
│   ├── indicators.json       # 模拟指标库（30+ 条）
│   └── search_responses.json
└── expected_outputs/
    ├── happy.json
    └── partial_unmapped.json
```

### 覆盖率目标

| 类别 | 目标 |
|------|------|
| 单元测试行覆盖 | ≥85% |
| 关键路径（match/render）分支覆盖 | 100% |
| 集成测试场景 | ≥6 个核心场景 |

### 端到端（手动）

| 场景 | 操作 |
|------|------|
| E1 | 上传真实 MD → 看 subagent 进度 → 拿三件套 |
| E2 | 故意 lint 错误 → 看错误提示 |
| E3 | L3 歧义 → 看 ask_clarification 是否触发 |
| E4 | DOCX 在 Word/WPS 中打开看样式 |

## 改动清单（实施时）

### 新增文件

- `skills/public/sqlbot-report/SKILL.md`
- `skills/public/sqlbot-report/README.md`
- `skills/public/sqlbot-report/.env.example`
- `skills/public/sqlbot-report/scripts/sqlbot_client.py` (mock 实现)
- `skills/public/sqlbot-report/scripts/md_lint.py`
- `skills/public/sqlbot-report/scripts/parse_md.py`
- `skills/public/sqlbot-report/scripts/match_indicators.py`
- `skills/public/sqlbot-report/scripts/generate_descriptions.py`
- `skills/public/sqlbot-report/scripts/render_markdown.py`
- `skills/public/sqlbot-report/scripts/render_docx.py`
- `skills/public/sqlbot-report/scripts/retry.py`
- `skills/public/sqlbot-report/scripts/report_style.json`
- `backend/tests/sqlbot_report/` (8 个 test_*.py)
- `backend/tests/integration/sqlbot_report/` (5 个 test_*.py)
- `backend/tests/fixtures/sqlbot_report/` (sample_md / mock_sqlbot / expected_outputs)

### 改动文件

- `config.example.yaml` → `custom_agents.sqlbot-report` 节点（新增）

### 不改动

- `deerflow.agents.lead_agent.*` 保持不变（subagent 通过 `task()` 调用）
- `deerflow.subagents.*` 框架不变（直接用 `custom_agents` 注册）
- LangGraph runtime / Gateway API 不变
- 前端不变

## SQLBot API 占位契约（待用户提供真实规格）

```python
# SQLBOT_SPEC_PENDING — 真实 schema 待用户提供

@dataclass
class Indicator:
    code: str            # 英文代码
    name_cn: str         # 中文名
    name_en: str         # 英文名
    category: str        # 分类（如 "财务"/"运营"）
    unit: str            # 单位（如 "万元"/"%"）
    description: str     # 描述

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
| L2 模糊匹配准确率低 | 用户频繁被打断 | 阈值 0.6 可调；积累训练数据后 Phase 2 引入 embeddings |
| DOCX 渲染对复杂多级表头支持不足 | 报表样式丑 | 提供 report_style.json 让用户调样式；Phase 2 引入模板系统 |
| 用户不会写 HTML 表格 | MD 样例难产出 | md_lint.py 给清晰错误信息；Phase 2 提供设计 GUI |
| subagent 长流程上下文爆 | 部分报表失败 | max_turns=80 + checkpoint 续跑 |
| 中文表格单元格内换行 | DOCX 显示错乱 | parser 把 `\n` 转为段落而非单 cell 多行 |

## 不在 Phase 1 范围

- PDF 渲染
- 数据查询（SQLBot 数据 API 集成）
- 匹配结果缓存
- 报表模板系统
- 设计 GUI
- 真实 SQLBot API 集成（用 mock 占位）
- CI workflow YAML（已与用户确认暂不做）

## 后续 Phase 计划

- **Phase 2**：PDF 渲染（reportlab）+ 数据查询
- **Phase 3**：报表模板系统（部门级样式库）
- **Phase 4**：设计 GUI（让设计师不写 HTML）
- **Phase 5**：匹配缓存 + 历史匹配复用
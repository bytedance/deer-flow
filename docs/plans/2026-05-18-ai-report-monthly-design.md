# AI 月报智能体功能设计文档

> **范围**：完整功能设计，覆盖 SOUL.md 改造、数据接入、Skill 脚本、GenUI 渲染、Markdown/PDF 导出、月环比与同期对比、改进跟踪与下月计划。
> **遵循模式**：完全对齐 [AI 周报智能体功能设计文档](./2026-05-18-ai-report-weekly-design.md) 的"SOUL.md（prompt 驱动）+ skill 脚本（确定性计算）+ GenUI 多轮表单"架构，复用 [list_equipment.py](../../skills/custom/data-analyst/scripts/list_equipment.py) 与 [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py)，**不引入新的后端 Python 代码、不新增路由、不新增前端组件**。
> **与自定义模板平台对齐**：本设计与 [AI 报告自定义模板功能设计文档](./2026-05-14-ai-report-custom-template-design.md) §13.4 月报 DSL 草案保持脚本契约一致，使原生 `ai-report--monthly` 与未来 `monthly-equipment` DSL builtin 模板可共享同一套数据/KPI 脚本。

---

## 1. 现状与目标

### 1.1 现状

当前 [agents/builtin/ai-report--monthly/SOUL.md](../../agents/builtin/ai-report--monthly/SOUL.md) 仅是 prompt-only 草稿（约 25 行），与周报相比存在以下显著差距：

- **无动态参数表单**：未使用 `render_ui form` 收集报告月份、设备类型、对比基准。
- **无设备/KPI 多步收集**：缺少与日报/周报对齐的"范围 → 设备 → KPI → 生成"4 轮交互。
- **无数据采集脚本**：没有 `query_monthly.py` 拉取月度聚合数据。
- **无 KPI 计算脚本**：没有 `monthly_kpi.py` 产出月均值、峰值、周维度趋势、MTBF/MTTR、月环比/同期 delta 等。
- **无导出能力**：未对接 `export_report.py`，用户无法下载 Markdown/PDF。
- **无演示数据回退**：真实数据源不可用时，端到端链路无法闭环。
- **章节内容凭空生成**：LLM 仅依据 prompt 描述输出虚构内容，违反"数据优先"原则。
- **无改进跟踪闭环**：占位 SOUL 提到"改进跟踪"，但没有数据来源与脚本契约。

[config.yaml](../../agents/builtin/ai-report--monthly/config.yaml) 已声明 `parent: ai-report` / `order: 5` / `skills: [data-analyst]`，无需改动；本立项只需要补齐 SOUL.md 与 2 个新脚本即可达到与周报对等的能力。

### 1.2 目标

| 能力 | 描述 |
|------|------|
| 交互式参数收集 | 4 轮 GenUI 表单：月报参数（报告月份/设备类型/对比基准） → 设备多选 → KPI 多选 → 生成 + 导出 |
| 自动数据采集 | 按优先级链获取月度聚合数据（MCP → `query_monthly.py` → http_connector → 演示数据回退） |
| 结构化输出 | `card`（月 KPI 含 MTBF/MTTR） + `echart`（周维度趋势） + `table`（重大事件 / 异常 TopN / 改进措施跟踪） + `markdown`（月度复盘 + 下月计划） |
| 导出 | Markdown 必需，PDF 可选降级（与周报一致），通过 sandbox artifact URL 提供下载 |
| 月环比/同期对比 | 自动拉取上月或去年同月数据，输出环比 delta 与同比 delta；同期数据缺失时优雅降级 |
| 月维度专属内容 | 周趋势曲线、MTBF/MTTR、月环比/同比表、重大事件回顾、改进措施跟踪、下月计划 |

### 1.3 与周报的差异

| 维度 | ai-report--weekly | ai-report--monthly |
|------|-------------------|--------------------|
| 时间维度 | 7 天（自然周或自定义 7 日窗口） | 自然月（按 `YYYY-MM` 锚定，跨闰年自动处理） |
| 数据聚合粒度 | 按日（7 桶） | 按周（4-5 桶）+ 整月聚合；不下钻到日级以避免过载 |
| 章节结构 | 概览 / 周 KPI / 日趋势 / 异常 TopN / 周环比 / 下周关注 | 月度总览 / 月 KPI（含 MTBF/MTTR）/ 周维度趋势 / 重大事件回顾 / 月环比 + 同比 / 改进措施跟踪 / 下月计划 |
| 对比基准 | `previous_week` / `previous_year` / `none` | `previous_month` / `previous_year_month`（去年同月）/ `none`；**也可同时选择两者**（multi-select） |
| KPI 指标语义 | 周均值 / 周峰值 / 周低谷 / 周波动率 | 月均值 / 月峰值 / 月低谷 / 月波动率 + **MTBF**（平均故障间隔时间）/ **MTTR**（平均修复时间）/ **达标率** |
| 告警呈现 | 周维度 TopN + 流水 | 整月 TopN + **重大事件回顾**（critical 级别独立 table） |
| 数据量级 | N × M × 7 | N × M × 28-31，**默认仅返回周聚合**，避免单脚本超时；用户显式启用 `--include-daily` 才下钻 |
| 趋势图横轴 | 周一–周日日期刻度 | 第 1 周 – 第 4/5 周（W1-W5），label 同时显示对应日期范围 |
| 闭环管理 | 仅下周关注 | **改进措施跟踪**（上月计划完成率） + 下月计划 |
| 下游延伸 | 周复盘 + 下周计划 | 月复盘 + 管理视角 + 下月计划 + 长期趋势伏笔（为趋势分析报告做铺垫） |

---

## 2. 系统架构

**入口流程**：用户从 `ai-report`（`type: group`）子 agent 列表中进入 `ai-report--monthly`，与现有 group/sub-agent 路由完全一致，父 group 不显式声明子 agent，依赖目录扫描发现。

```
┌────────────────────────────────────────────────────────────────┐
│                       前端对话页面                              │
│   workspace/agents/ai-report--monthly/chats/{thread_id}        │
│                                                                │
│   GenUI 区域：                                                  │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ Round 1: 月报参数表单（form / monthly-report-scope）  │   │
│   │  报告月份(YYYY-MM) / 设备类型 / 对比基准(multi)       │   │
│   └──────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ Round 1.5: 设备多选（form / monthly-report-equipment）│   │
│   │  按区域分组、可搜索、默认全选                          │   │
│   └──────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ Round 2: KPI 多选（form / monthly-report-confirm）    │   │
│   │  动态来自 list_equipment.available_kpis               │   │
│   │  额外固定项：MTBF / MTTR / 达标率（不在 available_kpis│   │
│   │  时由脚本派生）                                        │   │
│   └──────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ Round 3: 月报内容（多 GenUI Block 组合）              │   │
│   │  card: 月 KPI 卡片（含月环比 / 同比 delta）           │   │
│   │  echart: 周维度趋势曲线（W1-W5）                       │   │
│   │  table: 异常 TopN（按设备/级别聚合）                  │   │
│   │  table: 重大事件回顾（critical 级别独立列表）          │   │
│   │  table: 改进措施跟踪（上月计划完成率）                 │   │
│   │  markdown: 月度复盘 + 下月计划                         │   │
│   │  下载链接（artifact URL）                              │   │
│   └──────────────────────────────────────────────────────┘   │
└────────────────────┬───────────────────────────────────────────┘
                     │ LangGraph SSE（DeerFlowClient 流水线）
┌────────────────────┼───────────────────────────────────────────┐
│                    ▼   Backend                                  │
│                                                                │
│   Agent: ai-report--monthly                                    │
│   SOUL.md 驱动 LLM 按以下步骤工作：                            │
│     1. 渲染 Round 1 表单并停止                                 │
│     2. 收到 scope 回调 → 校验 → list_equipment → Round 1.5     │
│     3. 收到 equipment 回调 → 校验 → list_equipment → Round 2   │
│     4. 收到 confirm 回调 → query_monthly + monthly_kpi → 渲染  │
│     5. 调用 export_report 写 md / pdf → present_files          │
│                                                                │
│   skill: data-analyst                                          │
│   scripts/                                                     │
│     ├ list_equipment.py     # 已存在，直接复用                 │
│     ├ query_daily.py        # 已存在，月报不调用               │
│     ├ daily_kpi.py          # 已存在，月报不调用               │
│     ├ query_weekly.py       # 已存在，月报不调用               │
│     ├ weekly_kpi.py         # 已存在，月报不调用               │
│     ├ export_report.py      # 已存在，扩展 render_monthly_md   │
│     ├ query_monthly.py      # 新增：月度聚合数据查询           │
│     └ monthly_kpi.py        # 新增：月 KPI / 周趋势 / TopN /   │
│                              # MTBF / MTTR / 改进跟踪          │
└────────────────────────────────────────────────────────────────┘
```

**关键原则**：

- 所有逻辑都在 SOUL.md（prompt 驱动）+ 2 个新增 skill 脚本中，**不新增后端 Python 代码、不新增路由、不新增前端 GenUI 组件**。
- 完全复用 LangGraph SSE 流水线、`DeerFlowClient` 调用约定、`genui_middleware` 的 `(thread_id, callback_id)` 复合 key 机制（见 [genui_middleware.py](../../backend/packages/harness/deerflow/middleware/genui_middleware.py)）。
- 复用现有 artifact 路由（`/api/threads/{thread_id}/artifacts/...`，见 [uploads.py](../../backend/app/gateway/routers/uploads.py)）暴露下载链接。
- 复用 [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py) 中已存在的 `report_type` 调度逻辑（`SUPPORTED_REPORT_TYPES = {"daily", "weekly"}` 扩展为 `{"daily", "weekly", "monthly"}`）；输出目录环境变量遵循已有模式新增 `MONTHLY_REPORT_OUTPUT_DIR`，回退到 `DAILY_REPORT_OUTPUT_DIR`，最后回退到默认值 `/mnt/user-data/outputs`。

---

## 3. SOUL.md 改造

> **ui_interaction 回传字段约定**：当用户提交 `render_ui` 表单后，LLM 收到的消息结构为 `{type: "ui_interaction", callback_id, payload}`，表单字段值在 `payload` 顶层（非 `values`）。同一线程可能多次生成月报，**回溯 `ui_interaction` 历史时只能使用当前消息之前最近一次匹配的回调消息**，绝不能复用更早轮次参数。

### 3.1 GenUI 组件契约（与已注册 Block 对齐）

- `form`：`submit_label`、`default_values`（snake_case，顶层）；导出表单字段固定为 `format`（仅 `md`，PDF 由 SOUL 内部按 weasyprint 可用性自动尝试）。
- `card`：单值卡片，`title` + `value` + 可选 `subtitle` / `trend: {direction, value}` / `icon` / `color`。**每个 KPI 一个 card Block**，禁止把多个 KPI 塞进 `items`。`trend.value` 用于显示月环比百分比（如 `+3.2%`）；当同时选择了同比基准时，使用 `subtitle` 显示同比（如 `同比 +1.1%`）。
- `echart`：`option` 必须是完整 ECharts option（含 `xAxis`/`yAxis`/`series`），由 `monthly_kpi.py` 直接产出 `weekly_trend_chart` 字段。
- `table`：行数据用 `data`（不是 `rows`），列定义用 `columns: [{key, label}]`。月报使用三张表：`anomaly_top_n`（聚合）、`critical_events`（重大事件流水）、`improvement_tracking`（改进措施跟踪）。
- `markdown`：`content` 字符串，承载月度复盘与下月计划。

### 3.2 数据流与脚本契约（4 轮交互）

#### Round 1：渲染月报参数表单

当用户进入或要求生成月报但当前消息不是 `ui_interaction`、或缺少参数时，调用 `render_ui` 创建：

```json
{
  "component": "form",
  "action": "create",
  "interactive": true,
  "callback_id": "monthly-report-scope",
  "callback_timeout_ms": 600000,
  "props": {
    "title": "生成设备运行月报",
    "description": "请选择月报参数。下一步将选择具体设备和 KPI 指标。",
    "fields": [
      {
        "name": "report_month",
        "label": "报告月份（YYYY-MM）",
        "type": "text",
        "required": true,
        "placeholder": "如 2026-04",
        "validation": {"pattern": "^\\d{4}-\\d{2}$"}
      },
      {
        "name": "equipment_type",
        "label": "设备类型",
        "type": "select",
        "required": true,
        "options": [
          {"label": "全部", "value": "all"},
          {"label": "静设备", "value": "static_equipment"},
          {"label": "旋转机组", "value": "rotating_machinery"},
          {"label": "机泵", "value": "pump"},
          {"label": "往复机组", "value": "reciprocating_machinery"}
        ]
      },
      {
        "name": "compare_with",
        "label": "对比基准（可多选）",
        "type": "multi-select",
        "required": true,
        "options": [
          {"label": "上月（环比 MoM）", "value": "previous_month"},
          {"label": "去年同月（同比 YoY）", "value": "previous_year_month"},
          {"label": "不对比", "value": "none"}
        ]
      }
    ],
    "default_values": {
      "equipment_type": "all",
      "compare_with": ["previous_month"]
    },
    "submit_label": "下一步"
  }
}
```

渲染后只回复一句"请填写月报参数后提交。"并立即停止。**严禁在此轮渲染 Round 1.5 或 Round 2 表单**。

> `compare_with` 选 `none` 与其它任一基准互斥；脚本侧将 `none` 视为"清空对比基准"。

#### Round 1.5：月报参数回调 → 查询设备 → 渲染设备多选表单

收到 `callback_id == monthly-report-scope` 时：

1. 从 `payload` 读取 `report_month` / `equipment_type` / `compare_with`。
2. 执行 §3.3 输入校验。
3. 调用 `list_equipment.py`（与周报一致）：

   ```bash
   python /mnt/skills/custom/data-analyst/scripts/list_equipment.py \
     --type "{validated.equipment_type}" \
     --scope all \
     --limit 10000
   ```

4. 把脚本返回的 `equipment` 列表按 `area` 分组生成 `multi-select` `options`，渲染 `callback_id: monthly-report-equipment` 表单，默认全选。停止等待提交。

#### Round 2：设备选择回调 → 查询 KPI → 渲染 KPI 多选表单

收到 `callback_id == monthly-report-equipment` 时：

1. 从 `payload` 读取 `equipment_ids: string[]`，校验非空且每个 ID 符合 `[A-Za-z0-9_-]+`。
2. 回溯历史最近一次 `monthly-report-scope` 回调，取出 Round 1 参数。
3. 调用 `list_equipment.py --limit 1` 取 `available_kpis`。
4. 渲染 `callback_id: monthly-report-confirm` KPI 多选表单，每个 KPI（来自 `available_kpis`）生成 `kpi_{key}` checkbox。**额外固定项**（无论 `available_kpis` 是否返回，月报必须始终追加）：
   - `kpi_mtbf`：平均故障间隔时间，月度专属
   - `kpi_mttr`：平均修复时间，月度专属
   - `kpi_target_rate`：达标率（具备目标值的 KPI 在目标范围内的天数占比的简单平均）

   **默认勾选契约**：通过 `default_values` 顶层 dict 注入，三个固定项与 `available_kpis` 中标注为"主指标"（如 `runtime_rate` / `alarm_count`）的 KPI 一并勾选。下面的示例中 `kpi_runtime_rate` / `kpi_alarm_count` / `kpi_vibration` 等字段**仅为示意**，实际由 `list_equipment.available_kpis` 在运行时动态展开；`kpi_mtbf` / `kpi_mttr` / `kpi_target_rate` 是月报始终追加的三个固定项。"主指标"标记来自 `list_equipment.available_kpis[].is_primary`（若该元数据缺失，则默认勾选回退为"只勾固定 3 项"）：

   ```json
   {
     "component": "form",
     "action": "create",
     "interactive": true,
     "callback_id": "monthly-report-confirm",
     "props": {
       "title": "选择 KPI 指标",
       "fields": [
         {"name": "kpi_runtime_rate", "type": "checkbox", "label": "运行率"},
         {"name": "kpi_alarm_count",  "type": "checkbox", "label": "告警数"},
         {"name": "kpi_vibration",    "type": "checkbox", "label": "振动"},
         {"name": "kpi_mtbf",         "type": "checkbox", "label": "MTBF（平均故障间隔）"},
         {"name": "kpi_mttr",         "type": "checkbox", "label": "MTTR（平均修复时间）"},
         {"name": "kpi_target_rate",  "type": "checkbox", "label": "达标率"}
       ],
       "default_values": {
         "kpi_runtime_rate": true,
         "kpi_alarm_count": true,
         "kpi_mtbf": true,
         "kpi_mttr": true,
         "kpi_target_rate": true
       },
       "submit_label": "生成月报"
     }
   }
   ```

   用户可取消任意默认勾选项；三个固定项不是只读，用户有权放弃 MTBF/MTTR/达标率。停止等待提交。

#### Round 3：KPI 确认回调 → 生成月报 + 自动导出

收到 `callback_id == monthly-report-confirm` 时：

1. 收集所有 `kpi_*` 为 `true` 的字段，去前缀组装 `kpi_keys`（含 `mtbf` / `mttr` / `target_rate`）。如果为空，渲染 markdown 提示"请至少选择一个 KPI 指标"并停止。
2. 回溯历史 `monthly-report-scope` 与 `monthly-report-equipment` 最近一次回调，取出 `report_month` / `equipment_type` / `compare_with` / `equipment_ids`。
3. 调用月数据查询脚本。**设备数阈值映射**（与日报/周报同策略，便于 DSL 平台直接 copy）：

   | 设备数 | 同区域 | 跨区域 | 命令行模式 |
   |--------|--------|--------|------------|
   | ≤ 10 | — | — | `--equipment "csv"` 显式列出 |
   | > 10 | 同一 area | — | `--type T --scope area --scope-filter <area>` |
   | > 10 | — | 跨多 area | `--equipment "csv" --aggregate`（聚合模式，不下钻每台设备周序列） |
   | > 50 | 任意 | 任意 | 强制 `--aggregate`，覆盖上述路径 |

   ```bash
   python /mnt/skills/custom/data-analyst/scripts/query_monthly.py \
     --report-month "{validated.report_month}" \
     --type "{validated.equipment_type}" \
     --equipment "{csv_equipment_ids}" \
     --kpis "{validated.kpi_keys}" \
     --compare "{csv_compare_basis}"
   ```

   其中 `csv_compare_basis` 是经校验后的对比基准 CSV，如 `previous_month,previous_year_month` 或 `previous_month` 或空串（`none` 时）。

4. 调用月 KPI 计算脚本：

   ```bash
   python /mnt/skills/custom/data-analyst/scripts/monthly_kpi.py \
     --input /mnt/user-data/outputs/monthly_data.json \
     --output /mnt/user-data/outputs/monthly_kpi.json
   ```

5. 读取 `monthly_kpi.json`，按下列顺序渲染 GenUI Block：
   - 多个 `card` Block：每个 KPI 一张，含月环比 / 同比 trend
   - 1 个 `echart` Block：周维度趋势曲线
   - 1 个 `table` Block：异常 TopN（`anomaly_top_n`）
   - 1 个 `table` Block：重大事件回顾（`critical_events`）— 仅在 `critical_events` 非空时渲染
   - 1 个 `table` Block：改进措施跟踪（`improvement_tracking`）— 仅在 `improvement_tracking` 非空时渲染
   - 1 个 `markdown` Block：月度复盘 + 下月计划。**content 由 SOUL 用结构化字段拼装**（标题 + `overall_status.summary` 作为引言 + `monthly_review` 多段正文 + `next_month_plan[]` bullet 列表），不读取也不存在 `summary_markdown` 字段。完整长文版本由 `export_report.py` 在 artifact 中提供。

6. 调用 `export_report.py`（复用日报模块）自动写出 `monthly_report.md` 与 `monthly_report.pdf`。`write_report` 内部调用 `render_monthly_markdown(payload)` 完成全文拼装，SOUL 端不直接 import `render_monthly_markdown`：

   ```python
   import json, sys
   sys.path.insert(0, "/mnt/skills/custom/data-analyst/scripts")
   from export_report import write_report

   with open("/mnt/user-data/outputs/monthly_kpi.json", "r", encoding="utf-8") as f:
       payload = json.load(f)

   write_report(payload, "md", report_type="monthly")
   try:
       write_report(payload, "pdf", report_type="monthly")
       pdf_available = True
   except ImportError:
       pdf_available = False
   ```

7. 调用 `present_files(["/mnt/user-data/outputs/monthly_report.md", ...])`。**严禁对 `monthly_data.json` 或 `monthly_kpi.json` 调用 `present_files`**。

### 3.3 输入安全要求（MUST）

所有 shell 拼接前必须先校验 `payload`：

| 字段 | 校验规则 |
|------|----------|
| `report_month` | 正则 `^\d{4}-\d{2}$`，并能由 `datetime.strptime("%Y-%m")` 解析；月份在 `01-12` 范围；年份在 `2000-2100` 范围 |
| `equipment_type` | 枚举：`all` / `static_equipment` / `rotating_machinery` / `pump` / `reciprocating_machinery` |
| `compare_with[i]` | 枚举：`previous_month` / `previous_year_month` / `none`；若包含 `none` 则必须是唯一项 |
| `equipment_ids[i]` | 正则 `^[A-Za-z0-9_-]+$`，最长 64 字符 |
| `kpi_keys[i]` | 正则 `^[a-z_]+$`，必须在 `list_equipment.available_kpis` 返回集合 + `{mtbf, mttr, target_rate}` 内 |

任一校验失败时渲染 `markdown` 提示并停止，**禁止直接执行脚本**。命令行参数必须用双引号包裹，**禁止传入原始 `payload` 字符串**。

### 3.4 数据源优先级

1. MCP `data_catalog.*`：如未来注册可用，优先使用。
2. Skill 脚本 `query_monthly.py`：当前 MVP 主路径。
3. `http_connector`：真实数据接口落地后启用。
4. `query_monthly.py` 演示数据回退：必须明确告知用户当前为演示数据，不可包装为真实生产数据。

当 MCP 或真实接口返回错误、超时或未配置时，必须在 Markdown 中明确说明已使用演示数据回退。

### 3.5 callback_id 约定

| callback_id | 阶段 | 用途 |
|-------------|------|------|
| `monthly-report-scope` | Round 1 → 1.5 | 月报参数（报告月份、设备类型、对比基准） |
| `monthly-report-equipment` | Round 1.5 → 2 | 设备多选 |
| `monthly-report-confirm` | Round 2 → 3 | KPI 多选，触发生成 |
| `monthly-report-export` | Round 3 内（保留） | 手动重新导出（MVP 因 Round 3 自动导出，本回调保留备用） |

所有 callback_id 都以 `monthly-report-` 前缀，避免与日报（`daily-report-*`）和周报（`weekly-report-*`）混淆，符合 `(thread_id, callback_id)` 复合 key 隔离约定。

---

## 4. Skill 脚本设计

新增脚本目录：[skills/custom/data-analyst/scripts/](../../skills/custom/data-analyst/scripts/)。脚本均放在已存在的 `data-analyst` skill 下，符合 [config.yaml](../../agents/builtin/ai-report--monthly/config.yaml) 中声明的 `skills: [data-analyst]`。

### 4.1 query_monthly.py（月度数据查询）

**职责**：按月报参数生成 `monthly_data.json`，无真实数据 API 时返回稳定演示数据，确保端到端链路可运行。**默认仅返回周聚合 + 月聚合**，避免单脚本超时。`--include-daily` 标志显式启用日级下钻（MVP 阶段不在 SOUL 中启用，保留给 V2 趋势分析）。

**命令行参数**：

```bash
python /mnt/skills/custom/data-analyst/scripts/query_monthly.py \
  --report-month 2026-04 \
  --type rotating_machinery \
  --equipment "RM-001,RM-002" \
  --scope all \
  --scope-filter "" \
  --kpis "runtime_rate,downtime_count,alarm_count,vibration,energy,mtbf,mttr,target_rate" \
  --compare "previous_month,previous_year_month" \
  --aggregate
```

**输入校验**（脚本内层校验，作为 SOUL 校验的纵深防御）：

- `--report-month` 必须匹配 `^\d{4}-\d{2}$`，可由 `datetime.strptime("%Y-%m")` 解析；脚本内自动计算 `month_start` / `month_end`（含闰年 2 月）/ `day_count`。
- `--type` / `--compare` 校验同 SOUL §3.3；`--compare` 为 CSV，空串视为 `none`。
- `--equipment` 用逗号分隔，每项 `^[A-Za-z0-9_-]+$`。
- `--kpis` 用逗号分隔，每项必须在内置允许集合 + `{mtbf, mttr, target_rate}` 中。

**输出位置**：`/mnt/user-data/outputs/monthly_data.json`（沿用 `MONTHLY_REPORT_OUTPUT_DIR` → `DAILY_REPORT_OUTPUT_DIR` → 默认值的回退链）。

**输出 schema 关键字段**：

- `report_period: {report_month, month_start, month_end, day_count, week_buckets}`，其中 `week_buckets` 为按"月内截断 7 日桶"策略拆分的 4-5 个桶（**非 ISO 周**：W1 从 `month_start` 起，每 7 天一桶，W5 至 `month_end` 止；每桶含 `label` 如 `"W1: 04-01~04-07"` 与 `date_range` 与 `day_count`）。**禁止使用 `datetime.isocalendar()`**，避免跨自然月边界与示例对不上。
- `equipment_ids` / `kpi_keys`
- `compare_types: ["previous_month", "previous_year_month"]` / `compare_periods: {previous_month: {start, end}, previous_year_month: {start, end}}`
- `current.weekly`: 4-5 周序列，每周是与 `query_weekly.current.aggregated` 同构的对象（`kpis_mean` / `kpis_max` / `kpis_min` / `kpis_std`、`alarms` 该周流水）
- `current.aggregated`: 整月聚合 `kpis_mean` / `kpis_max` / `kpis_min` / `kpis_std` / `kpis_target_rate`（按 KPI 计算达标率）
- `current.maintenance`: `{total_failures: int, total_uptime_hours: float, total_downtime_minutes: float, total_repair_minutes: float, mtbf_hours: float | null, mttr_hours: float | null}`，用于派生 MTBF/MTTR；`total_uptime_hours` = 当月总运行小时数（`day_count × 24 − total_downtime_minutes / 60`），脚本直接产出，避免下游重复推导。
- `current.alarms`: 整月告警事件流水（按时间排序）
- `current.critical_events`: 仅 `level == "critical"` 的事件子集
- `current.improvement_tracking`: 上月遗留改进措施跟踪记录，结构 `[{id, owner, plan, due_date, status: "done"|"in_progress"|"delayed"|"closed", note}]`；演示数据回退时返回 2-3 条示例
- `compare`：以基准名为 key 的 dict，如 `{"previous_month": {weekly, aggregated, maintenance, alarms}, "previous_year_month": {...}}`；缺失基准对应 value 为 `null`
- `data_source: "real" | "demo_fallback"`：演示数据回退时强制为 `demo_fallback`

### 4.2 monthly_kpi.py（月 KPI 与图表生成）

**职责**：读取 `monthly_data.json`，生成可直接渲染的月 KPI、周趋势图、异常 TopN、重大事件、改进措施跟踪、下月计划。

**命令行参数**：

```bash
python /mnt/skills/custom/data-analyst/scripts/monthly_kpi.py \
  --input /mnt/user-data/outputs/monthly_data.json \
  --output /mnt/user-data/outputs/monthly_kpi.json
```

**输出位置**：`/mnt/user-data/outputs/monthly_kpi.json`。

**输出 schema 关键字段**：

- `report_period: {report_month, month_start, month_end, day_count}`
- `compare_types` / `compare_periods`（与 query_monthly 同步）
- `overall_status: {level: "good"|"warning"|"critical", summary: "..."}`：`summary` 为**单行**总结（≤ 80 字），供 SOUL 渲染概览 card / Markdown banner 使用；多段月度复盘见下方 `monthly_review`，两者职责不重叠。
- `kpi_summary[]`：每个 KPI 一项，字段：
  - `key` / `name` / `unit`
  - `current_mean` / `current_peak` / `current_trough` / `current_volatility`（std/mean）
  - `current_in_target_ratio`：**单 KPI** 达标占比（0-1，"达标天数 / 当月天数"；若 KPI 未配置目标值则为 `null`）。注意这是单 KPI 维度的字段，不要与整月聚合 KPI `key == "target_rate"` 混淆。
  - `previous_month_mean` / `delta_mom` / `delta_mom_pct` / `direction_mom`
  - `previous_year_month_mean` / `delta_yoy` / `delta_yoy_pct` / `direction_yoy`（**字段名包含 month**，明确为"去年同月"，不是"去年全年平均"）
  - `better_when_higher: bool`
  - **特殊 KPI**：
    - `key == "mtbf"`：`current_mean` 单位 `小时`，公式 `total_uptime_hours / max(total_failures, 1)`（`total_failures == 0` 时直接输出 `null`）
    - `key == "mttr"`：`current_mean` 单位 `小时`，公式 `total_repair_minutes / max(total_failures, 1) / 60`（`total_failures == 0` 时直接输出 `null`）
    - `key == "target_rate"`：**整月聚合 KPI**，由所有具备 `current_in_target_ratio` 的 KPI 做简单平均得出（暂不加权）；与单 KPI `current_in_target_ratio` 区分清楚——这一项的 `current_mean` 是数值本身，没有 `current_in_target_ratio` 子字段
- `weekly_trend_chart`：完整 ECharts option（4-5 周 x 轴，`xAxis.data` 取自 `report_period.week_buckets[].label`；多 KPI series，`legend.selected` 控制默认显示主 KPI）
- `anomaly_top_n[]`：聚合表，列 `equipment` / `level` / `count` / `latest_time` / `dominant_message`，按 `count` desc 取 Top10
- `critical_events[]`：重大事件流水，列 `time` / `equipment` / `level` / `message` / `duration_minutes` / `resolved`；为空数组时 SOUL 不渲染该 table
- `improvement_tracking[]`：上月遗留改进措施，列 `id` / `owner` / `plan` / `due_date` / `status` / `completion_rate`（百分比，已完成 100%，进行中按 SOUL/演示数据估算） / `note`；为空数组时 SOUL 不渲染该 table
- `monthly_review: string`：月度复盘多段正文（多行字符串，由 `monthly_kpi.py` 机械生成；供 `render_monthly_markdown` 直接嵌入"月度复盘"小节）
- `next_month_plan: string[]`：下月计划与关注重点（数组项为单行要点；由 `render_monthly_markdown` 渲染为 bullet 列表）
- `data_source: "real" | "demo_fallback"`（透传自 `monthly_data.json`）

**计算口径说明**：

- 月均值 = 周聚合 `kpis_mean` 加权（按周 day_count）平均；
- 月峰值/低谷 = 整月 daily 序列 max/min（若 `--include-daily=false` 则取周 max/min）；
- 月波动率 = 整月 std / 整月 mean（mean 为 0 时输出 `null`）；
- 月环比 `delta_mom_pct` = `(current_mean - previous_month_mean) / previous_month_mean`（previous_month_mean 为 0 时输出 `null`）；
- 月同比 `delta_yoy_pct` 同公式；
- MTBF = `total_uptime_hours / max(total_failures, 1)`；当 `total_failures == 0` 时输出 `null` 并在 markdown 中标注"本月零故障"。
- MTTR = `total_repair_minutes / max(total_failures, 1) / 60`；同上保护。
- `current_in_target_ratio` 单 KPI 计算口径：`满足目标值的天数 / 当月天数`，目标值定义由 `list_equipment.available_kpis[].target` 提供（如缺失则该 KPI 输出 `null` 并在 markdown 中标注）。整月聚合 KPI `target_rate` 由 `monthly_kpi.py` 对所有具备 `current_in_target_ratio` 的 KPI 做简单平均得出。

### 4.3 export_report.py 复用与扩展

**复用策略**：直接复用现有 [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py)，已具备 `SUPPORTED_REPORT_TYPES = {"daily", "weekly"}` 与 `report_type` 调度。扩展项：

1. `SUPPORTED_REPORT_TYPES` 扩展为 `{"daily", "weekly", "monthly"}`。
2. 新增常量 `MONTHLY_INPUT_FILENAME = "monthly_kpi.json"`。
3. `_output_dir(report_type)` 增加 `monthly` 分支：`MONTHLY_REPORT_OUTPUT_DIR` → `DAILY_REPORT_OUTPUT_DIR` → `DEFAULT_OUTPUT_DIR`。
4. `load_payload(path, report_type)` 增加 monthly 分支：默认文件名 `monthly_kpi.json`。
5. `write_report(payload, fmt, ..., report_type)` 增加 monthly 分支：文件名 `monthly_report.{md,pdf}`。
6. **新增 `render_monthly_markdown(payload, thread_id)` 函数**：把 `monthly_kpi.json` 渲染成 8 节 Markdown：月度总览 / 月 KPI 表（含 MTBF/MTTR/达标率；**小节尾部以引用块（`>`）输出"口径说明"脚注**，明确"月均值按周 day_count 加权平均"以与周报"7 日简单平均"、日报"单日值"区分）/ 周趋势图描述（PDF 时嵌入 SVG）/ 异常 TopN / 重大事件回顾 / 月环比 + 同比 / 改进措施跟踪 / 下月计划。
7. CLI `--report-type` 增加 `monthly` 选项，与现有 daily/weekly 路径一致。

**关键 Markdown 渲染契约**：

- `render_monthly_markdown(payload)` 是 **唯一渲染入口**，按 `monthly_kpi.json` 结构化字段拼装 8 节 Markdown（月度总览 / 月 KPI 表含 MTBF/MTTR/达标率 + 小节尾"口径说明"引用块 / 周趋势 SVG / 异常 TopN / 重大事件回顾 / 月环比+同比 / 改进措施跟踪 / 下月计划）。`monthly_kpi.py` **不输出**完整 Markdown 字符串，与日报 `daily_kpi.py` / 周报 `weekly_kpi.py` 行为一致——避免脚本与 export 层维护两套渲染。
- PDF 走与日报/周报一致的 weasyprint 路径；未安装时抛 `ImportError`，由 SOUL 捕获并降级。
- 周趋势图 SVG 嵌入复用现有 `trend_chart_to_svg`，输入为 `monthly_kpi.weekly_trend_chart`。

**命令行用法**（可选，主路径走 Python 直接 import）：

```bash
python /mnt/skills/custom/data-analyst/scripts/export_report.py \
  --input /mnt/user-data/outputs/monthly_kpi.json \
  --report-type monthly \
  --format md \
  --output /mnt/user-data/outputs/monthly_report.md
```

返回 JSON：

```json
{"format": "md", "filename": "monthly_report.md", "path": "/mnt/user-data/outputs/monthly_report.md", "artifact_path": "/mnt/user-data/outputs/monthly_report.md"}
```

---

## 5. 前端：复用已有 GenUI Block，无需新增

经核查 [frontend/src/core/genui/registry.ts](../../frontend/src/core/genui/registry.ts) 已支持月报全部所需组件：`form` / `card` / `echart` / `table` / `markdown`。

- 月报多 KPI 卡片：渲染多个 `card` Block，每个含 `trend.direction` + `trend.value`（环比百分比）；`subtitle` 显示同比百分比。
- 周趋势曲线：1 个 `echart`，`option` 来自 `monthly_kpi.weekly_trend_chart`，前端不做二次组装。
- 异常 TopN / 重大事件 / 改进跟踪：3 个独立 `table` Block，`columns` 由 SOUL 指定，`data` 来自 KPI JSON；当对应数据为空时 SOUL 跳过渲染该 table（不渲染空表）。
- 月度复盘 + 下月计划：1 个 `markdown` Block，content 由 SOUL 用 `overall_status.summary` + `monthly_review` + `next_month_plan[]` 三个结构化字段拼装；完整长文版本由 artifact 提供。
- 下载链接：通过 sandbox artifact URL（`/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/monthly_report.md`）实现，已有 [uploads 路由](../../backend/app/gateway/routers/uploads.py) 支持。

**无需新增前端组件，无需修改 GenUI registry，无需新增路由**。

---

## 6. 数据契约

### 6.1 query_monthly.py 输出

```json
{
  "report_period": {
    "report_month": "2026-04",
    "month_start": "2026-04-01",
    "month_end": "2026-04-30",
    "day_count": 30,
    "week_buckets": [
      {"label": "W1: 04-01~04-05", "date_range": {"start": "2026-04-01", "end": "2026-04-05"}, "day_count": 5},
      {"label": "W2: 04-06~04-12", "date_range": {"start": "2026-04-06", "end": "2026-04-12"}, "day_count": 7},
      {"label": "W3: 04-13~04-19", "date_range": {"start": "2026-04-13", "end": "2026-04-19"}, "day_count": 7},
      {"label": "W4: 04-20~04-26", "date_range": {"start": "2026-04-20", "end": "2026-04-26"}, "day_count": 7},
      {"label": "W5: 04-27~04-30", "date_range": {"start": "2026-04-27", "end": "2026-04-30"}, "day_count": 4}
    ]
  },
  "equipment_ids": ["RM-001", "RM-002"],
  "kpi_keys": ["runtime_rate", "downtime_count", "alarm_count", "vibration", "mtbf", "mttr", "target_rate"],
  "compare_types": ["previous_month", "previous_year_month"],
  "compare_periods": {
    "previous_month": {"start": "2026-03-01", "end": "2026-03-31"},
    "previous_year_month": {"start": "2025-04-01", "end": "2025-04-30"}
  },
  "current": {
    "weekly": [
      {
        "label": "W1",
        "date_range": {"start": "2026-04-01", "end": "2026-04-05"},
        "kpis_mean": {"runtime_rate": 92.5, "downtime_count": 1.4, "alarm_count": 3.7, "vibration": 3.0},
        "kpis_max":  {"runtime_rate": 96.0, "downtime_count": 3,   "alarm_count": 6,   "vibration": 3.6},
        "kpis_min":  {"runtime_rate": 89.5, "downtime_count": 0,   "alarm_count": 2,   "vibration": 2.5},
        "kpis_std":  {"runtime_rate": 2.1,  "downtime_count": 1.0, "alarm_count": 1.5, "vibration": 0.4},
        "alarms": []
      }
    ],
    "aggregated": {
      "kpis_mean": {"runtime_rate": 93.0, "downtime_count": 1.6, "alarm_count": 4.0, "vibration": 3.0},
      "kpis_max":  {"runtime_rate": 96.5, "downtime_count": 4,   "alarm_count": 8,   "vibration": 3.8},
      "kpis_min":  {"runtime_rate": 88.2, "downtime_count": 0,   "alarm_count": 1,   "vibration": 2.4},
      "kpis_std":  {"runtime_rate": 2.3,  "downtime_count": 1.1, "alarm_count": 1.7, "vibration": 0.4},
      "kpis_target_rate": {"runtime_rate": 0.83, "vibration": 0.93}
    },
    "maintenance": {
      "total_failures": 6,
      "total_downtime_minutes": 480,
      "total_repair_minutes": 320,
      "total_uptime_hours": 692,
      "mtbf_hours": 115.3,
      "mttr_hours": 0.89
    },
    "alarms": [
      {"time": "2026-04-03 08:15:32", "equipment": "RM-001", "level": "warning", "message": "振动超阈值"},
      {"time": "2026-04-17 14:02:17", "equipment": "RM-002", "level": "critical", "message": "轴承温度超限"}
    ],
    "critical_events": [
      {"time": "2026-04-17 14:02:17", "equipment": "RM-002", "level": "critical", "message": "轴承温度超限", "duration_minutes": 90, "resolved": true}
    ],
    "improvement_tracking": [
      {"id": "IMP-2026-03-01", "owner": "张三", "plan": "RM-002 轴承温度联合诊断", "due_date": "2026-04-15", "status": "done", "note": "已完成，温度告警下降 60%"},
      {"id": "IMP-2026-03-02", "owner": "李四", "plan": "RM-001 振动传感器更换", "due_date": "2026-04-30", "status": "in_progress", "note": "备件到货延期，预计 5 月 10 日完成"},
      {"id": "IMP-2026-02-07", "owner": "王五", "plan": "P-101 冷却水泵密封件更换", "due_date": "2026-04-10", "status": "delayed", "note": "因供应商交期延误，重新调度至 5 月上旬"}
    ]
  },
  "compare": {
    "previous_month": {
      "weekly": [],
      "aggregated": {
        "kpis_mean": {"runtime_rate": 91.0, "downtime_count": 1.8, "alarm_count": 4.5, "vibration": 3.1}
      },
      "maintenance": {
        "total_failures": 8,
        "total_uptime_hours": 681,
        "total_downtime_minutes": 540,
        "total_repair_minutes": 528,
        "mtbf_hours": 86.6,
        "mttr_hours": 1.10
      },
      "alarms": []
    },
    "previous_year_month": {
      "weekly": [],
      "aggregated": {
        "kpis_mean": {"runtime_rate": 89.5, "downtime_count": 2.2, "alarm_count": 5.1, "vibration": 3.3}
      },
      "maintenance": {
        "total_failures": 10,
        "total_uptime_hours": 700,
        "total_downtime_minutes": 600,
        "total_repair_minutes": 750,
        "mtbf_hours": 70.0,
        "mttr_hours": 1.25
      },
      "alarms": []
    }
  },
  "data_source": "demo_fallback"
}
```

### 6.2 monthly_kpi.py 输出

```json
{
  "report_period": {
    "report_month": "2026-04",
    "month_start": "2026-04-01",
    "month_end": "2026-04-30",
    "day_count": 30
  },
  "compare_types": ["previous_month", "previous_year_month"],
  "compare_periods": {
    "previous_month": {"start": "2026-03-01", "end": "2026-03-31"},
    "previous_year_month": {"start": "2025-04-01", "end": "2025-04-30"}
  },
  "overall_status": {
    "level": "good",
    "summary": "本月运行率 93.0%，环比上升 2.2pp，同比上升 3.5pp；MTBF 由 86.6h 提升至 115.3h，改进措施完成率 50%。"
  },
  "kpi_summary": [
    {
      "key": "runtime_rate", "name": "运行率", "unit": "%",
      "current_mean": 93.0, "current_peak": 96.5, "current_trough": 88.2, "current_volatility": 0.025,
      "current_in_target_ratio": 0.83,
      "previous_month_mean": 91.0, "delta_mom": 2.0, "delta_mom_pct": 0.022, "direction_mom": "up",
      "previous_year_month_mean": 89.5, "delta_yoy": 3.5, "delta_yoy_pct": 0.039, "direction_yoy": "up",
      "better_when_higher": true
    },
    {
      "key": "mtbf", "name": "MTBF", "unit": "小时",
      "current_mean": 115.3, "current_peak": null, "current_trough": null, "current_volatility": null,
      "current_in_target_ratio": null,
      "previous_month_mean": 86.6, "delta_mom": 28.7, "delta_mom_pct": 0.331, "direction_mom": "up",
      "previous_year_month_mean": 70.0, "delta_yoy": 45.3, "delta_yoy_pct": 0.647, "direction_yoy": "up",
      "better_when_higher": true
    },
    {
      "key": "mttr", "name": "MTTR", "unit": "小时",
      "current_mean": 0.89, "current_peak": null, "current_trough": null, "current_volatility": null,
      "current_in_target_ratio": null,
      "previous_month_mean": 1.10, "delta_mom": -0.21, "delta_mom_pct": -0.191, "direction_mom": "down",
      "previous_year_month_mean": 1.25, "delta_yoy": -0.36, "delta_yoy_pct": -0.288, "direction_yoy": "down",
      "better_when_higher": false
    }
  ],
  "weekly_trend_chart": {
    "title": {"text": "本月周维度趋势"},
    "tooltip": {"trigger": "axis"},
    "legend": {"data": ["运行率", "告警数"], "selected": {"运行率": true, "告警数": true}},
    "xAxis": {"type": "category", "data": ["W1: 04-01~04-05", "W2: 04-06~04-12", "W3: 04-13~04-19", "W4: 04-20~04-26", "W5: 04-27~04-30"]},
    "yAxis": [{"type": "value", "name": "%"}, {"type": "value", "name": "次"}],
    "series": [
      {"name": "运行率", "type": "line", "yAxisIndex": 0, "data": [92.5, 94.1, 93.0, 91.2, 95.3]},
      {"name": "告警数", "type": "bar",  "yAxisIndex": 1, "data": [18, 12, 22, 14, 8]}
    ]
  },
  "anomaly_top_n": [
    {"equipment": "RM-002", "level": "critical", "count": 3, "latest_time": "2026-04-26 10:22:08", "dominant_message": "轴承温度超限"},
    {"equipment": "RM-001", "level": "warning",  "count": 12, "latest_time": "2026-04-29 22:01:43", "dominant_message": "振动超阈值"}
  ],
  "critical_events": [
    {"time": "2026-04-17 14:02", "equipment": "RM-002", "level": "critical", "message": "轴承温度超限", "duration_minutes": 90, "resolved": true}
  ],
  "improvement_tracking": [
    {"id": "IMP-2026-03-01", "owner": "张三", "plan": "RM-002 轴承温度联合诊断", "due_date": "2026-04-15", "status": "done", "completion_rate": 100, "note": "已完成，温度告警下降 60%"},
    {"id": "IMP-2026-03-02", "owner": "李四", "plan": "RM-001 振动传感器更换", "due_date": "2026-04-30", "status": "in_progress", "completion_rate": 60, "note": "备件到货延期，预计 5 月 10 日完成"},
    {"id": "IMP-2026-02-07", "owner": "王五", "plan": "P-101 冷却水泵密封件更换", "due_date": "2026-04-10", "status": "delayed", "completion_rate": 30, "note": "因供应商交期延误，重新调度至 5 月上旬"}
  ],
  "monthly_review": "本月整体运行平稳，运行率环比上升 2.2pp、同比上升 3.5pp。MTBF 由 86.6h 提升至 115.3h，改善显著，主要受益于上月部署的 RM-002 轴承诊断方案。RM-001 振动传感器更换计划因备件到货延期未在月内闭环。",
  "next_month_plan": [
    "5 月 10 日前完成 RM-001 振动传感器更换（IMP-2026-03-02）",
    "RM-002 轴承温度持续监控，纳入预防性维护双周复盘",
    "MTTR 已下降至 0.89h，目标 5 月维持在 1h 以内",
    "新增改进项：W5 告警下降至 8 次，复盘是否可作为下月运行基线"
  ],
  "data_source": "demo_fallback"
}
```

> **字段口径说明**：
> - `critical_events` 与 `alarm_table` 的区别：月报放弃完整流水（数据量过大），仅保留 `critical` 级别独立列表 + `anomaly_top_n` 聚合表。如未来需要完整流水，可由前端通过 artifact URL 下载原始 `monthly_data.json`。
> - `improvement_tracking` 的来源：MVP 阶段由 `query_monthly.py` 的演示数据回退提供 2-3 条样例；真实数据落地时由 MCP `data_catalog.improvement_plans` 或 http_connector 接口提供。
> - **渲染分层契约**：`monthly_kpi.py` 只输出结构化数据（不输出完整 Markdown 正文），与日报/周报模式一致；完整 Markdown 由 `export_report.py` 的 `render_monthly_markdown(payload)` 在 export 时拼装。SOUL 渲染最终 `markdown` Block 时优先使用结构化字段（如 `overall_status.summary` / `monthly_review` / `next_month_plan`），需要完整长文时通过 artifact URL 拉取 `monthly_report.md`，避免脚本与 export 层维护两套渲染。

---

## 7. 与自定义模板平台 DSL 的兼容性

本设计与 [AI 报告自定义模板功能设计文档](./2026-05-14-ai-report-custom-template-design.md) §13.4 的月报 DSL 草案完全兼容，原则如下：

1. **脚本契约统一**：本设计的 `query_monthly.py` 与 `monthly_kpi.py` 同时是原生 `ai-report--monthly` SOUL.md 的直接调用对象，也是未来 `monthly-equipment` DSL builtin 模板在 `report_scripts.yaml` 注册的 entry。脚本 CLI 参数与输出 schema 是 contract，不会随调用方变化。
2. **DSL `form_steps` 字段名一致**：DSL 草案使用的 `report_month` / `equipment_type` / `compare_with` / `equipment_ids` / `kpi_keys` 字段命名与本设计 SOUL.md 完全一致，意味着同一组校验规则、同一组脚本参数。
3. **`compare_with` 取值统一**：DSL 草案使用 `mom` / `yoy` 短名，本设计使用 `previous_month` / `previous_year_month` 长名。**约定**：DSL 平台在加载模板时通过 alias 映射（`mom → previous_month`，`yoy → previous_year_month`），脚本参数最终统一为长名。这与日报 `previous_day` / 周报 `previous_week` 长名保持一致。
4. **输出 schema 可被 DSL `sections.source` 引用**：`monthly_kpi.json` 的顶层字段（`overall_status` / `kpi_summary` / `weekly_trend_chart` / `anomaly_top_n` / `critical_events` / `improvement_tracking` / `monthly_review` / `next_month_plan`）都是合法的 dotted-path 起点，DSL 可直接通过 `source: monthly_kpi.kpi_summary` 渲染章节，无需中间适配器。DSL 平台如需完整 Markdown 长文，应在 sections 中调用 `export_report.render_monthly_markdown` 而非读取脚本输出字段。
5. **改进跟踪脚本**：自定义模板设计中提到的 `improvement_tracking` 第三脚本被合并到 `query_monthly.py`（演示阶段）与 `monthly_kpi.py`（计算 completion_rate）中，避免脚本碎片化。当真实改进措施 API 可用时，可拆分为独立 `improvement_tracking.py`，并通过 `report_scripts.yaml` 注册——脚本契约保持向后兼容（`monthly_data.current.improvement_tracking` 字段不变）。
6. **双路径并行**：原生 `ai-report--monthly` 走 SOUL.md，未来 `monthly-equipment` DSL 模板走自定义模板平台模板运行时，二者最终输出结构一致；用户可在管理端基于 DSL 复制月报并自定义章节，而内置的 `ai-report--monthly` 保留作为 fallback。
7. **未来迁移路径**：当 DSL 平台稳定后，`ai-report--monthly` 可选择性重写为 `monthly-equipment` DSL builtin 模板（参见自定义模板设计 §11.4 fallback 双轨策略），SOUL.md 作为兜底保留，脚本零改动。

---

## 8. 实施计划引用

本设计仅完成"能力蓝图"，具体 Story 拆分、依赖关系、Sprint 排期、验收标准请独立编写 `2026-05-18-ai-report-monthly-sprint-plan.md`，建议拆分为以下 Story 雏形（不在本设计中展开）：

- Story M1：`query_monthly.py` 演示数据版（含输入校验、月份/闰年处理、月内截断 7 日桶拆分、单元测试）
- Story M2：`monthly_kpi.py` 月 KPI + MTBF/MTTR + 周趋势 ECharts option + 改进跟踪 completion_rate 计算
- Story M3：`export_report.py` 扩展 `render_monthly_markdown` + monthly 文件路径调度（保持日报/周报向后兼容）
- Story M4：SOUL.md 4 轮表单实现 + 输入校验（含 `compare_with` multi-select 互斥校验） + present_files 闭环
- Story M5：端到端联调（含 weasyprint 不可用降级、设备 > 20 跨区域聚合、`critical_events` 与 `improvement_tracking` 空数组跳过渲染）
- Story M6：与 DSL 平台脚本注册联调（依赖 [自定义模板 Phase 5](./2026-05-14-ai-report-custom-template-design.md)，含 `mom`/`yoy` alias 映射）

---

## 9. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 月份边界与闰年处理 | 2 月跨闰年时 day_count 错误 | `query_monthly.py` 使用 `calendar.monthrange(year, month)` 计算 day_count；单元测试覆盖 2020/2024/2025 平闰年；输出 `report_period.day_count` 让所有下游脚本透明使用 |
| 月内截断 7 日桶与自然月边界冲突 | 月末 W5 不足 7 天，月内总天数不被 7 整除时桶数浮动 | 采用"月内截断"策略：W1 从 month_start 起每 7 天一桶，W5 至 month_end 止；输出 `day_count` 字段说明每桶实际天数；周均值按 day_count 加权；明确禁止使用 ISO 周（避免跨月） |
| 数据量（30 天 × N 设备 × M KPI） | 单次脚本执行内存/时间放大 | `query_monthly.py` 默认 `--aggregate` 仅返回周聚合 + 月聚合，不下钻每日；`--include-daily` 显式启用日级（MVP 不启用，保留 V2 趋势分析）；`anomaly_top_n` 限制 Top10；`critical_events` 限制 50 条 |
| 同期对比缺失（去年同月数据可能不存在） | `compare_with=[previous_year_month]` 时报错或显示空 | `query_monthly.py` 检测到同期数据为空时返回 `compare.previous_year_month: null` 并附带 `compare_warning`；`monthly_kpi.py` 在 `kpi_summary` 的 `previous_year_month_mean` 输出 `null`；SOUL 渲染 `card.subtitle` 时显示 `同比 —` 而非 `+NaN%` |
| `compare_with` multi-select 与 `none` 互斥 | 用户可能同时勾选 `none` 与其它基准导致语义冲突 | SOUL Round 1.5 校验：若 `compare_with` 包含 `none` 但长度 > 1，渲染 markdown 提示"`none` 必须为唯一选项"并重新渲染 Round 1 表单 |
| MTBF/MTTR 数据来源 | 真实维修工单数据可能未接入 | 演示数据回退时由 `query_monthly.py` 生成稳定示例（`maintenance.total_failures` / `total_uptime_hours` / `total_repair_minutes`）；`monthly_kpi.py` 在 `total_failures == 0` 时输出 `null` 并在 markdown 中标注"本月零故障，MTBF/MTTR 不适用" |
| 改进措施跟踪数据来源 | 真实改进措施 API 未定 | MVP 阶段由 `query_monthly.py` 演示数据回退提供 2-3 条样例；真实接口落地后通过 MCP `data_catalog.improvement_plans` 或独立 `improvement_tracking.py` 接入；`monthly_kpi.improvement_tracking` 空数组时 SOUL 跳过该 table 渲染 |
| KPI 口径与周报/日报一致性 | 用户在三种报告间切换时质疑数据矛盾 | 月均值定义为"周聚合 day_count 加权平均"，并在 markdown 中标注"按周聚合再加权"，与周报"7 日 daily 简单平均"口径区分；导出 markdown 加入"口径说明"小节，引用 `2026-05-13-ai-report-daily-design.md` 与 `2026-05-18-ai-report-weekly-design.md` |
| 演示数据回退被误认为真实数据 | 决策风险 | 脚本演示数据在输出 JSON 中标 `data_source: "demo_fallback"`；SOUL 在概览开头插入"当前为演示数据"banner（红色 markdown 引用块）；`render_monthly_markdown` 同步在 Markdown 头部插入提示 |
| weasyprint 不可用导致 PDF 缺失 | 用户预期落空 | 与日报/周报相同：SOUL try/except 捕获 `ImportError`，降级为仅 Markdown 下载；下载区显式列出"PDF 不可用（weasyprint 未安装）" |
| 周趋势图 4-5 桶造成可视化"参差不齐" | W1/W5 不足 7 天导致曲线变形 | `weekly_trend_chart.xAxis.data` 使用桶 `label`（含日期范围），SOUL 在 markdown 中提示"W1/W5 可能不足 7 天"；KPI 计算按 day_count 加权 |

---

## 10. 与现有架构对齐检查

| 项 | 现有模式（周报） | 本设计（月报） | 状态 |
|----|------------------|----------------|------|
| Agent 配置位置 | `agents/builtin/ai-report--weekly/` | 复用现有 `agents/builtin/ai-report--monthly/`，仅改 SOUL.md | OK |
| Skill 脚本位置 | `skills/custom/data-analyst/scripts/` | 同（新增 2 个脚本，复用 list_equipment.py 与 export_report.py） | OK |
| 数据源发现 | MCP → skill 脚本 → http_connector → 演示数据 | 同优先级链 | OK |
| 交互方式 | render_ui form + ui_interaction，4 轮表单 | render_ui form + ui_interaction，4 轮表单（结构同构） | OK |
| 渲染组件 | GenUI registry：card/echart/table/markdown/form | 同（不新增组件；月报相比周报多渲染两个 `table` Block：`critical_events` + `improvement_tracking`） | OK |
| 文件下载 | sandbox `/mnt/user-data/outputs` + artifact URL | 同（`monthly_report.md` / `monthly_report.pdf`） | OK |
| LLM 流水线 | DeerFlowClient 标准流程 + LangGraph SSE | 同（不改动 runtime） | OK |
| 后端改动 | 零后端代码改动 | 零后端代码改动 | OK |
| 前端改动 | 零前端代码改动 | 零前端代码改动 | OK |
| callback_id 命名 | `weekly-report-*` | `monthly-report-*`（避免与日报/周报混淆） | OK |
| 对比基准命名 | `previous_week` / `previous_year` | `previous_month` / `previous_year_month`（保持与日报 `previous_day` 一致的长名风格） | OK |
| `export_report.py` `report_type` | 已支持 `daily` / `weekly` | 扩展为 `daily` / `weekly` / `monthly`，向后兼容 | OK |

**全部由 SOUL.md + Skill 脚本实现**，不引入新的 Python 后端代码、不新增路由、不新增前端组件。这与日报/周报智能体架构完全一致，符合 DeerFlow agent 体系"prompt 工程 + skill 脚本最大化扩展能力"的设计意图，并为未来迁移到 `monthly-equipment` DSL builtin 模板保留无缝路径。

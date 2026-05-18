# AI 周报智能体功能设计文档

> **范围**：完整功能设计，覆盖 SOUL.md 改造、数据接入、Skill 脚本、GenUI 渲染、Markdown/PDF 导出、周环比与同期对比。
> **遵循模式**：完全对齐 [AI 日报智能体功能设计文档](./2026-05-13-ai-report-daily-design.md) 的"SOUL.md（prompt 驱动） + skill 脚本（确定性计算） + GenUI 多轮表单"架构，复用 [list_equipment.py](../../skills/custom/data-analyst/scripts/list_equipment.py) 与 [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py)，不引入新的后端 Python 代码、不新增路由、不新增前端组件。
> **与自定义模板平台对齐**：本设计与 [AI 报告自定义模板功能设计文档](./2026-05-14-ai-report-custom-template-design.md) §13.3 周报 DSL 草案保持脚本契约一致，使原生 `ai-report--weekly` 与未来 `weekly-equipment` DSL builtin 模板可共享同一套数据/KPI 脚本。

---

## 1. 现状与目标

### 1.1 现状

当前 [agents/builtin/ai-report--weekly/SOUL.md](../../agents/builtin/ai-report--weekly/SOUL.md) 仅是 prompt-only 草稿（25 行），与日报相比存在以下显著差距：

- **无动态参数表单**：未使用 `render_ui form` 收集周开始日期、设备类型、对比基准。
- **无设备/KPI 多步收集**：缺少日报的 Round 1.5（设备多选） + Round 2（KPI 多选）多轮交互。
- **无数据采集脚本**：没有 `query_weekly.py` 拉取 7 天聚合数据。
- **无 KPI 计算脚本**：没有 `weekly_kpi.py` 产出周均值、峰值、日趋势、周环比 delta 等。
- **无导出能力**：未对接 `export_report.py`，用户无法下载 Markdown/PDF。
- **无演示数据回退**：真实数据源不可用时，端到端链路无法闭环。
- **章节内容凭空生成**：LLM 仅依据 prompt 描述输出虚构内容，违反"数据优先"原则。

[config.yaml](../../agents/builtin/ai-report--weekly/config.yaml) 已声明 `parent: ai-report` / `order: 2` / `skills: [data-analyst]`,无需改动；本立项只需要补齐 SOUL.md 与 2 个新脚本即可达到与日报对等的能力。

### 1.2 目标

| 能力 | 描述 |
|------|------|
| 交互式参数收集 | 4 轮 GenUI 表单：周报参数（周开始日期/设备类型/对比基准） → 设备多选 → KPI 多选 → 生成 + 导出 |
| 自动数据采集 | 按优先级链获取 7 天聚合数据（MCP → `query_weekly.py` → http_connector → 演示数据回退） |
| 结构化输出 | `card`（周 KPI） + `echart`（7 日趋势） + `table`（告警 TopN/告警流水） + `markdown`（周报总结/下周关注） |
| 导出 | Markdown 必需，PDF 可选降级（与日报一致），通过 sandbox artifact URL 提供下载 |
| 同期对比 | 自动拉取上一周或去年同期数据，输出周环比 delta；同期数据缺失时优雅降级 |
| 周维度专属内容 | 日趋势曲线、周环比表、异常 TopN 聚合、下周关注重点 |

### 1.3 与日报的差异

| 维度 | ai-report--daily | ai-report--weekly |
|------|------------------|-------------------|
| 时间维度 | 单日 24 小时 | 7 天（自然周或自定义 7 日窗口） |
| 数据聚合粒度 | 按小时（24 桶） | 按日（7 桶），每日复用 daily 维度 |
| 章节结构 | 概览 / KPI / 24h 趋势 / 异常事件 / 建议 | 概览 / 周 KPI / 日趋势 / 异常 TopN / 周环比 / 下周关注 |
| 对比基准 | `previous_day` / `previous_week` / `none` | `previous_week` / `previous_year` / `none` |
| KPI 指标语义 | 当日值 | 周均值 / 周峰值 / 周低谷 / 周波动率 |
| 告警呈现 | 完整事件流水表 | 按设备/级别聚合的 TopN + 简化流水 |
| 数据量级 | N 设备 × M KPI × 24 小时 | N 设备 × M KPI × 7 日（约 7 倍但仍可单脚本处理） |
| 趋势图横轴 | 0:00–23:00 小时刻度 | 周一–周日日期刻度 |
| 下游延伸 | 单日复盘 | 周复盘 + 下周计划 |

---

## 2. 系统架构

**入口流程**：用户从 `ai-report`（`type: group`）子 agent 列表中进入 `ai-report--weekly`，与现有 group/sub-agent 路由完全一致，父 group 不显式声明子 agent，依赖目录扫描发现。

```
┌────────────────────────────────────────────────────────────────┐
│                       前端对话页面                              │
│   workspace/agents/ai-report--weekly/chats/{thread_id}         │
│                                                                │
│   GenUI 区域：                                                  │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ Round 1: 周报参数表单（form / weekly-report-scope）   │   │
│   │  周开始日期 / 设备类型 / 对比基准                      │   │
│   └──────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ Round 1.5: 设备多选（form / weekly-report-equipment） │   │
│   │  按区域分组、可搜索、默认全选                          │   │
│   └──────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ Round 2: KPI 多选（form / weekly-report-confirm）     │   │
│   │  动态来自 list_equipment.available_kpis               │   │
│   └──────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ Round 3: 周报内容（多 GenUI Block 组合）              │   │
│   │  card: 周 KPI 卡片（含周环比 delta）                  │   │
│   │  echart: 7 日趋势曲线                                  │   │
│   │  table: 异常 TopN（按设备/级别聚合）                  │   │
│   │  table: 告警事件流水                                   │   │
│   │  markdown: 周复盘 + 下周关注                           │   │
│   │  下载链接（artifact URL）                              │   │
│   └──────────────────────────────────────────────────────┘   │
└────────────────────┬───────────────────────────────────────────┘
                     │ LangGraph SSE（DeerFlowClient 流水线）
┌────────────────────┼───────────────────────────────────────────┐
│                    ▼   Backend                                  │
│                                                                │
│   Agent: ai-report--weekly                                     │
│   SOUL.md 驱动 LLM 按以下步骤工作：                            │
│     1. 渲染 Round 1 表单并停止                                 │
│     2. 收到 scope 回调 → 校验 → list_equipment → Round 1.5     │
│     3. 收到 equipment 回调 → 校验 → list_equipment → Round 2   │
│     4. 收到 confirm 回调 → query_weekly + weekly_kpi → 渲染    │
│     5. 调用 export_report 写 md / pdf → present_files          │
│                                                                │
│   skill: data-analyst                                          │
│   scripts/                                                     │
│     ├ list_equipment.py     # 已存在,直接复用                  │
│     ├ query_daily.py        # 已存在,周报不调用                │
│     ├ daily_kpi.py          # 已存在,周报不调用                │
│     ├ export_report.py      # 已存在,扩展 render_weekly_md     │
│     ├ query_weekly.py       # 新增:7 天聚合数据查询            │
│     └ weekly_kpi.py         # 新增:周 KPI / 日趋势 / TopN      │
└────────────────────────────────────────────────────────────────┘
```

**关键原则**：

- 所有逻辑都在 SOUL.md（prompt 驱动）+ 2 个新增 skill 脚本中，**不新增后端 Python 代码、不新增路由、不新增前端 GenUI 组件**。
- 完全复用 LangGraph SSE 流水线、`DeerFlowClient` 调用约定、`genui_middleware` 的 `(thread_id, callback_id)` 复合 key 机制（见 [genui_middleware.py](../../backend/packages/harness/deerflow/middleware/genui_middleware.py)）。
- 复用现有 artifact 路由（`/api/threads/{thread_id}/artifacts/...`，见 [uploads.py](../../backend/app/gateway/routers/uploads.py)）暴露下载链接。

---

## 3. SOUL.md 改造

> **ui_interaction 回传字段约定**：当用户提交 `render_ui` 表单后，LLM 收到的消息结构为 `{type: "ui_interaction", callback_id, payload}`，表单字段值在 `payload` 顶层（非 `values`）。同一线程可能多次生成周报，**回溯 `ui_interaction` 历史时只能使用当前消息之前最近一次匹配的回调消息**，绝不能复用更早轮次参数。

### 3.1 GenUI 组件契约（与已注册 Block 对齐）

- `form`：`submit_label`、`default_values`（snake_case，顶层）；导出表单字段固定为 `format`（仅 `md`，PDF 由 SOUL 内部按 weasyprint 可用性自动尝试）。
- `card`：单值卡片，`title` + `value` + 可选 `subtitle` / `trend: {direction, value}` / `icon` / `color`。**每个 KPI 一个 card Block**，禁止把多个 KPI 塞进 `items`。`trend.value` 用于显示周环比百分比（如 `+3.2%`）。
- `echart`：`option` 必须是完整 ECharts option（含 `xAxis`/`yAxis`/`series`），由 `weekly_kpi.py` 直接产出 `daily_trend_chart` 字段。
- `table`：行数据用 `data`（不是 `rows`），列定义用 `columns: [{key, label}]`。周报使用两张表：`anomaly_top_n`（聚合）与 `alarm_table`（流水）。
- `markdown`：`content` 字符串，承载周复盘与下周关注重点。

### 3.2 数据流与脚本契约（4 轮交互）

#### Round 1：渲染周报参数表单

当用户进入或要求生成周报但当前消息不是 `ui_interaction`、或缺少参数时，调用 `render_ui` 创建：

```json
{
  "component": "form",
  "action": "create",
  "interactive": true,
  "callback_id": "weekly-report-scope",
  "callback_timeout_ms": 600000,
  "props": {
    "title": "生成设备运行周报",
    "description": "请选择周报参数。下一步将选择具体设备和 KPI 指标。",
    "fields": [
      {
        "name": "week_start",
        "label": "周开始日期（建议选择周一）",
        "type": "date",
        "required": true
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
        "label": "对比基准",
        "type": "select",
        "required": true,
        "options": [
          {"label": "上一周", "value": "previous_week"},
          {"label": "去年同期", "value": "previous_year"},
          {"label": "不对比", "value": "none"}
        ]
      }
    ],
    "default_values": {
      "equipment_type": "all",
      "compare_with": "previous_week"
    },
    "submit_label": "下一步"
  }
}
```

渲染后只回复一句"请填写周报参数后提交。"并立即停止。**严禁在此轮渲染 Round 1.5 或 Round 2 表单**。

#### Round 1.5：周报参数回调 → 查询设备 → 渲染设备多选表单

收到 `callback_id == weekly-report-scope` 时：

1. 从 `payload` 读取 `week_start` / `equipment_type` / `compare_with`。
2. 执行 §3.3 输入校验。
3. 调用 `list_equipment.py`（与日报一致）：

   ```bash
   python /mnt/skills/custom/data-analyst/scripts/list_equipment.py \
     --type "{validated.equipment_type}" \
     --scope all \
     --limit 10000
   ```

4. 把脚本返回的 `equipment` 列表按 `area` 分组生成 `multi-select` `options`，渲染 `callback_id: weekly-report-equipment` 表单，默认全选。停止等待提交。

#### Round 2：设备选择回调 → 查询 KPI → 渲染 KPI 多选表单

收到 `callback_id == weekly-report-equipment` 时：

1. 从 `payload` 读取 `equipment_ids: string[]`，校验非空且每个 ID 符合 `[A-Za-z0-9_-]+`。
2. 回溯历史最近一次 `weekly-report-scope` 回调，取出 Round 1 参数。
3. 调用 `list_equipment.py --limit 1` 取 `available_kpis`。
4. 渲染 `callback_id: weekly-report-confirm` KPI 多选表单，每个 KPI 生成 `kpi_{key}` checkbox。停止等待提交。

#### Round 3：KPI 确认回调 → 生成周报 + 自动导出

收到 `callback_id == weekly-report-confirm` 时：

1. 收集所有 `kpi_*` 为 `true` 的字段，去前缀组装 `kpi_keys`。如果为空，渲染 markdown 提示"请至少选择一个 KPI 指标"并停止。
2. 回溯历史 `weekly-report-scope` 与 `weekly-report-equipment` 最近一次回调，取出 `week_start` / `equipment_type` / `compare_with` / `equipment_ids`。
3. 调用周数据查询脚本（按设备数选择 `--equipment` 或 `--type/--scope` 模式，与日报同策略）：

   ```bash
   python /mnt/skills/custom/data-analyst/scripts/query_weekly.py \
     --week-start "{validated.week_start}" \
     --type "{validated.equipment_type}" \
     --equipment "{csv_equipment_ids}" \
     --kpis "{validated.kpi_keys}" \
     --compare "{validated.compare_with}"
   ```

4. 调用周 KPI 计算脚本：

   ```bash
   python /mnt/skills/custom/data-analyst/scripts/weekly_kpi.py \
     --input /mnt/user-data/outputs/weekly_data.json \
     --output /mnt/user-data/outputs/weekly_kpi.json
   ```

5. 读取 `weekly_kpi.json`，渲染多个 `card` / 1 个 `echart` / 2 个 `table` / 1 个 `markdown` Block。
6. 调用 `export_report.py`（复用日报模块）自动写出 `weekly_report.md` 与 `weekly_report.pdf`：

   ```python
   import json, sys
   sys.path.insert(0, "/mnt/skills/custom/data-analyst/scripts")
   from export_report import render_weekly_markdown, write_report

   with open("/mnt/user-data/outputs/weekly_kpi.json", "r", encoding="utf-8") as f:
       payload = json.load(f)

   report_md = render_weekly_markdown(payload, thread_id="{thread_id}")
   write_report(payload, "md", report_type="weekly")
   try:
       write_report(payload, "pdf", report_type="weekly")
       pdf_available = True
   except ImportError:
       pdf_available = False
   ```

7. 调用 `present_files(["/mnt/user-data/outputs/weekly_report.md", ...])`。**严禁对 `weekly_data.json` 或 `weekly_kpi.json` 调用 `present_files`**。

### 3.3 输入安全要求（MUST）

所有 shell 拼接前必须先校验 `payload`：

| 字段 | 校验规则 |
|------|----------|
| `week_start` | 正则 `^\d{4}-\d{2}-\d{2}$`，并解析为合法日期；建议但不强制周一 |
| `equipment_type` | 枚举：`all` / `static_equipment` / `rotating_machinery` / `pump` / `reciprocating_machinery` |
| `compare_with` | 枚举：`previous_week` / `previous_year` / `none` |
| `equipment_ids[i]` | 正则 `^[A-Za-z0-9_-]+$`，最长 64 字符 |
| `kpi_keys[i]` | 正则 `^[a-z_]+$`，必须在 `list_equipment.available_kpis` 返回集合内 |

任一校验失败时渲染 `markdown` 提示并停止，**禁止直接执行脚本**。命令行参数必须用双引号包裹，**禁止传入原始 `payload` 字符串**。

### 3.4 数据源优先级

1. MCP `data_catalog.*`：如未来注册可用，优先使用。
2. Skill 脚本 `query_weekly.py`：当前 MVP 主路径。
3. `http_connector`：真实数据接口落地后启用。
4. `query_weekly.py` 演示数据回退：必须明确告知用户当前为演示数据，不可包装为真实生产数据。

当 MCP 或真实接口返回错误、超时或未配置时，必须在 Markdown 中明确说明已使用演示数据回退。

### 3.5 callback_id 约定

| callback_id | 阶段 | 用途 |
|-------------|------|------|
| `weekly-report-scope` | Round 1 → 1.5 | 周报参数（周开始日期、设备类型、对比基准） |
| `weekly-report-equipment` | Round 1.5 → 2 | 设备多选 |
| `weekly-report-confirm` | Round 2 → 3 | KPI 多选，触发生成 |
| `weekly-report-export` | Round 3 内（保留） | 手动重新导出（MVP 因 Round 3 自动导出，本回调保留备用） |

所有 callback_id 都以 `weekly-report-` 前缀，避免与日报（`daily-report-*`）混淆，符合 `(thread_id, callback_id)` 复合 key 隔离约定。

---

## 4. Skill 脚本设计

新增脚本目录：[skills/custom/data-analyst/scripts/](../../skills/custom/data-analyst/scripts/)。脚本均放在已存在的 `data-analyst` skill 下，符合 [config.yaml](../../agents/builtin/ai-report--weekly/config.yaml) 中声明的 `skills: [data-analyst]`。

### 4.1 query_weekly.py（7 天数据查询）

**职责**：按周报参数生成 `weekly_data.json`，无真实数据 API 时返回稳定演示数据，确保端到端链路可运行。

**命令行参数**：

```bash
python /mnt/skills/custom/data-analyst/scripts/query_weekly.py \
  --week-start 2026-05-11 \
  --type rotating_machinery \
  --equipment "RM-001,RM-002" \
  --scope all \
  --scope-filter "" \
  --kpis "runtime_rate,downtime_count,alarm_count,vibration,energy" \
  --compare previous_week \
  --aggregate
```

**输入校验**（脚本内层校验，作为 SOUL 校验的纵深防御）：

- `--week-start` 必须匹配 `^\d{4}-\d{2}-\d{2}$`，并能由 `datetime.fromisoformat` 解析。如果不是周一，脚本仍以该日期为起点取 7 天窗口，但在输出中加入 `week_start_warning: "未对齐自然周一"`。
- `--type` / `--compare` 校验同 SOUL §3.3。
- `--equipment` 用逗号分隔，每项 `^[A-Za-z0-9_-]+$`。
- `--kpis` 用逗号分隔，每项必须在内置允许集合中。

**输出位置**：`/mnt/user-data/outputs/weekly_data.json`。

**输出 schema 关键字段**：

- `report_period: {week_start, week_end, day_count}`
- `equipment_ids` / `kpi_keys`
- `compare_type` / `compare_period: {start, end} | null`
- `current.daily`: 7 日序列，每日是与 `query_daily.current` 同构的对象（`kpis` 日聚合值、`kpi_units`、`alarms`）
- `current.aggregated`: 7 日聚合后的 `kpis_mean` / `kpis_max` / `kpis_min` / `kpis_std`
- `current.alarms`: 7 天全量告警事件流水
- `compare`：与 `current` 同结构或 `null`

### 4.2 weekly_kpi.py（周 KPI 与图表生成）

**职责**：读取 `weekly_data.json`，生成可直接渲染的周 KPI、日趋势图、异常 TopN、告警流水、下周关注重点。

**命令行参数**：

```bash
python /mnt/skills/custom/data-analyst/scripts/weekly_kpi.py \
  --input /mnt/user-data/outputs/weekly_data.json \
  --output /mnt/user-data/outputs/weekly_kpi.json
```

**输出位置**：`/mnt/user-data/outputs/weekly_kpi.json`。

**输出 schema 关键字段**：

- `report_period: {week_start, week_end}` / `compare_type` / `compare_period`
- `overall_status: {level: "good"|"warning"|"critical", summary: "..."}`
- `kpi_summary[]`：每个 KPI 一项，字段：`key` / `name` / `unit` / `current_mean` / `current_peak` / `current_trough` / `current_volatility`（标准差/均值） / `previous_mean` / `delta_mean`（周环比绝对差） / `delta_pct`（周环比百分比） / `direction: up|down|flat` / `better_when_higher: bool`
- `daily_trend_chart`：完整 ECharts option（含 7 日 x 轴、多 KPI series、`legend.selected` 控制默认显示主 KPI）
- `anomaly_top_n[]`：聚合表，列 `equipment` / `level` / `count` / `latest_time` / `dominant_message`，按 `count` desc 取 Top10
- `alarm_table[]`：告警事件流水，列 `time` / `equipment` / `level` / `message`（按日报告警 schema 兼容）
- `next_week_focus[]`：字符串数组，下周关注重点（来自异常 TopN 设备 + 持续下行 KPI 设备）

**计算口径说明**：

- 周均值 = 7 日 daily KPI 简单算术平均；
- 周峰值/低谷 = 7 日 daily KPI 的 max/min；
- 周波动率 = std / mean（mean 为 0 时输出 `null`）；
- 周环比 delta_pct = `(current_mean - previous_mean) / previous_mean`（previous_mean 为 0 时输出 `null` 并在 SOUL 渲染时显示"—"）。

### 4.3 export_report.py 复用与扩展

**复用策略**：直接复用日报已有的 [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py)，但新增 `render_weekly_markdown(payload, thread_id)` 函数，并在 `write_report(payload, format, report_type="daily")` 上增加 `report_type` 参数（默认 `daily`，向后兼容）。

**关键扩展点**：

- 新增 `render_weekly_markdown(payload, thread_id)`：负责把 `weekly_kpi.json` 渲染成 7 节 Markdown：本周概览 / 周 KPI 表 / 日趋势图描述 / 异常 TopN / 告警流水 / 周环比 / 下周关注。
- `write_report` 内部按 `report_type` 选择文件名：`weekly_report.md` / `weekly_report.pdf`，输出目录仍为 `/mnt/user-data/outputs/`。
- PDF 走与日报一致的 weasyprint 路径；未安装时抛 `ImportError`，由 SOUL 捕获并降级。

**命令行用法**（可选，主路径走 Python 直接 import）：

```bash
python /mnt/skills/custom/data-analyst/scripts/export_report.py \
  --input /mnt/user-data/outputs/weekly_kpi.json \
  --report-type weekly \
  --format md \
  --output /mnt/user-data/outputs/weekly_report.md
```

返回 JSON：

```json
{"format": "md", "filename": "weekly_report.md", "path": "/mnt/user-data/outputs/weekly_report.md", "artifact_path": "/mnt/user-data/outputs/weekly_report.md"}
```

---

## 5. 前端：复用已有 GenUI Block，无需新增

经核查 [frontend/src/core/genui/registry.ts](../../frontend/src/core/genui/registry.ts) 已支持周报全部所需组件：`form` / `card` / `echart` / `table` / `markdown`。

- 周报多 KPI 卡片：渲染多个 `card` Block，每个含 `trend.direction` + `trend.value`（周环比百分比）。
- 日趋势曲线：1 个 `echart`，`option` 来自 `weekly_kpi.daily_trend_chart`，前端不做二次组装。
- 异常 TopN 与告警流水：2 个独立 `table` Block，`columns` 由 SOUL 指定，`data` 来自 KPI JSON。
- 周复盘 + 下周关注：1 个 `markdown` Block，内容由 `render_weekly_markdown` 在后端构造。
- 下载链接：通过 sandbox artifact URL（`/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/weekly_report.md`）实现，已有 [uploads 路由](../../backend/app/gateway/routers/uploads.py) 支持。

**无需新增前端组件，无需修改 GenUI registry，无需新增路由**。

---

## 6. 数据契约

### 6.1 query_weekly.py 输出

```json
{
  "report_period": {
    "week_start": "2026-05-11",
    "week_end": "2026-05-17",
    "day_count": 7
  },
  "equipment_ids": ["RM-001", "RM-002"],
  "kpi_keys": ["runtime_rate", "downtime_count", "alarm_count", "vibration"],
  "compare_type": "previous_week",
  "compare_period": {"start": "2026-05-04", "end": "2026-05-10"},
  "current": {
    "daily": [
      {
        "date": "2026-05-11",
        "kpis": {"runtime_rate": 92.5, "downtime_count": 2, "alarm_count": 5, "vibration": 3.1},
        "kpi_units": {"runtime_rate": "%", "downtime_count": "次", "alarm_count": "条", "vibration": "mm/s"},
        "alarms": [
          {"time": "2026-05-11 08:15:32", "equipment": "RM-001", "level": "warning", "message": "振动超阈值"}
        ]
      },
      { "date": "2026-05-12", "kpis": {"runtime_rate": 94.1, "downtime_count": 1, "alarm_count": 3, "vibration": 2.9}, "alarms": [] }
    ],
    "aggregated": {
      "kpis_mean": {"runtime_rate": 93.2, "downtime_count": 1.4, "alarm_count": 3.7, "vibration": 3.0},
      "kpis_max":  {"runtime_rate": 96.0, "downtime_count": 3,   "alarm_count": 6,   "vibration": 3.6},
      "kpis_min":  {"runtime_rate": 89.5, "downtime_count": 0,   "alarm_count": 2,   "vibration": 2.5},
      "kpis_std":  {"runtime_rate": 2.1,  "downtime_count": 1.0, "alarm_count": 1.5, "vibration": 0.4}
    },
    "alarms": [
      {"time": "2026-05-11 08:15:32", "equipment": "RM-001", "level": "warning", "message": "振动超阈值"},
      {"time": "2026-05-13 14:02:17", "equipment": "RM-002", "level": "critical", "message": "轴承温度超限"}
    ]
  },
  "compare": {
    "daily": [],
    "aggregated": {
      "kpis_mean": {"runtime_rate": 91.0, "downtime_count": 1.8, "alarm_count": 4.2, "vibration": 3.2}
    },
    "alarms": []
  }
}
```

### 6.2 weekly_kpi.py 输出

```json
{
  "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17"},
  "compare_type": "previous_week",
  "compare_period": {"start": "2026-05-04", "end": "2026-05-10"},
  "overall_status": {
    "level": "warning",
    "summary": "本周运行率 93.2%，较上周提升 2.2 个百分点；RM-002 轴承温度告警 3 次，建议下周重点关注。"
  },
  "kpi_summary": [
    {
      "key": "runtime_rate", "name": "运行率", "unit": "%",
      "current_mean": 93.2, "current_peak": 96.0, "current_trough": 89.5, "current_volatility": 0.022,
      "previous_mean": 91.0, "delta_mean": 2.2, "delta_pct": 0.024,
      "direction": "up", "better_when_higher": true
    },
    {
      "key": "downtime_count", "name": "停机次数", "unit": "次",
      "current_mean": 1.4, "current_peak": 3, "current_trough": 0, "current_volatility": 0.71,
      "previous_mean": 1.8, "delta_mean": -0.4, "delta_pct": -0.22,
      "direction": "down", "better_when_higher": false
    }
  ],
  "daily_trend_chart": {
    "title": {"text": "本周日趋势"},
    "tooltip": {"trigger": "axis"},
    "legend": {"data": ["运行率", "告警数"], "selected": {"运行率": true, "告警数": true}},
    "xAxis": {"type": "category", "data": ["05-11 周一", "05-12 周二", "05-13 周三", "05-14 周四", "05-15 周五", "05-16 周六", "05-17 周日"]},
    "yAxis": [{"type": "value", "name": "%"}, {"type": "value", "name": "次"}],
    "series": [
      {"name": "运行率", "type": "line", "yAxisIndex": 0, "data": [92.5, 94.1, 93.0, 91.2, 95.3, 96.0, 89.5]},
      {"name": "告警数", "type": "bar",  "yAxisIndex": 1, "data": [5, 3, 6, 4, 2, 3, 3]}
    ]
  },
  "anomaly_top_n": [
    {"equipment": "RM-002", "level": "critical", "count": 3, "latest_time": "2026-05-16 10:22:08", "dominant_message": "轴承温度超限"},
    {"equipment": "RM-001", "level": "warning",  "count": 5, "latest_time": "2026-05-15 22:01:43", "dominant_message": "振动超阈值"}
  ],
  "alarm_table": [
    {"time": "2026-05-11 08:15", "equipment": "RM-001", "level": "warning", "message": "振动超阈值"},
    {"time": "2026-05-13 14:02", "equipment": "RM-002", "level": "critical", "message": "轴承温度超限"}
  ],
  "next_week_focus": [
    "RM-002 轴承温度持续异常，建议安排振动 + 温度联合诊断",
    "周日运行率跌至 89.5%，复查值班排班与启停记录",
    "整周告警数较上周下降 12%，保持当前预防性维护节奏"
  ]
}
```

> **字段口径说明**：`alarm_table` 与日报 `alarm_table` schema 完全一致，便于前端 `table` 组件复用同一 `columns` 配置；`anomaly_top_n` 是周报特有的聚合表；`daily_trend_chart` 替代日报的 `trend_chart`（日报为 24 小时维度，周报为 7 日维度）。

---

## 7. 与自定义模板平台 DSL 的兼容性

本设计与 [AI 报告自定义模板功能设计文档](./2026-05-14-ai-report-custom-template-design.md) §13.3 的周报 DSL 草案完全兼容，原则如下：

1. **脚本契约统一**：本设计的 `query_weekly.py` 与 `weekly_kpi.py` 同时是原生 `ai-report--weekly` SOUL.md 的直接调用对象，也是未来 `weekly-equipment` DSL builtin 模板在 `report_scripts.yaml` 注册的 entry。脚本 CLI 参数与输出 schema 是 contract，不会随调用方变化。
2. **DSL `form_steps` 字段名一致**：DSL 草案使用的 `week_start` / `equipment_type` / `compare_with` / `equipment_ids` / `kpi_keys` 字段命名与本设计 SOUL.md 完全一致，意味着同一组校验规则、同一组脚本参数。
3. **输出 schema 可被 DSL `sections.source` 引用**：`weekly_kpi.json` 的顶层字段（`overall_status` / `kpi_summary` / `daily_trend_chart` / `anomaly_top_n` / `alarm_table` / `next_week_focus`）都是合法的 dotted-path 起点，DSL 可直接通过 `source: weekly_kpi.kpi_summary` 渲染章节，无需中间适配器。
4. **双路径并行**：原生 `ai-report--weekly` 走 SOUL.md，未来 `weekly-equipment` DSL 模板走自定义模板平台模板运行时，二者最终输出结构一致；用户可在管理端基于 DSL 复制周报并自定义章节，而内置的 `ai-report--weekly` 保留作为 fallback。
5. **未来迁移路径**：当 DSL 平台稳定后，`ai-report--weekly` 可选择性重写为 `weekly-equipment` DSL builtin 模板（参见自定义模板设计 §11.4 fallback 双轨策略），SOUL.md 作为兜底保留，脚本零改动。

---

## 8. 实施计划引用

本设计仅完成"能力蓝图"，具体 Story 拆分、依赖关系、Sprint 排期、验收标准请独立编写 `2026-05-18-ai-report-weekly-sprint-plan.md`，建议拆分为以下 Story 雏形（不在本设计中展开）：

- Story W1：`query_weekly.py` 演示数据版（含输入校验与单元测试）
- Story W2：`weekly_kpi.py` 周 KPI 与 ECharts option 生成
- Story W3：`export_report.py` 扩展 `render_weekly_markdown` + `report_type` 参数（保持日报向后兼容）
- Story W4：SOUL.md 4 轮表单实现 + 输入校验 + present_files 闭环
- Story W5：端到端联调（含 weasyprint 不可用降级、设备 > 10 跨区域聚合）
- Story W6：与 DSL 平台脚本注册联调（依赖 [自定义模板 Phase 3](./2026-05-14-ai-report-custom-template-design.md)）

---

## 9. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 时区与自然周边界定义不统一 | 周一/周日起点歧义、跨日数据错位 | 统一约定：`week_start` 由用户指定具体日期（不强制周一），脚本以该日期为锚取 7 天窗口；输出 `report_period.week_start/week_end` 明确范围；未来支持 `--tz` 参数 |
| 周开始日期选择体验 | 用户可能选到周中导致语义偏差 | Round 1 表单 `label` 加 "建议选择周一" 提示；脚本在非周一时输出 `week_start_warning` 字段，SOUL 在概览中明示"自定义 7 日窗口（非自然周）" |
| 数据量（7 天 × N 设备 × M KPI） | 单次脚本执行内存/时间放大 | `query_weekly.py` 内部按 daily 切片串行拉取，避免单次大 join；设备 > 50 时自动启用 `--aggregate` 仅返回聚合值，不下钻每台设备日序列；`anomaly_top_n` 限制 Top10 |
| 同期对比缺失（去年同期数据可能不存在） | `compare=previous_year` 时报错或显示空 | `query_weekly.py` 检测到同期数据为空时返回 `compare: null` 并附带 `compare_warning`；`weekly_kpi.py` 在 `kpi_summary` 的 `previous_mean` 输出 `null`；SOUL 渲染 `card.trend` 时显示 `—` 而非 `+NaN%` |
| KPI 口径与日报一致性 | 用户在日报/周报切换时质疑数据矛盾 | 周均值定义为"7 日 daily KPI 简单平均"，且 `weekly_kpi.json.kpi_summary[i]` 显式输出 `unit` 与单位口径；在 Markdown 中加入"口径说明"小节，引用日报口径一致性 |
| weekly_kpi 与 daily_kpi 计算口径差异 | 用户混淆"周告警数" vs "日告警数" | `kpi_summary` 字段命名统一加前缀语义：`current_mean` / `current_peak` / `current_trough` / `current_volatility`，避免与日报 `current` 单值混淆；Markdown 渲染时显式标注"周均值" / "周峰值" |
| 演示数据回退被误认为真实数据 | 决策风险 | 脚本演示数据在输出 JSON 中标 `data_source: "demo_fallback"`；SOUL 在概览开头插入"当前为演示数据"banner（红色 markdown 引用块） |
| weasyprint 不可用导致 PDF 缺失 | 用户预期落空 | 与日报相同：SOUL try/except 捕获 `ImportError`，降级为仅 Markdown 下载；下载区显式列出"PDF 不可用（weasyprint 未安装）" |

---

## 10. 与现有架构对齐检查

| 项 | 现有模式（日报） | 本设计（周报） | 状态 |
|----|------------------|----------------|------|
| Agent 配置位置 | `agents/builtin/ai-report--daily/` | 复用现有 `agents/builtin/ai-report--weekly/`，仅改 SOUL.md | OK |
| Skill 脚本位置 | `skills/custom/data-analyst/scripts/` | 同（新增 2 个脚本，复用 list_equipment.py 与 export_report.py） | OK |
| 数据源发现 | MCP → skill 脚本 → http_connector → 演示数据 | 同优先级链 | OK |
| 交互方式 | render_ui form + ui_interaction，3 轮表单 | render_ui form + ui_interaction，4 轮表单（结构同构） | OK |
| 渲染组件 | GenUI registry：card/echart/table/markdown/form | 同（不新增组件，仅多渲染一个 table 用于 TopN） | OK |
| 文件下载 | sandbox `/mnt/user-data/outputs` + artifact URL | 同（`weekly_report.md` / `weekly_report.pdf`） | OK |
| LLM 流水线 | DeerFlowClient 标准流程 + LangGraph SSE | 同（不改动 runtime） | OK |
| 后端改动 | 零后端代码改动 | 零后端代码改动 | OK |
| 前端改动 | 零前端代码改动 | 零前端代码改动 | OK |

**全部由 SOUL.md + Skill 脚本实现**，不引入新的 Python 后端代码、不新增路由、不新增前端组件。这与日报智能体架构完全一致，符合 DeerFlow agent 体系"prompt 工程 + skill 脚本最大化扩展能力"的设计意图，并为未来迁移到 `weekly-equipment` DSL builtin 模板保留无缝路径。

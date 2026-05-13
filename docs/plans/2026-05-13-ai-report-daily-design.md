# AI 日报智能体功能设计文档

> **范围**：完整功能设计，覆盖 SOUL.md 优化、数据接入、Skill 脚本、GenUI 渲染、Markdown/PDF 导出。
> **遵循模式**：复用 `monitoring-analysis` 已有的"动态数据源发现 → render_ui 表单 → 数据获取 → 结构化输出"模式，与项目现有 agent 架构一致。

---

## 1. 现状与目标

### 1.1 现状

[ai-report--daily/config.yaml](../../agents/builtin/ai-report--daily/config.yaml) 已定义：
- `parent: ai-report`、`order: 1`、`skills: [data-analyst]`
- SOUL.md 仅描述报告结构，缺少：
  - 数据源发现流程
  - 与用户的交互式参数确认（日期、设备范围、KPI 选择）
  - 具体的 GenUI 渲染指令
  - 导出能力

### 1.2 目标

| 能力 | 描述 |
|------|------|
| 交互式参数收集 | 用户进入后，通过 `render_ui form` 选择日期、设备/产线、关注 KPI |
| 自动数据采集 | 按优先级链获取当日运行数据（MCP → Skill 脚本 → http_connector） |
| 结构化输出 | echart 趋势图 + table 异常事件 + card KPI + markdown 总结 |
| 导出 | MVP 仅支持 Markdown 下载；PDF 已延后到 Story 6 待依赖验证 |
| 同期对比 | 自动拉取前一日同时段数据并标注变化 |

### 1.3 与 monitoring-analysis 的区别

| 维度 | monitoring-analysis | ai-report--daily |
|------|---------------------|------------------|
| 用途 | 探索式数据分析 | 固定结构的日报 |
| 输出 | 用户选定的图表/表格 | 标准化报告（概览/KPI/异常/趋势/建议）|
| 时间范围 | 用户指定 | 默认当日，可选历史日期 |
| 交互 | 多轮探索 | 一次配置 → 一次生成 |

---

## 2. 系统架构

**入口流程**：用户从 `ai-report`（`type: group`）的子 agent 列表中进入 `ai-report--daily`，与现有 group/sub-agent 路由完全一致，父 group 的 `config.yaml` 不显式声明子 agent，依赖目录扫描发现。

```
┌────────────────────────────────────────────────────────────────┐
│                       前端对话页面                              │
│   workspace/agents/ai-report--daily/chats/{thread_id}          │
│                                                                │
│   GenUI 区域：                                                  │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ Step 1: 报告参数表单（render_ui form）                │   │
│   │  日期 / 设备范围 / KPI 选择                           │   │
│   └──────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ Step 2: 日报内容（多 GenUI Block 组合）              │   │
│   │  card: KPI 卡片                                       │   │
│   │  echart: 24h 运行趋势                                 │   │
│   │  table: 异常事件清单                                  │   │
│   │  markdown: 总结/建议                                  │   │
│   │  [导出 Markdown] 按钮（form action）                   │   │
│   └──────────────────────────────────────────────────────┘   │
└────────────────────┬───────────────────────────────────────────┘
                     │ LangGraph SSE
┌────────────────────┼───────────────────────────────────────────┐
│                    ▼   Backend (DeerFlowClient 流水线)          │
│                                                                │
│   Agent: ai-report--daily                                      │
│   SOUL.md 驱动 LLM 按以下步骤工作：                            │
│     1. 数据源发现（优先级链）                                  │
│     2. render_ui 表单 → 等待 ui_interaction                    │
│     3. 数据拉取（按用户选择）                                  │
│     4. 同期数据拉取                                            │
│     5. 计算 KPI 与异常                                         │
│     6. render_ui 系列 Block 输出                               │
│     7. 提供导出按钮                                            │
│                                                                │
│   skill: data-analyst                                          │
│   scripts/                                                     │
│     ├ list_datasets.py        # 已存在                        │
│     ├ query_daily.py          # 新增：当日运行数据查询        │
│     ├ daily_kpi.py            # 新增：KPI 计算                │
│     └ export_report.py        # 新增：Markdown 导出（PDF 延后） │
└────────────────────────────────────────────────────────────────┘
```

**关键原则**：所有逻辑都在 SOUL.md（prompt 驱动）+ skill 脚本（确定性计算）中，**不新增后端 Python 代码、不新增路由**。这与项目现有 agent 模式完全一致。

---

## 3. SOUL.md 改造

> **ui_interaction 回传字段约定**：当用户提交 `render_ui` 表单后，LLM 收到的消息结构为 `{type: "ui_interaction", callback_id, payload}`，表单字段值在 `payload` 顶层（非 `values`），见 [genui_middleware.py](../../backend/packages/harness/deerflow/middleware/genui_middleware.py) 与 [FormBlock.tsx](../../frontend/src/components/genui/FormBlock.tsx)。

> **正式实现以 [agents/builtin/ai-report--daily/SOUL.md](../../agents/builtin/ai-report--daily/SOUL.md) 为准**。本节早期草案曾包含完整 SOUL 全文，为避免文档与实现双维护漂移，已替换为下述关键契约摘要；任何字段/参数变更请直接修改实际 SOUL 文件。

### 3.1 GenUI 组件契约（与已注册 Block 对齐）

- `form`：使用 `submit_label`、`default_values`（snake_case，顶层）；字段不要使用 `defaultValue`；MVP 表单字段固定为 `report_date` / `equipment_scope_csv` / `kpis_csv` / `compare_with`，导出表单字段为 `format`（仅 `md`）。
- `card`：单值卡片，`title`（必填字符串）+ `value`（必填字符串或数字），可选 `subtitle`、`trend: {direction: "up"|"down"|"flat", value: string}`、`icon`、`color`。不支持 `items[{label,value}]` 或 `summary`，多个 KPI 必须渲染为多个 `card` Block。
- `echart`：`option` 必须是完整 ECharts option（含 `xAxis`/`yAxis`/`series` 等），由 `daily_kpi.py` 直接产出。
- `table`：行数据必须用 `data`（不是 `rows`），列定义用 `columns: [{key, label}]`。
- `markdown`：`content` 字符串。

### 3.2 数据流与脚本契约

1. 首次进入或缺少参数 → 渲染参数 `form` 后停止。
2. 收到 `daily-report-params` 回调 → 先白名单校验 `payload`（日期正则、设备/KPI 字符集、对比枚举），再调用 `query_daily.py` 写入 `/mnt/user-data/outputs/daily_data.json`。
3. 调用 `daily_kpi.py` 读 `daily_data.json`，写出 `daily_kpi.json`，渲染 `card`/`echart`/`table`/`markdown`，最后渲染导出 `form`。
4. 收到 `daily-report-export` 回调 → 仅当 `payload.format == "md"` 时调用 `export_report.py`，渲染 `markdown` 给出 artifact 下载链接 `/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/daily_report.md`。

### 3.3 输入安全要求（MUST）

- 所有 shell 拼接前必须先校验 `payload` 字段；校验失败时渲染 `markdown` 提示用户重新提交，禁止直接执行脚本。
- 命令行只允许传入校验后的值，并使用双引号包裹；禁止传入原始 `payload` 字符串。

### 3.4 数据源优先级

1. MCP `data_catalog.*`（暂未注册，未来可用时自动接入）。
2. Skill 脚本 `query_daily.py`（当前 MVP 主路径）。
3. `http_connector`（待真实数据接口落地后启用）。
4. `query_daily.py` 的演示数据回退（必须明确告知用户当前为演示数据）。

---

## 4. Skill 脚本设计

新增脚本目录：`skills/custom/data-analyst/scripts/`。正式实现以脚本源码和测试为准，本节记录稳定契约。

### 4.1 query_daily.py（数据查询）

职责：按日报参数生成 `daily_data.json`，无真实数据 API 时返回稳定演示数据，确保端到端链路可运行。

```bash
python /mnt/skills/custom/data-analyst/scripts/query_daily.py   --date YYYY-MM-DD   --equipment "E001,E002"   --kpis "runtime_rate,downtime_count,alarm_count"   --compare previous_day|previous_week|none
```

输出位置：`/mnt/user-data/outputs/daily_data.json`。

关键字段：

- `report_date` / `equipment_ids` / `kpi_keys`
- `compare_type` / `compare_date`
- `current.kpis` / `current.kpi_units` / `current.hourly_runtime_rate` / `current.alarms`
- `compare`：同 `current` 结构，或 `null`

异常事件只存在于 `current.alarms` 与 `compare.alarms`，不再输出顶层 `alarms`。

### 4.2 daily_kpi.py（KPI 计算与图表生成）

职责：读取 `daily_data.json`，生成可直接渲染的 KPI、趋势图、告警表格与建议。

```bash
python /mnt/skills/custom/data-analyst/scripts/daily_kpi.py   --input /mnt/user-data/outputs/daily_data.json   --output /mnt/user-data/outputs/daily_kpi.json
```

输出位置：`/mnt/user-data/outputs/daily_kpi.json`。

关键字段：

- `overall_status`: `{level, summary}`
- `kpi_summary`: `[{key, name, current, previous, delta, unit, direction, better_when_higher}]`
- `trend_chart`: 完整 ECharts option，可直接传给 `echart` 的 `props.option`
- `alarm_table`: `[{time, equipment, level, message}]`，用于 `table` 的 `props.data`
- `recommendations`: 字符串数组

不输出顶层 `alarm_count`；需要计数时由 `len(alarm_table)` 派生。

### 4.3 export_report.py（Markdown 导出）

职责：读取 `daily_kpi.json`，写出 Markdown artifact。当前 MVP 仅支持 `md`，PDF 导出已延后到 Story 6 依赖验证。

```bash
python /mnt/skills/custom/data-analyst/scripts/export_report.py   --input /mnt/user-data/outputs/daily_kpi.json   --format md   --output /mnt/user-data/outputs/daily_report.md
```

输出位置：`/mnt/user-data/outputs/daily_report.md`。

返回 JSON：

```json
{"format": "md", "filename": "daily_report.md", "path": "/mnt/user-data/outputs/daily_report.md", "artifact_path": "/mnt/user-data/outputs/daily_report.md"}
```

不支持格式会返回 JSON error，不应生成假链接。

---

## 5. 前端：复用已有 GenUI Block，无需新增

经核查 [frontend/src/core/genui/registry.ts](../../frontend/src/core/genui/registry.ts) 已支持：
- `card` / `echart` / `table` / `markdown` / `form`

**无需新增前端组件**。下载链接通过 sandbox artifact URL 实现，已有 [uploads 路由](../../backend/app/gateway/routers/uploads.py) 支持文件读取。

---

## 6. 数据契约

### 6.1 query_daily.py 输出

```json
{
  "report_date": "2026-05-13",
  "equipment_ids": ["E001", "E002"],
  "current": {
    "kpis": {
      "runtime_rate": 92.5,
      "downtime_count": 2,
      "alarm_count": 5,
      "output": 1280,
      "oee": 85.3,
      "energy": 1520
    },
    "kpi_units": {
      "runtime_rate": "%", "downtime_count": "次", "alarm_count": "次",
      "output": "件", "oee": "%", "energy": "kWh"
    },
    "hourly_runtime_rate": [95, 96, 94, ..., 92],
    "alarms": [
      {
        "time": "2026-05-13 08:15:32",
        "equipment": "E001",
        "level": "warning",
        "message": "振动超阈值"
      }
    ]
  },
  "compare": { "...同 current 结构..." },
  "compare_type": "previous_day",
  "compare_date": "2026-05-12"
}
```

### 6.2 daily_kpi.py 输出

```json
{
  "report_date": "2026-05-13",
  "compare_type": "previous_day",
  "compare_date": "2026-05-12",
  "overall_status": {"level": "warning", "summary": "..."},
  "kpi_summary": [
    {"key": "runtime_rate", "name": "运行率", "current": 0.925, "previous": 0.942,
     "delta": -0.017, "direction": "down", "unit": "%", "better_when_higher": true}
  ],
  "trend_chart": { "...完整 ECharts option（title/tooltip/legend/xAxis/yAxis/series）..." },
  "alarm_table": [
    {"time": "2026-05-13 08:00", "equipment": "E001", "level": "warning", "message": "振动超阈值"}
  ],
  "recommendations": ["..."]
}
```

> **字段口径说明**：`alarms` 仅出现在 `query_daily.py` 的 `current.alarms` / `compare.alarms` 中；`daily_kpi.py` 输出统一改名为 `alarm_table`，前端 `table` 组件以 `props.data` 接收。设计文档早期版本中提到的顶层 `alarms` / `alarm_count` 字段已废弃。

---

## 7. 实施计划引用

具体实施排期、Story 拆分、依赖、验收标准与 Sprint Sequencing 见独立文档：[AI 日报智能体 Sprint 实施计划](./2026-05-13-ai-report-daily-sprint-plan.md)。

---

## 8. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 数据 API 未定 | Phase 2 阻塞 | Phase 1 演示数据先跑通端到端，并行确认 API |
| sandbox 缺 pandoc/wkhtmltopdf | PDF 导出失败 | `md2pdf` 纯 Python 库回退；首选确认 sandbox 镜像 |
| KPI 定义不统一 | 数据口径混乱 | KPI 元数据（名称/单位/计算公式）集中在 daily_kpi.py |
| 多设备数据量大 | 表单/图表卡顿 | 设备数 > 20 时聚合显示，详情走"设备明细"二级页 |
| 时区问题 | 跨日数据错位 | 全链路使用 UTC + 用户显示本地时区，脚本接受 `--tz` 参数（Phase 4） |

---

## 9. 与现有架构对齐检查

| 项 | 现有模式 | 本设计 | 状态 |
|----|----------|--------|------|
| Agent 配置位置 | `agents/builtin/<name>/` | 复用现有 `ai-report--daily/` | ✅ |
| Skill 脚本位置 | `skills/custom/data-analyst/scripts/` | 同 | ✅ |
| 数据源发现 | monitoring-analysis 优先级链 | 同 | ✅ |
| 交互方式 | render_ui form + ui_interaction | 同 | ✅ |
| 渲染组件 | GenUI registry（card/echart/table/markdown/form）| 同（不新增组件） | ✅ |
| 文件下载 | sandbox `/mnt/user-data/outputs` + artifact URL | 同 | ✅ |
| LLM 流水线 | DeerFlowClient 标准流程 | 同（不改动 runtime） | ✅ |
| 后端改动 | — | 零后端代码改动 | ✅ |
| 前端改动 | — | 零前端代码改动 | ✅ |

**全部由 SOUL.md + Skill 脚本实现**，不引入新的 Python 后端代码、不新增路由、不新增前端组件。这是 DeerFlow agent 体系的设计意图：通过 prompt 工程 + skill 脚本最大化扩展能力。

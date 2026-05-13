# AI 日报智能体交互优化设计文档

> **前置文档**：[AI 日报智能体功能设计文档](./2026-05-13-ai-report-daily-design.md)、[Sprint 实施计划](./2026-05-13-ai-report-daily-sprint-plan.md)
> **范围**：在 MVP 已完成的基础上，针对真实设备规模（2200+ 台）优化日报参数表单的交互体验，使其对工业用户可用。
> **约束**：不新增后端路由、不新增前端组件，全部通过 SOUL.md + Skill 脚本实现。

---

## 1. 问题分析

### 1.1 当前表单

MVP 参数表单包含 4 个字段：

| 字段 | 类型 | 现状 |
|------|------|------|
| `report_date` | date | 正常 |
| `equipment_scope_csv` | text（手动输入 CSV） | 面对 2200 台设备完全不可用 |
| `kpis_csv` | text（手动输入 CSV） | 不同设备类型关注的 KPI 完全不同 |
| `compare_with` | select | 正常 |

### 1.2 核心痛点

1. **设备选择不可用**：用户不可能记住 2200 台设备的 ID 并手动输入 CSV。
2. **KPI 与设备类型脱节**：静设备关注腐蚀/壁厚，旋转机组关注振动/轴温，统一 5 个 KPI 不符合实际。
3. **缺少设备分类**：现有脚本不区分设备类型，无法按类型聚合。
4. **大量设备时的聚合策略缺失**：选择 1000 台静设备时不应逐台展示 KPI。

### 1.3 设备分类体系

| 设备类型 | 英文标识 | 数量 | ID 前缀 | 关键 KPI | 典型告警 |
|----------|----------|------|---------|----------|----------|
| 静设备 | `static_equipment` | ~1000 | SE- | 运行率、告警数、腐蚀速率、壁厚减薄 | 泄漏、腐蚀超标、壁厚不足 |
| 旋转机组 | `rotating_machinery` | ~100 | RM- | 运行率、振动水平、轴承温度、停机次数 | 振动超标、轴承过热、不平衡 |
| 机泵 | `pump` | ~1000 | PP- | 运行率、流量、出口压力、能耗 | 气蚀、密封泄漏、效率下降 |
| 往复机组 | `reciprocating_machinery` | ~100 | RC- | 运行率、振动水平、阀温、停机次数 | 阀片损坏、气缸磨损、振动异常 |

---

## 2. 方案概述

### 2.1 核心思路

将单轮表单改为**两轮交互**：

- **Round 1（日报范围配置）**：用户选择日期、设备类型、设备范围（按区域 / 指定设备 / 全部）、对比基准。
- **Agent 中间处理**：调用新增的 `list_equipment.py` 查询匹配设备数量和可用 KPI 列表。
- **Round 2（确认设备与 KPI）**：展示匹配结果，用 checkbox 让用户勾选关注的 KPI。
- **生成日报**：调用已有 `query_daily.py` → `daily_kpi.py` → GenUI 渲染。

### 2.2 交互流程

```
用户进入日报 Agent
        │
        ▼
┌─ Round 1: 日报范围配置 ─────────────────────┐
│                                              │
│  日报日期:     [2026-05-13]       (date)     │
│  设备类型:     [全部▾]            (select)   │
│               全部 / 静设备 / 旋转机组       │
│               机泵 / 往复机组                │
│  设备范围:     [全部▾]            (select)   │
│               全部 / 按区域 / 指定设备       │
│  区域或设备:   [A区,B区 或 SE-001] (text)    │
│  对比基准:     [前一日▾]          (select)   │
│                                              │
│  [下一步]                                    │
└──────────────────────────────────────────────┘
        │
        │ Agent 调用 list_equipment.py 查询匹配设备
        │ 根据设备类型筛选出相关 KPI
        ▼
┌─ Round 2: 确认设备与 KPI ───────────────────┐
│                                              │
│  已匹配: 静设备 · A区 · 238 台              │
│                                              │
│  ☑ 运行率           (checkbox, 默认选中)     │
│  ☑ 停机次数         (checkbox, 默认选中)     │
│  ☑ 告警数量         (checkbox, 默认选中)     │
│  ☐ 腐蚀速率         (checkbox)              │
│  ☐ 壁厚减薄量       (checkbox)              │
│  ☐ 能耗             (checkbox)              │
│                                              │
│  [生成日报]                                  │
└──────────────────────────────────────────────┘
        │
        │ Agent 调用 query_daily.py → daily_kpi.py
        ▼
┌─ 日报渲染 ──────────────────────────────────┐
│  card: 整体状态                              │
│  card×N: 各 KPI 卡片                         │
│  echart: 24h 运行率趋势                      │
│  table: 异常事件                             │
│  markdown: 总结与建议                        │
│  form: 导出                                  │
└──────────────────────────────────────────────┘
```

### 2.3 为什么是两轮而非一轮

GenUI `form` 组件不支持联动字段（如根据"设备类型"动态改变 KPI 选项）。两轮表单让 Agent 有机会在中间执行脚本，根据 Round 1 的选择动态生成 Round 2 的 KPI checkbox 列表。

---

## 3. KPI 扩展体系

### 3.1 设备类型与 KPI 映射

```python
EQUIPMENT_TYPE_KPIS = {
    "all": [
        "runtime_rate", "downtime_count", "alarm_count", "energy_consumption",
    ],
    "static_equipment": [
        "runtime_rate", "alarm_count", "corrosion_rate", "thickness_loss",
        "energy_consumption",
    ],
    "rotating_machinery": [
        "runtime_rate", "vibration_level", "bearing_temp", "downtime_count",
        "energy_consumption",
    ],
    "pump": [
        "runtime_rate", "flow_rate", "outlet_pressure", "energy_consumption",
        "alarm_count",
    ],
    "reciprocating_machinery": [
        "runtime_rate", "vibration_level", "valve_temp", "downtime_count",
        "alarm_count",
    ],
}
```

### 3.2 新增 KPI 定义

在 `query_daily.py` 的 `KPI_UNITS` 中扩展：

| KPI key | 名称 | 单位 | 适用设备 |
|---------|------|------|----------|
| `runtime_rate` | 运行率 | % | 全部 |
| `downtime_count` | 停机次数 | 次 | 旋转机组、往复机组 |
| `alarm_count` | 告警数量 | 条 | 全部 |
| `energy_consumption` | 能耗 | kWh | 全部 |
| `output` | 产量 | 件 | 通用（保留） |
| `corrosion_rate` | 腐蚀速率 | mm/a | 静设备 |
| `thickness_loss` | 壁厚减薄量 | mm | 静设备 |
| `vibration_level` | 振动水平 | mm/s | 旋转机组、往复机组 |
| `bearing_temp` | 轴承温度 | ℃ | 旋转机组 |
| `flow_rate` | 流量 | m³/h | 机泵 |
| `outlet_pressure` | 出口压力 | MPa | 机泵 |
| `valve_temp` | 阀温 | ℃ | 往复机组 |

### 3.3 KPI 默认选中规则

每个设备类型的前 3 个 KPI 默认选中（`default: true`），其余可选。当用户选择"全部"设备类型时，使用通用 KPI 集合。

---

## 4. 脚本设计

### 4.1 新增 `list_equipment.py`（设备目录查询）

**路径**：`skills/custom/data-analyst/scripts/list_equipment.py`

**职责**：根据设备类型、区域、搜索关键词查询匹配的设备列表和可用 KPI，无真实 API 时返回演示数据。

**命令行接口**：

```bash
python /mnt/skills/custom/data-analyst/scripts/list_equipment.py \
  --type static_equipment \
  --scope area \
  --filter "A区" \
  --limit 50
```

**参数说明**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--type` | 否 | 设备类型：`all`（默认）/ `static_equipment` / `rotating_machinery` / `pump` / `reciprocating_machinery` |
| `--scope` | 否 | 范围模式：`all`（默认）/ `area` / `specific` |
| `--filter` | 否 | 当 `scope=area` 时为区域名（逗号分隔），`scope=specific` 时为设备 ID（逗号分隔） |
| `--limit` | 否 | 最大返回设备数，默认 50 |

**输出契约**（写入 stdout）：

```json
{
  "equipment_type": "static_equipment",
  "type_display": "静设备",
  "scope": "area",
  "filter_display": "A区",
  "total_matched": 238,
  "total_in_type": 1000,
  "areas": ["A区", "B区", "C区", "D区"],
  "equipment": [
    {"id": "SE-001", "name": "E-101 换热器", "area": "A区", "sub_type": "换热器"},
    {"id": "SE-002", "name": "E-102 冷却器", "area": "A区", "sub_type": "冷却器"}
  ],
  "equipment_truncated": true,
  "available_kpis": [
    {"key": "runtime_rate", "name": "运行率", "unit": "%", "default": true},
    {"key": "alarm_count", "name": "告警数量", "unit": "条", "default": true},
    {"key": "corrosion_rate", "name": "腐蚀速率", "unit": "mm/a", "default": true},
    {"key": "thickness_loss", "name": "壁厚减薄量", "unit": "mm", "default": false},
    {"key": "energy_consumption", "name": "能耗", "unit": "kWh", "default": false}
  ]
}
```

**数据源优先级**：与 `query_daily.py` 一致（MCP → http_connector → 演示数据回退）。

**演示数据规模**：

| 类型 | 演示设备数 | 区域分布 |
|------|-----------|---------|
| 静设备 | 1000 | A-D 区各 250 |
| 旋转机组 | 100 | A-D 区各 25 |
| 机泵 | 1000 | A-D 区各 250 |
| 往复机组 | 100 | A-D 区各 25 |

**输入校验**：

- `--type`：枚举白名单
- `--scope`：枚举白名单
- `--filter`：当 `scope=area` 时每个区域名匹配 `^[一-鿿A-Za-z0-9_-]+$`；当 `scope=specific` 时每个 ID 匹配 `^[A-Za-z0-9_-]+$`

### 4.2 修改 `query_daily.py`

**新增参数**：

| 参数 | 说明 |
|------|------|
| `--type` | 设备类型（可选，默认 `all`），影响演示数据的 KPI 分布和告警内容 |
| `--scope` | 范围模式（可选，默认 `all`）：`all` / `area` / `specific`。用于大量设备场景，替代手动拼接 `--equipment` CSV |
| `--scope-filter` | 区域名或设备 ID（可选）。与 `--scope` 配合，当 `scope=area` 时为区域名 CSV，`scope=specific` 时为设备 ID CSV |

**设备 ID 传递策略**：

- **≤20 台（指定设备）**：继续使用 `--equipment` CSV，SOUL.md 可直接拼接。
- **>20 台（按区域或全部）**：使用 `--type` + `--scope` + `--scope-filter`，由 `query_daily.py` 内部调用 `list_equipment.py` 的查询逻辑获取完整设备列表，**SOUL.md 不需要拼接设备 ID CSV**。
- `--equipment` 与 `--scope` 互斥：传了 `--scope` 就忽略 `--equipment`。

> **为什么不让 SOUL.md 拼 CSV**：当用户选"全部静设备"（1000 台）时，LLM 无法从 `list_equipment.py` 返回的 50 条记录中凭空列出 1000 个设备 ID。同时 shell 命令长度在 Windows 上限制约 8191 字符，1000 个 `SE-xxx` ID 的 CSV 约 8000 字符，接近极限。

**KPI_UNITS 扩展**：新增 `corrosion_rate`、`thickness_loss`、`vibration_level`、`bearing_temp`、`flow_rate`、`outlet_pressure`、`valve_temp`。

**输出结构变更**：当设备数 > 20 时（通过 `--scope` 触发），`current` 新增 `per_equipment` 字段供 `daily_kpi.py` 计算 min/max/均值和识别异常设备：

```json
{
  "report_date": "2026-05-13",
  "equipment_ids": ["SE-001", "SE-002", "...（完整列表）"],
  "equipment_type": "static_equipment",
  "equipment_count": 238,
  "kpi_keys": ["runtime_rate", "corrosion_rate"],
  "compare_type": "previous_day",
  "compare_date": "2026-05-12",
  "current": {
    "kpis": {"runtime_rate": 0.943, "corrosion_rate": 0.12},
    "kpi_units": {"runtime_rate": "%", "corrosion_rate": "mm/a"},
    "hourly_runtime_rate": [24 floats（均值）],
    "alarms": [...],
    "per_equipment": {
      "SE-001": {"kpis": {"runtime_rate": 0.95, "corrosion_rate": 0.08}, "hourly_runtime_rate": [...]},
      "SE-002": {"kpis": {"runtime_rate": 0.78, "corrosion_rate": 0.48}, "hourly_runtime_rate": [...]}
    }
  },
  "compare": { "...同 current 结构，含 per_equipment..." }
}
```

- 当设备数 ≤ 20 时（`--equipment` 模式），`per_equipment` 不输出，`current` 保持原结构，完全向后兼容。
- 顶层 `kpis` 为全体设备均值，用于兼容现有逐台模式的 `daily_kpi.py`。

**演示数据适配**：`_demo_kpis()` 根据 KPI key 生成合理范围的演示值：

| KPI | 演示值范围 |
|-----|-----------|
| `corrosion_rate` | 0.01 – 0.5 mm/a |
| `thickness_loss` | 0.0 – 2.0 mm |
| `vibration_level` | 0.5 – 15.0 mm/s |
| `bearing_temp` | 35.0 – 90.0 ℃ |
| `flow_rate` | 50.0 – 500.0 m³/h |
| `outlet_pressure` | 0.3 – 2.5 MPa |
| `valve_temp` | 40.0 – 120.0 ℃ |

**告警内容适配**：`_demo_alarms()` 根据设备类型生成对应的告警消息：

| 设备类型 | 演示告警消息 |
|----------|-------------|
| 静设备 | 腐蚀速率超标、壁厚不足、泄漏检测 |
| 旋转机组 | 振动超标、轴承温度过高、不平衡 |
| 机泵 | 气蚀检测、密封泄漏、效率下降 |
| 往复机组 | 阀片磨损、气缸温度异常、振动异常 |

### 4.3 修改 `daily_kpi.py`

**KPI_DISPLAY_NAMES 扩展**：

```python
KPI_DISPLAY_NAMES = {
    "runtime_rate": "运行率",
    "downtime_count": "停机次数",
    "alarm_count": "告警数量",
    "output": "产量",
    "energy_consumption": "能耗",
    "corrosion_rate": "腐蚀速率",
    "thickness_loss": "壁厚减薄量",
    "vibration_level": "振动水平",
    "bearing_temp": "轴承温度",
    "flow_rate": "流量",
    "outlet_pressure": "出口压力",
    "valve_temp": "阀温",
}
```

**KPI_BETTER_WHEN_HIGHER 扩展**：新增 `flow_rate`、`outlet_pressure`。

**聚合策略**：当输入含 `per_equipment` 且设备数 > 20 时，输出新增以下顶层字段（与 §5.3 一致的扁平结构）：

- `aggregation_mode`：`"grouped"`（>20 台）或 `"detail"`（≤20 台）
- `kpi_summary` 中每项新增 `current_note`（`"均值"`）、`min`、`max`
- `trend_chart` 标题标注"均值"
- `top_anomalies`：Top-10 异常设备列表

```json
{
  "aggregation_mode": "grouped",
  "equipment_type": "static_equipment",
  "equipment_count": 238,
  "kpi_summary": [
    {
      "key": "runtime_rate",
      "name": "运行率",
      "current": 0.943,
      "current_note": "均值",
      "min": 0.78,
      "max": 0.99,
      "previous": 0.951,
      "delta": -0.008,
      "unit": "%",
      "direction": "down",
      "better_when_higher": true
    }
  ],
  "top_anomalies": [
    {"rank": 1, "equipment_id": "SE-042", "name": "E-142 换热器", "area": "A区", "issue": "腐蚀速率 0.48 mm/a（阈值 0.3）", "severity": "high"},
    {"rank": 2, "equipment_id": "SE-108", "name": "E-208 冷却器", "area": "A区", "issue": "壁厚减薄 1.8 mm", "severity": "warning"}
  ]
}
```

无 `per_equipment` 或设备数 ≤ 20 时，`aggregation_mode` 为 `"detail"`，无 `top_anomalies`，走现有逐台逻辑，输出不变。

聚合规则：

| 场景 | 聚合策略 | 展示方式 |
|------|---------|---------|
| 设备数 ≤ 20（指定设备） | 逐台展示（`detail`） | 每台设备独立 KPI 卡片和趋势 |
| 设备数 > 20（按区域或全部） | 整体聚合（`grouped`） | 聚合 KPI（均值/最大/最小）+ Top-10 异常设备排行 |

### 4.4 SOUL.md 修改摘要

**Round 1 表单**（`callback_id: daily-report-scope`）：

```json
{
  "component": "form",
  "action": "create",
  "interactive": true,
  "callback_id": "daily-report-scope",
  "callback_timeout_ms": 600000,
  "props": {
    "title": "生成设备运行日报",
    "description": "请选择日报参数。下一步将确认设备匹配结果和 KPI 指标。",
    "fields": [
      {
        "name": "report_date",
        "label": "日报日期",
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
        "name": "equipment_scope",
        "label": "设备范围",
        "type": "select",
        "required": true,
        "options": [
          {"label": "全部", "value": "all"},
          {"label": "按区域", "value": "area"},
          {"label": "指定设备", "value": "specific"}
        ]
      },
      {
        "name": "scope_filter",
        "label": "区域名称或设备ID（逗号分隔）",
        "type": "text",
        "required": false,
        "placeholder": "选'全部'时留空；按区域填'A区,B区'；指定设备填'SE-001,SE-002'"
      },
      {
        "name": "compare_with",
        "label": "对比基准",
        "type": "select",
        "required": true,
        "options": [
          {"label": "前一日", "value": "previous_day"},
          {"label": "上周同日", "value": "previous_week"},
          {"label": "不对比", "value": "none"}
        ]
      }
    ],
    "default_values": {
      "equipment_type": "all",
      "equipment_scope": "all",
      "compare_with": "previous_day"
    },
    "submit_label": "下一步"
  }
}
```

**Round 1 回调处理**：

1. 校验 `payload` 字段（`equipment_type` 枚举、`equipment_scope` 枚举、`scope_filter` 字符集、`report_date` 日期格式、`compare_with` 枚举）。
2. 调用 `list_equipment.py --type {type} --scope {scope} --filter {filter}`。
3. 读取返回的 `available_kpis` 和 `total_matched`。
4. 渲染 Round 2 表单。

**Round 2 表单**（`callback_id: daily-report-confirm`）：

Agent 根据 `list_equipment.py` 的返回动态生成，示例：

```json
{
  "component": "form",
  "action": "create",
  "interactive": true,
  "callback_id": "daily-report-confirm",
  "callback_timeout_ms": 600000,
  "props": {
    "title": "确认日报参数",
    "description": "已匹配: 静设备 · A区 · 238 台。请选择关注的 KPI 指标。",
    "fields": [
      {"name": "kpi_runtime_rate", "label": "运行率 (%)", "type": "checkbox", "required": false},
      {"name": "kpi_alarm_count", "label": "告警数量 (条)", "type": "checkbox", "required": false},
      {"name": "kpi_corrosion_rate", "label": "腐蚀速率 (mm/a)", "type": "checkbox", "required": false},
      {"name": "kpi_thickness_loss", "label": "壁厚减薄量 (mm)", "type": "checkbox", "required": false},
      {"name": "kpi_energy_consumption", "label": "能耗 (kWh)", "type": "checkbox", "required": false}
    ],
    "default_values": {
      "kpi_runtime_rate": true,
      "kpi_alarm_count": true,
      "kpi_corrosion_rate": true,
      "kpi_thickness_loss": false,
      "kpi_energy_consumption": false
    },
    "submit_label": "生成日报"
  }
}
```

**Round 2 回调处理**：

1. 从 `payload` 中收集所有 `kpi_*` 为 `true` 的字段，去掉 `kpi_` 前缀组装 KPI 列表。
2. 如果没有任何 KPI 被选中，渲染 `markdown` 提示"请至少选择一个 KPI 指标"并停止，不调用任何脚本。
3. **从对话历史中的 `daily-report-scope` 回调 payload 提取 Round 1 参数**：`report_date`、`equipment_type`、`equipment_scope`、`scope_filter`、`compare_with`。SOUL.md 必须显式指导 Agent 回溯对话历史获取这些值，不能假设 LLM 自动记忆。
4. 根据设备范围选择调用方式：
   - **指定设备（`equipment_scope=specific`，≤20 台）**：使用 `--equipment {ids}` 直接传递。
   - **按区域或全部（>20 台）**：使用 `--type {type} --scope {scope} --scope-filter {filter}`，由脚本内部解析设备列表，**SOUL.md 不拼接设备 ID CSV**。
5. 调用 `query_daily.py --date {date} --type {type} --scope {scope} --scope-filter {filter} --kpis {kpis} --compare {compare}`。
6. 调用 `daily_kpi.py`。
7. 按已有逻辑渲染 GenUI（card / echart / table / markdown / 导出 form）。聚合模式下额外渲染 `top_anomalies` 表格。

---

## 5. 大量设备聚合展示策略

### 5.1 聚合阈值

| 设备数 | 展示模式 | 说明 |
|--------|---------|------|
| ≤ 20 | 逐台明细 | 每台设备独立 KPI 卡片和趋势 |
| 21 - 200 | 聚合 + Top-10 异常 | 整体聚合 KPI + 异常设备排行 |
| > 200 | 分组聚合 + Top-10 异常 | 按区域或子类型分组 + 异常排行 |

### 5.2 聚合模式下的 GenUI 渲染

```
card: 整体状态（如"静设备 · A区 · 238 台 · 运行稳定"）
card×N: 聚合 KPI（均值/最大/最小）
echart: 24h 聚合运行率趋势（均值曲线 + 范围阴影）
table: Top-10 异常设备排行（columns: 排名/设备ID/名称/区域/异常描述/严重性）
table: 告警事件清单
markdown: 总结与建议
form: 导出
```

**`top_anomalies` 在各输出层的处理**：

| 层 | 处理方式 |
|---|---------|
| `daily_kpi.py` | 基于 `per_equipment` 数据计算异常评分，输出 `top_anomalies` 列表（`rank, equipment_id, name, area, issue, severity`） |
| SOUL.md GenUI 渲染 | 使用 `table` 组件，`columns: [{key: "rank", label: "排名"}, {key: "equipment_id", label: "设备ID"}, {key: "name", label: "名称"}, {key: "area", label: "区域"}, {key: "issue", label: "异常描述"}, {key: "severity", label: "严重性"}]`，`data: top_anomalies` |
| `export_report.py` | 新增"异常设备排行"Markdown 表格段落，渲染 `top_anomalies`；设备数 >20 时设备列表行改为"共 N 台"而非逐个列出 |

### 5.3 daily_kpi.py 聚合输出结构

当设备数 > 20 时，输出中新增 `aggregation` 段：

```json
{
  "report_date": "2026-05-13",
  "equipment_type": "static_equipment",
  "equipment_count": 238,
  "aggregation_mode": "grouped",
  "overall_status": {"level": "warning", "summary": "A区238台静设备整体运行稳定，3台设备腐蚀速率偏高"},
  "kpi_summary": [
    {
      "key": "runtime_rate",
      "name": "运行率",
      "current": 0.943,
      "current_note": "均值",
      "min": 0.78,
      "max": 0.99,
      "previous": 0.951,
      "delta": -0.008,
      "unit": "%",
      "direction": "down",
      "better_when_higher": true
    }
  ],
  "trend_chart": {
    "title": {"text": "24 小时运行率趋势（238台均值）"},
    "series": [
      {"name": "2026-05-13 均值", "type": "line", "data": [...]},
      {"name": "2026-05-13 范围", "type": "line", "areaStyle": {}, "data": [...]}
    ]
  },
  "top_anomalies": [
    {"rank": 1, "equipment_id": "SE-042", "name": "E-142 换热器", "area": "A区", "issue": "腐蚀速率 0.48 mm/a（阈值 0.3）", "severity": "high"},
    {"rank": 2, "equipment_id": "SE-108", "name": "E-208 冷却器", "area": "A区", "issue": "壁厚减薄 1.8 mm", "severity": "warning"}
  ],
  "alarm_table": [...],
  "recommendations": [...]
}
```

---

## 6. 与现有架构对齐检查

| 项 | 现有模式 | 本设计 | 状态 |
|----|----------|--------|------|
| Agent 配置位置 | `agents/builtin/ai-report--daily/` | 不变 | ✅ |
| Skill 脚本位置 | `skills/custom/data-analyst/scripts/` | 新增 `list_equipment.py`，同目录 | ✅ |
| 数据源发现 | 优先级链（MCP → Script → http_connector → 演示回退） | 同 | ✅ |
| 交互方式 | `render_ui form` + `ui_interaction` | 同（两轮表单） | ✅ |
| 渲染组件 | GenUI registry（card/echart/table/markdown/form）| 同（不新增组件） | ✅ |
| FormBlock 字段类型 | `text/number/date/select/checkbox/textarea/radio` | 使用 `date/select/text/checkbox` | ✅ |
| 文件下载 | sandbox `/mnt/user-data/outputs/` + artifact URL | 不变 | ✅ |
| 后端改动 | — | 零后端代码改动 | ✅ |
| 前端改动 | — | 零前端代码改动 | ✅ |

---

## 7. 设计决策记录

| 取舍 | 选择 | 原因 |
|------|------|------|
| 多选组件 vs checkbox 列表 | checkbox 列表 | GenUI FormBlock 无 multi-select 类型，checkbox 是已支持的字段类型 |
| 单轮 vs 两轮表单 | 两轮 | 第二轮需根据设备类型动态展示 KPI，GenUI form 无联动字段能力 |
| 设备搜索 vs 分类选择 | 分类选择为主 | GenUI form 无 async autocomplete，2200 台设备 select 不可行 |
| 设备目录硬编码 vs 脚本查询 | 脚本查询（含演示回退） | 与 `query_daily.py` 模式一致，未来接真实 API 只改脚本 |
| 逐台展示 vs 聚合 | 按阈值自动切换 | ≤20 台逐台，>20 台聚合，避免渲染爆炸 |
| KPI 硬编码 vs 动态发现 | 脚本返回可用 KPI 列表 | 设备类型决定 KPI，由 `list_equipment.py` 统一管理 |

---

## 8. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 两轮表单增加操作步骤 | 用户体验多一次点击 | Round 1 默认值合理（全部/前一日），快速用户可直接下一步 |
| checkbox 无法强制至少选一个 | 提交空 KPI 列表 | SOUL.md 校验，无选中 KPI 时 markdown 提示重选 |
| 演示数据 2200 台设备生成耗时 | 脚本执行变慢 | `list_equipment.py` 只返回 `--limit` 条，默认 50；总数通过计算获得不遍历 |
| 聚合逻辑复杂度 | `daily_kpi.py` 代码膨胀 | 聚合逻辑独立函数，按阈值分支，逐台模式走现有逻辑 |
| 真实设备 API 对接 | 接口 schema 不确定 | `list_equipment.py` 保持演示回退，真实 API 只需改数据获取层 |

---

## 9. 向后兼容

- **旧 `callback_id: daily-report-params`**：SOUL.md 更新后不再渲染该 callback，已提交的旧表单不受影响（已过期或已完成）。
- **`query_daily.py` 已有参数**：`--date`、`--equipment`、`--kpis`、`--compare` 保持不变，新增 `--type`、`--scope`、`--scope-filter` 为可选参数，不破坏现有调用。`--equipment` 与 `--scope` 互斥，传了 `--scope` 时忽略 `--equipment`。
- **`daily_kpi.py` 输出契约**：`kpi_summary`、`trend_chart`、`alarm_table` 字段不变，`aggregation_mode`、`top_anomalies` 为新增可选段，旧的逐台模式完全兼容。
- **`export_report.py` 输出契约**：当 `top_anomalies` 不存在或为空时不渲染该段落，现有 Markdown 结构不变。
- **现有测试**：所有 23 个现有测试不受影响（不使用 `--type`、不触发聚合）。

---

## 10. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `skills/custom/data-analyst/scripts/list_equipment.py` | 新增 | 设备目录查询脚本 |
| `skills/custom/data-analyst/scripts/query_daily.py` | 修改 | 新增 `--type`/`--scope`/`--scope-filter` 参数，扩展 KPI_UNITS，聚合场景输出 `per_equipment` |
| `skills/custom/data-analyst/scripts/daily_kpi.py` | 修改 | 扩展 KPI_DISPLAY_NAMES，新增聚合逻辑（min/max/均值、top_anomalies） |
| `skills/custom/data-analyst/scripts/export_report.py` | 修改 | 聚合模式下设备列表改为计数显示、报告标题含设备类型、新增 `top_anomalies` 表格渲染 |
| `agents/builtin/ai-report--daily/SOUL.md` | 修改 | 两轮表单流程，设备类型感知 KPI，聚合模式渲染指令 |
| `backend/tests/test_ai_report_daily_list_equipment.py` | 新增 | `list_equipment.py` 测试 |
| `backend/tests/test_ai_report_daily_query.py` | 修改 | 新增 `--type`/`--scope` 参数测试、新 KPI 演示数据测试 |
| `backend/tests/test_ai_report_daily_kpi.py` | 修改 | 新增聚合逻辑测试、top_anomalies 测试 |
| `backend/tests/test_ai_report_daily_export.py` | 修改 | 新增聚合模式 Markdown 渲染测试（设备计数、top_anomalies 表格） |
| `backend/tests/test_ai_report_daily_pipeline.py` | 修改 | 扩展 pipeline 测试覆盖新 KPI 和聚合场景 |
| `docs/plans/2026-05-13-ai-report-daily-design.md` | 修改 | 更新数据契约（新增 KPI、聚合输出、per_equipment 结构） |
| 前端代码 | **无** | — |
| 后端 Python 代码 | **无** | — |

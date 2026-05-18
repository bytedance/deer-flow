# 故障诊断智能体功能设计文档

> **范围**：完整功能设计，覆盖 group 升级、三个子 agent SOUL.md、数据接入（InS 工具链 + 振动诊断 skill 群）、规则库拆分、Skill 脚本、GenUI 渲染、Markdown/PDF 双导出。
> **遵循模式**：完全对齐 [AI 日报智能体功能设计文档](./2026-05-13-ai-report-daily-design.md) 与 [AI 周报智能体功能设计文档](./2026-05-18-ai-report-weekly-design.md) 的"SOUL.md（prompt 驱动） + skill 脚本（确定性计算） + GenUI 多轮表单 + 双格式导出"架构，复用 [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py) 的 weasyprint 自动降级路径。
> **与振动诊断 skill 对齐**：旋转机组直接复用 [vibration-fault-diagnosis](../../skills/custom/vibration-fault-diagnosis/SKILL.md) 与其 [diagnosis-rules.md](../../skills/custom/vibration-fault-diagnosis/references/diagnosis-rules.md)；机泵与往复机另起独立 skill 以隔离故障家族与规则演化节奏。

---

## 1. 现状与目标

### 1.1 现状

| 入口 | 现状 |
| ---- | ---- |
| `agents/builtin/fault-diagnosis/config.yaml` | 仍是 `type` 字段缺省的独立 agent，`order: 1`，未声明 `type: group`，未挂载任何子 agent。 |
| `agents/builtin/fault-diagnosis/SOUL.md` | 26 行 prompt-only 占位，描述了"角色/工作流程/输出标准"四段，没有 GenUI 表单、没有 InS 工具链调用契约、没有导出能力。 |
| 数据接入 | 已有 `ins-device-analysis` / `ins-get-trend-data` / `ins-get-waveform-data` / `ins-get-orbit-data` / `ins-extract-trend-features` / `ins-extract-spectral-waveform-features` / `ins-extract-orbit-centerline-features` 七个 skill，已经被 `vibration-fault-diagnosis` skill 引用。 |
| 规则库 | `vibration-fault-diagnosis/references/diagnosis-rules.md`（302 行）已覆盖汽轮机、离心/轴流压缩机、多轴齿轮式压缩机、螺杆式压缩机、齿轮箱五类设备的不平衡 / 不对中 / 临界响应 / 转子热弯曲 / 永久性弯曲 / 摩擦 / 旋转失速喘振 / 晃度 / 轴位移零点 / 轴承温度等故障家族。 |
| 机泵与往复机 | 无独立 skill，无独立规则库。`fault-diagnosis/SOUL.md` 仅一句"识别故障模式（不平衡、不对中、轴承损伤、共振等）"。 |
| AI 报告群 | `ai-report` 已是 `type: group`，下挂 `ai-report--daily/weekly/monthly/custom` 四个子 agent，多轮 GenUI 表单 + Markdown/PDF 双导出 + 严格回调隔离 + 严禁结构化会话摘要等约定经过线上验证。 |

### 1.2 目标

| 能力 | 描述 |
| ---- | ---- |
| group 升级 | `agents/builtin/fault-diagnosis/` 升级为 `type: group`，对齐 `ai-report` 父 group 的字段惯例。 |
| 三类设备子 agent | 新增 `fault-diagnosis--pump`（机泵）、`fault-diagnosis--rotating`（旋转机组）、`fault-diagnosis--reciprocating`（往复机），共享 group 入口与三轮 GenUI 模板。 |
| 交互式参数收集 | 三轮 GenUI 表单：诊断时间窗 + 设备类型 + 诊断模式 + 同期对比 → 设备/测点多选 → 故障特征焦点（按设备类型差异化呈现）。 |
| 数据采集主路径 | InS 工具链 skill 群（机泵也复用同一套 trend/waveform/orbit 工具）+ `query_diagnosis.py` 演示数据回退。 |
| 规则匹配主路径 | 旋转机组：`vibration-fault-diagnosis` skill；机泵：`pump-fault-diagnosis` skill；往复机：`reciprocating-fault-diagnosis` skill。三者 references 各自独立。 |
| 结构化输出 | 诊断结论 markdown + 关键趋势 echart + 关键频谱 echart + 轴心轨迹 echart（旋转机/机泵）+ 证据表 table + 同类故障历史 card + 处置建议 markdown。 |
| 导出 | Markdown 必需，PDF 走 weasyprint 自动降级，与日报一致。 |
| 严守日报已验证约束 | 严禁结构化会话摘要、严禁复用更早轮次回调、payload 顶层取值、`/mnt/user-data/outputs/` 固定路径、`present_files` 仅对最终交付物。 |

### 1.3 与 AI 报告群的差异

| 维度 | ai-report--daily | fault-diagnosis--{pump,rotating,reciprocating} |
| ---- | ---- | ---- |
| 用途 | 周期性结构化报告 | 异常事件触发的根因分析 |
| 输出基调 | KPI/趋势/异常事件汇总 | 故障家族判定 + 证据链 + 处置建议 |
| 时间窗 | 固定（日/周/月） | 用户指定，可短至单个工况切换 |
| 章节结构 | 概览/KPI/趋势/异常/建议 | 设备与任务/异常发现/证据链/诊断结论/差异诊断/处置建议 |
| 数据来源 | `query_daily.py` 等聚合脚本 | InS 工具链原始数据 + 特征提取 + 规则匹配 |
| 规则强度 | 弱（只算 KPI） | 强（必须落到具体故障家族） |
| 同期对比意义 | 上一周期对照 | 历史同工况对照（运行模式/转速带/工艺扰动） |

---

## 2. 系统架构

**入口流程**：用户从 `fault-diagnosis`（升级后的 `type: group`）的子 agent 列表中进入三个子 agent 之一，与现有 `ai-report` group 入口完全一致；父 group 的 `config.yaml` 不显式声明子 agent，依赖目录扫描发现。

```text
┌──────────────────────────────────────────────────────────────────┐
│                       前端对话页面                                │
│   workspace/agents/fault-diagnosis--{kind}/chats/{thread_id}     │
│                                                                  │
│   GenUI 区域（三轮表单 + 诊断输出）：                             │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │ Round 1: 诊断范围（form / fd-{kind}-scope）              │  │
│   │  时间窗起止 / 设备类型 / 诊断模式 / 同期对比              │  │
│   └──────────────────────────────────────────────────────────┘  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │ Round 1.5: 设备/测点多选（form / fd-{kind}-target）      │  │
│   │  设备多选（按区域分组）+ 关键测点确认                     │  │
│   └──────────────────────────────────────────────────────────┘  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │ Round 2: 故障特征焦点（form / fd-{kind}-focus）          │  │
│   │  按设备类型差异化的故障家族多选                           │  │
│   └──────────────────────────────────────────────────────────┘  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │ Round 3: 诊断输出（多 GenUI Block 组合）                 │  │
│   │  card: 设备工况摘要（运行阶段、最大值、报警状态）         │  │
│   │  echart: 关键测点 24h-7d 趋势                             │  │
│   │  echart: 频谱（1X/2X/分数次/低频）                        │  │
│   │  echart: 轴心轨迹（旋转机/机泵）                          │  │
│   │  table: 证据链（按 趋势→频谱→波形→轨迹→工艺 分组）        │  │
│   │  card: 同类故障历史命中（设备/家族/时间）                 │  │
│   │  markdown: 诊断结论 + 差异诊断 + 处置建议                 │  │
│   │  下载链接（Markdown + PDF artifact URL）                  │  │
│   └──────────────────────────────────────────────────────────┘  │
└──────────────────┬───────────────────────────────────────────────┘
                   │ LangGraph SSE（DeerFlowClient 流水线）
┌──────────────────┼───────────────────────────────────────────────┐
│                  ▼   Backend                                      │
│                                                                  │
│   Agent: fault-diagnosis--{pump,rotating,reciprocating}          │
│   SOUL.md 驱动 LLM 按以下步骤工作：                              │
│     1. 渲染 Round 1 表单并停止                                   │
│     2. 收到 scope 回调 → 校验 → ins-device-analysis              │
│        → 渲染 Round 1.5                                          │
│     3. 收到 target 回调 → 校验 → 按设备类型差异化生成 Round 2    │
│     4. 收到 focus 回调 → query_diagnosis.py + 调用 InS 工具链    │
│        → diagnosis_features.py → render_ui 多 Block              │
│     5. export_diagnosis_report.py 写 md/pdf → present_files      │
│                                                                  │
│   Skills（按子 agent 装配）：                                    │
│   - 共用：data-analyst（脚本承载）                               │
│   - 共用：ins-device-analysis / ins-get-trend-data /             │
│           ins-get-waveform-data / ins-get-orbit-data /           │
│           ins-extract-trend-features /                           │
│           ins-extract-spectral-waveform-features /               │
│           ins-extract-orbit-centerline-features                  │
│   - 旋转机：vibration-fault-diagnosis                            │
│   - 机泵：  pump-fault-diagnosis（新建）                         │
│   - 往复机：reciprocating-fault-diagnosis（新建）                │
│                                                                  │
│   skill: data-analyst                                            │
│   scripts/                                                       │
│     ├ query_diagnosis.py        # 新增：诊断数据查询/InS 编排    │
│     ├ diagnosis_features.py     # 新增：特征提取 + 规则匹配      │
│     └ export_diagnosis_report.py # 新增：Markdown + PDF 导出     │
└──────────────────────────────────────────────────────────────────┘
```

**关键原则**：

- 全部逻辑由 SOUL.md（prompt 驱动）+ 规则 skill + 三个新 skill 脚本承载，**不新增后端 Python 代码、不新增路由、不新增前端 GenUI 组件**。
- 复用 LangGraph SSE 流水线、`DeerFlowClient` 调用约定、`genui_middleware` 的 `(thread_id, callback_id)` 复合 key 机制。
- 复用现有 artifact 路由（`/api/threads/{thread_id}/artifacts/...`）暴露下载链接。

---

## 3. Agent 配置改造

> 以下 YAML 片段仅作为设计文档范例，**不修改真实 `agents/builtin/fault-diagnosis/config.yaml`**。

### 3.1 父 group 升级（fault-diagnosis）

```yaml
name: fault-diagnosis
display_name: "故障诊断"
description: "擅长机泵、旋转机组、往复机的振动与工艺联动诊断、根因定位与处置建议"
icon: "🔮"
type: group
order: 5
model: null
tool_groups:
  - bash
exclude_tools: []
skills: []
mcp_servers: null
tags:
  - diagnosis
  - fault
  - vibration
advanced:
  subagent_enabled: false
```

升级要点：

- 新增 `type: group`，与 `ai-report` 一致。
- `order` 顺延到 `5`（避免与 `ai-report` 的 `4` 冲突；最终值由项目导航顺序决定）。
- `skills: []` 留空，由各子 agent 单独装配 skill 集合，避免子 agent 互相污染规则库。
- `subagent_enabled: false` 沿用 `ai-report` 的隐式子 agent 发现策略。

### 3.2 子 agent fault-diagnosis--pump（机泵）

```yaml
name: fault-diagnosis--pump
display_name: "机泵故障诊断"
description: "面向离心泵/容积泵的振动 + 流量 + 压力 + 电流联动诊断"
icon: "💧"
parent: fault-diagnosis
order: 1
model: null
tool_groups:
  - bash
skills:
  - data-analyst
  - pump-fault-diagnosis
  - ins-device-analysis
  - ins-get-trend-data
  - ins-get-waveform-data
  - ins-get-orbit-data
  - ins-extract-trend-features
  - ins-extract-spectral-waveform-features
  - ins-extract-orbit-centerline-features
mcp_servers: null
tags:
  - diagnosis
  - pump
starters:
  - label: "诊断机泵振动异常"
    prompt: "诊断机泵故障"
    auto_start: true
```

### 3.3 子 agent fault-diagnosis--rotating（旋转机组）

```yaml
name: fault-diagnosis--rotating
display_name: "旋转机组故障诊断"
description: "汽轮机、离心/轴流压缩机、多轴齿轮压缩机、螺杆压缩机、齿轮箱"
icon: "⚙️"
parent: fault-diagnosis
order: 2
model: null
tool_groups:
  - bash
skills:
  - data-analyst
  - vibration-fault-diagnosis
  - ins-device-analysis
  - ins-get-trend-data
  - ins-get-waveform-data
  - ins-get-orbit-data
  - ins-extract-trend-features
  - ins-extract-spectral-waveform-features
  - ins-extract-orbit-centerline-features
mcp_servers: null
tags:
  - diagnosis
  - rotating
  - turbine
  - compressor
starters:
  - label: "诊断旋转机组振动异常"
    prompt: "诊断旋转机组故障"
    auto_start: true
```

### 3.4 子 agent fault-diagnosis--reciprocating（往复机）

```yaml
name: fault-diagnosis--reciprocating
display_name: "往复机故障诊断"
description: "面向往复式压缩机/泵的曲轴角联动 + 缸压 + 阀门事件诊断"
icon: "🔧"
parent: fault-diagnosis
order: 3
model: null
tool_groups:
  - bash
skills:
  - data-analyst
  - reciprocating-fault-diagnosis
  - ins-device-analysis
  - ins-get-trend-data
  - ins-get-waveform-data
  - ins-extract-trend-features
  - ins-extract-spectral-waveform-features
mcp_servers: null
tags:
  - diagnosis
  - reciprocating
  - compressor
starters:
  - label: "诊断往复机故障"
    prompt: "诊断往复机故障"
    auto_start: true
```

往复机暂不挂 `ins-get-orbit-data` / `ins-extract-orbit-centerline-features`：往复机以曲轴角对齐的缸压/阀门动作分析为主，轴心轨迹不是主路径，避免误导 LLM 调用。

---

## 4. 三个子 agent SOUL.md 设计

### 4.1 共性骨架（三个 SOUL.md 共享）

> **正式实现以 `agents/builtin/fault-diagnosis--{kind}/SOUL.md` 为准**，本节仅描述结构契约。任何字段/参数变更直接修改实际 SOUL 文件。

通用约束（与 `ai-report--daily/SOUL.md` 完全对齐）：

- **核心原则**
  - 数据优先：所有诊断结论必须来自脚本输出、规则匹配或 InS 工具链返回的数据，不凭空编造。
  - 先收参后诊断：首次进入或缺少参数时必须先渲染 Round 1 表单，然后停止等待用户提交。
  - 严格读取 `ui_interaction.payload`：表单字段位于 `payload` 顶层，不在 `values` 中。
  - 同一线程可能多次诊断：**回溯 `ui_interaction` 历史时只能使用当前消息之前最近一次匹配的回调消息**，绝不能复用更早轮次参数。
  - 输出路径固定：所有可下载产物必须写入 `/mnt/user-data/outputs/`。
  - 只使用已注册 GenUI 组件 `form` / `card` / `echart` / `table` / `markdown`，无后端路由、无前端组件变更。
  - **严禁输出结构化会话摘要**：不要输出 "SESSION INTENT" / "SUMMARY" / "ARTIFACTS" / "NEXT STEPS" 等章节标题。
  - **严禁对中间产物调用 `present_files`**：仅对 `diagnosis_report.md` / `diagnosis_report.pdf` 调用，不要暴露 `query_diagnosis.json` / `diagnosis_features.json`。
- **校验先行**：`payload` 中的设备 ID 必须匹配 `[A-Za-z0-9_-]+`；`start_date` / `end_date` 必须满足 `^\d{4}-\d{2}-\d{2}$`；`start_hour` / `end_hour` 必须为 `0`-`23`；任一校验失败时渲染 `markdown` 让用户重提，禁止直接拼接。
- **回调命名约定**
  - Round 1：`fd-{kind}-scope`
  - Round 1.5：`fd-{kind}-target`
  - Round 2：`fd-{kind}-focus`
  - 三个 callback_id 在不同 SOUL.md 中前缀不同（`fd-pump-*` / `fd-rotating-*` / `fd-reciprocating-*`），避免父 group 内串扰。
- **回调超时**：`callback_timeout_ms: 600000`，与日报一致。

### 4.2 Round 1：诊断范围

三个子 agent 共有字段：

| 字段 | 类型 | 选项 / 默认 |
| ---- | ---- | ---- |
| `start_date` | date | 必填，过去 7 日内默认 |
| `start_hour` | select | 0-23 整点，默认 `0` |
| `end_date` | date | 必填，必须 ≥ `start_date`，整体跨度不超过 30 天 |
| `end_hour` | select | 0-23 整点，默认 `0`（含义：`end_date 00:00`，即不含当日） |
| `mode` | select | `oneoff`（一次性深度诊断） / `screening`（快速筛查），默认 `oneoff` |
| `compare_with` | select | `previous_period`（同时长前一窗口） / `none`，默认 `previous_period` |

> **字段类型说明**：日期用 `date` + 小时下拉，与 [ai-report--daily/SOUL.md](../../agents/builtin/ai-report--daily/SOUL.md) 已验证的 `type: "date"` 风格保持一致；FormBlock 当前未明确支持 `datetime` 类型，避免引入未验证字段。SOUL 在收到回调后将 `start_date + start_hour` 拼成 ISO 字符串再交给脚本。

差异化字段（仅出现在对应子 agent）：

- 机泵（`fault-diagnosis--pump`）：增加 `equipment_kind` 单选 = {`centrifugal_pump`, `positive_displacement_pump`}，默认 `centrifugal_pump`。
- 旋转机组（`fault-diagnosis--rotating`）：增加 `equipment_kind` 单选 = {`steam_turbine`, `centrifugal_compressor`, `axial_compressor`, `geared_compressor`, `screw_compressor`, `gearbox`}，默认 `centrifugal_compressor`。
- 往复机（`fault-diagnosis--reciprocating`）：增加 `equipment_kind` 单选 = {`reciprocating_compressor`, `reciprocating_pump`}，默认 `reciprocating_compressor`。

提交后 SOUL 行为：校验 `payload` → 调用 `ins-device-analysis`（已知机器 ID 时）或 `query_diagnosis.py --mode list_machines --kind {equipment_kind}`，回填设备目录 → 渲染 Round 1.5。

### 4.3 Round 1.5：设备 / 测点多选

字段：

| 字段 | 类型 | 说明 |
| ---- | ---- | ---- |
| `equipment_ids` | multi-select | 按设备 `area` 分组，可搜索；**默认勾选最多 5 台**（与日报"全选"惯例不同） |
| `key_points` | multi-select | 关键测点（轴振 X/Y、轴位移、缸压、流量、出/入口压力、电机电流，按 `equipment_kind` 自动收敛默认勾选） |

> **为什么诊断默认 ≤5 台 ≠ 日报全选**：诊断要走 InS 波形/频谱/轨迹深度调用（每台 12+ 特征 × 多时间点），全选会导致 token 失控与单次诊断超时；日报只算 KPI 聚合，全选成本可控。在 SOUL.md 中需显式注释这条差异，避免后续维护者按日报惯例改回全选。

机泵默认勾选：轴振 X/Y、出口压力、入口压力、流量、电机电流。
旋转机组默认勾选：两端轴振 X/Y、轴位移、轴承温度、推力轴承温度、转速、入口流量、防喘振阀开度（按 InS 树存在性裁剪）。
往复机默认勾选：曲轴角对齐的振动、缸压、卸荷阀状态、阀门事件、活塞杆下沉量、电机电流。

校验：`equipment_ids` 至少一个；`key_points` 至少两个。失败时渲染 `markdown` 让用户补齐。

### 4.4 Round 2：故障特征焦点

**Changelog · 2026-05-18 Story S1-2 评审记录**：

- 修订前 / 后家族数：机泵 8→9、旋转机 12（不变）、往复机 10→11。
- 机泵 + 往复机增补 `motor_coupling`（电机端联动：电流谐波 / 转矩脉动 / 启停冲击），与各自 [§6.1](#61-pump-fault-diagnosis新建) / [§6.2](#62-reciprocating-fault-diagnosis新建) skill 的 references 章节骨架对齐。
- 机泵轴承故障（滚动 / 滑动）在 family 层合并为 `bearing_damage`，subtype 由 LLM 在报告 §4 写明，避免 form 选项过多。
- 旋转机 `runout` 注：英文 code 来自 references 中"晃度"章节，语义为**测量探头表面跳动 / measurement effect**，不是"shaft runout"。SOUL 提示文案需写中英文双标。
- vibration skill code 映射段已落入 [skills/custom/vibration-fault-diagnosis/SKILL.md](../../skills/custom/vibration-fault-diagnosis/SKILL.md) 末尾。

> 故障家族选项**按设备类型差异化呈现**，避免无关项干扰 LLM。下面列出三个子 agent 的不同 `options`。

机泵 `fd-pump-focus`（9 项）：

- `unbalance`（不平衡）
- `misalignment`（不对中）
- `bearing_damage`（轴承损伤；滚动 / 滑动 subtype 由报告内细化）
- `cavitation`（汽蚀）
- `seal_leakage`（密封泄漏）
- `impeller_wear`（叶轮磨损 / 腐蚀）
- `min_flow_violation`（流量低于最小连续流量）
- `resonance`（共振）
- `motor_coupling`（电机端联动：电流谐波 / 转矩脉动）

旋转机组 `fd-rotating-focus`（12 项；与 `vibration-fault-diagnosis/references/diagnosis-rules.md` 故障家族对齐）：

- `unbalance`（不平衡）
- `misalignment`（不对中）
- `critical_response`（临界响应大）
- `thermal_bend`（转子热弯曲）
- `permanent_bend`（转子永久性弯曲）
- `rub_seal`（动静摩擦 / 密封摩擦）
- `support_bearing`（支撑轴承装配 / 软脚 / 刚度差异；不含温度异常）
- `rotating_stall_surge`(旋转失速 / 喘振)
- `runout`（晃度 / measurement effect — **不是 shaft runout**，语义见 references "晃度"章节）
- `axial_offset_calibration`（轴位移零点调校异常）
- `bearing_temperature_high`（支撑轴承温度异常 / 装配异常）
- `thrust_bearing_temperature_high`（推力轴承温度异常 / 装配或设计异常）

往复机 `fd-reciprocating-focus`（11 项）：

- `valve_failure`（吸 / 排气阀故障；subtype 在报告内细化为吸 / 排）
- `piston_ring_wear`（活塞环磨损）
- `crosshead_knock`（十字头敲缸）
- `connecting_rod_clearance`（连杆轴承间隙过大）
- `piston_rod_droop`（活塞杆下沉）
- `cylinder_pressure_anomaly`（缸压异常）
- `unloader_anomaly`（卸荷阀异常）
- `bearing_damage`（轴承损伤）
- `misalignment`（不对中）
- `resonance`（共振）
- `motor_coupling`（电机端联动：电流谐波 / 启停冲击）

字段：`focus_codes` 多选 checkbox（每项 `name` 用 `focus_{code}`，与日报 KPI 字段命名风格一致）；至少选一项；下方一个可选自由文本 `extra_note`，最长 200 字符。

### 4.5 Round 3：诊断 + 导出（focus 回调内部）

收到 `fd-{kind}-focus` 回调后，SOUL 按以下顺序执行（详细命令在 §5 数据流）：

1. 回溯历史，分别拿到 Round 1 / Round 1.5 / Round 2 最近一次回调 payload；将 `start_date + start_hour`、`end_date + end_hour` 拼成 ISO 字符串。
2. **第一阶段（聚合拉取，由脚本承担）**：调用 `query_diagnosis.py`，脚本内部统一调用 `ins-extract-trend-features` 对所有设备 × 测点拉趋势特征，写出 `/mnt/user-data/outputs/query_diagnosis.json`。波形 / 频谱 / 轨迹**不在本阶段拉取**，避免 token 浪费。
3. **第二阶段（按需深度采样，由 LLM 承担）**：LLM 阅读 `query_diagnosis.json.points[].trend_summary.anomaly_time_ms`，**仅对存在异常时间点的测点**逐个调用：
   - 旋转机 / 机泵：`bash /mnt/skills/custom/ins-get-waveform-data/scripts/run.sh ...`、`bash /mnt/skills/custom/ins-extract-spectral-waveform-features/scripts/run.sh ...`、`bash /mnt/skills/custom/ins-get-orbit-data/scripts/run.sh ...`、`bash /mnt/skills/custom/ins-extract-orbit-centerline-features/scripts/run.sh ...`
   - 往复机：仅前两个（无 orbit）

   分工边界：聚合特征 → 脚本一次拉全；深度采样 → LLM 按异常点稀疏拉取。SOUL.md 必须显式列出该分工，避免 LLM 把第二阶段也丢给脚本，或反过来在第一阶段就 spawn 多次 ins 调用。

4. 调用 `diagnosis_features.py` 读 `query_diagnosis.json`（以及 LLM 在第二阶段写入的 `/mnt/user-data/outputs/spectrum_*.json` / `orbit_*.json`），写出 `/mnt/user-data/outputs/diagnosis_features.json`，包含规则匹配候选（按 §6 规则 skill 选择对应 rule book）。
5. 用 `render_ui` 顺序渲染：
   - `card`：设备工况摘要（一台设备一个 card；多台时取 TopN）
   - `echart`：关键测点趋势（沿用 `query_daily.py` ECharts option 格式，由 `diagnosis_features.json.trend_chart` 直接产出）
   - `echart`：频谱（每个目标点一张，由 `diagnosis_features.json.spectrum_charts[].option`）
   - `echart`：轴心轨迹（旋转机/机泵；往复机省略）
   - `table`：证据链（columns 固定为 `category` / `point` / `feature` / `value` / `threshold` / `verdict`）
   - `card`：同类故障历史（一条命中一个 card；最多 3 条）
   - `markdown`：诊断结论 / 差异诊断 / 处置建议（结构对齐 `vibration-fault-diagnosis/SKILL.md` 的输出模板第 1-6 节）
6. **In-process 导出（与 [ai-report--daily/SOUL.md](../../agents/builtin/ai-report--daily/SOUL.md) 第 239-273 行当前实现对齐）**：用 `bash` 工具运行内联 Python，`from export_diagnosis_report import render_diagnosis_markdown, write_diagnosis_report`，不再 spawn `python ... --format md` / `--format pdf` 两次。Markdown 总是写出，PDF 用 `try/except ImportError` 自动降级：

   ```python
   import json, sys
   sys.path.insert(0, "/mnt/skills/custom/data-analyst/scripts")
   from export_diagnosis_report import render_diagnosis_markdown, write_diagnosis_report

   with open("/mnt/user-data/outputs/diagnosis_features.json", encoding="utf-8") as f:
       payload = json.load(f)

   report_md = render_diagnosis_markdown(payload, thread_id="{thread_id}")
   write_diagnosis_report(payload, "md")  # 必成功

   pdf_available = True
   try:
       write_diagnosis_report(payload, "pdf")
   except ImportError:
       pdf_available = False

   links = ["- [下载 Markdown](/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/diagnosis_report.md)"]
   links.append(
       "- [下载 PDF](/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/diagnosis_report.pdf)"
       if pdf_available else
       "- PDF 不可用（weasyprint 未安装）"
   )
   report_md += "\n\n---\n## 下载\n" + "\n".join(links)

   render_ui(component="markdown", props={"content": report_md}, sequence=99)
   ```

7. `present_files(["/mnt/user-data/outputs/diagnosis_report.md", "/mnt/user-data/outputs/diagnosis_report.pdf"])`，PDF 失败时只 present `.md`。**绝对不要对 `query_diagnosis.json` / `diagnosis_features.json` / `spectrum_*.json` / `orbit_*.json` 调用 `present_files`**。

### 4.6 三个 SOUL.md 的差异点小结

| 项 | pump | rotating | reciprocating |
| ---- | ---- | ---- | ---- |
| 主要数据维度 | 振动 + 流量 + 压力 + 电机电流 | 振动 + 转速 + 轴位移 + 温度 + 工艺联动 | 振动 + 曲轴角 + 缸压 + 阀门事件 + 卸荷阀 |
| 默认证据链顺序 | 趋势→频谱→流量/压力→电流→（可选）轨迹 | 趋势→频谱→波形→轨迹→工艺→温度/轴位移 | 趋势→曲轴角对齐振动→缸压曲线→阀门事件→电流 |
| 是否输出 orbit echart | 是（小型机泵可降级） | 是 | 否 |
| 故障家族选项 | §4.4 机泵 | §4.4 旋转机组 | §4.4 往复机 |
| 规则 skill | pump-fault-diagnosis | vibration-fault-diagnosis | reciprocating-fault-diagnosis |

---

## 5. Skill 脚本设计

> 三个新脚本统一放在 `skills/custom/data-analyst/scripts/`，与 `query_daily.py` / `daily_kpi.py` / `export_report.py` 平级，便于复用 `data-analyst` 的 registry 配置与导出工具函数。

### 5.1 query_diagnosis.py

职责（**仅第一阶段聚合拉取**）：按设备类型、时间窗、诊断模式批量拉趋势特征。**只调 `ins-extract-trend-features`**；波形 / 频谱 / 轨迹由 LLM 在 §4.5 第二阶段按异常点稀疏调用，不在本脚本内。当 InS 不可用或机器 ID 在 demo 名单中时，写入稳定演示数据，确保端到端链路可运行。

```bash
python /mnt/skills/custom/data-analyst/scripts/query_diagnosis.py \
  --kind "centrifugal_pump" \
  --equipment "PUMP-A-001,PUMP-A-002" \
  --start "2026-05-12T00:00:00" \
  --end "2026-05-13T12:00:00" \
  --mode "oneoff" \
  --compare "previous_period" \
  --output /mnt/user-data/outputs/query_diagnosis.json
```

输入参数：

- `--kind`：与 Round 1 `equipment_kind` 一致，决定调用 InS 工具链时的默认特征列表（pump/rotating 用 `["pp_value","rms","p_value","speed","gap","one_freq_y","one_freq_x","two_freq_y","two_freq_x","half_freq","remain_freq"]`，往复机增加 `["crank_angle","cylinder_pressure"]`）。
- `--equipment`：逗号分隔设备 ID。
- `--start` / `--end`：ISO8601 起止。
- `--mode`：`oneoff` / `screening`。`screening` 模式下减少 waveform/orbit 采样点（节省 token 与时间）。
- `--compare`：`previous_period` / `none`。
- `--output`：输出路径，默认 `/mnt/user-data/outputs/query_diagnosis.json`。

输出 JSON 关键字段：

- `kind`、`equipment_ids`、`time_window`、`compare_window`
- `data_source`：`ins` / `demo_fallback`
- `points[]`：每个测点
  - `equipment_id` / `point_id` / `point_name` / `point_type`（`type=83/82/81`）
  - `default_features` 列表
  - `trend_summary`：`ins-extract-trend-features` 输出的 `summary` 与 `notable_points`
  - `anomaly_time_ms` 列表（用于后续 waveform/orbit 调用）
- `process_signals`：流量/压力/电流/温度等工艺通道（按 kind 裁剪）
- `compare`：与 `points` 同结构，或 `null`

异常处理：InS 调用失败时写入 `data_source=demo_fallback`，并把错误堆栈写入 `warnings[]`，不抛出。

### 5.2 diagnosis_features.py

职责：读取 `query_diagnosis.json`（必要时再调用 `ins-extract-spectral-waveform-features` / `ins-extract-orbit-centerline-features`），按 `--kind` 选择对应规则 skill 的 rule book，输出诊断结构化 JSON。

```bash
python /mnt/skills/custom/data-analyst/scripts/diagnosis_features.py \
  --input /mnt/user-data/outputs/query_diagnosis.json \
  --focus "unbalance,misalignment,bearing_damage" \
  --rules-skill "pump-fault-diagnosis" \
  --output /mnt/user-data/outputs/diagnosis_features.json
```

输入参数：

- `--input`：上一步输出。
- `--focus`：逗号分隔的故障家族 code（与 Round 2 选项对齐）。
- `--rules-skill`：`vibration-fault-diagnosis` / `pump-fault-diagnosis` / `reciprocating-fault-diagnosis`，决定加载哪个 `references/diagnosis-rules.md`。脚本内部以 markdown 解析获取规则节，再做 best-effort 轻量匹配（不替代 LLM 推理，仅给 LLM 提供候选列表与命中证据）。
- `--output`：输出路径。

输出 JSON 关键字段：

- `equipment_summary[]`：设备工况摘要，对应 Round 3 `card`
- `evidence_chain[]`：每行 `{category, point, feature, value, threshold, verdict}`
- `trend_chart`：完整 ECharts option（多 series / 阈值线）
- `spectrum_charts[]`：每个目标点一个 ECharts bar/line option
- `orbit_charts[]`：每个轴承一个 ECharts scatter/line option（往复机为空数组）
- `rule_matches[]`：`{equipment_id, kind, fault_family, fault_subtype, confidence, supporting_evidence_indices, missing_evidence}`
- `historical_cases[]`：从历史记录中检索到的同类故障（演示数据可返回 0-3 条）
- `recommendations`：字符串数组

`rule_matches[].confidence` 取 `high` / `medium` / `low`，与 vibration skill 的报告模板一致。

### 5.3 export_diagnosis_report.py + 在 export_report.py 注册新 report_type

> **核验结果（2026-05-18，Story S1-6 前置）**：
>
> - `export_report.py` 的 `SUPPORTED_REPORT_TYPES = {"daily", "weekly", "monthly"}`（line 33）已是参数化设计，扩展成本极低。
> - 现有三处 SOUL（daily/weekly/monthly）仅 import `render_*_markdown` + `write_report` 两类公共 API，未跨模块引用 `_markdown_to_html` / `_write_pdf` 等私有函数。
> - `build_export_result` 内部封装 `write_report`，对外暴露稳定 dict 形态。

基于上述核验，**改用注册新 report_type 的方式复用**，比"复制实现"或"提升私有 API"都干净：

1. 在 `export_report.py` 中：
   - `SUPPORTED_REPORT_TYPES` 增加 `"diagnosis"`。
   - `_output_dir(report_type)`、`load_payload(report_type)`、`write_report(report_type)` 各自加 `diagnosis` 分支（与 monthly 分支同结构）。
   - 在文件顶部 `import` 段加 `from export_diagnosis_report import render_diagnosis_markdown, render_diagnosis_html`。这样诊断专属字段不污染日报/周报模板，但 PDF / 降级 / 文件命名走同一套出口。
2. 在新文件 `skills/custom/data-analyst/scripts/export_diagnosis_report.py` 中：
   - 仅承载 `render_diagnosis_markdown(payload, thread_id)`、`render_diagnosis_html(payload)` 两个纯函数。
   - 不再实现独立 CLI；冒烟测试通过 `python -m export_report --report-type diagnosis --input ... --format md` 完成。

SOUL 调用（与 [ai-report--daily/SOUL.md:243](../../agents/builtin/ai-report--daily/SOUL.md) 现行写法 1:1 对齐）：

```python
import json, sys
sys.path.insert(0, "/mnt/skills/custom/data-analyst/scripts")
from export_report import write_report
from export_diagnosis_report import render_diagnosis_markdown

with open("/mnt/user-data/outputs/diagnosis_features.json", encoding="utf-8") as f:
    payload = json.load(f)

report_md = render_diagnosis_markdown(payload, thread_id="{thread_id}")
write_report(payload, "md", report_type="diagnosis")  # 必成功，落 diagnosis_report.md

pdf_available = True
try:
    write_report(payload, "pdf", report_type="diagnosis")
except ImportError:
    pdf_available = False
```

实现要点：

- `render_diagnosis_markdown(payload, thread_id)`：按 vibration skill 的 6 节模板组织（设备与任务 / 异常发现 / 证据链 / 诊断结论 / 差异诊断 / 处置建议）。
- `render_diagnosis_html(payload)`：被 `write_report(... report_type="diagnosis", fmt="pdf")` 内部调用，复用 `_markdown_to_html` 的样式（**通过 `write_report` 内部走，不需要跨文件 import 私有函数**）。
- 趋势 / 频谱 / 轨迹三类 ECharts option 通过 `trend_chart_to_svg`（公共函数）转 SVG 嵌入；超过 50KB 时落盘并以 artifact URL 引用。
- `ImportError`（weasyprint 缺失）由 `_write_pdf` 抛出后逐层冒泡到 SOUL 的 `try/except`，与日报行为一致。
- `build_export_result(payload, fmt, report_type="diagnosis")` 自动可用（由 `export_report.py` 已实现的封装提供），冒烟和 e2e 测试可直接调用。

> **不再需要**"提升私有函数为公共 API"或"在新文件中复制 `_markdown_to_html` / `_write_pdf` 实现"——这两条原备选方案在 S1-6 核验后被替代为更干净的"扩展 SUPPORTED_REPORT_TYPES"路径。

---

## 6. 三个新增 skill 的 SKILL.md 概要

> 旋转机组复用现有 `vibration-fault-diagnosis` skill，无需新建。下文仅给出新建 skill 的 SKILL.md 骨架与 references 目录骨架，规则细节不在本设计文档展开。

### 6.1 pump-fault-diagnosis（新建）

文件位置：`skills/custom/pump-fault-diagnosis/SKILL.md` + `references/diagnosis-rules.md`。

SKILL.md 概要：

- `name`: `pump-fault-diagnosis`
- `description`: 面向离心泵 / 多级离心泵 / 容积泵的振动 + 流量 + 压力 + 电机电流联动诊断
- `metadata.emoji`: 💧
- 覆盖设备类型：`centrifugal_pump` / `positive_displacement_pump`
- 覆盖故障家族（与 §4.4 `fd-pump-focus` 9 项 family 对齐；subtype 在报告内细化）：
  - 不平衡（叶轮失衡、积垢）
  - 不对中（联轴器、热膨胀）
  - 轴承损伤（subtype：滚动外环/内环/滚珠/保持架；滑动装配 / 间隙异常）
  - 汽蚀（含初生汽蚀与全工况汽蚀）
  - 密封泄漏（机械密封 / 填料密封）
  - 叶轮磨损 / 腐蚀
  - 流量低于最小连续流量（含再循环阀失效）
  - 共振（基础松动 / 管线共振 / 转速带共振）
  - 电机端联动（电流谐波 / 转矩脉动）

references/diagnosis-rules.md 章节骨架：

- 设备类型覆盖
- 故障家族总览
- 跨设备类型快速索引（按特征聚类）
- 离心泵 规则集合
- 容积泵 规则集合
- 工艺联动证据规则（流量 / 入出口压力 / 电流 / NPSH）
- 报告输出规则

### 6.2 reciprocating-fault-diagnosis（新建）

文件位置：`skills/custom/reciprocating-fault-diagnosis/SKILL.md` + `references/diagnosis-rules.md`。

SKILL.md 概要：

- `name`: `reciprocating-fault-diagnosis`
- `description`: 面向往复式压缩机 / 往复式泵的曲轴角对齐振动 + 缸压 + 阀门事件诊断
- `metadata.emoji`: 🔧
- 覆盖设备类型：`reciprocating_compressor` / `reciprocating_pump`
- 覆盖故障家族（与 §4.4 `fd-reciprocating-focus` 11 项 family 对齐；阀门 subtype 在报告内拆吸/排气）：
  - 阀门故障（吸气阀 / 排气阀；卡阀、片碎、密封不严）
  - 活塞环磨损（漏气率上升）
  - 十字头敲缸（曲轴角窗口冲击）
  - 连杆大端 / 小端轴承间隙
  - 活塞杆下沉
  - 缸压异常（吸/排气压力曲线偏移）
  - 卸荷阀异常（开合时序错位）
  - 轴承损伤
  - 不对中
  - 共振（机座 / 管线 / 缓冲罐）
  - 电机端联动（电流谐波 / 启停冲击）

references/diagnosis-rules.md 章节骨架：

- 设备类型覆盖
- 故障家族总览
- 曲轴角对齐特征聚类索引
- 往复式压缩机 规则集合
- 往复式泵 规则集合
- 阀门事件 / 缸压联动证据规则
- 报告输出规则

### 6.3 vibration-fault-diagnosis（复用）

无变更。`fault-diagnosis--rotating` 子 agent 通过 `skills` 字段挂载即可。校验项：

- skill 已存在并通过 SOUL 中"诊断规则参考"段引用了 `references/diagnosis-rules.md`。
- skill 的故障家族 code 与 §4.4 旋转机组 `focus_codes` 一一对应。

---

## 7. 数据契约

### 7.1 query_diagnosis.json 字段示例

```json
{
  "kind": "centrifugal_pump",
  "equipment_ids": ["PUMP-A-001"],
  "time_window": {"start": "2026-05-12T00:00:00", "end": "2026-05-13T12:00:00"},
  "compare_window": {"start": "2026-05-10T12:00:00", "end": "2026-05-12T00:00:00"},
  "mode": "oneoff",
  "data_source": "ins",
  "warnings": [],
  "points": [
    {
      "equipment_id": "PUMP-A-001",
      "point_id": "1801",
      "point_name": "驱动端 X 轴振",
      "point_type": 83,
      "default_features": ["pp_value", "rms", "one_freq_x", "one_freq_y", "two_freq_x", "two_freq_y", "half_freq"],
      "trend_summary": {
        "summary": "pp_value 持续上升，1X 主导",
        "notable_points": [
          {"feature": "pp_value", "time_ms": 1747033200000, "value": 38.7, "threshold": 35.0}
        ],
        "anomaly_time_ms": [1747033200000, 1747044000000]
      }
    }
  ],
  "process_signals": {
    "discharge_pressure": {"unit": "MPa", "series": [{"time_ms": 1747008000000, "value": 1.45}]},
    "suction_pressure":  {"unit": "MPa", "series": [{"time_ms": 1747008000000, "value": 0.32}]},
    "flow_rate":         {"unit": "m3/h", "series": [{"time_ms": 1747008000000, "value": 320.5}]},
    "motor_current":     {"unit": "A",    "series": [{"time_ms": 1747008000000, "value": 84.1}]}
  },
  "compare": null
}
```

### 7.2 diagnosis_features.json 字段示例

```json
{
  "report_meta": {
    "kind": "centrifugal_pump",
    "rules_skill": "pump-fault-diagnosis",
    "generated_at": "2026-05-13T12:30:00Z"
  },
  "equipment_summary": [
    {
      "equipment_id": "PUMP-A-001",
      "operation_phase": "steady_state",
      "max_value": {"point": "驱动端 X 轴振", "feature": "pp_value", "value": 38.7, "unit": "μm"},
      "alarm_status": "warning"
    }
  ],
  "evidence_chain": [
    {"category": "trend",   "point": "驱动端 X 轴振", "feature": "pp_value",   "value": 38.7, "threshold": 35.0, "verdict": "exceed"},
    {"category": "spectrum","point": "驱动端 X 轴振", "feature": "1X dominance","value": 0.78,"threshold": 0.6,  "verdict": "exceed"},
    {"category": "process", "point": "出口压力",      "feature": "rolling_std", "value": 0.12, "threshold": 0.08, "verdict": "exceed"}
  ],
  "trend_chart":   {"title": {"text": "驱动端轴振趋势"}, "xAxis": {"data": []}, "yAxis": {}, "series": []},
  "spectrum_charts": [{"point": "驱动端 X 轴振", "option": {"xAxis": {}, "yAxis": {}, "series": []}}],
  "orbit_charts":   [{"bearing": "驱动端轴承", "option": {"xAxis": {}, "yAxis": {}, "series": []}}],
  "rule_matches": [
    {
      "equipment_id": "PUMP-A-001",
      "kind": "centrifugal_pump",
      "fault_family": "unbalance",
      "fault_subtype": "impeller_initial_unbalance",
      "confidence": "medium",
      "supporting_evidence_indices": [0, 1],
      "missing_evidence": ["orbit_repeatability"]
    }
  ],
  "historical_cases": [
    {"equipment_id": "PUMP-A-007", "fault_family": "unbalance", "occurred_at": "2026-04-08", "summary": "高速动平衡后 pp_value 由 41 降至 18"}
  ],
  "recommendations": [
    "观察 24h 内 pp_value 是否突破 trip，若稳定则保持运行",
    "下次停机执行高速动平衡，检查叶轮积垢",
    "排查出口压力波动来源（再循环阀 / 工艺扰动）"
  ]
}
```

> **字段口径说明**：`evidence_chain` 是 LLM 生成 markdown 报告与 `table` Block 的唯一证据来源；`rule_matches[].supporting_evidence_indices` 引用 `evidence_chain` 的下标，避免重复描述。

---

## 8. 前端复用

经核查 [frontend/src/core/genui/registry.ts](../../frontend/src/core/genui/registry.ts) 已支持：

- `card` / `echart` / `table` / `markdown` / `form`

**无需新增前端组件**。下载链接通过 sandbox artifact URL 实现，已有 [uploads 路由](../../backend/app/gateway/routers/uploads.py) 支持文件读取。

复用映射：

| 章节 | GenUI Block | 数据来源 |
| ---- | ---- | ---- |
| 设备工况摘要 | `card`（一台设备一个） | `diagnosis_features.equipment_summary` |
| 关键测点趋势 | `echart`（line） | `diagnosis_features.trend_chart` |
| 频谱 | `echart`（bar） | `diagnosis_features.spectrum_charts[].option` |
| 轴心轨迹 | `echart`（scatter/line） | `diagnosis_features.orbit_charts[].option` |
| 证据链 | `table` | `diagnosis_features.evidence_chain` |
| 同类故障历史 | `card` | `diagnosis_features.historical_cases` |
| 诊断结论与建议 | `markdown` | LLM 基于 `rule_matches` + `evidence_chain` 渲染 |
| 下载链接 | `markdown`（追加在结论尾） | `export_diagnosis_report.py` 输出的 artifact URL |

---

## 9. 风险与应对

| 风险 | 影响 | 应对 |
| ---- | ---- | ---- |
| 往复机 InS 数据缺失（曲轴角对齐 / 缸压未接入 InS） | `fault-diagnosis--reciprocating` 主路径不可用 | `query_diagnosis.py` 在 `kind=reciprocating_*` 且 InS 返回字段不齐全时立即写入 `data_source=demo_fallback`，SOUL.md 在前端 `markdown` 顶部显式提示"当前为演示数据"，与日报演示数据告警保持一致 |
| PDF weasyprint 中文字体缺失 / sandbox 未装 weasyprint | PDF 导出失败 | **当前 sandbox 已确认 weasyprint / pandoc / wkhtmltopdf 均不可用**（见 [日报 Sprint Plan §3 Story 6 验证记录](./2026-05-13-ai-report-daily-sprint-plan.md)），本 Sprint **PDF 不作为承诺交付**，仅交付"自动降级路径就位"。SOUL 在 `try/except ImportError` 中追加 `PDF 不可用（weasyprint 未安装）`；`export_diagnosis_report.py` 直接复用 `_write_pdf`，等 sandbox 镜像装 weasyprint + 中文字体后无需改代码即生效 |
| `historical_cases[]` 在演示数据下永远造假 | 用户在生产模式下看到伪历史，诊断价值打折 | MVP 阶段：`diagnosis_features.json` 必须包含 `data_source ∈ {real_history, demo_fallback}` 标记；前端 `card` 标题前缀显示"演示"；上线时如真实历史故障案例库未接入，必须从 SOUL 中临时关闭"同类故障历史"`card` Block，避免误导 |
| 规则库与现场实际标准差异 | 误诊 / 漏诊 | 三类规则 skill 的 `references/diagnosis-rules.md` 在头部声明"用户提供版本号 / 修订日期"，明确不替代 OEM 标准；SOUL 输出强制要求"主诊断 + 至少一条差异诊断 + 缺失证据" |
| 设备多选与测点爆炸（>20 台 × 多测点 → token 失控） | LLM 上下文溢出 / 单次诊断超时 | Round 1.5 默认勾选最多 5 台；`query_diagnosis.py` 单次调用上限 N=10 设备 × 12 测点；超过时 `screening` 模式自动降级（仅 `pp_value/rms/1X` 三个特征） |
| 误报抑制（连续相同告警 / 短时抖动） | 报告噪声 | `diagnosis_features.py` 在 `evidence_chain` 加 `verdict ∈ {exceed, marginal, normal}`；`marginal` 不进入主诊断证据；连续 3 个同设备同 family 命中合并为一条 `historical_cases` |
| 跨子 agent 规则演化（共享术语漂移） | 三个 skill 故障 code 不一致 | 设计阶段强制对齐 §4.4 故障家族 code 列表；后续在 `data-analyst` 注册一份 `fault_family_codes.json` 由三个 skill 各自校验（Sprint 内不实现，列入 follow-up） |
| InS 工具链 503 / 网络抖动 | 主路径中断 | `query_diagnosis.py` 内部对每个 InS 调用做 1 次重试 + 5s 超时；失败时把错误堆栈写入 `warnings[]`，并继续走演示数据；SOUL 在最终 markdown 顶部显示警告 |
| group 升级与现有独立 agent `fault-diagnosis` 路由冲突 | 旧 thread 历史无入口 | 详见下文 §9.1 迁移策略 |

### 9.1 group 升级迁移策略

`fault-diagnosis` 从独立 agent 升级为 `type: group` 后：

- 父 group 节点不再承载会话功能；前端进入父节点时 SOUL 渲染一段 `markdown` 引导：「请从下方菜单选择 机泵 / 旋转机组 / 往复机 进入诊断」。
- 旧 thread（`thread_id` 关联到 `fault-diagnosis` 的）保留只读：用户可打开历史消息但不能继续发送，UI 提示「该会话由旧版故障诊断创建，请新建子 agent 会话」。后端不做强制迁移，避免误删数据。
- 新 thread 必须通过子 agent 入口创建：`fault-diagnosis--pump` / `fault-diagnosis--rotating` / `fault-diagnosis--reciprocating`。
- `order` 字段：当前 `fault-diagnosis` 为 `order: 1`，本设计建议 group 升级后保持 `order: 1`（"故障诊断"是一线诊断主入口），把 `anomaly-judgment` 调整或保留 `order: 2`。最终顺序由产品/UX 决定，本文档给出的 `order: 5` 为示例值，落地时按导航实际位置确认。
- 升级回滚预案：如发现旧 thread 因 group 化无法访问，仅需把 `fault-diagnosis/config.yaml` 中 `type: group` 行注释回 agent 形态，子 agent 会被发现器忽略；不会丢数据。

---

## 10. 与现有架构对齐检查

| 项 | 现有模式 | 本设计 | 状态 |
| ---- | ---- | ---- | ---- |
| Group 配置位置 | `agents/builtin/<group>/config.yaml` 含 `type: group` | `fault-diagnosis/config.yaml` 升级 `type: group` | OK |
| 子 Agent 配置位置 | `agents/builtin/<group>--<sub>/config.yaml` | `fault-diagnosis--{pump,rotating,reciprocating}/config.yaml` | OK |
| 子 Agent 发现 | 父 group 不显式声明，目录扫描 | 同 | OK |
| Skill 脚本位置 | `skills/custom/data-analyst/scripts/` | 同 | OK |
| 规则 Skill 位置 | `skills/custom/<skill>/SKILL.md` + `references/` | 同（pump-fault-diagnosis / reciprocating-fault-diagnosis 新增） | OK |
| 数据源发现优先级 | MCP → Skill → http_connector → demo_fallback | 同 | OK |
| 交互方式 | render_ui form + ui_interaction.payload 顶层 | 同（三轮表单 + 严禁复用更早回调） | OK |
| 渲染组件 | GenUI registry（card/echart/table/markdown/form） | 同（不新增组件） | OK |
| 文件下载 | sandbox `/mnt/user-data/outputs` + artifact URL | 同 | OK |
| 双格式导出 | Markdown 必需 + PDF weasyprint 自动降级 | Markdown 承诺；PDF 仅"降级路径就位"，sandbox 装 weasyprint 后零代码切换 | 对齐 |
| 导出调用方式 | SOUL in-process import（`from export_report import render_markdown, write_report`） | 同（`from export_diagnosis_report import render_diagnosis_markdown, write_diagnosis_report`） | 对齐 |
| 严禁结构化会话摘要 | 日报已强制 | 同（三个 SOUL.md 共性约束） | OK |
| 严禁复用更早轮次回调 | 日报已强制 | 同 | OK |
| 中间产物保护 | 不对 daily_kpi.json / daily_data.json 调 present_files | 不对 query_diagnosis.json / diagnosis_features.json 调 present_files | OK |
| LLM 流水线 | DeerFlowClient 标准流程 | 同（不改动 runtime） | OK |
| 后端改动 | 零 | 零后端代码改动 | OK |
| 前端改动 | 零 | 零前端代码改动 | OK |

---

## 11. 实施计划引用

具体实施排期、Story 拆分、依赖、验收标准与 Sprint Sequencing 见独立文档：[故障诊断智能体 Sprint 实施计划](./2026-05-18-fault-diagnosis-sprint-plan.md)。

## Context

监测分析 agent 现有 4 种分析类型（trend / anomaly / kpi_dashboard / correlation）都基于趋势数据（`getTrendDataHis` API，标量 KPI 时间序列），在 scope 回调中通过 `analysis_type` 枚举值调度到对应流水线。8k 端点（默认旋转机械）还提供波形/频谱原始数据（`getWaveDataHis` API）和轴心轨迹数据（`get_orbit_data`），系统已有 4 个对应技能和 Python 工具，但监测分析 agent 当前没有触发这些能力的入口。

故障诊断 agent（fault-diagnosis--rotating）已经在使用这些技能进行深度诊断，但其 SOUL.md 明确要求"最终报告彻底不要图谱"——图谱仅用于规则诊断内部。监测分析 agent 填补了这一空白：提供面向用户的图谱可视化与特征解读。

## Goals / Non-Goals

**Goals:**
- 新增 `spectrum` 分析类型，在 scope 表单的 `analysis_type` select 中增加选项
- 设计图谱分析流水线：先确定时间点/测点 → 调用现有技能获取波形/频谱 → ECharts 渲染 → 特征展示
- 在异常检测管线末尾增加"查看波形频谱"快捷入口（联动跳转）
- 图谱分析结果纳入 monitoring 报告导出，复用现有 `export_report.py`

**Non-Goals:**
- 不修改现有 4 个分析管线的逻辑
- 不创建新的 Python 工具或技能（复用 `ins-get-waveform-data`、`ins-extract-spectral-waveform-features`、`ins-get-orbit-data`、`ins-extract-orbit-centerline-features`）
- 不修改前端 GenUI 组件（仅使用现有 `form` / `echart` / `table` / `card` / `markdown` / `device-selector-multi`）
- 不修改 `export_report.py`（现有 monitoring 报告渲染已支持 chart + table + markdown 组合）
- 轴心轨迹为可选增强（`spectrum` 主能力覆盖波形+频谱即可，轨迹作为附加 deep-dive）

## Decisions

### Decision 1: 两步工作流（时间点选择 → 图谱展示）

**选择**: 两步交互流程

1. **Step S1（时间点选择）**: scope 回调校验通过后，首先跑一次轻量趋势查询获取候选时间点列表（异常时刻 + 均匀采样点），渲染表单让用户选择测点和时间点
2. **Step S2（图谱获取与展示）**: 用户提交时间点/测点选择后，调用 `ins-get-waveform-data` 获取原始数据，调用 `ins-extract-spectral-waveform-features` 提取特征，ECharts 渲染波形图+频谱图，table 展示特征

**原因**: 
- `getWaveDataHis` API 需要精确的毫秒时间戳，不能像趋势查询一样传日期范围
- 候选时间点必须来自趋势数据中真实存在的时间戳（技能文档明确要求："时间参数必须是趋势分析结果中已有的毫秒时间戳"）
- 用户可能需要从多个异常时刻中选择最关心的进行深挖

**备选方案**: 一步到位，用户在 scope 表单中直接输入时间。被否决——用户无法提前知道哪些时间点有数据，也无法判断哪个时刻最值得分析。

### Decision 2: 使用现有技能，编写新回调逻辑

**选择**: 在 SOUL.md 中新增 `monitor-spectrum-timestep` 回调和对应的流水线章节，bash 调用现有技能的 `run.sh` 脚本

**原因**:
- 4 个技能已完整封装了 InS API 调用和特征提取逻辑
- 不引入新的 Python 依赖或 Docker 镜像变更
- 与现有 4 个管线的 bash 调用模式一致

### Decision 3: ECharts 图表选型

**选择**:
- 波形图 → `echart` line chart: `series.type = "line"`, X 轴 = `wave_x` (时间 ms), Y 轴 = `wave_y` (振幅 μm)
- 频谱图 → `echart` bar chart: `series.type = "bar"`, X 轴 = `spec_x` (频率 Hz), Y 轴 = `spec_y` (幅值)，标注 1X/2X 位置
- 轨迹图 → `echart` scatter chart: `series.type = "scatter"`, X 探头幅值 × Y 探头幅值

**原因**: ECharts 原生支持这三种图表类型，无需扩展 GenUI。故障诊断 agent 虽不渲染图谱，但其诊断结果用到了同样的特征数据，说明数据格式已稳定。

### Decision 4: 异常检测联动入口

**选择**: 在异常检测管线末尾（A4 步骤之后），增加一个条件判断：如果检测到 ≥1 个异常点，渲染一个 `markdown` 提示"是否查看异常时刻的波形频谱？请选择 `spectrum` 分析类型重新分析。"

**原因**: 这是最低侵入性的联动方式，不需要修改前端 GenUI 路由。用户只需重新进入 scope 表单选择 spectrum 类型即可。未来可扩展为 `callback_id` 直接跳转，但当前保持简单。

### Decision 5: 8k 端点限制

**选择**: 图谱分析仅在 8k 端点系列（type 81-83 测点）可用。2k/6k/9k 设备不支持波形/频谱查询。

**原因**: `getWaveDataHis` 仅在 8k 端点系列（`/ins-os-view/sg8kData/getWaveDataHis`）可用。在 SOUL.md 中需要校验设备测点类型，对非 8k 设备给出明确的 `markdown` 提示。

## Risks / Trade-offs

- **[数据量] 波形原始数据可能包含数千个采样点** → ECharts 渲染大数据量 line/scatter 可能影响前端性能。缓解：在 SOUL.md 中指导对波形数据做降采样（每 N 个点取 1 个），目标渲染 ≤2000 个数据点。
- **[时间点依赖] 图谱分析强依赖趋势数据中的时间戳** → 如果趋势数据为空（设备无数据），图谱分析无法进行。缓解：Step S1 中先校验趋势数据是否存在，不存在则渲染 `markdown` 报错终止。
- **[工具链可用性] ins-get-waveform-data 和 ins-extract-spectral-waveform-features 都在 Docker sandbox 中运行** → 本地 sandbox 模式下不可用。缓解：与现有 data-analyst 脚本一致，INS 错误传播为 `markdown` 错误，不做 demo fallback。
- **[8k 限定] 图谱分析仅限 8k 旋转机械** → 2k/6k/9k 设备用户选择 spectrum 类型后会被拒绝。缓解：在 SOUL.md 中设备校验步骤明确提示，scope 表单 description 中注明"图谱分析仅支持 8k 旋转机械"。

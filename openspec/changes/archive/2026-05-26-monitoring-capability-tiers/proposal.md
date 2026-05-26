## Why

当前监测分析 Agent 的所有能力处于同一水平面——所有用户获得相同的线性回归、固定阈值 IQR、Pearson 相关。这不匹配 DeerFlow 作为平台型产品的定位：不同租户、不同场景对监测分析深度的需求差异巨大（日常巡检 vs 故障溯源 vs 预测性维护）。需要从系统能力角度，对监测分析的每一个业务功能定义 Basic / Pro / Ultra 三层，使 DeerFlow 的监测能力可分级、可售卖、可演进。

## What Changes

对监测分析域的全部 15 个业务功能，按三层定义系统能力：

### 数据与接入（3 项）

- **设备覆盖范围**：Basic 单次 ≤5 台 → Pro ≤50 台 + 分组 → Ultra 无限制 + 跨组织
- **数据接入**：Basic 仅趋势数据 → Pro +告警/事件 → Ultra +波形/频谱/外部数据源
- **数据质量**：Basic 无检查 → Pro 缺失检测 + 异常点标记 → Ultra 完整评分 + 自动插补

### 分析能力（5 项）

- **趋势分析**：Basic 线性回归 + 斜率 → Pro 多模型对比 + STL 分解 + 变点检测 → Ultra DL 预测 + 多变量协变 + 自适应阈值
- **异常检测**：Basic 固定阈值 + IQR → Pro Isolation Forest + DBSCAN + 滚动阈值 → Ultra Autoencoder + 多传感器交叉验证 + 根因排序
- **健康评估**：Basic 合规率 + 雷达图 → Pro 趋势 + 同类对比 + 加权评分 → Ultra 预测评分 + 风险排序矩阵
- **关联分析**：Basic Pearson 矩阵 → Pro Spearman/Kendall + 时滞 + 偏相关 → Ultra Granger 因果 + 传递熵 + 因果图
- **图谱分析**：Basic FFT 频谱 → Pro 包络/倒谱 + 轴承频率匹配 → Ultra CNN 分类 + 自动故障识别 + 演化追踪

### 运行与输出（4 项）

- **分析调度**：Basic 手动触发 → Pro 定时调度（日/周自动） → Ultra 事件驱动（异常自动触发深度分析）
- **结果呈现**：Basic 基础图表（线/柱/表） → Pro 增强图表（置信区间/标注） → Ultra 全景驾驶舱 + NL 解读
- **报告输出**：Basic Markdown 核心发现 → Pro +PDF + 证据链 → Ultra + 方法说明 + 行动计划
- **闭环联动**：Basic 手动建单 → Pro 严重异常自动建单 + SLA 跟踪 → Ultra 预测建单 + 复查调度 + 全链跟踪

### 交互与智能（3 项）

- **交互方式**：Basic 表单分步收集 → Pro 智能预填（按设备类型推荐参数） → Ultra 自然语言对话（"这台泵最近振动怎么样"）
- **历史对比**：Basic 无 → Pro 环比/同比 → Ultra 同类设备基准 + 行业基准
- **智能建议**：Basic 无 → Pro 规则匹配维护建议 → Ultra AI 行动建议 + 优先级 + 影响评估

每层能力通过**工具组门控**生效：`monitoring:pro` 和 `monitoring:ultra`，租户/Agent 级别独立控制。

## Capabilities

### New Capabilities

- `equipment-coverage-tiers`: 设备选择范围的分层能力——从 ≤5 台单次到无限制跨组织
- `data-access-tiers`: 数据源接入的分层能力——从单一趋势到全类型数据融合
- `data-quality-tiers`: 数据质量管理的分层能力——从无检查到完整评分与自动修复
- `trend-analysis-tiers`: 趋势分析的分层能力——从线性回归到深度学习预测
- `anomaly-detection-tiers`: 异常检测的分层能力——从固定阈值到 Autoencoder + 根因推理
- `health-assessment-tiers`: 健康评估的分层能力——从合规率到预测性风险排序
- `correlation-analysis-tiers`: 关联分析的分层能力——从 Pearson 矩阵到因果发现
- `spectrum-analysis-tiers`: 图谱分析的分层能力——从 FFT 到 CNN 故障识别
- `analysis-scheduling-tiers`: 分析调度的分层能力——从手动触发到事件驱动自动分析
- `result-presentation-tiers`: 结果呈现的分层能力——从基础图表到全景驾驶舱
- `report-output-tiers`: 报告输出的分层能力——从 Markdown 到多格式 + 行动计划
- `closure-integration-tiers`: 闭环联动的分层能力——从手动建单到预测性全链跟踪
- `interaction-mode-tiers`: 交互方式的分层能力——从表单分步到自然语言对话
- `historical-comparison-tiers`: 历史对比的分层能力——从无到行业基准对标
- `intelligent-recommendations-tiers`: 智能建议的分层能力——从无到 AI 优先级行动建议

### Modified Capabilities

无——本变更定义的是现有监测分析能力的纵向延伸，不修改 `openspec/specs/` 中已有 spec 的需求定义。

## Impact

- **Agent 文件**: `agents/builtin/monitoring-analysis/SOUL.md` — 每个分析流水线增加 Pro/Ultra 分支；交互流程增加智能预填和 NL 对话能力；调度逻辑增加定时和事件驱动模式
- **Skill 脚本**: `skills/custom/data-analyst/scripts/` 新增 ~15 个 Pro/Ultra 脚本（`pro_trend.py`, `ultra_trend.py`, `pro_anomaly.py`, `ultra_anomaly.py` 等）
- **Python 依赖**: Pro 需 `scikit-learn`, `statsmodels`, `ruptures`；Ultra 需 `onnxruntime` + 预训练模型文件
- **Sandbox 镜像**: `deer-flow-sandbox-features-tool` 需安装新依赖
- **配置**: `config.yaml` 新增 `monitoring:pro` 和 `monitoring:ultra` 工具组
- **前端**: 无变更——所有交互通过现有 GenUI 组件实现
- **报告**: `export_report.py` 扩展 `render_monitoring_markdown()` 支持 Pro/Ultra 新增字段

## 1. 基础设施：工具组门控与依赖

- [x] 1.1 在 `config.example.yaml` 新增 `monitoring:pro` 和 `monitoring:ultra` 工具组定义
- [x] 1.2 在 Agent 工具组解析逻辑中注册新工具组（`backend/` 侧）
- [x] 1.3 Sandbox Dockerfile 添加 Pro 依赖：`scikit-learn`, `statsmodels`, `ruptures`
- [x] 1.4 Sandbox Dockerfile 添加 Ultra 依赖：`onnxruntime`
- [x] 1.5 创建 `/opt/features-tool/models/` 目录，准备 ONNX 模型占位
- [x] 1.6 在 `monitoring-analysis/SOUL.md` 增加 `tool_groups` 能力门控分支代码

## 2. 数据与接入 — 设备覆盖 + 数据接入 + 数据质量

- [x] 2.1 实现 Pro 设备覆盖：`device-selector-multi` 的 `maxSelect` 提升至 50，按设备类型分组
- [x] 2.2 实现 Ultra 设备覆盖：支持 `queryParams.orgId=0` 跨组织设备查询
- [x] 2.3 实现 Pro 数据接入：`query_trend.py` 基础上并行拉取告警事件、启停事件
- [x] 2.4 实现 Ultra 数据接入：增加波形/频谱/轨迹数据拉取，合并为统一数据视图
- [x] 2.5 实现 Pro 数据质量：缺失值检测、±5σ 异常点标记、完整率计算
- [x] 2.6 实现 Ultra 数据质量：三维质量评分（完整性×一致性×时效性）、≤3 点线性插值

## 3. 分析能力 Pro — 趋势 + 异常

- [x] 3.1 创建 `pro_trend.py`：多模型回归（线性/多项式/指数）、R²_adj 选优、STL 分解、PELT 变点检测
- [x] 3.2 创建 `pro_anomaly.py`：Isolation Forest 多维检测、DBSCAN 聚类、自适应滚动阈值
- [x] 3.3 SOUL.md 增加 Pro 趋势分支：调用 `pro_trend.py`、渲染多模型对比图、STL 子图
- [x] 3.4 SOUL.md 增加 Pro 异常分支：调用 `pro_anomaly.py`、渲染聚类表、多维散点图

## 4. 分析能力 Pro — 健康 + 关联 + 图谱

- [x] 4.1 创建 `pro_kpi.py`：健康评分趋势、同类设备百分位对比、加权综合评分
- [x] 4.2 创建 `pro_correlation.py`：Spearman/Kendall 系数、时滞互相关(lag -7~+7)、偏相关
- [x] 4.3 创建 `pro_spectrum.py`：Hilbert 包络谱、倒谱、轴承故障频率匹配、边带检测
- [x] 4.4 SOUL.md 增加 Pro 健康分支、Pro 关联分支、Pro 图谱分支

## 5. 分析能力 Ultra — 趋势 + 异常

- [x] 5.1 准备 `trend_forecaster.onnx`：LSTM 多步预测模型（或 Holt-Winters+Theta 组合）
- [x] 5.2 创建 `ultra_trend.py`：ONNX 推理、80%/95% 置信区间、协变组检测、自适应阈值推荐
- [x] 5.3 准备 `anomaly_autoencoder.onnx`：重建误差异常评分模型
- [x] 5.4 创建 `ultra_anomaly.py`：Autoencoder 评分、多传感器交叉验证、故障签名模式匹配根因排序
- [x] 5.5 SOUL.md 增加 Ultra 趋势分支、Ultra 异常分支

## 6. 分析能力 Ultra — 健康 + 关联 + 图谱

- [x] 6.1 准备 `health_predictor.onnx`：30 天健康评分预测模型
- [x] 6.2 创建 `ultra_kpi.py`：预测性健康评分、风险排序（轨迹×关键性×不达标数）、风险矩阵数据
- [x] 6.3 创建 `ultra_correlation.py`：Granger 因果检验(lag 1-7)、传递熵、Graphical Lasso 因果图
- [x] 6.4 准备 `spectrum_classifier.onnx`：CNN 频谱故障分类模型
- [x] 6.5 创建 `ultra_spectrum.py`：CNN 分类、CNN+规则综合裁决、故障演化追踪
- [x] 6.6 SOUL.md 增加 Ultra 健康分支、Ultra 关联分支、Ultra 图谱分支

## 7. 运行与输出 — 调度 + 呈现 + 报告 + 闭环

- [x] 7.1 实现 Pro 调度：定时分析配置（日/周/月），对接现有调度基础设施
- [x] 7.2 实现 Ultra 调度：事件驱动分析（异常告警 → 自动触发深度分析），含去重限流
- [x] 7.3 扩展 SOUL.md Pro 呈现：置信区间、变点标注、模型对比叠加
- [x] 7.4 扩展 SOUL.md Ultra 呈现：全景驾驶舱（风险矩阵+健康仪表+异常表+趋势迷你图）+ NL 解读
- [x] 7.5 扩展 `export_report.py`：Pro 新增证据链和方法说明章节
- [x] 7.6 扩展 `export_report.py`：Ultra 新增模型可解释性和行动计划章节
- [x] 7.7 实现 Pro 闭环：`create_closure_ticket` 自动建单（severity=critical 或 high+confidence≥0.7）
- [x] 7.8 实现 Ultra 闭环：预测性建单（健康评分 30 天内将进入警戒区）、修复后复查调度

## 8. 交互与智能 — 交互 + 对比 + 建议

- [x] 8.1 实现 Pro 交互：按设备类型智能预填分析参数（指标、时间范围）
- [x] 8.2 实现 Ultra 交互：自然语言理解入口，推断分析意图（分析类型/指标/时间范围）
- [x] 8.3 实现 Pro 历史对比：环比/同比数据拉取和对比输出
- [x] 8.4 实现 Ultra 历史对比：同类设备基准 + 行业基准参考线
- [x] 8.5 实现 Pro 建议：规则表匹配维护建议（故障模式 → 建议动作）
- [x] 8.6 实现 Ultra 建议：LLM 生成优先级行动建议 + 影响评估

## 9. 优雅降级与测试

- [x] 9.1 Pro 脚本依赖缺失时返回 `DEPENDENCY_MISSING` 错误，Agent 降级到 Basic
- [x] 9.2 Ultra 脚本 ONNX 模型缺失时回退到 Pro 方法，标注 `model_fallback: true`
- [x] 9.3 回归测试：Basic 路径行为完全不变（运行现有 test suite）
- [x] 9.4 Pro 趋势 E2E：多模型对比 + STL + PELT
- [x] 9.5 Pro 异常 E2E：Isolation Forest + DBSCAN + 自适应阈值
- [x] 9.6 Ultra 趋势 E2E：LSTM 预测 + 协变组 + 阈值推荐
- [x] 9.7 Ultra 异常 E2E：Autoencoder + 交叉验证 + 根因排序
- [x] 9.8 Pro 健康 + 关联 + 图谱 E2E
- [x] 9.9 Ultra 健康 + 关联 + 图谱 E2E
- [x] 9.10 工具组门控测试：Pro/Ultra 禁用时回退到 Basic
- [x] 9.11 优雅降级测试：依赖缺失 / ONNX 缺失

## 10. 配置与文档

- [x] 10.1 更新 `config.example.yaml`：`monitoring:pro` 和 `monitoring:ultra` 工具组注释
- [x] 10.2 更新 `monitoring-analysis/config.yaml`：按能力等级区分 starter prompts
- [x] 10.3 如有新建独立脚本，更新 `report_scripts.yaml` 注册

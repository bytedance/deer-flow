# 机泵故障诊断

> **占位 SOUL**：本 SOUL 为 Sprint S1-1 的 placeholder，Story S1-7 将完整实现三轮 GenUI 表单 + 诊断输出 + Markdown 导出。当前用户进入仅看到本提示。

请等待 Story S1-7 上线，届时本 agent 将提供：

1. **Round 1（诊断范围）** — 时间窗（日期 + 整点小时）、设备类型（离心泵 / 容积泵）、诊断模式（一次性深度 / 快速筛查）、同期对比
2. **Round 1.5（设备 / 测点）** — 按区域分组的设备多选（默认 ≤5 台）、关键测点（轴振 X/Y、入/出口压力、流量、电机电流）
3. **Round 2（故障家族）** — 不平衡 / 不对中 / 轴承损伤 / 汽蚀 / 密封泄漏 / 叶轮磨损 / 流量低于最小连续流量 / 共振
4. **Round 3（诊断输出）** — 工况摘要 card + 趋势/频谱/轨迹 echart + 证据链 table + 同类故障历史 + 诊断结论 markdown + Markdown 下载（PDF 待 sandbox 镜像更新）

设计契约：

- 数据主路径：InS 工具链聚合趋势特征（脚本一次拉全） + LLM 按异常时间点稀疏深度采样
- 规则匹配：[pump-fault-diagnosis](../../../skills/custom/pump-fault-diagnosis/SKILL.md) skill（待 S1-3 创建）
- 导出：in-process import `from export_diagnosis_report import render_diagnosis_markdown, write_diagnosis_report`

> 完整设计：[docs/plans/2026-05-18-fault-diagnosis-design.md](../../../docs/plans/2026-05-18-fault-diagnosis-design.md)

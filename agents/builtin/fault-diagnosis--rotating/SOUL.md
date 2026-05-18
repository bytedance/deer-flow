# 旋转机组故障诊断

> **占位 SOUL**：本子 agent 计划在 **Sprint S2** 上线（Story S2-2）。当前菜单可见但功能未启用。

预计能力（S2 后）：

1. **Round 1（诊断范围）** — 时间窗、设备类型（汽轮机 / 离心压缩机 / 轴流压缩机 / 齿轮压缩机 / 螺杆压缩机 / 齿轮箱）、诊断模式、同期对比
2. **Round 1.5（设备 / 测点）** — 默认勾选两端轴振 X/Y + 轴位移 + 轴承温度 + 推力轴承温度 + 转速 + 工艺联动
3. **Round 2（故障家族）** — 不平衡 / 不对中 / 临界响应大 / 转子热弯曲 / 永久性弯曲 / 摩擦 / 旋转失速喘振 / 晃度 / 轴位移零点 / 轴承温度异常 等 12 项
4. **Round 3（诊断输出）** — 工况摘要 + 趋势/频谱/轨迹 + 证据链 + 同类故障历史 + 诊断结论 + 双格式导出

规则匹配：复用现有 [vibration-fault-diagnosis](../../../skills/custom/vibration-fault-diagnosis/SKILL.md) skill。

> 完整设计：[docs/plans/2026-05-18-fault-diagnosis-design.md](../../../docs/plans/2026-05-18-fault-diagnosis-design.md)
> Sprint 计划：[docs/plans/2026-05-18-fault-diagnosis-sprint-plan.md](../../../docs/plans/2026-05-18-fault-diagnosis-sprint-plan.md) §2.3 Story S2-2

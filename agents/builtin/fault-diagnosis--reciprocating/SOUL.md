# 往复机故障诊断

> **占位 SOUL**：本子 agent 计划在 **Sprint S2** 上线（Story S2-3）。当前菜单可见但功能未启用。

预计能力（S2 后）：

1. **Round 1（诊断范围）** — 时间窗、设备类型（往复式压缩机 / 往复式泵）、诊断模式、同期对比
2. **Round 1.5（设备 / 测点）** — 默认勾选曲轴角对齐振动 + 缸压 + 卸荷阀状态 + 阀门事件 + 活塞杆下沉 + 电机电流
3. **Round 2（故障家族）** — 吸气阀故障 / 排气阀故障 / 活塞环磨损 / 十字头敲缸 / 连杆轴承间隙 / 活塞杆下沉 / 缸压异常 / 卸荷阀异常 / 不对中 / 共振 等 11 项
4. **Round 3（诊断输出）** — 工况摘要 + 趋势/频谱（无 orbit）+ 证据链（含 crank_angle / cylinder_pressure / valve_event）+ 诊断结论 + 双格式导出

规则匹配：[reciprocating-fault-diagnosis](../../../skills/custom/reciprocating-fault-diagnosis/SKILL.md) skill（待 S2-1 创建）。

> 完整设计：[docs/plans/2026-05-18-fault-diagnosis-design.md](../../../docs/plans/2026-05-18-fault-diagnosis-design.md)
> Sprint 计划：[docs/plans/2026-05-18-fault-diagnosis-sprint-plan.md](../../../docs/plans/2026-05-18-fault-diagnosis-sprint-plan.md) §2.3 Story S2-3

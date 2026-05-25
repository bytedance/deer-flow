## Why

当前能力矩阵中的"建议 owner"仍是临时分工，模块没有明确的 Core/Scale-Up/Stabilize/Incubate 状态结论，Q3 投资方向缺乏明确判断依据。没有真实 owner 的模块在隐性漂浮，排期和月度评审时缺少可靠的责任归属。在 ISSUE-01 收敛了主对象模型后，需要立即把组织和治理层面的 owner 和状态固化下来。

## What Changes

- 能力矩阵中的每个模块都有真实业务 owner 和技术 owner
- 每个模块标注当前状态（Core / Scale-Up / Stabilize / Incubate）和本周期投资结论
- 仍未定责的模块被显式列为管理风险
- 结论可直接用于月度评审和排期，不只是讨论材料

## Capabilities

### New Capabilities

- `module-ownership-register`: 每个模块的真实业务 owner 和技术 owner 台账
- `module-status-classification`: 每个模块的 Core/Scale-Up/Stabilize/Incubate 分类和投资结论
- `ownership-risk-tracking`: 未定责模块的管理风险清单和跟踪机制

### Modified Capabilities

<!-- 本 change 为治理对齐类任务，不直接修改 spec -->

## Impact

- 影响所有模块的排期和资源分配
- 月度评审将直接引用此结论
- 后续 ISSUE-09（平台能力配置模型）依赖此 owner 台账

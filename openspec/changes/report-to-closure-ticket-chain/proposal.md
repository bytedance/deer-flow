## Why

报告结果、诊断结论和关键风险项当前无法转成可追踪的闭环工单。用户看到了问题但无法转化为处理动作，导致"发现问题→处理问题"的闭环断裂。需要建立从报告结果到闭环工单的最小可追溯链路，形成"结果产生 → 触发处理 → 状态流转 → 回看来源"的完整闭环。

## What Changes

- 用户可从报告或诊断结果创建闭环工单
- 工单能回溯到触发它的报告结果或诊断上下文
- 工单状态变化不会丢失来源和处理责任信息
- 至少有一条从结果到工单再回看的验证路径

## Capabilities

### New Capabilities

- `report-to-ticket-creation`: 从报告/诊断结果创建闭环工单的能力
- `ticket-source-traceability`: 工单回溯到触发源（报告结果/诊断上下文）的能力
- `ticket-state-preservation`: 工单状态流转中保留来源和处理责任信息

### Modified Capabilities

<!-- 可能涉及 closed-loop-tickets 的创建流程 -->

## Impact

- 影响报告详情页、诊断结果页的工单创建入口
- 影响 closed-loop-tickets 的数据模型和创建接口
- 依赖 ISSUE-07（报告可追踪链路）和 ISSUE-08（统一错误语义）

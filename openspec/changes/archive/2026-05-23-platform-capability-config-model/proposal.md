## Why

DeerFlow 当前的模型、Skills、MCP、Connector、Agent 五类能力各自独立管理，缺少统一的配置词汇表、发布口径和审计要求。配置者需要在多套不一致的页面和接口间理解能力关系，租户级和全局级边界模糊。在 ISSUE-05 固化 owner 和模块状态后，需要先拍板统一的治理模型，再进入配置面实现。

## What Changes

- 五类能力有统一的配置与发布词汇表
- 明确哪些字段是全局级、哪些是租户级、哪些需要审计
- 明确每类能力的发布、回滚、停用和变更责任
- 评审结论可直接指导后续配置面和接口实现（ISSUE-10, ISSUE-11）

## Capabilities

### New Capabilities

- `capability-config-vocabulary`: 五类能力的统一配置词汇表和命名规范
- `capability-scope-definition`: 全局级 vs 租户级字段的边界定义
- `capability-lifecycle-governance`: 每类能力的发布、回滚、停用和变更责任规则

### Modified Capabilities

<!-- HITL 类型，不直接修改 spec -->

## Impact

- 决定后续 ISSUE-10（统一配置视图）和 ISSUE-11（租户/全局边界）的实现方向
- 影响所有能力类模块的接口设计和数据模型
- 依赖 ISSUE-05（owner 台账）

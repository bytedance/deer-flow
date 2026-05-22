## Why

当前租户级能力与全局级能力的启用、继承、覆盖、停用和审计路径不明确。一个能力什么时候是平台共用、什么时候是租户私有、变更后影响谁、谁来回滚——这些问题没有清晰答案。在 ISSUE-09 定版配置模型和 ISSUE-10 交付配置视图后，需要将租户与全局的发布边界固化下来。

## What Changes

- 全局能力与租户能力的边界有明确规则
- 能力发布、覆盖、停用的影响范围可被解释和追踪
- 关键变更具备审计记录或等价的追责手段
- 至少有一条租户启用能力的验证路径

## Capabilities

### New Capabilities

- `capability-scope-boundary-rules`: 全局与租户能力的启用、继承、覆盖、停用规则
- `capability-change-impact-tracking`: 能力变更的影响范围追踪与审计
- `tenant-capability-enablement-path`: 租户启用能力的端到端验证路径

### Modified Capabilities

<!-- 一期独立构建，不修改现有 spec -->

## Impact

- 影响所有能力的发布和变更流程
- 需要实现能力继承和覆盖逻辑
- 依赖 ISSUE-09（配置模型）和 ISSUE-10（配置视图）

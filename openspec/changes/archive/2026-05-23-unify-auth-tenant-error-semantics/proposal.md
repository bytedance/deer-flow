## Why

当前认证失败、权限不足、租户配置错误、外部认证服务不可用等场景的错误语义、状态码和用户提示不统一。治理层错误常被误报成业务失败（如将上游 auth 不可用显示为"操作失败"），用户无法区分"我的凭证错了"和"系统暂时不可用"。需要统一这些场景的错误分型，让失败可诊断、可恢复、可升级。

## What Changes

- 用户可区分无效令牌、无权限、租户配置问题和上游不可用
- API 状态码与错误码在主要入口保持一致
- 日志和监控可反映根因，而非只记录表面异常
- 常见 401、403、503 场景有回归测试或验收清单

## Capabilities

### New Capabilities

- `auth-tenant-error-taxonomy`: 统一的认证、租户和外部依赖错误分类体系
- `error-code-consistency`: 所有入口的 API 状态码与错误码一致性
- `auth-error-regression-coverage`: 401/403/503 场景的回归测试覆盖

### Modified Capabilities

<!-- 可能影响现有 user-auth、ins-base-org-tenant-resolution 中已有的错误处理 -->

## Impact

- 影响所有涉及认证和租户解析的 API 入口
- 影响网关层的错误透传逻辑
- 依赖 ISSUE-02（统一状态语义）和 ISSUE-05（owner 台账）

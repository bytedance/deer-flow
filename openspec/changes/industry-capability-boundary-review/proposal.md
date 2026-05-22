## Why

当前 InS 认证、组织、设备、行业报表、诊断链路等能力与通用平台边界模糊，行业能力无边界地耦合进 Core Platform。这导致通用平台变更时行业功能意外受损，行业扩展时污染平台基线。需要进行正式边界评审，明确哪些属于 Core Platform、Enterprise Control Plane、Industry Solution Layer。

## What Changes

- 当前行业相关能力都有明确的层级归属
- 无法归属或争议较大的能力被列成待决清单
- 评审结论能直接指导后续目录、发布和 owner 归属
- 形成一版可供管理层和架构评审使用的分层结论

## Capabilities

### New Capabilities

- `industry-capability-layer-classification`: 行业能力层级归属（Core Platform / Enterprise Control Plane / Industry Solution Layer）
- `boundary-dispute-register`: 无法归属或争议较大的待决能力清单

### Modified Capabilities

<!-- HITL 类评审任务，不直接修改 spec -->

## Impact

- 决定后续行业能力的开发、归属和发布方式
- 直接影响 ISSUE-14（三层产品结构）和 ISSUE-15（交付方式）
- 依赖 ISSUE-05（owner 台账）和 ISSUE-09（配置模型）

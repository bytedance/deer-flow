## Why

当前知识检索链路缺乏可观测性基线——索引成功率、重建完成率、检索延迟和质量指标没有统一收集和展示。团队无法回答"知识链路是否在稳定支持主流程"这个基本问题，月度评审依赖主观判断而非数据。在 ISSUE-04 打通了知识主链后，需要立即建立可观测性基线以持续度量其健康度。

## What Changes

- 定义并落地一组可持续跟踪的知识链路指标（索引成功率、重建完成率、检索延迟、结果质量代理指标、失败原因分类）
- 支持按知识库或任务粒度定位索引失败和检索异常
- 输出一版面向运营或技术 owner 的观察口径与阈值建议
- 月度评审可直接引用这些指标

## Capabilities

### New Capabilities

- `knowledge-link-metrics`: 知识链路核心指标的定义、采集和展示
- `index-retrieval-anomaly-detection`: 按知识库/任务粒度定位索引失败和检索异常
- `knowledge-observability-thresholds`: 运营观察口径与阈值建议

### Modified Capabilities

<!-- 不涉及现有 spec 的需求变更 -->

## Impact

- 需要索引和检索链路增加指标采集点
- 影响月度评审的数据来源和决策方式
- 依赖 ISSUE-04（知识主链）和 ISSUE-05（owner 台账）

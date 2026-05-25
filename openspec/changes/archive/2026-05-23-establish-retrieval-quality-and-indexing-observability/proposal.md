## Why

当前知识链路（上传→索引→检索→报告消费）的稳定性判断完全依赖口头经验——没有可持续跟踪的指标、没有失败分类基线、没有按知识库或任务粒度的异常定位能力。月度评审时无法用数据回答"知识链路是否稳定支持主流程"，只能靠印象。6 月路线图目标 B 要求建立平台治理层，知识链路的可观测性是治理的基础前提。

## What Changes

- 定义并落地一组知识链路核心指标：索引成功率、重建完成率、检索延迟、失败原因分类
- 在现有 `GET /api/knowledge-bases` 和 `GET /api/knowledge-bases/{id}` API 中增加索引状态和基础计数指标
- 新增 `GET /api/knowledge-bases/{id}/index-stats` 端点，按知识库粒度返回索引统计（总数、成功、失败、进行中、平均延迟）
- 后端增加索引失败的分类计数器，按失败类型（EMPTY_RESULT、ENCRYPTED_PDF、UNSUPPORTED_FORMAT 等）分组
- 前端知识库列表和详情页展示基础指标（文档数、索引完成率、最近失败原因）
- 新增一份面向运营/技术 owner 的指标口径文档，定义各指标的计算方式和建议告警阈值

## Capabilities

### New Capabilities
- `indexing-observability`: 索引可观测性——索引成功率、失败分类、按知识库粒度的统计端点和前端展示
- `retrieval-quality-baseline`: 检索质量基线——检索延迟指标、按知识库维度的查询统计和异常定位

### Modified Capabilities
- `upload-index-pipeline-visibility`: 在现有上传到索引状态可见基础上，增加按知识库聚合的统计指标和失败分类计数

## Impact

- 后端：`app/gateway/routers/knowledge_bases.py`（新增 index-stats 端点）、`packages/harness/deerflow/knowledge_base/` 相关模块
- 前端：知识库列表和详情页面增加指标展示
- 文档：新增 `docs/observability/knowledge-metrics.md` 指标口径文档
- 不涉及破坏性变更

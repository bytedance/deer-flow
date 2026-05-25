## Context

当前知识库后端已经具备较完整的索引流水线（`IndexingDispatcher` → `IndexingService` → `IndexJobRepository`），文档有 `index_status` 字段（pending/indexing/ready/failed），job 表记录了每次索引尝试的状态和错误信息。但这些数据需要手动查数据库才能获取——没有 API 端点暴露聚合指标，没有失败分类维度，运维和技术 owner 无法快速回答"知识库整体健康度如何"。

ISSUE-04 已完成上传到报告的端到端链路，ISSUE-05 已确认知识域 owner。现在需要把已有的索引数据转成可观测指标。

## Goals / Non-Goals

**Goals:**
- 新增按知识库粒度的索引统计 API（`GET /api/knowledge-bases/{id}/index-stats`）
- 在知识库列表/详情 API 中附加基础指标（文档数、索引完成率）
- 索引失败按错误类型自动分类（ConversionErrorCode + EmbeddingDimensionMismatch + RuntimeError）
- 前端知识库详情页展示索引健康面板
- 输出一份指标口径文档

**Non-Goals:**
- 不引入 Prometheus/OTel/Grafana（保持与 report telemetry 一致的内存收集器模式）
- 不修改 Chroma/向量存储内部逻辑
- 不新增检索质量自动评分（那是更后期的需求）
- 不修改索引调度策略

## Decisions

### 决策 1：指标收集器采用内存 + JSONL 模式（复用 report telemetry 模式）

已有的 `report_templates/telemetry.py` 提供了 `TelemetryCollector` 模式——线程安全的内存计数器 + JSONL 日志。知识链路指标复用同一模式，新建 `knowledge_base/telemetry.py`。

理由：一致性，零外部依赖，可离线重建。

### 决策 2：API 设计——扩展现有端点 + 一个新增端点

**扩展现有端点：**
- `GET /api/knowledge-bases` 列表项新增 `document_count`、`indexed_count`、`indexing_count`、`failed_count`
- `GET /api/knowledge-bases/{id}` 详情新增上述字段 + `last_indexed_at`、`recent_failures`（最近 5 条失败）

**新增端点：**
- `GET /api/knowledge-bases/{id}/index-stats` → `{total, ready, pending, indexing, failed, cancelled, failure_by_type: {code: count}, avg_index_duration_ms, recent_jobs: [...]}`

理由：列表/详情附基础指标减少请求数；独立 stats 端点承载详细统计。

### 决策 3：失败分类策略

失败原因从两个来源提取：
1. `index_job.error` 字段的正则匹配 → 映射到固定分类（`EMPTY_RESULT`、`ENCRYPTED_PDF`、`UNSUPPORTED_FORMAT`、`DIMENSION_MISMATCH`、`INTERNAL_ERROR`）
2. 匹配不上时归类为 `OTHER`

不修改现有 error 存储逻辑，只在上层做分类。

### 决策 4：前端展示——知识库详情页新增"索引健康"面板

在现有知识库详情页增加一个卡片区域，显示：
- 环形或进度条展示索引完成率
- 按状态的文档计数
- 最近失败列表（含失败类型和文档名）

不引入新的图表依赖，用简单的数字 + 进度条。

## Risks / Trade-offs

- [风险] index-stats 端点在大知识库下 COUNT 查询可能慢 → 对 document 表加 `(knowledge_base_id, index_status)` 复合索引（通常已有）
- [取舍] 先用内存收集器，不考虑持久化时序数据库 → 重启丢失计数器，但 JSONL 文件可以离线重建
- [取舍] 不实时推送指标变化 → 前端轮询或手动刷新即可满足当前需求

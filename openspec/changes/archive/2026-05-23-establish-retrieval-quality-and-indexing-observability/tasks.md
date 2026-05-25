## 1. 后端 — 索引统计 API

- [x] 1.1 新增 `GET /api/knowledge-bases/{id}/index-stats` 端点，返回 `{total, ready, pending, indexing, failed, cancelled, failure_by_type, avg_index_duration_ms, recent_jobs}`
- [x] 1.2 扩展 `GET /api/knowledge-bases` 列表响应，每项新增 `document_count`、`indexed_count`、`failed_count`
- [x] 1.3 扩展 `GET /api/knowledge-bases/{id}` 详情响应，新增 `document_count`、`indexed_count`、`indexing_count`、`failed_count`、`last_indexed_at`、`recent_failures`
- [x] 1.4 在 `IndexJobRepository` 中增加按知识库聚合的统计查询方法

## 2. 后端 — 失败分类

- [x] 2.1 新增 `index_error_classifier.py`：从 `index_job.error` 提取已知 ConversionErrorCode、DIMENSION_MISMATCH，其余归 OTHER
- [x] 2.2 在 `GET /api/knowledge-bases/{id}/index-stats` 中集成失败分类，返回 `failure_by_type` 计数

## 3. 后端 — 检索延迟追踪

- [x] 3.1 在检索路径（`search_knowledge_base` 工具或 RAG 检索函数）增加延迟记录：计时并写入内存收集器
- [x] 3.2 在 index-stats 端点中附加 `avg_retrieval_latency_ms`、`p95_retrieval_latency_ms`、`total_queries` 字段

## 4. 后端 — 指标收集器

- [x] 4.1 新建 `knowledge_base/telemetry.py`：内存收集器 + JSONL 日志（复用 report telemetry 模式），记录索引事件（success/fail/cancel）和检索事件（query latency）
- [x] 4.2 在 IndexingService 和 Dispatcher 中接入收集器，索引成功/失败/取消时触发事件

## 5. 前端 — 索引健康面板

- [x] 5.1 在知识库详情页新增"索引健康"卡片，展示完成率、按状态计数、最近失败列表
- [x] 5.2 在知识库列表页展示文档数和失败数徽标
- [x] 5.3 更新前端 TypeScript 类型定义（`KnowledgeBaseResponse` 扩展）

## 6. 文档 — 指标口径

- [x] 6.1 创建 `docs/observability/knowledge-metrics.md`：定义各指标的计算方式、数据来源、建议告警阈值
- [x] 6.2 在文档中明确月度评审可直接引用的指标清单和查询方式

## 7. 测试

- [x] 7.1 新增 `test_kb_index_stats_api.py`：验证 index-stats 端点各字段正确性
- [x] 7.2 新增 `test_index_error_classifier.py`：验证各类错误被正确分类
- [x] 7.3 运行全量测试套件，确保无回归

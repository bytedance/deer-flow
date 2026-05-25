# 知识库索引与检索可观测性指标

> 面向月度评审和技术运营，定义知识库管线的关键指标、计算方式、数据来源和建议告警阈值。

## 指标总览

| 指标 | 类型 | 数据来源 | 更新频率 |
|------|------|----------|----------|
| 索引完成率 | 健康度 | `KnowledgeBaseDocument.index_status` | 实时（API 查询时聚合） |
| 按状态分布 | 健康度 | `KnowledgeBaseDocument.index_status` GROUP BY | 实时 |
| 失败分类分布 | 健康度 | `IndexJob.error` + `index_error_classifier` | 实时 |
| 平均索引耗时 | 性能 | `IndexJob.finished_at - IndexJob.started_at` | 实时（最近完成作业） |
| 检索 P95 延迟 | 性能 | `KbTelemetryCollector` 内存统计 | 近实时（内存滑动窗口） |
| 检索次数 | 用量 | `KbTelemetryCollector` 计数器 | 近实时 |

## 1. 索引完成率

**定义**：`ready_count / total_count * 100`，其中 `total_count` 为知识库下所有未删除文档数。

**计算方式**：
```
SELECT index_status, COUNT(*) FROM knowledge_base_documents
WHERE knowledge_base_id = :kb_id AND deleted_at IS NULL
GROUP BY index_status
```

**告警阈值建议**：
- **Warning**：完成率 < 90%（存在较多 pending/indexing/failed 文档）
- **Critical**：完成率 < 70% 或 failed_count > 0 超过 24 小时

**月度评审关注点**：
- 长期 pending 文档数 — 可能是 dispatcher 资源不足
- failed 文档趋势 — 是否上升，失败原因分类

## 2. 按状态分布

**定义**：文档在 `pending`、`indexing`、`ready`、`failed`、`cancelled` 各状态的计数。

**API 端点**：`GET /api/knowledge-bases/{id}/index-stats`

**响应字段**：`total`, `ready`, `pending`, `indexing`, `failed`, `cancelled`

**月度评审关注点**：
- `cancelled` 数量高 → 频繁的版本冲突，可能是并发编辑问题
- `pending` 堆积 → dispatcher worker 不足或作业队列阻塞

## 3. 失败分类分布

**定义**：将索引失败的 `IndexJob.error` 按关键词分类为标准化类别。

**分类类别**（来自 `index_error_classifier.py`）：

| 类别 | 匹配关键词 | 含义 |
|------|-----------|------|
| `EMPTY_RESULT` | empty_result, no text, no content | 文档转换后无有效文本 |
| `ENCRYPTED_PDF` | encrypted_pdf, encrypted | PDF 加密无法读取 |
| `UNSUPPORTED_FORMAT` | unsupported_format, unsupported file | 不支持的文件格式 |
| `MARKITDOWN_UNAVAILABLE` | markitdown_unavailable | 文档转换工具不可用 |
| `DIMENSION_MISMATCH` | dimension mismatch, embedding dimension | Embedding 维度不匹配 |
| `INTERNAL_ERROR` | internal_error | 内部错误 |
| `OTHER` | （默认） | 未分类错误 |

**API 响应字段**：`failure_by_type`（`dict[str, int]`）

**告警阈值建议**：
- `DIMENSION_MISMATCH` 出现 → **立即告警**，说明存在 embedding model 配置不一致
- `MARKITDOWN_UNAVAILABLE` 出现 → **Critical**，文档转换服务不可用
- `EMPTY_RESULT` 占比 > 20% → **Warning**，用户可能在上传扫描件

**月度评审关注点**：
- `failure_by_type` 分布变化趋势
- 新出现的失败类别

## 4. 平均索引耗时

**定义**：最近完成的索引作业的平均耗时（毫秒）。

**计算方式**：选取最近 N 条 `status='completed'` 的 `IndexJob`，计算 `(finished_at - started_at)` 的平均值。

**API 响应字段**：`avg_index_duration_ms`

**告警阈值建议**：
- **Warning**：平均耗时 > 30s
- **Critical**：平均耗时 > 120s

**月度评审关注点**：
- 耗时趋势 — 是否随文档量增加而线性增长
- 与大模型 embedding API 延迟的关联

## 5. 检索延迟

**定义**：知识库检索（向量搜索 + 可能的 rerank）的延迟分布。

**计算方式**：
- 每次检索调用记录 `(time.monotonic() - t0) * 1000` 到 `KbTelemetryCollector`
- 保留最近 1000 条样本的滑动窗口
- P95：排序后取 95 分位

**API 响应字段**：`avg_retrieval_latency_ms`, `p95_retrieval_latency_ms`, `total_queries`

**告警阈值建议**：
- **Warning**：P95 > 2000ms
- **Critical**：P95 > 5000ms

**月度评审关注点**：
- 检索延迟是否随文档/分块数增长
- 与 Chroma 后端性能的关联

## 6. 检索次数

**定义**：知识库被检索的总次数（自上次进程重启以来）。

**数据来源**：`KbTelemetryCollector` 内存计数器。

**API 响应字段**：`total_queries`

**注意**：此计数为进程内内存计数，进程重启后归零。如需长期统计，使用 JSONL 日志回放。

## 数据采集架构

```
KnowledgeBaseService.search()
  ├── 计时 → KbTelemetryCollector.record_latency()
  └── 事件 → KbTelemetryCollector.record_event("search")

IndexingService.execute_index_job()
  ├── 成功 → record_event("index_success")
  ├── 失败 → record_event("index_failed") + classify_index_error()
  └── 取消 → record_event("index_cancelled")

GET /api/knowledge-bases/{id}/index-stats
  ├── DocumentRepository.count_docs_by_status_for_kb()  → 状态计数
  ├── IndexJobRepository.stats_by_kb()                   → 作业统计
  ├── IndexJobRepository.failed_jobs_by_kb()             → 失败详情
  ├── classify_failures()                                → 失败分类
  └── KbTelemetryCollector.latency_stats()               → 检索延迟
```

## 月度评审引用指南

评审时可直接使用以下 API 查询：

```bash
# 索引健康概览
curl -H "X-Tenant-Id: <tid>" http://localhost:8001/api/knowledge-bases/<kb_id>/index-stats

# 知识库列表（含 indexed_count / failed_count）
curl -H "X-Tenant-Id: <tid>" http://localhost:8001/api/knowledge-bases
```

关注指标：
1. `failed / total` — 失败率
2. `failure_by_type` — 失败原因分布
3. `avg_index_duration_ms` — 索引性能
4. `p95_retrieval_latency_ms` — 检索性能
5. `total_queries` — 使用活跃度

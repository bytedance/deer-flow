# 知识链路核心指标

> 面向月度评审和日常运营的知识链路可观测性指标定义。

## 1. 索引成功率

**口径**：`ready / total`（仅计入有效文档，不含已删除）

**计算公式**：
```
index_success_rate = count_docs(status=ready) / count_docs(not deleted)
```

**数据来源**：`KnowledgeBaseDocumentRow.index_status`，通过 `DocumentRepository.count_docs_by_status_for_kb()` 查询。

## 2. 重建完成率

**口径**：最近一次重建任务中 `ready / (ready + failed)`，仅在有重建任务的 KB 上计算。

**数据来源**：`IndexJobRow` 表，通过 `IndexJobRepository.stats_by_kb()` 聚合。

## 3. 检索延迟

**口径**：单次检索的端到端耗时（毫秒），按知识库维度分桶记录。

**分位数**：`avg_ms`、`p95_ms`

**数据来源**：`KbTelemetryCollector.record_latency(kb_id, latency_ms)`，内存收集器保留最近 1000 条/知识库。

## 4. 结果质量代理指标

**口径**：以检索命中数（total_results）和 KB 覆盖数（kb_count）作为质量代理。

**数据来源**：`KbTelemetryCollector.record_event("retrieval.completed", {total_results, kb_count, per_kb_hits})`

## 5. 失败原因分类

| 类别 | 含义 | 触发关键词 |
|------|------|-----------|
| `EMPTY_RESULT` | 文档内容为空 | empty_result, no text, no content |
| `ENCRYPTED_PDF` | PDF 加密不可读 | encrypted_pdf, encrypted |
| `UNSUPPORTED_FORMAT` | 不支持的文件格式 | unsupported_format, unsupported file |
| `MARKITDOWN_UNAVAILABLE` | MarkItDown 不可用 | markitdown_unavailable |
| `DIMENSION_MISMATCH` | Embedding 维度不匹配 | dimension mismatch, embedding dimension |
| `INTERNAL_ERROR` | 内部处理错误 | internal_error |
| `OTHER` | 其他未分类错误 | (fallback) |

**分类函数**：`classify_index_error()` in `index_error_classifier.py`

## 6. 采集方式

- **埋点模式**：异步内存收集器 + 可选 JSONL 持久化
- **收集器**：`KbTelemetryCollector`（thread-safe 单例）
- **事件类型**：`index_success`、`index_failed`、`index_cancelled`、`retrieval.completed`、`retrieval.timeout`、`retrieval.failed`、`retrieval.blocked`

## 7. 接口

| 接口 | 粒度 | 用途 |
|------|------|------|
| `GET /api/knowledge-bases/{kb_id}/index-stats` | 单 KB | 技术视图 + 下钻 |
| `GET /api/knowledge-bases/health-summary` | 全租户 | 运营视图 |
| `listKnowledgeBases()` 返回含 `indexed_count`/`failed_count` | 列表 | 概览卡片 |

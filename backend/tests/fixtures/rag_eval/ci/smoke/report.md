# RAG 检索评估报告

- top_k: 5 · candidate_limit: 20 · 题目数: 24 · generated_at: 2026-10-07T17:26:22+00:00
- 阈值均为初始拍值（回退 3%），跑两周后按实际抖动校准（spec §4）
- parse_provider: mineru-cloud
- chunker: structure-max1024/min100/cl100k_base
- embedding_model: qwen3.7-text-embedding-flash
- embedding_dimension: 1024
- embedding_sparse_source: provider
- rerank_model: qwen3.7-text-rerank
- rerank_provider: dashscope

## 汇总

| scope | count | hit_rate | recall | mrr | path_acc |
|---|---|---|---|---|---|
| overall | 24 | 1.000 | 1.000 | 0.979 | 1.000 |
| text | 20 | 1.000 | 1.000 | 1.000 | 1.000 |
| table | 2 | 1.000 | 1.000 | 1.000 | 1.000 |
| image | 2 | 1.000 | 1.000 | 0.750 | 1.000 |

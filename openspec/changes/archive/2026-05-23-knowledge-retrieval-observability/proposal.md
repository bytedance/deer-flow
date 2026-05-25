## Why

知识链路（索引+检索）已有 `KbTelemetryCollector`、错误分类器、per-KB `/index-stats` 端点和前端 `useIndexStats` hook，但检索路径（`retrieval.py`、`tools.py`）未接入 telemetry，缺少跨知识库的全局健康摘要，也没有可配置的告警阈值。这导致无法按月度评审口径回答"知识链路到底稳不稳定"。

## What Changes

- 检索路径接入 telemetry：`multi_kb_retrieve` 和 `search_knowledge_base` 记录延迟和结果事件
- 新增全局 KB 健康摘要端点：跨所有 KB 汇总索引成功率、失败分布、检索延迟
- 新增运维观察阈值建议文档，定义警告/异常水位线
- 前端 `KbIndexHealthCard` 增强：显示检索延迟趋势和告警提示

## Capabilities

### New Capabilities

- `kb-global-health-summary`: 全局 KB 健康摘要端点，跨知识库汇总索引成功率、检索延迟和失败分类
- `kb-retrieval-telemetry`: 检索路径 telemetry 接入，记录每次检索的延迟、结果数和异常

### Modified Capabilities

<!-- No existing spec changes — all additions are new capabilities -->

## Impact

- Backend: `knowledge_base/retrieval.py`（telemetry 接入）、`rag/tools.py`（检索事件记录）、`app/gateway/routers/knowledge_bases.py`（新增 global summary 端点）、`app/gateway/routers/system.py`（可选：telemetry summary 端点）
- Frontend: `kb-index-health-card.tsx`（增强展示检索延迟趋势）
- Docs: 运维观察阈值建议文档

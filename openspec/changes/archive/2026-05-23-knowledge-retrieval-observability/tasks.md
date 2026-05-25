## 1. 检索路径 Telemetry 接入（Backend）

- [x] 1.1 `multi_kb_retrieve` 内部记录 per-KB 检索延迟（`record_latency`）和整体结果事件（`record_event`），包括 timeout 和异常事件的记录
- [x] 1.2 `search_knowledge_base` 入口记录检索结果事件（`retrieval.completed`/`retrieval.blocked`/`retrieval.failed`），source 标记为 `"tool"`
- [x] 1.3 编写检索 telemetry 单元测试：验证延迟记录、事件类型、异常路径不中断检索

## 2. 全局 KB 健康摘要（Backend）

- [x] 2.1 `KnowledgeBaseService` 新增 `get_health_summary` 方法：遍历用户可访问的 KB，汇总索引成功率、失败分布、检索延迟
- [x] 2.2 `knowledge_bases.py` router 新增 `GET /health-summary` 端点，返回聚合数据
- [x] 2.3 编写健康摘要测试：验证跨 KB 聚合、空列表、权限过滤、失败分类汇总

## 3. 前端增强

- [x] 3.1 `KbIndexHealthCard` 展示检索延迟趋势：利用 `index-stats` 中已有的 `avg_retrieval_latency_ms` 和 `total_queries` 字段，展示检索延迟数据和查询次数

## 4. 运维文档

- [x] 4.1 创建 `docs/admin-guide/kb-health-thresholds.md`：定义索引成功率、检索延迟、失败率等关键指标的警告/异常水位线建议

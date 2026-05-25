# KB 健康度运维观察阈值

知识链路可观测性数据来源：

- **per-KB**: `GET /api/knowledge-bases/{kb_id}/index-stats`
- **全局**: `GET /api/knowledge-bases/health-summary`
- **前端**: 知识库文档对话框中的"索引健康度"卡片，30s 自动刷新

## 1. 索引成功率

**定义**: `ready / total`（已索引文档数 / 文档总数）

| 级别 | 阈值 | 含义 | 建议动作 |
|------|------|------|----------|
| 正常 | >= 95% | 索引链路健康 | 无需操作 |
| 警告 | 80% ~ 95% | 部分文档索引失败 | 检查 `failure_by_type`，重点关注 `ENCRYPTED_PDF` 和 `UNSUPPORTED_FORMAT` |
| 异常 | < 80% | 大面积索引失败 | 排查 Markitdown 服务、embedding provider 连通性、Chroma 状态 |

## 2. 检索延迟

**定义**: P95 检索延迟（毫秒），per-KB 统计，最近 1000 次采样

| 级别 | 阈值 | 含义 | 建议动作 |
|------|------|------|----------|
| 正常 | < 500 ms | 检索响应及时 | 无需操作 |
| 警告 | 500 ~ 2000 ms | 检索出现延迟 | 检查 embedding provider 响应时间、Chroma 查询性能 |
| 异常 | > 2000 ms | 检索明显变慢 | 排查 embedding provider 是否降级、向量集合是否过大需优化 |

> **注意**: 首次查询延迟通常较高（embedding provider 冷启动），应以稳态数据为准（建议 `total_queries > 10` 后再观察）。

## 3. 检索查询量

**定义**: `total_queries`，最近 1000 次采样的查询次数

| 级别 | 阈值 | 含义 | 建议动作 |
|------|------|------|----------|
| 正常 | > 0 | 有检索流量 | 无需操作 |
| 关注 | = 0 | 无检索流量 | 检查 RAG 是否启用、agent 是否正确调用 `search_knowledge_base` 工具 |

## 4. 失败分类分布

**定义**: `failure_by_type` 中各分类的占比

**关键分类**:

| 分类 | 常见原因 | 排查方向 |
|------|----------|----------|
| `EMPTY_RESULT` | 扫描件/图片 PDF | 建议用户上传可提取文本的文档 |
| `ENCRYPTED_PDF` | 加密 PDF | 建议用户解密后重新上传 |
| `UNSUPPORTED_FORMAT` | 不支持的文件格式 | 检查文件扩展名，确认在支持列表中 |
| `MARKITDOWN_UNAVAILABLE` | Markitdown 服务未安装或不可用 | 安装 markitdown 依赖 |
| `DIMENSION_MISMATCH` | embedding 维度不一致 | `reindex-all` 重建向量集合 |
| `INTERNAL_ERROR` | 内部异常 | 查看服务端日志排查具体错误 |
| `OTHER` | 未分类错误 | 查看 `recent_failures` 中的具体 error 信息 |

**建议**: 如果 `OTHER` 占比超过 20%，说明有新的错误模式未被分类器覆盖，建议更新 `classify_index_error()` 函数。

## 5. 全局视角

**端点**: `GET /api/knowledge-bases/health-summary`

**关注指标**:
- `total_kbs`: 用户可访问的知识库总数
- `index_success_rate`: 全局索引成功率（加权平均）
- `retrieval.avg_latency_ms` / `retrieval.p95_latency_ms`: 全局检索延迟（跨 KB 加权）
- `failure_by_type`: 全局失败分类汇总
- `recent_failures`: 最近 20 条失败记录

**告警建议**:
- 全局 `index_success_rate < 80%` → 排查基础设施（Markitdown / Embedding / Chroma）
- 全局 `retrieval.p95_latency_ms > 2000ms` → 排查 embedding provider
- `recent_failures` 持续增长 → 检查是否有系统性上传/索引问题

## 6. 集成外部告警

当前系统不内置告警引擎。如需集成 Prometheus / Grafana / PagerDuty 等外部告警系统：

1. **Pull 模式**: 定时 GET `/api/knowledge-bases/health-summary`，提取指标推送到 Prometheus Pushgateway 或 InfluxDB
2. **Log 模式**: 解析 `{DEER_FLOW_HOME}/.telemetry.log`（JSONL 格式），通过 Loki / ELK 建立仪表盘和告警规则
3. **前端看板**: `KbIndexHealthCard` 组件内的检索延迟颜色指示器可作为快速视觉参考

## 7. 阈值调整

以上阈值为初始建议值，应根据实际运行环境和业务需求调整：

- **内网环境**（embedding provider 延迟低）：可收紧检索延迟阈值（正常 < 200ms）
- **大文档量**（单 KB 文档 1000+）：索引成功率阈值可适当放宽至 90%
- **非关键场景**：可整体放宽阈值，仅保留异常级别告警

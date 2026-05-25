## Context

知识链路可观测性分为两段：**索引段**（上传→转换→向量化）和**检索段**（用户查询→向量检索→结果合并）。索引段已有完善的 telemetry 接入（`KbTelemetryCollector` + `index_error_classifier` + per-KB `/index-stats` 端点），但检索段完全是盲区——`multi_kb_retrieve` 和 `search_knowledge_base` 不记录任何延迟、结果数或异常事件。

此外，当前只有 per-KB 粒度的统计端点，缺少一个跨所有知识库的全局健康摘要，运维人员无法快速回答"整体知识链路是否健康"。

现有基础设施：
- `KbTelemetryCollector`：线程安全的内存计数器 + 延迟采样（per-KB，最近 1000 条）+ JSONL 事件记录
- `classify_index_error()`：关键词匹配的错误分类器（7 种类型）
- `GET /{kb_id}/index-stats`：per-KB 索引统计 + 检索延迟（已从 telemetry 读取，但 telemetry 里没有检索数据）
- 前端 `useIndexStats` hook + `KbIndexHealthCard` 组件

## Goals / Non-Goals

**Goals:**
- 检索路径（`multi_kb_retrieve`、`search_knowledge_base`）接入现有 `KbTelemetryCollector`，记录延迟和结果事件
- 新增 `GET /api/knowledge-bases/health-summary` 全局端点，跨 KB 汇总索引成功率、检索延迟、失败分布
- 前端 `KbIndexHealthCard` 展示检索延迟趋势（基于已有的 `avg_retrieval_latency_ms` 字段，数据开始流入后自动有值）
- 提供运维观察阈值建议文档，定义警告/异常水位线

**Non-Goals:**
- 不引入 Prometheus / Grafana / OpenTelemetry 等外部可观测性依赖
- 不修改 `KbTelemetryCollector` 的数据结构或 API
- 不添加检索结果的持久化存储（telemetry 仅内存 + JSONL）
- 不实现自动告警（仅提供阈值建议，告警由外部系统按需配置）
- 不修改 Chroma 或 embedding provider 层的 telemetry

## Decisions

### Decision 1: 检索 telemetry 在 `multi_kb_retrieve` 内部记录

**选择**：在 `multi_kb_retrieve` 函数内部直接调用 `get_kb_telemetry()` 记录事件，而非在调用方（`tools.py`）单独记录。

**理由**：
- `multi_kb_retrieve` 已有 per-KB 的延迟信息（`per_kb_stats` 字典包含每个 KB 的耗时），在内部记录可以拿到最精确的单 KB 粒度延迟
- `tools.py` 只能拿到合并后的结果，丢失了 per-KB 分解信息
- 避免在两个调用点（`_search_selected_kbs` 和 `_search_single_collection`）重复埋点逻辑

**替代方案**：在 `tools.py` 的 `search_knowledge_base` 入口/出口记录整体延迟。此方案更简单但丢失 per-KB 粒度，且 `search_knowledge_base` 本身是工具函数不应承担 telemetry 职责。

### Decision 2: 全局健康摘要端点放在 knowledge_bases router 下

**选择**：`GET /api/knowledge-bases/health-summary` 而非 `/api/system/telemetry/kb-health`。

**理由**：
- 与现有 `GET /{kb_id}/index-stats` 在同一 router，保持知识库相关端点的内聚性
- 不需要 admin 权限（任何登录用户可查看自己有权限的 KB 的汇总），与 index-stats 的权限模型一致
- 避免在 `system.py` router 中引入对 `KnowledgeBaseService` 的依赖

### Decision 3: 全局摘要仅聚合用户可访问的 KB

**选择**：`health-summary` 端点基于 `list_accessible` 过滤，只汇总当前用户有权访问的知识库。

**理由**：
- 与现有 KB 列表和 index-stats 端点的权限模型一致
- 避免信息泄露：用户不应看到无权访问的 KB 的健康状态
- 如需全租户视角，admin 可通过 `X-DeerFlow-Admin` header 提升权限

### Decision 4: 运维阈值建议以 Markdown 文档形式交付

**选择**：在 `docs/` 目录下创建 `admin-guide/kb-health-thresholds.md`，而非在代码中定义常量或配置项。

**理由**：
- 阈值是运维经验值，需要根据实际运行数据调整，不适合硬编码
- 当前没有告警引擎，硬编码阈值不会触发任何自动化行为
- 文档形式便于运维团队按需修改和引用
- 后续如需自动化告警，可以此文档为基础配置 Prometheus rules 或其他告警系统

## Risks / Trade-offs

- **[Risk] 检索 telemetry 增加 `multi_kb_retrieve` 的职责** → 影响很小：telemetry 调用是 fire-and-forget（`record_event` 内部 try-catch），不会影响检索主流程的性能或正确性
- **[Risk] 内存中的 latency 采样在进程重启后丢失** → 可接受：telemetry 设计目标就是进程内实时快照，历史数据通过 JSONL 离线重建
- **[Risk] 全局 health-summary 对大量 KB（100+）可能较慢** → 当前规模预计 <20 KB，每个 KB 的 `get_index_stats` 是独立 DB 查询；后续如有性能问题可加简单缓存（60s TTL）
- **[Trade-off] 全局摘要不包含时间维度（如"过去 24 小时"）** → `KbTelemetryCollector` 只保留最近 1000 条延迟样本，没有时间戳。如需时间窗口统计需要改造 collector，属于后续迭代

## Open Questions

- 检索 telemetry 是否需要区分 `search_knowledge_base`（工具调用）和程序化 `multi_kb_retrieve` 调用？→ 当前设计用 `source` 字段区分（`"tool"` vs `"internal"`）
- 告警阈值是否需要可配置？→ 当前为文档建议，后续可在 `config.yaml` 中增加 `rag.health_thresholds` 配置段

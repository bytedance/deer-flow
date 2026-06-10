# 洞察系统 (Insights System)

闭环反馈系统：收集反馈和闭环数据，生成改进建议，并将验证过的改进注入 Agent 记忆。

## 数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                      反馈分析                                    │
│  FeedbackAggregator JOINs FeedbackRow with ThreadMetaRow        │
│  (租户隔离) + AgentUsageRow (Agent 关联，可空)                    │
│  计算正/负比率，检测负向聚类                                       │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      闭环知识                                    │
│  ClosureKnowledgeExtractor 钩入 ClosureService.transition()     │
│  在 verify_close 时提取 verification_summary 和 evidence         │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      改进生成                                    │
│  ImprovementEngine 分析反馈趋势和闭环模式                         │
│  生成带置信度评分的建议                                           │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      记忆集成                                    │
│  管理员通过仪表板应用建议时                                       │
│  FeedbackMemoryIntegration 创建记忆事实                           │
│  source="feedback_loop", category="improvement", confidence=0.9 │
└─────────────────────────────────────────────────────────────────┘
```

## 组件

| 模块 | 类/函数 | 职责 |
|------|---------|------|
| `analytics.py` | `FeedbackAggregator` | 按 Agent 聚合反馈模式，通过双 JOIN (ThreadMetaRow 租户隔离, AgentUsageRow Agent 关联) |
| `knowledge_extractor.py` | `ClosureKnowledgeExtractor` | 从验证过的闭环工单提取 KB 候选（查询 `submit_verification`/`verify_close` 事件的 `ClosureTicketEventRow`） |
| `kb_candidate_store.py` | `KBCandidateStore` | 持久化 KB 候选为 JSON 文件，租户隔离在 `{DEER_FLOW_HOME}/insights/{tenant_id}/kb_candidates/` |
| `improvement.py` | `ImprovementEngine` | 生成排名的 `ImprovementSuggestion` 对象，带置信度评分和去重 |
| `memory_integration.py` | `FeedbackMemoryIntegration` | 当建议被应用时创建记忆事实，`source="feedback_loop"` |
| `scheduler.py` | `InsightsScheduler` | 按可配置间隔（默认 6 小时）运行批量聚合 |
| `cache.py` | `JsonFileInsightsCache` | 存储聚合结果，带租户隔离 |

## Admin Dashboard API

**路由**: `app/gateway/routers/insights.py`

### 反馈趋势

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/insights/feedback-trends` | 每 Agent 聚合反馈指标 |

### 闭环指标

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/insights/closure-metrics` | 闭环工单 SLA 合规性和解决率 |

### 改进建议

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/insights/improvements` | 排名的改进建议 |
| POST | `/api/insights/improvements/{id}/apply` | 应用建议（触发记忆集成） |
| POST | `/api/insights/improvements/{id}/dismiss` | 忽略建议并说明原因 |

### 闭环知识

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/insights/closure-knowledge` | 列出 KB 候选（pending_review/approved/dismissed） |
| POST | `/api/insights/closure-knowledge/{ticket_id}/promote` | 批准并索引 KB 候选 |
| POST | `/api/insights/closure-knowledge/{ticket_id}/dismiss` | 忽略 KB 候选 |

## 权限

| 操作 | 权限 |
|------|------|
| GET | `insights:read` |
| POST | `insights:write` |

在 `app/gateway/authz.py` 中注册，默认授予 `superadmin` 和 `tenant_admin` 角色。

## 配置选项

`config.yaml` → `insights`:

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | true | 主开关 |
| `aggregation_interval_hours` | int | 6 | 批量聚合间隔 |
| `cluster_threshold` | int | 5 | 每小时负向反馈聚类阈值 |
| `low_confidence_threshold` | float | 0.3 | 抑制低于此置信度的建议 |
| `improvement_model_name` | str | null | LLM 建议生成模型（null = 默认） |

### 配置示例

```yaml
insights:
  enabled: true
  aggregation_interval_hours: 6
  cluster_threshold: 5
  low_confidence_threshold: 0.3
  improvement_model_name: null
```

## 软前提条件

`migrate-current-system-to-postgresql` 改善 JOIN 性能，但 SQLite 模式适用于 MVP。

## 改进建议生命周期

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   生成中     │───▶│   待审核     │───▶│   已应用     │
│ (generating)│    │ (pending)   │    │ (applied)   │
└─────────────┘    └──────┬──────┘    └─────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │   已忽略     │
                   │ (dismissed) │
                   └─────────────┘
```

## KB 候选生命周期

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  待审核      │───▶│   已批准     │───▶│   已索引     │
│(pending_    │    │ (approved)  │    │ (indexed)   │
│  review)    │    └─────────────┘    └─────────────┘
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   已忽略     │
│ (dismissed) │
└─────────────┘
```

## 最佳实践

### 监控反馈趋势

定期检查 `/api/insights/feedback-trends`:
- 识别负向反馈集中的 Agent
- 检测突然的负向聚类（可能表示问题）

### 应用改进建议

1. 查看 `/api/insights/improvements`
2. 评估建议的置信度和相关性
3. 应用高置信度建议
4. 忽略不相关的建议并说明原因（帮助系统学习）

### KB 候选审核

1. 查看 `/api/insights/closure-knowledge`
2. 验证候选的准确性和相关性
3. 批准有价值的候选以索引到知识库
4. 忽略低质量候选

### 性能考虑

- 批量聚合在后台运行，不阻塞主线程
- 大量反馈时考虑增加 `aggregation_interval_hours`
- PostgreSQL 迁移改善 JOIN 性能

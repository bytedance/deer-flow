## Context

### 现状

DeerFlow 已经实现的记忆系统（[backend/packages/harness/deerflow/agents/memory/](backend/packages/harness/deerflow/agents/memory/)）由 5 个模块组成：

| 模块 | 职责 |
|---|---|
| `storage.py` | `MemoryStorage` 抽象 + `FileMemoryStorage` / `StoreMemoryStorage` 两种实现，按 `(user_id, agent_name)` 分片，store 后端用 LangGraph `BaseStore`。 |
| `updater.py` | 提供 `get_memory_data / clear_memory_data / create_memory_fact / delete_memory_fact / update_memory_fact / import_memory_data / reload_memory_data`，还有 LLM 驱动的 `update_memory_async` 抽取上下文。 |
| `queue.py` | 30s 防抖队列，在 timer 触发时调用 LLM。 |
| `prompt.py` | LLM 抽取 prompt 模板。 |
| `summarization_hook.py` | 与 `SummarizationMiddleware` 协同的钩子。 |
| `MemoryMiddleware` | 在 `lead_agent` middleware 链第 13 位，过滤用户 + 最终 AI 消息后入队。 |

数据 schema：

```text
{
  "version": "1.0",
  "lastUpdated": "...",
  "user": {
    "workContext":     {"summary": "...", "updatedAt": "..."},
    "personalContext": {"summary": "...", "updatedAt": "..."},
    "topOfMind":       {"summary": "...", "updatedAt": "..."}
  },
  "history": {
    "recentMonths": ..., "earlierContext": ..., "longTermBackground": ...
  },
  "facts": [
    {"id", "content", "category", "confidence", "createdAt", "source", "sourceError"}
  ]
}
```

注入路径：每次 LLM 调用前，把 top-15 facts + 三段 user context 拼成 `<memory>...</memory>` 段塞入系统提示词，受 `max_injection_tokens=2000` 截断。

### 约束

- **必须向后兼容**：`memory.json` 文件、`StoreMemoryStorage` namespace、`/api/memory/*` 路由的现有响应 schema 都已被前端 / 渠道 / 嵌入式 client（`DeerFlowClient`）依赖；不能破坏。
- **租户隔离已实现**：`get_current_tenant_id()` + `get_effective_user_id()` 已在 contextvar 层贯穿 Gateway / Channels / Embedded client；新层必须沿用同一套 scope 解析。
- **Store 后端可插拔**：实现必须同时跑通 in-memory store / sqlite / postgres 三种 BaseStore 实现，不能假设特定后端的事务能力。
- **零新增第三方依赖**：embedding 复用 [`packages/harness/deerflow/knowledge_base/`](backend/packages/harness/deerflow/knowledge_base/) 已经接入的 ChromaDB + 嵌入提供方；不能引入 Mem0 / LangMem 等成品 SDK。
- **Local sandbox 模式可降级**：File backend 必须保留，使本地开发模式无依赖也能跑。

### 利益相关方

- **平台架构（含本提案作者）**：要保证可演进、可观测、可治理。
- **租户管理员**：要能管理租户级 Domain 记忆、能审计写入来源。
- **业务 SOUL 作者**（如 `pump-fault-diagnosis` / `ai-report--*`）：要有显式 `record_domain_memory` 工具可用，不再依赖隐式 LLM 抽取。
- **前端记忆管理页**：要在保留现有交互的前提下扩展三层视图（不在本 change 范围）。

## Goals / Non-Goals

**Goals:**

1. 把当前**单层、单用户、纯文件 / Store 二选一、纯 LLM 抽取**的记忆系统重构为**会话 / 用户 / 领域三层、统一 `MemoryService` 契约、检索可融合、可遗忘、可观测**的分层模型。
2. 现有 `memory.json` 数据零丢失迁移到新 schema 的 User 层；现有 API 路径 / 响应 / `MemoryMiddleware` 行为在缺省参数下与今天等价。
3. Domain 层提供给业务 SOUL 显式写入入口（工具调用），不依赖 LLM 隐式判定。
4. 检索阶段按 token 预算与优先级在三层之间智能融合，避免现状的硬截断。

**Non-Goals:**

- **不实现代码**（本 change 仅交付 design + specs + tasks，下一个 change 才 apply）。
- **不做前端视觉稿 / 像素级布局设计**（仅约定可观察行为契约：Tab 切换、Scope 过滤、权限驱动的只读/可写状态、TanStack Query 缓存键约定、错误码本地化规则）。
- **不做跨租户 Domain 共享治理**（先单租户内共享，跨租户委托后续 change）。
- **不做 GDPR delete-on-request / 审计合规出口**（独立 change 处理）。
- **不替换 `BaseStore`**：底层仍用 LangGraph Store + ChromaDB + 文件，不引入新数据库。
- **不调优 LLM 抽取 prompt**（属实现期任务）。
- **不重写 `SummarizationMiddleware`**：仅约定其产物归入 Session 层，不改其内部算法。

## Decisions

### D1：分层粒度 = Session / User / Domain（三层）

| 层 | scope | 例子 | 生命周期 | 写入方 | 检索方式 |
|---|---|---|---|---|---|
| **Session** | `(tenant_id, user_id, thread_id)` | "本会话用户要求 PDF 不要 Markdown"、"本会话锁定设备 ID = pump-123" | 与 Thread 同寿；归档到只读 store key | `MemoryMiddleware` 自动 + `SummarizationMiddleware` 钩子 | 全文匹配 + 时间倒序 |
| **User** | `(tenant_id, user_id)` | "用户偏好简短回答"、"用户专注于腐蚀监测领域" | 长期，可衰减 | `MemoryMiddleware` 自动（confidence ≥ 0.7） + 用户手动 CRUD | 时间衰减分数 + 全文 |
| **Domain** | `(tenant_id, domain, entity_id?)` | "设备 pump-123 历史 3 次轴温异常都是因为 X"、"6K 腐蚀 RBI 阈值定义" | 长期，可衰减，可被同租户用户共享 | 显式工具 `record_domain_memory` + `tenant_admin` API | embedding + 元数据过滤（domain / entity_id） |

**为什么是三层不是两层 / 四层**：

- **两层（User + Session）不够**：业务 SOUL 写入的设备故障经验、报告结论这种**可跨用户复用的领域知识**，混进 User 层会污染个人画像，混进 Session 层又随 Thread 死亡而丢失。Domain 是必须独立的。
- **四层（多加 Tenant Common）冗余**：租户级常识在 Domain 层用 `entity_id=None` 表达即可（"该租户的厂区命名约定"），不值得多一层。
- **不引入 Org / Project 层**：DeerFlow 当前 tenant model 未细分 org / project；如未来引入，Domain 层的 `domain` 字段可平移到这两个轴。

**替代方案**：

- *Mem0 风格的扁平 + tag 过滤*：所有记忆放一个池子，靠 tag 检索。优点是模型简单。劣势：（1）Session 与持久化记忆**本质生命周期不同**（Thread 关闭即归档 vs 跨 Thread 保留），扁平模型让生命周期管理变难；（2）领域 embedding 检索需要专属索引 schema（带 entity_id），扁平结构会拖累查询性能。
- *按 agent_name 分片（现状已有 `agent_memory_file`）*：本质是按 SOUL 分片，但同一 SOUL 跨设备的记忆该不该共用？答案是该共用；按 agent 分片切错了维度。本提案保留 agent_name 作为 User 层的可选 sub-scope（向后兼容现有 `("memory", tenant_id, user_id, agent_name)` namespace），但不作为分层主轴。

### D2：统一 `MemoryService` 接口，所有调用方都从这里走

接口签名（伪代码）：

```python
class MemoryScope(BaseModel):
    layer: Literal["session", "user", "domain"]
    tenant_id: str
    user_id: str | None = None
    thread_id: str | None = None
    agent_name: str | None = None
    domain: str | None = None
    entity_id: str | None = None

class MemoryRecord(BaseModel):
    id: str
    scope: MemoryScope
    kind: Literal["preference", "fact", "episode", "domain_assertion", "context_summary"]
    content: str
    embedding: list[float] | None = None
    source: Literal["middleware_auto", "tool_explicit", "user_manual", "import"]
    confidence: float = 0.5
    created_at: datetime
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    decay_policy: Literal["never"] | str = "never"  # e.g. "exponential:half_life_days=30"
    tags: list[str] = []
    metadata: dict[str, Any] = {}

class MemoryService(Protocol):
    def read(self, scope: MemoryScope, *, query: str | None = None,
             top_k: int = 10, kinds: list[str] | None = None,
             at_time: datetime | None = None) -> list[MemoryRecord]: ...
    def write(self, record: MemoryRecord) -> str: ...  # returns id
    def forget(self, scope: MemoryScope, *,
               record_id: str | None = None,
               filter: dict[str, Any] | None = None) -> int: ...  # returns deleted count
    def compose_for_prompt(self, *, tenant_id: str, user_id: str,
                           thread_id: str, agent_name: str | None,
                           query_hint: str | None,
                           budget_tokens: int) -> str: ...
```

**关键决策**：

- `compose_for_prompt` 是**唯一**给 `MemoryMiddleware` 的输出口。Middleware 不再自行拼 `<memory>` 标签，全部交给 service。这样未来要换检索策略（如改 Re-ranker）只动 service 一处。
- `write` 返回 id；`forget` 返回删除条数。所有写入操作幂等：同 `(scope, content_hash)` 重复写入 → 更新 `created_at` 不新增 record（避免 LLM 反复抽出同一事实导致膨胀，对应现状 `updater.py` 已有的 whitespace-normalized dedup，迁移到 service 层）。
- `read` 的 `at_time` 用于支持「按那时的事实回答」（应对 valid_from/valid_to 时序）。
- 错误模型：`MemoryNotFound` / `MemoryScopeForbidden` / `MemoryStorageError` / `MemoryEmbeddingUnavailable`，前端按错误码做用户提示。

**替代方案**：

- *直接暴露 `MemoryStorage` 给调用方*：现状就是这样。劣势：调用方需要自己关心 cache、namespace、embedding fallback，逻辑会散落到 Middleware / Tool / Router 三处。统一 service 是必经之路。
- *按层拆三个 service*：Session / User / Domain 三个独立类。劣势：`compose_for_prompt` 需要跨层融合，跨服务调用反而更绕；不如一个 service 内部分发到三个 storage。

### D3：Storage 后端按层映射，复用现有底座

| 层 | 主存储 | 文件 fallback | embedding |
|---|---|---|---|
| Session | LangGraph `BaseStore`，namespace `("memory_session", tenant_id, user_id, thread_id)` | 可关闭，因 Session 数据短命 | 不索引 |
| User | LangGraph `BaseStore`，namespace `("memory", tenant_id, user_id, agent_name)`（**保留现有**） | `FileMemoryStorage`（保留现有） | 可选；token 预算够时直接用全文 + 衰减分排序 |
| Domain | LangGraph `BaseStore`（结构化字段） + ChromaDB（embedding 向量），namespace `("memory_domain", tenant_id, domain, entity_id)` | File backend 仅存结构化部分，跳过 embedding | 必选；复用 `knowledge_base/` 的 `get_embedding_provider(spec)` |

**关键决策**：

- **Session 不持久 embedding**：Session 数据生命周期短、量小（单 Thread 通常 < 50 record）、用全文匹配 + 时间倒序就够了。embedding 计算延迟会拖慢 turn 间响应。
- **User 层 embedding 可选**：默认不做向量化以匹配现状成本曲线；当用户的 facts 数量超过一个阈值（如 200）时，service 自动启用 embedding。该阈值是 service 内部参数，不暴露给 spec。
- **Domain 层强制 embedding**：因为 Domain 数据典型量级 = 设备数 × 故障类型 × 历史经验，必然超出 token 预算，embedding 是检索可行性的前提。
- **复用 `knowledge_base/` 的 ChromaDB 实例**：但用**独立 collection**（前缀 `memory_domain_{tenant_id}`），不混入用户上传的知识库 collection；这样删除知识库不会牵动记忆。

**替代方案**：

- *Domain 用独立 vector DB（Qdrant / Weaviate）*：性能更好但引入新依赖，违反「零新增依赖」约束。
- *用 Postgres pgvector*：DeerFlow 现状 BaseStore 已支持 sqlite/postgres，但 pgvector 不是默认装；交给后续 change 演进。

### D4：写入路径 = Middleware 自动 + Tool 显式，按 confidence 分流

```text
                            ┌────────────────────────────────┐
   user msg + final AI msg →│      MemoryMiddleware          │
                            │ (filter: user + final AI only) │
                            └──────────┬─────────────────────┘
                                       │ enqueue (debounce 30s)
                                       ▼
                            ┌────────────────────────────────┐
                            │   memory.queue → LLM extract   │
                            └──────────┬─────────────────────┘
                                       │
              ┌────────────────────────┼─────────────────────┐
              ▼                        ▼                     ▼
     Session (always)          User (conf≥0.7)        Domain (conf≥0.8 + has entity_id)
              │                        │                     │
              ▼                        ▼                     ▼
                  MemoryService.write(record) — 幂等去重
```

**Tool 显式写入路径**（绕过 LLM 隐式抽取）：

- 新增 `record_domain_memory` 工具，签名 `(content, domain, entity_id?, confidence?, valid_from?, valid_to?, tags?)`。SOUL 在「诊断结论」「报告关键发现」「工单结案」节点显式调用。
- `tenant_admin` 角色有专属 API 写入 Domain 层（如批量导入设备故障经验库）。

**为什么 Domain 层 confidence 阈值更高（0.8）**：因为 Domain 记忆是**跨用户共享**的，错误成本远高于个人偏好；提高门槛减少污染。配合 `record_domain_memory` 工具直接 confidence=1.0（人工确认）。

**替代方案**：

- *全靠 LLM 抽取*：现状。劣势：业务 SOUL 想写入「设备 pump-123 第 4 次振动告警 = 联轴器对中偏差」这种结构化结论，LLM 抽取容易丢失字段、误归类。Tool 显式写入更可控。
- *全靠工具显式写入*：劣势：用户偏好这类隐性信号必须靠抽取，没有用户会主动调 `remember_my_preference("我喜欢简短")`。

### D5：检索 + 注入 = 三层分别检索 + 优先级融合

`compose_for_prompt(tenant_id, user_id, thread_id, agent_name, query_hint, budget_tokens)`：

```text
1. budget = budget_tokens                       # e.g. 2000
2. session_records = session.read(scope_session, top_k=20)
                       .filter(by recency)
3. user_records    = user.read(scope_user, query=query_hint, top_k=15)
                       .score(by decay × confidence × recency)
4. domain_records  = domain.read(scope_domain, query=query_hint, top_k=10,
                                  embedding_lookup=True)
                       .filter(by entity match)
5. merge into one list with priority Session > User > Domain
6. greedily pack into budget; emit telemetry on truncation
7. format as <memory><session>...</session><user>...</user><domain>...</domain></memory>
```

**关键决策**：

- **优先级 Session > User > Domain**：Session 是当前对话的局部约束，违反它的代价最高（直接产生用户感知错误）；Domain 反之是辅助知识，截断危害最低。
- **`query_hint` 取最近一轮用户消息**（由 Middleware 在调用 service 时传入），用于 User / Domain 的相关性排序；Session 不需要 query 因为本会话所有 record 都相关。
- **`<memory>` 标签按层分块**：方便 LLM 识别优先级，也方便 telemetry 记录哪一层被命中。
- **截断行为可观测**：每次 `compose_for_prompt` 调用都 emit `memory_compose_outcome` event（含每层 record 数、token 数、是否被截断），落盘到 `.telemetry.log`。

**替代方案**：

- *单一全局 Re-ranker*：所有层 record 一起喂 cross-encoder 排序。优点是相关性高。劣势：需要新模型依赖，且 Session 的「时序优先」语义会被 re-ranker 破坏。
- *固定 token 比例分配*（如 Session 40% / User 40% / Domain 20%）：简单但浪费 budget——若 Session 实际只占 100 token，剩余应让给 User。优先级 + 贪心打包更灵活。

### D6：遗忘 / 时效 = `decay_policy` + `valid_from/to` + 显式 `forget`

- **`decay_policy`** 字段值字符串化，便于扩展：`"never"` / `"linear:days=30"` / `"exponential:half_life_days=14"`。检索时 `effective_score = base_score × decay_factor(now - created_at, policy)`。
- **`valid_from / valid_to`**：硬时间窗。`valid_to < now` 的 record 不进入检索结果（但仍存于 store，便于 audit / 回溯）。
- **显式 `forget`**：API + 工具 `forget_memory(scope, filter)`；用户手动删除走 `DELETE /api/memory/{layer}/records/{id}`，受 scope 权限约束（用户只能删自己 scope 内 record；tenant_admin 可删 Domain 层全租户 record）。
- **过期清理后台任务**：可选的 sweeper 周期性删除 `valid_to + retention_days < now` 的 record；retention_days 默认 90，可通过 `config.yaml` 调整。本 change 把它列在 spec 但不强制实现期必须开启。

### D7：迁移策略

```text
[现状] memory.json
{
  "user": {workContext, personalContext, topOfMind},
  "history": {...},
  "facts": [...]
}

[迁移后] User 层 records:
  - 三段 user.* summary  → kind="context_summary", layer="user", source="import"
  - 三段 history.*       → kind="context_summary", layer="user", source="import"
  - facts[]              → kind="preference"|"fact" 按 category 映射, layer="user"
```

**迁移脚本** `scripts/migrate_layered_memory.py`：

1. 扫描 `{base_dir}/users/*/memory.json` 与 `{base_dir}/users/*/agents/*/memory.json`
2. 每个 record 转换成新 `MemoryRecord` 模型，写入 LangGraph Store 新 namespace `("memory", tenant, user, agent)`（**保持现有 namespace**）
3. 在 `MemoryRecord.metadata.legacy_path` 记录原文件路径，用于回滚
4. **保留原 `memory.json`**：不删除，只标记 `.migrated` sentinel 文件；service 在读到 sentinel 后从 Store 读，否则从文件读（双轨期）
5. 双轨期 ≥ 2 个 release 后再删除原文件

幂等保证：脚本检测 sentinel 后跳过；可重复执行。

回滚：删除 sentinel 文件 → service 自动回到旧路径。

### D8：Telemetry 事件类型

复用 [report_templates/telemetry.py](backend/packages/harness/deerflow/report_templates/telemetry.py) 模式（in-memory 计数器 + JSONL 落盘）：

| 事件 | 触发点 | 字段 |
|---|---|---|
| `memory_write` | `MemoryService.write` | layer, kind, source, confidence, byte_size |
| `memory_read` | `MemoryService.read` | layer, top_k, returned_n, has_embedding_query |
| `memory_compose_outcome` | `compose_for_prompt` | budget_tokens, used_tokens, session_n, user_n, domain_n, truncated |
| `memory_forget` | `MemoryService.forget` | layer, deleted_n, by (record_id|filter) |
| `memory_migration` | 迁移脚本 | direction (forward|rollback), users_n, records_n |

HTTP 出口：`GET /api/telemetry/memory/summary` 返回当前进程内的计数器快照。

### D9：与 Knowledge Base / Skills 的边界

- **Knowledge Base = 用户主动上传的文档库**（PDF / Excel / 网页），由 RAG 检索。
- **Memory（本提案）= 平台被动 / 主动累积的事实与偏好**。

二者**互不替代**：Domain Memory 中的「设备 pump-123 第 4 次轴温异常 = 联轴器对中」是**结论性事实**；KB 中的「2024 年泵故障维修手册.pdf」是**长文档**。检索时 KB 与 Memory 各走各的通道，最终都注入 LLM 上下文，但出口标签不同（`<knowledge>` vs `<memory>`）。

复用：embedding provider、ChromaDB 实例、`with_kb_context` 的 tenant 上下文恢复机制（用于后台 sweeper / 迁移脚本）。

### D10：API 兼容策略

| 路由 | 当前行为 | 新行为 |
|---|---|---|
| `GET /api/memory` | 返回 `{user, history, facts}` 旧 schema | 缺省 = 等价于 `?layer=user`，旧 schema；带 `?layer=session/domain` 走新路径 |
| `POST /api/memory/facts` | 写入 facts | 等价于 `POST /api/memory/user/records?kind=fact` |
| `DELETE /api/memory/facts/{id}` | 删 fact | 等价于 `DELETE /api/memory/user/records/{id}` |
| `GET /api/memory/config` | 不变 | 不变 |
| `GET /api/memory/status` | 不变 | 不变 |
| **新增** `GET /api/memory/{layer}/records` | — | 三层通用 list |
| **新增** `POST /api/memory/{layer}/records` | — | 三层通用 create |
| **新增** `PATCH /api/memory/{layer}/records/{id}` | — | 三层通用 update |
| **新增** `DELETE /api/memory/{layer}/records/{id}` | — | 三层通用 delete |
| **新增** `GET /api/telemetry/memory/summary` | — | 计数器快照 |

向后兼容验证：现有 `tests/test_memory_*.py` 保持绿；新增 `tests/test_memory_layered_compat.py` 校验旧 schema 出入两端等价。

### D11：前端三层 UI 演进策略

**现状盘点**（基于代码扫描）：

| 文件 | 现状 | 三层化方案 |
|---|---|---|
| [frontend/src/core/memory/types.ts](frontend/src/core/memory/types.ts) | `UserMemory`（含 user/history 三段 summary + facts[]）+ `MemoryFact{id,content,category,confidence,createdAt,source}` + `MemoryFactInput` + `MemoryFactPatchInput` | **保留全部既有类型**（作为 User 层 legacy 视图）；新增 `MemoryLayer = "session"|"user"|"domain"`、`MemoryScope`（与后端 Pydantic 模型字段对齐）、`MemoryRecord`（`id/scope/kind/content/source/confidence/createdAt/validFrom?/validTo?/decayPolicy?/tags?/metadata?`）、`LayeredMemoryFilter`、`MemoryTelemetrySummary` |
| [frontend/src/core/memory/api.ts](frontend/src/core/memory/api.ts) | `loadMemory / clearMemory / exportMemory / importMemory / createMemoryFact / updateMemoryFact / deleteMemoryFact`（全部走旧路径） | **保留全部既有函数**（实现内部由 `?layer=user` 兼容路径承接）；新增 `listLayeredRecords(layer, scope, filter)` / `createLayeredRecord` / `getLayeredRecord` / `updateLayeredRecord` / `deleteLayeredRecord` / `forgetLayeredRecords(layer, filter)` / `getMemoryTelemetrySummary()` |
| [frontend/src/core/memory/hooks.ts](frontend/src/core/memory/hooks.ts) | TanStack Query：key=`["memory"]` 单 query；6 个 mutation（clear/create/update/delete/import + create fact） | **保留全部既有 hook**（`useMemory()` query key=`["memory"]` 不变）；新增 `useLayeredMemoryRecords(layer, scope)` 用 key=`["memory", layer, scopeKey(scope)]`、对应 5 个 mutation、`useMemoryTelemetrySummary()` |
| [frontend/src/components/workspace/settings/memory-settings-page.tsx](frontend/src/components/workspace/settings/memory-settings-page.tsx) | 982 行单页：filter（`all`/`facts`/`summaries`） + 三段 summary + facts CRUD + import/export | 顶部新增 3-Tab Toggle（默认 `user`），User Tab 内容冻结，Session/Domain Tab 详见下方逐条说明 |
| [frontend/src/app/api/memory/[...path]/route.ts](frontend/src/app/api/memory/[...path]/route.ts) | 透明代理 `/api/memory/*` 到 Gateway | **不改**；新路径 `/api/memory/{layer}/records/...` 与 `/api/telemetry/memory/summary` 自动透传 |

**`memory-settings-page.tsx` Tab 内容契约**：

- **User Tab**（默认）：渲染既有 `MemorySettingsPage` 全部交互（三段 summary + facts CRUD + import/export），可包成子组件 `UserMemoryTab` 但**完全不改逻辑**。
- **Session Tab**：thread 选择器（默认当前激活 thread）+ 记录时间倒序列表 + 「Promote to User」按钮（每条记录右侧）。
- **Domain Tab**：`domain` 下拉 + `entity_id` 输入框 + 记录列表；`tenant_admin` 看到「Create」按钮，普通用户只读。

**关键决策**：

1. **TypeScript 类型共存策略**：旧 `UserMemory`/`MemoryFact` 与新 `MemoryRecord` 同时存在，**不强制 User 层 UI 切换到 `MemoryRecord`**。User Tab 继续用 `useMemory()` 拉旧 schema；新 Session/Domain Tab 用新 hook。理由：982 行 User UI 的 view-model 与 `UserMemory` 强耦合，强制重写会引入大量回归风险与本 change 无关的视觉调整。
2. **TanStack Query 缓存键命名**：旧 key `["memory"]` 保留含义=「User 层 legacy 视图」；新 key 形如 `["memory", "session", { tenantId, userId, threadId }]` / `["memory", "user", { kinds, agentName }]` / `["memory", "domain", { domain, entityId }]`。旧 mutation 的 `setQueryData(["memory"], ...)` 不受影响。新 mutation 在成功后只 `invalidateQueries({ queryKey: ["memory", layer] })`，不交叉失效。
3. **权限驱动的只读/可写**：UI 层不自行判断 role，统一靠后端响应——尝试写入收到 `403 MEMORY_FORBIDDEN` 时按 `core/memory/errors.ts` 的码表渲染 toast；首次加载时通过 `GET /api/memory/{layer}/records` 的成功/失败决定是否显示「Create」按钮。避免前端硬编码 `tenant_admin` 判定逻辑。
4. **错误码本地化**：复用 [conversion-errors.ts](frontend/src/core/uploads/conversion-errors.ts) 已成熟的「stable code → bilingual toast」模式，新增 `core/memory/errors.ts`：
   ```ts
   export class LayeredMemoryError extends Error {
     constructor(public code: MemoryErrorCode, public detail: string) { super(detail); }
   }
   export function memoryErrorToastText(code: MemoryErrorCode, locale: Locale): string;
   ```
   对应 `MEMORY_NOT_FOUND` / `MEMORY_FORBIDDEN` / `MEMORY_VALIDATION` / `MEMORY_STORAGE` / `MEMORY_EMBEDDING_UNAVAILABLE` 五个稳定码（与后端 `memory-management-api` spec 一致）；新增 / 删除时**前后端必须同步修改**（与 conversion-errors 模式相同的 drift-detection 测试）。
5. **Feature flag**：前端通过 `process.env.NEXT_PUBLIC_MEMORY_LAYERED_ENABLED` 控制 Tab 顶栏可见性；关闭时 UI 行为与今天逐字节相同（仅渲染 User 内容、不显示 Tab）。后端 feature flag (`MEMORY_LAYERED_ENABLED`) 与之独立、互不依赖。
6. **Session Tab 的 thread 选择来源**：默认值 = 当前 URL 解析出的 `thread_id`（`/workspace/chats/[thread_id]` 或 `/workspace/agents/[agent_name]/chats/[thread_id]`）；用户在 settings 页打开 Session Tab 而无激活 thread 时，渲染空态 + 「先打开一个会话」CTA。不为 settings 页引入额外的 thread 选择器（避免与 sidebar 重复）。
7. **Promote to User 按钮的语义**：调用 `POST /api/memory/user/records` body 携带 `metadata.promoted_from = <session_record_id>`，**不删除原 Session 记录**（与 layered-memory-model spec 的「层间迁移 = 新建 + 反向引用」一致）。前端在两侧都能看到提升痕迹。

**替代方案（已否决）**：

- *把 `UserMemory` 改造为 `MemoryRecord[]`*：劣势是 982 行 UI 的所有 view 转换都要重写，回归风险高。本 change 选保留 + 旁路。
- *新建独立路由 `/workspace/memory/`*：劣势是与现有 `/workspace/settings/memory` 入口分裂，用户教育成本高。Tab 内分层是更熟悉的交互。
- *把三层 Tab 做成 sidebar 子项*：违反现有信息架构（settings 是用户级配置，sidebar 是工作区导航）；Tab 是更小代价的演进。

**前端测试**：

- 单测：`frontend/tests/unit/core/memory/scope-key.test.ts`（cache key 序列化稳定性）、`frontend/tests/unit/core/memory/errors.test.ts`（code → toast 文案表）、`frontend/tests/unit/core/memory/legacy-compat.test.ts`（旧 hook 行为冻结）。
- E2E：`frontend/tests/e2e/memory-layered-tabs.spec.ts`（Tab 切换、Session 默认 thread、403 → 只读、Promote 双向可见）。

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| **检索延迟**：Domain embedding 检索给每次 LLM 调用增加 50-200ms | (1) 用 ChromaDB 本地实例，无网络往返；(2) 复用现有 KB 的 collection 缓存；(3) 关键路径打 telemetry，超过阈值自动降级到 metadata-only 检索 |
| **写入污染**：LLM 抽取错把会话局部偏好写进 User 层 | (1) Session 层是写入默认值，触发 User 层需 confidence ≥ 0.7；(2) `MemoryRecord.source` 字段记录写入来源，前端展示时用户可一键迁移 / 删除；(3) telemetry `memory_write` 含 source 字段，便于审计 |
| **多租户 Domain 混淆**：错误的 scope 计算导致租户 A 的设备记忆泄露到租户 B | (1) `MemoryScope.tenant_id` 必填，service 在 read 时用 `with_kb_context` 恢复 contextvar，复用 KB 已验证的隔离机制；(2) 加入 `tests/test_memory_tenant_isolation.py`（仿照现有 `test_kb_tenant_isolation.py`）；(3) ChromaDB collection 名内嵌 `tenant_id` 前缀，物理上不可能跨查 |
| **迁移失败 / 部分迁移**：用户量大时迁移脚本 OOM | (1) 脚本按用户分批，单用户事务；(2) sentinel 文件让 service 双轨读，迁移失败不阻断业务；(3) 提供 `--dry-run` / `--user-id <id>` 参数定向迁移 |
| **API 双 schema 维护成本**：新旧路径并存，response model 偏离 | (1) 旧路径在新代码中通过 `layer=user + kind=fact|preference` 转译实现，仅一层薄壳；(2) `TestGatewayConformance` 类（已有模式）扩展校验新旧 schema 双向等价 |
| **Decay 误删活跃 record**：`exponential` 衰减下久未访问但仍重要的 record 排到末尾被截断 | (1) `decay_policy` 缺省 `never`；(2) `recall_count` 字段（每次被检索 +1）作为加权因子（实现期任务）；(3) 用户手动 pin 的 record 跳过衰减 |
| **LLM 抽取成本翻倍**：三层都要写入意味着每次入队后 LLM 调用更复杂 | (1) 抽取阶段单次 LLM 调用同时输出三层候选，prompt 内做分层；(2) Session 层 80% 场景靠规则匹配（如检测 "用 PDF" "锁定设备" 这类显式表达），不走 LLM；(3) Domain 层主要靠工具显式写入，不靠抽取 |
| **`SummarizationMiddleware` 与 Session 层语义重叠** | 明确分工：summarization 输出**对话压缩 summary**进 Session 层 `kind="context_summary"`；Session 层其他记录是 `kind="preference"|"fact"|"episode"`。两者通过 kind 区分检索 |
| **存储增长无界**：Domain 层是租户级共享，量级会持续累积 | (1) `valid_to` + 默认 90 天 retention 后台 sweeper（可关）；(2) tenant_admin 可设置租户级 quota（实现期任务）；(3) telemetry `storage_snapshot` 周期性快照存储用量 |

## Migration Plan

| 阶段 | 动作 | 时间窗 |
|---|---|---|
| **M0** | 本 change 落地（设计 + spec + tasks） | T0 |
| **M1** | 实现 `MemoryService` + Session / User 两层 + 兼容路由（不动 Domain） | T0+1 sprint |
| **M2** | 实现迁移脚本，单元测试通过；CI 跑迁移正反向 | T0+1 sprint |
| **M3** | 灰度：内部租户切到新路径（旧文件保留）；监控 telemetry | T0+2 sprint |
| **M4** | Domain 层 + `record_domain_memory` 工具 + ChromaDB collection 接入 | T0+3 sprint |
| **M5** | 业务 SOUL（`pump-fault-diagnosis` / `static-equipment-corrosion-diagnosis` / `ai-report--*`）改造为显式调用 | T0+4 sprint |
| **M6** | 删除旧 `memory.json` 双轨读，强制新路径 | T0+6 sprint |

**回滚路径**：

- M3 阶段问题 → 删除 sentinel 文件，service 回到 file/store 旧路径
- M4 阶段问题 → 关闭 `record_domain_memory` 工具，Session/User 不受影响
- M6 之前任意阶段，原文件未删除，可一键回退

## Open Questions

1. **Q1：Session 层是否需要持久化跨进程重启？**
   当前 `BaseStore` 在 in-memory 模式下重启即丢；对短会话（<24h）通常无影响，但跨日重连的复杂业务对话会丢失局部约束。倾向：sqlite/postgres backend 默认持久化；in-memory backend 不持久化但 emit warning。
2. **Q2：Domain 层的 `domain` 字段值需要枚举约束吗？**
   候选：自由字符串 vs 受控 vocabulary（`equipment` / `process` / `workorder` / `report_template` / `policy`）。倾向：先自由字符串 + 在 spec 中给出推荐 vocabulary，等业务沉淀后再约束。
3. **Q3：用户在 Session 层显式说「记住下一会话也用 PDF」时如何处理？**
   方案 A：LLM 抽取检测到「下一次也」类语义，写入 User 层。方案 B：暴露 `promote_session_memory_to_user(record_id)` 工具让用户显式提升。倾向：A（自动）+ B（兜底）。
4. **Q4：Embedding 模型变更时 Domain 层如何处理？**
   参考 KB 模块的 `EmbeddingDimensionMismatchError` + `embedding_dim` 绑定模式：每条 Domain record 记录写入时的 embedding model spec，检索时按当前 spec 过滤；不匹配的 record 走 metadata-only 路径。
5. **Q5：跨用户分享 Session 的特殊场景（团队协作 Thread）**
   当前 DeerFlow 单 Thread 单 user，未支持；如未来支持团队 Thread，Session scope 中 `user_id` 退化为 `thread_creator_id`，需要 spec 单独说明。本 change 不展开。

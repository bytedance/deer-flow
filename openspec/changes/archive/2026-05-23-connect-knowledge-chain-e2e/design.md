## Context

知识主链的四个环节均已独立存在：

| 环节 | 实现位置 | 状态 |
|------|---------|------|
| 上传 | `knowledge_base/service.py` → `upload_files` → document created (`index_status=pending`) | 可用 |
| 索引 | `knowledge_base/dispatcher.py` → `IndexingService.execute_index_job` → Chroma vector store | 可用（异步） |
| 检索 | `rag/tools.py` → `search_knowledge_base` → `resolve_runtime_kb_selection` | 可用 |
| 报告消费 | LLM 在对话中调用 `search_knowledge_base`，再通过 report template tools 生成报告 | 可用（隐式） |

断层：
1. 上传后用户需主动刷新查看索引状态，无即时反馈
2. 权限校验在 `search_knowledge_base` 中已有，但 report run 上下文中没有显式校验路径
3. E2E 测试 `test_knowledge_chain_e2e.py` 是数据结构模拟，不是真实 pipeline
4. 报告模板 DSL 没有显式声明 KB 数据源（KB 消费纯粹靠 LLM 自主判断）

## Goals / Non-Goals

**Goals:**
- 上传后前端即时显示索引状态（pending/indexing/indexed/failed），自动轮询直到终态
- 加固知识权限在 workspace → retrieval → report run 三链一致性
- 将 E2E 测试从结构模拟升级为真实 pipeline 集成测试
- 确保边界场景（索引未完成/失败/权限拒绝）有明确用户提示

**Non-Goals:**
- 不在报告模板 DSL 中新增 KB 数据源声明（这是 ISSUE-07 的范围，涉及 DSL schema 变更）
- 不改变索引调度器架构（dispatcher 已工作）
- 不新增 KB 管理页面或 CRUD 功能
- 不新增 KB 相关 API 端点

## Decisions

### 1. 上传反馈：前端轮询而非 WebSocket

当前 `useDocumentIndexStatus` hook 已在轮询文档状态。增强方案：上传成功后立即开始轮询（每 2s 一次），直到 `index_status` 进入终态（`indexed` 或 `failed`），然后停止轮询。使用 `useDocumentIndexStatus` 的 `refetchInterval` 参数。

**Alternatives considered:**
- WebSocket 推送 → 过度设计，上传是低频操作
- SSE 长连接 → 同上，前端轮询足够

### 2. 权限一致性：运行时校验确保 `UserContext` 传递

`search_knowledge_base` 工具已通过 `get_effective_user_id()` + `get_current_tenant_id()` 构建 `UserContext` 并传给 `KbAccessControl`。需要确认报告 run 上下文中同样路径可用（两者都在同一个 thread/run 内执行，contextvars 一致），无需额外改造。

加固措施：在 `rag/tools.py` 的 `_search_selected_kbs` 中，对每个候选 KB 显式调用 `can_read()`，对拒绝的 KB 返回结构化错误信息（当前已有 `KbResolutionError`）。

### 3. E2E 测试：真实 pipeline 而非数据库 mock

现有 `test_knowledge_chain_e2e.py` 使用 dict 结构模拟。新增真实 pipeline 测试：
- 创建真实 KB → 上传测试文件 → 触发同步索引（dispatcher.enabled=False, inline）→ 调用 `search_knowledge_base` → 验证检索结果包含上传内容
- 边界场景：索引未完成时检索返回空/部分结果、索引失败有错误信息、权限拒绝有结构化错误

测试放在 `test_knowledge_chain_e2e.py` 中，标记为 `integration`。

**Alternatives considered:**
- 保持现有模拟测试 → 达不到验收标准"至少有一条端到端验证路径"
- 新增独立集成测试文件 → 逻辑上属于同一主题，扩建现有文件即可

## Risks / Trade-offs

- [轮询频率] 2s 轮询可能增加后端负载 → 每 KB 每文档最多一次轮询（终态即停），上传是低频操作，负载可忽略
- [同步索引测试] 真实集成测试需要 Embedding Provider → CI 需要有可用的 embedding 端点或 mock embedding provider → 使用 pytest marker 标记 `integration`，CI 中跳过或使用 mock embedding
- [权限加固影响] 显式 can_read 校验可能暴露新的 403 → 这是预期行为，当前实际已在 `resolve_runtime_kb_selection` 中隐式过滤

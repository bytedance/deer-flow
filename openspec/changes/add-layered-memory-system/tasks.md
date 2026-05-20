## 1. 数据模型与契约（Phase 1：契约层）

- [ ] 1.1 新建 `backend/packages/harness/deerflow/agents/memory/records.py`，定义 `MemoryScope` / `MemoryRecord` Pydantic 模型，字段与 layered-memory-model spec 一致；为 kind × layer 不合法组合写 validator
- [ ] 1.2 新建 `backend/packages/harness/deerflow/agents/memory/exceptions.py`，定义 `MemoryNotFound` / `MemoryScopeForbidden` / `MemoryStorageError` / `MemoryEmbeddingUnavailable` / `MemoryValidationError`
- [ ] 1.3 新建 `backend/packages/harness/deerflow/agents/memory/decay.py`，实现 `decay_factor(elapsed_seconds, policy_str)`，覆盖 `never` / `linear:days=N` / `exponential:half_life_days=N` 三种策略
- [ ] 1.4 新建 `backend/packages/harness/deerflow/agents/memory/fingerprint.py`，实现 `content_fingerprint(scope, kind, content)` 用于幂等去重；规范化算法与现状 `updater._normalize_fact_content` 对齐
- [ ] 1.5 单测：`backend/tests/test_memory_records.py` 覆盖 schema 验证、kind×layer 组合、空 content 拒绝、confidence 边界
- [ ] 1.6 单测：`backend/tests/test_memory_decay.py` 覆盖三种 policy 与时间窗
- [ ] 1.7 单测：`backend/tests/test_memory_fingerprint.py` 覆盖空白归一化、跨 scope 隔离

## 2. MemoryService 接口与依赖（Phase 1：契约层）

- [ ] 2.1 新建 `backend/packages/harness/deerflow/agents/memory/service.py`，定义 `MemoryService` Protocol（`read` / `write` / `forget` / `compose_for_prompt`）
- [ ] 2.2 在同文件实现 `DefaultMemoryService`，构造函数接受 `session_storage / user_storage / domain_storage / embedder` 四个依赖（DI），便于测试替换
- [ ] 2.3 实现内部 `_resolve_scope_from_context()`，从 `get_current_tenant_id()` + `get_effective_user_id()` + 调用方传入的 `thread_id/agent_name/domain/entity_id` 组装 `MemoryScope`，拒绝 `default` 租户写入（由 config flag 控制）
- [ ] 2.4 包装所有 service 入口为 `with_kb_context(...)`，确保后台 worker 调用时 contextvar 正确恢复
- [ ] 2.5 添加 `tests/test_memory_boundary.py`：用 importlib 静态扫描，断言 `agents/memory/storage.py` 不被 `memory/service.py` 之外任何模块直接 import
- [ ] 2.6 编写 `tests/test_memory_service_contract.py`：用内存假实现验证 read/write/forget/compose 的契约（含 idempotent、错误类型、tenant 隔离）

## 3. Session 层存储（Phase 2：实现层）

- [ ] 3.1 新建 `backend/packages/harness/deerflow/agents/memory/session_storage.py`，实现 `SessionStorage`，用 `BaseStore` namespace `("memory_session", tenant, user, thread)`；存全文 record，不持久 embedding
- [ ] 3.2 实现 Session 检索：substring/keyword 匹配 + 时间倒序，top_k ≤ 50
- [ ] 3.3 单测：`tests/test_memory_session_storage.py` 覆盖 thread 隔离、删除、reload、跨 thread 不可见
- [ ] 3.4 在 `MemoryMiddleware` 中钩入 Session 写入（**仅在本地分支验证流程，不合并**）

## 4. User 层重构（Phase 2：实现层）

- [ ] 4.1 在 `agents/memory/storage.py` 保留 `FileMemoryStorage` / `StoreMemoryStorage` 两个类（向后兼容），新增 `UserStorageAdapter` 把它们包装成符合 `MemoryRecord` 协议的接口
- [ ] 4.2 把 `updater.py` 的 `update_memory_async` 重写为：先抽取候选 → 投递到 `MemoryService.write`（service 内部分流到 Session/User/Domain）；旧函数 `create_memory_fact / delete_memory_fact / update_memory_fact` 转译为 service 调用
- [ ] 4.3 单测：`tests/test_memory_updater_v2.py` 验证抽取分流、confidence 阈值、whitespace 去重、tenant 隔离
- [ ] 4.4 回归测：现有 `tests/test_memory_updater.py` / `tests/test_memory_*.py` 全部保持绿（要求：行为等价）

## 5. Domain 层存储（Phase 3：实现层）

- [ ] 5.1 新建 `backend/packages/harness/deerflow/agents/memory/domain_storage.py`，结构化字段写 `BaseStore` namespace `("memory_domain", tenant, domain, entity_id|"_")`
- [ ] 5.2 接入 ChromaDB：复用 `knowledge_base/` 的 `get_embedding_provider(spec)`，每条 Domain record 写入独立 collection `memory_domain_<tenant_id>`，`metadata` 含 `domain / entity_id / kind / record_id`
- [ ] 5.3 实现 Domain 检索：先 metadata pre-filter（`tenant_id` + `domain` + `entity_id?`），再 cosine 相似度 top_k；query=None 直接返空
- [ ] 5.4 处理 `EmbeddingDimensionMismatchError`：record 上记录 `embedding_model` 字段，查询时与当前 embedder 的 spec 比对，不匹配的走 metadata-only 路径
- [ ] 5.5 处理 ChromaDB 不可达：write 时 `embedding=None` + telemetry `memory_embedding_unavailable`；read 时降级到 metadata-only + 503 响应
- [ ] 5.6 单测：`tests/test_memory_domain_storage.py` 覆盖 collection 命名、tenant 隔离、metadata 过滤、embedding 不可达降级
- [ ] 5.7 跨租户隔离测试：`tests/test_memory_tenant_isolation.py`（参考现有 `tests/test_kb_tenant_isolation.py` 模式）

## 6. 显式工具与 Middleware 改造（Phase 3：实现层）

- [ ] 6.1 新建 `backend/packages/harness/deerflow/tools/builtins/memory_tools.py`，实现 `record_domain_memory(content, domain, entity_id?, confidence?, valid_from?, valid_to?, tags?)` 工具；user_id/tenant_id 从 runnable config 取，永远不接受 LLM 输入
- [ ] 6.2 工具内部直接调 `MemoryService.write(scope.layer="domain", source="tool_explicit", confidence=入参或1.0)`
- [ ] 6.3 在 `lead_agent` 的 tool 装载逻辑中，按 SOUL 配置启用工具；默认对 `pump-fault-diagnosis` / `static-equipment-corrosion-diagnosis` / `reciprocating-fault-diagnosis` / `ai-report--*` 四类 SOUL 启用
- [ ] 6.4 重写 `MemoryMiddleware`：
  - 用户 + 最终 AI 消息出列后，调 `MemoryService.write` 时传入 `default_layer_hint="session"`，由 service 内部 LLM 抽取后再分流
  - 在每次 LLM 调用前调 `MemoryService.compose_for_prompt(...)`，把返回字符串注入 `<memory>` 段
- [ ] 6.5 删除/迁移旧 `prompt.py` 抽取模板，改为按层产出候选；prompt 加入 `expected_layer` 提示
- [ ] 6.6 单测：`tests/test_memory_middleware_v2.py` 覆盖三层分流、confidence 门限、空 query 处理

## 7. 检索融合与 token 预算（Phase 3：实现层）

- [ ] 7.1 实现 `MemoryService.compose_for_prompt`，遵循 memory-retrieval-and-injection spec：Session>User>Domain 优先级 + 贪心打包 + 整 record 截断 + 子块按需省略
- [ ] 7.2 token 计数复用现有 summarization middleware 的 token counter，避免不一致
- [ ] 7.3 单测：`tests/test_memory_compose.py` 至少 8 个用例（满 budget / 部分 budget / 单层空 / 全空 / 截断行为 / 子块省略 / 优先级反转保护）

## 8. Telemetry（Phase 3：实现层）

- [ ] 8.1 新建 `backend/packages/harness/deerflow/agents/memory/telemetry.py`，复用 `report_templates/telemetry.py` 模式
- [ ] 8.2 在 `MemoryService` 各方法埋点：`memory_write` / `memory_read` / `memory_forget` / `memory_compose_outcome` / `memory_embedding_unavailable`
- [ ] 8.3 在迁移脚本埋 `memory_migration`
- [ ] 8.4 JSONL 落盘到 `{DEER_FLOW_HOME}/memory/.telemetry.log`，env `DEER_FLOW_MEMORY_TELEMETRY_LOG=0` 关闭
- [ ] 8.5 单测：`tests/test_memory_telemetry.py` 覆盖事件计数、JSONL 落盘、opt-out

## 9. Gateway API 扩展（Phase 4：API 层）

- [ ] 9.1 修改 `backend/app/gateway/routers/memory.py`：
  - 现有路由（`GET /api/memory` 等）改为内部调 `MemoryService` 同时返回 legacy schema
  - 新增 `GET/POST /api/memory/{layer}/records`、`GET/PATCH/DELETE /api/memory/{layer}/records/{id}`、`POST /api/memory/{layer}/forget`
  - 错误统一封装 `{detail, code}` 格式
- [ ] 9.2 新建 `backend/app/gateway/routers/telemetry_memory.py`：`GET /api/telemetry/memory/summary`
- [ ] 9.3 权限装饰器：`record_domain_memory` REST 写入 + `POST /api/memory/domain/forget` 限 `tenant_admin` / `superadmin`；用户 layer 自我隔离
- [ ] 9.4 路由测试：`tests/test_memory_layered_routes.py`、`tests/test_memory_layered_compat.py`（验证旧路径与 `?layer=user` 等价）
- [ ] 9.5 扩展 `TestGatewayConformance`：把新增 response model（`LayeredMemoryRecordResponse` 等）纳入 `DeerFlowClient` 输出校验

## 10. 数据迁移（Phase 4：迁移）

- [ ] 10.1 新建 `backend/scripts/migrate_layered_memory.py`，支持 `--dry-run` / `--user-id <id>` / `--rollback`
- [ ] 10.2 迁移逻辑：扫描 `{base_dir}/users/*/memory.json` 与 `{base_dir}/users/*/agents/*/memory.json`，按 layered-memory-model spec 中的映射规则生成 User 层 records 并写入新 namespace
- [ ] 10.3 sentinel 文件：写完后落 `.migrated` 标记；service 在读到 sentinel 后从 Store 读，否则双轨读旧文件
- [ ] 10.4 单测：`tests/test_memory_migration.py` 覆盖正向 / 幂等 / rollback / 部分失败回滚
- [ ] 10.5 在 `backend/CLAUDE.md` 增加迁移命令与回滚说明

## 11. 文档与 SOUL 改造（Phase 5：发布）

- [ ] 11.1 在 `backend/CLAUDE.md` 的 "Memory System" 章节追加分层模型说明（不替换现有，append 子章节）
- [ ] 11.2 新增 `backend/docs/MEMORY_LAYERS.md`：开发者集成指南、`record_domain_memory` 工具用法、API 速查
- [ ] 11.3 更新 `pump-fault-diagnosis` / `static-equipment-corrosion-diagnosis` / `reciprocating-fault-diagnosis` 的 SOUL.md，在「诊断结论」节点显式调用 `record_domain_memory`
- [ ] 11.4 更新 `ai-report--daily/weekly/monthly` 的 SOUL.md，在生成报告后将关键发现写入 Domain 层
- [ ] 11.5 在 `frontend/CLAUDE.md` 增加分层记忆 UI 章节，链接 `core/memory/errors.ts` drift 测试与 Tab 行为契约（与 backend `MEMORY_LAYERED_ENABLED` flag 协同说明）

## 12. 前端三层 UI（Phase 5：发布）

- [ ] 12.1 [frontend/src/core/memory/types.ts](frontend/src/core/memory/types.ts) 追加 `MemoryLayer` / `MemoryScope` / `MemoryRecord` / `LayeredMemoryFilter` / `MemoryTelemetrySummary`；保留既有 `UserMemory` / `MemoryFact` / `MemoryFactInput` / `MemoryFactPatchInput` 完全不动
- [ ] 12.2 新建 [frontend/src/core/memory/errors.ts](frontend/src/core/memory/errors.ts)：`MemoryErrorCode` 枚举 + `LayeredMemoryError` 类 + `memoryErrorToastText(code, locale)`；模式参考 [conversion-errors.ts](frontend/src/core/uploads/conversion-errors.ts)
- [ ] 12.3 [frontend/src/core/memory/api.ts](frontend/src/core/memory/api.ts) 新增 `listLayeredRecords` / `getLayeredRecord` / `createLayeredRecord` / `updateLayeredRecord` / `deleteLayeredRecord` / `forgetLayeredRecords` / `getMemoryTelemetrySummary`；解析响应 `code` 字段时抛 `LayeredMemoryError`，未识别错误维持原 `readMemoryResponse` 的 `Error(detail)` 行为
- [ ] 12.4 [frontend/src/core/memory/hooks.ts](frontend/src/core/memory/hooks.ts) 新增 `useLayeredMemoryRecords` / `useCreateLayeredRecord` / `useUpdateLayeredRecord` / `useDeleteLayeredRecord` / `useForgetLayeredMemory` / `useMemoryTelemetrySummary`；实现 `scopeKey(scope)` 稳定排序
- [ ] 12.5 [frontend/src/components/workspace/settings/memory-settings-page.tsx](frontend/src/components/workspace/settings/memory-settings-page.tsx) 改造：
  - 抽取既有内容为 `UserMemoryTab` 子组件（**逐字节冻结**现有 view-model 与交互）
  - 新增 `SessionMemoryTab`、`DomainMemoryTab` 子组件
  - 顶部 Tab 切换：受 `process.env.NEXT_PUBLIC_MEMORY_LAYERED_ENABLED === "1"` 控制可见性；缺省时 page 行为与今天相同
  - Session Tab 通过 `usePathname` / Next.js route params 解析 `thread_id`；无激活 thread 时渲染空态 + CTA
- [ ] 12.6 单测：
  - `frontend/tests/unit/core/memory/scope-key.test.ts`：`scopeKey()` 顺序无关稳定性
  - `frontend/tests/unit/core/memory/errors.test.ts`：code → bilingual toast 表 + drift detection 与后端 `MemoryService` exception 同步
  - `frontend/tests/unit/core/memory/legacy-compat.test.ts`：`useMemory()` 行为冻结，`["memory"]` cache key 不被新 mutation 失效
- [ ] 12.7 E2E：`frontend/tests/e2e/memory-layered-tabs.spec.ts` 覆盖 Tab 切换、Session 默认 thread、403 → 只读、Promote 双向可见
- [ ] 12.8 i18n：在 `frontend/src/messages/{en-US,zh-CN}.json` 增加 Tab 标签、错误码 toast、Promote 按钮、Session 空态等文案；保持既有 `settings.memory.*` 不变

## 13. 验收与发布（Phase 5：发布）

- [ ] 12.1 全量回归：`make test` 在 backend 全绿；现有 `tests/test_memory_*.py` 全部通过
- [ ] 12.2 灰度上线 checklist：feature flag `MEMORY_LAYERED_ENABLED`（默认 `false` 等价旧行为）；内部租户先开
- [ ] 12.3 监控埋点验证：`GET /api/telemetry/memory/summary` 返回非零计数；`.telemetry.log` 有写入
- [ ] 12.4 性能基准：在 100 user-records / 200 domain-records 的样本下，`compose_for_prompt` p95 < 100ms（不含 embedding 计算）；用 `tests/test_memory_perf.py` 守门
- [ ] 12.5 archive change：执行 `openspec archive add-layered-memory-system`，把 4 个新 capability 落到 `openspec/specs/`

# Sprint Plan: 外部数据源选择与 Agent 集成

> 基于设计文档 `2026-05-12-external-data-source-selection-design.md`

## Sprint Summary

```
Sprint Goal: Agent 能通过 http_connector 动态获取外部数据源列表，渲染选择表单，用户选择后获取数据并分析展示
Duration: 2 weeks (2026-05-12 ~ 2026-05-23)
Team Capacity: 40 story points (假设 2 名后端 + 1 名前端，每人每周 8 SP)
Committed Stories: 34 story points across 12 stories
Buffer: 6 SP (15%) reserved for bugs and unexpected work
```

---

## Team Capacity Estimation

| 成员 | 角色 | 可用天数 | Story Points |
|------|------|----------|-------------|
| 后端 A | Backend (Tool/Config) | 10 天 | 16 SP |
| 后端 B | Backend (MCP/Skill) | 10 天 | 16 SP |
| 前端 C | Frontend (GenUI) | 8 天 (2 天会议) | 12 SP |
| **合计** | | | **44 SP** |
| **Buffer (15%)** | | | **-6 SP** |
| **可用容量** | | | **38 SP** |

---

## Stories (按优先级排序)

### Phase 1: 平台 http_connector Tool（核心路径）

| # | Story | SP | Owner | 依赖 | 验收标准 |
|---|-------|-----|-------|------|---------|
| 1 | 实现 `HttpConnectorConfig` Pydantic 模型 | 2 | 后端A | 无 | 模型定义完整，含 max_response_bytes/max_retries/retry_on_status/cache_ttl_seconds 字段；单元测试覆盖 resolved_headers() |
| 2 | `AppConfig` 新增 http_connectors 字段 + 方法 | 3 | 后端A | #1 | get_http_connector/list_connector_names 方法可用；config.yaml hot-reload 验证通过 |
| 3 | 实现 `http_connector` async tool（含截断+重试+可观测性） | 5 | 后端A | #2 | async tool 注册成功；响应截断在 max_bytes 处生效；重试逻辑对 502/503/504 生效；结构化日志包含字段：connector_name, tenant_id, status_code, latency_ms, response_size, truncated, retry_count；慢请求(>10s) WARN 日志 |
| 4 | 注册到 BUILTIN_TOOLS + 集成验证 | 2 | 后端A | #3 | Agent 运行时可调用 http_connector；无 connector 配置时返回友好错误 |

**Phase 1 小计：12 SP，关键路径，阻塞后续所有 Story**

> **可观测性说明**：Section 11.1 的结构化日志已纳入 Story #3 验收标准。告警阈值（连续失败通知、截断率监控）属于运维层面，当前阶段仅输出日志，不引入告警系统依赖（与设计文档 Section 11.1 "当前阶段：仅日志，不引入新依赖" 一致）。

> **安全设计说明**：Section 11 的安全要求（预配置 URL 防 SSRF、环境变量 token、租户隔离）已内嵌在 Story #1（config 模型 resolved_headers）、#2（tenant_id 隔离查询）、#3（只调用预配置 connector）的实现中，不单独拆 Story。Sprint 结束前通过 security-reviewer 统一检查（见 Definition of Done）。

### Phase 2: Skill 改造 + MCP 支持

| # | Story | SP | Owner | 依赖 | 验收标准 |
|---|-------|-----|-------|------|---------|
| 5 | 改造 data-analyst SOUL.md（4 级优先级） | 3 | 后端B | #4 | SOUL.md 包含 MCP→Script→http_connector→静态表单 4 级降级；Agent 按指导执行 |
| 6 | data-analyst AgentConfig 添加 mcp_servers 绑定 | 2 | 后端B | 无 | Agent 配置包含 mcp_servers: [data-platform]；MCP tools 自动合并到 tool set |
| 7 | 编写 config.yaml http_connectors 示例配置 | 1 | 后端B | #2 | list_datasets/fetch_dataset/dataset_schema 三个 connector 配置完整 |
| 8 | 定义 data_catalog.* MCP 工具协议文档 | 2 | 后端B | 无 | 协议文档包含 4 个 tool 的参数/返回值定义；含 Python MCP Server 示例代码 |

**Phase 2 小计：8 SP**

### Phase 3: 前端适配

| # | Story | SP | Owner | 依赖 | 验收标准 |
|---|-------|-----|-------|------|---------|
| 9 | GenUI form 组件验证动态选项渲染 | 3 | 前端C | #4 | Agent 返回动态 options 的 form 能正确渲染；callback 提交后 Agent 收到 payload |
| 10 | 验证 inline block rendering 与 http_connector 配合 | 3 | 前端C | #9 | 图表/表格渲染在对应轮次位置；streaming 期间 blocks 实时显示 |
| 11 | form disableExpiration 在历史消息中生效验证 | 2 | 前端C | #9 | 历史消息中的表单显示 expired 状态而非倒计时 |

**Phase 3 小计：8 SP**

### Phase 4: 测试与文档

| # | Story | SP | Owner | 依赖 | 验收标准 |
|---|-------|-----|-------|------|---------|
| 12 | 端到端集成测试 + 接入文档 | 6 | 后端A+B | #5, #10 | mock 外部 API 的 E2E 测试通过；接入文档覆盖 http_connectors + MCP 两种方式 |

**Phase 4 小计：6 SP**

---

## 依赖关系图

```
#1 HttpConnectorConfig
 └─→ #2 AppConfig 集成
      └─→ #3 http_connector tool 实现
           └─→ #4 注册 BUILTIN_TOOLS
                ├─→ #5 SOUL.md 改造
                ├─→ #7 config.yaml 示例
                ├─→ #9 前端 form 验证
                │    ├─→ #10 inline rendering 验证
                │    └─→ #11 disableExpiration 验证
                └─→ #12 E2E 测试

#6 MCP 绑定 (独立，可并行)
#8 MCP 协议文档 (独立，可并行)
```

**关键路径**：#1 → #2 → #3 → #4 → #5 → #12

---

## Sprint 日程安排

| 日期 | 后端 A | 后端 B | 前端 C |
|------|--------|--------|--------|
| Day 1-2 | #1 Config 模型 | #6 MCP 绑定 + #8 协议文档 | 其他任务 / 准备 |
| Day 3-4 | #2 AppConfig 集成 | #8 协议文档（续） | 其他任务 |
| Day 5-7 | #3 http_connector tool | #7 config.yaml 示例 | #9 form 动态渲染验证 |
| Day 8 | #4 BUILTIN_TOOLS 注册 | #5 SOUL.md 改造 | #10 inline rendering |
| Day 9 | #12 E2E 测试 | #5 SOUL.md（续）| #11 disableExpiration |
| Day 10 | #12 E2E + 文档 | #12 E2E + 文档 | Bug fix / Buffer |

---

## Risks & Mitigations

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 外部 API mock 不充分，E2E 测试覆盖不全 | 中 | 中 | 使用 httpx mock transport；定义标准响应 fixture |
| LangGraph async tool 注册方式与现有 sync tools 冲突 | 高 | 低 | 提前在 Day 1 做 spike：验证 async tool 在现有 Agent 中能正常调用 |
| SOUL.md 指导过于复杂，Agent 不按预期执行 | 中 | 中 | 迭代测试：先用简单 2 级指导验证，再扩展到 4 级 |
| 前端 GenUI form 动态 options 数量过多导致渲染卡顿 | 低 | 低 | form select 组件增加虚拟滚动（如超过 100 项）；http_connector 配置 limit |
| config.yaml hot-reload 在 http_connectors 段不生效 | 中 | 低 | 单元测试验证 mtime 变更后 get_http_connector 返回新配置 |

---

## Definition of Done

- [ ] 所有 Story 的验收标准通过
- [ ] `pnpm typecheck` 通过（前端）
- [ ] `pytest` 通过（后端，含新增测试）
- [ ] 无 CRITICAL/HIGH 安全问题（security-reviewer 检查）
- [ ] 接入文档可供其他团队参考使用
- [ ] Demo：使用 mock 外部 API 完成完整流程（选择数据源 → 获取数据 → 图表展示）

---

## Sprint Goal

**Agent 能通过配置驱动的 http_connector 动态获取外部数据源，渲染交互式选择表单，用户选择后自动获取数据并以图表/表格展示分析结果。**

---

## Out of Scope (下一个 Sprint)

- Redis 缓存实现（cache_ttl_seconds 为预留字段）
- Skill Script 模式实现（需 sandbox tool group 前置）
- GenUI Block 持久化（设计文档 Section 3.6 明确标注为 "Phase 2+" 已知限制，本 Sprint 不解决；当前页面刷新后历史 blocks 不可恢复）
- 多租户 Admin API 管理 connector 配置
- image 组件 + table 图片列支持
- 多级选择（两步表单）

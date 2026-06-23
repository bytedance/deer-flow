# DeerFlow Admin & Operations Console — 汇报方案

- **Date**: 2026-06-18
- **汇报对象**: DeerFlow 部署方 / 产品负责人 / 运维负责人
- **对应 spec**: `2026-06-17-deerflow-qa-tracking-design.md`、`2026-06-17-deerflow-qa-tracking-feature-design.md`、`2026-06-17-deerflow-qa-tracking-implementation-architecture.md`
- **本文档作用**：从 admin / 运营 / 用户跟踪视角，给出 DeerFlow 控制台的能力全景 + 3 期 
- **不包含**：具体 API schema、数据库迁移脚本、组件级实现（→ 后续 spec 文档）

---

## 0. 一句话总结

> DeerFlow 平台已具备完整的用户、会话、运行、反馈、memory 5 维数据，但 admin 没有运营视图。建议 **3 周内分 3 期** 落地一个 **6 模块** 的 admin 控制台，全部基于现有数据，v1 当周就能让 admin 看到"谁在用、用得怎么样、token 烧在哪"。

---

## 1. 业务背景 & 价值定位

### 1.1 当前现状

- DeerFlow 是 self-hosted 的 AI 智能体平台，已通过 5 套数据表完整记录 `users` / `threads_meta` / `runs` / `feedback` / `memory` 5 维数据。
- `User.system_role` 字段已支持 `admin` / `user` 两类身份；`require_permission` 装饰器已实现基于 resource/action 的权限校验。
- 已有的 spec `2026-06-17-deerflow-qa-tracking-feature-design.md` 规划了 `Q&A Analytics`（`/admin/analytics`）一个页面，但仅覆盖"内容运营"一个角。

### 1.2 关键空白

1. **看人**——admin 不知道"现在有谁在用、用得怎么样、谁已经流失"
2. **看运营**——admin 不知道"哪些会话成功、哪些失败、用户反馈好不好"
3. **看成本**——admin 不知道"token 烧在哪、哪个 model/agent 最贵"
4. **看实时**——admin 不知道"现在谁在跟 AI 聊、聊的是什么"
5. **做治理**——admin 没办法"导出运营数据、做数据脱敏、清理过期数据"

### 1.3 价值定位

- **防御性价值**：及时发现错误集中的 model/agent，避免线上事故；及时发现活跃用户下滑趋势。
- **进攻性价值**：通过 token 消耗榜找到降本空间；通过反馈样本改进 prompt / 工具设计。
- **合规价值**：数据导出 + 脱敏为审计 / 月报提供基础；保留策略为长期合规留出扩展点。

---

## 2. 六大功能模块（Feature Modules）

> 全部基于 DeerFlow **已落库的数据**，无需新表。
> 实施成本档位：✅ 零成本 / 🟢 1 天内 / 🟡 1-3 天 / 🔴 需 schema 改动

### 模块 A · 用户运营中心

| 项 | 内容 |
|---|---|
| 入口 | `/admin/users`（列表）+ `/admin/users/[id]`（画像） |
| 用户价值 | 看"谁在用、谁用得多、谁不用了、谁最贵" |
| 关键页面 | ① 用户列表（角色/创建时间/最后活跃/累计 token）<br>② 用户画像（累计 run / token / 错误数 / 反馈率 / 习惯 model）<br>③ 用户最近 thread 列表<br>④ 用户长期 memory 浏览 |
| 数据基础 | `UserRow`（`backend/packages/harness/deerflow/persistence/user/model.py:22`）+ `RunRow.user_id` 聚合（已有） |
| 实施成本 | 🟢 1 天 |
| 与已有 design 的关系 | design 文档中"User 过滤器"只支持按 user_id 等值过滤 run，没有用户视角的入口页 |

### 模块 B · Q&A 内容运营（design 文档已规划，作为 v1 锚点）

| 项 | 内容 |
|---|---|
| 入口 | `/admin/analytics` |
| 用户价值 | admin 可搜索"所有用户问过什么、AI 答了什么" |
| 关键页面 | ① Q&A 明细列表（filter：日期 / user / assistant / model / status / 全文搜索）<br>② 详情 drawer（首轮问题 + 最终回答 + 资源 + Follow-up 链）<br>③ 4 个 KPI 卡（今日 run / 错误率 / 总 token / 活跃用户数）<br>④ 7 日趋势图<br>⑤ CSV / JSONL 导出 |
| 数据基础 | `RunRow.first_human_message` / `last_ai_message`（已有） |
| 实施成本 | 🟡 2-3 天（功能最多的一页，但 design 文档已就绪） |
| 与已有 design 的关系 | **完全对应** `2026-06-17-deerflow-qa-tracking-feature-design.md`；本方案在 v1 之上扩展 KPI / 趋势图 / drawer 增强 |

### 模块 C · 资源 & 成本看板

| 项 | 内容 |
|---|---|
| 入口 | `/admin/usage` |
| 用户价值 | 看"token 烧在哪"——按 user / model / assistant / agent 类型排行 |
| 关键页面 | ① 全平台 token 总览（in / out 分摊）<br>② 按 user 排序的消耗榜（top 50）<br>③ 按 model 拆解（in / out / 调用次数）<br>④ subagent / middleware 占比饼图 |
| 数据基础 | `RunRow.total_tokens` / `lead_agent_tokens` / `subagent_tokens` / `middleware_tokens`（已有）<br>现成端点：`/api/threads/{thread_id}/runs/token-usage`（`backend/app/gateway/routers/thread_runs.py:427`） |
| 实施成本 | ✅ 0.5 天（仅前端，复用现有 schema） |
| 与已有 design 的关系 | 完全新增；design §4 drawer 仅展示单 run token，无跨 run / 跨 thread 视角 |

### 模块 D · 质量监控

| 项 | 内容 |
|---|---|
| 入口 | `/admin/quality` |
| 用户价值 | 看"产品好不好"——错误率、用户反馈 |
| 关键页面 | ① 错误率趋势（按天 / 按 model）<br>② 错误样本列表（含 first_human_message + 错误信息）<br>③ 👍 / 👎 反馈比例趋势<br>④ 差评样本（点开 join 完整 run 详情） |
| 数据基础 | `RunRow.status='error'` + `FeedbackRow.rating`（已有）<br>现成聚合：`FeedbackRepository.aggregate_by_run`（`backend/packages/harness/deerflow/persistence/feedback/sql.py:205`） |
| 实施成本 | 🟢 1 天 |
| 与已有 design 的关系 | 完全新增；design 文档未涉及 feedback 维度 |

### 模块 E · 实时运营（v3 视情况）

| 项 | 内容 |
|---|---|
| 入口 | `/admin/activity` |
| 用户价值 | 看"现在谁在跟 AI 聊" |
| 关键页面 | ① inflight run 列表（跨 user）<br>② SSE 旁路监听任意 run（只读） |
| 数据基础 | `RunStore.list_inflight`（已有）<br>SSE streaming 框架：`/api/threads/{id}/runs/stream`（`thread_runs.py:147`） |
| 实施成本 | 🟡 1-2 天 |
| 与已有 design 的关系 | design §11 明确"不做实时推送"——**这是与已有 design 的一个分歧点**，v1 / v2 阶段不实施 |

### 模块 F · 数据治理（v3 视情况）

| 项 | 内容 |
|---|---|
| 入口 | `/admin/data` |
| 用户价值 | 数据导出 / 脱敏 / 审计 / 保留 |
| 关键页面 | ① 跨维度导出（user / day / model 聚合 CSV）<br>② 脱敏导出开关（email 哈希化、message 截断）<br>③ 审计日志（如启用）<br>④ 保留策略（如启用） |
| 数据基础 | 部分已有（导出端点），部分需补（脱敏开关、审计、retention） |
| 实施成本 | 🟡 2 天（不含 schema 改动） |
| 与已有 design 的关系 | design §6 已有 CSV / JSONL 导出框架；本模块在 v3 扩展脱敏 + 多维度 |

---

## 3. 三期 Roadmap

> 推荐采用 **价值驱动切法**——把"高价值低成本"先上线，让 admin 当周就能用上。

### 🟢 Phase 1（v1）— 1.5 周 · "基础三件套"

**目标**：让 admin 当周能"看人、看会话、看成本"。

| 任务 | 描述 | 实施成本 |
|---|---|---|
| Admin landing 路由壳 | 新增 `/admin` 路由 + admin 角色守卫 | 🟢 0.5 天 |
| 模块 A · 用户列表 + 画像 | 端点 `/api/admin/users`、`/api/admin/users/[id]/overview`；前端 `/admin/users` 页面 | 🟢 1 天 |
| 模块 B · Q&A Analytics | design 文档主体功能（list / filter / drawer / export） | 🟡 2-3 天 |
| 模块 C · 资源 & 成本看板 | 端点 `/api/admin/usage/summary`；前端 `/admin/usage` 页面 | ✅ 0.5 天 |
| KPI 卡片 | 4 个 KPI（今日 run / 错误率 / 总 token / 活跃用户数） | 🟢 0.5 天 |
| 7 日趋势图 | runs/天 折线 + token/天 折线 | 🟢 0.5 天 |

**v1 验收标准**：
- admin 登录后能完成"找一个用户 → 看他的 thread → 看他的 token 消耗 → 导出 Q&A"完整链路。
- 列表页 < 500ms（10k runs 数据规模，参照 design §8 性能预期）。
- 4 个 KPI 卡 + 趋势图随数据更新而实时刷新。

### 🟡 Phase 2（v2）— 1 周 · "质量 + 协作"

**目标**：让 admin 能"看质量"——错误、反馈、跨用户 thread。

| 任务 | 描述 | 实施成本 |
|---|---|---|
| 模块 D · 质量监控 | 错误率趋势、错误样本、反馈比例、差评样本 | 🟢 1 天 |
| 跨用户 thread 列表 | 端点 `/api/admin/threads`；前端 `/admin/threads` 页面 | 🟢 1 天 |
| Follow-up 链时间线 | 利用 `RunRow.follow_up_to_run_id`（已有）建会话链路视图 | 🟢 0.5 天 |
| 反馈 join run 详情 | drawer 展示当前 run 的反馈聚合 | 🟢 0.5 天 |

**v2 验收标准**：
- admin 能完成"看差评 → 点进去看完整问答 → 找到出错的 run → 看具体错误"完整链路。
- 错误样本支持按 model / assistant 过滤。
- 反馈比例趋势展示 7 日 / 30 日两种窗口。

### 🔵 Phase 3（v3）— 1-2 周 · "实时 + 治理"

**目标**：让 admin 能"看实时、做治理"。

| 任务 | 描述 | 实施成本 |
|---|---|---|
| 模块 E · 实时活动流 | 跨用户 inflight 监控 + SSE 旁路监听 | 🟡 1-2 天 |
| 模块 F · 数据治理（基础） | 跨维度聚合导出 + 脱敏导出开关 | 🟡 2 天 |
| 审计日志 & retention 策略 | **需 schema 改动**（`audit_log` 表、`retention` config） | 🔴 二期讨论 |

**v3 验收标准**：
- admin 能看到当前所有 inflight run 并旁路监听。
- 支持按 user / day / model 三种粒度导出 CSV / JSONL。
- 脱敏开关可全局启用 / 关闭。

---

## 4. 关键决策点

| # | 决策点 | 备选项 | 推荐 | 理由 |
|---|---|---|---|---|
| 1 | **v1 上线时间** | 1.5 周 / 2 周 / 1 周（裁剪） | **1.5 周** | v1 三个模块均有现成数据，端到端可在 1.5 周内交付 |
| 2 | **是否做实时活动（v3）** | 做 / 不做 / 推迟 | **推迟到 v3** | design §11 已明确不做，v1 / v2 阶段价值密度更高 |
| 3 | **脱敏导出** | 必做 / 选做 / 不做 | **v3 选做** | PII 风险存在但可控，v3 阶段加开关足够 |
| 4 | **审计日志 & retention** | 现在做 / 推迟 / 不做 | **推迟（需 schema 改动）** | 影响面广，单独 spec 评审后再做 |
| 5 | **是否复用 design 文档的 Q&A 页面** | 完全复用 / 扩展 / 重做 | **扩展** | 在 design 基础上加 KPI / 趋势图 / drawer 增强，避免推翻重来 |
| 6 | **admin 角色如何获取** | 现有 system_role / 单独 admin 角色 / OAuth group | **复用 system_role** | 已实现，最小改动 |

---

## 5. 关键不做（Out of Scope）

明确边界，避免范围蔓延：

- ❌ **多租户 SaaS 化运营**——DeerFlow 是 self-hosted 工具，本方案只考虑单部署单 admin 视角
- ❌ **实时推送 / WebSocket**——v3 才考虑；v1 / v2 全部为拉模式
- ❌ **完整对话回放**——drawer 只展示首轮问题 + 最终回答 + Follow-up 链
- ❌ **聚合 dashboard 自动化**——v1 KPI 卡足够，不做 BI 类自动化报表
- ❌ **NPS / 用户调研**——产品功能，不在本期
- ❌ **Nginx 访问日志接入**——运维侧已有工具
- ❌ **自动告警**（email / Slack 通知）——需要外部依赖，本期不做
- ❌ **审计日志 & retention**——v3 之后单独 spec 评审
- ❌ **用户自助 admin 申请**——admin 角色由部署方手动授予

---

## 6. 风险 & 依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| `first_human_message` / `last_ai_message` 没填 | Q&A 检索失效 | design 已有 `Task 0 验证` 流程，必须先通过 |
| 数据量大时 list 慢 | 列表加载超时 | design §8 已规划分页 + index；`runs.user_id` 已有 index（`backend/packages/harness/deerflow/persistence/run/model.py`） |
| 多个 admin 端点需绕过 `owner_check` | 误暴露普通用户数据 | 集中加 `require_admin` 装饰器（基于 `system_role='admin'`），单点审计；新增端点全部归在 `/api/admin/*` 前缀下 |
| 脱敏策略未明 | 导出泄露 PII | v3 之前先内部 review 一份脱敏规范（至少覆盖 email、message、oauth_id） |
| 角色权限变更 | 撤销 admin 时已有 session 仍可访问 | 复用现有 `token_version` 机制（`UserRow.token_version`），权限变更时递增 version 即强制下线 |

---

## 7. 后续动作

1. **复用已有 spec**：`2026-06-17-deerflow-qa-tracking-feature-design.md`（设计已就绪，可直接进入实施）
2. **新增 3 份 design 文档**：
   - `docx/frontend/agent-qa/2026-06-18-deerflow-admin-users-design.md`（模块 A）
   - `docx/frontend/agent-qa/2026-06-18-deerflow-admin-quality-design.md`（模块 D）
   - `docx/frontend/agent-qa/2026-06-18-deerflow-admin-usage-design.md`（模块 C）
3. **升级 OpenSpec**：`proposal.md` / `design.md` / `tasks.md` 三件套
4. **进入 superpowers `writing-plans` 流程**产出实施计划
5. **v1 实施顺序**：admin landing 路由壳 → 模块 C（成本看板，最快出成果）→ 模块 A（用户列表）→ 模块 B（Q&A Analytics）

---

## 8. 附录：数据基础 & 端点复用清单

> 证明"无需新表"声明的依据。

| 已有数据 / 端点 | 文件位置 | 用途 |
|---|---|---|
| `UserRow` + `SQLiteUserRepository` | `backend/packages/harness/deerflow/persistence/user/model.py:22` + `backend/app/gateway/auth/repositories/sqlite.py` | 模块 A 用户列表 / 画像 / 角色管理 |
| `ThreadMetaRow` + `ThreadMetaStore.search` | `backend/packages/harness/deerflow/persistence/thread_meta/base.py:45` | 模块 A 用户最近 thread + 跨用户 thread 列表 |
| `RunRow` 全字段 | `backend/packages/harness/deerflow/persistence/run/sql.py` | 所有模块核心数据源 |
| `ThreadTokenUsageResponse` + 端点 | `backend/app/gateway/routers/thread_runs.py:91, 427` | 模块 C token 看板（按 thread 聚合） |
| `FeedbackRow` + `FeedbackRepository.aggregate_by_run` | `backend/packages/harness/deerflow/persistence/feedback/sql.py:205` | 模块 D 反馈比例 + 差评样本 |
| `RunStore.list_inflight` | `backend/packages/harness/deerflow/runtime/runs/store/base.py:130` | 模块 E 实时活动流 |
| `RunRow.follow_up_to_run_id` | `backend/packages/harness/deerflow/persistence/run/sql.py:96` | 模块 B Follow-up 链时间线 |
| `MemoryMiddleware`（已记录 user_id） | `backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py:28` | 模块 A 用户长期 memory 浏览 |
| `require_permission` + `system_role='admin'` | `backend/app/gateway/authz.py` | 所有 admin 端点的权限校验 |
| `token_version`（权限撤销强制下线） | `UserRow.token_version` | admin 角色变更时安全下线 |
| 已有 Q&A Analytics design 文档 | `docx/frontend/agent-qa/2026-06-17-deerflow-qa-tracking-feature-design.md` | 模块 B 直接复用 |

---

## 9. 附录：与已有 spec 文档的关系

| 已有文档 | 关系 |
|---|---|
| `2026-06-17-deerflow-qa-tracking-design.md` | 总 spec；本文档为"admin 视角扩展"，与该文档**不冲突** |
| `2026-06-17-deerflow-qa-tracking-design-questions.md` | 设计问题清单；本文档的 v1 / v2 / v3 切法可回答其中"是否做实时 / 是否做跨用户"等悬而未决问题 |
| `2026-06-17-deerflow-qa-tracking-feature-design.md` | **完全对应模块 B**，本文档将该文档纳入 v1 锚点 |
| `2026-06-17-deerflow-qa-tracking-implementation-architecture.md` | 技术架构文档；本文档不涉及实现细节，复用即可 |

---

**End of Document**

> 任何决策调整 / 范围变更，请直接在本文件标注或在本目录新增 `2026-06-18-deerflow-admin-operations-design-rev[N].md`。

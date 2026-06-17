# DeerFlow Q&A 内容跟踪 — 设计问题

- **Date**: 2026-06-17
- **对应 spec**: `2026-06-17-deerflow-qa-tracking-design.md`（已 commit `3ed5a0c4`）
- **本文档作用**：记录"为什么这么做"——待回答的问题、做出的决策、考虑过的备选、最终选择的权衡
- **读者**：审阅者、后续接手者、对设计动机好奇的人

---

## 1. 背景：为什么要做这件事

DeerFlow 已经把大量运行时数据持久化下来了：

- `RunRow`：每个 run 的 `user_id`、`thread_id`、`first_human_message`、`last_ai_message`、`tokens`、状态、错误、时间
- `ThreadMetaRow`：每个 thread 的 user、assistant、状态、时间
- `FeedbackRepository`：用户的 thumbs (+1/-1) 评分
- `TokenUsageMiddleware`：每次 LLM 调用的 token 记账
- LangSmith / Langfuse：分布式 trace

**问题**：这些数据"躺在数据库里"，但**没有上层分析视图**。管理员看不到"昨天谁问了什么、AI 怎么回的、是否出错、用户满不满意"。无法回答：

- 昨天有多少用户来用过？
- 大家最常问什么类型的问题？
- 哪些 run 出错了？错误集中在哪里？
- 用户的 thumbs 评分和实际答案质量是否对得上？
- 我想导出一份 CSV 给同事做离线分析，能吗？

**更大的背景**：用户提了一个更广的需求——跟踪、统计、检测、会话数、活跃用户、用户满意度。这是个跨多个子系统的产品蓝图。**本 spec 只解决其中"Q&A 内容跟踪"这一块**，作为后续每个子项目（活跃用户聚合 / 质量检测 / Nginx 日志 / 多维满意度）的事实基础。

---

## 2. 必须回答的设计问题

下面是 4 个真正决定形状的问题，每个都有 2-4 个候选，最终选择附理由。

### Q1：捕获范围 — 抓多少对话内容？

**候选**：

| 选项 | 内容 | 优点 | 缺点 |
|------|------|------|------|
| A. 最小（仅首轮 HumanMessage + 最终 AI） | 每个 run 一对文本 | 存储小、无 PII 风险、为后续指标提供事实 | 不能回放完整多轮对话 |
| B. 多轮（每 turn 的 HumanMessage + AI 最终回复） | 一个 thread 多对文本 | 能重建完整对话 | 存储变大、需要 dedupe |
| C. 全量（HumanMessage + AIMessage + ToolMessage） | 含 tool calls、reasoning | 完整回放 | PII 风险、token 成本、存储膨胀 |

**最终选择**：**A. 最小**

**理由**：

1. **YAGNI**：本 spec 的目标是"为后续指标提供事实视图"，不是"对话回放"。后续如果需要回放，可以独立加 spec（F1：扩到 RunEventStore 全量采集）。
2. **与现有 schema 对齐**：`RunRow` 已经有 `first_human_message` 和 `last_ai_message` 两个 Text 列，注释明确说"Convenience fields (for listing pages without querying RunEventStore)"。直接用这两个字段即可。
3. **降低风险**：最小捕获意味着没有中间推理、tool call 的 PII / 商业机密暴露风险。
4. **存储可控**：每个 run 一对文本，存储增长是 O(runs)，不会失控。

**权衡**：失去了"看完整多轮对话"的能力。如果后续强烈需要，可以加一个 F1 子 spec。

### Q2：存储路径 — 用哪里做事实层？

**候选**：

| 选项 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| A. 直接复用 RunRow | 不动 schema，写查询 | 零迁移、零新表、立等可用 | 查询性能受 RunRow 表大小影响 |
| B. 新建 analytics 表 | 后台从 RunRow 同步到独立表 | 查询快、可针对性索引 | 同步机制复杂、数据滞后、双写风险 |
| C. 事件流 + 物化视图 | append-only event log + 周期汇总 | 灵活、未来易扩展 | 工作量大、当前 spec 过度设计 |

**最终选择**：**A. 直接复用 RunRow**

**理由**：

1. **零迁移**：避免数据库迁移、schema 版本升级、CI 流程调整等连锁影响。
2. **数据即真相**：`RunRow` 已经是事实的权威来源，没有同步延迟问题。
3. **性能足够**：DeerFlow 是 trusted local 部署，典型规模 < 10k runs。SQLite + 索引完全够用。
4. **未来可演进**：如果将来性能真出问题，可以平滑迁移到方案 B（独立 analytics 表），但不需要现在做。

**权衡**：与 RunRow 共用存储，未来 RunRow 的写入路径变更（如 schema 升级）会影响 analytics。如果发生，需要同步更新查询逻辑。

### Q3：读者画像 — 谁能看到？

**候选**：

| 选项 | 读者 | 优点 | 缺点 |
|------|------|------|------|
| A. 管理员看全量 + 普通用户看自己 | 都有入口 | 体验最完整 | 工作量大、权限模型复杂 |
| B. 管理员看全量 | admin-only | 实现简单、合规风险低 | 普通用户无入口 |
| C. 管理员 + 全量导出 | admin-only + CSV/JSONL | 兼顾运维和离线分析 | 实现复杂度中等 |

**最终选择**：**C. 管理员 + 全量导出**

**理由**：

1. **DeerFlow 的安全定位**：CLAUDE.md 明确说"DeerFlow is designed for **local trusted environments** (127.0.0.1 loopback)"。这是一个自托管工具，不是 SaaS。
2. **隐私优先**：admin-only 比"用户看自己"更保守，避免误暴露其他用户的对话。
3. **导出价值高**：本地部署场景下，运维/产品需要把数据拿到 Excel / BI 工具里进一步分析。
4. **架构简单**：权限模型只需一个 `analytics:read` permission，默认给 admin。

**权衡**：用户看不到自己的对话历史汇总（其实单 thread 的对话已经能在原 workspace 里看到，缺的只是"跨 thread 列表"，这个粒度 admin 已经能覆盖大多数内部使用场景）。

### Q4：列表粒度 — 一个 thread 还是一个 run？

**候选**：

| 选项 | 粒度 | 优点 | 缺点 |
|------|------|------|------|
| A. 一个 thread 一行 | thread 级 | 符合"一个主题"的自然使用 | 看不出"同一个 thread 下哪些追问" |
| B. 一个 run 一行 | run 级 | 粒度细、容易接 quality metrics | 不直观 |
| C. 两种都提供 | 默认 thread + 下钻 | 体验最全 | 实现复杂 |

**最终选择**：**B. 一个 run 一行**

**理由**：

1. **与现有 schema 对齐**：`RunRow` 是一行一 run，查询就是 RunRow 查询，零投影成本。
2. **后续可扩展**：每个 run 自带 status / tokens / error，方便后续 quality metrics（子项目 4）直接接入。
3. **数据更准确**：一个 run = 一次 agent 执行 = 一次可观察的"事件"，比 thread 更适合做事件级聚合。
4. **导出简单**：CSV/JSONL 一行 = 一 run，离线分析最直接。

**权衡**：UI 上需要"thread_id"列让用户能把同一会话的多 run 关联起来。这是有意为之的代价。

---

## 3. 跨决策的一致性

四个决策互相约束，形成了一个内部一致的形状：

```
Q1=最小 ─┐
         ├─→ 零数据采集成本 ─→ Q2=RunRow 复用 ─→ 零迁移 ─→ 零 schema 风险
Q3=admin─┤
         └─→ 入口窄 ─────────→ Q4=run 粒度 ─→ 与 RunRow 一一对应
```

任何一项换了都会引发其他项调整：
- 如果 Q1 选 C（全量），Q2 必须改成 B 或 C（新表），否则 RunRow 装不下。
- 如果 Q3 选 A（用户看自己），Q4 选 B（run 粒度）会让用户体验割裂。
- 如果 Q4 选 C（两种粒度），Q1 至少要选 B 才能支持 thread 维度的 preview。

**结论**：四个决策形成了一个最小可用、最易扩展、最易实现的方案。

---

## 4. 显式未回答的问题

下面这些是本 spec 故意**不回答**的，留给后续 spec：

| # | 问题 | 留给谁 |
|---|------|--------|
| U1 | 全量消息采集（含 tool call / reasoning） | 子项目 F1 |
| U2 | Nginx 访问日志接入 | 子项目 2 |
| U3 | DAU/WAU/MAU、并发会话、留存 | 子项目 3 |
| U4 | 质量检测（loop、timeout、clarification 比例） | 子项目 4 |
| U5 | NPS、多维度满意度评分 | 后续 spec |
| U6 | 实时 dashboard 推送 | 后续 spec |
| U7 | 数据 retention / TTL | 后续 spec |
| U8 | 普通用户可见面板 | 后续 spec（如有需求） |

---

## 5. 关键风险问题（决定能不能动工）

下面是实施前必须验证或确认的几个事实问题：

| # | 风险问题 | 验证方式 | 失败时的行动 |
|---|---------|---------|------------|
| R1 | `first_human_message` / `last_ai_message` 在每次 run 完成时是否真的被填充？ | Task 0 前置测试 | 修复 `RunStore` / `RunJournal` 写入路径 |
| R2 | `authz.py` / `providers.py` 是否支持新 permission 注册？ | 代码调研 | 扩展 `Permission` 枚举和默认 grant |
| R3 | 前端 admin 路由是否能复用现有权限守卫模式？ | 代码调研 | 如不能，新增 `requireAdmin` HOC |
| R4 | 大结果集导出是否会 OOM？ | 设计 `StreamingResponse` + 异步游标 | 限制每次 fetch 1000 行 |

R1 是阻塞性的：如果 `first/last` 字段没填对，整个 spec 没意义。所以 Task 0（前置验证测试）是整个实施的第一步。

---

## 6. 决策的"出口条件"

任何一个决策在以下情况出现时需要重新评估：

- **Q1（最小）**：用户/产品明确要"完整对话回放"，或质量检测需要中间消息。
- **Q2（RunRow 复用）**：RunRow 大小超过 100k 行，查询性能下降到 > 1s。
- **Q3（admin-only）**：出现"用户自查自己的所有历史对话"的需求。
- **Q4（run 粒度）**：用户/产品主要想看"会话主题汇总"而非"事件列表"。

---

## 7. 一句话总结

**为什么这么做**：因为 DeerFlow 缺一个上层的"分析视角"，而 80% 的数据已经在 `RunRow` 里了——用最小代价（零迁移）把 admin 视角搭出来，为后续每个指标（活跃用户、质量、NPS、Nginx 日志）打地基。

**为什么不做得更多**：YAGNI。先证明"admin 能 list/export Q&A"有价值，再决定后续每个子项目的优先级。

**什么时候停止不进一步**：当出现上面"出口条件"任意一条时，重新走 brainstorming → spec → plan → implement 循环，而不是在当前 spec 里塞更多东西。
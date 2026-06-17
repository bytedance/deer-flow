# DeerFlow Q&A 内容跟踪 — Design Spec

- **Date**: 2026-06-17
- **Status**: Approved (brainstorming → writing-plans next)
- **Sub-project**: 1 of N in the broader "DeerFlow 行为/质量分析平台"
- **Owners**: TBD
- **Skill source**: `brainstorming` → `writing-plans` (next)

---

## 1. Context

DeerFlow 现有的运行时已经捕获了绝大部分运行数据 — `RunRow` 持久化了 `user_id`、`thread_id`、`first_human_message`、`last_ai_message`、`tokens`、`status`、`error`、`created_at` 等关键字段，`FeedbackRepository` 收集用户 thumbs 评分，`TokenUsageMiddleware` 记录每次 LLM 调用的 token 用量，LangSmith/Langfuse 已接通做分布式追踪。

**缺失的是上层"分析视角"**：管理员无法方便地 list / search / export 历史 Q&A 对话，没有统一的事实视图可用于后续的活跃用户统计、质量检测、满意度分析。

本 spec 是整个分析平台的**第一个子项目**：搭好"Q&A 内容跟踪"这一层，让后续每个指标（活跃用户、对话量、质量、Nginx 日志、多维满意度）都可以基于同一个事实视图扩展。

## 2. Goals

1. 管理员可在 `/admin/analytics` 页面浏览所有历史 run 的"用户提问 + AI 回答"。
2. 支持按日期范围、用户、assistant、model、status、关键词筛选。
3. 支持 CSV / JSONL 流式导出，便于离线分析。
4. **零迁移、零新表**：完全复用现有 `RunRow`。
5. **最小捕获范围**：每个 run 只持久化"首轮 HumanMessage + 最终 AI 文本"，不抓中间消息、tool call、reasoning。

## 3. Non-Goals (Out of Scope)

为防止 scope creep，下列内容显式不在本 spec 范围内，将由后续独立 spec 处理：

- 抓取中间消息、tool calls、reasoning（→ 后续可能扩展到 `RunEventStore` 全量采集）
- 新增 analytics 持久化表或迁移
- Nginx 访问日志接入（→ 子项目 2）
- DAU/WAU/MAU、并发会话、留存 等聚合指标（→ 子项目 3）
- Loop detection、超时率、clarification 比例等质量检测（→ 子项目 4）
- NPS、多维度满意度评分（→ 后续 spec）
- 实时推送（websocket）
- 数据 retention / TTL 策略（与现有 `RunStore` 保持一致）
- 普通用户可见的自服务 analytics（admin-only）

## 4. Brainstorming Decisions

通过 4 轮澄清问题确定的设计选择：

| # | 决策 | 选择 | 备选 |
|---|------|------|------|
| 1 | 捕获范围 | 仅首轮 HumanMessage + 最终 AI 文本 | 含中间消息 / 全量消息 |
| 2 | 存储路径 | 直接复用 `RunRow` | 新建 analytics 表 / 事件流 + 物化视图 |
| 3 | 读者画像 | 管理员 + 全量导出 | 管理员看全量 / 所有用户看自己 |
| 4 | 列表粒度 | 一个 run 一行 | 一个 thread 一行 / 两种都提供 |

## 5. Architecture

```
┌─────────────────────────┐
│  Admin 浏览器            │
│  /admin/analytics       │
└────────────┬────────────┘
             │ HTTP (cookie auth + CSRF)
             ▼
┌──────────────────────────────────────┐
│ Gateway (FastAPI)                     │
│  app/gateway/routers/admin_analytics  │
│   ├─ GET  /runs        (list+paging) │
│   ├─ GET  /runs/{rid}  (detail)      │
│   └─ GET  /export      (csv/jsonl)   │
└────────────┬─────────────────────────┘
             │ require_permission("analytics","read")
             ▼
┌──────────────────────────────────────┐
│ AnalyticsService (app/gateway/services│
│ /analytics.py)                        │
│  - filter / sort / paginate           │
│  - project RunRow → AnalyticsRunView  │
│  - LIKE-based full-text search        │
│  - StreamingResponse for export       │
└────────────┬─────────────────────────┘
             │ SQLAlchemy AsyncSession
             ▼
┌──────────────────────────────────────┐
│ RunRow (existing, no schema change)  │
└──────────────────────────────────────┘
```

**关键架构约束**：

- **零迁移**：不增加 column、不增加 table、不改 schema 版本
- **不写新事件源**：所有事实来自 `RunJournal` → `RunStore` 已有的写入路径
- **鉴权对称**：复用 `feedback.py` 的 `require_permission` 模式
- **app/harness 边界**：service 放在 `app/gateway/services/`（consumer-only），不放在 harness 层
- **Streaming**：export 用 FastAPI `StreamingResponse` + SQLAlchemy 异步游标，避免大结果集 OOM

## 6. Data Model (No Schema Change)

```
RunRow (已存在)
├─ 业务键: run_id, thread_id, user_id
├─ 内容: first_human_message, last_ai_message (TEXT)
├─ 上下文: assistant_id, model_name
├─ 结果: status, error
├─ 资源: total_input_tokens, total_output_tokens, total_tokens, llm_call_count
├─ 时间: created_at, updated_at
└─ 杂项: message_count, follow_up_to_run_id
```

**前置工作（Task 0）**：必须先验证 `first_human_message` 和 `last_ai_message` 在每次 run 完成时是否真的被填充。如果没填或填错，第一步修 `RunStore` / `RunJournal` 写入路径，否则整个 spec 无意义。

## 7. API Specification

**Base path**: `/api/admin/analytics`

### 7.1 `GET /runs` — 列表

**Query 参数**：

| 名称 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `date_from` | ISO 8601 string | 否 | - | 包含，匹配 `created_at >= date_from` |
| `date_to` | ISO 8601 string | 否 | - | 包含，匹配 `created_at <= date_to` |
| `user_id` | string，可重复 | 否 | - | 多次出现为 OR 关系 |
| `assistant_id` | string | 否 | - | 精确匹配 |
| `model_name` | string | 否 | - | 精确匹配 |
| `status` | enum | 否 | - | `pending\|running\|success\|error\|timeout\|interrupted` |
| `q` | string | 否 | - | 对 `first_human_message OR last_ai_message` 做 `LIKE '%q%'` |
| `page` | int | 否 | 1 | 1-indexed |
| `page_size` | int | 否 | 50 | clamp 到 [1, 200] |
| `sort` | enum | 否 | `-created_at` | `created_at\|-created_at\|total_tokens\|-total_tokens` |

**响应 200**：
```json
{
  "data": [
    {
      "run_id": "...",
      "thread_id": "...",
      "user_id": "...",
      "assistant_id": "lead-agent",
      "model_name": "gpt-4o",
      "status": "success",
      "message_count": 2,
      "first_human_message_preview": "How do I... (truncated to 200 chars)",
      "last_ai_message_preview": "You can... (truncated to 200 chars)",
      "total_input_tokens": 1234,
      "total_output_tokens": 567,
      "total_tokens": 1801,
      "llm_call_count": 3,
      "created_at": "2026-06-17T10:23:45Z",
      "updated_at": "2026-06-17T10:24:01Z"
    }
  ],
  "page": 1,
  "page_size": 50,
  "total": 1234
}
```

### 7.2 `GET /runs/{run_id}` — 详情

**响应 200**：
```json
{
  "run_id": "...",
  "thread_id": "...",
  "user_id": "...",
  "assistant_id": "lead-agent",
  "model_name": "gpt-4o",
  "status": "success",
  "message_count": 2,
  "first_human_message": "...完整文本...",
  "last_ai_message": "...完整文本...",
  "total_input_tokens": 1234,
  "total_output_tokens": 567,
  "total_tokens": 1801,
  "lead_agent_tokens": 1500,
  "subagent_tokens": 200,
  "middleware_tokens": 100,
  "llm_call_count": 3,
  "follow_up_to_run_id": null,
  "error": null,
  "created_at": "2026-06-17T10:23:45Z",
  "updated_at": "2026-06-17T10:24:01Z"
}
```

**404**：`{"detail": "Run {run_id} not found"}`

### 7.3 `GET /export` — 导出

**Query 参数**：与 `/runs` 相同的 filters（除 `page` / `page_size`）。

**额外必填参数**：

| 名称 | 类型 | 说明 |
|------|------|------|
| `format` | enum | `csv` 或 `jsonl` |

**响应**：
- `format=csv` → `Content-Type: text/csv`，`Content-Disposition: attachment; filename="deerflow-runs-<timestamp>.csv"`
- `format=jsonl` → `Content-Type: application/x-ndjson`，`Content-Disposition: attachment; filename="deerflow-runs-<timestamp>.jsonl"`
- Body 用 `StreamingResponse` 增量输出，避免大结果集 OOM

**CSV 列**：`run_id, thread_id, user_id, assistant_id, model_name, status, message_count, total_input_tokens, total_output_tokens, total_tokens, llm_call_count, created_at, updated_at, first_human_message, last_ai_message, error`（长消息字段做 CSV escape）

**JSONL 行**：每行一个 JSON 对象，schema 同 `/runs/{run_id}` 响应

### 7.4 Permission

- 新增 permission: `analytics:read`
- 默认只授给 `admin` 角色，不授给 `user`
- `auth_disabled` 模式：放行（与 `feedback.py` 等现有 admin endpoint 行为一致）
- 在 `app/gateway/authz.py` 注册 permission；在 `app/auth/providers.py` 默认 grant 中加入 admin 角色

## 8. UI Specification

### 8.1 入口

- 路径：`/admin/analytics`
- 权限：仅 `is_admin === true` 时菜单项可见
- 路由：`frontend/src/app/admin/analytics/page.tsx`

### 8.2 布局

```
┌────────────────────────────────────────────────────────────┐
│ Q&A Analytics                  [Export CSV] [Export JSONL] │
├────────────────────────────────────────────────────────────┤
│ Filters                                                    │
│ ┌──────────┐ ┌──────┐ ┌──────────┐ ┌──────┐ ┌──────┐       │
│ │Date range│ │ User │ │Assistant │ │Model │ │Status│       │
│ └──────────┘ └──────┘ └──────────┘ └──────┘ └──────┘       │
│ Search: [_________________________________________]        │
│                                              [Apply][Reset]│
├────────────────────────────────────────────────────────────┤
│ Showing 1-50 of 1,234 runs            [< Prev] [Next >]    │
├────────────────────────────────────────────────────────────┤
│ Time       | User  | Asst   | Model | Tokens | Status |   │
│ ...        | ...   | ...    | ...   | ...    | ...    |►  │
│ 2026-06-17 | alice | lead-ag| gpt-4 | 12.3k  | success|   │
│ "How do I..."  (preview)                                    │
├────────────────────────────────────────────────────────────┤
│ (Pagination)                                               │
└────────────────────────────────────────────────────────────┘
```

- 行点击 → 右侧 drawer 显示完整 `first_human_message` / `last_ai_message` + token 分布 + error
- Export 按钮按当前 filter 触发下载
- 默认排序 `-created_at`

### 8.3 组件清单

```
frontend/src/
├── app/admin/analytics/page.tsx                       ← 入口
├── components/admin/analytics/
│   ├── analytics-table.tsx
│   ├── analytics-filters.tsx
│   └── analytics-detail-drawer.tsx
├── core/api/analytics.ts                              ← API client
└── core/admin/analytics-hooks.ts                      ← React hooks
```

## 9. Error Handling

| 场景 | 状态码 | Response detail | 备注 |
|------|--------|-----------------|------|
| 非 admin 访问 | 403 | `Permission denied: analytics:read` | `auth_disabled` 模式不放行校验 |
| `date_from` / `date_to` 格式错 | 400 | `must be ISO 8601` | |
| `status` 不在 enum | 400 | `status must be one of [...]` | |
| `page_size > 200` | 200 + warning header | - | clamp 到 200，header `X-DeerFlow-Page-Size-Clamped: 200` |
| `page < 1` | 400 | `page must be >= 1` | |
| `sort` 不在 enum | 400 | `sort must be one of [...]` | |
| run_id 不存在 | 404 | `Run {run_id} not found` | |
| DB 错 | 500 | `Internal server error` | 完整 trace 进 logs，不泄露 SQL |
| Export 中途 DB 错 | 流已发出 | - | 客户端收到不完整文件；服务端 log ERROR；下次重试 |

## 10. Testing Strategy

### 10.1 前置验证测试（Task 0，先跑）

`tests/test_run_first_last_message_populated.py`：

- 启动真实 lead agent run，输入固定 prompt
- 断言 run 完成后 `first_human_message` 不为 None 且等于输入
- 断言 `last_ai_message` 不为 None 且非空
- **如果失败 → 进入修复模式：定位 `RunStore` / `RunJournal` 的写入路径，修到测试通过为止**

### 10.2 单元测试 `tests/test_admin_analytics.py`

**List (`GET /runs`)**：
- 无 filter → 全量
- 单 filter：date_from、date_to、user_id、assistant_id、model_name、status、q 各一个
- 组合 filter：多 filter 交集
- 翻页：page 1、2、3 数据不重叠、total 一致
- 排序：默认（`-created_at`）、`-total_tokens`
- 边界：空结果、page_size=200、page_size>200 clamp

**Detail (`GET /runs/{run_id}`)**：
- 存在 → 200 + 完整 schema
- 不存在 → 404

**Export (`GET /export`)**：
- `format=csv` → Content-Type 正确，CSV 头正确，行数 = filter 命中数
- `format=jsonl` → Content-Type 正确，每行一个 JSON，行数一致
- 空结果 → 200 + 仅 header
- 大结果（>1000 行）→ 不 OOM（断言 process RSS 在合理范围）

**Permission**：
- admin 访问 → 200
- 普通 user 访问 → 403
- `auth_disabled` 模式 → 无 auth 也能 200

### 10.3 Frontend 测试

- `analytics-table.test.tsx`：渲染 mock 数据、空状态、分页交互
- `analytics-filters.test.tsx`：filter 状态变化触发 hook 重 fetch
- `analytics-detail-drawer.test.tsx`：完整消息渲染
- `analytics-hooks.test.tsx`：mock API，验证参数传递、loading/error 状态
- E2E（Playwright）：admin login → `/admin/analytics` → 看列表 → 点 row → 看详情 → Export CSV → 验证文件内容

### 10.4 覆盖率目标

- Backend: 新增代码 > 80%
- Frontend: 新增组件 > 70%

## 11. Risks & Pre-work

| # | 风险 | 缓解 |
|---|------|------|
| R1 | `first_human_message` / `last_ai_message` 当前可能没被填充 | Task 0 前置测试；如失败则修复 `RunStore` 写入路径 |
| R2 | `authz.py` / `providers.py` 可能不支持新 permission 注册 | 先调研；必要时扩展 `Permission` 枚举和默认 grant |
| R3 | 大结果集导出 OOM | 用 `StreamingResponse` + 异步 SQL 游标，限制每次 fetch 1000 行 |
| R4 | CSV / JSONL 中含换行/引号/逗号转义问题 | 使用 Python `csv` 模块；JSONL 用 `json.dumps(ensure_ascii=False)` |
| R5 | `auth_disabled` 模式下 analytics 暴露给所有人 | 与现有 admin endpoint 一致；用户已选择此模式即信任本机 |
| R6 | 前端 admin 路由绕过 | 在 page 入口用 `useCurrentUser()` 守卫，非 admin 直接 redirect |

## 12. Future Work (Out of Scope Here)

明确不在本 spec，但记录以备后续 spec 引用：

- **F1**：扩到 `RunEventStore` 全量消息采集（中间消息、tool calls、reasoning）
- **F2**：Nginx 访问日志接入（子项目 2）—— `/logs/nginx` 文件 → pipeline → analytics 库
- **F3**：DAU/WAU/MAU、并发会话、留存聚合（子项目 3）
- **F4**：质量检测（loop、timeout、clarification 比例、anomaly）（子项目 4）
- **F5**：NPS、多维度满意度评分
- **F6**：实时 dashboard（websocket 推送）
- **F7**：基于 SQLite FTS5 升级 `LIKE` 全文检索（当 run 数 > 10k 时）
- **F8**：数据 retention / TTL 策略

## 13. Acceptance Criteria

本 spec 在以下条件同时满足时视为完成：

1. ✅ `tests/test_run_first_last_message_populated.py` 通过
2. ✅ `tests/test_admin_analytics.py` 全部用例通过，覆盖率 > 80%
3. ✅ `/admin/analytics` 页面可访问、可筛选、可分页、可查看详情、可导出 CSV / JSONL
4. ✅ 非 admin 访问被 403 拒绝（`auth_disabled` 模式除外）
5. ✅ 后端 `make lint` / `make test` 全部通过
6. ✅ 前端 `pnpm lint` / `pnpm typecheck` / `pnpm build` 全部通过
7. ✅ E2E：Playwright `admin can browse and export Q&A analytics` 通过
8. ✅ 本 spec 范围内的 4 个决策在代码中有对应实现（最小捕获 / RunRow 复用 / admin-only / run 粒度）
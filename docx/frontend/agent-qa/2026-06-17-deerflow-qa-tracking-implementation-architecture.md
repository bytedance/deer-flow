# DeerFlow Q&A 内容跟踪 — 实现架构设计

- **Date**: 2026-06-17
- **对应 spec**: `2026-06-17-deerflow-qa-tracking-design.md`
- **对应设计问题**: `2026-06-17-deerflow-qa-tracking-design-questions.md`
- **对应功能设计**: `2026-06-17-deerflow-qa-tracking-feature-design.md`
- **本文档作用**：定义"怎么实现"——技术架构、组件、数据流、API 详细 schema、存储、测试、风险
- **读者**：实施者（写 plan 和写代码的人）

---

## 1. 架构总览

```
┌─────────────────────────┐
│  Admin 浏览器            │
│  /admin/analytics       │
│  (Next.js App Router)   │
└────────────┬────────────┘
             │ HTTP (cookie auth + CSRF)
             │ GET /api/admin/analytics/{runs, runs/{rid}, export}
             ▼
┌──────────────────────────────────────────────────────────┐
│ Gateway (FastAPI)                                         │
│ ┌────────────────────────────────────────────────────┐  │
│ │ app/gateway/routers/admin_analytics.py             │  │
│ │  - thin handlers                                   │  │
│ │  - 解析 query params → AnalyticsFilters            │  │
│ │  - 调 require_permission("analytics","read")       │  │
│ │  - 调 AnalyticsService                             │  │
│ │  - StreamingResponse for export                    │  │
│ └──────────────────────┬─────────────────────────────┘  │
│                        │                                  │
│ ┌──────────────────────▼─────────────────────────────┐  │
│ │ app/gateway/services/analytics.py                  │  │
│ │  - AnalyticsService.list_runs(filters, paging)     │  │
│ │  - AnalyticsService.get_run_detail(run_id)         │  │
│ │  - AnalyticsService.stream_export(filters, fmt)    │  │
│ │  - AnalyticsRunView / RunDetail dataclass          │  │
│ │  - _to_run_view() projection                       │  │
│ │  - _csv_escape() / _jsonl_line()                   │  │
│ └──────────────────────┬─────────────────────────────┘  │
│                        │                                  │
│ ┌──────────────────────▼─────────────────────────────┐  │
│ │ app/gateway/deps.py                                 │  │
│ │  - get_analytics_service(request) → AnalyticsService│  │
│ │  - get_run_store(request) → RunStore (existing)     │  │
│ │  - get_current_user(request) → user_id              │  │
│ └──────────────────────┬─────────────────────────────┘  │
│                        │                                  │
│         SQLAlchemy AsyncSession                          │
└────────────────────────┼─────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│ RunRow (existing, NO schema change)                       │
│  - run_id, thread_id, user_id                              │
│  - first_human_message, last_ai_message                   │
│  - assistant_id, model_name                               │
│  - status, error                                          │
│  - total_input_tokens, total_output_tokens, total_tokens │
│  - llm_call_count, message_count                         │
│  - created_at, updated_at                                │
│  - follow_up_to_run_id                                   │
└──────────────────────────────────────────────────────────┘
```

---

## 2. 组件清单

### 2.1 后端文件

```
backend/
├── app/gateway/routers/
│   └── admin_analytics.py                 # 新增：3 endpoints
├── app/gateway/services/
│   └── analytics.py                       # 新增：AnalyticsService + dataclass
├── app/gateway/deps.py                    # 改动：+ get_analytics_service
├── app/gateway/app.py                     # 改动：+ include_router
├── app/gateway/authz.py                   # 改动：+ register "analytics:read" permission
└── tests/
    ├── test_run_first_last_message_populated.py  # 新增：Task 0 前置验证
    └── test_admin_analytics.py                  # 新增：完整测试套件
```

### 2.2 前端文件

```
frontend/src/
├── app/admin/analytics/
│   └── page.tsx                           # 新增：页面入口
├── components/admin/analytics/
│   ├── analytics-table.tsx                # 新增：表格
│   ├── analytics-filters.tsx              # 新增：过滤器
│   ├── analytics-detail-drawer.tsx        # 新增：详情 drawer
│   ├── analytics-export-buttons.tsx       # 新增：导出按钮组
│   └── index.ts                           # 新增：barrel export
├── core/api/
│   └── analytics.ts                       # 新增：API client
└── core/admin/
    └── analytics-hooks.ts                 # 新增：React hooks (useAnalyticsRuns 等)
```

---

## 3. 数据流（一次 list 请求的完整路径）

```
[用户操作] admin 在 /admin/analytics 设置 filter 并点 Apply
    ↓
[前端 hook] useAnalyticsRuns(filters) → SWR/React Query 触发 fetch
    ↓
[HTTP] GET /api/admin/analytics/runs?date_from=...&user_id=...&q=...
    ↓
[FastAPI middleware chain]
    - SessionMiddleware: 解析 cookie
    - AuthMiddleware: 解析当前用户
    - CSRFMiddleware: 校验 CSRF token (虽然 GET 不需要)
    ↓
[Router handler] list_runs(filters, page, page_size, sort)
    - require_permission("analytics","read") → 403 if not admin
    - 把 query string 解析成 AnalyticsFilters dataclass
    - service = get_analytics_service(request)
    - result = await service.list_runs(filters, page, page_size, sort)
    - return AnalyticsListResponse(data=[...], page, page_size, total)
    ↓
[Service] AnalyticsService.list_runs
    - 构造 select(RunRow).where(filter_clauses)
    - 排序、子句组装
    - COUNT(*) OVER() for total (一次 query)
    - LIMIT page_size OFFSET (page-1)*page_size
    - Project RunRow → AnalyticsRunView（截断 preview 到 200 字符）
    - 返回 AnalyticsListResult
    ↓
[SQLAlchemy] 执行 SQL
    ↓
[SQLite] RunRow 表扫描/索引扫描
    ↓
[反向] 结果序列化 → JSON response
    ↓
[前端] SWR 缓存 → 触发 useAnalyticsRuns 重渲染 → Table 显示
```

---

## 4. 数据模型

### 4.1 数据库表（无变更）

```
RunRow (existing)
├─ run_id: String(64) PRIMARY KEY
├─ thread_id: String(64) NOT NULL, INDEXED
├─ user_id: String(64) NULLABLE, INDEXED
├─ assistant_id: String(128) NULLABLE
├─ model_name: String(128) NULLABLE
├─ status: String(20) DEFAULT 'pending'  (pending|running|success|error|timeout|interrupted)
├─ message_count: int DEFAULT 0
├─ first_human_message: Text NULLABLE
├─ last_ai_message: Text NULLABLE
├─ total_input_tokens: int DEFAULT 0
├─ total_output_tokens: int DEFAULT 0
├─ total_tokens: int DEFAULT 0
├─ llm_call_count: int DEFAULT 0
├─ lead_agent_tokens: int DEFAULT 0
├─ subagent_tokens: int DEFAULT 0
├─ middleware_tokens: int DEFAULT 0
├─ follow_up_to_run_id: String(64) NULLABLE
├─ error: Text NULLABLE
├─ metadata_json: JSON DEFAULT {}
├─ kwargs_json: JSON DEFAULT {}
├─ multitask_strategy: String(20) DEFAULT 'reject'
├─ created_at: DateTime(timezone=True)
└─ updated_at: DateTime(timezone=True)
```

### 4.2 服务层 dataclass（Python 3.12）

```python
# app/gateway/services/analytics.py

@dataclass(frozen=True)
class AnalyticsFilters:
    date_from: datetime | None = None
    date_to: datetime | None = None
    user_ids: tuple[str, ...] = ()
    assistant_id: str | None = None
    model_name: str | None = None
    status: str | None = None
    q: str | None = None

    def __post_init__(self):
        if self.status and self.status not in ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {ALLOWED_STATUSES}")


@dataclass(frozen=True)
class AnalyticsSort:
    field: str  # 'created_at' | 'total_tokens'
    descending: bool

    def __post_init__(self):
        if self.field not in ALLOWED_SORT_FIELDS:
            raise ValueError(f"sort field must be one of {ALLOWED_SORT_FIELDS}")


@dataclass
class AnalyticsRunView:
    run_id: str
    thread_id: str
    user_id: str | None
    assistant_id: str | None
    model_name: str | None
    status: str
    message_count: int
    first_human_message_preview: str  # 截断到 200 字符
    last_ai_message_preview: str      # 截断到 200 字符
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    llm_call_count: int
    created_at: datetime
    updated_at: datetime


@dataclass
class RunDetail:
    """完整 detail，等同于 RunRow 加上完整消息字段。"""
    # ... 所有 AnalyticsRunView 字段（不带 _preview 后缀）
    first_human_message: str | None
    last_ai_message: str | None
    lead_agent_tokens: int
    subagent_tokens: int
    middleware_tokens: int
    follow_up_to_run_id: str | None
    error: str | None


@dataclass
class AnalyticsListResult:
    data: list[AnalyticsRunView]
    page: int
    page_size: int
    total: int
```

### 4.3 持久层查询构造

```python
# app/gateway/services/analytics.py (continued)

def _build_list_query(
    filters: AnalyticsFilters,
    sort: AnalyticsSort,
    page: int,
    page_size: int,
) -> tuple[Select[tuple[RunRow]], Select[tuple[int]]]:
    """Return (data_query, count_query) for pagination."""
    stmt = select(RunRow)
    count_stmt = select(func.count()).select_from(RunRow)

    if filters.date_from is not None:
        stmt = stmt.where(RunRow.created_at >= filters.date_from)
        count_stmt = count_stmt.where(RunRow.created_at >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(RunRow.created_at <= filters.date_to)
        count_stmt = count_stmt.where(RunRow.created_at <= filters.date_to)
    if filters.user_ids:
        stmt = stmt.where(RunRow.user_id.in_(filters.user_ids))
        count_stmt = count_stmt.where(RunRow.user_id.in_(filters.user_ids))
    if filters.assistant_id is not None:
        stmt = stmt.where(RunRow.assistant_id == filters.assistant_id)
        count_stmt = count_stmt.where(RunRow.assistant_id == filters.assistant_id)
    if filters.model_name is not None:
        stmt = stmt.where(RunRow.model_name == filters.model_name)
        count_stmt = count_stmt.where(RunRow.model_name == filters.model_name)
    if filters.status is not None:
        stmt = stmt.where(RunRow.status == filters.status)
        count_stmt = count_stmt.where(RunRow.status == filters.status)
    if filters.q:
        # 大小写不敏感搜索（SQLite LIKE 本身是大小写不敏感对 ASCII）
        like = f"%{filters.q}%"
        stmt = stmt.where(or_(
            RunRow.first_human_message.ilike(like),
            RunRow.last_ai_message.ilike(like),
        ))
        count_stmt = count_stmt.where(or_(
            RunRow.first_human_message.ilike(like),
            RunRow.last_ai_message.ilike(like),
        ))

    # 排序
    sort_col = RunRow.created_at if sort.field == "created_at" else RunRow.total_tokens
    stmt = stmt.order_by(sort_col.desc() if sort.descending else sort_col.asc())

    # 分页
    offset = (page - 1) * page_size
    stmt = stmt.limit(page_size).offset(offset)

    return stmt, count_stmt
```

---

## 5. API 详细定义

### 5.1 `GET /api/admin/analytics/runs`

**Query 参数**：

| 名称 | 类型 | 必填 | 默认 | 校验 |
|------|------|------|------|------|
| `date_from` | ISO 8601 string | 否 | - | `datetime.fromisoformat()` |
| `date_to` | ISO 8601 string | 否 | - | `datetime.fromisoformat()` |
| `user_id` | string, repeated | 否 | - | 多次出现合并为 tuple |
| `assistant_id` | string | 否 | - | |
| `model_name` | string | 否 | - | |
| `status` | enum | 否 | - | `pending\|running\|success\|error\|timeout\|interrupted` |
| `q` | string | 否 | - | 长度 0-500 |
| `page` | int | 否 | 1 | >= 1 |
| `page_size` | int | 否 | 50 | clamp 到 [1, 200] |
| `sort` | enum | 否 | `-created_at` | `created_at\|-created_at\|total_tokens\|-total_tokens` |

**响应 200**：
```json
{
  "data": [
    {
      "run_id": "01HX...",
      "thread_id": "01HX...",
      "user_id": "alice",
      "assistant_id": "lead-agent",
      "model_name": "gpt-4o",
      "status": "success",
      "message_count": 2,
      "first_human_message_preview": "How do I configure...",
      "last_ai_message_preview": "To configure a custom model...",
      "total_input_tokens": 1234,
      "total_output_tokens": 567,
      "total_tokens": 1801,
      "llm_call_count": 3,
      "created_at": "2026-06-17T10:23:45.123456Z",
      "updated_at": "2026-06-17T10:24:01.987654Z"
    }
  ],
  "page": 1,
  "page_size": 50,
  "total": 1234
}
```

**错误响应**：
- 400：`{"detail": "date_from must be ISO 8601"}`
- 400：`{"detail": "status must be one of [...]"}`
- 400：`{"detail": "page must be >= 1"}`
- 400：`{"detail": "sort must be one of [...]"}`
- 403：`{"detail": "Permission denied: analytics:read"}`
- 500：`{"detail": "Internal server error"}`

**Headers**：
- 200：`X-DeerFlow-Page-Size-Clamped: 200`（当 page_size 被 clamp 时）
- 200：`X-DeerFlow-Query-Time-Ms: 123`（查询耗时，仅 debug 用）

### 5.2 `GET /api/admin/analytics/runs/{run_id}`

**路径参数**：`run_id: str`

**响应 200**：
```json
{
  "run_id": "01HX...",
  "thread_id": "01HX...",
  "user_id": "alice",
  "assistant_id": "lead-agent",
  "model_name": "gpt-4o",
  "status": "success",
  "message_count": 2,
  "first_human_message": "...完整文本（可能很长）...",
  "last_ai_message": "...完整文本（可能很长）...",
  "total_input_tokens": 1234,
  "total_output_tokens": 567,
  "total_tokens": 1801,
  "lead_agent_tokens": 1500,
  "subagent_tokens": 200,
  "middleware_tokens": 100,
  "llm_call_count": 3,
  "follow_up_to_run_id": null,
  "error": null,
  "created_at": "2026-06-17T10:23:45.123456Z",
  "updated_at": "2026-06-17T10:24:01.987654Z"
}
```

**错误**：
- 404：`{"detail": "Run {run_id} not found"}`
- 403：permission denied
- 500：internal error

### 5.3 `GET /api/admin/analytics/export`

**Query 参数**：与 `/runs` 相同的 filters，**除 `page` 和 `page_size` 外**。

**额外必填**：
- `format`: `csv` | `jsonl`

**响应 200 CSV**：
```
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="deerflow-runs-20260617-102345.csv"
Transfer-Encoding: chunked

run_id,thread_id,user_id,assistant_id,model_name,status,message_count,total_input_tokens,total_output_tokens,total_tokens,llm_call_count,created_at,updated_at,first_human_message,last_ai_message,error
01HX...,01HX...,alice,lead-agent,gpt-4o,success,2,1234,567,1801,3,2026-06-17T10:23:45Z,2026-06-17T10:24:01Z,"How do I...","To configure...",,
...
```

CSV 头包含 UTF-8 BOM (`﻿`) 确保 Excel 正确显示中文。

**响应 200 JSONL**：
```
Content-Type: application/x-ndjson
Content-Disposition: attachment; filename="deerflow-runs-20260617-102345.jsonl"

{"run_id": "01HX...", "thread_id": "01HX...", ...}
{"run_id": "01HX...", "thread_id": "01HX...", ...}
...
```

**实现要点**：
```python
async def stream_export(
    self,
    filters: AnalyticsFilters,
    fmt: Literal["csv", "jsonl"],
) -> AsyncIterator[bytes]:
    """Yield bytes chunks for export."""
    if fmt == "csv":
        yield _csv_header().encode("utf-8")
    async for run_row in self._iter_filtered_runs(filters, batch_size=1000):
        if fmt == "csv":
            yield _csv_line(run_row).encode("utf-8")
        else:
            yield _jsonl_line(run_row).encode("utf-8")
            yield b"\n"

async def _iter_filtered_runs(
    self,
    filters: AnalyticsFilters,
    batch_size: int = 1000,
) -> AsyncIterator[RunRow]:
    """Yield RunRow in batches to avoid loading all into memory."""
    last_created_at = None
    last_run_id = None
    while True:
        stmt = self._build_export_query(filters, last_created_at, last_run_id, batch_size)
        rows = (await self._session.execute(stmt)).scalars().all()
        if not rows:
            return
        for row in rows:
            yield row
            last_created_at = row.created_at
            last_run_id = row.run_id
        if len(rows) < batch_size:
            return
```

**Export 行数上限**：100,000 行（防止 OOM 与滥用）。超出返回 400。

---

## 6. 鉴权实现

### 6.1 Permission 注册

在 `app/gateway/authz.py` 中（假设现有模式）：

```python
PERMISSIONS = {
    # 现有 ...
    "analytics:read": {"description": "Read Q&A analytics", "default_grant": "admin"},
}
```

### 6.2 Default grant

在 `app/auth/providers.py` 中 admin 角色的 default grants 列表里加 `analytics:read`。

### 6.3 Router 用法

```python
from app.gateway.authz import require_permission

@router.get("/runs")
@require_permission("analytics", "read")
async def list_runs(...):
    ...
```

### 6.4 auth_disabled 模式

`require_permission` 在 `auth_disabled` 模式下应放行所有 permission（与现有 admin endpoint 行为一致）。如果有例外情况，在测试中验证。

---

## 7. 前端组件详细

### 7.1 `app/admin/analytics/page.tsx`

```tsx
'use client';

import { useState } from 'react';
import { AnalyticsFilters } from '@/components/admin/analytics/analytics-filters';
import { AnalyticsTable } from '@/components/admin/analytics/analytics-table';
import { AnalyticsDetailDrawer } from '@/components/admin/analytics/analytics-detail-drawer';
import { AnalyticsExportButtons } from '@/components/admin/analytics/analytics-export-buttons';
import { useAnalyticsRuns } from '@/core/admin/analytics-hooks';
import { useCurrentUser } from '@/core/auth/hooks';
import { redirect } from 'next/navigation';

export default function AdminAnalyticsPage() {
  const user = useCurrentUser();
  if (!user || !user.is_admin) {
    redirect('/');
  }

  const [filters, setFilters] = useState<AnalyticsFilters>({
    date_from: sevenDaysAgo(),
    date_to: now(),
    user_ids: [],
    assistant_id: null,
    model_name: null,
    status: null,
    q: null,
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sort, setSort] = useState('-created_at');

  const { data, isLoading, error, mutate } = useAnalyticsRuns({
    filters, page, pageSize, sort,
  });

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  return (
    <div className="admin-analytics-page">
      <h1>Q&A Analytics</h1>
      <AnalyticsFilters value={filters} onChange={setFilters} />
      <AnalyticsExportButtons filters={filters} />
      <AnalyticsTable
        data={data?.data ?? []}
        total={data?.total ?? 0}
        page={page}
        pageSize={pageSize}
        onPageChange={setPage}
        onRowClick={setSelectedRunId}
        isLoading={isLoading}
      />
      {selectedRunId && (
        <AnalyticsDetailDrawer
          runId={selectedRunId}
          onClose={() => setSelectedRunId(null)}
        />
      )}
    </div>
  );
}
```

### 7.2 `core/api/analytics.ts`

```typescript
export interface AnalyticsFilters {
  date_from?: string;
  date_to?: string;
  user_ids?: string[];
  assistant_id?: string;
  model_name?: string;
  status?: 'pending' | 'running' | 'success' | 'error' | 'timeout' | 'interrupted';
  q?: string;
}

export interface AnalyticsRun {
  run_id: string;
  thread_id: string;
  user_id: string | null;
  assistant_id: string | null;
  model_name: string | null;
  status: string;
  message_count: number;
  first_human_message_preview: string;
  last_ai_message_preview: string;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  llm_call_count: number;
  created_at: string;
  updated_at: string;
}

export interface AnalyticsListResponse {
  data: AnalyticsRun[];
  page: number;
  page_size: number;
  total: number;
}

export interface RunDetail extends AnalyticsRun {
  first_human_message: string | null;
  last_ai_message: string | null;
  lead_agent_tokens: number;
  subagent_tokens: number;
  middleware_tokens: number;
  follow_up_to_run_id: string | null;
  error: string | null;
}

export async function listAnalyticsRuns(
  filters: AnalyticsFilters,
  page: number,
  pageSize: number,
  sort: string,
): Promise<AnalyticsListResponse> {
  const params = new URLSearchParams();
  if (filters.date_from) params.set('date_from', filters.date_from);
  if (filters.date_to) params.set('date_to', filters.date_to);
  filters.user_ids?.forEach(u => params.append('user_id', u));
  if (filters.assistant_id) params.set('assistant_id', filters.assistant_id);
  if (filters.model_name) params.set('model_name', filters.model_name);
  if (filters.status) params.set('status', filters.status);
  if (filters.q) params.set('q', filters.q);
  params.set('page', String(page));
  params.set('page_size', String(pageSize));
  params.set('sort', sort);

  const response = await fetch(`/api/admin/analytics/runs?${params}`, {
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Failed to list runs: ${response.status}`);
  }
  return response.json();
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  const response = await fetch(`/api/admin/analytics/runs/${runId}`, {
    credentials: 'include',
  });
  if (!response.ok) {
    throw new Error(`Failed to get run detail: ${response.status}`);
  }
  return response.json();
}

export function getExportUrl(filters: AnalyticsFilters, format: 'csv' | 'jsonl'): string {
  const params = new URLSearchParams();
  if (filters.date_from) params.set('date_from', filters.date_from);
  if (filters.date_to) params.set('date_to', filters.date_to);
  filters.user_ids?.forEach(u => params.append('user_id', u));
  if (filters.assistant_id) params.set('assistant_id', filters.assistant_id);
  if (filters.model_name) params.set('model_name', filters.model_name);
  if (filters.status) params.set('status', filters.status);
  if (filters.q) params.set('q', filters.q);
  params.set('format', format);
  return `/api/admin/analytics/export?${params}`;
}
```

### 7.3 `core/admin/analytics-hooks.ts`

```typescript
'use client';

import useSWR from 'swr';
import { listAnalyticsRuns, getRunDetail, type AnalyticsFilters } from '@/core/api/analytics';

export function useAnalyticsRuns(params: {
  filters: AnalyticsFilters;
  page: number;
  pageSize: number;
  sort: string;
}) {
  const key = ['analytics-runs', params];
  const { data, error, isLoading, mutate } = useSWR(
    key,
    () => listAnalyticsRuns(params.filters, params.page, params.pageSize, params.sort),
    { revalidateOnFocus: false, dedupingInterval: 2000 },
  );
  return { data, error, isLoading, mutate };
}

export function useRunDetail(runId: string | null) {
  const { data, error, isLoading } = useSWR(
    runId ? ['run-detail', runId] : null,
    () => runId ? getRunDetail(runId) : null,
  );
  return { data, error, isLoading };
}
```

---

## 8. 错误处理实现

| 场景 | 实现位置 | 处理 |
|------|---------|------|
| query 参数校验失败 | Router handler | `raise HTTPException(status_code=400, detail="...")` |
| 权限校验失败 | `require_permission` 装饰器 | 自动返回 403 |
| Run not found | `AnalyticsService.get_run_detail` | 返回 None → router 抛 404 |
| DB 连接错 | 全局 exception handler | 返回 500 generic message，详细进 logs |
| Export 中途错 | `try/except` 在 generator 里 | 已发出的字节保留；ERROR 进 logs；下次重试 |
| 前端 network error | SWR 自动重试（3 次） | UI 显示 "Failed, click to retry" |
| 前端权限中途撤销 | `useCurrentUser` 检测 | 自动跳转到登录页 |

---

## 9. 测试策略

### 9.1 Task 0：前置验证（必须先跑）

`backend/tests/test_run_first_last_message_populated.py`：

```python
import pytest
from deerflow.runtime.runs.manager import RunManager

@pytest.mark.asyncio
async def test_first_and_last_message_populated_after_run():
    """Verify RunRow.first_human_message and last_ai_message are populated."""
    # 启动一个真实 lead agent run，输入固定 prompt
    # 等待 run 完成
    # 断言 RunRow.first_human_message == 输入 prompt
    # 断言 RunRow.last_ai_message 非 None 且非空
```

**如果失败**：定位 `RunStore.update_status()` 或 `RunJournal.record_event()` 中是否漏写了 `first_human_message` / `last_ai_message` 字段。

### 9.2 单元测试 `backend/tests/test_admin_analytics.py`

```python
# 9.2.1 List endpoint
async def test_list_runs_no_filters(client, admin_user)
async def test_list_runs_date_from(client, admin_user, sample_runs)
async def test_list_runs_date_to(client, admin_user, sample_runs)
async def test_list_runs_user_id_single(client, admin_user, sample_runs)
async def test_list_runs_user_id_multiple(client, admin_user, sample_runs)
async def test_list_runs_assistant_id(client, admin_user, sample_runs)
async def test_list_runs_model_name(client, admin_user, sample_runs)
async def test_list_runs_status(client, admin_user, sample_runs)
async def test_list_runs_q_search(client, admin_user, sample_runs)
async def test_list_runs_combined_filters(client, admin_user, sample_runs)
async def test_list_runs_pagination_page_1(client, admin_user, sample_runs)
async def test_list_runs_pagination_page_2(client, admin_user, sample_runs)
async def test_list_runs_total_consistency(client, admin_user, sample_runs)
async def test_list_runs_sort_default(client, admin_user, sample_runs)
async def test_list_runs_sort_total_tokens(client, admin_user, sample_runs)
async def test_list_runs_empty_result(client, admin_user)
async def test_list_runs_page_size_clamp_to_200(client, admin_user)

# 9.2.2 Detail endpoint
async def test_get_run_detail_success(client, admin_user, sample_run)
async def test_get_run_detail_not_found(client, admin_user)
async def test_get_run_detail_long_messages(client, admin_user)  # 验证不截断

# 9.2.3 Export endpoint
async def test_export_csv_format(client, admin_user, sample_runs)
async def test_export_jsonl_format(client, admin_user, sample_runs)
async def test_export_with_filters(client, admin_user, sample_runs)
async def test_export_empty_result(client, admin_user)
async def test_export_large_result_no_oom(client, admin_user, large_sample)  # 10000+ runs
async def test_export_exceeds_limit(client, admin_user, huge_sample)  # > 100k rows → 400

# 9.2.4 Permission
async def test_admin_can_access(client, admin_user)
async def test_regular_user_forbidden(client, regular_user)
async def test_no_auth_disabled_mode_allows(client, auth_disabled)

# 9.2.5 Validation errors
async def test_invalid_date_format_returns_400(client, admin_user)
async def test_invalid_status_returns_400(client, admin_user)
async def test_invalid_sort_returns_400(client, admin_user)
async def test_page_zero_returns_400(client, admin_user)
```

### 9.3 前端测试

**组件测试**（Vitest + React Testing Library）：
- `analytics-table.test.tsx`: 渲染 mock、空状态、分页交互、行点击
- `analytics-filters.test.tsx`: filter 状态变化、URL 同步
- `analytics-detail-drawer.test.tsx`: 长消息折叠、链接跳转
- `analytics-export-buttons.test.tsx`: 触发下载

**Hook 测试**：
- `analytics-hooks.test.tsx`: mock fetch、验证参数传递、loading / error 状态

**E2E（Playwright）**：
```typescript
test('admin can browse and export Q&A analytics', async ({ page }) => {
  // 1. login as admin
  // 2. navigate to /admin/analytics
  // 3. assert table renders with default filter
  // 4. change date range filter
  // 5. assert table updates
  // 6. click row
  // 7. assert drawer opens with full messages
  // 8. close drawer
  // 9. click Export CSV
  // 10. assert download triggered
  // 11. parse downloaded CSV
  // 12. assert row count matches table total
});

test('non-admin cannot access analytics page', async ({ page }) => {
  // 1. login as regular user
  // 2. navigate to /admin/analytics
  // 3. assert redirect to /
});
```

### 9.4 覆盖率目标

- Backend 新增代码：`make test-coverage` 显示 > 80%
- Frontend 新增代码：> 70%

---

## 10. 实施步骤（高层 plan）

```
Task 0: 验证 first/last 字段被填充（前置）
   ├─ 跑 test_run_first_last_message_populated.py
   └─ 如失败：修复 RunStore/RunJournal 写入路径，再跑通过

Task 1: 注册新 permission
   ├─ app/gateway/authz.py: 加 analytics:read
   └─ app/auth/providers.py: admin 默认 grant 加 analytics:read

Task 2: AnalyticsService 后端实现
   ├─ app/gateway/services/analytics.py: dataclass + query builder
   ├─ app/gateway/deps.py: + get_analytics_service
   └─ unit tests

Task 3: Router 实现
   ├─ app/gateway/routers/admin_analytics.py: 3 endpoints
   ├─ app/gateway/app.py: include_router
   └─ integration tests

Task 4: 前端 API client + hooks
   ├─ frontend/src/core/api/analytics.ts
   └─ frontend/src/core/admin/analytics-hooks.ts

Task 5: 前端页面 + 组件
   ├─ page.tsx
   ├─ analytics-table.tsx
   ├─ analytics-filters.tsx
   ├─ analytics-detail-drawer.tsx
   └─ analytics-export-buttons.tsx

Task 6: 前端测试
   ├─ 组件单元测试
   ├─ hook 测试
   └─ E2E 测试

Task 7: 文档更新
   ├─ backend/CLAUDE.md: 加 admin_analytics router 说明
   ├─ frontend/CLAUDE.md (如有): 加 analytics 页说明
   └─ README.md: 加 admin analytics 入口

Task 8: 端到端验证
   ├─ 后端 make lint && make test
   ├─ 前端 pnpm lint && pnpm typecheck && pnpm build
   └─ E2E 通过
```

---

## 11. 风险与缓解

| # | 风险 | 严重度 | 缓解 |
|---|------|--------|------|
| R1 | `first_human_message` / `last_ai_message` 未填 | 阻塞 | Task 0 验证；失败则修 RunStore |
| R2 | authz.py 不支持新 permission | 高 | 代码调研先于实施；必要时扩展 |
| R3 | 大结果集导出 OOM | 中 | StreamingResponse + 异步游标 + batch=1000 |
| R4 | LIKE 搜索性能差 | 低（trusted local 规模）| 监控查询耗时；> 1s 时升级 FTS5 |
| R5 | CSV 中文乱码 | 中 | UTF-8 with BOM |
| R6 | 前端 admin 路由绕过 | 中 | useCurrentUser 守卫 + 后端再校验 |
| R7 | export 行数上限过低 | 低 | 100k 行足够 trusted local 用 |
| R8 | 前端 menu 在非 admin 下泄漏 | 低 | menu 用 `is_admin` 条件渲染 |

---

## 12. 一句话架构总结

**怎么实现**：在 admin 浏览器 ↔ Gateway ↔ RunRow 之间加一层 admin-only 的"分析视图"，3 个 endpoint（list / detail / export）+ 1 个 service + 1 个 page + 4 个前端组件，零数据库迁移，admin 鉴权，复用现有 RunStore 和权限模式。

**关键架构决策**：
- 服务层在 `app/gateway/services/`（consumer-only，不放 harness 层）
- Export 必须 StreamingResponse + 异步游标
- 前端路由守卫 + 后端权限校验 双保险
- 鉴权失败统一 403，validation 失败统一 400，DB 错统一 500 generic

**何时停止不进一步**：8 个 task 全部完成 + 全部测试通过 + 文档更新完毕 + E2E 验证通过 = spec 完成。不要在这个 spec 里继续添加新功能。
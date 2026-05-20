# feat/auth-on-2.0-rc 多租户隔离实现分析报告

> 分支来源: `upstream/feat/auth-on-2.0-rc`（bytedance/deer-flow）
> 分析日期: 2026-05-15
> 用途: 代码 review，仅记录不合并

---

## 一、核心架构总览

多租户隔离通过四层机制实现：

| 层级 | 组件 | 文件 |
|------|------|------|
| **认证层** | JWT cookie 解码 + contextvar 写入 | `auth_middleware.py`, `deps.py` |
| **授权层** | `@require_permission(owner_check=True)` 装饰器 | `authz.py` |
| **存储层** | `ThreadMetaRepository.check_access()` | `sql.py` |
| **LangGraph 层** | `add_owner_filter` 注入/过滤 | `langgraph_auth.py` |

---

## 二、完整请求流程（从请求到响应）

```
用户请求 (cookie 含 JWT access_token)
    ↓
┌─────────────────────────────────────────────────────────────┐
│ auth_middleware.py:AuthMiddleware.dispatch()                 │
│ 行 73-117                                                   │
│                                                              │
│   1. 行 73-74: _is_public(path) → 公共路径直接放行          │
│   2. 行 77-86: 无 access_token cookie → 401 NOT_AUTHENTICATED│
│   3. 行 103-110: get_current_user_from_request(request)     │
│      → JWT 解码 → provider.get_user() → User 对象            │
│   4. 行 112: request.state.user = user                     │
│   5. 行 113: set_current_user(user) → contextvar 写入        │
│   6. 行 114-117 finally: reset_current_user(token) 清理      │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ authz.py:require_permission() 装饰器                        │
│ 行 168-269                                                   │
│                                                              │
│   1. 行 215-217: 从 kwargs["request"] 获取 request          │
│   2. 行 219-222: request.state.auth 优先，否则调用          │
│      _authenticate(request) → get_optional_user_from_request│
│   3. 行 224-225: 未认证 → 401                                │
│   4. 行 228-232: 检查 resource:action 权限                  │
│   5. 行 250-263: 如果 owner_check=True:                      │
│      - 从 kwargs 获取 thread_id                              │
│      - get_thread_meta_repo(request) → repo                 │
│      - repo.check_access(thread_id, user.id)                │
│      - 返回 404 如果 not allowed                             │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ deps.py:get_thread_meta_repo()                              │
│ 行 113                                                       │
│                                                              │
│   return request.app.state.thread_meta_repo                  │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ thread_meta/sql.py:ThreadMetaRepository.check_access()       │
│ 行 80-92                                                     │
│                                                              │
│   async with self._sf() as session:                          │
│     row = await session.get(ThreadMetaRow, thread_id)       │
│     if row is None: return True (遗留线程放行)               │
│     if row.owner_id is None: return True (共享线程放行)     │
│     return row.owner_id == owner_id                          │
│                                                              │
│   如果 require_existing=True: 缺失行 → False                 │
└─────────────────────────────────────────────────────────────┘
    ↓
最终响应: 200 OK 或 404 Thread not found
```

### 2.1 请求流程详解（按调用顺序）

#### Step 1: JWT 验证 + contextvar 设置

**文件**: `backend/app/gateway/auth_middleware.py`
**类**: `AuthMiddleware`（继承 `BaseHTTPMiddleware`）
**方法**: `dispatch(request, call_next)`

```python
# 行 42-46: 公共路径判断
_PUBLIC_PATH_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json")
_PUBLIC_EXACT_PATHS = {"/api/auth/login", "/api/auth/register", ...}

def _is_public(path: str) -> bool:
    return any(path.startswith(p) for p in _PUBLIC_PATH_PREFIXES) or path in _PUBLIC_EXACT_PATHS
```

```python
# 行 73-117: dispatch 完整流程
async def dispatch(self, request: Request, call_next):
    path = request.url.path

    # 公共路径放行
    if _is_public(path):
        return await call_next(request)

    # 无 token → 401
    access_token = request.cookies.get("access_token")
    if not access_token:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    try:
        # JWT 解码 + 用户查询
        user = await get_current_user_from_request(request)  # deps.py:186
    except HTTPException:
        return JSONResponse(status_code=401, content={"detail": "Token error"})

    # 写入 contextvar
    request.state.user = user  # 行 112
    token = set_current_user(user)  # 行 113 — 写入 deerflow.runtime.user_context

    try:
        return await call_next(request)
    finally:
        reset_current_user(token)  # 行 115-117 — 清理 contextvar
```

#### Step 2: 权限检查装饰器

**文件**: `backend/app/gateway/authz.py`
**函数**: `require_permission()`
**签名**（行 168-172）:
```python
def require_permission(
    resource: str,
    action: str,
    owner_check: bool = False,      # ← 关键：是否检查 thread 所有权
    require_existing: bool = False,  # ← 关键：缺失行是否视为拒绝
) -> Callable[[Callable[P, T]], Callable[P, T]]:
```

**执行流程**（行 212-269）:
```python
# 获取 request（行 215-217）
request: Request = kwargs.get("request")
if not request:
    raise ValueError("require_permission must have 'request' in kwargs")

# 获取/创建 AuthContext（行 219-222）
auth: AuthContext = getattr(request.state, "auth", None)
if auth is None:
    auth = await _authenticate(request)
    request.state.auth = auth

# 认证检查（行 224-225）
if auth.user is None:
    raise HTTPException(status_code=401, detail="Not authenticated")

# 权限检查（行 228-232）
permission = f"{resource}:{action}"
if permission not in auth.permissions:
    raise HTTPException(status_code=403, detail="Permission denied")

# owner_check=True 时的逻辑（行 250-263）
if owner_check:
    thread_id = kwargs.get("thread_id")
    if thread_id is None:
        raise ValueError("require_permission with owner_check=True requires 'thread_id' parameter")

    from app.gateway.deps import get_thread_meta_repo
    thread_meta_repo = get_thread_meta_repo(request)

    allowed = await thread_meta_repo.check_access(
        thread_id,
        str(auth.user.id),
        require_existing=require_existing,  # main 分支有，auth 分支无此参数
    )
    if not allowed:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
```

#### Step 3: 获取 thread_meta_repo

**文件**: `backend/app/gateway/deps.py`
**函数**: `get_thread_meta_repo()`（行 113）
```python
get_thread_meta_repo = _require("thread_meta_repo", "Thread metadata store")

# _require helper（行 97-105）
def _require(attr: str, label: str):
    def dep(request: Request):
        val = getattr(request.app.state, attr, None)
        if val is None:
            raise HTTPException(status_code=503, detail=f"{label} not available")
        return val
    return dep
```

#### Step 4: check_access 所有权验证

**文件**: `backend/packages/harness/deerflow/persistence/thread_meta/sql.py`
**方法**: `check_access()`（行 80-92）
```python
async def check_access(
    self,
    thread_id: str,
    owner_id: str,
    require_existing: bool = False,  # main 分支有，auth 分支无此参数
) -> bool:
    """Check if owner_id has access to thread_id.

    Returns True if: row doesn't exist (untracked thread), owner_id
    is None on the row (shared thread), or owner_id matches.
    """
    async with self._sf() as session:
        row = await session.get(ThreadMetaRow, thread_id)

        # main 分支: require_existing 控制缺失行行为
        # auth 分支: 缺失行默认返回 True
        if row is None:
            return not require_existing  # main: require_existing=True → False

        if row.owner_id is None:
            return True  # 共享线程 → 放行

        return row.owner_id == owner_id  # 精确匹配
```

---

## 三、Feature 1：Thread 创建时注入 user_id

### 3.1 关键文件

**`backend/packages/harness/deerflow/persistence/thread_meta/sql.py`**

`create()` 方法（行 30-56）使用 `AUTO` sentinel 默认值，自动从 contextvar 解析 `owner_id`：

```python
async def create(
    self,
    thread_id: str,
    *,
    assistant_id: str | None = None,
    owner_id: str | None | _AutoSentinel = AUTO,  # ← 默认 AUTO
    display_name: str | None = None,
) -> dict:
    resolved_owner_id = resolve_owner_id(owner_id, method_name="ThreadMetaRepository.create")
    row = ThreadMetaRow(
        thread_id=thread_id,
        owner_id=resolved_owner_id,
        ...
    )
```

### 3.2 AUTO sentinel 定义

**`backend/packages/harness/deerflow/runtime/user_context.py`**

- `_current_user` ContextVar（行 46）：
  ```python
  _current_user: Final[ContextVar[CurrentUser | None]] = ContextVar("deerflow_current_user", default=None)
  ```

- `AUTO` 单例（行 103）：
  ```python
  AUTO: Final[_AutoSentinel] = _AutoSentinel()
  ```

- `resolve_owner_id()` 实现（行 119-142）：
  ```python
  def resolve_owner_id(
      value: str | None | _AutoSentinel,
      *,
      method_name: str = "repository method",
  ) -> str | None:
      if isinstance(value, _AutoSentinel):
          user = _current_user.get()
          if user is None:
              raise RuntimeError(f"{method_name} called with owner_id=AUTO but no user context is set; ...")
          return user.id
      return value
  ```

### 3.3 数据流

```
cookie (access_token)
    ↓
AuthMiddleware.dispatch() [auth_middleware.py:73-117]
    ↓
get_current_user_from_request() [deps.py:186-203]
    ↓ JWT decode → provider.get_user() → User object
    ↓
set_current_user(user) → contextvar写入 [user_context.py:55-62]
    ↓
ThreadMetaRepository.create(owner_id=AUTO) → resolve_owner_id() 读取
```

---

## 四、Feature 2：thread/run 端点所有权检查

### 4.1 装饰器实现

**`backend/app/gateway/authz.py`**（行 168-269）

```python
def require_permission(
    resource: str,
    action: str,
    owner_check: bool = False,      # ← 关键参数
    require_existing: bool = False, # ← main 分支有，auth 分支已删除
) -> Callable[[Callable[P, T]], Callable[P, T]]:
```

**owner_check=True 时的逻辑**（行 250-263）：
```python
if owner_check:
    thread_id = kwargs.get("thread_id")
    if thread_id is None:
        raise ValueError("require_permission with owner_check=True requires 'thread_id' parameter")

    from app.gateway.deps import get_thread_meta_repo
    thread_meta_repo = get_thread_meta_repo(request)
    allowed = await thread_meta_repo.check_access(thread_id, str(auth.user.id))
    if not allowed:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
```

### 4.2 threads.py 端点覆盖（auth-on-2.0-rc）

**`backend/app/gateway/routers/threads.py`**

| 行号 | 方法 | 路由 | 装饰器 |
|------|------|------|--------|
| 167 | DELETE | `/{thread_id}` | `require_permission("threads", "delete", owner_check=True)` |
| 177 | POST | `/` | 无 owner_check（创建时自动注入 owner_id） |
| 210 | POST | `/search` | 无 owner_check（search 自动带 owner 过滤） |
| 234 | PATCH | `/{thread_id}` | `require_permission("threads", "write", owner_check=True)` |
| 251 | GET | `/{thread_id}` | `require_permission("threads", "read", owner_check=True)` |
| 289 | GET | `/{thread_id}/state` | `require_permission("threads", "read", owner_check=True)` |
| 324 | POST | `/{thread_id}/state` | `require_permission("threads", "write", owner_check=True)` |
| 388 | POST | `/{thread_id}/history` | `require_permission("threads", "read", owner_check=True)` |

### 4.3 thread_runs.py 端点覆盖（auth-on-2.0-rc）

**`backend/app/gateway/routers/thread_runs.py`**

| 行号 | 方法 | 路由 | 装饰器 |
|------|------|------|--------|
| 130 | POST | `/{thread_id}/runs` | `require_permission("runs", "create", owner_check=True)` |
| 144 | POST | `/{thread_id}/runs/stream` | `require_permission("runs", "create", owner_check=True)` |
| 167 | POST | `/{thread_id}/runs/wait` | `require_permission("runs", "create", owner_check=True)` |
| 186 | GET | `/{thread_id}/runs` | `require_permission("runs", "read", owner_check=True)` |
| 195 | GET | `/{thread_id}/runs/{run_id}` | `require_permission("runs", "read", owner_check=True)` |
| 207 | POST | `/{thread_id}/runs/{run_id}/cancel` | `require_permission("runs", "cancel", owner_check=True)` |
| 237 | GET | `/{thread_id}/runs/{run_id}/join` | `require_permission("runs", "read", owner_check=True)` |
| 248 | GET/POST | `/{thread_id}/runs/{run_id}/stream` | `require_permission("runs", "read", owner_check=True)` |
| 283 | GET | `/{thread_id}/messages` | `require_permission("runs", "read", owner_check=True)` |
| 297 | GET | `/{thread_id}/runs/{run_id}/messages` | `require_permission("runs", "read", owner_check=True)` |
| 307 | GET | `/{thread_id}/runs/{run_id}/events` | `require_permission("runs", "read", owner_check=True)` |
| 321 | GET | `/{thread_id}/token-usage` | `require_permission("threads", "read", owner_check=True)` |

---

## 五、Feature 3：User B 无法访问 User A 的 thread

### 5.1 check_access() 核心逻辑

**`backend/packages/harness/deerflow/persistence/thread_meta/sql.py`**（行 80-92）

```python
async def check_access(self, thread_id: str, owner_id: str) -> bool:
    """Check if owner_id has access to thread_id.

    Returns True if: row doesn't exist (untracked thread), owner_id
    is None on the row (shared thread), or owner_id matches.
    """
    async with self._sf() as session:
        row = await session.get(ThreadMetaRow, thread_id)
        if row is None:
            return True          # 遗留线程 → 允许（避免阻断旧数据）
        if row.owner_id is None:
            return True          # 共享线程 → 允许
        return row.owner_id == owner_id  # 匹配 → 允许，不匹配 → 拒绝
```

**三值逻辑**：

| 情况 | 返回值 | 含义 |
|------|--------|------|
| 行不存在 | `True` | 遗留线程 → 允许访问 |
| `owner_id=NULL` | `True` | 共享线程 → 允许访问 |
| `owner_id` 匹配 | `True` | 正常访问 |
| `owner_id` 不匹配 | `False` | 隔离 → 返回 404 |

### 5.2 存储层 owner 过滤

`sql.py` 中所有读取方法均通过 `resolve_owner_id(AUTO)` 自动注入 owner 过滤：

**`get()` 方法**（行 58-72）：
```python
if resolved_owner_id is not None and row.owner_id != resolved_owner_id:
    return None  # 跨用户隔离
```

**`search()` 方法**（行 94-129）：
```python
if resolved_owner_id is not None:
    stmt = stmt.where(ThreadMetaRow.owner_id == resolved_owner_id)  # 自动 owner 过滤
```

### 5.3 LangGraph 层隔离

**`backend/app/gateway/langgraph_auth.py`**（行 94-106）

```python
@auth.on
async def add_owner_filter(ctx: Auth.types.AuthContext, value: dict):
    """Inject owner_id metadata on writes; filter by owner_id on reads."""
    metadata = value.setdefault("metadata", {})
    metadata["owner_id"] = ctx.user.identity
    return {"owner_id": ctx.user.identity}  # 返回过滤条件供 LangGraph 应用
```

写入时 stamp `owner_id`，读取时返回 filter 供 LangGraph 应用。

---

## 六、main 分支现有实现状态 vs auth-on-2.0-rc

### 6.1 main 分支已有（无需修改）

| 组件 | 文件:行号 | 状态 |
|------|-----------|------|
| JWT 验证 + contextvar 写入 | `auth_middleware.py:72-117` | 已有 |
| `require_permission` 装饰器 | `authz.py:168-269` | 已有 |
| `owner_check=True` 参数 | `authz.py:170` | 已有 |
| `require_existing` 参数 | `authz.py:171` | 已有（auth 分支删除了这个） |
| `check_access()` 方法 | `sql.py:80-92` | 已有 |
| `get_thread_meta_repo()` | `deps.py:113` | 已有 |
| `set_current_user()` / `reset_current_user()` | `user_context.py` | 已有 |
| AUTO sentinel + `resolve_owner_id()` | `user_context.py` | 已有 |

### 6.2 main 已有的 `owner_check=True` 端点

**`threads.py`**：

| 行号 | 端点 | 装饰器 |
|------|------|--------|
| 213 | `DELETE /{thread_id}` | `require_permission("threads", "delete", owner_check=True, require_existing=True)` |
| 349 | `PATCH /{thread_id}` | `require_permission("threads", "write", owner_check=True, require_existing=True)` |
| 384 | `GET /{thread_id}` | `require_permission("threads", "read", owner_check=True)` |
| 431 | `GET /{thread_id}/state` | `require_permission("threads", "read", owner_check=True)` |
| 488 | `POST /{thread_id}/state` | `require_permission("threads", "write", owner_check=True, require_existing=True)` |
| 558 | `POST /{thread_id}/history` | `require_permission("threads", "read", owner_check=True)` |

**`thread_runs.py`**：

| 行号 | 端点 | 装饰器 |
|------|------|--------|
| 117 | `POST /{thread_id}/runs` | `require_permission("runs", "create", owner_check=True, require_existing=True)` |
| 125 | `POST /{thread_id}/runs/stream` | `require_permission("runs", "create", owner_check=True, require_existing=True)` |
| 153 | `POST /{thread_id}/runs/wait` | `require_permission("runs", "create", owner_check=True, require_existing=True)` |
| 186 | `GET /{thread_id}/runs` | `require_permission("runs", "read", owner_check=True)` |
| 199 | `GET /{thread_id}/runs/{run_id}` | `require_permission("runs", "read", owner_check=True)` |
| 217 | `POST /{thread_id}/runs/{run_id}/cancel` | `require_permission("runs", "cancel", owner_check=True, require_existing=True)` |
| 253 | `GET /{thread_id}/runs/{run_id}/join` | `require_permission("runs", "read", owner_check=True)` |
| 296 | `GET/POST /{thread_id}/runs/{run_id}/stream` | `require_permission("runs", "read", owner_check=True)` |
| 310 | `GET /{thread_id}/messages` | `require_permission("runs", "read", owner_check=True)` |
| 325 | `GET /{thread_id}/runs/{run_id}/messages` | `require_permission("runs", "read", owner_check=True)` |
| 337 | `GET /{thread_id}/runs/{run_id}/events` | `require_permission("runs", "read", owner_check=True)` |
| 352 | `GET /{thread_id}/token-usage` | `require_permission("threads", "read", owner_check=True)` |

### 6.3 main 与 auth-on-2.0-rc 的关键差异

| 差异项 | main | auth-on-2.0-rc | 说明 |
|--------|------|----------------|------|
| `require_existing` 参数 | 有 | **已删除** | auth 分支简化了逻辑 |
| `check_access()` 签名 | `check_access(thread_id, owner_id, require_existing=False)` | `check_access(thread_id, owner_id)` | auth 分支移除了 `require_existing` |
| threads.py 端点数量 | 更多（包含 feedback 逻辑） | 精简 | auth 分支删除了一些冗余功能 |
| `list_thread_messages` | 有 feedback 注入逻辑 | 删除了 feedback 逻辑 | 行 291-313 变化 |
| Token usage 相关类型 | `ThreadTokenUsageResponse` 等（行 68-93） | 已删除 | 简化了响应模型 |

---

## 七、如果要将 auth-on-2.0-rc 同步到 main 需要修改的文件

### 7.1 `backend/app/gateway/authz.py`

- **删除** `require_existing` 参数（第 171 行）
- **修改** `check_access` 调用（第 266-269 行）移除 `require_existing`

**当前（main）**:
```python
# 行 168-172
def require_permission(
    resource: str,
    action: str,
    owner_check: bool = False,
    require_existing: bool = False,  # ← 删除此参数
) -> Callable[[Callable[P, T]], Callable[P, T]]:
```

```python
# 行 266-269
allowed = await thread_meta_repo.check_access(
    thread_id,
    str(auth.user.id),
    require_existing=require_existing,  # ← 删除此参数
)
```

### 7.2 `backend/packages/harness/deerflow/persistence/thread_meta/sql.py`

- **删除** `check_access()` 的 `require_existing` 参数（第 80 行）
- **调整** 缺失行的默认行为（auth 分支默认返回 True）

**当前（main）**:
```python
# 行 80
async def check_access(
    self,
    thread_id: str,
    owner_id: str,
    require_existing: bool = False,  # ← 删除此参数
) -> bool:
    ...
    if row is None:
        return not require_existing  # ← 改为 return True
```

### 7.3 `backend/app/gateway/routers/thread_runs.py`

- **删除** 所有 `require_existing=True`（约 4 处：行 117, 125, 153, 217）

**当前（main）**:
```python
# 行 117
@require_permission("runs", "create", owner_check=True, require_existing=True)
async def create_run(...):

# 行 125
@require_permission("runs", "create", owner_check=True, require_existing=True)
async def stream_run(...):

# 行 153
@require_permission("runs", "create", owner_check=True, require_existing=True)
async def wait_run(...):

# 行 217
@require_permission("runs", "cancel", owner_check=True, require_existing=True)
async def cancel_run(...):
```

### 7.4 `backend/app/gateway/routers/threads.py`

- **删除** `require_existing=True`（约 3 处：行 213, 349, 488）

**当前（main）**:
```python
# 行 213
@require_permission("threads", "delete", owner_check=True, require_existing=True)
async def delete_thread(...):

# 行 349
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def update_thread(...):

# 行 488
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def update_thread_state(...):
```

### 7.5 总结：需要修改的文件列表

| 文件 | 修改类型 | 修改数量 |
|------|----------|----------|
| `authz.py` | 删除参数 + 调用修改 | 约 2 处 |
| `sql.py` | 删除参数 + 修改默认行为 | 约 2 处 |
| `thread_runs.py` | 删除 require_existing=True | 约 4 处 |
| `threads.py` | 删除 require_existing=True | 约 3 处 |
| **合计** | | **约 11 处** |

---

## 八、测试覆盖

**`backend/tests/test_owner_isolation.py`**

| 测试 | 行号 | 验证内容 |
|------|------|----------|
| `test_thread_meta_cross_user_isolation` | 72-114 | User A 的 thread 对 User B 返回 None |
| `test_runs_cross_user_isolation` | 158-197 | User A 的 run 对 User B 返回 None |
| `test_run_events_cross_user_isolation` | 230-295 | 消息内容不泄露（最敏感向量） |
| `test_feedback_cross_user_isolation` | 336-385 | Feedback 隔离 |
| `test_repository_without_context_raises` | 419-431 | 缺少 contextvar 时正确报错 |

---

## 九、潜在风险与边界情况

### 9.1 高风险：check_access() 对不存在的行返回 True

```python
if row is None:
    return True  # 遗留线程任何认证用户都可访问
```

如果攻击者猜测 `thread_id`，可能访问到未被 `threads_meta` 表跟踪的遗留线程。

**缓解措施**：注释明确说明这是"严格拒绝"设计（`authz.py` 行 243-244），仅存在且 owner_id 不同的记录才触发 404。

### 9.2 中风险：Thread 返回 404，Run 返回 None

| 资源 | 隔离失败响应 |
|------|-------------|
| Thread | 404 "Thread not found" |
| Run | `None`（隐式） |

响应差异可能让攻击者推断其他用户的数据存在。

### 9.3 低风险：缺少 Alembic migration

`threads_meta` 表通过 SQLAlchemy `metadata.create_all()` 自动创建（`deps.py` 行 29-60），而非 Alembic migration。升级时需注意表结构同步。

### 9.4 低风险：AUTO sentinel 上下文缺失报错时机

`resolve_owner_id()` 在 contextvar 为空时抛出 `RuntimeError`。测试环境有 `test_repository_without_context_raises` 覆盖，但生产环境请求漏过 context 设置时会导致 500 错误。

---

## 十、文件行号索引

| 文件 | 关键位置 | 行号 |
|------|----------|------|
| `auth_middleware.py` | `AuthMiddleware.dispatch()` | 73-117 |
| `authz.py` | `require_permission` 装饰器 | 168-269 |
| `authz.py` | `owner_check=True` 逻辑 | 250-263 |
| `authz.py` | `require_existing` 参数 | 171, 266-269 |
| `authz.py` | `_authenticate()` | 120-133 |
| `sql.py` | `check_access()` | 80-92 |
| `sql.py` | `resolve_owner_id` 使用 | 41, 64, 108, 146, 160, 180, 199 |
| `sql.py` | `get()` owner 过滤 | 58-72 |
| `sql.py` | `search()` owner 过滤 | 94-129 |
| `sql.py` | `create()` AUTO 注入 | 30-56 |
| `langgraph_auth.py` | `add_owner_filter` | 94-106 |
| `user_context.py` | `resolve_owner_id()` | 119-142 |
| `user_context.py` | `AUTO` sentinel | 103 |
| `user_context.py` | `_current_user` ContextVar | 46 |
| `user_context.py` | `set_current_user()` | 55-62 |
| `deps.py` | `get_current_user_from_request` | 166-203 |
| `deps.py` | `get_thread_meta_repo` | 113 |
| `threads.py` (main) | 端点列表 | 213-558 |
| `thread_runs.py` (main) | 端点列表 | 117-352 |
| `test_owner_isolation.py` | 隔离测试套件 | 全文 |
| `thread_meta/model.py` | 表结构定义 | 13-23 |

---

## 十一、与 main 分支的分叉状态

**分叉点**: `055e4df0490dbd1bca9ffc8f6b2330668933223b`

| 分支 | 最新提交 |
|------|----------|
| `upstream/feat/auth-on-2.0-rc` | `2b33bfd7` — security(auth): wire @require_permission(owner_check=True) on isolation routes |
| `upstream/main` | `45060a9f` — fix(runtime): avoid postgres aggregate row lock (#2962) |

该分支在 auth 安全方向独立演进，与 upstream/main 各自有新提交，互不同步。合并时会需要处理冲突。

---

## 十二、结论

**main 分支已实现完整的多租户隔离**，与 `feat/auth-on-2.0-rc` 的核心逻辑一致。auth 分支的主要差异是**删除了 `require_existing` 参数**，简化了代码。

### 如果你只需要确认 main 是否已有这些功能：
**已有，无需额外修改。**

### 如果要同步 auth 分支的变更（删除 `require_existing`）：
需要修改 4 个文件，约 10+ 处改动，详见第七章。
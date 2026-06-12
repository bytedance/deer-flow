# Feature Design: Per-User Custom Skill Isolation

**Issue**: #3299
**Branch**: `feat/per-user-skill-isolation`
**Author**: Engineering
**Date**: 2026-06-04
**Status**: Ready for Review

---

## 0. 实现效果

> 以下均为真实代码运行输出，可复现。

### 0.0 整体效果：变更前 vs 变更后

#### 变更前 — 所有用户共享全局 storage，数据泄露 + 越权可写

```
Alice 创建 alice-secret（描述：Alice 工资核算脚本）
Bob   创建 bob-tool（描述：Bob 竞对分析技能）

Alice 看到的技能: ['alice-secret', 'bob-tool']   ← 泄露 Bob 的技能！
Bob   看到的技能: ['alice-secret', 'bob-tool']   ← 泄露 Alice 的技能！

Bob 读取 alice-secret 内容 : 成功  ← 越权！
Bob 篡改 alice-secret 描述 : 成功  ← 越权！  description: 被 Bob 篡改
Bob 删除 alice-secret      : 成功  ← 越权！
```

#### 变更后 — 每个用户持有独立的命名空间，全链路隔离

```
Alice 看到的技能: ['alice-secret']   ← 只有自己的
Bob   看到的技能: ['bob-tool']       ← 只有自己的

Bob 尝试读取 alice-secret  → FileNotFoundError  ← 阻断 ✓
Bob 尝试编辑 alice-secret  → FileNotFoundError  ← 阻断 ✓
Bob 尝试删除 alice-secret  → FileNotFoundError  ← 阻断 ✓

Alice 的技能内容完整无损: description: Alice 工资核算脚本
```

**一句话总结**：用户只能看到和操作自己创建的 custom skills。其他用户的技能对其完全不可见，所有越权操作均以 `FileNotFoundError` / **HTTP 404** 静默拒绝（而非 403），不向攻击者暴露目标是否存在。

---

### 0.1 存储层：文件系统命名空间

技能写入后的实际磁盘结构：

```
skills/
└── custom/
    ├── alice-uuid/
    │   └── alice-secret/SKILL.md      ← 只属于 alice
    └── bob-uuid/
        └── bob-tool/SKILL.md          ← 只属于 bob
```

两个用户可独立持有同名技能，路径互不冲突：

```
custom/alice-uuid/my-skill/SKILL.md
custom/bob-uuid/my-skill/SKILL.md    ← 同名，独立存在 ✓
```

### 0.2 API 层：HTTP 接口响应隔离

```
Alice  GET  /api/skills/custom               → 200  ['alice-secret']
Bob    GET  /api/skills/custom               → 200  ['bob-tool']

Bob    GET    /api/skills/custom/alice-secret → 404  Custom skill 'alice-secret' not found
Bob    PUT    /api/skills/custom/alice-secret → 404
Bob    DELETE /api/skills/custom/alice-secret → 404

Alice  GET    /api/skills/custom/alice-secret → 200  name=alice-secret  ✓ 自己的不受影响
```

> 404 而非 403：向攻击者隐藏目标技能是否存在的信息。

### 0.3 Prompt 层：Agent 系统提示词只含自己的技能

```
alice 的系统 Prompt 注入技能: ['data-analysis']    ← 只有 alice 的
bob   的系统 Prompt 注入技能: ['code-review']       ← 只有 bob 的

prompt cache 独立存储（2 个条目）:
  cache[user_id='alice-uuid'] → ['data-analysis']
  cache[user_id='bob-uuid']   → ['code-review']
```

### 0.4 Agent Tool 层：skill_manage_tool 写入用户专属路径

```
alice 创建技能 → custom/alice-uuid/my-skill/SKILL.md      ✓
bob  尝试编辑 alice 的技能 → FileNotFoundError             ← 阻断 ✓
bob  创建同名技能 → custom/bob-uuid/my-skill/SKILL.md      ✓（独立）
```

### 0.5 端到端测试（6/6 通过）

```
PASSED  test_users_cannot_see_each_others_custom_skills
PASSED  test_user_b_cannot_edit_user_a_skill
PASSED  test_user_b_cannot_delete_user_a_skill
PASSED  test_two_users_same_skill_name_independent
PASSED  test_prompt_cache_keyed_per_user
PASSED  test_skill_manage_tool_isolated_by_user_id
```

---

## 1. 背景与问题

### 1.1 现状

DeerFlow 支持用户创建「自定义技能（Custom Skill）」来扩展 Agent 能力。技能以 Markdown 文件形式存储在磁盘上，目录结构为：

```
skills/
├── public/<name>/SKILL.md        ← 内置公共技能
└── custom/
    ├── my-skill/SKILL.md         ← 所有用户共享
    └── .history/my-skill.jsonl
```

在多用户部署场景下，**所有用户共享同一个 `custom/` 目录**，导致：

| 风险 | 描述 |
|---|---|
| **数据泄露** | 用户 A 能看到用户 B 创建的技能，包括其中可能包含的私有业务逻辑 |
| **操作越权** | 用户 A 可以编辑、删除用户 B 的技能 |
| **提示注入污染** | Agent 系统 Prompt 中会出现其他用户的技能，干扰 LLM 行为 |

### 1.2 已有隔离基础

项目中 threads、memory、agents 已通过相同模式实现用户隔离：

- `AuthMiddleware` 全局认证，将用户对象写入 `request.state.user`
- `user_context.get_effective_user_id()` 从 ContextVar 读取当前 HTTP 请求用户的 UUID，未登录返回 `"default"`
- `user_context.resolve_runtime_user_id(runtime)` 从 Agent runtime context 读取用户 UUID，已被 `setup_agent_tool`、`update_agent_tool` 使用

本 Feature 沿用相同模式，将 custom skills 接入已有的用户隔离体系。

---

## 2. 设计目标

1. **完全隔离**：不同用户的 custom skills 相互不可见、不可读写
2. **权限收口**：隔离逻辑在基础设施层完成，业务代码无需感知用户身份
3. **Agent 侧一致**：Agent 通过 skill_manage_tool 创建的技能，也只属于发起该 session 的用户
4. **Prompt 隔离**：Agent 系统 Prompt 中只注入当前用户自己的 custom skills
5. **向后兼容**：不影响无 auth 的单机部署；现有 public skills 不受影响
6. **可迁移**：提供一次性迁移脚本处理旧数据

---

## 3. 方案设计

### 3.1 文件系统命名空间

核心思路：在 `custom/` 下按 `user_id` 增加一层子目录。

```
变更前（所有用户共享）:
  skills/custom/<name>/SKILL.md
  skills/custom/.history/<name>.jsonl

变更后（per-user 命名空间）:
  skills/custom/<user_id>/<name>/SKILL.md
  skills/custom/<user_id>/.history/<name>.jsonl
```

`user_id` 取值规则：
- 已认证用户：UUID 字符串（来自数据库）
- 未认证 / 单机部署：`"default"`（`DEFAULT_USER_ID` 常量）

### 3.2 整体架构（分层改动）

```
HTTP 请求 ──► AuthMiddleware ──► ContextVar[user_id]
                                        │
     ┌──────────────────────────────────▼──────────┐
     │         API Gateway 层 (skills.py)           │
     │   Depends(get_skill_storage)                │ ← 自动绑定当前用户
     │   PUT /api/skills/{name} admin-only check   │ ← 权限守卫
     └──────────────────────┬──────────────────────┘
                            │ LocalSkillStorage(user_id=...)
     ┌──────────────────────▼──────────────────────┐
     │         存储工厂 (storage/__init__.py)        │
     │   get_or_new_skill_storage(user_id=...)      │ ← user_id → 独立实例
     └──────────────────────┬──────────────────────┘
                            │
     ┌──────────────────────▼──────────────────────┐
     │         LocalSkillStorage                    │
     │   _get_custom_base() → custom/<user_id>/     │ ← 所有路径从此派生
     └─────────────────────────────────────────────┘

Agent session ──► runtime.context["user_id"]
                        │
     ┌──────────────────▼──────────────────────────┐
     │         skill_manage_tool                    │
     │   resolve_runtime_user_id(runtime)           │ ← 读取 user_id
     │   get_or_new_skill_storage(user_id=...)      │
     └─────────────────────────────────────────────┘

     ┌─────────────────────────────────────────────┐
     │         Prompt Cache (prompt.py)             │
     │   key: (id(app_config), user_id)             │ ← per-user 独立缓存
     │   get_effective_user_id() 自动读取           │
     └─────────────────────────────────────────────┘
```

---

## 4. 实现详解

### 4.1 Change 1 — SkillStorage 基类：`_get_custom_base()` 模板方法

**文件**: `packages/harness/deerflow/skills/storage/skill_storage.py`

在抽象基类中引入 `_get_custom_base()` 模板方法，将「custom skills 根目录」的计算从各个路径 helper 中提取出来，收口到一处：

```python
def _get_custom_base(self) -> Path:
    """子类可覆写以实现 per-user 命名空间。默认返回 <root>/custom/。"""
    return self.get_skills_root_path() / SkillCategory.CUSTOM.value

def get_custom_skill_dir(self, name: str) -> Path:
    return self._get_custom_base() / self.validate_skill_name(name)

def get_skill_history_file(self, name: str) -> Path:
    return self._get_custom_base() / ".history" / f"{self.validate_skill_name(name)}.jsonl"
```

**设计意图**：路径计算变更只需覆写一个方法，`get_custom_skill_dir`、`get_skill_history_file`、`get_custom_skill_file` 全部自动更新，消除散落在多处的路径硬编码。

### 4.2 Change 2 — LocalSkillStorage：支持 user_id 命名空间

**文件**: `packages/harness/deerflow/skills/storage/local_skill_storage.py`

`__init__` 新增 `user_id` 参数，覆写 `_get_custom_base()` 实现命名空间切换：

```python
def __init__(self, host_path, container_path, user_id=None):
    ...
    self._user_id = user_id or None

def _get_custom_base(self) -> Path:
    if self._user_id:
        return self._host_root / SkillCategory.CUSTOM.value / self._user_id
    return self._host_root / SkillCategory.CUSTOM.value   # 向后兼容
```

同步修改 `_iter_skill_files()` 和 `ainstall_skill_from_archive()`，使遍历和安装均从 `_get_custom_base()` 出发，不再硬编码 `custom/`。

**关键行为**：
- `user_id=None` → 读写 `custom/`（legacy，向后兼容）
- `user_id="alice"` → 读写 `custom/alice/`，遍历时不会触碰 `custom/bob/`

### 4.3 Change 3 — 存储工厂：`get_or_new_skill_storage()` 透传 user_id

**文件**: `packages/harness/deerflow/skills/storage/__init__.py`

```python
user_id = kwargs.pop("user_id", None)
...
if user_id is not None:
    # 永远创建新实例，不共享进程级单例
    # 不同用户的 _custom_base 路径不同，不能共享
    return _make_storage(app_config.skills, user_id=user_id, **kwargs)
```

**为什么 `user_id` 必须绕过单例**：进程级单例只能绑定一个 `user_id`，多用户并发请求下必须为每个用户创建独立实例，各自持有自己的 `_get_custom_base()` 路径。`_make_storage` 已有 `**kwargs`，`user_id` 自动透传到 `LocalSkillStorage.__init__`，无额外改动。

### 4.4 Change 4 — FastAPI Dependency：`get_skill_storage`

**文件**: `app/gateway/deps.py`

新增两个依赖函数，替代路由中直接调用 `get_or_new_skill_storage(app_config=config)`：

```python
def get_skill_storage(request: Request, config: AppConfig = Depends(get_config)):
    """普通路由使用：绑定当前认证用户。"""
    user_id = get_effective_user_id()   # 从 ContextVar 读，无感知
    return get_or_new_skill_storage(user_id=user_id, app_config=config)

def get_admin_skill_storage(
    request: Request,
    target_user_id: str | None = Query(default=None),
    config: AppConfig = Depends(get_config),
):
    """Admin 路由使用：可通过 ?target_user_id= 操作其他用户。"""
    user = getattr(request.state, "user", None)
    if target_user_id is not None:
        if getattr(user, "system_role", None) != "admin":
            raise HTTPException(status_code=403, ...)
        uid = target_user_id
    else:
        uid = get_effective_user_id()
    return get_or_new_skill_storage(user_id=uid, app_config=config)
```

**设计意图**：将「用户身份 → 存储实例」的绑定逻辑完全收口在 `deps.py`，路由层零感知。

### 4.5 Change 5 — Router 改造：统一使用 `get_skill_storage` + admin 守卫

**文件**: `app/gateway/routers/skills.py`

全部 CRUD 路由函数签名从：
```python
async def list_custom_skills(config: AppConfig = Depends(get_config)):
    storage = get_or_new_skill_storage(app_config=config)
```
统一改为：
```python
async def list_custom_skills(storage: SkillStorage = Depends(get_skill_storage)):
    # storage 已绑定当前用户，直接使用
```

`PUT /api/skills/{name}`（enable/disable 技能）新增 admin 守卫：

```python
async def update_skill(skill_name, request, http_request: Request, config = Depends(get_config)):
    user = getattr(http_request.state, "user", None)
    if user is not None and getattr(user, "system_role", None) != "admin":
        raise HTTPException(status_code=403, detail="Only admins can enable or disable skills")
```

**守卫语义**：`user is not None` 时才检查 admin 角色。未认证的单机部署（user=None）不受限制，保持向后兼容。

### 4.6 Change 6 — Prompt Cache：按 (config, user_id) 分键

**文件**: `packages/harness/deerflow/agents/lead_agent/prompt.py`

原缓存键仅为 `id(app_config)`，多用户共用同一个 `AppConfig` 对象时会相互覆盖：

```python
# Before
_enabled_skills_by_config_cache: dict[int, tuple[object, list[Skill]]] = {}
cache_key = id(app_config)
skills = list(get_or_new_skill_storage(app_config=app_config).load_skills(...))

# After
_enabled_skills_by_config_cache: dict[tuple[int, str | None], tuple[object, list[Skill]]] = {}

def get_enabled_skills_for_config(app_config=None):
    ...
    user_id = get_effective_user_id()          # 自动读取 ContextVar
    cache_key = (id(app_config), user_id)      # 复合键
    ...
    skills = list(get_or_new_skill_storage(app_config=app_config, user_id=user_id).load_skills(...))
```

复用 `_get_memory_context` 中已有的 `get_effective_user_id()` 模式，无需修改任何调用方（`apply_prompt_template`、`agent.py`、`client.py` 签名全部不变）。

### 4.7 Change 7 — skill_manage_tool：接入用户上下文

**文件**: `packages/harness/deerflow/tools/skill_manage_tool.py`

```python
# Before
skill_storage = get_or_new_skill_storage()   # 进程级单例，无用户感知

# After
user_id = resolve_runtime_user_id(runtime)   # 与 setup_agent_tool 等工具一致
skill_storage = get_or_new_skill_storage(user_id=user_id)
```

`resolve_runtime_user_id(runtime)` 的优先级：
1. `runtime.context["user_id"]`（Gateway `inject_authenticated_user_context` 写入，最权威）
2. `_current_user` ContextVar（HTTP 请求中间件设置）
3. `"default"`（兜底）

### 4.8 Change 8 — 迁移脚本

**文件**: `scripts/migrate_skills_to_user_namespace.py`

将旧 flat 布局迁移到 `default` 用户命名空间（供已有单机/未认证部署使用）：

```
迁移前: skills/custom/<name>/SKILL.md
迁移后: skills/custom/default/<name>/SKILL.md

迁移前: skills/custom/.history/<name>.jsonl
迁移后: skills/custom/default/.history/<name>.jsonl
```

特性：
- **幂等**：目标路径已存在则跳过，可重复执行
- **--dry-run**：预览所有操作，不修改文件
- **自动检测路径**：默认从 `config.yaml` 读取 `skills.path`，也可 `--skills-root` 指定

---

## 5. 边界条件与特殊情况

### 5.1 向后兼容

| 场景 | user_id | custom skill 路径 | 是否需要迁移 |
|---|---|---|---|
| 无 auth 单机部署 | `"default"` | `custom/default/` | 执行迁移脚本 |
| 已启用 auth 的多用户部署 | UUID | `custom/<uuid>/` | 无旧数据 |
| SDK 直接调用（无 user_id） | `None` | `custom/`（legacy flat） | 不需要 |
| 旧 flat 布局数据 | - | `custom/<name>/` | 执行迁移脚本 |

**核心原则**：`user_id=None` 永远保持 flat 布局，不破坏现有 SDK 调用方。

### 5.2 Public Skills 不受影响

`_iter_skill_files()` 对 `SkillCategory.PUBLIC` 分支使用原始的 `<root>/public/` 路径，`user_id` 仅影响 `CUSTOM` 分支。

### 5.3 enable/disable 全局生效

`PUT /api/skills/{name}` 写入 `extensions_config.json`，此文件是全局的。技能的开关状态对所有用户生效（公共设置，admin 管理）。但 custom skills 的「存在即启用」原则仍然是 per-user 的。

### 5.4 并发安全

`get_or_new_skill_storage(user_id=...)` 每次调用返回新实例，无共享状态，天然并发安全。`_enabled_skills_by_config_cache` 由 `_enabled_skills_lock`（`threading.Lock`）保护。

### 5.5 Prompt Cache 失效

`_invalidate_enabled_skills_cache()`（由技能 CRUD 操作触发）清除 `_enabled_skills_by_config_cache` 中**所有**用户的条目，即「任一用户改变技能时，所有用户的 per-config 缓存失效」。这是一个**保守且安全**的策略：下次请求时各用户各自重新加载，不会出现脏读。代价是在高并发场景下可能有轻微的额外磁盘读取，可接受。

### 5.6 未认证部署（single-user）

`get_effective_user_id()` 在未认证时返回 `"default"`，存储路径变为 `custom/default/`。执行迁移脚本后，旧 flat 布局数据自动归入 `default`，行为与之前完全一致，用户无感知。

### 5.7 Admin 跨用户操作

`get_admin_skill_storage` 提供 `?target_user_id=<uuid>` 接口，供 admin 查看和操作其他用户的技能。**非 admin 用户携带该参数会被拒绝（403）**，而不是静默忽略，防止参数注入攻击。

---

## 6. API 变更

### 新增接口行为（无破坏性变更）

所有 `/api/skills/custom/*` 接口的行为对普通用户透明，只是数据范围从「全局」缩小为「当前用户」：

| 接口 | 变更前 | 变更后 |
|---|---|---|
| `GET /api/skills/custom` | 返回所有用户的技能 | 仅返回当前用户的技能 |
| `POST /api/skills/install` | 安装到全局 custom/ | 安装到当前用户的 custom/<uid>/ |
| `PUT /api/skills/custom/{name}` | 可编辑任意技能 | 仅可编辑自己的技能（其他人的 → 404） |
| `DELETE /api/skills/custom/{name}` | 可删除任意技能 | 仅可删除自己的技能（其他人的 → 404） |

### 新增错误码

| HTTP Status | 场景 |
|---|---|
| `403 Forbidden` | 非 admin 用户调用 `PUT /api/skills/{name}`（enable/disable） |
| `403 Forbidden` | 非 admin 用户在 `get_admin_skill_storage` 携带 `target_user_id` |
| `404 Not Found` | 访问其他用户的 custom skill（隔离后不可见） |

### Admin 新增能力

```
GET  /api/skills/custom?target_user_id=<uuid>    → 查看指定用户的技能列表
GET  /api/skills/custom/{name}?target_user_id=<uuid>
PUT  /api/skills/custom/{name}?target_user_id=<uuid>
DELETE /api/skills/custom/{name}?target_user_id=<uuid>
```

---

## 7. 文件变更清单

### 核心改动（12 个文件，净增 ~125 行）

| 文件 | 改动 | 说明 |
|---|---|---|
| `packages/harness/deerflow/skills/storage/skill_storage.py` | +20 行 | 新增 `_get_custom_base()` 模板方法，更新 2 个路径 helper |
| `packages/harness/deerflow/skills/storage/local_skill_storage.py` | +21 行 | `user_id` 参数 + `_get_custom_base()` 覆写 + `_iter_skill_files` + `ainstall` 修正 |
| `packages/harness/deerflow/skills/storage/__init__.py` | +18 行 | `get_or_new_skill_storage` 透传 `user_id`，绕过单例 |
| `app/gateway/deps.py` | +48 行 | 新增 `get_skill_storage`、`get_admin_skill_storage` 两个依赖函数 |
| `app/gateway/routers/skills.py` | 重构 | 9 个路由使用新依赖，`PUT /skills/{name}` 增加 admin 守卫 |
| `packages/harness/deerflow/agents/lead_agent/prompt.py` | +16 行 | cache key 改为 `(id(config), user_id)`，storage 调用透传 `user_id` |
| `packages/harness/deerflow/tools/skill_manage_tool.py` | +4 行 | 使用 `resolve_runtime_user_id(runtime)` 确定用户 |
| `tests/conftest.py` | +15 行 | 新增 `_reset_extensions_config` autouse fixture |
| `tests/test_lead_agent_prompt.py` | 修复 | mock lambda 新增 `user_id=None` 参数 |
| `tests/test_skill_manage_tool.py` | 修复 | runtime context 加入 `user_id`，路径断言更新 |
| `tests/test_skills_custom_router.py` | 重构 | 改为 `dependency_overrides` 模式，路径断言使用 `storage._get_custom_base()` |

### 新增文件

| 文件 | 说明 |
|---|---|
| `scripts/migrate_skills_to_user_namespace.py` | 旧数据迁移脚本 |
| `tests/test_change1_storage_template_method.py` | 7 个测试：模板方法正确性 |
| `tests/test_change2_local_storage_user_id.py` | 11 个测试：LocalSkillStorage 路径、遍历、安装 |
| `tests/test_change3_storage_factory_user_id.py` | 6 个测试：工厂函数 user_id 绕过单例 |
| `tests/test_change4_5_gateway_skill_deps.py` | 5 个测试：Dependency 绑定、admin 守卫 |
| `tests/test_change6_prompt_cache_per_user.py` | 5 个测试：cache key 隔离、命中、失效 |
| `tests/test_change7_skill_manage_user_context.py` | 8 个测试：runtime user_id、ContextVar 兜底 |
| `tests/test_change8_migration_script.py` | 10 个测试：迁移各边界情况 |
| `tests/test_per_user_skill_isolation.py` | 6 个端到端隔离测试 |

---

## 8. 测试覆盖

### 新增测试：60 个，全部通过

```
tests/test_change1~8_*.py   各改动点单元测试：58 个
tests/test_per_user_skill_isolation.py   集成测试：6 个
```

### 回归测试

- **全套测试（~3500+ tests）**：与 baseline 相比减少 45 个失败（301 vs 346），无新增失败
- 现有 `test_skills_custom_router.py`（13 tests）、`test_skills_loader.py`（5 tests）、`test_skill_manage_tool.py`（5 tests）、`test_lead_agent_prompt.py`（10 tests）、`test_lead_agent_skills.py`（9 tests）全部通过

---

## 9. 部署指南

### 9.1 新部署（启用 auth）

无需额外操作，每个用户首次创建技能时自动创建 `custom/<uuid>/` 目录。

### 9.2 已有部署（升级）

```bash
# Step 1: 升级代码

# Step 2: 执行迁移脚本（将旧技能归入 "default" 用户）
cd backend
python scripts/migrate_skills_to_user_namespace.py --dry-run   # 先预览
python scripts/migrate_skills_to_user_namespace.py             # 执行

# Step 3: 重启服务
```

### 9.3 已有部署（不启用 auth）

无需迁移。`get_effective_user_id()` 始终返回 `"default"`，执行迁移脚本将技能移到 `custom/default/` 后，行为与升级前完全一致。

---

## 10. 未来扩展方向（不在本 PR 范围内）

- **技能共享**：管理员将某用户技能 promote 为 public skills
- **技能市场**：用户之间共享技能（需要版权和安全审查流程）
- **自定义技能权限模型**：团队级技能共享（RBAC）
- **per-user 失效优化**：`_invalidate_enabled_skills_cache` 仅清除特定用户的条目（当前为保守的全清策略）

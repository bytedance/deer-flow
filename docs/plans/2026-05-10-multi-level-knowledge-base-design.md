# 多级知识库设计方案（个人 / 公司 / 公共）

> **For Codex/Claude:** 实施时建议按 Phase 顺序推进，每个 Phase 独立可交付，避免一次性大改。

**Goal:** 将当前仅支持"个人私有"的知识库体系扩展为三级可见性模型（个人知识库、公司知识库、公共知识库），在不破坏现有数据和接口的前提下，实现跨用户、跨租户的知识共享与权限隔离。

**Architecture:** 复用现有 `visibility` 字段和 `tenant_id` + `owner_user_id` 隔离机制，在应用层引入分级访问控制，向量存储层保持不变。

**Tech Stack:** SQLAlchemy Async、Alembic、FastAPI、现有 pgvector/Chroma 向量存储。

---

## 1. 背景与问题定义

### 1.1 现状

当前知识库系统的访问模型：

- 每个知识库绑定 `tenant_id` + `owner_user_id`
- 所有查询严格按双字段过滤，用户只能看到自己创建的知识库
- `visibility` 字段已存在于 `knowledge_bases` 表（默认 `"private"`），但未参与任何访问控制逻辑
- 向量存储中每个 KB 有独立 collection（`kb_{uuid}`），天然隔离

### 1.2 需求

企业场景下，知识库需要支持多级共享：

| 级别 | 场景 |
|------|------|
| 个人知识库 | 用户私有笔记、个人资料，仅自己可见 |
| 公司知识库 | 部门文档、内部规范、产品手册，同租户所有人可搜索 |
| 公共知识库 | 平台通用知识（法规、行业标准），所有租户可搜索 |

### 1.3 设计约束

1. 向后兼容：现有 `private` 知识库行为不变
2. 向量存储层不改动：权限控制完全在应用层
3. 读写权限分离：可搜索 ≠ 可编辑
4. 最小侵入：尽量复用现有字段和接口

---

## 2. 数据模型设计

### 2.1 visibility 字段语义升级

`knowledge_bases.visibility` 从占位符升级为核心访问控制维度：

```
visibility ∈ {"private", "tenant", "public"}
```

| 值 | 含义 | 创建者要求 | 读取范围 | 写入范围 |
|----|------|-----------|---------|---------|
| `private` | 个人知识库 | 任何已认证用户 | owner_user_id 本人 | owner 本人 |
| `tenant` | 公司知识库 | tenant_admin 或被授权用户 | 同 tenant_id 下所有用户 | admin + 被授权 editor |
| `public` | 公共知识库 | platform_admin | 所有租户所有用户 | platform_admin |

### 2.2 新增权限表 kb_permissions

用于公司知识库的细粒度写权限控制：

```python
class KbPermissionRow(Base):
    __tablename__ = "kb_permissions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # role ∈ {"viewer", "editor", "admin"}
    # viewer: 显式授权查看（用于跨租户特殊场景）
    # editor: 可上传/编辑文档
    # admin: 可编辑 KB 元信息、管理权限、删除 KB
    granted_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
```

**约束**：`(knowledge_base_id, user_id)` 唯一索引，防止重复授权。

### 2.3 用户角色扩展

在现有用户体系中增加角色概念：

```
user.role ∈ {"user", "tenant_admin", "platform_admin"}
```

- `user`：普通用户，可创建 private KB
- `tenant_admin`：租户管理员，可创建 tenant KB，管理本租户所有 KB
- `platform_admin`：平台管理员，可创建 public KB，管理所有 KB

---

## 3. 访问控制规则

### 3.1 读取权限（搜索/查看）

```
CAN_READ(user, kb) =
    (kb.visibility == "private" AND kb.owner_user_id == user.id AND kb.tenant_id == user.tenant_id)
    OR (kb.visibility == "tenant" AND kb.tenant_id == user.tenant_id)
    OR (kb.visibility == "public")
```

### 3.2 写入权限（上传文档/编辑文档）

```
CAN_WRITE(user, kb) =
    (kb.visibility == "private" AND kb.owner_user_id == user.id)
    OR (kb.visibility == "tenant" AND (
        user.role == "tenant_admin"
        OR EXISTS kb_permissions WHERE kb_id=kb.id AND user_id=user.id AND role IN ("editor", "admin")
    ))
    OR (kb.visibility == "public" AND user.role == "platform_admin")
```

### 3.3 管理权限（删除 KB/修改元信息/管理权限）

```
CAN_ADMIN(user, kb) =
    (kb.visibility == "private" AND kb.owner_user_id == user.id)
    OR (kb.visibility == "tenant" AND (
        user.role == "tenant_admin"
        OR kb.owner_user_id == user.id
        OR EXISTS kb_permissions WHERE kb_id=kb.id AND user_id=user.id AND role == "admin"
    ))
    OR (kb.visibility == "public" AND user.role == "platform_admin")
```

### 3.4 创建权限

```
CAN_CREATE(user, visibility) =
    (visibility == "private")  -- 所有已认证用户
    OR (visibility == "tenant" AND user.role IN ("tenant_admin", "platform_admin"))
    OR (visibility == "public" AND user.role == "platform_admin")
```

---

## 4. Repository 层改造

### 4.1 新增 `list_accessible` 方法

替代现有 `list_by_owner`，返回用户可访问的所有知识库：

```python
from sqlalchemy import or_, and_

async def list_accessible(
    self,
    *,
    tenant_id: str,
    user_id: str,
    visibility_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    async with self._sf() as session:
        access_conditions = or_(
            and_(
                KnowledgeBaseRow.visibility == "private",
                KnowledgeBaseRow.owner_user_id == user_id,
                KnowledgeBaseRow.tenant_id == tenant_id,
            ),
            and_(
                KnowledgeBaseRow.visibility == "tenant",
                KnowledgeBaseRow.tenant_id == tenant_id,
            ),
            KnowledgeBaseRow.visibility == "public",
        )

        conditions = [
            KnowledgeBaseRow.deleted_at.is_(None),
            KnowledgeBaseRow.status == "active",
            access_conditions,
        ]

        if visibility_filter:
            conditions.append(KnowledgeBaseRow.visibility == visibility_filter)

        stmt = (
            select(KnowledgeBaseRow)
            .where(*conditions)
            .order_by(KnowledgeBaseRow.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return [self._row_to_dict(r) for r in result.scalars()]
```

### 4.2 新增 `resolve_accessible_by_ids` 方法

替代现有 `resolve_active_by_ids`，用于 RAG Middleware 校验用户是否有权搜索指定 KB：

```python
async def resolve_accessible_by_ids(
    self,
    kb_ids: list[str],
    *,
    tenant_id: str,
    user_id: str,
) -> list[dict[str, Any]]:
    if not kb_ids:
        return []
    async with self._sf() as session:
        access_conditions = or_(
            and_(
                KnowledgeBaseRow.visibility == "private",
                KnowledgeBaseRow.owner_user_id == user_id,
                KnowledgeBaseRow.tenant_id == tenant_id,
            ),
            and_(
                KnowledgeBaseRow.visibility == "tenant",
                KnowledgeBaseRow.tenant_id == tenant_id,
            ),
            KnowledgeBaseRow.visibility == "public",
        )
        stmt = (
            select(KnowledgeBaseRow)
            .where(
                KnowledgeBaseRow.id.in_(kb_ids),
                KnowledgeBaseRow.status == "active",
                KnowledgeBaseRow.deleted_at.is_(None),
                access_conditions,
            )
        )
        result = await session.execute(stmt)
        return [self._row_to_dict(r) for r in result.scalars()]
```

### 4.3 新增 `KbPermissionRepository`

```python
class KbPermissionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def grant(
        self, *, kb_id: str, tenant_id: str, user_id: str, role: str, granted_by: str
    ) -> dict[str, Any]:
        ...

    async def revoke(self, *, kb_id: str, user_id: str) -> bool:
        ...

    async def list_by_kb(self, kb_id: str) -> list[dict[str, Any]]:
        ...

    async def get_user_role(self, *, kb_id: str, user_id: str) -> str | None:
        ...

    async def has_write_access(self, *, kb_id: str, user_id: str) -> bool:
        role = await self.get_user_role(kb_id=kb_id, user_id=user_id)
        return role in ("editor", "admin")
```

---

## 5. Service 层改造

### 5.1 权限检查服务

新增 `KbAccessControl` 类，集中管理权限判断逻辑：

```python
class KbAccessControl:
    def __init__(
        self,
        kb_repo: KnowledgeBaseRepository,
        perm_repo: KbPermissionRepository,
    ) -> None:
        self._kb_repo = kb_repo
        self._perm_repo = perm_repo

    async def check_read(self, user: UserContext, kb: dict) -> bool:
        if kb["visibility"] == "private":
            return kb["owner_user_id"] == user.id and kb["tenant_id"] == user.tenant_id
        if kb["visibility"] == "tenant":
            return kb["tenant_id"] == user.tenant_id
        if kb["visibility"] == "public":
            return True
        return False

    async def check_write(self, user: UserContext, kb: dict) -> bool:
        if kb["visibility"] == "private":
            return kb["owner_user_id"] == user.id
        if kb["visibility"] == "tenant":
            if user.role == "tenant_admin":
                return True
            return await self._perm_repo.has_write_access(kb_id=kb["id"], user_id=user.id)
        if kb["visibility"] == "public":
            return user.role == "platform_admin"
        return False

    async def check_admin(self, user: UserContext, kb: dict) -> bool:
        if kb["visibility"] == "private":
            return kb["owner_user_id"] == user.id
        if kb["visibility"] == "tenant":
            if user.role == "tenant_admin" or kb["owner_user_id"] == user.id:
                return True
            role = await self._perm_repo.get_user_role(kb_id=kb["id"], user_id=user.id)
            return role == "admin"
        if kb["visibility"] == "public":
            return user.role == "platform_admin"
        return False

    def check_create(self, user: UserContext, visibility: str) -> bool:
        if visibility == "private":
            return True
        if visibility == "tenant":
            return user.role in ("tenant_admin", "platform_admin")
        if visibility == "public":
            return user.role == "platform_admin"
        return False
```

### 5.2 KnowledgeBaseService 改造

```python
async def create_knowledge_base(
    self,
    *,
    tenant_id: str,
    owner_user_id: str,
    name: str,
    description: str | None = None,
    visibility: str = "private",
) -> dict[str, Any]:
    return await self._kb_repo.create(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        name=name,
        description=description,
        visibility=visibility,
    )

async def list_knowledge_bases(
    self,
    *,
    tenant_id: str,
    user_id: str,
    visibility_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return await self._kb_repo.list_accessible(
        tenant_id=tenant_id,
        user_id=user_id,
        visibility_filter=visibility_filter,
        limit=limit,
        offset=offset,
    )
```

---

## 6. API 层改造

### 6.1 现有接口变更

**`GET /api/knowledge-bases`**

新增查询参数：
- `visibility`: 可选，筛选特定级别（`private` / `tenant` / `public`）

返回结果包含所有用户可访问的 KB（不再仅限自己创建的）。

**`POST /api/knowledge-bases`**

请求体新增：
- `visibility`: 可选，默认 `"private"`

服务端校验创建权限。

**`PATCH /api/knowledge-bases/{kb_id}`**

- 不允许修改 `visibility`（防止权限升级攻击）
- 如需变更 visibility，应删除后重建

**文档操作接口**（`POST/PATCH/DELETE .../documents`）

- 增加写权限校验：调用 `KbAccessControl.check_write`

### 6.2 新增权限管理接口

```
POST   /api/knowledge-bases/{kb_id}/permissions      -- 授权
DELETE /api/knowledge-bases/{kb_id}/permissions/{uid} -- 撤销
GET    /api/knowledge-bases/{kb_id}/permissions       -- 列出权限
```

仅 KB admin 可操作。

### 6.3 接口响应扩展

KB 对象增加字段：

```json
{
  "id": "...",
  "name": "...",
  "visibility": "tenant",
  "my_role": "editor",
  "can_write": true,
  "can_admin": false,
  "owner_user_id": "...",
  "owner_display_name": "张三"
}
```

---

## 7. RAG Middleware 改造

### 7.1 搜索权限校验

`rag_middleware.py` 中的 KB 解析逻辑改为使用 `resolve_accessible_by_ids`：

```python
# 之前：严格按 tenant_id + owner_user_id 过滤
resolved = await kb_repo.resolve_active_by_ids(kb_ids, tenant_id=tid, owner_user_id=uid)

# 之后：按可见性规则过滤（用户可搜索 private+tenant+public）
resolved = await kb_repo.resolve_accessible_by_ids(kb_ids, tenant_id=tid, user_id=uid)
```

### 7.2 search_knowledge_base tool

同样改为使用 `resolve_accessible_by_ids` 校验，确保 agent 调用搜索工具时也遵循可见性规则。

---

## 8. 前端改造

### 8.1 KB Gallery 页面

增加 Tab 分类视图：

```
+-----------------------------------------------------+
|  [全部]  [我的知识库]  [公司知识库]  [公共知识库]       |
+-----------------------------------------------------+
|                                                     |
|  +----------+  +----------+  +----------+          |
|  | KB Card  |  | KB Card  |  | KB Card  |          |
|  | [私有]   |  | [公司]   |  | [公共]   |          |
|  +----------+  +----------+  +----------+          |
|                                                     |
+-----------------------------------------------------+
```

- 每个 KB Card 显示 visibility 标签
- 根据 `can_write` / `can_admin` 控制操作按钮显示
- 公司/公共 KB 显示创建者名称

### 8.2 创建 KB 对话框

- 增加 visibility 选择器（下拉或 Radio）
- 根据用户角色禁用不可选的选项
- 选择 `tenant` 或 `public` 时显示提示："此知识库将对[同公司所有人/所有用户]可见"

### 8.3 KB Selector（会话中选择知识库）

- 按 visibility 分组展示可选 KB
- 标注来源：`[我的]`、`[公司]`、`[公共]`
- 搜索时可跨级别搜索

### 8.4 权限管理面板

公司 KB 详情页增加"权限管理"Tab：
- 列出已授权用户及角色
- 支持添加/移除/变更角色
- 仅 admin 角色可见此 Tab

---

## 9. 数据迁移

### 9.1 Alembic 迁移脚本

```python
def upgrade():
    # 1. 创建 kb_permissions 表
    op.create_table(
        "kb_permissions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("knowledge_base_id", sa.String(64), nullable=False, index=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("granted_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint(
        "uq_kb_permissions_kb_user",
        "kb_permissions",
        ["knowledge_base_id", "user_id"],
    )

    # 2. 为 knowledge_bases 表添加复合索引优化查询性能
    op.create_index(
        "ix_knowledge_bases_visibility_tenant",
        "knowledge_bases",
        ["visibility", "tenant_id"],
    )

    # 3. 现有数据全部为 private，无需数据迁移

def downgrade():
    op.drop_index("ix_knowledge_bases_visibility_tenant", "knowledge_bases")
    op.drop_table("kb_permissions")
```

### 9.2 数据兼容性

- 现有所有 KB 的 `visibility` 已经是 `"private"`，无需数据迁移
- 新的 `list_accessible` 方法对 `private` KB 的行为与旧 `list_by_owner` 完全一致
- 旧 API 调用方（不传 visibility 参数）默认行为不变

---

## 10. 安全考量

### 10.1 防止权限升级

- `visibility` 字段创建后不可修改（PATCH 接口忽略此字段）
- 权限变更操作需要 admin 角色
- 所有写操作在 service 层统一校验权限

### 10.2 防止数据泄露

- 搜索结果不返回文档全文，仅返回 chunk 片段
- 公司 KB 的文档内容仅对同租户用户可见
- API 响应中不暴露其他租户的 tenant_id

### 10.3 审计日志

建议后续增加操作审计：
- 谁创建了公司/公共 KB
- 谁被授予了什么权限
- 谁上传/删除了文档

---

## 11. 实施计划

### Phase 1：核心访问控制（预计 3-5 天）

**目标**：激活 visibility 字段，实现三级读取权限

- [ ] 新增 `list_accessible` 和 `resolve_accessible_by_ids` 方法
- [ ] 改造 `KnowledgeBaseService.list_knowledge_bases` 使用新方法
- [ ] 改造 RAG Middleware 使用 `resolve_accessible_by_ids`
- [ ] 改造 `search_knowledge_base` tool 的权限校验
- [ ] API 层 `GET /api/knowledge-bases` 增加 `visibility` 筛选参数
- [ ] API 层 `POST /api/knowledge-bases` 支持 `visibility` 参数
- [ ] 单元测试覆盖三级可见性场景

### Phase 2：前端分类展示（预计 2-3 天）

**目标**：用户可以看到并区分三级知识库

- [ ] KB Gallery 增加 Tab 分类
- [ ] KB Card 显示 visibility 标签和创建者
- [ ] 创建对话框增加 visibility 选择
- [ ] KB Selector 按级别分组
- [ ] 根据权限控制操作按钮

### Phase 3：写权限与权限管理（预计 3-4 天）

**目标**：公司 KB 支持细粒度写权限

- [ ] 创建 `kb_permissions` 表（Alembic 迁移）
- [ ] 实现 `KbPermissionRepository`
- [ ] 实现 `KbAccessControl` 服务
- [ ] 文档操作接口增加写权限校验
- [ ] 新增权限管理 API（`/permissions`）
- [ ] 前端权限管理面板
- [ ] 集成测试覆盖权限场景

### Phase 4：管理后台（预计 2-3 天）

**目标**：管理员可管理公司/公共知识库

- [ ] 租户管理员视图：管理本租户所有 tenant KB
- [ ] 平台管理员视图：管理所有 public KB
- [ ] 批量授权/撤销功能
- [ ] 操作审计日志

---

## 12. 测试策略

### 12.1 单元测试

```python
class TestKbAccessControl:
    async def test_private_kb_only_visible_to_owner(self): ...
    async def test_tenant_kb_visible_to_same_tenant(self): ...
    async def test_tenant_kb_invisible_to_other_tenant(self): ...
    async def test_public_kb_visible_to_all(self): ...
    async def test_private_kb_write_only_by_owner(self): ...
    async def test_tenant_kb_write_by_admin(self): ...
    async def test_tenant_kb_write_by_editor(self): ...
    async def test_tenant_kb_no_write_by_viewer(self): ...
    async def test_public_kb_write_only_by_platform_admin(self): ...
    async def test_create_tenant_kb_requires_admin_role(self): ...
    async def test_create_public_kb_requires_platform_admin(self): ...
    async def test_visibility_cannot_be_changed_after_creation(self): ...
```

### 12.2 集成测试

- 多用户场景：用户 A 创建 tenant KB，用户 B（同租户）可搜索但不可编辑
- 跨租户隔离：租户 X 的 tenant KB 对租户 Y 不可见
- RAG 搜索：会话中选择公司 KB 后，搜索结果正确返回
- 权限变更：授予 editor 后可上传文档，撤销后不可

### 12.3 覆盖率目标

- 访问控制逻辑：100% 分支覆盖
- Repository 新方法：>= 90%
- API 端点：>= 80%

---

## 13. 与现有设计的关系

本方案是对 `docs/plans/用户可编辑知识库与会话可选引用设计_完善版.md` 的扩展：

- 原设计明确将"tenant 级共享知识库"列为"本期非目标"
- 本方案在原设计已实现的基础上，补充多级可见性能力
- 不改变原设计的核心架构（文档实体、索引任务、会话选择机制）
- 仅扩展访问控制维度

---

## 14. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 查询性能下降（OR 条件增多） | 列表接口变慢 | 添加 `(visibility, tenant_id)` 复合索引 |
| 权限逻辑分散 | 安全漏洞 | 集中到 `KbAccessControl`，所有入口统一调用 |
| 前端状态复杂度增加 | 开发周期延长 | Phase 2 先做只读展示，Phase 3 再加写操作 |
| 用户角色体系不完善 | 无法区分管理员 | Phase 1 可先用 config 配置 admin 用户列表，后续接入完整 RBAC |
| no-auth 模式兼容 | 开发环境异常 | no-auth 模式下所有 KB 视为 private + 当前用户可见 |

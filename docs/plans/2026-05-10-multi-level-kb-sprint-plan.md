# 多级知识库实施 Sprint 计划

> **关联设计文档**: `docs/plans/2026-05-10-multi-level-knowledge-base-design.md`
> **创建日期**: 2026-05-10

---

## Sprint 概览

| 属性 | 值 |
|------|-----|
| Sprint Goal | 实现三级知识库可见性模型，支持个人/公司/公共知识库的访问控制与前端展示 |
| Duration | 3 Sprints x 2 周 = 6 周 |
| 总估算 | 约 66-75 Story Points |
| 涉及模块 | persistence, service, API router, RAG middleware, frontend |

---

## Sprint 1：核心访问控制（Week 1-2）

**Sprint Goal**: 激活 visibility 字段，实现三级读取权限，后端可正确返回用户可访问的所有知识库。

**容量**: ~27 Story Points

### Stories

| # | Story | Points | 优先级 | 依赖 | 涉及文件 |
|---|-------|--------|--------|------|----------|
| 1.1 | Repository: 新增 list_accessible 方法 | 3 | P0 | 无 | persistence/knowledge_base/repository.py |
| 1.2 | Repository: 新增 resolve_accessible_by_ids 和 resolve_accessible_by_collections 方法 | 4 | P0 | 无 | persistence/knowledge_base/repository.py |
| 1.3 | Repository: create 方法支持 visibility 参数 | 2 | P0 | 无 | persistence/knowledge_base/repository.py |
| 1.4 | Repository: 新增 get_accessible 方法（支持可见性访问） | 2 | P0 | 无 | persistence/knowledge_base/repository.py |
| 1.5 | Service: 改造 list_knowledge_bases 使用 list_accessible | 2 | P0 | 1.1 | knowledge_base/service.py |
| 1.6 | Service: 改造 create_knowledge_base 支持 visibility | 1 | P0 | 1.3 | knowledge_base/service.py |
| 1.7 | Service: 改造 get_knowledge_base 使用 get_accessible | 1 | P0 | 1.4 | knowledge_base/service.py |
| 1.8 | RAG Middleware + Tools: 搜索权限校验改用 resolve_accessible_by_ids 和 resolve_accessible_by_collections | 3 | P0 | 1.2 | rag/tools.py, agents/middlewares/rag_middleware.py |
| 1.9 | API: GET /api/knowledge-bases 增加 visibility 筛选参数 | 2 | P0 | 1.5 | routers/knowledge_bases.py, routers/knowledge_base_schemas.py |
| 1.10 | API: POST /api/knowledge-bases 支持 visibility 参数 | 2 | P0 | 1.6 | routers/knowledge_bases.py, routers/knowledge_base_schemas.py |
| 1.11 | API+Repository: PATCH 接口禁止修改 visibility，同时从 Repository.update() 的 allowed fields 中移除 visibility | 2 | P0 | 无 | routers/knowledge_bases.py, persistence/knowledge_base/repository.py |
| 1.12 | 单元测试: 三级可见性读取场景覆盖 | 3 | P0 | 1.1-1.10 | tests/test_kb_visibility.py |

### 验收标准

- [ ] private KB 仅 owner 可见（行为与改造前一致）
- [ ] tenant KB 同租户所有用户可见，跨租户不可见
- [ ] public KB 所有用户可见
- [ ] 创建 KB 时可指定 visibility，默认 private
- [ ] 单个 KB 的 get 接口遵循可见性规则（非 owner 可访问 tenant/public KB）
- [ ] RAG 搜索工具遵循可见性规则
- [ ] no-auth 模式下行为正常（所有 KB 视为 private + 当前用户可见）
- [ ] PATCH 接口无法修改 visibility，Repository.update() 不再允许 visibility 字段
- [ ] 现有 private KB 行为完全不变（向后兼容）
- [ ] 单元测试覆盖率 >= 90%

### 技术注意事项

- list_accessible 使用 OR 条件，需确认 (visibility, tenant_id) 复合索引已存在或在本 Sprint 添加
- `resolve_active_by_collections` 按 collection_name 解析 KB，同样需改为基于可见性的 `resolve_accessible_by_collections`（rag/tools.py `_search_single_collection` 路径）
- rag_middleware.py 中 `_retrieve_from_selected_kbs` 也调用 `resolve_active_by_ids`，需同步替换
- no-auth 模式下所有 KB 视为 private + 当前用户可见，保持兼容（RAG tools 中 `allow_no_auth_kb` 配置需保留）
- 不改动向量存储层，权限控制完全在应用层
- 代码中用户角色字段为 `system_role`，值为 `superadmin`（对应设计文档中的 `platform_admin`）、`tenant_admin`、`user`
- Repository.update() 当前 allowed fields 包含 visibility，需在 Story 1.11 中移除

---

## Sprint 2：前端分类展示 + 写权限基础（Week 3-4）

**Sprint Goal**: 用户可在前端看到并区分三级知识库；公司 KB 支持基本的写权限控制。

**容量**: ~28 Story Points

### Stories

| # | Story | Points | 优先级 | 依赖 | 涉及文件 |
|---|-------|--------|--------|------|----------|
| 2.1 | DB Migration: 创建 kb_permissions 表 + (visibility, tenant_id) 复合索引 | 3 | P0 | 无 | migrations/versions/, persistence/knowledge_base/model.py |
| 2.2 | Repository: 实现 KbPermissionRepository | 3 | P0 | 2.1 | 新建 persistence/knowledge_base/permission_repository.py |
| 2.3 | Service: 实现 KbAccessControl 权限检查服务 | 3 | P0 | 2.2 | 新建 knowledge_base/access_control.py |
| 2.4 | Repository: DocumentRepository 改造支持非 owner 写操作 | 3 | P0 | 2.3 | persistence/knowledge_base/document_repository.py |
| 2.5 | API: 文档操作接口增加写权限校验 | 3 | P0 | 2.3, 2.4 | routers/knowledge_bases.py |
| 2.6 | API: KB 响应增加 my_role, can_write, can_admin 字段 | 2 | P0 | 2.3 | routers/knowledge_bases.py, routers/knowledge_base_schemas.py |
| 2.7 | Frontend: KB Gallery 增加 Tab 分类视图 | 3 | P1 | 2.6 | kb-gallery.tsx |
| 2.8 | Frontend: KB Card 显示 visibility 标签和创建者 | 2 | P1 | 2.6 | kb-card.tsx |
| 2.9 | Frontend: 创建对话框增加 visibility 选择 | 2 | P1 | 2.6 | kb-form-dialog.tsx |
| 2.10 | Frontend: KB Selector 按级别分组展示 | 2 | P1 | 2.6 | knowledge-base-selector.tsx |
| 2.11 | 集成测试: 写权限场景覆盖 | 2 | P0 | 2.3-2.5 | tests/test_kb_permissions.py |

### 验收标准

- [ ] kb_permissions 表通过 Alembic 迁移创建成功
- [ ] (visibility, tenant_id) 复合索引创建成功
- [ ] tenant_admin 可写 tenant KB，普通用户不可写
- [ ] superadmin 可写 public KB
- [ ] DocumentRepository 支持非 owner 用户对 tenant/public KB 的文档操作
- [ ] 前端 Gallery 页面按 Tab 分类展示（全部/我的/公司/公共）
- [ ] KB Card 显示 visibility 标签（私有/公司/公共）
- [ ] 创建 KB 时可选择 visibility，非管理员无法选择 tenant/public
- [ ] 文档上传/编辑/删除操作正确校验写权限
- [ ] 操作按钮根据权限显示/隐藏

### 技术注意事项

- kb_permissions 表需要 (knowledge_base_id, user_id) 唯一索引
- 前端需要根据用户角色动态禁用 visibility 选项
- Phase 1 可先用 config 配置 admin 用户列表，暂不接入完整 RBAC
- DocumentRepository 当前所有方法按 owner_user_id 过滤，需新增不按 owner 过滤的变体方法（如 `get_by_kb_accessible`、`list_by_kb_accessible`），供 KbAccessControl 校验通过后调用
- 代码中角色判断使用 `user.system_role == "superadmin"`（对应设计文档 platform_admin）、`user.system_role == "tenant_admin"`

---

## Sprint 3：权限管理 + 管理后台（Week 5-6）

**Sprint Goal**: 公司 KB 支持细粒度权限管理，管理员可管理所有 KB。

**容量**: ~20 Story Points

### Stories

| # | Story | Points | 优先级 | 依赖 | 涉及文件 |
|---|-------|--------|--------|------|----------|
| 3.1 | API: 新增权限管理接口 (/permissions CRUD) | 3 | P0 | Sprint 2 | routers/knowledge_bases.py |
| 3.2 | Service: 权限授予/撤销/查询逻辑 | 2 | P0 | Sprint 2 | knowledge_base/access_control.py |
| 3.3 | Frontend: 权限管理面板（列出/添加/移除用户权限） | 5 | P1 | 3.1 | 新建 kb-permissions-dialog.tsx |
| 3.4 | Frontend: 根据权限控制操作按钮显示 | 2 | P1 | Sprint 2 | kb-card.tsx, kb-documents-dialog.tsx |
| 3.5 | API: 管理员视图接口（列出所有 tenant/public KB） | 2 | P1 | Sprint 2 | routers/knowledge_bases.py |
| 3.6 | Frontend: 管理员 KB 管理视图 | 3 | P2 | 3.5 | kb-gallery.tsx 或新建管理页面 |
| 3.7 | 集成测试: 权限管理全流程 | 2 | P0 | 3.1-3.2 | tests/test_kb_permission_management.py |
| 3.8 | 文档: 更新 API 文档和 README | 1 | P2 | 全部 | docs/API.md, README.md |

### 验收标准

- [ ] KB admin 可通过 API 授予/撤销用户权限
- [ ] 前端权限管理面板可列出已授权用户及角色
- [ ] 支持添加/移除/变更用户角色（viewer/editor/admin）
- [ ] 仅 admin 角色可见权限管理入口
- [ ] 管理员可查看和管理本租户所有 tenant KB
- [ ] 集成测试覆盖：授权后可写、撤销后不可写
- [ ] visibility 字段创建后不可修改（防止权限升级攻击）

### 技术注意事项

- 权限变更操作需要 admin 角色校验
- 前端权限面板仅对 tenant KB 的 admin 用户显示
- 批量授权可作为后续优化，本期支持单用户操作即可

---

## 依赖关系图

```
Sprint 1:
  1.1 --> 1.5 --> 1.9
  1.2 --> 1.8
  1.3 --> 1.6 --> 1.10
  1.4 --> 1.7
  1.1-1.10 --> 1.12

Sprint 2:
  2.1 --> 2.2 --> 2.3 --> 2.4 --> 2.5
                       --> 2.6 --> 2.7, 2.8, 2.9, 2.10

Sprint 3:
  Sprint 2 --> 3.1 --> 3.3
           --> 3.5 --> 3.6
```

---

## 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| OR 条件查询性能下降 | 列表接口变慢 | 中 | Sprint 1 中添加 (visibility, tenant_id) 复合索引（纳入 Sprint 2 迁移脚本） |
| 用户角色体系不完善 | 无法区分管理员 | 高 | Sprint 1 先用 config 配置 admin 列表，Sprint 2 接入 system_role 字段（superadmin/tenant_admin/user） |
| 前端状态复杂度增加 | 开发周期延长 | 中 | Sprint 2 先做只读展示，Sprint 3 再加写操作 |
| no-auth 模式兼容问题 | 开发环境异常 | 低 | no-auth 模式下所有 KB 视为 private + 当前用户可见，保留 allow_no_auth_kb 配置 |
| 插件更新覆盖 Alembic 迁移 | 数据丢失 | 低 | 迁移脚本纳入版本控制，CI 验证 |
| 权限逻辑分散导致安全漏洞 | 数据泄露 | 中 | 集中到 KbAccessControl，所有入口统一调用 |
| DocumentRepository owner 过滤 | 非 owner 无法操作 tenant/public KB 文档 | 高 | Sprint 2 Story 2.4 新增不按 owner 过滤的方法变体 |

---

## 关键技术决策

1. **权限控制在应用层** - 向量存储层不改动，每个 KB 仍有独立 collection
2. **visibility 不可变** - 创建后不允许修改，防止权限升级攻击（需同时从 Repository.update() allowed fields 中移除）
3. **渐进式角色引入** - Phase 1 用配置文件定义 admin，后续使用 UserRow.system_role 字段（superadmin/tenant_admin/user）
4. **读写分离** - 可搜索 != 可编辑，通过 kb_permissions 表控制细粒度写权限
5. **向后兼容** - 现有 private KB 行为完全不变，旧 API 调用方无需修改
6. **角色命名映射** - 代码中 `system_role="superadmin"` 对应设计文档中的 `platform_admin` 概念，实现时统一使用代码中的 `superadmin`

---

## Definition of Done

每个 Story 完成标准：

- [ ] 代码实现完成并通过 Code Review
- [ ] 单元测试/集成测试编写并通过
- [ ] 不引入新的安全漏洞（权限校验完整）
- [ ] 向后兼容（现有 private KB 行为不变）
- [ ] 相关文档更新（CLAUDE.md / API docs）

---

## 实施顺序建议

```
Week 1: Story 1.1 ~ 1.7 (Repository + Service 层改造，含 get_accessible)
Week 2: Story 1.8 ~ 1.12 (RAG + API + visibility 不可变 + 测试)
Week 3: Story 2.1 ~ 2.6 (权限表 + DocumentRepo 改造 + 写权限后端)
Week 4: Story 2.7 ~ 2.11 (前端展示 + 集成测试)
Week 5: Story 3.1 ~ 3.4 (权限管理 API + 前端面板)
Week 6: Story 3.5 ~ 3.8 (管理后台 + 文档 + 收尾)
```

每周结束时进行 Demo，确认交付物符合预期后再进入下一周。

---

## 实施状态

### Sprint 1 ✅ 完成

所有 12 个 Story 已完成，测试覆盖率 > 90%。

### Sprint 2 ✅ 完成

所有 11 个 Story 已完成，前后端联调通过。

### Sprint 3 ✅ 完成

| # | Story | 状态 | 备注 |
|---|-------|------|------|
| 3.1 | API: 权限管理接口 | ✅ | POST/GET/DELETE /permissions |
| 3.2 | Service: 权限授予/撤销/查询 | ✅ | access_control.py |
| 3.3 | Frontend: 权限管理面板 | ✅ | kb-permissions-dialog.tsx |
| 3.4 | Frontend: 权限控制按钮显示 | ✅ | can_write/can_admin 条件渲染 |
| 3.5 | API: 管理员视图接口 | ✅ | GET /admin/all |
| 3.6 | Frontend: 管理员 KB 管理视图 | ✅ | Gallery Tabs (Admin tab) |
| 3.7 | 集成测试: 权限管理全流程 | ✅ | 20 tests passing |
| 3.8 | 文档更新 | ✅ | Sprint plan + API reference |

**后端测试**: 140+ tests passing (pytest)
**前端**: TypeScript 编译通过，ESLint 无新增错误

---

## API 参考（Sprint 3 新增接口）

### 权限管理

| Method | Path | 说明 | 权限要求 |
|--------|------|------|---------|
| GET | `/api/knowledge-bases/{kb_id}/permissions` | 列出 KB 的所有权限授予 | admin |
| POST | `/api/knowledge-bases/{kb_id}/permissions` | 授予用户权限 | admin |
| DELETE | `/api/knowledge-bases/{kb_id}/permissions/{user_id}` | 撤销用户权限 | admin |

**POST body**:
```json
{ "user_id": "string", "role": "viewer|editor|admin" }
```

### 管理员视图

| Method | Path | 说明 | 权限要求 |
|--------|------|------|---------|
| GET | `/api/knowledge-bases/admin/all` | 列出所有 KB（管理员视角） | superadmin / tenant_admin |

**Query params**: `visibility`, `limit`, `offset`

### KB 响应新增字段

所有 KB 响应对象现在包含：
- `my_role`: 当前用户对该 KB 的角色 (`"owner"` / `"viewer"` / `"editor"` / `"admin"` / `null`)
- `can_write`: 当前用户是否有写权限 (boolean)
- `can_admin`: 当前用户是否有管理权限 (boolean)

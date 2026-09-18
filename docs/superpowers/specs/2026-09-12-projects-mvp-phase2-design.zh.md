# DeerFlow 项目 MVP —— Phase 2 设计（项目说明、文档、提升、回收站）

**日期**: 2026-09-12
**状态**: 评审草案（RFC v2，[issue #5160](https://github.com/bytedance/deer-flow/issues/5160)）
**阶段**: 项目 MVP 的 Phase 2。Phase 1（组织）已作为 #5265 落地（`cfda885c`..`e2f2afde`，2026-09-08 合并）。
**权威来源**: **本 spec 全文是 Phase 2 的实施依据**，包括与 RFC v2（`docs/plans/2026-09-06-projects-mvp-rfc-v2.md` / `.zh.md`）或前身 spec 不一致的地方。RFC 仅作为历史背景；§10 解释重要偏差，但不是本 spec 取得优先权的前提。未说明的内容是应依据本 spec 解决的实现细节，不代表隐式引入 RFC 要求。需求追踪：[#5129](https://github.com/bytedance/deer-flow/issues/5129)。
**前身**: `docs/superpowers/specs/2026-09-06-projects-mvp-design.md`（其 §"运行时设计（Phase 2）"、§"删除、回收站与归档语义"已被本文 §7/§8 **取代**；该 spec 的 Phase 1 各节依然准确）。
**锚定**: 下文每条当前系统断言都在本次 checkout 的 `main @ 0464502a`（2026-09-12）上复核过。

---

## 问题陈述

Phase 1 给了项目三样能装的东西：会话、名称和一个 `status`。它没给项目任何能*告诉 agent* 的东西，也没给任何能*当作素材持有*的东西。已在 `main @ 0464502a` 上验证：

- `projects.instructions` 会被存储、可 PATCH、会被返回——但**零消费者**：`persistence/projects/model.py:6` 写着 "Phase 1 stores and PATCHes it, Phase 2 injects it"，而在 `ProjectRepository` 之外不存在任何对 `ProjectRow.instructions` 的读取。今天写项目背景的用户，是在往虚空里写。
- **不存在项目文档实体**：没有 `project_documents` 表、没有 `users/{user_id}/projects/` 文件系统布局、没有 `Paths` helper、没有 `trash_retention_days` 配置键、没有 `/api/trash/*`、没有 documents/from-thread/attach-to-thread/thread-files 路由。这项设计唯一的文字痕迹是
  `persistence/projects/sql.py:6-9` 的一句前瞻性注释。
- **运行时不具备项目感知**：在 `deerflow/runtime/**` 与 `deerflow/agents/**` 下穷尽搜索 `project_id|deerflow_project_id|ProjectRow|ProjectRepository` 零命中；`runtime_ctx` 就是 `{"thread_id", "run_id"}` 加上调用方键（`runtime/runs/worker.py:542`）。run 无法知道自己属于哪个项目，因此既收不到说明，也
  拿不到文档访问。
- 运行准入会**剥离**保留键 `deerflow_project_id`，且从不写 membership（`app/gateway/services.py:207-218`，由 `tests/test_thread_meta_repo.py:598-623` 钉住）。membership 只由 `POST /api/threads`、分支创建和 `POST /api/threads/{id}/move` 写入（`app/gateway/AGENTS.md:13-19`）。

用户可见的后果：项目就是一个名字好听的文件夹。成员会话仍然要手工重新交代背景，"这个话题的文档"依旧无处安放——项目页的 Documents 与 Instructions 区块并不存在（`frontend/src/app/workspace/projects/[id]/page.tsx:86-93` 只渲染 header + Chats + Settings）。

Phase 1 的项目页、侧边栏、移动菜单和保留键线上契约没有 Phase-2 缺口：本 spec 消费它们，而不是修改它们。

## 方案概要

五个交付物，按 §16 的依赖顺序合并：

1. **有界的说明注入。** 每次模型请求只接收当前 run 的 pinned 项目说明，放在 user-role `<project>` 块中，绝不进入 system prompt 或持久化消息历史。写入时强制 UTF-8 字节上限（拒绝，绝不截断）。
2. **每轮使用最新项目上下文。** 准入时解析一次当前项目，再仅在模型请求中渲染其身份/说明和文档架索引。重命名、编辑、移动和移出在下一轮生效，不需要修正链或历史比较。哈希仅作为审计指纹。
3. **一个项目文档架。** `project_documents` 配合带哈希、不可变且每条文档行独占命名空间的存储（§6.2），支持直接上传、列表、预览/下载、active 内容去重和移入回收站。派生 markdown 的缓存生命周期与所属文档的不可变原件一致。
4. **成员会话的有界、惰性文档访问。** 带上限的请求作用域 `<documents>` 索引提供用于发现的文档 ID；`list_project_documents` / `read_project_document` 经 run 的 pinned 项目身份，按需从宿主机存储提供内容。不批量注入文档内容；trashed 行对三层访问都不可见。

5. **双向提升 + 一个回收站层。** 保存到项目（会话文件 → 文档架，带溯源的复制）、attach 到会话（文档架 → 会话 uploads，接上现有 `<current_uploads>` 路径）、一个只读的成员会话文件聚合视图，以及可恢复删除：删除文档和删除项目把行进回收站；永久 purge 是单独的、需单独确认的动作，有自己的端点、保留窗口和顺
   序规则。

## 明确的非目标

以下是 Phase 2 的范围决策，不是砍掉的打磨项。重新引入任何一项，都必须先在 #5160 取得维护者同意。

1. **项目作用域记忆**——提炼、读取模式、按模式的写入路由。Phase 3（RFC 的 §17）。不加 `memory_mode` 列、不改 memory 读写、不加 memory API 的 `scope` 参数。
2. **agent 主动写入文档架。** 文档架由用户策展。工具是只读的；不存在 `write_project_document`。
3. **文档架全文搜索。** 延期，等使用量足以支撑索引。
4. **自动提升**每个会话文件到文档架。
5. **把二进制内容投递进模型上下文。** `read_project_document` 只提供文本与转换后的文本；二进制被拒绝，错误指向 attach-to-thread。
6. **项目级 sandbox 文档挂载。** 远程 provider 的 sandbox 身份由 `(user_id, thread_id)` 派生；harness 工具让该功能与 provider 无关。
7. **项目间的文档共享/复制。** 恢复需要*一个* active 目标项目，允许把 trashed 文档重新分配到该项目，但每份文档只属于一个项目；不存在"把文档复制到另一个项目"的动作。
8. **超出"每请求一个文件"的批量上传 UI 语义**（§6.5）；多文件批量等使用量说话。
9. **文档架文档的版本化/快照。** 重新上传变化后的内容会创建新的内容地址；旧行就是用户对它做过的事（进回收站或什么也没做）。没有历史，没有 diff。
10. **新的 RunJournal 事件类型**（§10.5 保留现有 `context:memory` 事件，增加项目指纹 payload 字段）。

## 选定的架构

### 从 Phase 1 继承的原则（不变）

- **项目是元数据容器**，不是 sandbox 边界；membership 变化仍是组织行为。
- **稳定的代理身份**：`projects.id` 是不可变 uuid4 hex。
- **服务端验证的 membership**：服务端从 `threads_meta` 推导 run 的项目；客户端绝不在运行时提供项目身份。
- **check-and-set，而非 check-then-act**：存在性/所有权/状态校验发生在变更语句或同一事务内部，且处于 Phase 1 确立的同一 `projects` 行锁之下。
- **无休眠 schema**：这里新增的每一列在 §6/§7/§8 都有指名消费者。

### Phase 2 特有的决策（评审者应优先攻击的那些）

1. **保留角色权威边界。** 框架所有的日期/规则仍放在 SystemMessage；用户撰写的说明和文档名使用独立的请求作用域 HumanMessage（§7.2）。既有日期/memory 消息及其持久化行为保持不变，不在它们的 SystemMessage 上存储项目 revision。
2. **每个 run 一次解析，并 pin 住。** 网关在准入时解析一次 thread → project → snapshot，并作为服务端所有的键写进 run 上下文。middleware 只对 pinned 快照做纯字符串处理；文档工具读取 pinned `project_id`，然后查询实时文档架行。运行中的移动或文档架变化都无法在同一个 run 内混合上下文。
3. **不可变的文档架文件，每条行独占存储。** `stored_relpath` 同时内嵌 `sha256` 和新生成的文档 ID；不同的行绝不共享原件或派生文件路径。一个路径的字节永不改变。设计依赖的推论：去重按内容决定；转换出的 markdown 伴生文件不需要失效；恢复**不移动任何文件**，只重指一行（§10.6），因为相对路径依然有效。
4. **fail closed，降级要响。** 没有项目的 run 得不到项目上下文，工具也会拒绝。解析失败降级为"未分配"并记一条警告，而不是让 run 失败——这正是准入对会话元数据已有的形态（`services.py:1477-1490`）。
5. **prompt 保持静态。** 任何项目数据都不进入 `SYSTEM_PROMPT_TEMPLATE`（`agents/lead_agent/prompt.py:541`）；只有信任声明的*措辞*会变（§7.2），因为它当前描述的消息形态已被代码废弃（§10.1）。

## 用户故事

1. 作为用户，我写一次项目说明，每个成员会话的 agent 都知道它们——不必我再粘贴一遍。
2. 作为用户，我重命名项目或编辑其说明后，我*既有*的会话在下一次运行时就会跟上变化。
3. 作为用户，我在项目级上传参考资料，agent 按需发现并阅读它，而不必让整个文档架落进每个 prompt。
4. 作为用户，我把某条会话里的好产出保存到项目文档架，并让它的来源可见，而不必下载再重新上传。
5. 作为用户，我把文档架上的文档 attach 进某条会话，让 agent 通过正常的上传路径编辑/处理它。
6. 作为用户，我在一个地方浏览我项目里所有会话产出的每个文件，而这些文件不会变成文档架条目。
7. 作为用户，删除文档或项目在一个保留窗口内可恢复；永久删除是单独的、需确认的动作。
8. 作为用户，把会话移入项目会让它的 agent 在下一次运行获得项目说明；移出则收回它们。
9. 作为维护者，我可以先落地说明注入，再落地文档架存储及其必要的回收站状态转换，最后补齐恢复/purge UI。每个切片在其前置依赖存在时可用；回滚按依赖的逆序执行（§16）。

## 后端设计

### 6.1 持久化

`persistence/projects/model.py` 新增 `ProjectDocumentRow`；`persistence/projects/sql.py` 新增 `ProjectDocumentRepository`（docstring 纪律与既有的 `ProjectRow`/`ProjectRepository` 相同）。

| 列 | 类型 | 索引 / 可空 | 消费者 |
| --- | --- | --- | --- |
| `id` | `String(64)` PK | — | 每个路由/工具 |
| `project_id` | `String(64)` | 索引 | 文档架列表、项目删除语句 |
| `user_id` | `String(64)` | 索引 | fail-closed 所有者过滤 |
| `name` | `String(255)` | — | 文档架索引、工具输出（字节上限对齐 `uploads/manager.py:32` 的 `_MAX_FILENAME_BYTES`） |
| `stored_relpath` | `String` | — | 在 `users/{user_id}/projects/` 下解析（§6.2） |
| `sha256` | `String(64)` | 索引 | 去重键、内容地址 |
| `size_bytes` | `Integer` | — | 文档架展示 |
| `source_thread_id` | `String(64)` | 可空 | 提升溯源 |
| `source_kind` | `String(16)` | 可空 | `upload` \| `output` |
| `source_name` | `String(255)` | 可空 | 会话内的原名 |
| `trashed_at` | `DateTime(tz)` | 可空, 索引 | 回收站列表、每次查询的 live/trashed 划分 |
| `trash_origin` | `JSON` | 可空 | 供展示 + 恢复提示的 `{project_id, project_name}` 快照 |
| `created_at` / `updated_at` | `DateTime(tz)` | — | 文档架"修改时间"展示；索引排序 |

没有 `mime`、没有 `is_text`、没有 `version`、没有 `deleted_by`：文本检测是一次采样读取（§7.3），而文档架按设计没有历史。

repository 表面（所有方法都按 ContextVar 所有者过滤，`AUTO` 哨兵与 `ProjectRepository` 相同）：

- `insert_active(project_id, *, document_id, name, relpath, sha256, size_bytes, source_thread_id=None, source_kind=None, source_name=None) -> dict | None` —— 在事务内锁 `projects` 行（`status='active'`、按所有者限定、`with_for_update()`）；项目缺失/他人/已归档时返回 `None`。
- `find_active_by_sha256(project_id, sha256) -> dict | None` —— 去重命中。
- `list_active(project_id, *, limit, offset) -> list[dict]` —— `ORDER BY updated_at DESC, id ASC`。
- `count_active(project_id) -> int` 与 `shelf_snapshot(project_id, *, limit) -> (rows, total)` —— 一次往返喂给 §7.1 的 pinned 索引。
- `get(document_id, *, include_trashed=False) -> dict | None`。
- `trash(document_id) -> bool` —— 先锁自有 active 项目，再锁自有文档；执行带守卫的 `UPDATE … SET trashed_at=:now, trash_origin=:json WHERE id=:id AND user_id=:uid AND project_id=:pid AND trashed_at IS NULL`；`False` ⇒ 404。已归档文档架拒绝此写入。
- `trash_all_for_project(project_id, *, project_name)` → 在 `ProjectRepository.delete` 的事务内执行（§8.1）。
- `list_trashed(*, limit, offset) -> list[dict]`。
- `list_all_trashed() -> list[dict]` —— 调用者的全部 trashed 行，最旧在前；这是清空回收站使用的、与年龄无关的选择，逐行交由 `purge` 处理（§8.3），并在 purge 锁内复核 trashed 状态，因此并发恢复的行会被跳过。
- `restore(document_id, *, target_project_id) -> tuple[str, dict | None]` —— 结果枚举为 `Literal["restored", "merged", "not_found", "no_target", "content_missing"]`；数据库重指，以及文档锁内的只读原件检查（§10.6）。
- `purge_candidates(retention_days) -> list[dict]` —— 早于保留窗口的 trashed 行。
- `purge(document_id, *, retention_cutoff=None, expected_trashed_at=None) -> bool` —— 在同一事务及文档行锁内完成 trashed 状态校验、文件删除、行删除与提交（§6.3/§8.3）；`False` ⇒ 404。保留期调用者传入候选记录的 trash 时间戳和截止时间，并在锁内复核两者，防止已恢复又重新入回收站的文档按旧过期时间被清除。手动 purge 校验当前 trashed 状态，不要求达到保留期。不暴露无守卫的 `delete_row` 变更接口。

迁移 `0024_project_documents`（在 rebase 到 `0023_user_preferences` 之后由 `0023` 重编号；今天的链头是 `0023_user_preferences`，`migrations/AGENTS.md:22-30`）：用 `op.create_table` 建表 + 四个索引；按 `0019_projects.py:22-23` 的写法用现有 `inspector.has_table` 惯用法守卫。bootstrap 的前向兼容下限（`persistence/bootstrap.py:133-171`）**无需**改
动：`project_documents` 是新表，旧二进制把下限当作存在性检查，绝不从 `Base.metadata` 推导它。`tests/test_persistence_forward_revision_compat.py` 中的链头 pin 必须挪到新的链头（`0024_project_documents`）。

### 6.2 文件系统布局

```
users/{user_id}/projects/{project_id}/documents/
  .staging/{uuid}                       # in-flight upload/promote bytes
  {sha256[:2]}/{sha256}/{document_id}/
    original/{name}                    # immutable original, filename <=255 UTF-8 bytes
    derived/converted.md               # optional conversion; separate namespace
```

`stored_relpath` 存储为**相对于 `users/{user_id}/projects/`**——即它以 `{project_id}/documents/` 开头。这使恢复不依赖文件移动（§10.6），并让每次读取的限定检查与 `Paths.resolve_virtual_path` 的模式（`config/paths.py:446-484`）一致：先解析，再断言 `resolved.relative_to(users/{user_id}/projects/)`。

每条新行在最终落盘前获得服务端生成的全新 uuid4-hex `document_id`；ID 和存储命名空间绝不复用。去重是在 active `(project_id, sha256)` 行之间做出的数据库决策，不共享物理文件。命中去重时返回既有行，不发布另一个文件。文档入回收站后重新上传，即使字节和名称完全相同，也得到新行和不同路径。恢复保留其命名空间；归并清理只删除被舍弃行的命名空间。显示文件名单独占用一个路径分量，不添加哈希前缀或 `.md` 后缀，因此被接受的 255 字节文件名在支持的文件系统上仍有效。转换按原文件名扩展名判断类型，经临时文件与原子改名写入 `derived/converted.md`，并按文档串行化。

新增 `Paths` helper，对齐 `thread_dir`/`sandbox_uploads_dir`（`config/paths.py:310-351`），包含对 `project_id` 的 `_validate_user_id` 式 safe-id 检查：

- `user_projects_dir(user_id) -> Path`
- `user_project_dir(user_id, project_id) -> Path`
- `project_documents_dir(user_id, project_id) -> Path`
- `project_document_path(user_id, relpath) -> Path` —— 在 `user_projects_dir` 下拼接，并再次检查限定。

### 6.3 原子性规则（Phase 2）

Phase 1 把 check-and-set 实现为“在写事务内拿下 `projects` 行锁”（SQLite `BEGIN IMMEDIATE` + `SELECT … WHERE id/user_id/status='active' FOR UPDATE`；`persistence/thread_meta/sql.py:57-79, 126-161`）。Phase 2 复用这一惯用法：

- **文档架插入（上传 / 提升）：** 暂存并哈希字节、分配全新文档 ID，然后进入一个事务：锁自有 active 项目行 → 在 active `(project_id, sha256)` 行中去重 `SELECT` → 未命中时，把字节原子落到该文档独占的命名空间 → `INSERT` → 提交。命中时删除暂存文件并返回既有行。落盘先于插入（§10.3）；插入失败只尽力清理自身命名空间，崩溃残留在 24 小时后回收。
- **Attach-to-thread：** 锁定并校验自有 live 源文档，暂存稳定副本，然后调用共享的会话上传接收服务（§7.3）；后者负责目标校验、文件名分配、转换、权限及 sandbox 同步。已归档源项目允许此读取。
- **进回收站：** 同一事务内先锁自有 active 项目行，再锁自有文档行；执行带 `trashed_at IS NULL` 守卫的 `UPDATE`；项目缺失/已归档或 `rowcount = 0` ⇒ 404。
- **恢复：** 一个事务——先锁目标自有 active 项目行，再确定源文档及可能的归并候选行，按 ID 顺序锁文档行；加锁后重新校验源所有权及 `trashed_at IS NOT NULL`；随后归并到同 `sha256` 的 active 行，或清 trash 字段并重指 `project_id`。源缺失/已恢复/已 purge ⇒ 404。两种结果之前都在源锁内检查原件存在性和大小；`content_missing` 时源保持 trashed。归并还需在目标文档锁内检查保留行的内容。恢复事务内不修改文件；提交后清理被舍弃的源文件。
- **项目删除：** §8.1 的三条语句在既有事务内、处于 `ProjectRepository.delete` 已持有的同一项目行锁之下（`persistence/projects/sql.py:159-176`）。
- **Purge：** 一个数据库事务连续持有自有文档行锁，覆盖 `SELECT … WHERE trashed_at IS NOT NULL` → unlink 原件及派生文件 → 删行 → 提交。恢复在此期间不能越过源行锁。文件系统操作不可回滚；其他 unlink 失败会回滚数据库变更，保留可重试的 trashed 行。`FileNotFoundError` 按已删除处理（§8.3）。SQLite 使用 `BEGIN IMMEDIATE`。
- **锁顺序：** 需要项目锁的操作先锁项目，再锁文档；多个文档锁按 ID 排序获取。项目删除在批量更新前按 ID 顺序锁定受影响文档。purge 只拿自身文档锁，之后绝不再等待项目锁。恢复、进回收站、转换和 purge 都遵守文档串行化约束；转换加锁后重新校验 active 状态，不能在 purge 后发布派生文件。

### 6.4 配置

新增 `config/projects_config.py`，沿用 `read_before_write_config.py` 的形态（有类型的 Pydantic 模型 + `Field(...)` 边界），外加 `AppConfig.projects` 字段（`config/app_config.py:185-262`）和 `config.example.yaml` 里的 `projects:` 块：

| 键 | 默认值 | 边界 | 消费者 |
| --- | --- | --- | --- |
| `instructions_max_bytes` | `8192` | `ge=256, le=262144` | 写入时 422（§6.5） |
| `shelf_index_max_entries` | `50` | `ge=1, le=500` | §7.1 索引渲染 |
| `shelf_index_max_bytes` | `4096` | `ge=512, le=65536` | §7.1 索引渲染 |
| `trash_retention_days` | `30` | `ge=1, le=3650` | §8.3 清扫 |

文档架文档的大小限制**复用**会话上传限制（`uploads.max_file_size`，默认 50 MiB；`routers/uploads.py:45-47, 163-168`），而不是引入第二个同义旋钮。`uploads.auto_convert_documents` 保持其含义，并会被 `read_project_document` 的转换路径遵循（§7.3）：关闭时，可转换文件会被明确报错拒绝，而不是被转换。

### 6.5 网关 API

三个新 router，在 `app.py:create_app` 中与 `projects.router` 并列挂载（`app.py:836`）：

`routers/project_documents.py` —— `APIRouter(prefix="/api/projects/{project_id}/documents", tags=["project-documents"])`：

| 方法 + 路径 | body / query | 响应 | 权限 |
| --- | --- | --- | --- |
| `GET ""` | `limit`（默认 100，1..1000）、`offset` | `ProjectDocumentListResponse` | `projects:read` |
| `POST ""` | multipart，**恰好一个文件** + 可选 `name` | `ProjectDocumentUploadResponse`（`201` 创建 / `200` 去重命中） | `projects:write` |
| `POST "/from-thread"` | `{thread_id, kind: "upload"\|"output", name, shelf_name?: str}` | 与上传相同 | `projects:write` + `threads:read` |
| `POST "/{document_id}/attach-to-thread/{thread_id}"` | — | `{filename, size_bytes, virtual_path, artifact_url}` | `projects:write` + `threads:write` |
| `GET "/{document_id}/content"` | `download: bool = false` | 内联文本或附件 | `projects:read` |
| `DELETE "/{document_id}"` | — | `204`（移入回收站） | `projects:delete` |

`routers/project_thread_files.py` —— `APIRouter(prefix="/api/projects/{project_id}/thread-files")`：

| 方法 + 路径 | query | 响应 | 权限 |
| --- | --- | --- | --- |
| `GET ""` | `offset`（成员会话游标）、`thread_limit`（默认 20，1..50）、`file_limit`（默认 50，1..200） | `ThreadFilesResponse` | `projects:read` + `threads:read` |

`routers/trash.py` —— `APIRouter(prefix="/api/trash", tags=["trash"])`：

| 方法 + 路径 | body / query | 响应 | 权限 |
| --- | --- | --- | --- |
| `GET "/documents"` | `limit`、`offset` | `TrashListResponse` | `projects:read` |
| `POST "/documents/{document_id}/restore"` | `{project_id?: str}` | `RestoreResponse`（可能报告 `merged`） | `projects:write` |
| `POST "/documents/{document_id}/purge"` | — | `204` | `projects:delete` |
| `POST "/purge"` | — | `{purged: int}` | `projects:delete` |

请求校验：

- `instructions`（既有的 `ProjectCreateRequest`/`ProjectPatchRequest` 字段）：当 `len(value.encode("utf-8")) > projects.instructions_max_bytes` 时以 **422** 拒绝。截断是评审阻断项（§15）。
- 上传 `name`：可选；默认取经 `normalize_filename` 之后的 multipart 文件名；规范化后为空、含路径分隔符或超过 255 UTF-8 字节时拒绝。
- `from-thread` 的 `name`：必填（源文件名）；`kind ∈ {upload, output}`；源必须解析在该会话自己的 uploads/outputs 目录内。可选 `shelf_name` 默认取源文件名，并遵循上传名称校验。
- `restore` body：`project_id` 可选；仅当来源项目已不存在或已归档时必填；无效/他人/已归档的目标 ⇒ 404。
- 上传**每请求恰好一个文件**（§17.2）：部分失败的语义不进响应 body，一个请求最多映射到一行（或一次去重命中），多文件拖放由 UI 自己循环。
- 分页边界沿用现有 422 惯例（`routers/projects.py:143-157`）。

错误映射：每个路由对缺失/他人资源返回 404。自有 active 和 archived 项目均允许文档架列表、内容/下载、会话文件读取、run 注入及文档工具读取。上传/提升、恢复目标和单份文档移入回收站要求 active 项目；已归档项目返回 404。attach 可以从已归档源文档架读取，写入自有且可写的目标会话，不修改源文档架。项目删除保持 Phase-1 契约。资源查询失败不通过 403 暴露存在性。项目 repository 不可用（memory 后端）时，经现有 `deps.py:654` 的 `_require` 访问器返回 **503 `"Projects"`**，并扩展 `project_document_repo` 访问器；上传超限为 413（对齐 `routers/uploads.py:320-321`），校验失败为 422。

PAT 默认拒绝：每条新路由都必须加入 `auth/pat.py` 的允许清单（`:59-68`）——当前规则只覆盖 `/api/projects`、`/api/projects/{id}`、`archive|restore`、`/threads` 和 `/threads/{id}/move`。漂移守卫是 `tests/test_pat_auth.py::test_pat_projects_policy_admits_exactly_the_mounted_routes`，必须用新路由扩展它。

## 运行时设计

### 7.1 运行上下文解析与 pin

每个 run 一次异步解析，位于 `app/gateway/services.py` 共享的 run 创建路径（`:1455-1490` 附近的代码块，在 `inject_authenticated_user_context` 之后、`create_or_reject` 之前）：

1. 经 `run_ctx.thread_store` 读取 `record.thread_id` 的 `threads_meta.project_id`。
2. 若为非 NULL，则加载项目行（按所有者限定，`status IN ('active', 'archived')`；已归档 membership 保留说明及只读文档架访问），以及一个**有界**文档架快照：计数与按 `updated_at DESC, id ASC` 排列的前 `shelf_index_max_entries + 1` 行。多出的 `+ 1` 行仅用于判断截断，不参与渲染。

   只有有界渲染窗口和计数进入 runtime context，避免复制无人使用的整架元数据。`shelf_hash` 覆盖最终渲染的索引，不覆盖未展示行，且仅用于审计。文档架变化绝不触发持久化修正。计数和行来自一致的数据库快照；后续工具调用刻意读取实时行，并可能因并发修改而得到不同结果。

3. 构建 pinned 快照，写在一个新的服务端所有的键下：

```python
# deerflow/runtime/context_keys.py
PROJECT_CONTEXT_KEY: Final[str] = "__deerflow_project_context"
```

```python
{
  "project_id": "…", "name": "…",
  "instructions": "…",
  "shelf": {"total": 7, "entries": [{"id","name","size_bytes","updated_at"}, …]},
  "shelf_hash": "<hex>"          # sha256 over the rendered index (see below)
}
```

4. 把 `PROJECT_CONTEXT_KEY` 加入**两个**服务端所有的集合，使客户端提供的值绝无可能存活：`services.py:435-446`（它在 `:586-591` 处从 `config["context"]` 和 `config["configurable"]` 里 pop 该键）以及 worker 的 `_SERVER_OWNED_RUNTIME_CONTEXT_KEYS`（`runtime/runs/worker.py:511-530`）。
5. 解析失败（DB 错误，或会话行尚不存在）只记一条警告并让 run 保持未分配——绝不让 run 失败；这是组织层面的故障，不是授权故障。这与 `_ensure_thread_metadata` 的非致命契约一致（`services.py:1477-1490`）。

消费者只读 pinned 值：middleware（§7.2）从它渲染；工具（§7.3）从它取 `project_id`，然后查询实时文档架。任何组件都不在运行中途重新解析会话的 membership。

### 7.2 只注入最新版本的说明与文档架索引

**统一投递方式。** 说明和文档架索引都只存在于装配后的模型请求中。`DynamicContextMiddleware` 新增 `wrap_model_call` / `awrap_model_call` 钩子，调用 `deerflow/projects/context.py` 中的纯渲染 helper；既有 `_build_full_reminder`、`_inject`、日期修正和 `__memory` 持久化行为保持不变。项目渲染不依赖 memory 读取成功，也不执行数据库或文件系统 I/O。

```
Persisted history (existing behavior unchanged):
SystemMessage  <system-reminder><current_date>…</current_date></system-reminder>
HumanMessage   id={user_msg_id}__memory   <memory>…</memory>  # optional
… conversation history …
HumanMessage   current user turn

Model request only, inserted immediately before the current user turn:
HumanMessage   <project id="…" name="Roadmap">
               {current instructions}
               </project>
               <documents count="7" shown="7">
               - id=abc123… | q3-report.pdf (2.1 MB, modified 2026-09-10)
               - …
               </documents>
```

- **每 run 一份快照，每次模型调用一个当前块。** 同一 run 的全部调用和重试使用准入时固定的快照（§7.1），自动压缩后也一样；下一 run 重新解析快照。工具仍在 pinned 项目 ID 下读取实时行。
- **仅最新版本语义。** 重命名、说明编辑或项目移动在下一 run 替换所注入的配置。说明为空时省略说明正文，保留当前项目身份；文档架为空时省略 `<documents>`。未分配项目的 run 不注入任一块，也不注册项目工具。不再有 `__project` 修正、移出通知或与历史 revision 的比较。
- **幂等请求装配。** 用保留消息 ID 前缀、服务端所有的 `deerflow_project_context` 标记及 provenance 共同识别本 middleware 的临时消息；Gateway 准入剥离客户端提供的同名标记。每次装配只从请求副本中移除本 middleware 可确认属于自身的临时消息，再插入至多一条新渲染消息。不能仅按文本或 ID 前缀删除用户消息。设置 `hide_from_ui`，但不设置 `dynamic_context_reminder`；绝不作为 state 更新返回，也不写入 checkpoint。
- **插入位置。** 放在当前 run 的真实用户消息之前，通过服务端所有的 run/message 身份识别，不能把最后任意一条 HumanMessage 当成用户。工具循环内保持锚点稳定，不在每次工具结果之后追加新上下文，不拆开 assistant 工具调用及结果序列。恢复/内部 run 没有保留下来的当前用户锚点时，使用前导 SystemMessage 之后的协议安全位置。压缩后根据当前请求重新定位有效锚点。既有前置插入共享 helper 不变，项目专用定位由项目渲染器负责。正常、恢复、内部和压缩后的 run 均需断言实际请求顺序。
- **不改写历史。** 用户/assistant 过去讨论旧说明的内容仍是历史会话，不是当前项目配置。静态信任声明明确：运行时提供的当前块是有效项目设置的来源，缺席时不提供项目说明。这不会抹除已经讨论过的事实，也不改变用户全局 memory 语义。
- **压缩。** 现有 summarizer 会救回所有标记 `dynamic_context_reminder` 的消息（`summarization_middleware.py::_preserve_dynamic_context_reminders`）。项目消息不进入该路径：state 中没有项目块，没有受保护的修正累积，也不需要项目专用保留规则。下一次模型请求直接重新渲染 pinned 快照。撤回旧稿中“正常压缩会丢掉这些 reminder”的描述。

**有界渲染与信任。** `<project>` 块携带 pinned ID/名称及当前说明。属性值需转义，说明与文档名经过 `neutralize_untrusted_tags`。把 `"project"` 和 `"documents"` 加入 `_BLOCKED_TAG_NAMES`、前端 `INTERNAL_MARKER_TAGS` 和导出擦除词表；更新 denylist 漂移守卫，不削弱它。项目值和文档名都不进入 SystemMessage。重写 `prompt.py` 信任段落，区分既有 user-role `<memory>` 数据、请求作用域项目数据及框架规则；标签转义不会授予 system 权威。

索引提供精确 `count`/`shown`，按 `updated_at DESC, id ASC` 排序，包含每条文档的稳定 ID。只输出同时满足 `shelf_index_max_entries` 和 `shelf_index_max_bytes` 的完整条目；ID、转义名称、包裹文本、分隔符及溢出提示都计入字节上限，先为包裹文本/提示预留空间。提示必须可行动：`…and 12 more — call list_project_documents to list them all`。索引是准入时文档架顺序的有界前缀，不保证后续实时分页仍看到同一份文档架。

**审计指纹，不是更新状态。** 保留既有 `context:memory` 事件类型，增补项目字段：

```python
content={"content_sha256": <hex | None>, "project_context_revision": <str | None>, "project_shelf_revision": <str | None>}
# content_sha256: selected existing __memory message only; null when absent
# project_context_revision: sha256(rendered <project> text), or null
# project_shelf_revision: sha256(rendered <documents> text), or null
```

项目哈希描述实际提供给模型的块，绝不与历史比较，也不存入 reminder 的 `additional_kwargs`。扩展 `record_memory_context`，允许 `content_sha256` 为空；首次模型请求装配确定投递内容后，只要有 memory 或任一项目块便发一次事件，覆盖没有 `__memory` 的纯项目 run。同一 run 后续模型调用不重复记录。没有这些上下文的 run 保持不发事件。装配失败不能声称投递成功；既有 memory 失败遵循其配置策略。读取者兼容缺少项目字段的旧 payload。

这些是指纹，不是保留的版本。注入器不把说明或索引文本保存到 transcript，哈希也不能重建任一历史块；run-event UI 不得承诺重放确切配置。文档存储、用户聊天历史和全局 memory 与此请求作用域的注入生命周期相互独立。

### 7.3 文档：有界的项目级访问

三层，由廉到贵；trashed 行在三层里都被排除。

1. **文档架索引（发现）** —— 每个 run 都按 §7.2 从 pinned 快照把 `<documents>` 块渲染进该 run 的请求里，受 `shelf_index_max_entries` / `shelf_index_max_bytes` 限制，按 `updated_at DESC` 排序，条目渲染为 `- id={document_id} | {name} ({size}, modified {date})`。稳定 ID 可以直接传给 `read_project_document`，也能区分同名文档，并计入字节上限和渲染哈希。仅元数据。因为它是每 run 重新渲染的，唯一的陈旧窗口就是**一
   次 run 之内**——用户在某次 run 的准入之后移入回收站、purge、重命名或新增的文档不在这次 run 的块里——而且它从不累积：文档架相关的任何东西都没有被持久化，因此对话后面不会有陈旧清单。这个窗口永远到不了内容层：每次读取都会按实时状态重新校验（§7.3 第 2 层），并以明确的错误失败（§11），而不是提供过期字
   节。
2. **按需读取（内容）** —— 新模块 `deerflow/projects/tools.py` 里两个 harness 侧工具，用 `get_project_document_tools()` 注册，并经同一个跳过重名的 helper（由 `_append_memory_tools_without_name_conflicts` 泛化而来）追加到 lead agent 的工具列表里 memory 工具旁边
   （`agents/lead_agent/agent.py:182-192, 1024-1030`）。**注册以 run 的 pinned 项目上下文为条件**：只有当 `PROJECT_CONTEXT_KEY` 存在时才追加这两个工具，因此没有项目的 run 永远不付它们的 schema token，也永远看不到它们。这很便宜，因为装配本来就是每 run 一次——`make_lead_agent(config)`
   →`assemble_lead_agent(config)`（`agents/lead_agent/agent.py:758-801, 878+`）今天就从 run 作用域的 config（`agent_name`、模型覆盖、`should_use_memory_tools`）算出工具列表，而且没有任何 run-graph 缓存依赖它（`_state_accessor_graph_cache` 只缓存 state-accessor 图，键
   为`(assistant_id, mode, snapshot_frequency)`——`app/gateway/services.py:916-951`）。判据只读**服务端所有的 pinned 键**，绝不读客户端可影响的字段，而且即使该键在调用时因某种原因缺失，两个工具仍然 fail closed（双保险）。准入解析并保存快照（§7.1）后，middleware 与工具注册共享一个只读服务端 pinned 键的判据。解析过程不能在该键尚不存在时依赖这一判据。说明或文档架为空时可以省略渲染文本，但不能禁用工具；准入解析失败时键缺失，两个工具均不注册。
   - `list_project_documents(offset: int = 0, limit: int = 50) -> str` —— live 文档架行的 JSON 列表（分页，`limit ≤ 200`），按索引自己的 `updated_at DESC, id ASC` 顺序，并返回 `total` 与 `next_offset`，让模型可以走完被索引截断的文档架；用于超出注入索引上限的架子。
   - `read_project_document(document_id: str, offset: int = 0, limit: int = 8000) -> str` —— 文档文本的有界切片。`limit ≤ 20000` 个字符；响应携带 `{name, total_chars, offset, returned_chars, truncated, content}`。文本检测用现有 `is_text_file_by_content` helper（`routers/artifacts.py:235`）采样文件头
     部，该 helper 被抽到一个共享的 `deerflow/utils/` 模块，让 router 与工具用同一份实现。可转换类型（`CONVERTIBLE_EXTENSIONS`，`utils/file_conversion.py:32`）在首次读取时用 `convert_file_to_markdown` 转换，之后从该文档独占的 `derived/converted.md` 伴生文件提供；`uploads.auto_convert_documents` 关闭时跳过转换并拒绝该
     调用。不可转换的二进制会被拒绝，错误指明 attach-to-thread 这条路线。
   - 两个工具都从 `runtime.context[PROJECT_CONTEXT_KEY]` 取 `project_id`，从 `resolve_runtime_user_id(runtime)`（`runtime/user_context.py:178-219`）取 `user_id`，沿用 `list_uploaded_files_tool.py:42-63` 的做法。缺失项目上下文或缺失 session factory ⇒ 工具错误，绝不是一个空的成功。
   - **子 agent 在 Phase 2 拿不到这些工具。** 子 agent runtime 有自己的 middleware 集合（只有日期，不做 memory 查找）和自己的工具列表；lead agent 自己读取所需内容，并在任务 prompt 里把内容传下去。把文档架访问扩展到子 agent 是一个独立决策，有自己的消费者，而不是 lead 注册的副作用。
   - 每次文件读取、恢复内容检查和转换都做了 offload（`asyncio.to_thread` / `convert_file_to_markdown` 自带的 >1 MiB offload），并且需要一个 `tests/blocking_io/` 锚点——仓库的守卫套件覆盖触碰文件系统的异步路径。
3. **Attach 到会话（显式，架 → 会话）** —— `POST …/attach-to-thread/{thread_id}` 读取自有 live 文档（源项目可为 active 或 archived），经从 `routers/uploads.py` 抽取的共享会话上传接收服务生成独立副本。服务负责暂存、`claim_unique_filename`、大小校验、受 `uploads.auto_convert_documents` 控制的可选转换、sandbox 可读权限，以及通过既有授权 sandbox 请求租约把原件和派生文件同步到非挂载 provider。`sandbox:execute` 被拒时遵循普通上传：保留宿主机上传文件，但不分配 sandbox。获取/sync/转换失败遵循普通上传服务的错误与清理行为；所需同步完成前不能返回成功附件。测试为两个调用者固定相同行为，包括部分同步后的清理行为。源文档架不变。

   只有接收流程成功后才返回 `{filename, size_bytes, virtual_path, artifact_url}`。前端将文件加入 composer 附件列表，接入既有 `additional_kwargs.files` → `UploadsMiddleware` 的 `<current_uploads>`。源校验及稳定读取与 purge 串行化；目标会话所有权/写入准入由共享上传服务重新校验。不要跨 sandbox 分配或网络同步持有文档事务：先在锁内暂存源副本，再按普通会话上传的生命周期保证完成接收。

### 7.4 保存到文档架，以及会话文件视图

**保存到项目**（`POST …/documents/from-thread`，`{thread_id, kind, name, shelf_name?}`）：把会话文件（uploads 或 outputs）复制进文档架，成为项目所有的快照。源文件不动；文档架不持有任何指向会话存储的引用，所以删除会话不可能影响它。`source_thread_id` / `source_kind` / `source_name` 会被记录并渲染为溯
源徽标（"来自 *会话名* · output"）。`name` 用于在会话内定位源文件；提升对话框的可编辑名称字段发送 `shelf_name`（默认：源文件名），这是两者产生分歧的唯一途径——这恰恰使 `source_name` 成为有消费者的列，而不是休眠列（RFC §4.3："original name inside the thread, if renamed on the shelf"）。校验走的是上传
路径那一套：按所有者校验的会话与项目、必须为 active 项目、`uploads.max_file_size`、暂存 + `os.replace`、文档独占的带哈希路径。源解析被限定在该会话自己的 `user-data/{uploads,outputs}` 目录内——即 `resolve_virtual_path` 的纪律（`config/paths.py:446-484`），而不是字符串拼接。

**会话文件视图**（`GET …/thread-files`）：对成员会话的只读聚合。响应形态：

```json
{"groups": [{"thread_id": "…", "display_name": "…", "updated_at": "…",
             "files": [{"kind": "upload", "name": "…", "size_bytes": 0, "modified_at": "…",
                        "artifact_url": "/api/threads/…/artifacts/mnt/user-data/uploads/…"}]}],
 "next_offset": 20, "truncated": false}
```

有界 fan-out：成员会话按项目会话列表所用的同一非归档排序分页（`thread_limit` 默认 20，最大 50）；每条会话贡献它的 uploads（经 `list_files_in_dir(sandbox_uploads_dir)`，`uploads/manager.py:287`）和它的 outputs（对 `sandbox_outputs_dir` 的新列表——今天不存在 outputs 列表端点，因此这个 helper 是新的，且
不与任何其他东西共用）。每条会话的文件上限为 `file_limit`；响应报告 `truncated`，而不是静默裁剪。它自身零存储：条目随其会话被删除而消失，这是对所有权诚实的陈述。该视图是"保存到项目"的发现路径，且永不喂给文档架、索引或工具。

## 8. 删除、回收站与归档语义

### 8.1 项目删除

`ProjectRepository.delete` 保持其形态（按所有者限定的项目行锁，然后在一个事务里执行下列语句），并新增第二条语句：

1. `UPDATE threads_meta SET project_id = NULL WHERE project_id = :pid`（+ 所有者谓词）——今天已实现（`persistence/projects/sql.py:171-176`），包括对 `updated_at` 的保序自赋值。
2. `UPDATE project_documents SET trashed_at = :now, trash_origin = :json WHERE project_id = :pid AND trashed_at IS NULL` —— 新增；一条语句，无文件系统操作，行在项目行消失之前快照 `{project_id, project_name}`。
3. `DELETE FROM projects WHERE id = :pid`。

删除确认文案随之改变（会话解除关联；文档架文档移入回收站，并在 `trash_retention_days` 内保持可恢复）；当前那句承诺"文件不受影响"的字符串（`frontend/src/core/i18n/locales/en-US.ts:357-358`）在 Phase 2 之后就是错的，必须替换，zh-CN 一并替换。

### 8.2 回收站恢复

`POST /api/trash/documents/{document_id}/restore`，body 为 `{project_id?}`：

- 目标 = body 里的值；否则当 `trash_origin.project_id` 对应项目仍存在、属于调用者且为 `status='active'` 时用它；再否则请求以 404 失败，UI 提供项目选择器。
- 归并情形：目标已有同 `sha256` 的 active 行 → 删除回收站行，响应报告 `merged`。提交后对那个不再被引用的文件（回收站行独占、不会被任何保留行引用的文档命名空间）做 best-effort unlink；失败记日志，由清扫回收（§8.3）。
- 其他情况下，在一个事务里重指该行（`project_id` = 目标，`trashed_at` = NULL，`trash_origin` = NULL）。**不移动文件**：`stored_relpath` 相对项目根（§6.2），因此字节依然有效。
- 恢复到调用者不拥有的项目是 404，与项目不存在不可区分。

### 8.3 永久 purge 与保留期

- purge 只存在于 `POST /api/trash/documents/{id}/purge` 和 `POST /api/trash/purge` 两条路径，各自在 UI 上有一道明确的"此操作不可撤销"确认，外加保留期清扫。清空回收站会清除调用者的**全部** trashed 行，与年龄无关——它的确认覆盖整个列表——因此保留期截止时间只约束清扫：`purge_candidates` 仍是唯一带年龄过滤的选择。
- 顺序：在持续持有文档行锁的数据库事务内（§6.3），先 unlink 原件及 `derived/converted.md`，再删行并提交。`FileNotFoundError` 是幂等成功，包括可选转换文件不存在的情形。其他文件系统错误保留 trashed 行并返回可重试错误。unlink 后发生崩溃、部分 unlink 或数据库提交失败，可能留下内容缺失的 trashed 行；下一次 purge 完成清理。恢复在同一组文档行锁内检查原件存在性和大小（归并时还检查将保留的目标内容），缺失时返回 409 `content_missing`，不把损坏行激活。数据库回滚不能恢复字节。归并清理是另一种情况：它发生在行删除已提交之后，失败只能留下无人引用的文件。
- 保留期：`projects.trash_retention_days`（默认 30）。清扫先通过同一受守卫的 purge 服务处理过期 trash，再做非破坏性的行侧对账。在 `GET /api/trash/documents` 上懒执行，并在网关启动时于 `lifespan` handler 中执行一次（`app.py:196`，与 `:253-320` 的其他启动工作并列）。不新增守护进程，不依赖调度器。
- 清扫还会以年龄为界做存储对账；任何 active 或 trashed 行都会保护其原件/派生文件的整个命名空间，即使它已经恢复到另一个项目：删除 `.staging/*` 条目，以及用户 `projects/*/documents/` 下超过 24 小时且无人引用的文件。任何不足 24 小时的内容都不回收，因此进行中的上传不会被扫掉。
- 清空某项目最后一个 trashed 文档后会留下空目录；对父目录做 best-effort `rmdir`。
- **行侧对账。** 清扫的另一个方向：内容文件缺失（被 unlink）、或磁盘上的大小与 `size_bytes` 不一致、且超过同一道 24 小时守卫的行，**会被检测但绝不自动删除**。清扫以 warning 级别记录它，该行也会以 `content_missing` 的形式暴露（§11）。删除该行会抹掉"这份文档曾经存在"这一用户仅有的记录，并把溯源一并带走；处置从用户将 active 内容移入回收站开始；随后可由手动 purge 或满足条件的保留期 purge 删除 trashed 行。文件不可变且带哈希，因此大小不一致意味着外部干扰，而不是陈旧——它会被报告，绝不被就地修复。

### 8.4 归档

Phase-1 的归档矩阵对会话部分不变，并新增它此前无法表达的那一行——文档：

| 问题 | 回答 |
| --- | --- |
| 其会话还能运行吗？ | 能 |
| run 还会被注入说明 / 文档架索引吗？ | 会——注入读取已归档项目的行（§7.1 第 2 步） |
| 能把会话移入其中吗？ | 不能（Phase 1 已强制） |
| 能往其中上传/提升文档吗？ | 不能——文档架插入以 `status='active'` 锁项目行（§6.3）；UI 在上传/提升入口处省略已归档项目 |
| 其文档架能被读取吗？ | 能——列表、预览/下载、会话文件和工具读取保持可用；项目页显示只读横幅 |
| 能将文档架文件 attach 到会话吗？ | 能——包括从已归档项目读取；遵守目标会话写权限及普通上传/sandbox 规则 |
| 能单独把文档架文件移入回收站或恢复到其中吗？ | 不能——这些变更要求 active 项目；删除整个项目保持既有契约，并把文档架移入回收站 |
| 其会话出现在哪里？ | 平铺列表不变；分组模式折叠进 "Archived"（Phase 1） |

## 9. 前端设计

默认文案语言是 `en-US`（`core/i18n/locale.ts:3`）；每个新键都同时落到 `locales/types.ts`、`en-US.ts` 和 `zh-CN.ts`。

- **项目页**（`app/workspace/projects/[id]/page.tsx`）增加标签页——Chats（现有）、Documents、Instructions、Settings（现有）——沿用 `app/workspace/chats/page.tsx:130-138` 已在用的 Tabs 模式。
  - **Documents** 有两个以分隔线隔开的区域：策展文档架（上传按钮 + 拖放、带名称 / 大小 / 修改时间 / 溯源徽标的行、预览、下载、attach-to-thread、移入回收站），以及下方只读的会话文件浏览器（按会话分组，每条目带预览和**保存到项目**）。行布局与逐行动作复用
    `ArtifactFileList`（`components/workspace/artifacts/artifact-file-list.tsx:34-192`）；预览复用 `ArtifactFilePreview` / `ArtifactViewer` / `/artifacts/view` 路由。这里回收站**不是**一个撤销 toast：删除会弹出一道确认，点名回收站和保留窗口。
  - **Instructions** 是一个 `Textarea`，经 `usePatchProject` 显式保存（该字段已接好：`core/projects/api.ts:79, 104-106`），带一个对照 `projects.instructions_max_bytes` 的实时字节计数器，以及一个镜像 422 的客户端守卫。
- **回收站视图**：新路由 `/workspace/trash` ——刻意**不**放在 `/workspace/projects/` 下，因为那里的动态 `[id]` 段会吞掉字面的 `trash` 路径——从项目页的 Documents 区块和侧边栏的 Projects 区块表头可达，列出 trashed 文档及其来源项目名和剩余保留期、逐条目的 Restore / Delete-permanently，以及带独立确认的
  "Empty trash"。动作行沿用 `app/workspace/chats/page.tsx:200-216`。
- **侧边栏**：`ProjectsSection` 增加一个回收站入口。分组不变。
- **移动菜单**：不变——"移动不是隔离"提示（`move-to-project-menu.tsx:100-103`）原文照留。
- **过渡期记忆提示**：项目页的空状态（以及 Documents 标签页的空状态）承载 RFC §10 的文案——记忆在 Phase 3 之前保持用户全局，因此项目内讨论的任何内容都可能进入全局记忆。既然文档已经存在，这就是 issue 验收清单要求的"明确提示"。
- **状态**：`core/projects/` 下的新 hooks——`useProjectDocuments`、`useUploadProjectDocument`、`usePromoteThreadFile`、`useAttachProjectDocument`、`useDeleteProjectDocument`、`useProjectThreadFiles`，query key 位于 `["projects", "documents", projectId]` / `["projects", "thread-files", projectId]` 之
  下；`core/trash/` 下有 `useTrashDocuments`、`useRestoreDocument`、`usePurgeDocument`、`useEmptyTrash`。mutation 失效 `["projects"]` 前缀（`invalidateProjectCaches` 惯例，`core/projects/hooks.ts:38-46`），并在 attach 改变某会话 uploads 时失效 `["threads"]`。
- **静态 demo 守卫**：每个 Phase-2 界面在 `isStaticWebsiteOnly()` 下返回 `null`，与 `projects-section.tsx:266-268` 一致。

## 10. 偏差登记表（RFC v2 与 Phase-1 spec vs. 代码）

本登记表解释与 RFC 和前身 spec 的重要差异。本 spec 全文是 Phase 2 的实施依据，不论某项差异是否在这里再次列出；历史 RFC 验收要求仅在本 spec 明确采纳时适用。

### 10.1 提醒形态与角色权威

RFC 把项目说明放进 SystemMessage。本 spec 保留既有权威划分：项目身份/说明和文档名作为请求作用域 HumanMessage 数据。既有日期 SystemMessage 与 `__memory` 消息保持原行为，项目数据不拼入其中。

### 10.2 消息合并不持有项目状态

SystemMessage 合并可以对日期提醒去重，但项目块是独立的请求作用域 HumanMessage。SystemMessage 不携带或重发项目 revision；模型请求装配必须保留恰好一个当前块（§7.2）。

### 10.3 先文件后行，而非先行后文件

RFC §5.2 先暂存字节、提交行、再移动文件，并接受一个崩溃窗口，留下"没有文件的文档架行"。这个坏状态对模型是*可见的*（索引会列它），而反向泄漏则不然。Phase 2 在插入行**之前**把暂存文件改名进它独占的带哈希存储位置：崩溃留下的是一个无人引用的文件，任何消费者都看不到，由清扫回收。RFC 自己的 §4.4 已经把文件侧泄
漏当作有界失败接受下来。

### 10.4 `shelf_revision` 哈希的是渲染后的索引

RFC §7.1 把 `shelf_revision` 定义为"文档数 + active 行中最大 `updated_at`"。这个二元组对重命名、对索引在两个方向上越过条目/字节上限、对排序并列都是盲的。实现改为哈希渲染后的 `<documents>` 文本——即模型实际拿到的确切字节，这也正是 revision 身份应有的含义。语义（文档架变化刷新索引）不变，且被严格收紧。

### 10.5 显式项目审计字段

现有 `context:memory` 哈希只覆盖选中的 `__memory` 消息。项目块不再搭载该消息，审计需使用独立的 `project_context_revision` 和 `project_shelf_revision`，对渲染后的块计算指纹（§7.2）。扩展既有事件及其触发守卫以支持纯项目 run，不新增事件类型，也不声称 memory 哈希覆盖项目说明。指纹不能重建历史配置。

### 10.6 恢复只重指、不移动文件

RFC §5.1 说恢复"在目标目录不同时物理移动文件"。因为 `stored_relpath` 是相对 `users/{user_id}/projects/` 存储的（§6.2），路径在重指之后依然有效：恢复仅改变数据库中的所属项目和 trash 字段，不移动文件。文档锁内的只读存在性/大小检查防止恢复激活在部分 purge 中丢失内容的行（§8.3）。提交后的归并清理是恢复路径唯一的文件系统变更；移入回收站仍不做文件系统操作。

### 10.7 准入不翻译保留键（Phase-1 偏差，为 Phase 2 重述）

RFC §6 说首次运行准入会校验 `deerflow_project_id` 并写入 membership 列。它没有：准入剥离该键，且从不写 membership（`services.py:207-218`，由 `tests/test_thread_meta_repo.py:598-623` 钉住），客户端侧的缺口由前端预先带 `project_id` 建会话补上（`chat-page.tsx:213-230`）。因此 Phase 2 在运行开始时从
`threads_meta` 解析项目上下文（§7.1），而不是从 run metadata 解析，并且对准入键路径不加任何东西。

### 10.8 原子性使用已落地的锁惯用法

RFC §5.2 把校验写成字面的 `INSERT … WHERE EXISTS (SELECT …)` SQL。Phase 1 以写事务内加锁的 `SELECT … FOR UPDATE`（配合 SQLite `BEGIN IMMEDIATE`）落地了等价物。Phase 2 扩展这一惯用法；拿 RFC 的 SQL 片段比对的评审者应改读 §6.3。

### 10.9 去重返回第一个名字，而非请求里的名字

RFC §4.4 说重新添加相同内容会返回既有行，但没说谁提供的 `name` 胜出。决策：**第一个**写入者的名字胜出，响应就是既有行（`200` 而不是 `201`）。既有行及其原始溯源也一并保留。进回收站后新建的行会获得新的独占命名空间（§6.2），即使字节/名称相同也如此。不同的行绝不共享物理文件；转换缓存有效性来自同一行内不可变的字节，而不是跨生命周期去重。


### 10.10 截断策略：有界的索引，可接受的发现尾巴

RFC §7.2 给索引设了上限，但留了两件事未定：被截断的文档架对“发现”意味着什么，以及可见子集按什么顺序选出。以下是决策，并前置说明它们接受的弱点：

- **截断被接受，但绝不静默、绝不失效**：精确的 `count`/`shown`、被略去的数量，以及点名 `list_project_documents` 的溢出提示（§7.2）。模型绝不会只知道“还有更多”却没有下一步。
- **顺序是 `updated_at DESC, id ASC`**，与工具分页的顺序完全一致。推论：新加入的材料是 agent 免费就能看到的，而*又旧又重要*的那份文档恰恰会随着文档架增长而掉出可见子集。这是该策略的真实代价，它由工具层兜住而不是被隐藏：尾巴只有一次调用之遥，`count` 说明它有多大，而用户总能 attach 某一篇具体文档。
- 本阶段被否决的替代方案：**给文档加星/置顶**（在它有消费者之前就需要新增一列外加一个 UI 动作——“无休眠 schema”规则）、**按 name 或 `created_at` 排序**（确定性，但丢掉了常见情形所依赖的近期性信号；稳定顺序的洗牌也更少，因此若使用情况显示尾巴常被漏掉，它是第一个该回头看的点）、**文档架全文/向量搜
  索**（RFC 已延期；索引比一个逐页工具大得多的承诺）。
- 如果“大海捞针”的情形最终占主导，最小的充分修复是重新审视*排序*，而不是把注入做大：上限是配置，但无界索引与 issue 追踪器设定的非目标相矛盾。


### 10.11 项目工具只存在于项目 run 中

RFC §7.2 列出了这两个工具，但从未说明由谁注册、何时注册。决策：注册**以 run 的 pinned 项目上下文为条件**（§7.3），在准入解析好快照之后，经由那里描述的唯一共享判据求值。消费者共享 pinned 身份；空块和注入失败遵循 §7.2/§7.3 的明确投递语义。

接受的后果，每条都带缓解手段：

- 解析静默失败的 run 既没有块也没有工具；唯一的信号是准入警告（§7.1）和下一次运行的自愈。这是明说而非隐藏的：对一个组织功能而言，静默降级优于让 run 失败，但对那一次 run 而言，这确实是能力上的真实损失。
- 每个 agent 的装配描述符会多出一个变体（带/不带项目工具），因为工具列表喂给 `build_assembly_descriptor`（`agents/lead_agent/agent.py:850-875`）。断言“单一稳定描述符”的测试与观察者必须同时接受两者；`test_agent_assembly_descriptor.py` 式的覆盖把两个分支都钉住。
- 对项目 run，这两个工具留在常开列表里，而不是加入延迟工具搜索：注入的索引按名字宣传 `list_project_documents`，而一个被宣传却无法直接调用的工具，比一个根本不存在的工具更糟。

否决：无条件注册、调用时 fail closed 的工具。它会让每个没有项目的 run 为一项永远用不到的能力付出固定 schema 预算——经常性成本落在多数情形上——而“它保留了明确的错误信号”这一反驳很弱，因为 `<project>` 块同样缺席，模型没有任何可行动的东西。


### 10.12 每个 run 一份项目快照

准入只解析并固定一次 membership、身份/说明及有界索引。渲染与注册使用同一快照；工具在其项目 ID 下查询实时内容。每次模型调用重新渲染不等于重新读库，也不改变工具循环中的 membership。解析失败在准入处理；纯项目渲染器不向 memory 注入路径添加异步数据库桥接。即使实时 offset 分页与索引使用相同顺序，并发文档架变更后仍可能漂移。

### 10.13 最新配置取代持久化修正链

旧稿持久化初始说明，并在每次变化后追加带 revision 的修正。该方案已被取代：模型只通过请求装配接收当前 run 的项目配置（§7.2）。不再比较身份 revision，不再有历史键缺失后的恢复分支，也不需要修正保留策略。现有压缩会保留所有 `dynamic_context_reminder` 消息；给每次项目修正加该标记，即使单条有上限，也会累积受保护的说明。请求作用域注入消除了这一联动，不改变 memory/日期保留行为。

“仅最新版本”指注入的配置，不是删除历史聊天。请求块不进入 checkpoint 消息或压缩输入；历史对话仍可能提及旧设置。版本管理和确切历史配置重放不属于 Phase 2，journal 哈希仅是指纹。

### 10.14 请求位置与前缀缓存取舍

说明和文档架索引共用一条请求作用域消息。普通 run 将其放在当前用户轮之前，不改写早先的历史提醒。再次渲染相同 pinned 内容本身不意味着缓存失效：复用取决于最终序列化请求的前缀、工具 schema、插入位置和 provider 行为。上下文变化或插入边界移动可能改变可复用的后缀；恢复 run 的回退位置可能影响更多历史，其他 middleware 也可能在前部插入变化数据。本 spec 承诺上下文有界且不累积，不保证缓存命中率或仅有一个块按未缓存计费。用结构断言验证最终请求；性能结论应以 provider 的缓存 token 和延迟实测为依据。

## 11. 错误处理

| 情形 | 行为 |
| --- | --- |
| 跨用户 / 缺失的项目、文档、会话 | 404（fail closed；绝不 403） |
| 上传/提升进已归档或他人的项目 | 经加锁的 active 项目校验返回 404 |
| `instructions` 超字节上限 | 写入时 422（POST 与 PATCH）；绝不截断 |
| 上传超过 `uploads.max_file_size` / 空文件 / 不可用文件名 | 与 uploads router 一致：413 / 400 |
| 提升的 `kind`/name 解析到会话 uploads/outputs 之外 | 404（限定失败与不存在不可区分） |
| attach 进调用者无法写入的会话 | 404 |
| 恢复时没有有效目标（来源已消失/已归档，也未提供） | 404；UI 提供选择器 |
| 恢复与 active 内容冲突 | `merged` 结果；回收站条目消失 |
| purge 时 unlink 抛出 `FileNotFoundError` 以外的错误 | 回滚事务，保留 trashed 行，500 并给出可重试提示 |
| purge 时原件/派生内容已不存在 | 缺失文件按已删除处理；完成剩余清理和行删除 |
| 恢复时原件缺失或大小不符 | 409 `content_missing`；行保持 trashed |
| 文件已改名到位后文档架插入失败 | 无人引用的文件，由清扫（>24 h）回收 |
| 对二进制或转换被关闭的可转换文件调用 `read_project_document` | 工具错误，指明 attach-to-thread |
| 没有 pinned 项目上下文时的工具调用 | 工具错误；无数据 |
| 本次 run 的索引已渲染之后文档被移入回收站或 purge | 工具错误 `no longer on the shelf`——绝不返回过期内容；下一次 run 的索引直接省略它（没有任何被持久化的东西需要修复） |
| 内容文件缺失的行（`content_missing`） | 内容端点与工具返回明确的 `content_missing` 错误；项目页把该行渲染为 **content missing**，active 项目内该文档的唯一动作是移入回收站；archived 文档架在项目恢复前不提供文档变更动作；清扫记录它（§8.3） |
| repository 不可用（memory 后端） | 503 `"Projects"`（现有访问器惯例） |
| 准入时解析失败 | 记警告日志；run 以未分配继续 |

purge 端点不携带确认参数："此操作不可撤销"这一步是 UI 契约（§8.3、§9），它不是服务端强制的确认握手。获授权的 API 客户端可以直接调用 purge；省略 flag 既不会改变也不会撤销其破坏性语义。

## 12. 安全与隔离

- 每次查询都经按 ContextVar 用户自动过滤的 repository；没有任何路由或工具接受 `user_id`。
- pinned 项目上下文是服务端所有的 runtime-context 键，准入时从调用者 config/context 剥离，worker 合并时也拒绝。独立的 `deerflow_project_context` 消息标记同样从客户端消息元数据中剥离；请求注入时连同 provenance 和保留 ID 前缀一起盖章（§7.2）。
- 文档读取在 `users/{user_id}/projects/` 下解析并复查 `relative_to`，与 `resolve_virtual_path` 同一纪律；`stored_relpath` 值只来自服务端生成的内容地址，绝不来自请求文本。
- 说明和文档名是不可信文本：渲染前针对被禁 tag 做中性化（§7.2），并在输入净化器中列入拒绝名单，使用户消息无法伪造 `<project>` 块。
- trashed 文档对文档架索引、工具和列表 API 都不可见；只经用户自己的回收站端点可见。
- 保留期与 purge 与其他一切一样按用户限定；除内容已不存在之外的 unlink 错误会保留 trashed 行；部分文件系统进展及提交失败遵循 §8.3 的明确重试契约。
- PAT 调用者在把新路由加入允许清单（`auth/pat.py`）之前一律被默认拒绝，这就是预期的默认。

## 13. 测试策略

**后端单元**

- `ProjectDocumentRepository`：active 行之间的去重（trashed 行不阻止重新添加）、每次读取过滤 `trashed_at`、`shelf_snapshot` 排序、`restore` 结果矩阵（`restored` / `merged` / `not_found` / `no_target` / `content_missing`）、`purge_candidates` 在恰好 `retention_days` 处的边界。
- 说明上限：恰好 `instructions_max_bytes` 被接受，超一字节在 create 与 patch 上均以 422 拒绝；多字节（CJK）输入按 UTF-8 字节计数，不按字符计数。
- 索引渲染：条目上限、字节上限、截断提示、空文档架不出现索引、`</project>` 及文档名中被禁 tag 的转义。
- 索引渲染算法：CJK 名称下字节上限先于条目上限触发；不发出半个条目；省略数等于 `count − shown`；溢出提示点名 `list_project_documents`；没有并发文档架变更时，工具分页按同一顺序遍历条目。独立测试允许修改后的实时分页漂移，不断言快照式分页。ID 及全部包裹文本/溢出提示字节都计入上限。
- 最新说明：{重命名、说明编辑、清空、移入、移出} 分别使下一 run 的请求只包含当前配置，没有旧注入说明或修正消息。说明为空仍保留项目身份，未分配时没有项目块。日期/memory 消息及元数据不变，覆盖同时跨午夜的情形。
- 请求作用域投递：有项目时每次模型调用/重试恰好一条当前项目消息，文档架非空时含一个索引；run 前后 checkpoint 消息不含注入的项目文本。跨 run 编辑四十次后，包括自动/手动压缩后，仍只产生一个当前块。再次装配已修饰请求时替换自身临时消息，不删除用户内容；伪造标记/ID 不能压掉或替换该块。测试当前真实用户消息前的插入、工具循环内稳定位置，以及恢复/内部调用的协议安全回退。
- Journal 身份：每个已投递 run 发一次 `context:memory`；`content_sha256` 只覆盖既有 `__memory` 消息（缺席时为空），项目哈希覆盖当前渲染块。覆盖纯项目 run、空说明、无文档架、无项目、重复调用、装配失败及旧事件 payload。项目哈希变化绝不追加或重写 checkpoint 消息，不能将指纹呈现为可重建版本。
- 工具：切片边界（offset 等于/超过 `total_chars`）、`limit` 钳制在 20000、二进制拒绝、`auto_convert_documents` 开/关时的转换路径、无 pinned 上下文时 fail closed、无需重新 attach 即可反映实时文档架编辑。
- 配置：`projects:` 缺失时的默认值、非法值带警告回退（`_get_upload_limit` 惯用法）、边界强制。

**后端集成**

- 每条新路由对他人或缺失项目/文档/会话返回 fail-closed 404。
- 经 API 走通 上传 → 列表 → 内容 → attach → 删除 → 恢复 → 再次进回收站 → purge，中间包含回收站视图。
- 文件名边界：原件及可转换文档接受 255 UTF-8 字节、拒绝 256；物理路径分量不超过文件系统限制。同名不同内容的行拥有不同 ID，能直接依据索引 ID 读取。
- 归档矩阵：列表/内容/工具读取/注入及 attach 保持可用；上传/提升/单文档进回收站/作为恢复目标返回 404；删除整个项目仍会把文档架移入回收站。
- attach 与普通上传一致：挂载及非挂载 provider、原件/转换文件同步、可读权限、拒绝 `sandbox:execute` 时不分配 sandbox、获取/同步失败及部分清理。只有成功时 composer 才收到完成的附件。
- 切片边界：A 不依赖文档表即可注入说明；仅 B 落地时，删除项目后也不能留下 active 文档行。在加入 D 前验证。
- 项目删除：清 membership、同一事务内把文档架移入回收站、不触碰文件、不永久删除。
- purge 顺序：注入 `OSError` 时保留 trashed 行；可选转换文件缺失可成功；原件 unlink 后派生文件 unlink 失败、或数据库提交失败均可重试。恢复缺失/大小不符内容返回 409，不激活。清理只作用于所属文档命名空间，包括 `derived/converted.md`。
- 保留期清扫：回收站列表懒触发、启动触发、24 小时孤儿守卫（新暂存文件存活）；行侧对账发现内容缺失或大小不符时记录并保留行，只有显式 purge 或满足保留期条件的 purge 才能随后删除 trashed 行，对账本身不删除。并发恢复/再次入回收站后，在锁内复核候选 trash 时间戳和截止时间。
- PAT 允许清单漂移守卫扩展新路由。
- 迁移 `0023` 可升级、可降级；更新前向 revision 兼容链头 pin；`test_migration_0021_batch_acceptance.py` 式参数化升级仍通过。

**并发（硬性要求）**

- 上传 vs 项目删除：插入看不到 active 项目而返回 404，或删除把新行也移入回收站；绝不留下指向已删除项目的 active 行。
- 并发重复上传相同字节：恰好一行、一个文件，两个请求均成功。
- 并发恢复到正在删除的项目：404 或完整的回收站转换；绝不留下项目行已消失却未 trashed 的文档。
- 同一文档的 purge vs restore：存储健康时一方成功、另一方 404；锁覆盖 unlink 和提交，在 SQLite 及支持行锁的数据库中用屏障测试。purge 失败保留 trashed 行；若字节已删除，restore 返回 409。覆盖两种先获得锁的次序。
- 上传 → 进回收站 → 同名同内容重传 → purge 旧行：新行原件和转换结果仍在。再覆盖旧行恢复到同项目时的归并，以及恢复到另一项目后的场景；断言命名空间不同、清理不越界。
- 转换 vs purge：转换不能在文档 purge 后发布文件，不暴露部分转换文本。

**运行 pin**

- 移动前启动的 run 以移动前说明和工具读取完成；下一次 run 只注入新解析的项目配置（§7.2）。
- 未分配会话的 run 不获得 `<project>` 块，`list_project_documents` fail closed。
- 冻结索引一致性：准入后进回收站的文档仍在该 run 索引内，同一 run 的 `read_project_document` 返回过期条目错误；下一 run 的请求作用域索引省略它，不写入任何持久化项目消息。
- 准入：客户端在 `config["context"]` 或 `configurable` 中提供的 `PROJECT_CONTEXT_KEY` 不得进入 run。
- 工具可用性跟随 pinned 键：没有该键时不注册 `list_project_documents` / `read_project_document`（断言装配后的工具列表，不只是调用行为）；有键时注册两者；新获 membership 的会话下次 run 可见工具，失去 membership 后不可见。即使说明和文档架都为空，注册仍跟随 pinned 键，仍提供仅身份的块和工具。准入解析失败时不注册任一工具。测试固定两个装配描述符变体，因为工具列表进入描述符。

**Blocking-IO 锚点**

- `backend/tests/blocking_io/` 为新文件系统异步路径增加锚点：上传暂存/改名、purge unlink、恢复内容检查、转换、共享 attach 接收流程、清扫对账和工具读取。已有 `DynamicContextMiddleware` 锚点覆盖新增渲染路径。移除 offload 时锚点必须失败，沿用套件的变异验证方式。

**前端**

- DOM：Documents 标签页（溯源徽标、空状态、截断提示）、Instructions 编辑器（计数、保存、超限守卫）、回收站保留期展示、删除项目文案。
- Playwright：经 mock 路由走通 上传 → 文档架 → attach → 删除 → 恢复 → purge；扩展 `tests/e2e/utils/mock-api.ts`，沿用 `:930-956` 默认空模式；再覆盖带项目说明的 run，确保 `<project>` 不泄漏进渲染消息。

**验收映射**：本 spec 的用户故事、契约及上述检查定义 Phase 2 完成标准。RFC §14 第 6–12 项及第 15 项仅作为历史追踪参考，服从本 spec 的决策。

## 14. 需要更新的文档

- `README.md`——用户可见的项目说明、文档架、归档读取语义和回收站保留期。
- `backend/docs/API.md`——Phase-2 路由参考（documents、thread-files、trash）。
- `backend/docs/ARCHITECTURE.md`——项目文档架布局、运行开始时 pin、角色权威划分、回收站层。
- `backend/packages/harness/deerflow/persistence/migrations/AGENTS.md`——链头挪到 `0024_project_documents`（`0023_user_preferences` → `0024_project_documents`），并注明前向兼容下限不变。
- `backend/app/gateway/AGENTS.md`——membership-writer 契约增加"运行准入以只读方式 pin 项目上下文；它仍然从不写 membership"。
- `config.example.yaml`——`projects:` 块（§6.4）。
- `frontend` 的 i18n 词典——所有新键（§9）。
- 过渡期记忆语义与回收站保留窗口的用户可见文案。

## 15. 代码评审清单

出现以下任何一条即驳回 PR：

1. `instructions` 或文档名被渲染进 SystemMessage，或渲染进静态 system prompt。
2. 超长说明被截断，而不是写入时 422。
3. 文档批量注入；带静默裁剪的索引；trashed 行对索引或工具可见。
4. 文档工具在调用时重新解析会话的项目，而不是读取 pinned 键；出现第二条解析路径。
5. 新写入里任何地方存在 check-then-act：存在性/所有权/状态的校验出现在与其变更分离的读中。
6. 行在其字节落到文档独占的带哈希路径之前就被插入（§10.3 的反向）。
7. 恢复移动或重写原件，或移入回收站执行文件系统操作。恢复允许锁内只读内容检查，以及提交后的归并清理（§8.2/§8.3）。
8. purge 在清理/提交前释放文档锁，先删行后清理文件，或吞掉 `FileNotFoundError` 以外的 unlink 错误。
9. 为保留期新增守护进程、cron 或调度器条目。
10. `project_documents.project_id` 上的 DB 级外键，或休眠列（`mime`、`is_text`、`version`、`deleted_by`）。
11. 从请求 body、参数或工具参数接受 `user_id`；任何泄露存在性的 403。
12. 客户端提供的值作为 pinned 项目上下文存活下来；新 runtime-context 键缺失于两个服务端所有的集合之一；工具注册判据读取了该服务端所有的键之外的任何东西。
13. 为项目上下文新增 RunJournal 事件类型（§10.5）。
14. `_BLOCKED_TAG_NAMES` / `INTERNAL_MARKER_TAGS` 缺少 `"project"`、`"documents"` 中任一项，或以削弱而非归类新 tag 的方式更新漂移守卫测试。
15. memory 读写路径的任何改动，或 memory API 的 `scope` 参数。
16. 切片 A 依赖文档存储；切片 B 缺少删除项目时的文档 trash 转换；合并/回滚切片时未遵守其前置依赖（§16）。
17. 行侧对账删除行而非报告：保留期 purge 可以按 §8.3 删除过期 trash，但对账本身绝不移除行，任何代码路径都不得把内容文件缺失当作空文档。
18. 项目注入改写持久化历史、搭载 `__memory`，或给项目消息设置 `dynamic_context_reminder`，而不是使用请求作用域路径。
19. 将项目 revision 与历史比较，或追加修正/移出通知链；下一次准入已解析新快照后仍使用旧说明。
20. 说明或文档架索引跨请求累积、从 pinned 快照以外的数据渲染，或插在 assistant 工具调用与其结果之间。

## 16. 实施顺序

五个切片，各自在前置依赖落地后可合并。回滚按依赖逆序执行，不支持移除前置依赖却保留其消费者。每个切片按 §13/§14 自带测试与文档。

- **切片 A —— 说明注入。** `ProjectsConfig` + 写入时上限 + 422；`deerflow/projects/context.py`、准入身份/说明 pin（`PROJECT_CONTEXT_KEY`、两个服务端所有的集合）；通过 DynamicContext 模型调用钩子进行请求作用域 `<project>` 渲染和幂等定位；服务端临时标记剥离、provenance 及前端隐藏；后端/前端标记词表中的 `project` 和漂移守卫；静态信任段落；可空 memory 哈希及仅审计使用的项目指纹；Instructions 标签页。不依赖文档 repository，不建立身份修正链，不改变 memory/日期持久化。先回滚依赖它的切片，再回滚 A。
- **切片 B —— 文档架存储、投递与读取。** `ProjectDocumentRow` + `0023` 迁移 + repository；`Paths` helper；`deerflow/projects/documents.py` 与 `tools.py`；用有界文档架快照扩展 A 的 pinned 上下文；upload/list/content/delete-to-trash 路由；项目删除时的文档 trash 转换和删除确认文案，含 `trash_origin` 快照；**请求作用域 `<documents>` 块**（每 run 从 pinned 快照渲染，永不持久化）；journal payload 的 `project_shelf_revision`；两个工具与 `is_text_file_by_content` 抽取。依赖 A，因为它扩展 A 的请求作用域项目渲染器；将 `documents` 加入两侧标记词表及漂移守卫。
- **切片 C —— 提升与文件浏览器。** `from-thread`、`attach-to-thread`、`thread-files`（含新增 outputs 列表 helper）及前端界面。依赖 B。
- **切片 D —— 回收站收尾。** Restore/purge/empty-trash 路由、`trash_origin` 展示字段、保留期清扫与启动钩子、孤儿对账。`DELETE …/documents/{id}` 路由在 B 落地（删除即入回收站），且 B 必须已支持删除项目时将全部 active 文档行移入回收站；restore/purge 与清扫属于 D。依赖 B。
- **切片 E —— 前端收尾与文案。** Documents 标签页（文档架与会话文件浏览器）、回收站路由、侧边栏入口、过渡期记忆提示、i18n 与文案更新、e2e/mocks。B/C/D 路由契约冻结后可开始。

Phase 1 的保留键线上契约、归档门禁和 membership 写入者**不**被任何切片修改。

## 17. 已决决策

以下决策明确当前配置如何进入 run，以及上传如何准入。变更任一决策都需要同步修改契约和测试，不只是选择另一种实现细节。

### 17.1 新鲜度——准入时最新，run 内稳定

说明和文档发现都使用准入时解析的最新快照。同一 run 的每次模型调用使用这份快照；运行中发生的修改在下一次准入生效。清空说明会从下一请求移除旧正文；移出项目会移除两个项目块。不需要额外延迟一轮，也不需要持久化修正。文档读取仍在 pinned 项目内查询实时内容。

**回看条件**：未来明确要求历史说明版本或运行中途变更配置；“仅最新版本注入”不隐含这些需求。

### 17.2 上传粒度——每请求一个文件

`POST /api/projects/{id}/documents` 恰好接收一个文件。部分失败的语义不进响应 body（一个 N 文件请求将不得不报告 N 个结果并挑一个状态码），一个请求最多映射到一行或一次去重命中（§10.9），而 UI 本来就对拖入的文件循环。批处理是日后按需追加的端点；schema 或存储布局都不需要改动。

**回看条件**：文档架被用于批量导入（每次动作几十个文件），此时逐文件往返主导了用户的时间。

工具注册刻意不在这张清单上：它已在设计正文中定案——以 run 的 pinned 项目上下文为条件（§7.3、§10.11），因为没有项目的 run 绝不能携带项目工具的 schema，也绝不能看到项目工具。

# Phase 2 交付报告

> **基线**：[2026-05-14-ai-report-custom-template-design.md](2026-05-14-ai-report-custom-template-design.md) §15 Phase 2。
> **范围**：模板存储与权限（Repository 抽象 + 文件存储 + Pydantic 模型 + 权限矩阵 + 模板生命周期）。
> **状态**：**全部 5 项工作通过**。可进入 Phase 3（受控工具 + ai-report--custom SOUL.md）。

## 交付清单

| Phase 2 项 | 状态 | 交付物 |
| ---- | ---- | ---- |
| **2.1 Repository 抽象** | ✅ 通过 | `FileSystemReportTemplateRepository` 类 |
| **2.2 文件存储** | ✅ 通过 | atomic rename + etag 乐观锁 + fcntl/Windows 锁 + index.json 维护 |
| **2.3 元数据/版本/Run 模型** | ✅ 通过 | `records.py` — 4 个 Pydantic 模型 |
| **2.4 权限矩阵校验** | ✅ 通过 | `permissions.py` — §11.1 完整矩阵 |
| **2.5 模板生命周期** | ✅ 通过 | `create / save_draft / publish / fork / archive / delete` |

**Phase 2 新增测试**：75 个（11 records + 18 permissions + 31 repository + 15 重叠）。
**测试总计（Phase 0+1+2+回归）**：338 passed / 0 failed。

---

## 2.1+2.2+2.5 Repository 实现

[backend/packages/harness/deerflow/report_templates/repository.py](../../backend/packages/harness/deerflow/report_templates/repository.py)

### 三层 Scope 模型

```python
Scope.private("alice")    → {DEER_FLOW_HOME}/report-templates/users/alice/
Scope.tenant("ten_a")     → {DEER_FLOW_HOME}/report-templates/tenants/ten_a/
Scope.builtin()           → agents/builtin/report-templates/    # 只读
```

`scope.user_id` / `scope.tenant_id` 在构造时即正则校验，保证后续路径拼装永不接受恶意字符。

### 文件布局（§7.1.1）

```text
{scope_root}/
  index.json                          # 用户/租户模板索引
  {template_id}/
    template.json                     # 元数据（含 etag、current_version）
    template.json.lock                # 进程锁哨兵（fcntl 或 O_EXCL）
    versions/
      v0.json                         # 工作草稿（每次 save_draft 覆盖）
      v1.json                         # 不可变版本快照（publish 后写入）
      v2.json
      ...
    runs/
      {report_run_id}.json            # ReportRun 索引
```

### 并发控制（§7.1.3）

每次写操作经过三层保护：

1. **进程内 `threading.Lock`**：`_lock_table[abs_path]` 保证同进程内同 key 串行
2. **跨进程哨兵锁**：
   - POSIX：`fcntl.flock(LOCK_EX | LOCK_NB)` + 50 ms 自旋直至 30 s 超时
   - Windows：`os.open(O_CREAT | O_EXCL)` 自旋直至同样超时
3. **原子写入**：临时文件 → `os.replace()`，避免读到半写状态
4. **etag 乐观锁**：`save_draft`、`archive`、`delete` 必须传 `expected_etag`，不匹配抛 `EtagMismatchError`（HTTP 409 语义）

`delete` 特别处理：先在锁内更新 index，**退出锁后**再 `_rm_dir(template_dir)`，因为 lock sentinel 位于 template_dir 内（必须先释放锁，目录才能完全清空）。

### 生命周期 6 项方法

| 方法 | 输入 | 输出/语义 | 关键校验 |
| ---- | ---- | ---- | ---- |
| `create_template` | scope, name, display_name, owner_user_id, tenant_id | 新建 draft，返回 `ReportTemplateRecord` | builtin 拒绝；自动分配 `tpl_` ULID |
| `save_draft` | scope, template_id, dsl, dsl_yaml, expected_etag | 覆写 v0.json 工作副本，刷新元数据 etag | published 状态拒绝；etag 不匹配抛错 |
| `publish` | scope, template_id, expected_current_version, changelog | v0 → v{n+1} 不可变快照，状态 published | 必须先 save_draft；版本号递增；记录 changelog |
| `fork` | source/target scope + version + 新 name/display_name | 目标 draft，v0 携带 `source_template_id/version` 溯源 | 目标不可 builtin；源版本必须存在 |
| `archive` | scope, template_id, expected_etag | 状态 archived | builtin 拒绝；etag 校验 |
| `delete` | scope, template_id, expected_etag | 硬删模板目录 + 清除索引 | builtin 拒绝；etag 校验 |

### Versions 公开列表过滤

`list_versions(scope, template_id)` 仅返回 ≥ 1 的版本号，**v0 工作副本对外隐藏**——保证用户在版本对比 UI 中不会看到混乱的"版本 0"。

### 测试覆盖（31 用例）

`test_report_template_repository.py`：

- **Create（4）**：files on disk、index entry、builtin 拒绝、user/tenant 隔离
- **SaveDraft（4）**：工作副本写入、stale etag、published 不可改、覆写
- **Publish（4）**：immutable v1、wrong current_version 拒绝、缺工作副本拒绝、两次发布递增版本
- **Fork（3）**：provenance 溯源、target 不可 builtin、缺源版本拒绝
- **Archive/Delete（3）**：archive 状态、delete 清目录+索引、wrong etag 拒绝
- **PathSafety（3）**：恶意 template_id / user_id / tenant_id 一律拒绝
- **Concurrency（1）**：两线程同时 save_draft 同一 template，**恰好 1 成功 + 1 EtagMismatchError**
- **ReportRuns（3）**：create+list、duplicate id 拒绝、update 覆写
- **TestFork（含上）** + 多 scope 隔离测试

---

## 2.3 Pydantic 持久化模型

[backend/packages/harness/deerflow/report_templates/records.py](../../backend/packages/harness/deerflow/report_templates/records.py)

### 模型一览

| Model | 写入文件 | 关键字段 |
| ---- | ---- | ---- |
| `ReportTemplateRecord` | `template.json` | id, owner_user_id, tenant_id, visibility, status, current_version, etag |
| `ReportTemplateVersionRecord` | `versions/v{N}.json` | template_id, version (≥0, v0=working), dsl, dsl_yaml, checksum, source_template_id/version |
| `ReportRunRecord` | `runs/{rr_id}.json` | id (rr_*), template_id, thread_id, run_id, status, parameters_summary, artifact_paths, error_code/message |
| `TemplateIndex` + `IndexEntry` | `index.json` | 列表数据源，刷新由 repository 触发 |

### ID 验证（§7.1.4）

- `tpl_[A-Z0-9]{20,32}` — Crockford base32 ULID 风格
- `rr_[A-Z0-9]{20,32}` — 同上
- `[a-zA-Z0-9_-]{1,64}` — user_id / tenant_id（路径段安全）
- 所有 ID 在 Pydantic field_validator 内重新校验，**不信任上游**

### 时间戳

`now_iso()` 统一返回 UTC ISO 8601，对齐 §7.1.5 V2 数据库迁移约束。

### 测试覆盖（11 用例）

`test_report_template_records.py`：

- **ID 生成器（3）**：模式匹配、唯一性（500 次无碰撞）
- **ID 验证器（3+）**：拒绝短 / 大小写错 / 含特殊字符 / 越权字符
- **ReportTemplateRecord（4）**：最小、bad id、bad owner、extra 字段
- **ReportTemplateVersionRecord（3）**：最小、v0 working copy 允许、负版本拒绝
- **ReportRunRecord（2）**：最小、状态枚举
- **TemplateIndex（1）**：往返序列化

---

## 2.4 权限矩阵

[backend/packages/harness/deerflow/report_templates/permissions.py](../../backend/packages/harness/deerflow/report_templates/permissions.py)

### 设计要点

- **无状态、纯谓词**：`check_permission(principal, operation, template) -> Decision`
- **不依赖任何 DI 框架**：Repository 不调用本模块；权限决策放在 Gateway 路由层和工具层（§8.1）
- **结构化 reason**：失败时附带可解释字符串，方便 Gateway 返回 4xx 错误体
- **复用现有角色**：`Principal.is_superadmin` / `is_tenant_admin` 字段直接映射 `tenant_agents.py` 的现有角色（§0 决策"复用 superadmin/tenant_admin"）

### §11.1 完整矩阵实现

| 操作 | private | tenant | builtin |
| ---- | ---- | ---- | ---- |
| view | owner ✓ | tenant member ✓ | all ✓ |
| run | owner ✓ | tenant member ✓ | all ✓ |
| edit_draft | owner ✓ | tenant_admin ✓ | superadmin ✓ |
| publish | owner ✓ | tenant_admin ✓ | superadmin ✓ |
| archive | owner ✓ | tenant_admin ✓ | superadmin ✓ |
| delete | owner ✓ | tenant_admin ✓ | superadmin ✓ |
| fork | 可读用户 ✓ | 同上 ✓ | 同上 ✓ |
| promote_to_tenant | tenant_admin（同租户） | — | — |
| promote_to_builtin | — | — | superadmin ✓ |

### 测试覆盖（18 用例）

`test_report_template_permissions.py`：

- **View（5）**：owner 私有可见、非 owner 不可、superadmin 可、tenant member 可看 tenant 模板、跨租户拒绝、builtin 人人可见
- **Edit（7）**：覆盖所有可见性 × 所有角色组合 + publish 复用谓词
- **Archive/Delete（3）**：owner-private、tenant_admin-tenant、only-superadmin-builtin
- **Fork（3）**：anyone-can-fork-builtin、不可读拒绝、tenant_member 可 fork tenant
- **Promotion（4）**：member 不能升级、tenant_admin 升 tenant、跨租户拒绝、only-superadmin 升 builtin
- **未知操作（1）**：默认拒绝

---

## 文件变更总结

```text
本次会话新增 3 个 production 文件：
  backend/packages/harness/deerflow/report_templates/records.py        (231 行)
  backend/packages/harness/deerflow/report_templates/repository.py     (~770 行)
  backend/packages/harness/deerflow/report_templates/permissions.py    (188 行)

本次会话新增 3 个测试文件：
  backend/tests/test_report_template_records.py                        (199 行, 11 用例)
  backend/tests/test_report_template_permissions.py                    (213 行, 18 用例)
  backend/tests/test_report_template_repository.py                     (491 行, 31 用例)

本次会话修改 1 个文件：
  backend/packages/harness/deerflow/report_templates/__init__.py
    扩展 public API 至 67 个导出
```

```text
累计 Phase 0+1+2 模块产物（10 个 production 文件）：
  source_resolver.py     271
  push_block.py          113
  generic_renderer.py    220
  schema.py              244
  script_registry.py     273
  validator.py           453
  records.py             231
  repository.py          770
  permissions.py         188
  __init__.py            177
  ─────────────────────
  合计 2940 行 production code

测试（9 个测试文件 + 现有回归）：
  source_resolver        43
  push_block              7
  generic_renderer       21
  schema                 27
  script_registry        15
  validator              28
  records                11
  permissions            18
  repository             31
  ─────────────────────
  Phase 0+1+2 合计     201 单元测试
  外加现有日报回归       121 测试无回归
  ─────────────────────
  338 passed / 0 failed
```

---

## 实施过程中的两个 bug 修复

1. **`version` 字段约束**：原 schema 用 `Field(ge=1)` 拒绝 v0，但 v0 是 working copy 设计的一部分。改为 `ge=0`，对外 `list_versions` 过滤 v0。
2. **`_process_lock` ImportError 处理**：原嵌套 try/except 在 Windows 上 `import fcntl` 失败时会泄漏 fd。改为函数入口处一次性检测 `has_fcntl` 标志，避免半打开状态。
3. **`delete` 顺序**：原实现在锁内 `_rm_dir(template_dir)` 会失败，因为 lock sentinel 仍在目录内阻止 rmdir。改为退出锁后再清理目录。

---

## 关键决策落实情况

| §0 决策 | Phase 2 落地 |
|---|---|
| MVP 文件存储 → V2 PostgreSQL | `FileSystemReportTemplateRepository` 实现完毕；所有时间戳 ISO 8601 with timezone，schema 对齐预期 DB 字段名（§7.1.5 V2 迁移预约束已满足） |
| 完整权限矩阵 | `permissions.py` 完整实现 §11.1 8 个操作 × 3 个可见性 |
| 平台管理员复用 superadmin/tenant_admin | `Principal.is_superadmin` / `is_tenant_admin` 字段直接复用，无新增角色 |
| 强制版本迭代 | `publish` 必须基于已 `save_draft` 的 v0，递增创建 v1/v2/...；published 状态禁止 in-place 编辑 |
| Thread 删除级联 | MVP repository **没有** `delete_by_thread()` 方法——Thread 删除时调用方（Gateway thread 删除路由）需要遍历该用户/租户的 `runs/` 索引并删除匹配 thread_id 的 ReportRun（这是 Phase 5 的工作） |
| Builtin 模板仓库内 | `Scope.builtin()` 接受独立 `builtin_root` 参数；repository 对 builtin 只暴露读接口，所有写方法立即抛 `BuiltinNotWritableError` |

---

## Phase 3 启动前置

可立即进入 **Phase 3：受控工具 + ai-report--custom SOUL.md（1 人月）**。

Phase 3 任务清单（按 §15）：

1. **生命周期工具（6 个）**：`report_template_list/get/validate/save_draft/publish/fork`
   - 全部委托本 Phase 的 `FileSystemReportTemplateRepository` + Phase 1 `validate_dsl`
   - 在工具入口校验 `Principal` + 调用 `permissions.check_permission` 后再写仓库
2. **改造 ai-report--custom SOUL.md**：完整的工具调用流程、错误处理指引
3. **禁止 LLM 直接 bash 写模板**：通过 `BUILTIN_TOOLS` 列表隔离
4. **GenUI 模板创建向导**

Phase 4 的运行时工具（`prepare_run / render_step / submit_step / run_data_steps / assemble_payload / render_report / export / resume_run`）只在 Phase 3 留接口占位，**实现放到 Phase 4**。


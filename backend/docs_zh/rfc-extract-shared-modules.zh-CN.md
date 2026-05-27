# RFC：将共享的 Skill 安装器与上传管理器提取到 Harness 层

## 1. 问题

Gateway（`app/gateway/routers/skills.py`、`uploads.py`）和 Client（`deerflow/client.py`）目前各自独立实现了相同业务逻辑：

### Skill 安装

| 逻辑 | Gateway（`skills.py`） | Client（`client.py`） |
|-------|----------------------|---------------------|
| Zip 安全检查 | `_is_unsafe_zip_member()` | 内联 `Path(info.filename).is_absolute()` |
| 符号链接过滤 | `_is_symlink_member()` | 解压后通过 `p.is_symlink()` 删除 |
| Zip Bomb 防御 | `total_size += info.file_size`（声明大小） | `total_size > 100MB`（声明大小） |
| macOS 元数据过滤 | `_should_ignore_archive_entry()` | 无 |
| Frontmatter 校验 | `_validate_skill_frontmatter()` | `_validate_skill_frontmatter()` |
| 重复检测 | `HTTPException(409)` | `ValueError` |

**两套实现，行为不一致**：Gateway 采用流式写入并统计真实解压字节数；Client 仅累加声明的 `file_size`。Gateway 在解压阶段跳过 symlink；Client 先全部解压，再遍历删除 symlink。

### 上传管理

| 逻辑 | Gateway（`uploads.py`） | Client（`client.py`） |
|-------|----------------------|---------------------|
| 目录访问 | `get_uploads_dir()` + `mkdir` | `_get_uploads_dir()` + `mkdir` |
| 文件名安全 | 内联 `Path(f).name` + 手动检查 | 无检查，直接使用 `src_path.name` |
| 重名处理 | 无（覆盖） | 无（覆盖） |
| 列表查询 | 内联 `iterdir()` | 内联 `os.scandir()` |
| 删除 | 内联 `unlink()` + traversal 检查 | 内联 `unlink()` + traversal 检查 |
| 路径穿越 | `resolve().relative_to()` | `resolve().relative_to()` |

**同一套 traversal 检查被写了两次**——任何安全修复都必须在两处同时改动。

## 2. 设计原则

### 依赖方向

```
app.gateway.routers.skills  ──┐
app.gateway.routers.uploads ──┤── calls ──→  deerflow.skills.installer
deerflow.client             ──┘              deerflow.uploads.manager
```

- 共享模块放在 harness 层（`deerflow.*`），只包含纯业务逻辑，不依赖 FastAPI
- Gateway 负责 HTTP 适配（`UploadFile` → bytes，异常 → `HTTPException`）
- Client 负责本地适配（`Path` → copy，异常 → Python 异常）
- 满足 `test_harness_boundary.py` 约束：harness 不导入 app

### 异常策略

| 共享层异常 | Gateway 映射 | Client |
|----------------------|-----------------|--------|
| `FileNotFoundError` | `HTTPException(404)` | 透传 |
| `ValueError` | `HTTPException(400)` | 透传 |
| `SkillAlreadyExistsError` | `HTTPException(409)` | 透传 |
| `PermissionError` | `HTTPException(403)` | 透传 |

将字符串匹配路由（`"already exists" in str(e)`）替换为类型化异常匹配（`SkillAlreadyExistsError`）。

## 3. 新模块

### 3.1 `deerflow.skills.installer`

```python
# 安全检查
is_unsafe_zip_member(info: ZipInfo) -> bool     # 绝对路径 / .. 穿越
is_symlink_member(info: ZipInfo) -> bool         # Unix symlink 检测
should_ignore_archive_entry(path: Path) -> bool  # __MACOSX / dotfiles

# 解压
safe_extract_skill_archive(zip_ref, dest_path, max_total_size=512MB)
  # 流式写入，累计真实字节数（非声明 file_size）
  # 双重 traversal 检查：member 级 + resolve 级

# 目录解析
resolve_skill_dir_from_archive(temp_path: Path) -> Path
  # 自动进入单层目录，过滤 macOS 元数据

# 安装入口
install_skill_from_archive(zip_path, *, skills_root=None) -> dict
  # 在扩展名校验前先做 is_file() 预检查
  # 用 SkillAlreadyExistsError 替代 ValueError

# 异常
class SkillAlreadyExistsError(ValueError)
```

### 3.2 `deerflow.uploads.manager`

```python
# 目录管理
get_uploads_dir(thread_id: str) -> Path      # 纯路径，无副作用
ensure_uploads_dir(thread_id: str) -> Path   # 创建目录（用于写路径）

# 文件名安全
normalize_filename(filename: str) -> str
  # Path.name 提取 + 拒绝 ".." / "." / 反斜杠 / >255 bytes
deduplicate_filename(name: str, seen: set) -> str
  # _N 后缀递增去重，原地修改 seen

# 路径安全
validate_path_traversal(path: Path, base: Path) -> None
  # resolve().relative_to()，失败时抛 PermissionError

# 文件操作
list_files_in_dir(directory: Path) -> dict
  # scandir + 上下文内 stat（避免重复 stat）
  # follow_symlinks=False 防止元数据泄露
  # 目录不存在时返回空列表
delete_file_safe(base_dir: Path, filename: str) -> dict
  # 先校验 traversal，再执行 unlink

# URL 辅助
upload_artifact_url(thread_id, filename) -> str   # 百分号编码，保证 HTTP 安全
upload_virtual_path(filename) -> str               # 沙箱内部路径
enrich_file_listing(result, thread_id) -> dict     # 增加 URL，size 转字符串
```

## 4. 变更内容

### 4.1 Gateway 瘦身

**`app/gateway/routers/skills.py`**：
- 移除 `_is_unsafe_zip_member`、`_is_symlink_member`、`_safe_extract_skill_archive`、`_should_ignore_archive_entry`、`_resolve_skill_dir_from_archive_root`（约 80 行）
- `install_skill` 路由简化为一次 `install_skill_from_archive(path)` 调用
- 异常映射：`SkillAlreadyExistsError → 409`、`ValueError → 400`、`FileNotFoundError → 404`

**`app/gateway/routers/uploads.py`**：
- 移除内联 `get_uploads_dir`（改为 `ensure_uploads_dir`/`get_uploads_dir`）
- `upload_files` 用 `normalize_filename()` 替代内联安全检查
- `list_uploaded_files` 使用 `list_files_in_dir()` + enrich
- `delete_uploaded_file` 使用 `delete_file_safe()` + 配套 markdown 清理

### 4.2 Client 瘦身

**`deerflow/client.py`**：
- 移除 `_get_uploads_dir` 静态方法
- 移除 `install_skill` 中约 50 行内联 zip 处理
- `install_skill` 委托给 `install_skill_from_archive()`
- `upload_files` 使用 `deduplicate_filename()` + `ensure_uploads_dir()`
- `list_uploads` 使用 `get_uploads_dir()` + `list_files_in_dir()`
- `delete_upload` 使用 `get_uploads_dir()` + `delete_file_safe()`
- `update_mcp_config` / `update_skill` 现在会重置 `_agent_config_key = None`

### 4.3 读写路径分离

| 操作 | 函数 | 会创建目录？ |
|-----------|----------|:------------:|
| upload（写） | `ensure_uploads_dir()` | 是 |
| list（读） | `get_uploads_dir()` | 否 |
| delete（读） | `get_uploads_dir()` | 否 |

读路径不再有 `mkdir` 副作用——目录不存在时返回空列表。

## 5. 安全改进

| 改进项 | 之前 | 之后 |
|-------------|--------|-------|
| Zip bomb 检测 | 累加声明 `file_size` | 流式写入，累加真实字节 |
| 符号链接处理 | Gateway 跳过 / Client 解压后删 | 统一为跳过 + 日志 |
| Traversal 检查 | 仅 member 级 | member 级 + `resolve().is_relative_to()` |
| 文件名反斜杠 | Gateway 检查 / Client 不检查 | 统一拒绝 |
| 文件名长度 | 不检查 | 拒绝 > 255 bytes（OS 限制） |
| thread_id 校验 | 无 | 拒绝不安全文件系统字符 |
| 列表 symlink 泄露 | `follow_symlinks=True`（默认） | `follow_symlinks=False` |
| 409 状态路由 | `"already exists" in str(e)` | `SkillAlreadyExistsError` 类型匹配 |
| Artifact URL 编码 | URL 使用原始文件名 | 使用 `urllib.parse.quote()` |

## 6. 备选方案

| 方案 | 不采用原因 |
|-------------|---------|
| 逻辑继续放 Gateway，Client 走 HTTP 调 Gateway | 为嵌入式 Client 增加网络依赖；违背 `DeerFlowClient` 作为进程内 API 的目标 |
| 抽象基类 + Gateway/Client 子类 | 对纯函数场景过度设计；不需要多态 |
| 全部移到 `client.py` 再让 Gateway 导入 | 破坏 harness/app 边界——Gateway 专有模型（Pydantic response types）应留在 app 层 |
| Gateway 与 Client 合并为单模块 | 两者消费场景不同（HTTP vs 进程内），适配需求不同 |

## 7. 破坏性变更

**无。** 所有公开 API（Gateway HTTP endpoint、`DeerFlowClient` 方法）保留原有签名与返回格式。`SkillAlreadyExistsError` 是 `ValueError` 子类，因此现有 `except ValueError` 仍可捕获。

## 8. 测试

| 模块 | 测试文件 | 数量 |
|--------|-----------|:-----:|
| `skills.installer` | `tests/test_skills_installer.py` | 22 |
| `uploads.manager` | `tests/test_uploads_manager.py` | 20 |
| `client` 加固 | `tests/test_client.py`（新增用例） | ~40 |
| `client` 端到端 | `tests/test_client_e2e.py`（新文件） | ~20 |

覆盖范围：unsafe zip / symlink / zip bomb / frontmatter / duplicate / extension / macOS filter / normalize / deduplicate / traversal / list / delete / agent invalidation / upload lifecycle / thread isolation / URL encoding / config pollution。

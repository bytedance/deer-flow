# RFC: 提取共享 Skill Installer 和 Upload Manager 到 Harness 层

## 1. 问题

Gateway（`app/gateway/routers/skills.py`、`uploads.py`）和 Client（`deerflow/client.py`）各自独立实现了相同的业务逻辑：

### Skill 安装

| 逻辑 | Gateway (`skills.py`) | Client (`client.py`) |
|------|----------------------|---------------------|
| zip 安全检查 | `_is_unsafe_zip_member()` | 内联 `Path(info.filename).is_absolute()` |
| symlink 过滤 | `_is_symlink_member()` | `p.is_symlink()` 事后删除 |
| zip bomb 防御 | `total_size += info.file_size` (声明值) | `total_size > 100MB` (声明值) |
| macOS 元数据过滤 | `_should_ignore_archive_entry()` | 无 |
| frontmatter 验证 | `_validate_skill_frontmatter()` | `_validate_skill_frontmatter()` |
| 重名检测 | `HTTPException(409)` | `ValueError` |

**两套实现，行为不一致**：Gateway 用流式写入检测真实解压大小，Client 用声明 `file_size` 求和；Gateway 跳过 symlink，Client 先全量解压再遍历删除。

### Upload 管理

| 逻辑 | Gateway (`uploads.py`) | Client (`client.py`) |
|------|----------------------|---------------------|
| 目录获取 | `get_uploads_dir()` + `mkdir` | `_get_uploads_dir()` + `mkdir` |
| 文件名安全 | 内联 `Path(f).name` + 手工检查 | 无检查，直接用 `src_path.name` |
| 重名处理 | 无（覆盖） | 无（覆盖） |
| 列表 | 内联 `iterdir()` | 内联 `os.scandir()` |
| 删除 | 内联 `unlink()` + traversal 检查 | 内联 `unlink()` + traversal 检查 |
| path traversal | `resolve().relative_to()` | `resolve().relative_to()` |

**同样的 traversal 检查写了两遍**，任何安全修复都需要同步到两处。

## 2. 设计原则

### 依赖方向

```
app.gateway.routers.skills  ──┐
app.gateway.routers.uploads ──┤── 调用 ──→  deerflow.skills.installer
deerflow.client             ──┘             deerflow.uploads.manager
```

- 共享模块在 harness 层（`deerflow.*`），纯业务逻辑，无 FastAPI 依赖
- Gateway 负责 HTTP 适配（`UploadFile` → bytes、异常 → `HTTPException`）
- Client 负责本地适配（`Path` → copy、异常 → Python 异常）
- 满足 `test_harness_boundary.py` 约束：harness 不 import app

### 异常策略

| 共享层异常 | Gateway 转换 | Client 直接抛 |
|-----------|-------------|--------------|
| `FileNotFoundError` | `HTTPException(404)` | 透传 |
| `ValueError` | `HTTPException(400)` | 透传 |
| `SkillAlreadyExistsError` | `HTTPException(409)` | 透传 |
| `PermissionError` | `HTTPException(403)` | 透传 |

用具体异常类型（`SkillAlreadyExistsError`）替代字符串匹配（`"already exists" in str(e)`），避免隐式耦合。

## 3. 新增模块

### 3.1 `deerflow.skills.installer`

```python
# 安全检查
is_unsafe_zip_member(info: ZipInfo) -> bool     # 绝对路径 / .. 遍历
is_symlink_member(info: ZipInfo) -> bool         # Unix symlink 检测
should_ignore_archive_entry(path: Path) -> bool  # __MACOSX / dotfiles

# 解压
safe_extract_skill_archive(zip_ref, dest_path, max_total_size=512MB)
  # 流式写入，逐 chunk 累加真实大小（vs 声明值）
  # 双重 traversal 检查：部件级 + resolve 级

# 目录定位
resolve_skill_dir_from_archive(temp_path: Path) -> Path
  # 单目录自动进入，过滤 macOS 元数据

# 安装入口
install_skill_from_archive(zip_path, *, skills_root=None) -> dict
  # 单次 is_file() 替代 exists() + is_file()（减少 stat syscall）
  # SkillAlreadyExistsError 替代 ValueError

# 异常
class SkillAlreadyExistsError(ValueError)
```

### 3.2 `deerflow.uploads.manager`

```python
# 目录管理
get_uploads_dir(thread_id: str) -> Path      # 纯路径，无副作用
ensure_uploads_dir(thread_id: str) -> Path   # 创建目录（写路径用）

# 文件名安全
normalize_filename(filename: str) -> str
  # Path.name 提取 + 拒绝 ".." / "." / 反斜杠
deduplicate_filename(name: str, seen: set) -> str
  # _N 后缀递增去重，不修改 seen

# 路径安全
validate_path_traversal(path: Path, base: Path) -> None
  # resolve().relative_to()，失败抛 PermissionError

# 文件操作
list_files_in_dir(directory: Path) -> dict
  # scandir context 内完成 stat（避免 re-stat）
  # 不存在返回空列表
delete_file_safe(base_dir: Path, filename: str) -> dict
  # 先 validate traversal，再 unlink
```

## 4. 改动列表

### 4.1 Gateway 瘦身

**`app/gateway/routers/skills.py`**:
- 删除 `_is_unsafe_zip_member`、`_is_symlink_member`、`_safe_extract_skill_archive`、`_should_ignore_archive_entry`、`_resolve_skill_dir_from_archive_root`（~80 行）
- `install_skill` 路由改为一行调用 `install_skill_from_archive(path)`
- 异常转换：`SkillAlreadyExistsError → 409`、`ValueError → 400`、`FileNotFoundError → 404`

**`app/gateway/routers/uploads.py`**:
- 删除内联 `get_uploads_dir`（替换为 `ensure_uploads_dir`/`get_uploads_dir`）
- `upload_files` 用 `normalize_filename()` 替代内联安全检查
- `list_uploaded_files` 用 `list_files_in_dir()` + enrichment
- `delete_uploaded_file` 用 `delete_file_safe()` + companion markdown 清理

### 4.2 Client 瘦身

**`deerflow/client.py`**:
- 删除 `_get_uploads_dir` 静态方法
- 删除 `install_skill` 中 ~50 行内联 zip 处理
- `install_skill` 改为调用 `install_skill_from_archive()`
- `upload_files` 使用 `deduplicate_filename()` + `ensure_uploads_dir()`
- `list_uploads` 使用 `get_uploads_dir()` + `list_files_in_dir()`
- `delete_upload` 使用 `get_uploads_dir()` + `delete_file_safe()`
- `update_mcp_config` / `update_skill` 补充 `_agent_config_key = None` 重置

### 4.3 读写路径分离

| 操作 | 函数 | mkdir |
|------|------|-------|
| upload（写） | `ensure_uploads_dir()` | 是 |
| list（读） | `get_uploads_dir()` | 否 |
| delete（读） | `get_uploads_dir()` | 否 |

读路径不再有 `mkdir` 副作用——对不存在的目录直接返回空列表。

## 5. 安全改进

| 改进 | 之前 | 之后 |
|------|------|------|
| zip bomb 检测 | 声明 `file_size` 求和 | 流式写入，累加真实字节 |
| symlink 处理 | Gateway 跳过 / Client 事后删除 | 统一跳过 + 日志 |
| traversal 双重检查 | 仅部件级 | 部件级 + `resolve().is_relative_to()` |
| 文件名反斜杠 | Gateway 检查 / Client 不检查 | 统一拒绝 |
| 409 状态码路由 | `"already exists" in str(e)` | `SkillAlreadyExistsError` 类型匹配 |

## 6. 测试

| 模块 | 测试文件 | 数量 |
|------|---------|------|
| `skills.installer` | `tests/test_skills_installer.py` | 22 |
| `uploads.manager` | `tests/test_uploads_manager.py` | 20 |
| `client` 加固 | `tests/test_client.py` (新增) | ~40 |
| `client` e2e | `tests/test_client_e2e.py` (新增) | ~20 |

覆盖：unsafe zip / symlink / zip bomb / frontmatter / duplicate / extension / macOS filter / normalize / deduplicate / traversal / list / delete / agent invalidation / upload lifecycle / thread isolation。

# RFC: 提取共享的技能安装器和上传管理器到Harness层

===================
设计思路说明
===================

**为什么需要这个RFC**：
1. **代码重复**：Gateway和Client各自独立实现了相同的业务逻辑
2. **行为不一致**：两套实现导致不同的行为，增加维护负担
3. **安全风险**：安全补丁需要在两个地方同时应用
4. **架构混乱**：违反了DRY原则和分层架构原则

**核心设计目标**：
- 消除代码重复，建立单一真相来源
- 统一安全检查和错误处理
- 保持清晰的依赖方向：harness不依赖app
- 提高代码可测试性和可维护性

## 1. 问题分析

Gateway（`app/gateway/routers/skills.py`、`uploads.py`）和Client（`deerflow/client.py`）各自独立实现了相同的业务逻辑。

**为什么这是一个问题**：
- **维护负担**：任何变更需要在两处同步
- **不一致风险**：两套实现可能产生不同的行为
- **安全漏洞**：安全补丁可能遗漏其中一个实现

### 1.1 技能安装逻辑对比

| Logic | Gateway (`skills.py`) | Client (`client.py`) |
|-------|----------------------|---------------------|
| Zip safety check | `_is_unsafe_zip_member()` | Inline `Path(info.filename).is_absolute()` |
| Symlink filtering | `_is_symlink_member()` | `p.is_symlink()` post-extraction delete |
| Zip bomb defence | `total_size += info.file_size` (declared) | `total_size > 100MB` (declared) |
| macOS metadata filter | `_should_ignore_archive_entry()` | None |
| Frontmatter validation | `_validate_skill_frontmatter()` | `_validate_skill_frontmatter()` |
| Duplicate detection | `HTTPException(409)` | `ValueError` |

**两个实现，行为不一致**：
- Gateway使用流式写入并跟踪实际解压大小
- Client累加声明的`file_size`（可能被伪造）
- Gateway在解压时跳过符号链接
- Client先解压所有内容，然后遍历删除符号链接

**为什么这种不一致是危险的**：
- **安全漏洞**：声明的文件大小可能被伪造，导致zip bomb攻击
- **性能问题**：Client的"先解压后删除"策略浪费资源
- **行为差异**：用户在不同入口获得不同的结果

### 1.2 上传管理逻辑对比

| Logic | Gateway (`uploads.py`) | Client (`client.py`) |
|-------|----------------------|---------------------|
| Directory access | `get_uploads_dir()` + `mkdir` | `_get_uploads_dir()` + `mkdir` |
| Filename safety | Inline `Path(f).name` + manual checks | No checks, uses `src_path.name` directly |
| Duplicate handling | None (overwrites) | None (overwrites) |
| Listing | Inline `iterdir()` | Inline `os.scandir()` |
| Deletion | Inline `unlink()` + traversal check | Inline `unlink()` + traversal check |
| Path traversal | `resolve().relative_to()` | `resolve().relative_to()` |

**相同的遍历检查被编写了两次** — 任何安全修复都必须同时应用到两个位置。

**为什么这是安全风险**：
- 开发者可能忘记同步修复
- 两处检查可能实现略有不同
- 增加了审计和维护成本

## 2. 设计原则

### 2.1 依赖方向设计

```
app.gateway.routers.skills  ──┐
app.gateway.routers.uploads ──┤── calls ──→  deerflow.skills.installer
deerflow.client             ──┘              deerflow.uploads.manager
```

- **共享模块位于harness层**（`deerflow.*`）：纯业务逻辑，无FastAPI依赖
- **Gateway处理HTTP适配**：`UploadFile` → bytes，异常 → `HTTPException`
- **Client处理本地适配**：`Path` → copy，异常 → Python异常
- **满足边界约束**：`test_harness_boundary.py`确保harness永不导入app

**为什么这样设计依赖方向**：
- **可移植性**：harness可以在无FastAPI的环境中独立使用
- **测试性**：纯业务逻辑更容易单元测试
- **复用性**：Client和Gateway都可以使用相同的底层实现
- **清晰边界**：明确的依赖方向避免循环依赖

### 2.2 异常处理策略

| Shared Layer Exception | Gateway Maps To | Client |
|----------------------|-----------------|--------|
| `FileNotFoundError` | `HTTPException(404)` | Propagates |
| `ValueError` | `HTTPException(400)` | Propagates |
| `SkillAlreadyExistsError` | `HTTPException(409)` | Propagates |
| `PermissionError` | `HTTPException(403)` | Propagates |

**为什么使用类型化异常**：
- 替代基于字符串的路由（`"already exists" in str(e)`）
- 使用类型化异常匹配（`SkillAlreadyExistsError`）
- 编译时类型检查，减少运行时错误
- 更清晰的错误语义和传播路径

**为什么这样设计异常映射**：
- **Gateway层**：将业务异常映射为HTTP状态码
- **Client层**：直接传播业务异常，由调用者处理
- **共享层**：定义纯业务异常，无框架依赖

## 3. 新模块设计

### 3.1 `deerflow.skills.installer` - 技能安装器

### 3.1 `deerflow.skills.installer`

```python
# Safety checks
is_unsafe_zip_member(info: ZipInfo) -> bool     # Absolute path / .. traversal
is_symlink_member(info: ZipInfo) -> bool         # Unix symlink detection
should_ignore_archive_entry(path: Path) -> bool  # __MACOSX / dotfiles

# Extraction
safe_extract_skill_archive(zip_ref, dest_path, max_total_size=512MB)
  # Streaming write, accumulates real bytes (vs declared file_size)
  # Dual traversal check: member-level + resolve-level

# Directory resolution
resolve_skill_dir_from_archive(temp_path: Path) -> Path
  # Auto-enters single directory, filters macOS metadata

# Install entry point
install_skill_from_archive(zip_path, *, skills_root=None) -> dict
  # is_file() pre-check before extension validation
  # SkillAlreadyExistsError replaces ValueError

# Exception
class SkillAlreadyExistsError(ValueError)
```

**为什么需要独立的安装器模块**：
- **安全集中化**：所有安全检查在一个地方实现和维护
- **可测试性**：纯函数更容易编写单元测试
- **复用性**：Gateway和Client都使用相同的安装逻辑
- **可扩展性**：未来添加新的安全检查只需修改一处

### 3.2 `deerflow.uploads.manager` - 上传管理器

```python
# Directory management
get_uploads_dir(thread_id: str) -> Path      # Pure path, no side effects
ensure_uploads_dir(thread_id: str) -> Path   # Creates directory (for write paths)

# Filename safety
normalize_filename(filename: str) -> str
  # Path.name extraction + rejects ".." / "." / backslash / >255 bytes
deduplicate_filename(name: str, seen: set) -> str
  # _N suffix increment for dedup, mutates seen in place

# Path safety
validate_path_traversal(path: Path, base: Path) -> None
  # resolve().relative_to(), raises PermissionError on failure

# File operations
list_files_in_dir(directory: Path) -> dict
  # scandir with stat inside context (no re-stat)
  # follow_symlinks=False to prevent metadata leakage
  # Non-existent directory returns empty list
delete_file_safe(base_dir: Path, filename: str) -> dict
  # Validates traversal first, then unlinks

# URL helpers
upload_artifact_url(thread_id, filename) -> str   # Percent-encoded for HTTP safety
upload_virtual_path(filename) -> str               # Sandbox-internal path
enrich_file_listing(result, thread_id) -> dict     # Adds URLs, stringifies sizes
```

**为什么需要独立的上传管理器**：
- **路径安全**：统一处理路径遍历攻击防护
- **文件名规范化**：处理特殊字符和重复文件名
- **读写分离**：读操作不创建目录，写操作才创建
- **URL安全**：正确编码文件名用于HTTP传输

## 4. 变更说明

### 4.1 Gateway精简

**`app/gateway/routers/skills.py`**:
- Remove `_is_unsafe_zip_member`, `_is_symlink_member`, `_safe_extract_skill_archive`, `_should_ignore_archive_entry`, `_resolve_skill_dir_from_archive_root` (~80 lines)
- `install_skill` route becomes a single call to `install_skill_from_archive(path)`
- Exception mapping: `SkillAlreadyExistsError → 409`, `ValueError → 400`, `FileNotFoundError → 404`

**`app/gateway/routers/uploads.py`**:
- Remove inline `get_uploads_dir` (replaced by `ensure_uploads_dir`/`get_uploads_dir`)
- `upload_files` uses `normalize_filename()` instead of inline safety checks
- `list_uploaded_files` uses `list_files_in_dir()` + enrichment
- `delete_uploaded_file` uses `delete_file_safe()` + companion markdown cleanup

**为什么Gateway需要精简**：
- **职责单一**：Gateway只负责HTTP适配，不处理业务逻辑
- **代码减少**：移除约80行重复的安全检查代码
- **维护简化**：业务逻辑变更只需修改harness层
- **测试聚焦**：Gateway测试专注于HTTP适配层

### 4.2 Client精简

**`deerflow/client.py`**:
- Remove `_get_uploads_dir` static method
- Remove ~50 lines of inline zip handling in `install_skill`
- `install_skill` delegates to `install_skill_from_archive()`
- `upload_files` uses `deduplicate_filename()` + `ensure_uploads_dir()`
- `list_uploads` uses `get_uploads_dir()` + `list_files_in_dir()`
- `delete_upload` uses `get_uploads_dir()` + `delete_file_safe()`
- `update_mcp_config` / `update_skill` now reset `_agent_config_key = None`

**为什么Client需要精简**：
- **一致性**：使用与Gateway相同的底层实现
- **代码减少**：移除约50行重复的zip处理代码
- **行为统一**：确保本地和HTTP调用行为一致
- **配置同步**：配置更新后正确失效缓存

### 4.3 读写路径分离设计

| Operation | Function | Creates dir? |
|-----------|----------|:------------:|
| upload (write) | `ensure_uploads_dir()` | Yes |
| list (read) | `get_uploads_dir()` | No |
| delete (read) | `get_uploads_dir()` | No |

**为什么需要读写路径分离**：
- **副作用控制**：读操作不应该有创建目录的副作用
- **明确语义**：写操作明确需要创建目录，读操作不需要
- **错误处理**：不存在的目录对于读操作应该返回空列表而非错误
- **性能优化**：避免不必要的目录创建和检查

## 5. 安全改进

| Improvement | Before | After |
|-------------|--------|-------|
| Zip bomb detection | Sum of declared `file_size` | Streaming write, accumulates real bytes |
| Symlink handling | Gateway skips / Client deletes post-extract | Unified skip + log |
| Traversal check | Member-level only | Member-level + `resolve().is_relative_to()` |
| Filename backslash | Gateway checks / Client doesn't | Unified rejection |
| Filename length | No check | Reject > 255 bytes (OS limit) |
| thread_id validation | None | Reject unsafe filesystem characters |
| Listing symlink leak | `follow_symlinks=True` (default) | `follow_symlinks=False` |
| 409 status routing | `"already exists" in str(e)` | `SkillAlreadyExistsError` type match |
| Artifact URL encoding | Raw filename in URL | `urllib.parse.quote()` |

**为什么这些安全改进很重要**：
- **Zip bomb防护**：从声明大小改为实际字节统计，防止伪造大小的攻击
- **符号链接处理**：统一跳过符号链接，防止信息泄露
- **双重遍历检查**：成员级别+解析级别，防止路径遍历攻击
- **文件名验证**：拒绝反斜杠和超长文件名，防止Windows和文件系统攻击
- **thread_id验证**：拒绝不安全的文件系统字符
- **符号链接泄露**：列表操作不跟随符号链接，防止元数据泄露
- **类型化错误**：用异常类型匹配替代字符串匹配，减少错误路由

## 6. 替代方案考虑

| Alternative | Why Not |
|-------------|---------|
| Keep logic in Gateway, Client calls Gateway via HTTP | Adds network dependency to embedded Client; defeats the purpose of `DeerFlowClient` as an in-process API |
| Abstract base class with Gateway/Client subclasses | Over-engineered for what are pure functions; no polymorphism needed |
| Move everything into `client.py` and have Gateway import it | Violates harness/app boundary — Client is in harness, but Gateway-specific models (Pydantic response types) should stay in app layer |
| Merge Gateway and Client into one module | They serve different consumers (HTTP vs in-process) with different adaptation needs |

**为什么没有选择这些替代方案**：

| 替代方案 | 未采用原因 |
|---------|-----------|
| Client通过HTTP调用Gateway | 为嵌入式Client添加网络依赖，违背了DeerFlowClient作为进程内API的设计初衷 |
| 抽象基类+Gateway/Client子类 | 对于纯函数来说过度设计，不需要多态 |
| 将所有逻辑移入client.py，由Gateway导入 | 违反harness/app边界 — Client在harness中，但Gateway特定的模型（Pydantic响应类型）应该留在app层 |
| 合并Gateway和Client为一个模块 | 它们服务于不同的消费者（HTTP vs 进程内），有不同的适配需求 |

**设计权衡说明**：
- **简单性**：纯函数比类层次结构更简单
- **边界清晰**：保持harness和app的明确边界
- **关注点分离**：HTTP适配和本地适配应该分开

## 7. 破坏性变更

**无破坏性变更**。所有公共API（Gateway HTTP端点、`DeerFlowClient`方法）保留其现有签名和返回格式。

**为什么没有破坏性变更**：
- **向后兼容**：现有代码无需修改即可工作
- **异常兼容**：`SkillAlreadyExistsError`是`ValueError`的子类，现有的`except ValueError`处理器仍然能捕获它
- **API稳定**：公共接口保持不变，只是内部实现重构
- **平滑升级**：用户可以无缝升级到新版本

## 8. 测试策略

| Module | Test File | Count |
|--------|-----------|:-----:|
| `skills.installer` | `tests/test_skills_installer.py` | 22 |
| `uploads.manager` | `tests/test_uploads_manager.py` | 20 |
| `client` hardening | `tests/test_client.py` (new cases) | ~40 |
| `client` e2e | `tests/test_client_e2e.py` (new file) | ~20 |

**为什么需要这么全面的测试覆盖**：
- **安全关键**：文件操作涉及安全风险，需要全面测试
- **边界条件**：测试各种边界情况和攻击向量
- **回归防护**：防止未来的变更破坏安全检查
- **文档价值**：测试用例作为预期行为的文档

**测试覆盖范围**：
不安全的zip / 符号链接 / zip bomb / frontmatter / 重复检测 / 扩展名验证 / macOS过滤器 / 文件名规范化 / 去重 / 路径遍历 / 列表 / 删除 / agent失效 / 上传生命周期 / 线程隔离 / URL编码 / 配置污染

---

**总结**：这个RFC通过提取共享模块到harness层，消除了代码重复，统一了安全检查，提高了代码的可维护性和安全性。设计保持了清晰的依赖方向，无破坏性变更，并通过全面的测试覆盖确保了重构的安全性。

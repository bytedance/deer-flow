# RFC: Extract Shared Skill Installer and Upload Manager into Harness

## 1. Problem

Gateway (`app/gateway/routers/skills.py`, `uploads.py`) and Client (`deerflow/client.py`) each independently implement the same business logic:

### Skill Installation

| Logic | Gateway (`skills.py`) | Client (`client.py`) |
|-------|----------------------|---------------------|
| Zip safety check | `_is_unsafe_zip_member()` | Inline `Path(info.filename).is_absolute()` |
| Symlink filtering | `_is_symlink_member()` | `p.is_symlink()` post-extraction delete |
| Zip bomb defence | `total_size += info.file_size` (declared) | `total_size > 100MB` (declared) |
| macOS metadata filter | `_should_ignore_archive_entry()` | None |
| Frontmatter validation | `_validate_skill_frontmatter()` | `_validate_skill_frontmatter()` |
| Duplicate detection | `HTTPException(409)` | `ValueError` |

**Two implementations, inconsistent behaviour**: Gateway streams writes and tracks real decompressed size; Client sums declared `file_size`. Gateway skips symlinks during extraction; Client extracts everything then walks and deletes symlinks.

### Upload Management

| Logic | Gateway (`uploads.py`) | Client (`client.py`) |
|-------|----------------------|---------------------|
| Directory access | `get_uploads_dir()` + `mkdir` | `_get_uploads_dir()` + `mkdir` |
| Filename safety | Inline `Path(f).name` + manual checks | No checks, uses `src_path.name` directly |
| Duplicate handling | None (overwrites) | None (overwrites) |
| Listing | Inline `iterdir()` | Inline `os.scandir()` |
| Deletion | Inline `unlink()` + traversal check | Inline `unlink()` + traversal check |
| Path traversal | `resolve().relative_to()` | `resolve().relative_to()` |

**The same traversal check is written twice** — any security fix must be applied to both locations.

## 2. Design Principles

### Dependency Direction

```
app.gateway.routers.skills  ──┐
app.gateway.routers.uploads ──┤── calls ──→  deerflow.skills.installer
deerflow.client             ──┘              deerflow.uploads.manager
```

- Shared modules live in the harness layer (`deerflow.*`), pure business logic, no FastAPI dependency
- Gateway handles HTTP adaptation (`UploadFile` → bytes, exceptions → `HTTPException`)
- Client handles local adaptation (`Path` → copy, exceptions → Python exceptions)
- Satisfies `test_harness_boundary.py` constraint: harness never imports app

### Exception Strategy

| Shared Layer Exception | Gateway Maps To | Client |
|----------------------|-----------------|--------|
| `FileNotFoundError` | `HTTPException(404)` | Propagates |
| `ValueError` | `HTTPException(400)` | Propagates |
| `SkillAlreadyExistsError` | `HTTPException(409)` | Propagates |
| `PermissionError` | `HTTPException(403)` | Propagates |

Replaces stringly-typed routing (`"already exists" in str(e)`) with typed exception matching (`SkillAlreadyExistsError`).

## 3. New Modules

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

### 3.2 `deerflow.uploads.manager`

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

## 4. Changes

### 4.1 Gateway Slimming

**`app/gateway/routers/skills.py`**:
- Remove `_is_unsafe_zip_member`, `_is_symlink_member`, `_safe_extract_skill_archive`, `_should_ignore_archive_entry`, `_resolve_skill_dir_from_archive_root` (~80 lines)
- `install_skill` route becomes a single call to `install_skill_from_archive(path)`
- Exception mapping: `SkillAlreadyExistsError → 409`, `ValueError → 400`, `FileNotFoundError → 404`

**`app/gateway/routers/uploads.py`**:
- Remove inline `get_uploads_dir` (replaced by `ensure_uploads_dir`/`get_uploads_dir`)
- `upload_files` uses `normalize_filename()` instead of inline safety checks
- `list_uploaded_files` uses `list_files_in_dir()` + enrichment
- `delete_uploaded_file` uses `delete_file_safe()` + companion markdown cleanup

### 4.2 Client Slimming

**`deerflow/client.py`**:
- Remove `_get_uploads_dir` static method
- Remove ~50 lines of inline zip handling in `install_skill`
- `install_skill` delegates to `install_skill_from_archive()`
- `upload_files` uses `deduplicate_filename()` + `ensure_uploads_dir()`
- `list_uploads` uses `get_uploads_dir()` + `list_files_in_dir()`
- `delete_upload` uses `get_uploads_dir()` + `delete_file_safe()`
- `update_mcp_config` / `update_skill` now reset `_agent_config_key = None`

### 4.3 Read/Write Path Separation

| Operation | Function | Creates dir? |
|-----------|----------|:------------:|
| upload (write) | `ensure_uploads_dir()` | Yes |
| list (read) | `get_uploads_dir()` | No |
| delete (read) | `get_uploads_dir()` | No |

Read paths no longer have `mkdir` side effects — non-existent directories return empty lists.

## 5. Security Improvements

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

## 6. Alternatives Considered

| Alternative | Why Not |
|-------------|---------|
| Keep logic in Gateway, Client calls Gateway via HTTP | Adds network dependency to embedded Client; defeats the purpose of `DeerFlowClient` as an in-process API |
| Abstract base class with Gateway/Client subclasses | Over-engineered for what are pure functions; no polymorphism needed |
| Move everything into `client.py` and have Gateway import it | Violates harness/app boundary — Client is in harness, but Gateway-specific models (Pydantic response types) should stay in app layer |
| Merge Gateway and Client into one module | They serve different consumers (HTTP vs in-process) with different adaptation needs |

## 7. Breaking Changes

**None.** All public APIs (Gateway HTTP endpoints, `DeerFlowClient` methods) retain their existing signatures and return formats. The `SkillAlreadyExistsError` is a subclass of `ValueError`, so existing `except ValueError` handlers still catch it.

## 8. Tests

| Module | Test File | Count |
|--------|-----------|:-----:|
| `skills.installer` | `tests/test_skills_installer.py` | 22 |
| `uploads.manager` | `tests/test_uploads_manager.py` | 20 |
| `client` hardening | `tests/test_client.py` (new cases) | ~40 |
| `client` e2e | `tests/test_client_e2e.py` (new file) | ~20 |

Coverage: unsafe zip / symlink / zip bomb / frontmatter / duplicate / extension / macOS filter / normalize / deduplicate / traversal / list / delete / agent invalidation / upload lifecycle / thread isolation / URL encoding / config pollution.

# Upload Collision Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every DeerFlow upload ingress preserve same-name files under concurrent writes while isolating generated Markdown so conversion and deletion never overwrite or remove user uploads.

**Architecture:** A shared upload manager stages complete payloads and publishes them with an atomic hard-link no-replace primitive, returning the actual `_N` filename. A focused layout module maps each primary upload to a system-owned `.upload-conversions/<full-primary-name>.md` asset, and a conversion wrapper publishes that asset atomically. Gateway, embedded client, generic IM, Feishu, DingTalk, and WeChat download staging become transport adapters over these shared primitives.

**Tech Stack:** Python 3.12+, pathlib/os/tempfile/shutil, asyncio, FastAPI/Pydantic, pytest/pytest-asyncio, unittest.mock, Ruff.

## Global Constraints

- Primary names follow `name.ext`, `name_1.ext`, `name_2.ext`; the suffix is inserted before only the final extension.
- When a collision suffix would exceed 255 UTF-8 bytes, only the stem is shortened at a valid UTF-8 boundary; the final extension and `_N` marker are preserved.
- A successful publication must expose a complete file and must never replace an existing upload, symlink, directory, FIFO, or hard-linked file.
- Atomic no-replace support is required. Unsupported storage fails explicitly instead of falling back to scan-then-replace or a partially visible copy.
- Primary uploads remain under `<thread>/user-data/uploads/<actual-primary-filename>`.
- Generated Markdown lives at `<thread>/user-data/.upload-conversions/<actual-primary-filename>.md`.
- Conversion identity includes the primary extension, so `report.pdf` and `report.docx` have distinct Markdown assets.
- API and client results return the actual primary and generated paths; consumers must not derive a sibling Markdown path.
- Deletion removes only the selected primary and its exact generated asset. Legacy `uploads/<stem>.md` files are preserved.
- All filesystem work reached from async request/channel code stays behind `run_file_io` or `asyncio.to_thread`.
- No new dependency is introduced.

---

## File Map

- Create `backend/packages/harness/deerflow/uploads/layout.py`: pure primary/conversion physical path, virtual path, and artifact URL mapping.
- Create `backend/packages/harness/deerflow/uploads/conversion.py`: conversion staging and atomic publication into the owned namespace.
- Modify `backend/packages/harness/deerflow/uploads/manager.py`: shared staging object, atomic no-replace publication, byte/copy adapters, exact deletion, stale-stage cleanup.
- Modify `backend/packages/harness/deerflow/uploads/__init__.py`: export the new shared interfaces and retain compatible URL helpers.
- Modify `backend/app/gateway/routers/uploads.py`: stream into shared staging, use returned filenames, publish conversions in the owned namespace, sync exact paths.
- Modify `backend/packages/harness/deerflow/client.py`: replace direct `shutil.copy2` and request-local naming with shared publication and conversion.
- Modify `backend/app/channels/manager.py`: replace scan-then-write inbound attachment persistence with shared publication.
- Modify `backend/app/channels/dingtalk.py`: replace the per-instance scan/claim/write sequence with shared publication.
- Modify `backend/packages/harness/deerflow/utils/file_outline.py`: read verified direct Markdown primaries; for every other format resolve owned conversion paths instead of guessing siblings.
- Modify upload, router, client, channel, outline, middleware, list-tool, and blocking-I/O tests named in the tasks below.
- Modify `README.md`, `backend/AGENTS.md`, `backend/docs/API.md`, `backend/docs/FILE_UPLOAD.md`, `backend/docs/PATH_EXAMPLES.md`, and `backend/docs/rfc-extract-shared-modules.md`: document the invariant and exact paths.

---

### Task 1: Shared Layout and Atomic Primary Publication

**Files:**
- Create: `backend/packages/harness/deerflow/uploads/layout.py`
- Modify: `backend/packages/harness/deerflow/uploads/manager.py`
- Modify: `backend/packages/harness/deerflow/uploads/__init__.py`
- Test: `backend/tests/test_uploads_manager.py`

**Interfaces:**
- Produces: `conversion_dir_for_uploads(uploads_dir: Path) -> Path`
- Produces: `conversion_path_for_upload(upload_path: Path) -> Path`
- Produces: `conversion_virtual_path(filename: str) -> str`
- Produces: `artifact_url_for_virtual_path(thread_id: str, virtual_path: str) -> str`
- Produces: `AtomicUploadPublishError(UnsafeUploadPathError)`
- Produces: `StagedUpload(base_dir: Path, path: Path, handle: BinaryIO)`
- Produces: `create_upload_staging_file(base_dir: Path) -> StagedUpload`
- Produces: `abort_staged_upload(staged: StagedUpload) -> None`
- Produces: `publish_staged_upload(staged: StagedUpload, preferred_filename: str) -> Path`
- Produces: `publish_upload_bytes(base_dir: Path, preferred_filename: str, data: bytes) -> Path`
- Produces: `publish_upload_copy(base_dir: Path, preferred_filename: str, source_path: Path) -> Path`
- Preserves: `write_upload_file_no_symlink(...)` as a compatibility wrapper with new no-overwrite semantics.

- [ ] **Step 1: Write failing layout and publication tests**

Replace the overwrite expectation in `TestWriteUploadFileNoSymlink` and add these cases:

```python
from concurrent.futures import ThreadPoolExecutor

from deerflow.uploads.layout import (
    artifact_url_for_virtual_path,
    conversion_path_for_upload,
    conversion_virtual_path,
)
from deerflow.uploads.manager import AtomicUploadPublishError, publish_upload_bytes


def test_conversion_layout_uses_full_primary_name(tmp_path):
    upload = tmp_path / "user-data" / "uploads" / "report.pdf"
    assert conversion_path_for_upload(upload) == (
        tmp_path / "user-data" / ".upload-conversions" / "report.pdf.md"
    )
    assert conversion_virtual_path("report.pdf") == (
        "/mnt/user-data/.upload-conversions/report.pdf.md"
    )
    assert artifact_url_for_virtual_path(
        "thread-1", conversion_virtual_path("report #1.pdf")
    ) == (
        "/api/threads/thread-1/artifacts/mnt/user-data/"
        ".upload-conversions/report%20%231.pdf.md"
    )


def test_existing_regular_file_is_renamed_not_overwritten(tmp_path):
    original = tmp_path / "notes.txt"
    original.write_bytes(b"old")

    published = publish_upload_bytes(tmp_path, "notes.txt", b"new")

    assert published == tmp_path / "notes_1.txt"
    assert original.read_bytes() == b"old"
    assert published.read_bytes() == b"new"


def test_existing_symlink_is_preserved_and_skipped(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"protected")
    (tmp_path / "notes.txt").symlink_to(outside)

    published = publish_upload_bytes(tmp_path, "notes.txt", b"new")

    assert published.name == "notes_1.txt"
    assert (tmp_path / "notes.txt").is_symlink()
    assert outside.read_bytes() == b"protected"
    assert published.read_bytes() == b"new"


def test_parallel_publication_preserves_every_payload(tmp_path):
    payloads = [f"payload-{i}".encode() for i in range(12)]

    with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
        paths = list(
            pool.map(lambda payload: publish_upload_bytes(tmp_path, "same.txt", payload), payloads)
        )

    assert {path.name for path in paths} == {
        "same.txt",
        *(f"same_{i}.txt" for i in range(1, len(payloads))),
    }
    assert {path.read_bytes() for path in paths} == set(payloads)
    assert not list(tmp_path.glob(".upload-*.part"))


def test_unsupported_atomic_publish_fails_and_cleans_stage(tmp_path):
    with patch(
        "deerflow.uploads.manager.os.link",
        side_effect=OSError(errno.EOPNOTSUPP, "hard links unsupported"),
    ):
        with pytest.raises(AtomicUploadPublishError, match="atomic no-replace"):
            publish_upload_bytes(tmp_path, "same.txt", b"payload")

    assert not (tmp_path / "same.txt").exists()
    assert not list(tmp_path.glob(".upload-*.part"))


@pytest.mark.parametrize(
    ("name", "existing", "expected"),
    [
        ("archive.tar.gz", "archive.tar.gz", "archive.tar_1.gz"),
        ("README", "README", "README_1"),
        (".env", ".env", ".env_1"),
    ],
)
def test_suffix_is_inserted_before_final_extension(tmp_path, name, existing, expected):
    (tmp_path / existing).write_bytes(b"old")
    assert publish_upload_bytes(tmp_path, name, b"new").name == expected


def test_collision_suffix_keeps_filename_within_255_utf8_bytes(tmp_path):
    name = f"{'é' * 125}.txt"
    assert len(name.encode("utf-8")) == 254
    (tmp_path / name).write_bytes(b"old")

    published = publish_upload_bytes(tmp_path, name, b"new")

    assert published.name.endswith("_1.txt")
    assert len(published.name.encode("utf-8")) <= 255
    assert published.read_bytes() == b"new"
```

Delete the obsolete tests that assert `open_upload_file_no_symlink` uses
`O_NOFOLLOW`, `O_NONBLOCK`, or the Windows dual-`lstat` fallback. The final
destination is no longer opened for writing; the hard-link no-replace tests
above become the security contract. Retain the FIFO, hard-link, traversal,
listing, and stale-stage cases, updating them to expect collision renaming or
explicit atomic-publication failure as appropriate.

- [ ] **Step 2: Run the new tests and confirm the current implementation fails**

Run:

```bash
cd backend
uv run pytest tests/test_uploads_manager.py -q
```

Expected: failures show that existing regular files are overwritten, concurrent calls collapse onto one name, and the new layout/publication interfaces do not exist.

- [ ] **Step 3: Implement the pure layout helpers**

Create `uploads/layout.py` with the exact mapping contract:

```python
from pathlib import Path
from urllib.parse import quote

from deerflow.config.paths import VIRTUAL_PATH_PREFIX

UPLOAD_CONVERSIONS_DIRNAME = ".upload-conversions"


def conversion_dir_for_uploads(uploads_dir: Path) -> Path:
    return uploads_dir.parent / UPLOAD_CONVERSIONS_DIRNAME


def conversion_path_for_upload(upload_path: Path) -> Path:
    return conversion_dir_for_uploads(upload_path.parent) / f"{upload_path.name}.md"


def upload_virtual_path(filename: str) -> str:
    return f"{VIRTUAL_PATH_PREFIX}/uploads/{filename}"


def conversion_virtual_path(filename: str) -> str:
    return f"{VIRTUAL_PATH_PREFIX}/{UPLOAD_CONVERSIONS_DIRNAME}/{filename}.md"


def artifact_url_for_virtual_path(thread_id: str, virtual_path: str) -> str:
    encoded_path = quote(virtual_path, safe="/")
    return f"/api/threads/{thread_id}/artifacts{encoded_path}"
```

- [ ] **Step 4: Implement staged-file lifecycle and candidate generation**

Implement publication in `uploads/manager.py` around a closed-or-closeable staging handle:

```python
class AtomicUploadPublishError(UnsafeUploadPathError):
    """Raised when storage cannot honor atomic no-replace publication."""


@dataclass(slots=True)
class StagedUpload:
    base_dir: Path
    path: Path
    handle: BinaryIO


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _filename_candidates(name: str) -> Iterator[str]:
    yield name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while True:
        marker = f"_{counter}"
        max_stem_bytes = 255 - len(marker.encode()) - len(suffix.encode("utf-8"))
        if max_stem_bytes < 1:
            raise AtomicUploadPublishError("Filename suffix leaves no room for collision marker")
        yield f"{_truncate_utf8(stem, max_stem_bytes)}{marker}{suffix}"
        counter += 1


def publish_staged_upload(staged: StagedUpload, preferred_filename: str) -> Path:
    safe_name = normalize_filename(preferred_filename)
    staged.handle.close()
    try:
        for candidate_name in _filename_candidates(safe_name):
            candidate = staged.base_dir / candidate_name
            try:
                os.link(staged.path, candidate, follow_symlinks=False)
            except FileExistsError:
                continue
            except OSError as exc:
                raise AtomicUploadPublishError(
                    f"Storage does not support atomic no-replace publication: {exc}"
                ) from exc
            staged.path.unlink()
            return candidate
    except Exception:
        staged.path.unlink(missing_ok=True)
        raise
```

- [ ] **Step 5: Add staging validation and byte/copy convenience functions**

Before linking, validate that the staging entry is a direct child of `base_dir`, is a regular non-symlink file, and has one link. Create staging with `tempfile.mkstemp(..., dir=base_dir)` and mode `0o600`. Implement byte and source-copy helpers with `try/except` cleanup; `publish_upload_copy` copies contents into staging instead of preserving source ownership metadata.

```python
def publish_upload_bytes(base_dir: Path, preferred_filename: str, data: bytes) -> Path:
    staged = create_upload_staging_file(base_dir)
    try:
        staged.handle.write(data)
        return publish_staged_upload(staged, preferred_filename)
    except Exception:
        abort_staged_upload(staged)
        raise


def publish_upload_copy(
    base_dir: Path, preferred_filename: str, source_path: Path
) -> Path:
    staged = create_upload_staging_file(base_dir)
    try:
        with source_path.open("rb") as source:
            shutil.copyfileobj(source, staged.handle)
        return publish_staged_upload(staged, preferred_filename)
    except Exception:
        abort_staged_upload(staged)
        raise
```

- [ ] **Step 6: Wire compatibility wrappers and exports**

Update `upload_artifact_url` to call `artifact_url_for_virtual_path(thread_id, upload_virtual_path(filename))`. Export the new interfaces from `uploads/__init__.py`. Keep `claim_unique_filename` only for compatibility tests and external imports; no ingress adapter will use it after Task 5.

```python
def write_upload_file_no_symlink(base_dir: Path, filename: str, data: bytes) -> Path:
    return publish_upload_bytes(base_dir, filename, data)


def upload_artifact_url(thread_id: str, filename: str) -> str:
    return artifact_url_for_virtual_path(thread_id, upload_virtual_path(filename))
```

- [ ] **Step 7: Run manager tests and confirm green**

Run:

```bash
cd backend
uv run pytest tests/test_uploads_manager.py -q
```

Expected: all manager tests pass, including the concurrent payload-preservation test.

- [ ] **Step 8: Commit the shared publication invariant**

```bash
git add backend/packages/harness/deerflow/uploads/layout.py \
  backend/packages/harness/deerflow/uploads/manager.py \
  backend/packages/harness/deerflow/uploads/__init__.py \
  backend/tests/test_uploads_manager.py
git commit -m "fix: publish uploads without overwriting"
```

---

### Task 2: Owned Conversion Publication, Outline Lookup, and Exact Deletion

**Files:**
- Create: `backend/packages/harness/deerflow/uploads/conversion.py`
- Modify: `backend/packages/harness/deerflow/uploads/layout.py`
- Modify: `backend/packages/harness/deerflow/uploads/manager.py`
- Modify: `backend/packages/harness/deerflow/uploads/__init__.py`
- Modify: `backend/packages/harness/deerflow/utils/file_outline.py`
- Test: `backend/tests/test_upload_conversion.py`
- Test: `backend/tests/test_uploads_manager.py`
- Test: `backend/tests/test_uploads_middleware_core_logic.py`
- Test: `backend/tests/test_list_uploaded_files_tool.py`

**Interfaces:**
- Consumes: Task 1 `StagedUpload`, `create_upload_staging_file`, `abort_staged_upload`, and layout helpers.
- Produces: `UnsafeConversionPathError(ValueError)` in `uploads/layout.py`.
- Produces: `ensure_conversion_dir(uploads_dir: Path) -> Path`, which rejects a pre-existing symlink or non-directory.
- Produces: `validate_conversion_dir(uploads_dir: Path) -> Path | None`, which returns `None` when absent and rejects unsafe existing entries without creating anything.
- Produces: `existing_conversion_path_for_upload(upload_path: Path) -> Path | None`, which returns only a regular single-link generated file.
- Produces: `replace_system_owned_staged_file(staged: StagedUpload, filename: str) -> Path` for atomic replace only inside the conversion namespace.
- Produces: `convert_uploaded_file_to_markdown(upload_path: Path) -> Path | None`.
- Changes: `delete_file_safe(base_dir: Path, filename: str) -> dict` deletes the exact owned conversion without an extension-set argument.
- Changes: `extract_outline_for_file(file_path: Path)` reads a verified regular primary when `file_path` is Markdown; otherwise it reads `conversion_path_for_upload(file_path)` only.

- [ ] **Step 1: Write failing conversion ownership, deletion, and outline tests**

Create `tests/test_upload_conversion.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from deerflow.uploads.conversion import convert_uploaded_file_to_markdown
from deerflow.uploads.layout import conversion_path_for_upload


@pytest.mark.asyncio
async def test_conversion_uses_owned_full_filename_target(tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    pdf = uploads / "report.pdf"
    docx = uploads / "report.docx"
    pdf.write_bytes(b"PDF")
    docx.write_bytes(b"DOCX")

    async def fake_convert(source: Path, output_path: Path | None = None):
        assert output_path is not None
        output_path.write_text(f"from:{source.name}", encoding="utf-8")
        return output_path

    with patch(
        "deerflow.uploads.conversion.convert_file_to_markdown",
        AsyncMock(side_effect=fake_convert),
    ):
        pdf_md = await convert_uploaded_file_to_markdown(pdf)
        docx_md = await convert_uploaded_file_to_markdown(docx)

    assert pdf_md == conversion_path_for_upload(pdf)
    assert docx_md == conversion_path_for_upload(docx)
    assert pdf_md.read_text(encoding="utf-8") == "from:report.pdf"
    assert docx_md.read_text(encoding="utf-8") == "from:report.docx"


@pytest.mark.asyncio
async def test_conversion_failure_cleans_stage_and_keeps_user_markdown(tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    source = uploads / "report.pdf"
    source.write_bytes(b"PDF")
    user_markdown = uploads / "report.md"
    user_markdown.write_text("user", encoding="utf-8")

    with patch(
        "deerflow.uploads.conversion.convert_file_to_markdown",
        AsyncMock(return_value=None),
    ):
        assert await convert_uploaded_file_to_markdown(source) is None

    assert user_markdown.read_text(encoding="utf-8") == "user"
    conversion_dir = uploads.parent / ".upload-conversions"
    assert not list(conversion_dir.glob(".upload-*.part"))


@pytest.mark.asyncio
async def test_conversion_directory_symlink_is_rejected(tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    source = uploads / "report.pdf"
    source.write_bytes(b"PDF")
    outside = tmp_path / "outside"
    outside.mkdir()
    (uploads.parent / ".upload-conversions").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="conversion directory"):
        await convert_uploaded_file_to_markdown(source)

    assert list(outside.iterdir()) == []
```

Add exact deletion coverage to `test_uploads_manager.py`:

```python
def test_delete_removes_owned_conversion_but_preserves_legacy_sibling(tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"PDF")
    legacy_or_user = uploads / "report.md"
    legacy_or_user.write_text("user markdown", encoding="utf-8")
    owned = conversion_path_for_upload(primary)
    owned.parent.mkdir()
    owned.write_text("generated", encoding="utf-8")

    delete_file_safe(uploads, "report.pdf")

    assert not primary.exists()
    assert not owned.exists()
    assert legacy_or_user.read_text(encoding="utf-8") == "user markdown"


def test_delete_rejects_symlink_instead_of_unlinking_target(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("protected", encoding="utf-8")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "report.pdf").symlink_to(outside)

    with pytest.raises(UnsafeUploadPathError):
        delete_file_safe(uploads, "report.pdf")

    assert outside.read_text(encoding="utf-8") == "protected"


def test_delete_rejects_path_components(tmp_path):
    (tmp_path / "report.pdf").write_bytes(b"PDF")

    with pytest.raises(PathTraversalError):
        delete_file_safe(tmp_path, "folder/report.pdf")

    assert (tmp_path / "report.pdf").exists()
```

Update outline fixtures in both middleware/list-tool suites so `report.pdf.md` is created under `uploads.parent / ".upload-conversions"`. Add negative assertions that a legacy `uploads/report.md` alone does not produce an outline and that a symlink planted at the owned conversion path is ignored without reading its target.

- [ ] **Step 2: Run the new ownership tests and confirm red**

Run:

```bash
cd backend
uv run pytest tests/test_upload_conversion.py \
  tests/test_uploads_manager.py \
  tests/test_uploads_middleware_core_logic.py \
  tests/test_list_uploaded_files_tool.py -q
```

Expected: the conversion module is missing; current deletion removes `report.md`; current outline lookup reads the sibling path.

- [ ] **Step 3: Implement the guarded conversion-directory helpers**

Add the directory guard in `layout.py`:

```python
def validate_conversion_dir(uploads_dir: Path) -> Path | None:
    conversion_dir = conversion_dir_for_uploads(uploads_dir)
    try:
        st = os.lstat(conversion_dir)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise UnsafeConversionPathError("Unsafe upload conversion directory")
    return conversion_dir


def ensure_conversion_dir(uploads_dir: Path) -> Path:
    conversion_dir = conversion_dir_for_uploads(uploads_dir)
    try:
        conversion_dir.mkdir(mode=0o755)
    except FileExistsError:
        pass
    validated = validate_conversion_dir(uploads_dir)
    if validated is None:
        raise UnsafeConversionPathError("Upload conversion directory disappeared")
    return validated


def existing_conversion_path_for_upload(upload_path: Path) -> Path | None:
    if validate_conversion_dir(upload_path.parent) is None:
        return None
    candidate = conversion_path_for_upload(upload_path)
    try:
        st = os.lstat(candidate)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise UnsafeConversionPathError("Unsafe upload conversion file")
    return candidate
```

Keep the upload exception definition in `manager.py` to avoid a layout/manager import cycle by placing the guard's local exception in `layout.py` as `UnsafeConversionPathError(ValueError)` and translating it only where HTTP behavior needs `UnsafeUploadPathError`.

- [ ] **Step 4: Implement conversion staging and publication**

Implement `convert_uploaded_file_to_markdown` as:

```python
async def convert_uploaded_file_to_markdown(upload_path: Path) -> Path | None:
    conversion_dir = ensure_conversion_dir(upload_path.parent)
    target = conversion_path_for_upload(upload_path)
    staged = create_upload_staging_file(conversion_dir)
    staged.handle.close()
    try:
        result = await convert_file_to_markdown(upload_path, output_path=staged.path)
        if result is None:
            abort_staged_upload(staged)
            return None
        if result != staged.path:
            raise UnsafeConversionPathError("Converter returned an unexpected output path")
        return replace_system_owned_staged_file(staged, target.name)
    except Exception:
        abort_staged_upload(staged)
        raise
```

- [ ] **Step 5: Add the system-owned atomic replace primitive**

`replace_system_owned_staged_file` validates the staging file and its direct parent, requires `staged.base_dir.name == UPLOAD_CONVERSIONS_DIRNAME`, closes the handle idempotently, then calls `os.replace(staged.path, staged.base_dir / normalize_filename(filename))`. It is used only by `uploads/conversion.py`; primary upload code never calls it.

```python
def replace_system_owned_staged_file(staged: StagedUpload, filename: str) -> Path:
    if staged.base_dir.name != UPLOAD_CONVERSIONS_DIRNAME:
        raise UnsafeUploadPathError("System-owned replace requires conversion directory")
    _validate_staged_upload(staged)
    staged.handle.close()
    target = staged.base_dir / normalize_filename(filename)
    os.replace(staged.path, target)
    return target
```

- [ ] **Step 6: Replace guessed companion deletion with exact deletion**

Change `delete_file_safe` to normalize the basename and inspect the primary with `os.lstat`, rejecting symlinks/non-regular/multi-link entries. Before unlinking anything, call `validate_conversion_dir(uploads_dir)`; when it returns a directory, identify only `conversion_path_for_upload(primary)`, and when it returns `None`, do not create the directory. Then unlink the primary and the exact owned conversion. Do not call `with_suffix(".md")` anywhere in upload deletion.

```python
safe_name = normalize_filename(filename)
if safe_name != filename:
    raise PathTraversalError("Path traversal detected")
primary = base_dir / safe_name
primary_stat = os.lstat(primary)
if not stat.S_ISREG(primary_stat.st_mode) or primary_stat.st_nlink != 1:
    raise UnsafeUploadPathError(f"Unsafe upload file: {safe_name}")
owned_conversion = existing_conversion_path_for_upload(primary)
primary.unlink()
if owned_conversion is not None:
    owned_conversion.unlink(missing_ok=True)
```

- [ ] **Step 7: Point outline lookup and stale-stage cleanup at the owned namespace**

Change `extract_outline_for_file` to:

```python
try:
    md_path = existing_conversion_path_for_upload(file_path)
except UnsafeConversionPathError:
    logger.warning("Ignoring unsafe generated conversion for %s", file_path.name)
    return [], []
if md_path is None:
    return [], []
```

Extend stale-stage cleanup to scan both `user-data/uploads` and existing real `user-data/.upload-conversions` directories without following symlinks.

```python
def _iter_upload_storage_dirs(base_dir: Path):
    for user_data in base_dir.glob("threads/*/user-data"):
        yield user_data / "uploads"
        yield user_data / UPLOAD_CONVERSIONS_DIRNAME
    for user_data in base_dir.glob("users/*/threads/*/user-data"):
        yield user_data / "uploads"
        yield user_data / UPLOAD_CONVERSIONS_DIRNAME
```

- [ ] **Step 8: Run conversion, deletion, outline, and stale-stage tests**

Run:

```bash
cd backend
uv run pytest tests/test_upload_conversion.py \
  tests/test_uploads_manager.py \
  tests/test_uploads_middleware_core_logic.py \
  tests/test_list_uploaded_files_tool.py -q
```

Expected: all selected tests pass; user/legacy sibling Markdown remains untouched.

- [ ] **Step 9: Commit generated-asset ownership**

```bash
git add backend/packages/harness/deerflow/uploads/conversion.py \
  backend/packages/harness/deerflow/uploads/layout.py \
  backend/packages/harness/deerflow/uploads/manager.py \
  backend/packages/harness/deerflow/uploads/__init__.py \
  backend/packages/harness/deerflow/utils/file_outline.py \
  backend/tests/test_upload_conversion.py \
  backend/tests/test_uploads_manager.py \
  backend/tests/test_uploads_middleware_core_logic.py \
  backend/tests/test_list_uploaded_files_tool.py
git commit -m "fix: isolate generated upload conversions"
```

---

### Task 3: Gateway Streaming, Metadata, Synchronization, and Deletion

**Files:**
- Modify: `backend/app/gateway/routers/uploads.py`
- Test: `backend/tests/test_uploads_router.py`

**Interfaces:**
- Consumes: Task 1 staging/publication functions and actual returned `Path`.
- Consumes: Task 2 `convert_uploaded_file_to_markdown` and conversion layout/URL helpers.
- Produces: unchanged `UploadResponse` schema populated with exact primary and generated paths.

- [ ] **Step 1: Write failing cross-request, concurrent, conversion, and deletion tests**

Add tests using the existing `call_unwrapped`, `_mounted_provider`, and upload fixtures:

```python
def test_separate_upload_requests_never_replace_same_name(tmp_path):
    uploads_dir = tmp_path / "user-data" / "uploads"
    uploads_dir.mkdir(parents=True)

    async def upload(payload: bytes):
        return await call_unwrapped(
            uploads.upload_files,
            "thread-local",
            request=MagicMock(),
            files=[UploadFile(filename="report.txt", file=BytesIO(payload))],
            config=SimpleNamespace(),
        )

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
    ):
        first = asyncio.run(upload(b"first"))
        second = asyncio.run(upload(b"second"))

    assert [first.files[0].filename, second.files[0].filename] == [
        "report.txt",
        "report_1.txt",
    ]
    assert (uploads_dir / "report.txt").read_bytes() == b"first"
    assert (uploads_dir / "report_1.txt").read_bytes() == b"second"


def test_concurrent_upload_requests_preserve_all_payloads(tmp_path):
    uploads_dir = tmp_path / "user-data" / "uploads"
    uploads_dir.mkdir(parents=True)
    payloads = [f"payload-{i}".encode() for i in range(8)]

    async def upload(payload: bytes):
        return await call_unwrapped(
            uploads.upload_files,
            "thread-local",
            request=MagicMock(),
            files=[UploadFile(filename="same.bin", file=BytesIO(payload))],
            config=SimpleNamespace(),
        )

    async def run_all():
        return await asyncio.gather(*(upload(payload) for payload in payloads))

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
    ):
        results = asyncio.run(run_all())

    paths = [uploads_dir / result.files[0].filename for result in results]
    assert len({path.name for path in paths}) == len(payloads)
    assert {path.read_bytes() for path in paths} == set(payloads)


def test_conversion_metadata_uses_owned_namespace_and_preserves_user_md(tmp_path):
    uploads_dir = tmp_path / "user-data" / "uploads"
    uploads_dir.mkdir(parents=True)

    async def fake_convert(path: Path):
        target = conversion_path_for_upload(path)
        target.parent.mkdir()
        target.write_text("generated", encoding="utf-8")
        return target

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
        patch.object(uploads, "_auto_convert_documents_enabled", return_value=True),
        patch.object(
            uploads,
            "convert_uploaded_file_to_markdown",
            AsyncMock(side_effect=fake_convert),
        ),
    ):
        result = asyncio.run(
            call_unwrapped(
                uploads.upload_files,
                "thread-local",
                request=MagicMock(),
                files=[
                    UploadFile(filename="notes.docx", file=BytesIO(b"DOCX")),
                    UploadFile(filename="notes.md", file=BytesIO(b"USER")),
                ],
                config=SimpleNamespace(),
            )
        )

    document, markdown = result.files
    assert document.markdown_file == "notes.docx.md"
    assert document.markdown_virtual_path == (
        "/mnt/user-data/.upload-conversions/notes.docx.md"
    )
    assert markdown.filename == "notes.md"
    assert (uploads_dir / "notes.md").read_bytes() == b"USER"
```

Update the delete route test to create both `.upload-conversions/report.pdf.md` and `uploads/report.md`, then assert only the primary and owned conversion disappear. Update non-mounted sandbox tests to assert `sandbox.update_file` receives the exact conversion virtual path and bytes.

Rewrite `test_upload_files_does_not_sync_non_local_sandbox_when_conversion_fails`: a raised conversion error is logged and treated as a non-fatal conversion miss, the primary upload remains successful, only the primary is synchronized, and no `markdown_*` fields are returned.

- [ ] **Step 2: Run Gateway tests and confirm failures describe the old behavior**

Run:

```bash
cd backend
uv run pytest tests/test_uploads_router.py -q
```

Expected: separate requests overwrite, conversion metadata points into `uploads/`, and deletion removes the sibling Markdown.

- [ ] **Step 3: Replace Gateway-local staging and naming with shared publication**

Remove `_UploadTempFile`, `_prepare_upload_destination`, `_abort_upload_temp`, `_commit_upload_temp`, `seen_filenames`, and all calls to `claim_unique_filename`.

Change `_write_upload_file_with_limits` to stage without selecting a final name, then publish after all chunks pass limits:

```python
staged = await run_file_io(create_upload_staging_file, Path(uploads_dir))
try:
    while chunk := await file.read(UPLOAD_CHUNK_SIZE):
        file_size += len(chunk)
        total_size += len(chunk)
        if file_size > max_single_file_size:
            raise HTTPException(status_code=413, detail=f"File too large: {display_filename}")
        if total_size > max_total_size:
            raise HTTPException(status_code=413, detail="Total upload size too large")
        await run_file_io(staged.handle.write, chunk)
    file_path = await run_file_io(publish_staged_upload, staged, display_filename)
except Exception:
    await run_file_io(abort_staged_upload, staged)
    raise
return file_path, file_size, total_size
```

- [ ] **Step 4: Build primary and conversion metadata from published paths**

After publication, derive `safe_filename = file_path.name`. Build primary metadata with `upload_virtual_path`/`upload_artifact_url`. For conversion metadata use:

```python
try:
    md_path = await convert_uploaded_file_to_markdown(file_path)
except Exception:
    logger.warning("Failed to convert %s to markdown", safe_filename, exc_info=True)
    md_path = None
if md_path is not None:
    md_virtual_path = conversion_virtual_path(safe_filename)
    file_info.update(
        markdown_file=md_path.name,
        markdown_path=str(md_path),
        markdown_virtual_path=md_virtual_path,
        markdown_artifact_url=artifact_url_for_virtual_path(thread_id, md_virtual_path),
    )
```

- [ ] **Step 5: Wire exact cleanup, sandbox synchronization, and deletion paths**

Append both exact physical paths to `written_paths` and both exact virtual paths to `sandbox_sync_targets`. `_delete_uploaded_file_for_thread` calls `delete_file_safe(uploads_dir, filename)` without guessing by extension.

```python
written_paths.append(file_path)
if sync_to_sandbox:
    sandbox_sync_targets.append((file_path, upload_virtual_path(file_path.name)))
if md_path is not None:
    written_paths.append(md_path)
    if sync_to_sandbox:
        sandbox_sync_targets.append((md_path, conversion_virtual_path(file_path.name)))


def _delete_uploaded_file_for_thread(thread_id: str, filename: str, user_id: str) -> dict:
    return delete_file_safe(get_uploads_dir(thread_id, user_id=user_id), filename)
```

- [ ] **Step 6: Run Gateway and blocking-I/O tests**

Run:

```bash
cd backend
uv run pytest tests/test_uploads_router.py \
  tests/blocking_io/test_uploads_router.py -q
```

Expected: all pass and no synchronous filesystem call reaches the event loop.

- [ ] **Step 7: Commit Gateway integration**

```bash
git add backend/app/gateway/routers/uploads.py \
  backend/tests/test_uploads_router.py \
  backend/tests/blocking_io
git commit -m "fix: make gateway uploads collision safe"
```

---

### Task 4: Embedded Client Conformance

**Files:**
- Modify: `backend/packages/harness/deerflow/client.py`
- Test: `backend/tests/test_client.py`

**Interfaces:**
- Consumes: `publish_upload_copy`, `convert_uploaded_file_to_markdown`, and Task 1/2 layout helpers.
- Produces: embedded upload dictionaries conforming to Gateway `UploadedFileInfo` paths and naming.

- [ ] **Step 1: Write failing repeated/concurrent client and conversion metadata tests**

Add to `TestUploads`:

```python
def test_upload_files_across_calls_never_overwrite(client, tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "same.txt"
    second = second_dir / "same.txt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    with (
        patch("deerflow.client.ensure_uploads_dir", return_value=uploads),
        patch("deerflow.client.get_uploads_dir", return_value=uploads),
    ):
        first_result = client.upload_files("thread-1", [first])
        second_result = client.upload_files("thread-1", [second])

    assert first_result["files"][0]["filename"] == "same.txt"
    assert second_result["files"][0]["filename"] == "same_1.txt"
    assert (uploads / "same.txt").read_bytes() == b"first"
    assert (uploads / "same_1.txt").read_bytes() == b"second"


def test_concurrent_client_uploads_preserve_all_payloads(client, tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    sources = []
    for index in range(8):
        source_dir = tmp_path / f"source-{index}"
        source_dir.mkdir()
        source = source_dir / "same.bin"
        source.write_bytes(f"payload-{index}".encode())
        sources.append(source)

    with (
        patch("deerflow.client.ensure_uploads_dir", return_value=uploads),
        patch("deerflow.client.get_uploads_dir", return_value=uploads),
        ThreadPoolExecutor(max_workers=len(sources)) as pool,
    ):
        results = list(
            pool.map(lambda source: client.upload_files("thread-1", [source]), sources)
        )

    names = [result["files"][0]["filename"] for result in results]
    assert len(set(names)) == len(sources)
    assert {(uploads / name).read_bytes() for name in names} == {
        source.read_bytes() for source in sources
    }
```

Rewrite the same-stem conversion test to expect `a.docx.md` and `a.pdf.md` under `.upload-conversions`, while a separately uploaded `a.md` remains in `uploads/`. Assert `markdown_virtual_path` and `markdown_artifact_url` match Gateway output.

- [ ] **Step 2: Run client tests and confirm direct copy overwrites**

Run:

```bash
cd backend
uv run pytest tests/test_client.py -k "upload" -q
```

Expected: repeated/concurrent tests fail because `shutil.copy2` replaces the first file, and conversion metadata uses sibling names.

- [ ] **Step 3: Route embedded primary files through the shared publisher**

Validate all sources up front as today, but retain only their `Path` objects; remove `seen_names` and provisional destination names. In the upload loop:

```python
dest = publish_upload_copy(uploads_dir, src_path.name, src_path)
dest_name = dest.name
info = {
    "filename": dest_name,
    "size": dest.stat().st_size,
    "path": str(dest),
    "virtual_path": upload_virtual_path(dest_name),
    "artifact_url": upload_artifact_url(thread_id, dest_name),
}
```

- [ ] **Step 4: Wire owned conversion metadata and exact deletion**

Run `convert_uploaded_file_to_markdown(dest)` through the existing single conversion executor when an event loop is active. Populate generated metadata from `conversion_virtual_path(dest_name)` and `artifact_url_for_virtual_path`. Keep conversion failure non-fatal. Change `delete_upload` to the exact `delete_file_safe(uploads_dir, filename)` contract.

```python
md_virtual_path = conversion_virtual_path(dest_name)
info["markdown_file"] = md_path.name
info["markdown_path"] = str(md_path)
info["markdown_virtual_path"] = md_virtual_path
info["markdown_artifact_url"] = artifact_url_for_virtual_path(
    thread_id, md_virtual_path
)
```

- [ ] **Step 5: Run client conformance and manager tests**

Run:

```bash
cd backend
uv run pytest tests/test_client.py -k "upload or GatewayConformance" -q
uv run pytest tests/test_uploads_manager.py tests/test_upload_conversion.py -q
```

Expected: repeated and concurrent calls preserve all files; response dictionaries validate against Gateway models.

- [ ] **Step 6: Commit embedded client integration**

```bash
git add backend/packages/harness/deerflow/client.py backend/tests/test_client.py
git commit -m "fix: preserve embedded client uploads"
```

---

### Task 5: Generic IM and DingTalk Concurrency

**Files:**
- Modify: `backend/app/channels/manager.py`
- Modify: `backend/app/channels/dingtalk.py`
- Test: `backend/tests/test_channel_file_attachments.py`
- Test: `backend/tests/test_dingtalk_channel.py`
- Test: `backend/tests/blocking_io/test_channels_ingest.py`

**Interfaces:**
- Consumes: `publish_upload_bytes(base_dir, preferred_filename, data) -> Path` and `upload_virtual_path(filename)`.
- Produces: inbound metadata and DingTalk message prefixes containing the actual published name.

- [ ] **Step 1: Write failing parallel channel tests and update planted-entry expectations**

Add a generic-channel concurrency regression:

```python
def test_concurrent_inbound_messages_with_same_name_preserve_all_bytes(tmp_path):
    from app.channels import manager

    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    payloads = [f"payload-{index}".encode() for index in range(8)]
    messages = [
        InboundMessage(
            channel_name="telegram",
            chat_id="chat-1",
            user_id="user-1",
            text="attachment",
            files=[{"type": "file", "filename": "same.txt", "_content": payload}],
        )
        for payload in payloads
    ]

    async def run_all():
        return await asyncio.gather(
            *(manager._ingest_inbound_files("thread-1", message) for message in messages)
        )

    with patch("deerflow.uploads.manager.ensure_uploads_dir", return_value=uploads_dir):
        results = _run(run_all())

    created = [batch[0] for batch in results]
    assert len({item["filename"] for item in created}) == len(payloads)
    assert {
        (uploads_dir / item["filename"]).read_bytes() for item in created
    } == set(payloads)
```

Change planted symlink/dangling-symlink expectations: the planted entry remains intact, the external target remains untouched, and the attachment succeeds as `victim_1.txt` rather than being dropped.

Add a parallel DingTalk regression:

```python
def test_concurrent_duplicate_document_names_preserve_all_bytes(tmp_path, monkeypatch):
    async def go():
        channel = DingTalkChannel(MessageBus(), config={})
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        _patch_uploads(monkeypatch, uploads)
        payloads = [f"version-{index}".encode() for index in range(8)]
        channel._download_by_code = AsyncMock(side_effect=payloads)

        paths = await asyncio.gather(
            *(
                channel._receive_single_file(
                    f"code-{index}",
                    "file",
                    "quote.xlsx",
                    "thread-1",
                    user_id="default",
                )
                for index in range(len(payloads))
            )
        )

        assert len(set(paths)) == len(payloads)
        assert {
            (uploads / path.rsplit("/", 1)[-1]).read_bytes() for path in paths
        } == set(payloads)

    _run(go())
```

Update the DingTalk planted-symlink test to expect `/uploads/image_1.png` while verifying the symlink and outside target are unchanged.

- [ ] **Step 2: Run channel tests and confirm red**

Run:

```bash
cd backend
uv run pytest tests/test_channel_file_attachments.py \
  tests/test_dingtalk_channel.py \
  tests/blocking_io/test_channels_ingest.py \
  tests/blocking_io/test_dingtalk_receive_file.py -q
```

Expected: the generic adapter's scan/write race loses payloads under concurrency; old symlink tests expect rejection instead of collision renaming.

- [ ] **Step 3: Replace generic inbound scan/claim/write with shared publication**

In `_ingest_inbound_files`, make directory preparation return only the `Path`. Normalize the requested basename, then offload one shared publication call:

```python
safe_name = normalize_filename(filename)
dest = await asyncio.to_thread(
    publish_upload_bytes,
    uploads_dir,
    safe_name,
    data,
)
created.append(
    {
        "filename": dest.name,
        "size": len(data),
        "path": upload_virtual_path(dest.name),
        "is_image": ftype == "image",
    }
)
```

- [ ] **Step 4: Replace DingTalk locking and naming with shared publication**

In DingTalk `_persist`, keep owner-scoped directory creation but replace the lock/scan/claim body with:

```python
paths.ensure_thread_dirs(thread_id, user_id=effective_user_id)
uploads_dir = paths.sandbox_uploads_dir(
    thread_id, user_id=effective_user_id
)
return publish_upload_bytes(uploads_dir, safe_filename, content)
```

Do not resolve the upload directory before publication: the shared publisher must inspect and reject a planted directory symlink itself. Remove `_file_write_lock` because the shared primitive supplies cross-thread and cross-process correctness. Keep the other DingTalk locks. Build the returned path through `upload_virtual_path(resolved_target.name)`.

- [ ] **Step 5: Refresh the channel blocking-I/O regression descriptions**

Update the blocking-I/O test module description so it names staging/publication rather than directory enumeration; keep the strict event-loop gate.

- [ ] **Step 6: Run channel, DingTalk, and blocking-I/O suites**

Run:

```bash
cd backend
uv run pytest tests/test_channel_file_attachments.py \
  tests/test_dingtalk_channel.py \
  tests/blocking_io/test_channels_ingest.py \
  tests/blocking_io/test_dingtalk_receive_file.py -q
```

Expected: all pass, including parallel same-name messages and exact advertised bytes.

- [ ] **Step 7: Commit channel integration**

```bash
git add backend/app/channels/manager.py \
  backend/app/channels/dingtalk.py \
  backend/tests/test_channel_file_attachments.py \
  backend/tests/test_dingtalk_channel.py \
  backend/tests/blocking_io/test_channels_ingest.py \
  backend/tests/blocking_io/test_dingtalk_receive_file.py
git commit -m "fix: make inbound attachments collision safe"
```

---

### Task 6: Documentation, Cleanup, and Complete Verification

**Files:**
- Modify: `README.md`
- Modify: `backend/AGENTS.md`
- Modify: `backend/docs/API.md`
- Modify: `backend/docs/FILE_UPLOAD.md`
- Modify: `backend/docs/PATH_EXAMPLES.md`
- Modify: `backend/docs/rfc-extract-shared-modules.md`
- Modify: any focused test file whose old sibling-Markdown expectation remains.

**Interfaces:**
- Consumes: all previous task interfaces.
- Produces: one documented storage/API contract and a clean, fully verified branch.

- [ ] **Step 1: Remove stale behavior assertions and dead adapter imports**

Run these audits:

```bash
rg -n "with_suffix\(\"\.md\"\)|uploads/.+\.md|claim_unique_filename|shutil\.copy2|os\.replace" \
  backend/app/gateway/routers/uploads.py \
  backend/app/channels/manager.py \
  backend/app/channels/dingtalk.py \
  backend/packages/harness/deerflow/client.py \
  backend/packages/harness/deerflow/uploads \
  backend/packages/harness/deerflow/utils/file_outline.py
rg -n "report\.md|document\.md|same directory|同一目录|companion markdown" \
  backend/tests backend/docs README.md backend/AGENTS.md
```

Expected: `claim_unique_filename`, `shutil.copy2`, and sibling `with_suffix(".md")` have no ingress/conversion/deletion call sites. Any remaining matches are compatibility helpers, low-level system-owned replace, explicit legacy-preservation tests, or documentation that this task updates.

- [ ] **Step 2: Update API, upload-guide, and path examples**

Document all of the following verbatim behaviors:

```text
Primary:   /mnt/user-data/uploads/report.pdf
Generated: /mnt/user-data/.upload-conversions/report.pdf.md
Collision: report.pdf, report_1.pdf, report_2.pdf
Deletion:  report.pdf deletes only report.pdf.md in .upload-conversions;
           /mnt/user-data/uploads/report.md is never inferred or deleted.
```

In `backend/docs/API.md` and `PATH_EXAMPLES.md`, update JSON examples so:

```json
{
  "markdown_file": "document.pdf.md",
  "markdown_path": ".deer-flow/threads/abc123/user-data/.upload-conversions/document.pdf.md",
  "markdown_virtual_path": "/mnt/user-data/.upload-conversions/document.pdf.md",
  "markdown_artifact_url": "/api/threads/abc123/artifacts/mnt/user-data/.upload-conversions/document.pdf.md"
}
```

- [ ] **Step 3: Update overview and maintainer architecture documentation**

In `README.md` and `backend/AGENTS.md`, add `.upload-conversions/` to the user-data map, state that generated assets are omitted from upload listings, and replace “single request”/“atomic replace” wording with cross-request/process atomic no-replace behavior. In the shared-modules RFC, replace request-local deduplication and guessed companion cleanup with the final manager/layout interfaces.

- [ ] **Step 4: Run focused regression suites**

Run:

```bash
cd backend
uv run pytest \
  tests/test_uploads_manager.py \
  tests/test_upload_conversion.py \
  tests/test_uploads_router.py \
  tests/test_client.py \
  tests/test_channel_file_attachments.py \
  tests/test_dingtalk_channel.py \
  tests/test_file_conversion.py \
  tests/test_uploads_middleware_core_logic.py \
  tests/test_list_uploaded_files_tool.py \
  tests/blocking_io/test_channels_ingest.py \
  tests/blocking_io/test_dingtalk_receive_file.py \
  tests/blocking_io/test_uploads_router.py -q
```

Expected: every selected test passes.

- [ ] **Step 5: Format and lint the complete backend change**

Run:

```bash
cd backend
make format
make lint
```

Expected: Ruff applies no unresolved fixes and both `ruff check .` and `ruff format --check .` pass.

- [ ] **Step 6: Run the full non-live backend suite**

Run:

```bash
cd backend
make test
```

Expected: the entire `-m "not live"` backend suite passes.

- [ ] **Step 7: Review the final diff against issue #3750 and the approved spec**

Run:

```bash
git diff --check origin/main...HEAD
git status --short
git diff --stat origin/main...HEAD
git log --oneline origin/main..HEAD
```

Review every changed file and confirm:

- no entry point selects a final name before the atomic publisher;
- every response/path uses the returned primary filename;
- every conversion/delete/outline path uses the shared layout;
- no legacy sibling Markdown is deleted or treated as generated;
- no hidden staging files appear in listings;
- failure cleanup receives exact paths created by the current operation;
- documentation matches executable tests.

- [ ] **Step 8: Commit documentation and final cleanup**

```bash
git add README.md backend/AGENTS.md backend/docs \
  backend/packages/harness backend/app backend/tests
git commit -m "docs: document collision-safe upload storage"
```

- [ ] **Step 9: Re-run post-commit verification before completion**

Run:

```bash
cd backend
make lint
make test
git status --short
```

Expected: lint and the full non-live suite pass, and the worktree is clean.

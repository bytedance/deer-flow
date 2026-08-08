# Upload Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every actionable finding from the independent review of PR #4704 and reach a fresh zero-finding review before marking the PR ready.

**Architecture:** Add a cross-process per-filename lease that is acquired before atomic publication and retained through every pathname-dependent side effect. Conversion and deletion share the lease; `PublishedUpload` carries an inode identity for safe rollback. Generated conversions gain deterministic long-name mapping and explicit mounted-AIO/Local-file-API read-only boundaries, while all async conversion filesystem work is offloaded and cancellation drains active workers.

**Tech Stack:** Python 3.12, asyncio, POSIX `fcntl` / Windows `msvcrt`, FastAPI, pytest, pytest-asyncio, Blockbuster, Ruff.

## Global Constraints

- Keep PR #4704 in Draft until a fresh independent review reports zero actionable findings.
- Use test-driven development: every production behavior change must have a test observed failing for the intended reason before implementation.
- Locks are per actual filename, work across threads and processes, and never require a database or manifest.
- Stable name-lock files live under `user-data/.upload-conversions/.locks/` and are not deleted during normal operation; transient stage-liveness locks live below `.locks/stages/`.
- Unrelated filenames remain concurrent; only deletion of the exact name waits for its active lifecycle.
- Conversion failure remains non-fatal to a successfully published primary upload.
- Mounted AIO uses a read-only conversion mount; Local structured file APIs use a read-only mapping, while Local host bash remains outside that enforcement boundary.
- All filesystem calls made from async conversion and Gateway code run off the event loop.
- Normal conversion names remain `<actual-primary-filename>.md`; overlong components use deterministic UTF-8-safe truncation plus a full SHA-256 digest.
- Preserve public response/list/delete compatibility except where an internal staging-pattern filename is now rejected as unsafe.

---

### Task 1: Cross-process name leases and publication identity

**Files:**
- Create: `backend/packages/harness/deerflow/uploads/errors.py`
- Create: `backend/packages/harness/deerflow/uploads/lease.py`
- Modify: `backend/packages/harness/deerflow/uploads/layout.py`
- Modify: `backend/packages/harness/deerflow/uploads/manager.py`
- Modify: `backend/packages/harness/deerflow/uploads/__init__.py`
- Test: `backend/tests/test_uploads_manager.py`

**Interfaces:**
- Moves shared publication exceptions to `uploads/errors.py`; both `manager.py` and
  `lease.py` import them so the lease layer never imports the manager layer.
- Produces: `UploadIdentity(device: int, inode: int)`.
- Produces: `UploadNameLease.acquire(uploads_dir: Path, filename: str) -> UploadNameLease`,
  `is_active: bool`, `release() -> None`, and context-manager methods.
- Produces: `PublishedUpload(path: Path, identity: UploadIdentity, lease: UploadNameLease)` with idempotent `release()`.
- Produces: `publish_staged_upload_leased(...) -> PublishedUpload`, `publish_upload_bytes_leased(...) -> PublishedUpload`, `publish_upload_copy_leased(...) -> PublishedUpload`.
- Produces: `rollback_published_upload(publication: PublishedUpload) -> None`, which removes only the matching generation while its lease is held.
- Keeps: existing `publish_*() -> Path` functions as immediate-release compatibility wrappers.

- [ ] **Step 1: Write failing reserved-name, lease, rollback, and cleanup tests**

Add focused tests to `TestUploadPublication`:

```python
def test_reserved_staging_name_is_rejected_before_stage_creation(tmp_path):
    with patch("deerflow.uploads.manager.create_upload_staging_file") as create_stage:
        with pytest.raises(ValueError, match="reserved"):
            publish_upload_bytes(tmp_path, ".upload-user.part", b"payload")
    create_stage.assert_not_called()


def test_leased_publication_blocks_delete_until_release(tmp_path):
    publication = publish_upload_bytes_leased(tmp_path, "report.pdf", b"old")
    started = threading.Event()
    finished = threading.Event()

    def delete():
        started.set()
        delete_file_safe(tmp_path, "report.pdf")
        finished.set()

    worker = threading.Thread(target=delete)
    worker.start()
    assert started.wait(1)
    assert not finished.wait(0.1)
    publication.release()
    worker.join(2)
    assert finished.is_set()


def test_rollback_does_not_remove_reused_path(tmp_path):
    publication = publish_upload_bytes_leased(tmp_path, "report.pdf", b"old")
    publication.path.unlink()
    publication.path.write_bytes(b"new")
    rollback_published_upload(publication)
    publication.release()
    assert (tmp_path / "report.pdf").read_bytes() == b"new"


def test_staging_unlink_failure_is_not_reported_as_success(tmp_path):
    staged = create_upload_staging_file(tmp_path)
    staged.handle.write(b"payload")
    real_unlink = Path.unlink

    def fail_only_for_stage(path, *args, **kwargs):
        if path == staged.path:
            raise OSError("cannot unlink stage")
        return real_unlink(path, *args, **kwargs)

    with patch.object(Path, "unlink", autospec=True, side_effect=fail_only_for_stage):
        with pytest.raises(AtomicUploadPublishError, match="staging"):
            publish_staged_upload(staged, "report.pdf")
    assert not (tmp_path / "report.pdf").exists()


def test_abort_unlinks_stage_when_close_raises(tmp_path):
    staged = create_upload_staging_file(tmp_path)

    class CloseFailingHandle:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        @property
        def closed(self):
            return self._wrapped.closed

        def close(self):
            self._wrapped.close()
            raise OSError("close failed")

    staged.handle = CloseFailingHandle(staged.handle)
    with pytest.raises(OSError, match="close failed"):
        abort_staged_upload(staged)
    assert not staged.path.exists()
```

Add a multiprocessing regression with a top-level child-process helper: the parent holds
the lease for `report.pdf`, the child attempts `delete_file_safe()`, and a queue/event
proves the child cannot finish before release. This is the cross-process acceptance gate;
the thread test separately protects the in-process exact-name keyed-lock behavior.

- [ ] **Step 2: Run the tests and verify the intended failures**

Run:

```bash
cd backend
uv run pytest tests/test_uploads_manager.py -k "reserved_staging or leased_publication or rollback_does_not or staging_unlink_failure or abort_unlinks" -q
```

Expected: failures show the missing leased APIs, current staging-name acceptance, cleanup success after unlink failure, and close preventing unlink.

- [ ] **Step 3: Implement the lock namespace and cross-platform lease**

In `layout.py`, add safe lock-directory helpers below conversion-directory helpers:

```python
UPLOAD_LOCKS_DIRNAME = ".locks"


def upload_lock_dir_for_uploads(uploads_dir: Path) -> Path:
    return conversion_dir_for_uploads(uploads_dir) / UPLOAD_LOCKS_DIRNAME


def ensure_upload_lock_dir(uploads_dir: Path) -> Path:
    conversion_dir = ensure_conversion_dir(uploads_dir)
    lock_dir = conversion_dir / UPLOAD_LOCKS_DIRNAME
    try:
        lock_dir.mkdir(mode=0o700)
    except FileExistsError:
        pass
    st = os.lstat(lock_dir)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise UnsafeConversionPathError("Unsafe upload lock directory")
    return lock_dir
```

Create `lease.py` using the repository's existing `fcntl`/`msvcrt` pattern. Use exact-name
in-process locks keyed by upload-directory identity and filename. Reference-count holders
and waiters, and remove the dictionary entry when its count reaches zero so unrelated names
never alias and historical names are not retained:

```python
@dataclass(frozen=True, slots=True)
class UploadIdentity:
    device: int
    inode: int

    @classmethod
    def from_path(cls, path: Path) -> "UploadIdentity":
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            raise UnsafeUploadPathError("Published upload is not a regular file")
        return cls(st.st_dev, st.st_ino)

    def matches(self, path: Path) -> bool:
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return False
        return stat.S_ISREG(st.st_mode) and (st.st_dev, st.st_ino) == (self.device, self.inode)


class UploadNameLease:
    @classmethod
    def acquire(cls, uploads_dir: Path, filename: str) -> "UploadNameLease":
        digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()
        lock_path = ensure_upload_lock_dir(uploads_dir) / f"{digest}.lock"
        # acquire the exact-name thread lock, then the stable fcntl/msvcrt lock

    def release(self) -> None:
        # unlock and close the file before releasing the keyed thread lock; idempotent
```

Keep the lock file in place after release.

Move `PathTraversalError`, `UnsafeUploadPathError`, and `AtomicUploadPublishError` from
`manager.py` into `errors.py`, and re-export them from `uploads/__init__.py`. This preserves
existing imports while keeping dependency direction `manager -> lease -> layout/errors`.

- [ ] **Step 4: Implement leased publication and identity-safe rollback**

In `manager.py`:

```python
@dataclass(slots=True)
class PublishedUpload:
    path: Path
    identity: UploadIdentity
    lease: UploadNameLease

    def release(self) -> None:
        self.lease.release()
```

Make `_publish_staged_upload_leased()` acquire each candidate lease before `os.link`.
On `EEXIST`, release it and continue. After link success, capture `UploadIdentity`, remove
the staging link, and return the held publication. If stage removal fails, unlink the
matching candidate, release the lease, and raise `AtomicUploadPublishError`.

Validate `preferred_filename` before `create_upload_staging_file()` in byte/copy wrappers.
Extend `normalize_filename()` with:

```python
if is_upload_staging_file(safe):
    raise ValueError(f"Filename uses reserved upload staging pattern: {filename!r}")
```

Compatibility wrappers call their leased counterpart and release in `finally`.
`rollback_published_upload()` checks `publication.identity.matches(publication.path)` before
deleting the primary and its exact conversion.

Change `abort_staged_upload()` so unlink is attempted even when close raises, while
preserving the close error if both operations fail. Publication wrappers must not let a
secondary best-effort cleanup exception mask the original publication error. A permanent
staging unlink failure may leave a hidden staging inode for startup cleanup, but must roll
back the visible candidate and report failure.

- [ ] **Step 5: Run manager tests and verify green**

Run:

```bash
cd backend
uv run pytest tests/test_uploads_manager.py -q
```

Expected: all manager tests pass; successful publications leave no `.upload-*.part`
remnants, and a forced permanent unlink failure leaves no visible published candidate.

- [ ] **Step 6: Commit the lease foundation**

```bash
git add backend/packages/harness/deerflow/uploads backend/tests/test_uploads_manager.py
git commit -m "fix: lease published upload generations"
```

---

### Task 2: Conversion ownership, long names, and non-blocking lifecycle

**Files:**
- Modify: `backend/packages/harness/deerflow/uploads/conversion.py`
- Modify: `backend/packages/harness/deerflow/uploads/layout.py`
- Modify: `backend/packages/harness/deerflow/utils/file_conversion.py`
- Test: `backend/tests/test_upload_conversion.py`
- Test: `backend/tests/test_file_conversion.py`
- Create: `backend/tests/blocking_io/test_upload_conversion.py`

**Interfaces:**
- Consumes: `PublishedUpload`, `UploadNameLease`, `UploadIdentity` from Task 1.
- Produces: `conversion_filename_for_upload(filename: str) -> str`.
- Changes: `convert_uploaded_file_to_markdown(upload_path: Path, *, publication: PublishedUpload | None = None) -> Path | None`.

- [ ] **Step 1: Write the failing conversion/delete race and long-name tests**

Add to `test_upload_conversion.py`:

```python
@pytest.mark.asyncio
async def test_delete_and_reupload_cannot_receive_old_conversion(tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    publication = publish_upload_bytes_leased(uploads, "report.pdf", b"OLD")
    converter_started = asyncio.Event()
    allow_converter = asyncio.Event()

    async def paused_convert(source, output_path=None):
        converter_started.set()
        await allow_converter.wait()
        output_path.write_text("FROM OLD", encoding="utf-8")
        return output_path

    with patch("deerflow.uploads.conversion.convert_file_to_markdown", side_effect=paused_convert):
        conversion = asyncio.create_task(
            convert_uploaded_file_to_markdown(publication.path, publication=publication)
        )
        await converter_started.wait()
        deletion = asyncio.create_task(asyncio.to_thread(delete_file_safe, uploads, "report.pdf"))
        await asyncio.sleep(0.05)
        assert not deletion.done()
        allow_converter.set()
        await conversion
        publication.release()
        await deletion

    replacement = publish_upload_bytes(uploads, "report.pdf", b"NEW")
    assert replacement.read_bytes() == b"NEW"
    assert existing_conversion_path_for_upload(replacement) is None


@pytest.mark.parametrize("byte_length", [252, 253, 254, 255])
def test_long_conversion_filename_fits_component_limit(byte_length, tmp_path):
    filename = "a" * (byte_length - 4) + ".pdf"
    upload = tmp_path / "uploads" / filename
    target = conversion_path_for_upload(upload)
    assert len(target.name.encode("utf-8")) <= 255
    assert target.name.endswith(".md")
```

Use literal expected output for the 255-byte case: 187 `a` bytes, a dot, the full SHA-256
of the original filename, and `.md`.

- [ ] **Step 2: Write a strict blocking-I/O regression**

Create `tests/blocking_io/test_upload_conversion.py`. Run the real wrapper under the
directory-wide Blockbuster fixture and patch only the parser operation below the public
conversion helper:

```python
@pytest.mark.asyncio
async def test_real_upload_conversion_lifecycle_does_not_block_event_loop(tmp_path, monkeypatch):
    uploads = tmp_path / "user-data" / "uploads"
    await asyncio.to_thread(uploads.mkdir, parents=True)
    source = uploads / "report.pdf"
    await asyncio.to_thread(source.write_bytes, b"PDF")
    monkeypatch.setattr(
        "deerflow.utils.file_conversion._do_convert",
        lambda path, converter: "# converted",
    )
    result = await convert_uploaded_file_to_markdown(source)
    assert result is not None
    assert await asyncio.to_thread(result.read_text, encoding="utf-8") == "# converted"
```

- [ ] **Step 3: Run new conversion tests and verify red**

Run:

```bash
cd backend
uv run pytest tests/test_upload_conversion.py tests/blocking_io/test_upload_conversion.py -q
```

Expected: the race lacks a lease-aware API, long names exceed 255 bytes, and Blockbuster
reports filesystem work on the event loop.

- [ ] **Step 4: Implement deterministic conversion filenames**

In `layout.py`, centralize every physical and virtual conversion name:

```python
def conversion_filename_for_upload(filename: str) -> str:
    desired = f"{filename}.md"
    if len(desired.encode("utf-8")) <= 255:
        return desired
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()
    marker = f".{digest}.md"
    prefix = _truncate_utf8(filename, 255 - len(marker.encode("utf-8")))
    return f"{prefix}{marker}"
```

Move/reuse one UTF-8 truncation helper instead of duplicating byte slicing. Make
`conversion_path_for_upload()`, `conversion_virtual_path()`, outline lookup, deletion, and
response metadata call this helper.

- [ ] **Step 5: Offload converter and wrapper filesystem work**

Change `convert_file_to_markdown()` to run `_do_convert` and the Markdown write through
`asyncio.to_thread` for every file size. Remove `_ASYNC_THRESHOLD_BYTES` and update its old
large/small routing tests to assert both sizes execute outside the event-loop thread.

In `conversion.py`, group synchronous setup/publication/cleanup into small sync helpers and
call each with `asyncio.to_thread`. If `publication` is supplied, require its active lease
and matching identity. Otherwise acquire an `UploadNameLease` off-thread, capture the
current identity, and release it in an off-thread `finally`.

- [ ] **Step 6: Run conversion and file-conversion suites**

```bash
cd backend
uv run pytest tests/test_upload_conversion.py tests/test_file_conversion.py tests/blocking_io/test_upload_conversion.py -q
```

Expected: all pass; the real wrapper trips no Blockbuster call.

- [ ] **Step 7: Commit conversion lifecycle fixes**

```bash
git add backend/packages/harness/deerflow/uploads backend/packages/harness/deerflow/utils/file_conversion.py backend/tests/test_upload_conversion.py backend/tests/test_file_conversion.py backend/tests/blocking_io/test_upload_conversion.py
git commit -m "fix: bind conversions to upload generations"
```

---

### Task 3: Gateway lease ownership and identity-safe rollback

**Files:**
- Modify: `backend/app/gateway/routers/uploads.py`
- Test: `backend/tests/test_uploads_router.py`
- Test: `backend/tests/blocking_io/test_uploads_router.py`

**Interfaces:**
- Consumes: `publish_staged_upload_leased`, `PublishedUpload`, `rollback_published_upload`.
- Changes: `_write_upload_file_with_limits(...) -> tuple[PublishedUpload, int, int]`.

- [ ] **Step 1: Write failing Gateway lifecycle tests**

Add a route-level test that pauses conversion, starts DELETE concurrently, asserts DELETE
does not complete until upload response post-processing releases the lease, then verifies
the response conversion belongs to the published primary.

Add a rollback test with two generations using a patched failure after publication:

```python
def test_cleanup_uses_publication_identity_not_reused_path(tmp_path):
    old = publish_upload_bytes_leased(tmp_path, "report.pdf", b"old")
    old.path.unlink()
    old.path.write_bytes(b"new")
    _cleanup_published_uploads([old])
    old.release()
    assert (tmp_path / "report.pdf").read_bytes() == b"new"
```

- [ ] **Step 2: Run Gateway regressions and verify red**

```bash
cd backend
uv run pytest tests/test_uploads_router.py -k "lease or identity_not_reused" -q
```

Expected: helper types/signatures are missing and DELETE is not coordinated.

- [ ] **Step 3: Carry `PublishedUpload` through the full request**

Replace `written_paths` with `publications` plus generated conversion paths. Hold each
publication lease until conversion, permission adjustment, and every remote sync completes.
Pass `publication=` into `convert_uploaded_file_to_markdown()`.

Rollback calls `rollback_published_upload()` for each publication and separately removes
only generated paths created by the request. Release every lease in a `finally` block via
`run_file_io`. Permission and sync helpers receive the publication path while its lease is
active.

- [ ] **Step 4: Extend the strict Gateway blocking-I/O test**

Exercise real lease release, rollback, and conversion wrapper setup through the route; keep
only the parser and remote sandbox transport mocked. The strict gate must remain green.

- [ ] **Step 5: Run complete Gateway suites**

```bash
cd backend
uv run pytest tests/test_uploads_router.py tests/blocking_io/test_uploads_router.py -q
```

- [ ] **Step 6: Commit Gateway lifecycle integration**

```bash
git add backend/app/gateway/routers/uploads.py backend/tests/test_uploads_router.py backend/tests/blocking_io/test_uploads_router.py
git commit -m "fix: retain upload leases through gateway sync"
```

---

### Task 4: Embedded client and direct IM lifecycle integration

**Files:**
- Modify: `backend/packages/harness/deerflow/client.py`
- Modify: `backend/app/channels/feishu.py`
- Modify: `backend/app/channels/dingtalk.py`
- Modify: `backend/app/channels/wechat.py`
- Test: `backend/tests/test_client.py`
- Test: `backend/tests/test_dingtalk_channel.py`
- Test: `backend/tests/test_wechat_channel.py`
- Test: `backend/tests/blocking_io/test_feishu_receive_file.py`
- Test: `backend/tests/blocking_io/test_dingtalk_receive_file.py`

**Interfaces:**
- Consumes: `publish_upload_copy_leased`, `publish_upload_bytes_leased`, and `PublishedUpload.release()`.

- [ ] **Step 1: Write failing client and channel lease tests**

For Client, pause conversion and show a concurrent `delete_upload()` waits until metadata
construction completes. For Feishu and DingTalk, pause remote `sandbox.update_file()` and
show deletion of the exact name waits while a different name still publishes.

Add WeChat hostile-name cases:

```python
@pytest.mark.parametrize("filename", ["a" * 256 + ".pdf", r"folder\\report.pdf", ".upload-user.part"])
def test_wechat_invalid_platform_filename_uses_safe_fallback(tmp_path, filename):
    channel = WechatChannel(bus=MessageBus(), config={"bot_token": "x", "state_dir": str(tmp_path)})
    safe = channel._normalize_inbound_filename(filename, default_prefix="wechat-file", message_id="m1", index=0)
    assert safe == "wechat-file-m1-0.bin"
    assert channel._stage_downloaded_file(safe, b"payload") is not None
```

Also patch `publish_upload_bytes` to raise a plain `ValueError` and assert
`_stage_downloaded_file()` returns `None`.

- [ ] **Step 2: Run the focused adapter tests and verify red**

```bash
cd backend
uv run pytest tests/test_client.py tests/test_dingtalk_channel.py tests/test_wechat_channel.py tests/blocking_io/test_feishu_receive_file.py tests/blocking_io/test_dingtalk_receive_file.py -k "lease or invalid_platform or plain_value_error" -q
```

- [ ] **Step 3: Integrate leases**

Client uses `publish_upload_copy_leased`, passes the publication to conversion, constructs
metadata, and releases in `finally`.

Feishu and DingTalk use `publish_upload_bytes_leased`; keep the returned publication alive
through mounted/non-mounted sandbox handling and release with `asyncio.to_thread` in
`finally`. Return paths always use `publication.path.name`.

WeChat's `_normalize_inbound_filename()` calls shared `normalize_filename()` and falls back
to `_safe_media_filename(...)` on `ValueError`. `_stage_downloaded_file()` catches both
`OSError` and `ValueError` so one hostile attachment cannot escape the channel handler.

- [ ] **Step 4: Run full adapter suites**

```bash
cd backend
uv run pytest tests/test_client.py tests/test_channel_file_attachments.py tests/test_dingtalk_channel.py tests/test_wechat_channel.py tests/blocking_io/test_channels_ingest.py tests/blocking_io/test_feishu_receive_file.py tests/blocking_io/test_dingtalk_receive_file.py -q
```

- [ ] **Step 5: Commit client and channel lifecycle fixes**

```bash
git add backend/packages/harness/deerflow/client.py backend/app/channels backend/tests/test_client.py backend/tests/test_channel_file_attachments.py backend/tests/test_dingtalk_channel.py backend/tests/test_wechat_channel.py backend/tests/blocking_io/test_channels_ingest.py backend/tests/blocking_io/test_feishu_receive_file.py backend/tests/blocking_io/test_dingtalk_receive_file.py
git commit -m "fix: retain upload leases through adapter sync"
```

---

### Task 5: Read-only conversion boundaries for mounted AIO and Local file APIs

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py`
- Modify: `backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py`
- Test: `backend/tests/test_local_sandbox_provider_mounts.py`
- Test: `backend/tests/test_aio_sandbox_provider.py`

**Interfaces:**
- Consumes: `UPLOAD_CONVERSIONS_DIRNAME`, `ensure_conversion_dir`, and existing `join_host_path`.
- Produces: an explicit read-only AIO mount and a Local structured-file mapping for
  `/mnt/user-data/.upload-conversions`; Local host bash is documented as outside the mapping.

- [ ] **Step 1: Write failing mount-contract tests**

Add literal assertions to the existing provider mount tests:

```python
def test_local_thread_mappings_mount_conversions_read_only(paths_config):
    mappings = LocalSandboxProvider._build_thread_path_mappings("thread-1", user_id="user-1")
    conversion = next(m for m in mappings if m.container_path == "/mnt/user-data/.upload-conversions")
    assert conversion.read_only is True
    assert Path(conversion.local_path).is_dir()


def test_get_thread_mounts_includes_upload_conversions_read_only(tmp_path, monkeypatch):
    mounts = AioSandboxProvider._get_thread_mounts("thread-1", user_id="user-1")
    assert any(container == "/mnt/user-data/.upload-conversions" and read_only for _, container, read_only in mounts)
```

- [ ] **Step 2: Run mount tests and verify red**

```bash
cd backend
uv run pytest tests/test_local_sandbox_provider_mounts.py tests/test_aio_sandbox_provider.py -k "conversion" -q
```

Expected: neither provider exposes the explicit mapping.

- [ ] **Step 3: Add the Local and AIO mappings**

Both builders call `ensure_conversion_dir(paths.sandbox_uploads_dir(...))` before returning.
Local adds a longer, read-only `PathMapping` beneath the aggregate writable user-data map
for structured file operations. AIO adds:

```python
(
    join_host_path(paths.host_sandbox_user_data_dir(thread_id, user_id=effective_user_id), UPLOAD_CONVERSIONS_DIRNAME),
    f"{VIRTUAL_PATH_PREFIX}/{UPLOAD_CONVERSIONS_DIRNAME}",
    True,
)
```

- [ ] **Step 4: Run provider and virtual-path suites**

```bash
cd backend
uv run pytest tests/test_local_sandbox_provider_mounts.py tests/test_aio_sandbox_provider.py tests/test_local_sandbox_virtual_path_contract.py -q
```

- [ ] **Step 5: Commit sandbox visibility**

```bash
git add backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py backend/tests/test_local_sandbox_provider_mounts.py backend/tests/test_aio_sandbox_provider.py
git commit -m "fix: mount upload conversions read-only"
```

---

### Task 6: Documentation, complete verification, and independent review loop

**Files:**
- Modify: `README.md`
- Modify: `backend/AGENTS.md`
- Modify: `backend/docs/API.md`
- Modify: `backend/docs/FILE_UPLOAD.md`
- Modify: `backend/docs/PATH_EXAMPLES.md`
- Modify: `docs/superpowers/specs/2026-08-06-upload-collision-safety-design.md`
- Modify: `docs/superpowers/specs/2026-08-06-upload-review-remediation-design.md`

**Interfaces:**
- Documents: same-name delete waiting, read-only conversion mount, reserved staging pattern, and long-name conversion mapping.

- [ ] **Step 1: Update documentation from actual final behavior**

Set the remediation spec status to `Implemented; awaiting independent review`. Explain that
delete waits only for an active lifecycle of the exact filename. Document that generated
conversions are read-only through mounted AIO and Local structured file interfaces, while
Local host bash and non-mounted private copies have narrower guarantees. Overlong conversion
components use `<truncated-primary>.<full-sha256>.md`. State that `.upload-*.part` is reserved.

### Independent review round 2 amendments

- Replace hash-striped thread locks with reference-counted exact-name locks; unrelated
  filenames must never deadlock merely because their digests share a stripe.
- Run blocking lease acquisition on a dedicated executor so same-name waiters cannot starve
  lease release in the general file-I/O pool. Windows acquisition retries until success.
- Give each active stage a cross-process liveness lock and make startup cleanup skip any
  stage whose lock is held.
- Drain conversion and publication workers before cancellation cleans a stage or releases a
  generation lease.
- Track successful non-mounted sandbox updates and remove those exact remote copies before
  host rollback on later failure or cancellation.
- Describe read-only behavior at the actual enforcement boundary: mounted AIO and Local
  structured file APIs, not Local host bash or a non-mounted private copy.

- [ ] **Step 2: Run the complete focused suite**

```bash
cd backend
uv run pytest tests/test_uploads_manager.py tests/test_upload_conversion.py tests/test_file_conversion.py tests/test_uploads_router.py tests/test_client.py tests/test_channel_file_attachments.py tests/test_dingtalk_channel.py tests/test_wechat_channel.py tests/test_local_sandbox_provider_mounts.py tests/test_aio_sandbox_provider.py tests/test_uploads_middleware_core_logic.py tests/test_list_uploaded_files_tool.py tests/blocking_io/test_upload_conversion.py tests/blocking_io/test_uploads_router.py tests/blocking_io/test_channels_ingest.py tests/blocking_io/test_feishu_receive_file.py tests/blocking_io/test_dingtalk_receive_file.py -q
```

- [ ] **Step 3: Run formatting, lint, and the full backend suite**

```bash
cd backend
make format
make lint
make test
```

Expected: zero failures. Existing third-party deprecation warnings may remain but no new
warnings from changed code are accepted.

- [ ] **Step 4: Run static and repository-state audits**

```bash
git diff --check origin/main...HEAD
git status --short
rg -n "publish_upload_|publish_staged_upload|delete_file_safe|convert_uploaded_file_to_markdown" backend/app backend/packages/harness/deerflow
rg -n "sandbox_uploads_dir\([^\n]*\)\.resolve|\.write_bytes\(" backend/app/channels backend/app/gateway/routers/uploads.py
```

Confirm every pathname-dependent post-publication adapter either retains a lease or has no
later destructive/sync side effect.

- [ ] **Step 5: Commit final docs and verification state**

```bash
git add README.md backend/AGENTS.md backend/docs docs/superpowers/specs
git commit -m "docs: document upload generation leases"
```

- [ ] **Step 6: Push and request a fresh independent review**

```bash
git push origin fix/3750-upload-collisions
```

Dispatch one fresh Code Reviewer with pinned `origin/main...HEAD`, both approved specs,
repository standards, and an explicit zero-actionable-finding gate. It must not mutate the
checkout or PR.

- [ ] **Step 7: Repeat until clean**

For every new actionable finding: verify it against code, add a failing regression, apply
the minimal fix, rerun focused and full verification, push, and request another fresh
independent review. Do not mark ready while any Critical, Important, or Minor finding
remains.

- [ ] **Step 8: Mark PR #4704 ready and read it back**

Only after a reviewer says `No actionable findings`, use the GitHub connector's
`github_mark_pull_request_ready_for_review` operation (or authenticated `gh pr ready 4704`
if connector permissions fail). Read back `isDraft=false`, head SHA, mergeability, and CI.

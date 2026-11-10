# Uploads

`manager.py::list_files_in_dir` returns a best-effort snapshot under concurrent
cleanup. Entry stat races (`ENOENT`, `ENOTDIR`, `ELOOP`) are skipped with debug
logging. Directory removal or replacement by a non-directory during scanning
returns entries already collected and logs the directory path and retained
entry count at debug level. Permission and other operational errors propagate.

Keep both entry and directory race coverage in
`backend/tests/test_uploads_manager.py`.

Staging cleanup is best-effort: warn with the directory and exception on scan
errors, keep its files and continue elsewhere. A vanished directory stays quiet.

Embedded first-time uploads use `publish_upload_copy` for suffix retries from the
normalized original name, for originals and companions. With `snapshot_path`,
capture the opened source once before retries and retain its original `fstat`
metadata; every attempt reads the held private capture. Collision copies share
this capture helper and publish complete staged copies under the next free name.
Validate the requested destination before seeding copy suffixes from a directory
snapshot, so unsafe links still fail and known collisions do not stage twice.
Atomic no-replace links remain the concurrency boundary; retry after a lost claim.
Never copy snapshot permission bits onto the saved upload.
Close the caller's descriptor after capture and finish conversion workers before
removing captures. Never reopen the caller/sandbox upload path for conversion.
Original names already present in the initial snapshot also take a free suffix;
never truncate an earlier upload. Default open/write helpers claim with O_EXCL
and retry suffixes, while explicit `exclusive=True` preserves exact-name
FileExistsError so callers can own their retry policy. Converted
Markdown always uses no-replace publication, including across upload calls, and
registers the actual saved name. An existing basename does not establish companion
ownership. Apply source timestamps after new-file publication so cleanup cannot sweep an in-flight copy
of an old source. New final names must expose complete copies.

No-replace publication binds pre-link staging and post-link destination checks to
the open staging descriptor. Use a no-follow hard link where supported; fallback
identity checks narrow but do not eliminate the link-time race. Reject substituted
regular files and symlinks, and remove a mismatched publication before reporting
failure. Cleanup errors are logged without masking success or the original error.
Keep publication/fallback coverage in `backend/tests/test_upload_copy_publication.py`
and capture-through-collision cases in `backend/tests/test_client_upload_snapshot.py`.

`companions.py::register_companion` publishes its ownership record through
`utils.atomic_write.cleanup_failed_atomic_write`. Do not restore a bare
`finally: os.unlink(staged)`: when `json.dump` or `os.replace` failed, a failing
unlink replaced that primary error, and the old `with os.fdopen(fd, ...)` leaked
the descriptor whenever `fdopen` itself failed. Pass the raw descriptor only
until `fdopen` succeeds, and keep cleanup best-effort so a leftover staged
record is reported rather than becoming the caller's error. Coverage:
`backend/tests/test_atomic_cleanup_preserves_primary_error.py`.

Companion ownership validates both source and Markdown device, inode, size,
mtime and ctime. Legacy three-field source identities and four-field Markdown
identities fail closed with distinct debug diagnostics; never backfill their
missing timestamps on read. Re-upload/re-convert to register a fresh association.
Keep legacy rejection, unchanged record bytes, and explicit re-registration
coverage in `backend/tests/test_upload_companions.py`.
These metadata checks detect ordinary edits; they do not guarantee content
integrity against a sandbox writer that can restore timestamps. Content hashing
is a separate enhancement.

### File Upload

Outlines use ATX syntax (1–6 hashes, space/tab separator, ≤3 leading spaces), strip closing hashes and skip fenced code; closing markers use a linear suffix scan — never unanchored whitespace regex on unbounded headings.
- Endpoint: `POST /api/threads/{thread_id}/uploads`; PDF/PPT/Excel/Word via `markitdown`, one conversion worker per request; directories rejected, keeping uploads all-or-nothing; duplicate filenames in one request get `_N` suffixes.
- Files live in thread-isolated `users/{user_id}/threads/{thread_id}/user-data/uploads` (IM channels thread the owner via the `user_id=` kwarg — see IM Channels → Owner-scoped file storage; HTTP/embedded callers resolve `get_effective_user_id()`); per-thread `upload-companions/` holds source mtime/ctime.
- Gateway HTTP uploads stage `.upload-*.part` files hidden from upload listings, agent context, and sandbox listings/searches; publication is atomic after size validation. Startup sweep keeps lone `.part` files under 24h (possibly in flight on another replica); `st_nlink > 1` means a published alias, removed at any age so the multi-link check can still replace the file.
- Upload/list/delete handlers offload filesystem work through `deerflow.utils.file_io.run_file_io` (ContextVar-preserving); non-mounted sandbox uploads use `SandboxProvider.acquire_async()` and offload `read_bytes()` + `sandbox.update_file()` together. Mounted uploads skip acquire/sync; AIO remote/provisioner requires accurate `sandbox.thread_data_mounts: true`, omission keeps backend auto-detection.
- `UploadsMiddleware` caps outline titles at 200 characters and previews at 2000 including markers. Titles use `original_user_content`; attachment-only titles use a sanitized, bounded filename or count.

See [docs/FILE_UPLOAD.md](../../../../docs/FILE_UPLOAD.md) for details.

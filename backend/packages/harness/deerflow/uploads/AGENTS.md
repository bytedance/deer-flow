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

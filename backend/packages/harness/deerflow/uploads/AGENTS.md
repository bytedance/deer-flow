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
metadata; every attempt reads the held private capture. Replacement copies share
this capture helper. Never copy snapshot permission bits onto the saved upload.
Close the caller's descriptor after capture and finish conversion workers before
removing captures. Never reopen the caller/sandbox upload path for conversion.
Names already present in the call's initial regular-file snapshot retain
replacement behavior; these replacements are not serialized. Apply source
timestamps after new-file publication so cleanup cannot sweep an in-flight copy
of an old source. New final names must expose complete copies.

No-replace publication binds pre-link staging and post-link destination checks to
the open staging descriptor. Use a no-follow hard link where supported; fallback
identity checks narrow but do not eliminate the link-time race. Reject substituted
regular files and symlinks, and remove a mismatched publication before reporting
failure. Cleanup errors are logged without masking success or the original error.
Keep publication/fallback coverage in `backend/tests/test_upload_copy_publication.py`
and capture-through-collision cases in `backend/tests/test_client_upload_snapshot.py`.

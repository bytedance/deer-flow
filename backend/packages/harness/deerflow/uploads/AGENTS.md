# Uploads

`manager.py::list_files_in_dir` returns a best-effort snapshot under concurrent
cleanup. Entry stat races (`ENOENT`, `ENOTDIR`, `ELOOP`) are skipped with debug
logging. Directory removal or replacement by a non-directory during scanning
returns entries already collected and logs the directory path and retained
entry count at debug level. Permission and other operational errors propagate.

Keep both entry and directory race coverage in
`backend/tests/test_uploads_manager.py`.

Embedded first-time uploads use `publish_upload_copy` for suffix retries, seeded
from the normalized original name for both originals and converted companions.
`copy_upload_file_no_replace` binds its pre-link staging and post-link destination
checks to the open staging descriptor's identity. Use a no-follow hard link when
supported; the fallback pre/post checks reduce but do not eliminate the link-time
race on platforms without that option. Reject substituted regular files as well
as symlinks and remove a mismatched destination before reporting failure. Cleanup
errors are logged without masking a successful copy or its original exception.
Keep adversarial publication and fallback coverage in
`backend/tests/test_upload_copy_publication.py`.

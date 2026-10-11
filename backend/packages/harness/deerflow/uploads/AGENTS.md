# Uploads

`manager.py::list_files_in_dir` returns a best-effort snapshot under concurrent
cleanup. Entry stat races (`ENOENT`, `ENOTDIR`, `ELOOP`) are skipped with debug
logging. Directory removal or replacement by a non-directory during scanning
returns entries already collected and logs the directory path and retained
entry count at debug level. Permission and other operational errors propagate.

Keep both entry and directory race coverage in
`backend/tests/test_uploads_manager.py`.

"""Remote ``list_dir`` find command and stdout contract.

Remote providers list with ``find ... | head`` under ``sh -lc``. POSIX ``sh``
does not enable ``pipefail``, so the pipeline's exit code is ``head``'s, not
``find``'s. A missing ``find`` binary (127) then looks like an empty listing
and becomes ``FileNotFoundError``.

The command checks root existence before running ``find`` and writes its own
status after the bounded listing, distinguishing missing paths from traversal
failures even when no entries were printed. ``head`` closing the
pipe can kill ``find`` with SIGPIPE (141); that is a successful truncation,
not an error.
"""

from __future__ import annotations

import shlex

_STATUS_PREFIX = "__DF_FIND_STATUS__:"
_MISSING_ROOT = "missing"
_LIST_LIMIT = 500
# 0 = ok, 141 = SIGPIPE from head truncating a large listing.
# A missing root has its own marker; status 1 always means traversal failed.
_FIND_OK = (0, 141)


def remote_list_dir_command(path: str, max_depth: int, *, limit: int = _LIST_LIMIT) -> str:
    """Return a POSIX ``sh -lc`` script that lists ``path`` and records find status."""
    quoted = shlex.quote(path)
    depth = int(max_depth)
    n = int(limit)
    # Status file is written by the find side of the pipe, then printed AFTER
    # head so a 500-line listing cannot truncate the marker. ``set +e`` undoes
    # a login-profile ``set -e`` so a failing find still records $?. End with
    # ``exit`` of that status (126 if the file is missing): the last command
    # would otherwise be ``rm``, whose 0/1 is not find's status.
    return (
        f"set +e; if [ ! -e {quoted} ]; then printf '%s\\n' {_STATUS_PREFIX}{_MISSING_ROOT}; exit 1; fi; "
        f"_st=/tmp/df_find_$$; "
        f"{{ find -H {quoted} -maxdepth {depth} \\( -type f -o -type d \\) 2>/dev/null; "
        f'echo $? > "$_st"; }} | head -n {n}; '
        f'st=$(cat "$_st" 2>/dev/null); '
        f"printf '\\n%s\\n' {_STATUS_PREFIX}$st; "
        f'rm -f "$_st"; exit "${{st:-126}}"'
    )


def parse_remote_list_dir_output(
    stdout: str | None,
    resolved: str,
    *,
    pipeline_exit_code: int | None = None,
) -> list[str]:
    """Parse listing stdout, preferring the find-status marker over pipeline status.

    Raises:
        OSError: Command/client failure or an incomplete traversal.
        FileNotFoundError: The root is missing or no listable entries exist.
    """
    # find delimits records with "\n" only. splitlines() would also split on
    # \v, \f, \x1c-\x1e and \x85, which are legal in Linux filenames. Do not
    # strip entries: trailing whitespace can be part of the name.
    lines = (stdout or "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    find_status: int | None = None
    if lines and lines[-1].startswith(_STATUS_PREFIX):
        raw = lines.pop()[len(_STATUS_PREFIX) :]
        if raw == _MISSING_ROOT:
            raise FileNotFoundError(resolved)
        try:
            find_status = int(raw)
        except ValueError:
            find_status = None
        if lines and lines[-1] == "":
            lines.pop()

    if find_status is None:
        # Do not treat a missing marker as success. The process status used to
        # be ``rm``'s (0/1), which reclassified a lost 127
        # as FileNotFoundError.
        if pipeline_exit_code is not None and pipeline_exit_code not in (*_FIND_OK, 1):
            raise OSError(f"Failed to list_dir {resolved}: command exited with code {pipeline_exit_code}")
        raise OSError(f"Failed to list_dir {resolved}: find status marker missing")

    entries = [line for line in lines if line]
    if find_status == 1:
        raise OSError(f"Failed to list_dir {resolved}: find exited with code 1, usually because some files or directories could not be read; results would be incomplete, so list a narrower path")
    if find_status not in _FIND_OK:
        raise OSError(f"Failed to list_dir {resolved}: command exited with code {find_status}")

    if not entries:
        raise FileNotFoundError(resolved)
    return entries

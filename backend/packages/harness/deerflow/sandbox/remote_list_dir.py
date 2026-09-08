"""Remote ``list_dir`` find command and stdout contract.

Remote providers list with ``find ... | head`` under ``sh -lc``. POSIX ``sh``
does not enable ``pipefail``, so the pipeline's exit code is ``head``'s, not
``find``'s. A missing ``find`` binary (127) then looks like an empty listing
and becomes ``FileNotFoundError``.

The command below writes ``find``'s own status after the bounded listing so
callers can tell a missing path from a command failure. ``head`` closing the
pipe can kill ``find`` with SIGPIPE (141); that is a successful truncation,
not an error.
"""

from __future__ import annotations

import shlex

_STATUS_PREFIX = "__DF_FIND_STATUS__:"
_LIST_LIMIT = 500
# 0 = ok, 1 = find reported a missing start point / tree error, 141 = SIGPIPE
# from head truncating a large listing.
_FIND_OK = (0, 1, 141)


def remote_list_dir_command(path: str, max_depth: int, *, limit: int = _LIST_LIMIT) -> str:
    """Return a POSIX ``sh -lc`` script that lists ``path`` and records find status."""
    quoted = shlex.quote(path)
    depth = int(max_depth)
    n = int(limit)
    # Status file is written by the find side of the pipe, then printed AFTER
    # head so a 500-line listing cannot truncate the marker. ``set +e`` undoes
    # a login-profile ``set -e`` so a failing find still records $?.
    return (
        f"set +e; _st=/tmp/df_find_$$; "
        f"{{ find -H {quoted} -maxdepth {depth} \\( -type f -o -type d \\) 2>/dev/null; "
        f'echo $? > "$_st"; }} | head -n {n}; '
        f'printf \'\\n%s\\n\' {_STATUS_PREFIX}$(cat "$_st"); '
        f'rm -f "$_st"'
    )


def parse_remote_list_dir_output(
    stdout: str | None,
    resolved: str,
    *,
    pipeline_exit_code: int | None = None,
) -> list[str]:
    """Parse listing stdout, preferring the find-status marker over pipeline status.

    Raises:
        OSError: Command/client failure (missing binary, invocation error, ...).
        FileNotFoundError: ``find`` ran and produced no entries (missing path).
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
        try:
            find_status = int(raw)
        except ValueError:
            find_status = None
        if lines and lines[-1] == "":
            lines.pop()

    if find_status is None:
        find_status = pipeline_exit_code
    if find_status not in _FIND_OK:
        raise OSError(f"Failed to list_dir {resolved}: command exited with code {find_status}")

    entries = [line for line in lines if line]
    if not entries:
        raise FileNotFoundError(resolved)
    return entries

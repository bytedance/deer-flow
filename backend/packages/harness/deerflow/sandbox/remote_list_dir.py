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

import os
import shlex

from deerflow.sandbox.search import IGNORE_PATTERNS, should_ignore_path

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
    # Match the parser's host-platform case policy. Prune ignored descendants
    # before head so they cannot consume the visible listing's output budget.
    name_test = "-iname" if os.path.normcase("A") == "a" else "-name"
    # IGNORE_PATTERNS must contain basename patterns (no '/'); -name/-iname do not match paths.
    ignored = " -o ".join(f"{name_test} {shlex.quote(pattern)}" for pattern in IGNORE_PATTERNS)
    prune = f"\\( {ignored} \\) -prune -o " if ignored else ""
    # Status file is written by the find side of the pipe, then printed AFTER
    # head so a 500-line listing cannot truncate the marker. ``set +e`` undoes
    # a login-profile ``set -e`` so a failing find still records $?. End with
    # ``exit`` of that status (126 if the file is missing): the last command
    # would otherwise be ``rm``, whose 0/1 is not find's status.
    # ``set +e`` stays outermost (pinned by existing tests); the rest runs in a
    # ( ... ) subshell: a bare ``exit`` in the implicit persistent session kills
    # the session's shell process and the AIO server's response path for that
    # request hangs forever (verified: bare ``exit 0`` always wedges; a subshell
    # ``exit`` only kills the subshell, the session survives, and the exit code
    # and output propagate unchanged).
    return (
        f"set +e; ( if [ ! -e {quoted} ]; then printf '%s\\n' {_STATUS_PREFIX}{_MISSING_ROOT}; exit 1; fi; "
        f"_st=/tmp/df_find_$$; "
        # Print the explicit root separately and only filter its descendants.
        # Unlike a -path root exemption, this treats glob metacharacters in
        # the root literally and still permits listing an ignored root itself.
        f"{{ printf '%s\\n' {quoted}; "
        f"find -H {quoted} -mindepth 1 -maxdepth {depth} {prune}\\( -type f -o -type d \\) -print 2>/dev/null; "
        f'echo $? > "$_st"; }} | head -n {n}; '
        f'st=$(cat "$_st" 2>/dev/null); '
        f"printf '\\n%s\\n' {_STATUS_PREFIX}$st; "
        f'rm -f "$_st"; exit "${{st:-126}}" )'
    )


def parse_remote_list_dir_output(
    stdout: str | None,
    resolved: str,
    *,
    pipeline_exit_code: int | None = None,
) -> list[str]:
    """Parse listing stdout, preferring the find-status marker over pipeline status.

    Entries under ignored directories (``IGNORE_PATTERNS``) are dropped, matching
    the local ``list_dir`` and the remote ``glob``/``grep`` implementations, which
    already skip those paths. Patterns apply to the path relative to the listing
    root, so an ignored name only hides that directory's *descendants*: explicitly
    listing ``build`` — or a path below an ignored ancestor — still returns its
    contents, as the local walk does. Filtering happens after the empty-output
    check, so a directory whose entries are all ignored returns an empty list
    rather than a missing-path error.

    Raises:
        OSError: Command/client failure or an incomplete traversal.
        FileNotFoundError: The root is missing or ``find`` produced no output.
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
    root = resolved.rstrip("/") or "/"
    prefix = "/" if root == "/" else f"{root}/"
    kept: list[str] = []
    for entry in entries:
        if entry.rstrip("/") == root:
            # The requested root is what the caller asked for; keep it even when
            # its own name matches an ignore pattern.
            kept.append(entry)
        elif entry.startswith(prefix):
            if not should_ignore_path(entry[len(prefix) :]):
                kept.append(entry)
        else:
            # Defensive fallback for unexpected entries outside the requested
            # prefix: root-relative ignore matching cannot classify them.
            kept.append(entry)
    return kept

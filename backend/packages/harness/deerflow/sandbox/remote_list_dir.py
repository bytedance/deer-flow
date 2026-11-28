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

from deerflow.sandbox.search import (
    IGNORE_PATTERNS,
    USER_DATA_IGNORE_PATTERNS,
    search_uses_content_rules,
    should_ignore_path,
    user_data_ignore_rules,
)

_STATUS_PREFIX = "__DF_FIND_STATUS__:"
_MISSING_ROOT = "missing"
_NOT_A_DIR = "notadir"
_LIST_LIMIT = 500
# 0 = ok, 141 = SIGPIPE from head truncating a large listing.
# A missing root has its own marker; status 1 always means traversal failed.
_FIND_OK = (0, 141)


def remote_list_dir_command(
    path: str,
    max_depth: int | None,
    *,
    limit: int = _LIST_LIMIT,
    user_data: bool = False,
    name_glob: str | None = None,
    files_only: bool = False,
    glob: str | None = None,
) -> str:
    """Return a POSIX ``sh -lc`` script that lists ``path`` and records find status.

    ``user_data`` marks a root the provider maps to the user's own files; the
    prune list then keeps only repository machinery and in-flight uploads, so
    ``*.log`` uploads survive the server-side walk. Pass the same value to
    :func:`parse_remote_list_dir_output`.

    ``max_depth=None`` walks without a depth bound (used by glob, which matches
    at any depth); an int keeps the ``-maxdepth`` bound ``list_dir`` wants.

    ``name_glob`` adds a server-side ``-name`` coarse filter. The caller still
    re-matches client-side: ``-name`` tests only the basename, so it is always a
    superset of the anchored ``path_matches`` semantics, never dropping a match
    the local walk would keep. ``files_only`` restricts the walk to ``-type f``
    so a files-only glob does not need the client to know each entry's type.
    """
    quoted = shlex.quote(path)
    n = int(limit)
    # Match the parser's host-platform case policy. Prune ignored descendants
    # before head so they cannot consume the visible listing's output budget.
    name_test = "-iname" if os.path.normcase("A") == "a" else "-name"
    # Ignore patterns must contain basename patterns (no '/'); -name/-iname do not match paths.
    # The prune list must mirror the client's rule set, or the server would drop
    # a name the caller asked for: a glob that names user data (``*.log``) makes
    # the client treat logs as content, so the walk must not prune them. Mirror
    # ``_rules_for_search``: user-data roots and data-naming globs keep content.
    if search_uses_content_rules(glob=glob, user_data=user_data):
        patterns = USER_DATA_IGNORE_PATTERNS
    else:
        patterns = IGNORE_PATTERNS
    ignored = " -o ".join(f"{name_test} {shlex.quote(pattern)}" for pattern in patterns)
    prune = f"\\( {ignored} \\) -prune -o " if ignored else ""
    depth = f"-maxdepth {int(max_depth)} " if max_depth is not None else ""
    # Type predicate: a files-only glob must not transfer directories, because
    # the string entries it returns carry no is_directory flag for the client.
    type_test = "-type f" if files_only else "\\( -type f -o -type d \\)"
    name_clause = f"{name_test} {shlex.quote(name_glob)} " if name_glob else ""
    # The glob coarse filter must match the SANDBOX's case policy, not the
    # host's. The sandbox is POSIX, where ``path_matches`` uses ``fnmatchcase``
    # (case-sensitive), so the server-side ``-name`` must stay case-sensitive
    # even when this code runs on a case-folding host. ``-iname`` here would let
    # ``*.md`` match ``A.MD`` on the server while the client matcher rejects it
    # — a harmless superset, but it would also silently change which files
    # transfer, so we keep the predicates aligned.
    if name_glob:
        name_clause = f"-name {shlex.quote(name_glob)} "
    # ``list_dir`` (a bounded depth) pre-prints the explicit root so the listing
    # includes the start point even when its own name matches an ignore pattern.
    # A glob search (unbounded depth) must NOT: the root's rel_path is empty and
    # the matcher drops it, but pre-printing it would still consume one line of
    # the head budget that should go to a real candidate.
    _root_print = "" if max_depth is None else f"printf '%s\\n' {quoted}; "
    # A glob search over a path that is a file must raise NotADirectoryError,
    # matching the local walk; find -mindepth 1 on a file would otherwise print
    # nothing and silently return "no matches". list_dir keeps its own behavior.
    not_a_dir = f"if [ ! -d {quoted} ]; then printf '%s\\n' {_STATUS_PREFIX}{_NOT_A_DIR}; exit 1; fi; " if max_depth is None else ""
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
        f"{not_a_dir}"
        f"_st=/tmp/df_find_$$; "
        # Print the explicit root separately and only filter its descendants.
        # Unlike a -path root exemption, this treats glob metacharacters in
        # the root literally and still permits listing an ignored root itself.
        # ``head`` returns N+1 lines for a glob search (one past the caller's
        # cap) so the parser can tell an exact fit from a truncated one; the
        # root is NOT pre-printed on that path, so the budget is purely find's.
        f"{{ {_root_print}find -H {quoted} -mindepth 1 {depth}{prune}{type_test} {name_clause}-print 2>/dev/null; "
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
    user_data: bool = False,
) -> list[str]:
    """Parse listing stdout, preferring the find-status marker over pipeline status.

    Entries under ignored directories (``IGNORE_PATTERNS``) are dropped, matching
    the local ``list_dir`` and the remote ``glob``/``grep`` implementations, which
    already skip those paths. Patterns apply to the path relative to the listing
    root, so an ignored name only hides that directory's *descendants*: explicitly
    listing ``build`` — or a path below an ignored ancestor — still returns its
    contents, as the local walk does. Filtering happens after the empty-output
    check, so a directory whose entries are all ignored returns an empty list
    rather than a missing-path error. ``user_data`` mirrors the command's prune
    list: the user's own ``*.log`` files are content, while repository machinery
    and in-flight ``.upload-*.part`` files stay hidden.

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
    # Same rule split as the command's prune list and search.ignore_rules_for.
    rules = user_data_ignore_rules(user_data=user_data)
    kept: list[str] = []
    for entry in entries:
        if entry.rstrip("/") == root:
            # The requested root is what the caller asked for; keep it even when
            # its own name matches an ignore pattern.
            kept.append(entry)
        elif entry.startswith(prefix):
            if not should_ignore_path(entry[len(prefix) :], rules=rules):
                kept.append(entry)
        else:
            # Defensive fallback for unexpected entries outside the requested
            # prefix: root-relative ignore matching cannot classify them.
            kept.append(entry)
    return kept


def parse_remote_find_output(
    stdout: str | None,
    resolved: str,
    *,
    limit: int,
    pipeline_exit_code: int | None = None,
) -> tuple[list[str], bool]:
    """Parse a glob ``find`` listing into ``(entries, truncated)``.

    Unlike :func:`parse_remote_list_dir_output`, an empty result is a valid "no
    matches" rather than a missing-path error. ``limit`` is the number of lines
    ``head`` was asked for, which is ONE more than the candidate budget: when
    find prints ``limit`` lines, head filled its request and find still had at
    least one more candidate, so the search is truncated and we keep the first
    ``limit - 1``. Fewer than ``limit`` lines means find finished on its own —
    the listing is complete even at an exact fit, so we keep all of them.

    SIGPIPE (141) is accepted as a non-error status but is NOT the truncation
    signal: a small find result fits the pipe buffer and find exits 0 even when
    head cut it off, so the raw line count is the only reliable signal.

    No ignore filtering happens here: the ``find`` command already prunes
    ignored trees during the walk, so the lines it prints are candidates. The
    client re-applies the full ignore and glob filters (and its own
    ``max_results`` cap) on whatever this returns.

    Raises:
        OSError: Command/client failure or an incomplete traversal.
        FileNotFoundError: The root is missing.
        NotADirectoryError: The root is a file, matching the local walk.
    """
    lines = (stdout or "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    find_status: int | None = None
    if lines and lines[-1].startswith(_STATUS_PREFIX):
        raw = lines.pop()[len(_STATUS_PREFIX) :]
        if raw == _MISSING_ROOT:
            raise FileNotFoundError(resolved)
        if raw == _NOT_A_DIR:
            raise NotADirectoryError(resolved)
        try:
            find_status = int(raw)
        except ValueError:
            find_status = None
        if lines and lines[-1] == "":
            lines.pop()

    if find_status is None:
        if pipeline_exit_code is not None and pipeline_exit_code not in (*_FIND_OK, 1):
            raise OSError(f"Failed to glob {resolved}: command exited with code {pipeline_exit_code}")
        raise OSError(f"Failed to glob {resolved}: find status marker missing")

    entries = [line for line in lines if line]
    if find_status == 1:
        raise OSError(f"Failed to glob {resolved}: find exited with code 1, usually because some files or directories could not be read; results would be incomplete, so search a narrower path")
    if find_status not in _FIND_OK:
        raise OSError(f"Failed to glob {resolved}: command exited with code {find_status}")

    # ``head`` was asked for ``limit`` lines (one past the candidate budget).
    # Receiving ``limit`` lines means find had more to give: truncated, keep the
    # first ``limit - 1``. Fewer means find finished: complete, keep them all.
    truncated = len(entries) >= limit

    root = resolved.rstrip("/") or "/"
    # The root itself is never a glob candidate; the walk starts at its children.
    kept = [entry for entry in entries if entry.rstrip("/") != root]
    # Drop the extra probe line when truncated so the client sees a clean budget.
    return kept[: limit - 1] if truncated else kept, truncated

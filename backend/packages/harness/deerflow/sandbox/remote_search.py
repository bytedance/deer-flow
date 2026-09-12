"""Remote ``grep`` / ``glob`` command wrapper and stdout contract.

Remote providers search with ``grep ... | head`` or ``find ... | head`` under
``sh -lc``. POSIX ``sh`` has no ``pipefail`` and the search's stderr is
discarded, so the pipeline status is ``head``'s: a missing search root, a
missing ``grep``/``find`` binary (127) or an unreadable tree all printed
nothing and exited 0, exactly like a genuine "no matches" (#5376).

:func:`remote_search_command` checks the root first and records the search
command's own status after the bounded output, the same technique as
:mod:`deerflow.sandbox.remote_list_dir`. The script always exits 0 so SDKs that
raise on a non-zero exit still return the marker; the marker alone decides.
"""

from __future__ import annotations

import shlex
from typing import Literal

SearchTool = Literal["grep", "find"]

_STATUS_PREFIX = "__DF_SEARCH_STATUS__:"
_MISSING_ROOT = "missing"
# head closing the pipe after the limit kills the search with SIGPIPE: a
# successful truncation, not an error.
_SIGPIPE = 141
# Statuses of a complete search. grep: 0 = matches, 1 = no match. Everything
# else fails, even after printed results.
_OK_STATUSES: dict[str, tuple[int, ...]] = {"grep": (0, 1, _SIGPIPE), "find": (0, _SIGPIPE)}
# grep 2 / find 1 usually mean an unreadable file or subdirectory. Printed
# results are then incomplete and callers have no partial-result channel, so
# the error tells the agent to narrow the search instead.
_READ_ERROR_STATUS: dict[str, int] = {"grep": 2, "find": 1}


def remote_search_command(search: str, root: str, *, limit: int) -> str:
    """Wrap a ``grep``/``find`` command so its outcome survives ``| head``.

    ``search`` must write only results to stdout; callers keep ``2>/dev/null``.
    """
    quoted = shlex.quote(root)
    n = int(limit)
    return (
        f"set +e; if [ ! -e {quoted} ]; then printf '%s\\n' {_STATUS_PREFIX}{_MISSING_ROOT}; exit 0; fi; "
        f'_st=/tmp/df_search_$$; {{ {search}; echo $? > "$_st"; }} | head -n {n}; '
        f'st=$(cat "$_st" 2>/dev/null); rm -f "$_st"; '
        f"printf '\\n%s\\n' {_STATUS_PREFIX}\"$st\"; exit 0"
    )


def parse_remote_search_output(stdout: str | None, root: str, *, tool: SearchTool) -> str:
    """Return the search output without the status marker.

    Raises:
        FileNotFoundError: The search root does not exist.
        OSError: The search did not complete (missing binary, unreadable
            root or subtree, invalid invocation) or its status was lost.
    """
    # Split on "\n" only: splitlines() would also split on characters that are
    # legal in Linux filenames. Callers keep their own per-line handling.
    lines = (stdout or "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or not lines[-1].startswith(_STATUS_PREFIX):
        raise OSError(f"Failed to {tool} under {root}: search status marker missing")
    raw = lines.pop()[len(_STATUS_PREFIX) :]
    if raw == _MISSING_ROOT:
        raise FileNotFoundError(root)
    if lines and lines[-1] == "":
        lines.pop()
    try:
        status = int(raw)
    except ValueError:
        raise OSError(f"Failed to {tool} under {root}: search status unavailable") from None
    if status in _OK_STATUSES[tool]:
        return "\n".join(lines)
    if status == _READ_ERROR_STATUS[tool]:
        raise OSError(f"Failed to {tool} under {root}: {tool} exited with code {status}, usually because some files or directories could not be read; results would be incomplete, so search a narrower path")
    raise OSError(f"Failed to {tool} under {root}: command exited with code {status}")

"""Exit markers in the sandbox bash result protocol, without executing commands."""

import re
from typing import Literal

BASH_TOOL_NAMES = frozenset({"bash", "bash_tool"})

# Local/providers append a final line; silent remote failures use the whole body.
# Do not treat a phrase embedded in ordinary command output as an exit marker.
_EXIT_CODE_TAIL = re.compile(r"(?:^|\n)(Exit Code: (-?[0-9]+))\s*\Z")
_SILENT_EXIT = re.compile(r"(Command exited with code (-?[0-9]+))")


def bash_exit_status(content: str) -> tuple[Literal["success", "error"], str] | None:
    """Return reported execution status and the exact marker, or no marker.

    This is execution evidence, not task acceptance. A command's own trailing
    text can mimic the protocol, so retain the marker for evidence consumers.
    """
    match = _EXIT_CODE_TAIL.search(content) or _SILENT_EXIT.fullmatch(content.strip())
    if match is None:
        return None
    # String comparison also handles signed zero without converting unbounded
    # command-supplied digits through int(). Signals and timeout 124 are errors.
    status = "error" if match.group(2).lstrip("-0") else "success"
    return status, match.group(1)

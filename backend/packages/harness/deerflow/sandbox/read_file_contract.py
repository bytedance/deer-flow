"""Text markers shared by read_file and its display-only consumers."""

import io

READ_FILE_EMPTY = "(empty)"
READ_FILE_START_LINE_EXCEEDS = "(start_line exceeds file length)"
READ_FILE_INVALID_START_LINE = "(start_line must be >= 1)"
READ_FILE_INVALID_END_LINE = "(end_line must be >= 1)"
READ_FILE_INVALID_RANGE = "(invalid line range: start_line must be <= end_line)"
# Backward-compat alias — callers that imported READ_FILE_EMPTY_RANGE by name continue to work.
READ_FILE_EMPTY_RANGE = READ_FILE_INVALID_RANGE
READ_FILE_NO_CONTENT_RESULTS = frozenset(
    {
        READ_FILE_EMPTY,
        READ_FILE_START_LINE_EXCEEDS,
        READ_FILE_INVALID_START_LINE,
        READ_FILE_INVALID_END_LINE,
        READ_FILE_INVALID_RANGE,
    }
)
READ_FILE_TRUNCATION_PREFIX = "... [truncated:"
READ_FILE_NUMBERED_MAX_LINES = 40


def count_file_lines(content: str) -> int:
    """Count file lines as LocalSandbox and read_file's truncation marker see them.

    Uses ``count("\\n") + (1 if not endswith("\\n") else 0)`` — matching the
    ``newline="\\n"`` line iteration used by ``LocalSandbox.read_file`` and the formula in
    ``_truncate_read_file_output``.  This ensures the line count shown in the gate
    block message agrees with the ``start_line``/``end_line`` values the model can
    pass back to ``read_file``.

    Unlike ``splitlines()``, this function does not treat ``\\f``, ``\\v``, ``\\x85``,
    ``\\u2028``, or ``\\u2029`` as line separators — consistent with LocalSandbox's
    line iteration where those characters are just regular content.
    """
    if not content:
        return 0
    return content.count("\n") + (1 if not content.endswith("\n") else 0)


def split_file_lines(content: str) -> list[str]:
    """Split file content into the lines a ranged ``read_file`` numbers.

    Lines end only at ``"\\n"``, as in ``LocalSandbox.read_file`` and
    :func:`count_file_lines`, so ``len(split_file_lines(c)) == count_file_lines(c)``.
    A trailing ``"\\r"`` is dropped from each line, as ``LocalSandbox`` does for
    CRLF files. Remote providers that slice fetched content use this instead of
    ``splitlines()``, which also ends lines at a bare ``"\\r"``, ``\\f``, ``\\v``,
    ``\\x1c``-``\\x1e``, ``\\x85``, ``\\u2028`` and ``\\u2029``.
    """
    if not content:
        return []
    lines = content.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line.rstrip("\r") for line in lines]


def _line_start(content: str, line: int, pos: int = 0, at: int = 1) -> int:
    """Offset where 1-indexed ``line`` starts, counting from line ``at`` at ``pos``; -1 past the end."""
    remaining = line - at
    while remaining > 0:
        block_end = min(pos + 65536, len(content))
        newlines = content.count("\n", pos, block_end)
        if newlines < remaining:
            if block_end == len(content):
                return -1
            remaining -= newlines
            pos = block_end
            continue
        for _ in range(remaining):
            pos = content.index("\n", pos) + 1
        remaining = 0
    return pos


def slice_file_lines(content: str, start_line: int | None = None, end_line: int | None = None) -> str:
    """Return lines ``start_line``-``end_line`` of ``content`` as a ranged ``read_file`` does.

    The result equals joining ``split_file_lines(content)[start - 1 : end]``
    with ``"\\n"``, with ``start`` and ``end`` clamped as ``LocalSandbox.read_file``
    clamps them, but only the selected lines are copied: splitting a large,
    newline-dense file into a list of every line takes many times its size.
    """
    start = max(start_line or 1, 1)
    if end_line is not None and end_line < start:
        return ""
    begin = _line_start(content, start)
    if begin < 0 or begin >= len(content):
        return ""
    stop = len(content) if end_line is None else _line_start(content, end_line + 1, begin, start)
    text = content[begin : stop if stop >= 0 else len(content)]
    if text.endswith("\n"):
        text = text[:-1]
    return _drop_line_end_crs(text).rstrip("\r")


def _drop_line_end_crs(text: str) -> str:
    """Drop every run of ``"\\r"`` that sits directly before a ``"\\n"``.

    Every character is read a fixed number of times, so the time is linear
    however long a run of ``"\\r"`` is and whatever follows it, and the
    output is built as one string, never as a list of lines.
    """
    # One CR before each LF: the usual CRLF line, handled in C.
    text = text.replace("\r\n", "\n")
    if "\r\n" not in text:
        return text
    # A line ended in two or more CRs. Each remaining CRLF ends such a run:
    # cut the run off the text before it and keep the LF.
    out = io.StringIO()
    pos = 0
    while (crlf := text.find("\r\n", pos)) >= 0:
        out.write(text[pos:crlf].rstrip("\r"))
        out.write("\n")
        pos = crlf + 2
    out.write(text[pos:])
    return out.getvalue()

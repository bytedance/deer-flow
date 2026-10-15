"""Text markers shared by read_file and its display-only consumers."""

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

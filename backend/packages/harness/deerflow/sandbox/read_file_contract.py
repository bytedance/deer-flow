"""Text markers shared by read_file and its display-only consumers."""

READ_FILE_EMPTY = "(empty)"
READ_FILE_START_LINE_EXCEEDS = "(start_line exceeds file length)"
READ_FILE_INVALID_START_LINE = "(start_line must be >= 1)"
READ_FILE_INVALID_END_LINE = "(end_line must be >= 1)"
READ_FILE_EMPTY_RANGE = "(start_line > end_line — no lines in range)"
READ_FILE_NO_CONTENT_RESULTS = frozenset(
    {
        READ_FILE_EMPTY,
        READ_FILE_START_LINE_EXCEEDS,
        READ_FILE_INVALID_START_LINE,
        READ_FILE_INVALID_END_LINE,
        READ_FILE_EMPTY_RANGE,
    }
)
READ_FILE_TRUNCATION_PREFIX = "... [truncated:"

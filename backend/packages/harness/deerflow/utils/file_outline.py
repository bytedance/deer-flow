"""Shared document outline extraction.

Extracted from ``file_conversion.py`` and ``uploads_middleware.py`` so both
the middleware and the ``list_uploaded_files`` tool can use the same code.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import stat
from pathlib import Path
from typing import TextIO

logger = logging.getLogger(__name__)

# Regex for bold structural headings produced by pymupdf4llm when it can't
# promote bold text to a Markdown # heading (common in SEC filings).
#
# Chinese headings (第三节...) are already captured as standard # headings
# by pymupdf4llm, so they don't need this pattern.
_BOLD_HEADING_RE = re.compile(r"^\*\*((ITEM|PART|SECTION|SCHEDULE|EXHIBIT|APPENDIX|ANNEX|CHAPTER)\b[A-Z0-9 .,\-]*)\*\*\s*$")

# Regex for split-bold headings produced by pymupdf4llm when a heading spans
# multiple text spans in the PDF (e.g. section number and title are separate spans).
# Matches lines like:  **1** **Introduction**  or  **3.2** **Multi-Head Attention**
# Requirements:
#   1. Entire line consists only of **...** blocks separated by whitespace (no prose)
#   2. First block is a section number (digits and dots, e.g. "1", "3.2", "A.1")
#   3. Second block must not be purely numeric/punctuation — excludes financial table
#      headers like **2023** **2022** **2021** while allowing non-ASCII titles such as
#      **1** **概述** or accented words (negative lookahead instead of [A-Za-z])
#   4. At most two additional blocks (four total) with [^*]+ (no * inside) to keep
#      the regex linear and avoid ReDoS on attacker-controlled content
_SPLIT_BOLD_HEADING_RE = re.compile(r"^\*\*[\dA-Z][\d\.]*\*\*\s+\*\*(?!\d[\d\s.,\-–—/:()%]*\*\*)[^*]+\*\*(?:\s+\*\*[^*]+\*\*){0,2}\s*$")

# Maximum number of outline entries injected into the agent context.
# Keeps prompt size bounded even for very long documents.
MAX_OUTLINE_ENTRIES = 50

_OUTLINE_PREVIEW_LINES = 5


def _clean_bold_title(raw: str) -> str:
    """Normalise a title string that may contain pymupdf4llm bold artefacts.

    pymupdf4llm sometimes emits adjacent bold spans as ``**A** **B**`` instead
    of a single ``**A B**`` block.  This helper merges those fragments and then
    strips the outermost ``**...**`` wrapper so the caller gets plain text.

    Examples::

        "**Overview**"                       → "Overview"
        "**UNITED STATES** **SECURITIES**"   → "UNITED STATES SECURITIES"
        "plain text"                         → "plain text"  (unchanged)
    """
    # Merge adjacent bold spans: "** **" → " "
    merged = re.sub(r"\*\*\s*\*\*", " ", raw).strip()
    # Strip outermost **...** if the whole string is wrapped
    if m := re.fullmatch(r"\*\*(.+?)\*\*", merged, re.DOTALL):
        return m.group(1).strip()
    return merged


def extract_outline(md_path: Path) -> list[dict]:
    """Extract document outline (headings) from a Markdown file.

    Recognises three heading styles produced by pymupdf4llm:

    1. Standard Markdown headings: lines starting with one or more '#'.
       Inline ``**...**`` wrappers and adjacent bold spans (``** **``) are
       cleaned so the title is plain text.

    2. Bold-only structural headings: ``**ITEM 1. BUSINESS**``, ``**PART II**``,
       etc.  SEC filings use bold+caps for section headings with the same font
       size as body text, so pymupdf4llm cannot promote them to # headings.

    3. Split-bold headings: ``**1** **Introduction**``, ``**3.2** **Attention**``.
       pymupdf4llm emits these when the section number and title text are
       separate spans in the underlying PDF (common in academic papers).

    Args:
        md_path: Path to the .md file.

    Returns:
        List of dicts with keys: title (str), line (int, 1-based).
        When the outline is truncated at MAX_OUTLINE_ENTRIES, a sentinel entry
        ``{"truncated": True}`` is appended as the last element so callers can
        render a "showing first N headings" hint without re-scanning the file.
        Returns an empty list if the file cannot be read or has no headings.
    """
    try:
        with md_path.open(encoding="utf-8") as stream:
            outline, _ = _extract_outline_and_preview(stream)
            return outline
    except Exception:
        return []


def _extract_outline_and_preview(stream: TextIO) -> tuple[list[dict], list[str]]:
    """Parse outline and preview from one already-opened Markdown stream."""
    outline: list[dict] = []
    preview: list[str] = []
    for lineno, line in enumerate(stream, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if len(preview) < _OUTLINE_PREVIEW_LINES:
            preview.append(stripped)

        if stripped.startswith("#"):
            title = _clean_bold_title(stripped.lstrip("#").strip())
            if title:
                outline.append({"title": title, "line": lineno})
        elif m := _BOLD_HEADING_RE.match(stripped):
            title = m.group(1).strip()
            if title:
                outline.append({"title": title, "line": lineno})
        elif _SPLIT_BOLD_HEADING_RE.match(stripped):
            title = " ".join(re.findall(r"\*\*([^*]+)\*\*", stripped))
            if title:
                outline.append({"title": title, "line": lineno})

        if len(outline) > MAX_OUTLINE_ENTRIES:
            outline.pop()
            outline.append({"truncated": True})
            break

    return outline, [] if outline else preview


def _open_uploaded_markdown_posix(uploads_dir: Path, markdown_filename: str) -> TextIO:
    """Open one upload-relative Markdown file without following links on POSIX."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_only = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_only is None:
        raise OSError(errno.ENOTSUP, "Atomic no-follow opens are unavailable")

    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    directory_fd = -1
    file_fd = -1
    try:
        directory_fd = os.open(uploads_dir, os.O_RDONLY | directory_only | nofollow | close_on_exec)
        flags = os.O_RDONLY | nofollow | close_on_exec | getattr(os, "O_NONBLOCK", 0)
        file_fd = os.open(markdown_filename, flags, dir_fd=directory_fd)
        opened_stat = os.fstat(file_fd)
        if not stat.S_ISREG(opened_stat.st_mode) or opened_stat.st_nlink != 1:
            raise OSError(errno.EPERM, "Markdown companion is not an exclusive regular file")
        stream = os.fdopen(file_fd, "r", encoding="utf-8")
        file_fd = -1
        return stream
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _open_uploaded_markdown_windows(uploads_dir: Path, markdown_filename: str) -> TextIO:
    """Open one upload-relative Markdown file through verified Windows handles."""
    import ctypes
    import msvcrt
    import ntpath
    from ctypes import wintypes

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    get_file_information = kernel32.GetFileInformationByHandle
    get_file_information.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation)]
    get_file_information.restype = wintypes.BOOL
    get_file_type = kernel32.GetFileType
    get_file_type.argtypes = [wintypes.HANDLE]
    get_file_type.restype = wintypes.DWORD
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    get_final_path.restype = wintypes.DWORD

    invalid_handle = ctypes.c_void_p(-1).value
    # Omitting FILE_SHARE_DELETE pins the verified directory name until the
    # child handle has been opened and checked.
    share_read_write = 0x00000001 | 0x00000002
    share_all = share_read_write | 0x00000004
    open_existing = 3
    read_attributes = 0x00000080
    generic_read = 0x80000000
    backup_semantics = 0x02000000
    open_reparse_point = 0x00200000
    sequential_scan = 0x08000000
    file_attribute_directory = 0x00000010
    file_attribute_reparse_point = 0x00000400
    file_type_disk = 0x0001

    def winerror(path: Path) -> OSError:
        error_code = ctypes.get_last_error()
        return OSError(error_code, ctypes.FormatError(error_code), str(path))

    def open_handle(path: Path, access: int, share_mode: int, flags: int) -> int:
        handle = create_file(str(path), access, share_mode, None, open_existing, flags, None)
        if handle == invalid_handle:
            raise winerror(path)
        return handle

    def handle_information(handle: int, path: Path) -> _ByHandleFileInformation:
        information = _ByHandleFileInformation()
        if not get_file_information(handle, ctypes.byref(information)):
            raise winerror(path)
        return information

    def final_path(handle: int, path: Path) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_final_path(handle, buffer, len(buffer), 0)
        if length == 0:
            raise winerror(path)
        if length >= len(buffer):
            raise OSError(errno.ENAMETOOLONG, "Opened Markdown path is too long", str(path))
        return buffer.value

    def normalized(path: str) -> str:
        return ntpath.normcase(ntpath.normpath(path.rstrip("\\/")))

    candidate = uploads_dir / markdown_filename
    directory_handle = invalid_handle
    file_handle = invalid_handle
    file_fd = -1
    try:
        directory_handle = open_handle(uploads_dir, read_attributes, share_read_write, backup_semantics | open_reparse_point)
        directory_info = handle_information(directory_handle, uploads_dir)
        if not directory_info.dwFileAttributes & file_attribute_directory or directory_info.dwFileAttributes & file_attribute_reparse_point:
            raise OSError(errno.EPERM, "Uploads directory is not a regular directory", str(uploads_dir))

        file_handle = open_handle(candidate, generic_read | read_attributes, share_all, open_reparse_point | sequential_scan)
        file_info = handle_information(file_handle, candidate)
        if get_file_type(file_handle) != file_type_disk or file_info.dwFileAttributes & (file_attribute_directory | file_attribute_reparse_point) or file_info.nNumberOfLinks != 1:
            raise OSError(errno.EPERM, "Markdown companion is not an exclusive regular file", str(candidate))
        # Query containment only while both identity-bearing handles are live.
        directory_final_path = normalized(final_path(directory_handle, uploads_dir))
        if normalized(ntpath.dirname(final_path(file_handle, candidate))) != directory_final_path:
            raise OSError(errno.EPERM, "Markdown companion resolved outside uploads", str(candidate))

        file_fd = msvcrt.open_osfhandle(file_handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        file_handle = invalid_handle
        stream = os.fdopen(file_fd, "r", encoding="utf-8")
        file_fd = -1
        return stream
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if file_handle != invalid_handle:
            close_handle(file_handle)
        if directory_handle != invalid_handle:
            close_handle(directory_handle)


def _open_uploaded_markdown(uploads_dir: Path, markdown_filename: str) -> TextIO:
    if not isinstance(markdown_filename, str) or not markdown_filename:
        raise ValueError("Markdown companion must be a non-empty basename")
    if "/" in markdown_filename or "\\" in markdown_filename or Path(markdown_filename).name != markdown_filename:
        raise ValueError("Markdown companion must be a basename")
    if ":" in markdown_filename:
        raise ValueError("Markdown companion must not contain alternate stream syntax")
    if Path(markdown_filename).suffix.lower() != ".md":
        raise ValueError("Markdown companion must have a .md suffix")
    if os.name == "nt":
        return _open_uploaded_markdown_windows(uploads_dir, markdown_filename)
    return _open_uploaded_markdown_posix(uploads_dir, markdown_filename)


def extract_outline_from_markdown(md_path: Path) -> tuple[list[dict], list[str]]:
    """Return the document outline and fallback preview for an exact Markdown path."""
    if not md_path.is_file():
        return [], []
    try:
        with md_path.open(encoding="utf-8") as stream:
            outline, preview = _extract_outline_and_preview(stream)
    except Exception:
        logger.debug("Failed to read outline data from %s", md_path, exc_info=True)
        return [], []

    if outline:
        logger.debug("Extracted %d outline entries from %s", len(outline), md_path.name)
    return outline, preview


def extract_outline_from_uploaded_markdown(uploads_dir: Path, markdown_filename: str) -> tuple[list[dict], list[str]]:
    """Return outline data from one safely opened explicit upload companion."""
    try:
        with _open_uploaded_markdown(uploads_dir, markdown_filename) as stream:
            outline, preview = _extract_outline_and_preview(stream)
    except Exception:
        logger.warning("Ignoring an unsafe or unreadable explicit Markdown companion", exc_info=True)
        return [], []

    if outline:
        logger.debug("Extracted %d outline entries from an explicit Markdown companion", len(outline))
    return outline, preview


def extract_outline_for_file(file_path: Path) -> tuple[list[dict], list[str]]:
    """Return outline data from the legacy same-stem Markdown companion."""
    return extract_outline_from_markdown(file_path.with_suffix(".md"))

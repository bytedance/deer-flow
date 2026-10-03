import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

IGNORE_PATTERNS = [
    ".git",
    ".svn",
    ".hg",
    ".bzr",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".env",
    "env",
    ".tox",
    ".nox",
    ".eggs",
    "*.egg-info",
    "site-packages",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".output",
    ".turbo",
    "target",
    "out",
    ".idea",
    ".vscode",
    "*.swp",
    "*.swo",
    "*~",
    ".project",
    ".classpath",
    ".settings",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "*.lnk",
    "*.log",
    "*.tmp",
    "*.temp",
    ".upload-*.part",
    "*.bak",
    "*.cache",
    ".cache",
    "logs",
    ".coverage",
    "coverage",
    ".nyc_output",
    "htmlcov",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
]

DEFAULT_MAX_FILE_SIZE_BYTES = 1_000_000
DEFAULT_LINE_SUMMARY_LENGTH = 200


@dataclass(frozen=True)
class GrepMatch:
    path: str
    line_number: int
    line: str


# ``should_ignore_name`` runs once per directory entry during glob/grep tree
# walks, so we avoid ~50 ``fnmatch`` calls per name. Most ignore patterns are
# literal names (O(1) set lookup after normcase); the few glob patterns are
# pre-translated into a single combined regex. ``os.path.normcase`` keeps the
# same case behavior ``fnmatch`` applies (case-sensitive on POSIX, folded on
# Windows).
_EXACT_IGNORE_NAMES = frozenset(os.path.normcase(p) for p in IGNORE_PATTERNS if not any(c in p for c in "*?["))
_GLOB_IGNORE_PATTERNS = [p for p in IGNORE_PATTERNS if any(c in p for c in "*?[")]
_GLOB_IGNORE_RE = re.compile("|".join(fnmatch.translate(os.path.normcase(p)) for p in _GLOB_IGNORE_PATTERNS)) if _GLOB_IGNORE_PATTERNS else None


def should_ignore_name(name: str) -> bool:
    normalized = os.path.normcase(name)
    if normalized in _EXACT_IGNORE_NAMES:
        return True
    return _GLOB_IGNORE_RE is not None and _GLOB_IGNORE_RE.match(normalized) is not None


def should_ignore_path(path: str) -> bool:
    return any(should_ignore_name(segment) for segment in path.replace("\\", "/").split("/") if segment)


def _match_segments(pattern_parts: tuple[str, ...], path_parts: tuple[str, ...]) -> bool:
    # Positions in ``path_parts`` reachable after consuming each pattern part;
    # ``**`` spans zero or more whole segments, any other part exactly one.
    reachable = {0}
    for part in pattern_parts:
        if part == "**":
            reachable = set(range(min(reachable), len(path_parts) + 1))
        else:
            reachable = {i + 1 for i in reachable if i < len(path_parts) and fnmatch.fnmatchcase(path_parts[i], part)}
        if not reachable:
            return False
    return len(path_parts) in reachable


def should_ignore_path_under_root(path: str, root: str) -> bool:
    """Apply :func:`should_ignore_path` to ``path`` as seen from ``root``.

    Ignore patterns are scoped to the search root, the way ``list_dir`` already
    applies them: an ignored name hides its own descendants, so searching
    ``build`` -- or any path below an ignored ancestor -- still returns its
    contents. Testing the absolute path instead silently hides every result as
    soon as the search root, or one of its ancestors, is itself an ignored
    name, so ``glob``/``grep`` reported "no matches" for a directory the local
    walk lists without any trouble.
    """
    root_clean = root.rstrip("/")
    if not root_clean:
        root_clean = "/"
    if path == root_clean:
        # The caller asked for this exact path. There is nothing relative to
        # test, and an ignored name must not hide what was explicitly
        # requested (a single-file ``grep`` hits this on every match).
        return False
    prefix = "/" if root_clean == "/" else f"{root_clean}/"
    if path.startswith(prefix):
        return should_ignore_path(path[len(prefix) :])
    return should_ignore_path(path)


def path_matches(pattern: str, rel_path: str) -> bool:
    """Match ``rel_path`` (relative to the search root) against a glob pattern.

    A pattern without ``/`` matches the basename at any depth (``*.py``). Any
    other pattern is anchored at the search root, and ``**`` matches zero or
    more directories (``src/**/*.py`` includes ``src/top.py``).
    ``PurePosixPath.match`` is not used for these: it matches from the right
    and treats ``**`` as a single-segment ``*``.
    """
    if "/" not in pattern:
        return PurePosixPath(rel_path).match(pattern)
    return _match_segments(PurePosixPath(pattern).parts, PurePosixPath(rel_path).parts)


def truncate_line(line: str, max_chars: int = DEFAULT_LINE_SUMMARY_LENGTH) -> str:
    line = line.rstrip("\n\r")
    if len(line) <= max_chars:
        return line
    return line[: max_chars - 3] + "..."


def is_binary_file(path: Path, sample_size: int = 8192) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\0" in handle.read(sample_size)
    except OSError:
        return True


def find_glob_matches(root: Path, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
    matches: list[str] = []
    root = root.resolve()

    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    for current_root, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if not should_ignore_name(name)]
        # root is already resolved; os.walk builds current_root by joining under root,
        # so relative_to() works without an extra stat()/resolve() per directory.
        rel_dir = Path(current_root).relative_to(root)

        if include_dirs:
            for name in dirs:
                rel_path = (rel_dir / name).as_posix()
                if path_matches(pattern, rel_path):
                    matches.append(str(Path(current_root) / name))
                    if len(matches) > max_results:
                        return matches[:max_results], True

        for name in files:
            if should_ignore_name(name):
                continue
            rel_path = (rel_dir / name).as_posix()
            if path_matches(pattern, rel_path):
                matches.append(str(Path(current_root) / name))
                # Look one match past the cap before deciding. Stopping on the
                # max-th match cannot tell a tree that held exactly
                # ``max_results`` matches from one that held more, so an
                # exhausted walk was reported as truncated; the same line also
                # returned one match for ``max_results=0``. ``AioSandbox.glob``
                # and the shared ``parse_remote_search_output`` cap decide the
                # same way.
                if len(matches) > max_results:
                    return matches[:max_results], True

    return matches, False


def find_grep_matches(
    root: Path,
    pattern: str,
    *,
    glob_pattern: str | None = None,
    literal: bool = False,
    case_sensitive: bool = False,
    max_results: int = 100,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE_BYTES,
    line_summary_length: int = DEFAULT_LINE_SUMMARY_LENGTH,
) -> tuple[list[GrepMatch], bool]:
    matches: list[GrepMatch] = []
    root = root.resolve()

    if not root.exists():
        raise FileNotFoundError(root)
    root_is_file = root.is_file()
    if not root_is_file and not root.is_dir():
        raise NotADirectoryError(root)

    regex_source = re.escape(pattern) if literal else pattern
    flags = 0 if case_sensitive else re.IGNORECASE
    regex = re.compile(regex_source, flags)

    # Skip lines longer than this to prevent ReDoS on minified / no-newline files.
    _max_line_chars = line_summary_length * 10

    def candidate_files():
        if root_is_file:
            yield root, root.name
            return

        for current_root, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if not should_ignore_name(name)]
            rel_dir = Path(current_root).relative_to(root)
            for name in files:
                if should_ignore_name(name):
                    continue
                yield Path(current_root) / name, (rel_dir / name).as_posix()

    for candidate_path, rel_path in candidate_files():
        if glob_pattern is not None and not path_matches(glob_pattern, rel_path):
            continue

        try:
            if not root_is_file and candidate_path.is_symlink():
                continue
            file_path = candidate_path.resolve()
            if not root_is_file and not file_path.is_relative_to(root):
                continue
            if file_path.stat().st_size > max_file_size or is_binary_file(file_path):
                continue
            with file_path.open(encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if len(line) > _max_line_chars:
                        continue
                    if regex.search(line):
                        matches.append(
                            GrepMatch(
                                path=str(file_path),
                                line_number=line_number,
                                line=truncate_line(line, line_summary_length),
                            )
                        )
                        # Same one-past-the-cap decision as ``find_glob_matches``:
                        # a search whose last eligible line lands exactly on the
                        # cap is complete, not truncated.
                        if len(matches) > max_results:
                            return matches[:max_results], True
        except OSError:
            continue

    return matches, False

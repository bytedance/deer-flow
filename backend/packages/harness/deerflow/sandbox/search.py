import errno
import fnmatch
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# Repository noise: version-control metadata, dependency trees, build output
# and editor scratch. These names are machinery, never user content.
REPO_IGNORE_PATTERNS = [
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
    ".coverage",
    "coverage",
    ".nyc_output",
    "htmlcov",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
]

# Data-looking names that are ordinary user files. Uploads arrive as ``*.log``
# and ``logs/`` is a directory the user made, so outside a git checkout these
# stay searchable; inside one they are the repository noise the list is for.
# ``.upload-*.part`` is the in-flight upload suffix and stays ignored everywhere.
USER_DATA_PATTERNS = ["*.log", "*.tmp", "*.temp", "*.bak", "*.cache", ".cache", "logs"]

# In-flight uploads are repository machinery, not content: they stay hidden in
# user data too, until publication renames them.
STAGING_PATTERNS = [".upload-*.part"]

# ``should_ignore_name`` keeps answering with the repository defaults.
IGNORE_PATTERNS = [*REPO_IGNORE_PATTERNS, *USER_DATA_PATTERNS, *STAGING_PATTERNS]

# Directory walks skip files above this so one huge log cannot stall a search;
# a file named as the search root is read whatever its size.
DEFAULT_MAX_FILE_SIZE_BYTES = 1_000_000
DEFAULT_LINE_SUMMARY_LENGTH = 200
_GREP_RACE_ERRNOS = {errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EISDIR, getattr(errno, "ESTALE", errno.ENOENT)}


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
def _compile_ignore_patterns(patterns: list[str]) -> tuple[frozenset[str], re.Pattern[str] | None]:
    exact = frozenset(os.path.normcase(p) for p in patterns if not any(c in p for c in "*?["))
    globs = [p for p in patterns if any(c in p for c in "*?[")]
    combined = re.compile("|".join(fnmatch.translate(os.path.normcase(p)) for p in globs)) if globs else None
    return exact, combined


@dataclass(frozen=True)
class IgnoreRules:
    """Name filter for one search root."""

    exact: frozenset[str]
    glob_re: re.Pattern[str] | None

    def should_ignore(self, name: str) -> bool:
        normalized = os.path.normcase(name)
        if normalized in self.exact:
            return True
        return self.glob_re is not None and self.glob_re.match(normalized) is not None


_REPOSITORY_RULES = IgnoreRules(*_compile_ignore_patterns(IGNORE_PATTERNS))
_CONTENT_RULES = IgnoreRules(*_compile_ignore_patterns([*REPO_IGNORE_PATTERNS, *STAGING_PATTERNS]))


def should_ignore_name(name: str) -> bool:
    """What a search inside a git checkout hides: the repository defaults."""
    return _REPOSITORY_RULES.should_ignore(name)


def _names_user_data(pattern: str) -> bool:
    return any(fnmatch.fnmatchcase(part, candidate) for part in pattern.split("/") for candidate in USER_DATA_PATTERNS)


def ignore_rules_for(search_root: Path, *, glob: str | None = None, user_data: bool = False) -> IgnoreRules:
    """Names to skip while searching ``search_root``.

    Everything except the user's own files keeps the repository filter, so a
    skills mount or an ad-hoc host path hides ``*.log`` as it always did.
    ``user_data`` marks a root the sandbox maps to ``/mnt/user-data``; there
    ``*.log`` and ``logs/`` are content, so only repository noise is hidden. A
    glob the caller spelled out wins over the defaults: asking for ``*.log`` is
    a request for logs, even in a checkout.
    """
    if user_data or (glob is not None and _names_user_data(glob)):
        return _CONTENT_RULES
    return _REPOSITORY_RULES


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
    with path.open("rb") as handle:
        return b"\0" in handle.read(sample_size)


def find_glob_matches(
    root: Path,
    pattern: str,
    *,
    include_dirs: bool = False,
    max_results: int = 200,
    relative_prefix: str = "",
    user_data: bool = False,
) -> tuple[list[str], bool]:
    matches: list[str] = []
    truncated = False
    root = root.resolve()

    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    rules = ignore_rules_for(root, glob=pattern, user_data=user_data)

    def handle_walk_error(error: OSError) -> None:
        # Entries may disappear or change type during enumeration. Other
        # errors, such as permission failures, must reach the caller rather
        # than being reported as an incomplete successful search.
        if error.errno not in _GREP_RACE_ERRNOS:
            raise error

    for current_root, dirs, files in os.walk(root, onerror=handle_walk_error):
        dirs[:] = [name for name in dirs if not rules.should_ignore(name)]
        # root is already resolved; os.walk builds current_root by joining under root,
        # so relative_to() works without an extra stat()/resolve() per directory.
        rel_dir = Path(current_root).relative_to(root)

        if include_dirs:
            for name in dirs:
                rel_path = (rel_dir / name).as_posix()
                if relative_prefix:
                    rel_path = f"{relative_prefix}/{rel_path}"
                if path_matches(pattern, rel_path):
                    matches.append(str(Path(current_root) / name))
                    if len(matches) >= max_results:
                        truncated = True
                        return matches, truncated

        for name in files:
            if rules.should_ignore(name):
                continue
            rel_path = (rel_dir / name).as_posix()
            if relative_prefix:
                rel_path = f"{relative_prefix}/{rel_path}"
            if path_matches(pattern, rel_path):
                matches.append(str(Path(current_root) / name))
                if len(matches) >= max_results:
                    truncated = True
                    return matches, truncated

    return matches, truncated


def _make_literal_matcher(pattern: str, *, case_sensitive: bool) -> Callable[[str], bool]:
    if case_sensitive:
        return lambda line: pattern in line
    if not pattern:
        return lambda _line: True

    # KMP bounds comparisons by pattern + text length. Matching one character
    # at a time retains re.IGNORECASE's Unicode equivalences without rescanning
    # a long escaped prefix. Full-string casefold would change cases such as ß.
    by_character = {character: re.compile(re.escape(character), re.IGNORECASE).fullmatch for character in set(pattern)}
    character_matches = [by_character[character] for character in pattern]
    failure = [0] * len(pattern)
    prefix_length = 0
    for index in range(1, len(pattern)):
        while prefix_length and not character_matches[prefix_length](pattern[index]):
            prefix_length = failure[prefix_length - 1]
        if character_matches[prefix_length](pattern[index]):
            prefix_length += 1
        failure[index] = prefix_length

    def matches_line(line: str) -> bool:
        matched = 0
        for character in line:
            while matched and not character_matches[matched](character):
                matched = failure[matched - 1]
            if character_matches[matched](character):
                matched += 1
                if matched == len(pattern):
                    return True
        return False

    return matches_line


def find_grep_matches(
    root: Path,
    pattern: str,
    *,
    glob_pattern: str | None = None,
    literal: bool = False,
    case_sensitive: bool = False,
    max_results: int = 100,
    max_file_size: int | None = None,
    line_summary_length: int = DEFAULT_LINE_SUMMARY_LENGTH,
    relative_prefix: str = "",
    user_data: bool = False,
    display_line: Callable[[str], str] | None = None,
) -> tuple[list[GrepMatch], bool]:
    """Search text files under ``root``.

    ``display_line`` rewrites a matched line for the caller before it is
    shortened to ``line_summary_length``; the pattern still matches the stored
    text. Rewriting after shortening could leave a cut-off fragment behind.
    """
    matches: list[GrepMatch] = []
    truncated = False
    root = root.resolve()

    if not root.exists():
        raise FileNotFoundError(root)
    root_is_file = root.is_file()
    if not root_is_file and not root.is_dir():
        raise NotADirectoryError(root)
    # The traversal budget keeps a directory walk bounded; a file the caller
    # named is read whatever its size, unless that caller sets its own budget.
    size_limit = DEFAULT_MAX_FILE_SIZE_BYTES if max_file_size is None else max_file_size

    if literal:
        matches_line = _make_literal_matcher(pattern, case_sensitive=case_sensitive)
    else:
        regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        matches_line = regex.search

    # Only regex searches need the long-line work guard. Literal matching
    # avoids repeated-prefix rescans, including case-insensitive searches.
    _max_line_chars = line_summary_length * 10

    rules = ignore_rules_for(root, glob=glob_pattern, user_data=user_data)

    def handle_search_error(error: OSError) -> None:
        # Entries may disappear or change type during enumeration or reading.
        if error.errno not in _GREP_RACE_ERRNOS:
            raise error

    def candidate_files():
        if root_is_file:
            yield root, root.name
            return

        for current_root, dirs, files in os.walk(root, onerror=handle_search_error):
            dirs[:] = [name for name in dirs if not rules.should_ignore(name)]
            rel_dir = Path(current_root).relative_to(root)
            for name in files:
                if rules.should_ignore(name):
                    continue
                yield Path(current_root) / name, (rel_dir / name).as_posix()

    for candidate_path, rel_path in candidate_files():
        if relative_prefix:
            rel_path = f"{relative_prefix}/{rel_path}"
        if glob_pattern is not None and not path_matches(glob_pattern, rel_path):
            continue

        try:
            if not root_is_file and candidate_path.is_symlink():
                continue
            file_path = candidate_path.resolve()
            if not root_is_file and not file_path.is_relative_to(root):
                continue
            file_stat = file_path.stat()
            if not stat.S_ISREG(file_stat.st_mode):
                continue
            if is_binary_file(file_path):
                continue
            if file_stat.st_size > size_limit and (not root_is_file or max_file_size is not None):
                continue
            # newline="\n" ends lines where LocalSandbox.read_file does, so a
            # hit's line_number is the start_line that reads it back; a bare
            # "\r" stays content. Like native grep on Unix, local matching
            # excludes LF. LocalSandbox also strips the CR in CRLF, so $ anchors
            # at the end of the line text for both line endings.
            with file_path.open(encoding="utf-8", errors="replace", newline="\n") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if line.endswith("\r\n"):
                        line = line[:-2]
                    elif line.endswith("\n"):
                        line = line[:-1]
                    if not literal and len(line) > _max_line_chars:
                        continue
                    if matches_line(line):
                        matches.append(
                            GrepMatch(
                                path=str(file_path),
                                line_number=line_number,
                                line=truncate_line(display_line(line) if display_line is not None else line, line_summary_length),
                            )
                        )
                        if len(matches) >= max_results:
                            truncated = True
                            return matches, truncated
        except OSError as exc:
            handle_search_error(exc)

    return matches, truncated

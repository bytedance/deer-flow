"""Shared search semantics through real providers and offline execution seams.

Shell-backed providers run their production command strings with local sh/find/
grep. AIO's file RPC seam reads the same fixture tree independently. The
user-data cases map each provider's backing directory the way its production
mapping does (virtual prefix kept, or rewritten under a home directory), so the
labeling logic runs for real. This does not test a live SDK/server, shell-session
lifecycle, or provider provisioning.
"""

from __future__ import annotations

import fnmatch
import glob as filesystem_glob
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping

PROVIDERS = ("local", "aio", "e2b", "boxlite", "tenki", "opensandbox", "boxd")
REMOTE_PROVIDERS = tuple(name for name in PROVIDERS if name != "local")
SHELL_SEARCH_PROVIDERS = ("e2b", "boxlite", "tenki", "opensandbox", "boxd")
# Providers whose _resolve_path rewrites VIRTUAL_PATH_PREFIX under a home dir.
HOME_REWRITE_PROVIDERS = ("e2b", "tenki")
pytestmark = pytest.mark.skipif(
    os.name == "nt" or any(shutil.which(name) is None for name in ("sh", "find", "grep", "head")),
    reason="offline provider search contract requires a POSIX shell and search utilities",
)


class _Transport:
    """Execution/RPC replacement; never returns precomputed contract answers."""

    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.env = os.environ.copy()
        self.error: OSError | None = None
        # Container-absolute roots (the user-data cases) map onto a real
        # directory under tmp_path, the way a container rootfs would.
        self.path_map: dict[str, str] = {}
        self.commands: list[str] = []

    def _to_host(self, path: str) -> str:
        normalized = path.replace("\\", "/")
        for virtual, host in self.path_map.items():
            if normalized == virtual or normalized.startswith(virtual + "/"):
                return host + normalized[len(virtual) :]
        return path

    def _to_virtual(self, path: str) -> str:
        normalized = path.replace("\\", "/")
        for virtual, host in self.path_map.items():
            host_normalized = host.replace("\\", "/")
            if normalized == host_normalized or normalized.startswith(host_normalized + "/"):
                return virtual + normalized[len(host_normalized) :]
        return path

    def check(self, path: str | None = None):
        if self.error is not None:
            raise self.error
        if path is not None and not Path(self._to_host(path)).exists():
            raise FileNotFoundError(path)

    def shell(self, command: str, **_kwargs):
        self.check()
        self.commands.append(command)
        for virtual, host in self.path_map.items():
            # shlex.quote leaves simple paths unquoted; replace the bare token
            # at a command-word boundary so quoted and unquoted forms both map.
            # MSYS sh treats unquoted backslashes as escapes, so re-quote the
            # host path; a lambda replacement keeps the backslashes literal.
            command = re.sub(r"(?<![\w./\\-])" + re.escape(virtual), lambda _m, h=host: shlex.quote(h), command)
        result = subprocess.run(["sh", "-c", command], capture_output=True, text=True, env=self.env, timeout=10, check=False)
        stdout = result.stdout
        for virtual, host in self.path_map.items():
            for host_spelling in {host, host.replace("\\", "/")}:
                stdout = stdout.replace(host_spelling, virtual)
        return SimpleNamespace(stdout=stdout, stderr=result.stderr, stdout_text=stdout, stderr_text=result.stderr, exit_code=result.returncode)

    def aio_shell(self, *, command: str, **kwargs):
        result = self.shell(command, **kwargs)
        return SimpleNamespace(data=SimpleNamespace(output=result.stdout, exit_code=result.exit_code))

    def opensandbox_shell(self, command: str, **kwargs):
        result = self.shell(command, **kwargs)
        return SimpleNamespace(logs=SimpleNamespace(stdout=[SimpleNamespace(text=result.stdout)], stderr=[]), exit_code=result.exit_code, error=None)

    def missing_program(self, name: str):
        directory = self.tmp_path / "unavailable-program"
        directory.mkdir()
        program = directory / name
        program.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
        program.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + self.env.get("PATH", "")

    def glob_files(
        self,
        *,
        path: str,
        pattern: str,
        files_only: bool = True,
        include_hidden: bool = True,
        include_metadata: bool = False,
        max_results: int | None = None,
    ):
        self.check(path)
        assert include_metadata is False
        # Python's filesystem glob is independent of DeerFlow's path_matches.
        # The real endpoint has been observed returning directories even when
        # the caller asked for files only, so the fake keeps both types: the
        # provider must filter files itself before applying its cap.
        host = self._to_host(path)
        matches = sorted(filesystem_glob.glob(filesystem_glob.escape(host) + "/" + pattern, recursive=True))
        truncated = max_results is not None and len(matches) > max_results
        if truncated:
            matches = matches[:max_results]
        return SimpleNamespace(
            data=SimpleNamespace(
                files=[SimpleNamespace(path=self._to_virtual(p), is_directory=Path(p).is_dir()) for p in matches],
                truncated=truncated,
            )
        )

    def list_path(self, *, path: str, recursive: bool, show_hidden: bool, file_types=None):
        self.check(path)
        assert recursive and show_hidden
        # ``file_types`` filters files by extension server-side; directories
        # are returned regardless, as the real endpoint does. The endpoint
        # drops the whole leading dot-run from a dot-only name, so a name such
        # as ``.csv`` or ``..csv`` has no extension.
        suffixes = tuple(file_types) if file_types else None
        host = Path(self._to_host(path))
        entries = [p for p in sorted(host.rglob("*")) if p.is_dir() or suffixes is None or os.path.splitext(p.name)[1] in suffixes]
        return SimpleNamespace(data=SimpleNamespace(files=[SimpleNamespace(path=self._to_virtual(str(p)), is_directory=p.is_dir()) for p in entries]))

    def grep_files(self, *, path: str, pattern: str, case_insensitive: bool, fixed_strings: bool, max_results: int, max_file_size: str, recursive: bool, include=None):
        self.check(path)
        assert recursive and max_file_size == "1M"
        includes = list(include) if include else None
        matcher = re.compile(re.escape(pattern) if fixed_strings else pattern, re.IGNORECASE if case_insensitive else 0)
        root = Path(self._to_host(path))
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        if includes:
            files = [p for p in files if any(fnmatch.fnmatchcase(p.name, pattern) for pattern in includes)]
        matches = []
        for file in files:
            for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                if matcher.search(line):
                    matches.append(SimpleNamespace(file=self._to_virtual(str(file)), line_number=number, line_content=line))
        return SimpleNamespace(data=SimpleNamespace(matches=matches[:max_results], truncated=len(matches) > max_results))


@pytest.fixture(params=PROVIDERS)
def provider(request, tmp_path, monkeypatch):
    name = request.param
    transport = _Transport(tmp_path)
    if name == "local":
        sandbox = LocalSandbox("search-contract")
    elif name == "aio":
        from deerflow.community.aio_sandbox import aio_sandbox as module

        client = SimpleNamespace(file=transport, shell=SimpleNamespace(exec_command=transport.aio_shell))
        monkeypatch.setattr(module, "AioSandboxClient", lambda **kwargs: client)
        monkeypatch.setattr(module, "sandbox_http_trust_env", lambda _url: True)
        sandbox = module.AioSandbox("search-contract", "http://127.0.0.1:1", home_dir=str(tmp_path))
    elif name == "e2b":
        from deerflow.community.e2b_sandbox.e2b_sandbox import E2BSandbox

        sandbox = E2BSandbox("search-contract", SimpleNamespace(commands=SimpleNamespace(run=transport.shell)))
    elif name == "boxlite":
        from deerflow.community.boxlite.box import BoxliteBox

        sandbox = BoxliteBox("search-contract", SimpleNamespace(), run=None)
        monkeypatch.setattr(sandbox, "_sh", transport.shell)
    elif name == "tenki":
        from deerflow.community.tenki.sandbox import TenkiSandbox

        sandbox = TenkiSandbox("search-contract", SimpleNamespace())
        monkeypatch.setattr(sandbox, "_sh", transport.shell)
    elif name == "opensandbox":
        from deerflow.community.opensandbox.sandbox import OpenSandboxSandbox

        sandbox = OpenSandboxSandbox("search-contract", SimpleNamespace(), run_command_opts_cls=SimpleNamespace)
        monkeypatch.setattr(sandbox, "_run", transport.opensandbox_shell)
    elif name == "boxd":
        from deerflow.community.boxd_sandbox.boxd_sandbox import BoxdSandbox

        sandbox = BoxdSandbox("search-contract", SimpleNamespace(), "machine-id")
        monkeypatch.setattr(sandbox, "run_shell", transport.shell)
    else:
        raise AssertionError(f"Unregistered contract provider: {name}")
    return SimpleNamespace(name=name, sandbox=sandbox, transport=transport)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "project [one]'s 中文"
    root.mkdir()
    (root / "nested").mkdir()
    (root / "node_modules").mkdir()
    (root / "-résumé '中文'.txt").write_text("header\nneedle exact\nNeedle upper\n", encoding="utf-8")
    (root / "nested" / "result.txt").write_text("needle nested\n", encoding="utf-8")
    (root / "node_modules" / "dependency.txt").write_text("needle ignored\n", encoding="utf-8")
    return root


@pytest.fixture
def ignored_name_tree(tmp_path):
    """A tree whose root *and* one nested directory carry an ignored name.

    ``build`` is in ``IGNORE_PATTERNS``; ``node_modules`` is ignored one level
    below it. ``list_dir`` already scopes ignore patterns to the listing root,
    so an ignored name may not hide the root that was explicitly requested,
    while an ignored name inside the tree keeps hiding its descendants.
    """
    root = tmp_path / "build"
    (root / "node_modules" / "dep").mkdir(parents=True)
    (root / "workspace").mkdir()
    (root / "notes.txt").write_text("header\nneedle build\n", encoding="utf-8")
    (root / "workspace" / "report.txt").write_text("needle nested\n", encoding="utf-8")
    (root / "node_modules" / "dep" / "lib.js").write_text("needle hidden\n", encoding="utf-8")
    return root


def _relative_paths(paths, root):
    # Directory suffixes and inclusion of the requested root are legitimate
    # provider presentation differences; names and descendants must agree.
    return {Path(path.rstrip("/")).relative_to(root).as_posix() for path in paths if Path(path.rstrip("/")) != root}


def _call(sandbox, operation, root):
    if operation == "ls":
        return sandbox.list_dir(str(root))
    if operation == "glob":
        return sandbox.glob(str(root), "**/*.txt")
    return sandbox.grep(str(root), "needle")


def test_listing_preserves_paths_and_ignores_descendants(provider, tree):
    assert _relative_paths(provider.sandbox.list_dir(str(tree)), tree) == {"-résumé '中文'.txt", "nested", "nested/result.txt"}


def test_glob_preserves_paths_and_ignores_descendants(provider, tree):
    matches, truncated = provider.sandbox.glob(str(tree), "**/*.txt")
    assert _relative_paths(matches, tree) == {"-résumé '中文'.txt", "nested/result.txt"}
    assert truncated is False


def test_glob_can_include_directories(provider, tree):
    matches, truncated = provider.sandbox.glob(str(tree), "**/nested", include_dirs=True)
    assert _relative_paths(matches, tree) == {"nested"}
    assert truncated is False


def test_search_root_at_an_ignored_name_keeps_its_contents(provider, ignored_name_tree):
    assert _relative_paths(provider.sandbox.list_dir(str(ignored_name_tree)), ignored_name_tree) == {"notes.txt", "workspace", "workspace/report.txt"}
    matches, truncated = provider.sandbox.glob(str(ignored_name_tree), "**/*.txt")
    assert _relative_paths(matches, ignored_name_tree) == {"notes.txt", "workspace/report.txt"}
    assert truncated is False


def test_search_root_below_an_ignored_name_keeps_its_contents(provider, ignored_name_tree):
    root = ignored_name_tree / "workspace"
    matches, truncated = provider.sandbox.glob(str(root), "**/*.txt")
    assert _relative_paths(matches, root) == {"report.txt"}
    assert truncated is False


def test_search_root_at_an_ignored_name_still_hides_ignored_descendants(provider, ignored_name_tree):
    assert provider.sandbox.glob(str(ignored_name_tree), "**/*.js") == ([], False)
    matches, truncated = provider.sandbox.grep(str(ignored_name_tree), "needle")
    assert {(Path(m.path).relative_to(ignored_name_tree).as_posix(), m.line_number) for m in matches} == {
        ("notes.txt", 2),
        ("workspace/report.txt", 1),
    }
    assert truncated is False


def test_glob_with_directories_at_an_ignored_name_keeps_its_contents(provider, ignored_name_tree):
    matches, truncated = provider.sandbox.glob(str(ignored_name_tree), "**/workspace", include_dirs=True)
    assert _relative_paths(matches, ignored_name_tree) == {"workspace"}
    assert truncated is False


def test_glob_with_directories_at_an_ignored_name_still_hides_ignored_descendants(provider, ignored_name_tree):
    assert provider.sandbox.glob(str(ignored_name_tree), "**/*.js", include_dirs=True) == ([], False)


def test_grep_preserves_line_numbers_and_ignores_descendants(provider, tree):
    matches, truncated = provider.sandbox.grep(str(tree), "needle", case_sensitive=True)
    assert {(Path(m.path).relative_to(tree).as_posix(), m.line_number, m.line) for m in matches} == {
        ("-résumé '中文'.txt", 2, "needle exact"),
        ("nested/result.txt", 1, "needle nested"),
    }
    assert truncated is False


def test_grep_case_insensitive_and_file_scope(provider, tree):
    file = tree / "-résumé '中文'.txt"
    matches, truncated = provider.sandbox.grep(str(file), "needle", literal=True)
    assert {(m.path, m.line_number) for m in matches} == {(str(file), 2), (str(file), 3)}
    assert truncated is False


@pytest.mark.parametrize(
    ("pattern", "line"),
    [
        ("alpha.beta", "alpha.beta"),
        ("hello world", "hello world"),
        ("x[0]", "x[0]"),
        ("path\\file", "path\\file"),
        ("a+b", "a+b"),
    ],
    ids=["dot", "space", "brackets", "backslash", "plus"],
)
def test_grep_literal_matches_regex_metacharacters(provider, tmp_path, pattern, line):
    # A literal pattern is matched verbatim: the sandbox must hand the RAW
    # pattern to ``grep -F``. Re-escaping it first (``alpha\.beta``) makes
    # fixed-string grep search for the backslash as part of the text, so an
    # exact line never matches (#5626).
    root = tmp_path / "literal"
    root.mkdir()
    (root / "sample.txt").write_text(f"header\n{line}\ntrailer\n", encoding="utf-8")

    matches, truncated = provider.sandbox.grep(str(root), pattern, literal=True)

    assert [(m.line_number, m.line) for m in matches] == [(2, line)]
    assert truncated is False


@pytest.mark.parametrize("single_file", [False, True], ids=["directory", "file"])
@pytest.mark.parametrize("case_sensitive", [False, True], ids=["ignore-case", "match-case"])
def test_grep_literal_finds_long_lines_with_bounded_prefix_summaries(provider, tmp_path, single_file, case_sensitive):
    root = tmp_path / "long-lines"
    root.mkdir()
    target = root / "data.json"
    target.write_text("header\n" + "x" * 2500 + "Needle[0].value\nNeedle0Xvalue\n", encoding="utf-8")
    search_root = target if single_file else root
    pattern = "Needle[0].value" if case_sensitive else "needle[0].VALUE"

    matches, truncated = provider.sandbox.grep(str(search_root), pattern, literal=True, case_sensitive=case_sensitive)

    # Search the full eligible line even when the fixed-length preview ends
    # before the needle. `truncated` describes result limits, not preview text.
    assert [(match.path, match.line_number, match.line) for match in matches] == [(str(target), 2, "x" * 197 + "...")]
    assert truncated is False


def test_grep_glob_filter_is_root_relative(provider, tree):
    matches, truncated = provider.sandbox.grep(str(tree), "needle", glob="nested/*.txt")
    assert [(m.path, m.line_number) for m in matches] == [(str(tree / "nested" / "result.txt"), 1)]
    assert truncated is False


@pytest.mark.parametrize(
    ("filename", "glob"),
    [
        ("release notes.txt", "release *.txt"),
        ("author's-notes.txt", "author's-*.txt"),
        ('release"notes.txt', 'release"*.txt'),
        ("price$USD.txt", "price$USD.txt"),
        ("report1.txt", "report[0-9].txt"),
        ("plain.txt", "*.txt"),
    ],
    ids=["space", "single-quote", "double-quote", "dollar", "character-range", "wildcard"],
)
def test_grep_glob_preserves_filename_characters(provider, tmp_path, filename, glob):
    root = tmp_path / "workspace"
    for directory in (root / "docs", root / "other", root / "docs" / "nested"):
        directory.mkdir(parents=True)
        (directory / filename).write_text("header\nneedle\n", encoding="utf-8")
    (root / "docs" / "excluded.md").write_text("needle\n", encoding="utf-8")
    provider.transport.env["USD"] = "expanded"

    matches, truncated = provider.sandbox.grep(str(root), "needle", glob=f"docs/{glob}")

    assert [(match.path, match.line_number, match.line) for match in matches] == [(str(root / "docs" / filename), 2, "needle")]
    assert truncated is False


def test_no_match_is_empty_and_complete(provider, tree):
    assert provider.sandbox.glob(str(tree), "**/*.missing") == ([], False)
    assert provider.sandbox.grep(str(tree), "absentneedle") == ([], False)


def test_existing_empty_directory_is_not_an_error(provider, tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    assert _relative_paths(provider.sandbox.list_dir(str(root)), root) == set()
    assert provider.sandbox.glob(str(root), "**/*.txt") == ([], False)
    assert provider.sandbox.grep(str(root), "needle") == ([], False)


@pytest.mark.parametrize("operation", ["ls", "glob", "grep"])
def test_missing_root_is_not_an_empty_result(provider, tmp_path, operation):
    with pytest.raises(FileNotFoundError):
        _call(provider.sandbox, operation, tmp_path / "missing")


def test_invalid_regex_is_rejected(provider, tree):
    with pytest.raises(re.error):
        provider.sandbox.grep(str(tree), "[invalid")


@pytest.mark.parametrize("operation", ["glob", "grep"])
def test_a_dropped_eligible_match_reports_truncation(provider, tmp_path, operation):
    root = tmp_path / "results"
    root.mkdir()
    for number in range(3):
        (root / f"result{number}.txt").write_text("needle\n", encoding="utf-8")
    if operation == "glob":
        matches, truncated = provider.sandbox.glob(str(root), "**/*.txt", max_results=2)
    else:
        matches, truncated = provider.sandbox.grep(str(root), "needle", max_results=2)
    assert len(matches) == 2
    assert truncated is True


@pytest.fixture
def user_data_tree(provider, tmp_path, monkeypatch):
    """Uploads and a checkout with the same data-looking names, mapped per provider.

    Every provider's real path mapping runs: local labels from its mount table,
    e2b/Tenki rewrite the virtual prefix under a configured home directory, and
    the others keep container-absolute paths that the transport maps onto the
    fixture tree. The checkout stays outside user data under every mapping.
    """

    def build_uploads(base: Path) -> Path:
        uploads = base / "uploads"
        (uploads / "logs").mkdir(parents=True, exist_ok=True)
        (uploads / "app.log").write_text("FATAL app\n", encoding="utf-8")
        (uploads / "logs" / "worker.log").write_text("FATAL worker\n", encoding="utf-8")
        (uploads / "notes.txt").write_text("FATAL notes\n", encoding="utf-8")
        (uploads / ".upload-active.part").write_text("FATAL partial\n", encoding="utf-8")
        (uploads / "node_modules").mkdir(exist_ok=True)
        (uploads / "node_modules" / "dep.log").write_text("FATAL dependency\n", encoding="utf-8")
        return uploads

    def build_checkout(base: Path) -> Path:
        checkout = base / "checkout"
        (checkout / "logs").mkdir(parents=True, exist_ok=True)
        (checkout / "app.log").write_text("FATAL repo app\n", encoding="utf-8")
        (checkout / "logs" / "run.txt").write_text("FATAL repo run\n", encoding="utf-8")
        (checkout / "notes.txt").write_text("FATAL repo notes\n", encoding="utf-8")
        return checkout

    name = provider.name
    virtual_uploads = f"{VIRTUAL_PATH_PREFIX}/uploads"
    if name in ("aio", "boxlite", "opensandbox", "boxd"):
        uploads = build_uploads(tmp_path / "user-data")
        checkout = build_checkout(tmp_path)
        provider.transport.path_map[virtual_uploads] = str(uploads)
        provider.transport.path_map["/workspace/checkout"] = str(checkout)
        return SimpleNamespace(uploads=virtual_uploads, checkout="/workspace/checkout", host_uploads=uploads)

    if name == "local":
        # local resolves host paths itself; it always uses the real tmp_path.
        build_uploads(tmp_path / "user-data")
        build_checkout(tmp_path)
        provider.sandbox = LocalSandbox("search-contract", [PathMapping(virtual_uploads, str(tmp_path / "user-data" / "uploads"))])
        return SimpleNamespace(uploads=virtual_uploads, checkout=str(tmp_path / "checkout"), host_uploads=tmp_path / "user-data" / "uploads")
    # e2b/Tenki back the virtual prefix with a configurable home directory and
    # report the paths they return under that prefix again.
    host_uploads = build_uploads(tmp_path / "user-data")
    build_checkout(tmp_path)
    home_str = str(tmp_path / "user-data")
    checkout_arg = str(tmp_path / "checkout")
    if name == "e2b":
        from deerflow.community.e2b_sandbox.e2b_sandbox import E2BSandbox

        provider.sandbox = E2BSandbox("search-contract", SimpleNamespace(commands=SimpleNamespace(run=provider.transport.shell)), home_dir=home_str)
    elif name == "tenki":
        from deerflow.community.tenki.sandbox import TenkiSandbox

        sandbox = TenkiSandbox("search-contract", SimpleNamespace(), home_dir=home_str)
        monkeypatch.setattr(sandbox, "_sh", provider.transport.shell)
        provider.sandbox = sandbox
    else:
        raise AssertionError(f"Unregistered user-data provider: {name}")
    return SimpleNamespace(uploads=virtual_uploads, checkout=checkout_arg, host_uploads=host_uploads)


def _user_data_relative(paths, root):
    # Providers legitimately present either the container path they were given
    # or its backing host path. Names below the root must agree either way.
    suffix = "/uploads/"
    relatives = set()
    for path in paths:
        normalized = path.rstrip("/").replace("\\", "/")
        if normalized.endswith("/uploads"):
            continue
        assert suffix in normalized, normalized
        relatives.add(normalized.split(suffix, 1)[1])
    return relatives


def test_user_data_uploads_list_data_looking_names(provider, user_data_tree):
    listed = provider.sandbox.list_dir(user_data_tree.uploads)
    assert _user_data_relative(listed, user_data_tree.uploads) == {"app.log", "logs", "logs/worker.log", "notes.txt"}


def test_user_data_uploads_glob_and_grep_reach_logs(provider, user_data_tree):
    matches, truncated = provider.sandbox.glob(user_data_tree.uploads, "**/*.log")
    assert _user_data_relative(matches, user_data_tree.uploads) == {"app.log", "logs/worker.log"}
    assert truncated is False
    matches, truncated = provider.sandbox.grep(user_data_tree.uploads, "FATAL")
    assert _user_data_relative([m.path for m in matches], user_data_tree.uploads) == {"app.log", "logs/worker.log", "notes.txt"}
    assert truncated is False


def test_user_data_uploads_still_hide_machinery_and_staging(provider, user_data_tree):
    matches, _ = provider.sandbox.glob(user_data_tree.uploads, "**/*")
    assert _user_data_relative(matches, user_data_tree.uploads) == {"app.log", "logs/worker.log", "notes.txt"}
    matches, _ = provider.sandbox.glob(user_data_tree.uploads, "**/*", include_dirs=True)
    relatives = _user_data_relative(matches, user_data_tree.uploads)
    assert "logs" in relatives
    assert not any(part in relatives for part in ("node_modules", ".upload-active.part"))
    matches, _ = provider.sandbox.grep(user_data_tree.uploads, "FATAL", glob="**/*.part")
    assert matches == []


def test_checkout_keeps_hiding_data_looking_names(provider, user_data_tree):
    listed = provider.sandbox.list_dir(user_data_tree.checkout)
    assert all("app.log" not in path and "/logs/" not in path.replace("\\", "/") for path in listed)
    # Existence anchors: an over-hiding regression must not pass on empty results.
    assert any(path.replace("\\", "/").endswith("notes.txt") for path in listed)
    matches, _ = provider.sandbox.glob(user_data_tree.checkout, "**/*")
    assert matches and all(path.replace("\\", "/").endswith("notes.txt") for path in matches)
    matches, _ = provider.sandbox.grep(user_data_tree.checkout, "FATAL")
    assert matches and all(m.path.replace("\\", "/").endswith("notes.txt") for m in matches)


def test_explicit_glob_wins_inside_a_checkout(provider, user_data_tree):
    matches, truncated = provider.sandbox.glob(user_data_tree.checkout, "*.log")
    assert [Path(path).name for path in matches] == ["app.log"]
    assert truncated is False
    matches, truncated = provider.sandbox.grep(user_data_tree.checkout, "FATAL", glob="*.log")
    assert [(Path(m.path).name, m.line_number) for m in matches] == [("app.log", 1)]
    assert truncated is False


def test_explicit_data_directory_glob_wins_inside_a_checkout(provider, user_data_tree):
    matches, truncated = provider.sandbox.glob(user_data_tree.checkout, "logs/*.txt")
    assert [Path(path).name for path in matches] == ["run.txt"]
    assert truncated is False
    matches, truncated = provider.sandbox.grep(user_data_tree.checkout, "FATAL", glob="logs/*.txt")
    assert [(Path(m.path).name, m.line_number) for m in matches] == [("run.txt", 1)]
    assert truncated is False


def test_files_only_glob_drops_directories(provider, user_data_tree):
    """The file API reports directories among the matches; a files-only
    search must filter them out before returning results, and must still
    return every data file the search asked for."""
    matches, truncated = provider.sandbox.glob(user_data_tree.uploads, "**/*")
    assert _user_data_relative(matches, user_data_tree.uploads) == {"app.log", "logs/worker.log", "notes.txt"}
    assert truncated is False


def test_glob_keeps_a_dotfile_that_matches_the_extension_pattern(provider, user_data_tree):
    """A pattern such as ``*.csv`` also matches a file named exactly ``.csv``.

    The listing endpoint reports a dot-only name with no extension, so a
    server-side extension filter would drop it even though the client matcher
    accepts it; the search must still return it with directories included.
    A wildcard stem has the same problem for a longer dot run (``?*.csv``
    matches ``..csv``), so both shapes are checked."""
    (user_data_tree.host_uploads / ".csv").write_text("FATAL bare\n", encoding="utf-8")
    (user_data_tree.host_uploads / "..csv").write_text("FATAL dots\n", encoding="utf-8")
    (user_data_tree.host_uploads / "report.csv").write_text("FATAL report\n", encoding="utf-8")

    matches, truncated = provider.sandbox.glob(user_data_tree.uploads, "*.csv", include_dirs=True)
    assert _user_data_relative(matches, user_data_tree.uploads) == {".csv", "..csv", "report.csv"}
    assert truncated is False

    matches, truncated = provider.sandbox.glob(user_data_tree.uploads, "?*.csv", include_dirs=True)
    assert _user_data_relative(matches, user_data_tree.uploads) == {"..csv", "report.csv"}
    assert truncated is False


def test_hidden_data_directory_is_searchable_with_directories_included(provider, user_data_tree):
    """An explicit hidden-name glob must see through the directory: turning
    include_dirs on must not hide ``.cache`` and its contents."""
    cache = user_data_tree.host_uploads / ".cache"
    cache.mkdir(exist_ok=True)
    (cache / "trace.txt").write_text("FATAL cache\n", encoding="utf-8")

    matches, truncated = provider.sandbox.glob(user_data_tree.uploads, ".cache/*.txt", include_dirs=True)
    assert [Path(path).name for path in matches] == ["trace.txt"]
    assert truncated is False
    matches, truncated = provider.sandbox.glob(user_data_tree.uploads, ".cache/*.txt")
    assert [Path(path).name for path in matches] == ["trace.txt"]
    assert truncated is False


@pytest.mark.parametrize("provider", HOME_REWRITE_PROVIDERS, indirect=True)
def test_ls_paths_from_a_user_data_root_can_be_searched_back(provider, user_data_tree):
    """A path from ``ls`` must be usable as a search root again: both
    home-backed providers report virtual paths, so the user-data label
    survives the round trip."""
    listed = provider.sandbox.list_dir(user_data_tree.uploads)
    logs_dir = next(path for path in listed if path.rstrip("/").endswith("/logs"))
    assert logs_dir.startswith(VIRTUAL_PATH_PREFIX)

    matches, truncated = provider.sandbox.grep(logs_dir, "FATAL")
    assert [(Path(match.path).name, match.line_number) for match in matches] == [("worker.log", 1)]
    assert truncated is False


@pytest.mark.parametrize("provider", HOME_REWRITE_PROVIDERS, indirect=True)
def test_a_user_data_ls_prunes_only_machinery(provider, user_data_tree):
    provider.sandbox.list_dir(user_data_tree.uploads)
    command = provider.transport.commands[-1]
    # -name on POSIX, -iname where the host folds case (same policy as the parser).
    assert "node_modules" in command
    assert ".upload-*.part" in command
    assert "*.log" not in command
    # shlex.quote leaves bare words unquoted, so check the prune term itself.
    assert "-name logs" not in command and "-iname logs" not in command


@pytest.mark.parametrize("provider", HOME_REWRITE_PROVIDERS, indirect=True)
def test_home_root_label_follows_the_addressed_path(provider, user_data_tree):
    """The documented trade-off when a skills root lives inside the backing home.

    A search rooted at the virtual prefix labels the whole home as user data,
    so a skills tree configured inside it is searched as content; addressing
    the home path directly keeps the repository filter. Both directions are
    pinned so neither can drift silently.
    """
    # The fixture's home is wherever the provider's home_dir points; derive the
    # host location from it so the skills tree lands in the same backing store.
    home_arg = provider.sandbox.home_dir if hasattr(provider.sandbox, "home_dir") else provider.sandbox._home_dir
    home = Path(provider.transport._to_host(home_arg))
    skills = home / "skills" / "public" / "demo"
    skills.mkdir(parents=True, exist_ok=True)
    (skills / "trace.log").write_text("FATAL skill trace\n", encoding="utf-8")
    virtual_root = VIRTUAL_PATH_PREFIX

    matches, _ = provider.sandbox.glob(virtual_root, "**/*.log")
    assert any(path.replace("\\", "/").endswith("skills/public/demo/trace.log") for path in matches)
    matches, _ = provider.sandbox.grep(virtual_root, "FATAL", glob="**/trace.log")
    assert any(m.path.replace("\\", "/").endswith("skills/public/demo/trace.log") for m in matches)

    # The same skills tree addressed through the home path keeps the repository
    # filter. The pattern must not name a data-looking file: an explicit
    # ``*.log`` wins in either root type (pinned by the checkout case), which
    # is also why a generic home-root search would show the uploads logs.
    assert provider.sandbox.glob(str(home / "skills"), "**/trace.*")[0] == []
    assert provider.sandbox.grep(str(home / "skills"), "FATAL")[0] == []


@pytest.mark.parametrize("provider", REMOTE_PROVIDERS, indirect=True)
@pytest.mark.parametrize("operation", ["ls", "glob", "grep"])
def test_transport_failure_does_not_become_no_matches(provider, tree, operation):
    provider.transport.error = OSError("synthetic transport failure")
    with pytest.raises(OSError):
        _call(provider.sandbox, operation, tree)


@pytest.mark.parametrize(
    ("provider", "operation", "program"),
    [(name, "ls", "find") for name in REMOTE_PROVIDERS] + [(name, operation, program) for name in SHELL_SEARCH_PROVIDERS for operation, program in (("glob", "find"), ("grep", "grep"))],
    indirect=["provider"],
)
def test_missing_search_program_does_not_become_no_matches(provider, tree, operation, program):
    provider.transport.missing_program(program)
    with pytest.raises(OSError):
        _call(provider.sandbox, operation, tree)

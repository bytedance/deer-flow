"""Shared search semantics through real providers and offline execution seams.

Shell-backed providers run their production command strings with local sh/find/
grep. AIO's file RPC seam reads the same fixture tree independently. This does
not test a live SDK/server, shell-session lifecycle, or provider provisioning.
"""

from __future__ import annotations

import glob as filesystem_glob
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox

PROVIDERS = ("local", "aio", "e2b", "boxlite", "tenki", "opensandbox")
REMOTE_PROVIDERS = tuple(name for name in PROVIDERS if name != "local")
SHELL_SEARCH_PROVIDERS = ("e2b", "boxlite", "tenki", "opensandbox")
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

    def check(self, path: str | None = None):
        if self.error is not None:
            raise self.error
        if path is not None and not Path(path).exists():
            raise FileNotFoundError(path)

    def shell(self, command: str, **_kwargs):
        self.check()
        result = subprocess.run(["sh", "-c", command], capture_output=True, text=True, env=self.env, timeout=10, check=False)
        return SimpleNamespace(stdout=result.stdout, stderr=result.stderr, stdout_text=result.stdout, stderr_text=result.stderr, exit_code=result.returncode)

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

    def find_files(self, *, path: str, glob: str):
        self.check(path)
        # Python's filesystem glob is independent of DeerFlow's path_matches.
        matches = sorted(p for p in filesystem_glob.glob(filesystem_glob.escape(str(Path(path))) + "/" + glob, recursive=True) if Path(p).is_file())
        return SimpleNamespace(data=SimpleNamespace(files=matches))

    def list_path(self, *, path: str, recursive: bool, show_hidden: bool):
        self.check(path)
        assert recursive and not show_hidden
        return SimpleNamespace(data=SimpleNamespace(files=[SimpleNamespace(path=str(p)) for p in sorted(Path(path).rglob("*")) if not p.name.startswith(".")]))

    def grep_files(self, *, path: str, pattern: str, case_insensitive: bool, fixed_strings: bool, max_results: int, max_file_size: str, recursive: bool):
        self.check(path)
        assert recursive and max_file_size == "1M"
        matcher = re.compile(re.escape(pattern) if fixed_strings else pattern, re.IGNORECASE if case_insensitive else 0)
        root = Path(path)
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        matches = []
        for file in files:
            for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                if matcher.search(line):
                    matches.append(SimpleNamespace(file=str(file), line_number=number, line_content=line))
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


def test_grep_glob_filter_is_root_relative(provider, tree):
    matches, truncated = provider.sandbox.grep(str(tree), "needle", glob="nested/*.txt")
    assert [(m.path, m.line_number) for m in matches] == [(str(tree / "nested" / "result.txt"), 1)]
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

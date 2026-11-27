import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from support.symlinks import symlink_or_skip

from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox
from deerflow.config.paths import Paths
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.search import GrepMatch, find_glob_matches, find_grep_matches
from deerflow.sandbox.tools import glob_tool, grep_tool, ls_tool


def _make_runtime(tmp_path):
    workspace = tmp_path / "workspace"
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    workspace.mkdir()
    uploads.mkdir()
    outputs.mkdir()
    return SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": str(workspace),
                "uploads_path": str(uploads),
                "outputs_path": str(outputs),
            },
        },
        context={"thread_id": "thread-1"},
    )


def test_glob_tool_returns_virtual_paths_and_ignores_common_dirs(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (workspace / "pkg").mkdir()
    (workspace / "pkg" / "util.py").write_text("print('util')\n", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "skip.py").write_text("ignored\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = glob_tool.func(
        runtime=runtime,
        description="find python files",
        pattern="**/*.py",
        path="/mnt/user-data/workspace",
    )

    assert "/mnt/user-data/workspace/app.py" in result
    assert "/mnt/user-data/workspace/pkg/util.py" in result
    assert "node_modules" not in result
    assert str(workspace) not in result


def test_glob_tool_supports_skills_virtual_paths(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    skills_dir = tmp_path / "skills"
    (skills_dir / "public" / "demo").mkdir(parents=True)
    (skills_dir / "public" / "demo" / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

    sandbox = LocalSandbox(
        id="local",
        path_mappings=[
            PathMapping(container_path="/mnt/skills", local_path=str(skills_dir), read_only=True),
        ],
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)

    result = glob_tool.func(
        runtime=runtime,
        description="find skills",
        pattern="**/SKILL.md",
        path="/mnt/skills",
    )

    assert "/mnt/skills/public/demo/SKILL.md" in result
    assert str(skills_dir) not in result


def test_grep_tool_filters_by_glob_and_skips_binary_files(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "main.py").write_text("TODO = 'ship it'\nprint(TODO)\n", encoding="utf-8")
    (workspace / "notes.txt").write_text("TODO in txt should be filtered\n", encoding="utf-8")
    (workspace / "image.bin").write_bytes(b"\0binary TODO")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = grep_tool.func(
        runtime=runtime,
        description="find todo references",
        pattern="TODO",
        path="/mnt/user-data/workspace",
        glob="**/*.py",
    )

    assert "/mnt/user-data/workspace/main.py:1: TODO = 'ship it'" in result
    assert "notes.txt" not in result
    assert "image.bin" not in result
    assert str(workspace) not in result


def test_grep_tool_accepts_single_file_path(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    uploads = tmp_path / "uploads"
    report = uploads / "report.md"
    report.write_text("Revenue grew 20%\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = grep_tool.func(
        runtime=runtime,
        description="find revenue in the uploaded report",
        pattern="Revenue",
        path="/mnt/user-data/uploads/report.md",
    )

    assert "/mnt/user-data/uploads/report.md:1: Revenue grew 20%" in result
    assert "Path is not a directory" not in result
    assert str(uploads) not in result


def _remote_search_runtime():
    return SimpleNamespace(state={"sandbox": {"sandbox_id": "remote-1"}}, context={"thread_id": "thread-1"})


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        (glob_tool, {"pattern": "src/*.py"}),
        (grep_tool, {"pattern": "needle", "glob": "src/*.py"}),
    ],
)
def test_search_tools_do_not_report_a_truncated_empty_result_as_no_matches(monkeypatch, tool, arguments) -> None:
    """A remote search whose output hit its cap before any line survived the glob
    filter has no results to show, but it has not proven there are none."""
    sandbox = SimpleNamespace(glob=lambda *args, **kwargs: ([], True), grep=lambda *args, **kwargs: ([], True))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)

    result = tool.func(runtime=_remote_search_runtime(), description="scoped search", path="/mnt/user-data/workspace", **arguments)

    assert not result.startswith(("No files matched", "No matches found"))
    assert "incomplete" in result
    assert "/mnt/user-data/workspace" in result


@pytest.mark.parametrize(("tool", "arguments", "expected"), [(glob_tool, {"pattern": "*.py"}, "No files matched under"), (grep_tool, {"pattern": "needle"}, "No matches found under")])
def test_search_tools_keep_the_no_match_message_for_a_complete_empty_result(monkeypatch, tool, arguments, expected) -> None:
    sandbox = SimpleNamespace(glob=lambda *args, **kwargs: ([], False), grep=lambda *args, **kwargs: ([], False))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)

    result = tool.func(runtime=_remote_search_runtime(), description="search", path="/mnt/user-data/workspace", **arguments)

    assert result == f"{expected} /mnt/user-data/workspace"


def test_grep_tool_truncates_results(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "main.py").write_text("TODO one\nTODO two\nTODO three\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))
    # Prevent config.yaml tool config from overriding the caller-supplied max_results=2.
    monkeypatch.setattr("deerflow.sandbox.tools.get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: None))

    result = grep_tool.func(
        runtime=runtime,
        description="limit matches",
        pattern="TODO",
        path="/mnt/user-data/workspace",
        max_results=2,
    )

    assert "Found 2 matches under /mnt/user-data/workspace (showing first 2)" in result
    assert "TODO one" in result
    assert "TODO two" in result
    assert "TODO three" not in result
    assert "Results truncated." in result


def test_glob_tool_include_dirs_filters_nested_ignored_paths(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir()
    (workspace / "src" / "main.py").write_text("x\n", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "lib").mkdir()

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = glob_tool.func(
        runtime=runtime,
        description="find dirs",
        pattern="**",
        path="/mnt/user-data/workspace",
        include_dirs=True,
    )

    assert "src" in result
    assert "node_modules" not in result


def test_grep_tool_literal_mode(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "file.py").write_text("price = (a+b)\nresult = a+b\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    # literal=True should treat (a+b) as a plain string, not a regex group
    result = grep_tool.func(
        runtime=runtime,
        description="literal search",
        pattern="(a+b)",
        path="/mnt/user-data/workspace",
        literal=True,
    )

    assert "price = (a+b)" in result
    assert "result = a+b" not in result


def test_grep_tool_case_sensitive(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "file.py").write_text("TODO: fix\ntodo: also fix\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = grep_tool.func(
        runtime=runtime,
        description="case sensitive search",
        pattern="TODO",
        path="/mnt/user-data/workspace",
        case_sensitive=True,
    )

    assert "TODO: fix" in result
    assert "todo: also fix" not in result


def test_grep_tool_invalid_regex_returns_error(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = grep_tool.func(
        runtime=runtime,
        description="bad pattern",
        pattern="[invalid",
        path="/mnt/user-data/workspace",
    )

    assert "Invalid regex pattern" in result


def test_aio_sandbox_glob_include_dirs_filters_nested_ignored(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "list_path",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(name="src", path="/mnt/workspace/src"),
                    SimpleNamespace(name="node_modules", path="/mnt/workspace/node_modules"),
                    # child of node_modules — should be filtered via should_ignore_path
                    SimpleNamespace(name="lib", path="/mnt/workspace/node_modules/lib"),
                ]
            )
        ),
    )

    matches, truncated = sandbox.glob("/mnt/workspace", "**", include_dirs=True)

    assert "/mnt/workspace/src" in matches
    assert "/mnt/workspace/node_modules" not in matches
    assert "/mnt/workspace/node_modules/lib" not in matches
    assert truncated is False


def test_aio_sandbox_glob_include_dirs_exactly_full_is_not_truncated(monkeypatch) -> None:
    """A listing whose matches exactly fill max_results is complete.

    The branch used to return as soon as it had collected ``max_results``
    matches, without looking at the remaining entries, so a listing that held
    exactly that many was reported as cut off even though every entry was
    seen. It now scans one eligible match past the cap, the same rule the
    sibling ``include_dirs=False`` branch has always applied to the full list.
    """
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "list_path",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(name="a", path="/mnt/workspace/a"),
                    SimpleNamespace(name="b", path="/mnt/workspace/b"),
                ]
            )
        ),
    )

    matches, truncated = sandbox.glob("/mnt/workspace", "**", include_dirs=True, max_results=2)

    assert matches == ["/mnt/workspace/a", "/mnt/workspace/b"]
    assert truncated is False


def test_aio_sandbox_glob_include_dirs_reports_a_dropped_match_as_truncated(monkeypatch) -> None:
    """The counterpart: a match past the cap still reports truncated."""
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "list_path",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(name="a", path="/mnt/workspace/a"),
                    SimpleNamespace(name="b", path="/mnt/workspace/b"),
                    SimpleNamespace(name="c", path="/mnt/workspace/c"),
                ]
            )
        ),
    )

    matches, truncated = sandbox.glob("/mnt/workspace", "**", include_dirs=True, max_results=2)

    assert matches == ["/mnt/workspace/a", "/mnt/workspace/b"]
    assert truncated is True


def _filtered_tail_entries(*, second_eligible: bool):
    """Two eligible matches, then entries only the ignore rules, the pattern or
    the root scope reject — a tail that must not count toward the cap."""
    entries = [
        SimpleNamespace(name="a.py", path="/mnt/workspace/a.py"),
        SimpleNamespace(name="b.py", path="/mnt/workspace/b.py"),
        # ignored directory
        SimpleNamespace(name="lib.py", path="/mnt/workspace/node_modules/lib.py"),
        # outside the search root
        SimpleNamespace(name="c.py", path="/mnt/elsewhere/c.py"),
        # inside the root but not matched by the pattern
        SimpleNamespace(name="notes.txt", path="/mnt/workspace/notes.txt"),
    ]
    if second_eligible:
        entries.append(SimpleNamespace(name="c.py", path="/mnt/workspace/c.py"))
    return entries


def _patched_sandbox(monkeypatch, entries):
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "list_path",
        lambda **kwargs: SimpleNamespace(data=SimpleNamespace(files=entries)),
    )
    return sandbox


def test_aio_sandbox_glob_include_dirs_looks_past_a_filtered_tail(monkeypatch) -> None:
    """Trailing entries the filters reject do not make a full result truncated.

    The cap counts *eligible* matches, so the branch has to keep scanning
    rather than assume the max-th match was the last one: here two matches fill
    ``max_results`` and everything after them is ignored, out of root, or a
    pattern miss, which leaves the result complete.
    """
    sandbox = _patched_sandbox(monkeypatch, _filtered_tail_entries(second_eligible=False))

    matches, truncated = sandbox.glob("/mnt/workspace", "**/*.py", include_dirs=True, max_results=2)

    assert matches == ["/mnt/workspace/a.py", "/mnt/workspace/b.py"]
    assert truncated is False


def test_aio_sandbox_glob_include_dirs_reports_a_match_after_a_filtered_tail(monkeypatch) -> None:
    """An eligible match beyond that filtered tail still reports truncation."""
    sandbox = _patched_sandbox(monkeypatch, _filtered_tail_entries(second_eligible=True))

    matches, truncated = sandbox.glob("/mnt/workspace", "**/*.py", include_dirs=True, max_results=2)

    assert matches == ["/mnt/workspace/a.py", "/mnt/workspace/b.py"]
    assert truncated is True


def test_aio_sandbox_grep_invalid_regex_raises() -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")

    import re

    try:
        sandbox.grep("/mnt/workspace", "[invalid")
        assert False, "Expected re.error"
    except re.error:
        pass


def test_aio_sandbox_glob_parses_json(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "glob_files",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(path="/mnt/user-data/workspace/app.py", is_directory=False),
                    SimpleNamespace(path="/mnt/user-data/workspace/node_modules/skip.py", is_directory=False),
                ],
                truncated=False,
            )
        ),
    )

    matches, truncated = sandbox.glob("/mnt/user-data/workspace", "**/*.py")

    assert matches == ["/mnt/user-data/workspace/app.py"]
    assert truncated is False


def test_aio_sandbox_glob_drops_directories_before_the_cap(monkeypatch) -> None:
    """The file API reports directories among matches; a files-only glob drops
    them before counting toward max_results, so a directory cannot consume a
    result slot or claim truncation."""
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    seen: dict = {}

    def glob_files(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(path="/mnt/user-data/uploads/logs", is_directory=True),
                    SimpleNamespace(path="/mnt/user-data/uploads/logs/worker.log", is_directory=False),
                ],
                truncated=False,
            )
        )

    monkeypatch.setattr(sandbox._client.file, "glob_files", glob_files)

    # ``**/*`` matches the directory too, so a missing is_directory skip would
    # fill the single slot with it and report truncation.
    matches, truncated = sandbox.glob("/mnt/user-data/uploads", "**/*", max_results=1)

    assert seen["files_only"] is True
    assert seen["include_hidden"] is True
    assert seen["include_metadata"] is False
    assert matches == ["/mnt/user-data/uploads/logs/worker.log"]
    assert truncated is False


def test_aio_sandbox_glob_matches_a_non_canonical_root(monkeypatch) -> None:
    """The caller may spell the root with ``//``; the server returns canonical
    entry paths, so the scope check must normalize the root instead of
    dropping every entry."""
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "glob_files",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[SimpleNamespace(path="/mnt/user-data/uploads/app.log", is_directory=False)],
                truncated=False,
            )
        ),
    )

    matches, truncated = sandbox.glob("/mnt//user-data/uploads", "*.log")

    assert matches == ["/mnt/user-data/uploads/app.log"]
    assert truncated is False


def test_aio_sandbox_grep_matches_a_non_canonical_root(monkeypatch) -> None:
    """grep scopes returned files the same way, so ``/.`` in the root must not
    turn every match into an out-of-scope result."""
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "grep_files",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                matches=[SimpleNamespace(file="/mnt/user-data/uploads/app.log", line_number=1, line_content="FATAL app")],
                truncated=False,
            )
        ),
    )

    matches, truncated = sandbox.grep("/mnt/./user-data/uploads", "FATAL")

    assert matches == [GrepMatch(path="/mnt/user-data/uploads/app.log", line_number=1, line="FATAL app")]
    assert truncated is False


def test_aio_sandbox_glob_reports_server_truncation(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "glob_files",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[SimpleNamespace(path="/mnt/user-data/uploads/app.log", is_directory=False)],
                truncated=True,
            )
        ),
    )

    matches, truncated = sandbox.glob("/mnt/user-data/uploads", "**/*.log")

    assert matches == ["/mnt/user-data/uploads/app.log"]
    assert truncated is True


def test_aio_sandbox_glob_falls_back_to_list_path_when_glob_files_is_missing(monkeypatch) -> None:
    """Images that predate /v1/file/glob answer 404; the typed listing is the
    fallback and must apply the same files-only rule."""
    from agent_sandbox.core.api_error import ApiError

    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")

    def missing_glob_files(**kwargs):
        raise ApiError(status_code=404, headers={}, body={"detail": "Not Found"})

    monkeypatch.setattr(sandbox._client.file, "glob_files", missing_glob_files)
    monkeypatch.setattr(
        sandbox._client.file,
        "list_path",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(path="/mnt/user-data/uploads/logs", is_directory=True),
                    SimpleNamespace(path="/mnt/user-data/uploads/logs/worker.log", is_directory=False),
                ]
            )
        ),
    )

    matches, truncated = sandbox.glob("/mnt/user-data/uploads", "**/*.log")

    assert matches == ["/mnt/user-data/uploads/logs/worker.log"]
    assert truncated is False


def test_aio_sandbox_glob_fallback_pushes_a_literal_extension_to_the_server(monkeypatch) -> None:
    """A pattern that names an extension narrows the listing server-side, so a
    search for one file does not transfer the whole tree from an image without
    /v1/file/glob."""
    from agent_sandbox.core.api_error import ApiError

    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")

    def missing_glob_files(**kwargs):
        raise ApiError(status_code=404, headers={}, body={"detail": "Not Found"})

    seen: dict = {}

    def list_path(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(path="/mnt/user-data/uploads/logs", is_directory=True),
                    SimpleNamespace(path="/mnt/user-data/uploads/logs/worker.log", is_directory=False),
                ]
            )
        )

    monkeypatch.setattr(sandbox._client.file, "glob_files", missing_glob_files)
    monkeypatch.setattr(sandbox._client.file, "list_path", list_path)

    matches, truncated = sandbox.glob("/mnt/user-data/uploads", "**/*.log")

    assert seen["file_types"] == [".log"]
    assert matches == ["/mnt/user-data/uploads/logs/worker.log"]
    assert truncated is False


def test_aio_sandbox_glob_fallback_omits_file_types_without_a_literal_extension(monkeypatch) -> None:
    """A wildcard extension cannot be expressed as ``file_types``; the full
    listing stays correct and the client keeps filtering."""
    from agent_sandbox.core.api_error import ApiError

    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")

    def missing_glob_files(**kwargs):
        raise ApiError(status_code=404, headers={}, body={"detail": "Not Found"})

    seen: dict = {}

    def list_path(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(path="/mnt/user-data/uploads/logs", is_directory=True),
                    SimpleNamespace(path="/mnt/user-data/uploads/logs/worker.log", is_directory=False),
                ]
            )
        )

    monkeypatch.setattr(sandbox._client.file, "glob_files", missing_glob_files)
    monkeypatch.setattr(sandbox._client.file, "list_path", list_path)

    matches, truncated = sandbox.glob("/mnt/user-data/uploads", "**/*")

    assert "file_types" not in seen
    assert matches == ["/mnt/user-data/uploads/logs/worker.log"]
    assert truncated is False


def test_aio_sandbox_glob_include_dirs_pushes_a_literal_extension_to_the_server(monkeypatch) -> None:
    """The include-dirs listing benefits from the same extension filter; the
    server still returns directories, so they remain matchable."""
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    seen: dict = {}

    def list_path(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(path="/mnt/user-data/uploads/.cache", is_directory=True),
                    SimpleNamespace(path="/mnt/user-data/uploads/.cache/trace.txt", is_directory=False),
                ]
            )
        )

    monkeypatch.setattr(sandbox._client.file, "list_path", list_path)

    matches, truncated = sandbox.glob("/mnt/user-data/uploads", ".cache/*.txt", include_dirs=True)

    assert seen["file_types"] == [".txt"]
    assert matches == ["/mnt/user-data/uploads/.cache/trace.txt"]
    assert truncated is False


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("**/*.log", [".log"]),
        ("*.txt", [".txt"]),
        ("notes.txt", [".txt"]),
        ("logs/app.log", [".log"]),
        ("*.tar.gz", [".gz"]),
        ("*", None),
        ("**/*", None),
        ("*.*", None),
        ("*.[jt]s", None),
        ("*.{log,txt}", None),
        (".log", None),
        ("notes.", None),
        ("notes", None),
    ],
)
def test_aio_pattern_file_types(pattern, expected) -> None:
    from deerflow.community.aio_sandbox.aio_sandbox import _pattern_file_types

    assert _pattern_file_types(pattern) == expected


def test_aio_sandbox_glob_include_dirs_keeps_hidden_directory_contents(monkeypatch) -> None:
    """A hidden directory named by the pattern must not hide its children:
    the listing endpoint has to include hidden entries so the pattern can
    match inside it."""
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    seen: dict = {}

    def list_path(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(path="/mnt/user-data/uploads/.cache", is_directory=True),
                    SimpleNamespace(path="/mnt/user-data/uploads/.cache/trace.txt", is_directory=False),
                ]
            )
        )

    monkeypatch.setattr(sandbox._client.file, "list_path", list_path)

    matches, truncated = sandbox.glob("/mnt/user-data/uploads", ".cache/*.txt", include_dirs=True)

    assert seen["show_hidden"] is True
    assert matches == ["/mnt/user-data/uploads/.cache/trace.txt"]
    assert truncated is False


def test_aio_sandbox_grep_parses_json(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "grep_files",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                matches=[
                    SimpleNamespace(
                        file="/mnt/user-data/workspace/app.py",
                        line_number=7,
                        line_content="TODO = True",
                    )
                ],
                truncated=False,
            )
        ),
    )

    matches, truncated = sandbox.grep("/mnt/user-data/workspace", "TODO")

    assert matches == [GrepMatch(path="/mnt/user-data/workspace/app.py", line_number=7, line="TODO = True")]
    assert truncated is False


def test_aio_sandbox_grep_forwards_an_explicit_glob_to_the_server(monkeypatch) -> None:
    """The file API applies its own filter before returning matches, so an
    explicit glob must reach the server; the basename is the coarse filter and
    the client still enforces the directory scope."""
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    seen: dict = {}

    def grep_files(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            data=SimpleNamespace(
                matches=[
                    SimpleNamespace(file="/mnt/user-data/workspace/logs/app.log", line_number=3, line_content="FATAL app"),
                    SimpleNamespace(file="/mnt/user-data/workspace/app.log", line_number=4, line_content="FATAL root"),
                ],
                truncated=False,
            )
        )

    monkeypatch.setattr(sandbox._client.file, "grep_files", grep_files)

    matches, _ = sandbox.grep("/mnt/user-data/workspace", "FATAL", glob="logs/*.log")

    assert seen["include"] == ["*.log"]
    assert matches == [GrepMatch(path="/mnt/user-data/workspace/logs/app.log", line_number=3, line="FATAL app")]


def test_aio_sandbox_grep_does_not_send_include_without_a_glob(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    seen: dict = {}

    def grep_files(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(data=SimpleNamespace(matches=[], truncated=False))

    monkeypatch.setattr(sandbox._client.file, "grep_files", grep_files)

    sandbox.grep("/mnt/user-data/workspace", "FATAL")

    assert "include" not in seen


def test_aio_sandbox_grep_accepts_single_file_path(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "grep_files",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                matches=[
                    SimpleNamespace(
                        file="/mnt/user-data/uploads/report.md",
                        line_number=3,
                        line_content="Revenue grew 20%",
                    )
                ],
                truncated=False,
            )
        ),
    )
    monkeypatch.setattr(
        sandbox._client.file,
        "list_path",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("single-file grep must not list the path as a directory")),
    )

    matches, truncated = sandbox.grep("/mnt/user-data/uploads/report.md", "Revenue")

    assert matches == [GrepMatch(path="/mnt/user-data/uploads/report.md", line_number=3, line="Revenue grew 20%")]
    assert truncated is False


def test_find_glob_matches_raises_not_a_directory(tmp_path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("x\n", encoding="utf-8")

    try:
        find_glob_matches(file_path, "**/*.py")
        assert False, "Expected NotADirectoryError"
    except NotADirectoryError:
        pass


_NON_ROOT_POSIX = pytest.mark.skipif(
    os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="requires non-root POSIX directory permissions",
)


@_NON_ROOT_POSIX
def test_local_list_dir_propagates_permission_error(tmp_path) -> None:
    """Permission-denied roots must not look like an empty successful listing."""
    from deerflow.sandbox.local.list_dir import list_dir

    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "secret.txt").write_text("hidden\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        with pytest.raises(PermissionError) as caught:
            list_dir(str(locked))
        assert caught.value.filename is not None
        assert Path(os.fsdecode(caught.value.filename)).resolve() == locked.resolve()
    finally:
        locked.chmod(0o700)


@_NON_ROOT_POSIX
def test_find_glob_matches_propagates_permission_error(tmp_path) -> None:
    """Inaccessible subtrees must surface instead of being skipped as no matches."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    locked = workspace / "locked"
    locked.mkdir()
    (locked / "secret.py").write_text("x = 1\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        with pytest.raises(PermissionError) as caught:
            find_glob_matches(workspace, "**/*.py")
        assert caught.value.filename is not None
        assert Path(os.fsdecode(caught.value.filename)).resolve() == locked.resolve()
    finally:
        locked.chmod(0o700)


@_NON_ROOT_POSIX
def test_ls_tool_permission_error_names_denied_entry(tmp_path, monkeypatch) -> None:
    """ls must name the denied entry, not only the requested root."""
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    locked = workspace / "locked"
    locked.mkdir()
    (locked / "secret.txt").write_text("hidden\n", encoding="utf-8")
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda _: LocalSandbox(id="local"))
    locked.chmod(0o000)
    try:
        result = ls_tool.func(runtime=runtime, description="list locked", path="/mnt/user-data/workspace/locked")
    finally:
        locked.chmod(0o700)
    assert result.startswith("Error: Permission denied:"), result
    assert "/mnt/user-data/workspace/locked" in result
    assert str(workspace) not in result
    assert str(tmp_path) not in result


@_NON_ROOT_POSIX
def test_glob_tool_permission_error_names_denied_subdirectory(tmp_path, monkeypatch) -> None:
    """glob must name the denied subdirectory, not only the search root."""
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    locked = workspace / "locked"
    locked.mkdir()
    (locked / "secret.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda _: LocalSandbox(id="local"))
    locked.chmod(0o000)
    try:
        result = glob_tool.func(
            runtime=runtime,
            description="search locked",
            path="/mnt/user-data/workspace",
            pattern="**/*.py",
        )
    finally:
        locked.chmod(0o700)
    assert result.startswith("Error: Permission denied:"), result
    assert "/mnt/user-data/workspace/locked" in result
    assert str(workspace) not in result
    assert str(tmp_path) not in result


def test_find_grep_matches_accepts_single_file(tmp_path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("TODO\n", encoding="utf-8")

    matches, truncated = find_grep_matches(file_path, "TODO")

    assert matches == [GrepMatch(path=str(file_path), line_number=1, line="TODO")]
    assert truncated is False


def test_find_grep_matches_skips_symlink_outside_root(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("TODO outside\n", encoding="utf-8")
    symlink_or_skip(workspace / "outside-link.txt", outside)

    matches, truncated = find_grep_matches(workspace, "TODO")

    assert matches == []
    assert truncated is False


def test_glob_tool_honors_smaller_requested_max_results(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "a.py").write_text("print('a')\n", encoding="utf-8")
    (workspace / "b.py").write_text("print('b')\n", encoding="utf-8")
    (workspace / "c.py").write_text("print('c')\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))
    monkeypatch.setattr(
        "deerflow.sandbox.tools.get_app_config",
        lambda: SimpleNamespace(get_tool_config=lambda name: SimpleNamespace(model_extra={"max_results": 50})),
    )

    result = glob_tool.func(
        runtime=runtime,
        description="limit glob matches",
        pattern="**/*.py",
        path="/mnt/user-data/workspace",
        max_results=2,
    )

    assert "Found 2 paths under /mnt/user-data/workspace (showing first 2)" in result
    assert "Results truncated." in result


def test_aio_sandbox_glob_include_dirs_enforces_root_boundary(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "list_path",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(name="src", path="/mnt/workspace/src"),
                    SimpleNamespace(name="src2", path="/mnt/workspace2/src2"),
                ]
            )
        ),
    )

    matches, truncated = sandbox.glob("/mnt/workspace", "**", include_dirs=True)

    assert matches == ["/mnt/workspace/src"]
    assert truncated is False


def test_aio_sandbox_grep_drops_matches_outside_requested_root(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "grep_files",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                matches=[
                    SimpleNamespace(
                        file="/mnt/user-data/workspace/app.py",
                        line_number=7,
                        line_content="TODO = True",
                    ),
                    SimpleNamespace(
                        file="/mnt/user-data/workspace-sibling/leak.py",
                        line_number=9,
                        line_content="TODO = False",
                    ),
                ],
                truncated=False,
            )
        ),
    )

    matches, truncated = sandbox.grep("/mnt/user-data/workspace", "TODO")

    assert matches == [GrepMatch(path="/mnt/user-data/workspace/app.py", line_number=7, line="TODO = True")]
    assert truncated is False


def _grep_files_returning(count: int):
    """Provider reply holding ``count`` matching lines, none of them cut off."""
    return lambda **kwargs: SimpleNamespace(
        data=SimpleNamespace(
            matches=[SimpleNamespace(file=f"/mnt/user-data/workspace/f{index}.py", line_number=index + 1, line_content="TODO = True") for index in range(count)],
            truncated=False,
        )
    )


def test_aio_sandbox_grep_exactly_full_is_not_truncated(monkeypatch) -> None:
    """A grep whose matches exactly fill max_results is complete.

    The loop used to return as soon as it had collected ``max_results``
    matches, without looking at the remaining lines, so a search that found
    exactly that many was reported as cut off even though every line was seen.
    It now scans one eligible match past the cap, as the ``glob`` branches do.
    """
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(sandbox._client.file, "grep_files", _grep_files_returning(2))

    matches, truncated = sandbox.grep("/mnt/user-data/workspace", "TODO", max_results=2)

    assert [match.path for match in matches] == ["/mnt/user-data/workspace/f0.py", "/mnt/user-data/workspace/f1.py"]
    assert truncated is False


def test_aio_sandbox_grep_reports_a_dropped_match_as_truncated(monkeypatch) -> None:
    """The counterpart: a match past the cap still reports truncated."""
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(sandbox._client.file, "grep_files", _grep_files_returning(3))

    matches, truncated = sandbox.grep("/mnt/user-data/workspace", "TODO", max_results=2)

    assert [match.path for match in matches] == ["/mnt/user-data/workspace/f0.py", "/mnt/user-data/workspace/f1.py"]
    assert truncated is True


# ---------------------------------------------------------------------------
# ls_tool — path masking
# ---------------------------------------------------------------------------


def test_ls_tool_masks_user_data_host_paths(tmp_path, monkeypatch) -> None:
    """ls_tool output must not leak host user-data paths; they should be virtual."""
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "report.txt").write_text("hello\n", encoding="utf-8")
    (workspace / "subdir").mkdir()

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = ls_tool.func(
        runtime=runtime,
        description="list workspace",
        path="/mnt/user-data/workspace",
    )

    # Virtual paths must be present
    assert "/mnt/user-data/workspace" in result
    # Host paths must NOT leak
    assert str(workspace) not in result
    assert str(tmp_path) not in result


def test_ls_tool_masks_skills_host_paths(tmp_path, monkeypatch) -> None:
    """ls_tool output must not leak host skills paths; they should be virtual."""
    runtime = _make_runtime(tmp_path)
    skills_dir = tmp_path / "skills"
    (skills_dir / "public").mkdir(parents=True)
    (skills_dir / "public" / "SKILL.md").write_text("# Skill\n", encoding="utf-8")

    sandbox = LocalSandbox(
        id="local",
        path_mappings=[
            PathMapping(container_path="/mnt/skills", local_path=str(skills_dir), read_only=True),
        ],
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)

    result = ls_tool.func(
        runtime=runtime,
        description="list skills",
        path="/mnt/skills",
    )

    # Virtual paths must be present
    assert "/mnt/skills" in result
    # Host paths must NOT leak
    assert str(skills_dir) not in result
    assert str(tmp_path) not in result


def test_ls_tool_returns_empty_for_empty_directory(tmp_path, monkeypatch) -> None:
    """ls_tool should return '(empty)' for an empty directory."""
    runtime = _make_runtime(tmp_path)

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = ls_tool.func(
        runtime=runtime,
        description="list empty dir",
        path="/mnt/user-data/workspace",
    )

    assert result == "(empty)"


def test_ls_tool_skills_path_uses_sandbox_mapping_user_id_not_contextvar(tmp_path, monkeypatch) -> None:
    """ls_tool must resolve /mnt/skills/custom via the sandbox PathMapping
    (which uses the user_id from acquire time), not via _resolve_skills_path
    (which uses get_effective_user_id() from contextvar).

    Regression: when the contextvar user_id differs from the sandbox mapping's
    user_id (e.g., contextvar unset → "default", but sandbox uses authenticated
    "user-abc"), _resolve_skills_path would resolve to the wrong directory,
    making /mnt/skills/custom appear empty. The fix delegates resolution to the
    sandbox's PathMapping which always uses the acquire-time user_id.
    """
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    # Create two user-specific custom skill directories:
    # - user-abc: has a skill "my-skill"
    # - default: empty (the fallback when contextvar is unset)
    base_dir = tmp_path / ".deer-flow"
    user_abc_custom = base_dir / "users" / "user-abc" / "skills" / "custom"
    user_abc_custom.mkdir(parents=True)
    (user_abc_custom / "my-skill").mkdir()
    (user_abc_custom / "my-skill" / "SKILL.md").write_text("# My Skill\n", encoding="utf-8")

    default_custom = base_dir / "users" / "default" / "skills" / "custom"
    default_custom.mkdir(parents=True)  # exists but empty

    # Create a sandbox with PathMappings that use user-abc's directory
    # (simulating a sandbox acquired for user-abc)
    sandbox = LocalSandbox(
        id="local:user-abc:thread-1",
        path_mappings=[
            PathMapping(container_path="/mnt/skills/custom", local_path=str(user_abc_custom), read_only=True),
        ],
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)

    # Listing a category root descends into the skills below it, so the
    # disabled-skill gate now resolves each one's enabled state. That lookup
    # needs app config; without it the gate fails closed (see PR #3889) and the
    # listing would be empty for a reason unrelated to what this test asserts.
    skills_root = tmp_path / "skills"
    (skills_root / "custom").mkdir(parents=True)
    app_config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )

    # Leave contextvar unset → get_effective_user_id() returns "default"
    # Before the fix, _resolve_skills_path would resolve to default_custom (empty)
    # After the fix, the sandbox PathMapping resolves to user-abc_custom (has my-skill)
    token = set_current_user(SimpleNamespace(id="default"))  # contextvar says "default"
    try:
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.get_app_config", return_value=app_config):
                result = ls_tool.func(
                    runtime=_make_runtime(tmp_path),
                    description="list custom skills",
                    path="/mnt/skills/custom",
                )

        # Must show user-abc's skill (sandbox mapping), NOT default's empty dir (contextvar)
        assert "my-skill" in result
        assert str(user_abc_custom) not in result  # host paths must not leak
    finally:
        reset_current_user(token)


def test_ls_tool_filters_upload_staging_files(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    uploads = tmp_path / "uploads"
    (uploads / "report.txt").write_text("ready\n", encoding="utf-8")
    (uploads / ".upload-active.part").write_text("partial\n", encoding="utf-8")
    (uploads / ".upload-note.txt").write_text("intentional\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = ls_tool.func(
        runtime=runtime,
        description="list uploads",
        path="/mnt/user-data/uploads",
    )

    assert "/mnt/user-data/uploads/report.txt" in result
    assert "/mnt/user-data/uploads/.upload-note.txt" in result
    assert ".upload-active.part" not in result


@pytest.mark.parametrize("path", ["/mnt/user-data", "/mnt/user-data/"])
def test_ls_tool_lists_user_data_root(tmp_path, monkeypatch, path) -> None:
    """The local provider maps the aggregate root, so ls must list it like AIO."""
    runtime = _make_runtime(tmp_path)
    (tmp_path / "uploads" / "report.txt").write_text("ready\n", encoding="utf-8")
    (tmp_path / "uploads" / ".upload-active.part").write_text("partial\n", encoding="utf-8")
    (tmp_path / "workspace" / "src").mkdir()
    (tmp_path / "workspace" / "src" / "deep.py").write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = ls_tool.func(runtime=runtime, description="list user data", path=path)

    for name in ("workspace", "uploads", "outputs"):
        assert f"/mnt/user-data/{name}" in result
    assert "/mnt/user-data/uploads/report.txt" in result
    assert "/mnt/user-data/workspace/src" in result
    # Two levels from the root, like any other ls.
    assert "deep.py" not in result
    assert ".upload-active.part" not in result
    assert str(tmp_path) not in result


def _plant_outside_allowed_dirs(tmp_path) -> None:
    """Content in user-data/ that is not under workspace, uploads, or outputs."""
    (tmp_path / "private.txt").write_text("ROOT_SECRET\n", encoding="utf-8")
    (tmp_path / "extra").mkdir()
    (tmp_path / "extra" / "notes.txt").write_text("EXTRA_SECRET\n", encoding="utf-8")


@pytest.mark.parametrize("path", ["/mnt/user-data", "/mnt/user-data/"])
def test_ls_tool_on_user_data_root_lists_only_allowed_dirs(tmp_path, monkeypatch, path) -> None:
    runtime = _make_runtime(tmp_path)
    _plant_outside_allowed_dirs(tmp_path)
    symlink_or_skip(tmp_path / "workspace" / "alias.txt", tmp_path / "private.txt")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = ls_tool.func(runtime=runtime, description="list user data", path=path)

    assert "/mnt/user-data/workspace" in result
    assert "private.txt" not in result
    assert "extra" not in result


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        (glob_tool, {"pattern": "**/*.txt"}),
        (grep_tool, {"pattern": "SECRET"}),
    ],
)
@pytest.mark.parametrize("path", ["/mnt/user-data", "/mnt/user-data/"])
def test_search_tools_reject_user_data_root(tmp_path, monkeypatch, tool, arguments, path) -> None:
    """A search walks every descendant, so it must not start above the allowed dirs."""
    runtime = _make_runtime(tmp_path)
    _plant_outside_allowed_dirs(tmp_path)

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = tool.func(runtime=runtime, description="search user data", path=path, **arguments)

    assert result == f"Error: Permission denied: {path}"


def _make_skills_sandbox(tmp_path, monkeypatch, *, disabled: str):
    """Skills tree with one disabled and one enabled public skill.

    Drives the real `_is_disabled_skill_path` gate through a real
    extensions_config.json rather than stubbing the gate out.
    """
    skills_dir = tmp_path / "skills"
    for name, body in [(disabled, "SECRET_PROCEDURE = step-1-step-2\n"), ("open-skill", "PUBLIC_PROCEDURE = hello\n")]:
        (skills_dir / "public" / name).mkdir(parents=True)
        (skills_dir / "public" / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n\n{body}", encoding="utf-8")

    ext = tmp_path / "extensions_config.json"
    ext.write_text(
        json.dumps({"mcpServers": {}, "skills": {disabled: {"enabled": False}, "open-skill": {"enabled": True}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(ext))

    sandbox = LocalSandbox(
        id="local",
        path_mappings=[PathMapping(container_path="/mnt/skills", local_path=str(skills_dir), read_only=True)],
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    return sandbox


def test_glob_tool_blocks_disabled_skill_root(tmp_path, monkeypatch) -> None:
    """glob must refuse a disabled skill's own directory, like ls and read_file do."""
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = glob_tool.func(
        runtime=runtime,
        description="list skill files",
        pattern="**/*.md",
        path="/mnt/skills/public/secret-skill",
    )

    assert "Skill 'secret-skill' is disabled" in result
    assert "SKILL.md" not in result


def test_grep_tool_blocks_disabled_skill_root(tmp_path, monkeypatch) -> None:
    """grep must refuse a disabled skill's own directory, like ls and read_file do."""
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = grep_tool.func(
        runtime=runtime,
        description="search skill files",
        pattern="SECRET_PROCEDURE",
        path="/mnt/skills/public/secret-skill",
    )

    assert "Skill 'secret-skill' is disabled" in result
    assert "SECRET_PROCEDURE = step-1-step-2" not in result


def test_glob_tool_does_not_surface_disabled_skill_from_ancestor_root(tmp_path, monkeypatch) -> None:
    """A root above the skill must not surface it: glob descends past the path gate."""
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = glob_tool.func(
        runtime=runtime,
        description="find skills",
        pattern="**/SKILL.md",
        path="/mnt/skills",
    )

    assert "secret-skill" not in result
    # ...while the enabled sibling is still returned.
    assert "/mnt/skills/public/open-skill/SKILL.md" in result


def test_glob_tool_drops_disabled_skill_reported_under_a_provider_alias(tmp_path, monkeypatch) -> None:
    """A provider that reports results under /mnt/user-data but checks skills
    against the backing home must still filter a disabled skill.

    E2B and Tenki map ``/home/<user>/skills`` to ``/mnt/user-data/skills`` in
    their results; without resolving the alias the enabled-state check cannot
    recognize the skill and returns its files.
    """
    runtime = _make_runtime(tmp_path)
    runtime.state["sandbox"] = {"sandbox_id": "e2b-fake"}
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")
    monkeypatch.setattr("deerflow.sandbox.tools._get_skills_container_path", lambda: "/home/user/skills")

    class _AliasSandbox:
        def glob(self, path, pattern, *, include_dirs=False, max_results=200):
            return [
                "/mnt/user-data/skills/public/secret-skill/SKILL.md",
                "/mnt/user-data/skills/public/open-skill/SKILL.md",
            ], False

        def resolve_access_control_path(self, path):
            prefix = "/mnt/user-data/skills/"
            if path.startswith(prefix):
                return "/home/user/skills/" + path[len(prefix) :]
            return path

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: _AliasSandbox())

    result = glob_tool.func(
        runtime=runtime,
        description="find skills",
        pattern="**/SKILL.md",
        path="/mnt/user-data/skills",
    )

    assert "secret-skill" not in result
    # ...while the enabled sibling is still returned.
    assert "/mnt/user-data/skills/public/open-skill/SKILL.md" in result


def test_glob_tool_drops_disabled_skill_reported_under_a_non_canonical_skills_root(tmp_path, monkeypatch) -> None:
    """A shell-backed provider echoes the root spelling, so results may carry
    ``/mnt//skills``; the filter must normalize before extracting the skill."""
    runtime = _make_runtime(tmp_path)
    runtime.state["sandbox"] = {"sandbox_id": "boxlite-fake"}
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    class _SpellingSandbox:
        def glob(self, path, pattern, *, include_dirs=False, max_results=200):
            return [
                "/mnt//skills/public/secret-skill/SKILL.md",
                "/mnt//skills/public/open-skill/SKILL.md",
            ], False

        def resolve_access_control_path(self, path):
            return path

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: _SpellingSandbox())

    result = glob_tool.func(
        runtime=runtime,
        description="find skills",
        pattern="**/SKILL.md",
        path="/mnt//skills",
    )

    assert "secret-skill" not in result
    assert "/mnt//skills/public/open-skill/SKILL.md" in result


def test_ls_tool_drops_disabled_skill_reported_under_a_provider_alias(tmp_path, monkeypatch) -> None:
    """ls descends into results too, so the same alias resolution must apply."""
    runtime = _make_runtime(tmp_path)
    runtime.state["sandbox"] = {"sandbox_id": "e2b-fake"}
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")
    monkeypatch.setattr("deerflow.sandbox.tools._get_skills_container_path", lambda: "/home/user/skills")

    class _AliasSandbox:
        def list_dir(self, path):
            return [
                "/mnt/user-data/skills/public/secret-skill/SKILL.md",
                "/mnt/user-data/skills/public/open-skill/SKILL.md",
            ]

        def resolve_access_control_path(self, path):
            prefix = "/mnt/user-data/skills/"
            if path.startswith(prefix):
                return "/home/user/skills/" + path[len(prefix) :]
            return path

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: _AliasSandbox())

    result = ls_tool.func(
        runtime=runtime,
        description="list skills",
        path="/mnt/user-data/skills/public",
    )

    assert "secret-skill" not in result
    assert "/mnt/user-data/skills/public/open-skill/SKILL.md" in result


def test_grep_tool_drops_disabled_skill_reported_under_a_provider_alias(tmp_path, monkeypatch) -> None:
    """grep results carry the same aliased paths, including their contents."""
    runtime = _make_runtime(tmp_path)
    runtime.state["sandbox"] = {"sandbox_id": "e2b-fake"}
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")
    monkeypatch.setattr("deerflow.sandbox.tools._get_skills_container_path", lambda: "/home/user/skills")

    class _AliasSandbox:
        def grep(self, path, pattern, *, glob=None, literal=False, case_sensitive=False, max_results=100):
            return [
                GrepMatch(
                    path="/mnt/user-data/skills/public/secret-skill/SKILL.md",
                    line_number=1,
                    line="SECRET_PROCEDURE = step-1-step-2",
                ),
                GrepMatch(
                    path="/mnt/user-data/skills/public/open-skill/SKILL.md",
                    line_number=1,
                    line="PUBLIC_PROCEDURE = hello",
                ),
            ], False

        def resolve_access_control_path(self, path):
            prefix = "/mnt/user-data/skills/"
            if path.startswith(prefix):
                return "/home/user/skills/" + path[len(prefix) :]
            return path

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: _AliasSandbox())

    result = grep_tool.func(
        runtime=runtime,
        description="search skills",
        pattern="PROCEDURE",
        path="/mnt/user-data/skills/public",
    )

    assert "SECRET_PROCEDURE" not in result
    assert "PUBLIC_PROCEDURE = hello" in result


def test_grep_tool_does_not_surface_disabled_skill_content_from_ancestor_root(tmp_path, monkeypatch) -> None:
    """The strongest leak: grep from /mnt/skills printed a disabled skill's file contents."""
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = grep_tool.func(
        runtime=runtime,
        description="search skills",
        pattern="PROCEDURE",
        path="/mnt/skills",
    )

    assert "SECRET_PROCEDURE = step-1-step-2" not in result
    assert "secret-skill" not in result
    # ...while the enabled sibling still matches.
    assert "PUBLIC_PROCEDURE = hello" in result


def test_ls_tool_does_not_surface_disabled_skill_from_category_root(tmp_path, monkeypatch) -> None:
    """ls gates the requested path but descends two levels, so the category root leaked."""
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = ls_tool.func(
        runtime=runtime,
        description="list public skills",
        path="/mnt/skills/public",
    )

    assert "secret-skill" not in result
    # ...while the enabled sibling is still listed.
    assert "open-skill" in result


def test_ls_tool_blocks_a_non_canonical_disabled_skill_path(tmp_path, monkeypatch) -> None:
    """`/mnt//skills/...` addresses the same skill, so the gate must normalize
    before the prefix check instead of letting the spelling skip it."""
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = ls_tool.func(
        runtime=runtime,
        description="list the disabled skill",
        path="/mnt//skills/public/secret-skill",
    )

    assert "Skill 'secret-skill' is disabled" in result


def test_ls_tool_keeps_category_dirs_when_listing_skills_root(tmp_path, monkeypatch) -> None:
    """`ls /mnt/skills` lists dirs with a trailing slash ("public/"), which the
    skill-name extractor must read as a category root, not as a skill named "".

    An empty name skips the `skill_name is None` short-circuit and falls through
    to a config read; it currently lands on "keep" only because unknown skills
    default to enabled. This pins the intended outcome directly: category dirs
    stay visible while the disabled skill below them does not.
    """
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = ls_tool.func(
        runtime=runtime,
        description="list skills root",
        path="/mnt/skills",
    )

    assert "/mnt/skills/public" in result
    assert "open-skill" in result
    assert "secret-skill" not in result


def test_extract_skill_name_treats_category_dir_with_trailing_slash_as_root() -> None:
    """LocalSandbox.list_dir appends "/" to directories, so the gate sees
    "/mnt/skills/public/" — which must resolve to None (category root), not "".
    """
    from deerflow.sandbox.tools import _extract_skill_name_from_skills_path as extract

    # Changed direction: trailing-slash category roots used to yield "".
    assert extract("/mnt/skills/public/") is None
    assert extract("/mnt/skills/custom/") is None
    assert extract("/mnt/skills/legacy/") is None
    # Unchanged directions: real skills still resolve, with or without the slash.
    assert extract("/mnt/skills/public") is None
    assert extract("/mnt/skills/public/bootstrap") == "bootstrap"
    assert extract("/mnt/skills/public/bootstrap/") == "bootstrap"
    assert extract("/mnt/skills/public/bootstrap/SKILL.md") == "bootstrap"
    assert extract("/mnt/skills/my-skill/") == "my-skill"
    assert extract("/mnt/user-data/workspace/file.md") is None
    # Equivalent spellings address the same skill tree and must not dodge the
    # prefix check.
    assert extract("/mnt//skills/public/bootstrap/SKILL.md") == "bootstrap"
    assert extract("/mnt/./skills/public/bootstrap/SKILL.md") == "bootstrap"
    assert extract("/mnt//skills/public/") is None
    assert extract("/mnt//user-data/workspace/file.md") is None


def _make_custom_skills_sandbox(tmp_path, monkeypatch, *, user_id: str, disabled: str):
    """Per-user CUSTOM skills tree with one disabled and one enabled skill.

    CUSTOM/LEGACY enabled state lives in the per-user ``_skill_states.json``
    (``UserScopedSkillStorage``), a different store from the public skills'
    ``extensions_config.json`` — so the public fixture above does not exercise
    this branch of ``_is_disabled_skill_path``.
    """
    from deerflow.skills.storage import reset_skill_storage

    base_dir = tmp_path / ".deer-flow"
    user_skills = base_dir / "users" / user_id / "skills"
    user_custom = user_skills / "custom"
    for name, body in [(disabled, "SECRET_PROCEDURE = step-1-step-2\n"), ("open-custom", "PUBLIC_PROCEDURE = hello\n")]:
        (user_custom / name).mkdir(parents=True)
        (user_custom / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n\n{body}", encoding="utf-8")

    (user_skills / "_skill_states.json").write_text(
        json.dumps({disabled: {"enabled": False}, "open-custom": {"enabled": True}}),
        encoding="utf-8",
    )

    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir(parents=True)
    app_config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )

    sandbox = LocalSandbox(
        id=f"local:{user_id}:thread-1",
        path_mappings=[PathMapping(container_path="/mnt/skills/custom", local_path=str(user_custom), read_only=True)],
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    # The storage cache is keyed by user id, not by base_dir: a cached instance
    # from another test would read the wrong _skill_states.json.
    reset_skill_storage()
    monkeypatch.setattr("deerflow.sandbox.tools.resolve_runtime_user_id", lambda runtime: user_id)
    return base_dir, app_config


def test_grep_tool_does_not_surface_disabled_custom_skill(tmp_path, monkeypatch) -> None:
    """CUSTOM skills resolve enabled state through the per-user _skill_states.json,
    not extensions_config.json — the store the public-skill tests never touch."""
    from deerflow.skills.storage import reset_skill_storage

    runtime = _make_runtime(tmp_path)
    base_dir, app_config = _make_custom_skills_sandbox(tmp_path, monkeypatch, user_id="user-abc", disabled="secret-custom")

    try:
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.get_app_config", return_value=app_config):
                result = grep_tool.func(
                    runtime=runtime,
                    description="search custom skills",
                    pattern="PROCEDURE",
                    path="/mnt/skills/custom",
                )
    finally:
        reset_skill_storage()

    assert "SECRET_PROCEDURE = step-1-step-2" not in result
    assert "secret-custom" not in result
    # ...while the enabled sibling still matches.
    assert "PUBLIC_PROCEDURE = hello" in result


def test_ls_tool_does_not_surface_disabled_custom_skill(tmp_path, monkeypatch) -> None:
    """Same per-user store, via the descending ls listing."""
    from deerflow.skills.storage import reset_skill_storage

    runtime = _make_runtime(tmp_path)
    base_dir, app_config = _make_custom_skills_sandbox(tmp_path, monkeypatch, user_id="user-abc", disabled="secret-custom")

    try:
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.get_app_config", return_value=app_config):
                result = ls_tool.func(
                    runtime=runtime,
                    description="list custom skills",
                    path="/mnt/skills/custom",
                )
    finally:
        reset_skill_storage()

    assert "secret-custom" not in result
    assert "open-custom" in result

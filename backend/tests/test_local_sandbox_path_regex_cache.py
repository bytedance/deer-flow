"""Issue #3647 — LocalSandbox must compile its path-rewrite regexes once per
sandbox (cached), not on every bash/read_file/write_file call, while keeping
the exact same rewriting behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.sandbox.local import local_sandbox as local_sandbox_module
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping


def _make_sandbox(tmp_path: Path) -> LocalSandbox:
    ws = tmp_path / "workspace"
    skills = tmp_path / "skills"
    ws.mkdir()
    skills.mkdir()
    return LocalSandbox(
        id="test",
        path_mappings=[
            PathMapping(container_path="/mnt/user-data/workspace", local_path=str(ws)),
            PathMapping(container_path="/mnt/skills", local_path=str(skills), read_only=True),
        ],
    )


def test_patterns_are_compiled_once_and_cached(tmp_path):
    sb = _make_sandbox(tmp_path)
    # Each cached_property returns the identical object across accesses.
    assert sb._command_pattern is sb._command_pattern
    assert sb._content_pattern is sb._content_pattern
    assert sb._reverse_output_patterns is sb._reverse_output_patterns
    # Two mappings -> two reverse-output patterns.
    assert len(sb._reverse_output_patterns) == 2


def test_empty_mappings_yield_no_pattern(tmp_path):
    sb = LocalSandbox(id="empty", path_mappings=[])
    assert sb._command_pattern is None
    assert sb._content_pattern is None
    assert sb._reverse_output_patterns == []
    # No mappings -> command/content pass through unchanged.
    assert sb._resolve_paths_in_command("echo hello") == "echo hello"
    assert sb._resolve_paths_in_content("plain text") == "plain text"


def test_command_paths_resolved_to_local(tmp_path):
    sb = _make_sandbox(tmp_path)
    ws_local = str((tmp_path / "workspace").resolve())
    out = sb._resolve_paths_in_command("cat /mnt/user-data/workspace/foo.txt")
    assert out == f"cat {ws_local}/foo.txt"
    # Calling again uses the cached pattern and produces the same result.
    assert sb._resolve_paths_in_command("cat /mnt/user-data/workspace/foo.txt") == out


def test_segment_boundary_not_matched_inside_longer_name(tmp_path):
    sb = _make_sandbox(tmp_path)
    # "/mnt/skills-extra" must NOT be rewritten by the "/mnt/skills" mapping.
    out = sb._resolve_paths_in_command("ls /mnt/skills-extra/data")
    assert out == "ls /mnt/skills-extra/data"


def test_reverse_resolve_output_maps_local_back_to_container(tmp_path):
    sb = _make_sandbox(tmp_path)
    ws_local = str((tmp_path / "workspace").resolve())
    out = sb._reverse_resolve_paths_in_output(f"wrote {ws_local}/foo.txt ok")
    assert out == "wrote /mnt/user-data/workspace/foo.txt ok"


@pytest.mark.parametrize("suffix", ["-extra/data.txt", "2/x", ".bak", "foo", "_backup/y"])
def test_reverse_resolve_does_not_match_inside_longer_sibling(tmp_path, suffix):
    """Mirror of test_segment_boundary_not_matched_inside_longer_name, reverse direction.

    Without a segment-boundary lookahead the pattern matches the bare mount root
    inside a sibling that shares its prefix. The extracted text then *equals* the
    mount root, so ``_reverse_resolve_path``'s own ``+ "/"`` guard is satisfied and
    the sibling is rewritten to ``/mnt/skills<suffix>`` — a container path forward
    resolution refuses to map back, so the model can never read it.
    """
    sb = _make_sandbox(tmp_path)
    skills_local = str((tmp_path / "skills").resolve())
    sibling = f"{skills_local}{suffix}"

    out = sb._reverse_resolve_paths_in_output(f"see {sibling}")

    assert out == f"see {sibling}"
    assert "/mnt/skills" not in out


@pytest.mark.parametrize(
    ("trailer", "expected_trailer"),
    [
        (", ok", ", ok"),  # comma — a path can end a clause in prose output
        (":/other", ":/other"),  # colon — PATH-style concatenation
        ("\\win\\p", "/win/p"),  # backslash — Windows-style separator
        (" done", " done"),  # whitespace
        ("' ", "' "),  # quote
    ],
)
def test_reverse_resolve_still_matches_root_before_non_slash_boundaries(tmp_path, trailer, expected_trailer):
    """The narrowing must not drop boundaries the old pattern accepted.

    ``_reverse_output_patterns`` runs over arbitrary command output, so the mount
    root can legitimately be followed by ``,``, ``:`` or ``\\``. Copying
    ``_command_pattern``'s shell-oriented boundary class here would silently stop
    translating all three; this pins the ``_content_pattern`` class that does not.
    """
    sb = _make_sandbox(tmp_path)
    skills_local = str((tmp_path / "skills").resolve())

    out = sb._reverse_resolve_paths_in_output(f"{skills_local}{trailer}")

    assert out == f"/mnt/skills{expected_trailer}"


@pytest.mark.parametrize("prefix", ["", "cwd: ", "see "])
def test_reverse_resolve_translates_a_bare_root_at_end_of_output(tmp_path, prefix):
    """The lookahead's ``$`` alternative, pinned on its own.

    Output ending exactly at a mount root (no trailing separator, no newline —
    ``printf '%s' "$PWD"``, a stripped last line, a truncated buffer) satisfies
    neither ``/`` nor ``[^\\w./-]``. Drop ``$`` and the match fails, so the raw
    host path is handed to the model instead of the container path: the leak
    this whole function exists to prevent. The suite is otherwise blind to it —
    removing ``$`` leaves all 6866 tests green.
    """
    sb = _make_sandbox(tmp_path)
    skills_local = str((tmp_path / "skills").resolve())

    out = sb._reverse_resolve_paths_in_output(f"{prefix}{skills_local}")

    assert out == f"{prefix}/mnt/skills"
    assert skills_local not in out


def test_reverse_resolve_path_matches_windows_backslash_containment(monkeypatch):
    """Regression for the os.sep containment fix in ``_reverse_resolve_path``.

    ``Path.resolve()`` always renders with the native separator (backslash on
    Windows). The containment check used to hardcode a ``"/"`` suffix, so a
    backslash-joined nested path could never satisfy
    ``path_str.startswith(local_path_resolved + "/")`` on Windows and silently
    fell through to the "no mapping found" branch, leaking the raw host path
    (real username, full directory tree) instead of the virtual
    ``/mnt/user-data/...`` path.

    CI runs only on ``ubuntu-latest`` (``os.sep == "/"``), where the pre-fix and
    post-fix code are observationally identical -- neither the hardcoded ``"/"``
    nor ``os.sep`` behave any differently there, so a test that just calls
    ``_reverse_resolve_path`` on real POSIX paths cannot discriminate. To force
    the Windows code path independent of host OS, ``os.sep`` is monkeypatched to
    ``"\\"`` and both the module's ``Path`` name and the sandbox's cached
    ``_resolved_local_paths`` are stubbed to return backslash-joined strings --
    exactly what real ``WindowsPath.resolve()`` produces -- without touching the
    real filesystem or requiring an actual Windows host.
    """
    sb = LocalSandbox(
        id="windows-sep-test",
        path_mappings=[
            PathMapping(container_path="/mnt/user-data/workspace", local_path="C:\\Users\\test\\workspace"),
        ],
    )
    mapping = sb.path_mappings[0]

    monkeypatch.setattr(local_sandbox_module.os, "sep", "\\")
    # Bypass the real (POSIX) filesystem resolution this cached_property would
    # otherwise perform and pin it directly to the Windows-resolved root.
    sb._resolved_local_paths = {mapping: "C:\\Users\\test\\workspace"}

    class _FakeWindowsPath:
        """Stand-in for ``Path`` inside ``_reverse_resolve_path``. Mimics
        ``WindowsPath.resolve()`` -- a backslash-joined ``str()`` -- without
        touching the real filesystem, so this runs identically on Linux CI."""

        def __init__(self, raw: str) -> None:
            self._raw = raw

        def resolve(self) -> _FakeWindowsPath:
            return _FakeWindowsPath(self._raw.replace("/", "\\"))

        def __str__(self) -> str:
            return self._raw

    monkeypatch.setattr(local_sandbox_module, "Path", _FakeWindowsPath)

    result = sb._reverse_resolve_path("C:\\Users\\test\\workspace\\sub\\f.txt")

    assert result == "/mnt/user-data/workspace/sub/f.txt"


def test_resolved_paths_and_sorted_views_are_cached(tmp_path):
    sb = _make_sandbox(tmp_path)
    # Resolved-local map and sorted views are computed once and reused.
    assert sb._resolved_local_paths is sb._resolved_local_paths
    assert sb._mappings_by_container_specificity is sb._mappings_by_container_specificity
    assert sb._mappings_by_local_specificity is sb._mappings_by_local_specificity
    # Map covers every mapping with its filesystem-resolved local root.
    assert set(sb._resolved_local_paths.values()) == {
        str((tmp_path / "workspace").resolve()),
        str((tmp_path / "skills").resolve()),
    }
    # Most-specific (longest) container path is ordered first.
    assert sb._mappings_by_container_specificity[0].container_path == "/mnt/user-data/workspace"


def test_forward_resolution_behavior_unchanged(tmp_path):
    sb = _make_sandbox(tmp_path)
    ws_local = str((tmp_path / "workspace").resolve())
    # Container path resolves to the mapped local path.
    assert sb._resolve_path("/mnt/user-data/workspace/sub/foo.txt") == f"{ws_local}/sub/foo.txt"
    # An unmapped path is returned unchanged.
    assert sb._resolve_path("/etc/hosts") == "/etc/hosts"


def test_read_only_mount_detected(tmp_path):
    sb = _make_sandbox(tmp_path)
    skills_local = str((tmp_path / "skills").resolve())
    ws_local = str((tmp_path / "workspace").resolve())
    assert sb._is_read_only_path(f"{skills_local}/a.md") is True
    assert sb._is_read_only_path(f"{ws_local}/a.txt") is False

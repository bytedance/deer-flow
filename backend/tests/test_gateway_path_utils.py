"""Tests for the shared outputs-confinement helpers in ``app.gateway.path_utils``.

The artifact editor (``PUT /artifacts``) and IM-channel attachment delivery
both must never touch anything outside ``/mnt/user-data/outputs``. The rule
used to be re-implemented per caller; these tests pin the single shared
implementation so the copies cannot drift again.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.gateway.path_utils import OUTPUTS_VIRTUAL_ROOT, normalize_outputs_virtual_path, resolve_outputs_confined_path
from deerflow.config.paths import Paths

THREAD_ID = "thread-1"
USER_ID = "user-1"


@pytest.fixture
def thread_dirs(tmp_path, monkeypatch) -> tuple[Path, Path]:
    """Point the global ``Paths`` at *tmp_path* and return (outputs, uploads)."""
    paths = Paths(tmp_path)
    monkeypatch.setattr("app.gateway.path_utils.get_paths", lambda: paths)
    outputs = paths.sandbox_outputs_dir(THREAD_ID, user_id=USER_ID)
    uploads = paths.sandbox_uploads_dir(THREAD_ID, user_id=USER_ID)
    outputs.mkdir(parents=True)
    uploads.mkdir(parents=True)
    return outputs, uploads


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")


class TestNormalizeOutputsVirtualPath:
    def test_returns_canonical_absolute_virtual_path(self) -> None:
        assert normalize_outputs_virtual_path("mnt/user-data/outputs/report.md") == "/mnt/user-data/outputs/report.md"
        assert normalize_outputs_virtual_path("//mnt/user-data/outputs//a/./b.txt") == "/mnt/user-data/outputs/a/b.txt"

    def test_collapses_dot_dot_that_stays_inside_outputs(self) -> None:
        assert normalize_outputs_virtual_path("/mnt/user-data/outputs/nested/../note.txt") == "/mnt/user-data/outputs/note.txt"

    @pytest.mark.parametrize(
        "virtual_path",
        [
            "/mnt/user-data/uploads/secret.pdf",
            "/mnt/user-data/workspace/config.py",
            "/mnt/user-data/outputs/../uploads/secret.pdf",
            "/mnt/user-data/outputsX/file.txt",
            "/mnt/user-data/outputs",
            "/mnt/user-data/outputs/",
            "/invalid/path",
            "",
        ],
    )
    def test_rejects_paths_outside_outputs(self, virtual_path: str) -> None:
        with pytest.raises(HTTPException) as exc_info:
            normalize_outputs_virtual_path(virtual_path)
        assert exc_info.value.status_code == 400

    def test_root_constant_matches_prefix(self) -> None:
        assert OUTPUTS_VIRTUAL_ROOT == "/mnt/user-data/outputs"


class TestResolveOutputsConfinedPath:
    def test_resolves_regular_file_under_outputs(self, thread_dirs) -> None:
        outputs, _ = thread_dirs
        target = outputs / "report.md"
        target.write_text("hello", encoding="utf-8")

        resolved = resolve_outputs_confined_path(THREAD_ID, "/mnt/user-data/outputs/report.md", user_id=USER_ID)

        assert resolved == target.resolve()

    def test_does_not_require_the_file_to_exist(self, thread_dirs) -> None:
        # Existence is the caller's decision (the editor 404s, channels warn).
        outputs, _ = thread_dirs

        resolved = resolve_outputs_confined_path(THREAD_ID, "/mnt/user-data/outputs/missing.txt", user_id=USER_ID)

        assert resolved == (outputs / "missing.txt").resolve()

    def test_rejects_dot_dot_escape_lexically(self, thread_dirs) -> None:
        _, uploads = thread_dirs
        (uploads / "victim.txt").write_text("before", encoding="utf-8")

        with pytest.raises(HTTPException) as exc_info:
            resolve_outputs_confined_path(THREAD_ID, "/mnt/user-data/outputs/../uploads/victim.txt", user_id=USER_ID)

        assert exc_info.value.status_code == 400

    def test_rejects_symlink_pointing_at_sibling_directory(self, thread_dirs) -> None:
        outputs, uploads = thread_dirs
        victim = uploads / "victim.txt"
        victim.write_text("before", encoding="utf-8")
        _symlink_or_skip(outputs / "linked.txt", victim)

        with pytest.raises(HTTPException) as exc_info:
            resolve_outputs_confined_path(THREAD_ID, "/mnt/user-data/outputs/linked.txt", user_id=USER_ID)

        assert exc_info.value.status_code == 400

    def test_symlink_escaping_user_data_is_a_traversal(self, thread_dirs, tmp_path) -> None:
        # Above ``user-data/`` the underlying resolver already refuses; that 403
        # must not be downgraded by the outputs check layered on top.
        outputs, _ = thread_dirs
        outside = tmp_path / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        _symlink_or_skip(outputs / "linked.txt", outside)

        with pytest.raises(HTTPException) as exc_info:
            resolve_outputs_confined_path(THREAD_ID, "/mnt/user-data/outputs/linked.txt", user_id=USER_ID)

        assert exc_info.value.status_code == 403

    def test_symlinked_outputs_root_outside_user_data_is_a_traversal(self, thread_dirs, tmp_path) -> None:
        # An outputs root re-pointed outside ``user-data/`` is refused by the
        # underlying resolver (matching ``artifact_archive``), not accepted
        # because both sides happen to resolve consistently.
        outputs, _ = thread_dirs
        real_outputs = tmp_path / "real-outputs"
        real_outputs.mkdir()
        (real_outputs / "report.md").write_text("hello", encoding="utf-8")
        outputs.rmdir()
        _symlink_or_skip(outputs, real_outputs)

        with pytest.raises(HTTPException) as exc_info:
            resolve_outputs_confined_path(THREAD_ID, "/mnt/user-data/outputs/report.md", user_id=USER_ID)

        assert exc_info.value.status_code == 403

    def test_defaults_to_effective_user(self, thread_dirs, monkeypatch) -> None:
        outputs, _ = thread_dirs
        monkeypatch.setattr("app.gateway.path_utils.get_effective_user_id", lambda: USER_ID)

        resolved = resolve_outputs_confined_path(THREAD_ID, "/mnt/user-data/outputs/report.md")

        assert resolved == (outputs / "report.md").resolve()

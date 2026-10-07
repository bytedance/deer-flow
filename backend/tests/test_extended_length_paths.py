"""Windows filesystem spelling and document confinement regressions."""

import ntpath
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config.paths import Paths
from deerflow.utils import host_paths


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r"C:\shelf\..\documents", r"\\?\C:\documents"),
        ("C:/shelf/documents", r"\\?\C:\shelf\documents"),
        (r"\\server\share\shelf", r"\\?\UNC\server\share\shelf"),
        (r"\\?\C:\shelf", r"\\?\C:\shelf"),
        (r"\\?\UNC\server\share\shelf", r"\\?\UNC\server\share\shelf"),
    ],
)
def test_windows_extended_spelling(monkeypatch, raw, expected):
    # Patch this module's OS binding, never the process-wide os.name (pathlib
    # and pytest need to keep using the actual host's path implementation).
    monkeypatch.setattr(host_paths, "os", SimpleNamespace(name="nt", path=ntpath))
    assert str(host_paths.extended_length_path(Path(raw))) == expected


def test_posix_path_is_unchanged(monkeypatch):
    monkeypatch.setattr(host_paths, "os", SimpleNamespace(name="posix"))
    path = Path("relative/documents")
    assert host_paths.extended_length_path(path) is path


@pytest.mark.skipif(os.name != "nt", reason="native Windows relative-path normalization")
def test_windows_relative_path_is_absolutized(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    actual = host_paths.extended_length_path(Path("shelf/../documents"))
    assert str(actual) == "\\\\?\\" + str(tmp_path / "documents")


def test_document_traversal_is_still_rejected(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with pytest.raises(ValueError, match="path traversal"):
        paths.project_document_path("alice", "../outside")
    with pytest.raises(ValueError, match="path traversal"):
        paths.project_document_path("alice", str(tmp_path / "outside"))


@pytest.mark.parametrize("outside_root", [False, True])
def test_document_symlink_confinement(tmp_path, outside_root):
    paths = Paths(base_dir=tmp_path)
    base = paths.user_projects_dir("alice")
    base.mkdir(parents=True)
    target = tmp_path / "outside" if outside_root else base / "target"
    target.mkdir()
    try:
        (base / "link").symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name == "nt":
            pytest.skip("Windows symlink privilege is not available")
        raise
    if outside_root:
        with pytest.raises(ValueError, match="path traversal"):
            paths.project_document_path("alice", "link/content")
    else:
        assert paths.project_document_path("alice", "link/content") == (target / "content").resolve()

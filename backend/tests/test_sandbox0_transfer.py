"""Artifact boundary tests use synthetic archives, never cloud credentials."""

import io
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deerflow.community.sandbox0.transfer import _write_host_file, download_artifacts, upload_skills


def test_artifacts_are_available_to_host_endpoint(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("outputs/report.txt", "result")
        z.writestr("workspace/code.py", "print(1)")
    sandbox = Mock()
    sandbox.remote.read_file.return_value = data.getvalue()
    download_artifacts(sandbox, tmp_path)
    assert (tmp_path / "outputs/report.txt").read_text() == "result"
    assert (tmp_path / "workspace/code.py").read_text() == "print(1)"
    sandbox.remote.delete_file.assert_called_once()


@pytest.mark.parametrize("path", ["../../outside", "/etc/file", "outputs/../../file", "uploads/file"])
def test_artifact_archive_rejects_escape(tmp_path, path):
    with pytest.raises(PermissionError):
        _write_host_file(tmp_path, path, b"data")


def test_artifact_destination_cannot_follow_symlink(tmp_path):
    target = tmp_path / "unrelated"
    target.mkdir()
    (tmp_path / "outputs").symlink_to(target, target_is_directory=True)
    with pytest.raises(PermissionError):
        _write_host_file(tmp_path, "outputs/secret", b"overwrite")
    assert not (target / "secret").exists()


def test_skill_upload_contains_only_prepared_categories(tmp_path):
    roots = {}
    for category in ("public", "custom", "legacy", "integrations"):
        roots[category] = tmp_path / category
        roots[category].mkdir()
    (roots["public"] / "SKILL.md").write_text("synthetic skill")
    sandbox = Mock()
    upload_skills(sandbox, SimpleNamespace(**roots))
    content = sandbox.update_file.call_args.args[1]
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        assert z.namelist() == ["public/SKILL.md"]
    sandbox.remote.delete_file.assert_called_once()


def test_skill_symlink_cannot_exfiltrate_host_file(tmp_path):
    roots = {c: tmp_path / c for c in ("public", "custom", "legacy", "integrations")}
    for root in roots.values():
        root.mkdir()
    (tmp_path / "secret").write_text("secret")
    (roots["public"] / "escape").symlink_to(tmp_path / "secret")
    sandbox = Mock()
    with pytest.raises(PermissionError):
        upload_skills(sandbox, SimpleNamespace(**roots))
    sandbox.update_file.assert_not_called()


@pytest.mark.parametrize(
    "name",
    [
        r"outputs/C:\outside\owned.txt",
        "outputs/C:/outside/owned.txt",
        "outputs/C:owned.txt",
        r"outputs/\outside\owned.txt",
        r"outputs/\\server\share\owned.txt",
        r"outputs/..\outside\owned.txt",
        r"outputs/\\?\C:\outside\owned.txt",
        "outputs/report.txt:stream",
        "outputs/NUL",
        "outputs/CON.txt",
        "outputs/.. /owned.txt",
        "outputs/report.",
        "outputs/zero\x00name",
    ],
)
def test_artifact_windows_names_rejected_before_host_io(name):
    from pathlib import PureWindowsPath

    # This pure Windows root has no filesystem methods. Validation must reject
    # the member before either touching the filesystem or joining host paths.
    with pytest.raises(PermissionError):
        _write_host_file(PureWindowsPath("C:/threads/owned"), name, b"untrusted")


def test_artifact_resolved_destination_must_remain_under_root(tmp_path, monkeypatch):
    from pathlib import Path

    root = tmp_path / "thread"
    target = root / "outputs/report.txt"
    outside = tmp_path / "outside/report.txt"
    real_resolve = Path.resolve

    def resolve(path, **kwargs):
        return outside if path == target else real_resolve(path, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(PermissionError, match="escapes"):
        _write_host_file(root, "outputs/report.txt", b"untrusted")
    assert not root.exists()
    assert not outside.exists()


def test_artifact_archive_windows_escape_cannot_write_host_file(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(r"outputs/C:\outside\owned.txt", b"untrusted")
    sandbox = Mock()
    sandbox.remote.read_file.return_value = data.getvalue()
    with pytest.raises(PermissionError):
        download_artifacts(sandbox, tmp_path)
    assert list(tmp_path.iterdir()) == []
    sandbox.remote.delete_file.assert_called_once()


def test_artifact_safe_unicode_and_spaces_preserved(tmp_path):
    _write_host_file(tmp_path, "outputs/报告 final.txt", b"result")
    assert (tmp_path / "outputs/报告 final.txt").read_bytes() == b"result"

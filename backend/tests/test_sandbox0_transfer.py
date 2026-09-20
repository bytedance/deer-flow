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

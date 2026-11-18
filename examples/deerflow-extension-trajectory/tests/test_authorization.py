from types import SimpleNamespace

import pytest
from deerflow_extension_trajectory.exporting import ExportLimit


def test_images_are_scoped_to_owner_uploads_without_symlink_escape(
    tmp_path, monkeypatch
):
    from deerflow_extension_trajectory import gateway

    from deerflow.config import paths

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    content = b"\x89PNG\r\n\x1a\nimage"
    (uploads / "valid.png").write_bytes(content)
    secret = tmp_path / "outside.png"
    secret.write_bytes(content)
    (uploads / "link.png").symlink_to(secret)
    (uploads / "directory").symlink_to(tmp_path, target_is_directory=True)

    def owner_dir(thread, user_id):
        assert (thread, user_id) == ("t", "owner")
        return uploads

    monkeypatch.setattr(
        paths, "get_paths", lambda: SimpleNamespace(sandbox_uploads_dir=owner_dir)
    )

    def read(path):
        return gateway.read_export_image("t", "owner", path)

    assert read("/mnt/user-data/uploads/valid.png") == content
    for path in [
        "/mnt/user-data/uploads/../outside.png",
        "/etc/a.png",
        "/mnt/user-data/uploads/a.svg",
    ]:
        with pytest.raises(ValueError):
            read(path)
    for path in [
        "/mnt/user-data/uploads/link.png",
        "/mnt/user-data/uploads/directory/outside.png",
    ]:
        with pytest.raises(OSError):
            read(path)
    monkeypatch.setattr(gateway, "MAX_IMAGE_BYTES", 4)
    with pytest.raises(ExportLimit):
        read("/mnt/user-data/uploads/valid.png")

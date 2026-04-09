import asyncio
import json
import stat
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import UploadFile

from app.gateway.routers import uploads
from deerflow.uploads.manager import write_docx_sidecar_manifest


def _file_dict(result, index: int = 0) -> dict:
    return result.files[index].model_dump()


def test_upload_files_writes_thread_storage_and_skips_local_sandbox_sync(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "local"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        file = UploadFile(filename="notes.txt", file=BytesIO(b"hello uploads"))
        result = asyncio.run(uploads.upload_files("thread-local", files=[file]))

    assert result.success is True
    assert len(result.files) == 1
    assert _file_dict(result)["filename"] == "notes.txt"
    assert (thread_uploads_dir / "notes.txt").read_bytes() == b"hello uploads"

    sandbox.update_file.assert_not_called()


def test_upload_files_syncs_non_local_sandbox_and_marks_markdown_file(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "aio-1"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    async def fake_convert(file_path: Path) -> Path:
        md_path = file_path.with_suffix(".md")
        md_path.write_text("converted", encoding="utf-8")
        return md_path

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "convert_file_to_markdown", AsyncMock(side_effect=fake_convert)),
    ):
        file = UploadFile(filename="report.pdf", file=BytesIO(b"pdf-bytes"))
        result = asyncio.run(uploads.upload_files("thread-aio", files=[file]))

    assert result.success is True
    assert len(result.files) == 1
    file_info = _file_dict(result)
    assert file_info["filename"] == "report.pdf"
    assert file_info["markdown_file"] == "report.md"

    assert (thread_uploads_dir / "report.pdf").read_bytes() == b"pdf-bytes"
    assert (thread_uploads_dir / "report.md").read_text(encoding="utf-8") == "converted"

    sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report.pdf", b"pdf-bytes")
    sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report.md", b"converted")


def test_upload_files_makes_non_local_files_sandbox_writable(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "aio-1"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    async def fake_convert(file_path: Path) -> Path:
        md_path = file_path.with_suffix(".md")
        md_path.write_text("converted", encoding="utf-8")
        return md_path

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "convert_file_to_markdown", AsyncMock(side_effect=fake_convert)),
        patch.object(uploads, "_make_file_sandbox_writable") as make_writable,
    ):
        file = UploadFile(filename="report.pdf", file=BytesIO(b"pdf-bytes"))
        result = asyncio.run(uploads.upload_files("thread-aio", files=[file]))

    assert result.success is True
    make_writable.assert_any_call(thread_uploads_dir / "report.pdf")
    make_writable.assert_any_call(thread_uploads_dir / "report.md")


def test_upload_files_does_not_adjust_permissions_for_local_sandbox(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "local"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "_make_file_sandbox_writable") as make_writable,
    ):
        file = UploadFile(filename="notes.txt", file=BytesIO(b"hello uploads"))
        result = asyncio.run(uploads.upload_files("thread-local", files=[file]))

    assert result.success is True
    make_writable.assert_not_called()


def test_upload_files_returns_extracted_images_for_docx_and_syncs_them_to_sandbox(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "aio-1"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    async def fake_convert(file_path: Path) -> Path:
        md_path = file_path.with_suffix(".md")
        md_path.write_text("converted", encoding="utf-8")
        return md_path

    async def fake_extract(file_path: Path) -> list[Path]:
        image1 = file_path.with_name("report__image1.png")
        image1.write_bytes(b"png")
        image2 = file_path.with_name("report__image2.jpeg")
        image2.write_bytes(b"jpeg")
        return [image1, image2]

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "convert_file_to_markdown", AsyncMock(side_effect=fake_convert)),
        patch.object(uploads, "extract_docx_images", AsyncMock(side_effect=fake_extract)),
    ):
        file = UploadFile(filename="report.docx", file=BytesIO(b"docx-bytes"))
        result = asyncio.run(uploads.upload_files("thread-aio", files=[file]))

    assert result.success is True
    file_info = _file_dict(result)
    assert file_info["filename"] == "report.docx"
    assert file_info["markdown_file"] == "report.md"
    assert [img["filename"] for img in file_info["extracted_images"]] == [
        "report__image1.png",
        "report__image2.jpeg",
    ]
    assert file_info["extracted_images"][0]["virtual_path"] == "/mnt/user-data/uploads/report__image1.png"

    sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report.docx", b"docx-bytes")
    sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report.md", b"converted")
    sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report__image1.png", b"png")
    sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report__image2.jpeg", b"jpeg")


def test_upload_files_rewrites_docx_markdown_and_resyncs_sandbox_when_rewrite_succeeds(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "aio-1"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    async def fake_convert(file_path: Path) -> Path:
        md_path = file_path.with_suffix(".md")
        md_path.write_text("converted", encoding="utf-8")
        return md_path

    async def fake_extract(file_path: Path) -> list[Path]:
        image = file_path.with_name("report__image1.png")
        image.write_bytes(b"png")
        return [image]

    def fake_rewrite(md_path: Path, extracted_image_paths: list[Path]) -> bool:
        md_path.write_text("rewritten", encoding="utf-8")
        return True

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "convert_file_to_markdown", AsyncMock(side_effect=fake_convert)),
        patch.object(uploads, "extract_docx_images", AsyncMock(side_effect=fake_extract)),
        patch.object(uploads, "rewrite_docx_markdown_image_links", side_effect=fake_rewrite) as rewrite,
    ):
        file = UploadFile(filename="report.docx", file=BytesIO(b"docx-bytes"))
        result = asyncio.run(uploads.upload_files("thread-aio", files=[file]))

    assert result.success is True
    rewrite.assert_called_once()
    assert (thread_uploads_dir / "report.md").read_text(encoding="utf-8") == "rewritten"
    sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report.md", b"rewritten")


def test_upload_files_keeps_original_markdown_when_docx_rewrite_fails_open(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "local"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    async def fake_convert(file_path: Path) -> Path:
        md_path = file_path.with_suffix(".md")
        md_path.write_text("converted", encoding="utf-8")
        return md_path

    async def fake_extract(file_path: Path) -> list[Path]:
        image = file_path.with_name("report__image1.png")
        image.write_bytes(b"png")
        return [image]

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "convert_file_to_markdown", AsyncMock(side_effect=fake_convert)),
        patch.object(uploads, "extract_docx_images", AsyncMock(side_effect=fake_extract)),
        patch.object(uploads, "rewrite_docx_markdown_image_links", return_value=False) as rewrite,
    ):
        file = UploadFile(filename="report.docx", file=BytesIO(b"docx-bytes"))
        result = asyncio.run(uploads.upload_files("thread-local", files=[file]))

    assert result.success is True
    rewrite.assert_called_once()
    assert (thread_uploads_dir / "report.md").read_text(encoding="utf-8") == "converted"


def test_upload_files_replaces_existing_docx_sidecars(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    source = thread_uploads_dir / "report.docx"
    source.write_bytes(b"old-docx")
    old_image = thread_uploads_dir / "report__image1.png"
    old_image.write_bytes(b"old-png")
    stale_image = thread_uploads_dir / "report__image2.jpeg"
    stale_image.write_bytes(b"stale-jpeg")
    write_docx_sidecar_manifest(source, [old_image, stale_image])

    provider = MagicMock()
    provider.acquire.return_value = "local"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    async def fake_convert(file_path: Path) -> Path:
        md_path = file_path.with_suffix(".md")
        md_path.write_text("converted", encoding="utf-8")
        return md_path

    async def fake_extract(file_path: Path) -> list[Path]:
        image = file_path.with_name("report__image1.png")
        image.write_bytes(b"new-png")
        return [image]

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "convert_file_to_markdown", AsyncMock(side_effect=fake_convert)),
        patch.object(uploads, "extract_docx_images", AsyncMock(side_effect=fake_extract)),
    ):
        file = UploadFile(filename="report.docx", file=BytesIO(b"new-docx"))
        result = asyncio.run(uploads.upload_files("thread-local", files=[file]))

    assert result.success is True
    assert (thread_uploads_dir / "report__image1.png").read_bytes() == b"new-png"
    assert not stale_image.exists()
    manifest_data = json.loads((thread_uploads_dir / "report.docx.docx.images.json").read_text(encoding="utf-8"))
    assert manifest_data["image_filenames"] == ["report__image1.png"]


def test_make_file_sandbox_writable_adds_write_bits_for_regular_files(tmp_path):
    file_path = tmp_path / "report.pdf"
    file_path.write_bytes(b"pdf-bytes")
    os_chmod_mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    file_path.chmod(os_chmod_mode)

    uploads._make_file_sandbox_writable(file_path)

    updated_mode = stat.S_IMODE(file_path.stat().st_mode)
    assert updated_mode & stat.S_IWUSR
    assert updated_mode & stat.S_IWGRP
    assert updated_mode & stat.S_IWOTH


def test_make_file_sandbox_writable_skips_symlinks(tmp_path):
    file_path = tmp_path / "target-link.txt"
    file_path.write_text("hello", encoding="utf-8")
    symlink_stat = MagicMock(st_mode=stat.S_IFLNK)

    with (
        patch.object(uploads.os, "lstat", return_value=symlink_stat),
        patch.object(uploads.os, "chmod") as chmod,
    ):
        uploads._make_file_sandbox_writable(file_path)

    chmod.assert_not_called()


def test_upload_files_rejects_dotdot_and_dot_filenames(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "local"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        # These filenames must be rejected outright
        for bad_name in ["..", "."]:
            file = UploadFile(filename=bad_name, file=BytesIO(b"data"))
            result = asyncio.run(uploads.upload_files("thread-local", files=[file]))
            assert result.success is True
            assert result.files == [], f"Expected no files for unsafe filename {bad_name!r}"

        # Path-traversal prefixes are stripped to the basename and accepted safely
        file = UploadFile(filename="../etc/passwd", file=BytesIO(b"data"))
        result = asyncio.run(uploads.upload_files("thread-local", files=[file]))
        assert result.success is True
        assert len(result.files) == 1
        assert _file_dict(result)["filename"] == "passwd"

    # Only the safely normalised file should exist
    assert [f.name for f in thread_uploads_dir.iterdir()] == ["passwd"]


def test_delete_uploaded_file_removes_generated_markdown_companion(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    (thread_uploads_dir / "report.pdf").write_bytes(b"pdf-bytes")
    (thread_uploads_dir / "report.md").write_text("converted", encoding="utf-8")

    with patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir):
        result = asyncio.run(uploads.delete_uploaded_file("thread-aio", "report.pdf"))

    assert result == {"success": True, "message": "Deleted report.pdf"}
    assert not (thread_uploads_dir / "report.pdf").exists()
    assert not (thread_uploads_dir / "report.md").exists()


def test_list_uploaded_files_groups_docx_sidecars_under_source_file(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    source = thread_uploads_dir / "report.docx"
    source.write_bytes(b"docx")
    (thread_uploads_dir / "report.md").write_text("converted", encoding="utf-8")
    image = thread_uploads_dir / "report__image1.png"
    image.write_bytes(b"png")
    write_docx_sidecar_manifest(source, [image])

    with patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir):
        result = asyncio.run(uploads.list_uploaded_files("thread-aio"))

    filenames = [f["filename"] for f in result["files"]]
    assert filenames == ["report.docx", "report.md"]
    assert [img["filename"] for img in result["files"][0]["extracted_images"]] == ["report__image1.png"]
    assert result["files"][0]["extracted_images"][0]["virtual_path"] == "/mnt/user-data/uploads/report__image1.png"


def test_list_uploaded_files_keeps_untracked_matching_png_as_standalone_file(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    (thread_uploads_dir / "report.docx").write_bytes(b"docx")
    (thread_uploads_dir / "report__image1.png").write_bytes(b"png")

    with patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir):
        result = asyncio.run(uploads.list_uploaded_files("thread-aio"))

    assert [f["filename"] for f in result["files"]] == ["report.docx", "report__image1.png"]

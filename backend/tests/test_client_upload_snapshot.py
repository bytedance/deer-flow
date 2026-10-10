"""Embedded upload and conversion must consume the same captured bytes."""

import asyncio
import os
import shutil
import stat
from pathlib import Path

import pytest

from deerflow.client import DeerFlowClient
from deerflow.uploads.companions import resolve_companion


@pytest.fixture
def upload_case(monkeypatch, tmp_path):
    import deerflow.client as client_module

    uploads = tmp_path / "thread/user-data/uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(client_module, "ensure_uploads_dir", lambda *args, **kwargs: uploads)
    # upload_files has no dependency on initialized instance fields.
    return DeerFlowClient.__new__(DeerFlowClient), uploads


def call_upload(client, source, in_loop):
    if not in_loop:
        return client.upload_files("snapshot-thread", [source])

    async def call():
        return client.upload_files("snapshot-thread", [source])

    return asyncio.run(call())


@pytest.mark.parametrize("in_loop", [False, True])
@pytest.mark.parametrize("change", ["edit", "remove"])
def test_conversion_keeps_uploaded_version(upload_case, monkeypatch, tmp_path, in_loop, change):
    import deerflow.client as client_module
    import deerflow.utils.file_conversion as conversion

    client, uploads = upload_case
    source = tmp_path / "report.pdf"
    source.write_bytes(b"VERSION A")
    real_copy = client_module.copy_upload_file_no_symlink
    conversion_paths = []

    def copy_then_change(base, name, src, **kwargs):
        result = real_copy(base, name, src, **kwargs)
        if Path(src) == source:
            if change == "edit":
                source.write_bytes(b"VERSION B")
            else:
                source.unlink()
        return result

    async def convert(path, output_path=None):
        conversion_paths.append(path)
        output_path.write_bytes(b"CONVERTED:" + path.read_bytes())
        return output_path

    monkeypatch.setattr(client_module, "copy_upload_file_no_symlink", copy_then_change)
    monkeypatch.setattr(conversion, "CONVERTIBLE_EXTENSIONS", {".pdf"})
    monkeypatch.setattr(conversion, "convert_file_to_markdown", convert)
    response = call_upload(client, source, in_loop)

    assert response["success"]
    saved = uploads / response["files"][0]["filename"]
    assert saved.read_bytes() == b"VERSION A"
    companion = resolve_companion(saved)
    assert companion is not None
    assert companion.read_bytes() == b"CONVERTED:VERSION A"
    assert conversion_paths[0].name == source.name
    assert conversion_paths[0] != source
    assert not conversion_paths[0].is_relative_to(uploads)
    assert not conversion_paths[0].parent.exists()


@pytest.mark.parametrize("in_loop", [False, True])
def test_failed_conversion_keeps_original_and_cleans_snapshot(upload_case, monkeypatch, tmp_path, in_loop):
    import deerflow.utils.file_conversion as conversion

    client, uploads = upload_case
    source = tmp_path / "report.pdf"
    source.write_bytes(b"VERSION A")
    paths = []

    async def fail(path, output_path=None):
        paths.append(path)
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(conversion, "CONVERTIBLE_EXTENSIONS", {".pdf"})
    monkeypatch.setattr(conversion, "convert_file_to_markdown", fail)
    response = call_upload(client, source, in_loop)
    assert response["success"]
    assert "markdown_file" not in response["files"][0]
    assert (uploads / "report.pdf").read_bytes() == b"VERSION A"
    assert source.read_bytes() == b"VERSION A"
    assert paths[0] != source
    assert not paths[0].parent.exists()


def test_convertible_same_file_is_rejected_without_data_loss(upload_case):
    client, uploads = upload_case
    source = uploads / "report.pdf"
    source.write_bytes(b"IMPORTANT BYTES")
    with pytest.raises(shutil.SameFileError):
        client.upload_files("snapshot-thread", [source])
    assert source.read_bytes() == b"IMPORTANT BYTES"


def test_captured_upload_preserves_original_metadata(upload_case, monkeypatch, tmp_path):
    import deerflow.utils.file_conversion as conversion

    client, uploads = upload_case
    source = tmp_path / "report.pdf"
    source.write_bytes(b"VERSION A")
    source.chmod(0o640)
    os.utime(source, ns=(1_700_000_000_000_000_000, 1_700_000_001_000_000_000))
    before = source.stat()

    async def convert(path, output_path=None):
        output_path.write_bytes(path.read_bytes())
        return output_path

    monkeypatch.setattr(conversion, "CONVERTIBLE_EXTENSIONS", {".pdf"})
    monkeypatch.setattr(conversion, "convert_file_to_markdown", convert)
    client.upload_files("snapshot-thread", [source])
    saved = (uploads / "report.pdf").stat()
    if os.chmod in os.supports_fd:
        assert stat.S_IMODE(saved.st_mode) == stat.S_IMODE(before.st_mode)
    if os.utime in os.supports_fd:
        assert saved.st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("in_loop", [False, True])
def test_real_xlsx_conversion_uses_captured_version(upload_case, monkeypatch, tmp_path, in_loop):
    from openpyxl import Workbook, load_workbook

    import deerflow.client as client_module

    client, uploads = upload_case
    source = tmp_path / "report.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "VERSION A"
    workbook.save(source)
    real_copy = client_module.copy_upload_file_no_symlink

    def copy_then_save(base, name, src, **kwargs):
        result = real_copy(base, name, src, **kwargs)
        if Path(src) == source:
            workbook.active["A1"] = "VERSION B"
            workbook.save(source)
        return result

    monkeypatch.setattr(client_module, "copy_upload_file_no_symlink", copy_then_save)
    response = call_upload(client, source, in_loop)
    assert response["success"]
    saved = uploads / "report.xlsx"
    saved_workbook = load_workbook(saved)
    try:
        assert saved_workbook.active["A1"].value == "VERSION A"
    finally:
        saved_workbook.close()
        workbook.close()
    companion = resolve_companion(saved)
    assert companion is not None
    text = companion.read_text(encoding="utf-8")
    assert "VERSION A" in text
    assert "VERSION B" not in text


def test_capture_failure_preserves_existing_upload(upload_case, monkeypatch, tmp_path):
    import deerflow.uploads.manager as manager

    client, uploads = upload_case
    source = tmp_path / "report.pdf"
    source.write_bytes(b"NEW CONTENT")
    existing = uploads / "report.pdf"
    existing.write_bytes(b"EXISTING CONTENT")
    captures = []

    def fail_capture(src, dest):
        captures.append(Path(dest.name))
        raise OSError("snapshot disk full")

    monkeypatch.setattr(manager.shutil, "copyfileobj", fail_capture)
    with pytest.raises(OSError, match="snapshot disk full"):
        client.upload_files("snapshot-thread", [source])
    assert existing.read_bytes() == b"EXISTING CONTENT"
    assert source.read_bytes() == b"NEW CONTENT"
    assert not captures[0].parent.exists()

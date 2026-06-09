"""Unit tests for scripts/batch_convert.py routing logic."""
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import batch_convert  # noqa: E402


def test_convert_file_routes_image_to_mineru(mineru_env, tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"fake-jpg-bytes")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with mock.patch.object(batch_convert.mineru_client, "ocr_to_markdown", return_value="# OCR result") as ocr:
        with mock.patch.object(batch_convert, "MarkItDown") as md_cls:
            ok, _, msg = batch_convert.convert_file(img, out_dir, verbose=False)

    assert ok is True
    assert "Converted" in msg
    ocr.assert_called_once_with(str(img))
    md_cls.assert_not_called()

    out = out_dir / "photo.md"
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "# photo" in content
    assert "**Source**: photo.jpg" in content
    assert "# OCR result" in content


def test_convert_file_routes_text_pdf_to_markitdown(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    fake_result = mock.Mock()
    fake_result.text_content = "Long enough PDF body " * 20  # > 50 chars

    fake_md_instance = mock.Mock()
    fake_md_instance.convert.return_value = fake_result

    with mock.patch.object(batch_convert, "MarkItDown", return_value=fake_md_instance) as md_cls:
        with mock.patch.object(batch_convert.mineru_client, "ocr_to_markdown") as ocr:
            ok, _, _ = batch_convert.convert_file(pdf, out_dir, verbose=False)

    assert ok is True
    md_cls.assert_called_once_with()
    fake_md_instance.convert.assert_called_once_with(str(pdf))
    ocr.assert_not_called()


def test_convert_file_falls_back_to_mineru_for_scanned_pdf(tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    fake_result = mock.Mock()
    fake_result.text_content = "x"  # < 50 chars -> scanned

    fake_md_instance = mock.Mock()
    fake_md_instance.convert.return_value = fake_result

    with mock.patch.object(batch_convert, "MarkItDown", return_value=fake_md_instance):
        with mock.patch.object(batch_convert.mineru_client, "ocr_to_markdown", return_value="# OCR scan") as ocr:
            ok, _, _ = batch_convert.convert_file(pdf, out_dir, verbose=False)

    assert ok is True
    ocr.assert_called_once_with(str(pdf))


def test_convert_file_skips_missing_path(tmp_path, capsys):
    missing = tmp_path / "ghost.pdf"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    ok, _, msg = batch_convert.convert_file(missing, out_dir, verbose=False)

    assert ok is False
    assert "Skipping" in msg
    captured = capsys.readouterr()
    assert "ghost.pdf" in captured.out


def test_convert_file_continues_on_markitdown_exception(tmp_path):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"x")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    fake_md_instance = mock.Mock()
    fake_md_instance.convert.side_effect = RuntimeError("markitdown blew up")

    with mock.patch.object(batch_convert, "MarkItDown", return_value=fake_md_instance):
        ok, _, msg = batch_convert.convert_file(pdf, out_dir, verbose=False)

    assert ok is False
    assert "Error" in msg
    placeholder = out_dir / "broken.md"
    assert placeholder.exists()
    assert "markitdown blew up" in placeholder.read_text(encoding="utf-8")


def test_convert_file_echoes_content_to_stdout(mineru_env, tmp_path, capsys):
    """On success, the full MD body is printed so it surfaces in the chat UI
    (matches the data-analysis `print(result)` pattern at scripts/analyze.py)."""
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"fake-jpg-bytes")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with mock.patch.object(
        batch_convert.mineru_client, "ocr_to_markdown", return_value="# OCR result"
    ):
        ok, _, _ = batch_convert.convert_file(img, out_dir, verbose=False)

    assert ok is True
    captured = capsys.readouterr()
    assert "# photo" in captured.out
    assert "**Source**: photo.jpg" in captured.out
    assert "# OCR result" in captured.out

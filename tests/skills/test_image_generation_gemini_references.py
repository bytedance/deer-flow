"""Verify content-based reference MIME metadata in the Gemini image path."""

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

img = load("image-generation")

from PIL import Image  # noqa: E402


def _gemini_scaffold(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-test-key")
    captured = {"posts": []}
    generated = b"offline-image-bytes"

    def fake_post(url, headers=None, json=None, **kwargs):
        captured["posts"].append(json)
        return FakeResp(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "data": base64.b64encode(generated).decode()
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(img.requests, "post", fake_post)
    return captured, generated


def _real_image(tmp_path, filename, fmt):
    reference = tmp_path / filename
    Image.new("RGB", (2, 2), "red").save(reference, format=fmt)
    return str(reference)


def _inline_parts(request):
    return request["contents"][0]["parts"]


def test_gemini_labels_references_from_content(monkeypatch, tmp_path):
    """Real Pillow-created images are labeled by their actual format."""
    captured, generated = _gemini_scaffold(monkeypatch, tmp_path)
    prompt = tmp_path / "prompt.json"
    prompt.write_text("use the reference", encoding="utf-8")
    png = _real_image(tmp_path, "reference.png", "PNG")
    output = tmp_path / "output.png"

    msg = img.generate_image(str(prompt), [png], str(output))

    assert "Successfully" in msg
    assert output.read_bytes() == generated
    parts = _inline_parts(captured["posts"][0])
    assert len(parts) == 2
    inline = parts[0]["inlineData"]
    assert inline["mimeType"] == "image/png"


def test_gemini_jpeg_control_still_labeled_jpeg(monkeypatch, tmp_path):
    captured, _ = _gemini_scaffold(monkeypatch, tmp_path)
    prompt = tmp_path / "prompt.json"
    prompt.write_text("use the reference", encoding="utf-8")
    jpeg = _real_image(tmp_path, "reference.jpg", "JPEG")

    img.generate_image(str(prompt), [jpeg], str(tmp_path / "output.png"))

    inline = _inline_parts(captured["posts"][0])[0]["inlineData"]
    assert inline["mimeType"] == "image/jpeg"


def test_gemini_misleading_extension_uses_content(monkeypatch, tmp_path):
    """A PNG payload stored under a .jpg name is still labeled image/png."""
    captured, _ = _gemini_scaffold(monkeypatch, tmp_path)
    prompt = tmp_path / "prompt.json"
    prompt.write_text("use the reference", encoding="utf-8")
    png = _real_image(tmp_path, "photo.jpg", "PNG")

    img.generate_image(str(prompt), [png], str(tmp_path / "output.png"))

    inline = _inline_parts(captured["posts"][0])[0]["inlineData"]
    assert inline["mimeType"] == "image/png"


def test_gemini_missing_extension_uses_content(monkeypatch, tmp_path):
    captured, _ = _gemini_scaffold(monkeypatch, tmp_path)
    prompt = tmp_path / "prompt.json"
    prompt.write_text("use the reference", encoding="utf-8")
    webp = _real_image(tmp_path, "reference", "WEBP")

    img.generate_image(str(prompt), [webp], str(tmp_path / "output.png"))

    inline = _inline_parts(captured["posts"][0])[0]["inlineData"]
    assert inline["mimeType"] == "image/webp"


def test_gemini_preserves_reference_order_and_bytes(monkeypatch, tmp_path):
    captured, _ = _gemini_scaffold(monkeypatch, tmp_path)
    prompt = tmp_path / "prompt.json"
    prompt.write_text("use the references", encoding="utf-8")
    jpeg = _real_image(tmp_path, "first.jpg", "JPEG")
    gif = _real_image(tmp_path, "second.gif", "GIF")

    img.generate_image(str(prompt), [jpeg, gif], str(tmp_path / "output.png"))

    parts = _inline_parts(captured["posts"][0])
    first = parts[0]["inlineData"]
    second = parts[1]["inlineData"]
    assert first["mimeType"] == "image/jpeg"
    assert second["mimeType"] == "image/gif"
    assert base64.b64decode(first["data"]) == Path(jpeg).read_bytes()
    assert base64.b64decode(second["data"]) == Path(gif).read_bytes()
    assert parts[2]["text"] == "use the references"


def test_gemini_skips_corrupt_references(monkeypatch, tmp_path):
    captured, _ = _gemini_scaffold(monkeypatch, tmp_path)
    prompt = tmp_path / "prompt.json"
    prompt.write_text("use the reference", encoding="utf-8")
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"definitely-not-an-image")
    good = _real_image(tmp_path, "good.png", "PNG")

    msg = img.generate_image(
        str(prompt), [str(corrupt), good], str(tmp_path / "output.png")
    )

    assert "Successfully" in msg
    parts = _inline_parts(captured["posts"][0])
    assert len(parts) == 2  # one inlineData + the text part
    assert parts[0]["inlineData"]["mimeType"] == "image/png"


def test_gemini_bmp_reference_labeled_by_content(monkeypatch, tmp_path):
    """A BMP payload stored under a .jpg name is labeled image/bmp, not image/jpeg."""
    captured, _ = _gemini_scaffold(monkeypatch, tmp_path)
    prompt = tmp_path / "prompt.json"
    prompt.write_text("use the reference", encoding="utf-8")
    bmp = _real_image(tmp_path, "photo.jpg", "BMP")

    img.generate_image(str(prompt), [bmp], str(tmp_path / "output.png"))

    inline = _inline_parts(captured["posts"][0])[0]["inlineData"]
    assert inline["mimeType"] == "image/bmp"


def test_gemini_tiff_reference_labeled_by_content(monkeypatch, tmp_path):
    """A TIFF payload stored under a .jpg name is labeled image/tiff, not image/jpeg."""
    captured, _ = _gemini_scaffold(monkeypatch, tmp_path)
    prompt = tmp_path / "prompt.json"
    prompt.write_text("use the reference", encoding="utf-8")
    tiff = _real_image(tmp_path, "photo.jpg", "TIFF")

    img.generate_image(str(prompt), [tiff], str(tmp_path / "output.png"))

    inline = _inline_parts(captured["posts"][0])[0]["inlineData"]
    assert inline["mimeType"] == "image/tiff"


class _BlockPIL:
    """Import finder that makes Pillow look unavailable."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PIL" or fullname.startswith("PIL."):
            raise ImportError(f"Pillow blocked for this test: {fullname}")
        return None


def test_gemini_reference_free_generation_without_pillow(monkeypatch, tmp_path):
    """A reference-free generation keeps working when Pillow is unavailable."""
    import sys

    captured, _ = _gemini_scaffold(monkeypatch, tmp_path)
    # Purge cached PIL modules so the meta_path blocker actually intercepts:
    # a meta_path finder is only consulted on cache misses, and PIL is already
    # imported by this test module, so without the purge the block never fires.
    for name in [n for n in sys.modules if n == "PIL" or n.startswith("PIL.")]:
        monkeypatch.delitem(sys.modules, name)
    blocker = _BlockPIL()
    monkeypatch.setattr(sys, "meta_path", [blocker, *sys.meta_path])
    prompt = tmp_path / "prompt.json"
    prompt.write_text("a red apple", encoding="utf-8")

    msg = img.generate_image(str(prompt), [], str(tmp_path / "output.png"))

    assert "Successfully" in msg
    parts = _inline_parts(captured["posts"][0])
    assert len(parts) == 1
    assert parts[0]["text"] == "a red apple"

"""Verify reference-image metadata at the Gemini HTTP boundary."""

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

vid = load("video-generation")


@pytest.mark.parametrize(
    "images",
    [
        pytest.param([("reference.png", b"\x89PNG\r\n\x1a\nreference", "image/png")], id="png"),
        pytest.param([("reference.PNG", b"\x89PNG\r\n\x1a\nreference", "image/png")], id="uppercase-png"),
        pytest.param([("reference.jpg", b"\xff\xd8\xffreference", "image/jpeg")], id="jpg"),
        pytest.param([("reference.jpeg", b"\xff\xd8\xffreference", "image/jpeg")], id="jpeg"),
        pytest.param(
            [
                ("first.jpg", b"\xff\xd8\xfffirst", "image/jpeg"),
                ("second.png", b"\x89PNG\r\n\x1a\nsecond", "image/png"),
            ],
            id="mixed-references",
        ),
    ],
)
def test_gemini_preserves_reference_image_mime(monkeypatch, tmp_path, images):
    monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-test-key")
    prompt = tmp_path / "prompt.json"
    prompt.write_text("a cat runs", encoding="utf-8")
    reference_paths = []
    for filename, image_bytes, _ in images:
        reference = tmp_path / filename
        reference.write_bytes(image_bytes)
        reference_paths.append(str(reference))
    output = tmp_path / "video.mp4"
    captured = {}

    def fake_post(url, *, json, **kwargs):
        captured["request"] = json
        return FakeResp({"name": "operations/offline-test"})

    def fake_get(url, **kwargs):
        if url.endswith("/operations/offline-test"):
            return FakeResp(
                {
                    "done": True,
                    "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": "https://example.test/video.mp4"}}]}},
                }
            )
        assert url == "https://example.test/video.mp4"
        return FakeResp(content=b"offline-video-bytes")

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)

    result = vid.generate_video(str(prompt), reference_paths, str(output))

    references = captured["request"]["instances"][0]["referenceImages"]
    assert len(references) == len(images)
    for reference, (_, image_bytes, expected_mime) in zip(references, images, strict=True):
        assert reference["referenceType"] == "asset"
        assert reference["image"]["mimeType"] == expected_mime
        assert base64.b64decode(reference["image"]["bytesBase64Encoded"]) == image_bytes
    assert output.read_bytes() == b"offline-video-bytes"
    assert "successfully" in result

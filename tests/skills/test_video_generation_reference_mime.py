"""Verify extension-based reference metadata at offline provider boundaries."""

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

vid = load("video-generation")


def _mock_provider(monkeypatch, provider):
    monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", provider)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-test-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "offline-test-key")
    monkeypatch.setenv("MINIMAX_API_HOST", "https://api.example.test")
    captured = {"posts": [], "gets": []}

    def fake_post(url, *, json, **kwargs):
        captured["posts"].append(json)
        if provider == "gemini":
            return FakeResp({"name": "operations/offline-test"})
        return FakeResp({"task_id": "offline-task", "base_resp": {"status_code": 0}})

    def fake_get(url, **kwargs):
        captured["gets"].append(url)
        if url.endswith("/operations/offline-test"):
            return FakeResp({"done": True, "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": "https://example.test/video.mp4"}}]}}})
        if url.endswith("/v1/query/video_generation"):
            return FakeResp({"status": "Success", "file_id": "offline-file", "base_resp": {"status_code": 0}})
        if url.endswith("/v1/files/retrieve"):
            return FakeResp({"file": {"download_url": "https://example.test/video.mp4"}, "base_resp": {"status_code": 0}})
        assert url == "https://example.test/video.mp4"
        return FakeResp(content=b"offline-video-bytes")

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    return captured


@pytest.mark.parametrize("provider", ["gemini", "minimax"])
@pytest.mark.parametrize(
    "images",
    [
        pytest.param([("reference.png", b"\x89PNG\r\n\x1a\nreference", "image/png")], id="png"),
        pytest.param([("reference.PNG", b"\x89PNG\r\n\x1a\nreference", "image/png")], id="uppercase-png"),
        pytest.param([("reference.jpg", b"\xff\xd8\xffreference", "image/jpeg")], id="jpg"),
        pytest.param([("reference.jpeg", b"\xff\xd8\xffreference", "image/jpeg")], id="jpeg"),
        pytest.param([("reference.JPG", b"\xff\xd8\xffreference", "image/jpeg")], id="uppercase-jpg"),
        pytest.param([("reference.webp", b"RIFF\x00\x00\x00\x00WEBPreference", "image/webp")], id="webp"),
        pytest.param([("reference.WEBP", b"RIFF\x00\x00\x00\x00WEBPreference", "image/webp")], id="uppercase-webp"),
        pytest.param([("reference.gif", b"GIF89areference", "image/gif")], id="gif"),
        pytest.param([("reference.GIF", b"GIF89areference", "image/gif")], id="uppercase-gif"),
        pytest.param(
            [
                ("first.jpg", b"\xff\xd8\xfffirst", "image/jpeg"),
                ("second.png", b"\x89PNG\r\n\x1a\nsecond", "image/png"),
            ],
            id="mixed-references",
        ),
    ],
)
def test_provider_preserves_reference_image_mime(monkeypatch, tmp_path, provider, images):
    captured = _mock_provider(monkeypatch, provider)
    prompt = tmp_path / "prompt.json"
    prompt.write_text("a cat runs", encoding="utf-8")
    reference_paths = []
    for filename, image_bytes, _ in images:
        reference = tmp_path / filename
        reference.write_bytes(image_bytes)
        reference_paths.append(str(reference))
    output = tmp_path / "video.mp4"

    result = vid.generate_video(str(prompt), reference_paths, str(output))

    assert len(captured["posts"]) == 1
    request = captured["posts"][0]
    if provider == "gemini":
        references = request["instances"][0]["referenceImages"]
        assert len(references) == len(images)
        for reference, (_, image_bytes, expected_mime) in zip(references, images, strict=True):
            assert reference["referenceType"] == "asset"
            assert reference["image"]["mimeType"] == expected_mime
            assert base64.b64decode(reference["image"]["bytesBase64Encoded"]) == image_bytes
    else:
        # MiniMax uses only the first reference, as documented by the skill.
        prefix, encoded = request["first_frame_image"].split(",", 1)
        assert prefix == f"data:{images[0][2]};base64"
        assert base64.b64decode(encoded) == images[0][1]
    assert output.read_bytes() == b"offline-video-bytes"
    assert "successfully" in result


@pytest.mark.parametrize("provider", ["gemini", "minimax"])
@pytest.mark.parametrize("filename", ["reference", "reference.bmp", "reference.BMP", "reference.avif"])
def test_unsupported_reference_extension_rejected_before_submission(monkeypatch, tmp_path, provider, filename):
    captured = _mock_provider(monkeypatch, provider)
    prompt = tmp_path / "prompt.json"
    prompt.write_text("a cat runs", encoding="utf-8")
    reference = tmp_path / filename
    reference.write_bytes(b"unsupported-image-bytes")
    output = tmp_path / "video.mp4"

    with pytest.raises(ValueError) as caught:
        vid.generate_video(str(prompt), [str(reference)], str(output))

    message = str(caught.value)
    assert reference.name in message
    for extension in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        assert extension in message
    assert captured == {"posts": [], "gets": []}
    assert not output.exists()


def test_gemini_rejects_later_unsupported_reference_before_submission(monkeypatch, tmp_path):
    captured = _mock_provider(monkeypatch, "gemini")
    prompt = tmp_path / "prompt.json"
    prompt.write_text("a cat runs", encoding="utf-8")
    first = tmp_path / "first.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\nfirst")
    unsupported = tmp_path / "second.bmp"
    unsupported.write_bytes(b"unsupported-image-bytes")
    output = tmp_path / "video.mp4"

    with pytest.raises(ValueError, match="second.bmp"):
        vid.generate_video(str(prompt), [str(first), str(unsupported)], str(output))

    assert captured == {"posts": [], "gets": []}
    assert not output.exists()

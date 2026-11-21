"""Provider decode failures must not erase a previous image or create an artifact."""

import base64
import binascii
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load

image = load("image-generation")
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC"
)


def _response(provider, encoded):
    if provider == "gemini":
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"inlineData": {"mimeType": "image/png", "data": encoded}}
                        ]
                    }
                }
            ]
        }
    return {"data": [{"b64_json": encoded}]}


def _generate(monkeypatch, tmp_path, provider, encoded, output):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", provider)
    for key in ("MINIMAX_API_KEY", "GEMINI_API_KEY", "IMAGE_GENERATION_API_KEY"):
        monkeypatch.setenv(key, "offline-fixture")
    monkeypatch.setenv("IMAGE_GENERATION_MODEL", "gpt-image-1")
    monkeypatch.setattr(
        image.requests,
        "post",
        lambda *args, **kwargs: FakeResp(_response(provider, encoded)),
    )
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("a blue square", encoding="utf-8")
    return image.generate_image(str(prompt), [], str(output))


@pytest.mark.parametrize("provider", ["gemini", "openai"])
@pytest.mark.parametrize(
    "existing", [False, True], ids=["new-output", "existing-output"]
)
@pytest.mark.parametrize(
    "encoded",
    ["AA", "☃", ["not a string"]],
    ids=["bad-padding", "non-ascii", "wrong-type"],
)
def test_decode_failure_preserves_output(
    monkeypatch, tmp_path, provider, existing, encoded
):
    output = tmp_path / "images" / "result.png"
    if existing:
        output.parent.mkdir()
        output.write_bytes(PNG)

    with pytest.raises((binascii.Error, ValueError, TypeError)):
        _generate(monkeypatch, tmp_path, provider, encoded, output)

    if existing:
        assert output.read_bytes() == PNG
    else:
        assert not output.exists()
        assert not output.parent.exists()


@pytest.mark.parametrize("provider", ["gemini", "openai"])
@pytest.mark.parametrize(
    "existing", [False, True], ids=["new-output", "existing-output"]
)
def test_valid_image_can_be_written_or_replaced(
    monkeypatch, tmp_path, provider, existing
):
    output = tmp_path / "images" / "result.png"
    if existing:
        output.parent.mkdir()
        output.write_bytes(b"previous image")

    result = _generate(
        monkeypatch, tmp_path, provider, base64.b64encode(PNG).decode("ascii"), output
    )

    assert "Successfully generated image" in result
    assert output.read_bytes() == PNG

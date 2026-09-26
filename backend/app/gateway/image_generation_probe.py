"""Bounded, redacted image-provider probes initiated explicitly by an admin."""

import base64
import binascii
import struct
import zlib
from urllib.parse import urlsplit

import httpx

from deerflow.config.image_generation import ImageGenerationProfile, ImageProvider


def _image_data(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    encoded = value.partition(",")[2] if value.startswith("data:image/") else value
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return False
    return data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")) or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")


def _solid_png() -> bytes:
    """A valid 1024 px PNG for reference-image capability checks."""
    width = height = 1024
    row = b"\x00" + b"\x80\xa0\xc0" * width
    image = zlib.compress(row * height)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", image) + chunk(b"IEND", b"")


def _probe_openai(client: httpx.Client, profile: ImageGenerationProfile, key: str, prompt: str, operation: str) -> str:
    base = profile.base_url or "https://api.openai.com/v1"
    fields = {"model": profile.model, "prompt": prompt, "n": 1, "size": profile.size or "1024x1024"}
    if profile.model in {"dall-e-2", "dall-e-3"}:
        fields["response_format"] = "b64_json"
    else:
        fields["output_format"] = "png"
    headers = {"Authorization": f"Bearer {key}"}
    if operation == "generation":
        response = client.post(f"{base}/images/generations", headers=headers, json=fields)
    else:
        response = client.post(
            f"{base}/images/edits",
            headers=headers,
            data=fields,
            files={"image[]": ("reference.png", _solid_png(), "image/png")},
        )
    response.raise_for_status()
    images = response.json().get("data") or []
    if images and isinstance(images[0], dict):
        item = images[0]
        if any(_image_data(item.get(field)) for field in ("b64_json", "image_base64", "base64")):
            return "success"
        url = item.get("url")
        if isinstance(url, str):
            parsed = urlsplit(url)
            if (parsed.scheme in {"http", "https"} and parsed.hostname) or _image_data(url):
                return "success"
    return "invalid_response"


def _probe_gemini(client: httpx.Client, profile: ImageGenerationProfile, key: str, prompt: str, operation: str) -> str:
    parts = [{"text": prompt}]
    if operation == "edit":
        reference = base64.b64encode(_solid_png()).decode("ascii")
        parts.insert(0, {"inlineData": {"mimeType": "image/png", "data": reference}})
    response = client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{profile.model}:generateContent",
        headers={"x-goog-api-key": key},
        json={"contents": [{"parts": parts}], "generationConfig": {"imageConfig": {"aspectRatio": "1:1"}}},
    )
    response.raise_for_status()
    candidates = response.json().get("candidates") or []
    response_parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    if any(_image_data(part.get("inlineData", {}).get("data")) for part in response_parts if isinstance(part, dict)):
        return "success"
    return "invalid_response"


def _probe_minimax(client: httpx.Client, profile: ImageGenerationProfile, key: str, prompt: str, operation: str) -> str:
    body = {
        "model": profile.model,
        "prompt": prompt,
        "aspect_ratio": "1:1",
        "response_format": "base64",
        "n": 1,
        "prompt_optimizer": True,
    }
    if operation == "edit":
        reference = base64.b64encode(_solid_png()).decode("ascii")
        body["subject_reference"] = [{"type": "character", "image_file": "data:image/png;base64," + reference}]
    response = client.post(
        f"{profile.base_url or 'https://api.minimaxi.com'}/v1/image_generation",
        headers={"Authorization": f"Bearer {key}"},
        json=body,
    )
    response.raise_for_status()
    payload = response.json()
    if (payload.get("base_resp") or {}).get("status_code", 0) != 0:
        return "provider_rejected"
    images = (payload.get("data") or {}).get("image_base64") or []
    return "success" if isinstance(images, list) and any(_image_data(item) for item in images) else "invalid_response"


def probe_image_profile(profile: ImageGenerationProfile, operation: str) -> str:
    """Return a stable result code. Provider response bodies never leave here."""
    if operation not in {"generation", "edit"}:
        return "invalid_operation"
    if not profile.usable():
        return "missing_api_key"
    if profile.provider == ImageProvider.OPENAI and operation == "edit" and profile.model in {"dall-e-2", "dall-e-3"}:
        return "unsupported_edit"

    key = profile.api_key.get_secret_value()  # type: ignore[union-attr]
    prompt = "A simple blue square" if operation == "generation" else "Keep this blue square unchanged"
    try:
        with httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0), follow_redirects=False) as client:
            if profile.provider == ImageProvider.OPENAI:
                return _probe_openai(client, profile, key, prompt, operation)
            if profile.provider == ImageProvider.GEMINI:
                return _probe_gemini(client, profile, key, prompt, operation)
            return _probe_minimax(client, profile, key, prompt, operation)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403}:
            return "authentication_failed"
        if exc.response.status_code == 429:
            return "rate_limited"
        if exc.response.status_code in {404, 405, 501} and operation == "edit":
            return "unsupported_edit"
        return "provider_rejected"
    except httpx.HTTPError:
        return "unreachable"
    except (ValueError, KeyError, TypeError, AttributeError):
        return "invalid_response"

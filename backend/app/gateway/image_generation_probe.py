"""Bounded, redacted image-provider probes initiated explicitly by an admin."""

import base64
import binascii
import json
import struct
import zlib
from io import BytesIO
from urllib.parse import urlsplit

import httpx
from PIL import Image

from deerflow.config.image_generation import ImageGenerationProfile, ImageProvider

MAX_PROBE_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_PROBE_IMAGE_PIXELS = 64 * 1024 * 1024


def _read_probe_json(response: httpx.Response) -> dict:
    response.raise_for_status()
    # A compressed chunk can expand beyond the byte budget inside HTTPX.
    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
        raise ValueError("Compressed image probe response")
    chunks = []
    size = 0
    for chunk in response.iter_bytes(chunk_size=64 * 1024):
        size += len(chunk)
        if size > MAX_PROBE_RESPONSE_BYTES:
            raise ValueError("Image probe response limit exceeded")
        chunks.append(chunk)
    payload = json.loads(b"".join(chunks))
    if not isinstance(payload, dict):
        raise ValueError("Invalid image probe response")
    return payload


def _image_data(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    encoded = value.partition(",")[2] if value.startswith("data:image/") else value
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return False
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG", "GIF", "WEBP"} or image.width * image.height > MAX_PROBE_IMAGE_PIXELS:
                return False
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError):
        return False
    return True


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
    headers["Accept-Encoding"] = "identity"
    url = f"{base}/images/{'generations' if operation == 'generation' else 'edits'}"
    request_fields = {"json": fields} if operation == "generation" else {"data": fields, "files": {"image[]": ("reference.png", _solid_png(), "image/png")}}
    with client.stream("POST", url, headers=headers, **request_fields) as response:
        images = _read_probe_json(response).get("data") or []
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
    with client.stream(
        "POST",
        f"https://generativelanguage.googleapis.com/v1beta/models/{profile.model}:generateContent",
        headers={"x-goog-api-key": key, "Accept-Encoding": "identity"},
        json={"contents": [{"parts": parts}], "generationConfig": {"imageConfig": {"aspectRatio": "1:1"}}},
    ) as response:
        candidates = _read_probe_json(response).get("candidates") or []
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
    with client.stream(
        "POST",
        f"{profile.base_url or 'https://api.minimaxi.com'}/v1/image_generation",
        headers={"Authorization": f"Bearer {key}", "Accept-Encoding": "identity"},
        json=body,
    ) as response:
        payload = _read_probe_json(response)
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
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            return "authentication_failed"
        if status_code == 429:
            return "rate_limited"
        if 500 <= status_code < 600:
            return "unreachable"
        if status_code in {404, 405} and operation == "edit":
            return "unsupported_edit"
        return "provider_rejected"
    except httpx.HTTPError:
        return "unreachable"
    except (ValueError, KeyError, TypeError, AttributeError):
        return "invalid_response"

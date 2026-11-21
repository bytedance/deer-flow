import base64
from contextlib import ExitStack
import ipaddress
import json
import os
import re
import sys
from typing import BinaryIO
from urllib.parse import urljoin, urlsplit

import requests

MINIMAX_DEFAULT_HOST = "https://api.minimaxi.com"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
OPENAI_DEFAULT_MODEL = "gpt-image-2.5-flare"
MAX_REDIRECTS = 5
# MiniMax image-01 caps the prompt at 1500 characters and rejects longer requests
# with a generic "invalid params" error, so validate before calling the API.
MINIMAX_PROMPT_MAX_CHARS = 1500


def validate_image(image_path: str) -> bool:
    """Validate if an image file can be opened and is not corrupted."""
    from PIL import Image  # lazy import: keeps module importable without Pillow

    try:
        with Image.open(image_path) as image:
            image.verify()
        with Image.open(image_path) as image:
            image.load()
        return True
    except Exception as exc:
        print(f"Warning: Image '{image_path}' is invalid or corrupted: {exc}")
        return False


def _resolve_provider(
    override_env: str, existing_provider: str, has_existing_creds: bool
) -> str:
    """Pick the generation provider.

    1. Explicit <SKILL>_PROVIDER override wins.
    2. Otherwise prefer the existing provider when its credentials are present.
    3. Otherwise fall back to MiniMax, then the OpenAI-compatible provider.
    """
    override = os.getenv(override_env)
    if override:
        return override.strip().lower()
    if has_existing_creds:
        return existing_provider
    if os.getenv("MINIMAX_API_KEY"):
        return "minimax"
    if os.getenv("IMAGE_GENERATION_API_KEY"):
        return "openai"
    raise ValueError(
        f"No credentials found. Set GEMINI_API_KEY for {existing_provider}, "
        "MINIMAX_API_KEY for minimax, or IMAGE_GENERATION_API_KEY for openai "
        f"(optionally force with {override_env})."
    )


def _minimax_host() -> str:
    return os.getenv("MINIMAX_API_HOST", MINIMAX_DEFAULT_HOST).rstrip("/")


def _openai_base_url() -> str:
    return os.getenv("IMAGE_GENERATION_BASE_URL", OPENAI_DEFAULT_BASE_URL).rstrip("/")


def _openai_size(aspect_ratio: str, model: str) -> str:
    override = os.getenv("IMAGE_GENERATION_SIZE")
    if override:
        allowed_dall_e_sizes = {
            "dall-e-2": {"256x256", "512x512", "1024x1024"},
            "dall-e-3": {"1024x1024", "1792x1024", "1024x1792"},
        }
        allowed = allowed_dall_e_sizes.get(model)
        if allowed is not None and override not in allowed:
            supported = ", ".join(sorted(allowed))
            raise ValueError(f"{model} size must be one of: {supported}")
        return override
    portrait = aspect_ratio in {"9:16", "2:3", "3:4"}
    landscape = aspect_ratio in {"16:9", "3:2", "4:3"}
    if model == "dall-e-2":
        return "1024x1024"
    if model == "dall-e-3":
        if portrait:
            return "1024x1792"
        if landscape:
            return "1792x1024"
        return "1024x1024"
    if portrait:
        return "1024x1536"
    if landscape:
        return "1536x1024"
    return "1024x1024"


def _openai_output_format(output_file: str) -> str:
    extension = os.path.splitext(output_file)[1].lower()
    if extension in {".jpg", ".jpeg"}:
        return "jpeg"
    if extension == ".webp":
        return "webp"
    return "png"


def _check_base_resp(payload: dict) -> None:
    base = payload.get("base_resp") or {}
    if base.get("status_code", 0) != 0:
        raise Exception(
            f"MiniMax error {base.get('status_code')}: {base.get('status_msg')}"
        )


def _guess_mime(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lower()
    return {
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(ext, "image/jpeg")


def _to_data_url(image_path: str) -> str:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{_guess_mime(image_path)};base64,{b64}"


def _ensure_output_dir(output_file: str) -> None:
    """Create the output file's parent directory so nested paths don't fail."""
    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)


def _download_host(url: str) -> str:
    """Validate one provider-supplied image URL before fetching it.

    Accept HTTPS on port 443 with a DNS hostname or a public IPv4 literal.
    Check DNS hostname syntax here and leave DNS resolution to the transport.
    The caller validates each redirect before following it.
    """
    if not isinstance(url, str) or re.search(r"[\x00-\x20\x7f\\]", url):
        raise ValueError("Invalid image download URL")
    parsed = urlsplit(url)
    host = parsed.hostname
    if (
        parsed.scheme != "https"
        or not host
        or parsed.netloc.lower() not in {host, f"{host}:443"}
    ):
        raise ValueError(
            "Image downloads require an HTTPS host on port 443 without user information"
        )
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError:
        if host == "localhost" or not re.fullmatch(
            r"(?:[a-z0-9-]+\.)+[a-z][a-z0-9-]*", host
        ):
            raise ValueError("Invalid image download hostname")
    else:
        if not address.is_global or address.is_multicast:
            raise ValueError(f"Image download host {host!r} is not a public address")
    return host


def _download_image(url: str) -> bytes:
    """Download a provider image URL, validating the target and every redirect."""
    for _ in range(MAX_REDIRECTS + 1):
        _download_host(url)
        response = requests.get(url, timeout=120, allow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = (getattr(response, "headers", None) or {}).get("Location")
            if not location:
                raise ValueError("Image download redirect has no destination")
            url = urljoin(url, location)
            continue
        _require_success(response)
        return response.content
    raise ValueError("Too many image download redirects")


def _require_success(response: requests.Response) -> None:
    response.raise_for_status()
    if not 200 <= response.status_code < 300:
        raise ValueError(
            f"Unexpected HTTP status {response.status_code} from image provider"
        )


def _api_origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Invalid image generation API URL")
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname, port


def _post_image(
    url: str,
    *,
    files: list[tuple[str, tuple[str, BinaryIO, str]]] | None = None,
    **kwargs,
) -> requests.Response:
    """Preserve the POST body and credentials only on same-origin redirects."""
    origin = _api_origin(url)
    for hop in range(MAX_REDIRECTS + 1):
        response = requests.post(url, files=files, allow_redirects=False, **kwargs)
        if response.status_code not in {307, 308}:
            _require_success(response)
            return response
        if hop == MAX_REDIRECTS:
            break
        location = response.headers.get("Location")
        if not location:
            raise ValueError("Image generation redirect has no destination")
        if re.search(r"[\x00-\x20\x7f\\]", location):
            raise ValueError("Invalid image generation redirect destination")
        destination = urljoin(url, location)
        if _api_origin(destination) != origin:
            raise ValueError("Image generation redirect points to a different origin")
        url = destination
        for _, (_, file, _) in files or ():
            file.seek(0)
    raise ValueError("Too many image generation redirects")


def _minimax_prompt(raw: str) -> str:
    """Extract the single text prompt MiniMax image-01 expects.

    The shared prompt file is structured JSON (a consolidated ``prompt`` plus
    Gemini-oriented fields like ``style`` / ``composition`` / ``negative_prompt``),
    but MiniMax consumes one string and expands it via ``prompt_optimizer``. The
    provider adapts the input itself — the caller never needs to know MiniMax is
    active. Use the JSON ``prompt`` field; fall back to the raw text for plain-text
    prompt files or JSON without a ``prompt`` field.
    """
    text = raw.strip()
    try:
        data = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return text
    if isinstance(data, dict):
        core = data.get("prompt")
        if isinstance(core, str) and core.strip():
            return core.strip()
    return text


def _generate_image_minimax(
    prompt: str, reference_images: list[str], output_file: str, aspect_ratio: str
) -> str:
    bearer_value = os.getenv("MINIMAX_API_KEY")
    if not bearer_value:
        return "MINIMAX_API_KEY is not set"
    prompt = _minimax_prompt(prompt)
    if len(prompt) > MINIMAX_PROMPT_MAX_CHARS:
        return (
            f"Prompt is {len(prompt)} characters but MiniMax image-01 accepts at most "
            f"{MINIMAX_PROMPT_MAX_CHARS}. Shorten the prompt to stay within the limit; "
            f"reference images plus a tighter description usually recover the detail."
        )
    body = {
        "model": os.getenv("MINIMAX_IMAGE_MODEL", "image-01"),
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "response_format": "base64",
        "n": 1,
        "prompt_optimizer": True,
    }
    if reference_images:
        # Reference images are passed as character subjects as-is; unlike the Gemini
        # path we do not pre-validate them — invalid files surface as a MiniMax API error.
        body["subject_reference"] = [
            {"type": "character", "image_file": _to_data_url(p)}
            for p in reference_images
        ]
    response = _post_image(
        f"{_minimax_host()}/v1/image_generation",
        headers={
            "Authorization": f"Bearer {bearer_value}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=60,
    )
    payload = response.json()
    _check_base_resp(payload)
    images = (payload.get("data") or {}).get("image_base64") or []
    if not images:
        raise Exception("MiniMax returned no image data")
    _ensure_output_dir(output_file)
    with open(output_file, "wb") as f:
        f.write(base64.b64decode(images[0]))
    return f"Successfully generated image to {output_file}"


def _generate_image_gemini(
    prompt: str, reference_images: list[str], output_file: str, aspect_ratio: str
) -> str:
    parts = []
    valid_reference_images = []
    for ref_img in reference_images:
        if validate_image(ref_img):
            valid_reference_images.append(ref_img)
        else:
            print(f"Skipping invalid reference image: {ref_img}")
    if len(valid_reference_images) < len(reference_images):
        skipped = len(reference_images) - len(valid_reference_images)
        print(
            f"Note: {skipped} reference image(s) were skipped due to validation failure."
        )

    for reference_image in valid_reference_images:
        with open(reference_image, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": image_b64}})

    bearer_value = os.getenv("GEMINI_API_KEY")
    if not bearer_value:
        return "GEMINI_API_KEY is not set"
    response = _post_image(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image-preview:generateContent",
        headers={"x-goog-api-key": bearer_value, "Content-Type": "application/json"},
        json={
            "generationConfig": {"imageConfig": {"aspectRatio": aspect_ratio}},
            "contents": [{"parts": [*parts, {"text": prompt}]}],
        },
    )
    data = response.json()
    response_parts: list[dict] = data["candidates"][0]["content"]["parts"]
    image_parts = [part for part in response_parts if part.get("inlineData", False)]
    if len(image_parts) == 1:
        base64_image = image_parts[0]["inlineData"]["data"]
        image_bytes = base64.b64decode(base64_image)
        _ensure_output_dir(output_file)
        with open(output_file, "wb") as f:
            f.write(image_bytes)
        return f"Successfully generated image to {output_file}"
    raise Exception("Failed to generate image")


def _write_openai_image(payload: dict, output_file: str) -> str:
    images = payload.get("data") or []
    if not images or not isinstance(images[0], dict):
        raise Exception("OpenAI-compatible provider returned no image data")

    item = images[0]
    encoded = item.get("b64_json") or item.get("image_base64") or item.get("base64")
    if encoded:
        image_bytes = base64.b64decode(encoded)
    else:
        image_url = item.get("url")
        if not image_url:
            raise Exception(
                "OpenAI-compatible provider returned neither base64 data nor a URL"
            )
        if image_url.startswith("data:"):
            _, encoded = image_url.split(",", 1)
            image_bytes = base64.b64decode(encoded)
        else:
            image_bytes = _download_image(image_url)

    _ensure_output_dir(output_file)
    with open(output_file, "wb") as f:
        f.write(image_bytes)
    return f"Successfully generated image to {output_file}"


def _generate_image_openai(
    prompt: str, reference_images: list[str], output_file: str, aspect_ratio: str
) -> str:
    bearer_value = os.getenv("IMAGE_GENERATION_API_KEY")
    if not bearer_value:
        return "IMAGE_GENERATION_API_KEY is not set"

    url = f"{_openai_base_url()}/images/generations"
    headers = {"Authorization": f"Bearer {bearer_value}"}
    model = os.getenv("IMAGE_GENERATION_MODEL", OPENAI_DEFAULT_MODEL)
    is_dall_e = model in {"dall-e-2", "dall-e-3"}
    if is_dall_e and os.path.splitext(output_file)[1].lower() != ".png":
        raise ValueError("DALL-E output files must use a .png extension")
    if is_dall_e and reference_images:
        raise ValueError(
            f"{model} reference-image editing is not supported by this skill"
        )
    fields = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": _openai_size(aspect_ratio, model),
    }
    if is_dall_e:
        fields["response_format"] = "b64_json"
    else:
        fields["output_format"] = _openai_output_format(output_file)

    if reference_images:
        url = f"{_openai_base_url()}/images/edits"
        with ExitStack() as stack:
            files = [
                (
                    "image[]",
                    (
                        os.path.basename(path),
                        stack.enter_context(open(path, "rb")),
                        _guess_mime(path),
                    ),
                )
                for path in reference_images
            ]
            response = _post_image(
                url, headers=headers, data=fields, files=files, timeout=180
            )
    else:
        response = _post_image(
            url,
            headers={**headers, "Content-Type": "application/json"},
            json=fields,
            timeout=180,
        )
    return _write_openai_image(response.json(), output_file)


def generate_image(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
) -> str:
    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt = f.read()
    provider = _resolve_provider(
        "IMAGE_GENERATION_PROVIDER", "gemini", bool(os.getenv("GEMINI_API_KEY"))
    )
    if provider in ("openai", "openai-compatible"):
        return _generate_image_openai(
            prompt, reference_images, output_file, aspect_ratio
        )
    if provider == "minimax":
        return _generate_image_minimax(
            prompt, reference_images, output_file, aspect_ratio
        )
    if provider in ("gemini", "google"):
        return _generate_image_gemini(
            prompt, reference_images, output_file, aspect_ratio
        )
    raise ValueError(
        f"Unknown image provider: {provider!r} "
        "(use 'gemini', 'minimax', 'openai', or 'openai-compatible')"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate images using Gemini, MiniMax, or an OpenAI-compatible API"
    )
    parser.add_argument(
        "--prompt-file", required=True, help="Absolute path to JSON prompt file"
    )
    parser.add_argument(
        "--reference-images",
        nargs="*",
        default=[],
        help="Absolute paths to reference images (space-separated)",
    )
    parser.add_argument(
        "--output-file", required=True, help="Output path for generated image"
    )
    parser.add_argument(
        "--aspect-ratio",
        required=False,
        default="16:9",
        help="Aspect ratio of the generated image",
    )
    args = parser.parse_args()

    try:
        print(
            generate_image(
                args.prompt_file,
                args.reference_images,
                args.output_file,
                args.aspect_ratio,
            )
        )
    except Exception as e:
        print(f"Error while generating image: {e}", file=sys.stderr)
        sys.exit(1)

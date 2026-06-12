"""Thin HTTP wrapper around the internal MinerU OCR service."""
import os
import urllib.request
import urllib.error
import json
import uuid
import mimetypes
from pathlib import Path


class MinerUError(Exception):
    """Raised when the MinerU API returns a non-2xx response or the call fails."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def ocr_to_markdown(file_path: str, *, timeout: int = 60) -> str:
    """POST a file to MinerU and return the markdown string from the response.

    Requires env: MINERU_API_URL (required), MINERU_API_KEY (required).
    Raises MinerUError on any failure.
    """
    url = os.environ.get("MINERU_API_URL", "").rstrip("/")
    api_key = os.environ.get("MINERU_API_KEY", "")
    if not url:
        raise MinerUError("MINERU_API_URL is not set")
    if not api_key:
        raise MinerUError("MINERU_API_KEY is not set")

    p = Path(file_path)
    if not p.exists():
        raise MinerUError(f"File not found: {file_path}")

    boundary = f"----markitdown{uuid.uuid4().hex}"
    mime, _ = mimetypes.guess_type(str(p))
    if mime is None:
        mime = "application/octet-stream"

    with open(p, "rb") as f:
        file_bytes = f.read()

    body = _build_multipart(boundary, p.name, mime, file_bytes)

    req = urllib.request.Request(
        f"{url}/ocr",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise MinerUError(f"MinerU HTTP {e.code}", status=e.code, body=body_text) from e
    except urllib.error.URLError as e:
        raise MinerUError(f"MinerU connection error: {e.reason}") from e

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise MinerUError(f"MinerU returned non-JSON: {raw[:200]}") from e

    md = payload.get("markdown") or payload.get("text") or payload.get("content")
    if not md:
        raise MinerUError(
            f"MinerU response had no markdown/text/content field: {raw[:200]}"
        )
    return md


def _build_multipart(boundary: str, filename: str, mime: str, data: bytes) -> bytes:
    """Build a multipart/form-data body for a single file field named 'file'."""
    crlf = b"\r\n"
    parts: list[bytes] = []
    parts.append(f"--{boundary}".encode())
    parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode()
    )
    parts.append(f"Content-Type: {mime}".encode())
    parts.append(b"")
    parts.append(data)
    parts.append(f"--{boundary}--".encode())
    parts.append(b"")
    return crlf.join(parts)

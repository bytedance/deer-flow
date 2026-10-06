"""Video streaming helpers (spec 2026-09-08 §4/§5, plan Task 10b).

The drawer's inline ``<video>`` player is served by
``GET /{kb_id}/documents/{doc_id}/video/stream``. **Starlette ≥ 1.3
``FileResponse`` negotiates HTTP Range natively** — it returns 200 for a plain
GET, 206 with ``Content-Range`` for a satisfiable range, 416 (``Content-Range:
bytes */size``) for an unsatisfiable one and 400 for a malformed header, reading
the file through ``anyio`` so a large video never blocks the event loop. The
router therefore hands ``FileResponse`` the resolved path and this module supplies
only the piece FileResponse otherwise *guesses*: the response ``Content-Type``.

``FileResponse`` falls back to ``mimetypes.guess_type``, which is
platform-dependent (Windows registry / system mime db) and does not reliably know
``.mkv``. The frozen video upload set (``parser.VIDEO_UPLOAD_SUFFIXES``) gets a
pinned suffix → Content-Type map so the player always receives a playable
``video/*`` type regardless of host. This is the pure, unit-tested helper the plan
asked to "钉死"; a hand-written Range parser is deliberately **not** here — it
would be dead code duplicating FileResponse's native, upstream-tested handling.
"""

from __future__ import annotations

#: Suffix → Content-Type for the frozen video set (mirrors
#: ``parser.VIDEO_UPLOAD_SUFFIXES``). Dotted, lowercase keys.
VIDEO_MEDIA_TYPES: dict[str, str] = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}

#: Total fallback for an unmapped suffix. The router gates on the video set before
#: serving, so this is only reached if that set and the map ever drift apart.
_DEFAULT_MEDIA_TYPE = "application/octet-stream"


def content_type_for_video(suffix: str) -> str:
    """Content-Type for a video file suffix (case-insensitive, dotted).

    >>> content_type_for_video(".MP4")
    'video/mp4'
    """
    return VIDEO_MEDIA_TYPES.get(suffix.lower(), _DEFAULT_MEDIA_TYPE)

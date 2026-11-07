# Video Generation Maintenance

[scripts/generate.py](scripts/generate.py) shares extension-based MIME inference between Gemini references
and MiniMax first-frame data URLs. Reject unmapped suffixes with a `ValueError`
that names the file and supported extensions. Preserve case-insensitive PNG,
JPEG, WebP and GIF metadata without decoding or transcoding images.

Keep provider format acceptance separate from MIME recognition. The public-skill
reference-MIME regressions mock HTTP calls, verify request metadata and exact input
bytes for both providers, and reject unknown extensions before submission.
Preserve the layout of unrelated script code.

Omit blank MiniMax resolution and duration overrides from the request. Report
invalid duration strings with a `ValueError` naming `MINIMAX_VIDEO_DURATION`
before submission. The provider checks model-specific resolution and duration
combinations. Clear both override variables in offline video test fixtures.

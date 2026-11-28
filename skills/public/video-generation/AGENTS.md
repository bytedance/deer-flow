# Video generation skill (`skills/public/video-generation/`)

- **One extension-based MIME lookup serves Gemini references, MiniMax
  first-frame data URLs, and BytePlus Agent Plan reference images.** An unmapped
  suffix raises an error that names the file and the supported extensions.
  Images are not decoded or transcoded.
- **MIME recognition is separate from the formats a provider accepts.**
- **Blank MiniMax and BytePlus Agent Plan resolution and duration overrides are
  omitted from the request.** An invalid duration string is reported before
  submission. The provider checks the model-specific combinations.
- **Tests mock HTTP and check request metadata and the exact input bytes** for
  all providers. Offline fixtures clear all override variables.
- **`scripts/preflight.py` is stdlib-only and deterministic.** It validates the
  6-section beat-synced plain-text format in `templates/commercial-short-ad.md`
  and rejects invalid `--image-count` or `--duration` values before reading.
- **`scripts/stitch.sh` wraps `ffmpeg` concat assembly in POSIX bash** (keeping
  Python scripts free of `subprocess` calls for SkillScan compliance). It
  validates all arguments, input clips, output extension (`.mp4`/`.mov`), and
  `ffmpeg` availability before creating directories, writes into a sibling temp
  directory, and atomically moves the verified output so existing files are
  preserved on failure.

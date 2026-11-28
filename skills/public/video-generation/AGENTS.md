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

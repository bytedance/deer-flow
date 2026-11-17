# Video generation skill (`skills/public/video-generation/`)

- **One extension-based MIME lookup serves Gemini references and MiniMax
  first-frame data URLs.** An unmapped suffix raises an error that names the file
  and the supported extensions. Images are not decoded or transcoded.
- **MIME recognition is separate from the formats a provider accepts.**
- **Blank MiniMax resolution and duration overrides are omitted from the
  request.** An invalid duration string is reported before submission. The
  provider checks the model-specific combinations.
- **Tests mock HTTP and check request metadata and the exact input bytes** for
  both providers. Offline fixtures clear both override variables.

Gemini media downloads attach `x-goog-api-key` only to the HTTPS
`generativelanguage.googleapis.com` origin (default port or 443). Follow redirects
manually, recomputing credentials per hop; external HTTPS media URLs receive no
API key. Reject HTTP downgrades and embedded credentials, and bound redirects.
Credential regressions mock the Requests transport, not its redirect handling.

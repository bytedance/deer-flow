# Advisory screening of fetched content

An experimental DeerFlow extension for RFC #5737. It examines the model-visible
text of `web_fetch`, `web_search`, `image_search`, `web_capture` and MCP tool
results. A TypeSafe Jev `noul` answer above the configured threshold adds one
fixed warning before the original result. The original content is preserved;
there is no automatic denial, tool authorization, redaction or claim that the
agent will ignore the suspicious instruction.

The extension is disabled by default. A deployment operator must install this
package and enable it in the operator-owned `config.yaml`:

```yaml
plugins:
  - use: deerflow_extension_jev_screening:install
    config:
      enabled: true
      api_key_env: TYPESAFE_API_KEY
      model: jev-latest
      threshold: 0.5
      max_excerpt_chars: 4000
      timeout_seconds: 3.0
```

Install from `backend/` with
`uv run deerflow extensions install ../examples/deerflow-extension-jev-screening --yes`,
then restart Gateway. Supply `TYPESAFE_API_KEY` to the Gateway process. The
optionally configured endpoint must use HTTPS or loopback HTTP. The key is read
from its named environment variable on each call and is never placed in plugin
settings, tool results or logs.

**Data sharing:** Enabling this extension sends up to 4,000 characters of each
eligible result to the configured TypeSafe service, including possible page or
MCP content. A tool result can contain private material. Review data egress
before enabling it. The fixed screening question is the v2 wording in the
reproducible evaluation kit attached to RFC #5737. The stored detection
measurements do not measure this extension's effect on agent behavior.

One request is made for each eligible tool call containing text (including a
`Command` with multiple tool messages). The HTTP deadline is at most
10 seconds; failures, missing credentials, malformed responses, multimodal
content pass through unchanged, while task cancellation propagates.
The extension uses a new client per result and does not retry or cache. It
classifies a bounded excerpt, then keeps the original result unchanged except
for the fixed marker. A missed instruction beyond the excerpt is possible.

The plugin middleware uses `TOOL_VISIBLE`, after the host's sanitizer and output
budget have prepared the result for the model. It does not handle local file or
shell output. A future host-owned trust annotation would require a separate
contract; this example uses a short text marker for design review.

Tests use `httpx.MockTransport`, a local tool-call handler and no API key or
paid model call. To assess protective value, a separate paired agent replay
must measure whether the model follows injected instructions and whether benign
tasks are disrupted. Classifier accuracy by itself does not establish that.

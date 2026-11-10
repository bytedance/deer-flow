# Model catalog and recent choices

`catalog.ts` filters only authorized models. `recent.ts` stores eight recent
choices per user/browser. Favorites remain in the existing store.

### Shared model settings

Settings → Models (`?settings=models`) offers administrator-only catalog management
through `/api/managed-models`. YAML entries are read-only. `core/models/management.ts`
whitelists editable fields so source metadata and `has_api_key` never get posted.
Draft credentials stay in editor state, never query cache or browser storage; blank
keeps the saved key, explicit removal sends an empty key. Saving invalidates both the
admin catalog and `MODELS_QUERY_KEY`. Editor unmount aborts probes and fences late
callbacks. Static demos and non-admin users must not query the management API.

### Model reasoning capabilities

`/api/models` projects a per-model `reasoning` contract (issue #5073) beside the
deprecated `supports_thinking` / `supports_reasoning_effort` booleans.
`core/models/reasoning.ts` is the only place that interprets it: it falls back to
the booleans for older Gateways, clamps the chat mode (`getResolvedMode` never
yields `flash` for a required-thinking model), lists the effort options the
composer and the sidecar render, and maps mode presets and remembered values
through the contract's aliases/default (`resolveReasoningEffort`). Effort values
are open strings (`ReasoningEffortValue`), so provider-specific tokens such as
`max` flow through local settings and account preferences unchanged; the custom
agent dialog offers only the intersection with the per-agent `low/medium/high`
schema and blocks new "off" for required-thinking models. Do not read the booleans in
components directly. Legacy `resolveReasoningEffort` keeps only advertised generic
values, dropping provider tokens after a switch; backend requests stay unchanged.
Agent settings omit untouched reasoning, show invalid saved values for clearing,
and require a known model to save a model switch.

### Web model provider presets

Settings → Models obtains provider form metadata from the admin-only backend `/api/managed-models/providers`; do not copy endpoints, protocols or adapter maps into the UI. New models need only provider, API key and arbitrary model ID, with server-generated stable names. Custom endpoint fields and legacy edits stay supported. Provider/endpoint changes clear test results and saved-key reuse; omitted keys retain only the same connection. Capability overrides belong in Advanced settings. Successful saves/toggles invalidate both managed-model queries and MODELS_QUERY_KEY so existing chat/Agent selectors refresh. Keep locale text and administrator/static-mode restrictions aligned.

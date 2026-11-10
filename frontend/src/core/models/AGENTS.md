# Model catalog (`core/models/`)

```bash
cd frontend && pnpm rstest run core/models
```

- **The catalog shows authorized models only.** Recent choices are stored per
  user and browser.
- **`reasoning.ts` is the only reader of the reasoning contract.** It also
  handles the fallback to the deprecated capability booleans for an older
  Gateway. Components do not read those booleans directly.
- **Effort values are open strings**, so a provider-specific value passes
  through local settings and account preferences unchanged. The custom agent
  dialog offers only the values that the per-agent schema also allows.
- **A required-thinking model never resolves to the mode without thinking.**
- **`management.ts` allows a fixed set of editable fields**, so source metadata
  and `has_api_key` are never posted. Entries from YAML are read-only.
- **A draft credential lives in editor state only**, never in the query cache
  or browser storage. A blank field keeps the saved key, and an explicit removal
  sends an empty key. A change of provider or endpoint clears test results and
  the reuse of the saved key.
- **Provider form metadata comes from the backend.** Do not copy endpoints,
  protocols or adapter maps into the UI.
- **A successful save or toggle invalidates the admin catalog and
  `MODELS_QUERY_KEY`**, so open chat and agent selectors refresh.
- **Static demos and non-admin users never query the management API.** Closing
  the editor aborts running probes and ignores their late callbacks.

# Knowledge center example

A browser-only extension package. It stays independent of the management
extension and of backend activation.

- **Reach the platform through the host's `requestBackend`.** Do not import host
  modules, copy Provider logic, or keep credentials or content in browser
  storage.
- **A capability is not an authorization and not an observed execution.** Show
  real resource identities, unknown states and explicit false options. Do not
  invent directories, task IDs, percentages or traces. A missing entry, version
  or graph API is shown as unavailable.
- **Order document reads and invalidate them before a write.** Honor page and
  selection cancellation, and keep one selector listener.
- **A write is never retried.** A submitted write that failed needs explicit
  reconciliation.
- **Render external text through `textContent`.**
- **Update `ui_manifest.json` for every asset** and verify the wheel contents.
- **Follow the host UI rules**: semantic tokens, system UI type, English and
  Chinese copy, and a 375px layout.

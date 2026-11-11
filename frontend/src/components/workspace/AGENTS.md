# Workspace components (`frontend/src/components/workspace/`)

The signed-in workspace UI: sidebar, composer, artifact panel, settings dialogs,
the Capability Center and plugin pages. Product contracts:
[capability center](../../../../docs/capability-center.md),
[full-stack plugins](../../../../docs/full-stack-plugins.md#frontend-implementation-invariants).
Message rendering rules are in the [frontend source guide](../../AGENTS.md).

## Verify

```bash
cd frontend
pnpm check
pnpm test
pnpm catalog:sync   # after a change to the capability catalog
```

## Requests and dialogs

- **A dialog aborts its requests when it closes**, and ignores a callback that
  arrives for an earlier user, skill or thread. A late response must not write
  into a dialog that now shows something else.
- **A write is never retried automatically.** Model import, plugin backend calls
  and deletion show the failure and let the user retry.
- **A change to a connection's destination clears its credential draft.** A key
  typed for one endpoint must not be sent to another. A blank key keeps the
  saved one; an explicit removal sends an empty key.
- **Thread deletion is hosted outside the virtualized sidebar lists.** The dialog
  keeps its thread snapshot and retry state when a partial deletion removes the
  row. `onDeleted` runs after both the remote and the local step succeed.
- **Project memory promotion compares the saved instructions.** Disable it
  while the editor has unsaved changes. After promotion, refetch the
  project details so the editor sees the new instructions.
- **A browser download handoff does not prove that the file was saved.** Do not
  report an export as stored.
- **Read an error body as unknown**, and narrow each field before use. A malformed
  body keeps the typed HTTP failure.

## Capability Center

- **Installed, enabled, credential-configured and authorization-verified are four
  states.** Keep them apart in the UI.
- **Provider identity comes from catalog metadata.** Do not infer a provider or a
  brand icon from a server display name; a custom server name never selects a
  brand.
- **The catalog source is `capabilities/builtin.json` in the harness.** The demo
  snapshot is generated from it, and a unit test compares the two.
- **Agent plugin selection uses installation IDs.** `null` means all and `[]`
  means none. The dialog submits only the selections that changed since it
  opened, so a concurrent update elsewhere survives. The selection is a runtime
  choice, not an authorization policy.
- **MCP secrets and raw settings stay in the administrator editor.** Other views
  read the safe status projection. A plugin icon is a bounded PNG data URL in
  presentation metadata and never enters transport parameters. Remote URLs and
  SVG are not rendered.
- **Skill diagnostics check YAML syntax only.** Keep the scope note visible, and
  do not interpret parser exception wording in the UI.
- **`pluginPages` lists enabled runtime entries.** A catalog entry does not imply
  activation.

## Composer references

- **A label grants no read authority.** The backend checks every referenced skill
  against the user's registry and the agent allowlist.
- **Render a label as DOM text, never as HTML.**
- **Only a successful discovery may flatten references.** While discovery is
  pending or failed, keep the IDs and block a send that carries references.
- **Commit mention text before you restore focus, in the same tick.** A delayed
  callback would overwrite what the user typed in between.
- **The web slash picker lists composer commands only.** Skills are selected with
  `@`. Typed slash text is still submitted as a normal message, which the backend
  and the IM channels rely on.

## Delimited preview

- **CSV parsing runs in the worker only**, with bounded input, cancellation of
  stale work and a timeout. Parsing on the main thread freezes the workspace on
  a large file.
- **The parser is told the record separator explicitly.** Auto-detection is
  corrupted by a newline inside an incomplete quoted field of a truncated sample.

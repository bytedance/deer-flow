# Workspace model catalog

`settings/model-catalog-dialog.tsx` keeps connection drafts in component state,
aborts on dismissal, sequences `/discover` + `/import`, and refreshes both model
queries after partial/cancelled imports. Never retry writes automatically. Custom endpoints precede keys; destination edits clear credentials. Picker rows
and arrow-key navigation share one group order; catalog refresh clears absent
provider filters; active filters always remain clearable, including YAML models. The
server deduplicates by connection, credential and model under the catalog lock.

`settings/model-connection-fields.tsx` owns provider, endpoint and key fields for
single-model editing and catalog imports. Destination edits drop draft keys and
saved-source references; blank keys retain, explicit removal sends an empty key.
Parents own their model capabilities, revisions and independent draft lifetimes.

### Delimited artifact preview

CSV/TSV previews share `artifact-table-preview.tsx` between the panel and standalone viewer. Papa Parse runs only inside `delimited-preview.worker.ts`; `use-delimited-preview.ts` bounds input before transfer, cancels stale work, and enforces a five-second timeout. The parser detects the first record separator outside quoted fields and passes it explicitly to Papa Parse, so embedded newlines in an incomplete quoted field cannot corrupt newline detection. It retains at most 202 logical records and 50 columns, discarding an incomplete final record from truncated input. UI pagination displays at most 200 data rows in pages of 50. Keep the table mounted but inactive when switching to source so header/pagination state survives; changing file identity resets it. Pending `write_file` content stays in source mode until success.

For a truncated sample whose first separator is LF or CRLF, strip a terminal CR
before parsing so a split CRLF separator cannot make a quoted final field
invalidate the whole preview, including LF-first files with later CRLF records.
The terminal record remains incomplete and is discarded; complete CR-only files
and malformed quotes retain their existing behavior.

Custom skill export is admin-only and disabled in static demos. The lazy
`skill-export-dialog.tsx` must abort requests and ignore stale callbacks on close
or user/skill changes. `core/skills/export.ts` owns the revision-bound Blob download;
HTTP 409 requires explicit preview refresh. Keep file lists paginated and diagnostics
localized. Browser handoff does not prove the file was saved to disk.

`core/skills/error-detail.ts` reads error JSON as unknown for skill management
and export. Narrow records and string fields before use; malformed bodies must
preserve typed HTTP failures and the upload API's soft-failure contract.

Sidebar rows request deletion through `ThreadDeleteDialogProvider`, hosted in
`WorkspaceSidebar` outside the virtualized flat/project lists. Keep the selected
thread snapshot and retry UI alive when a partial deletion removes its row.
Focus Cancel on open and after a failed deletion has re-enabled the actions;
block dismissal while deletion is pending. Show the error message when available,
with a localized fallback, and log the rejection for debugging. The shared
delete helper accepts remote 404 (not 403) before retrying local cleanup, and
`onDeleted` runs only after both deletion steps succeed.

## Capability Center

`skill-diagnostics.tsx` mounts only for administrators outside static demos. Its
user-keyed diagnostics query is separate from `useSkills()` and every picker.
Reload posts `/api/skills/reload` before invalidating both normal skills and
diagnostics; failures retain the warning and show localized retry feedback.
Never interpret raw parser exception wording in the UI.
Keep the scope note visible even when diagnostics are empty. It must describe
the YAML-syntax-only check and its exclusions (missing frontmatter, metadata
validation, unreadable and non-UTF-8 files); it is not a package-validity check.

`/workspace/capabilities` owns Plugins and Skills navigation. Plugins composes the
MCP manager and a lazily loaded Lark configuration dialog; installation, OAuth,
mutation permissions, and cache ownership remain in the existing hooks. Skill display names/summaries are presentation
metadata; runtime names and full descriptions remain unchanged. Public, custom,
integration, and legacy sources must stay distinct. Community currently offers
archive import, not a remote marketplace. Screenshot E2E fixtures are demo data.
`backend/packages/harness/deerflow/capabilities/builtin.json` owns localized
catalog manifests. Refresh the generated demo snapshot with `pnpm catalog:sync`
after changing the catalog; unit tests enforce equality with the source. Demo
business projections derive provider IDs from the catalog adapter metadata. The
sync script uses decoded filesystem paths for formatter configuration lookup.
`plugin-catalog.ts` only resolves localized text and explicit
installation metadata; never infer provider identity from server display names.
`plugin-directory.tsx` groups rows and applies search/category/installed filters.
`core/capabilities` consumes catalog and safe status projections; MCP secrets and
raw settings remain in the administrator-only editor. `plugin-adapters.tsx`
registers integration-specific settings flows once, independent of catalog size.
The `business` form uses manifest credential fields without asking for an MCP URL;
its backend adapter generates bundled DingTalk/WeCom notification or HubSpot CRM
connections. These also appear in MCP discovery, so deduplicate projections by
installation ID. Keep their labels as configuration, not package installation.
Keep installation, enabled state, configured credentials, and verified authorization
distinct. Agent `mcp_plugins` uses stable installation IDs; null means all, [] means
none. The settings dialog submits only selections changed from its opening
snapshot, preserving concurrent updates on unrelated saves and treating restored
selections as unchanged. It is runtime selection, not a replacement authorization policy. See
`docs/capability-center.md` for the complete contract and extension example.
`PluginIcon` is shared by recommendations, configured entries, and the editor;
brand assets and their provenance live in `public/images/plugins/`. Brand icons
require explicit catalog metadata; a custom server name never selects a brand.
Ambiguous installation IDs remain visible but cannot be selected for an Agent. The icon picker
accepts local PNG/JPEG/WebP up to 2 MiB, checks the signature, decodes and contains
the image in a 128px PNG, and stages changes until the existing targeted MCP save.
`presentation.icon` is a bounded PNG data URL carried by the API's existing extra
metadata support; it must never enter transport parameters. Preserve sibling
presentation fields and masked credentials; cancel/reset/unmount must fence stale
image-decoding results. Uploaded remote URLs and SVG are never rendered. Existing
shared-MCP administrator checks remain authoritative; this adds no personal scope.

## Full-stack plugin UI

Follow [plugin invariants](../../../../docs/full-stack-plugins.md#frontend-implementation-invariants).
Use `pluginPages` only for enabled runtime entries; catalogs never imply activation.
Package documentation and bundled-copy sync: `examples/README.md`. Hide empty requirements.
Optional `requestBackend` binds viewers, rejects redirects, never retries; routes retain authorization.

### Composer references

`components/workspace/mentions/` owns cursor-local `@` detection, the picker,
and atomic references. Render labels as DOM text, never HTML; canonical tokens
preserve draft positions. Submission expands tokens to `@label` and sends up to
16 unique skill IDs in `additional_kwargs.skill_references`; the backend checks
each against the user registry and agent allowlist. The web slash picker lists
only `/goal` and `/compact`; skill selection uses `@`. Legacy typed slash text
continues through normal message submission for backend and channel compatibility.
Project files require confirmed `additional_kwargs.files`. Conversation context
is reconciled from tokens against the current capability and limit. Only successful
discovery may flatten references; pending/errors preserve IDs and block reference
sends, with retry on failure. Polish restores whole labels longest-first in one
pass. Confirmed thread creation seeds metadata before migration; references stay
locked during attachment. Deleting an object removes its context; undo restores
references already attached to the draft. Labels grant no read authority. IME,
caret, thread changes and attachment fences apply to editor and picker. Commit
mention text before restoring focus synchronously; a delayed callback must not
overwrite subsequent typing or caret movement. The `@`
and attachment buttons share the picker.

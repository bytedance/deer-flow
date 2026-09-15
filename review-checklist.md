# Code Review Checklist — feat/connector

## [P1] Keep connector tenant identity and upstream authentication server-owned

- [x] **connector_interceptor.py**: Always overwrite `request.args["userId"]` — never trust model-supplied value  
  → `"Always overwrite — never trust a model-supplied userId"` ✓
- [x] **connector.py**: Header allowlist (`_REQUEST_HEADER_ALLOWLIST`) replaces blocklist, only forwards `accept`, `content-type`, `user-agent`  
  → `_REQUEST_HEADER_ALLOWLIST = frozenset({"accept", "content-type", "user-agent"})` ✓
- [x] **connector.py**: `Authorization` set unconditionally, not just when missing  
  → `"Always set the configured connector app credential"` ✓

## [P2] Do not proxy AnyConnect admin APIs without an admin boundary

- [x] **connector.py**: `/api/connector/runtime-tokens` routes removed  
  → 0 occurrences of `runtime.token` found ✓

## [P1] Restore the required compile, lint, and format gates

- [x] **Backend Ruff check**: passes (`All checks passed!`) ✓
- [x] **Backend Ruff format**: applied ✓
- [x] **Unused `HTTPException` import**: removed ✓
- [x] **`workspace-gallery-header.tsx`**: added to branch ✓
- [x] **`workspace-mobile-sidebar-trigger.tsx`**: dependency added ✓
- [ ] Frontend typecheck: `workspace-gallery-header.tsx` imports resolved; full project check needs existing pre-existing errors resolved
- [ ] Frontend ESLint: TBD
- [ ] Frontend Prettier format: TBD

## [P2] Do not forward decoded bytes with the upstream encoding metadata

- [x] **connector.py**: `_CONTENT_HEADERS` reduced to `{"content-type"}` only, no longer forwards `content-encoding` or `content-length`  
  → `_CONTENT_HEADERS = {"content-type"}` ✓

## [P2] Preserve every API-key credential field declared by the provider

- [x] **connector-page.tsx**: Renders all `authConfig.fields`, not just `fields[0]`  
  → `"Render every field declared by the provider"` ✓

## [P2] Open the OAuth window inside the click gesture

- [x] **connector-page.tsx**: `window.open("about:blank")` before `await`, navigates after response  
  → `"about:blank"` matched ✓

## [P2] Remove the unrelated Monocle PR from this connector change

- [x] **Monocle files**: not present in feat/connector diff vs upstream  
  → 0 Monocle paths ✓

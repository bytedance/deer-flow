# Conversation Sharing (`app.gateway.shares` + `routers/shares.py`)

Read-only public sharing of conversation snapshots (#4548, design of record).
Gated on `conversation_sharing.enabled` (off by default) and a SQL database —
memory-only backends fail management routes with 503 and public reads with 404,
so links nobody can durably resolve cannot be minted.

## Owner endpoints — `threads:read` + owner_check

- `POST /api/threads/{id}/shares` enforces **strict row ownership**: the thread
  row must exist and name the caller as owner. The decorator's permissive
  `owner_check` semantics (missing rows / `user_id=NULL` pass) deliberately do
  not apply to a publishing action — any authenticated user could otherwise
  mint public links for pre-auth shared data. Consequence: legacy `user_id=NULL`
  threads are unshareable by anyone; in auth-disabled deployments threads are
  owned by the synthetic `default` admin, so sharing works there.
- The snapshot is frozen at creation through `_scan_thread_message_page` with
  the hidden/control filter re-applied (allowlisted `ask_clarification` replies
  can be persisted), converted to a strict-allowlist DTO: snapshot-local ids,
  `user`/`assistant` roles, renderable text only — no run/thread/user
  identifiers, tool arguments, or debug data. The scan pages arrive
  newest-page-first with each page internally ascending; the builder flips the
  page order only. Conversations over the 2000-message cap are **rejected with
  413** (`ShareSnapshotTooLarge`) — a share promises the complete visible
  transcript, so it is never silently truncated.
- `GET` lists management metadata (never token hashes); `DELETE /{share_id}`
  revokes immediately (scoped to thread + owner in the repository).

## Token storage (`tokens.py`)

`dfs_` + urlsafe(32 CSPRNG bytes), returned exactly once. Only the HMAC-SHA-256
`token_hash` is persisted (unique index, constant-time lookup). The pepper
comes from `SHARE_TOKEN_PEPPER` or an auto-generated 0600 `.share_token_pepper`
(the `AUTH_JWT_SECRET` lifecycle) — never a YAML field; pepper rotation
invalidates every outstanding token.

## Public endpoint — the single auth-exempt route

`GET /api/shares/{share_token}` is the feature's only anonymous surface (the
middleware exemption is prefix-based, so two contract tests pin that nothing
non-GET may mount under `/api/shares/`). Properties: per-request
expiry/revocation checks with indistinguishable 404s for unknown/revoked/
expired; per-IP resolve throttle (in-memory, per-worker — a courtesy control,
the token is 256-bit unguessable); `Referrer-Policy: no-referrer`; and zero
thread-state access — explicit share records are the only gate in every mode,
including auth-disabled. A regression test patches `get_thread_store` to
raise, proving the public path never consults thread access under any
principal.

Token-in-URL leakage has two repository-level controls (both pinned by
`tests/test_share_token_log_masking.py`; `Referrer-Policy` only covers browser
referrers, not log sinks):

- **Gateway logs** — `install_share_token_redaction()` (`deerflow/logging_config`,
  called at app import and from `configure_logging`) masks `dfs_…` in every
  rendered record: a filter on the root handlers, plus a logger-level filter on
  `uvicorn.access`, which logs full request paths with `propagate=False`.
- **nginx access logs** — both shipped configs map the request line to a masked
  variant (`$masked_request`) for `/share/` and `/api/shares/` and log the
  `combined`-format `masked_access` format; the regression test evaluates the
  config's own regex, so a dropped or loosened mask fails CI.

Snapshot immutability: later messages/edits never modify an existing share;
`source_last_seq` is audit-only and public rendering never re-reads the source.

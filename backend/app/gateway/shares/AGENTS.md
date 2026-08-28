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
  identifiers, tool arguments, or debug data. The 2000-message cap logs a loud
  truncation warning.
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
the token is 256-bit unguessable); `Referrer-Policy: no-referrer` (token rides
in the URL; nginx log masking is deployment-side); and zero thread-state access
— explicit share records are the only gate in every mode, including
auth-disabled. A regression test patches `get_thread_store` to raise, proving
the public path never consults thread access under any principal.

Snapshot immutability: later messages/edits never modify an existing share;
`source_last_seq` is audit-only and public rendering never re-reads the source.

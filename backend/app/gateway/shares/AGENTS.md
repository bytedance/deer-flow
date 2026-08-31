# Conversation Sharing (`app.gateway.shares` + `routers/shares.py`)

Read-only public sharing of conversation snapshots (#4548, design of record).
Gated on `conversation_sharing.enabled` (off by default) and a SQL database —
memory-only backends fail management routes with 503 and public reads with 404,
so links nobody can durably resolve cannot be minted.
This phase is backend/API groundwork only: the Share dialog and the HTML
`/share/{token}` page remain Phase 2 frontend work.

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
  `user`/`assistant` roles, renderable text only. Structured content admits
  only bare strings and explicit `text` / `output_text` blocks; reasoning,
  thinking, and tool-call blocks are ignored, and inline assistant `<think>`
  sections are stripped outside Markdown code examples. Owner-only
  `/mnt/user-data` and thread artifact/upload references (including
  percent-encoded and JSON-escaped separator forms — classification runs on a
  separator-normalized shadow of the text, while the original bytes are what
  get replaced, so public content is emitted unchanged) are replaced with a
  public omission marker in both messages and
  titles (at create time and again on public read) — no run/thread/user
  identifiers, tool arguments, or debug data. The scan pages arrive
  newest-page-first with each page internally ascending; the builder flips the
  page order only. Rows are sanitized per page, so the 2000 cap counts
  **public messages**, not raw rows (tool output never consumes budget). At
  exactly 2000 public messages the scan continues only to prove that no older
  public message exists; older tool/hidden rows do not make a complete share
  fail. An independent 50k raw-scan budget is consumed inside the canonical
  pager, before its visibility filters, and uses one sentinel row to prove an
  over-limit history without walking the remainder. Either bound rejecting yields **413**
  (`ShareSnapshotTooLarge`) — a share promises the complete visible
  transcript, so it is never silently truncated.
- `GET` lists management metadata (never token hashes); `DELETE /{share_id}`
  revokes immediately (scoped to thread + owner in the repository).

## Token storage (`tokens.py`)

`dfs_` + urlsafe(32 CSPRNG bytes), returned exactly once. Only the HMAC-SHA-256
`token_hash` is persisted (unique indexed equality lookup). The pepper
comes from `SHARE_TOKEN_PEPPER` or an auto-generated 0600 `.share_token_pepper`
(the `AUTH_JWT_SECRET` lifecycle) — never a YAML field. The generated file is
accepted only at its complete 43-character length, and async share routes
offload uncached file creation/read/retry to a worker thread. Pepper rotation
invalidates every outstanding token.

## Public endpoint — the single auth-exempt route

`GET /api/shares/{share_token}` is the feature's only anonymous surface (the
middleware exemption is prefix-based, so two contract tests pin that nothing
non-GET may mount under `/api/shares/`). Properties: per-request
expiry/revocation checks with indistinguishable 404s for unknown/revoked/
expired; all success and known 404 paths carry `Referrer-Policy: no-referrer`
and `Cache-Control: no-store` and
`Content-Security-Policy: frame-ancestors 'none'` (the page must not be
framed — a real conversation embedded in a phishing page lends it
credibility; frame-ancestors is response-header-only, so it belongs on the
Gateway) through response or exception headers; per-IP
resolve throttle (in-memory, per-worker — a courtesy control,
the token is 256-bit unguessable; the bucket key uses the deployment-wide
trusted-proxy model from `app.gateway.client_ip`, shared with the login
limiter — behind the shipped nginx, deployments must set
`AUTH_TRUSTED_PROXIES` to the proxy network or every anonymous visitor shares
the proxy's single bucket); and zero thread-state access — explicit share
records are the only gate in every mode, including auth-disabled. The
bearer-URL response must never survive in a browser/proxy cache past
revocation. The
API response's `Referrer-Policy` is defense in depth only: it does not establish
the document policy for the Phase 2 frontend `/share/{token}` page, which must
set its own `no-referrer` policy and avoid third-party resources. A regression
test patches `get_thread_store` to raise, proving the public path never consults
thread access under any principal.

Token-in-URL leakage also has repository-level log and diagnostic controls
(`Referrer-Policy` does not protect those sinks):

- **Gateway logs** — `install_share_token_redaction()` (`deerflow/logging_config`,
  called at app import and from `configure_logging`) masks `dfs_…` in rendered
  messages and exception tracebacks for both text and JSON output: filters on
  the root handlers, the known `uvicorn.access` / `uvicorn` / `uvicorn.error`
  loggers, and their current handlers. Handler-level coverage is required for
  descendants such as `uvicorn.asgi` because Python does not apply ancestor
  logger filters to propagated records. The filter preserves Uvicorn's
  five-value access-log tuple for `AccessFormatter`; the canonical redaction
  primitive also rejects `dfs_…` values during trace-id normalization so
  structured logs and tracing metadata cannot bypass message redaction.
- **nginx access logs** — both shipped configs mask share tokens in the request
  line (`$masked_request`) by classifying the normalized `$uri` and then
  emitting a constant route label; a raw-request fallback also catches tokens
  in query strings. The client-controlled Referer is masked in
  `$masked_referer` before writing the `combined`-format `masked_access`
  record; User-Agent and Basic-auth remote-user fields have equivalent masks.
  The matchers recognize literal and percent-encoded tokens. The regression
  test renders the config's full log format, so a dropped or loosened mask
  fails CI. nginx
  `error_log` messages embed the full request line, severity does not redact
  them (nginx trac #2193: crit-level failures still append the request
  line), and the output cannot be format-masked — so the dedicated `^~`
  share locations route `error_log` to `/dev/null`, a sink that cannot
  retain the token (pinned by an exclusive test — the block's ONLY
  error_log directive; share-route upstream diagnostics are the accepted
  trade-off, the Gateway still logs its own side). Known residual: the
  rare pre-location-selection error line (request line already parsed)
  still reaches the parent `error_log`, which cannot be masked or routed
  per-location — deployments that must close even that gap should scrub
  `dfs_[A-Za-z0-9_-]+` in their nginx error-log pipeline, like any other
  bearer-in-URL system.
- **Support bundles** — `scripts/support_bundle.py` keeps a parity-tested copy
  of the canonical token regex. Its final JSON/text archive writers and
  Markdown sidecar writers apply redaction as a last-line guarantee, in
  addition to collection-time masking.

Snapshot immutability: later messages/edits never modify an existing share;
`source_last_seq` is audit-only and public rendering never re-reads the source.

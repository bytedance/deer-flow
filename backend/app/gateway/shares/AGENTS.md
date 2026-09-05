# Conversation Sharing (`app.gateway.shares` + `routers/shares.py`)

Read-only public sharing of conversation snapshots (#4548, design of record).
Gated on `conversation_sharing.enabled` (off by default) and a SQL database —
memory-only backends fail management routes with 503 and public reads with 404,
so links nobody can durably resolve cannot be minted.
This phase is backend/API groundwork only: the Share dialog and the HTML
`/share/{token}` page remain Phase 2 frontend work.

## Owner endpoints — `threads:read`; ownership by actor

- `POST /api/threads/{id}/shares` enforces **strict row ownership**: the thread
  row must exist and name the caller as owner. `GET`/`DELETE` on the same
  subtree authorize by the **share record's owner** instead (the repository
  predicates scope by the calling user): thread ids are client-selectable, so
  after the minter's thread is deleted and the id recreated under another
  owner, the still-public share stays listable and revocable by whoever minted
  it — and invisible to the new owner of the reused id. The thread-row
  `owner_check` would have locked the record away from both. The decorator's permissive
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
  sections are stripped outside Markdown code examples — code recognition
  is block-aware per CommonMark (fences, all seven raw-HTML block types,
  indented code, ATX headings including empty forms inside quote/list
  containers, and lazy paragraphs). Once a list or quote appears,
  document-level fence/indent protection is suppressed: item indentation is
  not modeled, so possible code is over-stripped rather than reasoning leaked.
  Owner-only references are replaced in messages and titles, both at create
  and public-read time. They cover `/mnt/user-data`; every `/api/threads/{id}`
  route and subpath (plus nginx's `/api/langgraph/threads/…` alias); and rooted
  `/workspace/chats/{id}` or `/workspace/agents/{agent}/chats/{id}` routes,
  including copied HTTP(S) URLs. Classification uses a bounded normalized
  shadow for percent, JSON slash, HTML-entity, and Unicode escapes while cuts
  retain exact source coordinates. Workspace routes require a literal root or
  literal HTTP(S) scheme/authority; encoded anchors, protocol-relative/UNC,
  relative-dot, and Windows-drive forms stay public. Only canonical agent and
  thread-id grammars match; lowercase `/new` stays public, and identifier
  suffixes cannot validate a prefix. Thread ids are capped at 64 characters;
  if that canonical prefix is followed by a terminal underscore run at an
  otherwise valid route boundary, the public-share boundary redacts the
  complete route-like run without trying to reconstruct frontend Markdown
  delimiter semantics. This intentionally over-redacts a narrow class of
  invalid 65+ character lookalikes, including normalized percent-, entity-,
  and Unicode-escaped underscore spellings, because confidentiality takes
  precedence over lossless transcript fidelity. Backslashes keep their URL
  path-separator meaning rather than being treated as Markdown escapes. An
  accepted route consumes its path/query/fragment but
  preserves a URL authority and structural prose delimiters — no
  run/thread/user ids, tool arguments, or debug data. The scan pages arrive
  newest-page-first with each page internally ascending; the builder flips the
  page order only. Rows are sanitized per page, so the 2000 cap counts
  **public messages**, not raw rows (tool output never consumes budget). At
  exactly 2000 public messages the scan continues only to prove that no older
  public message exists; older tool/hidden rows do not make a complete share
  fail. A 2 MiB rendered-bytes budget bounds the total public text, counted
  in UTF-8 encoded bytes (code points would under-count astral-plane text
  4x) — a
  "few huge messages" thread fails 413 like a many-messages one, because
  every anonymous resolution deserializes and re-sanitizes the stored
  snapshot. An independent 50k raw-scan budget is consumed inside the canonical
  pager, before its visibility filters, and uses one sentinel row to prove an
  over-limit history without walking the remainder. Any bound rejecting yields **413**
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
limiter — the bundled Docker topology sets `AUTH_TRUSTED_PROXIES` to the
compose-internal ranges (safe: the gateway port is unpublished, so the peer
is always a compose container); the Helm chart ships no cluster-wide
default (namespace peers include user-code sandbox pods, which must never
be trusted proxies) but restricts gateway ingress to the nginx/frontend/
provisioner pods via a NetworkPolicy, under which `gateway.trustedProxies`
set to the pod network safely restores per-client keying; until it is set,
every anonymous visitor shares the proxy's single bucket); and zero
thread-state access — explicit share
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
- **nginx access logs** — all three shipped configs (both Docker configs and
  the Helm chart's configmap) mask share tokens in the request
  line (`$masked_request`) by classifying the normalized `$uri` and then
  emitting a constant route label; a raw-request fallback also catches tokens
  in query strings. The client-controlled Referer is masked in
  `$masked_referer` before writing the `combined`-format `masked_access`
  record; User-Agent and Basic-auth remote-user fields have equivalent masks.
  The matchers recognize literal and percent-encoded tokens. The regression
  test sweeps every config, so a dropped or loosened mask — or a shipped
  config that leaves the sweep — fails CI. nginx
  `error_log` messages embed the full request line, severity does not redact
  them (nginx trac #2193: crit-level failures still append the request
  line), and the output cannot be format-masked — so the dedicated `^~`
  share locations route `error_log` to `/dev/null`, a sink that cannot
  retain the token (pinned by an exclusive test — the block's ONLY
  error_log directive; share-route upstream diagnostics are the accepted
  trade-off, the Gateway still logs its own side). Non-share routes cannot
  carry a valid bearer at all: a server-level guard refuses
  (`return 404`, which writes no `error_log` entry) any request whose raw
  request line carries a full-strength token (32+ tail chars — short
  dfs_-shaped words stay maskable-in-logs without becoming refusable),
  except the surfaces where the bearer is legitimate: `/share/…`,
  `/api/(langgraph/)?shares/…`, and `/login` (the frontend encodes a
  return path like `/share/dfs_…` into `next=`, where the token charset
  survives encodeURIComponent — that page gets its own non-retaining
  `error_log`, pinned like the share locations). Known residual: the
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
`source_last_seq` records the highest source seq the bounded create scan observed
(audit-only; public rendering never re-reads the source).

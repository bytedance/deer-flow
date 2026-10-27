# Enterprise connections

`enterprise_messaging` is an optional config tool, not a default-granted capability.
The session-only `/api/enterprise` router and tool both enforce fresh authorization
and exact authenticated owner scoping. Schedule creation additionally requires
`threads:write` and `runs:create`. Preserve fail-closed policy failures.
Provider construction must receive both the discovered spec and authorization
config. Router regressions exercise the real provider with admin, direct and group
grants plus live revocation; provider doubles must preserve the factory signature.

`providers.py` owns provider registration, URL validation and async transport.
Only the exact HTTPS WeCom group webhook endpoint is accepted, with redirects
disabled. Never expose secrets or remote error text. A response is accepted only
when HTTP succeeds and integer errcode equals zero.

`mail.py`/`mail_tool.py` provide separately granted `enterprise_mail` (list/read)
and session-only `/api/enterprise/mail` endpoints. AliMail accounts share encrypted
target storage with `provider=alimail`; WeCom lists/sends/deletes must never accept
them. Use official allowlisted IMAP hosts on verified TLS port 993, EXAMINE and
BODY.PEEK only. Network/crypto/storage run in workers, with at most two active
connections, 15-second socket timeouts and a cooperative 60-second read budget.
Read INBOX only, 1–90 days, up to 50 messages/call, 256 KiB/message and 6,000 body
characters. UIDVALIDITY fences pagination. Bodies are untrusted plain text, no
external resources or attachment contents; keyword categories are only previews.
AI analysis uses the normal chat lifecycle and its configured model, with coverage
and truncation reported. This read tool has no mailbox mutation, sending, polling
loop or RAG sharing.
Tests: `test_enterprise_mail.py`, `test_enterprise_mail_router.py` and blocking-I/O.

`mail_compose_tool.py` provides separately granted `enterprise_mail_compose`
(accounts/draft/list only), returning a review link rather than sending.
`mail_outbox.py` encrypts immutable drafts in `enterprise_mail_drafts` in the same
private security database, bound to owner/draft IDs. Sending requires a session
POST to `/api/enterprise/mail/drafts/{id}/send` with `confirmed: true`, CSRF and
fresh compose authorization. Never expand the read grant into a send grant.
An atomic `draft → sending` claim precedes SMTP; repeated/concurrent requests
cannot submit again. Do not retry unknown/partial/failed submissions, or `sending`
left after a crash. HTTP cancellation does not stop or restart the worker.
`mail_sender.py` maps existing IMAP hosts to official SMTP hosts on verified TLS
465 and reuses the saved account/password; no arbitrary host or From override.
Two SMTP connections maximum, 15-second socket timeout per operation, up to
20 To/Cc recipients, 200 subject characters and 20,000 plain-text body characters.
No attachments or IMAP Sent-folder writes. `sent` means SMTP accepted, not delivered;
partial acceptances retain accepted/refused recipients without raw SMTP errors.
Pending drafts are capped at 100 per owner; at most 20 submission claims/minute.
All SMTP/SQLite/crypto work stays off the event loop. Tests: mail_send,
mail_outbox_router and blocking_io/test_enterprise_connections.py.

`store.py` extends the private security store's own SQLite schema initialization
with `enterprise_targets`/`enterprise_deliveries`; this is outside the application
ORM/Alembic database. Credentials are encrypted and bound to owner/target IDs.
All storage and crypto operations run in worker threads. Multi-instance scheduler
configuration is rejected until shared storage is implemented.

`service.py` reserves durable receipts before transmission. Ambiguous outcomes
are never retried automatically. Duplicate request keys cannot send again.
`sending` after a crash requires inspection, not retry. Schedule construction
uses the existing scheduled-task repository and normal Gateway run lifecycle;
the Gateway owns the process-local bridge in `runtime.py`. Never import app code
into this package or introduce another scheduling loop.

Tests: `tests/test_enterprise_connections.py`, `tests/test_enterprise_router.py`,
and `tests/blocking_io/test_enterprise_connections.py`. The operator guide is
`docs/ENTERPRISE_CONNECTIONS.md` at the repository root.

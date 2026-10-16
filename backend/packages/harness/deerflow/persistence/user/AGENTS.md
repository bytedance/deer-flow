# User persistence

`user_preferences` stores independent `(user_id, key)` rows in the shared SQL
database. PATCH upserts only supplied keys in one transaction; `null` resets a
field, disjoint edits commute, and same-field writes are last-commit-wins.

The Gateway's `GET/PATCH /api/v1/auth/preferences` allows only notification
enablement, the default model, conversation mode, and reasoning effort. It
requires a browser session plus `X-Expected-User-Id` matching that session (a
stale-tab guard, never an authorization source); PAT, internal, and auth-disabled
callers are rejected. Never persist arbitrary agent context or credentials
through this API. See `backend/docs/API.md` for the HTTP contract.


`im_notifications.py` stores shared proactive-IM choices in the separate
`im_notification_preferences` owner/provider table (0041), without a users FK:
IM binding owners include the synthetic local `default` identity. Opt-out and
terminal cancellation of pending/sending outbox rows share one transaction;
reenabling never reopens them. PostgreSQL enqueue/patch lock preference rows in
provider order; SQLite uses the enclosing writer transaction. Browser preference
storage is unchanged. The app owns route auth, CSRF and stale-viewer checks.

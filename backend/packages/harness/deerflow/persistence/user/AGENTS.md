# User persistence (`deerflow/persistence/user/`)

User preferences and IM notification choices. The HTTP contract is in
[API.md](../../../../../docs/API.md). General rules are in the
[persistence guide](../AGENTS.md).

- **A preference is one row per user and key.** A PATCH writes only the supplied
  keys in one transaction, so edits to different keys commute and the last
  commit wins for the same key.
- **The preferences API accepts a fixed set of UI settings.** Do not persist
  agent context or credentials through it.
- **`X-Expected-User-Id` is a stale-tab guard, not a source of authorization.**
  The route needs a browser session whose user matches the header.
- **IM notification choices have their own table without a foreign key to
  users.** An IM binding owner can be the synthetic local `default` identity.
- **Opt-out and the cancellation of pending outbox rows share one
  transaction.** Enabling again never reopens the cancelled rows.

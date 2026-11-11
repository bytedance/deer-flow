# Workspace UI

## Token usage dashboard

Open **Token usage** in the workspace sidebar (`/workspace/usage`) to review
your recorded tokens over the last 7 or 30 days, daily input/output totals,
cache-hit input tokens by model, and paginated run history with failure filters.
Run history covers all dates independently of the selected chart period.
Conversation links use each run's recorded assistant to open the default or
matching custom-agent chat.
Periods with no recorded runs show an empty message without a date axis or
zero-filled daily details; runs with zero reported tokens still show details.

Reporting requires `runs:read` permission and a SQLite or PostgreSQL database;
it is unavailable in the static demo. Counts reflect persisted provider usage,
may be incomplete during active runs or when providers omit usage, and are not
a provider bill. Cache hits are included in input tokens. Daily buckets use the
browser's current UTC offset and attribute a run to its creation date.
The page reuses the existing `/api/console` APIs; their optional cost and currency
fields and server-side pricing configuration remain supported.
See [dashboard behavior and design](../../frontend/docs/token-usage-dashboard.md).

## Workspace

The workspace keeps a collapsed icon sidebar visible on narrow screens. Its
toggle opens the full navigation drawer; closing the drawer returns to the icon
bar without changing your saved desktop sidebar preference. Navigating to another
page also closes the mobile drawer and preserves the destination page's focus.
Dismissing the drawer returns keyboard focus to the control that opened it.
The Agents gallery header wraps to the available width so its import and create
actions remain visible beside the compact sidebar on narrow screens.

## Chat Archive

Deleting a chat from the sidebar requires confirmation showing its title. Deletion removes the conversation and its files and cannot be undone.

Use **Archive chat** in a recent chat's sidebar menu to hide completed work while keeping its messages, files, and original link. The success message offers **Undo**. Open **Chats → Archived** to find archived conversations and restore them individually; an open archived conversation also shows a restore button in its header. Search filters the titles of loaded conversations, with **Load more** for older entries.

Archive and restore preserve the chat's activity time and pinned state. Archiving does not stop a running task or pause its schedules, and new activity does not automatically restore it. Use the existing Delete action when you intend to remove a conversation and its files.

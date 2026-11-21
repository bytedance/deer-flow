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

## Customize the sidebar menu

Open the **More** entry in the sidebar and choose **Customize menu**. Drag the
handle beside an entry to reorder it within its group, or drag it between the
menu and **More**. While a dragged entry is over the other group, a line marks
where it will land. The arrow button on each row moves an entry between the two
groups without dragging, and the dialog saves every change immediately.

**New chat** sits above the main menu and cannot be moved; **Chats** is an
ordinary entry, first by default. Entries the current user cannot see, such as
**Token usage** without `runs:read`, are not offered in the dialog. An entry
whose feature is switched off, such as **Agents** when the agents API is
disabled, stays visible and can be rearranged, but remains inert and is greyed
out with a "feature not enabled" reason in the menu, in **More**, and in the
customization dialog. A server state that still leaves the page usable does not
grey the entry: while the scheduler is paused, **Scheduled tasks** stays a
normal link and the page explains that automatic runs are off. Moving an entry
into **More** changes only the sidebar, not the page's route or its permissions.
**Search** can be collapsed into **More**, and **⌘K / Ctrl+K** continues to
open search.

The layout is saved in this browser, not on the account: accounts signed in to
the same browser share it, and another browser or device keeps its own menu.
Cleared storage or an unreadable layout falls back to the shipped order, and
entries added in a newer version are inserted at the position their default
order implies even when an older saved layout does not mention them. A saved
entry whose visible neighbors are all hidden stays at the end of its group.

## Search conversations and messages

Use **Search** in the sidebar or **⌘K / Ctrl+K** to find conversation titles and
visible user/assistant message text, including code. Filter by conversations or
messages and include archived chats. Results show matching excerpts; selecting a
message opens its historical context, with earlier/later navigation and a **Return
to latest messages** button. Type `>` for new chat, settings and keyboard commands.
Title search is built in. Enable message search with the packaged
[workspace search extension](../../examples/deerflow-extension-workspace-search/README.md).
Its first search backfills existing history and shows progress while indexing.

## Chat Archive

Deleting a chat from the sidebar requires confirmation showing its title. Deletion removes the conversation and its files and cannot be undone.

Use **Archive chat** in a recent chat's sidebar menu to hide completed work while keeping its messages, files, and original link. The success message offers **Undo**. Open **Chats → Archived** to find archived conversations and restore them individually; an open archived conversation also shows a restore button in its header. Search filters the titles of loaded conversations, with **Load more** for older entries.

Archive and restore preserve the chat's activity time and pinned state. Archiving does not stop a running task or pause its schedules, and new activity does not automatically restore it. Use the existing Delete action when you intend to remove a conversation and its files.

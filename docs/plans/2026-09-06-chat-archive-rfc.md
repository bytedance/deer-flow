# RFC: Single-chat archive and restore

Status: Proposed for review in [PR #5236](https://github.com/bytedance/deer-flow/pull/5236).

## Why

Completed work accumulates in recent chats. Users need to hide it while keeping conversations and artifacts available. Pinning prioritizes work but does not remove clutter; deleting removes content users may need again.

[ChatGPT](https://help.openai.com/en/articles/8809935-how-to-delete-and-archive-chats-in-chatgpt) and [Open WebUI](https://docs.openwebui.com/features/chat-conversations/data-controls/archived-chats/) provide archive/restore for this purpose. These establish a familiar interaction, not measured demand from DeerFlow users. The earlier [#3032](https://github.com/bytedance/deer-flow/pull/3032#issuecomment-4648439072) was closed with guidance to separate additional functionality into smaller PRs; this proposal covers single-chat organization only.

## Proposal

- Add **Archive chat** to the sidebar menu and **Undo** to its success toast. Keep an open conversation at its original URL.
- Add **Recent chats / Archived** tabs above the Chats search field. Archived rows offer **Restore chat**; opening an archived chat also exposes restore in both default and custom-agent headers.
- Preserve messages, files, ownership, pin state and activity time. Archiving does not stop runs or pause schedules. New activity stays archived until explicitly restored.

## Contract

Use the existing owner-checked metadata PATCH with boolean `deerflow_archived`. Archive/restore writes do not touch `updated_at`; no new table or migration is required.

`POST /api/threads/search` accepts optional `archived`: `true` selects only JSON boolean true, `false` includes missing/null/non-true legacy flags, and omitted/null preserves existing unfiltered behavior. SQL and Memory stores apply this filter before pagination. Web lists explicitly choose a view through authenticated Gateway requests because the SDK does not forward this extension.

After a successful write, reconcile metadata and reset list pagination. Cancel stale reads and merge only the changed flag so concurrent pin responses cannot undo archive state. Failed writes leave the visible chat intact.

## Scope and tradeoffs

Exclude bulk actions, automatic archiving/restoration, folders, deletion changes and full-text search. Title search retains its existing loaded-page scope and explicit load-more action. Explicit restoration avoids background activity unexpectedly repopulating recent chats; UI copy explains that running work continues.

## Acceptance

Verify archive, undo, reload and restore on desktop/mobile; legacy rows and filtering before pagination; owner isolation; unchanged activity/pin state; original links and artifact downloads; failed writes and concurrent cache updates. The PR records test results and limitations. Implementation invariants live in [Thread lifecycle](../../backend/docs/THREAD_LIFECYCLE.md).

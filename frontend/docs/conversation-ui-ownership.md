# Conversation UI ownership

This expands the ownership index in `frontend/src/AGENTS.md`.

- `src/components/workspace/model-picker-content.tsx` owns the compact model
  list, favorite grouping, and the anchored non-modal picker shared by the main
  composer and Side Chat. Each row keeps model selection and its inline
  favorite star as sibling buttons. The picker deliberately follows the
  pre-favorites two-line row density and does not add a search field. Favorites
  are stored by
  `core/models/favorites-store.ts` under a user-scoped browser key and only
  reorder derived display arrays: never sort `useModels().models`, promote a
  favorite to the default model, prune a temporarily unavailable favorite, or
  merge the main and Side Chat selection callbacks. Keep favorite buttons out
  of model-selection buttons; the two call sites continue to own their triggers
  and their distinct mode/reasoning-effort transitions.
- `src/app/workspace/chats/[thread_id]/page.tsx` owns composer busy-state wiring.
- `src/app/workspace/chats/[thread_id]/page.tsx` owns branch-from-turn submission and navigation; sidecar `MessageList` instances do not receive the branch action.
- `core/threads/thread-branch-tree.ts` projects only loaded, same-pin branch lineage into Recent chats. Missing, malformed, cross-pin, self, or cyclic parents stay top-level; unpinned groups follow their freshest descendant while pinned root order stays stable. `recent-chat-list.tsx` caps visual indentation without changing the recursive order.
- `src/app/workspace/chats/[thread_id]/page.tsx` and `src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` own edit-and-rerun submission wiring because the page must preserve normal/custom-agent run context; `MessageList` only detects the latest editable user turn and renders the inline editor.
- `src/app/workspace/chats/[thread_id]/page.tsx` gates the Workspace Browser trigger and browser right panel on `/api/features -> browser_control.enabled`; `src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` applies the same capability gate and additionally requires the Custom Agent's tool groups to be unrestricted or include `browser`. Default/failed feature discovery hides the browser control so optional backend installs do not show a dead Live socket.
- `src/app/workspace/chats/[thread_id]/page.tsx` and `src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` own active-goal display state for their composer overlays.
- `src/components/workspace/messages/message-list.tsx` owns human-input card answered/latest/pending gating; entry pages only translate a submitted card response into `sendMessage` calls.
- `src/components/workspace/browser-view/browser-view-panel.tsx` forwards each physical pointer click as one `click` input; do not also emit `down`/`up` for the same gesture because the remote Playwright click would run twice.
- `src/components/workspace/browser-view/use-browser-stream.ts` requests binary JPEG
  frames with `frame_format=binary`; status, URL, tabs, and navigation rejection
  messages remain JSON. `LatestBrowserFrameBuffer` keeps only the newest pending
  frame, publishes through `useSyncExternalStore` at most once per animation
  frame, and owns object-URL revocation. Keep the Gateway's legacy JSON/base64
  frame path for older clients.

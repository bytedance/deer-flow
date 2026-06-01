## Context

`TokenUsageIndicator` was a header button in the chat workspace that opened a popover showing cumulative token usage (input/output/total) for the current thread. It was gated by `useModels.tokenUsageEnabled` and persisted user preferences (`inlineMode`) via `localSettings.tokenUsage`.

The indicator has already been removed from both chat page headers (`chats/[thread_id]/page.tsx` and `agents/[agent_name]/chats/[thread_id]/page.tsx`). What remains:

- `tokenUsageInlineMode` is still passed to `MessageList` to render per-message token badges
- `useModels.tokenUsageEnabled` and `localSettings.tokenUsage` are still wired
- `TokenUsageIndicator` component itself still exists but is now dead code

This design covers the full cleanup and relocation.

## Goals / Non-Goals

**Goals:**
- Add a read-only "Token 用量" section to the settings dialog
- Remove `tokenUsageInlineMode` from `MessageList` entirely
- Clean up dead code: `TokenUsageIndicator` component, `useModels.tokenUsageEnabled`, `localSettings.tokenUsage`, and related types
- Keep settings dialog architecture consistent with existing sections (side nav + content panel)

**Non-Goals:**
- Changing how the backend reports token usage (stream events remain unchanged)
- Adding per-thread token history or persistence
- Modifying the admin dashboard token charts

## Decisions

1. **Settings section, not a popover**: Placing token usage in the settings dialog aligns with the principle that cost/usage monitoring is a secondary concern, not a primary workflow action. The settings dialog already has a sidebar navigation pattern with sections like account, appearance, memory, etc.

2. **Full removal of inline mode**: Once the header indicator is gone, the `tokenUsageInlineMode` inside `MessageList` serves no coherent purpose. Per-message token badges without a header summary are orphaned UX. Remove the entire feature rather than keeping half of it.

3. **No settings section icon for "cost" category**: The existing settings uses lucide icons per section. `CoinsIcon` or `BarChart3Icon` would work for token usage.

4. **Data source**: Token data comes from `thread.messages` — the same array already used by the removed `TokenUsageIndicator`. The settings page receives thread context via `ThreadContext` (already available) or can compute totals from messages passed in.

5. **Settings section type extension**: Add `"token-usage"` to the `SettingsSection` union type. Follow the existing pattern: import the page component, add a nav entry, add conditional rendering in the content area.

## Risks / Trade-offs

- **No real-time update when settings dialog is closed**: Token usage only refreshes when the dialog is open. This is acceptable — the original popover had the same limitation.
- **i18n keys**: The `settings.sections` object needs a new key for the nav label. Both zh-CN (`"Token 用量"`) and en-US (`"Token Usage"`) need entries.

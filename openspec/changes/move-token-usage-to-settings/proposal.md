## Why

Token usage display clutters the chat workspace header and conflicts with the industrial-first UX principle — operators don't monitor LLM costs in real-time. Moving it to a settings sub-page keeps it accessible for cost-aware users without polluting the primary workflow surface.

## What Changes

- **BREAKING**: Remove `TokenUsageIndicator` from chat page headers (already done in a prior change)
- Add a "Token 用量" (Token Usage) section to the workspace settings dialog
- Remove `tokenUsageInlineMode` from `MessageList` — inline token display inside message bubbles goes away entirely
- Clean up stale wiring: `useModels.tokenUsageEnabled`, `localSettings.tokenUsage` preferences, and associated type definitions
- The new settings sub-page shows cumulative session token usage (input/output/total) in a read-only summary

## Capabilities

### New Capabilities
- `token-usage-settings`: A settings sub-page that displays cumulative token usage for the current session, replacing the removed header indicator

### Modified Capabilities
_None_ — existing spec-level behavior is unchanged; this is a pure relocation of the display surface.

## Impact

- **Components**: `TokenUsageIndicator` (already unused), `MessageList` (remove `tokenUsageInlineMode` prop), `SettingsDialog` (add token section)
- **State**: `localSettings.tokenUsage`, `useModels.tokenUsageEnabled`
- **Types**: `TokenUsagePreferences` in settings type definitions
- **i18n**: Existing `tokenUsage` translation keys may be reused or adapted

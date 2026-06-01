## 1. Create token-usage settings page

- [ ] 1.1 Create `frontend/src/components/workspace/settings/token-usage-settings-page.tsx` — read-only summary showing input/output/total tokens from the current thread, with empty state when no usage data is available

## 2. Wire settings dialog

- [ ] 2.2 Add `"token-usage"` to `SettingsSection` union type in [settings-dialog.tsx](frontend/src/components/workspace/settings/settings-dialog.tsx)
- [ ] 2.3 Add nav entry (icon + label) and conditional rendering for token-usage section
- [ ] 2.4 Add `settings.sections.tokenUsage` i18n key in zh-CN.ts (`"Token 用量"`) and en-US.ts (`"Token Usage"`)

## 3. Remove tokenUsageInlineMode from MessageList

- [ ] 3.1 Remove `tokenUsageInlineMode` prop from `MessageList` component and its internal rendering logic
- [ ] 3.2 Remove `tokenUsageInlineMode` computation and prop pass in `chats/[thread_id]/page.tsx`
- [ ] 3.3 Remove `tokenUsageInlineMode` computation and prop pass in `agents/[agent_name]/chats/[thread_id]/page.tsx`

## 4. Clean up stale state and types

- [ ] 4.1 Remove `tokenUsage` from `DEFAULT_LOCAL_SETTINGS` and `LocalSettings` type in [local.ts](frontend/src/core/settings/local.ts)
- [ ] 4.2 Remove `tokenUsageEnabled` from `useModels` hook in [hooks.ts](frontend/src/core/models/hooks.ts)
- [ ] 4.3 Remove `TokenUsageInlineMode` type from [usage-model.ts](frontend/src/core/messages/usage-model.ts) if no other consumers exist
- [ ] 4.4 Delete dead component `token-usage-indicator.tsx` if no other consumers exist

## 5. Verify

- [ ] 5.1 Run `pnpm typecheck` — ensure zero new type errors
- [ ] 5.2 Manually verify settings dialog shows "Token 用量" section and renders correctly with thread data

## 1. Promote knowledge base to top-level sidebar item

- [x] 1.1 Add knowledge base `SidebarMenuItem` in `workspace-nav-chat-list.tsx` between "对话历史" and "智能体", using `BookOpenIcon` and linking to `/workspace/knowledge-bases`
- [x] 1.2 Active state highlights when `pathname.startsWith("/workspace/knowledge-bases")`

## 2. Remove tools collapsible menu from sidebar

- [x] 2.1 Remove the entire "工具" `<Collapsible>` block (lines 197-262) from `workspace-nav-chat-list.tsx`
- [x] 2.2 Remove `TOOLS_MENU_KEY` constant, `toolsOpen` state, and related `useEffect`
- [x] 2.3 Clean up unused imports (`WrenchIcon`, `BugIcon`, `Settings2Icon`) if no other consumers in the file

## 3. Rebuild ToolSettingsPage with embedded tabs

- [x] 3.1 Wrap `tool-settings-page.tsx` content in shadcn `Tabs` with three tabs: "工具管理" / "平台能力" / "A2UI 调试"
- [x] 3.2 "工具管理" tab (default): existing MCP server list
- [x] 3.3 "平台能力" tab: embed `CapabilitiesPage` list view with internal state for list↔detail navigation. Extract detail view as a reusable component accepting `capType`/`capName` props instead of `useParams`
- [x] 3.4 "A2UI 调试" tab: directly render `<A2UIDebugPanel />`

## 4. Add i18n keys

- [x] 4.1 Add `settings.tools.tabs.toolManagement`, `settings.tools.tabs.capabilities`, `settings.tools.tabs.a2uiDebug` to zh-CN and en-US locales
- [x] 4.2 Add tab label types to `Translations` interface in `types.ts`

## 5. Verify

- [x] 5.1 Run `pnpm typecheck` — zero new source errors
- [ ] 5.2 Visual check: sidebar shows knowledge base as top-level item, no tools menu
- [ ] 5.3 Visual check: settings → tools shows three tabs with correct embedded content

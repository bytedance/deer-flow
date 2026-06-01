## 1. Create budget settings page

- [ ] 1.1 Create `budget-settings-page.tsx` — reuse `useBudgetStatus()` from BudgetIndicator to render daily/monthly cost with progress bars and warning states

## 2. Wire settings dialog

- [ ] 2.1 Add `"budget"` to `SettingsSection` union type in settings-dialog.tsx
- [ ] 2.2 Add nav entry (CoinsIcon + label) and conditional rendering for budget section
- [ ] 2.3 Add `settings.sections.budget` i18n key: zh-CN `"费用用量"`, en-US `"Cost & Quota"`

## 3. Remove BudgetIndicator from sidebar

- [ ] 3.1 Remove `<BudgetIndicator />` from workspace-sidebar.tsx SidebarFooter
- [ ] 3.2 Remove BudgetIndicator import if no other consumers

## 4. Verify

- [ ] 4.1 Run `pnpm typecheck` — zero new source errors
- [ ] 4.2 Visually check settings dialog shows budget section and sidebar no longer shows budget indicator

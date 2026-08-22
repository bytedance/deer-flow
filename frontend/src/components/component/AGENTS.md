# Workspace component kit (`src/components/component/`)

Shared UI primitives for workspace resource index pages: list/card layouts, page
chrome, and create/edit dialogs.

**Current adoption:** only the Chats index (`app/workspace/chats/page.tsx`) uses
this kit today. Agents, scheduled tasks, settings, and other workspace pages are
unchanged; migrate them in follow-up PRs rather than assuming they already use
these APIs.

## Import rules

- Resource **pages** under `src/app/workspace/**`: import kit APIs from `@/components/component` plus unmodified `@/components/ui/*`.
- **Feature-specific** row/card/dialog bodies live under `@/components/workspace/<feature>/` (e.g. `ChatListRow`), not in this directory.
- Do **not** edit `ui/`, `ai-elements/`, or unrelated paths under `components/` when building resource pages.
- Import the **public barrel** (`@/components/component`). Tailwind tokens in `styles.ts` are kit-internal; they are not re-exported from the barrel.

## Mental model (three layers)

```
Shell                          ← full-height layout: header slot + scroll body
  ShellHeader                  ← page h1, description, create/import actions
  WorkspaceIndexList           ← bordered list panel (optional search + pagination)
    children                   ← ItemRow slots or feature *ListRow components
```

- **`ShellHeader`** = index page title bar (sticky glass strip).
- **`Shell` / `shell.tsx`** = UI page frame in this kit — not Next.js `app/.../layout.tsx`, not sandbox/bash “shell”.
- **`Header`** (`header.tsx`) = **sub-page** bar with back link — not the same as `ShellHeader`.
- **`ItemListPanel` title** = section heading inside the panel (h2), not the page h1.

## Default: flush list index page

Reference: `src/app/workspace/chats/page.tsx`.

```tsx
import { Shell, ShellHeader, WorkspaceIndexList } from "@/components/component";
import { MyListRow } from "@/components/workspace/my-feature/my-list-row";

<Shell
  fillBody={rows.length === 0}
  header={
    <ShellHeader
      title={t.my.pageTitle}
      description={t.my.pageDescription}
      actions={<HeaderCreateButton onClick={…}>{t.common.create}</HeaderCreateButton>}
    />
  }
>
  <WorkspaceIndexList
    title={t.my.listTitle}
    countLabel={…}
    search={{
      value: search,
      onChange: setSearch,
      placeholder: t.my.searchPlaceholder,
    }}
    pagination={{
      hasNextPage,
      isFetchingNextPage,
      onLoadMore: fetchNextPage,
      loadMoreLabel: t.my.loadMore,
      loadMoreSearchLabel: t.my.loadMoreToSearch,
      loadingLabel: t.common.loading,
      listLength: loadedCount,
    }}
    isEmpty={loadedCount === 0}
    empty={t.my.empty}
    isSearchEmpty={isSearching && filtered.length === 0}
    searchEmpty={t.my.searchEmpty}
  >
    {filtered.map((item) => (
      <MyListRow key={item.id} item={item} />
    ))}
  </WorkspaceIndexList>
</Shell>
```

### `WorkspaceIndexList` options

| Prop                            | Purpose                                                                                                                                                                                                   |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `search?`                       | Toolbar search field (`Search`); optional `autoFocus` for pages that want the filter focused on land. When the query is non-empty, infinite scroll auto-load is off and the panel footer shows load-more. |
| `pagination?`                   | Infinite scroll sentinel + loading line; search-mode footer. Wire to TanStack `useInfiniteQuery` (or similar).                                                                                            |
| `toolbar?`                      | Extra filters beside search (`ListFilterField`, custom controls).                                                                                                                                         |
| `isLoading` / `loadingLabel`    | Initial fetch placeholder.                                                                                                                                                                                |
| `isEmpty` / `empty`             | No data at all.                                                                                                                                                                                           |
| `isSearchEmpty` / `searchEmpty` | Filter returned zero rows but loaded data exists.                                                                                                                                                         |
| `countLabel`                    | Shown next to panel title (i18n strings from the page).                                                                                                                                                   |

Helper: `formatItemListCountLabel({ shownCount, loadedCount, hasNextPage, isFiltering })` for common count patterns.

## Card index (grid, future pages)

For card-style indexes (e.g. Agents gallery), use **`ItemGrid`**, **`ItemCard`**,
**`ItemCardIcon`**, **`ItemCardBadge`**, **`itemMetaTags`**, **`CardAction`** from
`item.tsx`. Same `Shell` + `ShellHeader`; body is a grid instead of
`WorkspaceIndexList`.

## List row building blocks

For flush rows inside `WorkspaceIndexList` (or `ItemList`):

| Component                           | Role                                                                                                                                                                                                                                  |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ItemRow`                           | Two-line flush row; pass `href` on the row for full-row navigation (title, preview, meta). Row actions stay outside the link and stop propagation. Slots: `topStart` / `topEnd` / `bottomStart` / `bottomEnd`, or legacy flush props. |
| `ItemRowTitle`                      | Primary line only. Do not pass `href` when the parent `ItemRow` already has `href`.                                                                                                                                                   |
| `ItemRowSubtitle`                   | Secondary line under title.                                                                                                                                                                                                           |
| `ItemRowMeta`                       | Bottom meta row.                                                                                                                                                                                                                      |
| `ItemRowStatusBadge` / `ItemRowTag` | Status and kind chips.                                                                                                                                                                                                                |
| `CardAction`                        | Icon button for row/card actions.                                                                                                                                                                                                     |
| `dotSeparatedMeta`                  | Join meta segments with middots.                                                                                                                                                                                                      |

Prefer a thin feature wrapper (e.g. `ChatListRow`) that composes these slots.

## Dialogs (create / edit / confirm, future pages)

Chats uses feature-local rename/delete dialogs in `ChatListRow` today; the kit
dialog primitives below are for upcoming page migrations.

| Component                                                                                              | Role                                             |
| ------------------------------------------------------------------------------------------------------ | ------------------------------------------------ |
| `FormDialog`                                                                                           | Standard create/edit modal with footer actions.  |
| `ConfirmDialog`                                                                                        | Delete/revoke confirm.                           |
| `DialogShell`                                                                                          | Lower-level layout (title, scroll body, footer). |
| `DialogFormSection` / `DialogFieldGrid`                                                                | Grouped fields.                                  |
| `DialogInputField`, `DialogTextareaField`, `DialogSelectField`, `DialogToggleField`, `DialogSlotField` | Form controls with shared spacing.               |
| `FormActions`                                                                                          | Cancel/save row (also usable outside dialogs).   |
| `FormDialogDeleteButton`                                                                               | Outline delete in edit footer.                   |
| `dialogSaveFooterProps`, `buildFormDialogEditResourceMeta`                                             | Footer labels and audit meta helpers.            |

Supporting controls: **`FormField`**, **`FormSelect`**, **`Toggle`**, **`Search`** (toolbar or standalone).

## Layout & chrome (advanced)

| Component                                    | When to use                                              |
| -------------------------------------------- | -------------------------------------------------------- |
| `Shell` / `ShellHeader`                      | Standard workspace index layout.                         |
| `SplitView`                                  | Master/detail (sidebar + main) on large screens.         |
| `Header`                                     | Detail/sub-page with back navigation.                    |
| `HeaderCreateButton` / `HeaderOutlineButton` | Actions in `ShellHeader`.                                |
| `Section`                                    | Titled blocks inside a scroll body (forms, settings).    |
| `ItemListPanel` + `ListPanelToolbar`         | Custom list layout without `WorkspaceIndexList` helpers. |
| `ItemList`                                   | List container only (`variant="flush"` \| `"card"`).     |

## Empty states & errors

Not user/run **feedback** (see `core/api/feedback.ts`). These are list/page placeholders and inline error banners.

| Component        | When to use                                                                |
| ---------------- | -------------------------------------------------------------------------- |
| `PanelEmpty`     | Empty copy inside `WorkspaceIndexList` / panel.                            |
| `ListEmpty`      | Dashed bordered empty inside cards/sections.                               |
| `PageEmptyState` | Full-body centered empty (title + optional description).                   |
| `InlineEmpty`    | Base dashed empty block; used by `ListEmpty` / `PanelEmpty`.               |
| `AlertError`     | Destructive alert for load/save errors (see `alert.tsx` for more presets). |

Implementation: `empty.tsx`, `alert.tsx`.

## File map (implementation)

| File                                                   | Contents                                                                                        |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| `shell.tsx`                                            | `Shell`, `ShellHeader`, `SplitView` — workspace page frame (not Next.js `layout.tsx`, not bash) |
| `list.tsx`                                             | `WorkspaceIndexList`, rows, toolbar fields, pagination internals                                |
| `item.tsx`                                             | Card grid, row badges, `CardAction`                                                             |
| `dialogs.tsx`                                          | Dialog system                                                                                   |
| `header.tsx`                                           | Sub-page `Header`, header action buttons                                                        |
| `search.tsx`                                           | `Search`                                                                                        |
| `select.tsx`, `toggle.tsx`, `form-field.tsx`           | Form controls                                                                                   |
| `empty.tsx`, `alert.tsx`, `section.tsx`, `tooltip.tsx` | Empty states, alert presets, sections, tooltips                                                 |
| `styles.ts`                                            | Shared Tailwind class tokens (kit-internal)                                                     |
| `index.ts`                                             | Public exports                                                                                  |

## Checklist for a new resource index page

1. Page component in `app/workspace/…` — data hooks, filter state, i18n.
2. `Shell` + `ShellHeader` + `WorkspaceIndexList` (or card grid).
3. Feature `*ListRow` or `ItemRow` composition under `components/workspace/<feature>/`.
4. Create/edit via `FormDialog` + `Dialog*Field` on the page or in a feature dialog component.
5. Run `pnpm check` before commit.

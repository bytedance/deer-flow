## 1. Rewrite TodoCountIndicator component

- [x] 1.1 Replace the three-badge layout with a single `BellIcon` button (ghost + icon size)
- [x] 1.2 Add a total count badge indicator on the bell when total > 0, with amber highlight
- [x] 1.3 Wrap in `DropdownMenu` with `DropdownMenuContent` containing three read-only rows (异常/启机/停机) with icons, labels, counts, and color-coded indicators
- [x] 1.4 Remove the `CountBadge` internal component (no longer needed)
- [x] 1.5 Keep the existing `useCallback` + `useEffect` data-fetching logic unchanged

## 2. Verify

- [x] 2.1 Run `pnpm typecheck` — zero new source errors
- [ ] 2.2 Visual check: header shows single bell icon instead of three badges; click opens dropdown with todo counts

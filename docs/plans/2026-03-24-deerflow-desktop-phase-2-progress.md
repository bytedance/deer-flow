# DeerFlow Desktop Phase 2 Progress

## Scope Lock

- Keep all WebView traffic on the existing DeerFlow origin only.
- Preserve the Phase 1 web/business-logic ownership split.
- Do not add agent-window support, sidecars, backend/service management, or cloud-backend migration.
- Keep frontend changes out of Card 1.
- Card 1 only adds tray entrypoint and main-window visibility controls.
- Do not include Card 2+ features in Card 1: global shortcut, autostart, file-drop, updater.
- Card 2 only adds a desktop-global main-window shortcut plus autostart wiring; it does not move chat shortcut ownership into Rust.

## Dependency Graph

`1 -> 2 -> 3 -> 4`

## Card Board

| ID | Status | Depends | Goal | Files | Verification |
|---|---|---|---|---|---|
| 1 | done | - | Add tray entrypoint and main-window visibility controls | `desktop/src-tauri/Cargo.toml`, `desktop/src-tauri/src/lib.rs`, `desktop/src-tauri/src/tray.rs` | `cargo test` passed; manual tray/show/hide/quit verification recorded below |
| 2 | done | 1 | Add global shortcut and autostart integration | `desktop/src-tauri/Cargo.toml`, `desktop/src-tauri/Cargo.lock`, `desktop/src-tauri/src/lib.rs`, `desktop/src-tauri/src/desktop_integration.rs` | red `cargo test` failure observed first; fresh `cargo test` then passed; `pnpm tauri dev` loaded autostart wiring before the known Windows GUI exit-code false negative; direct debug-exe verification confirmed the desktop shortcut restores and focuses the main window |
| 3 | pending | 2 | Add desktop file drag-and-drop bridge | `desktop/src-tauri/...`, `frontend/...` | not started |
| 4 | pending | 3 | Add updater and distribution groundwork | `desktop/package.json`, `desktop/src-tauri/...`, `docs/plans/...` | not started |

## Current Handoff

- Current card: 1
- Status: complete with follow-up verification notes recorded here
- Product commit: `c270e62` (`feat(desktop): add tray-based window controls`)
- Files in Card 1 product scope:
  - `desktop/src-tauri/Cargo.toml`
  - `desktop/src-tauri/src/lib.rs`
  - `desktop/src-tauri/src/tray.rs`
- Working-tree additions in this follow-up are documentation/evidence only.
- Known verification deviation:
  - `pnpm tauri dev` in this Windows environment can launch the app but later report a misleading `0xffffffff` GUI exit code.
  - Because of that environment noise, the follow-up manual checks used the built debug executable plus direct process/window inspection.

## Card 1 Verification

### Automated Verification

- Command:
  - `cd desktop/src-tauri`
  - `cargo test`
- Result:
  - Passed.
- Evidence:
  - `docs/plans/2026-03-24-deerflow-desktop-phase-2-card1-cargo-test.txt`

### Manual Verification Notes

- `Show DeerFlow`
  - The user manually verified that selecting `Show DeerFlow` displayed the DeerFlow desktop window.
  - Supporting system evidence was captured while the app was visible:
    - `docs/plans/2026-03-24-deerflow-desktop-phase-2-card1-show-window-check.json`
  - That check shows a visible top-level window with:
    - `ClassName = "Tauri Window"`
    - `Title = "DeerFlow"`

- `Hide DeerFlow`
  - The user reported that after selecting `Hide DeerFlow`, a black `deerflow-desktop.exe` window still remained.
  - Root-cause investigation showed this was the debug console window, not the Tauri main window.
  - Supporting system evidence was captured immediately after `Hide DeerFlow`:
    - `docs/plans/2026-03-24-deerflow-desktop-phase-2-card1-hide-window-check.json`
  - That check shows:
    - `ClassName = "Tauri Window"`, `Title = "DeerFlow"`, `Visible = false`
    - `ClassName = "ConsoleWindowClass"`, `Visible = true`
  - Interpretation:
    - `Hide DeerFlow` successfully hid the DeerFlow Tauri main window.
    - The remaining black window is expected debug-build console noise, because `desktop/src-tauri/src/main.rs` only disables the console window outside debug builds.

- `Quit`
  - `Quit` was manually triggered during follow-up verification.
  - Supporting system evidence:
    - `docs/plans/2026-03-24-deerflow-desktop-phase-2-card1-quit-process-check.txt`
  - Result:
    - No `deerflow-desktop` process remained after the quit check.

- `Tray icon appears`
  - The user manually verified the DeerFlow tray icon was visible during follow-up review.
  - No desktop screenshot was retained in-repo for this item because the user preferred not to archive desktop screenshots from their cluttered desktop.

## Verification Matrix

- [x] Tray icon appears
- [x] `Show DeerFlow` displays the main window
- [x] `Hide DeerFlow` hides the Tauri main window without crashing the app
- [x] `Quit` exits the desktop app cleanly
- [x] Scope lock remained intact for Card 1 only

## Session Log

### Entry Template

```md
### YYYY-MM-DD HH:mm
- Card: 1
- Status: in_progress | blocked | done
- Executor: Codex
- Files touched:
  - `path/to/file`
- Commands run:
  - `command`
- Result summary:
- Blockers / deviations:
- Next recommended action:
```

### 2026-03-24 22:00

- Card: 1
- Status: done
- Executor: Codex
- Files touched:
  - `desktop/src-tauri/Cargo.toml`
  - `desktop/src-tauri/src/lib.rs`
  - `desktop/src-tauri/src/tray.rs`
- Commands run:
  - `cd desktop/src-tauri && cargo test`
  - `cd desktop && pnpm tauri dev`
  - direct launch of `desktop/src-tauri/target/debug/deerflow-desktop.exe`
- Result summary:
  - Card 1 tray behavior was implemented and committed in `c270e62`.
  - Rust tests passed.
  - The desktop shell launched and the DeerFlow main window was reachable.
- Blockers / deviations:
  - `pnpm tauri dev` reported misleading GUI exit codes in this Windows environment, so direct executable launch was used as a fallback verification path.
- Next recommended action:
  - Record explicit follow-up evidence for show/hide/quit before starting Card 2.

### 2026-03-24 22:59

- Card: 1
- Status: done
- Executor: Codex + user-assisted manual verification
- Files touched:
  - `docs/plans/2026-03-24-deerflow-desktop-phase-2-progress.md`
  - `docs/plans/2026-03-24-deerflow-desktop-phase-2-card1-cargo-test.txt`
  - `docs/plans/2026-03-24-deerflow-desktop-phase-2-card1-show-window-check.json`
  - `docs/plans/2026-03-24-deerflow-desktop-phase-2-card1-hide-window-check.json`
  - `docs/plans/2026-03-24-deerflow-desktop-phase-2-card1-quit-process-check.txt`
- Commands run:
  - `cargo test`
  - top-level Windows window enumeration for the `deerflow-desktop` process while visible
  - top-level Windows window enumeration for the `deerflow-desktop` process after `Hide DeerFlow`
  - `Get-Process deerflow-desktop -ErrorAction SilentlyContinue`
- Result summary:
  - `Show DeerFlow` was confirmed with a visible `Tauri Window` titled `DeerFlow`.
  - `Hide DeerFlow` was confirmed by inspection: the `Tauri Window` became hidden while the remaining black window was only the debug console.
  - `Quit` was confirmed by the absence of a running `deerflow-desktop` process.
- Blockers / deviations:
  - Tray-icon visibility was manually confirmed by the user, but no in-repo desktop screenshot was retained because the user preferred not to archive desktop screenshots.
- Next recommended action:
  - Treat Card 1 as complete and proceed to Card 2 only when the next assignment is given.

### 2026-03-24 23:45

- Card: 2
- Status: done
- Executor: Codex
- Files touched:
  - `desktop/src-tauri/Cargo.toml`
  - `desktop/src-tauri/Cargo.lock`
  - `desktop/src-tauri/src/lib.rs`
  - `desktop/src-tauri/src/desktop_integration.rs`
- Commands run:
  - `cd desktop/src-tauri && cargo test`
  - `cd desktop/src-tauri && cargo test` after adding the red helper tests
  - `cd desktop/src-tauri && cargo test` after wiring the plugins
  - `cd desktop && pnpm install`
  - `cd desktop && pnpm tauri dev`
  - direct launch of `desktop/src-tauri/target/debug/deerflow-desktop.exe`
  - Windows window enumeration + `ShowWindowAsync(..., 6)` + low-level `Ctrl+Shift+Alt+D` key injection
- Result summary:
  - Added a desktop-global shortcut dedicated to `show-or-focus-main-window` and kept the existing Phase 1 in-page chat shortcut ownership untouched.
  - Added autostart plugin wiring plus desktop-side persisted default state in the Tauri store; the first launch defaults to disabled until a saved desktop preference exists.
  - Fresh Rust tests passed after the new helper coverage was implemented.
  - Live Windows verification confirmed the DeerFlow `Tauri Window` moved from `IsIconic = true`, `Foreground = false` after manual minimize to `IsIconic = false`, `Foreground = true` after the global shortcut fired.
- Blockers / deviations:
  - `desktop/src-tauri/tauri.conf.json` and `frontend/src/lib/tauri.ts` were inspected but did not require code changes for this card. The full Card 2 wiring lived in Rust and did not need a new frontend bridge or config mutation.
  - `pnpm tauri dev` in this Windows environment still reports the known misleading GUI exit code `0xffffffff` after launching the app, so direct debug-executable launch was used for the trustworthy window-level shortcut verification.
- Next recommended action:
  - Proceed to Card 3 only. Keep Card 3 scoped to native file drag-and-drop bridging and preserve the same frontend ownership boundary used in Card 2.

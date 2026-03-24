# DeerFlow Desktop Phase 2 Release Notes

## Status

- This document records the Card 4 updater and distribution baseline for DeerFlow Desktop Phase 2.
- Scope remains limited to the existing Tauri desktop shell over the current DeerFlow web origin at `http://localhost:2026`.
- This card does not add backend bundling, sidecars, agent-window support, or a custom release pipeline.

## Integrated Baseline

- This updater/distribution groundwork is integrated with the Phase 2 global shortcut, autostart, and native file-drop bridge on the final integration branch.
- The shared desktop bootstrap in `desktop/src-tauri/src/lib.rs` now starts the updater wiring alongside the desktop integration and tray setup.

## Card 4 Additions

- The Rust desktop bootstrap now includes the official `tauri-plugin-updater` dependency.
- Updater bootstrap is intentionally environment-driven only for secrets:
  - `DEERFLOW_UPDATER_PUBLIC_KEY`
  - `TAURI_SIGNING_PRIVATE_KEY`
  - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
- Default feed shape is documented in `desktop/src-tauri/tauri.conf.json` and validated in Rust as:
  - `https://updates.example.invalid/deerflow/<channel>/{{target}}/{{arch}}/{{current_version}}`
- If `DEERFLOW_UPDATER_PUBLIC_KEY` is missing, the updater plugin stays idle and the desktop shell still starts.
- If `TAURI_SIGNING_PRIVATE_KEY` is missing, development builds still work, but the shell emits a reminder that signed updater artifacts are not ready yet.

## Build Commands

- Debug packaging smoke test:
  - `pnpm tauri build --debug`
- Optional convenience aliases:
  - `pnpm tauri:build:debug`
  - `pnpm tauri:build:release`
  - `pnpm tauri:signer:generate`
- Release signing prerequisites:
  - Generate a Tauri updater signing keypair before the first signed release.
  - Export `DEERFLOW_UPDATER_PUBLIC_KEY` to the public key value used by release builds.
  - Export `TAURI_SIGNING_PRIVATE_KEY` before building signed updater artifacts.
  - Export `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` if the private key is password-protected.

## Packaging Notes

### Windows

- `pnpm tauri build --debug` is the baseline verification command for this card.
- Release builds should produce the normal Tauri Windows installer outputs under `desktop/src-tauri/target/`.
- The updater config uses passive Windows install mode so install prompts stay closer to standard desktop expectations.
- Debug builds may still show a console window because `desktop/src-tauri/src/main.rs` only suppresses it outside debug mode.

### macOS

- macOS remains a documented first-class packaging target, but this card only establishes release notes and updater placeholders from Windows.
- Expected release artifacts are the standard Tauri macOS app bundle and disk image when built on macOS.
- Signing, notarization, and Apple certificate handling are still manual follow-up work for a future release pass.
- The repository currently only tracks `desktop/src-tauri/icons/icon.ico`, so macOS-specific icon assets still need to be added before polished macOS distribution.

## Verification

- Automated verification for Card 4:
  - `cargo test` in `desktop/src-tauri/`
  - `pnpm tauri build --debug` in `desktop/`
- Result on the final integration branch:
  - updater helper validation passed inside the full desktop test suite
  - the debug desktop build completed and produced Windows MSI and NSIS bundles

## Known Gaps

- There is still no desktop CI release workflow under `.github/workflows/`.
- The updater endpoint remains a documented placeholder until a real release feed exists.
- Signed updater artifacts are intentionally not enabled by default in `tauri.conf.json` yet.

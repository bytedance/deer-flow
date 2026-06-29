- [x] Replace the new-thread composer centering strategy with a normal-flow layout that does not use viewport-based translate offsets.
- [x] Keep the existing docked composer behavior for non-new-thread chat pages.
- [x] Add an EHM host -> DeerFlow viewport resume message for iframe first-load and tab re-show.
- [x] Trigger a chat-page reflow/remount when DeerFlow receives the host viewport resume event.
- [x] Verify the new-thread page stays stable after login, after browser refresh, and during the first streaming turn inside the EHM iframe.
      Verification note: `pnpm --dir frontend exec prettier --check ...` passed for the DeerFlow frontend changes, and `pnpm --dir ui-ehm exec prettier --check ...` passed for the EHM host iframe page. Manual browser verification is still required for the login-first-entry and first-stream-switch scenarios. No successful local `tsc --noEmit` result is available in this session.

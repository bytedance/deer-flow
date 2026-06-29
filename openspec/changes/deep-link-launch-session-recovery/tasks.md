## 1. Deep-Link Protocol

- [x] 1.1 Extend frontend deep-link parsing to recognize `launch_id` as a reserved parameter.
- [x] 1.2 Ensure `launch_id` is excluded from Agent passthrough params and only used by the DeerFlow frontend recovery flow.
- [x] 1.3 Update `docs/deep-link-api.md` to document `launch_id`, including refresh-restore vs explicit-relaunch semantics.

## 2. Launch Session Recovery

- [x] 2.1 Add a shared frontend helper for storing and reading `launch_id -> threadId` mappings from `sessionStorage`.
- [x] 2.2 In `/workspace/chats/[thread_id]/page.tsx`, check for an existing thread mapping before deep-link auto-send and restore the thread when found.
- [x] 2.3 In `/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`, check for an existing thread mapping before deep-link auto-send / auto_start and restore the thread when found.
- [x] 2.4 Persist the mapping when a new thread is created from a deep-link carrying `launch_id`.
- [x] 2.5 Validate that repeated loads with the same `launch_id` restore the existing thread, while a new `launch_id` still triggers a fresh execution.
- [x] 2.6 Sync the current real workspace route/thread back to the EHM host bridge after restore or thread creation.

## 3. Verification

- [x] 3.1 Add or update frontend tests for deep-link parsing of `launch_id`.
- [x] 3.2 Add or update tests for launch-session restore behavior on chat pages.
- [x] 3.3 Run relevant frontend lint / type checks / tests, or document any environment-limited verification.
      Verification note: `pnpm --dir frontend exec prettier --check ...` passed. `pnpm --dir frontend exec vitest run ...` is currently blocked by a missing local optional dependency `@rollup/rollup-linux-x64-gnu`. `pnpm --dir frontend exec eslint ...` and `pnpm --dir frontend exec tsc --noEmit` both timed out in this local environment before producing actionable diagnostics.

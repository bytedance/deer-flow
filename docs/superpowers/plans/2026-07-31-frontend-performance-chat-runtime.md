# Frontend Chat Runtime Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep streaming chat, long histories, Markdown, and chat navigation responsive with work proportional to the changed or visible data rather than the entire history.

**Architecture:** Pure indexed derivation functions update only affected turns. Query policy avoids surprise focus refetches. TanStack Virtual owns visible message/chat windows with measured rows and anchored scrolling. Streaming Markdown commits bounded chunks at a fixed cadence.

**Tech Stack:** React 19, TanStack Query, `@tanstack/react-virtual`, Rstest/happy-dom, TypeScript.

**Global Constraints:** Preserve message ordering, tool-result association, human-input cards, usage totals, stick-to-bottom behavior, pagination anchors, and accessibility. Add the virtualization dependency only after its first RED test.

## Task 1: Index message-derived state once per update

**Files:**
- Modify: `frontend/src/components/workspace/messages/message-list.tsx`
- Modify: `frontend/src/components/workspace/messages/message-group.tsx`
- Modify: `frontend/src/core/messages/utils.ts`
- Create: `frontend/src/core/messages/derived-state.ts`
- Create: `frontend/tests/unit/core/messages/derived-state.test.ts`
- Modify: `frontend/tests/unit/components/workspace/messages/message-group.test.ts`

- [ ] Write failing pure tests for `deriveMessageState(messages, previous?)`: assistant-turn usage, tool-call/result lookup, workspace-change anchors, and stable object identity for unchanged completed turns when only the streaming tail changes.
- [ ] Add a 5,000-message operation-count fixture that fails if derivation revisits every completed item on a tail-only update.
- [ ] Run focused tests and capture RED.
- [ ] Implement maps keyed by message ID/tool-call ID and a step-index map keyed by step identity. Replace `steps.indexOf(step)` and repeated full-history scans in render paths with precomputed indices.
- [ ] Memoize the derived state at the message-list boundary and pass precise slices to groups/items.
- [ ] Run tests GREEN; revert the incremental reuse branch to prove the tail-update test RED, then restore.
- [ ] Commit: `perf(frontend): index incremental message derivation`.

## Task 2: Make history pagination focus-stable

**Files:**
- Modify: `frontend/src/core/threads/hooks.ts`
- Create: `frontend/tests/unit/core/threads/thread-history-options.test.ts`

- [ ] Write a failing query-options test asserting `refetchOnWindowFocus: false`, explicit `staleTime`, and unchanged next-page cursor behavior.
- [ ] Run the focused test and capture RED.
- [ ] Set `refetchOnWindowFocus: false` for paged immutable history while leaving active-run streaming/cache writes authoritative. Use a concrete five-minute `staleTime`; explicit refresh/invalidation remains available.
- [ ] Run GREEN; revert the option, prove RED, restore.
- [ ] Commit: `perf(frontend): stabilize paged history cache policy`.

## Task 3: Bound streaming Markdown work

**Files:**
- Modify: `frontend/src/components/workspace/messages/markdown-content.tsx`
- Modify: `frontend/tests/unit/components/workspace/messages/markdown-content.dom.test.tsx`
- Modify: `frontend/tests/unit/components/workspace/messages/markdown-content.test.ts`

- [ ] Add fake-timer tests asserting a long streaming append causes no more than one rendered-content update per 50 ms, the final content becomes exact within 300 ms after stream completion, unmount cancels work, and reduced-motion renders immediately.
- [ ] Run focused tests and capture RED against requestAnimationFrame-per-growth behavior.
- [ ] Replace per-frame growing-string state with a bounded scheduler: retain the latest target in a ref, commit at most every 50 ms, reveal at least 64 new characters per commit, and flush the exact target on completion. Memoize parsed output by the committed string.
- [ ] Run GREEN. Restore the old RAF scheduler temporarily and confirm the update-count assertion RED, then restore the fix.
- [ ] Commit: `perf(frontend): bound streaming markdown renders`.

## Task 4: Virtualize long message histories

**Files:**
- Modify: `frontend/package.json`
- Modify: `pnpm-lock.yaml`
- Create: `frontend/src/components/workspace/messages/virtual-message-list.tsx`
- Modify: `frontend/src/components/workspace/messages/message-list.tsx`
- Create: `frontend/tests/unit/components/workspace/messages/virtual-message-list.dom.test.tsx`
- Modify: relevant Playwright chat history tests under `frontend/tests/e2e/`

- [ ] Write a DOM test with 2,000 variable-height rows and assert fewer than 80 message groups are mounted, the first/last items become reachable, and appending while pinned keeps the bottom anchored.
- [ ] Add a pagination-anchor test: prepending older rows keeps the previously visible message at the same visual offset.
- [ ] Run the tests and capture RED.
- [ ] Add `@tanstack/react-virtual` with pnpm. Implement measured rows with stable message-group IDs, overscan 8, explicit scroll-margin handling, and pin-to-bottom state integrated with `use-stick-to-bottom`.
- [ ] Keep live assistant/tool rows mounted while active even if measurement changes; announce newly arrived assistant content through the existing accessible live region.
- [ ] Run DOM and focused E2E tests GREEN. Temporarily replace the virtual items with the full array and prove the mount-count test RED, then restore.
- [ ] Commit: `perf(frontend): virtualize message history`.

## Task 5: Normalize, bound, and virtualize chat navigation

**Files:**
- Modify: `frontend/src/components/workspace/recent-chat-list.tsx`
- Modify: `frontend/src/app/workspace/chats/page.tsx`
- Create: `frontend/src/core/threads/thread-list-model.ts`
- Create: `frontend/tests/unit/core/threads/thread-list-model.test.ts`
- Create: `frontend/tests/unit/components/workspace/recent-chat-list.dom.test.tsx`

- [ ] Write failing tests proving sidebar and page share one normalized `Map<threadId, ThreadSummary>`, sorting happens only when page data changes, retained pages are capped at 200 threads, and a 1,000-row fixture mounts fewer than 60 rows.
- [ ] Run focused tests and capture RED.
- [ ] Move dedupe/sort into one memoized selector. Use bounded infinite-query retention and virtual rows for both consumers. Keep sentinel pagination based on the virtualizer's final item instead of a permanently rendered DOM tail.
- [ ] Preserve active-thread visibility and keyboard/focus semantics.
- [ ] Run tests GREEN and relevant chats E2E. Reintroduce full mapping to prove mount-count RED, restore.
- [ ] Commit: `perf(frontend): bound and virtualize chat lists`.

## Final verification

- [ ] Run `cd frontend && pnpm check && pnpm test`.
- [ ] Run Playwright coverage for long history, pagination, active streaming, and chat navigation.
- [ ] Profile a 5,000-message synthetic thread: record commit count and maximum rendered rows before/after in the PR description.
- [ ] Run `pnpm perf:check` and confirm virtualization does not breach route budgets.

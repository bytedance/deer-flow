# Background-task queries (`core/background-tasks/`)

On a successful cancel, await cancellation of the exact thread list and target
detail queries before writing the confirmed result to either cache. Then
invalidate only the exact list. Other task details keep loading. Both GETs pass
TanStack Query's `AbortSignal` to `fetch`. Callers that omit the signal keep the
single-argument `fetch` call. `core/memory` follows the same cache update order.

`frontend/tests/unit/core/background-tasks/hooks.dom.test.tsx` exercises the
cache updates with a real `QueryClient`. The sibling `cancellation-http.dom.test.tsx`
covers closed panels, HTTP aborts, cached and initial reads, isolation between
tasks and threads, and failed cancellations. An uncached list stays undefined
until a fresh list GET succeeds.

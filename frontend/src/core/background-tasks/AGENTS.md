# Background-task queries

Cancelling a task must not be undone by a poll that started before the cancel
answered. Await cancellation of the exact list and target-detail queries before
seeding either cache, then invalidate only the exact list query. Preserve sibling
detail requests, including their initial loads. Both GETs consume the query's
AbortSignal; callers that omit it retain the single-argument fetch call.
Same ordering contract as `core/memory` (#6959).

Keep the QueryClient regressions in `frontend/tests/unit/core/background-tasks/hooks.dom.test.tsx`.
Real-hook/HTTP coverage in `frontend/tests/unit/core/background-tasks/cancellation-http.dom.test.tsx`
also pins closed panels, cached and initial reads, transport aborts, sibling/thread
isolation, and failed cancellation. An uncached list stays undefined until a fresh
list GET succeeds; the cancel response must not fabricate a one-task list.

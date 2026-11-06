# Background-task queries

Cancelling a task must not be undone by a poll that started before the cancel
answered: the mutation drops the thread's `["background-tasks", threadId]`
reads before seeding the confirmed detail and list entry, then invalidates the
list prefix. Same ordering contract as `core/memory` (#6959). Regressions use a
real `QueryClient` in
`frontend/tests/unit/core/background-tasks/hooks.dom.test.tsx`.

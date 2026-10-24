# Background task queries

Successful cancellation cancels the thread's whole background-task query prefix
before caching its response, so neither a list poll nor a detail poll that
started earlier can restore the pre-cancel status. Both polling queries forward
TanStack's abort signal to the API, so cancelling also aborts the in-flight
request. The list entry is replaced in place and the list prefix invalidated
afterwards. Preserve failed cancellations and later refreshes. Regressions use
real QueryClient hooks in
`frontend/tests/unit/core/background-tasks/hooks.dom.test.tsx`.

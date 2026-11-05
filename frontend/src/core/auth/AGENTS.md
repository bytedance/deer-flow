# Authentication state and recovery

`AuthProvider` publishes the query owner: user ID, confirmed logout (`null`), or
unknown auth (`undefined`). Keep auth outside `QueryClientProvider`. Its mount-local
client remounts consumers, clears the old cache and cancels queries on owner changes.
Confirmed logout unmounts consumers immediately; public/unknown routes retain an
independent client. Superseded refreshes cannot restore an earlier owner.

Transport failure leaves unknown auth eligible for the 60-second visible-tab
check. A visible `online` event revalidates unknown auth immediately, but never
authenticates on connectivity alone. Confirmed anonymous/logout and static demos
do not probe. Keep wakeups single-flight and remove listeners on unmount.
Only the current request may release its in-flight guard; confirmed user/logout
supersedes that ownership. Coalesce reconnects during a pending refresh into one
follow-up only if auth remains unknown. Success, 401/logout, account replacement
and unmount discard the deferred wake. Hidden tabs retain reconnect wakeups until
visible, bypassing the tab-switch throttle once. Keep `isLoading` in the effect
dependencies so failed requests that leave auth unchanged still drain pending wakes.

Regressions: `tests/unit/core/auth/AuthProvider-recovery.dom.test.tsx` and
`tests/e2e/auth-network-recovery.spec.ts` under `frontend/`, alongside query-owner
and artifact-draft isolation suites. Forms trim emails, never raw passwords.

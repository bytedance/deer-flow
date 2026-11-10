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

### Admin user management

Settings → Users (admin-only nav entry; `?settings=users`) suspends and restores
accounts through `core/auth/admin-users.ts` → `/api/v1/admin/users`. The page
reuses `userSchema` for rows — both endpoints parse against it, so a
malformed payload fails the load instead of rendering a phantom row
(`disabled` optional — absent means not disabled) — and PATCHes only
`{disabled}`; role stays a read-only column. Like model management, the page
also gates on `isStaticWebsiteOnly()` (the demo user is nominally an admin,
but there is no Gateway to query), and the settings dialog falls back to the
first nav section when a deep link or stale store activates a section the
current user's nav does not offer. The Gateway's rejection detail
(last-active-admin 409) renders verbatim. A session
that turns out to be disabled maps `account_disabled` (see `AUTH_ERROR_CODES`)
to a login redirect with a stated reason (login surface only — sign-up keeps
the backend message so a suspended account cannot be probed) on all three
surfaces: SSR
`AuthResult` tag (consumed exhaustively by the workspace/artifacts/auth
layouts), the shared fetcher's 401 interception, and `AuthProvider.refreshUser`.
Direct auth-page visits with a live suspended-session cookie get the SSR
verdict via `AuthDisabledContext`, so the login form states the known reason
without waiting for a deliberately generic login failure.

Other sign-in bounces keep path, query and fragment via `currentReturnPath()`. The
workspace layout cannot read the URL, so `unauthenticated` renders
`WorkspaceLoginRedirect` (never `children`), not `redirect()`.

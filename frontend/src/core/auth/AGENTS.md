# Authentication state (`core/auth/`)

```bash
cd frontend && pnpm rstest run core/auth
```

## Query ownership

- **`AuthProvider` publishes the query owner**: a user ID, confirmed logout, or
  unknown. It stays outside `QueryClientProvider`. An owner change remounts the
  consumers with a new client, clears the old cache and cancels its queries, so
  one account never reads another account's cache.
- **Confirmed logout unmounts the consumers at once.** A refresh that was
  superseded cannot restore an earlier owner.

## Recovery from unknown auth

- **Connectivity alone never authenticates.** A visible `online` event
  revalidates unknown auth. Confirmed logout and static demos do not probe.
- **Wakeups are single-flight.** Only the current request releases the in-flight
  guard. Reconnects during a pending refresh collapse into one follow-up, which
  runs only if auth is still unknown.
- **`isLoading` stays in the effect dependencies**, so a failed request that
  leaves auth unchanged still drains pending wakeups.

## Disabled accounts and redirects

- **`account_disabled` maps to a login redirect with a stated reason on three
  surfaces**: the server-side auth result, the shared fetcher's 401 handling and
  `AuthProvider.refreshUser`. Sign-up keeps the backend message, so a suspended
  account cannot be probed.
- **A sign-in bounce keeps path, query and fragment.** The workspace layout
  cannot read the URL, so the unauthenticated case renders
  `WorkspaceLoginRedirect` and not `redirect()`, and never renders `children`.
- **The admin users page parses both endpoints with `userSchema`**, so a
  malformed payload fails the load and no phantom row appears. It sends only
  `{disabled}`. Like model management, it does not query in static-website mode.
- **Forms trim emails and leave passwords unchanged.**

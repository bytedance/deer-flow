/**
 * Helpers for Next.js `allowedDevOrigins` (dev-only cross-origin allow-list).
 *
 * `next dev` blocks cross-origin requests to /_next/* dev endpoints for any
 * request whose `Origin` hostname is not allow-listed. The request that
 * actually breaks the page is the Turbopack HMR WebSocket
 * (ws://<host>/_next/webpack-hmr): plain <script> chunks still load (a `<script>`
 * tag sends no Origin header, so it is not blocked), but once the HMR socket is
 * refused the dev client runtime never initializes, React never hydrates, and
 * every client page is frozen on its server-rendered initial markup. For /setup
 * that markup is the literal "Loading…", so it hangs there forever (verified in
 * a real browser: hostname not allow-listed -> 0 React fibers, stuck on
 * "Loading…"; allow-listed -> hydrates and proceeds). Issues #3385, #2983.
 *
 * DeerFlow's dev server sits behind the nginx proxy on port 2026 and is reached
 * through whatever host the browser uses — `localhost`, `127.0.0.1`, a LAN IP,
 * or an SSH-tunnelled host. Next.js only allows `localhost` / `*.localhost` out
 * of the box, so opening `make dev` via anything else (e.g. `127.0.0.1:2026` on
 * an autodl tunnel, or `<host>:2026` on a LAN) blocks the HMR socket and hangs
 * the UI. Docker (`make up`) runs a production build, which has no dev
 * cross-origin protection (and no HMR), so it is unaffected.
 *
 * `allowedDevOrigins` is dev-only — production builds ignore it.
 *
 * This module is `.mjs` (not `.ts`) because `next.config.js` is loaded by
 * Node's native ESM loader, which cannot import TypeScript. It is still unit
 * tested via Vitest (see tests/unit/lib/dev-origins.test.ts).
 */

/**
 * Resolve the hostname from an origin string. Accepts full origins
 * (`http://host:port`) and bare `host[:port]` values; returns null for blank or
 * unparseable input. Next.js matches on hostname only (port/scheme are
 * ignored), so we normalize down to the hostname here. IPv6 literals keep their
 * brackets (e.g. `http://[::1]:2026` -> `[::1]`), matching how Next.js parses
 * the incoming Origin header.
 *
 * @param {string | null | undefined} origin
 * @returns {string | null}
 */
export function hostnameOf(origin) {
  if (!origin) return null;
  try {
    return new URL(origin.includes("://") ? origin : `http://${origin}`)
      .hostname;
  } catch {
    return null;
  }
}

/**
 * Build the `allowedDevOrigins` list for `next dev`.
 *
 * Always allows the loopback IP `127.0.0.1` (the most common remote-access
 * shape — an SSH tunnel to `127.0.0.1:2026`). Additional hosts are derived from
 * the existing `GATEWAY_CORS_ORIGINS` browser allow-list (already required for
 * split-origin / port-forwarded deployments per `.env.example`) so LAN/remote
 * hosts only need to be configured in one place. `localhost` / `*.localhost`
 * are allowed by Next.js itself and need not be listed here.
 *
 * `*` is intentionally skipped to stay aligned with the backend CORS parser
 * (`app/gateway/csrf_middleware.py`), which treats `*` as "not an explicit
 * origin". Next.js would not honour a bare `*` as a wildcard anyway.
 *
 * @param {string | undefined} [corsOrigins] defaults to GATEWAY_CORS_ORIGINS
 * @returns {string[]}
 */
export function getAllowedDevOrigins(
  corsOrigins = process.env.GATEWAY_CORS_ORIGINS,
) {
  const hosts = new Set(["127.0.0.1"]);
  for (const raw of (corsOrigins ?? "").split(",")) {
    const value = raw.trim();
    if (!value || value === "*") continue;
    const host = hostnameOf(value);
    if (host && host !== "*") hosts.add(host);
  }
  return [...hosts];
}

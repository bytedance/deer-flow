import { NextResponse, type NextRequest } from "next/server";

/**
 * The Gateway trusts `X-DeerFlow-Internal-Token` / `X-DeerFlow-Owner-User-Id`
 * as internal credentials that bypass session auth and impersonate arbitrary
 * owners (see `backend/app/gateway/internal_auth.py`).
 *
 * Browser clients can set arbitrary custom headers, and this Next server is a
 * public hop for two surfaces: its own route handlers (`/api/memory/...`) and
 * the `next.config.js` rewrites (`/api/langgraph/*`, `/api/agents`,
 * `/api/skills`, plus the catch-all `/api/:path*`), which forward the client's
 * request headers untouched to the Gateway. Stripping both headers here covers
 * app-router routes and rewrites in one place, so the next proxy route cannot
 * forget them the way per-route `headers.delete()` calls would.
 *
 * nginx clears the same two headers in every proxying location
 * (`docker/nginx/nginx.conf`, `docker/nginx/nginx.local.conf`); this keeps the
 * Next.js hop consistent with that layer.
 *
 * Next 16 renamed the `middleware` file convention to `proxy`; the handler
 * must be exported as `proxy` (or as the default export) and always runs on the
 * Node.js runtime, so route segment config such as `runtime` is not allowed
 * here.
 */
export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.delete("x-deerflow-internal-token");
  headers.delete("x-deerflow-owner-user-id");

  return NextResponse.next({ request: { headers } });
}

export const config = {
  /**
   * Run for every request except Next's own build output. Paths that merely
   * *look* static are deliberately not excluded: an extension-based exclusion
   * (`.png`, `.svg`, ...) would let a request such as
   * `/api/threads/<id>/artifacts/report.png` — which the `/api/:path*` rewrite
   * forwards to the Gateway — bypass this file and carry the trust headers
   * through, which is exactly the hole this file exists to close.
   */
  matcher: ["/((?!_next/).*)"],
};

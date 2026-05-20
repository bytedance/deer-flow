import { type NextRequest, NextResponse } from "next/server";

/**
 * Propagate ?mock=true from the URL into a request header so that server
 * components (e.g. workspace/layout.tsx) can skip the auth redirect for
 * public demo pages without needing access to searchParams, which layouts
 * do not receive in Next.js App Router.
 */
export function middleware(request: NextRequest) {
  if (request.nextUrl.searchParams.get("mock") !== "true") {
    return NextResponse.next();
  }
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-mock", "true");
  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  matcher: ["/workspace/:path*"],
};

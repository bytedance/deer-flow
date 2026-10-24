import { NextResponse, type NextRequest } from "next/server";

import {
  REQUEST_ROUTE_HEADER,
  requestReturnPath,
} from "@/core/auth/return-path";

/** Capture the actual request URI; never trust a client-provided return header. */
export function proxy(request: NextRequest) {
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(REQUEST_ROUTE_HEADER, requestReturnPath(request.nextUrl));
  return NextResponse.next({ request: { headers: requestHeaders } });
}

// Keep public pages/assets untouched; overwrite the header everywhere auth layouts use it.
export const config = {
  matcher: ["/workspace/:path*", "/login", "/setup", "/auth/:path*"],
};

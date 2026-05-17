import { NextResponse, type NextRequest } from "next/server";

import {
  DEERFLOW_REQUEST_PATHNAME_HEADER,
  DEERFLOW_REQUEST_SEARCH_HEADER,
} from "@/core/request-headers";

export function middleware(request: NextRequest) {
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(
    DEERFLOW_REQUEST_PATHNAME_HEADER,
    request.nextUrl.pathname,
  );
  requestHeaders.set(DEERFLOW_REQUEST_SEARCH_HEADER, request.nextUrl.search);

  return NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });
}

export const config = {
  matcher: ["/workspace/:path*"],
};

import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

/**
 * Inject the full request URL as a header so Server Component layouts can
 * read query parameters (e.g. ?mock=true) that Next.js App Router does not
 * expose to layout components directly.
 */
export function middleware(request: NextRequest) {
  const response = NextResponse.next();
  response.headers.set("x-invoke-url", request.nextUrl.toString());
  return response;
}

export const config = {
  matcher: ["/workspace/:path*"],
};

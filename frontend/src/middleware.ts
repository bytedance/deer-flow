import { type NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "deerflow_session";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Only protect /workspace/* routes
  if (!pathname.startsWith("/workspace")) {
    return NextResponse.next();
  }

  // Check for session cookie
  const session = request.cookies.get(SESSION_COOKIE);
  if (session?.value) {
    return NextResponse.next();
  }

  // Redirect to login with the original URL as redirect parameter
  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("redirect", pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/workspace/:path*"],
};

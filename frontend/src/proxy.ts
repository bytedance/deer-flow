import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export default function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (pathname === "/workspace") {
    const url = request.nextUrl.clone();
    url.pathname = "/workspace/chats/new";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/workspace"],
};

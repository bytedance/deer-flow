import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const ACCESS_TOKEN_COOKIE = "access_token";
const CSRF_COOKIE = "csrf_token";

function firstHeaderValue(value: string | null): string | null {
  if (!value) return null;
  const first = value.split(",", 1)[0]?.trim();
  return first === undefined || first.length === 0 ? null : first;
}

function normalizeOrigin(value: string): string | null {
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

function getRequestOrigin(request: NextRequest): string {
  const protocol =
    firstHeaderValue(request.headers.get("x-forwarded-proto")) ??
    request.nextUrl.protocol.replace(/:$/, "");
  const host =
    firstHeaderValue(request.headers.get("x-forwarded-host")) ??
    firstHeaderValue(request.headers.get("host")) ??
    request.nextUrl.host;

  return normalizeOrigin(`${protocol}://${host}`) ?? request.nextUrl.origin;
}

function isAllowedOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;

  const normalizedOrigin = normalizeOrigin(origin);
  return (
    normalizedOrigin !== null && normalizedOrigin === getRequestOrigin(request)
  );
}

export async function POST(request: NextRequest) {
  if (!isAllowedOrigin(request)) {
    return NextResponse.json(
      { detail: "Cross-site auth request denied." },
      { status: 403 },
    );
  }

  // This frontend route intentionally avoids /api/* so nginx can still reach
  // it when the gateway is unavailable and cannot return its own Set-Cookie.
  const response = NextResponse.json({ message: "Successfully logged out" });
  response.cookies.delete(ACCESS_TOKEN_COOKIE);
  response.cookies.delete(CSRF_COOKIE);
  return response;
}

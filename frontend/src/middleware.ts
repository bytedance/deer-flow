import { type NextRequest, NextResponse } from "next/server";

// Authentik forward-auth trust relay.
//
// Traefik runs forward-auth before this app. On authenticated requests it
// injects X-authentik-* headers. The gateway exposes /api/v1/auth/me which,
// when those headers are present, mints an access_token cookie via
// AuthentikTrustMiddleware.
//
// In Next.js 16 Server Components, cookies().set() throws — only middleware,
// Route Handlers and Server Actions can mutate cookies. This middleware does
// the relay: if X-authentik-* headers arrive with no access_token cookie,
// fetch /auth/me upstream, copy the Set-Cookie onto the outgoing response.
// The downstream Server Component then sees a normal access_token cookie.

const SSO_TIMEOUT_MS = 5_000;

export async function middleware(req: NextRequest) {
  if (req.cookies.has("access_token")) return NextResponse.next();

  const auEmail = req.headers.get("x-authentik-email");
  const auUser = req.headers.get("x-authentik-username");
  if (!auEmail || !auUser) return NextResponse.next();

  const internalUrl =
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?.trim().replace(/\/+$/, "");
  if (!internalUrl) return NextResponse.next();

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), SSO_TIMEOUT_MS);
  let ssoRes: Response;
  try {
    ssoRes = await fetch(`${internalUrl}/api/v1/auth/me`, {
      headers: {
        "X-authentik-email": auEmail,
        "X-authentik-username": auUser,
      },
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeout);
    console.error("[mw trust] gateway fetch failed:", err);
    return NextResponse.next();
  }
  clearTimeout(timeout);
  if (!ssoRes.ok) {
    console.error(`[mw trust] /auth/me responded ${ssoRes.status}`);
    return NextResponse.next();
  }

  const setCookie = ssoRes.headers.get("set-cookie");
  if (!setCookie) return NextResponse.next();

  const parsed = parseAccessToken(setCookie);
  // Forward the cookie on this same request so the downstream Server
  // Component's cookies().get("access_token") returns the freshly minted
  // value on the first render (no extra round-trip).
  const fwdHeaders = new Headers(req.headers);
  if (parsed) {
    const existing = fwdHeaders.get("cookie");
    const cookieLine = `${parsed.name}=${parsed.value}`;
    fwdHeaders.set(
      "cookie",
      existing ? `${existing}; ${cookieLine}` : cookieLine,
    );
  }
  const res = NextResponse.next({ request: { headers: fwdHeaders } });
  if (parsed) {
    res.cookies.set(parsed.name, parsed.value, parsed.options);
  } else {
    res.headers.append("set-cookie", setCookie);
  }
  return res;
}

type SsoCookieOptions = {
  httpOnly?: boolean;
  secure?: boolean;
  sameSite?: "lax" | "strict" | "none";
  path?: string;
  maxAge?: number;
  expires?: Date;
};

function parseAccessToken(
  raw: string,
): { name: string; value: string; options: SsoCookieOptions } | null {
  const parts = raw.split(";").map((p) => p.trim());
  const [first, ...attrs] = parts;
  if (!first) return null;
  const eq = first.indexOf("=");
  if (eq === -1) return null;
  const name = first.slice(0, eq);
  if (name !== "access_token") return null;
  const value = first.slice(eq + 1);
  const options: SsoCookieOptions = {};
  for (const attr of attrs) {
    const [k, v] = attr.split("=").map((s) => s.trim());
    const key = k?.toLowerCase();
    if (key === "httponly") options.httpOnly = true;
    else if (key === "secure") options.secure = true;
    else if (key === "samesite" && v) {
      const sv = v.toLowerCase();
      if (sv === "lax" || sv === "strict" || sv === "none")
        options.sameSite = sv;
    } else if (key === "path" && v) options.path = v;
    else if (key === "max-age" && v) options.maxAge = Number(v);
    else if (key === "expires" && v) options.expires = new Date(v);
  }
  return { name, value, options };
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/health|.*\\..*).*)"],
};

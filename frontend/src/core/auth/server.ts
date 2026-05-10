import { cookies, headers } from "next/headers";

import { getGatewayConfig } from "./gateway-config";
import { type AuthResult, userSchema } from "./types";

const SSR_AUTH_TIMEOUT_MS = 5_000;

// Trust middleware path: when Traefik forward-auth has Authentik-authenticated the
// request, it injects X-authentik-* headers. The gateway's AuthentikTrustMiddleware
// mints an access_token cookie on /api/v1/auth/me when these headers are present.
// SSR forwards them so the user never sees the native /login form post-Authentik.
type SsoCookieOptions = {
  httpOnly?: boolean;
  secure?: boolean;
  sameSite?: "lax" | "strict" | "none";
  path?: string;
  maxAge?: number;
  expires?: Date;
};

function parseSetCookie(
  setCookie: string,
): { name: string; value: string; options: SsoCookieOptions } | null {
  const parts = setCookie.split(";").map((p) => p.trim());
  const [first, ...attrs] = parts;
  if (!first) return null;
  const eq = first.indexOf("=");
  if (eq === -1) return null;
  const name = first.slice(0, eq);
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

/**
 * Fetch the authenticated user from the gateway using the request's cookies.
 * Returns a tagged AuthResult — callers use exhaustive switch, no try/catch.
 */
export async function getServerSideUser(): Promise<AuthResult> {
  if (process.env.DEER_FLOW_AUTH_DISABLED === "1") {
    return {
      tag: "authenticated",
      user: {
        id: "e2e-user",
        email: "e2e@test.local",
        system_role: "admin",
        needs_setup: false,
      },
    };
  }

  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get("access_token");

  let internalGatewayUrl: string;
  try {
    internalGatewayUrl = getGatewayConfig().internalGatewayUrl;
  } catch (err) {
    return { tag: "config_error", message: String(err) };
  }

  if (!sessionCookie) {
    // SSO trust path: if Traefik forward-auth proved the user via Authentik, it
    // injected X-authentik-* headers. Forward them to gateway /api/v1/auth/me;
    // the AuthentikTrustMiddleware mints an access_token cookie which we relay
    // back to the browser. User never sees the native /login form.
    const hdrs = await headers();
    const auEmail = hdrs.get("x-authentik-email");
    const auUser = hdrs.get("x-authentik-username");
    if (auEmail && auUser) {
      const ssoController = new AbortController();
      const ssoTimeout = setTimeout(
        () => ssoController.abort(),
        SSR_AUTH_TIMEOUT_MS,
      );
      try {
        const ssoRes = await fetch(`${internalGatewayUrl}/api/v1/auth/me`, {
          headers: {
            "X-authentik-email": auEmail,
            "X-authentik-username": auUser,
          },
          cache: "no-store",
          signal: ssoController.signal,
        });
        clearTimeout(ssoTimeout);
        if (ssoRes.ok) {
          const setCookieHdr = ssoRes.headers.get("set-cookie");
          if (setCookieHdr) {
            const parsed = parseSetCookie(setCookieHdr);
            if (parsed) {
              cookieStore.set(parsed.name, parsed.value, parsed.options);
            }
          }
          const userParsed = userSchema.safeParse(await ssoRes.json());
          if (userParsed.success) {
            if (userParsed.data.needs_setup) {
              return { tag: "needs_setup", user: userParsed.data };
            }
            return { tag: "authenticated", user: userParsed.data };
          }
          console.error(
            "[SSR auth] Malformed /auth/me trust response:",
            userParsed.error,
          );
        }
      } catch {
        clearTimeout(ssoTimeout);
        // Trust path unreachable — fall through to native unauthenticated flow.
      }
    }

    // No session — check whether the system has been initialised yet.
    const setupController = new AbortController();
    const setupTimeout = setTimeout(
      () => setupController.abort(),
      SSR_AUTH_TIMEOUT_MS,
    );
    try {
      const setupRes = await fetch(
        `${internalGatewayUrl}/api/v1/auth/setup-status`,
        {
          cache: "no-store",
          signal: setupController.signal,
        },
      );
      clearTimeout(setupTimeout);
      if (setupRes.ok) {
        const setupData = (await setupRes.json()) as { needs_setup?: boolean };
        if (setupData.needs_setup) {
          return { tag: "system_setup_required" };
        }
      }
    } catch {
      clearTimeout(setupTimeout);
      // If setup-status is unreachable/times out, fall through to unauthenticated.
    }
    return { tag: "unauthenticated" };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), SSR_AUTH_TIMEOUT_MS);

  try {
    const res = await fetch(`${internalGatewayUrl}/api/v1/auth/me`, {
      headers: { Cookie: `access_token=${sessionCookie.value}` },
      cache: "no-store",
      signal: controller.signal,
    });
    clearTimeout(timeout); // Clear immediately — covers all response branches

    if (res.ok) {
      const parsed = userSchema.safeParse(await res.json());
      if (!parsed.success) {
        console.error("[SSR auth] Malformed /auth/me response:", parsed.error);
        return { tag: "gateway_unavailable" };
      }
      if (parsed.data.needs_setup) {
        return { tag: "needs_setup", user: parsed.data };
      }
      return { tag: "authenticated", user: parsed.data };
    }
    if (res.status === 401 || res.status === 403) {
      return { tag: "unauthenticated" };
    }
    console.error(`[SSR auth] /api/v1/auth/me responded ${res.status}`);
    return { tag: "gateway_unavailable" };
  } catch (err) {
    clearTimeout(timeout);
    console.error("[SSR auth] Failed to reach gateway:", err);
    return { tag: "gateway_unavailable" };
  }
}

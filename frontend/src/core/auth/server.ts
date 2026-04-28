import { cookies } from "next/headers";

import { getGatewayConfig } from "./gateway-config";
import { type AuthResult, userSchema } from "./types";

const SSR_AUTH_TIMEOUT_MS = 5_000;

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

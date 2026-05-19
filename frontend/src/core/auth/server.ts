import { cookies } from "next/headers";

import { getGatewayConfig } from "./gateway-config";
import { type AuthResult, userSchema } from "./types";
import { getServerEhmToken, getServerEhmUser } from "./ehm-auth";

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
        system_role: "superadmin",
        tenant_id: "default",
        user_name: "e2e",
        real_name: "E2E User",
      },
    };
  }

  const cookieStore = await cookies();

  // EHM token auto-login: bypass backend, read user info from cookies
  const ehmToken = getServerEhmToken(cookieStore);
  if (ehmToken) {
    const ehmUser = getServerEhmUser(cookieStore);
    if (ehmUser) {
      return { tag: "authenticated", user: ehmUser };
    }
  }

  const sessionCookie = cookieStore.get("access_token");

  let internalGatewayUrl: string;
  try {
    internalGatewayUrl = getGatewayConfig().internalGatewayUrl;
  } catch (err) {
    return { tag: "config_error", message: String(err) };
  }

  if (!sessionCookie) {
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
    clearTimeout(timeout);

    if (res.ok) {
      const parsed = userSchema.safeParse(await res.json());
      if (!parsed.success) {
        console.error("[SSR auth] Malformed /auth/me response:", parsed.error);
        return { tag: "gateway_unavailable" };
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

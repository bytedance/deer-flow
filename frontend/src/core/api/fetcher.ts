import { buildLoginUrl } from "@/core/auth/types";
import { EHM_TOKEN_COOKIE } from "@/core/auth/ehm-auth";

/** HTTP methods that the gateway's CSRFMiddleware checks. */
export type StateChangingMethod = "POST" | "PUT" | "DELETE" | "PATCH";

export const STATE_CHANGING_METHODS: ReadonlySet<StateChangingMethod> = new Set(
  ["POST", "PUT", "DELETE", "PATCH"],
);

/** Mirror of the gateway's ``should_check_csrf`` decision. */
export function isStateChangingMethod(method: string): boolean {
  return (STATE_CHANGING_METHODS as ReadonlySet<string>).has(
    method.toUpperCase(),
  );
}

const CSRF_COOKIE_PREFIX = "csrf_token=";

/**
 * Read the ``csrf_token`` cookie set by the gateway at login.
 *
 * SSR-safe: returns ``null`` when ``document`` is undefined so the same
 * helper can be imported from server components without a guard.
 *
 * Uses `String.split` instead of a regex to side-step ESLint's
 * `prefer-regexp-exec` rule and the cookie value's reliable `; `
 * separator (set by the gateway, not the browser, so format is stable).
 */
export function readCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  for (const pair of document.cookie.split("; ")) {
    if (pair.startsWith(CSRF_COOKIE_PREFIX)) {
      return decodeURIComponent(pair.slice(CSRF_COOKIE_PREFIX.length));
    }
  }
  return null;
}

/**
 * Read the EHM token cookie for auto-login users.
 * Returns null if not present or running on the server.
 */
function readEhmTokenCookie(): string | null {
  if (typeof document === "undefined") return null;
  for (const pair of document.cookie.split("; ")) {
    if (pair.startsWith(`${EHM_TOKEN_COOKIE}=`)) {
      const raw = pair.slice(EHM_TOKEN_COOKIE.length + 1);
      console.log("[EHM fetcher] found ehm_token cookie, length:", raw.length);
      return decodeURIComponent(raw);
    }
  }
  console.log("[EHM fetcher] ehm_token cookie NOT found, cookies:", document.cookie);
  return null;
}

/**
 * Fetch with credentials and automatic CSRF protection.
 *
 * Two centralized contracts every API call needs:
 *
 * 1. ``credentials: "include"`` so the HttpOnly access_token cookie
 *    accompanies cross-origin SSR-routed requests.
 * 2. ``X-CSRF-Token`` header on state-changing methods (POST/PUT/
 *    DELETE/PATCH), echoed from the ``csrf_token`` cookie. The gateway's
 *    CSRFMiddleware enforces Double Submit Cookie comparison and returns
 *    403 if the header is missing — silently breaking every call site
 *    that uses raw ``fetch()`` instead of this wrapper.
 *
 * 3. If an EHM token cookie is present (iframed auto-login), it is sent
 *    as ``Authorization: Bearer <ehm_token>`` header.
 *
 * Auto-redirects to ``/login`` on 401. Caller-supplied headers are
 * preserved; the helper only ADDS headers when they aren't already
 * present, so explicit overrides win.
 */
export async function fetch(
  input: RequestInfo | URL | string,
  init?: RequestInit,
): Promise<Response> {
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;

  const merged = new Headers(init?.headers);

  // Inject EHM token as Bearer if using EHM auto-login
  if (!merged.has("Authorization")) {
    const ehmToken = readEhmTokenCookie();
    if (ehmToken) {
      console.log("[EHM fetcher] injecting Authorization Bearer header for:", url);
      merged.set("Authorization", `Bearer ${ehmToken}`);
    }
  }

  // Inject CSRF for state-changing methods. GET/HEAD/OPTIONS/TRACE skip
  // it to mirror the gateway's ``should_check_csrf`` logic exactly.
  if (isStateChangingMethod(init?.method ?? "GET")) {
    const token = readCsrfCookie();
    if (token && !merged.has("X-CSRF-Token")) {
      merged.set("X-CSRF-Token", token);
    }
  }

  const res = await globalThis.fetch(url, {
    ...init,
    headers: merged,
    credentials: "include",
  });

  if (res.status === 401) {
    // Skip refresh for EHM auto-login users (no backend session)
    if (readEhmTokenCookie()) {
      return res;
    }

    // A refresh attempt is about to be made — set a flag to avoid infinite loops
    // when the refresh endpoint itself returns 401.
    const isRefreshRequest = url.includes("/api/v1/auth/refresh");
    if (!isRefreshRequest) {
      try {
        const refreshRes = await globalThis.fetch("/api/v1/auth/refresh", {
          method: "POST",
          credentials: "include",
        });
        if (refreshRes.ok) {
          // Token refreshed successfully — retry the original request
          return globalThis.fetch(input, { ...init, headers: merged, credentials: "include" });
        }
      } catch {
        // Refresh failed, fall through to redirect
      }
    }

    window.location.href = buildLoginUrl(window.location.pathname);
    throw new Error("Unauthorized");
  }

  return res;
}

/**
 * Build headers for CSRF-protected requests.
 *
 * **Prefer :func:`fetchWithAuth`** for new code — it injects the header
 * automatically on state-changing methods. This helper exists for legacy
 * call sites that need to compose headers manually (e.g. inside
 * `next/server` route handlers that build their own ``Headers`` object).
 *
 * Per RFC-001: Double Submit Cookie pattern.
 */
export function getCsrfHeaders(): HeadersInit {
  const token = readCsrfCookie();
  return token ? { "X-CSRF-Token": token } : {};
}

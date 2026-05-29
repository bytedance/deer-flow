import { EHM_TOKEN_COOKIE, isEhmTokenExpired } from "@/core/auth/ehm-auth";
import { buildLoginUrl } from "@/core/auth/types";

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
const REFRESH_PATH = "/api/v1/auth/refresh";
const EHM_AUTHENTICATE_PATH = "/api/v1/auth/ins-base/authenticate";

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
 * Returns the raw token whenever the cookie is present. Expiry is checked
 * later in the 401 handler, where we decide whether to clear the cookie.
 *
 * SSR-safe: returns null when document is undefined.
 */
function readEhmTokenCookie(): string | null {
  if (typeof document === "undefined") return null;
  for (const pair of document.cookie.split("; ")) {
    if (pair.startsWith(`${EHM_TOKEN_COOKIE}=`)) {
      const raw = pair.slice(EHM_TOKEN_COOKIE.length + 1);
      return decodeURIComponent(raw);
    }
  }
  return null;
}

/**
 * Check if the EHM token cookie exists, even if expired.
 * Used to detect EHM auto-login users for 401 handling.
 */
function hasEhmTokenCookie(): boolean {
  if (typeof document === "undefined") return false;
  for (const pair of document.cookie.split("; ")) {
    if (pair.startsWith(`${EHM_TOKEN_COOKIE}=`)) {
      return true;
    }
  }
  return false;
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
 *    403 if the header is missing, silently breaking every call site
 *    that uses raw ``fetch()`` instead of this wrapper.
 *
 * 3. If an EHM token cookie is present (iframed auto-login), it is sent
 *    as ``Authorization: Bearer <ehm_token>`` header.
 *
 * Auto-redirects to ``/login`` on 401. Caller-supplied headers are
 * preserved; the helper only adds headers when they are not already
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

  const merged = buildAuthHeaders(init?.headers, init?.method ?? "GET", url);

  const res = await globalThis.fetch(url, {
    ...init,
    headers: merged,
    credentials: "include",
  });

  if (res.status === 401) {
    if (hasEhmTokenCookie()) {
      const authRes = await reauthenticateEhmSession(url, merged);
      if (authRes?.ok) {
        const retryRes = await globalThis.fetch(input, {
          ...init,
          headers: buildAuthHeaders(init?.headers, init?.method ?? "GET", url),
          credentials: "include",
        });
        if (retryRes.status !== 401) {
          return retryRes;
        }
      }
    }

    if (!url.includes(REFRESH_PATH)) {
      try {
        const refreshRes = await globalThis.fetch(resolveAuthUrl(url, REFRESH_PATH), {
          method: "POST",
          headers: buildAuthHeaders(merged, "POST", REFRESH_PATH),
          credentials: "include",
        });
        if (refreshRes.ok) {
          const retryRes = await globalThis.fetch(input, {
            ...init,
            headers: buildAuthHeaders(init?.headers, init?.method ?? "GET", url),
            credentials: "include",
          });
          if (retryRes.status !== 401) {
            return retryRes;
          }
        }
      } catch {
        // Refresh failed, fall through to redirect.
      }
    }

    // Delay redirect so callers (e.g. publish dialog) can catch the error
    // and show a toast before the page navigates away.
    window.setTimeout(() => {
      window.location.href = buildLoginUrl(window.location.pathname);
    }, 2000);

    // Preserve the original server response body so callers can inspect
    // the real error code/message (e.g. token_expired vs not_authenticated).
    let detail: unknown = { code: "not_authenticated", message: "Session expired" };
    try {
      detail = await res.clone().json();
    } catch {
      // Response body is not JSON — keep the fallback detail.
    }
    const err = new Error("Unauthorized") as Error & { status: number; detail: unknown };
    err.status = 401;
    err.detail = detail;
    throw err;
  }

  return res;
}

async function reauthenticateEhmSession(
  requestUrl: string,
  headers: Headers,
): Promise<Response | null> {
  const currentToken = readEhmTokenCookie();
  if (!currentToken) {
    return null;
  }
  if (isEhmTokenExpired(currentToken)) {
    clearEhmTokenCookie();
    return null;
  }
  if (requestUrl.includes(EHM_AUTHENTICATE_PATH)) {
    return null;
  }

  try {
    return await globalThis.fetch(resolveAuthUrl(requestUrl, EHM_AUTHENTICATE_PATH), {
      method: "POST",
      headers: buildAuthHeaders(headers, "POST", EHM_AUTHENTICATE_PATH),
      credentials: "include",
    });
  } catch {
    return null;
  }
}

function resolveAuthUrl(requestUrl: string, authPath: string): string {
  if (requestUrl.startsWith("http://") || requestUrl.startsWith("https://")) {
    return new URL(authPath, requestUrl).toString();
  }
  return authPath;
}

function clearEhmTokenCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${EHM_TOKEN_COOKIE}=; path=/; max-age=0`;
}

function buildAuthHeaders(
  headers: HeadersInit | undefined,
  method: string,
  _url: string,
): Headers {
  const merged = new Headers(headers);

  if (!merged.has("Authorization")) {
    const ehmToken = readEhmTokenCookie();
    if (ehmToken) {
      merged.set("Authorization", `Bearer ${ehmToken}`);
    }
  }

  if (isStateChangingMethod(method)) {
    const token = readCsrfCookie();
    if (token && !merged.has("X-CSRF-Token")) {
      merged.set("X-CSRF-Token", token);
    }
  }

  return merged;
}

/**
 * Build headers for CSRF-protected requests.
 *
 * **Prefer :func:`fetchWithAuth`** for new code. It injects the header
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

import { EHM_TOKEN_COOKIE, isEhmTokenExpired } from "@/core/auth/ehm-auth";
import {
  EHM_SESSION_RECOVERED_EVENT,
  requestFreshHostToken,
} from "@/core/auth/ehm-host-bridge";
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
const INS_BASE_REFRESH_PATH = "/api/v1/auth/ins-base/refresh";
const INS_REFRESH_COOKIE = "InS-refresh";
const LOGIN_REDIRECT_DELAY_MS = 2000;

let ehmSessionRecoveryPromise: Promise<boolean> | null = null;
let pendingLoginRedirectTimer: number | null = null;
let recoveryEpoch = 0;
let isRecoveryEventBound = false;
let hasPendingEhmRedirectConfirmation = false;

/**
 * Read a named cookie from document.cookie.
 * SSR-safe: returns null when document is undefined.
 */
function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  for (const pair of document.cookie.split("; ")) {
    if (pair.startsWith(prefix)) {
      return decodeURIComponent(pair.slice(prefix.length));
    }
  }
  return null;
}

/**
 * Read the EHM ``InS-refresh`` cookie set by the EHM platform.
 * This is the InS refresh token used to obtain a new bearer token
 * when the access_token has expired.
 */
function readInsRefreshCookie(): string | null {
  return readCookie(INS_REFRESH_COOKIE);
}

/**
 * Attempt to refresh the InS access token via ins-base-rpc /auth/refresh.
 * On success, the gateway sets a new ``access_token`` cookie.
 * Returns true if the refresh succeeded.
 */
async function refreshInsBaseSession(): Promise<boolean> {
  const refreshToken = readInsRefreshCookie();
  if (!refreshToken) return false;
  try {
    const res = await globalThis.fetch("/api/v1/auth/ins-base/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      credentials: "include",
    });
    return res.ok;
  } catch {
    return false;
  }
}

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
 * Auto-redirects to ``/login`` on 401. Caller-supplied headers are
 * preserved; the helper only adds headers when they are not already
 * present, so explicit overrides win.
 */
export async function fetch(
  input: RequestInfo | URL | string,
  init?: RequestInit,
): Promise<Response> {
  ensureRecoveryEventBinding();

  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
      ? input.toString()
      : input.url;

  await waitForOngoingEhmRecovery(url);

  const merged = buildAuthHeaders(init?.headers, init?.method ?? "GET", url);

  const res = await globalThis.fetch(url, {
    ...init,
    headers: merged,
    credentials: "include",
  });

  if (res.ok) {
    clearEhmRedirectConfirmation();
    cancelPendingLoginRedirect();
  }

  if (res.status === 401) {
    if (hasEhmTokenCookie()) {
      const ehmSessionRecovered = await recoverEhmSession(url);
      if (ehmSessionRecovered) {
        cancelPendingLoginRedirect();
        const retryRes = await globalThis.fetch(input, {
          ...init,
          headers: buildAuthHeaders(init?.headers, init?.method ?? "GET", url),
          credentials: "include",
        });
        if (retryRes.ok) {
          cancelPendingLoginRedirect();
        }
        if (retryRes.status !== 401) {
          return retryRes;
        }
      }
    }

    // EHM-authenticated session: try refreshing via InS-refresh cookie
    // (set by EHM platform when running under same-origin reverse proxy)
    if (!url.includes(REFRESH_PATH) && readInsRefreshCookie()) {
      const insRefreshed = await refreshInsBaseSession();
      if (insRefreshed) {
        markRecoverySucceeded();
        const retryRes = await globalThis.fetch(input, {
          ...init,
          headers: buildAuthHeaders(init?.headers, init?.method ?? "GET"),
          credentials: "include",
        });
        if (retryRes.ok) {
          cancelPendingLoginRedirect();
        }
        if (retryRes.status !== 401) {
          return retryRes;
        }
      }
    }

    if (!url.includes(REFRESH_PATH)) {
      try {
        const refreshRes = await globalThis.fetch(resolveAuthUrl(url, REFRESH_PATH), {
          method: "POST",
          headers: buildAuthHeaders(merged, "POST"),
          credentials: "include",
        });
        if (refreshRes.ok) {
          markRecoverySucceeded();
          const retryRes = await globalThis.fetch(input, {
            ...init,
            headers: buildAuthHeaders(init?.headers, init?.method ?? "GET"),
            credentials: "include",
          });
          if (retryRes.ok) {
            cancelPendingLoginRedirect();
          }
          if (retryRes.status !== 401) {
            return retryRes;
          }
        }
      } catch {
        // Refresh failed, fall through to redirect.
      }
    }

    if (shouldDeferInitialEhmLoginRedirect()) {
      let detail: unknown = { code: "not_authenticated", message: "Session expired" };
      try {
        detail = await res.clone().json();
      } catch {
        // Response body is not JSON — keep the fallback detail.
      }
      const err = new Error("Unauthorized") as Error & {
        status: number;
        detail: unknown;
      };
      err.status = 401;
      err.detail = detail;
      throw err;
    }

    scheduleLoginRedirect();

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

function ensureRecoveryEventBinding(): void {
  if (isRecoveryEventBound || typeof window === "undefined") {
    return;
  }

  window.addEventListener(EHM_SESSION_RECOVERED_EVENT, () => {
    markRecoverySucceeded();
  });
  isRecoveryEventBound = true;
}

async function waitForOngoingEhmRecovery(requestUrl: string): Promise<void> {
  if (!ehmSessionRecoveryPromise) {
    return;
  }
  if (shouldBypassRecoveryWait(requestUrl)) {
    return;
  }

  try {
    await ehmSessionRecoveryPromise;
  } catch {
    // Keep the original request flow: if recovery failed, the request should
    // proceed and fall through to the existing 401 handling.
  }
}

function markRecoverySucceeded(): void {
  recoveryEpoch += 1;
  clearEhmRedirectConfirmation();
  cancelPendingLoginRedirect();
}

function clearEhmRedirectConfirmation(): void {
  hasPendingEhmRedirectConfirmation = false;
}

function cancelPendingLoginRedirect(): void {
  if (!pendingLoginRedirectTimer) {
    return;
  }
  clearTimeout(pendingLoginRedirectTimer);
  pendingLoginRedirectTimer = null;
}

function scheduleLoginRedirect(): void {
  if (pendingLoginRedirectTimer) {
    return;
  }

  const scheduledEpoch = recoveryEpoch;
  pendingLoginRedirectTimer = window.setTimeout(() => {
    pendingLoginRedirectTimer = null;

    if (ehmSessionRecoveryPromise) {
      return;
    }
    if (scheduledEpoch !== recoveryEpoch) {
      return;
    }

    window.location.href = buildLoginUrl(window.location.pathname);
  }, LOGIN_REDIRECT_DELAY_MS);
}

function shouldDeferInitialEhmLoginRedirect(): boolean {
  if (!hasEhmTokenCookie()) {
    return false;
  }
  if (hasPendingEhmRedirectConfirmation) {
    return false;
  }

  hasPendingEhmRedirectConfirmation = true;
  return true;
}

export function shouldSuppressAuthErrorRedirect(): boolean {
  return (
    ehmSessionRecoveryPromise !== null ||
    pendingLoginRedirectTimer !== null ||
    hasPendingEhmRedirectConfirmation
  );
}

function shouldBypassRecoveryWait(requestUrl: string): boolean {
  return (
    requestUrl.includes(EHM_AUTHENTICATE_PATH) ||
    requestUrl.includes(INS_BASE_REFRESH_PATH) ||
    requestUrl.includes(REFRESH_PATH)
  );
}

async function recoverEhmSession(requestUrl: string): Promise<boolean> {
  if (requestUrl.includes(EHM_AUTHENTICATE_PATH)) {
    return false;
  }

  if (ehmSessionRecoveryPromise) {
    return ehmSessionRecoveryPromise;
  }

  ehmSessionRecoveryPromise = recoverEhmSessionOnce(requestUrl).finally(() => {
    ehmSessionRecoveryPromise = null;
  });

  return ehmSessionRecoveryPromise;
}

async function recoverEhmSessionOnce(requestUrl: string): Promise<boolean> {
  const authRes = await reauthenticateEhmSession(requestUrl);
  if (authRes?.ok) {
    markRecoverySucceeded();
    return true;
  }

  const hostTokenUpdated = await requestFreshHostToken();
  if (!hostTokenUpdated) {
    return false;
  }

  const authRetryRes = await reauthenticateEhmSession(requestUrl);
  if (authRetryRes?.ok) {
    markRecoverySucceeded();
    return true;
  }
  return false;
}

async function reauthenticateEhmSession(requestUrl: string): Promise<Response | null> {
  const currentToken = readEhmTokenCookie();
  if (!currentToken) {
    return null;
  }
  if (isEhmTokenExpired(currentToken)) {
    return null;
  }
  if (requestUrl.includes(EHM_AUTHENTICATE_PATH)) {
    return null;
  }

  try {
    return await globalThis.fetch(resolveAuthUrl(requestUrl, EHM_AUTHENTICATE_PATH), {
      method: "POST",
      headers: buildEhmAuthenticateHeaders(),
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

function buildEhmAuthenticateHeaders(): Headers {
  const headers = new Headers();
  const ehmToken = readEhmTokenCookie();
  if (ehmToken) {
    headers.set("Authorization", `Bearer ${ehmToken}`);
  }

  const csrfToken = readCsrfCookie();
  if (csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  return headers;
}

function buildAuthHeaders(
  headers: HeadersInit | undefined,
  method: string,
): Headers {
  const merged = new Headers(headers);

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

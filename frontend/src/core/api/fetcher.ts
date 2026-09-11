import {
  deferredUnauthorized,
  isLoginRedirectDeferred,
} from "@/core/auth/login-redirect-deferral";
import { buildLoginUrl } from "@/core/auth/types";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { UnauthorizedError } from "./errors";
import { staticApiResponse } from "./static-response";

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
 * Auto-redirects to ``/login`` on 401. Caller-supplied headers are
 * preserved; the helper only ADDS the CSRF header when it isn't already
 * present, so explicit overrides win.
 */
export async function fetch(
  input: RequestInfo | string,
  init?: RequestInit,
): Promise<Response> {
  const url = typeof input === "string" ? input : input.url;

  // Static demos have no Gateway. Resolve REST calls before credentials,
  // CSRF, or redirects; demo assets and explicit mock routes still use HTTP.
  if (isStaticWebsiteOnly()) {
    const response = await staticApiResponse(url, {
      ...init,
      method:
        init?.method ?? (typeof input === "string" ? "GET" : input.method),
    });
    if (response) return response;
  }

  // Inject CSRF for state-changing methods. GET/HEAD/OPTIONS/TRACE skip
  // it to mirror the gateway's ``should_check_csrf`` logic exactly.
  let headers = init?.headers;
  if (isStateChangingMethod(init?.method ?? "GET")) {
    const token = readCsrfCookie();
    if (token) {
      // Fresh Headers instance so we don't mutate caller-supplied objects.
      const merged = new Headers(headers);
      if (!merged.has("X-CSRF-Token")) {
        merged.set("X-CSRF-Token", token);
      }
      headers = merged;
    }
  }

  const res = await globalThis.fetch(url, {
    ...init,
    headers,
    credentials: "include",
  });

  if (res.status === 401) {
    // Include the search string: routes that carry their target in the query
    // (e.g. the standalone artifact viewer) are otherwise unrecoverable after
    // login, which lands on the default workspace instead.
    const target = buildLoginUrl(
      `${window.location.pathname}${window.location.search}`,
    );
    // A held login-redirect deferral suppresses this hard navigation too:
    // it discards every client-state copy of what is on screen, and the
    // deferring flow (the PAT show-once window) keeps the only copy of a
    // live credential there — session expiry does not revoke a minted
    // token. Suppressing alone would strand the 401 — UnauthorizedError's
    // consumers (the model-load banner withholds its warning, the models
    // hook declines to retry) all trust that a login redirect is underway —
    // so the suppressed redirect is handed to the provider's held-redirect
    // machinery and fires the moment the last deferral clears. The count is
    // read live, never from a closure: a request already in flight when the
    // deferral armed must be gated by the same value a request started
    // later sees.
    if (!isLoginRedirectDeferred()) {
      window.location.href = target;
    } else {
      deferredUnauthorized(target);
    }
    throw new UnauthorizedError();
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

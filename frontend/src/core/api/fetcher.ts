import { buildLoginUrl } from "@/core/auth/types";
import { getBackendBaseURL } from "@/core/config";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import {
  captureWorkspaceRequestScope,
  createWorkspaceFetch,
  prepareWorkspaceRequest,
  type WorkspaceRequestScope,
} from "@/core/workspaces/request-scope";

import { parseGatewayApiError, UnauthorizedError } from "./errors";
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
async function fetchAuthenticated(
  input: RequestInfo | URL,
  init?: RequestInit,
  transport?: typeof globalThis.fetch,
): Promise<Response> {
  const request = input instanceof Request ? input : undefined;
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;
  const method = init?.method ?? request?.method ?? "GET";

  // Static demos have no Gateway. Resolve REST calls before credentials,
  // CSRF, or redirects; demo assets and explicit mock routes still use HTTP.
  if (isStaticWebsiteOnly()) {
    const response = await staticApiResponse(url, {
      ...init,
      method,
    });
    if (response) return response;
  }

  // Inject CSRF for state-changing methods. GET/HEAD/OPTIONS/TRACE skip
  // it to mirror the gateway's ``should_check_csrf`` logic exactly.
  let headers = init?.headers ?? request?.headers;
  if (isStateChangingMethod(method)) {
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

  // Forward the original Request so its body, method and cancellation signal
  // survive. Reducing it to a URL loses explicit workspace selectors as well.
  const res = await (transport ?? globalThis.fetch)(input, {
    ...init,
    headers,
    credentials: "include",
  });

  if (res.status === 401) {
    // Include the search string: routes that carry their target in the query
    // (e.g. the standalone artifact viewer) are otherwise unrecoverable after
    // login, which lands on the default workspace instead.
    window.location.href = buildLoginUrl(
      `${window.location.pathname}${window.location.search}`,
    );
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

/** Native REST callers retain their existing unscoped behavior. */
export async function fetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  return fetchAuthenticated(input, init);
}

/** Bind browser REST calls to one immutable actor/workspace lifetime. */
export function createWorkspaceRESTClient(scope: WorkspaceRequestScope) {
  if (isStaticWebsiteOnly())
    throw new Error("Workspace clients are unavailable in demo mode");
  const snapshot = captureWorkspaceRequestScope(scope);
  const origin =
    typeof window === "undefined"
      ? "http://localhost:2026"
      : window.location.origin;
  const apiRoot = new URL(`${getBackendBaseURL()}/api`, origin).toString();
  const transport = createWorkspaceFetch(snapshot, apiRoot);
  const scopedFetch = (input: RequestInfo | URL, init?: RequestInit) =>
    fetchAuthenticated(input, init, transport);
  return Object.freeze({
    fetch: scopedFetch,
    async json<T = unknown>(
      input: RequestInfo | URL,
      init?: RequestInit,
    ): Promise<T> {
      // Retain this exact combined signal through decoding, rather than reread
      // mutable caller options or a newly selected workspace after an await.
      const prepared = prepareWorkspaceRequest(snapshot, apiRoot, input, init);
      const response = await scopedFetch(input, prepared);
      let body: unknown;
      try {
        body = await response.json();
      } catch (error) {
        prepared.signal?.throwIfAborted();
        if (response.ok) throw error;
        body = {};
      }
      prepared.signal?.throwIfAborted();
      if (!response.ok)
        throw parseGatewayApiError(
          body,
          response.status,
          "Workspace request failed",
        );
      return body as T;
    },
  });
}

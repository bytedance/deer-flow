/**
 * Default user identity for Gateway API calls (see backend ``get_user_id_from_request``).
 * Caller ``init.headers`` override these defaults when the same header keys are set.
 */

import { isOaAuthEnabled } from "@/core/auth/oa-auth-flags";
import { isWorkspaceLoginRequiredSync } from "@/core/auth/workspace-login-gate";

export const DEFAULT_GATEWAY_USER_ID = "gateway_test_user" as const;

const X_USER_INFO = "x-user-info";

let gatewayUserIdOverride: string | null = null;

/** When OA / SSO is enabled, set the Gateway ``user_id`` (from ``/user/oa-auth/me``). */
export function setGatewayUserIdOverride(userId: string | null): void {
  gatewayUserIdOverride = userId?.trim() ? userId.trim() : null;
}

export function getGatewayUserIdForRequest(): string {
  return gatewayUserIdOverride ?? DEFAULT_GATEWAY_USER_ID;
}

export function defaultGatewayUserHeaders(): Record<string, string> {
  return {
    [X_USER_INFO]: JSON.stringify({ user_id: getGatewayUserIdForRequest() }),
  };
}

export function mergeGatewayFetchInit(init?: RequestInit): RequestInit {
  const merged = new Headers(defaultGatewayUserHeaders());
  if (init?.headers !== undefined) {
    new Headers(init.headers).forEach((value, key) => {
      merged.set(key, value);
    });
  }
  return { ...init, headers: merged };
}

export function gatewayFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const merged = mergeGatewayFetchInit(init);
  const credentials =
    merged.credentials ??
    (isWorkspaceLoginRequiredSync() || isOaAuthEnabled()
      ? "include"
      : "same-origin");
  return fetch(input, { ...merged, credentials });
}

/** For server proxies: set default user header only if the client did not send one. */
export function applyDefaultGatewayUserHeadersIfMissing(headers: Headers): void {
  if (headers.has(X_USER_INFO)) {
    return;
  }
  const defs = defaultGatewayUserHeaders();
  headers.set(X_USER_INFO, defs[X_USER_INFO]!);
}

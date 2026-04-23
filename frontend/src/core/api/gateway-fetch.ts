/**
 * Default user identity for Gateway API calls (see backend ``get_user_id_from_request``).
 *
 * Caller ``init.headers`` override these defaults when the same header keys are set.
 *
 * Forks/deployments that need SSO / OAuth credential policies can plug in via
 * ``setGatewayUserIdOverride`` (to set the ``user_id``) and
 * ``setGatewayCredentialsHook`` (to compute ``RequestCredentials``) without
 * patching this file.
 */

export const DEFAULT_GATEWAY_USER_ID = "gateway_test_user" as const;

const X_USER_INFO = "x-user-info";

let gatewayUserIdOverride: string | null = null;

/** When SSO / OAuth is enabled, set the Gateway ``user_id`` (from your auth provider). */
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

/**
 * Pluggable credentials policy for ``gatewayFetch``.
 *
 * Forks that ship SSO (cookie-bearing OAuth, workspace login gates, etc.) can
 * register a hook to return ``"include"`` when the auth state requires it,
 * without coupling this core helper to any specific auth provider.
 */
export type CredentialsHook = () => RequestCredentials | undefined;

let credentialsHook: CredentialsHook | null = null;

export function setGatewayCredentialsHook(hook: CredentialsHook | null): void {
  credentialsHook = hook;
}

export function gatewayFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const merged = mergeGatewayFetchInit(init);
  const credentials =
    merged.credentials ?? credentialsHook?.() ?? "same-origin";
  return fetch(input, { ...merged, credentials });
}

/** For server proxies: set default user header only if the client did not send one. */
export function applyDefaultGatewayUserHeadersIfMissing(
  headers: Headers,
): void {
  if (headers.has(X_USER_INFO)) {
    return;
  }
  const defs = defaultGatewayUserHeaders();
  headers.set(X_USER_INFO, defs[X_USER_INFO]!);
}

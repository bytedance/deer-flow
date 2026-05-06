import { fetch as fetchWithAuth } from "./fetcher";
import { getTenantHeaders } from "../tenant";

/**
 * Wraps fetch() with X-DeerFlow-Tenant header injected automatically.
 * Use this for all Gateway API calls instead of raw fetch().
 */
export async function fetchGateway(
  url: string | URL,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  const tenantHeaders = getTenantHeaders();
  for (const [key, value] of Object.entries(tenantHeaders)) {
    if (!headers.has(key)) {
      headers.set(key, value);
    }
  }
  return fetchWithAuth(url, { ...init, headers });
}

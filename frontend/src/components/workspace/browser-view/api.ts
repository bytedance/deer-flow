import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export interface BrowserNavigateResult {
  screenshot: string | null;
  url: string;
  title: string;
}

export async function navigateBrowser(
  threadId: string,
  url: string,
): Promise<BrowserNavigateResult> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/browser/navigate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to navigate browser: ${response.statusText}`,
    );
  }
  return response.json();
}

/**
 * Build the WebSocket URL for the live browser stream.
 *
 * Uses the configured backend base URL when present (split-origin dev/prod),
 * otherwise falls back to the current same-origin host (nginx proxies the
 * upgrade in the unified deployment).
 *
 * When ``seedUrl`` is provided, the server aligns the live page to it when the
 * current page is blank or points at a different URL — so reconnecting to a
 * stale session lands on the page the user expects instead of a white
 * about:blank screen or a leftover page. The seed is SSRF-screened server-side.
 */
export function browserStreamURL(threadId: string, seedUrl?: string): string {
  const base = getBackendBaseURL();
  const origin =
    base && base.length > 0
      ? base
      : typeof window !== "undefined"
        ? window.location.origin
        : "";
  const wsOrigin = origin.replace(/^http/i, "ws");
  const query = seedUrl ? `?seed=${encodeURIComponent(seedUrl)}` : "";
  return `${wsOrigin}/api/threads/${encodeURIComponent(threadId)}/browser/stream${query}`;
}

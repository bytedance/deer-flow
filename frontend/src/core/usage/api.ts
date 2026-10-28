import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { UsageRunFilter, UsageRunsResponse, UsageSummary } from "./types";

async function readConsole<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${getBackendBaseURL()}/api/console/${path}`, {
    signal,
  });
  if (!response.ok) {
    await throwGatewayApiError(response, "Unable to load usage data");
  }
  return response.json() as Promise<T>;
}

export function fetchUsage(
  days: number,
  timezoneOffsetMinutes: number,
  signal?: AbortSignal,
): Promise<UsageSummary> {
  const query = new URLSearchParams({
    days: String(days),
    tz_offset_minutes: String(timezoneOffsetMinutes),
  });
  return readConsole(`usage?${query.toString()}`, signal);
}

export function fetchUsageRuns(
  offset: number,
  status: UsageRunFilter,
  signal?: AbortSignal,
): Promise<UsageRunsResponse> {
  const query = new URLSearchParams({ limit: "20", offset: String(offset) });
  if (status !== "all") query.set("status", status);
  return readConsole(`runs?${query.toString()}`, signal);
}

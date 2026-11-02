import { useQuery } from "@tanstack/react-query";

import { fetchUsage, fetchUsageRuns } from "./api";
import type { UsagePeriod, UsageRunFilter } from "./types";

// The workspace QueryClient is already account-scoped; explicit owner keys
// also fence requests when auth is unknown or a caller mounts us elsewhere.
export function useUsage(
  owner: string | undefined,
  days: UsagePeriod,
  timezoneOffsetMinutes: number,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["usage", owner, "window", days, timezoneOffsetMinutes],
    queryFn: ({ signal }) => fetchUsage(days, timezoneOffsetMinutes, signal),
    enabled: enabled && !!owner,
    staleTime: 30_000,
    retry: false,
  });
}

export function useUsageRuns(
  owner: string | undefined,
  page: number,
  status: UsageRunFilter,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["usage", owner, "runs", status, page],
    queryFn: ({ signal }) => fetchUsageRuns(page * 20, status, signal),
    enabled: enabled && !!owner,
    staleTime: 30_000,
    refetchOnWindowFocus: page === 0,
    refetchOnReconnect: page === 0,
    retry: false,
  });
}

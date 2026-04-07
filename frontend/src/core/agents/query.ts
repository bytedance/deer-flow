import { queryOptions } from "@tanstack/react-query";

import { WORKSPACE_NAV_DATA_STALE_TIME_MS } from "@/core/query/constants";

import { listAgents } from "./api";

export function agentsQueryOptions() {
  return queryOptions({
    queryKey: ["agents"],
    queryFn: () => listAgents(),
    staleTime: WORKSPACE_NAV_DATA_STALE_TIME_MS,
    refetchOnWindowFocus: false,
  });
}

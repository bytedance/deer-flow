import { queryOptions } from "@tanstack/react-query";

import { WORKSPACE_NAV_DATA_STALE_TIME_MS } from "@/core/query/constants";

import { loadModels } from "./api";

export function modelsQueryOptions() {
  return queryOptions({
    queryKey: ["models"],
    queryFn: () => loadModels(),
    staleTime: WORKSPACE_NAV_DATA_STALE_TIME_MS,
    refetchOnWindowFocus: false,
  });
}

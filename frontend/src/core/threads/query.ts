import type { ThreadsClient } from "@langchain/langgraph-sdk/client";
import { queryOptions } from "@tanstack/react-query";

import { getAPIClient } from "@/core/api";
import { WORKSPACE_NAV_DATA_STALE_TIME_MS } from "@/core/query/constants";

import type { AgentThread, AgentThreadState } from "./types";

type ThreadSearchParams = NonNullable<Parameters<ThreadsClient["search"]>[0]>;

export const DEFAULT_THREADS_SEARCH_PARAMS: ThreadSearchParams = {
  limit: 50,
  sortBy: "updated_at",
  sortOrder: "desc",
  select: ["thread_id", "updated_at", "values"],
};

export function threadsSearchQueryOptions(
  params: Parameters<ThreadsClient["search"]>[0] = DEFAULT_THREADS_SEARCH_PARAMS,
) {
  const normalizedParams: ThreadSearchParams =
    params ?? DEFAULT_THREADS_SEARCH_PARAMS;
  const apiClient = getAPIClient();

  return queryOptions<AgentThread[]>({
    queryKey: ["threads", "search", normalizedParams],
    queryFn: async () => {
      const maxResults = normalizedParams.limit;
      const initialOffset = normalizedParams.offset ?? 0;
      const DEFAULT_PAGE_SIZE = 50;

      if (maxResults !== undefined && maxResults <= 0) {
        const response =
          await apiClient.threads.search<AgentThreadState>(normalizedParams);
        return response as AgentThread[];
      }

      const pageSize =
        typeof maxResults === "number" && maxResults > 0
          ? Math.min(DEFAULT_PAGE_SIZE, maxResults)
          : DEFAULT_PAGE_SIZE;

      const threads: AgentThread[] = [];
      let offset = initialOffset;

      while (true) {
        if (typeof maxResults === "number" && threads.length >= maxResults) {
          break;
        }

        const currentLimit =
          typeof maxResults === "number"
            ? Math.min(pageSize, maxResults - threads.length)
            : pageSize;

        if (typeof maxResults === "number" && currentLimit <= 0) {
          break;
        }

        const response = (await apiClient.threads.search<AgentThreadState>({
          ...normalizedParams,
          limit: currentLimit,
          offset,
        })) as AgentThread[];

        threads.push(...response);

        if (response.length < currentLimit) {
          break;
        }

        offset += response.length;
      }

      return threads;
    },
    staleTime: WORKSPACE_NAV_DATA_STALE_TIME_MS,
    refetchOnWindowFocus: false,
  });
}

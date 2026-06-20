import type { ThreadsClient } from "@langchain/langgraph-sdk/client";

import type { AgentThread, AgentThreadState } from "./types";

type ThreadsSearchClient = {
  threads: {
    search: ThreadsClient["search"];
  };
};

export type ThreadSearchParams = NonNullable<
  Parameters<ThreadsClient["search"]>[0]
>;

export const DEFAULT_THREAD_SEARCH_PARAMS: ThreadSearchParams = {
  limit: 50,
  sortBy: "updated_at",
  sortOrder: "desc",
  select: ["thread_id", "updated_at", "values", "metadata"],
};

export const THREAD_SEARCH_REFETCH_INTERVAL_MS = 5000;

export function buildThreadsSearchQueryOptions(
  apiClient: ThreadsSearchClient,
  params: ThreadSearchParams = DEFAULT_THREAD_SEARCH_PARAMS,
) {
  return {
    queryKey: ["threads", "search", params],
    queryFn: async () => {
      const maxResults = params.limit;
      const initialOffset = params.offset ?? 0;
      const DEFAULT_PAGE_SIZE = 50;

      // Preserve prior semantics: if a non-positive limit is explicitly provided,
      // delegate to a single search call with the original parameters.
      if (maxResults !== undefined && maxResults <= 0) {
        const response =
          await apiClient.threads.search<AgentThreadState>(params);
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
          ...params,
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
    refetchInterval: THREAD_SEARCH_REFETCH_INTERVAL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
  };
}

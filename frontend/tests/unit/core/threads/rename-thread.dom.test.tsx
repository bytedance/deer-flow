import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import {
  type InfiniteData,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const apiMocks = rs.hoisted(() => ({
  updateState: rs.fn(),
}));

rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    threads: {
      updateState: apiMocks.updateState,
    },
  }),
}));

import {
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  useRenameThread,
} from "@/core/threads/hooks";
import { DEFAULT_THREAD_SEARCH_PARAMS } from "@/core/threads/thread-search-query";
import type { AgentThread } from "@/core/threads/types";

const THREAD_ID = "thread-1";
const ORIGINAL_TITLE = "Original title";
const RENAMED_TITLE = "Renamed title";

function makeThread(title: string): AgentThread {
  return {
    thread_id: THREAD_ID,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    metadata: {},
    status: "idle",
    values: { title },
  } as unknown as AgentThread;
}

function createDelayedResult<T>(value: T) {
  let markStarted!: () => void;
  const started = new Promise<void>((resolve) => {
    markStarted = resolve;
  });
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let markCompleted!: () => void;
  const completed = new Promise<void>((resolve) => {
    markCompleted = resolve;
  });

  return {
    completed,
    queryFn: async () => {
      markStarted();
      await gate;
      markCompleted();
      return value;
    },
    release,
    started,
  };
}

function readSearchTitle(
  queryClient: QueryClient,
  queryKey: readonly unknown[],
) {
  return queryClient.getQueryData<AgentThread[]>(queryKey)?.[0]?.values.title;
}

function readInfiniteSearchTitle(
  queryClient: QueryClient,
  queryKey: readonly unknown[],
) {
  return queryClient.getQueryData<InfiniteData<AgentThread[]>>(queryKey)
    ?.pages[0]?.[0]?.values.title;
}

test("stale list responses cannot restore the old title after rename", async () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const infiniteParams = {
    sortBy: "updated_at",
    sortOrder: "desc",
    select: ["thread_id", "updated_at", "values", "metadata"],
  };
  const searchKey = [
    "threads",
    "search",
    DEFAULT_THREAD_SEARCH_PARAMS,
  ] as const;
  const infiniteSearchKey = [
    ...INFINITE_THREADS_QUERY_KEY_PREFIX,
    infiniteParams,
  ] as const;
  const originalThread = makeThread(ORIGINAL_TITLE);
  const staleSearch = createDelayedResult([originalThread]);
  const staleInfiniteSearch = createDelayedResult([originalThread]);

  queryClient.setQueryData(searchKey, [originalThread]);
  queryClient.setQueryData<InfiniteData<AgentThread[]>>(infiniteSearchKey, {
    pages: [[originalThread]],
    pageParams: [0],
  });

  const searchFetch = queryClient
    .fetchQuery({
      queryKey: searchKey,
      queryFn: staleSearch.queryFn,
    })
    .catch(() => undefined);
  const infiniteSearchFetch = queryClient
    .fetchInfiniteQuery({
      queryKey: infiniteSearchKey,
      initialPageParam: 0,
      queryFn: staleInfiniteSearch.queryFn,
      getNextPageParam: () => undefined,
    })
    .catch(() => undefined);

  await Promise.all([staleSearch.started, staleInfiniteSearch.started]);
  apiMocks.updateState.mockResolvedValue(undefined);
  const { result } = renderHook(() => useRenameThread(), { wrapper });

  await act(async () => {
    await result.current.mutateAsync({
      threadId: THREAD_ID,
      title: RENAMED_TITLE,
    });
  });

  expect(readSearchTitle(queryClient, searchKey)).toBe(RENAMED_TITLE);
  expect(readInfiniteSearchTitle(queryClient, infiniteSearchKey)).toBe(
    RENAMED_TITLE,
  );

  staleSearch.release();
  staleInfiniteSearch.release();
  await Promise.all([staleSearch.completed, staleInfiniteSearch.completed]);
  await Promise.all([searchFetch, infiniteSearchFetch]);

  expect(readSearchTitle(queryClient, searchKey)).toBe(RENAMED_TITLE);
  expect(readInfiniteSearchTitle(queryClient, infiniteSearchKey)).toBe(
    RENAMED_TITLE,
  );

  queryClient.clear();
});

beforeEach(() => {
  apiMocks.updateState.mockReset();
});

afterEach(() => {
  cleanup();
});

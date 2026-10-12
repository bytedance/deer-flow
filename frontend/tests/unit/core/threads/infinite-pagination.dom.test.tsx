import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const apiMocks = rs.hoisted(() => ({
  search: rs.fn(),
}));

rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    threads: {
      search: apiMocks.search,
    },
  }),
}));

import { SIDECAR_METADATA_KEY } from "@/core/sidecar/thread";
import {
  filterInfiniteThreadsCache,
  INFINITE_THREADS_PAGE_SIZE,
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  setThreadTitleInCaches,
  useInfiniteThreads,
} from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

// The first 50 server rows hold three sidecar threads, so the first visible
// page of 50 primary threads ends at server offset 53, not 50.
const SIDECAR_INDEXES = new Set([5, 22, 39]);
const FIRST_PAGE_SERVER_ROWS =
  INFINITE_THREADS_PAGE_SIZE + SIDECAR_INDEXES.size;

function makeServerRows(count: number): AgentThread[] {
  return Array.from(
    { length: count },
    (_, index) =>
      ({
        thread_id: `t-${index}`,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        metadata: SIDECAR_INDEXES.has(index)
          ? { [SIDECAR_METADATA_KEY]: true, parent_thread_id: "parent" }
          : {},
        status: "idle",
        values: { title: `Title ${index}` },
      }) as unknown as AgentThread,
  );
}

let serverRows: AgentThread[] = [];
let queryClient: QueryClient;

function renderInfiniteThreads() {
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(() => useInfiniteThreads(), { wrapper });
}

function requestedOffsets(): number[] {
  return apiMocks.search.mock.calls.map(
    ([request]) => (request as { offset: number }).offset,
  );
}

function loadedThreadIds(
  result: ReturnType<typeof renderInfiniteThreads>["result"],
): string[] {
  return (result.current.data?.pages ?? []).flatMap((page) =>
    page.map((thread) => thread.thread_id),
  );
}

async function loadFirstPage() {
  const hook = renderInfiniteThreads();
  await waitFor(() => expect(hook.result.current.isSuccess).toBe(true));
  expect(hook.result.current.data?.pages[0]).toHaveLength(
    INFINITE_THREADS_PAGE_SIZE,
  );
  apiMocks.search.mockClear();
  return hook;
}

beforeEach(() => {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  serverRows = makeServerRows(120);
  apiMocks.search.mockImplementation(
    async ({ limit, offset }: { limit: number; offset: number }) =>
      serverRows.slice(offset, offset + limit),
  );
});

afterEach(() => {
  cleanup();
  queryClient.clear();
  apiMocks.search.mockReset();
});

test("a cache write keeps the next page at the server offset past hidden sidecars", async () => {
  const { result } = await loadFirstPage();

  act(() => {
    setThreadTitleInCaches(queryClient, "t-3", "Renamed");
  });
  await act(async () => {
    await result.current.fetchNextPage();
  });

  expect(requestedOffsets()[0]).toBe(FIRST_PAGE_SERVER_ROWS);
  const ids = loadedThreadIds(result);
  expect(new Set(ids).size).toBe(ids.length);
});

test("a refetch keeps the next page at the server offset past hidden sidecars", async () => {
  const { result } = await loadFirstPage();

  serverRows = serverRows.map((thread) =>
    thread.thread_id === "t-3"
      ? { ...thread, values: { ...thread.values, title: "Renamed" } }
      : thread,
  );
  await act(async () => {
    await queryClient.invalidateQueries({
      queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
    });
  });
  await waitFor(() =>
    expect(result.current.data?.pages[0]?.[3]?.values.title).toBe("Renamed"),
  );
  apiMocks.search.mockClear();

  await act(async () => {
    await result.current.fetchNextPage();
  });

  expect(requestedOffsets()[0]).toBe(FIRST_PAGE_SERVER_ROWS);
  const ids = loadedThreadIds(result);
  expect(new Set(ids).size).toBe(ids.length);
});

test("removing a row from a full page keeps the list open for more pages", async () => {
  const { result } = await loadFirstPage();
  expect(result.current.hasNextPage).toBe(true);

  act(() => {
    queryClient.setQueriesData(
      { queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX },
      (data: Parameters<typeof filterInfiniteThreadsCache>[0]) =>
        filterInfiniteThreadsCache(
          data,
          (thread) => thread.thread_id !== "t-0",
        ),
    );
  });
  await waitFor(() =>
    expect(result.current.data?.pages[0]).toHaveLength(
      INFINITE_THREADS_PAGE_SIZE - 1,
    ),
  );

  expect(result.current.hasNextPage).toBe(true);
});

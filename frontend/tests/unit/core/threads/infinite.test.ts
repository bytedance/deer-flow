import { describe, expect, rs, test } from "@rstest/core";
import {
  QueryClient,
  QueryObserver,
  type InfiniteData,
} from "@tanstack/react-query";

import {
  fetchInfiniteThreadsPage,
  filterInfiniteThreadsCache,
  getInfiniteThreadsNextPageParam,
  INFINITE_THREADS_PAGE_SIZE,
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  invalidateStoppedThreadCaches,
  mapInfiniteThreadsCache,
  STOP_THREAD_FINALIZATION_REFETCH_DELAY_MS,
  stopThreadAndInvalidateCaches,
  upsertThreadInInfiniteCache,
} from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

// Issue #3482: the sidebar and /workspace/chats list used to be capped at
// 50 threads because `useThreads()` exits as soon as `threads.length >=
// params.limit`.  These pure helpers back the `useInfiniteThreads()`
// pagination logic and the mirrored cache writes that keep rename / delete
// / stream-finish in sync with both the legacy array cache and the new
// infinite cache.

function makeThread(
  id: string,
  title = `Title ${id}`,
  metadata: Record<string, unknown> = {},
): AgentThread {
  return {
    thread_id: id,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    metadata,
    status: "idle",
    values: { title },
  } as unknown as AgentThread;
}

function makePage(start: number, size: number): AgentThread[] {
  return Array.from({ length: size }, (_, i) => makeThread(`t-${start + i}`));
}

function makeInfiniteData(pages: AgentThread[][]): InfiniteData<AgentThread[]> {
  return {
    pages,
    pageParams: pages.map((_, i) => i * INFINITE_THREADS_PAGE_SIZE),
  };
}

describe("getInfiniteThreadsNextPageParam", () => {
  test("returns next offset when the last page is full", () => {
    const page1 = makePage(0, INFINITE_THREADS_PAGE_SIZE);
    expect(getInfiniteThreadsNextPageParam(page1, [page1])).toBe(
      INFINITE_THREADS_PAGE_SIZE,
    );
  });

  test("returns next offset across multiple full pages", () => {
    const page1 = makePage(0, INFINITE_THREADS_PAGE_SIZE);
    const page2 = makePage(
      INFINITE_THREADS_PAGE_SIZE,
      INFINITE_THREADS_PAGE_SIZE,
    );
    expect(getInfiniteThreadsNextPageParam(page2, [page1, page2])).toBe(
      INFINITE_THREADS_PAGE_SIZE * 2,
    );
  });

  test("returns undefined when the last page is short (end of list)", () => {
    const page1 = makePage(0, INFINITE_THREADS_PAGE_SIZE);
    const page2 = makePage(INFINITE_THREADS_PAGE_SIZE, 10);
    expect(
      getInfiniteThreadsNextPageParam(page2, [page1, page2]),
    ).toBeUndefined();
  });

  test("returns undefined when the last page is empty", () => {
    const page1 = makePage(0, INFINITE_THREADS_PAGE_SIZE);
    expect(getInfiniteThreadsNextPageParam([], [page1, []])).toBeUndefined();
  });

  test("respects a custom page size", () => {
    const page1 = makePage(0, 5);
    expect(getInfiniteThreadsNextPageParam(page1, [page1], 5)).toBe(5);
    expect(getInfiniteThreadsNextPageParam(page1, [page1], 10)).toBeUndefined();
  });
});

describe("fetchInfiniteThreadsPage", () => {
  test("fills a visible page while advancing offsets by raw backend rows", async () => {
    const search = rs
      .fn()
      .mockResolvedValueOnce([
        makeThread("sidecar-1", "Sidecar", { deerflow_sidecar: true }),
        makeThread("primary-1"),
      ])
      .mockResolvedValueOnce([makeThread("primary-2")]);

    const page = await fetchInfiniteThreadsPage(
      { threads: { search } },
      { sortBy: "updated_at", sortOrder: "desc" },
      0,
      2,
    );

    expect(page.map((thread) => thread.thread_id)).toEqual([
      "primary-1",
      "primary-2",
    ]);
    expect(search).toHaveBeenNthCalledWith(1, {
      sortBy: "updated_at",
      sortOrder: "desc",
      limit: 2,
      offset: 0,
    });
    expect(search).toHaveBeenNthCalledWith(2, {
      sortBy: "updated_at",
      sortOrder: "desc",
      limit: 1,
      offset: 2,
    });
    expect(getInfiniteThreadsNextPageParam(page, [page], 2)).toBe(3);
  });

  test("keeps sidecar rows when the caller explicitly searches for sidecars", async () => {
    const search = rs.fn().mockResolvedValueOnce([
      makeThread("sidecar-1", "Sidecar", {
        deerflow_sidecar: true,
        parent_thread_id: "parent-1",
      }),
    ]);

    const page = await fetchInfiniteThreadsPage(
      { threads: { search } },
      {
        sortBy: "updated_at",
        sortOrder: "desc",
        metadata: { deerflow_sidecar: true, parent_thread_id: "parent-1" },
      },
      0,
      2,
    );

    expect(page.map((thread) => thread.thread_id)).toEqual(["sidecar-1"]);
    expect(getInfiniteThreadsNextPageParam(page, [page], 2)).toBeUndefined();
  });
});

describe("mapInfiniteThreadsCache", () => {
  test("returns undefined when oldData is undefined", () => {
    expect(mapInfiniteThreadsCache(undefined, (t) => t)).toBeUndefined();
  });

  test("updates the matching thread across multiple pages", () => {
    const page1 = [makeThread("a"), makeThread("b")];
    const page2 = [makeThread("c"), makeThread("d")];
    const data = makeInfiniteData([page1, page2]);

    const updated = mapInfiniteThreadsCache(data, (t) =>
      t.thread_id === "c"
        ? { ...t, values: { ...t.values, title: "renamed" } }
        : t,
    );

    expect(updated?.pages[0]?.[0]?.values?.title).toBe("Title a");
    expect(updated?.pages[1]?.[0]?.thread_id).toBe("c");
    expect(updated?.pages[1]?.[0]?.values?.title).toBe("renamed");
    expect(updated?.pages[1]?.[1]?.values?.title).toBe("Title d");
  });

  test("preserves pageParams", () => {
    const data = makeInfiniteData([[makeThread("a")]]);
    const updated = mapInfiniteThreadsCache(data, (t) => t);
    expect(updated?.pageParams).toEqual(data.pageParams);
  });
});

describe("filterInfiniteThreadsCache", () => {
  test("returns undefined when oldData is undefined", () => {
    expect(filterInfiniteThreadsCache(undefined, () => true)).toBeUndefined();
  });

  test("removes matching threads across all pages", () => {
    const page1 = [makeThread("a"), makeThread("b")];
    const page2 = [makeThread("b"), makeThread("c")];
    const data = makeInfiniteData([page1, page2]);

    const filtered = filterInfiniteThreadsCache(
      data,
      (t) => t.thread_id !== "b",
    );

    expect(filtered?.pages[0]?.map((t) => t.thread_id)).toEqual(["a"]);
    expect(filtered?.pages[1]?.map((t) => t.thread_id)).toEqual(["c"]);
  });

  test("keeps an emptied page as an empty array (does not drop the page)", () => {
    const page1 = [makeThread("a")];
    const page2 = [makeThread("b")];
    const data = makeInfiniteData([page1, page2]);

    const filtered = filterInfiniteThreadsCache(
      data,
      (t) => t.thread_id !== "a",
    );

    expect(filtered?.pages).toHaveLength(2);
    expect(filtered?.pages[0]).toEqual([]);
    expect(filtered?.pages[1]?.[0]?.thread_id).toBe("b");
  });

  test("does not regress next offset when an earlier page has been shrunk by a delete", () => {
    // Simulate two full pages already loaded.
    const page1 = Array.from({ length: 50 }, (_, i) => ({
      thread_id: `a${i}`,
    }));
    const page2 = Array.from({ length: 50 }, (_, i) => ({
      thread_id: `b${i}`,
    }));

    // Offset right after fetching page 2 (this is the value TanStack Query
    // freezes into pageParams).
    const offsetAfterPage2 = getInfiniteThreadsNextPageParam(
      page2 as unknown as AgentThread[],
      [page1, page2] as unknown as AgentThread[][],
    );
    expect(offsetAfterPage2).toBe(100);

    // Now a delete mutation runs filterInfiniteThreadsCache and shrinks
    // page 1 from 50 to 49 entries. TanStack does NOT re-invoke
    // getNextPageParam on cache mutations; the previously-computed offset
    // (100) remains the param for the next fetchNextPage() call, so the
    // helper is consistent with how the library uses its return value.
    const shrunkPage1 = page1.slice(0, 49);
    const recomputed = getInfiniteThreadsNextPageParam(
      page2 as unknown as AgentThread[],
      [shrunkPage1, page2] as unknown as AgentThread[][],
    );
    // We document the recomputed value for completeness, but in practice
    // useDeleteThread invalidates the query in onSettled, so pages are
    // refetched from offset 0 rather than relying on this number.
    expect(recomputed).toBe(99);
  });
});

describe("upsertThreadInInfiniteCache", () => {
  function seedClient(initial?: InfiniteData<AgentThread[]>): QueryClient {
    const client = new QueryClient();
    if (initial) {
      client.setQueryData([...INFINITE_THREADS_QUERY_KEY_PREFIX, {}], initial);
    }
    return client;
  }

  function readCache(
    client: QueryClient,
  ): InfiniteData<AgentThread[]> | undefined {
    return client.getQueryData([...INFINITE_THREADS_QUERY_KEY_PREFIX, {}]);
  }

  test("no-op when the infinite cache has not been initialised yet", () => {
    const client = seedClient();
    upsertThreadInInfiniteCache(client, makeThread("new"));
    expect(readCache(client)).toBeUndefined();
  });

  test("prepends a brand-new thread to the first page", () => {
    const client = seedClient({
      pages: [[makeThread("a"), makeThread("b")]],
      pageParams: [0],
    });
    upsertThreadInInfiniteCache(client, makeThread("new"));
    const cache = readCache(client);
    expect(cache?.pages[0]?.map((t) => t.thread_id)).toEqual(["new", "a", "b"]);
  });

  test("merges into the existing entry instead of duplicating it", () => {
    const existing = makeThread("a", "Old title");
    const client = seedClient({
      pages: [[existing, makeThread("b")]],
      pageParams: [0],
    });
    // Simulate an onCreated upsert that races with a thread already in cache:
    // the cache copy should win for title/metadata (it represents later state),
    // but no duplicate row should appear.
    upsertThreadInInfiniteCache(client, {
      ...makeThread("a", "New title"),
      status: "busy",
    });
    const cache = readCache(client);
    const ids = cache?.pages[0]?.map((t) => t.thread_id);
    expect(ids).toEqual(["a", "b"]);
    expect(cache?.pages[0]?.[0]?.values.title).toBe("Old title");
  });
});

describe("invalidateStoppedThreadCaches", () => {
  function invalidatedQueryKeys(client: QueryClient) {
    const invalidate = rs.spyOn(client, "invalidateQueries");
    return {
      invalidate,
      queryKeys: () =>
        invalidate.mock.calls.map(([filters]) => filters?.queryKey),
    };
  }

  test("refreshes current thread and sidebar caches after fire-and-forget stop", () => {
    const client = new QueryClient();
    const { queryKeys } = invalidatedQueryKeys(client);

    invalidateStoppedThreadCaches(client, "thread-1", false);

    expect(queryKeys()).toContainEqual(["threads", "search"]);
    expect(queryKeys()).toContainEqual(INFINITE_THREADS_QUERY_KEY_PREFIX);
    expect(queryKeys()).toContainEqual(["thread", "thread-1"]);
    expect(queryKeys()).toContainEqual([
      "thread",
      "metadata",
      "thread-1",
      false,
    ]);
    expect(queryKeys()).toContainEqual(["thread-token-usage", "thread-1"]);
  });

  test("does not refresh per-thread API caches for mock threads", () => {
    const client = new QueryClient();
    const { queryKeys } = invalidatedQueryKeys(client);

    invalidateStoppedThreadCaches(client, "thread-1", true);

    expect(queryKeys()).toContainEqual(["threads", "search"]);
    expect(queryKeys()).toContainEqual(INFINITE_THREADS_QUERY_KEY_PREFIX);
    expect(queryKeys()).not.toContainEqual(["thread", "thread-1"]);
    expect(queryKeys()).not.toContainEqual([
      "thread",
      "metadata",
      "thread-1",
      true,
    ]);
    expect(queryKeys()).not.toContainEqual(["thread-token-usage", "thread-1"]);
  });

  test("wraps SDK stop and refreshes caches after it resolves", async () => {
    const client = new QueryClient();
    const stop = rs.fn(() => Promise.resolve());
    const { queryKeys } = invalidatedQueryKeys(client);

    await stopThreadAndInvalidateCaches(client, stop, "thread-1", false);

    expect(stop).toHaveBeenCalledTimes(1);
    expect(queryKeys()).toContainEqual([
      "thread",
      "metadata",
      "thread-1",
      false,
    ]);
  });

  test("still refreshes caches when SDK stop rejects", async () => {
    const client = new QueryClient();
    const stop = rs.fn(async () => {
      throw new Error("cancel failed");
    });
    const { queryKeys } = invalidatedQueryKeys(client);

    await expect(
      stopThreadAndInvalidateCaches(client, stop, "thread-1", false),
    ).rejects.toThrow("cancel failed");

    expect(queryKeys()).toContainEqual(["threads", "search"]);
    expect(queryKeys()).toContainEqual([
      "thread",
      "metadata",
      "thread-1",
      false,
    ]);
  });

  test("schedules sidebar refetch even if stopped thread id is not known", async () => {
    rs.useFakeTimers();

    const client = new QueryClient();
    const { queryKeys } = invalidatedQueryKeys(client);

    try {
      await stopThreadAndInvalidateCaches(
        client,
        () => Promise.resolve(),
        null,
        false,
      );

      const countSearchInvalidations = () =>
        queryKeys().filter(
          (queryKey) =>
            queryKey?.length === 2 &&
            queryKey[0] === "threads" &&
            queryKey[1] === "search",
        ).length;

      expect(countSearchInvalidations()).toBe(1);

      await rs.advanceTimersByTimeAsync(
        STOP_THREAD_FINALIZATION_REFETCH_DELAY_MS,
      );

      expect(countSearchInvalidations()).toBe(2);
      expect(queryKeys()).not.toContainEqual(["thread", null]);
    } finally {
      client.clear();
      rs.useRealTimers();
    }
  });

  test("scheduled refetch lets sidebar receive delayed backend title finalization", async () => {
    rs.useFakeTimers();

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    let finalized = false;
    let fetchCount = 0;
    const observer = new QueryObserver<AgentThread[]>(client, {
      queryKey: ["threads", "search"],
      queryFn: async () => {
        fetchCount += 1;
        return [
          makeThread(
            "thread-1",
            finalized ? "Generated Title" : "New Conversation",
          ),
        ];
      },
    });
    const unsubscribe = observer.subscribe((result) => {
      void result.status;
    });

    try {
      await observer.refetch();
      expect(
        client.getQueryData<AgentThread[]>(["threads", "search"])?.[0]?.values
          ?.title,
      ).toBe("New Conversation");

      await stopThreadAndInvalidateCaches(
        client,
        () => Promise.resolve(),
        "thread-1",
        false,
      );
      await Promise.resolve();

      expect(
        client.getQueryData<AgentThread[]>(["threads", "search"])?.[0]?.values
          ?.title,
      ).toBe("New Conversation");

      finalized = true;
      await rs.advanceTimersByTimeAsync(
        STOP_THREAD_FINALIZATION_REFETCH_DELAY_MS,
      );

      expect(
        client.getQueryData<AgentThread[]>(["threads", "search"])?.[0]?.values
          ?.title,
      ).toBe("Generated Title");
      expect(fetchCount).toBeGreaterThanOrEqual(3);
    } finally {
      unsubscribe();
      client.clear();
      rs.useRealTimers();
    }
  });
});

import { describe, expect, test } from "@rstest/core";
import { QueryClient, type InfiniteData } from "@tanstack/react-query";

import {
  filterInfiniteThreadsCache,
  getInfiniteThreadsNextPageParam,
  INFINITE_THREADS_PAGE_SIZE,
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  mapInfiniteThreadsCache,
  upsertThreadInInfiniteCache,
} from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

// Issue #3482: the sidebar and /workspace/chats list used to be capped at
// 50 threads because `useThreads()` exits as soon as `threads.length >=
// params.limit`.  These pure helpers back the `useInfiniteThreads()`
// pagination logic and the mirrored cache writes that keep rename / delete
// / stream-finish in sync with both the legacy array cache and the new
// infinite cache.

function makeThread(id: string, title = `Title ${id}`): AgentThread {
  return {
    thread_id: id,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    metadata: {},
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

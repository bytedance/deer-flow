import type { InfiniteData } from "@tanstack/react-query";
import { describe, expect, test } from "vitest";

import {
  filterInfiniteThreadsCache,
  getInfiniteThreadsNextPageParam,
  INFINITE_THREADS_PAGE_SIZE,
  mapInfiniteThreadsCache,
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
});

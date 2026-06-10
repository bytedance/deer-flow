import type { InfiniteData } from "@tanstack/react-query";
import { describe, expect, test } from "vitest";

import {
  patchThreadInSearchCache,
  removeThreadFromSearchCache,
  upsertThreadIntoSearchCache,
  type ThreadSearchCache,
} from "@/core/threads/search-cache";
import type { AgentThread } from "@/core/threads/types";

function thread(id: string, title: string): AgentThread {
  return {
    thread_id: id,
    metadata: {},
    values: { title },
  } as unknown as AgentThread;
}

// Two pages, mirroring how useThreads accumulates paginated results. The bug in
// #3482's first fix was treating this as a flat array; these helpers must walk
// `pages` instead.
function twoPageCache(): InfiniteData<AgentThread[], number> {
  return {
    pages: [
      [thread("a", "Alpha"), thread("b", "Beta")],
      [thread("c", "Gamma"), thread("d", "Delta")],
    ],
    pageParams: [0, 2],
  };
}

describe("patchThreadInSearchCache", () => {
  test("updates a thread that lives on a later page", () => {
    const next = patchThreadInSearchCache(twoPageCache(), "c", (t) => ({
      ...t,
      values: { ...t.values, title: "Renamed" },
    }));

    expect(next?.pages[1]?.[0]?.values?.title).toBe("Renamed");
    // Other threads and the page/pageParam structure are untouched.
    expect(next?.pages[0]?.map((t) => t.values?.title)).toEqual([
      "Alpha",
      "Beta",
    ]);
    expect(next?.pages[1]?.[1]?.values?.title).toBe("Delta");
    expect(next?.pageParams).toEqual([0, 2]);
  });

  test("no-ops on a missing thread and passes undefined through", () => {
    const cache = twoPageCache();
    const next = patchThreadInSearchCache(cache, "missing", (t) => ({
      ...t,
      values: { ...t.values, title: "X" },
    }));
    expect(next?.pages).toEqual(cache.pages);
    expect(patchThreadInSearchCache(undefined, "a", (t) => t)).toBeUndefined();
  });
});

describe("removeThreadFromSearchCache", () => {
  test("drops the thread from its page only", () => {
    const next = removeThreadFromSearchCache(twoPageCache(), "b");
    expect(next?.pages[0]?.map((t) => t.thread_id)).toEqual(["a"]);
    expect(next?.pages[1]?.map((t) => t.thread_id)).toEqual(["c", "d"]);
  });

  test("passes undefined through", () => {
    expect(
      removeThreadFromSearchCache(undefined as ThreadSearchCache, "a"),
    ).toBeUndefined();
  });
});

describe("upsertThreadIntoSearchCache", () => {
  test("seeds a fresh cache when none exists", () => {
    const next = upsertThreadIntoSearchCache(undefined, thread("a", "Alpha"));
    expect(next).toEqual({
      pages: [[thread("a", "Alpha")]],
      pageParams: [0],
    });
  });

  test("prepends a brand-new thread to the first page", () => {
    const next = upsertThreadIntoSearchCache(twoPageCache(), thread("z", "Zed"));
    expect(next.pages[0]?.map((t) => t.thread_id)).toEqual(["z", "a", "b"]);
    expect(next.pages[1]?.map((t) => t.thread_id)).toEqual(["c", "d"]);
  });

  test("merges an existing thread in place without duplicating it", () => {
    const incoming = {
      thread_id: "c",
      metadata: { agent_name: "researcher" },
      values: { title: "ignored-because-existing-wins", subtitle: "added" },
    } as unknown as AgentThread;

    const next = upsertThreadIntoSearchCache(twoPageCache(), incoming);

    const ids = next.pages.flat().map((t) => t.thread_id);
    expect(ids).toEqual(["a", "b", "c", "d"]); // no duplicate, stays on page 2
    const merged = next.pages[1]?.[0];
    // Existing values win; new fields are merged in.
    expect(merged?.values?.title).toBe("Gamma");
    expect(
      (merged?.values as Record<string, unknown>)?.subtitle,
    ).toBe("added");
    expect((merged?.metadata as Record<string, unknown>)?.agent_name).toBe(
      "researcher",
    );
  });
});

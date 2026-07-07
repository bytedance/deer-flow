import { expect, test, rs } from "@rstest/core";

import {
  buildThreadsSearchQueryOptions,
  DEFAULT_THREAD_SEARCH_PARAMS,
  THREAD_SEARCH_REFETCH_INTERVAL_MS,
} from "@/core/threads/thread-search-query";
import type { AgentThread } from "@/core/threads/types";

function makeThread(
  threadId: string,
  metadata: Record<string, unknown> = {},
): AgentThread {
  return {
    thread_id: threadId,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    metadata,
    status: "idle",
    values: { title: threadId, messages: [] },
  } as unknown as AgentThread;
}

test("thread search query refreshes so IM-created sessions appear in the sidebar", () => {
  const search = rs.fn();
  const options = buildThreadsSearchQueryOptions(
    { threads: { search } },
    DEFAULT_THREAD_SEARCH_PARAMS,
  );

  expect(options.refetchInterval).toBe(THREAD_SEARCH_REFETCH_INTERVAL_MS);
  expect(options.refetchIntervalInBackground).toBe(false);
  expect(options.refetchOnWindowFocus).toBe(false);
});

test("thread search hides sidecar threads from primary lists by default", async () => {
  const search = rs
    .fn()
    .mockResolvedValue([
      makeThread("primary-1"),
      makeThread("sidecar-1", { deerflow_sidecar: true }),
      makeThread("primary-2"),
    ]);
  const options = buildThreadsSearchQueryOptions(
    { threads: { search } },
    DEFAULT_THREAD_SEARCH_PARAMS,
  );

  await expect(options.queryFn()).resolves.toEqual([
    makeThread("primary-1"),
    makeThread("primary-2"),
  ]);
});

test("thread search can explicitly include sidecar threads for parent lookup", async () => {
  const sidecar = makeThread("sidecar-1", {
    deerflow_sidecar: true,
    parent_thread_id: "parent-1",
  });
  const search = rs.fn().mockResolvedValue([sidecar]);
  const options = buildThreadsSearchQueryOptions(
    { threads: { search } },
    {
      ...DEFAULT_THREAD_SEARCH_PARAMS,
      metadata: {
        deerflow_sidecar: true,
        parent_thread_id: "parent-1",
      },
    },
  );

  await expect(options.queryFn()).resolves.toEqual([sidecar]);
});

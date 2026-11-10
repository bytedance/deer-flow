import { beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient } from "@tanstack/react-query";

import type { AgentThread } from "@/core/threads/types";

// The rollback after a rejected first send may only delete the thread that
// Gateway admission created with no checkpoint. A thread that already has a
// checkpoint (project pre-create, saved goal, accepted run) must survive, and
// any unreadable state or failed delete keeps the row.

const mocks = rs.hoisted(() => ({
  state: { kind: "404" as "404" | "ok" | "500" },
  getState: rs.fn(async () => ({ values: {} })),
  delete: rs.fn(async () => undefined),
  deletedLocal: [] as string[],
  fetchStatus: 404,
}));

rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    threads: {
      getState: mocks.getState,
      delete: mocks.delete,
      search: async () => [],
    },
  }),
}));

function thread(threadId: string): AgentThread {
  return {
    thread_id: threadId,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    metadata: {},
    status: "idle",
    values: { messages: [], artifacts: [], title: "", todos: [] },
    interrupts: {},
  } as AgentThread;
}

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { status });
}

function createQueryClient(threadId = "new-thread") {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["threads", "search"], [thread(threadId)]);
  const invalidate = rs.spyOn(queryClient, "invalidateQueries");
  return { queryClient, invalidate };
}

beforeEach(() => {
  mocks.delete.mockReset();
  mocks.deletedLocal = [];
  mocks.fetchStatus = 404;
  mocks.getState.mockReset();
  mocks.getState.mockRejectedValue(httpError(404));
  rs.stubGlobal("fetch", async (input: unknown) => {
    mocks.deletedLocal.push(String(input));
    return new Response(null, { status: mocks.fetchStatus });
  });
});

test("deletes the unwritten thread and drops it from the sidebar caches", async () => {
  const { discardUnwrittenThread } = await import("@/core/threads/hooks");
  const { queryClient } = createQueryClient();

  await expect(discardUnwrittenThread(queryClient, "new-thread")).resolves.toBe(
    true,
  );

  expect(mocks.delete).toHaveBeenCalledWith("new-thread");
  expect(mocks.deletedLocal).toHaveLength(1);
  const cachedThreads = queryClient.getQueryData<AgentThread[]>([
    "threads",
    "search",
  ])!;
  expect(cachedThreads.map((item) => item.thread_id)).toEqual([]);
});

test("keeps a thread that already holds a checkpoint", async () => {
  mocks.getState.mockResolvedValue({ values: { messages: [] } });
  const { discardUnwrittenThread } = await import("@/core/threads/hooks");
  const { queryClient } = createQueryClient();

  await expect(discardUnwrittenThread(queryClient, "new-thread")).resolves.toBe(
    false,
  );

  expect(mocks.delete).not.toHaveBeenCalled();
  expect(mocks.deletedLocal).toEqual([]);
  expect(queryClient.getQueryData(["threads", "search"])).toHaveLength(1);
});

test("keeps the thread when its state cannot be read", async () => {
  mocks.getState.mockRejectedValue(httpError(500));
  const { discardUnwrittenThread } = await import("@/core/threads/hooks");
  const { queryClient } = createQueryClient();

  await expect(discardUnwrittenThread(queryClient, "new-thread")).resolves.toBe(
    false,
  );

  expect(mocks.delete).not.toHaveBeenCalled();
});

test("keeps the thread when the delete fails", async () => {
  mocks.delete.mockRejectedValue(httpError(403));
  const { discardUnwrittenThread } = await import("@/core/threads/hooks");
  const { queryClient } = createQueryClient();
  const warn = rs.spyOn(console, "warn").mockImplementation(() => undefined);

  await expect(discardUnwrittenThread(queryClient, "new-thread")).resolves.toBe(
    false,
  );

  expect(queryClient.getQueryData(["threads", "search"])).toHaveLength(1);
  expect(warn).toHaveBeenCalled();
});

import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import {
  QueryClient,
  QueryClientProvider,
  type InfiniteData,
} from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  fetch: rs.fn(),
  available: true,
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/features/hooks", () => ({
  useThreadActivityFeature: () => ({
    available: mocks.available,
    isLoading: false,
  }),
}));

import {
  applyThreadActivity,
  cachedThreadUnread,
  MARK_THREAD_READ_DEBOUNCE_MS,
  threadActivityState,
  useMarkThreadRead,
  useThreadActivity,
} from "@/core/threads/activity";
import { INFINITE_THREADS_QUERY_KEY_PREFIX } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

const clients: QueryClient[] = [];

function thread(id: string, unread: boolean | null | undefined): AgentThread {
  return {
    thread_id: id,
    unread,
    metadata: {},
    values: { title: id },
  } as unknown as AgentThread;
}

function newClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(queryClient);
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

function setup(
  threadId: string | null,
  {
    search = [],
    infinite = [],
  }: { search?: AgentThread[]; infinite?: AgentThread[] } = {},
) {
  const { queryClient, wrapper } = newClient();
  queryClient.setQueryData(["threads", "search", { limit: 50 }], search);
  queryClient.setQueryData<InfiniteData<AgentThread[]>>(
    [...INFINITE_THREADS_QUERY_KEY_PREFIX, {}],
    { pages: [infinite], pageParams: [0] },
  );
  const hook = renderHook(({ id }) => useMarkThreadRead(id), {
    wrapper,
    initialProps: { id: threadId },
  });
  return { queryClient, hook };
}

async function advance(ms = MARK_THREAD_READ_DEBOUNCE_MS) {
  await act(async () => {
    await rs.advanceTimersByTimeAsync(ms);
  });
}

function readPosts() {
  return mocks.fetch.mock.calls.filter(
    ([, init]) => (init as RequestInit | undefined)?.method === "POST",
  );
}

beforeEach(() => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  mocks.available = true;
  mocks.fetch
    .mockReset()
    .mockImplementation(async () =>
      Response.json({ unread: false, read_version: 7 }),
    );
});
afterEach(() => {
  cleanup();
  rs.useRealTimers();
  clients.splice(0).forEach((client) => client.clear());
});

describe("useMarkThreadRead", () => {
  test("debounces repeated calls into one POST after 1 s", async () => {
    const { hook } = setup("t-1", { search: [thread("t-1", true)] });
    act(() => {
      hook.result.current();
      hook.result.current();
    });
    await advance(MARK_THREAD_READ_DEBOUNCE_MS - 1);
    expect(readPosts()).toHaveLength(0);
    act(() => hook.result.current());
    await advance();
    expect(readPosts()).toHaveLength(1);
    expect(String(readPosts()[0]![0])).toBe("/api/threads/t-1/read");
  });

  test("patches the cached unread flag in search and infinite lists", async () => {
    let finish!: (response: Response) => void;
    mocks.fetch.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    );
    const { queryClient, hook } = setup("t-1", {
      search: [thread("t-1", true), thread("t-2", true)],
      infinite: [thread("t-1", true)],
    });
    act(() => hook.result.current());
    await advance();
    // Optimistic: patched before the POST answers.
    expect(readPosts()).toHaveLength(1);
    expect(cachedThreadUnread(queryClient, "t-1")).toBe(false);
    expect(cachedThreadUnread(queryClient, "t-2")).toBe(true);
    const infinite = queryClient.getQueryData<InfiniteData<AgentThread[]>>([
      ...INFINITE_THREADS_QUERY_KEY_PREFIX,
      {},
    ]);
    expect(infinite?.pages[0]?.[0]?.unread).toBe(false);
    await act(async () => {
      finish(Response.json({ unread: false, read_version: 3 }));
      await rs.advanceTimersByTimeAsync(0);
    });
  });

  test("posts nothing when the cached unread flag is false", async () => {
    const { hook } = setup("t-1", {
      search: [thread("t-1", false)],
      infinite: [thread("t-1", false)],
    });
    act(() => hook.result.current());
    await advance(MARK_THREAD_READ_DEBOUNCE_MS * 2);
    expect(readPosts()).toHaveLength(0);
  });

  test("posts when no loaded list knows the thread", async () => {
    const { hook } = setup("t-9", { search: [thread("t-1", false)] });
    act(() => hook.result.current());
    await advance();
    expect(readPosts()).toHaveLength(1);
  });

  test("does nothing when thread activity is unavailable", async () => {
    mocks.available = false;
    const { hook } = setup("t-1", { search: [thread("t-1", true)] });
    act(() => hook.result.current());
    await advance(MARK_THREAD_READ_DEBOUNCE_MS * 2);
    expect(mocks.fetch).not.toHaveBeenCalled();
  });

  test("leaving the thread before the debounce ends cancels the read", async () => {
    const { hook } = setup("t-1", { search: [thread("t-1", true)] });
    act(() => hook.result.current());
    hook.rerender({ id: "t-2" });
    await advance(MARK_THREAD_READ_DEBOUNCE_MS * 2);
    expect(readPosts()).toHaveLength(0);
  });

  test("stores the returned read_version so the next poll does not refetch the lists", async () => {
    const { queryClient, hook } = setup("t-1", {
      search: [thread("t-1", true)],
    });
    const state = threadActivityState(queryClient);
    state.cursor = "5:run-5";
    state.readVersion = 6;
    act(() => hook.result.current());
    await advance();
    expect(state.readVersion).toBe(7);
    const outcome = applyThreadActivity(queryClient, state, {
      cursor: "5:run-5",
      threads: [],
      truncated: false,
      read_version: 7,
    });
    expect(outcome.threads).toBe(false);
  });

  test("a returned version that also covers reads on other devices refetches the lists", async () => {
    // Version 6 seen here; another device read Y (7), then this tab reads X (8).
    mocks.fetch.mockImplementation(async () =>
      Response.json({ unread: false, read_version: 8 }),
    );
    const { queryClient, hook } = setup("t-1", {
      search: [thread("t-1", true)],
    });
    const state = threadActivityState(queryClient);
    state.cursor = "5:run-5";
    state.readVersion = 6;
    const invalidate = rs.spyOn(queryClient, "invalidateQueries");
    act(() => hook.result.current());
    await advance();
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
    });
    expect(state.readVersion).toBe(8);
  });

  test("a failed POST refetches the lists to show the server state again", async () => {
    mocks.fetch.mockImplementation(async () =>
      Response.json({ detail: "Thread not found" }, { status: 404 }),
    );
    const { queryClient, hook } = setup("t-1", {
      search: [thread("t-1", true)],
    });
    const invalidate = rs.spyOn(queryClient, "invalidateQueries");
    act(() => hook.result.current());
    await advance();
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["threads", "search"],
    });
  });
});

describe("useThreadActivity", () => {
  test("leaving the workspace forgets the cursor and read clock (another account may sign in)", () => {
    mocks.available = false;
    const { queryClient, wrapper } = newClient();
    const hook = renderHook(() => useThreadActivity(), { wrapper });
    const state = threadActivityState(queryClient);
    state.cursor = "40:run-40";
    state.readVersion = 9;
    hook.rerender();
    expect(state).toEqual({ cursor: "40:run-40", readVersion: 9 });
    hook.unmount();
    expect(threadActivityState(queryClient)).toEqual({
      cursor: null,
      readVersion: null,
    });
  });
});

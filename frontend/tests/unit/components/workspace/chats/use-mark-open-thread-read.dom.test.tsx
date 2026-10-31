import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({ fetch: rs.fn(), available: true }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/features/hooks", () => ({
  useThreadActivityFeature: () => ({
    available: mocks.available,
    isLoading: false,
  }),
}));

import { useMarkOpenThreadRead } from "@/components/workspace/chats/use-mark-open-thread-read";
import {
  cachedThreadUnread,
  MARK_THREAD_READ_DEBOUNCE_MS,
} from "@/core/threads/activity";
import type { AgentThread } from "@/core/threads/types";

const SEARCH_KEY = ["threads", "search", { limit: 50 }] as const;
const clients: QueryClient[] = [];

function thread(id: string, unread: boolean | null): AgentThread {
  return {
    thread_id: id,
    unread,
    metadata: {},
    values: { title: id },
  } as unknown as AgentThread;
}

function setup({
  unread,
  enabled = true,
}: {
  unread: boolean | null | "absent";
  enabled?: boolean;
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(queryClient);
  queryClient.setQueryData(
    SEARCH_KEY,
    unread === "absent" ? [] : [thread("t-1", unread)],
  );
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const hook = renderHook(
    ({ on }) => useMarkOpenThreadRead("t-1", { enabled: on }),
    { wrapper, initialProps: { on: enabled } },
  );
  return { queryClient, hook };
}

function readPosts() {
  return mocks.fetch.mock.calls.filter(
    ([url, init]) =>
      (init as RequestInit | undefined)?.method === "POST" &&
      String(url) === "/api/threads/t-1/read",
  );
}

async function settle() {
  await act(async () => {
    await rs.advanceTimersByTimeAsync(MARK_THREAD_READ_DEBOUNCE_MS);
  });
}

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  mocks.available = true;
  mocks.fetch
    .mockReset()
    .mockImplementation(async () =>
      Response.json({ unread: false, read_version: 3 }),
    );
});
afterEach(() => {
  cleanup();
  rs.useRealTimers();
  clients.splice(0).forEach((client) => client.clear());
  Reflect.deleteProperty(document, "visibilityState");
});

describe("useMarkOpenThreadRead", () => {
  test("marks an unread thread read once it has loaded", async () => {
    const { queryClient, hook } = setup({ unread: true, enabled: false });
    await settle();
    expect(readPosts()).toHaveLength(0);

    hook.rerender({ on: true });
    await settle();
    expect(readPosts()).toHaveLength(1);
    expect(cachedThreadUnread(queryClient, "t-1")).toBe(false);
  });

  test("posts for a thread no loaded list knows", async () => {
    setup({ unread: "absent" });
    await settle();
    expect(readPosts()).toHaveLength(1);
  });

  test("does nothing for a thread the lists already show as read", async () => {
    setup({ unread: false });
    await settle();
    expect(readPosts()).toHaveLength(0);
  });

  test("marks read again when the cached flag flips to unread while open", async () => {
    const { queryClient } = setup({ unread: false });
    await settle();
    expect(readPosts()).toHaveLength(0);

    // A poll refetched the lists: a scheduled run in this thread changed.
    act(() => {
      queryClient.setQueryData(SEARCH_KEY, [thread("t-1", true)]);
    });
    await settle();
    expect(readPosts()).toHaveLength(1);
    expect(cachedThreadUnread(queryClient, "t-1")).toBe(false);
  });

  test("marks read when the tab becomes visible, unless already read", async () => {
    setup({ unread: false });
    act(() => setVisibility("visible"));
    await settle();
    expect(readPosts()).toHaveLength(0);
    cleanup();

    // Not in any loaded list: the server may know better, so returning to
    // the tab posts again.
    setup({ unread: "absent" });
    await settle();
    expect(readPosts()).toHaveLength(1);
    act(() => setVisibility("hidden"));
    act(() => setVisibility("visible"));
    await settle();
    expect(readPosts()).toHaveLength(2);
  });

  test("the returned callback marks read (a run in this thread ended)", async () => {
    const { hook } = setup({ unread: "absent" });
    await settle();
    expect(readPosts()).toHaveLength(1);
    act(() => hook.result.current());
    await settle();
    expect(readPosts()).toHaveLength(2);
  });

  test("never posts while the thread is not loaded or the feature is off", async () => {
    setup({ unread: true, enabled: false });
    act(() => setVisibility("visible"));
    await settle();
    expect(readPosts()).toHaveLength(0);

    cleanup();
    mocks.available = false;
    setup({ unread: true });
    await settle();
    expect(readPosts()).toHaveLength(0);
  });
});

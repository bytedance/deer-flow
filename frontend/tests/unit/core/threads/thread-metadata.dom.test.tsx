import { afterEach, describe, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({ get: rs.fn() }));
rs.mock("@/core/api", () => ({
  getAPIClient: () => ({ threads: { get: mocks.get } }),
}));

import { useThreadMetadata } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

const thread: AgentThread = {
  thread_id: "chat",
  created_at: "2026-11-13T00:00:00Z",
  updated_at: "2026-11-13T00:00:00Z",
  status: "idle",
  interrupts: {},
  values: {
    title: "Saved conversation",
    messages: [],
    artifacts: [],
    todos: [],
  },
  metadata: { agent_name: "research" },
};
const key = ["thread", "metadata", "chat", false];
const clients: QueryClient[] = [];

function setup() {
  const client = new QueryClient({
    // The hook must opt out of retries even when the application enables them.
    defaultOptions: { queries: { retry: 2, retryDelay: 0 } },
  });
  clients.push(client);
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  rs.resetAllMocks();
});

describe("thread metadata recovery", () => {
  for (const status of [403, 404]) {
    test.each([false, true])(
      `treats HTTP ${status} as inaccessible metadata (nested: %s)`,
      async (nested) => {
        const error = Object.assign(
          new Error("Thread is unavailable"),
          nested ? { response: { status } } : { status },
        );
        mocks.get.mockRejectedValue(error);
        const { client, wrapper } = setup();
        const { result } = renderHook(() => useThreadMetadata("chat"), {
          wrapper,
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));
        // null lets the chat page recover a stale/inaccessible thread URL.
        expect(result.current.data).toBeNull();
        expect(client.getQueryData(key)).toBeNull();
        expect(mocks.get).toHaveBeenCalledExactlyOnceWith("chat");
      },
    );
  }

  test("keeps a server failure distinct from missing metadata and recovers on explicit retry", async () => {
    const error = Object.assign(new Error("Gateway unavailable"), {
      status: 503,
    });
    mocks.get.mockRejectedValue(error);
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useThreadMetadata("chat"), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBe(error);
    expect(result.current.data).toBeUndefined();
    expect(client.getQueryData(key)).toBeUndefined();
    expect(mocks.get).toHaveBeenCalledExactlyOnceWith("chat");

    mocks.get.mockResolvedValue(thread);
    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(thread);
    expect(result.current.error).toBeNull();
    expect(client.getQueryData(key)).toEqual(thread);
    expect(mocks.get).toHaveBeenCalledTimes(2);
  });

  test("retains the last metadata snapshot when a refresh fails", async () => {
    const error = Object.assign(new Error("Refresh failed"), {
      response: { status: 500 },
    });
    mocks.get.mockRejectedValue(error);
    const { client, wrapper } = setup();
    client.setQueryData(key, thread);
    const { result } = renderHook(() => useThreadMetadata("chat"), { wrapper });

    await waitFor(() => expect(result.current.isRefetchError).toBe(true));
    // A transient failure must not turn a known conversation into null.
    expect(result.current.data).toEqual(thread);
    expect(result.current.error).toBe(error);
    expect(client.getQueryData(key)).toEqual(thread);
    expect(mocks.get).toHaveBeenCalledExactlyOnceWith("chat");
  });
});

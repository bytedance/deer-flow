import type { Run } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import { useThreadStream } from "@/core/threads/hooks";

// Drives the real SDK useStream (not a mock) so the test pins the SDK
// behavior the hook relies on: one same-tab reconnect from the lg:stream
// pointer, a pointer that survives a failed join, and an onFinish callback
// that runs inside the stream's try.

const clientMockState = rs.hoisted(() => ({
  getHistory: rs.fn(async () => [] as unknown[]),
  joinStream: rs.fn(),
  listRuns: rs.fn(async () => [] as Run[]),
}));

const toastMockState = rs.hoisted(() => ({ error: rs.fn() }));

rs.mock("sonner", () => ({
  toast: Object.assign(rs.fn(), { error: toastMockState.error }),
}));

rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    runs: {
      cancel: async () => undefined,
      joinStream: clientMockState.joinStream,
      list: clientMockState.listRuns,
    },
    threads: {
      getHistory: clientMockState.getHistory,
      getState: async () => ({ values: {} }),
    },
  }),
}));

const ACTIVE_RUN = {
  run_id: "run-active",
  status: "running",
} as Run;

function createWrapper(queryClient: QueryClient) {
  return function NativeReconnectTestWrapper({
    children,
  }: {
    children: ReactNode;
  }) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(
        I18nContext.Provider,
        {
          value: {
            locale: "en-US",
            setLocale: () => undefined,
            t: enUS,
          },
        },
        children,
      ),
    );
  };
}

async function flushFrames() {
  for (let index = 0; index < 10; index += 1) {
    await act(async () => {
      await rs.advanceTimersByTimeAsync(0);
    });
  }
}

function renderThread(
  onFinish?: Parameters<typeof useThreadStream>[0]["onFinish"],
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
        onFinish,
      }),
    { wrapper: createWrapper(queryClient) },
  );
  return { queryClient, ...rendered };
}

beforeEach(() => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  window.sessionStorage.clear();
  clientMockState.listRuns.mockReset();
  clientMockState.listRuns.mockResolvedValue([ACTIVE_RUN]);
  clientMockState.joinStream.mockReset();
  clientMockState.getHistory.mockReset();
  clientMockState.getHistory.mockResolvedValue([]);
  toastMockState.error.mockReset();
  rs.stubGlobal(
    "fetch",
    rs.fn(
      async () =>
        new Response(
          JSON.stringify({ data: [], has_more: false, next_before_seq: null }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    ),
  );
  rs.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  rs.useRealTimers();
  rs.unstubAllGlobals();
  rs.restoreAllMocks();
});

test("rejoins when the SDK's reconnect fails before the runs read", async () => {
  let resolveRuns!: (runs: Run[]) => void;
  clientMockState.listRuns.mockImplementation(
    () =>
      new Promise<Run[]>((resolve) => {
        resolveRuns = resolve;
      }),
  );
  clientMockState.joinStream.mockImplementationOnce(async function* () {
    throw new Error("network down");
  });
  clientMockState.joinStream.mockImplementation(async function* () {
    yield { event: "values", data: { messages: [] } };
  });
  window.sessionStorage.setItem("lg:stream:thread-1", "run-active");

  const { unmount } = renderThread();
  await flushFrames();
  // The SDK made its single reconnect; it failed and nothing else joined.
  expect(clientMockState.joinStream).toHaveBeenCalledTimes(1);
  expect(clientMockState.joinStream.mock.calls[0]?.[1]).toBe("run-active");

  act(() => resolveRuns([ACTIVE_RUN]));
  await flushFrames();

  expect(clientMockState.joinStream).toHaveBeenCalledTimes(2);
  expect(clientMockState.joinStream.mock.calls[1]?.[1]).toBe("run-active");
  unmount();
});

test("rejoins when the SDK's reconnect drops after the runs read", async () => {
  let dropStream!: () => void;
  clientMockState.joinStream.mockImplementationOnce(async function* () {
    yield { event: "values", data: { messages: [] } };
    await new Promise<void>((resolve) => {
      dropStream = resolve;
    });
    throw new Error("connection reset");
  });
  clientMockState.joinStream.mockImplementation(async function* () {
    yield { event: "values", data: { messages: [] } };
  });
  window.sessionStorage.setItem("lg:stream:thread-1", "run-active");

  const { result, unmount } = renderThread();
  await flushFrames();
  expect(clientMockState.listRuns).toHaveBeenCalled();
  expect(result.current.thread.isLoading).toBe(true);
  expect(clientMockState.joinStream).toHaveBeenCalledTimes(1);

  act(() => dropStream());
  await flushFrames();

  expect(clientMockState.joinStream).toHaveBeenCalledTimes(2);
  expect(clientMockState.joinStream.mock.calls[1]?.[1]).toBe("run-active");
  unmount();
});

// The chat page's listener shows a browser notification, and Chrome for
// Android throws from `new Notification()`. The SDK calls onFinish inside the
// stream's try, so an escaping throw would turn the finished run into a
// stream error and skip the hook's finish bookkeeping.
test("keeps a run finished when the page's onFinish listener throws", async () => {
  // The SDK calls onFinish only with the thread's head after the stream.
  clientMockState.getHistory.mockResolvedValue([
    {
      values: { messages: [], title: "Done" },
      next: [],
      tasks: [],
      metadata: {},
      created_at: "2026-11-27T00:00:00Z",
      checkpoint: {
        thread_id: "thread-1",
        checkpoint_ns: "",
        checkpoint_id: "checkpoint-1",
      },
      parent_checkpoint: null,
    },
  ]);
  clientMockState.joinStream.mockImplementation(async function* () {
    yield { event: "values", data: { messages: [] } };
  });
  window.sessionStorage.setItem("lg:stream:thread-1", "run-active");
  const listenerError = new TypeError("Illegal constructor");
  const onFinish = rs.fn(() => {
    throw listenerError;
  });

  const { queryClient, result, unmount } = renderThread(onFinish);
  const invalidateQueries = rs.spyOn(queryClient, "invalidateQueries");
  await flushFrames();

  expect(onFinish).toHaveBeenCalledTimes(1);
  expect(result.current.thread.isLoading).toBe(false);
  expect(result.current.thread.error).toBeUndefined();
  expect(toastMockState.error).not.toHaveBeenCalled();
  // The finish bookkeeping after the listener still refreshes the thread list.
  expect(invalidateQueries).toHaveBeenCalledWith({
    queryKey: ["threads", "search"],
  });
  expect(console.error).toHaveBeenCalledWith(
    "Thread onFinish listener failed:",
    listenerError,
  );
  unmount();
});

import type { Run } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import { useThreadStream } from "@/core/threads/hooks";

type StreamOptions = {
  onError?: (error: unknown) => void;
  onFinish?: (state: {
    values: { artifacts: never[]; messages: never[]; title: string };
  }) => void;
};

const apiMockState = rs.hoisted(() => ({
  listRuns: rs.fn(async () => [] as Run[]),
}));

const streamMockState = rs.hoisted(() => ({
  isLoading: false,
  joinStream: rs.fn(async (_runId: string) => undefined),
  options: undefined as StreamOptions | undefined,
}));

rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    runs: { list: apiMockState.listRuns },
  }),
}));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: StreamOptions) => {
    streamMockState.options = options;
    return {
      isLoading: streamMockState.isLoading,
      joinStream: streamMockState.joinStream,
      messages: [],
      stop: async () => undefined,
      submit: async () => undefined,
      values: {
        artifacts: [],
        messages: [],
        title: "",
        todos: [],
      },
    };
  },
}));

const ACTIVE_RUN = {
  run_id: "run-active",
  status: "running",
} as Run;

function createWrapper(queryClient: QueryClient) {
  return function ActiveRunRejoinTestWrapper({
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
  for (let index = 0; index < 6; index += 1) {
    await act(async () => {
      await rs.advanceTimersByTimeAsync(0);
    });
  }
}

function renderThread(threadId = "thread-1") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const rendered = renderHook(
    ({ activeThreadId }: { activeThreadId: string }) =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: activeThreadId,
      }),
    {
      initialProps: { activeThreadId: threadId },
      wrapper: createWrapper(queryClient),
    },
  );
  return { queryClient, ...rendered };
}

beforeEach(() => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  window.sessionStorage.clear();
  apiMockState.listRuns.mockReset();
  apiMockState.listRuns.mockResolvedValue([ACTIVE_RUN]);
  streamMockState.isLoading = false;
  streamMockState.joinStream.mockReset();
  streamMockState.joinStream.mockResolvedValue(undefined);
  streamMockState.options = undefined;
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
});

afterEach(() => {
  rs.useRealTimers();
  rs.unstubAllGlobals();
});

test("joins the newest active run when a reopened tab has no reconnect pointer", async () => {
  const { unmount } = renderThread();
  await flushFrames();

  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);
  expect(streamMockState.joinStream).toHaveBeenCalledWith("run-active");
  expect(window.sessionStorage.getItem("lg:stream:thread-1")).toBe(
    "run-active",
  );

  unmount();
});

test("leaves a matching reconnect pointer to the SDK without joining twice", async () => {
  window.sessionStorage.setItem("lg:stream:thread-1", "run-active");
  const { unmount } = renderThread();
  await flushFrames();

  expect(streamMockState.joinStream).not.toHaveBeenCalled();
  expect(window.sessionStorage.getItem("lg:stream:thread-1")).toBe(
    "run-active",
  );

  unmount();
});

test("retries a failed recovered stream twice with bounded backoff", async () => {
  const { unmount } = renderThread();
  await flushFrames();
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);

  act(() => streamMockState.options?.onError?.(new Error("disconnected")));
  await act(async () => {
    await rs.advanceTimersByTimeAsync(999);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);
  await act(async () => {
    await rs.advanceTimersByTimeAsync(1);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(2);

  act(() => streamMockState.options?.onError?.(new Error("disconnected")));
  await act(async () => {
    await rs.advanceTimersByTimeAsync(1_999);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(2);
  await act(async () => {
    await rs.advanceTimersByTimeAsync(1);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(3);

  act(() => streamMockState.options?.onError?.(new Error("disconnected")));
  await act(async () => {
    await rs.advanceTimersByTimeAsync(10_000);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(3);

  unmount();
});

test("does not retry after the recovered run finishes", async () => {
  const { unmount } = renderThread();
  await flushFrames();
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);

  act(() =>
    streamMockState.options?.onFinish?.({
      values: { artifacts: [], messages: [], title: "Done" },
    }),
  );
  await act(async () => {
    await rs.advanceTimersByTimeAsync(10_000);
  });

  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);
  unmount();
});

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
  onCreated?: (meta: { thread_id: string; run_id: string }) => void;
  onError?: (
    error: unknown,
    run?: { thread_id: string; run_id: string },
  ) => void;
  onFinish?: (
    state: {
      values: { artifacts: never[]; messages: never[]; title: string };
    },
    run?: { thread_id: string; run_id: string },
  ) => void;
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
const ACTIVE_RUN_META = {
  thread_id: "thread-1",
  run_id: "run-active",
};

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

function failActiveRecoveredStream() {
  streamMockState.options?.onError?.(
    new Error("disconnected"),
    ACTIVE_RUN_META,
  );
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
  expect(window.sessionStorage.getItem("lg:stream:thread-1")).toBeNull();
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

test("takes over a failed same-tab reconnect with bounded recovery", async () => {
  window.sessionStorage.setItem("lg:stream:thread-1", "run-active");
  const { unmount } = renderThread();
  await flushFrames();
  expect(streamMockState.joinStream).not.toHaveBeenCalled();

  // The SDK keeps its pointer when its single reconnect fails.
  act(() => failActiveRecoveredStream());
  await flushFrames();
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);
  expect(streamMockState.joinStream).toHaveBeenCalledWith("run-active");
  expect(window.sessionStorage.getItem("lg:stream:thread-1")).toBe(
    "run-active",
  );

  act(() => failActiveRecoveredStream());
  await act(async () => {
    await rs.advanceTimersByTimeAsync(1_000);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(2);

  act(() => failActiveRecoveredStream());
  await act(async () => {
    await rs.advanceTimersByTimeAsync(2_000);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(3);

  act(() => failActiveRecoveredStream());
  await act(async () => {
    await rs.advanceTimersByTimeAsync(10_000);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(3);

  unmount();
});

test("recovers a same-tab reconnect that failed before the runs read", async () => {
  let resolveRuns!: (runs: Run[]) => void;
  apiMockState.listRuns.mockImplementation(
    () =>
      new Promise<Run[]>((resolve) => {
        resolveRuns = resolve;
      }),
  );
  window.sessionStorage.setItem("lg:stream:thread-1", "run-active");
  const { unmount } = renderThread();
  await flushFrames();

  act(() => failActiveRecoveredStream());
  expect(window.sessionStorage.getItem("lg:stream:thread-1")).toBeNull();
  expect(streamMockState.joinStream).not.toHaveBeenCalled();

  act(() => resolveRuns([ACTIVE_RUN]));
  await flushFrames();

  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);
  expect(streamMockState.joinStream).toHaveBeenCalledWith("run-active");
  unmount();
});

test("leaves a failed submitted run to the submit flow", async () => {
  apiMockState.listRuns.mockResolvedValue([]);
  const { queryClient, unmount } = renderThread();
  await flushFrames();

  act(() => {
    window.sessionStorage.setItem("lg:stream:thread-1", "run-active");
    streamMockState.options?.onCreated?.(ACTIVE_RUN_META);
  });
  act(() => {
    queryClient.setQueryData(["thread", "thread-1"], [ACTIVE_RUN]);
  });
  await flushFrames();
  act(() => failActiveRecoveredStream());
  await act(async () => {
    await rs.advanceTimersByTimeAsync(10_000);
  });

  expect(streamMockState.joinStream).not.toHaveBeenCalled();
  expect(window.sessionStorage.getItem("lg:stream:thread-1")).toBe(
    "run-active",
  );
  unmount();
});

test.each([
  ["has no run metadata", undefined],
  [
    "belongs to another thread",
    { thread_id: "thread-2", run_id: "run-active" },
  ],
  ["belongs to another run", { thread_id: "thread-1", run_id: "run-other" }],
])(
  "keeps the recovered-run pointer when an error %s",
  async (_caseName, run) => {
    const { unmount } = renderThread();
    await flushFrames();
    expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);

    act(() =>
      streamMockState.options?.onError?.(new Error("history failed"), run),
    );
    expect(window.sessionStorage.getItem("lg:stream:thread-1")).toBe(
      "run-active",
    );

    await act(async () => {
      await rs.advanceTimersByTimeAsync(10_000);
    });
    expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);

    unmount();
  },
);

test("retries a failed recovered stream twice with bounded backoff", async () => {
  const { unmount } = renderThread();
  await flushFrames();
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);

  act(() => failActiveRecoveredStream());
  await act(async () => {
    await rs.advanceTimersByTimeAsync(999);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);
  await act(async () => {
    await rs.advanceTimersByTimeAsync(1);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(2);

  act(() => failActiveRecoveredStream());
  await act(async () => {
    await rs.advanceTimersByTimeAsync(1_999);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(2);
  await act(async () => {
    await rs.advanceTimersByTimeAsync(1);
  });
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(3);

  act(() => failActiveRecoveredStream());
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

test("cancels a pending retry when the recovered stream unmounts", async () => {
  const { unmount } = renderThread();
  await flushFrames();
  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);

  act(() => failActiveRecoveredStream());
  unmount();
  await act(async () => {
    await rs.advanceTimersByTimeAsync(10_000);
  });

  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);
  expect(window.sessionStorage.getItem("lg:stream:thread-1")).toBeNull();
});

test("clears the old retry when the active run changes", async () => {
  const { queryClient, unmount } = renderThread();
  await flushFrames();
  expect(streamMockState.joinStream).toHaveBeenCalledWith("run-active");

  act(() => failActiveRecoveredStream());
  act(() => {
    queryClient.setQueryData(
      ["thread", "thread-1"],
      [{ ...ACTIVE_RUN, run_id: "run-next", status: "pending" }],
    );
  });
  await flushFrames();
  await act(async () => {
    await rs.advanceTimersByTimeAsync(10_000);
  });

  expect(streamMockState.joinStream).toHaveBeenCalledTimes(2);
  expect(streamMockState.joinStream).toHaveBeenLastCalledWith("run-next");
  expect(window.sessionStorage.getItem("lg:stream:thread-1")).toBe("run-next");
  unmount();
});

test.each(["submitted", "same-tab reconnect"])(
  "does not rejoin a finished %s run while the runs cache is stale",
  async (kind) => {
    if (kind === "same-tab reconnect") {
      window.sessionStorage.setItem("lg:stream:thread-1", "run-active");
    }
    streamMockState.isLoading = true;
    const { rerender, unmount } = renderThread();
    await flushFrames();
    expect(streamMockState.joinStream).not.toHaveBeenCalled();

    // The SDK removes its pointer before onFinish. Keep the runs refetch
    // pending so the effect still sees the previous "running" snapshot.
    apiMockState.listRuns.mockImplementation(
      () =>
        new Promise(() => {
          // Keep the cached running snapshot until the hook unmounts.
        }),
    );
    act(() => {
      window.sessionStorage.removeItem("lg:stream:thread-1");
      streamMockState.options?.onFinish?.(
        { values: { artifacts: [], messages: [], title: "Done" } },
        { thread_id: "thread-1", run_id: "run-active" },
      );
      streamMockState.isLoading = false;
    });
    rerender({ activeThreadId: "thread-1" });
    await flushFrames();

    expect(streamMockState.joinStream).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem("lg:stream:thread-1")).toBeNull();
    unmount();
  },
);

test("does not rejoin a finished run discovered by a delayed initial runs read", async () => {
  let resolveRuns!: (runs: Run[]) => void;
  apiMockState.listRuns.mockImplementation(
    () =>
      new Promise<Run[]>((resolve) => {
        resolveRuns = resolve;
      }),
  );
  streamMockState.isLoading = true;
  const { rerender, unmount } = renderThread();
  await flushFrames();

  act(() => {
    streamMockState.options?.onFinish?.(
      { values: { artifacts: [], messages: [], title: "Done" } },
      { thread_id: "thread-1", run_id: "run-active" },
    );
    streamMockState.isLoading = false;
    resolveRuns([ACTIVE_RUN]);
  });
  rerender({ activeThreadId: "thread-1" });
  await flushFrames();

  expect(streamMockState.joinStream).not.toHaveBeenCalled();
  unmount();
});

test("still recovers a different active run after an earlier run finishes", async () => {
  streamMockState.isLoading = true;
  const { queryClient, rerender, unmount } = renderThread();
  await flushFrames();

  apiMockState.listRuns.mockImplementation(
    () =>
      new Promise(() => {
        // Keep the cached running snapshot until the hook unmounts.
      }),
  );
  act(() => {
    streamMockState.options?.onFinish?.(
      { values: { artifacts: [], messages: [], title: "Done" } },
      { thread_id: "thread-1", run_id: "run-active" },
    );
    streamMockState.isLoading = false;
  });
  rerender({ activeThreadId: "thread-1" });
  await flushFrames();
  expect(streamMockState.joinStream).not.toHaveBeenCalled();

  act(() => {
    queryClient.setQueryData(
      ["thread", "thread-1"],
      [{ ...ACTIVE_RUN, run_id: "run-next", status: "pending" }],
    );
  });
  await flushFrames();

  expect(streamMockState.joinStream).toHaveBeenCalledTimes(1);
  expect(streamMockState.joinStream).toHaveBeenCalledWith("run-next");
  unmount();
});

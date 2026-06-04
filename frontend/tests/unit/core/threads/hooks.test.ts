/* @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const apiClient = {
    runs: {
      list: vi.fn(),
    },
    threads: {
      update: vi.fn(),
      updateState: vi.fn(),
    },
  };

  return {
    apiClient,
    useStream: vi.fn(),
  };
});

vi.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: mocks.useStream,
}));

vi.mock("@/core/api", () => ({
  fetchGateway: vi.fn(),
  getAPIClient: vi.fn(() => mocks.apiClient),
}));

vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

vi.mock("@/core/genui/sse-recovery", () => ({
  GenUISSEManager: class {
    recoverBlocks = vi.fn().mockResolvedValue(undefined);
    scheduleReconnect = vi.fn();
    disconnect = vi.fn();

    get connected() {
      return false;
    }
  },
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      uploads: {
        uploadingFiles: "Uploading files",
      },
      errors: {
        quota_daily_exceeded: (used: number, limit: number) =>
          `Daily quota exceeded: ${used}/${limit}`,
        quota_monthly_exceeded: (used: number, limit: number) =>
          `Monthly quota exceeded: ${used}/${limit}`,
      },
    },
  }),
}));

vi.mock("@/core/tasks/context", () => ({
  useUpdateSubtask: () => vi.fn(),
}));

vi.mock("@/core/tenant", () => ({
  getCurrentTenantId: () => "tenant-test",
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
  },
}));

import { useThreadHistory, useThreadStream } from "@/core/threads/hooks";
import type { LocalSettings } from "@/core/settings";

type Snapshot = {
  messageIds: string[];
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;

  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });

  return { promise, resolve, reject };
}

function flushPromises(times = 3): Promise<void> {
  return React.act(async () => {
    for (let index = 0; index < times; index += 1) {
      await Promise.resolve();
    }
  });
}

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: Number.POSITIVE_INFINITY,
      },
    },
  });
}

function StreamProbe({
  threadId,
  snapshots,
}: {
  threadId?: string;
  snapshots: Snapshot[];
}) {
  const { thread } = useThreadStream({
    threadId,
    context: { mode: undefined } as LocalSettings["context"],
  });

  snapshots.push({
    messageIds: thread.messages
      .map((message) => message.id)
      .filter((value): value is string => typeof value === "string"),
  });

  return React.createElement("div", null, snapshots.at(-1)?.messageIds.join(","));
}

function HistoryProbe({
  threadId,
  snapshots,
}: {
  threadId: string;
  snapshots: Snapshot[];
}) {
  const { messages } = useThreadHistory(threadId);

  snapshots.push({
    messageIds: messages
      .map((message) => message.id)
      .filter((value): value is string => typeof value === "string"),
  });

  return React.createElement("div", null, snapshots.at(-1)?.messageIds.join(","));
}

describe("thread hooks", () => {
  let container: HTMLDivElement;
  let root: Root;
  let queryClient: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.clearAllMocks();
    queryClient = createQueryClient();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    queryClient.clear();
    container.remove();
    vi.unstubAllGlobals();
  });

  it("does not expose the previous stream messages during a switch to a new thread", async () => {
    mocks.apiClient.runs.list.mockResolvedValue([]);
    mocks.useStream.mockImplementation(({ threadId }: { threadId?: string }) => ({
      messages:
        threadId === "thread-old"
          ? [
              {
                type: "human",
                id: "old-stream-message",
                content: [{ type: "text", text: "old thread content" }],
              },
            ]
          : [],
      isLoading: false,
      isThreadLoading: false,
      error: null,
      values: {},
      stop: vi.fn(),
      submit: vi.fn(),
    }));

    const snapshots: Snapshot[] = [];

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(StreamProbe, {
            threadId: "thread-old",
            snapshots,
          }),
        ),
      );
    });

    expect(snapshots.some((snapshot) => snapshot.messageIds.includes("old-stream-message"))).toBe(true);

    const previousCount = snapshots.length;

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(StreamProbe, {
            threadId: undefined,
            snapshots,
          }),
        ),
      );
    });

    const afterSwitch = snapshots.slice(previousCount);

    expect(afterSwitch.length).toBeGreaterThan(0);
    expect(
      afterSwitch.some((snapshot) =>
        snapshot.messageIds.includes("old-stream-message"),
      ),
    ).toBe(false);
  });

  it("ignores late history responses from the previous thread after a thread switch", async () => {
    const oldHistoryResponse = deferred<{
      data: Array<{
        metadata: Record<string, unknown>;
        content: {
          type: "human";
          id: string;
          content: Array<{ type: "text"; text: string }>;
        };
      }>;
      hasMore: boolean;
    }>();

    mocks.apiClient.runs.list.mockResolvedValue([]);

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.includes("/api/threads/thread-old/runs/run-old/messages")) {
          return Promise.resolve({
            json: () => oldHistoryResponse.promise,
          });
        }
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );

    const snapshots: Snapshot[] = [];

    queryClient.setQueryData(["thread", "thread-old"], [{ run_id: "run-old" }]);

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(HistoryProbe, {
            threadId: "thread-old",
            snapshots,
          }),
        ),
      );
    });

    await flushPromises();

    const fetchMock = vi.mocked(global.fetch);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const previousCount = snapshots.length;

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(HistoryProbe, {
            threadId: "thread-new",
            snapshots,
          }),
        ),
      );
    });

    await flushPromises();

    oldHistoryResponse.resolve({
      data: [
        {
          metadata: {},
          content: {
            type: "human",
            id: "old-history-message",
            content: [{ type: "text", text: "stale history" }],
          },
        },
      ],
      hasMore: false,
    });

    await flushPromises();

    const afterSwitch = snapshots.slice(previousCount);

    expect(
      afterSwitch.some((snapshot) =>
        snapshot.messageIds.includes("old-history-message"),
      ),
    ).toBe(false);
  });
});

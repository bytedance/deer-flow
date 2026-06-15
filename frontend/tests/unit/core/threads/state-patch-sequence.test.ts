/* @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Message } from "@langchain/langgraph-sdk";
import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const apiClient = {
    runs: { list: vi.fn() },
    threads: { update: vi.fn(), updateState: vi.fn() },
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

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats/test-thread",
}));

vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

vi.mock("@/core/genui/sse-recovery", () => ({
  GenUISSEManager: class {
    recoverBlocks = vi.fn().mockResolvedValue(undefined);
    scheduleReconnect = vi.fn();
    disconnect = vi.fn();
    setVisibility = vi.fn();

    get connected() {
      return false;
    }
  },
}));

vi.mock("@/core/genui/use-ui-block-extractor", () => ({
  useUIBlockExtractor: () => {},
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      uploads: { uploadingFiles: "Uploading files" },
      errors: {
        quota_daily_exceeded: () => "Daily quota exceeded",
        quota_monthly_exceeded: () => "Monthly quota exceeded",
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

import { useThreadStream } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";
import type { LocalSettings } from "@/core/settings";

type StreamCallbacks = {
  onCustomEvent?: (event: unknown) => void;
  onUpdateEvent?: (data: Record<string, unknown>) => void;
};

const capturedCallbacks: StreamCallbacks = {};

function Probe({ snapshots }: { snapshots: unknown[] }) {
  const { thread } = useThreadStream({
    threadId: "test-thread",
    context: { mode: undefined } as LocalSettings["context"],
  });

  snapshots.push({ error: thread.error, isLoading: thread.isLoading });
  return React.createElement("div", null, String(thread.isLoading));
}

describe("state_patch idempotency and sequence gap detection", () => {
  let container: HTMLDivElement;
  let root: Root;
  let queryClient: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.clearAllMocks();
    delete capturedCallbacks.onCustomEvent;
    delete capturedCallbacks.onUpdateEvent;
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Number.POSITIVE_INFINITY } },
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    mocks.apiClient.runs.list.mockResolvedValue([]);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    queryClient.clear();
    container.remove();
  });

  function setupStream() {
    mocks.useStream.mockImplementation((options: Record<string, unknown>) => {
      capturedCallbacks.onCustomEvent = options.onCustomEvent as (event: unknown) => void;
      capturedCallbacks.onUpdateEvent = options.onUpdateEvent as (data: Record<string, unknown>) => void;
      return {
        messages: [],
        isLoading: true,
        isThreadLoading: false,
        error: null,
        values: {},
        stop: vi.fn(),
        submit: vi.fn(),
      };
    });
  }

  function seedThreadCache() {
    queryClient.setQueryData(["thread", "test-thread"], {
      thread_id: "test-thread",
      status: "idle",
      values: { title: "Old Title" },
    } as Partial<AgentThread> as AgentThread);
  }

  it("state_patch and update event with same title produce single write (3.8)", async () => {
    setupStream();
    seedThreadCache();
    const snapshots: unknown[] = [];

    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(Probe, { snapshots }),
        ),
      );
    });
    await Promise.resolve();

    capturedCallbacks.onCustomEvent?.({
      type: "state_patch",
      patch: { title: "New Title" },
    });
    await React.act(async () => {
      await Promise.resolve();
    });

    capturedCallbacks.onUpdateEvent?.({
      someKey: { title: "New Title" },
    });
    await React.act(async () => {
      await Promise.resolve();
    });

    const cached = queryClient.getQueryData(["thread", "test-thread"]) as AgentThread | undefined;
    expect(cached?.values?.title).toBe("New Title");

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("state_patch with different fields merges without overwriting (3.8)", async () => {
    setupStream();
    seedThreadCache();
    const snapshots: unknown[] = [];

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(Probe, { snapshots }),
        ),
      );
    });
    await Promise.resolve();

    capturedCallbacks.onCustomEvent?.({
      type: "state_patch",
      patch: { title: "Patched Title" },
    });
    await React.act(async () => {
      await Promise.resolve();
    });

    capturedCallbacks.onCustomEvent?.({
      type: "state_patch",
      patch: { todos: [{ id: "1", content: "task" }] },
    });
    await React.act(async () => {
      await Promise.resolve();
    });

    const cached = queryClient.getQueryData(["thread", "test-thread"]) as AgentThread | undefined;
    expect(cached?.values?.title).toBe("Patched Title");
    expect(cached?.values?.todos).toEqual([{ id: "1", content: "task" }]);
  });

  it("detects sequence gap and triggers state refetch (4.10)", async () => {
    setupStream();
    seedThreadCache();
    const snapshots: unknown[] = [];

    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(Probe, { snapshots }),
        ),
      );
    });
    await Promise.resolve();

    capturedCallbacks.onCustomEvent?.({ _seq: 1, type: "tool_end", name: "x", data: {} });
    await React.act(async () => {
      await Promise.resolve();
    });

    capturedCallbacks.onCustomEvent?.({ _seq: 2, type: "tool_end", name: "y", data: {} });
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(invalidateSpy).not.toHaveBeenCalled();

    capturedCallbacks.onCustomEvent?.({ _seq: 5, type: "tool_end", name: "z", data: {} });
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ["thread", "test-thread"] }),
    );
  });

  it("does not trigger refetch on first sequence number (4.10)", async () => {
    setupStream();
    seedThreadCache();
    const snapshots: unknown[] = [];

    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(Probe, { snapshots }),
        ),
      );
    });
    await Promise.resolve();

    capturedCallbacks.onCustomEvent?.({ _seq: 100, type: "tool_end", name: "x", data: {} });
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("detects sequence gap in update events (4.10)", async () => {
    setupStream();
    seedThreadCache();
    const snapshots: unknown[] = [];

    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(Probe, { snapshots }),
        ),
      );
    });
    await Promise.resolve();

    const update1 = { agent: { title: "X" } } as Record<string, unknown>;
    Object.defineProperty(update1, "_seq", { value: 1, enumerable: false });
    capturedCallbacks.onUpdateEvent?.(update1);
    await React.act(async () => {
      await Promise.resolve();
    });

    const update4 = { agent: { title: "X" } } as Record<string, unknown>;
    Object.defineProperty(update4, "_seq", { value: 4, enumerable: false });
    capturedCallbacks.onUpdateEvent?.(update4);
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ["thread", "test-thread"] }),
    );
  });
});

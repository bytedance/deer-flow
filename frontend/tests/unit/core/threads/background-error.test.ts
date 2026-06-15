/* @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

const toastErrorMock = vi.fn();

vi.mock("sonner", () => ({
  toast: {
    error: (...args: unknown[]) => {
      toastErrorMock(...args);
    },
  },
}));

import { useThreadStream } from "@/core/threads/hooks";
import type { LocalSettings } from "@/core/settings";

type StreamCallbacks = {
  onError?: (error: unknown) => void;
  onFinish?: (state: unknown) => void;
};

const capturedCallbacks: StreamCallbacks = {};

type Snapshot = {
  backgroundPaused: boolean;
  backgroundError: unknown;
};

function BackgroundErrorProbe({ snapshots }: { snapshots: Snapshot[] }) {
  const { thread } = useThreadStream({
    threadId: "test-thread",
    context: { mode: undefined } as LocalSettings["context"],
  });

  snapshots.push({
    backgroundPaused: (thread as unknown as { backgroundPaused: boolean }).backgroundPaused,
    backgroundError: (thread as unknown as { backgroundError: unknown }).backgroundError,
  });

  return React.createElement("div", null, String((thread as unknown as { backgroundPaused: boolean }).backgroundPaused));
}

type OnFinishSnapshot = {
  backgroundPaused: boolean;
  backgroundError: unknown;
};

function OnFinishProbe({
  snapshots,
  onFinishCalledRef,
}: {
  snapshots: OnFinishSnapshot[];
  onFinishCalledRef: { current: boolean };
}) {
  const { thread } = useThreadStream({
    threadId: "test-thread",
    context: { mode: undefined } as LocalSettings["context"],
    onFinish: () => {
      onFinishCalledRef.current = true;
    },
  });

  snapshots.push({
    backgroundPaused: (thread as unknown as { backgroundPaused: boolean }).backgroundPaused,
    backgroundError: (thread as unknown as { backgroundError: unknown }).backgroundError,
  });

  return React.createElement("div", null, String((thread as unknown as { backgroundPaused: boolean }).backgroundPaused));
}

describe("background error handling", () => {
  let container: HTMLDivElement;
  let root: Root;
  let queryClient: QueryClient;
  let originalVisibilityState: DocumentVisibilityState;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.clearAllMocks();
    toastErrorMock.mockClear();
    delete capturedCallbacks.onError;
    delete capturedCallbacks.onFinish;
    originalVisibilityState = document.visibilityState;
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      writable: true,
      configurable: true,
    });
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
    Object.defineProperty(document, "visibilityState", {
      value: originalVisibilityState,
      writable: true,
      configurable: true,
    });
  });

  function setVisibility(state: DocumentVisibilityState) {
    Object.defineProperty(document, "visibilityState", {
      value: state,
      writable: true,
      configurable: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  }

  function setupLoadingStream() {
    mocks.useStream.mockImplementation((options: Record<string, unknown>) => {
      capturedCallbacks.onError = options.onError as (error: unknown) => void;
      capturedCallbacks.onFinish = options.onFinish as (state: unknown) => void;
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

  it("does NOT call toast.error when error occurs while tab is hidden (5.5)", async () => {
    setupLoadingStream();
    const snapshots: Snapshot[] = [];

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(BackgroundErrorProbe, { snapshots }),
        ),
      );
    });
    await Promise.resolve();

    setVisibility("hidden");
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(capturedCallbacks.onError).toBeTypeOf("function");
    capturedCallbacks.onError?.(new Error("connection lost"));
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it("sets backgroundPaused when tab hidden while loading (5.5)", async () => {
    setupLoadingStream();
    const snapshots: Snapshot[] = [];

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(BackgroundErrorProbe, { snapshots }),
        ),
      );
    });
    await Promise.resolve();

    expect(snapshots.at(-1)?.backgroundPaused).toBe(false);

    setVisibility("hidden");
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(snapshots.at(-1)?.backgroundPaused).toBe(true);
  });

  it("surfaces background error inline when tab returns to visible (5.5)", async () => {
    setupLoadingStream();
    const snapshots: Snapshot[] = [];

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(BackgroundErrorProbe, { snapshots }),
        ),
      );
    });
    await Promise.resolve();

    setVisibility("hidden");
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(snapshots.at(-1)?.backgroundPaused).toBe(true);

    capturedCallbacks.onError?.(new Error("background failure"));
    await React.act(async () => {
      await Promise.resolve();
    });

    setVisibility("visible");
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(snapshots.at(-1)?.backgroundPaused).toBe(false);
    expect(snapshots.at(-1)?.backgroundError).toBeInstanceOf(Error);
    expect((snapshots.at(-1)?.backgroundError as Error).message).toBe("background failure");
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it("clears backgroundPaused when tab returns to visible without error (5.5)", async () => {
    setupLoadingStream();
    const snapshots: Snapshot[] = [];

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(BackgroundErrorProbe, { snapshots }),
        ),
      );
    });
    await Promise.resolve();

    setVisibility("hidden");
    await React.act(async () => {
      await Promise.resolve();
    });
    expect(snapshots.at(-1)?.backgroundPaused).toBe(true);

    setVisibility("visible");
    await React.act(async () => {
      await Promise.resolve();
    });
    expect(snapshots.at(-1)?.backgroundPaused).toBe(false);
    expect(snapshots.at(-1)?.backgroundError).toBeNull();
  });

  it("fires onFinish callback when run fails in background and tab returns (5.6)", async () => {
    setupLoadingStream();
    const snapshots: OnFinishSnapshot[] = [];
    const onFinishCalledRef = { current: false };

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(OnFinishProbe, { snapshots, onFinishCalledRef }),
        ),
      );
    });
    await Promise.resolve();

    setVisibility("hidden");
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(snapshots.at(-1)?.backgroundPaused).toBe(true);

    capturedCallbacks.onError?.(new Error("run failed in background"));
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(toastErrorMock).not.toHaveBeenCalled();

    mocks.useStream.mockImplementation((options: Record<string, unknown>) => {
      capturedCallbacks.onError = options.onError as (error: unknown) => void;
      capturedCallbacks.onFinish = options.onFinish as (state: unknown) => void;
      return {
        messages: [],
        isLoading: false,
        isThreadLoading: false,
        error: null,
        values: {},
        stop: vi.fn(),
        submit: vi.fn(),
      };
    });

    setVisibility("visible");
    await React.act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(snapshots.at(-1)?.backgroundPaused).toBe(false);
    expect(snapshots.at(-1)?.backgroundError).toBeInstanceOf(Error);
    expect((snapshots.at(-1)?.backgroundError as Error).message).toBe("run failed in background");
    expect(toastErrorMock).not.toHaveBeenCalled();
    expect(onFinishCalledRef.current).toBe(true);
  });

  it("fires onFinish exactly once when SDK fires it in background then tab returns (1.13)", async () => {
    setupLoadingStream();
    const snapshots: OnFinishSnapshot[] = [];
    const onFinishCalledRef = { current: false };

    await React.act(async () => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(OnFinishProbe, { snapshots, onFinishCalledRef }),
        ),
      );
    });
    await Promise.resolve();

    setVisibility("hidden");
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(snapshots.at(-1)?.backgroundPaused).toBe(true);

    capturedCallbacks.onFinish?.({ values: {} });
    await React.act(async () => {
      await Promise.resolve();
    });

    expect(onFinishCalledRef.current).toBe(true);

    mocks.useStream.mockImplementation((options: Record<string, unknown>) => {
      capturedCallbacks.onError = options.onError as (error: unknown) => void;
      capturedCallbacks.onFinish = options.onFinish as (state: unknown) => void;
      return {
        messages: [],
        isLoading: false,
        isThreadLoading: false,
        error: null,
        values: {},
        stop: vi.fn(),
        submit: vi.fn(),
      };
    });

    onFinishCalledRef.current = false;

    setVisibility("visible");
    await React.act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(snapshots.at(-1)?.backgroundPaused).toBe(false);
    expect(onFinishCalledRef.current).toBe(false);
  });
});

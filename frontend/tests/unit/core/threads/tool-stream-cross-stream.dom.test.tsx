/**
 * Cross-stream scoping of the tool-streaming map (#4150).
 *
 * ``ToolStreamingProvider`` is mounted **once per route** (``chat-providers``,
 * which the route ``layout.tsx`` renders), while two independent
 * ``useThreadStream`` consumers hang off it: the main conversation
 * (``chat-page``) and the sidecar panel (``chat-box`` renders ``SidecarPanel``
 * inside the same provider).  The provider's map is keyed by ``tool_call_id``
 * only — there is no thread dimension.
 *
 * The run-end teardown therefore has to be scoped to the entries the calling
 * stream owns.  A global clear lets one stream's run end wipe the other
 * stream's in-flight tool output, which is precisely what these tests pin.
 *
 * The ``useStream`` mock registers its callbacks **per thread id** so each
 * stream can be driven independently, mirroring the SDK, where each thread's
 * SSE connection only delivers its own thread's events.
 */
import type { Message } from "@langchain/langgraph-sdk";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { ChatProviders } from "@/components/workspace/chats/chat-providers";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import {
  ToolStreamingProvider,
  useToolCallStream,
} from "@/core/tasks/tool-streaming";
import type * as ThreadsHooks from "@/core/threads/hooks";

interface StreamCallbacks {
  onFinish?: (state: { values: { messages: Message[] } }) => void;
  onError?: (error: unknown) => void;
  onStop?: (options: { mutate: (updater: unknown) => void }) => void;
  onUpdateEvent?: (
    data: unknown,
    options: { mutate: (updater: unknown) => void },
  ) => void;
  onCustomEvent?: (event: unknown) => void;
}

const streams = rs.hoisted(() => ({
  byThread: {} as Record<string, StreamCallbacks>,
}));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: {
    threadId?: string;
    onFinish?: StreamCallbacks["onFinish"];
    onError?: StreamCallbacks["onError"];
    onStop?: StreamCallbacks["onStop"];
    onUpdateEvent?: StreamCallbacks["onUpdateEvent"];
    onCustomEvent?: StreamCallbacks["onCustomEvent"];
  }) => {
    if (options.threadId) {
      streams.byThread[options.threadId] = {
        onFinish: options.onFinish,
        onError: options.onError,
        onStop: options.onStop,
        onUpdateEvent: options.onUpdateEvent,
        onCustomEvent: options.onCustomEvent,
      };
    }
    return {
      isLoading: false,
      messages: [],
      stop: async () => undefined,
      submit: async () => undefined,
      values: { artifacts: [], messages: [], title: "", todos: [] },
    };
  },
}));

const MAIN_THREAD = "thread-main";
const SIDECAR_THREAD = "thread-sidecar";
const MAIN_TOOL_CALL = "tc-main";
const SIDECAR_TOOL_CALL = "tc-sidecar";

// Loaded per test so the `rs.mock` above is in place before the hook module
// (and its SDK import) is evaluated.
let useThreadStream: typeof ThreadsHooks.useThreadStream;

/**
 * Mirrors the streaming block in ``subtask-card``: the spinner exists exactly
 * while ``useToolCallStream`` holds a partial entry for this tool call.
 */
function ToolStreamProbe({
  testId,
  toolCallId,
}: {
  testId: string;
  toolCallId: string;
}) {
  const stream = useToolCallStream(toolCallId);
  return createElement(
    "span",
    { "data-testid": testId, "data-present": stream ? "yes" : "no" },
    stream?.isPartial
      ? createElement("span", {
          "data-testid": `${testId}-spinner`,
          className: "animate-spin",
        })
      : null,
  );
}

/** One thread view: its own stream hook plus the card that renders its spinner. */
function ThreadView({
  threadId,
  testId,
  toolCallId,
}: {
  threadId: string;
  testId: string;
  toolCallId: string;
}) {
  useThreadStream({
    context: DEFAULT_LOCAL_SETTINGS.context,
    isMock: true,
    threadId,
  });
  return createElement(ToolStreamProbe, { testId, toolCallId });
}

function createWrapper(queryClient: QueryClient) {
  return function ToolStreamTestWrapper({ children }: { children: ReactNode }) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(
        I18nContext.Provider,
        {
          value: { locale: "en-US", setLocale: () => undefined, t: enUS },
        },
        createElement(ToolStreamingProvider, null, children),
      ),
    );
  };
}

/** Mount the main thread and the sidecar thread under ONE provider. */
async function renderBothStreams() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    createElement(
      "div",
      null,
      createElement(ThreadView, {
        threadId: MAIN_THREAD,
        testId: "main-stream",
        toolCallId: MAIN_TOOL_CALL,
      }),
      createElement(ThreadView, {
        threadId: SIDECAR_THREAD,
        testId: "sidecar-stream",
        toolCallId: SIDECAR_TOOL_CALL,
      }),
    ),
    { wrapper: createWrapper(queryClient) },
  );
  await flushFrames();
  return view;
}

/** Let the render chain from mount effects settle without ever sleeping. */
async function flushFrames() {
  for (let index = 0; index < 6; index += 1) {
    await act(async () => {
      await rs.advanceTimersByTimeAsync(0);
    });
  }
}

function present(container: HTMLElement, testId: string): string | null {
  return (
    container
      .querySelector(`[data-testid="${testId}"]`)
      ?.getAttribute("data-present") ?? null
  );
}

/** Feed one partial chunk to a specific thread's stream. */
function startToolStream(threadId: string, toolCallId: string): void {
  act(() => {
    streams.byThread[threadId]?.onCustomEvent?.({
      type: "tool_output_chunk",
      tool_call_id: toolCallId,
      tool_name: "bash",
      chunk: "partial output",
      is_partial: true,
      is_final: false,
    });
  });
}

function finishStream(threadId: string): void {
  act(() => {
    streams.byThread[threadId]?.onFinish?.({ values: { messages: [] } });
  });
}

function failStream(threadId: string): void {
  act(() => {
    streams.byThread[threadId]?.onError?.(new Error("stream lost"));
  });
}

function replayGap(threadId: string): void {
  act(() => {
    streams.byThread[threadId]?.onCustomEvent?.({ type: "stream_replay_gap" });
  });
}

/**
 * User cancellation.  The SDK calls the user's ``onStop`` (and only that
 * callback: ``manager.js`` swallows AbortError before ``onError`` and never
 * reaches the ``onSuccess`` that carries ``onFinish``).
 */
function stopStream(threadId: string): void {
  act(() => {
    streams.byThread[threadId]?.onStop?.({ mutate: () => undefined });
  });
}

beforeEach(async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  streams.byThread = {};
  rs.stubGlobal(
    "fetch",
    async () =>
      new Response(
        JSON.stringify({ data: [], has_more: false, next_before_seq: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
  );
  ({ useThreadStream } = await import("@/core/threads/hooks"));
});

afterEach(() => {
  cleanup();
  rs.useRealTimers();
  rs.unstubAllGlobals();
});

describe("tool-stream teardown is scoped to the stream that owns the run", () => {
  test("two concurrent streams share the provider map", async () => {
    const { container } = await renderBothStreams();

    startToolStream(MAIN_THREAD, MAIN_TOOL_CALL);
    startToolStream(SIDECAR_THREAD, SIDECAR_TOOL_CALL);

    expect(present(container, "main-stream")).toBe("yes");
    expect(present(container, "sidecar-stream")).toBe("yes");
  });

  test("the main thread finishing keeps the sidecar's in-flight entry", async () => {
    const { container } = await renderBothStreams();
    startToolStream(SIDECAR_THREAD, SIDECAR_TOOL_CALL);
    expect(present(container, "sidecar-stream")).toBe("yes");

    // The main conversation's run ends while the sidecar is still streaming.
    finishStream(MAIN_THREAD);

    expect(present(container, "sidecar-stream")).toBe("yes");
  });

  test("the sidecar finishing keeps the main thread's in-flight entry", async () => {
    const { container } = await renderBothStreams();
    startToolStream(MAIN_THREAD, MAIN_TOOL_CALL);
    expect(present(container, "main-stream")).toBe("yes");

    finishStream(SIDECAR_THREAD);

    expect(present(container, "main-stream")).toBe("yes");
  });

  test("the main thread erroring keeps the sidecar's in-flight entry", async () => {
    const { container } = await renderBothStreams();
    startToolStream(SIDECAR_THREAD, SIDECAR_TOOL_CALL);
    expect(present(container, "sidecar-stream")).toBe("yes");

    failStream(MAIN_THREAD);

    expect(present(container, "sidecar-stream")).toBe("yes");
  });

  test("a replay gap on the main thread keeps the sidecar's in-flight entry", async () => {
    const { container } = await renderBothStreams();
    startToolStream(SIDECAR_THREAD, SIDECAR_TOOL_CALL);
    expect(present(container, "sidecar-stream")).toBe("yes");

    replayGap(MAIN_THREAD);

    expect(present(container, "sidecar-stream")).toBe("yes");
  });
});

describe("the three run-end teardown routes still clear their own stream", () => {
  test("onFinish clears this stream's entry", async () => {
    const { container } = await renderBothStreams();
    startToolStream(MAIN_THREAD, MAIN_TOOL_CALL);
    expect(present(container, "main-stream")).toBe("yes");

    finishStream(MAIN_THREAD);

    expect(present(container, "main-stream")).toBe("no");
  });

  test("onError clears this stream's entry", async () => {
    const { container } = await renderBothStreams();
    startToolStream(MAIN_THREAD, MAIN_TOOL_CALL);
    expect(present(container, "main-stream")).toBe("yes");

    failStream(MAIN_THREAD);

    expect(present(container, "main-stream")).toBe("no");
  });

  test("a replay gap clears this stream's entry", async () => {
    const { container } = await renderBothStreams();
    startToolStream(SIDECAR_THREAD, SIDECAR_TOOL_CALL);
    expect(present(container, "sidecar-stream")).toBe("yes");

    replayGap(SIDECAR_THREAD);

    expect(present(container, "sidecar-stream")).toBe("no");
  });

  test("a run end also clears an entry whose final chunk was dropped earlier", async () => {
    const { container } = await renderBothStreams();
    startToolStream(MAIN_THREAD, MAIN_TOOL_CALL);
    startToolStream(MAIN_THREAD, "tc-main-second");
    startToolStream(SIDECAR_THREAD, SIDECAR_TOOL_CALL);

    failStream(MAIN_THREAD);

    // Both of this stream's entries go; the sidecar's survives.
    expect(present(container, "main-stream")).toBe("no");
    expect(present(container, "sidecar-stream")).toBe("yes");
  });
});

describe("the real route-level provider wrapper shares one map", () => {
  test("ChatProviders gives both streams the same tool-stream context", async () => {
    // Same probe, but through the actual component the three route
    // ``layout.tsx`` files render, so the "mounted once per route" premise is
    // asserted against real code instead of the bare provider.
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { container } = render(
      createElement(
        "div",
        null,
        createElement(ThreadView, {
          threadId: MAIN_THREAD,
          testId: "main-stream",
          toolCallId: MAIN_TOOL_CALL,
        }),
        createElement(ThreadView, {
          threadId: SIDECAR_THREAD,
          testId: "sidecar-stream",
          toolCallId: SIDECAR_TOOL_CALL,
        }),
      ),
      {
        wrapper: ({ children }: { children: ReactNode }) =>
          createElement(
            QueryClientProvider,
            { client: queryClient },
            createElement(
              I18nContext.Provider,
              {
                value: { locale: "en-US", setLocale: () => undefined, t: enUS },
              },
              // ``ArtifactsProvider`` (inside ``ChatProviders``) reads the
              // sidebar context, which the workspace shell supplies in the app.
              createElement(
                SidebarProvider,
                null,
                createElement(ChatProviders, null, children),
              ),
            ),
          ),
      },
    );
    await flushFrames();

    startToolStream(MAIN_THREAD, MAIN_TOOL_CALL);
    startToolStream(SIDECAR_THREAD, SIDECAR_TOOL_CALL);
    expect(present(container, "main-stream")).toBe("yes");
    expect(present(container, "sidecar-stream")).toBe("yes");

    finishStream(MAIN_THREAD);

    expect(present(container, "main-stream")).toBe("no");
    expect(present(container, "sidecar-stream")).toBe("yes");
  });
});

describe("user cancellation tears the aborted run's entries down", () => {
  test("onStop clears this stream's entry", async () => {
    const { container } = await renderBothStreams();
    startToolStream(MAIN_THREAD, MAIN_TOOL_CALL);
    expect(present(container, "main-stream")).toBe("yes");

    stopStream(MAIN_THREAD);

    expect(present(container, "main-stream")).toBe("no");
  });

  test("onStop keeps the sidecar's in-flight entry", async () => {
    const { container } = await renderBothStreams();
    startToolStream(SIDECAR_THREAD, SIDECAR_TOOL_CALL);
    expect(present(container, "sidecar-stream")).toBe("yes");

    stopStream(MAIN_THREAD);

    expect(present(container, "sidecar-stream")).toBe("yes");
  });
});

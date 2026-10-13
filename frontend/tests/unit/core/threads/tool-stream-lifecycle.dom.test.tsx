/**
 * Tool-stream teardown at run termination (#4150).
 *
 * A ``tool_output_chunk`` entry only leaves the streaming map when its
 * ``is_final`` chunk arrives.  A run can end without one — it errored, the
 * stream replay had a gap, or the final chunk was emitted before a disconnect
 * — and the entry then stayed in the provider's map, keeping its spinner
 * rendered until the provider remounted.
 *
 * These drive the real ``useThreadStream`` against the real
 * ``ToolStreamingProvider`` and assert through ``useToolCallStream``, which is
 * exactly what ``subtask-card`` renders the streaming block (and its spinner)
 * from.
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

import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import {
  ToolStreamingProvider,
  useToolCallStream,
} from "@/core/tasks/tool-streaming";
import type * as ThreadsHooks from "@/core/threads/hooks";

const streamMockState = rs.hoisted(() => ({
  isLoading: false,
  messages: [] as Message[],
  onFinish: undefined as
    | ((state: { values: { messages: Message[] } }) => void)
    | undefined,
  onError: undefined as ((error: unknown) => void) | undefined,
  onUpdateEvent: undefined as
    | ((data: unknown, options: { mutate: (updater: unknown) => void }) => void)
    | undefined,
  onCustomEvent: undefined as ((event: unknown) => void) | undefined,
  stop: rs.fn(async () => undefined),
  submit: rs.fn(async () => undefined),
}));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: {
    onFinish?: (state: { values: { messages: Message[] } }) => void;
    onError?: (error: unknown) => void;
    onUpdateEvent?: (
      data: unknown,
      options: { mutate: (updater: unknown) => void },
    ) => void;
    onCustomEvent?: (event: unknown) => void;
  }) => {
    streamMockState.onFinish = options.onFinish;
    streamMockState.onError = options.onError;
    streamMockState.onUpdateEvent = options.onUpdateEvent;
    streamMockState.onCustomEvent = options.onCustomEvent;
    return {
      isLoading: streamMockState.isLoading,
      messages: streamMockState.messages,
      stop: streamMockState.stop,
      submit: streamMockState.submit,
      values: {
        artifacts: [],
        messages: streamMockState.messages,
        title: "",
        todos: [],
      },
    };
  },
}));

const TOOL_CALL_ID = "tc-stream";

// Loaded per test so the `rs.mock` above is in place before the hook module
// (and its SDK import) is evaluated.
let useThreadStream: typeof ThreadsHooks.useThreadStream;

/**
 * Mirrors the streaming block in ``subtask-card``: the spinner exists exactly
 * while ``useToolCallStream`` holds a partial entry for this tool call.
 */
function ToolStreamProbe({ toolCallId }: { toolCallId: string }) {
  const stream = useToolCallStream(toolCallId);
  return createElement(
    "span",
    { "data-testid": "tool-stream", "data-present": stream ? "yes" : "no" },
    stream?.isPartial
      ? createElement("span", {
          "data-testid": "tool-stream-spinner",
          className: "animate-spin",
        })
      : null,
  );
}

/** A whole thread view: the stream hook plus the card that renders the spinner. */
function ThreadView({ threadId }: { threadId: string }) {
  useThreadStream({
    context: DEFAULT_LOCAL_SETTINGS.context,
    isMock: true,
    threadId,
  });
  return createElement(ToolStreamProbe, { toolCallId: TOOL_CALL_ID });
}

function createWrapper(queryClient: QueryClient) {
  return function ToolStreamTestWrapper({ children }: { children: ReactNode }) {
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
        createElement(ToolStreamingProvider, null, children),
      ),
    );
  };
}

/** Mount a thread view and let the mount effects settle. */
async function renderThread(threadId = "thread-1") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(createElement(ThreadView, { threadId }), {
    wrapper: createWrapper(queryClient),
  });
  await flushFrames();
  return { ...view, queryClient };
}

/** Let the render chain from mount effects settle without ever sleeping. */
async function flushFrames() {
  for (let index = 0; index < 6; index += 1) {
    await act(async () => {
      await rs.advanceTimersByTimeAsync(0);
    });
  }
}

function toolStreamEntry(container: HTMLElement): Element | null {
  return container.querySelector('[data-testid="tool-stream"]');
}

function spinners(container: HTMLElement): NodeListOf<Element> {
  return container.querySelectorAll('[data-testid="tool-stream-spinner"]');
}

/** Feed one partial chunk, i.e. a tool call that is still in flight. */
function startToolStream(): void {
  act(() => {
    streamMockState.onCustomEvent?.({
      type: "tool_output_chunk",
      tool_call_id: TOOL_CALL_ID,
      tool_name: "bash",
      chunk: "partial output",
      is_partial: true,
      is_final: false,
    });
  });
}

/**
 * Remount the same view: before the fix a stale entry survived in the provider
 * and the card kept spinning, so the assertion is repeated after a remount too.
 */
async function expectNoStaleSpinnerAfterRemount(view: {
  unmount: () => void;
  queryClient: QueryClient;
}): Promise<void> {
  view.unmount();
  const remounted = render(
    createElement(ThreadView, { threadId: "thread-1" }),
    {
      wrapper: createWrapper(view.queryClient),
    },
  );
  await flushFrames();
  expect(spinners(remounted.container)).toHaveLength(0);
  expect(
    toolStreamEntry(remounted.container)?.getAttribute("data-present"),
  ).toBe("no");
}

beforeEach(async () => {
  // Only the timers the hook schedules need faking; faking the whole clock
  // breaks React's scheduler in a DOM environment.
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  streamMockState.isLoading = false;
  streamMockState.messages = [];
  streamMockState.onFinish = undefined;
  streamMockState.onError = undefined;
  streamMockState.onUpdateEvent = undefined;
  streamMockState.onCustomEvent = undefined;
  streamMockState.stop.mockClear();
  streamMockState.submit.mockClear();
  // Mock mode never fetches history, but the hook still mounts its query
  // plumbing — keep any stray request from escaping to a real socket.
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

describe("tool-stream teardown when a run ends without a final chunk", () => {
  test("a partial chunk renders the streaming entry and its spinner", async () => {
    const { container } = await renderThread();

    expect(toolStreamEntry(container)?.getAttribute("data-present")).toBe("no");
    startToolStream();

    expect(toolStreamEntry(container)?.getAttribute("data-present")).toBe(
      "yes",
    );
    expect(spinners(container)).toHaveLength(1);
  });

  test("onFinish clears the entry so no spinner survives a remount", async () => {
    const { container, unmount, queryClient } = await renderThread();
    startToolStream();
    expect(spinners(container)).toHaveLength(1);

    // The run ends without the tool's is_final chunk ever arriving.
    act(() => {
      streamMockState.onFinish?.({ values: { messages: [] } });
    });

    expect(toolStreamEntry(container)?.getAttribute("data-present")).toBe("no");
    expect(spinners(container)).toHaveLength(0);
    await expectNoStaleSpinnerAfterRemount({ unmount, queryClient });
  });

  test("onError clears the entry so no spinner survives a remount", async () => {
    const { container, unmount, queryClient } = await renderThread();
    startToolStream();
    expect(spinners(container)).toHaveLength(1);

    act(() => {
      streamMockState.onError?.(new Error("stream lost"));
    });

    expect(toolStreamEntry(container)?.getAttribute("data-present")).toBe("no");
    expect(spinners(container)).toHaveLength(0);
    await expectNoStaleSpinnerAfterRemount({ unmount, queryClient });
  });

  test("a stream replay gap clears the entry so no spinner survives a remount", async () => {
    const { container, unmount, queryClient } = await renderThread();
    startToolStream();
    expect(spinners(container)).toHaveLength(1);

    // A gap means the is_final chunk may have been dropped outright, so this
    // entry can never be completed by a later chunk.
    act(() => {
      streamMockState.onCustomEvent?.({ type: "stream_replay_gap" });
    });

    expect(toolStreamEntry(container)?.getAttribute("data-present")).toBe("no");
    expect(spinners(container)).toHaveLength(0);
    await expectNoStaleSpinnerAfterRemount({ unmount, queryClient });
  });

  test("a final chunk still tears the entry down on its own", async () => {
    const { container, unmount, queryClient } = await renderThread();
    startToolStream();
    expect(spinners(container)).toHaveLength(1);

    act(() => {
      streamMockState.onCustomEvent?.({
        type: "tool_output_chunk",
        tool_call_id: TOOL_CALL_ID,
        tool_name: "bash",
        chunk: "final output",
        is_partial: false,
        is_final: true,
      });
    });

    expect(toolStreamEntry(container)?.getAttribute("data-present")).toBe("no");
    expect(spinners(container)).toHaveLength(0);
    await expectNoStaleSpinnerAfterRemount({ unmount, queryClient });
  });
});

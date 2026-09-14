import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { isHiddenFromUIMessage } from "@/core/messages/utils";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import type { RunMessage } from "@/core/threads/types";

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

function humanMessage(
  id: string,
  text: string,
  extra?: Record<string, unknown>,
): Message {
  return {
    id,
    type: "human",
    content: [{ type: "text", text }],
    ...(extra ? { additional_kwargs: extra } : {}),
  } as Message;
}

function aiMessage(
  id: string,
  text: string,
  extra?: { run_id?: string; seq?: number },
): Message {
  return {
    id,
    type: "ai",
    content: text,
    ...(extra?.run_id ? { run_id: extra.run_id } : {}),
    ...(extra?.seq !== undefined
      ? { additional_kwargs: { deerflow_seq: extra.seq } }
      : {}),
  } as Message;
}

function historyRow(seq: number, runId: string, content: Message): RunMessage {
  return {
    run_id: runId,
    seq,
    content,
    metadata: { caller: "" },
    created_at: "2026-09-08T00:00:00Z",
  } as RunMessage;
}

function historyPageResponse(rows: RunMessage[]): Response {
  return new Response(
    JSON.stringify({ data: rows, has_more: false, next_before_seq: null }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

/** Serve per-thread history pages through the wrapped API fetcher. */
function stubHistoryFetch(pagesByThread: Record<string, () => RunMessage[]>) {
  rs.stubGlobal("fetch", async (input: unknown) => {
    const url = String(input);
    const pageMatch = /\/api\/threads\/([^/]+)\/messages\/page/.exec(url);
    if (pageMatch) {
      return historyPageResponse(pagesByThread[pageMatch[1]!]?.() ?? []);
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}

function visibleMessageIds(messages: Message[]): string[] {
  return messages
    .filter((message) => !isHiddenFromUIMessage(message))
    .map((message) => String(message.id));
}

function createWrapper(queryClient: QueryClient) {
  return function ThreadStreamTestWrapper({
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
  // React Query delivers cache updates through setTimeout(0) and the history
  // retained-rows effect adds another render cycle, so a flush fires due
  // 0ms timers (never the 80ms coalesce trailing flush) and lets the render
  // chain settle — a fixed number of rounds, never a real sleep.
  for (let index = 0; index < 6; index += 1) {
    await act(async () => {
      if (rs.isFakeTimers()) {
        await rs.advanceTimersByTimeAsync(0);
      }
    });
  }
}

beforeEach(() => {
  streamMockState.isLoading = false;
  streamMockState.messages = [];
  streamMockState.onFinish = undefined;
  streamMockState.onError = undefined;
  streamMockState.onUpdateEvent = undefined;
  streamMockState.onCustomEvent = undefined;
  streamMockState.stop.mockClear();
  streamMockState.submit.mockClear();
});

afterEach(() => {
  rs.useRealTimers();
  rs.unstubAllGlobals();
});

// Compaction trimmed the checkpoint tail to the latest turn while the REST
// history feed still holds both turns: A更早(1), H旧(2), H近(3), A近(4).
const EARLIER_ANSWER = aiMessage("earlier-answer", "Earlier answer");
const OLD_HUMAN = humanMessage("old-human", "An older request");
const RECENT_HUMAN = humanMessage("recent-human", "The recent request");
const RECENT_ANSWER = aiMessage("recent-answer", "The recent answer");

function seededHistoryRows(): RunMessage[] {
  return [
    historyRow(1, "run-earlier", EARLIER_ANSWER),
    historyRow(2, "run-old", OLD_HUMAN),
    historyRow(3, "run-recent", RECENT_HUMAN),
    historyRow(4, "run-recent", RECENT_ANSWER),
  ];
}

function checkpointMessages(): Message[] {
  return [
    {
      id: "recent-human",
      type: "human",
      content: [{ type: "text", text: "The recent request" }],
      additional_kwargs: { deerflow_seq: 3 },
    } as Message,
    aiMessage("recent-answer", "The recent answer", { seq: 4 }),
  ];
}

async function renderSeededThread(options?: {
  threadId?: string;
  isMock?: boolean;
  historyRows?: () => RunMessage[];
}) {
  const threadId = options?.threadId ?? "thread-1";
  if (!options?.isMock) {
    stubHistoryFetch({
      [threadId]: options?.historyRows ?? (() => []),
    });
  }
  const { useThreadStream } = await import("@/core/threads/hooks");
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const hook = renderHook(
    ({ currentThreadId }: { currentThreadId?: string } = {}) =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        isMock: options?.isMock ?? false,
        threadId: currentThreadId ?? threadId,
      }),
    { wrapper: createWrapper(queryClient) },
  );
  await flushFrames();
  return hook;
}

/** Submit one visible turn and return the id shared by display and submit. */
async function submitVisibleTurn(
  result: {
    current: {
      sendMessage: (
        threadId: string,
        message: { files: []; text: string },
      ) => Promise<unknown>;
      thread: { messages: Message[] };
    };
  },
  text = "Continue the work",
): Promise<string> {
  await act(async () => {
    await result.current.sendMessage("thread-1", { files: [], text });
  });
  const displayed = result.current.thread.messages.at(-1);
  const submittedId = displayed?.id;
  expect(typeof submittedId).toBe("string");
  // The submit mock is an untyped rs.fn(); cast the call list once so the
  // tuple indexing below typechecks.
  const submitCalls = streamMockState.submit.mock.calls as unknown as Array<
    [{ messages: Message[] }]
  >;
  const submittedInput = submitCalls.at(-1)?.[0];
  expect(submittedInput?.messages.at(-1)?.id).toBe(submittedId);
  return submittedId!;
}

test("keeps early streamed steps behind a local user message after finish", async () => {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const { rerender, result } = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        isMock: true,
        threadId: "thread-1",
      }),
    { wrapper: createWrapper(queryClient) },
  );

  const submittedId = await submitVisibleTurn(result, "Build a presentation");

  const earlyAssistantStep = {
    id: "early-assistant-step",
    type: "ai",
    content: "Reading the presentation skill",
  } as Message;
  // The server keeps the client-submitted id and the runtime injects the
  // visible copy as `<id>__user`; both normalize onto the same identity.
  const injectedHuman = {
    id: `${submittedId}__user`,
    type: "human",
    content: "Build a presentation",
  } as Message;
  streamMockState.messages = [earlyAssistantStep, injectedHuman];
  streamMockState.isLoading = true;
  rerender();

  expect(result.current.thread.messages).toEqual([
    injectedHuman,
    earlyAssistantStep,
  ]);

  act(() => {
    streamMockState.onFinish?.({
      values: { messages: streamMockState.messages },
    });
    streamMockState.isLoading = false;
    rerender();
  });

  expect(result.current.thread.messages).toEqual([
    injectedHuman,
    earlyAssistantStep,
  ]);
});

test("keeps established history order while the submitted human is outside the render snapshot", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  let rows = seededHistoryRows();
  streamMockState.messages = checkpointMessages();
  const { rerender, result } = await renderSeededThread({
    historyRows: () => rows,
  });

  // Frame 0: history beyond the checkpoint baseline renders in feed order.
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
  ]);

  const submittedId = await submitVisibleTurn(result);
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    submittedId,
  ]);

  // Frame 1 (leading-edge flush): the first AI step of the new turn arrives
  // before the server echo of the human input.
  const newStep = aiMessage("new-step", "Working on the follow-up", {
    run_id: "run-new",
  });
  streamMockState.messages = [RECENT_HUMAN, RECENT_ANSWER, newStep];
  streamMockState.isLoading = true;
  rerender();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    submittedId,
    "new-step",
  ]);

  // Frame 2: the server human copy reaches the unthrottled SDK state, but the
  // ~80ms render snapshot cannot see it yet. The established history must keep
  // its order and the local input must stay visible — no frame may drop the
  // current turn's human or relocate the history-only `old-human`.
  const serverHuman = {
    id: `${submittedId}__user`,
    type: "human",
    content: "Continue the work",
    run_id: "run-new",
  } as Message;
  streamMockState.messages = [
    RECENT_HUMAN,
    RECENT_ANSWER,
    newStep,
    serverHuman,
  ];
  rerender();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    submittedId,
    "new-step",
  ]);

  // Frame 3: the throttled snapshot catches up; the confirmed server copy
  // takes over the same identity exactly once.
  await act(async () => {
    await rs.advanceTimersByTimeAsync(100);
  });
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    `${submittedId}__user`,
    "new-step",
  ]);

  // Frame 4: finish triggers the history refetch; the canonical page now
  // commits the whole turn and the display converges to seq order.
  rows = [
    ...seededHistoryRows(),
    historyRow(5, "run-new", serverHuman),
    historyRow(6, "run-new", newStep),
  ];
  await act(async () => {
    streamMockState.onFinish?.({
      values: { messages: streamMockState.messages },
    });
    streamMockState.isLoading = false;
  });
  rerender();
  await flushFrames();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    `${submittedId}__user`,
    "new-step",
  ]);
});

test("keeps a pre-submit older-turn rescue above the submitted human", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  const rescuedOldHuman = {
    id: "rescued-old-human",
    type: "human",
    content: "Older request",
    run_id: "run-old",
    additional_kwargs: { deerflow_seq: 1 },
  } as Message;
  const rescuedOldAnswer = aiMessage("rescued-old-answer", "Older answer", {
    run_id: "run-old",
    seq: 2,
  });
  const recentHuman = {
    id: "recent-human",
    type: "human",
    content: "Recent request",
    run_id: "run-recent",
    additional_kwargs: { deerflow_seq: 3 },
  } as Message;
  const recentAnswer = aiMessage("recent-answer", "Recent answer", {
    run_id: "run-recent",
    seq: 4,
  });
  const rows = [
    historyRow(3, "run-recent", recentHuman),
    historyRow(4, "run-recent", recentAnswer),
  ];
  streamMockState.messages = [
    rescuedOldHuman,
    rescuedOldAnswer,
    recentHuman,
    recentAnswer,
  ];
  const { rerender, result } = await renderSeededThread({
    historyRows: () => rows,
  });

  const removeAll = {
    id: "__remove_all__",
    type: "remove",
    content: "",
  } as Message;
  const hiddenSummary = humanMessage("summary-old", "Conversation summary", {
    hide_from_ui: true,
  });
  act(() => {
    streamMockState.onUpdateEvent?.(
      {
        "DeerFlowSummarizationMiddleware.before_model": {
          messages: [removeAll, hiddenSummary, recentHuman, recentAnswer],
        },
      },
      { mutate: () => undefined },
    );
    streamMockState.messages = [hiddenSummary, recentHuman, recentAnswer];
    rerender();
  });
  await act(async () => {
    await rs.advanceTimersByTimeAsync(100);
  });
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "rescued-old-human",
    "rescued-old-answer",
    "recent-human",
    "recent-answer",
  ]);

  await act(async () => {
    await result.current.sendMessage("thread-1", {
      files: [],
      text: "Continue the work",
    });
  });
  const submitCalls = streamMockState.submit.mock.calls as unknown as Array<
    [{ messages: Message[] }]
  >;
  const submittedId = submitCalls.at(-1)?.[0].messages.at(-1)?.id;
  expect(typeof submittedId).toBe("string");
  const serverHuman = {
    id: `${submittedId}__user`,
    type: "human",
    content: "Continue the work",
    run_id: "run-current",
  } as Message;
  const currentStep = aiMessage("current-step", "Current step", {
    run_id: "run-current",
  });
  streamMockState.messages = [
    hiddenSummary,
    recentHuman,
    recentAnswer,
    serverHuman,
    currentStep,
  ];
  streamMockState.isLoading = true;
  rerender();
  await act(async () => {
    await rs.advanceTimersByTimeAsync(100);
  });

  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "rescued-old-human",
    "rescued-old-answer",
    "recent-human",
    "recent-answer",
    `${submittedId}__user`,
    "current-step",
  ]);
});

test("keeps a transiently rescued current-turn step behind its submitted human", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  const previousHuman = humanMessage("previous-human", "Previous request");
  const previousAnswer = aiMessage("previous-answer", "Previous answer", {
    run_id: "run-previous",
  });
  const rows = [
    historyRow(1, "run-previous", previousHuman),
    historyRow(2, "run-previous", previousAnswer),
  ];
  streamMockState.messages = [previousHuman, previousAnswer];
  const { rerender, result } = await renderSeededThread({
    historyRows: () => rows,
  });

  const submittedId = await submitVisibleTurn(result);
  const serverHuman = {
    id: `${submittedId}__user`,
    type: "human",
    content: "Continue the work",
    run_id: "run-current",
  } as Message;
  // Deliberately omit run_id: this is the streamed step whose ownership has
  // not yet been restored by canonical history.
  const rescuedStep = aiMessage("rescued-step", "First current step");
  const retainedStep = aiMessage("retained-step", "Latest current step", {
    run_id: "run-current",
  });
  streamMockState.messages = [serverHuman, rescuedStep, retainedStep];
  streamMockState.isLoading = true;
  rerender();
  await act(async () => {
    await rs.advanceTimersByTimeAsync(100);
  });
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "previous-human",
    "previous-answer",
    `${submittedId}__user`,
    "rescued-step",
    "retained-step",
  ]);

  const removeAll = {
    id: "__remove_all__",
    type: "remove",
    content: "",
  } as Message;
  const hiddenSummary = humanMessage(
    "summary-current",
    "Conversation summary",
    { hide_from_ui: true },
  );
  act(() => {
    streamMockState.onUpdateEvent?.(
      {
        "DeerFlowSummarizationMiddleware.before_model": {
          messages: [removeAll, hiddenSummary, serverHuman, retainedStep],
        },
      },
      { mutate: () => undefined },
    );
    streamMockState.messages = [hiddenSummary, serverHuman, retainedStep];
    rerender();
  });
  await act(async () => {
    await rs.advanceTimersByTimeAsync(100);
  });

  // The rescued step is transient current-turn state, not canonical old
  // history, so it must remain behind the submitted human.
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "previous-human",
    "previous-answer",
    `${submittedId}__user`,
    "rescued-step",
    "retained-step",
  ]);
});

test("does not move a later externally submitted answer ahead of the retained local anchor", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  const previousHuman = humanMessage("previous-human", "Previous request");
  const previousAnswer = aiMessage("previous-answer", "Previous answer", {
    run_id: "run-previous",
  });
  let rows = [
    historyRow(1, "run-previous", previousHuman),
    historyRow(2, "run-previous", previousAnswer),
  ];
  streamMockState.messages = [previousHuman, previousAnswer];
  const { rerender, result } = await renderSeededThread({
    historyRows: () => rows,
  });

  const submittedId = await submitVisibleTurn(result);
  const localHuman = {
    id: `${submittedId}__user`,
    type: "human",
    content: "Continue the work",
    run_id: "run-local",
  } as Message;
  const localAnswer = aiMessage("local-answer", "Local answer", {
    run_id: "run-local",
  });
  streamMockState.messages = [localHuman, localAnswer];
  streamMockState.isLoading = true;
  rerender();
  await act(async () => {
    await rs.advanceTimersByTimeAsync(100);
  });

  const remoteHuman = humanMessage("remote-human", "Later request elsewhere");
  const remoteAnswer = aiMessage("remote-answer", "Later external answer", {
    run_id: "run-remote",
  });
  rows = [
    historyRow(1, "run-previous", previousHuman),
    historyRow(2, "run-previous", previousAnswer),
    historyRow(3, "run-local", localHuman),
    historyRow(4, "run-local", localAnswer),
    historyRow(5, "run-remote", remoteHuman),
    historyRow(6, "run-remote", remoteAnswer),
  ];
  await act(async () => {
    streamMockState.onFinish?.({
      values: { messages: streamMockState.messages },
    });
    streamMockState.isLoading = false;
  });
  rerender();
  await flushFrames();

  // The local anchor survives finish only to repair its own turn. Canonical
  // messages submitted later by another client must retain their feed order.
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "previous-human",
    "previous-answer",
    `${submittedId}__user`,
    "local-answer",
    "remote-human",
    "remote-answer",
  ]);
});

test("hidden human-input reply never borrows an older visible human as its turn anchor", async () => {
  const rows = seededHistoryRows();
  streamMockState.messages = checkpointMessages();
  const { rerender, result } = await renderSeededThread({
    historyRows: () => rows,
  });

  // A clarification answer submits hidden: no visible optimistic human exists
  // for this turn at all.
  await act(async () => {
    await result.current.sendMessage(
      "thread-1",
      { files: [], text: "For your clarification, my answer is: staging" },
      undefined,
      { additionalKwargs: { hide_from_ui: true } },
    );
  });
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
  ]);

  const hiddenReply = humanMessage(
    "hidden-reply",
    "For your clarification, my answer is: staging",
    { hide_from_ui: true },
  );
  const replyStep = aiMessage("reply-step", "Applying the answer", {
    run_id: "run-reply",
  });
  streamMockState.messages = [
    RECENT_HUMAN,
    RECENT_ANSWER,
    hiddenReply,
    replyStep,
  ];
  streamMockState.isLoading = true;
  rerender();

  // The hidden turn must not re-anchor on `old-human`: visible history order
  // is already correct and stays untouched, the new step appends at the tail.
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    "reply-step",
  ]);
});

test("keeps the new turn in place when the history page resolves after submit", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  let resolveHistory: ((response: Response) => void) | undefined;
  rs.stubGlobal(
    "fetch",
    () =>
      new Promise<Response>((resolve) => {
        resolveHistory = resolve;
      }),
  );
  streamMockState.messages = checkpointMessages();
  const { useThreadStream } = await import("@/core/threads/hooks");
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const { rerender, result } = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        isMock: false,
        threadId: "thread-1",
      }),
    { wrapper: createWrapper(queryClient) },
  );
  await flushFrames();

  // History is still loading: only the checkpoint tail is visible.
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "recent-human",
    "recent-answer",
  ]);

  const submittedId = await submitVisibleTurn(result);
  const newStep = aiMessage("new-step", "Working on the follow-up", {
    run_id: "run-new",
  });
  streamMockState.messages = [RECENT_HUMAN, RECENT_ANSWER, newStep];
  streamMockState.isLoading = true;
  rerender();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "recent-human",
    "recent-answer",
    submittedId,
    "new-step",
  ]);

  // The page resolves mid-turn: older turns slot in ahead of the established
  // anchor without disturbing the in-flight turn.
  await act(async () => {
    resolveHistory?.(historyPageResponse(seededHistoryRows()));
  });
  await flushFrames();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    submittedId,
    "new-step",
  ]);
});

test("clears the local turn anchor when switching threads before the pending flush", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  const thread2Human = humanMessage("t2-human", "Another thread request");
  const thread2Answer = aiMessage("t2-answer", "Another thread answer");
  streamMockState.messages = checkpointMessages();
  const { rerender, result } = await renderSeededThread({
    historyRows: () => seededHistoryRows(),
  });

  const submittedId = await submitVisibleTurn(result);
  const newStep = aiMessage("new-step", "Working on the follow-up", {
    run_id: "run-new",
  });
  streamMockState.messages = [RECENT_HUMAN, RECENT_ANSWER, newStep];
  streamMockState.isLoading = true;
  rerender();
  expect(visibleMessageIds(result.current.thread.messages)).toContain(
    submittedId,
  );

  // Switch threads while a trailing coalesce flush is still pending. The
  // other thread's view must not inherit this turn's anchor or messages.
  stubHistoryFetch({
    "thread-1": () => seededHistoryRows(),
    "thread-2": () => [
      historyRow(1, "run-t2", thread2Human),
      historyRow(2, "run-t2", thread2Answer),
    ],
  });
  streamMockState.messages = [thread2Human, thread2Answer];
  streamMockState.isLoading = false;
  rerender({ currentThreadId: "thread-2" });
  await flushFrames();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "t2-human",
    "t2-answer",
  ]);

  // The pending timer from the previous thread's stream must not repaint its
  // messages into this view either.
  await act(async () => {
    await rs.advanceTimersByTimeAsync(200);
  });
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "t2-human",
    "t2-answer",
  ]);
});

test("releases the in-flight turn state when the submit fails", async () => {
  const rows = seededHistoryRows();
  streamMockState.messages = checkpointMessages();
  const { rerender, result } = await renderSeededThread({
    historyRows: () => rows,
  });

  streamMockState.submit.mockRejectedValueOnce(new Error("network down"));
  await act(async () => {
    await result.current
      .sendMessage("thread-1", { files: [], text: "This send fails" })
      .catch(() => undefined);
  });

  // The failed input is withdrawn and must not linger through any ledger.
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
  ]);

  // The in-flight guard is released: the next send proceeds and anchors on
  // its own fresh identity, never on the failed one.
  const nextId = await submitVisibleTurn(result, "Retry the request");
  const newStep = aiMessage("new-step", "Working on the retry", {
    run_id: "run-retry",
  });
  streamMockState.messages = [RECENT_HUMAN, RECENT_ANSWER, newStep];
  streamMockState.isLoading = true;
  rerender();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    nextId,
    "new-step",
  ]);
});

test("anchors an edit-regenerate replay on the replacement human identity", async () => {
  const threadHuman = humanMessage("srv-h1", "Original question");
  const threadAnswer = aiMessage("srv-a1", "Original answer");
  const rows = [
    historyRow(1, "run-1", threadHuman),
    historyRow(2, "run-1", threadAnswer),
  ];
  streamMockState.messages = [threadHuman, threadAnswer];

  const replacementHuman = humanMessage("repl-h1", "Edited question");
  rs.stubGlobal("fetch", async (input: unknown, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/runs/edit-regenerate/prepare")) {
      return new Response(
        JSON.stringify({
          input: { messages: [replacementHuman] },
          checkpoint: {
            checkpoint_ns: "",
            checkpoint_id: "cp-1",
            checkpoint_map: null,
          },
          metadata: {},
          target_run_id: "run-1",
          replacement_human_message_id: "repl-h1",
          source_message_ids: ["srv-h1", "srv-a1"],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.includes("/messages/page")) {
      return historyPageResponse(rows);
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });

  const { useThreadStream } = await import("@/core/threads/hooks");
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const { rerender, result } = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        isMock: false,
        threadId: "thread-1",
      }),
    { wrapper: createWrapper(queryClient) },
  );
  await flushFrames();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "srv-h1",
    "srv-a1",
  ]);

  await act(async () => {
    await result.current.editAndRegenerateMessage(
      "thread-1",
      "srv-h1",
      "Edited question",
    );
  });

  // The superseded turn is masked; the replacement human from the prepare
  // response is shown optimistically with its server-assigned identity.
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "repl-h1",
  ]);

  // The replay's first step arrives before the replacement human echo: the
  // replay anchors on the prepare identity, not on any older human.
  const replayStep = aiMessage("repl-step", "Recomputing the answer", {
    run_id: "run-2",
  });
  streamMockState.messages = [replayStep];
  streamMockState.isLoading = true;
  rerender();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "repl-h1",
    "repl-step",
  ]);

  // Once the server copy lands, the same identity is shown exactly once and
  // the optimistic copy is withdrawn.
  const serverReplacement = {
    id: "repl-h1__user",
    type: "human",
    content: "Edited question",
    run_id: "run-2",
  } as Message;
  streamMockState.messages = [replayStep, serverReplacement];
  streamMockState.isLoading = false;
  rerender();
  await flushFrames();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "repl-h1__user",
    "repl-step",
  ]);
});

test("drops the local turn anchor after a stream replay gap", async () => {
  const rows = seededHistoryRows();
  streamMockState.messages = checkpointMessages();
  const { rerender, result } = await renderSeededThread({
    historyRows: () => rows,
  });

  const submittedId = await submitVisibleTurn(result);
  expect(visibleMessageIds(result.current.thread.messages)).toContain(
    submittedId,
  );

  // A replay gap invalidates every locally kept ordering assumption.
  act(() => {
    streamMockState.onCustomEvent?.({ type: "stream_replay_gap" });
  });
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
  ]);

  // Afterwards, reconnection semantics apply: an arriving step with no local
  // anchor left must not reorder the established history.
  const newStep = aiMessage("new-step", "Working on the follow-up", {
    run_id: "run-new",
  });
  streamMockState.messages = [RECENT_HUMAN, RECENT_ANSWER, newStep];
  streamMockState.isLoading = true;
  rerender();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    "new-step",
  ]);
});

test("keeps the submitted turn anchored through stop and the final history refresh", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  let rows = seededHistoryRows();
  streamMockState.messages = checkpointMessages();
  const { rerender, result } = await renderSeededThread({
    historyRows: () => rows,
  });

  const submittedId = await submitVisibleTurn(result);
  const newStep = aiMessage("new-step", "Working on the follow-up", {
    run_id: "run-new",
  });
  const serverHuman = {
    id: `${submittedId}__user`,
    type: "human",
    content: "Continue the work",
    run_id: "run-new",
  } as Message;
  streamMockState.messages = [
    RECENT_HUMAN,
    RECENT_ANSWER,
    newStep,
    serverHuman,
  ];
  streamMockState.isLoading = true;
  rerender();
  await act(async () => {
    await rs.advanceTimersByTimeAsync(100);
  });
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    `${submittedId}__user`,
    "new-step",
  ]);

  // Stop flushes the turn into canonical history; the refresh must converge
  // to the same order the stream already showed.
  rows = [
    ...seededHistoryRows(),
    historyRow(5, "run-new", serverHuman),
    historyRow(6, "run-new", newStep),
  ];
  await act(async () => {
    await result.current.thread.stop();
    streamMockState.isLoading = false;
  });
  rerender();
  await flushFrames();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    `${submittedId}__user`,
    "new-step",
  ]);

  // The delayed finalization refetch changes nothing.
  await act(async () => {
    await rs.advanceTimersByTimeAsync(1600);
  });
  await flushFrames();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    `${submittedId}__user`,
    "new-step",
  ]);
});

test("keeps history stable when the stream errors after the human was confirmed", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  let rows = seededHistoryRows();
  streamMockState.messages = checkpointMessages();
  const { rerender, result } = await renderSeededThread({
    historyRows: () => rows,
  });

  const submittedId = await submitVisibleTurn(result);
  const newStep = aiMessage("new-step", "Working on the follow-up", {
    run_id: "run-new",
  });
  const serverHuman = {
    id: `${submittedId}__user`,
    type: "human",
    content: "Continue the work",
    run_id: "run-new",
  } as Message;
  streamMockState.messages = [
    RECENT_HUMAN,
    RECENT_ANSWER,
    newStep,
    serverHuman,
  ];
  streamMockState.isLoading = true;
  rerender();
  await act(async () => {
    await rs.advanceTimersByTimeAsync(100);
  });
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    `${submittedId}__user`,
    "new-step",
  ]);

  // The stream errors; the error path invalidates history and the refreshed
  // canonical page keeps the turn exactly where the user saw it.
  rows = [
    ...seededHistoryRows(),
    historyRow(5, "run-new", serverHuman),
    historyRow(6, "run-new", newStep),
  ];
  await act(async () => {
    streamMockState.onError?.(new Error("stream broke"));
    streamMockState.isLoading = false;
  });
  rerender();
  await flushFrames();
  expect(visibleMessageIds(result.current.thread.messages)).toEqual([
    "earlier-answer",
    "old-human",
    "recent-human",
    "recent-answer",
    `${submittedId}__user`,
    "new-step",
  ]);
});

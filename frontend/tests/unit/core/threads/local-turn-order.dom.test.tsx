import type { Message } from "@langchain/langgraph-sdk";
import { expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";

const streamMockState = rs.hoisted(() => ({
  isLoading: false,
  messages: [] as Message[],
  onFinish: undefined as
    | ((state: { values: { messages: Message[] } }) => void)
    | undefined,
  stop: rs.fn(async () => undefined),
  submit: rs.fn(async () => undefined),
}));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: {
    onFinish?: (state: { values: { messages: Message[] } }) => void;
  }) => {
    streamMockState.onFinish = options.onFinish;
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

test("keeps early streamed steps behind a local user message after finish", async () => {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(
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
  const { rerender, result } = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        isMock: true,
        threadId: "thread-1",
      }),
    { wrapper },
  );

  await act(async () => {
    await result.current.sendMessage("thread-1", {
      files: [],
      text: "Build a presentation",
    });
  });

  const earlyAssistantStep = {
    id: "early-assistant-step",
    type: "ai",
    content: "Reading the presentation skill",
  } as Message;
  const injectedHuman = {
    id: "current-request__user",
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

test("anchors a compacted local turn to the latest non-baseline human", async () => {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const oldHistoryHuman = {
    id: "old-history-human",
    type: "human",
    content: "An earlier request omitted by the checkpoint",
  } as Message;
  const oldHistoryAnswer = {
    id: "old-history-answer",
    type: "ai",
    content: "An earlier answer",
  } as Message;
  const previousHuman = {
    id: "previous-human",
    type: "human",
    content: "The immediately previous request",
  } as Message;
  const previousAnswer = {
    id: "previous-answer",
    type: "ai",
    content: "The immediately previous answer",
  } as Message;
  const currentHuman = {
    id: "current-human",
    type: "human",
    content: "The newly submitted request",
  } as Message;
  const currentStep = {
    id: "current-step",
    type: "ai",
    content: "Current streamed progress",
  } as Message;

  rs.stubGlobal(
    "fetch",
    rs.fn(async () =>
      Response.json({
        data: [
          {
            run_id: "run-old",
            seq: 1,
            content: oldHistoryHuman,
          },
          {
            run_id: "run-old",
            seq: 2,
            content: oldHistoryAnswer,
          },
          {
            run_id: "run-previous",
            seq: 3,
            content: previousHuman,
          },
          {
            run_id: "run-previous",
            seq: 4,
            content: previousAnswer,
          },
        ],
        has_more: false,
        next_before_seq: null,
      }),
    ),
  );

  streamMockState.isLoading = false;
  streamMockState.messages = [previousHuman, previousAnswer];
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(
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
  const { rerender, result } = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        isMock: false,
        threadId: "thread-compacted",
      }),
    { wrapper },
  );

  await waitFor(() =>
    expect(result.current.thread.messages.map((message) => message.id)).toEqual(
      [
        "old-history-human",
        "old-history-answer",
        "previous-human",
        "previous-answer",
      ],
    ),
  );

  await act(async () => {
    await result.current.sendMessage("thread-compacted", {
      files: [],
      text: "The newly submitted request",
    });
  });

  streamMockState.messages = [
    previousHuman,
    previousAnswer,
    currentHuman,
    currentStep,
  ];
  rerender();

  expect(result.current.thread.messages.map((message) => message.id)).toEqual([
    "old-history-human",
    "old-history-answer",
    "previous-human",
    "previous-answer",
    "current-human",
    "current-step",
  ]);
});

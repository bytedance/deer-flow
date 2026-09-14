import type { Message } from "@langchain/langgraph-sdk";
import { expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import type { AgentThreadState, GoalState } from "@/core/threads/types";

type StreamOptions = {
  onUpdateEvent?: (
    data: unknown,
    options: {
      mutate: (
        update:
          | Partial<AgentThreadState>
          | ((previous: AgentThreadState) => Partial<AgentThreadState>),
      ) => void;
    },
  ) => void;
};

const streamMockState = rs.hoisted(() => {
  const existingMessage = {
    type: "ai",
    id: "message-1",
    content: "Already streamed",
  } as Message;
  return {
    existingMessage,
    options: undefined as StreamOptions | undefined,
    values: {
      title: "Before",
      messages: [existingMessage],
      artifacts: ["old.md"],
      todos: [{ content: "old", status: "pending" as const }],
      goal: null,
    } as AgentThreadState,
  };
});

const existingMessage = streamMockState.existingMessage;

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: StreamOptions) => {
    streamMockState.options = options;
    return {
      isLoading: true,
      messages: streamMockState.values.messages,
      stop: async () => undefined,
      submit: async () => undefined,
      values: streamMockState.values,
    };
  },
}));

test("updates rendered thread state without receiving a values frame", async () => {
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

  const goal = {
    objective: "Finish the report",
    status: "active",
    created_at: "2026-09-02T00:00:00Z",
    updated_at: "2026-09-02T00:01:00Z",
    continuation_count: 1,
    max_continuations: 8,
    no_progress_count: 0,
  } as GoalState;
  const todos = [{ content: "Draft", status: "in_progress" as const }];

  act(() => {
    streamMockState.options?.onUpdateEvent?.(
      { agent: { messages: [existingMessage], summary_text: "internal" } },
      {
        mutate() {
          throw new Error("irrelevant updates must not mutate thread values");
        },
      },
    );
  });

  act(() => {
    streamMockState.options?.onUpdateEvent?.(
      {
        agent: {
          artifacts: ["report.md"],
          goal,
          // The same message also arrives through messages-tuple. The update
          // path must not apply it a second time.
          messages: [existingMessage],
          title: "After",
          todos,
        },
      },
      {
        mutate(update) {
          const patch =
            typeof update === "function"
              ? update(streamMockState.values)
              : update;
          streamMockState.values = { ...streamMockState.values, ...patch };
        },
      },
    );
    rerender();
  });

  expect(result.current.thread.values).toMatchObject({
    artifacts: ["old.md", "report.md"],
    goal,
    title: "After",
    todos,
  });
  expect(result.current.thread.messages).toEqual([existingMessage]);
});

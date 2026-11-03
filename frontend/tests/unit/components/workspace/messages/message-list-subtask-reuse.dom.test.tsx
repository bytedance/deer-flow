import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, expect, it, rs } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";
import type { ReactNode } from "react";

import { MessageList } from "@/components/workspace/messages/message-list";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import type { MessageGroup } from "@/core/messages/utils";
import type { Subtask } from "@/core/tasks/types";

const renderedCards = rs.hoisted(() => ({
  current: [] as Array<{ taskId: string; live?: boolean; task: Subtask }>,
}));

rs.mock("@/components/workspace/messages/subtask-card", () => ({
  SubtaskCard: ({
    taskId,
    live,
    fallbackTask,
  }: {
    taskId: string;
    live?: boolean;
    fallbackTask: Subtask;
  }) => {
    renderedCards.current.push({ taskId, live, task: fallbackTask });
    return <div data-testid="subtask-card">{fallbackTask.description}</div>;
  },
}));
rs.mock("@/components/workspace/messages/message-group", () => ({
  MessageGroup: () => null,
  getMessageGroupReasoningMessage: () => undefined,
}));
rs.mock("@/components/ai-elements/conversation", () => ({
  Conversation: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  ConversationContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
rs.mock("@/components/workspace/messages/virtual-message-list", () => ({
  VirtualMessageList: ({
    groups,
    renderGroup,
  }: {
    groups: MessageGroup[];
    renderGroup: (group: MessageGroup, index: number) => ReactNode;
  }) => (
    <div>
      {groups.map((group, index) => (
        <div key={group.id}>{renderGroup(group, index)}</div>
      ))}
    </div>
  ),
}));
rs.mock("@/components/workspace/messages/message-list-item", () => ({
  MessageListItem: () => null,
}));

afterEach(() => {
  cleanup();
  renderedCards.current = [];
});

function turn(id: string, description: string, result: string): Message[] {
  return [
    { type: "human", id: `${id}-human`, content: description },
    {
      type: "ai",
      id: `${id}-ai`,
      content: "",
      tool_calls: [
        {
          id: "call_0",
          name: "task",
          args: {
            subagent_type: "researcher",
            description,
            prompt: description,
          },
        },
      ],
    } as unknown as Message,
    {
      type: "tool",
      id: `${id}-tool`,
      name: "task",
      tool_call_id: "call_0",
      content: result,
      additional_kwargs: {
        subagent_status: "completed",
        subagent_result_brief: result,
      },
    } as Message,
  ];
}

function view(messages: Message[]) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <MessageList
        threadId="reused-task-id"
        thread={
          {
            messages,
            isLoading: false,
            isThreadLoading: false,
            values: {},
            getMessagesMetadata: () => undefined,
          } as unknown as React.ComponentProps<typeof MessageList>["thread"]
        }
      />
    </I18nContext.Provider>
  );
}

it("renders each turn's own subtask card when a provider reuses one tool_call_id", () => {
  render(
    view([
      ...turn("first", "First task", "first result"),
      ...turn("second", "Second task", "second result"),
    ]),
  );

  const cards = renderedCards.current.slice(-2);
  expect(cards.map((card) => card.taskId)).toEqual(["call_0", "call_0"]);
  expect(cards.map((card) => card.task.description)).toEqual([
    "First task",
    "Second task",
  ]);
});

it("lets only the latest turn's card read the shared live subtask state", () => {
  render(
    view([
      ...turn("first", "First task", "first result"),
      ...turn("second", "Second task", "second result"),
    ]),
  );

  const cards = renderedCards.current.slice(-2);
  expect(cards.map((card) => card.live)).toEqual([false, true]);
});

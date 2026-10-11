import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, expect, it, rs } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";
import type { ReactNode } from "react";

import { MessageList } from "@/components/workspace/messages/message-list";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import type { MessageGroup } from "@/core/messages/utils";

const selectReasoning = rs.hoisted(() =>
  rs.fn((messages: Message[]) =>
    messages.find((message) => message.additional_kwargs?.reasoning_content),
  ),
);

rs.mock("@/components/workspace/messages/message-group", () => ({
  MessageGroup: () => null,
  getMessageGroupReasoningMessage: selectReasoning,
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
rs.mock("@/components/workspace/messages/subtask-card", () => ({
  SubtaskCard: () => null,
}));

afterEach(() => {
  cleanup();
  selectReasoning.mockClear();
});

function reasoningMessage(kind: "processing" | "subagent", duration?: number) {
  return {
    id: "reasoning",
    run_id: "historical-run",
    type: "ai",
    content: "",
    additional_kwargs: {
      reasoning_content: "Consider the question.",
      ...(duration === undefined ? {} : { turn_duration: duration }),
    },
    ...(kind === "subagent"
      ? {
          tool_calls: [
            {
              id: "task",
              name: "task",
              args: { prompt: "Research", subagent_type: "general-purpose" },
            },
          ],
        }
      : {}),
  } satisfies Message & { run_id: string };
}

const getMessagesMetadata = () => undefined;
function view(messages: Message[], isLoading: boolean, revision = 0) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <MessageList
        className={`revision-${revision}`}
        threadId="reasoning-cache"
        thread={
          {
            messages,
            isLoading,
            isThreadLoading: false,
            values: {},
            getMessagesMetadata,
          } as unknown as React.ComponentProps<typeof MessageList>["thread"]
        }
      />
    </I18nContext.Provider>
  );
}

for (const kind of ["processing", "subagent"] as const) {
  for (const isLoading of [true, false]) {
    it(`skips unused ${kind} targets: loading=${isLoading}`, () => {
      render(view([reasoningMessage(kind)], isLoading));
      expect(selectReasoning).not.toHaveBeenCalled();
    });
  }

  it(`reuses ${kind} targets and invalidates changed messages`, () => {
    const message = reasoningMessage(kind, 31);
    const messages = [message];
    const { rerender } = render(view(messages, false));
    expect(selectReasoning).toHaveBeenCalledTimes(1);
    for (let revision = 1; revision <= 5; revision++) {
      rerender(view(messages, false, revision));
    }
    expect(selectReasoning).toHaveBeenCalledTimes(1);
    const changed = {
      ...message,
      additional_kwargs: {
        ...message.additional_kwargs,
        reasoning_content: "Updated reasoning.",
      },
    };
    rerender(view([changed], false));
    expect(selectReasoning).toHaveBeenCalledTimes(2);
    expect(selectReasoning.mock.calls.at(-1)?.[0][0]).toBe(changed);
  });
}

it("reuses historical targets across actual streaming message updates", () => {
  const history: Message[] = [
    { id: "old-human", type: "human", content: "Previous question" },
    reasoningMessage("processing", 31),
    { id: "new-human", type: "human", content: "Next question" },
  ];
  const live = (chunk: number): Message => ({
    id: "live-reasoning",
    type: "ai",
    content: "",
    additional_kwargs: { reasoning_content: `Live reasoning ${chunk}` },
  });
  const { rerender } = render(view([...history, live(0)], true));
  expect(selectReasoning).toHaveBeenCalledTimes(1);
  for (let chunk = 1; chunk <= 5; chunk++) {
    rerender(view([...history, live(chunk)], true));
  }
  expect(selectReasoning).toHaveBeenCalledTimes(1);
});

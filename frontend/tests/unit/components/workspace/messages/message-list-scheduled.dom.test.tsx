import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { MessageList } from "@/components/workspace/messages/message-list";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import type { MessageGroup } from "@/core/messages/utils";

import {
  loadScheduledThread,
  withOrdinaryHumanTurn,
} from "../../../helpers/scheduled-fixtures";

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
        <div key={`${group.type}:${group.id}`}>{renderGroup(group, index)}</div>
      ))}
    </div>
  ),
}));
rs.mock("@/components/workspace/messages/message-list-item", () => ({
  MessageListItem: ({
    message,
    canEdit,
  }: {
    message: Message;
    canEdit?: boolean;
  }) => (
    <div
      data-testid={`item-${message.type}`}
      data-can-edit={canEdit ? "true" : "false"}
    />
  ),
}));
rs.mock("@/components/workspace/messages/subtask-card", () => ({
  SubtaskCard: () => null,
}));
rs.mock("@/components/workspace/messages/scheduled-task-card", () => ({
  ScheduledTaskCard: ({ result }: { result: { task: { id: string } } }) => (
    <div data-testid="card" data-task-id={result.task.id} />
  ),
  taskPagePath: (id: string) => `/workspace/scheduled-tasks?task_id=${id}`,
}));
rs.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

afterEach(cleanup);

const getMessagesMetadata = () => undefined;

function view(messages: Message[], isLoading: boolean) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <MessageList
        threadId="scheduled-run"
        canEdit
        onEditAndRegenerateMessage={async () => true}
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

/** The recorded run thread with a persisted duration on its final answer. */
function runThread(): Message[] {
  return loadScheduledThread("en-3-run-thread").messages.map((message) =>
    message.id === "ai-final"
      ? ({
          ...message,
          additional_kwargs: { turn_duration: 11 },
        } as Message)
      : message,
  );
}

function snapshot(messages: Message[], isLoading: boolean) {
  const { unmount } = render(view(messages, isLoading));
  const result = {
    durations: screen.queryAllByTestId("run-duration").length,
    activity: screen.queryAllByTestId("run-activity").length,
    assistantItems: screen.queryAllByTestId("item-ai").length,
  };
  unmount();
  return result;
}

describe("MessageList with scheduled runs", () => {
  it("renders the run block instead of the launched prompt, without edit", () => {
    render(view(runThread(), false));
    expect(screen.getByTestId("scheduled-run-prompt")).toBeTruthy();
    expect(screen.queryByTestId("item-human")).toBeNull();
    expect(document.body.textContent).not.toContain("Stop rule from the user");
  });

  it("an ordinary twin of the same turn stays editable", () => {
    render(view(withOrdinaryHumanTurn(runThread()), false));
    expect(screen.getByTestId("item-human").getAttribute("data-can-edit")).toBe(
      "true",
    );
  });

  it("turn duration and the active-answer indicator match an ordinary turn", () => {
    const scheduled = runThread();
    const ordinary = withOrdinaryHumanTurn(scheduled);
    expect(snapshot(scheduled, false)).toEqual(snapshot(ordinary, false));
    expect(snapshot(scheduled, false).durations).toBe(1);
    const beforeAnswer = (messages: Message[]) => messages.slice(0, -1);
    expect(snapshot(beforeAnswer(scheduled), true)).toEqual(
      snapshot(beforeAnswer(ordinary), true),
    );
    expect(snapshot(beforeAnswer(scheduled), true).activity).toBe(1);
    expect(snapshot(scheduled, true)).toEqual(snapshot(ordinary, true));
  });

  it("renders one card per schedule result and keeps the replies", () => {
    render(view(loadScheduledThread("en-3-chat-thread").messages, false));
    expect(screen.getAllByTestId("card")).toHaveLength(2);
    expect(screen.getAllByTestId("item-ai")).toHaveLength(2);
  });
});

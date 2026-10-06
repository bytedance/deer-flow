import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { MessageList } from "@/components/workspace/messages/message-list";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import type { MessageGroup } from "@/core/messages/utils";
import type { ScheduledTaskEvent } from "@/core/scheduled-tasks/events";

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
    renderAfterGroup,
  }: {
    groups: MessageGroup[];
    renderGroup: (group: MessageGroup, index: number) => ReactNode;
    renderAfterGroup?: (index: number) => ReactNode;
  }) => (
    <div>
      {groups.map((group, index) => (
        <div key={`${group.type}:${group.id}`}>
          {renderGroup(group, index)}
          {renderAfterGroup?.(index)}
        </div>
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

function view(
  messages: Message[],
  isLoading: boolean,
  scheduledTaskEvents?: ScheduledTaskEvent[],
) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <MessageList
        threadId="scheduled-run"
        scheduledTaskEvents={scheduledTaskEvents}
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

/** The recorded origin chat with one run per turn: create, then trial. */
function chatThreadWithRuns(): Message[] {
  const messages = loadScheduledThread("en-3-chat-thread").messages;
  const trialStart = messages.findIndex(
    (message, index) => index > 0 && message.type === "human",
  );
  return messages.map(
    (message, index) =>
      ({
        ...message,
        run_id: index < trialStart ? "run-create" : "run-trial",
      }) as unknown as Message,
  );
}

function taskEvent(
  id: string,
  overrides: Partial<ScheduledTaskEvent> = {},
): ScheduledTaskEvent {
  return {
    id,
    task_id: "task-2b559ac2af344c3f9e55b90391f7fb1a",
    event: "task_stopped",
    reason_code: "agent_stop",
    task_title: "Release checklist status watcher",
    stop_condition: null,
    run_thread_id: "83d5133d-f8aa-4095-9bba-2aca03f8f61c",
    run_number: 2,
    run_status: "success",
    max_runs: null,
    end_at: null,
    schedule_type: "cron",
    after_run_id: "run-trial",
    created_at: "2026-10-05T12:22:00+00:00",
    ...overrides,
  };
}

const follows = (a: Element, b: Element) =>
  Boolean(b.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("MessageList with schedule event lines", () => {
  it("puts a line at the end of its run's turn, before the next question", () => {
    render(
      view(chatThreadWithRuns(), false, [
        taskEvent("evt-a", { after_run_id: "run-create" }),
      ]),
    );
    const line = screen.getByTestId("scheduled-task-event-line");
    const [firstCard, secondCard] = screen.getAllByTestId("card");
    const humans = screen.getAllByTestId("item-human");
    expect(follows(line, firstCard!)).toBe(true);
    expect(follows(humans[1]!, line)).toBe(true);
    expect(follows(secondCard!, line)).toBe(true);
  });

  it("falls back to the tail when no message carries the anchor run", () => {
    render(
      view(chatThreadWithRuns(), false, [
        taskEvent("evt-a", { after_run_id: "run-from-a-pruned-branch" }),
      ]),
    );
    const line = screen.getByTestId("scheduled-task-event-line");
    for (const item of [
      ...screen.getAllByTestId("item-ai"),
      ...screen.getAllByTestId("card"),
    ]) {
      expect(follows(line, item)).toBe(true);
    }
  });

  it("keeps lines of one anchor in created order", () => {
    render(
      view(chatThreadWithRuns(), false, [
        taskEvent("evt-later", {
          event: "task_finished",
          reason_code: "end_at",
          created_at: "2026-10-05T12:30:00+00:00",
        }),
        taskEvent("evt-earlier"),
      ]),
    );
    expect(
      screen
        .getAllByTestId("scheduled-task-event-line")
        .map((line) => line.getAttribute("data-event-id")),
    ).toEqual(["evt-earlier", "evt-later"]);
  });

  it("renders no line without events", () => {
    render(view(chatThreadWithRuns(), false, []));
    expect(screen.queryByTestId("scheduled-task-event-line")).toBeNull();
  });
});

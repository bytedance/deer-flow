import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { MessageList } from "@/components/workspace/messages/message-list";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { getMessageRunId } from "@/core/messages/run-duration";
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

/** The live-recorded run thread; its final answer carries the run's recorded duration. */
function runThread(): Message[] {
  return loadScheduledThread("minute-run").messages;
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
    // Live: create, trial, edit, pause and resume, each with its reply.
    render(view(loadScheduledThread("weekday-chat").messages, false));
    expect(screen.getAllByTestId("card")).toHaveLength(5);
    expect(screen.getAllByTestId("item-ai")).toHaveLength(5);
  });
});

/**
 * The live origin chat (create, trial, edit, pause, resume); every message
 * carries the run id it was recorded with, one run per turn.
 */
function chatThreadWithRuns(): Message[] {
  return loadScheduledThread("weekday-chat").messages;
}

/** The recorded run id of the chat's n-th turn (0 = create, 1 = trial). */
function turnRunId(turn: number): string {
  const human = chatThreadWithRuns().filter(
    (message) => message.type === "human",
  )[turn];
  const runId = human ? getMessageRunId(human) : undefined;
  if (!runId) {
    throw new Error(`weekday-chat turn ${turn} has no run id`);
  }
  return runId;
}

function taskEvent(
  id: string,
  overrides: Partial<ScheduledTaskEvent> = {},
): ScheduledTaskEvent {
  return {
    id,
    task_id: "task-f3a00a4dd1574021b6cacfa875fd1bdd",
    event: "task_stopped",
    reason_code: "agent_stop",
    task_title: "工作日发布清单未完成项提醒",
    stop_condition: null,
    run_thread_id: "e0a4c9eb-80aa-44b1-b4f1-d8e44df07749",
    run_number: 2,
    run_status: "success",
    max_runs: null,
    end_at: null,
    schedule_type: "cron",
    after_run_id: turnRunId(1),
    created_at: "2026-10-06T08:53:00+00:00",
    ...overrides,
  };
}

const follows = (a: Element, b: Element) =>
  Boolean(b.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("MessageList with schedule event lines", () => {
  it("puts a line at the end of its run's turn, before the next question", () => {
    render(
      view(chatThreadWithRuns(), false, [
        taskEvent("evt-a", { after_run_id: turnRunId(0) }),
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
          created_at: "2026-10-06T09:00:00+00:00",
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

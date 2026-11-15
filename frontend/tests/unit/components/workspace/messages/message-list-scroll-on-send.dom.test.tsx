import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";
import {
  forwardRef,
  StrictMode,
  useImperativeHandle,
  type ReactNode,
} from "react";

import { MessageList } from "@/components/workspace/messages/message-list";
import type { VirtualMessageListHandle } from "@/components/workspace/messages/virtual-message-list";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import type { MessageGroup } from "@/core/messages/utils";

const mocks = rs.hoisted(() => ({
  pinnedGroups: [] as (string | null)[],
}));

rs.mock("@/components/workspace/messages/message-group", () => ({
  MessageGroup: () => null,
  getMessageGroupReasoningMessage: () => undefined,
}));
rs.mock("@/components/ai-elements/conversation", () => ({
  ConversationScrollButton: () => null,
  Conversation: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  ConversationContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
rs.mock("@/components/workspace/messages/virtual-message-list", () => ({
  VirtualMessageList: forwardRef<
    VirtualMessageListHandle,
    {
      groups: MessageGroup[];
      pinGroupKey?: string | null;
      renderGroup: (group: MessageGroup, index: number) => ReactNode;
      renderAfterGroup?: (index: number) => ReactNode;
    }
  >(function VirtualMessageListMock({ groups, pinGroupKey, renderGroup }, ref) {
    mocks.pinnedGroups.push(pinGroupKey ?? null);
    useImperativeHandle(ref, () => ({
      scrollToGroup: () => undefined,
      cancelPinFollow: () => undefined,
    }));
    return (
      <div>
        {groups.map((group, index) => (
          <div key={`${group.type}:${group.id}`}>
            {renderGroup(group, index)}
          </div>
        ))}
      </div>
    );
  }),
}));
rs.mock("@/components/workspace/messages/message-list-item", () => ({
  MessageListItem: ({ message }: { message: Message }) => (
    <div data-testid={`item-${message.type}`} />
  ),
}));
rs.mock("@/components/workspace/messages/subtask-card", () => ({
  SubtaskCard: () => null,
}));
rs.mock("@/components/workspace/messages/scheduled-task-card", () => ({
  ScheduledTaskCard: () => null,
  taskPagePath: (id: string) => `/workspace/scheduled-tasks?task_id=${id}`,
}));
rs.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

afterEach(() => {
  cleanup();
  mocks.pinnedGroups = [];
});

const HUMAN_1 = { id: "human-1", type: "human", content: "First question" };
const AI_1 = { id: "ai-1", type: "ai", content: "First answer" };
const HUMAN_2 = {
  id: "local-human-2",
  type: "human",
  content: "Second question",
};

function view({
  threadId,
  messages,
  isLoading,
}: {
  threadId: string;
  messages: Message[];
  isLoading: boolean;
}) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <MessageList
        threadId={threadId}
        thread={
          {
            messages,
            isLoading,
            isThreadLoading: false,
            values: {},
            getMessagesMetadata: () => undefined,
          } as unknown as React.ComponentProps<typeof MessageList>["thread"]
        }
      />
    </I18nContext.Provider>
  );
}

function lastPinnedGroup(): string | null {
  return mocks.pinnedGroups.at(-1) ?? null;
}

function idle(threadId = "thread-1") {
  return view({
    threadId,
    messages: [HUMAN_1, AI_1] as Message[],
    isLoading: false,
  });
}

describe("MessageList scroll-on-send", () => {
  it("pins a newly sent user turn to the top of the viewport", () => {
    const { rerender } = render(idle());
    expect(lastPinnedGroup()).toBeNull();

    // The send: an optimistic human message lands while the run starts.
    rerender(
      view({
        threadId: "thread-1",
        messages: [HUMAN_1, AI_1, HUMAN_2] as Message[],
        isLoading: true,
      }),
    );

    expect(lastPinnedGroup()).toBe("local-human-2");
  });

  it("re-pins on a second send while the first run is still active", () => {
    const { rerender } = render(idle());
    rerender(
      view({
        threadId: "thread-1",
        messages: [HUMAN_1, AI_1, HUMAN_2] as Message[],
        isLoading: true,
      }),
    );
    expect(lastPinnedGroup()).toBe("local-human-2");

    // A queued second send appends another optimistic human turn; the pin
    // moves to the newest one.
    const HUMAN_3 = {
      id: "local-human-3",
      type: "human",
      content: "Third question",
    };
    rerender(
      view({
        threadId: "thread-1",
        messages: [HUMAN_1, AI_1, HUMAN_2, HUMAN_3] as Message[],
        isLoading: true,
      }),
    );

    expect(lastPinnedGroup()).toBe("local-human-3");
  });

  it("keeps pinning the same turn while its reply streams in", () => {
    const { rerender } = render(idle());
    rerender(
      view({
        threadId: "thread-1",
        messages: [HUMAN_1, AI_1, HUMAN_2] as Message[],
        isLoading: true,
      }),
    );
    expect(lastPinnedGroup()).toBe("local-human-2");

    // Streaming chunks grow the reply without adding a human group.
    rerender(
      view({
        threadId: "thread-1",
        messages: [
          HUMAN_1,
          AI_1,
          HUMAN_2,
          { id: "ai-2", type: "ai", content: "answer" },
        ] as Message[],
        isLoading: true,
      }),
    );

    expect(lastPinnedGroup()).toBe("local-human-2");
  });

  it("does not pin when a run starts without a new user turn", () => {
    const { rerender } = render(idle());

    // A regenerate: the run restarts on the existing turn.
    rerender(
      view({
        threadId: "thread-1",
        messages: [HUMAN_1, AI_1] as Message[],
        isLoading: true,
      }),
    );

    expect(lastPinnedGroup()).toBeNull();
  });

  it("does not pin when a regenerate masks the superseded assistant turn", () => {
    const { rerender } = render(idle());

    // The real regenerate flow removes the superseded assistant messages
    // before the replay starts, so an EXISTING human turn becomes the last
    // group mid-run. Nothing was appended; there must be no pin.
    rerender(
      view({
        threadId: "thread-1",
        messages: [HUMAN_1] as Message[],
        isLoading: true,
      }),
    );

    expect(lastPinnedGroup()).toBeNull();
  });

  it("does not pin when loading older history prepends messages", () => {
    const { rerender } = render(idle());

    // History pagination prepends an older page; the last group is unchanged.
    rerender(
      view({
        threadId: "thread-1",
        messages: [
          { id: "human-0", type: "human", content: "Older question" },
          HUMAN_1,
          AI_1,
        ] as Message[],
        isLoading: false,
      }),
    );

    expect(lastPinnedGroup()).toBeNull();
  });

  it("does not pin when mounting mid-run with a trailing human group", () => {
    // Restoring a thread (or opening a sidecar chat) whose run is already in
    // flight: the trailing human turn is not a fresh send.
    render(
      view({
        threadId: "thread-1",
        messages: [HUMAN_1, AI_1, HUMAN_2] as Message[],
        isLoading: true,
      }),
    );

    expect(lastPinnedGroup()).toBeNull();
  });

  it("does not pin when StrictMode double-runs the mount with a mid-run thread", () => {
    // React StrictMode (the App Router dev default) runs effects
    // mount → cleanup → mount with refs preserved. The mount absorption must
    // survive the second pass instead of falling through to the pin path.
    render(
      <StrictMode>
        {view({
          threadId: "thread-1",
          messages: [HUMAN_1, AI_1, HUMAN_2] as Message[],
          isLoading: true,
        })}
      </StrictMode>,
    );

    expect(lastPinnedGroup()).toBeNull();
  });

  it("clears the pin when the run finishes", () => {
    const { rerender } = render(idle());
    rerender(
      view({
        threadId: "thread-1",
        messages: [HUMAN_1, AI_1, HUMAN_2] as Message[],
        isLoading: true,
      }),
    );
    expect(lastPinnedGroup()).toBe("local-human-2");

    // The reply completed: the end spacer must collapse with the pin.
    rerender(
      view({
        threadId: "thread-1",
        messages: [
          HUMAN_1,
          AI_1,
          HUMAN_2,
          { id: "ai-2", type: "ai", content: "final answer" },
        ] as Message[],
        isLoading: false,
      }),
    );

    expect(lastPinnedGroup()).toBeNull();
  });

  it("clears the pin when switching to another thread", () => {
    const { rerender } = render(idle());
    rerender(
      view({
        threadId: "thread-1",
        messages: [HUMAN_1, AI_1, HUMAN_2] as Message[],
        isLoading: true,
      }),
    );
    expect(lastPinnedGroup()).toBe("local-human-2");

    // Opening another thread absorbs its last group instead of re-pinning.
    rerender(
      view({
        threadId: "thread-2",
        messages: [HUMAN_1] as Message[],
        isLoading: true,
      }),
    );

    expect(lastPinnedGroup()).toBeNull();
  });
});

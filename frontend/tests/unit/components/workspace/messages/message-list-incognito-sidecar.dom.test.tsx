import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { MessageList } from "@/components/workspace/messages/message-list";
import { SidecarProvider } from "@/components/workspace/sidecar/context";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import type { MessageGroup } from "@/core/messages/utils";

// The provider restores the last side thread on mount; keep the network out of
// this test and let it reconcile to "no side thread".
const api = rs.hoisted(() => ({ findLatestSidecarThread: rs.fn() }));
rs.mock("@/core/sidecar/api", () => api);

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
  MessageListItem: ({ message }: { message: Message }) => (
    <p>{typeof message.content === "string" ? message.content : ""}</p>
  ),
}));
rs.mock("@/components/workspace/messages/subtask-card", () => ({
  SubtaskCard: () => null,
}));

const selectedAnswer = "The answer quotes a budget line.";
const messages: Message[] = [
  { id: "ai-1", type: "ai", content: selectedAnswer },
];

/** Selects the whole answer and fires the mouseup the message list listens for. */
function selectAnswer() {
  const paragraph = screen.getByText(selectedAnswer);
  const textNode = paragraph.firstChild;
  if (!textNode) {
    throw new Error("assistant text node missing");
  }
  const range = document.createRange();
  range.setStart(textNode, 0);
  range.setEnd(textNode, selectedAnswer.length);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  fireEvent.mouseUp(paragraph);
}

function renderList(disabled: boolean) {
  return render(
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <SidecarProvider
        context={{ mode: "flash" }}
        disabled={disabled}
        parentThreadId="thread-1"
      >
        <MessageList
          threadId="thread-1"
          thread={
            {
              messages,
              error: undefined,
              isLoading: false,
              isThreadLoading: false,
              values: {},
              getMessagesMetadata: () => undefined,
            } as unknown as React.ComponentProps<typeof MessageList>["thread"]
          }
        />
      </SidecarProvider>
    </I18nContext.Provider>,
  );
}

function toolbar() {
  const element = document.querySelector("[data-sidecar-selection-toolbar]");
  expect(element).not.toBeNull();
  return element as HTMLElement;
}

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("message selection toolbar in an incognito chat", () => {
  it("offers quoting but not the side-chat entry", () => {
    api.findLatestSidecarThread.mockResolvedValue(null);
    renderList(true);

    selectAnswer();

    const actions = toolbar();
    expect(
      within(actions).getByText(enUS.sidecar.addToConversation),
    ).not.toBeNull();
    expect(within(actions).queryByText(enUS.sidecar.askInSideChat)).toBeNull();
  });

  it("keeps the side-chat entry in an ordinary chat", () => {
    api.findLatestSidecarThread.mockResolvedValue(null);
    renderList(false);

    selectAnswer();

    const actions = toolbar();
    expect(
      within(actions).getByText(enUS.sidecar.addToConversation),
    ).not.toBeNull();
    expect(
      within(actions).getByText(enUS.sidecar.askInSideChat),
    ).not.toBeNull();
  });
});

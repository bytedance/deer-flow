import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, beforeAll, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ConversationReferenceList } from "@/components/workspace/conversation-references/conversation-reference-picker";
import { MessageListItem } from "@/components/workspace/messages/message-list-item";
import {
  buildConversationReferenceMetadata,
  type ConversationReference,
} from "@/core/conversation-references";
import { enUS } from "@/core/i18n/locales/en-US";
import type { AgentThread } from "@/core/threads/types";

// The source conversation belongs to a custom agent; metadata.agent_name is
// what the sidebar's thread list carries for it.
const threads = [
  {
    thread_id: "t-current",
    updated_at: "2026-09-16T09:00:00Z",
    values: { title: "This conversation" },
    metadata: {},
  },
  {
    thread_id: "source-1",
    updated_at: "2026-09-16T08:00:00Z",
    values: { title: "Writer brief" },
    metadata: { agent_name: "writer" },
  },
] as unknown as AgentThread[];

rs.mock("@/core/threads/hooks", () => ({
  useThreads: () => ({ data: threads, isPending: false, isError: false }),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    setLocale: () => undefined,
    t: enUS,
  }),
}));

// The transcript body is not under test; stubbing the markdown pipeline also
// avoids its first-render suspension.
rs.mock("@/components/workspace/messages/markdown-content", () => ({
  MarkdownContent: () => null,
}));

beforeAll(() => {
  // cmdk measures its list and scrolls the active item; happy-dom has neither.
  class ResizeObserverStub {
    observe = rs.fn();
    unobserve = rs.fn();
    disconnect = rs.fn();
  }
  globalThis.ResizeObserver ??=
    ResizeObserverStub as unknown as typeof ResizeObserver;
  if (!("scrollIntoView" in Element.prototype)) {
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: rs.fn(),
      writable: true,
    });
  }
});

afterEach(cleanup);

describe("conversation reference picker-to-transcript flow", () => {
  it("links the transcript chip to a custom-agent source conversation", () => {
    // 1. Select the custom-agent conversation in the picker.
    let selected: ConversationReference | undefined;
    render(
      <ConversationReferenceList
        currentThreadId="t-current"
        maxReferences={3}
        onToggle={(reference) => {
          selected = reference;
        }}
        selected={[]}
      />,
    );
    fireEvent.click(screen.getByText("Writer brief"));
    expect(selected).toEqual({
      threadId: "source-1",
      title: "Writer brief",
      agentName: "writer",
    });

    // 2. The send path stores the display-only metadata on the human message.
    const message = {
      id: "human-1",
      type: "human",
      content: "Summarize the referenced brief",
      additional_kwargs: buildConversationReferenceMetadata([selected!]),
    } as unknown as Message;

    // 3. The transcript chip routes back to the custom-agent conversation.
    cleanup();
    render(
      <MessageListItem
        message={message}
        threadId="t-current"
        showCopyButton={false}
        isLoading={false}
      />,
    );
    const chip = screen.getByTestId("conversation-reference-chip");
    expect(chip.getAttribute("href")).toBe(
      "/workspace/agents/writer/chats/source-1",
    );
  });

  it("links a default-agent source to the plain chats path", () => {
    const message = {
      id: "human-2",
      type: "human",
      content: "Summarize the referenced chat",
      additional_kwargs: buildConversationReferenceMetadata([
        { threadId: "source-2", title: "Plain chat" },
      ]),
    } as unknown as Message;

    render(
      <MessageListItem
        message={message}
        threadId="t-current"
        showCopyButton={false}
        isLoading={false}
      />,
    );
    const chip = screen.getByTestId("conversation-reference-chip");
    expect(chip.getAttribute("href")).toBe("/workspace/chats/source-2");
  });
});

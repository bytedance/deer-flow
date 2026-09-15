import { afterEach, beforeAll, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ConversationReferenceList } from "@/components/workspace/conversation-references/conversation-reference-picker";
import type { AgentThread } from "@/core/threads/types";

const threads = [
  {
    thread_id: "t-current",
    updated_at: "2026-09-15T09:00:00Z",
    values: { title: "This conversation" },
    metadata: {},
  },
  {
    thread_id: "t-a",
    updated_at: "2026-09-15T08:00:00Z",
    values: { title: "Alpha requirements" },
    metadata: {},
  },
  {
    thread_id: "t-b",
    updated_at: "2026-09-15T07:00:00Z",
    values: { title: "Beta design" },
    metadata: {},
  },
  {
    thread_id: "t-c",
    updated_at: "2026-09-15T06:00:00Z",
    values: {},
    metadata: {},
  },
] as unknown as AgentThread[];

let threadsQuery: {
  data?: AgentThread[];
  isPending: boolean;
  isError: boolean;
} = {
  data: threads,
  isPending: false,
  isError: false,
};

rs.mock("@/core/threads/hooks", () => ({
  useThreads: () => threadsQuery,
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      inputBox: {
        referenceConversations: "Reference a conversation",
        referenceConversationsSearch: "Search conversations",
        referenceConversationsEmpty: "No conversations found",
        referenceConversationsLimit: (max: number) =>
          `Up to ${max} conversations per message`,
        referenceConversationsRemove: (title: string) => `Remove ${title}`,
        referencedConversations: "Referenced conversations",
      },
      common: { loading: "Loading...", untitled: "Untitled" },
    },
  }),
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

afterEach(() => {
  cleanup();
  threadsQuery = { data: threads, isPending: false, isError: false };
});

describe("ConversationReferenceList", () => {
  it("shows a loading row, not the empty state, while the list is still loading", () => {
    threadsQuery = { data: undefined, isPending: true, isError: false };
    render(
      <ConversationReferenceList
        currentThreadId="t-current"
        maxReferences={3}
        onToggle={rs.fn()}
        selected={[]}
      />,
    );
    expect(screen.getByTestId("conversation-reference-loading")).toBeTruthy();
    expect(screen.queryByText("No conversations found")).toBeNull();
  });

  it("lists other conversations by title and never the current one", () => {
    render(
      <ConversationReferenceList
        currentThreadId="t-current"
        maxReferences={3}
        onToggle={rs.fn()}
        selected={[]}
      />,
    );
    expect(screen.getByText("Alpha requirements")).toBeTruthy();
    expect(screen.getByText("Beta design")).toBeTruthy();
    expect(screen.getByText("Untitled")).toBeTruthy();
    expect(screen.queryByText("This conversation")).toBeNull();
  });

  it("toggles a reference with its title", () => {
    const onToggle = rs.fn();
    render(
      <ConversationReferenceList
        currentThreadId="t-current"
        maxReferences={3}
        onToggle={onToggle}
        selected={[]}
      />,
    );
    fireEvent.click(screen.getByText("Alpha requirements"));
    expect(onToggle).toHaveBeenCalledWith({
      threadId: "t-a",
      title: "Alpha requirements",
    });
  });

  it("disables unselected rows at the cap but keeps selected rows removable", () => {
    render(
      <ConversationReferenceList
        currentThreadId="t-current"
        maxReferences={2}
        onToggle={rs.fn()}
        selected={[
          { threadId: "t-a", title: "Alpha requirements" },
          { threadId: "t-b", title: "Beta design" },
        ]}
      />,
    );
    const untitled = screen.getByText("Untitled").closest("[cmdk-item]");
    const alpha = screen.getByText("Alpha requirements").closest("[cmdk-item]");
    expect(untitled?.getAttribute("aria-disabled")).toBe("true");
    expect(alpha?.getAttribute("aria-disabled")).not.toBe("true");
    expect(screen.getByText("Up to 2 conversations per message")).toBeTruthy();
  });
});

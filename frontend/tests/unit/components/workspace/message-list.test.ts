/* @vitest-environment jsdom */

import React from "react";
import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentThreadState } from "@/core/threads";
import { useBlockStore, type UIBlock } from "@/core/genui/store";

vi.mock("@/components/ai-elements/conversation", () => ({
  Conversation: ({
    children,
  }: React.PropsWithChildren) => React.createElement("div", null, children),
  ConversationContent: ({
    children,
  }: React.PropsWithChildren) => React.createElement("div", null, children),
}));

vi.mock("@/components/genui", () => ({
  GenUIBlockList: ({ blockIds }: { blockIds?: string[] }) =>
    React.createElement(
      "div",
      { "data-testid": "block-list" },
      `BLOCK:${blockIds?.join(",") ?? ""}`,
    ),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: React.PropsWithChildren<Record<string, unknown>>) =>
    React.createElement("button", props, children),
}));

vi.mock("@/core/genui", () => ({
  submitInteraction: vi.fn(),
}));

vi.mock("@/core/genui/sse-recovery", () => ({
  recoverBlocksFromMessages: vi.fn(),
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: {
        loading: "Loading",
        loadMore: "Load more",
      },
      subtasks: {
        executing: (count: number) => `Executing ${count}`,
      },
      uploads: {
        uploadingFiles: "Uploading files",
      },
    },
  }),
}));

vi.mock("@/core/messages/usage-model", () => ({
  buildTokenDebugSteps: () => [],
}));

vi.mock("@/core/rehype", () => ({
  useRehypeSplitWordsIntoSpans: () => [],
}));

vi.mock("@/core/tasks/context", () => ({
  useUpdateSubtask: () => vi.fn(),
}));

vi.mock("@/components/workspace/messages/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) =>
    React.createElement("div", null, content),
}));

vi.mock("@/components/workspace/messages/message-group", () => ({
  MessageGroup: ({ messages }: { messages: Array<{ id?: string }> }) =>
    React.createElement(
      "div",
      null,
      `GROUP:${messages.map((message) => message.id ?? "").join(",")}`,
    ),
}));

vi.mock("@/components/workspace/messages/message-list-item", () => ({
  MessageListItem: ({ message }: { message: { id?: string; type: string } }) =>
    React.createElement(
      "div",
      { "data-testid": "message-item" },
      `${message.type.toUpperCase()}:${message.id ?? ""}`,
    ),
}));

vi.mock("@/components/workspace/messages/message-token-usage", () => ({
  MessageTokenUsageDebugList: () => null,
  MessageTokenUsageList: () => null,
}));

vi.mock("@/components/workspace/messages/retrieval-sources", () => ({
  RetrievalSources: () => null,
}));

vi.mock("@/components/workspace/messages/skeleton", () => ({
  MessageListSkeleton: () => React.createElement("div", null, "skeleton"),
}));

vi.mock("@/components/workspace/messages/subtask-card", () => ({
  SubtaskCard: () => null,
}));

vi.mock("@/components/workspace/artifacts/artifact-file-list", () => ({
  ArtifactFileList: () => null,
}));

vi.mock("@/components/workspace/copy-button", () => ({
  CopyButton: () => null,
}));

vi.mock("@/components/workspace/streaming-indicator", () => ({
  StreamingIndicator: () => React.createElement("div", null, "STREAMING"),
}));

import { MessageList } from "@/components/workspace/messages/message-list";

function makeBlock(block_id: string): UIBlock {
  return {
    schema_version: "1.0",
    type: "ui_block",
    action: "create",
    block_id,
    component: "table",
    props: {},
    interactive: false,
  };
}

function makeThread(
  isLoading: boolean,
  messages: Array<Record<string, unknown>>,
): BaseStream<AgentThreadState> {
  return {
    messages,
    isLoading,
    isThreadLoading: false,
  } as unknown as BaseStream<AgentThreadState>;
}

describe("MessageList standalone block placement", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    useBlockStore.getState().reset();
    useBlockStore.setState({
      blocks: new Map([["old-block", makeBlock("old-block")]]),
      interactions: new Map(),
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    container.remove();
    useBlockStore.getState().reset();
  });

  it("keeps pre-existing standalone blocks after messages when submit starts streaming", async () => {
    const baseMessages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "生成日报" }],
      },
    ];

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, baseMessages),
        }),
      );
    });

    expect(container.textContent?.indexOf("HUMAN:human-1")).toBeLessThan(
      container.textContent?.indexOf("BLOCK:old-block") ?? Number.POSITIVE_INFINITY,
    );

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(true, baseMessages),
        }),
      );
    });

    await React.act(async () => {
      await Promise.resolve();
    });

    expect(container.textContent?.indexOf("HUMAN:human-1")).toBeLessThan(
      container.textContent?.indexOf("BLOCK:old-block") ?? Number.POSITIVE_INFINITY,
    );
  });

  it("moves previous-turn standalone blocks back above the new turn once live messages arrive", async () => {
    const previousMessages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "上一轮日报" }],
      },
    ];

    const nextTurnMessages = [
      ...previousMessages,
      {
        type: "human" as const,
        id: "human-2",
        content: [{ type: "text" as const, text: "再来一份日报" }],
      },
      {
        type: "ai" as const,
        id: "ai-2",
        content: [{ type: "text" as const, text: "请填写日报参数后提交。" }],
      },
    ];

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, previousMessages),
        }),
      );
    });

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(true, previousMessages),
        }),
      );
    });

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, nextTurnMessages),
        }),
      );
    });

    expect(container.textContent?.indexOf("BLOCK:old-block")).toBeLessThan(
      container.textContent?.indexOf("HUMAN:human-2") ?? Number.POSITIVE_INFINITY,
    );
  });

  it("keeps blocks near their first processing turn when they later become standalone", async () => {
    const firstTurnMessages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "第一轮日报" }],
      },
      {
        type: "ai" as const,
        id: "ai-1",
        content: "",
        tool_calls: [{ id: "tool-call-1", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-1",
        tool_call_id: "tool-call-1",
        content:
          "UI component 'card' (create) rendered successfully. block_id=old-block",
      },
    ];

    const secondTurnMessages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "第一轮日报" }],
      },
      {
        type: "ai" as const,
        id: "ai-1",
        content: "",
        tool_calls: [{ id: "tool-call-1", name: "render_ui", args: {} }],
      },
      {
        type: "human" as const,
        id: "human-2",
        content: [{ type: "text" as const, text: "第二轮日报" }],
      },
      {
        type: "ai" as const,
        id: "ai-2",
        content: [{ type: "text" as const, text: "请提交第一步表单" }],
      },
    ];

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, firstTurnMessages),
        }),
      );
    });

    expect(container.textContent?.indexOf("GROUP:ai-1,tool-1")).toBeLessThan(
      container.textContent?.indexOf("BLOCK:old-block") ?? Number.POSITIVE_INFINITY,
    );

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, secondTurnMessages),
        }),
      );
    });

    expect(container.textContent).toContain("GROUP:ai-1");
    expect(container.textContent).toContain("BLOCK:old-block");

    const processingGroupIndex =
      container.textContent?.indexOf("GROUP:ai-1") ?? -1;
    const oldBlockIndex = container.textContent?.indexOf("BLOCK:old-block") ?? -1;
    const secondTurnIndex =
      container.textContent?.indexOf("HUMAN:human-2") ?? Number.POSITIVE_INFINITY;

    expect(processingGroupIndex).toBeGreaterThanOrEqual(0);
    expect(oldBlockIndex).toBeGreaterThan(processingGroupIndex);
    expect(oldBlockIndex).toBeLessThan(secondTurnIndex);
  });

  it("renders separate historical results when two rounds reused the same raw block id", async () => {
    useBlockStore.setState({
      blocks: new Map(),
      interactions: new Map(),
    });

    const duplicateBlockContent = (title: string) =>
      `UI component 'card' (create) rendered successfully. block_id=daily-report-chart\n<!--ui_block:{"schema_version":"1.0","type":"ui_block","action":"create","block_id":"daily-report-chart","component":"card","props":{"title":"${title}"},"interactive":false}-->`;

    const messages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "first turn" }],
      },
      {
        type: "ai" as const,
        id: "ai-1",
        content: "",
        tool_calls: [{ id: "tool-call-1", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-1",
        tool_call_id: "tool-call-1",
        content: duplicateBlockContent("Round 1"),
      },
      {
        type: "human" as const,
        id: "human-2",
        content: [{ type: "text" as const, text: "second turn" }],
      },
      {
        type: "ai" as const,
        id: "ai-2",
        content: "",
        tool_calls: [{ id: "tool-call-2", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-2",
        tool_call_id: "tool-call-2",
        content: duplicateBlockContent("Round 2"),
      },
    ];

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, messages),
        }),
      );
    });

    expect(container.textContent).toContain("BLOCK:daily-report-chart__1");
    expect(container.textContent).toContain("BLOCK:daily-report-chart__2");
    expect(
      container.textContent?.indexOf("BLOCK:daily-report-chart__1"),
    ).toBeLessThan(
      container.textContent?.indexOf("HUMAN:human-2") ?? Number.POSITIVE_INFINITY,
    );
    expect(
      container.textContent?.indexOf("BLOCK:daily-report-chart__2"),
    ).toBeGreaterThan(
      container.textContent?.indexOf("HUMAN:human-2") ?? Number.NEGATIVE_INFINITY,
    );
  });
});

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, test, vi } from "vitest";

const capturedProps = vi.hoisted(() => ({
  artifactFileList: [] as Array<Record<string, unknown>>,
  markdownContent: [] as Array<Record<string, unknown>>,
  messageGroup: [] as Array<Record<string, unknown>>,
  subtaskCard: [] as Array<Record<string, unknown>>,
  updateSubtask: vi.fn(),
}));

vi.mock("@/components/ai-elements/conversation", () => ({
  Conversation: ({ children }: { children: React.ReactNode }) => children,
  ConversationContent: ({ children }: { children: React.ReactNode }) =>
    children,
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      subtasks: {
        executing: (count: number) => `executing ${count}`,
      },
    },
  }),
}));

vi.mock("@/core/messages/utils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/core/messages/utils")>();
  const clarificationMessage = { id: "clarification-message", type: "tool" };
  const presentFilesMessage = { id: "present-files-message", type: "ai" };
  const subagentMessage = {
    id: "subagent-message",
    type: "ai",
    tool_calls: [
      {
        id: "task-1",
        name: "task",
        args: {
          subagent_type: "general",
          description: "Run a subtask",
          prompt: "subtask prompt",
        },
      },
    ],
  };
  const processingMessage = { id: "processing-message", type: "ai" };

  return {
    ...actual,
    groupMessages: (
      _messages: unknown[],
      mapper: (group: unknown) => unknown,
    ) =>
      [
        {
          id: "clarification-group",
          type: "assistant:clarification",
          messages: [clarificationMessage],
        },
        {
          id: "present-files-group",
          type: "assistant:present-files",
          messages: [presentFilesMessage],
        },
        {
          id: "subagent-group",
          type: "assistant:subagent",
          messages: [subagentMessage],
        },
        {
          id: "processing-group",
          type: "assistant:processing",
          messages: [processingMessage],
        },
      ].map(mapper),
    extractContentFromMessage: (message: { id: string }) =>
      `content:${message.id}`,
    extractPresentFilesFromMessage: () => ["mnt/user-data/outputs/result.md"],
    extractTextFromMessage: () => "",
    hasContent: () => true,
    hasPresentFiles: (message: { id: string }) =>
      message.id === "present-files-message",
    hasReasoning: (message: { id: string }) =>
      message.id === "subagent-message",
  };
});

vi.mock("@/core/rehype", () => ({
  useRehypeSplitWordsIntoSpans: () => [],
}));

vi.mock("@/core/tasks/context", () => ({
  useUpdateSubtask: () => capturedProps.updateSubtask,
}));

vi.mock("@/lib/utils", () => ({
  cn: (...parts: Array<string | undefined | false | null>) =>
    parts.filter(Boolean).join(" "),
}));

vi.mock(
  "../../../../../src/components/workspace/artifacts/artifact-file-list",
  () => ({
    ArtifactFileList: (props: Record<string, unknown>) => {
      capturedProps.artifactFileList.push(props);
      return null;
    },
  }),
);

vi.mock(
  "../../../../../src/components/workspace/messages/markdown-content",
  () => ({
    MarkdownContent: (props: Record<string, unknown>) => {
      capturedProps.markdownContent.push(props);
      return null;
    },
  }),
);

vi.mock(
  "../../../../../src/components/workspace/messages/message-group",
  () => ({
    MessageGroup: (props: Record<string, unknown>) => {
      capturedProps.messageGroup.push(props);
      return null;
    },
  }),
);

vi.mock(
  "../../../../../src/components/workspace/messages/message-list-item",
  () => ({
    MessageListItem: () => null,
  }),
);

vi.mock("../../../../../src/components/workspace/messages/skeleton", () => ({
  MessageListSkeleton: () => null,
}));

vi.mock(
  "../../../../../src/components/workspace/messages/subtask-card",
  () => ({
    SubtaskCard: (props: Record<string, unknown>) => {
      capturedProps.subtaskCard.push(props);
      return null;
    },
  }),
);

vi.mock("../../../../../src/components/workspace/streaming-indicator", () => ({
  StreamingIndicator: () => null,
}));

import { MessageList } from "../../../../../src/components/workspace/messages/message-list";

beforeEach(() => {
  capturedProps.artifactFileList.length = 0;
  capturedProps.markdownContent.length = 0;
  capturedProps.messageGroup.length = 0;
  capturedProps.subtaskCard.length = 0;
  capturedProps.updateSubtask.mockReset();
});

test("passes threadId through thread markdown rendering branches", () => {
  const thread = {
    isLoading: false,
    isThreadLoading: false,
    messages: [],
  } as unknown as Parameters<typeof MessageList>[0]["thread"];

  renderToStaticMarkup(
    createElement(MessageList, {
      threadId: "thread-1",
      thread,
    }),
  );

  expect(capturedProps.markdownContent).toHaveLength(2);
  expect(capturedProps.markdownContent).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        content: "content:clarification-message",
        threadId: "thread-1",
      }),
      expect.objectContaining({
        content: "content:present-files-message",
        threadId: "thread-1",
      }),
    ]),
  );
  expect(capturedProps.messageGroup).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        threadId: "thread-1",
      }),
      expect.objectContaining({
        threadId: "thread-1",
      }),
    ]),
  );
  expect(capturedProps.subtaskCard).toEqual([
    expect.objectContaining({
      taskId: "task-1",
      threadId: "thread-1",
    }),
  ]);
  expect(capturedProps.artifactFileList).toEqual([
    expect.objectContaining({
      files: ["mnt/user-data/outputs/result.md"],
      threadId: "thread-1",
    }),
  ]);
});

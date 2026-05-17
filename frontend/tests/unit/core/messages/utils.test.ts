import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "vitest";

import {
  getAssistantTurnCopyData,
  getAssistantTurnUsageMessages,
  getCurrentStreamingAssistantMessage,
  getMessageGroups,
  isCurrentStreamingAssistantTurn,
} from "@/core/messages/utils";

test("aggregates token usage messages once per assistant turn", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Plan a trip",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "",
      tool_calls: [{ id: "tool-1", name: "web_search", args: {} }],
      usage_metadata: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
    },
    {
      id: "tool-1-result",
      type: "tool",
      name: "web_search",
      tool_call_id: "tool-1",
      content: "[]",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "Here is the itinerary",
      usage_metadata: { input_tokens: 2, output_tokens: 8, total_tokens: 10 },
    },
    {
      id: "human-2",
      type: "human",
      content: "Make it shorter",
    },
    {
      id: "ai-3",
      type: "ai",
      content: "Short version",
      usage_metadata: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
    },
  ] as Message[];

  const groups = getMessageGroups(messages);
  const usageMessagesByGroupIndex = getAssistantTurnUsageMessages(groups);

  expect(groups.map((group) => group.type)).toEqual([
    "human",
    "assistant:processing",
    "assistant",
    "human",
    "assistant",
  ]);

  expect(
    usageMessagesByGroupIndex.map(
      (groupMessages) => groupMessages?.map((message) => message.id) ?? null,
    ),
  ).toEqual([null, null, ["ai-1", "ai-2"], null, ["ai-3"]]);
});

test("hides internal todo reminder messages from message groups", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Audit the middleware",
    },
    {
      id: "todo-reminder-1",
      type: "human",
      name: "todo_completion_reminder",
      content: "<system_reminder>finish todos</system_reminder>",
    },
    {
      id: "todo-reminder-2",
      type: "human",
      name: "todo_reminder",
      content: "<system_reminder>remember todos</system_reminder>",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Done",
    },
  ] as Message[];

  const groups = getMessageGroups(messages);

  expect(groups.map((group) => group.type)).toEqual(["human", "assistant"]);
  expect(
    groups.flatMap((group) => group.messages).map((message) => message.id),
  ).toEqual(["human-1", "ai-1"]);
});

test("hides assistant turn copy data while that turn is still streaming", () => {
  const messages = [
    {
      id: "ai-1",
      type: "ai",
      content: "Partial answer",
    },
  ] as Message[];

  expect(getAssistantTurnCopyData(messages)).toBe("Partial answer");
  expect(getAssistantTurnCopyData(messages, { isStreaming: true })).toBeNull();
});

test("marks only the latest visible AI turn as streaming", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "First answer",
    },
    {
      id: "human-2",
      type: "human",
      content: "Continue",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "Still generating",
    },
  ] as Message[];

  const assistantGroups = getMessageGroups(messages).filter(
    (group) => group.type === "assistant",
  );
  const pendingStreamMessages = messages.slice(2);

  expect(
    isCurrentStreamingAssistantTurn(
      assistantGroups[0]?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, true, {
        pendingStreamMessages,
      }),
    ),
  ).toBe(false);
  expect(
    isCurrentStreamingAssistantTurn(
      assistantGroups[1]?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, true, {
        pendingStreamMessages,
      }),
    ),
  ).toBe(true);
  expect(
    isCurrentStreamingAssistantTurn(
      assistantGroups[1]?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, false, {
        pendingStreamMessages,
      }),
    ),
  ).toBe(false);
});

test("does not mark the previous assistant turn as streaming while waiting for a new answer", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "First answer",
    },
    {
      id: "human-2",
      type: "human",
      content: "Continue",
    },
  ] as Message[];

  const [assistantGroup] = getMessageGroups(messages).filter(
    (group) => group.type === "assistant",
  );

  expect(
    isCurrentStreamingAssistantTurn(
      assistantGroup?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, true, {
        pendingStreamMessages: [messages[2]!],
      }),
    ),
  ).toBe(false);
});

test("does not mark the previous assistant turn as streaming after a hidden human message", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "First answer",
    },
    {
      id: "human-hidden",
      type: "human",
      content: "Save this agent",
      additional_kwargs: { hide_from_ui: true },
    },
  ] as Message[];

  const [assistantGroup] = getMessageGroups(messages).filter(
    (group) => group.type === "assistant",
  );

  expect(
    isCurrentStreamingAssistantTurn(
      assistantGroup?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, true, {
        pendingStreamMessages: [messages[2]!],
      }),
    ),
  ).toBe(false);
});

test("does not fall back to a completed assistant turn when no pending AI has arrived", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "First answer",
    },
  ] as Message[];

  const [assistantGroup] = getMessageGroups(messages).filter(
    (group) => group.type === "assistant",
  );

  expect(
    isCurrentStreamingAssistantTurn(
      assistantGroup?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, true, {
        pendingStreamMessages: [],
      }),
    ),
  ).toBe(false);
});

test("marks a streaming AI message before an optimistic human message", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "First answer",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "Still generating",
    },
    {
      id: "opt-human-1",
      type: "human",
      content: "Continue",
    },
  ] as Message[];

  const assistantGroups = getMessageGroups(messages).filter(
    (group) => group.type === "assistant",
  );

  expect(
    isCurrentStreamingAssistantTurn(
      assistantGroups[0]?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, true, {
        pendingStreamMessages: [messages[2]!],
      }),
    ),
  ).toBe(false);
  expect(
    isCurrentStreamingAssistantTurn(
      assistantGroups[1]?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, true, {
        pendingStreamMessages: [messages[2]!],
      }),
    ),
  ).toBe(true);
});

test("does not mark the previous assistant turn as streaming after an optimistic human message", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "First answer",
    },
    {
      id: "opt-human-1",
      type: "human",
      content: "Continue",
    },
  ] as Message[];

  const [assistantGroup] = getMessageGroups(messages).filter(
    (group) => group.type === "assistant",
  );

  expect(
    isCurrentStreamingAssistantTurn(
      assistantGroup?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, true, {
        pendingStreamMessages: [],
      }),
    ),
  ).toBe(false);
});

test("keeps the pending AI streaming when the server human arrives after it", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "First answer",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "Still generating",
    },
    {
      id: "opt-human-1",
      type: "human",
      content: "Continue",
    },
  ] as Message[];

  const assistantGroups = getMessageGroups(messages).filter(
    (group) => group.type === "assistant",
  );

  expect(
    isCurrentStreamingAssistantTurn(
      assistantGroups[1]?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, true, {
        pendingStreamMessages: [
          messages[2]!,
          {
            id: "human-2",
            type: "human",
            content: "Continue",
          } as Message,
        ],
      }),
    ),
  ).toBe(true);
});

test("keeps the pending AI streaming when a hidden human arrives after it", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "First answer",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "Still generating",
    },
    {
      id: "opt-human-1",
      type: "human",
      content: "Continue",
    },
  ] as Message[];

  const assistantGroups = getMessageGroups(messages).filter(
    (group) => group.type === "assistant",
  );

  expect(
    isCurrentStreamingAssistantTurn(
      assistantGroups[1]?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, true, {
        pendingStreamMessages: [
          messages[2]!,
          {
            id: "human-hidden",
            type: "human",
            content: "Save this agent",
            additional_kwargs: { hide_from_ui: true },
          } as Message,
        ],
      }),
    ),
  ).toBe(true);
});

test("ignores hidden AI messages when finding the streaming assistant turn", () => {
  const messages = [
    {
      id: "ai-visible",
      type: "ai",
      content: "Visible answer",
    },
    {
      id: "ai-hidden",
      type: "ai",
      content: "Hidden control update",
      additional_kwargs: { hide_from_ui: true },
    },
  ] as Message[];

  const [visibleGroup] = getMessageGroups(messages).filter(
    (group) => group.type === "assistant",
  );

  expect(
    isCurrentStreamingAssistantTurn(
      visibleGroup?.messages ?? [],
      getCurrentStreamingAssistantMessage(messages, true, {
        pendingStreamMessages: messages,
      }),
    ),
  ).toBe(true);
});

test("matches id-less streaming AI messages by object identity", () => {
  const streamingAi = {
    type: "ai",
    content: "Still generating",
  } as Message;
  const copiedStreamingAi = {
    type: "ai",
    content: "Still generating",
  } as Message;

  expect(
    isCurrentStreamingAssistantTurn(
      [streamingAi],
      getCurrentStreamingAssistantMessage([streamingAi], true, {
        pendingStreamMessages: [streamingAi],
      }),
    ),
  ).toBe(true);
  expect(
    isCurrentStreamingAssistantTurn(
      [copiedStreamingAi],
      getCurrentStreamingAssistantMessage([streamingAi], true, {
        pendingStreamMessages: [streamingAi],
      }),
    ),
  ).toBe(false);
});

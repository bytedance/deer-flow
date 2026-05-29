import type { Message } from "@langchain/langgraph-sdk";
import { expect, test, vi } from "vitest";

import {
  getAssistantTurnUsageMessages,
  getMessageGroups,
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

test("creates synthetic processing group for orphaned tool messages", () => {
  const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

  // Scenario: tool message arrives without a preceding AI message with tool_calls
  // (e.g., out-of-order streaming, or AI message was classified as terminal group)
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Search for something",
    },
    {
      id: "tool-orphan",
      type: "tool",
      name: "web_search",
      tool_call_id: "tool-1",
      content: "search results",
    },
  ] as Message[];

  const groups = getMessageGroups(messages);

  // Should create a synthetic processing group instead of logging an error
  expect(groups.map((group) => group.type)).toEqual([
    "human",
    "assistant:processing",
  ]);

  expect(groups[1]?.messages).toHaveLength(1);
  expect(groups[1]?.messages[0]?.id).toBe("tool-orphan");

  // Should NOT log an error
  expect(consoleSpy).not.toHaveBeenCalled();

  consoleSpy.mockRestore();
});

import type { Message } from "@langchain/langgraph-sdk";
import { expect, test, vi } from "vitest";

import {
  getAssistantTurnUsageMessages,
  extendMessageGroups,
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

test("hides safety policy block placeholder messages", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "我现在选中的这个缺陷绑定的设备id是什么？",
    },
    {
      id: "human-safety-block",
      type: "human",
      content:
        "[Content blocked by safety policy: Prompt injection detected: obfuscation]",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "设备 ID 是 2067266200919998465。",
    },
  ] as Message[];

  const groups = getMessageGroups(messages);

  expect(groups.map((group) => group.type)).toEqual(["human", "assistant"]);
  expect(groups.flatMap((group) => group.messages.map((message) => message.id))).toEqual([
    "human-1",
    "ai-1",
  ]);
});

test("appending a tool message extends the existing processing group (2.9)", () => {
  const baseMessages = [
    { id: "human-1", type: "human", content: "Search" },
    {
      id: "ai-1",
      type: "ai",
      content: "",
      tool_calls: [{ id: "tc-1", name: "web_search", args: {} }],
    },
  ] as Message[];

  const baseGroups = getMessageGroups(baseMessages);
  expect(baseGroups.map((g) => g.type)).toEqual(["human", "assistant:processing"]);
  expect(baseGroups[1]?.messages).toHaveLength(1);

  const withToolResult = [
    ...baseMessages,
    {
      id: "tool-1",
      type: "tool",
      name: "web_search",
      tool_call_id: "tc-1",
      content: "search results",
    },
  ] as Message[];

  const extendedGroups = getMessageGroups(withToolResult);
  expect(extendedGroups.map((g) => g.type)).toEqual(["human", "assistant:processing"]);
  expect(extendedGroups[1]?.messages).toHaveLength(2);
  expect(extendedGroups[1]?.messages.map((m) => m.id)).toEqual(["ai-1", "tool-1"]);
});

test("appending a new human message creates a new group (2.9)", () => {
  const baseMessages = [
    { id: "human-1", type: "human", content: "Hello" },
    { id: "ai-1", type: "ai", content: "Hi there" },
  ] as Message[];

  const baseGroups = getMessageGroups(baseMessages);
  expect(baseGroups).toHaveLength(2);

  const withNewHuman = [
    ...baseMessages,
    { id: "human-2", type: "human", content: "Follow-up" },
  ] as Message[];

  const newGroups = getMessageGroups(withNewHuman);
  expect(newGroups).toHaveLength(3);
  expect(newGroups.map((g) => g.type)).toEqual(["human", "assistant", "human"]);
  expect(newGroups[2]?.messages).toHaveLength(1);
  expect(newGroups[2]?.messages[0]?.id).toBe("human-2");
});

test("incremental append preserves existing group structure (2.9)", () => {
  const messages1 = [
    { id: "h1", type: "human", content: "Q1" },
    { id: "a1", type: "ai", content: "A1" },
  ] as Message[];

  const groups1 = getMessageGroups(messages1);

  const messages2 = [
    ...messages1,
    { id: "h2", type: "human", content: "Q2" },
    { id: "a2", type: "ai", content: "A2" },
  ] as Message[];

  const groups2 = getMessageGroups(messages2);

  expect(groups2.slice(0, groups1.length).map((g) => g.type)).toEqual(
    groups1.map((g) => g.type),
  );
  expect(groups2.slice(0, groups1.length).map((g) => g.messages.length)).toEqual(
    groups1.map((g) => g.messages.length),
  );
  expect(groups2.length).toBe(groups1.length + 2);
});

test("extendMessageGroups returns existing groups when no new messages", () => {
  const messages = [
    { id: "h1", type: "human", content: "Hello" },
    { id: "a1", type: "ai", content: "Hi" },
  ] as Message[];
  const groups = getMessageGroups(messages);

  const extended = extendMessageGroups(groups, []);
  expect(extended).toBe(groups);
});

test("extendMessageGroups computes from scratch when existing groups empty", () => {
  const newMessages = [
    { id: "h1", type: "human", content: "Hello" },
  ] as Message[];

  const extended = extendMessageGroups([], newMessages);
  expect(extended.map((g) => g.type)).toEqual(["human"]);
});

test("extendMessageGroups appends to open processing group", () => {
  const baseMessages = [
    { id: "h1", type: "human", content: "Search" },
    {
      id: "ai1",
      type: "ai",
      content: "",
      tool_calls: [{ id: "tc-1", name: "web_search", args: {} }],
    },
  ] as Message[];
  const baseGroups = getMessageGroups(baseMessages);
  expect(baseGroups.map((g) => g.type)).toEqual(["human", "assistant:processing"]);

  const newMessages = [
    {
      id: "tool-1",
      type: "tool",
      name: "web_search",
      tool_call_id: "tc-1",
      content: "results",
    },
  ] as Message[];

  const extended = extendMessageGroups(baseGroups, newMessages);
  expect(extended.map((g) => g.type)).toEqual(["human", "assistant:processing"]);
  expect(extended[1]?.messages).toHaveLength(2);
  expect(extended[1]?.messages.map((m) => m.id)).toEqual(["ai1", "tool-1"]);
});

test("extendMessageGroups creates new groups after closed group", () => {
  const baseMessages = [
    { id: "h1", type: "human", content: "Hello" },
    { id: "a1", type: "ai", content: "Hi" },
  ] as Message[];
  const baseGroups = getMessageGroups(baseMessages);
  expect(baseGroups.map((g) => g.type)).toEqual(["human", "assistant"]);

  const newMessages = [
    { id: "h2", type: "human", content: "Follow-up" },
    { id: "a2", type: "ai", content: "Reply" },
  ] as Message[];

  const extended = extendMessageGroups(baseGroups, newMessages);
  expect(extended.map((g) => g.type)).toEqual([
    "human",
    "assistant",
    "human",
    "assistant",
  ]);
  expect(extended).toHaveLength(4);
});

test("extendMessageGroups produces same result as full recomputation for append", () => {
  const baseMessages = [
    { id: "h1", type: "human", content: "Q1" },
    { id: "a1", type: "ai", content: "A1" },
  ] as Message[];
  const baseGroups = getMessageGroups(baseMessages);

  const appended = [
    { id: "h2", type: "human", content: "Q2" },
    {
      id: "ai2",
      type: "ai",
      content: "",
      tool_calls: [{ id: "tc-2", name: "search", args: {} }],
    },
    {
      id: "tool-2",
      type: "tool",
      name: "search",
      tool_call_id: "tc-2",
      content: "results",
    },
  ] as Message[];

  const incremental = extendMessageGroups(baseGroups, appended);
  const full = getMessageGroups([...baseMessages, ...appended]);

  expect(incremental.map((g) => g.type)).toEqual(full.map((g) => g.type));
  expect(incremental.map((g) => g.messages.length)).toEqual(
    full.map((g) => g.messages.length),
  );
});

test("extendMessageGroups does not mutate existing groups", () => {
  const baseMessages = [
    { id: "h1", type: "human", content: "Hello" },
    {
      id: "ai1",
      type: "ai",
      content: "",
      tool_calls: [{ id: "tc-1", name: "search", args: {} }],
    },
  ] as Message[];
  const baseGroups = getMessageGroups(baseMessages);
  const originalLastGroupMessageCount = baseGroups[1]?.messages.length ?? 0;

  extendMessageGroups(baseGroups, [
    {
      id: "tool-1",
      type: "tool",
      name: "search",
      tool_call_id: "tc-1",
      content: "result",
    },
  ] as Message[]);

  expect(baseGroups[1]?.messages.length).toBe(originalLastGroupMessageCount);
});

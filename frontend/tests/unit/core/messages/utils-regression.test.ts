import type { AIMessage, Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "vitest";

import {
  extractPresentFilesFromMessage,
  getMessageGroups,
} from "@/core/messages/utils";

describe("regression: tool-call messages must not swallow text/reasoning content", () => {
  test("AI message with tool_calls + text content generates both processing and assistant bubble", () => {
    const messages = [
      {
        id: "human-1",
        type: "human",
        content: "Search for deer",
      },
      {
        id: "ai-1",
        type: "ai",
        content: "Let me search that for you",
        tool_calls: [
          { id: "tc-1", name: "web_search", args: { query: "deer" } },
        ],
      },
      {
        id: "tool-1",
        type: "tool",
        name: "web_search",
        tool_call_id: "tc-1",
        content: "Results about deer",
      },
      {
        id: "ai-2",
        type: "ai",
        content: "Here is what I found",
      },
    ] as Message[];

    const groups = getMessageGroups(messages);

    expect(groups.map((g) => g.type)).toEqual([
      "human",
      "assistant",
      "assistant:processing",
      "assistant",
    ]);

    // The assistant bubble with the tool-call message text must exist
    // and contain the visible content.
    const assistantGroups = groups.filter((g) => g.type === "assistant");
    expect(assistantGroups).toHaveLength(2);
    expect(assistantGroups[0]!.messages).toHaveLength(1);
    expect(assistantGroups[0]!.messages[0]!.content).toBe(
      "Let me search that for you",
    );

    // The processing group must contain the tool-call AI + tool result.
    const processingGroup = groups.find(
      (g) => g.type === "assistant:processing",
    );
    expect(processingGroup).toBeDefined();
    expect(processingGroup!.messages.map((m) => m.id)).toEqual([
      "ai-1",
      "tool-1",
    ]);
  });

  test("AI message with reasoning + tool_calls + text content produces all three", () => {
    const messages = [
      {
        id: "human-1",
        type: "human",
        content: "Hello",
      },
      {
        id: "ai-1",
        type: "ai",
        content: "<think>need to search</think>Let me check",
        tool_calls: [{ id: "tc-1", name: "web_search", args: {} }],
      },
    ] as Message[];

    const groups = getMessageGroups(messages);

    // Order: human, assistant bubble (before processing), processing
    expect(groups.map((g) => g.type)).toEqual([
      "human",
      "assistant",
      "assistant:processing",
    ]);

    const assistantGroup = groups.find((g) => g.type === "assistant");
    expect(assistantGroup).toBeDefined();
    // The visible content after stripping <think> should be "Let me check"
    expect(assistantGroup!.messages[0]!.content).toContain("Let me check");

    // The processing group must be the last group (after the assistant bubble)
    // and contain both reasoning and tool_calls.
    const processingGroup = groups.at(-1);
    expect(processingGroup?.type).toBe("assistant:processing");
    expect(processingGroup!.messages).toHaveLength(1);

    const processingMessage = processingGroup!.messages[0]! as AIMessage;
    expect(processingMessage.id).toBe("ai-1");
    // Both reasoning (<think>) and tool_calls must be present
    expect(processingMessage.content).toContain("<think>");
    expect(processingMessage.tool_calls).toBeDefined();
    expect(processingMessage.tool_calls).toHaveLength(1);
  });

  test("plain AI answer without tool_calls produces only an assistant bubble", () => {
    const messages = [
      { id: "human-1", type: "human", content: "Hi" },
      { id: "ai-1", type: "ai", content: "Hello there" },
    ] as Message[];

    const groups = getMessageGroups(messages);
    expect(groups.map((g) => g.type)).toEqual(["human", "assistant"]);
  });

  test("AI message with files presented will not be displayed twice in processing and assistant bubble", () => {
    const messages = [
      { id: "human-1", type: "human", content: "Hi" },
      {
        id: "ai-1",
        type: "ai",
        content: "Here are the files you requested",
        tool_calls: [
          {
            id: "tc-1",
            name: "present_files",
            args: {
              filepaths: ["/path/to/file1.txt", "test.txt"],
            },
          },
        ],
      },
    ] as Message[];

    const groups = getMessageGroups(messages);
    expect(groups.map((g) => g.type)).toEqual([
      "human",
      "assistant:present-files",
    ]);
    expect(groups[1]!.messages).toHaveLength(1);
    expect(groups[1]!.messages[0]!.content).toBe(
      "Here are the files you requested",
    );
    expect(extractPresentFilesFromMessage(groups[1]!.messages[0]!)).toEqual([
      "/path/to/file1.txt",
      "test.txt",
    ]);
  });

  test("present_files tool result attaches to the present-files group", () => {
    const messages = [
      { id: "human-1", type: "human", content: "Show me the report" },
      {
        id: "ai-1",
        type: "ai",
        content: "Here is the report.",
        tool_calls: [
          {
            id: "tc-1",
            name: "present_files",
            args: {
              filepaths: ["/mnt/user-data/outputs/report.md"],
            },
          },
        ],
      },
      {
        id: "tool-1",
        type: "tool",
        name: "present_files",
        tool_call_id: "tc-1",
        content: "Successfully presented files",
      },
    ] as Message[];

    const groups = getMessageGroups(messages);

    expect(groups.map((g) => g.type)).toEqual([
      "human",
      "assistant:present-files",
    ]);
    expect(groups[1]!.messages.map((message) => message.id)).toEqual([
      "ai-1",
      "tool-1",
    ]);
  });

  test("subagent AI message with content creates assistant bubble and subagent group", () => {
    const messages = [
      { id: "human-1", type: "human", content: "Delegate this" },
      {
        id: "ai-1",
        type: "ai",
        content: "Launching a subagent to help.",
        tool_calls: [
          {
            id: "tc-1",
            name: "task",
            args: {
              subagent_type: "general-purpose",
              description: "Inspect the issue",
              prompt: "Inspect the issue",
            },
          },
        ],
      },
    ] as Message[];

    const groups = getMessageGroups(messages);

    expect(groups.map((g) => g.type)).toEqual([
      "human",
      "assistant",
      "assistant:subagent",
    ]);
    expect(groups[1]!.messages.map((message) => message.id)).toEqual(["ai-1"]);
    expect(groups[2]!.messages.map((message) => message.id)).toEqual(["ai-1"]);
  });

  test("subagent tool result attaches to the subagent group", () => {
    const messages = [
      { id: "human-1", type: "human", content: "Delegate this" },
      {
        id: "ai-1",
        type: "ai",
        content: "Launching a subagent to help.",
        tool_calls: [
          {
            id: "tc-1",
            name: "task",
            args: {
              subagent_type: "general-purpose",
              description: "Inspect the issue",
              prompt: "Inspect the issue",
            },
          },
        ],
      },
      {
        id: "tool-1",
        type: "tool",
        name: "task",
        tool_call_id: "tc-1",
        content: "Done",
      },
    ] as Message[];

    const groups = getMessageGroups(messages);

    expect(groups.map((g) => g.type)).toEqual([
      "human",
      "assistant",
      "assistant:subagent",
    ]);
    expect(groups[2]!.messages.map((message) => message.id)).toEqual([
      "ai-1",
      "tool-1",
    ]);
  });
});

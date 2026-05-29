import type { AIMessage, Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "vitest";

import { getMessageGroups } from "@/core/messages/utils";

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

  describe("subagent ordering", () => {
    test("subagent message shows visible content in assistant bubble, then subagent group", () => {
      const messages = [
        { id: "human-1", type: "human", content: "Run a subagent" },
        {
          id: "ai-1",
          type: "ai",
          content: "Launching a subagent to help",
          tool_calls: [{ id: "tc-1", name: "task", args: { subagent_type: "general-purpose" } }],
        },
      ] as Message[];

      const groups = getMessageGroups(messages);

      // hasSubagent is checked before needsProcessing. The user-visible text
      // goes into a regular assistant bubble, then the subagent group is
      // created to collect follow-up tool results. No processing group is
      // needed — the subagent group itself acts as the processing container.
      expect(groups.map((g) => g.type)).toEqual([
        "human",
        "assistant",
        "assistant:subagent",
      ]);

      // The assistant bubble contains the visible text.
      const assistantGroup = groups.find((g) => g.type === "assistant");
      expect(assistantGroup).toBeDefined();
      expect(assistantGroup!.messages[0]!.content).toBe(
        "Launching a subagent to help",
      );
    });

    test("subagent tool result lands in the subagent group", () => {
      const messages = [
        { id: "human-1", type: "human", content: "Run a subagent" },
        {
          id: "ai-1",
          type: "ai",
          content: "Launching a subagent to help",
          tool_calls: [{ id: "tc-1", name: "task", args: { subagent_type: "general-purpose" } }],
        },
        {
          id: "tool-1",
          type: "tool",
          name: "task",
          tool_call_id: "tc-1",
          content: "Subagent completed",
        },
      ] as Message[];

      const groups = getMessageGroups(messages);

      // tool-1 is absorbed by the subagent group (the last open group),
      // not by the processing group.
      const subagentGroup = groups.find((g) => g.type === "assistant:subagent");
      expect(subagentGroup!.messages.map((m) => m.id)).toEqual([
        "ai-1",
        "tool-1",
      ]);

      // Subagent messages skip the generic needsProcessing path, so there
      // is no assistant:processing group — the subagent group itself acts
      // as the tool-result container.
      const processingGroup = groups.find(
        (g) => g.type === "assistant:processing",
      );
      expect(processingGroup).toBeUndefined();
    });

    test("human, plain ai, subagent ai, tool, web_search ai, tool, final ai — mixed turn", () => {
      const messages = [
        { id: "human-1", type: "human", content: "Run a subagent then search" },
        { id: "ai-1", type: "ai", content: "Let me delegate and search" },
        {
          id: "ai-2",
          type: "ai",
          content: "Launching subagent",
          tool_calls: [{ id: "tc-1", name: "task", args: { subagent_type: "general-purpose" } }],
        },
        { id: "tool-1", type: "tool", name: "task", tool_call_id: "tc-1", content: "Subagent done" },
        {
          id: "ai-3",
          type: "ai",
          content: "Now let me search the web",
          tool_calls: [{ id: "tc-2", name: "web_search", args: { query: "test" } }],
        },
        { id: "tool-2", type: "tool", name: "web_search", tool_call_id: "tc-2", content: "Results found" },
        { id: "ai-4", type: "ai", content: "Here is the combined result" },
      ] as Message[];

      const groups = getMessageGroups(messages);

      // Subagent messages (hasSubagent) are checked before needsProcessing.
      // They get a regular assistant bubble for visible text + a subagent
      // group for tool results — no processing group. Regular tool calls
      // (like web_search) still get assistant + processing.
      expect(groups.map((g) => g.type)).toEqual([
        "human",
        "assistant",
        "assistant",
        "assistant:subagent",
        "assistant",
        "assistant:processing",
        "assistant",
      ]);

      // ai-1: plain → own bubble
      expect(groups.find((g) => g.id === "ai-1")!.messages[0]!.id).toBe("ai-1");

      // Subagent assistant bubble: ai-2's visible content is shown.
      const subagentBubble = groups.find((g) => g.id === "ai-2" && g.type === "assistant");
      expect(subagentBubble).toBeDefined();
      expect(subagentBubble!.messages[0]!.content).toBe("Launching subagent");

      // Subagent group: ai-2 + tool-1 (tool result goes to subagent via lastOpenGroup)
      const subagentGroup = groups.find((g) => g.type === "assistant:subagent");
      expect(subagentGroup!.messages.map((m) => m.id)).toEqual(["ai-2", "tool-1"]);

      // The only processing group is for the web_search turn (ai-3 + tool-2).
      // Subagent messages skip the generic needsProcessing path entirely.
      const processingGroups = groups.filter(
        (g) => g.type === "assistant:processing",
      );
      expect(processingGroups).toHaveLength(1);
      expect(processingGroups[0]!.messages.map((m) => m.id)).toEqual([
        "ai-3",
        "tool-2",
      ]);

      // web_search bubble: ai-3 splice'd before its processing group
      const searchBubble = groups.find((g) => g.id === "ai-3");
      expect(searchBubble!.type).toBe("assistant");

      // ai-4: final plain → own bubble
      expect(groups.find((g) => g.id === "ai-4")!.messages[0]!.id).toBe("ai-4");
    });

    test("keeps visible content and attaches tool result for subagent task calls", () => {
      const messages = [
        {
          id: "human-1",
          type: "human",
          content: "Run a subagent",
        },
        {
          id: "ai-1",
          type: "ai",
          content: "Launching a subagent to help",
          tool_calls: [
            {
              id: "tc-1",
              name: "task",
              args: { subagent_type: "general-purpose" },
            },
          ],
        },
        {
          id: "tool-1",
          type: "tool",
          name: "task",
          tool_call_id: "tc-1",
          content: "Subagent completed: found 3 results",
        },
      ] as Message[];

      const groups = getMessageGroups(messages);

      expect(groups.map((group) => group.type)).toEqual([
        "human",
        "assistant",
        "assistant:subagent",
      ]);

      expect(groups[1]!.messages.map((message) => message.id)).toEqual([
        "ai-1",
      ]);

      expect(groups[2]!.messages.map((message) => message.id)).toEqual([
        "ai-1",
        "tool-1",
      ]);
    });
  });

  describe("present-files ordering", () => {
    test("present_files message with visible content shows assistant bubble then file panel", () => {
      const messages = [
        { id: "human-1", type: "human", content: "Show me the files" },
        {
          id: "ai-1",
          type: "ai",
          content: "Here are the files you requested",
          tool_calls: [
            {
              id: "tc-1",
              name: "present_files",
              args: { filepaths: ["/tmp/result.txt"] },
            },
          ],
        },
      ] as Message[];

      const groups = getMessageGroups(messages);

      // Visible text goes into a regular assistant bubble. The present-files
      // group renders the file-list panel below it.
      expect(groups.map((g) => g.type)).toEqual([
        "human",
        "assistant",
        "assistant:present-files",
      ]);

      // Assistant bubble shows the visible text.
      const assistantGroup = groups.find((g) => g.type === "assistant");
      expect(assistantGroup).toBeDefined();
      expect(assistantGroup!.messages[0]!.content).toBe(
        "Here are the files you requested",
      );

      // Present-files group carries the tool-call data for the file panel.
      const presentGroup = groups.find(
        (g) => g.type === "assistant:present-files",
      );
      expect(presentGroup).toBeDefined();
      expect(presentGroup!.messages[0]!.id).toBe("ai-1");
    });
  });
});

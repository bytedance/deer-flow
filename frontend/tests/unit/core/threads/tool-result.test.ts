import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import { hasToolResult } from "@/core/threads/hooks";

test("recognizes a completed tool from its ToolMessage", () => {
  const messages = [
    {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call-1", name: "setup_agent", args: {} }],
    },
    {
      type: "tool",
      content: "Agent saved",
      name: "setup_agent",
      tool_call_id: "call-1",
    },
  ] as Message[];

  expect(hasToolResult(messages, "setup_agent")).toBe(true);
});

test("does not treat a pending call or another tool result as completed", () => {
  const pending = [
    {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call-1", name: "setup_agent", args: {} }],
    },
  ] as Message[];
  const otherTool = [
    {
      type: "tool",
      content: "Done",
      name: "web_search",
      tool_call_id: "call-2",
    },
  ] as Message[];

  expect(hasToolResult(pending, "setup_agent")).toBe(false);
  expect(hasToolResult(otherTool, "setup_agent")).toBe(false);
});

test("matches a ToolMessage without a name through its tool call id", () => {
  const messages = [
    {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call-1", name: "setup_agent", args: {} }],
    },
    {
      type: "tool",
      content: "Agent saved",
      tool_call_id: "call-1",
    },
  ] as Message[];

  expect(hasToolResult(messages, "setup_agent")).toBe(true);
});

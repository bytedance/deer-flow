import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import { getToolResultStatus, hasToolResult } from "@/core/threads/hooks";

test.each(["success", "error", "pending"] as const)(
  "a unique setup call resolves its leading result as %s",
  (status) => {
    const messages: Message[] = [
      ...(status === "pending"
        ? []
        : [
            {
              type: "tool",
              tool_call_id: "call_0",
              name: "setup_agent",
              content:
                status === "error" ? "Error: save failed" : "Agent saved",
              status,
            } as Message,
          ]),
      {
        type: "ai",
        id: "setup",
        content: "",
        tool_calls: [{ id: "call_0", name: "setup_agent", args: {} }],
      },
    ];
    expect(getToolResultStatus(messages, "setup_agent")).toBe(status);
  },
);

test("a setup result before a human boundary cannot finish the next turn", () => {
  const messages = [
    { type: "tool", tool_call_id: "call_0", content: "Agent saved" },
    { type: "human", content: "Try again" },
    {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call_0", name: "setup_agent", args: {} }],
    },
  ] as Message[];
  expect(getToolResultStatus(messages, "setup_agent")).toBe("pending");
});

test.each([false, true])(
  "an unrelated assistant fences setup status (leading=%s)",
  (leading) => {
    const owner = {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call_0", name: "setup_agent", args: {} }],
    } as Message;
    const other = { type: "ai", content: "An unrelated answer" } as Message;
    const result = {
      type: "tool",
      tool_call_id: "call_0",
      content: "Agent saved",
    } as Message;
    expect(
      getToolResultStatus(
        leading ? [result, other, owner] : [owner, other, result],
        "setup_agent",
      ),
    ).toBe("pending");
  },
);

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

test("reports a failed tool result instead of treating it as a successful save", () => {
  const messages = [
    {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call-1", name: "setup_agent", args: {} }],
    },
    {
      type: "tool",
      content: "Error: unable to save agent",
      name: "setup_agent",
      tool_call_id: "call-1",
      status: "error",
    },
  ] as Message[];

  expect(getToolResultStatus(messages, "setup_agent")).toBe("error");
});

test("honors structured DeerFlow error metadata", () => {
  const messages = [
    {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call-1", name: "setup_agent", args: {} }],
    },
    {
      type: "tool",
      content: "Agent storage is unavailable",
      name: "setup_agent",
      tool_call_id: "call-1",
      additional_kwargs: {
        deerflow_tool_meta: { status: "error" },
      },
    },
  ] as Message[];

  expect(getToolResultStatus(messages, "setup_agent")).toBe("error");
});

test("waits for the latest setup attempt instead of reusing an older success", () => {
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
    {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call-2", name: "setup_agent", args: {} }],
    },
  ] as Message[];

  expect(getToolResultStatus(messages, "setup_agent")).toBe("pending");
});

test("another tool reusing a provider id cannot replace the setup result", () => {
  const messages = [
    {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call_0", name: "setup_agent", args: {} }],
    },
    { type: "tool", tool_call_id: "call_0", content: "Saved" },
    {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call_0", name: "web_search", args: {} }],
    },
    {
      type: "tool",
      tool_call_id: "call_0",
      content: "Error: failed",
      status: "error",
    },
  ] as Message[];
  expect(getToolResultStatus(messages, "setup_agent")).toBe("success");
});

test("a reused provider id cannot complete a new pending setup attempt", () => {
  const messages = [
    {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call_0", name: "setup_agent", args: {} }],
    },
    { type: "tool", tool_call_id: "call_0", content: "Saved" },
    {
      type: "ai",
      content: "",
      tool_calls: [{ id: "call_0", name: "setup_agent", args: {} }],
    },
  ] as Message[];
  expect(getToolResultStatus(messages, "setup_agent")).toBe("pending");
});

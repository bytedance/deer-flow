import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "vitest";

import {
  convertToToolCallSteps,
  partitionStepsForDisplay,
} from "@/core/tools/utils";

function aiMessage(
  id: string,
  toolCalls: { id: string; name: string; args?: Record<string, unknown> }[],
  reasoning?: string,
): Message {
  return {
    type: "ai",
    id,
    content: "",
    tool_calls: toolCalls.map((tc) => ({
      id: tc.id,
      name: tc.name,
      args: tc.args ?? {},
    })),
    additional_kwargs: reasoning ? { reasoning_content: reasoning } : {},
  } as Message;
}

function toolMessage(toolCallId: string, content: string): Message {
  return {
    type: "tool",
    id: `tool-msg-${toolCallId}`,
    tool_call_id: toolCallId,
    content,
  } as Message;
}

test("a single tool call in the latest AI message stays the only active step", () => {
  const messages: Message[] = [
    aiMessage("ai-1", [
      { id: "call-1", name: "web_search", args: { query: "x" } },
    ]),
    toolMessage("call-1", "[]"),
    aiMessage("ai-2", [
      { id: "call-2", name: "web_fetch", args: { url: "u" } },
    ]),
  ];
  const steps = convertToToolCallSteps(messages);
  const { aboveSteps, activeSteps } = partitionStepsForDisplay(steps);

  expect(activeSteps.map((s) => s.id)).toEqual(["call-2"]);
  expect(aboveSteps.map((s) => s.id)).toEqual(["call-1"]);
});

test("all parallel siblings stay active until each one completes", () => {
  const messages: Message[] = [
    aiMessage("ai-1", [
      { id: "call-1", name: "web_search", args: { query: "a" } },
      { id: "call-2", name: "web_search", args: { query: "b" } },
      { id: "call-3", name: "web_search", args: { query: "c" } },
    ]),
    toolMessage("call-2", "[]"),
  ];
  const steps = convertToToolCallSteps(messages);
  const { aboveSteps, activeSteps } = partitionStepsForDisplay(steps);

  expect(activeSteps.map((s) => s.id)).toEqual(["call-1", "call-2", "call-3"]);
  expect(aboveSteps).toEqual([]);
});

test("parallel tool results pair by tool_call_id regardless of arrival order", () => {
  const messages: Message[] = [
    aiMessage("ai-1", [
      { id: "call-1", name: "web_search", args: { query: "a" } },
      { id: "call-2", name: "web_search", args: { query: "b" } },
    ]),
    toolMessage("call-2", '[{"url":"u2","title":"t2"}]'),
    toolMessage("call-1", '[{"url":"u1","title":"t1"}]'),
  ];
  const steps = convertToToolCallSteps(messages);
  const toolSteps = steps.filter((s) => s.type === "toolCall");
  const byId = new Map(toolSteps.map((s) => [s.id, s]));
  expect(byId.get("call-1")?.result).toEqual([{ url: "u1", title: "t1" }]);
  expect(byId.get("call-2")?.result).toEqual([{ url: "u2", title: "t2" }]);
});

test("reasoning emitted with parallel tool calls stays visible above the active batch", () => {
  const messages: Message[] = [
    aiMessage(
      "ai-1",
      [
        { id: "call-1", name: "web_search", args: { query: "a" } },
        { id: "call-2", name: "web_search", args: { query: "b" } },
      ],
      "considering both queries in parallel",
    ),
  ];
  const steps = convertToToolCallSteps(messages);
  const { aboveSteps, activeSteps } = partitionStepsForDisplay(steps);

  expect(aboveSteps.map((s) => s.type)).toEqual(["reasoning"]);
  expect(activeSteps.map((s) => s.id)).toEqual(["call-1", "call-2"]);
});

test("earlier serial tool calls collapse above a fresh parallel batch", () => {
  const messages: Message[] = [
    aiMessage("ai-1", [{ id: "call-0", name: "ls", args: { path: "/" } }]),
    toolMessage("call-0", "ok"),
    aiMessage("ai-2", [
      { id: "call-1", name: "web_search", args: { query: "a" } },
      { id: "call-2", name: "web_search", args: { query: "b" } },
    ]),
  ];
  const steps = convertToToolCallSteps(messages);
  const { aboveSteps, activeSteps } = partitionStepsForDisplay(steps);

  expect(aboveSteps.map((s) => s.id)).toEqual(["call-0"]);
  expect(activeSteps.map((s) => s.id)).toEqual(["call-1", "call-2"]);
});

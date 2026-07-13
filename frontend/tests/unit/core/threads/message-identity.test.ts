import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import { messageIdentity } from "@/core/threads/message-identity";

// ---------------------------------------------------------------------------
// messageIdentity
// ---------------------------------------------------------------------------

test("returns tool:<tool_call_id> for tool messages", () => {
  const tool = {
    type: "tool",
    id: "t1",
    tool_call_id: "tc-1",
    content: "result",
    name: "search",
  } as unknown as Message;

  expect(messageIdentity(tool)).toBe("tool:tc-1");
});

test("prefers tool_call_id over id when both are present", () => {
  // A tool message that also carries an id must still key off tool_call_id —
  // otherwise an AI message sharing the same id would collide and be wrongly
  // dropped downstream.
  const tool = {
    type: "tool",
    id: "shared-id",
    tool_call_id: "tc-shared",
    content: "result",
  } as unknown as Message;

  expect(messageIdentity(tool)).toBe("tool:tc-shared");
});

test("returns message:<id> for non-tool messages", () => {
  const human = { type: "human", id: "m1", content: "hello" } as Message;
  const ai = { type: "ai", id: "m2", content: "hi" } as Message;

  expect(messageIdentity(human)).toBe("message:m1");
  expect(messageIdentity(ai)).toBe("message:m2");
});

test("treats empty string tool_call_id as missing and falls back to id", () => {
  const tool = {
    type: "tool",
    id: "t1",
    tool_call_id: "",
    content: "result",
  } as unknown as Message;

  expect(messageIdentity(tool)).toBe("message:t1");
});

test("returns undefined when neither tool_call_id nor id is usable", () => {
  const noId = { type: "ai", content: "no id" } as Message;

  expect(messageIdentity(noId)).toBeUndefined();
});

test("uses namespacing so equal id strings in different roles do not collide", () => {
  // Existing tool with tool_call_id="tc-x" and incoming AI with id="tc-x"
  // must produce different identity strings, otherwise the AI message would
  // be incorrectly filtered as a duplicate of the tool message.
  const existingTool = {
    type: "tool",
    id: "t0",
    tool_call_id: "tc-x",
    content: "result",
  } as unknown as Message;
  const incomingAi = { type: "ai", id: "tc-x", content: "response" } as Message;

  expect(messageIdentity(existingTool)).toBe("tool:tc-x");
  expect(messageIdentity(incomingAi)).toBe("message:tc-x");
  expect(messageIdentity(existingTool)).not.toBe(messageIdentity(incomingAi));
});

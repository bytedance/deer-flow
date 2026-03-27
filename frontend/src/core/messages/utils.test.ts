import assert from "node:assert/strict";
import test from "node:test";

const { extractTextFromMessage, groupMessages } = await import(
  new URL("./utils.ts", import.meta.url).href,
);

void test("groups orphan tool messages into a standalone assistant tool group", () => {
  const messages = [
    {
      type: "tool",
      id: "tool-1",
      tool_call_id: "call-1",
      name: "bash",
      content: "command output",
    },
  ];

  const groups = groupMessages(messages as never, (group) => ({
    type: group.type,
    texts: group.messages.map((message) => extractTextFromMessage(message)),
  }));

  assert.deepEqual(groups, [
    {
      type: "assistant:tool",
      texts: ["command output"],
    },
  ]);
});

void test("keeps clarification tool messages in their dedicated group", () => {
  const messages = [
    {
      type: "tool",
      id: "tool-clarify",
      tool_call_id: "call-clarify",
      name: "ask_clarification",
      content: "Which environment should I use?",
    },
  ];

  const groups = groupMessages(messages as never, (group) => group.type);

  assert.deepEqual(groups, ["assistant:clarification"]);
});

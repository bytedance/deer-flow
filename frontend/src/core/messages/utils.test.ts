import assert from "node:assert/strict";
import test from "node:test";

const { extractContentFromMessage, normalizeRawActionBlocks } = await import(
  new URL("./utils.ts", import.meta.url).href
);

void test("normalizes raw action blocks into fenced xml", () => {
  const normalized = normalizeRawActionBlocks(
    [
      "Let me inspect that.",
      "",
      '<action_call> { "action": "read_file" } </action_call>',
      "",
      '<action_result> { "content": "ok" } </action_result>',
    ].join("\n"),
  );

  assert.match(
    normalized,
    /```xml\n<action_call>\n\{ "action": "read_file" \}\n<\/action_call>\n```/,
  );
  assert.match(
    normalized,
    /```xml\n<action_result>\n\{ "content": "ok" \}\n<\/action_result>\n```/,
  );
});

void test("extractContentFromMessage sanitizes raw action markup for ai messages", () => {
  const content = extractContentFromMessage({
    type: "ai",
    content: '<action_call> { "action": "read_file" } </action_call>',
  });

  assert.equal(
    content,
    ['```xml', "<action_call>", '{ "action": "read_file" }', "</action_call>", "```"].join(
      "\n",
    ),
  );
});

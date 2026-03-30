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

void test("normalizeRawActionBlocks returns content unchanged when no action blocks present", () => {
  const input = "Here is a plain message without any action tags.";
  assert.equal(normalizeRawActionBlocks(input), input);
});

void test("normalizeRawActionBlocks wraps action_result blocks too", () => {
  const normalized = normalizeRawActionBlocks(
    '<action_result> { "status": "done" } </action_result>',
  );

  assert.match(
    normalized,
    /```xml\n<action_result>\n\{ "status": "done" \}\n<\/action_result>\n```/,
  );
});

void test("normalizeRawActionBlocks wraps multiple consecutive blocks", () => {
  const input = [
    '<action_call> { "action": "bash" } </action_call>',
    "",
    '<action_result> { "output": "ok" } </action_result>',
  ].join("\n");

  const normalized = normalizeRawActionBlocks(input);

  assert.match(normalized, /```xml\n<action_call>/);
  assert.match(normalized, /```xml\n<action_result>/);
});

void test("normalizeRawActionBlocks trims leading and trailing whitespace from body", () => {
  const normalized = normalizeRawActionBlocks(
    "<action_call>   \n  trimmed   \n  </action_call>",
  );

  assert.match(normalized, /```xml\n<action_call>\ntrimmed\n<\/action_call>\n```/);
});

void test("normalizeRawActionBlocks preserves multiline JSON body", () => {
  const body = '{\n  "action": "read_file",\n  "path": "/tmp/a.txt"\n}';
  const normalized = normalizeRawActionBlocks(`<action_call>${body}</action_call>`);

  assert.ok(normalized.includes(body.trim()), "multiline body should be preserved");
});

void test("extractContentFromMessage returns content unchanged for non-ai messages", () => {
  const content = extractContentFromMessage({
    type: "tool",
    content: "tool result",
  });

  assert.equal(content, "tool result");
});

void test("extractContentFromMessage returns empty string for empty ai message", () => {
  const content = extractContentFromMessage({ type: "ai", content: "" });
  assert.equal(content, "");
});

void test("extractContentFromMessage sanitizes action_result blocks", () => {
  const content = extractContentFromMessage({
    type: "ai",
    content: '<action_result> { "output": "done" } </action_result>',
  });

  assert.match(content, /```xml\n<action_result>/);
});

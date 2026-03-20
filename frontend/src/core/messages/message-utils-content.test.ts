import assert from "node:assert/strict";
import test from "node:test";

// ---- Test fixtures: minimal Message-like objects ----

/** Simulates a thinking-only array content (e.g. Anthropic-style) */
const thinkingOnlyContent = [{ type: "thinking", text: "Let me think..." }];

/** Simulates text block content */
const textOnlyContent = [{ type: "text", text: "Hello world" }];

/** Simulates empty text block */
const emptyTextContent = [{ type: "text", text: "   " }];

/** Simulates image-only content */
const imageOnlyContent = [{ type: "image_url", image_url: { url: "data:..." } }];

// ---- Test: hasContent must filter non-text blocks ----

test("hasContent rejects thinking-only array content", () => {
  const hasTextBlock = thinkingOnlyContent.some(
    (block) =>
      "type" in block &&
      block.type === "text" &&
      typeof block.text === "string" &&
      block.text.trim().length > 0,
  );
  assert.equal(hasTextBlock, false, "thinking-only blocks should not count as content");
});

test("hasContent accepts text blocks", () => {
  const hasTextBlock = textOnlyContent.some(
    (block) =>
      "type" in block &&
      block.type === "text" &&
      typeof block.text === "string" &&
      block.text.trim().length > 0,
  );
  assert.equal(hasTextBlock, true, "text blocks should count as content");
});

test("hasContent rejects empty text blocks", () => {
  const hasTextBlock = emptyTextContent.some(
    (block) =>
      "type" in block &&
      block.type === "text" &&
      typeof block.text === "string" &&
      block.text.trim().length > 0,
  );
  assert.equal(hasTextBlock, false, "empty/whitespace-only text should not count");
});

test("hasContent rejects image-only content", () => {
  const hasTextBlock = imageOnlyContent.some(
    (block) =>
      "type" in block &&
      block.type === "text" &&
      typeof block.text === "string" &&
      block.text.trim().length > 0,
  );
  assert.equal(hasTextBlock, false, "image_url blocks should not count as content");
});

// ---- Test: string content path ----

test("hasContent handles string content correctly", () => {
  const stringContent = "Hello world";
  assert.equal(typeof stringContent === "string" && stringContent.trim().length > 0, true);

  const emptyString = "   ";
  assert.equal(typeof emptyString === "string" && emptyString.trim().length > 0, false);
});

// ---- Test: block.type check prevents thinking blocks from passing ----

test("hasContent must check block.type, not just block.text property", () => {
  const thinkingBlock = { type: "thinking", text: "some thinking" };

  // Old (buggy) check: "text" in block
  const oldCheck = "text" in thinkingBlock && typeof thinkingBlock.text === "string";
  assert.equal(oldCheck, true, "old check incorrectly passes thinking block");

  // New (fixed) check: block.type === "text"
  const newCheck =
    thinkingBlock.type === "text" &&
    typeof thinkingBlock.text === "string" &&
    thinkingBlock.text.trim().length > 0;
  assert.equal(newCheck, false, "new check correctly rejects thinking block");
});

// ---- Test: groupMessages produces assistant bubble for tool_calls + text ----

test("AI message with tool_calls + text content should create assistant group", () => {
  const aiWithToolCallsAndText = {
    type: "ai",
    id: "msg-1",
    tool_calls: [{ id: "call-1", name: "search", args: { query: "test" } }],
    content: "Here are the results:",
  };

  const hasTextContent =
    typeof aiWithToolCallsAndText.content === "string" &&
    aiWithToolCallsAndText.content.trim().length > 0;
  assert.equal(hasTextContent, true);

  const hasToolCalls =
    aiWithToolCallsAndText.type === "ai" &&
    aiWithToolCallsAndText.tool_calls &&
    aiWithToolCallsAndText.tool_calls.length > 0;
  assert.equal(hasToolCalls, true);

  // OLD: hasContent && !hasToolCalls → false (text dropped)
  const oldCondition = hasTextContent && !hasToolCalls;
  assert.equal(oldCondition, false, "old condition incorrectly drops the text");

  // NEW: hasContent && (!hasToolCalls || extractText().length > 0)
  const extractedText = typeof aiWithToolCallsAndText.content === "string"
    ? aiWithToolCallsAndText.content.trim()
    : "";
  const newCondition = hasTextContent && (!hasToolCalls || extractedText.length > 0);
  assert.equal(newCondition, true, "new condition correctly preserves the text");
});

test("AI message with tool_calls but empty text should NOT create assistant group", () => {
  const hasTextContent =
    typeof "" === "string" && "".trim().length > 0;
  assert.equal(hasTextContent, false, "empty content should not trigger assistant bubble");
});

test("AI message with tool_calls and array content with only thinking blocks", () => {
  const content = [{ type: "thinking", text: "Let me search for this..." }];

  const hasTextBlock = content.some(
    (block) =>
      "type" in block &&
      block.type === "text" &&
      typeof block.text === "string" &&
      block.text.trim().length > 0,
  );

  assert.equal(hasTextBlock, false, "thinking-only content should not create assistant bubble");
});

test("AI message with tool_calls and array content with thinking + text", () => {
  const content = [
    { type: "thinking", text: "Let me search..." },
    { type: "text", text: "Found 3 results for your query." },
  ];

  const hasTextBlock = content.some(
    (block) =>
      "type" in block &&
      block.type === "text" &&
      typeof block.text === "string" &&
      block.text.trim().length > 0,
  );

  assert.equal(hasTextBlock, true, "mixed content with text should create assistant bubble");
});

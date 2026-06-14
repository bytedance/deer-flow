import assert from "node:assert/strict";
import test from "node:test";

// Import production functions
const { hasContent, groupMessages, extractTextFromMessage } = await import(
  new URL("./utils.ts", import.meta.url).href
);

// ---- Test: hasContent filters non-text blocks ----

test("hasContent rejects thinking-only array content", () => {
  const message = {
    type: "ai" as const,
    id: "msg-1",
    content: [{ type: "thinking", text: "Let me think..." }],
  };
  assert.equal(hasContent(message), false);
});

test("hasContent accepts text blocks", () => {
  const message = {
    type: "ai" as const,
    id: "msg-1",
    content: [{ type: "text", text: "Hello world" }],
  };
  assert.equal(hasContent(message), true);
});

test("hasContent rejects empty/whitespace text blocks", () => {
  const message = {
    type: "ai" as const,
    id: "msg-1",
    content: [{ type: "text", text: "   " }],
  };
  assert.equal(hasContent(message), false);
});

test("hasContent accepts image_url blocks with valid URL", () => {
  const message = {
    type: "ai" as const,
    id: "msg-1",
    content: [{ type: "image_url", image_url: { url: "https://example.com/img.png" } }],
  };
  assert.equal(hasContent(message), true);
});

test("hasContent rejects empty array", () => {
  const message = {
    type: "ai" as const,
    id: "msg-1",
    content: [],
  };
  assert.equal(hasContent(message), false);
});

test("hasContent handles string content correctly", () => {
  assert.equal(
    hasContent({ type: "ai", id: "m", content: "Hello world" } as any),
    true,
  );
  assert.equal(
    hasContent({ type: "ai", id: "m", content: "   " } as any),
    false,
  );
});

test("hasContent accepts mixed thinking + text blocks", () => {
  const message = {
    type: "ai" as const,
    id: "msg-1",
    content: [
      { type: "thinking", text: "reasoning..." },
      { type: "text", text: "Here is the answer." },
    ],
  };
  assert.equal(hasContent(message), true);
});

// ---- Test: groupMessages for tool_calls + text scenario ----
//
// When an AI message has both tool_calls and text, the text is deferred:
// the message goes to the processing group (with tool_calls), and the text
// is displayed when the final AI message (no tool_calls) arrives.
// This prevents creating a terminal assistant group that would break tool message attachment.

test("AI message with tool_calls + text goes to processing group", () => {
  const messages = [
    {
      type: "human" as const,
      id: "h1",
      content: "search for cats",
    },
    {
      type: "ai" as const,
      id: "ai1",
      tool_calls: [{ id: "call-1", name: "search", args: { query: "cats" } }],
      content: "Here are the results:",
    },
    {
      type: "tool" as const,
      id: "t1",
      tool_call_id: "call-1",
      name: "search",
      content: "Cat results...",
    },
  ];

  const groups = groupMessages(messages, (g) => g);

  // AI with tool_calls goes to processing group AND creates an assistant bubble for text
  const processingGroup = groups.find((g) => g.type === "assistant:processing");
  assert.ok(processingGroup, "should create a processing group for tool_calls");
  assert.equal(processingGroup!.messages.length, 2, "processing group should contain AI + tool messages");

  // Text content also creates an assistant group (backward search keeps tool attachment working)
  const assistantGroup = groups.find((g) => g.type === "assistant");
  assert.ok(assistantGroup, "should create assistant group to show text content");
  assert.equal(assistantGroup!.messages[0].id, "ai1", "assistant group should contain the AI message with text");
});

test("full conversation: tool_calls + text, then final AI answer shows text", () => {
  const messages = [
    {
      type: "human" as const,
      id: "h1",
      content: "search for cats",
    },
    {
      type: "ai" as const,
      id: "ai1",
      tool_calls: [{ id: "call-1", name: "search", args: { query: "cats" } }],
      content: "Let me search...",
    },
    {
      type: "tool" as const,
      id: "t1",
      tool_call_id: "call-1",
      name: "search",
      content: "Cat results: fluffy, tabby",
    },
    {
      type: "ai" as const,
      id: "ai2",
      content: "Here are the cat results I found.",
    },
  ];

  const groups = groupMessages(messages, (g) => g);

  // Both ai1 (tool_calls + text) and ai2 (final answer) create assistant groups
  const assistantGroups = groups.filter((g) => g.type === "assistant");
  assert.equal(assistantGroups.length, 2, "both AI messages with content should create assistant groups");
  assert.equal(assistantGroups[0].messages[0].id, "ai1");
  assert.equal(assistantGroups[1].messages[0].id, "ai2");

  // Tool message still attaches to processing group (backward search)
  const processingGroup = groups.find((g) => g.type === "assistant:processing");
  assert.ok(processingGroup, "processing group should exist");
  assert.equal(processingGroup!.messages.length, 2, "processing group should contain AI + tool messages");
});

test("AI message with tool_calls but empty text does NOT create assistant group", () => {
  const messages = [
    {
      type: "human" as const,
      id: "h1",
      content: "search",
    },
    {
      type: "ai" as const,
      id: "ai1",
      tool_calls: [{ id: "call-1", name: "search", args: {} }],
      content: "",
    },
  ];

  const groups = groupMessages(messages, (g) => g);
  const assistantGroup = groups.find((g) => g.type === "assistant");
  assert.equal(assistantGroup, undefined, "should not create assistant group for empty text");
});

test("AI message with tool_calls + thinking-only does NOT create assistant group", () => {
  const messages = [
    {
      type: "human" as const,
      id: "h1",
      content: "search",
    },
    {
      type: "ai" as const,
      id: "ai1",
      tool_calls: [{ id: "call-1", name: "search", args: {} }],
      content: [{ type: "thinking", text: "Let me search..." }],
    },
  ];

  const groups = groupMessages(messages, (g) => g);
  const assistantGroup = groups.find((g) => g.type === "assistant");
  assert.equal(assistantGroup, undefined, "should not create assistant group for thinking-only");
});

test("AI message with tool_calls + thinking + text goes to processing group", () => {
  const messages = [
    {
      type: "human" as const,
      id: "h1",
      content: "search",
    },
    {
      type: "ai" as const,
      id: "ai1",
      tool_calls: [{ id: "call-1", name: "search", args: {} }],
      content: [
        { type: "thinking", text: "Let me search..." },
        { type: "text", text: "Found 3 results." },
      ],
    },
  ];

  const groups = groupMessages(messages, (g) => g);
  const processingGroup = groups.find((g) => g.type === "assistant:processing");
  assert.ok(processingGroup, "should go to processing group (has tool_calls)");
  const assistantGroup = groups.find((g) => g.type === "assistant");
  assert.ok(assistantGroup, "should create assistant group for text content even with tool_calls");
});

test("AI message without tool_calls + text creates assistant group (no regression)", () => {
  const messages = [
    {
      type: "human" as const,
      id: "h1",
      content: "hello",
    },
    {
      type: "ai" as const,
      id: "ai1",
      content: "Hi there!",
    },
  ];

  const groups = groupMessages(messages, (g) => g);
  const assistantGroup = groups.find((g) => g.type === "assistant");
  assert.ok(assistantGroup, "simple text-only AI message should still create assistant group");
});

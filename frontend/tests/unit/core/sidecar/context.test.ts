import { expect, rs, test } from "@rstest/core";

import {
  buildMessageSidecarContext,
  buildParentConversationContext,
  buildSidecarContextPrompt,
} from "@/core/sidecar/context";

test("builds message sidecar context with a readable label", () => {
  const context = buildMessageSidecarContext(
    { type: "ai", id: "msg-1", content: "A focused answer." },
    3,
  );

  expect(context).toMatchObject({
    type: "referenced_message",
    label: "Assistant message #3",
    messageId: "msg-1",
    role: "assistant",
    content: "A focused answer.",
  });
});

test("builds sidecar context from selected text", () => {
  const context = buildMessageSidecarContext(
    {
      type: "ai",
      id: "msg-1",
      content: "The full answer includes more detail.",
    },
    2,
    { selectedText: "includes more detail" },
  );

  expect(context).toMatchObject({
    type: "referenced_message",
    label: "Selected assistant text #2",
    messageId: "msg-1",
    role: "assistant",
    content: "includes more detail",
  });
});

test("renders hidden sidecar context prompt around quoted material", () => {
  const prompt = buildSidecarContextPrompt({
    type: "referenced_message",
    label: "Selected assistant text #2",
    messageId: "msg-1",
    role: "assistant",
    content: "A side conversation panel.",
  });

  expect(prompt).toContain("You are answering in a side conversation");
  expect(prompt).toContain(
    '<referenced_message index="1" label="Selected assistant text #2">',
  );
  expect(prompt).toContain("Message ID: msg-1");
  expect(prompt).toContain("A side conversation panel.");
});

test("renders hidden sidecar context prompt around multiple quoted materials", () => {
  const prompt = buildSidecarContextPrompt([
    {
      type: "referenced_message",
      label: "Selected assistant text #2",
      messageId: "msg-1",
      role: "assistant",
      content: "First quoted fragment.",
    },
    {
      type: "referenced_message",
      label: "Selected user text #3",
      messageId: "msg-2",
      role: "user",
      content: "Second quoted fragment.",
    },
  ] as never);

  expect(prompt).toContain('referenced_message index="1"');
  expect(prompt).toContain('referenced_message index="2"');
  expect(prompt).toContain("First quoted fragment.");
  expect(prompt).toContain("Second quoted fragment.");
});

test("builds compact parent conversation context from visible messages", () => {
  const parentContext = buildParentConversationContext([
    {
      type: "human",
      id: "parent-human-1",
      content: "Plan the feature.",
    },
    {
      type: "human",
      id: "hidden-context",
      content: "Hidden implementation note.",
      additional_kwargs: { hide_from_ui: true },
    },
    {
      type: "ai",
      id: "parent-ai-1",
      content: "Use a side conversation with cited snippets.",
    },
  ] as never);

  expect(parentContext).toEqual([
    {
      role: "user",
      messageId: "parent-human-1",
      content: "Plan the feature.",
    },
    {
      role: "assistant",
      messageId: "parent-ai-1",
      content: "Use a side conversation with cited snippets.",
    },
  ]);
});

test("renders parent conversation as read-only background in sidecar prompt", () => {
  const prompt = buildSidecarContextPrompt(
    [
      {
        type: "referenced_message",
        label: "Selected assistant text #2",
        messageId: "msg-1",
        role: "assistant",
        content: "Quoted fragment.",
      },
    ] as never,
    {
      parentConversation: [
        {
          role: "user",
          messageId: "parent-human-1",
          content: "Plan the feature.",
        },
        {
          role: "assistant",
          messageId: "parent-ai-1",
          content: "Use a side conversation.",
        },
      ],
    },
  );

  expect(prompt).toContain("<parent_conversation_context");
  expect(prompt).toContain(
    '<parent_message index="1" role="User" message_id="parent-human-1">',
  );
  expect(prompt).toContain("Plan the feature.");
  expect(prompt).toContain("Use a side conversation.");
  expect(prompt).toContain('referenced_message index="1"');
});

test("renders parent conversation for sidecar follow-ups without new references", () => {
  const prompt = buildSidecarContextPrompt([], {
    parentConversation: [
      {
        role: "assistant",
        messageId: "parent-ai-1",
        content: "Use a side conversation.",
      },
    ],
  });

  expect(prompt).toContain(
    "The user did not attach new referenced messages for this side question.",
  );
  expect(prompt).toContain(
    "Use parent_conversation_context only as continuity background",
  );
  expect(prompt).toContain("<parent_conversation_context");
  expect(prompt).toContain("Use a side conversation.");
  expect(prompt).not.toContain("<referenced_message");
});

test("truncates parent conversation by code points without splitting an emoji", () => {
  const parentContext = buildParentConversationContext(
    [
      {
        type: "ai",
        id: "parent-ai-emoji",
        content: "a😀bc",
      },
    ] as never,
    { maxCharsPerMessage: 2 },
  );

  expect(parentContext).toEqual([
    {
      role: "assistant",
      messageId: "parent-ai-emoji",
      content: "a😀\n[truncated]",
    },
  ]);
});

test("does not truncate when emoji count fits the code-point budget", () => {
  const content = "😀".repeat(1200);
  const parentContext = buildParentConversationContext(
    [{ type: "ai", id: "parent-ai-many-emoji", content }] as never,
    { maxCharsPerMessage: 1200, maxTotalChars: 1200 },
  );

  expect(parentContext).toEqual([
    {
      role: "assistant",
      messageId: "parent-ai-many-emoji",
      content,
    },
  ]);
});

test("does not truncate when the total code-point budget includes complete emoji", () => {
  const content = "😀".repeat(1200);
  const parentContext = buildParentConversationContext(
    [{ type: "ai", id: "parent-ai-total-emoji", content }] as never,
    { maxCharsPerMessage: 5000, maxTotalChars: 1200 },
  );

  expect(parentContext).toEqual([
    {
      role: "assistant",
      messageId: "parent-ai-total-emoji",
      content,
    },
  ]);
});

test("truncates an emoji-only message to the marker at a zero budget", () => {
  const parentContext = buildParentConversationContext(
    [{ type: "ai", id: "parent-ai-zero-budget", content: "😀" }] as never,
    { maxCharsPerMessage: 0, maxTotalChars: 10 },
  );

  expect(parentContext).toEqual([
    {
      role: "assistant",
      messageId: "parent-ai-zero-budget",
      content: "\n[truncated]",
    },
  ]);
});

test("shares the total budget across messages by code point", () => {
  const parentContext = buildParentConversationContext(
    [
      { type: "human", id: "parent-human-budget", content: "😀" },
      { type: "ai", id: "parent-ai-budget", content: "😀😀" },
    ] as never,
    { maxCharsPerMessage: 100, maxTotalChars: 3 },
  );

  expect(parentContext).toEqual([
    {
      role: "user",
      messageId: "parent-human-budget",
      content: "😀",
    },
    {
      role: "assistant",
      messageId: "parent-ai-budget",
      content: "😀😀",
    },
  ]);
});
test("does not materialize an unbounded parent message", () => {
  const content = `😀${"a".repeat(1_000_000)}`;
  const from = rs.spyOn(Array, "from");
  let rawContentReads = 0;
  let result: ReturnType<typeof buildParentConversationContext>;
  try {
    result = buildParentConversationContext(
      [{ type: "ai", id: "parent-ai-large", content }] as never,
      { maxCharsPerMessage: 2, maxTotalChars: 2 },
    );
    rawContentReads = from.mock.calls.filter(
      ([value]) => value === content,
    ).length;
  } finally {
    from.mockRestore();
  }

  expect(rawContentReads).toBe(0);
  expect(result![0]?.content).toBe("😀a\n[truncated]");
});
test("does not materialize a large message that fits its budget", () => {
  const content = "a".repeat(1_000_000);
  const from = rs.spyOn(Array, "from");
  let rawContentReads = 0;
  let result: ReturnType<typeof buildParentConversationContext>;
  try {
    result = buildParentConversationContext(
      [{ type: "ai", id: "parent-ai-fit", content }] as never,
      { maxCharsPerMessage: 2_000_000, maxTotalChars: 2_000_000 },
    );
    rawContentReads = from.mock.calls.filter(
      ([value]) => value === content,
    ).length;
  } finally {
    from.mockRestore();
  }

  expect(rawContentReads).toBe(0);
  expect(result![0]?.content).toBe(content);
});
test("counts the truncation marker by code point after a truncated message", () => {
  const parentContext = buildParentConversationContext(
    [
      { type: "human", id: "parent-human-marker", content: "x" },
      { type: "ai", id: "parent-ai-marker", content: "😀😀😀" },
    ] as never,
    { maxCharsPerMessage: 1, maxTotalChars: 14 },
  );

  expect(parentContext).toEqual([
    {
      role: "user",
      messageId: "parent-human-marker",
      content: "x",
    },
    {
      role: "assistant",
      messageId: "parent-ai-marker",
      content: "😀\n[truncated]",
    },
  ]);
});
test.each([
  { content: "😀😀😀", budget: 1 },
  { content: "a😀b😀c", budget: 3 },
  { content: "😀   trailing", budget: 1 },
])(
  "accumulates the actual truncated output for $content at budget $budget",
  ({ content, budget }) => {
    const [truncatedMessage] = buildParentConversationContext(
      [{ type: "ai", id: "ai", content }] as never,
      { maxCharsPerMessage: budget, maxTotalChars: 10_000 },
    );
    expect(truncatedMessage).toBeDefined();
    const truncated = truncatedMessage!.content;

    const parentContext = buildParentConversationContext(
      [
        { type: "human", id: "human", content: "x" },
        { type: "ai", id: "ai", content },
      ] as never,
      {
        maxCharsPerMessage: budget,
        maxTotalChars: Array.from(truncated).length + 1,
      },
    );

    expect(parentContext.map((message) => message.messageId)).toEqual([
      "human",
      "ai",
    ]);
  },
);

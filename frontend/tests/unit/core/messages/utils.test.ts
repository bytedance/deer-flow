import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "@rstest/core";

import {
  extractContentFromMessage,
  extractTextFromMessage,
  extractReasoningContentFromMessage,
  getAssistantTurnCopyData,
  getAssistantTurnUsageMessages,
  getMessageGroups,
  getStreamingMessageLookup,
  hasContent,
  hasReasoning,
  isAssistantMessageGroupStreaming,
  stripUploadedFilesTag,
} from "@/core/messages/utils";

function aiMessage(content: string): Message {
  return {
    id: "ai-1",
    type: "ai",
    content,
  } as Message;
}

test("aggregates token usage messages once per assistant turn", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Plan a trip",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "",
      tool_calls: [{ id: "tool-1", name: "web_search", args: {} }],
      usage_metadata: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
    },
    {
      id: "tool-1-result",
      type: "tool",
      name: "web_search",
      tool_call_id: "tool-1",
      content: "[]",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "Here is the itinerary",
      usage_metadata: { input_tokens: 2, output_tokens: 8, total_tokens: 10 },
    },
    {
      id: "human-2",
      type: "human",
      content: "Make it shorter",
    },
    {
      id: "ai-3",
      type: "ai",
      content: "Short version",
      usage_metadata: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
    },
  ] as Message[];

  const groups = getMessageGroups(messages);
  const usageMessagesByGroupIndex = getAssistantTurnUsageMessages(groups);

  expect(groups.map((group) => group.type)).toEqual([
    "human",
    "assistant:processing",
    "assistant",
    "human",
    "assistant",
  ]);

  expect(
    usageMessagesByGroupIndex.map(
      (groupMessages) => groupMessages?.map((message) => message.id) ?? null,
    ),
  ).toEqual([null, null, ["ai-1", "ai-2"], null, ["ai-3"]]);
});

test("reasoning + content (no tool calls) yields a single assistant bubble, not a duplicate processing group", () => {
  // Regression for #3868: in thinking/pro/ultra modes the final assistant
  // message carries both reasoning_content and answer text. It must surface its
  // reasoning exactly once — inside the assistant bubble's <Reasoning>
  // collapsible. Routing the same message into a processing group as well makes
  // the ChainOfThought panel above the bubble paint the identical reasoning a
  // second time.
  const messages = [
    { id: "human-1", type: "human", content: "Why is the sky blue?" },
    {
      id: "ai-1",
      type: "ai",
      content: "Rayleigh scattering makes the sky blue.",
      additional_kwargs: { reasoning_content: "Recall Rayleigh scattering." },
    },
  ] as Message[];

  const groups = getMessageGroups(messages);

  expect(groups.map((group) => group.type)).toEqual(["human", "assistant"]);

  // The reasoning-bearing message lands in exactly one group, so turn-usage
  // aggregation never double-counts it (see #2770).
  const turnUsage = getAssistantTurnUsageMessages(groups);
  expect(turnUsage.at(-1)?.map((message) => message.id)).toEqual(["ai-1"]);
});

test("keeps tool-call reasoning in the processing group while the final answer's reasoning rides its own bubble", () => {
  // Companion to #3868: only the message that also becomes an assistant bubble
  // (content, no tool calls) is pulled out of the processing group. Reasoning
  // attached to an intermediate tool-calling step still belongs above, with its
  // tool steps.
  const messages = [
    { id: "human-1", type: "human", content: "Search and summarize" },
    {
      id: "ai-1",
      type: "ai",
      content: "",
      additional_kwargs: { reasoning_content: "I should search first." },
      tool_calls: [{ id: "tool-1", name: "web_search", args: { query: "x" } }],
    },
    {
      id: "tool-1-result",
      type: "tool",
      name: "web_search",
      tool_call_id: "tool-1",
      content: "[]",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "Here is the summary.",
      additional_kwargs: { reasoning_content: "Synthesize the findings." },
    },
  ] as Message[];

  const groups = getMessageGroups(messages);

  expect(groups.map((group) => group.type)).toEqual([
    "human",
    "assistant:processing",
    "assistant",
  ]);
  expect(groups[1]?.messages.map((message) => message.id)).toEqual([
    "ai-1",
    "tool-1-result",
  ]);
  expect(groups[2]?.messages.map((message) => message.id)).toEqual(["ai-2"]);
});

describe("inline <think> tag splitting", () => {
  test("strips a fully closed <think> block from AI content", () => {
    const message = aiMessage("<think>internal reasoning</think>final answer");
    expect(extractContentFromMessage(message)).toBe("final answer");
    expect(extractReasoningContentFromMessage(message)).toBe(
      "internal reasoning",
    );
  });

  test("strips multiple closed <think> blocks and joins their reasoning", () => {
    const message = aiMessage(
      "<think>step one</think>between<think>step two</think>after",
    );
    expect(extractContentFromMessage(message)).toBe("betweenafter");
    expect(extractReasoningContentFromMessage(message)).toBe(
      "step one\n\nstep two",
    );
  });

  test("during streaming, an unclosed <think> tag does not leak its tail into content", () => {
    // Simulates accumulated content mid-stream, before </think> arrives.
    const message = aiMessage(
      "<think>I need to analyze the user's question step by",
    );
    expect(extractContentFromMessage(message)).toBe("");
    expect(extractContentFromMessage(message)).not.toContain("<think>");
    expect(extractReasoningContentFromMessage(message)).toBe(
      "I need to analyze the user's question step by",
    );
  });

  test("preamble before an unclosed <think> stays in content", () => {
    const message = aiMessage(
      "Here is part of the answer.<think>but wait, let me reconsider",
    );
    expect(extractContentFromMessage(message)).toBe(
      "Here is part of the answer.",
    );
    expect(extractReasoningContentFromMessage(message)).toBe(
      "but wait, let me reconsider",
    );
  });

  test("closed <think> followed by a trailing unclosed <think> merges both into reasoning", () => {
    const message = aiMessage(
      "<think>first step</think>partial answer<think>second step still streaming",
    );
    expect(extractContentFromMessage(message)).toBe("partial answer");
    expect(extractReasoningContentFromMessage(message)).toBe(
      "first step\n\nsecond step still streaming",
    );
  });

  test("hasReasoning recognises an unclosed <think> tag mid-stream", () => {
    expect(hasReasoning(aiMessage("<think>thinking in progress"))).toBe(true);
  });

  test("hasContent excludes an unclosed <think> tail when no preamble exists", () => {
    expect(hasContent(aiMessage("<think>thinking in progress"))).toBe(false);
  });

  test("hasContent stays true when preamble precedes an unclosed <think>", () => {
    expect(hasContent(aiMessage("preamble<think>still thinking"))).toBe(true);
  });

  test("a lone <think> open tag with no body yields no reasoning and no content", () => {
    const message = aiMessage("<think>");
    expect(extractContentFromMessage(message)).toBe("");
    expect(extractReasoningContentFromMessage(message)).toBeNull();
    expect(hasReasoning(message)).toBe(false);
  });

  test("a literal <think> inside markdown inline code is not treated as reasoning", () => {
    const message = aiMessage(
      "Use `<think>` markers to delimit reasoning sections.",
    );
    expect(extractContentFromMessage(message)).toBe(
      "Use `<think>` markers to delimit reasoning sections.",
    );
    expect(extractReasoningContentFromMessage(message)).toBeNull();
    expect(hasReasoning(message)).toBe(false);
  });

  test("a backtick-prefixed <think> mid-stream is not split into reasoning", () => {
    // Simulates the moment the model has emitted the opening backtick and
    // `<think>` for a literal documentation reference, before the closing
    // backtick arrives. The pre-fix behaviour would have permanently
    // truncated the content here.
    const message = aiMessage("Documentation: `<think>");
    expect(extractContentFromMessage(message)).toBe("Documentation: `<think>");
    expect(extractReasoningContentFromMessage(message)).toBeNull();
  });
});

describe("human message internal context stripping", () => {
  test("strips slash skill activation context from display content", () => {
    const content =
      "<slash_skill_activation>\n<skill_content># Secret SKILL.md</skill_content>\n</slash_skill_activation>\nreal user task";

    expect(stripUploadedFilesTag(content)).toBe("real user task");
  });

  test("hides leaked slash skill activation messages with no user text", () => {
    const messages = [
      {
        id: "slash-activation",
        type: "human",
        content:
          "<slash_skill_activation>\n<skill_content># Secret SKILL.md</skill_content>\n</slash_skill_activation>",
      },
      {
        id: "ai-1",
        type: "ai",
        content: "Public answer",
      },
    ] as Message[];

    const groups = getMessageGroups(messages);

    expect(groups.map((group) => group.type)).toEqual(["assistant"]);
    expect(
      groups.flatMap((group) => group.messages).map((message) => message.id),
    ).toEqual(["ai-1"]);
  });
});

test("hides internal todo reminder messages from message groups", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Audit the middleware",
    },
    {
      id: "todo-reminder-1",
      type: "human",
      name: "todo_completion_reminder",
      content: "<system_reminder>finish todos</system_reminder>",
    },
    {
      id: "todo-reminder-2",
      type: "human",
      name: "todo_reminder",
      content: "<system_reminder>remember todos</system_reminder>",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Done",
    },
  ] as Message[];

  const groups = getMessageGroups(messages);

  expect(groups.map((group) => group.type)).toEqual(["human", "assistant"]);
  expect(
    groups.flatMap((group) => group.messages).map((message) => message.id),
  ).toEqual(["human-1", "ai-1"]);
});

test("hides assistant copy data while that turn is streaming", () => {
  const messages = [
    {
      id: "ai-1",
      type: "ai",
      content: "Partial answer",
    },
  ] as Message[];

  expect(getAssistantTurnCopyData(messages)).toBe("Partial answer");
  expect(getAssistantTurnCopyData(messages, { isStreaming: true })).toBeNull();
});

test("marks the latest assistant message as streaming", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Still generating",
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true, () => ({
        streamMetadata: { langgraph_node: "agent" },
      })),
    ),
  ).toBe(true);
  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, false, () => ({
        streamMetadata: { langgraph_node: "agent" },
      })),
    ),
  ).toBe(false);
});

test("keeps previous assistant copyable while waiting for a new visible answer", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Completed answer",
    },
    {
      id: "opt-human-1",
      type: "human",
      content: "Continue",
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true),
    ),
  ).toBe(false);
});

test("keeps previous assistant copyable while a hidden send is starting", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Completed answer",
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true),
    ),
  ).toBe(false);
});

test("keeps previous assistant copyable after a hidden send is appended", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Completed answer",
    },
    {
      id: "human-hidden",
      type: "human",
      content: "Save this agent",
      additional_kwargs: { hide_from_ui: true },
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true),
    ),
  ).toBe(false);
});

test("uses stream metadata to identify an assistant before optimistic input", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Completed answer",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "Still generating",
    },
    {
      id: "opt-human-1",
      type: "human",
      content: "Continue",
    },
  ] as Message[];
  const assistantGroups = getMessageGroups(messages).filter(
    (group) => group.type === "assistant",
  );
  const groups = getMessageGroups(messages);
  const assistantGroupIndexes = groups
    .map((group, index) => (group.type === "assistant" ? index : -1))
    .filter((index) => index >= 0);

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndexes[0] ?? -1]?.messages ?? [],
      getStreamingMessageLookup(messages, true, (message) =>
        message.id === "ai-2"
          ? { streamMetadata: { langgraph_node: "agent" } }
          : undefined,
      ),
    ),
  ).toBe(false);
  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndexes[1] ?? -1]?.messages ?? [],
      getStreamingMessageLookup(messages, true, (message) =>
        message.id === "ai-2"
          ? { streamMetadata: { langgraph_node: "agent" } }
          : undefined,
      ),
    ),
  ).toBe(true);
  expect(assistantGroups.map((group) => group.id)).toEqual(["ai-1", "ai-2"]);
});

test("does not mark a completed assistant group streaming from a later processing group", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Visible answer",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "",
      tool_calls: [{ id: "tool-1", name: "web_search", args: {} }],
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(groups.map((group) => group.type)).toEqual([
    "human",
    "assistant",
    "assistant:processing",
  ]);
  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true, (message) =>
        message.id === "ai-2"
          ? { streamMetadata: { langgraph_node: "agent" } }
          : undefined,
      ),
    ),
  ).toBe(false);
});

test("keeps streaming assistant hidden when a hidden control message follows it", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Still generating",
    },
    {
      id: "human-hidden",
      type: "human",
      content: "Save this agent",
      additional_kwargs: { hide_from_ui: true },
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true, (message) =>
        message.id === "ai-1"
          ? { streamMetadata: { langgraph_node: "agent" } }
          : undefined,
      ),
    ),
  ).toBe(true);
});

describe("multi-part content with bare-string continuations", () => {
  // Gemini streams the first content block as a {type:"text"} object carrying
  // the thinking signature, then emits continuation deltas as plain strings.
  // LangChain's Python merge_content preserves these as bare-string elements,
  // so the finalized message content is [{type:"text", ...}, "...rest..."].
  const geminiMessage = {
    id: "ai-1",
    type: "ai",
    content: [
      {
        type: "text",
        text: "First block carrying the signature.",
        extras: { signature: "abc123" },
        index: 0,
      },
      "Continuation streamed as a bare string.",
    ],
  } as unknown as Message;

  test("extractContentFromMessage includes the bare-string parts", () => {
    expect(extractContentFromMessage(geminiMessage)).toBe(
      "First block carrying the signature.\nContinuation streamed as a bare string.",
    );
  });

  test("extractTextFromMessage includes the bare-string parts", () => {
    expect(extractTextFromMessage(geminiMessage)).toBe(
      "First block carrying the signature.\nContinuation streamed as a bare string.",
    );
  });
});

describe("orphan tool messages", () => {
  // LangGraph stream-mode "messages-tuple" can emit tool-result events out of order or
  // replayed from subagent state (e.g. bash subagent under LocalSandboxProvider with
  // allow_host_bash). When that happens, the tool message arrives after a terminal
  // assistant/human group, so getMessageGroups' lastOpenGroup() returns null.
  //
  // The previous behaviour was console.error + drop, which silently hid the tool
  // result from the UI. The fix falls back to attaching the orphan tool to the most
  // recent group so the user can still see what the agent did.

  test("attaches orphan tool message to the most recent group instead of dropping it", () => {
    const messages = [
      { id: "h-1", type: "human", content: "Run something" },
      {
        id: "ai-1",
        type: "ai",
        content: "ok",
        tool_calls: [{ id: "call-1", name: "bash", args: {} }],
      },
      {
        id: "t-1",
        type: "tool",
        name: "bash",
        tool_call_id: "call-1",
        content: "output-1",
      },
      { id: "ai-2", type: "ai", content: "Done." }, // terminal assistant group
      // Orphan tool: arrives after a terminal group, no preceding processing group
      {
        id: "t-2",
        type: "tool",
        name: "bash",
        tool_call_id: "call-2",
        content: "output-2",
      },
    ] as Message[];

    const groups = getMessageGroups(messages);

    // Expect groups: human, assistant:processing (ai-1 + t-1), assistant (ai-2), and
    // t-2 should be attached to the last group (assistant), not dropped.
    const types = groups.map((g) => g.type);
    expect(types).toEqual(["human", "assistant:processing", "assistant"]);

    // t-2 must be retrievable from one of the groups — must NOT be silently dropped
    const allMessages = groups.flatMap((g) => g.messages);
    const t2 = allMessages.find((m) => m.id === "t-2");
    expect(t2).toBeDefined();
    expect(t2?.type).toBe("tool");
  });

  test("replayed tool with same tool_call_id is not lost (duplicate stream events)", () => {
    // LangGraph subagent state restoration can replay tool-result events. The
    // frontend log shows the same tool_call_id arriving twice. Both occurrences
    // should be visible in the UI, not just the first.
    const messages = [
      { id: "h-1", type: "human", content: "q" },
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [{ id: "call-x", name: "bash", args: {} }],
      },
      {
        id: "t-1a",
        type: "tool",
        name: "bash",
        tool_call_id: "call-x",
        content: "first delivery",
      },
      // Terminal assistant group ends the turn and closes the processing group.
      // Without this interleave the replayed t-1b would still take the
      // unchanged happy path; with it, t-1b arrives when lastOpenGroup()
      // returns null and must take the new fallback branch to be visible.
      { id: "ai-2", type: "ai", content: "Done." },
      // Replayed tool-result for the original tool_call — must reach the new
      // else-if (groups.length > 0) branch instead of being dropped.
      {
        id: "t-1b",
        type: "tool",
        name: "bash",
        tool_call_id: "call-x",
        content: "first delivery",
      },
    ] as Message[];

    const groups = getMessageGroups(messages);
    const allMessages = groups.flatMap((g) => g.messages);

    // Strict assertion: the replayed tool message must be reachable from a
    // group (i.e. attached via the new fallback). Before the fix this was
    // silently dropped by console.error.
    const t1b = allMessages.find((m) => m.id === "t-1b");
    expect(t1b).toBeDefined();
    expect(t1b?.type).toBe("tool");
  });
});

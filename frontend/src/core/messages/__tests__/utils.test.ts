import { describe, expect, it } from "vitest";

import type { Message } from "@langchain/langgraph-sdk";

import {
  extractContentFromMessage,
  extractPresentFilesFromMessage,
  extractReasoningContentFromMessage,
  extractTextFromMessage,
  findToolCallResult,
  groupMessages,
  hasContent,
  hasReasoning,
  hasSubagent,
  hasToolCalls,
  isClarificationToolMessage,
  parseUploadedFiles,
  removeReasoningContentFromMessage,
} from "../utils";

// -- Helpers --

function humanMsg(content: string, id = "h1"): Message {
  return { type: "human", content, id } as Message;
}

function aiMsg(
  content: string | object[],
  opts?: {
    id?: string;
    tool_calls?: { id: string; name: string; args: Record<string, unknown> }[];
    additional_kwargs?: Record<string, unknown>;
  },
): Message {
  return {
    type: "ai",
    content,
    id: opts?.id ?? "ai1",
    tool_calls: opts?.tool_calls ?? [],
    additional_kwargs: opts?.additional_kwargs ?? {},
  } as Message;
}

function toolMsg(
  toolCallId: string,
  content: string = "result",
  name: string = "tool",
): Message {
  return { type: "tool", content, tool_call_id: toolCallId, name, id: `t-${toolCallId}` } as Message;
}

const identity = <T>(x: T) => x;

// ---------------------------------------------------------------------------
// groupMessages
// ---------------------------------------------------------------------------
describe("groupMessages", () => {
  it("returns empty array for empty messages", () => {
    expect(groupMessages([], identity)).toEqual([]);
  });

  it("groups human messages", () => {
    const msgs = [humanMsg("hello")];
    const groups = groupMessages(msgs, identity);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.type).toBe("human");
  });

  it("groups AI messages with tool calls into assistant:processing", () => {
    const msgs = [
      aiMsg("", {
        tool_calls: [{ id: "tc1", name: "bash", args: {} }],
      }),
      toolMsg("tc1"),
    ];
    const groups = groupMessages(msgs, identity);
    const processingGroups = groups.filter((g) => g.type === "assistant:processing");
    expect(processingGroups.length).toBeGreaterThanOrEqual(1);
  });

  it("keeps assistant content when AI message has both tool calls and text", () => {
    const msgs = [
      aiMsg("Final answer", {
        id: "ai-with-tools",
        tool_calls: [{ id: "tc1", name: "bash", args: {} }],
      }),
      toolMsg("tc1"),
    ];
    const groups = groupMessages(msgs, identity);

    const processingGroup = groups.find((g) => g.type === "assistant:processing");
    const assistantGroup = groups.find((g) => g.type === "assistant");

    expect(processingGroup).toBeDefined();
    expect(assistantGroup).toBeDefined();
    expect(assistantGroup?.id).toBe("ai-with-tools:content");
    expect(assistantGroup?.messages[0]?.content).toBe("Final answer");
  });

  it("groups AI content-only messages into assistant", () => {
    const msgs = [aiMsg("Hello! Here's the answer.")];
    const groups = groupMessages(msgs, identity);
    expect(groups.some((g) => g.type === "assistant")).toBe(true);
  });

  it("associates tool messages with preceding processing group", () => {
    const msgs = [
      aiMsg("", {
        tool_calls: [{ id: "tc1", name: "bash", args: {} }],
      }),
      toolMsg("tc1"),
    ];
    const groups = groupMessages(msgs, identity);
    const processingGroup = groups.find((g) => g.type === "assistant:processing");
    expect(processingGroup).toBeDefined();
    // Tool message should be in the processing group
    expect(processingGroup!.messages.length).toBe(2);
  });

  it("creates clarification group for clarification tool", () => {
    const msgs = [
      aiMsg("", {
        tool_calls: [{ id: "tc1", name: "ask_clarification", args: {} }],
      }),
      toolMsg("tc1", "user response", "ask_clarification"),
    ];
    const groups = groupMessages(msgs, identity);
    expect(groups.some((g) => g.type === "assistant:clarification")).toBe(true);
  });

  it("creates present-files group for present_files calls", () => {
    const msgs = [
      aiMsg("", {
        tool_calls: [{ id: "tc1", name: "present_files", args: { filepaths: ["/a.py"] } }],
      }),
    ];
    const groups = groupMessages(msgs, identity);
    expect(groups.some((g) => g.type === "assistant:present-files")).toBe(true);
  });

  it("creates subagent group for task tool calls", () => {
    const msgs = [
      aiMsg("", {
        tool_calls: [{ id: "tc1", name: "task", args: {} }],
      }),
    ];
    const groups = groupMessages(msgs, identity);
    expect(groups.some((g) => g.type === "assistant:subagent")).toBe(true);
  });

  it("throws for orphaned tool message", () => {
    const msgs = [toolMsg("tc1")];
    expect(() => groupMessages(msgs, identity)).toThrow();
  });
});

// ---------------------------------------------------------------------------
// extractTextFromMessage
// ---------------------------------------------------------------------------
describe("extractTextFromMessage", () => {
  it("returns trimmed string content", () => {
    expect(extractTextFromMessage(humanMsg("  hello  "))).toBe("hello");
  });

  it("joins text blocks from array content", () => {
    const msg = aiMsg([
      { type: "text", text: "line 1" },
      { type: "text", text: "line 2" },
    ]);
    expect(extractTextFromMessage(msg)).toBe("line 1\nline 2");
  });

  it("returns empty string for non-text content", () => {
    expect(extractTextFromMessage({ type: "ai", content: 42 } as unknown as Message)).toBe("");
  });
});

// ---------------------------------------------------------------------------
// extractContentFromMessage
// ---------------------------------------------------------------------------
describe("extractContentFromMessage", () => {
  it("formats image_url as markdown", () => {
    const msg = aiMsg([
      { type: "image_url", image_url: { url: "https://example.com/img.png" } },
    ]);
    const result = extractContentFromMessage(msg);
    expect(result).toContain("![image](https://example.com/img.png)");
  });
});

// ---------------------------------------------------------------------------
// extractReasoningContentFromMessage
// ---------------------------------------------------------------------------
describe("extractReasoningContentFromMessage", () => {
  it("extracts from reasoning_content in additional_kwargs", () => {
    const msg = aiMsg("answer", {
      additional_kwargs: { reasoning_content: "thinking step" },
    });
    expect(extractReasoningContentFromMessage(msg)).toBe("thinking step");
  });

  it("extracts from reasoning block in additional_kwargs", () => {
    const msg = aiMsg("answer", {
      additional_kwargs: {
        reasoning: { summary: "thought summary" },
      },
    });
    expect(extractReasoningContentFromMessage(msg)).toBe("thought summary");
  });

  it("extracts from thinking content blocks", () => {
    const msg = aiMsg([
      { type: "thinking", thinking: "deep thought" },
      { type: "text", text: "answer" },
    ]);
    expect(extractReasoningContentFromMessage(msg)).toBe("deep thought");
  });

  it("returns null for non-AI message", () => {
    expect(extractReasoningContentFromMessage(humanMsg("hi"))).toBeNull();
  });

  it("returns null when no reasoning present", () => {
    const msg = aiMsg("plain answer");
    expect(extractReasoningContentFromMessage(msg)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// removeReasoningContentFromMessage
// ---------------------------------------------------------------------------
describe("removeReasoningContentFromMessage", () => {
  it("removes reasoning_content from additional_kwargs", () => {
    const msg = aiMsg("answer", {
      additional_kwargs: { reasoning_content: "thought" },
    });
    removeReasoningContentFromMessage(msg);
    expect(msg.additional_kwargs?.reasoning_content).toBeUndefined();
  });

  it("filters thinking blocks from content array", () => {
    const msg = aiMsg([
      { type: "thinking", thinking: "deep thought" },
      { type: "text", text: "answer" },
    ]);
    removeReasoningContentFromMessage(msg);
    expect(Array.isArray(msg.content)).toBe(true);
    const arr = msg.content as { type: string }[];
    expect(arr.every((b) => b.type !== "thinking")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// hasContent / hasReasoning / hasToolCalls
// ---------------------------------------------------------------------------
describe("hasContent", () => {
  it("true for non-empty string", () => {
    expect(hasContent(humanMsg("hello"))).toBe(true);
  });

  it("true for array with text block", () => {
    expect(hasContent(aiMsg([{ type: "text", text: "hi" }]))).toBe(true);
  });

  it("false for empty string", () => {
    expect(hasContent(humanMsg(""))).toBe(false);
  });

  it("false for whitespace-only string", () => {
    expect(hasContent(humanMsg("   "))).toBe(false);
  });

  it("false for empty array", () => {
    expect(hasContent(aiMsg([]))).toBe(false);
  });
});

describe("hasReasoning", () => {
  it("true when reasoning present", () => {
    const msg = aiMsg("answer", {
      additional_kwargs: { reasoning_content: "thinking" },
    });
    expect(hasReasoning(msg)).toBe(true);
  });

  it("false when no reasoning", () => {
    expect(hasReasoning(aiMsg("plain"))).toBe(false);
  });
});

describe("hasToolCalls", () => {
  it("true when tool_calls exist", () => {
    const msg = aiMsg("", {
      tool_calls: [{ id: "tc1", name: "bash", args: {} }],
    });
    expect(hasToolCalls(msg)).toBe(true);
  });

  it("false when no tool_calls", () => {
    expect(hasToolCalls(aiMsg("plain"))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isClarificationToolMessage / extractPresentFilesFromMessage / hasSubagent
// ---------------------------------------------------------------------------
describe("isClarificationToolMessage", () => {
  it("true for ask_clarification tool message", () => {
    expect(isClarificationToolMessage(toolMsg("tc1", "result", "ask_clarification"))).toBe(true);
  });

  it("false for other tool messages", () => {
    expect(isClarificationToolMessage(toolMsg("tc1", "result", "bash"))).toBe(false);
  });
});

describe("extractPresentFilesFromMessage", () => {
  it("extracts filepaths from present_files tool call", () => {
    const msg = aiMsg("", {
      tool_calls: [{ id: "tc1", name: "present_files", args: { filepaths: ["/a.py", "/b.py"] } }],
    });
    const files = extractPresentFilesFromMessage(msg);
    expect(files).toEqual(["/a.py", "/b.py"]);
  });

  it("returns empty array for non-present_files message", () => {
    expect(extractPresentFilesFromMessage(humanMsg("hi"))).toEqual([]);
  });
});

describe("hasSubagent", () => {
  it("true for task tool call", () => {
    const msg = aiMsg("", {
      tool_calls: [{ id: "tc1", name: "task", args: {} }],
    });
    // hasSubagent expects AIMessage type
    expect(hasSubagent(msg as any)).toBe(true);
  });

  it("false for non-task tool calls", () => {
    const msg = aiMsg("", {
      tool_calls: [{ id: "tc1", name: "bash", args: {} }],
    });
    expect(hasSubagent(msg as any)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// findToolCallResult
// ---------------------------------------------------------------------------
describe("findToolCallResult", () => {
  it("finds matching tool message by tool_call_id", () => {
    const messages = [
      aiMsg("", { tool_calls: [{ id: "tc1", name: "bash", args: {} }] }),
      toolMsg("tc1", "command output"),
    ];
    expect(findToolCallResult("tc1", messages)).toBe("command output");
  });

  it("returns undefined when no match", () => {
    const messages = [humanMsg("hi")];
    expect(findToolCallResult("tc-missing", messages)).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// parseUploadedFiles
// ---------------------------------------------------------------------------
describe("parseUploadedFiles", () => {
  it("extracts files from uploaded_files tag", () => {
    const content = `<uploaded_files>
- report.pdf (1.2 MB)
  Path: /mnt/user-data/uploads/report.pdf
- data.csv (500 KB)
  Path: /mnt/user-data/uploads/data.csv
</uploaded_files>
Please analyze these files.`;

    const result = parseUploadedFiles(content);
    expect(result.files).toHaveLength(2);
    expect(result.files[0]!.filename).toBe("report.pdf");
    expect(result.files[0]!.size).toBe("1.2 MB");
    expect(result.files[0]!.path).toBe("/mnt/user-data/uploads/report.pdf");
    expect(result.files[1]!.filename).toBe("data.csv");
    expect(result.cleanContent).toBe("Please analyze these files.");
  });

  it("returns empty files for no tag", () => {
    const result = parseUploadedFiles("Hello, no files here.");
    expect(result.files).toEqual([]);
    expect(result.cleanContent).toBe("Hello, no files here.");
  });

  it('returns empty files for "no files uploaded" message', () => {
    const content = `<uploaded_files>
No files have been uploaded yet.
</uploaded_files>
Start working.`;

    const result = parseUploadedFiles(content);
    expect(result.files).toEqual([]);
    expect(result.cleanContent).toBe("Start working.");
  });
});

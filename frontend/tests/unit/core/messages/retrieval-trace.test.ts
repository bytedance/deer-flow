import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "vitest";

import { extractRetrievalTrace } from "@/core/messages/utils";

describe("extractRetrievalTrace", () => {
  test("returns null when no retrieval trace is present", () => {
    const messages: Message[] = [
      { id: "h1", type: "human", content: "hello" },
      { id: "a1", type: "ai", content: "hi there" },
    ] as Message[];

    expect(extractRetrievalTrace(messages)).toBeNull();
  });

  test("extracts sources from system message with retrieval_trace tag", () => {
    const trace = JSON.stringify({
      sources: [
        { kb_id: "kb-1", kb_name: "Docs", doc_title: "Guide.md", score: 0.92 },
        { kb_id: "kb-2", kb_name: "FAQ", doc_title: "Common.md", score: 0.85 },
      ],
    });

    const messages: Message[] = [
      {
        id: "sys-1",
        type: "system",
        content: `Some context\n<retrieval_trace>${trace}</retrieval_trace>\nMore text`,
      },
      { id: "a1", type: "ai", content: "Based on the docs..." },
    ] as Message[];

    const result = extractRetrievalTrace(messages);
    expect(result).toHaveLength(2);
    expect(result![0]).toEqual({
      kb_id: "kb-1",
      kb_name: "Docs",
      doc_title: "Guide.md",
      score: 0.92,
    });
    expect(result![1]).toEqual({
      kb_id: "kb-2",
      kb_name: "FAQ",
      doc_title: "Common.md",
      score: 0.85,
    });
  });

  test("returns the last retrieval trace when multiple exist", () => {
    const trace1 = JSON.stringify({
      sources: [{ kb_id: "kb-1", kb_name: "Old", doc_title: "A.md", score: 0.5 }],
    });
    const trace2 = JSON.stringify({
      sources: [{ kb_id: "kb-2", kb_name: "New", doc_title: "B.md", score: 0.9 }],
    });

    const messages: Message[] = [
      { id: "sys-1", type: "system", content: `<retrieval_trace>${trace1}</retrieval_trace>` },
      { id: "h1", type: "human", content: "question" },
      { id: "sys-2", type: "system", content: `<retrieval_trace>${trace2}</retrieval_trace>` },
      { id: "a1", type: "ai", content: "answer" },
    ] as Message[];

    const result = extractRetrievalTrace(messages);
    expect(result).toHaveLength(1);
    expect(result![0]!.kb_name).toBe("New");
  });

  test("returns null for empty sources array", () => {
    const trace = JSON.stringify({ sources: [] });
    const messages: Message[] = [
      { id: "sys-1", type: "system", content: `<retrieval_trace>${trace}</retrieval_trace>` },
    ] as Message[];

    expect(extractRetrievalTrace(messages)).toBeNull();
  });

  test("returns null for malformed JSON in retrieval_trace", () => {
    const messages: Message[] = [
      { id: "sys-1", type: "system", content: `<retrieval_trace>{invalid json</retrieval_trace>` },
    ] as Message[];

    expect(extractRetrievalTrace(messages)).toBeNull();
  });

  test("extracts from ai message content as well", () => {
    const trace = JSON.stringify({
      sources: [{ kb_id: "kb-1", kb_name: "KB", doc_title: "Doc.md", score: 0.88 }],
    });

    const messages: Message[] = [
      { id: "a1", type: "ai", content: `Here is info\n<retrieval_trace>${trace}</retrieval_trace>` },
    ] as Message[];

    const result = extractRetrievalTrace(messages);
    expect(result).toHaveLength(1);
    expect(result![0]!.doc_title).toBe("Doc.md");
  });

  test("skips human and tool messages", () => {
    const trace = JSON.stringify({
      sources: [{ kb_id: "kb-1", kb_name: "KB", doc_title: "Doc.md", score: 0.8 }],
    });

    const messages: Message[] = [
      { id: "h1", type: "human", content: `<retrieval_trace>${trace}</retrieval_trace>` },
      { id: "t1", type: "tool", content: `<retrieval_trace>${trace}</retrieval_trace>`, name: "search", tool_call_id: "tc1" },
    ] as Message[];

    expect(extractRetrievalTrace(messages)).toBeNull();
  });
});

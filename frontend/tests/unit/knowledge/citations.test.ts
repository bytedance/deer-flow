/**
 * Citation extraction from retrieval tool messages (spec §4.6): the rag
 * agent's knowledge_search returns a JSON payload whose ``results`` are
 * chunk-level sources. The assistant's ``[n]`` markers map onto the merged,
 * deduped source list of its own turn.
 */
import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "@rstest/core";

import {
  parseRetrievalToolContent,
  sourcesForAssistantMessage,
} from "@/core/knowledge/citations";

function toolMessage(name: string, payload: unknown, id: string): Message {
  return {
    type: "tool",
    id,
    name,
    content: typeof payload === "string" ? payload : JSON.stringify(payload),
  } as unknown as Message;
}

function human(id: string): Message {
  return { type: "human", id, content: "问题" } as unknown as Message;
}

function ai(id: string): Message {
  return { type: "ai", id, content: "回答 [1]" } as unknown as Message;
}

const HYBRID = {
  results: [
    { chunk_id: "c1", doc_name: "手册.pdf", page: 3, heading_path: ["第一章"], text: "切片一", score: 0.9 },
    { chunk_id: "c2", doc_name: "白皮书.md", page: null, heading_path: [], text: "切片二", score: 0.8 },
  ],
  message: "检索到 2 条相关切片。",
};

describe("parseRetrievalToolContent", () => {
  test("parses knowledge_search results into chunk citations", () => {
    const citations = parseRetrievalToolContent("knowledge_search", JSON.stringify(HYBRID));
    expect(citations).toHaveLength(2);
    expect(citations[0]).toMatchObject({ chunk_id: "c1", doc_name: "手册.pdf", page: 3, text: "切片一" });
  });

  test("stamps source_type chunk for the retrieval tool", () => {
    expect(parseRetrievalToolContent("knowledge_search", JSON.stringify(HYBRID))[0]?.source_type).toBe("chunk");
  });

  test("tolerates malformed JSON and unknown tools by returning nothing", () => {
    expect(parseRetrievalToolContent("knowledge_search", "not-json")).toEqual([]);
    expect(parseRetrievalToolContent("web_search", JSON.stringify(HYBRID))).toEqual([]);
    expect(parseRetrievalToolContent("knowledge_search", JSON.stringify({ results: [], message: "空" }))).toEqual([]);
  });
});

describe("sourcesForAssistantMessage", () => {
  test("merges retrieval results between the previous human message and the answer, deduped by chunk_id", () => {
    const second = {
      results: [{ chunk_id: "c3", doc_name: "手册.pdf", page: 5, heading_path: ["第二章"], text: "切片三", score: 0.7 }],
    };
    const messages = [
      human("h1"),
      toolMessage("knowledge_search", HYBRID, "t1"),
      toolMessage("knowledge_search", second, "t2"),
      ai("a1"),
    ];
    const sources = sourcesForAssistantMessage(messages, "a1");
    expect(sources.map((s) => s.chunk_id)).toEqual(["c1", "c2", "c3"]);
  });

  test("scopes to the message's own turn (earlier turns are invisible)", () => {
    const second = {
      results: [{ chunk_id: "c3", doc_name: "手册.pdf", page: 5, heading_path: [], text: "切片三", score: 0.7 }],
    };
    const messages = [
      human("h1"),
      toolMessage("knowledge_search", HYBRID, "t1"),
      ai("a1"),
      human("h2"),
      toolMessage("knowledge_search", second, "t2"),
      ai("a2"),
    ];
    expect(sourcesForAssistantMessage(messages, "a2").map((s) => s.chunk_id)).toEqual(["c3"]);
    expect(sourcesForAssistantMessage(messages, "a1").map((s) => s.chunk_id)).toEqual(["c1", "c2"]);
  });

  test("carries the backend citation_no through parsing", () => {
    const hybrid = {
      results: [{ chunk_id: "c1", doc_name: "手册.pdf", page: 3, heading_path: [], text: "切片", score: 0.9, citation_no: 4 }],
    };
    expect(parseRetrievalToolContent("knowledge_search", JSON.stringify(hybrid))[0]?.citation_nos).toEqual([4]);
  });

  test("dedupe merges citation numbers of every call onto one source (production overlap repro)", () => {
    // Production repro: repeated searches recalled the SAME chunks, and the
    // backend assigned each call its own citation_no range (4-8, then 9-12).
    // Dedupe must keep one card per chunk while preserving BOTH numbers —
    // otherwise the model's [9]-[12] marks dangle.
    const first5 = {
      results: [
        { chunk_id: "cA", doc_name: "a.md", page: null, heading_path: [], text: "切片A", score: 0.9, citation_no: 4 },
        { chunk_id: "cB", doc_name: "b.md", page: null, heading_path: [], text: "切片B", score: 0.8, citation_no: 5 },
        { chunk_id: "cD", doc_name: "d.md", page: null, heading_path: [], text: "切片D", score: 0.7, citation_no: 6 },
        { chunk_id: "cC", doc_name: "c.md", page: null, heading_path: [], text: "切片C", score: 0.6, citation_no: 7 },
        { chunk_id: "cE", doc_name: "e.md", page: null, heading_path: [], text: "切片E", score: 0.5, citation_no: 8 },
      ],
    };
    const second4 = {
      results: [
        { chunk_id: "cA", doc_name: "a.md", page: null, heading_path: [], text: "证据A", score: 0.7, citation_no: 9 },
        { chunk_id: "cB", doc_name: "b.md", page: null, heading_path: [], text: "证据B", score: 0.6, citation_no: 10 },
        { chunk_id: "cC", doc_name: "c.md", page: null, heading_path: [], text: "证据C", score: 0.5, citation_no: 11 },
        { chunk_id: "cD", doc_name: "d.md", page: null, heading_path: [], text: "证据D", score: 0.4, citation_no: 12 },
      ],
    };
    const messages = [
      human("h1"),
      toolMessage("knowledge_search", first5, "t1"),
      toolMessage("knowledge_search", second4, "t2"),
      ai("a1"),
    ];
    const sources = sourcesForAssistantMessage(messages, "a1");
    // overlap collapses to the 5 unique chunks
    expect(sources).toHaveLength(5);
    // Sorted by each card's smallest citation_no (NOT tool-completion order),
    // so the array position is the stable display number.
    expect(sources.map((s) => s.chunk_id)).toEqual(["cA", "cB", "cD", "cC", "cE"]);
    const byId = new Map(sources.map((s) => [s.chunk_id, s]));
    expect(byId.get("cA")?.citation_nos).toEqual([4, 9]);
    expect(byId.get("cB")?.citation_nos).toEqual([5, 10]);
    expect(byId.get("cD")?.citation_nos).toEqual([6, 12]);
    expect(byId.get("cC")?.citation_nos).toEqual([7, 11]);
    expect(byId.get("cE")?.citation_nos).toEqual([8]);
    // Every citation_no the model may cite resolves to exactly one source.
    for (const n of [4, 5, 6, 7, 8, 9, 10, 11, 12]) {
      expect(sources.some((s) => s.citation_nos?.includes(n))).toBe(true);
    }
  });

  test("sorts cards by their smallest citation_no regardless of tool-completion order", () => {
    const first = {
      results: [{ chunk_id: "cB", doc_name: "b.md", page: null, heading_path: [], text: "切片", score: 0.9, citation_no: 3 }],
    };
    const second = {
      results: [{ chunk_id: "cA", doc_name: "a.md", page: null, heading_path: [], text: "证据", score: 0.5, citation_no: 4 }],
    };
    const messages = [
      human("h1"),
      toolMessage("knowledge_search", second, "t1"),
      toolMessage("knowledge_search", first, "t2"),
      ai("a1"),
    ];
    expect(sourcesForAssistantMessage(messages, "a1").map((s) => s.chunk_id)).toEqual(["cB", "cA"]);
  });

  test("returns nothing for an answer without retrieval", () => {
    const messages = [human("h1"), ai("a1")];
    expect(sourcesForAssistantMessage(messages, "a1")).toEqual([]);
  });
});

/**
 * Citation extraction from retrieval tool messages (spec §4.6): the rag
 * agent's tools return JSON payloads — knowledge_search ``results`` (chunk
 * level), graph_search ``evidence`` (chunk level), wiki_search ``entries``
 * (entry level). The assistant's ``[n]`` markers map onto the merged,
 * deduped source list of its own turn.
 */
import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "@rstest/core";

import {
  latestGraphTraceTurn,
  latestRetrievalTurn,
  parseGraphSearchTrace,
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

const WIKI = {
  entries: [{ entry_id: "e1", title: "DeerFlow", content: "条目全文", score: 0.7, updated_at: "2026-08-09" }],
  message: "命中 1 篇百科条目。",
};

const GRAPH = {
  entities: [],
  relations: [],
  evidence: [{ chunk_id: "c3", text: "证据切片", doc_name: "手册.pdf", heading_path: ["第二章"], page: 5 }],
  message: "命中 1 个实体。",
};

// Phase-3 P6 (spec §8): wiki_search now mixes manual cards into its entries —
// each hit carries its own source_type, overriding the tool-name fallback.
const WIKI_MIXED = {
  entries: [
    { entry_id: "e1", title: "DeerFlow", content: "条目全文", score: 0.7, source_type: "wiki" },
    { entry_id: "card-1", title: "发布禁令", content: "周五下午不发布", score: 0.9, source_type: "manual" },
  ],
  message: "命中 1 篇百科条目、1 张人工知识卡片。",
};

describe("parseRetrievalToolContent", () => {
  test("parses knowledge_search results into chunk citations", () => {
    const citations = parseRetrievalToolContent("knowledge_search", JSON.stringify(HYBRID));
    expect(citations).toHaveLength(2);
    expect(citations[0]).toMatchObject({ chunk_id: "c1", doc_name: "手册.pdf", page: 3, text: "切片一" });
  });

  test("stamps source_type from the tool name (phase-2 batch-1: zero backend change)", () => {
    expect(parseRetrievalToolContent("knowledge_search", JSON.stringify(HYBRID))[0]?.source_type).toBe("chunk");
    expect(parseRetrievalToolContent("graph_search", JSON.stringify(GRAPH))[0]?.source_type).toBe("chunk");
    expect(parseRetrievalToolContent("wiki_search", JSON.stringify(WIKI))[0]?.source_type).toBe("wiki");
  });

  test("honors the payload's own source_type (phase-3 P6: manual cards mix into wiki_search)", () => {
    const citations = parseRetrievalToolContent("wiki_search", JSON.stringify(WIKI_MIXED));
    expect(citations.map((citation) => citation.source_type)).toEqual(["wiki", "manual"]);
    // Manual card: title becomes the source name, content becomes the text.
    expect(citations[1]).toMatchObject({ chunk_id: "card-1", doc_name: "发布禁令", text: "周五下午不发布" });
  });

  test("parses wiki_search entries into entry citations (title as source name)", () => {
    const citations = parseRetrievalToolContent("wiki_search", JSON.stringify(WIKI));
    expect(citations).toHaveLength(1);
    expect(citations[0]).toMatchObject({ chunk_id: "e1", doc_name: "DeerFlow", text: "条目全文", page: null });
  });

  test("parses graph_search evidence into chunk citations", () => {
    const citations = parseRetrievalToolContent("graph_search", JSON.stringify(GRAPH));
    expect(citations[0]).toMatchObject({ chunk_id: "c3", doc_name: "手册.pdf", text: "证据切片" });
  });

  test("tolerates malformed JSON and unknown tools by returning nothing", () => {
    expect(parseRetrievalToolContent("knowledge_search", "not-json")).toEqual([]);
    expect(parseRetrievalToolContent("web_search", JSON.stringify(HYBRID))).toEqual([]);
    expect(parseRetrievalToolContent("knowledge_search", JSON.stringify({ results: [], message: "空" }))).toEqual([]);
  });
});

describe("sourcesForAssistantMessage", () => {
  test("merges retrieval results between the previous human message and the answer, deduped by chunk_id", () => {
    const messages = [
      human("h1"),
      toolMessage("knowledge_search", HYBRID, "t1"),
      toolMessage("wiki_search", WIKI, "t2"),
      toolMessage("graph_search", GRAPH, "t3"),
      ai("a1"),
    ];
    const sources = sourcesForAssistantMessage(messages, "a1");
    expect(sources.map((s) => s.chunk_id)).toEqual(["c1", "c2", "e1", "c3"]);
  });

  test("scopes to the message's own turn (earlier turns are invisible)", () => {
    const messages = [
      human("h1"),
      toolMessage("knowledge_search", HYBRID, "t1"),
      ai("a1"),
      human("h2"),
      toolMessage("wiki_search", WIKI, "t2"),
      ai("a2"),
    ];
    expect(sourcesForAssistantMessage(messages, "a2").map((s) => s.chunk_id)).toEqual(["e1"]);
    expect(sourcesForAssistantMessage(messages, "a1").map((s) => s.chunk_id)).toEqual(["c1", "c2"]);
  });

  test("dedupes the same chunk recalled by two paths", () => {
    const graphSame = { ...GRAPH, evidence: [{ ...GRAPH.evidence[0], chunk_id: "c1" }] };
    const messages = [
      human("h1"),
      toolMessage("knowledge_search", HYBRID, "t1"),
      toolMessage("graph_search", graphSame, "t3"),
      ai("a1"),
    ];
    expect(sourcesForAssistantMessage(messages, "a1").map((s) => s.chunk_id)).toEqual(["c1", "c2"]);
  });

  test("carries the backend citation_no through parsing", () => {
    const hybrid = {
      results: [{ chunk_id: "c1", doc_name: "手册.pdf", page: 3, heading_path: [], text: "切片", score: 0.9, citation_no: 4 }],
    };
    const graph = {
      entities: [],
      relations: [],
      evidence: [{ chunk_id: "c3", text: "证据", doc_name: "手册.pdf", heading_path: [], page: 5, citation_no: 9 }],
    };
    const wiki = {
      entries: [{ entry_id: "e1", title: "条目", content: "全文", score: 0.7, citation_no: 1 }],
    };
    expect(parseRetrievalToolContent("knowledge_search", JSON.stringify(hybrid))[0]?.citation_nos).toEqual([4]);
    expect(parseRetrievalToolContent("graph_search", JSON.stringify(graph))[0]?.citation_nos).toEqual([9]);
    expect(parseRetrievalToolContent("wiki_search", JSON.stringify(wiki))[0]?.citation_nos).toEqual([1]);
  });

  test("dedupe merges citation numbers of every path onto one source (production overlap repro)", () => {
    // Production repro: graph and hybrid recalled the SAME chunks, and the
    // backend assigned each path its own citation_no range (hybrid 4-8,
    // graph 9-12). Dedupe must keep one card per chunk while preserving BOTH
    // numbers — otherwise the model's [9]-[12] marks dangle.
    const wiki3 = {
      entries: [1, 2, 3].map((n) => ({ entry_id: `e${n}`, title: `条目${n}`, content: "全文", score: 0.7, citation_no: n })),
    };
    const graph4 = {
      entities: [],
      relations: [],
      evidence: [
        { chunk_id: "cA", text: "证据A", doc_name: "a.md", heading_path: [], page: null, citation_no: 9 },
        { chunk_id: "cB", text: "证据B", doc_name: "b.md", heading_path: [], page: null, citation_no: 10 },
        { chunk_id: "cC", text: "证据C", doc_name: "c.md", heading_path: [], page: null, citation_no: 11 },
        { chunk_id: "cD", text: "证据D", doc_name: "d.md", heading_path: [], page: null, citation_no: 12 },
      ],
    };
    const hybrid5 = {
      results: [
        { chunk_id: "cA", doc_name: "a.md", page: null, heading_path: [], text: "切片A", score: 0.9, citation_no: 4 },
        { chunk_id: "cB", doc_name: "b.md", page: null, heading_path: [], text: "切片B", score: 0.8, citation_no: 5 },
        { chunk_id: "cD", doc_name: "d.md", page: null, heading_path: [], text: "切片D", score: 0.7, citation_no: 6 },
        { chunk_id: "cC", doc_name: "c.md", page: null, heading_path: [], text: "切片C", score: 0.6, citation_no: 7 },
        { chunk_id: "cE", doc_name: "e.md", page: null, heading_path: [], text: "切片E", score: 0.5, citation_no: 8 },
      ],
    };
    const messages = [
      human("h1"),
      toolMessage("wiki_search", wiki3, "t1"),
      toolMessage("graph_search", graph4, "t2"),
      toolMessage("knowledge_search", hybrid5, "t3"),
      ai("a1"),
    ];
    const sources = sourcesForAssistantMessage(messages, "a1");
    // 3 wiki + 4 graph chunks + 1 hybrid-only chunk (cE) — overlap collapses.
    expect(sources).toHaveLength(8);
    // Sorted by each card's smallest citation_no (NOT tool-completion order),
    // so the array position is the stable display number: e1..e3 (1-3), then
    // cA(4) cB(5) cD(6) cC(7) cE(8).
    expect(sources.map((s) => s.chunk_id)).toEqual(["e1", "e2", "e3", "cA", "cB", "cD", "cC", "cE"]);
    const byId = new Map(sources.map((s) => [s.chunk_id, s]));
    expect(byId.get("cA")?.citation_nos).toEqual([9, 4]);
    expect(byId.get("cB")?.citation_nos).toEqual([10, 5]);
    expect(byId.get("cD")?.citation_nos).toEqual([12, 6]);
    expect(byId.get("cC")?.citation_nos).toEqual([11, 7]);
    expect(byId.get("cE")?.citation_nos).toEqual([8]);
    // Every citation_no the model may cite resolves to exactly one source.
    for (const n of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]) {
      expect(sources.some((s) => s.citation_nos?.includes(n))).toBe(true);
    }
  });

  test("sorts cards by their smallest citation_no regardless of tool-completion order", () => {
    // Production: tools finish in any order (graph first here), and the strip
    // used to follow completion order — so wiki cards (citation_no 1-2) could
    // land behind chunk cards (3-4). Display numbers are the SORTED array
    // positions, keeping the strip order stable across runs.
    const wiki = {
      entries: [1, 2].map((n) => ({ entry_id: `e${n}`, title: `条目${n}`, content: "全文", score: 0.7, citation_no: n })),
    };
    const graph = {
      entities: [],
      relations: [],
      evidence: [{ chunk_id: "cA", text: "证据", doc_name: "a.md", heading_path: [], page: null, citation_no: 4 }],
    };
    const hybrid = {
      results: [{ chunk_id: "cB", doc_name: "b.md", page: null, heading_path: [], text: "切片", score: 0.9, citation_no: 3 }],
    };
    const messages = [
      human("h1"),
      toolMessage("graph_search", graph, "t1"),
      toolMessage("knowledge_search", hybrid, "t2"),
      toolMessage("wiki_search", wiki, "t3"),
      ai("a1"),
    ];
    expect(sourcesForAssistantMessage(messages, "a1").map((s) => s.chunk_id)).toEqual(["e1", "e2", "cB", "cA"]);
  });

  test("returns nothing for an answer without retrieval", () => {
    const messages = [human("h1"), ai("a1")];
    expect(sourcesForAssistantMessage(messages, "a1")).toEqual([]);
  });
});

// ── P6 检索联动（2026-08-15 spec §9 通道二）：最新一轮检索上下文提取 ──────

describe("latestRetrievalTurn", () => {
  test("returns null for an empty transcript or one without any assistant answer", () => {
    expect(latestRetrievalTurn([])).toBeNull();
    expect(latestRetrievalTurn([human("h1")])).toBeNull();
  });

  test("returns null when the latest answer never retrieved (no citations)", () => {
    // 最后一轮无引用 → 不更新叠加（保留旧 overlay，由调用方决定）。
    const messages = [
      human("h1"),
      toolMessage("knowledge_search", HYBRID, "t1"),
      ai("a1"),
      { type: "human", id: "h2", content: "闲聊" } as unknown as Message,
      ai("a2"),
    ];
    expect(latestRetrievalTurn(messages)).toBeNull();
  });

  test("extracts the latest turn: question text, merged citations, answer id", () => {
    const messages = [human("h1"), toolMessage("knowledge_search", HYBRID, "t1"), ai("a1")];
    const turn = latestRetrievalTurn(messages);
    expect(turn?.messageId).toBe("a1");
    expect(turn?.text).toBe("问题");
    expect(turn?.citations.map((citation) => citation.chunk_id)).toEqual(["c1", "c2"]);
  });

  test("keeps the LAST turn when the transcript has several", () => {
    const messages = [
      human("h1"),
      toolMessage("knowledge_search", HYBRID, "t1"),
      ai("a1"),
      { type: "human", id: "h2", content: "第二个问题" } as unknown as Message,
      toolMessage("graph_search", GRAPH, "t2"),
      ai("a2"),
    ];
    const turn = latestRetrievalTurn(messages);
    expect(turn?.messageId).toBe("a2");
    expect(turn?.text).toBe("第二个问题");
    expect(turn?.citations.map((citation) => citation.chunk_id)).toEqual(["c3"]);
  });

  test("walks past a hide_from_ui human (human_input_response) to the visible question", () => {
    // ask_clarification 轮：隐藏 human 的 content 是结构化 JSON，不能作为 query
    // 文本去投影——该轮的语义提问取更早的可见 human。
    const messages = [
      { type: "human", id: "h1", content: "JVM 是什么" } as unknown as Message,
      ai("a1"), // ask_clarification 中断提问（无引用）
      {
        type: "human",
        id: "h2",
        content: '{"type":"human_input_response","answer":"展开说说"}',
        additional_kwargs: { hide_from_ui: true },
      } as unknown as Message,
      toolMessage("knowledge_search", HYBRID, "t1"),
      ai("a2"),
    ];
    const turn = latestRetrievalTurn(messages);
    expect(turn?.messageId).toBe("a2");
    expect(turn?.text).toBe("JVM 是什么");
  });

  test("extracts text from complex human content arrays", () => {
    const messages = [
      {
        type: "human",
        id: "h1",
        content: [{ type: "text", text: "数组形态提问" }],
      } as unknown as Message,
      toolMessage("knowledge_search", HYBRID, "t1"),
      ai("a1"),
    ];
    expect(latestRetrievalTurn(messages)?.text).toBe("数组形态提问");
  });
});

// ── P4 graph_search 路径高亮（2026-08-19 spec §7）：检索轨迹提取 ─────────────

const GRAPH_TRACE = {
  entities: [],
  relations: [],
  evidence: [{ chunk_id: "c3", text: "证据切片", doc_name: "手册.pdf", heading_path: ["第二章"], page: 5 }],
  trace: {
    seed_entities: ["JVM"],
    expanded_nodes: [
      { name: "堆内存", hop: 1 },
      { name: "垃圾回收", hop: 2 },
    ],
    evidence_entities: ["JVM", "堆内存"],
  },
  message: "命中 1 个实体。",
};

describe("parseGraphSearchTrace", () => {
  test("parses the three-layer trace from a graph_search payload", () => {
    expect(parseGraphSearchTrace(JSON.stringify(GRAPH_TRACE))).toEqual({
      seed_entities: ["JVM"],
      expanded_nodes: [
        { name: "堆内存", hop: 1 },
        { name: "垃圾回收", hop: 2 },
      ],
      evidence_entities: ["JVM", "堆内存"],
    });
  });

  test("returns null for malformed payloads or a missing trace (legacy responses)", () => {
    expect(parseGraphSearchTrace("not-json")).toBeNull();
    expect(parseGraphSearchTrace(JSON.stringify(GRAPH))).toBeNull(); // 旧响应无 trace 字段
    expect(parseGraphSearchTrace(JSON.stringify({ trace: "junk" }))).toBeNull();
  });

  test("drops malformed trace entries defensively", () => {
    const trace = parseGraphSearchTrace(
      JSON.stringify({
        trace: {
          seed_entities: ["JVM", 42],
          expanded_nodes: [{ name: "堆内存", hop: 1 }, { name: 7, hop: "x" }, "junk"],
          evidence_entities: ["JVM", null],
        },
      }),
    );
    expect(trace).toEqual({
      seed_entities: ["JVM"],
      expanded_nodes: [{ name: "堆内存", hop: 1 }],
      evidence_entities: ["JVM"],
    });
  });
});

describe("latestGraphTraceTurn", () => {
  test("returns null for an empty transcript or one without an assistant answer", () => {
    expect(latestGraphTraceTurn([])).toBeNull();
    expect(latestGraphTraceTurn([human("h1")])).toBeNull();
  });

  test("returns null when the latest turn ran no graph_search (or the trace is empty)", () => {
    // 最后一轮只走了 hybrid 路 → 图谱叠加不更新（语义对齐 latestRetrievalTurn）。
    const hybridOnly = [human("h1"), toolMessage("knowledge_search", HYBRID, "t1"), ai("a1")];
    expect(latestGraphTraceTurn(hybridOnly)).toBeNull();
    // graph_search 空命中（trace 三层全空）→ 同样不更新（避免全图无意义淡化）。
    const emptyTrace = {
      ...GRAPH_TRACE,
      trace: { seed_entities: [], expanded_nodes: [], evidence_entities: [] },
    };
    const emptyRun = [human("h1"), toolMessage("graph_search", emptyTrace, "t1"), ai("a1")];
    expect(latestGraphTraceTurn(emptyRun)).toBeNull();
  });

  test("extracts the latest turn's trace with the visible question text", () => {
    const messages = [human("h1"), toolMessage("graph_search", GRAPH_TRACE, "t1"), ai("a1")];
    const turn = latestGraphTraceTurn(messages);
    expect(turn?.messageId).toBe("a1");
    expect(turn?.text).toBe("问题");
    expect(turn?.trace).toEqual({
      seed_entities: ["JVM"],
      expanded_nodes: [
        { name: "堆内存", hop: 1 },
        { name: "垃圾回收", hop: 2 },
      ],
      evidence_entities: ["JVM", "堆内存"],
    });
  });

  test("scopes to the LAST turn — an earlier graph turn stays invisible", () => {
    const messages = [
      human("h1"),
      toolMessage("graph_search", GRAPH_TRACE, "t1"),
      ai("a1"),
      { type: "human", id: "h2", content: "闲聊" } as unknown as Message,
      ai("a2"),
    ];
    expect(latestGraphTraceTurn(messages)).toBeNull();
  });

  test("merges several graph_search calls in one turn (union seeds/evidence, min hop)", () => {
    const second = {
      ...GRAPH_TRACE,
      trace: {
        seed_entities: ["GC"],
        expanded_nodes: [
          { name: "堆内存", hop: 2 },
          { name: "元空间", hop: 1 },
        ],
        evidence_entities: ["GC"],
      },
    };
    const messages = [
      human("h1"),
      toolMessage("graph_search", GRAPH_TRACE, "t1"),
      toolMessage("graph_search", second, "t2"),
      ai("a1"),
    ];
    const turn = latestGraphTraceTurn(messages);
    expect(turn?.trace.seed_entities).toEqual(["JVM", "GC"]);
    // 堆内存两次调用分别 hop1/hop2 → 取更浅的 hop1（插入序稳定）。
    expect(turn?.trace.expanded_nodes).toEqual([
      { name: "堆内存", hop: 1 },
      { name: "垃圾回收", hop: 2 },
      { name: "元空间", hop: 1 },
    ]);
    expect(turn?.trace.evidence_entities).toEqual(["JVM", "堆内存", "GC"]);
  });

  test("walks past a hide_from_ui human to the visible question", () => {
    const messages = [
      { type: "human", id: "h1", content: "JVM 结构" } as unknown as Message,
      {
        type: "human",
        id: "h2",
        content: '{"type":"human_input_response","answer":"展开"}',
        additional_kwargs: { hide_from_ui: true },
      } as unknown as Message,
      toolMessage("graph_search", GRAPH_TRACE, "t1"),
      ai("a1"),
    ];
    expect(latestGraphTraceTurn(messages)?.text).toBe("JVM 结构");
  });

  test("falls back to event-collected traces when the message body was externalized", () => {
    // 工具输出预算把超大 graph_search 结果替换成摘要预览：消息体解析不出 trace。
    const synopsis = "[Full graph_search output saved to /x/.tool-results/g.txt (20592 chars, ~5148 tokens).]";
    const messages = [
      human("h1"),
      { ...toolMessage("graph_search", synopsis, "t1"), tool_call_id: "call-9" } as unknown as Message,
      ai("a1"),
    ];
    expect(latestGraphTraceTurn(messages)).toBeNull();

    const turn = latestGraphTraceTurn(
      messages,
      new Map([
        [
          "call-9",
          {
            seed_entities: ["JVM"],
            expanded_nodes: [{ name: "堆内存", hop: 1 }],
            evidence_entities: ["JVM"],
          },
        ],
      ]),
    );
    expect(turn?.messageId).toBe("a1");
    expect(turn?.text).toBe("问题");
    expect(turn?.trace).toEqual({
      seed_entities: ["JVM"],
      expanded_nodes: [{ name: "堆内存", hop: 1 }],
      evidence_entities: ["JVM"],
    });
  });

  test("event fallback merges with parsed messages in the same turn", () => {
    const synopsis = "[Full graph_search output saved to /x/.tool-results/g.txt (20592 chars).]";
    const second = {
      ...GRAPH_TRACE,
      trace: {
        seed_entities: ["GC"],
        expanded_nodes: [{ name: "元空间", hop: 1 }],
        evidence_entities: ["GC"],
      },
    };
    const messages = [
      human("h1"),
      { ...toolMessage("graph_search", synopsis, "t1"), tool_call_id: "call-9" } as unknown as Message,
      toolMessage("graph_search", second, "t2"),
      ai("a1"),
    ];
    const turn = latestGraphTraceTurn(
      messages,
      new Map([["call-9", { seed_entities: ["JVM"], expanded_nodes: [], evidence_entities: ["JVM"] }]]),
    );
    expect(turn?.trace.seed_entities).toEqual(["JVM", "GC"]);
    expect(turn?.trace.evidence_entities).toEqual(["JVM", "GC"]);
  });
});

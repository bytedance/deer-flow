/**
 * Citation extraction from retrieval tool messages (spec §4.6).
 *
 * The rag agent's tools return JSON payloads: knowledge_search ``results`` and
 * graph_search ``evidence`` are chunk-level sources; wiki_search ``entries``
 * are entry-level (title as the source name, full content as the text). An
 * assistant answer's ``[n]`` markers map onto the merged, deduped source list
 * of its own turn — everything between the previous human message and the
 * answer, in tool-call order.
 */
import type { Message } from "@langchain/langgraph-sdk";

import { extractTextFromMessage } from "@/core/messages/utils";

import type { GraphRetrievalTrace, KnowledgeCitation } from "./types";

const RETRIEVAL_TOOLS = new Set(["knowledge_search", "wiki_search", "graph_search"]);

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function toCitation(value: unknown, fallbackName: string | undefined, sourceType: "chunk" | "wiki"): KnowledgeCitation | null {
  const record = asRecord(value);
  if (!record) return null;
  const chunkId = record.chunk_id ?? record.entry_id;
  const text = record.text ?? record.content;
  if (typeof chunkId !== "string" || typeof text !== "string") return null;
  const citationNo = typeof record.citation_no === "number" ? record.citation_no : null;
  // Phase-3 P6 (spec §8): wiki_search mixes manual cards into its entries and
  // stamps each hit with its own source_type — a valid payload value wins over
  // the tool-name fallback.
  const payloadType = record.source_type;
  const resolvedType = payloadType === "manual" || payloadType === "wiki" || payloadType === "chunk" ? payloadType : sourceType;
  return {
    chunk_id: chunkId,
    doc_name: typeof record.doc_name === "string" ? record.doc_name : (fallbackName ?? ""),
    page: typeof record.page === "number" ? record.page : null,
    heading_path: Array.isArray(record.heading_path) ? (record.heading_path as string[]) : [],
    text,
    score: typeof record.score === "number" ? record.score : 0,
    source_type: resolvedType,
    ...(citationNo != null ? { citation_nos: [citationNo] } : {}),
  };
}

/** Parse one retrieval tool message payload into citations (bad input → []). */
export function parseRetrievalToolContent(toolName: string | null | undefined, content: unknown): KnowledgeCitation[] {
  if (!toolName || !RETRIEVAL_TOOLS.has(toolName)) {
    return [];
  }
  let payload: unknown = content;
  if (typeof content === "string") {
    try {
      payload = JSON.parse(content);
    } catch {
      return [];
    }
  }
  const record = asRecord(payload);
  if (!record) {
    return [];
  }
  const key = toolName === "knowledge_search" ? "results" : toolName === "wiki_search" ? "entries" : "evidence";
  // source_type falls back to the tool the payload came through; phase-3 P6
  // payloads may override it per item (manual cards ride wiki_search).
  const sourceType = toolName === "wiki_search" ? "wiki" : "chunk";
  const items = Array.isArray(record[key]) ? (record[key] as unknown[]) : [];
  return items
    .map((item) => toCitation(item, typeof asRecord(item)?.title === "string" ? (asRecord(item)?.title as string) : undefined, sourceType))
    .filter((citation): citation is KnowledgeCitation => citation !== null);
}

/**
 * Sources for one assistant answer: every retrieval tool message between the
 * preceding human message and that answer, merged in order and deduped by
 * chunk_id. First recall wins for the card content (better rank), but the
 * citation numbers of EVERY path merge onto the surviving card: hybrid and
 * graph often recall the same chunk under different citation_no ranges, and
 * the model cites either number — dropping one would strand those ``[n]``
 * marks (they'd point past the end of the deduped list).
 */
export function sourcesForAssistantMessage(
  messages: readonly Message[],
  assistantMessageId: string | undefined,
): KnowledgeCitation[] {
  if (!assistantMessageId) {
    return [];
  }
  const answerIndex = messages.findIndex((message) => message.id === assistantMessageId);
  if (answerIndex < 0) {
    return [];
  }
  let turnStart = 0;
  for (let index = answerIndex - 1; index >= 0; index -= 1) {
    if (messages[index]?.type === "human") {
      turnStart = index + 1;
      break;
    }
  }
  const byChunkId = new Map<string, KnowledgeCitation>();
  const sources: KnowledgeCitation[] = [];
  for (let index = turnStart; index < answerIndex; index += 1) {
    const message = messages[index];
    if (message?.type !== "tool") {
      continue;
    }
    const toolName = (message as { name?: string }).name;
    for (const citation of parseRetrievalToolContent(toolName, message.content)) {
      const existing = byChunkId.get(citation.chunk_id);
      if (existing) {
        if (citation.citation_nos) {
          const merged = existing.citation_nos ?? (existing.citation_nos = []);
          for (const no of citation.citation_nos) {
            if (!merged.includes(no)) {
              merged.push(no);
            }
          }
        }
        continue;
      }
      byChunkId.set(citation.chunk_id, citation);
      sources.push(citation);
    }
  }
  // Display order: sort by each card's smallest merged citation_no. Tool
  // completion order varies run to run (wiki may finish before or after the
  // chunk tools), but the citation numbers are what the model saw — sorting
  // by them keeps the strip stable, and the sorted position becomes the
  // display number (1..N), the only number the user ever sees. Cards without
  // citation numbers (legacy payloads) keep their relative order at the end.
  return sources
    .map((source, index) => ({ source, index }))
    .sort((a, b) => minCitationNo(a.source) - minCitationNo(b.source) || a.index - b.index)
    .map((entry) => entry.source);
}

function minCitationNo(source: KnowledgeCitation): number {
  return source.citation_nos?.length ? Math.min(...source.citation_nos) : Number.POSITIVE_INFINITY;
}

// ── P6 检索联动（2026-08-15 spec §9 通道二）──────────────────────────────

/** 最新一轮已完成检索对话的叠加上下文（供向量空间投影联动）。 */
export interface RetrievalTurn {
  /** 该轮 ai message id——调用方去重句柄（同一轮只上报一次）。 */
  messageId: string;
  /** 该轮的可见用户提问文本（跳过 hide_from_ui 的 human_input_response）。 */
  text: string;
  /** 该轮合并引用（sourcesForAssistantMessage 已 dedupe / 按展示号排序）。 */
  citations: KnowledgeCitation[];
}

/**
 * 提取最新一轮「有引用」的助手回答。只认最后一条 ai message：它没有引用就
 * 返回 null（该轮不更新叠加，旧叠加由调用方保留或按指纹规则清理），绝不
 * 回退到更早的轮次——叠加层的语义是「刚才那轮问答」。
 */
export function latestRetrievalTurn(messages: readonly Message[]): RetrievalTurn | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.type !== "ai") {
      continue;
    }
    const citations = sourcesForAssistantMessage(messages, message.id);
    if (citations.length === 0) {
      return null;
    }
    let text = "";
    for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
      const candidate = messages[cursor];
      if (candidate?.type === "human" && candidate.additional_kwargs?.hide_from_ui !== true) {
        text = extractTextFromMessage(candidate);
        break;
      }
    }
    return { messageId: message.id ?? "", text, citations };
  }
  return null;
}

// ── P4 graph_search 路径高亮（2026-08-19 spec §7）：检索轨迹提取 ─────────────

/** 从单条 graph_search 工具消息内容解析检索轨迹（无 trace 字段 / 非法 → null）。 */
export function parseGraphSearchTrace(content: unknown): GraphRetrievalTrace | null {
  let payload: unknown = content;
  if (typeof content === "string") {
    try {
      payload = JSON.parse(content);
    } catch {
      return null;
    }
  }
  const trace = asRecord(asRecord(payload)?.trace);
  if (!trace) {
    return null;
  }
  const names = (value: unknown): string[] =>
    Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  const expandedNodes = (Array.isArray(trace.expanded_nodes) ? trace.expanded_nodes : [])
    .map((item) => asRecord(item))
    .filter(
      (item): item is Record<string, unknown> =>
        item !== null && typeof item.name === "string" && typeof item.hop === "number",
    )
    .map((item) => ({ name: item.name as string, hop: item.hop as number }));
  return {
    seed_entities: names(trace.seed_entities),
    expanded_nodes: expandedNodes,
    evidence_entities: names(trace.evidence_entities),
  };
}

/** 最新一轮含图谱检索轨迹的助手回答（供知识图谱路径高亮叠加）。 */
export interface GraphTraceTurn {
  /** 该轮 ai message id——调用方去重句柄（同一轮只上报一次）。 */
  messageId: string;
  /** 该轮的可见用户提问文本（跳过 hide_from_ui 的 human_input_response）。 */
  text: string;
  /** 该轮全部 graph_search 调用合并后的轨迹（种子/证据并集，hop 取最浅）。 */
  trace: GraphRetrievalTrace;
}

/**
 * 提取最新一轮的图谱检索轨迹。语义对齐 latestRetrievalTurn：只认最后一条 ai
 * message——该轮没有 graph_search 轨迹就返回 null（不更新叠加，旧叠加由调用方
 * 保留或按指纹规则清理），绝不回退到更早的轮次。空命中（三层全空）同样不更新
 * ——避免全图无意义淡化。
 *
 * ``fallbackTraces``（按 tool_call_id 索引）是实时通道的兜底：工具输出预算
 * 中间件可能把超大 graph_search 结果替换成摘要预览，消息体解析不出 trace；
 * 此时若该调用通过 custom 事件（graph_retrieval_trace）旁路送达过轨迹，则用
 * 事件副本补齐。重载路径的消息来自 journal 全文，正常解析，不需要回退。
 */
export function latestGraphTraceTurn(messages: readonly Message[], fallbackTraces?: ReadonlyMap<string, GraphRetrievalTrace>): GraphTraceTurn | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.type !== "ai") {
      continue;
    }
    let turnStart = 0;
    for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
      if (messages[cursor]?.type === "human") {
        turnStart = cursor + 1;
        break;
      }
    }
    // 合并该轮全部 graph_search 调用：种子/证据并集（保序），扩展按名取最浅 hop。
    const seeds: string[] = [];
    const evidence: string[] = [];
    const hopByName = new Map<string, number>();
    for (let cursor = turnStart; cursor < index; cursor += 1) {
      const candidate = messages[cursor];
      if (candidate?.type !== "tool" || (candidate as { name?: string }).name !== "graph_search") {
        continue;
      }
      let trace = parseGraphSearchTrace(candidate.content);
      if (!trace && fallbackTraces) {
        const toolCallId = (candidate as { tool_call_id?: string }).tool_call_id;
        if (typeof toolCallId === "string") {
          trace = fallbackTraces.get(toolCallId) ?? null;
        }
      }
      if (!trace) {
        continue;
      }
      for (const name of trace.seed_entities) {
        if (!seeds.includes(name)) {
          seeds.push(name);
        }
      }
      for (const name of trace.evidence_entities) {
        if (!evidence.includes(name)) {
          evidence.push(name);
        }
      }
      for (const node of trace.expanded_nodes) {
        const previous = hopByName.get(node.name);
        if (previous === undefined || node.hop < previous) {
          hopByName.set(node.name, node.hop);
        }
      }
    }
    if (seeds.length === 0 && hopByName.size === 0 && evidence.length === 0) {
      return null;
    }
    let text = "";
    for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
      const candidate = messages[cursor];
      if (candidate?.type === "human" && candidate.additional_kwargs?.hide_from_ui !== true) {
        text = extractTextFromMessage(candidate);
        break;
      }
    }
    return {
      messageId: message.id ?? "",
      text,
      trace: {
        seed_entities: seeds,
        expanded_nodes: [...hopByName.entries()].map(([name, hop]) => ({ name, hop })),
        evidence_entities: evidence,
      },
    };
  }
  return null;
}

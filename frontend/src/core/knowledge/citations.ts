/**
 * Citation extraction from retrieval tool messages (spec §4.6).
 *
 * The rag agent's knowledge_search returns a JSON payload whose ``results``
 * are chunk-level sources. An assistant answer's ``[n]`` markers map onto the
 * merged, deduped source list of its own turn — everything between the
 * previous human message and the answer, in tool-call order.
 */
import type { Message } from "@langchain/langgraph-sdk";

import type { KnowledgeCitation } from "./types";

const RETRIEVAL_TOOL = "knowledge_search";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function toCitation(value: unknown, fallbackName: string | undefined): KnowledgeCitation | null {
  const record = asRecord(value);
  if (!record) return null;
  const chunkId = record.chunk_id;
  const text = record.text;
  if (typeof chunkId !== "string" || typeof text !== "string") return null;
  const citationNo = typeof record.citation_no === "number" ? record.citation_no : null;
  return {
    chunk_id: chunkId,
    doc_name: typeof record.doc_name === "string" ? record.doc_name : (fallbackName ?? ""),
    page: typeof record.page === "number" ? record.page : null,
    heading_path: Array.isArray(record.heading_path) ? (record.heading_path as string[]) : [],
    text,
    score: typeof record.score === "number" ? record.score : 0,
    source_type: "chunk",
    ...(citationNo != null ? { citation_nos: [citationNo] } : {}),
  };
}

/** Parse one retrieval tool message payload into citations (bad input → []). */
export function parseRetrievalToolContent(toolName: string | null | undefined, content: unknown): KnowledgeCitation[] {
  if (toolName !== RETRIEVAL_TOOL) {
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
  const items = Array.isArray(record.results) ? (record.results as unknown[]) : [];
  return items
    .map((item) => toCitation(item, typeof asRecord(item)?.title === "string" ? (asRecord(item)?.title as string) : undefined))
    .filter((citation): citation is KnowledgeCitation => citation !== null);
}

/**
 * Sources for one assistant answer: every retrieval tool message between the
 * preceding human message and that answer, merged in order and deduped by
 * chunk_id. First recall wins for the card content (better rank), but the
 * citation numbers of EVERY call merge onto the surviving card: repeated
 * calls often recall the same chunk under different citation_no ranges, and
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
  // completion order varies run to run, but the citation numbers are what the
  // model saw — sorting by them keeps the strip stable, and the sorted
  // position becomes the display number (1..N), the only number the user ever
  // sees. Cards without citation numbers (legacy payloads) keep their relative
  // order at the end.
  return sources
    .map((source, index) => ({ source, index }))
    .sort((a, b) => minCitationNo(a.source) - minCitationNo(b.source) || a.index - b.index)
    .map((entry) => entry.source);
}

function minCitationNo(source: KnowledgeCitation): number {
  return source.citation_nos?.length ? Math.min(...source.citation_nos) : Number.POSITIVE_INFINITY;
}

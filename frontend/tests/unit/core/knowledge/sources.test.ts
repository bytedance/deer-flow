import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import {
  citedKnowledgeSources,
  collectKnowledgeSources,
  knowledgeSourceId,
} from "@/core/knowledge/sources";

const id = "0123456789abcdef0123456789abcdef-1";
const source = {
  id,
  provider: "ragflow",
  document_name: "Manual.pdf",
  dataset_name: "Engineering",
  text: "Limit: 42.",
  truncated: false,
  pages: [3],
};
const message = {
  type: "tool",
  name: "knowledge_search",
  content: "retrieved",
  tool_call_id: "call",
  artifact: { knowledge_sources: { version: 1, sources: [source] } },
} as unknown as Message;

describe("knowledge citation provenance", () => {
  it("resolves repeated citations to the persisted tool evidence after JSON reload", () => {
    const messages = JSON.parse(JSON.stringify([message])) as Message[];
    const sources = collectKnowledgeSources(messages);
    const citation = `[citation:1](#knowledge-${id})`;
    expect(citedKnowledgeSources(`${citation} ${citation}`, sources)).toEqual([
      source,
    ]);
    expect(knowledgeSourceId(`#knowledge-${id}`)).toBe(id);
    expect(knowledgeSourceId(`#user-content-knowledge-${id}`)).toBe(id);
  });
  it("does not let model labels or human artifacts invent a source", () => {
    const sources = collectKnowledgeSources([
      { ...message, type: "human" } as Message,
      { ...message, type: "ai" } as Message,
    ]);
    expect(sources.size).toBe(0);
    expect(
      citedKnowledgeSources(`[citation:invented](#knowledge-${id})`, sources),
    ).toEqual([]);
    expect(knowledgeSourceId(`https://evil.test/#knowledge-${id}`)).toBeNull();
  });
  it("ignores citations in code and images", () => {
    const link = `[citation:1](#knowledge-${id})`;
    expect(
      citedKnowledgeSources(
        `\`${link}\`\n\n\`\`\`\n${link}\n\`\`\`\n!${link}`,
        collectKnowledgeSources([message]),
      ),
    ).toEqual([]);
  });
  it("rejects malformed and unknown artifact versions", () => {
    for (const payload of [
      { version: 2, sources: [source] },
      { version: 1, sources: [{ ...source, pages: [-1] }] },
      { version: 1, sources: [{ ...source, text: 42 }] },
    ]) {
      const bad = {
        ...message,
        artifact: { knowledge_sources: payload },
      } as Message;
      expect(collectKnowledgeSources([bad]).size).toBe(0);
    }
  });
  it("keeps independent source identities for repeated searches", () => {
    const other = {
      ...source,
      id: "fedcba9876543210fedcba9876543210-1",
      text: "Limit: 43.",
    };
    const next = {
      ...message,
      artifact: { knowledge_sources: { version: 1, sources: [other] } },
    } as Message;
    expect(collectKnowledgeSources([message, next, message]).size).toBe(2);
  });
});

it("collects ordinary Sources-section links without collecting code or images", () => {
  const link = `[Manual.pdf](#knowledge-${id})`;
  expect(
    citedKnowledgeSources(
      `## Sources\n- ${link}\n${link}`,
      collectKnowledgeSources([message]),
    ),
  ).toEqual([source]);
  expect(
    citedKnowledgeSources(
      `\`${link}\`\n!${link}`,
      collectKnowledgeSources([message]),
    ),
  ).toEqual([]);
});

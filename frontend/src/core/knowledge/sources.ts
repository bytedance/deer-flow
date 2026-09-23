import type { Message } from "@langchain/langgraph-sdk";

import { maskCitationCode } from "@/core/citations/sources";

export type KnowledgeSource = {
  id: string;
  provider: "ragflow";
  dataset_name: string;
  document_name: string;
  text: string;
  truncated: boolean;
  pages: number[];
};

const SOURCE_ID = /^[a-f0-9]{32}-[1-9][0-9]{0,2}$/;
const SOURCE_LINK =
  /(?<!!)\[[^\]\n]+\]\(#(?:user-content-)?knowledge-([a-f0-9]{32}-[1-9][0-9]{0,2})\)/g;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Read only native tool artifacts, never model or human-provided metadata. */
export function collectKnowledgeSources(messages: readonly Message[]) {
  const sources = new Map<string, KnowledgeSource>();
  for (const message of messages) {
    if (
      message.type !== "tool" ||
      !["knowledge_search", "task"].includes(message.name ?? "")
    )
      continue;
    const artifact: unknown = Reflect.get(message, "artifact");
    const payload = record(artifact) ? artifact.knowledge_sources : null;
    if (
      !record(payload) ||
      payload.version !== 1 ||
      !Array.isArray(payload.sources)
    )
      continue;
    for (const raw of payload.sources.slice(0, 100)) {
      if (
        !record(raw) ||
        typeof raw.id !== "string" ||
        !SOURCE_ID.test(raw.id) ||
        raw.provider !== "ragflow"
      )
        continue;
      if (
        typeof raw.document_name !== "string" ||
        raw.document_name.length > 1024 ||
        typeof raw.dataset_name !== "string" ||
        raw.dataset_name.length > 1024 ||
        typeof raw.text !== "string" ||
        raw.text.length > 200_000 ||
        typeof raw.truncated !== "boolean" ||
        !Array.isArray(raw.pages) ||
        raw.pages.length > 100 ||
        !raw.pages.every(
          (page: unknown) =>
            typeof page === "number" &&
            Number.isInteger(page) &&
            page > 0 &&
            page <= 1_000_000,
        )
      )
        continue;
      const source: KnowledgeSource = {
        id: raw.id,
        provider: "ragflow",
        dataset_name: raw.dataset_name,
        document_name: raw.document_name,
        text: raw.text,
        truncated: raw.truncated,
        pages: raw.pages as number[],
      };
      // Stream replays can repeat records; never silently replace evidence.
      if (!sources.has(source.id)) sources.set(source.id, source);
    }
  }
  return sources;
}

export function knowledgeSourceId(href: string | undefined): string | null {
  // rehype-sanitize prefixes same-document anchors to prevent DOM clobbering.
  const match =
    /^#(?:user-content-)?knowledge-([a-f0-9]{32}-[1-9][0-9]{0,2})$/.exec(
      href ?? "",
    );
  return match?.[1] ?? null;
}

export function citedKnowledgeSources(
  markdown: string,
  sources: ReadonlyMap<string, KnowledgeSource>,
) {
  const result: KnowledgeSource[] = [];
  const seen = new Set<string>();
  for (const match of maskCitationCode(markdown).matchAll(SOURCE_LINK)) {
    const id = match[1]!;
    const source = sources.get(id);
    if (source && !seen.has(id)) {
      seen.add(id);
      result.push(source);
    }
  }
  return result;
}

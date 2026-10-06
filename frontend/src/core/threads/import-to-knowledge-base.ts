import type { Message } from "@langchain/langgraph-sdk";

import { listDocuments, uploadDocument } from "@/core/knowledge/api";
import { nextCopyName } from "@/core/knowledge/duplicate-check";

import { formatThreadAsMarkdown, sanitizeFilename } from "./export";
import type { AgentThread } from "./types";
import { titleOfThread } from "./utils";

export interface ImportToKnowledgeBaseResult {
  /** Final document name in the KB — may carry a ` (2)` suffix on conflicts. */
  documentName: string;
  /** True when the preferred name was taken and a copy suffix was allocated. */
  renamed: boolean;
}

/**
 * Import a conversation into a knowledge base as a Markdown document.
 *
 * Reuses the export formatter (same user-visible transcript) and the regular
 * KB upload pipeline — no dedicated backend endpoint. Name collisions are
 * resolved client-side with the same `name (2).md` rule the knowledge page's
 * "keep both" flow uses.
 */
export async function importThreadToKnowledgeBase(
  thread: AgentThread,
  messages: Message[],
  kbId: string,
): Promise<ImportToKnowledgeBaseResult> {
  const markdown = formatThreadAsMarkdown(thread, messages);
  const baseFilename = `${sanitizeFilename(titleOfThread(thread))}.md`;
  const documents = await listDocuments(kbId);
  const existingNames = new Set(documents.map((doc) => doc.name));
  const filename = existingNames.has(baseFilename)
    ? nextCopyName(baseFilename, existingNames)
    : baseFilename;
  const file = new File([markdown], filename, {
    type: "text/markdown;charset=utf-8",
  });
  await uploadDocument(kbId, file);
  return { documentName: filename, renamed: filename !== baseFilename };
}

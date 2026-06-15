import type { Message } from "@langchain/langgraph-sdk";

import { fetch } from "@/core/api/fetcher";
import type { UIBlock } from "@/core/genui/store";
import { extractTextFromMessage } from "@/core/messages/utils";

const BLOCK_ID_REGEX = /block_id=([A-Za-z0-9_-]+)/g;

function getBackendBaseUrl(): string {
  if (typeof window !== "undefined") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

export function getHistoryMessageKey(message: Message): string {
  return (
    message.id ??
    ("tool_call_id" in message ? message.tool_call_id : undefined) ??
    `${message.type}:${extractTextFromMessage(message)}`
  );
}

export function extractBlockIdsFromMessages(messages: Message[]): string[] {
  const blockIds: string[] = [];
  for (const msg of messages) {
    if (msg.type === "tool") {
      const text = extractTextFromMessage(msg);
      let match: RegExpExecArray | null;
      BLOCK_ID_REGEX.lastIndex = 0;
      while ((match = BLOCK_ID_REGEX.exec(text)) !== null) {
        blockIds.push(match[1]!);
      }
    }
  }
  return blockIds;
}

interface ResolvedBlockHistory {
  blocks: UIBlock[];
  blockIdsByMessageKey: Map<string, string[]>;
  duplicatedRawBlockIds: Set<string>;
}

export async function fetchResolvedBlockHistory(
  threadId: string,
  messages: Message[],
): Promise<ResolvedBlockHistory> {
  const baseUrl = getBackendBaseUrl();
  const response = await fetch(
    `${baseUrl}/api/threads/${encodeURIComponent(threadId)}/ui-blocks/extract`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    },
  );

  if (!response.ok) {
    return { blocks: [], blockIdsByMessageKey: new Map(), duplicatedRawBlockIds: new Set() };
  }

  const data: {
    blocks: UIBlock[];
    blockIdsByMessageKey: Record<string, string[]>;
    duplicatedRawBlockIds: string[];
  } = await response.json();

  return {
    blocks: data.blocks,
    blockIdsByMessageKey: new Map(Object.entries(data.blockIdsByMessageKey)),
    duplicatedRawBlockIds: new Set(data.duplicatedRawBlockIds),
  };
}

export async function extractBlocksIncremental(
  threadId: string,
  newMessages: Message[],
): Promise<ResolvedBlockHistory> {
  if (newMessages.length === 0) {
    return { blocks: [], blockIdsByMessageKey: new Map(), duplicatedRawBlockIds: new Set() };
  }
  return fetchResolvedBlockHistory(threadId, newMessages);
}

export function extractResolvedBlockIdsFromMessages(
  messages: Message[],
  blockIdsByMessageKey: Map<string, string[]>,
): string[] {
  const resolvedBlockIds: string[] = [];

  for (const message of messages) {
    const blockIds = blockIdsByMessageKey.get(getHistoryMessageKey(message));
    if (blockIds && blockIds.length > 0) {
      resolvedBlockIds.push(...blockIds);
      continue;
    }

    resolvedBlockIds.push(...extractBlockIdsFromMessages([message]));
  }

  return resolvedBlockIds;
}

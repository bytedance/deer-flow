import type { Message } from "@langchain/langgraph-sdk";

import type { UIBlock } from "@/core/genui/store";
import { extractTextFromMessage } from "@/core/messages/utils";

const BLOCK_ID_REGEX = /block_id=([A-Za-z0-9_-]+)/g;
const UI_BLOCK_PATTERN = /<!--ui_block:(.+?)-->/g;

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

type ResolvedBlockHistory = {
  blocks: UIBlock[];
  blockIdsByMessageKey: Map<string, string[]>;
  duplicatedRawBlockIds: Set<string>;
};

function buildCreateBlockCounts(messages: Message[]): Map<string, number> {
  const counts = new Map<string, number>();

  for (const message of messages) {
    if (message.type !== "tool" || typeof message.content !== "string") {
      continue;
    }

    UI_BLOCK_PATTERN.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = UI_BLOCK_PATTERN.exec(message.content)) !== null) {
      try {
        const block = JSON.parse(match[1]!) as UIBlock;
        if (!block.block_id) {
          continue;
        }

        const action = block.action ?? "create";
        if (action !== "create") {
          continue;
        }

        counts.set(block.block_id, (counts.get(block.block_id) ?? 0) + 1);
      } catch {
        // Ignore malformed JSON markers.
      }
    }
  }

  return counts;
}

function getResolvedBlockId(
  rawBlockId: string,
  createCounts: Map<string, number>,
  createIndices: Map<string, number>,
): string {
  const occurrence = createIndices.get(rawBlockId) ?? 0;
  if ((createCounts.get(rawBlockId) ?? 0) <= 1) {
    return rawBlockId;
  }
  return `${rawBlockId}__${occurrence}`;
}

export function buildResolvedBlockHistory(
  messages: Message[],
): ResolvedBlockHistory {
  const createCounts = buildCreateBlockCounts(messages);
  const duplicatedRawBlockIds = new Set(
    Array.from(createCounts.entries())
      .filter(([, count]) => count > 1)
      .map(([blockId]) => blockId),
  );
  const createIndices = new Map<string, number>();
  const latestResolvedBlockIdByRaw = new Map<string, string>();
  const blocks = new Map<string, UIBlock>();
  const blockIdsByMessageKey = new Map<string, string[]>();

  for (const message of messages) {
    if (message.type !== "tool" || typeof message.content !== "string") {
      continue;
    }

    const resolvedBlockIds: string[] = [];
    UI_BLOCK_PATTERN.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = UI_BLOCK_PATTERN.exec(message.content)) !== null) {
      try {
        const block = JSON.parse(match[1]!) as UIBlock;
        const rawBlockId = block.block_id;
        if (!rawBlockId) {
          continue;
        }

        const action = block.action ?? "create";
        if (action === "create") {
          const nextCreateIndex = (createIndices.get(rawBlockId) ?? 0) + 1;
          createIndices.set(rawBlockId, nextCreateIndex);
          const resolvedBlockId = getResolvedBlockId(
            rawBlockId,
            createCounts,
            createIndices,
          );
          latestResolvedBlockIdByRaw.set(rawBlockId, resolvedBlockId);
          blocks.set(resolvedBlockId, {
            ...block,
            block_id: resolvedBlockId,
            metadata: {
              ...block.metadata,
              raw_block_id: rawBlockId,
            },
          });
          resolvedBlockIds.push(resolvedBlockId);
          continue;
        }

        const resolvedBlockId =
          latestResolvedBlockIdByRaw.get(rawBlockId) ?? rawBlockId;

        if (action === "delete") {
          blocks.delete(resolvedBlockId);
          continue;
        }

        const existing = blocks.get(resolvedBlockId);
        if (existing) {
          blocks.set(resolvedBlockId, {
            ...existing,
            ...block,
            block_id: resolvedBlockId,
            props: {
              ...existing.props,
              ...block.props,
            },
            metadata: {
              ...existing.metadata,
              ...block.metadata,
              raw_block_id: rawBlockId,
            },
          });
        } else {
          blocks.set(resolvedBlockId, {
            ...block,
            block_id: resolvedBlockId,
            metadata: {
              ...block.metadata,
              raw_block_id: rawBlockId,
            },
          });
        }
        latestResolvedBlockIdByRaw.set(rawBlockId, resolvedBlockId);
        resolvedBlockIds.push(resolvedBlockId);
      } catch {
        // Ignore malformed JSON markers.
      }
    }

    if (resolvedBlockIds.length > 0) {
      blockIdsByMessageKey.set(
        getHistoryMessageKey(message),
        Array.from(new Set(resolvedBlockIds)),
      );
    }
  }

  return {
    blocks: Array.from(blocks.values()),
    blockIdsByMessageKey,
    duplicatedRawBlockIds,
  };
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

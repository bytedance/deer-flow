import type { Message } from "@langchain/langgraph-sdk";

import { extractTextFromMessage } from "@/core/messages/utils";

const BLOCK_ID_REGEX = /block_id=([A-Za-z0-9_-]+)/g;

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

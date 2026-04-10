import type { Message } from "@langchain/langgraph-sdk";

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

export type TokenUsageCache = Map<string, TokenUsage>;

/**
 * Extract usage_metadata from an AI message if present.
 * When a later stream snapshot temporarily omits usage_metadata for a message
 * we fall back to the last seen value stored in the cache.
 */
function getUsageMetadata(
  message: Message,
  cache?: TokenUsageCache,
): TokenUsage | null {
  if (message.type !== "ai") {
    return null;
  }

  const messageId =
    typeof message.id === "string" && message.id.length > 0 ? message.id : null;
  const usage = (message as Record<string, unknown>).usage_metadata as
    | { input_tokens?: number; output_tokens?: number; total_tokens?: number }
    | undefined;

  if (usage) {
    const normalized = {
      inputTokens: usage.input_tokens ?? 0,
      outputTokens: usage.output_tokens ?? 0,
      totalTokens: usage.total_tokens ?? 0,
    };
    if (messageId && cache) {
      cache.set(messageId, normalized);
    }
    return normalized;
  }

  if (messageId && cache?.has(messageId)) {
    return cache.get(messageId) ?? null;
  }

  return null;
}

function getMessageUsageKey(message: Message, index: number): string {
  if (typeof message.id === "string" && message.id.length > 0) {
    return message.id;
  }
  return `idx:${index}`;
}

/**
 * Accumulate token usage across all AI messages in a thread.
 * Messages are deduplicated by id to avoid double counting when the same
 * message appears multiple times during stream reconciliation.
 */
export function accumulateUsage(
  messages: Message[],
  cache?: TokenUsageCache,
): TokenUsage | null {
  const cumulative: TokenUsage = {
    inputTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
  };
  let hasUsage = false;
  const latestUsageByKey = new Map<string, TokenUsage | null>();

  for (const [index, message] of messages.entries()) {
    const key = getMessageUsageKey(message, index);
    const usage = getUsageMetadata(message, cache);
    latestUsageByKey.set(key, usage);
  }

  for (const usage of latestUsageByKey.values()) {
    if (usage) {
      hasUsage = true;
      cumulative.inputTokens += usage.inputTokens;
      cumulative.outputTokens += usage.outputTokens;
      cumulative.totalTokens += usage.totalTokens;
    }
  }

  return hasUsage ? cumulative : null;
}

/**
 * Format a token count for display: 1234 -> "1,234", 12345 -> "12.3K"
 */
export function formatTokenCount(count: number): string {
  if (count < 10_000) {
    return count.toLocaleString();
  }
  return `${(count / 1000).toFixed(1)}K`;
}

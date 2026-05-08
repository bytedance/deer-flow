import type { Message } from "@langchain/langgraph-sdk";

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

/**
 * Extract usage_metadata from an AI message if present.
 * The field is added by the backend (PR #1218) but not typed in the SDK.
 */
export function getUsageMetadata(message: Message): TokenUsage | null {
  if (message.type !== "ai") {
    return null;
  }
  const usage = (message as Record<string, unknown>).usage_metadata as
    | { input_tokens?: number; output_tokens?: number; total_tokens?: number }
    | undefined;
  if (!usage) {
    return null;
  }
  return {
    inputTokens: usage.input_tokens ?? 0,
    outputTokens: usage.output_tokens ?? 0,
    totalTokens: usage.total_tokens ?? 0,
  };
}

/**
 * Accumulate token usage across AI messages.
 *
 * UI rendering may place the same AI message in more than one group, such as
 * when a message contains both reasoning and final answer content. Token usage
 * is attached to the AI message itself, so a message id should only contribute
 * once to any aggregate.
 */
export function accumulateUsage(messages: Message[]): TokenUsage | null {
  const cumulative: TokenUsage = {
    inputTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
  };
  let hasUsage = false;
  const countedMessageIds = new Set<string>();

  for (const message of messages) {
    const usage = getUsageMetadata(message);
    if (!usage) {
      continue;
    }

    if (message.id) {
      if (countedMessageIds.has(message.id)) {
        continue;
      }
      countedMessageIds.add(message.id);
    }

    hasUsage = true;
    cumulative.inputTokens += usage.inputTokens;
    cumulative.outputTokens += usage.outputTokens;
    cumulative.totalTokens += usage.totalTokens;
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

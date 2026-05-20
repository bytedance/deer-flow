import type { TokenUsage } from "@/core/messages/usage";

import type { ContextUsage } from "./api";
import type { ThreadTokenUsageResponse } from "./types";

export function threadTokenUsageQueryKey(threadId?: string | null) {
  return ["thread-token-usage", threadId] as const;
}

export function contextUsageQueryKey(threadId?: string | null) {
  return ["thread-context-usage", threadId] as const;
}

export function threadTokenUsageToTokenUsage(
  usage: ThreadTokenUsageResponse | null | undefined,
): TokenUsage | null {
  if (!usage) {
    return null;
  }
  return {
    inputTokens: usage.total_input_tokens ?? 0,
    outputTokens: usage.total_output_tokens ?? 0,
    totalTokens: usage.total_tokens ?? 0,
  };
}

export function threadTokenUsageToContextUsage(
  usage: ThreadTokenUsageResponse | null | undefined,
): ContextUsage | null {
  return usage?.context_usage ?? null;
}

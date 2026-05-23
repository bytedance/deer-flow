import type { TokenUsage } from "@/core/messages/usage";

import type { ThreadTokenUsageResponse } from "./types";

export function threadTokenUsageQueryKey(threadId?: string | null) {
  return ["thread-token-usage", threadId] as const;
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

export interface ContextUsageBreakdownItem {
  key: string;
  tokens: number;
  active: boolean;
}

export interface ContextUsage {
  usedTokens: number;
  maxContextTokens: number | null;
  percentage: number | null;
  breakdown: ContextUsageBreakdownItem[];
}

export function selectContextUsage(
  usage: ThreadTokenUsageResponse | null | undefined,
): ContextUsage | null {
  if (!usage?.context_usage) {
    return null;
  }
  const { used_tokens, max_context_tokens, percentage, breakdown } =
    usage.context_usage;
  return {
    usedTokens: used_tokens ?? 0,
    maxContextTokens: max_context_tokens ?? null,
    percentage: percentage ?? null,
    breakdown: (breakdown ?? []).map((row) => ({
      key: row.key,
      tokens: row.tokens,
      active: row.active,
    })),
  };
}

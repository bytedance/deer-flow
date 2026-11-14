import type { TokenUsage } from "@/core/messages/usage";

import type { ThreadTokenUsageResponse } from "./types";

export function threadTokenUsageQueryKey(threadId?: string | null) {
  return ["thread-token-usage", threadId] as const;
}

export function retainThreadTokenUsagePlaceholder(
  previous: ThreadTokenUsageResponse | null | undefined,
  threadId?: string | null,
): ThreadTokenUsageResponse | undefined {
  return previous && previous.thread_id === threadId ? previous : undefined;
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

export interface ContextUsage {
  tokenCount: number;
  maxContextTokens: number | null;
  percentage: number | null;
}

export function selectContextUsage(
  usage: ThreadTokenUsageResponse | null | undefined,
): ContextUsage | null {
  if (!usage?.context_usage) {
    return null;
  }
  const { token_count, max_context_tokens, percentage } = usage.context_usage;
  return {
    tokenCount: token_count ?? 0,
    maxContextTokens: max_context_tokens ?? null,
    percentage: percentage ?? null,
  };
}

/**
 * Composition of the last model request, as captured by the backend.
 *
 * Counts are approximate tokens. ``contextWindow`` is the model's declared
 * capacity; when it is null the UI shows each category's share of what is
 * already used instead of its share of the window.
 */
export interface ContextUsageBreakdown {
  totalTokens: number;
  percentage: number | null;
  remainingTokens: number | null;
  systemPromptTokens: number;
  builtinToolsTokens: number;
  mcpToolsTokens: number;
  skillBodyTokens: number;
  memoryTokens: number;
  taskStateTokens: number;
  otherInjectionTokens: number;
  conversationTokens: number;
  toolResultTokens: number;
  modelName: string | null;
  contextWindow: number | null;
  capturedAt: string | null;
}

export function selectContextUsageBreakdown(
  usage: ThreadTokenUsageResponse | null | undefined,
): ContextUsageBreakdown | null {
  const breakdown = usage?.context_usage?.breakdown;
  if (!breakdown) {
    return null;
  }
  return {
    totalTokens: breakdown.total_tokens ?? 0,
    percentage: breakdown.percentage ?? null,
    remainingTokens: breakdown.remaining_tokens ?? null,
    systemPromptTokens: breakdown.system_prompt_tokens ?? 0,
    builtinToolsTokens: breakdown.builtin_tools_tokens ?? 0,
    mcpToolsTokens: breakdown.mcp_tools_tokens ?? 0,
    skillBodyTokens: breakdown.skill_body_tokens ?? 0,
    memoryTokens: breakdown.memory_tokens ?? 0,
    taskStateTokens: breakdown.task_state_tokens ?? 0,
    otherInjectionTokens: breakdown.other_injection_tokens ?? 0,
    conversationTokens: breakdown.conversation_tokens ?? 0,
    toolResultTokens: breakdown.tool_result_tokens ?? 0,
    modelName: breakdown.model_name ?? null,
    contextWindow: breakdown.context_window ?? null,
    capturedAt: breakdown.captured_at ?? null,
  };
}

export type ContextUsageCategoryKey =
  | "systemPrompt"
  | "tools"
  | "skills"
  | "memoryContext"
  | "conversation";

export type ContextUsageSubcategoryKey =
  | "builtinTools"
  | "mcpTools"
  | "memory"
  | "taskState"
  | "otherInjection"
  | "conversationMessages"
  | "toolResults";

export interface ContextUsageSubcategory {
  key: ContextUsageSubcategoryKey;
  tokens: number;
}

export interface ContextUsageCategory {
  key: ContextUsageCategoryKey;
  tokens: number;
  subcategories: ContextUsageSubcategory[];
}

/**
 * Group the flat backend counts into the five top-level segments the popover
 * shows. The five groups are exhaustive: their token sum equals the snapshot
 * total, which is what the bar and the percentages rely on.
 */
export function contextUsageCategories(
  breakdown: ContextUsageBreakdown,
): ContextUsageCategory[] {
  return [
    {
      key: "systemPrompt",
      tokens: breakdown.systemPromptTokens,
      subcategories: [],
    },
    {
      key: "tools",
      tokens: breakdown.builtinToolsTokens + breakdown.mcpToolsTokens,
      subcategories: [
        { key: "builtinTools", tokens: breakdown.builtinToolsTokens },
        { key: "mcpTools", tokens: breakdown.mcpToolsTokens },
      ],
    },
    {
      key: "skills",
      tokens: breakdown.skillBodyTokens,
      subcategories: [],
    },
    {
      key: "memoryContext",
      tokens:
        breakdown.memoryTokens +
        breakdown.taskStateTokens +
        breakdown.otherInjectionTokens,
      subcategories: [
        { key: "memory", tokens: breakdown.memoryTokens },
        { key: "taskState", tokens: breakdown.taskStateTokens },
        { key: "otherInjection", tokens: breakdown.otherInjectionTokens },
      ],
    },
    {
      key: "conversation",
      tokens: breakdown.conversationTokens + breakdown.toolResultTokens,
      subcategories: [
        {
          key: "conversationMessages",
          tokens: breakdown.conversationTokens,
        },
        { key: "toolResults", tokens: breakdown.toolResultTokens },
      ],
    },
  ];
}

/**
 * Denominator for every displayed share.
 *
 * A declared window is the true capacity, so the categories add up to the
 * window-relative total and the leftover is the remaining space. Without one,
 * the only meaningful denominator is what the request already uses.
 */
export function contextUsageDenominator(
  breakdown: ContextUsageBreakdown,
): number {
  return breakdown.contextWindow && breakdown.contextWindow > 0
    ? breakdown.contextWindow
    : breakdown.totalTokens;
}

export function contextUsageShare(
  tokens: number,
  denominator: number,
): number | null {
  if (!Number.isFinite(tokens) || !Number.isFinite(denominator)) {
    return null;
  }
  if (denominator <= 0) {
    return null;
  }
  // Round away binary-float noise (550 / 1000 * 100 is 55.00000000000001),
  // which would otherwise render as "55.0%" instead of "55%".
  return Math.round((tokens / denominator) * 100 * 10_000) / 10_000;
}

/**
 * Recompute the window-relative fields for a model other than the one that
 * produced the snapshot.
 *
 * The snapshot records the window of the model call it describes, but the
 * composer lets the user switch models before the next call. Passing the
 * selected model's window keeps the ring in sync until that call. ``undefined``
 * keeps the recorded window (for example while the model list is loading), and
 * ``null`` means the selected model declares no window.
 */
export function withContextUsageWindow(
  breakdown: ContextUsageBreakdown,
  contextWindow: number | null | undefined,
): ContextUsageBreakdown {
  if (
    contextWindow === undefined ||
    contextWindow === breakdown.contextWindow
  ) {
    return breakdown;
  }
  const window =
    contextWindow != null && contextWindow > 0 ? contextWindow : null;
  return {
    ...breakdown,
    contextWindow: window,
    // Keep the same precision as contextUsageShare so the formatter can still
    // render a real but tiny share as "<0.1%" instead of "0%".
    percentage:
      window != null ? contextUsageShare(breakdown.totalTokens, window) : null,
    remainingTokens:
      window != null ? Math.max(window - breakdown.totalTokens, 0) : null,
  };
}

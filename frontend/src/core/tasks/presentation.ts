import { formatTokenCount, type TokenUsage } from "@/core/messages/usage";
import type { Model } from "@/core/models/types";

/** Resolve the card label when a provider omits the task tool's optional description. */
export function resolveSubtaskDescription(
  description: unknown,
  prompt: unknown,
  fallback: string,
): string {
  if (typeof description === "string" && description.trim()) {
    return description.trim();
  }
  if (typeof prompt === "string" && prompt.trim()) {
    return prompt.trim();
  }
  return fallback;
}

/** Return the user-facing label for a configured subagent model. */
export function resolveSubtaskModelLabel(
  modelName: string | undefined,
  models: Model[],
): string | undefined {
  if (!modelName) {
    return undefined;
  }
  return (
    models.find((model) => model.name === modelName)?.display_name ?? modelName
  );
}

export function formatSubtaskTokenUsage(
  usage: TokenUsage | undefined,
): string | undefined {
  return usage ? formatTokenCount(usage.totalTokens) : undefined;
}

/** Preserve the external source label and absent-usage state. */
export function formatExternalUsage(
  usage: Record<string, unknown> | undefined,
): string | undefined {
  const tokens = usage?.total_tokens ?? usage?.totalTokens;
  if (typeof tokens === "number" && Number.isFinite(tokens) && tokens >= 0)
    return formatTokenCount(tokens);
  return undefined;
}

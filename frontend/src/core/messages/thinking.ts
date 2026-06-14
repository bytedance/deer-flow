const COLLAPSED_THINKING_SUMMARY_MAX_CHARS = 180;

export function summarizeCollapsedThinkingStep(
  reasoning?: string | null,
): string {
  if (!reasoning) {
    return "";
  }

  const summary = reasoning
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[#>*_\-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return summary.length > COLLAPSED_THINKING_SUMMARY_MAX_CHARS
    ? `${summary.slice(0, COLLAPSED_THINKING_SUMMARY_MAX_CHARS).trimEnd()}...`
    : summary;
}

export function getCollapsedThinkingSummary({
  reasoning,
  showCollapsedThinkingStep,
  showLastThinking,
}: {
  reasoning?: string | null;
  showCollapsedThinkingStep: boolean;
  showLastThinking: boolean;
}): string {
  if (!showCollapsedThinkingStep || showLastThinking) {
    return "";
  }

  return summarizeCollapsedThinkingStep(reasoning);
}

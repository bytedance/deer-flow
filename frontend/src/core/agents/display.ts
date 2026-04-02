import type { Agent } from "./types";

export function getAgentDisplayName(
  agent: Pick<Agent, "name" | "display_name"> | null | undefined,
  fallbackName?: string,
): string {
  return agent?.display_name ?? agent?.name ?? fallbackName ?? "";
}

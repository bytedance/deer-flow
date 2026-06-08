import type { Agent } from "./types";

export function getAgentDisplayName(
  agent: Pick<Agent, "display_name" | "name"> | null | undefined,
  fallbackName?: string,
) {
  const trimmedDisplayName = agent?.display_name?.trim();
  if (trimmedDisplayName) {
    return trimmedDisplayName;
  }

  return agent?.name ?? fallbackName ?? "";
}

export function hasAgentDisplayName(
  agent: Pick<Agent, "display_name"> | null | undefined,
) {
  return !!agent?.display_name?.trim();
}

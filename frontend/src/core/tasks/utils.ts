/**
 * Derive a human-friendly display name from a subagent_type string.
 * e.g. "web_researcher" → "Web Researcher", "data_analyst" → "Data Analyst"
 */
export function agentNameFromType(subagentType: string): string {
  if (!subagentType) return "Agent";
  return subagentType
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

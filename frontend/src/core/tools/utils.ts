import type { ToolCall } from "@langchain/core/messages";
import type { AIMessage } from "@langchain/langgraph-sdk";

import type { Translations } from "../i18n";
import { hasToolCalls } from "../messages/utils";

/**
 * Check if a file path is a skill file
 */
export function isSkillPath(path: string): boolean {
  return (
    path.includes("/mnt/skills/") ||
    path.includes("skills/public/") ||
    path.includes("skills/custom/")
  );
}

/**
 * Extract skill name from a skill file path
 * Examples:
 *   /mnt/skills/custom/demand-discovery/SKILL.md → demand-discovery
 *   skills/public/deep-research/SKILL.md → deep-research
 */
export function extractSkillName(path: string): string | null {
  const match = path.match(/skills\/(?:public|custom)\/([^\/]+)/);
  return match ? match[1] : null;
}

/**
 * Get skill display name (convert kebab-case to Title Case)
 */
export function getSkillDisplayName(skillName: string): string {
  return skillName
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function explainLastToolCall(message: AIMessage, t: Translations) {
  if (hasToolCalls(message)) {
    const lastToolCall = message.tool_calls![message.tool_calls!.length - 1]!;
    return explainToolCall(lastToolCall, t);
  }
  return t.common.thinking;
}

export function explainToolCall(toolCall: ToolCall, t: Translations) {
  if (toolCall.name === "web_search" || toolCall.name === "image_search") {
    return t.toolCalls.searchFor(toolCall.args.query);
  } else if (toolCall.name === "web_fetch") {
    return t.toolCalls.viewWebPage;
  } else if (toolCall.name === "present_files") {
    return t.toolCalls.presentFiles;
  } else if (toolCall.name === "write_todos") {
    return t.toolCalls.writeTodos;
  } else if (toolCall.args.description) {
    return toolCall.args.description;
  } else {
    return t.toolCalls.useTool(toolCall.name);
  }
}

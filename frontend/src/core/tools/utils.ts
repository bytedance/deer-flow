import type { ToolCall } from "@langchain/core/messages";
import type { AIMessage } from "@langchain/langgraph-sdk";

import type { Translations } from "../i18n";
import { hasToolCalls } from "../messages/utils";

export function explainLastToolCall(message: AIMessage, t: Translations) {
  if (hasToolCalls(message) && Array.isArray(message.tool_calls)) {
    const lastToolCall = message.tool_calls[message.tool_calls.length - 1]!;
    return explainToolCall(lastToolCall, t);
  }
  return t.common.thinking;
}

function parseToolCallArgs(args: unknown): Record<string, unknown> {
  if (typeof args === "string") {
    try {
      return JSON.parse(args) as Record<string, unknown>;
    } catch {
      return {};
    }
  }
  return (args as Record<string, unknown>) ?? {};
}

export function explainToolCall(toolCall: ToolCall, t: Translations) {
  const args = parseToolCallArgs(toolCall.args);
  if (toolCall.name === "web_search" || toolCall.name === "image_search") {
    return t.toolCalls.searchFor(args.query as string);
  } else if (toolCall.name === "web_fetch") {
    return t.toolCalls.viewWebPage;
  } else if (toolCall.name === "present_files") {
    return t.toolCalls.presentFiles;
  } else if (toolCall.name === "write_todos") {
    return t.toolCalls.writeTodos;
  } else if (args.description) {
    return args.description as string;
  } else {
    return t.toolCalls.useTool(toolCall.name);
  }
}

import type { ToolCall } from "@langchain/core/messages";
import type { AIMessage } from "@langchain/langgraph-sdk";

import type { Translations } from "../i18n";
import { hasToolCalls } from "../messages/utils";

/**
 * Read a tool-call argument for display: the value when it is a non-empty
 * string, otherwise `undefined`, so callers can fall back with `??`.
 *
 * Tool-call args are the model's output, not validated input: a tool's schema
 * can make `description` an object or an array, and a malformed or
 * mid-stream call can carry anything. React throws on an object child, and
 * the chat has no error boundary around tool steps, so one such value would
 * take down the whole page.
 */
export function stringArg(args: unknown, key: string): string | undefined {
  if (typeof args !== "object" || args === null) {
    return undefined;
  }
  const value = (args as Record<string, unknown>)[key];
  return typeof value === "string" && value ? value : undefined;
}

export function explainLastToolCall(message: AIMessage, t: Translations) {
  if (hasToolCalls(message)) {
    const lastToolCall = message.tool_calls![message.tool_calls!.length - 1]!;
    return explainToolCall(lastToolCall, t);
  }
  return t.common.thinking;
}

export function explainToolCall(toolCall: ToolCall, t: Translations) {
  const query = stringArg(toolCall.args, "query");
  if (
    (toolCall.name === "web_search" || toolCall.name === "image_search") &&
    query
  ) {
    return t.toolCalls.searchFor(query);
  } else if (toolCall.name === "web_fetch") {
    return t.toolCalls.viewWebPage;
  } else if (toolCall.name === "present_files") {
    return t.toolCalls.presentFiles;
  } else if (toolCall.name === "write_todos") {
    return t.toolCalls.writeTodos;
  }
  return (
    stringArg(toolCall.args, "description") ??
    t.toolCalls.useTool(toolCall.name)
  );
}

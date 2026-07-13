import type { Message } from "@langchain/langgraph-sdk";

/**
 * Returns a stable per-message identity string used to deduplicate messages
 * across history reloads. Tool messages are keyed by their `tool_call_id`
 * (namespaced as `tool:<tool_call_id>`); all other messages fall back to their
 * `id` (namespaced as `message:<id>`). Returns `undefined` when no usable key
 * is available, so callers can decide whether to keep or drop such messages.
 */
export function messageIdentity(message: Message): string | undefined {
  if (
    "tool_call_id" in message &&
    typeof message.tool_call_id === "string" &&
    message.tool_call_id.length > 0
  ) {
    return `tool:${message.tool_call_id}`;
  }
  if (typeof message.id === "string" && message.id.length > 0) {
    return `message:${message.id}`;
  }
  return undefined;
}

import type { Message } from "@langchain/langgraph-sdk";

/** Presentation only. This metadata never authorizes a model or an action. */
export function modelControlDisplayText(message: Message): string | null {
  if (message.type !== "human") return null;
  if (typeof message.content !== "string" && !Array.isArray(message.content))
    return null;
  const value: unknown = message.additional_kwargs?.model_control;
  if (!value || typeof value !== "object") return null;
  const data = value as Record<string, unknown>;
  if (
    data.version !== 1 ||
    typeof data.original_text !== "string" ||
    typeof data.execution_text !== "string"
  )
    return null;
  const content =
    typeof message.content === "string"
      ? message.content
      : message.content
          .map((part) =>
            typeof part === "string"
              ? part
              : part.type === "text"
                ? part.text
                : "",
          )
          .join("");
  // Edited/replayed content must never display an earlier control statement.
  return content.trim() === data.execution_text.trim()
    ? data.original_text
    : null;
}

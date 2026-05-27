import type { Message } from "@langchain/langgraph-sdk";

export type ErrorCategory =
  | "network_issue"
  | "timeout"
  | "service_unavailable"
  | "data_not_found"
  | "permission_denied"
  | "rate_limited";

export interface ToolErrorInfo {
  category: ErrorCategory;
  suggestedAction: string;
  rawMessage: string;
  toolName: string;
}

const RETRYABLE_CATEGORIES: ReadonlySet<ErrorCategory> = new Set([
  "network_issue",
  "timeout",
  "rate_limited",
]);

export function isRetryableError(category: ErrorCategory): boolean {
  return RETRYABLE_CATEGORIES.has(category);
}

export function findToolCallErrorInfo(
  toolCallId: string,
  messages: Message[],
): ToolErrorInfo | null {
  for (const message of messages) {
    if (message.type !== "tool" || message.tool_call_id !== toolCallId) {
      continue;
    }

    const status = (message as Record<string, unknown>).status;
    if (status !== "error") continue;

    const kwargs = message.additional_kwargs ?? {};
    const category = kwargs.error_category as string | undefined;
    const suggestedAction = kwargs.suggested_action as string | undefined;
    const toolName = message.name ?? "";

    if (!category) {
      const text =
        typeof message.content === "string" ? message.content : String(message.content ?? "");
      return {
        category: "service_unavailable",
        suggestedAction: "",
        rawMessage: text,
        toolName,
      };
    }

    const text =
      typeof message.content === "string" ? message.content : String(message.content ?? "");

    return {
      category: category as ErrorCategory,
      suggestedAction: suggestedAction ?? "",
      rawMessage: text,
      toolName,
    };
  }

  return null;
}

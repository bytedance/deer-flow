import type { Subtask } from "./types";

export type SubtaskStatus = Subtask["status"];

export interface SubtaskResultUpdate {
  status: SubtaskStatus;
  result?: string;
  error?: string;
}

const SUCCESS_PREFIX = "Task Succeeded. Result:";
const FAILURE_PREFIX = "Task failed.";
const TIMEOUT_PREFIX = "Task timed out";

/**
 * Map a `task` tool result string to a {@link SubtaskStatus}.
 *
 * Bytedance/deer-flow issue #3107 BUG-007: parent-visible task tool errors do
 * not always start with one of the three legacy prefixes (e.g. when
 * `ToolErrorHandlingMiddleware` wraps an exception as
 * `Error: Tool 'task' failed ...`). Treat any leading `Error:` token as a
 * terminal failure so subtask cards stop being stuck on "in_progress".
 */
export function parseSubtaskResult(text: string): SubtaskResultUpdate {
  const trimmed = text.trim();

  if (trimmed.startsWith(SUCCESS_PREFIX)) {
    return {
      status: "completed",
      result: trimmed.slice(SUCCESS_PREFIX.length).trim(),
    };
  }

  if (trimmed.startsWith(FAILURE_PREFIX)) {
    return {
      status: "failed",
      error: trimmed.slice(FAILURE_PREFIX.length).trim(),
    };
  }

  if (trimmed.startsWith(TIMEOUT_PREFIX)) {
    return { status: "failed", error: trimmed };
  }

  // ToolErrorHandlingMiddleware-style wrapper, or any other terminal error
  // signal the backend forwards to the lead agent.
  if (/^Error\b/i.test(trimmed)) {
    return { status: "failed", error: trimmed };
  }

  return { status: "in_progress" };
}

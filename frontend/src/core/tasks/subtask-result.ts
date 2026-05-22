import type { Subtask } from "./types";

export type SubtaskStatus = Subtask["status"];

export interface SubtaskResultUpdate {
  status: SubtaskStatus;
  result?: string;
  error?: string;
}

/**
 * Prefix strings the backend `task` tool writes into its result `content`.
 *
 * These values are not user-facing copy — they are part of the
 * backend↔frontend contract defined in
 * `backend/packages/harness/deerflow/tools/builtins/task_tool.py` (returned
 * from the tool body) and in
 * `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py`
 * (wrapper for tool exceptions). Any change here must be paired with the
 * matching backend change. Exported so a future structured-status migration
 * can reference the same values from one place.
 *
 * `task_tool.py` also emits three `Error:` strings for pre-execution failures
 * — unknown subagent type, host-bash disabled, and "task disappeared from
 * background tasks". They are handled by {@link ERROR_WRAPPER_PATTERN}
 * rather than dedicated prefixes because the wrapper already produces
 * exactly the right `terminal failed` shape.
 */
export const SUCCESS_PREFIX = "Task Succeeded. Result:";
export const FAILURE_PREFIX = "Task failed.";
export const TIMEOUT_PREFIX = "Task timed out";
export const CANCELLED_PREFIX = "Task cancelled by user.";
export const POLLING_TIMEOUT_PREFIX = "Task polling timed out";
export const ERROR_WRAPPER_PATTERN = /^Error\b/i;

/**
 * Map a `task` tool result string to a {@link SubtaskStatus}.
 *
 * Bytedance/deer-flow issue #3107 BUG-007: parent-visible task tool errors do
 * not always start with one of the three legacy prefixes (e.g. when
 * `ToolErrorHandlingMiddleware` wraps an exception as
 * `Error: Tool 'task' failed ...`). Treat any leading `Error:` token as a
 * terminal failure so subtask cards stop being stuck on "in_progress".
 *
 * Returning `in_progress` is the **deliberate** fallback for content that
 * matches none of the known prefixes. LangChain only ever emits a
 * `ToolMessage` once the tool itself has returned (success or wrapped
 * exception), so an unknown shape means "the contract changed underneath us"
 * — surfacing it as still-running prompts the operator to investigate, where
 * eagerly marking it terminal-failed would mask the drift.
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

  if (trimmed.startsWith(CANCELLED_PREFIX)) {
    return { status: "failed", error: trimmed };
  }

  if (trimmed.startsWith(POLLING_TIMEOUT_PREFIX)) {
    return { status: "failed", error: trimmed };
  }

  // ToolErrorHandlingMiddleware-style wrapper, or any other terminal error
  // signal the backend forwards to the lead agent.
  if (ERROR_WRAPPER_PATTERN.test(trimmed)) {
    return { status: "failed", error: trimmed };
  }

  return { status: "in_progress" };
}

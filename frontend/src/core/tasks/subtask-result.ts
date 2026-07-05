import type { Message } from "@langchain/langgraph-sdk";

import type { Subtask } from "./types";

export type SubtaskStatus = Subtask["status"];

export interface SubtaskResultUpdate {
  status: SubtaskStatus;
  result?: string;
  error?: string;
}

/**
 * Structured-status keys the backend stamps onto
 * ``ToolMessage.additional_kwargs`` for every ``task`` tool result.
 *
 * The values mirror the Python contract in
 * ``backend/packages/harness/deerflow/subagents/status_contract.py``
 * (``SUBAGENT_STATUS_KEY`` / ``SUBAGENT_ERROR_KEY`` /
 * ``SUBAGENT_RESULT_BRIEF_KEY`` / ``SUBAGENT_RESULT_SHA256_KEY``). The
 * result metadata fields are optional and bounded: ``subagent_result_brief``
 * carries a trimmed summary for completed tasks and
 * ``subagent_result_sha256`` carries the full-result digest. The
 * cross-language fixture at ``contracts/subagent_status_contract.json``
 * pins both sides to the same values.
 */
export const SUBAGENT_STATUS_KEY = "subagent_status";
export const SUBAGENT_ERROR_KEY = "subagent_error";
export const SUBAGENT_RESULT_BRIEF_KEY = "subagent_result_brief";
export const SUBAGENT_RESULT_SHA256_KEY = "subagent_result_sha256";
const STRUCTURED_SUBAGENT_KEYS = [
  SUBAGENT_STATUS_KEY,
  SUBAGENT_ERROR_KEY,
  SUBAGENT_RESULT_BRIEF_KEY,
  SUBAGENT_RESULT_SHA256_KEY,
];

const SUCCESS_PREFIX = "Task Succeeded. Result:";
const FAILURE_PREFIX = "Task failed.";
const TIMEOUT_PREFIX = "Task timed out";
const CANCELLED_PREFIX = "Task cancelled by user.";
const POLLING_TIMEOUT_PREFIX = "Task polling timed out";
const ERROR_WRAPPER_PATTERN = /^Error\b/i;

/**
 * Map from the backend ``subagent_status`` value to the frontend
 * {@link SubtaskStatus} enum. The frontend collapses ``cancelled`` /
 * ``timed_out`` / ``polling_timed_out`` into ``failed`` because the
 * subtask card only renders three pill states. The richer backend
 * vocabulary still survives on ``error`` for tooling that wants the
 * detail.
 */
const STRUCTURED_STATUS_TO_SUBTASK: Record<string, SubtaskStatus> = {
  completed: "completed",
  failed: "failed",
  cancelled: "failed",
  timed_out: "failed",
  polling_timed_out: "failed",
  max_turns_reached: "failed",
};

/**
 * Map a `task` tool result to a {@link SubtaskStatus}.
 *
 * The backend writes task lifecycle facts into
 * ``ToolMessage.additional_kwargs``. The textual ``content`` remains
 * model-visible display content only; it is not parsed as a protocol.
 *
 * Returning `in_progress` is the **deliberate** default for content that
 * carries no structured stamp.
 * LangChain only ever emits a `ToolMessage` once the tool itself has
 * returned (success or wrapped exception), so an unknown shape means
 * "the contract changed underneath us" — surfacing it as still-running
 * prompts the operator to investigate, where eagerly marking it
 * terminal-failed would mask the drift.
 */
export function parseSubtaskResult(
  text: string,
  additionalKwargs?: Record<string, unknown> | null,
): SubtaskResultUpdate {
  const structured = readStructuredStatus(additionalKwargs);
  if (!structured) {
    if (!hasStructuredSubagentMetadata(additionalKwargs)) {
      return parseLegacyTaskResult(text.trim());
    }
    return { status: "in_progress" };
  }

  const update: SubtaskResultUpdate = { status: structured.status };
  if (structured.error) {
    update.error = structured.error;
  }
  const structuredResult = readStructuredResultBrief(additionalKwargs);
  if (structured.status === "completed" && structuredResult) {
    update.result = structuredResult;
  }
  return update;
}

function parseLegacyTaskResult(trimmed: string): SubtaskResultUpdate {
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

  if (ERROR_WRAPPER_PATTERN.test(trimmed)) {
    return { status: "failed", error: trimmed };
  }

  return { status: "in_progress" };
}

export function hasSubtaskToolResult(
  toolCallId: string | undefined,
  messages: Message[],
) {
  if (!toolCallId) {
    return false;
  }
  return messages.some(
    (message) => message.type === "tool" && message.tool_call_id === toolCallId,
  );
}

export function derivePendingSubtaskStatus(
  toolCallId: string | undefined,
  messages: Message[],
  isCurrentTurnLoading: boolean,
): SubtaskStatus {
  if (isCurrentTurnLoading || hasSubtaskToolResult(toolCallId, messages)) {
    return "in_progress";
  }
  return "failed";
}

interface StructuredStatus {
  status: SubtaskStatus;
  error?: string;
}

function readStructuredStatus(
  additionalKwargs: Record<string, unknown> | null | undefined,
): StructuredStatus | null {
  if (!additionalKwargs) return null;
  const rawStatus = additionalKwargs[SUBAGENT_STATUS_KEY];
  if (typeof rawStatus !== "string") return null;
  const mapped = STRUCTURED_STATUS_TO_SUBTASK[rawStatus];
  if (mapped === undefined) {
    return null;
  }
  const rawError = additionalKwargs[SUBAGENT_ERROR_KEY];
  const result: StructuredStatus = { status: mapped };
  if (typeof rawError === "string" && rawError.trim()) {
    result.error = rawError;
  }
  return result;
}

function hasStructuredSubagentMetadata(
  additionalKwargs: Record<string, unknown> | null | undefined,
): boolean {
  if (!additionalKwargs) return false;
  return STRUCTURED_SUBAGENT_KEYS.some((key) =>
    Object.prototype.hasOwnProperty.call(additionalKwargs, key),
  );
}

function readStructuredResultBrief(
  additionalKwargs: Record<string, unknown> | null | undefined,
): string | undefined {
  const value = additionalKwargs?.[SUBAGENT_RESULT_BRIEF_KEY];
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

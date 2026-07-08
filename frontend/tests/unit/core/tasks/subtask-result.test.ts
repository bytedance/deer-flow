import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import {
  SUBAGENT_ERROR_KEY,
  SUBAGENT_RESULT_BRIEF_KEY,
  SUBAGENT_STATUS_KEY,
  SUBAGENT_STOP_REASON_KEY,
  derivePendingSubtaskStatus,
  hasSubtaskToolResult,
  parseSubtaskResult,
} from "@/core/tasks/subtask-result";

interface ContractFile {
  valid_status_values: string[];
  valid_stop_reason_values: string[];
}

const CONTRACT_PATH = resolve(
  __dirname,
  "../../../../../contracts/subagent_status_contract.json",
);
const CONTRACT: ContractFile = JSON.parse(
  readFileSync(CONTRACT_PATH, "utf-8"),
) as ContractFile;

describe("parseSubtaskResult", () => {
  it("uses legacy task result text when structured metadata is absent", () => {
    expect(
      parseSubtaskResult(
        "Task Succeeded. Result: investigated and produced a 3-page report",
      ),
    ).toEqual({
      status: "completed",
      result: "investigated and produced a 3-page report",
    });

    expect(
      parseSubtaskResult(
        "Task failed. Error: underlying tool raised RuntimeError",
      ),
    ).toEqual({
      status: "failed",
      error: "Error: underlying tool raised RuntimeError",
    });

    expect(parseSubtaskResult("Task cancelled by user.")).toEqual({
      status: "failed",
      error: "Task cancelled by user.",
    });

    expect(parseSubtaskResult("Task timed out. Error: 900 seconds")).toEqual({
      status: "failed",
      error: "Task timed out. Error: 900 seconds",
    });

    expect(
      parseSubtaskResult(
        "Task polling timed out after 15 minutes. Status: RUNNING",
      ),
    ).toEqual({
      status: "failed",
      error: "Task polling timed out after 15 minutes. Status: RUNNING",
    });

    expect(
      parseSubtaskResult("Error: Tool 'task' failed with TypeError: boom"),
    ).toEqual({
      status: "failed",
      error: "Error: Tool 'task' failed with TypeError: boom",
    });
  });

  it("keeps unknown content-only task results in progress", () => {
    const parsed = parseSubtaskResult("partial streaming chunk");

    expect(parsed.status).toBe("in_progress");
    expect(parsed.error).toBeUndefined();
    expect(parsed.result).toBeUndefined();
  });
});

describe("hasSubtaskToolResult", () => {
  it("matches a task tool call to its ToolMessage", () => {
    const messages = [
      { type: "ai" },
      { type: "tool", tool_call_id: "call_task_1" },
    ] as Message[];

    expect(hasSubtaskToolResult("call_task_1", messages)).toBe(true);
  });

  it("returns false when a task tool call has no ToolMessage", () => {
    const messages = [
      { type: "ai" },
      { type: "tool", tool_call_id: "call_other" },
    ] as Message[];

    expect(hasSubtaskToolResult("call_task_1", messages)).toBe(false);
  });
});

describe("derivePendingSubtaskStatus", () => {
  it("keeps a task in progress while its own assistant turn is loading", () => {
    const messages = [{ type: "ai" }] as Message[];

    expect(derivePendingSubtaskStatus("call_task_1", messages, true)).toBe(
      "in_progress",
    );
  });

  it("does not revive an earlier unfinished task during a later turn", () => {
    const messages = [{ type: "ai" }] as Message[];

    expect(derivePendingSubtaskStatus("call_task_1", messages, false)).toBe(
      "failed",
    );
  });

  it("leaves result parsing to the ToolMessage path when a result exists", () => {
    const messages = [
      { type: "ai" },
      { type: "tool", tool_call_id: "call_task_1" },
    ] as Message[];

    expect(derivePendingSubtaskStatus("call_task_1", messages, false)).toBe(
      "in_progress",
    );
  });
});

/**
 * Structured-status path (bytedance/deer-flow#3146).
 *
 * The backend stamps `ToolMessage.additional_kwargs.subagent_status`
 * directly. The frontend should prefer that over reverse-engineering it
 * from the content string.
 */
describe("parseSubtaskResult — structured additional_kwargs (preferred path)", () => {
  it("uses additional_kwargs.subagent_status when present", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: foo", {
      [SUBAGENT_STATUS_KEY]: "completed",
    });
    expect(parsed.status).toBe("completed");
  });

  it("collapses cancelled / timed_out / polling_timed_out to failed for the card UI", () => {
    for (const backendStatus of [
      "cancelled",
      "timed_out",
      "polling_timed_out",
    ]) {
      const parsed = parseSubtaskResult("anything at all", {
        [SUBAGENT_STATUS_KEY]: backendStatus,
      });
      expect(parsed.status).toBe("failed");
    }
  });

  it("renders legacy max_turns_reached (checkpointed under #3949) as a terminal failed pill, not spinning in_progress", () => {
    // Phase 1 wrote `subagent_status: "max_turns_reached"` into ToolMessage
    // additional_kwargs, which is checkpointed in thread history. Phase 2 (#3980)
    // stopped producing it, but old turns still carry it. Without the deprecated
    // alias, readStructuredStatus returns null while hasStructuredSubagentMetadata
    // stays true (sibling keys present) -> parseSubtaskResult returns
    // { status: "in_progress" } and the card spins forever. The alias keeps it
    // terminal, matching how Phase 1 itself rendered the value.
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "max_turns_reached",
      [SUBAGENT_ERROR_KEY]: "Reached max_turns=150",
      [SUBAGENT_RESULT_BRIEF_KEY]: "investigated 3 of 5 sources",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBe("Reached max_turns=150");
    // result only attaches for the completed pill; legacy data renders as failed.
    expect(parsed.result).toBeUndefined();
  });

  it("surfaces stop_reason on a capped run while keeping a normal pill status", () => {
    // bytedance/deer-flow#3875 Phase 2: a token-capped run produced a final
    // answer, so it is `completed` with the cap on the additive
    // `subagent_stop_reason` field. The card stays green; stopReason carries
    // the cap detail for a future badge, and the recovered partial result
    // lives on subagent_result_brief.
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "completed",
      [SUBAGENT_RESULT_BRIEF_KEY]: "investigated 3 of 5 sources",
      [SUBAGENT_STOP_REASON_KEY]: "token_capped",
    });
    expect(parsed.status).toBe("completed");
    expect(parsed.result).toBe("investigated 3 of 5 sources");
    expect(parsed.stopReason).toBe("token_capped");
  });

  it("surfaces stop_reason on a turn-capped run that produced no usable result", () => {
    // No usable partial -> the backend stamps `failed` + turn_capped. The card
    // goes red; stopReason still carries the cap so a future badge can say so.
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "failed",
      [SUBAGENT_ERROR_KEY]: "Reached max_turns=150",
      [SUBAGENT_STOP_REASON_KEY]: "turn_capped",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBe("Reached max_turns=150");
    expect(parsed.stopReason).toBe("turn_capped");
  });

  it("ignores an unknown subagent_stop_reason value", () => {
    // An unrecognized stop_reason is dropped so a stale frontend never renders
    // a bogus cap badge.
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "completed",
      [SUBAGENT_STOP_REASON_KEY]: "future_cap_kind",
    });
    expect(parsed.status).toBe("completed");
    expect(parsed.stopReason).toBeUndefined();
  });

  it("uses subagent_error when supplied", () => {
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "failed",
      [SUBAGENT_ERROR_KEY]: "boom from backend",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBe("boom from backend");
  });

  it("ignores empty / non-string subagent_error", () => {
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "failed",
      [SUBAGENT_ERROR_KEY]: "",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBeUndefined();
  });

  it("ignores terminal-looking content when partial structured metadata is present", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: foo", {
      [SUBAGENT_RESULT_BRIEF_KEY]: "structured result without status",
    });
    expect(parsed.status).toBe("in_progress");
    expect(parsed.result).toBeUndefined();
  });

  it("ignores terminal-looking content when the structured status is unknown", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: foo", {
      [SUBAGENT_STATUS_KEY]: "renamed_in_v3",
    });
    expect(parsed.status).toBe("in_progress");
  });

  it("structured status overrides misleading content", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: this is a lie", {
      [SUBAGENT_STATUS_KEY]: "failed",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.result).toBeUndefined();
    expect(parsed.error).toBeUndefined();
  });

  it("does not back-fill result from content when structured result metadata is missing", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: text-only", {
      [SUBAGENT_STATUS_KEY]: "completed",
    });
    expect(parsed.status).toBe("completed");
    expect(parsed.result).toBeUndefined();
  });

  it("uses bounded structured result metadata when present for completed task", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: text body", {
      [SUBAGENT_STATUS_KEY]: "completed",
      subagent_result_brief: "structured",
      subagent_result_sha256: "a".repeat(64),
    });
    expect(parsed.status).toBe("completed");
    expect(parsed.result).toBe("structured");
  });

  it("does not back-fill error from content when structured error metadata is missing", () => {
    const parsed = parseSubtaskResult(
      "Error: Tool 'task' failed with TypeError: boom",
      {
        [SUBAGENT_STATUS_KEY]: "failed",
      },
    );
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBeUndefined();
  });

  it("leaves `error` undefined when structured says failed with no error and unrecognised text", () => {
    // Don't dump arbitrary content into the error field — better to render
    // an empty `failed` pill than to surface noise.
    const parsed = parseSubtaskResult("partial streaming chunk", {
      [SUBAGENT_STATUS_KEY]: "failed",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBeUndefined();
  });
});

/**
 * Cross-language contract test for the structured subagent status field.
 * The backend and frontend share the enum values, but task result text is
 * no longer part of the wire contract.
 */
describe("parseSubtaskResult — shared contract fixture", () => {
  const expectedCardStatus = (backendStatus: string): string => {
    if (backendStatus === "completed") return "completed";
    return "failed";
  };

  for (const status of CONTRACT.valid_status_values) {
    it(`maps structured status: ${status}`, () => {
      const parsed = parseSubtaskResult("ignored content", {
        [SUBAGENT_STATUS_KEY]: status,
      });
      expect(parsed.status).toBe(expectedCardStatus(status));
    });
  }

  for (const stopReason of CONTRACT.valid_stop_reason_values) {
    it(`carries stop_reason through unchanged: ${stopReason}`, () => {
      const parsed = parseSubtaskResult("ignored content", {
        [SUBAGENT_STATUS_KEY]: "completed",
        [SUBAGENT_RESULT_BRIEF_KEY]: "partial work",
        [SUBAGENT_STOP_REASON_KEY]: stopReason,
      });
      expect(parsed.stopReason).toBe(stopReason);
    });
  }
});

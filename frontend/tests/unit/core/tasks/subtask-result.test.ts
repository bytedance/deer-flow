import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  SUBAGENT_ERROR_KEY,
  SUBAGENT_STATUS_KEY,
  parseSubtaskResult,
} from "@/core/tasks/subtask-result";

interface ContractCase {
  name: string;
  content: string;
  expected_status: string | null;
  expected_error_contains: string | null;
}

interface ContractFile {
  valid_status_values: string[];
  cases: ContractCase[];
}

// The frontend package is ESM (`"type": "module"`), so `__dirname` is not
// defined. Resolve the cross-language fixture relative to this module URL.
const CONTRACT_PATH = fileURLToPath(
  new URL(
    "../../../../../contracts/subagent_status_contract.json",
    import.meta.url,
  ),
);
const CONTRACT: ContractFile = JSON.parse(
  readFileSync(CONTRACT_PATH, "utf-8"),
) as ContractFile;

describe("parseSubtaskResult", () => {
  it("recognises the standard success prefix", () => {
    const parsed = parseSubtaskResult(
      "Task Succeeded. Result: investigated and produced a 3-page report",
    );
    expect(parsed.status).toBe("completed");
    expect(parsed.result).toBe("investigated and produced a 3-page report");
  });

  it("recognises the standard failure prefix", () => {
    const parsed = parseSubtaskResult(
      "Task failed. underlying tool raised RuntimeError",
    );
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBe("underlying tool raised RuntimeError");
  });

  it("recognises the standard timeout prefix", () => {
    const parsed = parseSubtaskResult("Task timed out after 900s");
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBe("Task timed out after 900s");
  });

  it("recognises the cancelled-by-user prefix", () => {
    // bytedance/deer-flow#3131 review: this is one of the five terminal
    // strings task_tool.py actually emits — the previous cut treated it as
    // unrecognised content and pushed the card back to in_progress.
    const parsed = parseSubtaskResult("Task cancelled by user.");
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBe("Task cancelled by user.");
  });

  it("recognises the polling-timed-out prefix", () => {
    // Emitted by task_tool when the background polling loop runs out of
    // budget waiting for the subagent to reach a terminal state.
    const parsed = parseSubtaskResult(
      "Task polling timed out after 15 minutes. This may indicate the background task is stuck. Status: RUNNING",
    );
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toContain("polling timed out");
  });

  it("recognises polling-timed-out with different durations", () => {
    // `task_tool` emits `Task polling timed out after {N} minutes` where N
    // varies with the configured subagent timeout. Guard against the regex
    // accidentally being pinned to a specific number.
    for (const n of [1, 5, 60]) {
      const parsed = parseSubtaskResult(
        `Task polling timed out after ${n} minutes. Status: RUNNING`,
      );
      expect(parsed.status).toBe("failed");
    }
  });

  it("trims whitespace around cancelled and polling-timed-out prefixes", () => {
    // Streaming chunks sometimes arrive with leading/trailing newlines.
    expect(parseSubtaskResult("  Task cancelled by user.  \n").status).toBe(
      "failed",
    );
    expect(
      parseSubtaskResult("\n\nTask polling timed out after 3 minutes").status,
    ).toBe("failed");
  });

  it("recognises task_tool pre-execution Error: returns via the wrapper", () => {
    // `task_tool.py` returns three `Error:` strings for unknown subagent
    // type, host-bash disabled, and "task disappeared". They share the
    // ERROR_WRAPPER_PATTERN, not a dedicated prefix, so this guards
    // against a refactor splitting them off.
    for (const text of [
      "Error: Unknown subagent type 'foo'. Available: bash, general-purpose",
      "Error: Host bash subagent is disabled by configuration",
      "Error: Task 1234 disappeared from background tasks",
    ]) {
      expect(parseSubtaskResult(text).status).toBe("failed");
    }
  });

  it("treats middleware-wrapped tool errors as terminal failures", () => {
    // bytedance/deer-flow issue #3107 BUG-007: the parent-visible ToolMessage
    // produced by ToolErrorHandlingMiddleware never matches the three legacy
    // prefixes, so subtask cards stay stuck on "in_progress".
    const parsed = parseSubtaskResult(
      "Error: Tool 'task' failed with TypeError: 'AsyncCallbackManager' object is not iterable. Continue with available context, or choose an alternative tool.",
    );
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toContain("AsyncCallbackManager");
  });

  it("treats any other Error: prefix as a terminal failure", () => {
    const parsed = parseSubtaskResult("Error: subagent worker pool exhausted");
    expect(parsed.status).toBe("failed");
  });

  it("keeps unrecognised non-error output as in_progress", () => {
    // Streaming partial chunks should not flip the card to terminal early.
    const parsed = parseSubtaskResult("Investigating ...");
    expect(parsed.status).toBe("in_progress");
    expect(parsed.error).toBeUndefined();
    expect(parsed.result).toBeUndefined();
  });

  it("trims surrounding whitespace before matching prefixes", () => {
    const parsed = parseSubtaskResult("   Task Succeeded. Result: ok   ");
    expect(parsed.status).toBe("completed");
    expect(parsed.result).toBe("ok");
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

  it("falls back to prefix parsing when the structured status is missing", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: foo", {
      // No subagent_status here — backend versions that pre-date the
      // middleware stamping commit still need to render.
      other_field: "irrelevant",
    });
    expect(parsed.status).toBe("completed");
    expect(parsed.result).toBe("foo");
  });

  it("falls back to prefix parsing when the structured status is an unknown future value", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: foo", {
      [SUBAGENT_STATUS_KEY]: "renamed_in_v3",
    });
    // Falls back to prefix and still finds the success path.
    expect(parsed.status).toBe("completed");
  });

  it("structured status overrides legacy text — opposite content", () => {
    // Defence: if backend sends `failed` structured but the content
    // accidentally starts with "Task Succeeded.", we must trust the
    // structured field. The structured field is the source of truth.
    const parsed = parseSubtaskResult("Task Succeeded. Result: this is a lie", {
      [SUBAGENT_STATUS_KEY]: "failed",
    });
    expect(parsed.status).toBe("failed");
    // The misleading success body must be dropped — `result` is reserved
    // for the completed pill, and the suspicious text isn't replayed as
    // an error either.
    expect(parsed.result).toBeUndefined();
    expect(parsed.error).toBeUndefined();
  });

  it("back-fills `result` from the success-prefixed content when structured says completed", () => {
    // The backend currently stamps `subagent_status: completed` but the
    // success body still lives in `content`. Without back-fill the card
    // would render an empty completed pill (regression flagged in PR #3154
    // Copilot review).
    const parsed = parseSubtaskResult(
      "Task Succeeded. Result: investigated and produced a 3-page report",
      { [SUBAGENT_STATUS_KEY]: "completed" },
    );
    expect(parsed.status).toBe("completed");
    expect(parsed.result).toBe("investigated and produced a 3-page report");
  });

  it("back-fills `error` from a wrapped-error body when structured says failed and no subagent_error", () => {
    // Same regression on the failure side: the wrapper text is the only
    // place the diagnostic message exists when the backend stamps the
    // enum but not `subagent_error`.
    const parsed = parseSubtaskResult(
      "Error: Tool 'task' failed with TypeError: boom",
      { [SUBAGENT_STATUS_KEY]: "failed" },
    );
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toContain("TypeError: boom");
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
 * Cross-language contract test (bytedance/deer-flow#3146).
 *
 * Loads the shared fixture at ``contracts/subagent_status_contract.json``
 * and runs every case through the legacy prefix parser. The matching
 * backend test (`backend/tests/test_subagent_status_contract.py`) runs
 * the same cases through ``extract_subagent_status``. Any drift between
 * the two implementations surfaces here.
 *
 * Status-collapse expectations:
 *   - `completed`  → `completed`
 *   - `failed`     → `failed`
 *   - `cancelled` / `timed_out` / `polling_timed_out` → `failed`
 *     (the frontend card has three pill states, not five)
 *   - `null`       → `in_progress`
 */
describe("parseSubtaskResult — shared contract fixture", () => {
  const expectedCardStatus = (backendStatus: string | null): string => {
    if (backendStatus === null) return "in_progress";
    if (backendStatus === "completed") return "completed";
    return "failed";
  };

  for (const c of CONTRACT.cases) {
    it(`legacy prefix parser matches contract: ${c.name}`, () => {
      const parsed = parseSubtaskResult(c.content);
      expect(parsed.status).toBe(expectedCardStatus(c.expected_status));
    });
  }
});

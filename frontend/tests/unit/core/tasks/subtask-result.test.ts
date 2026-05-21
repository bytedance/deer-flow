import { describe, expect, it } from "vitest";

import { parseSubtaskResult } from "@/core/tasks/subtask-result";

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

import { describe, expect, it } from "@rstest/core";

import {
  localTimeToIso,
  parseScheduleToolResult,
  snapshotToTask,
} from "@/core/scheduled-tasks/tool-result";

const view = {
  id: "task-2b559ac2af344c3f9e55b90391f7fb1a",
  title: "Release checklist status watcher",
  status: "enabled",
  schedule_type: "cron",
  schedule_spec: { cron: "0 9 * * 1-5" },
  timezone: "Asia/Shanghai",
  timezone_source: "browser_default",
  next_run_local: "2026-10-07 09:00 (Asia/Shanghai)",
  active_run_status: null,
  prompt: "Read the checklist and list unchecked items.",
  stop_condition: "every item on the checklist is checked",
  goal_objective: null,
  max_runs: 60,
  end_at_local: "2026-12-31 18:00 (Asia/Shanghai)",
  automatic_runs_used: 2,
  context_mode: "fresh_thread_per_run",
  standing_notes: [],
};

describe("parseScheduleToolResult", () => {
  it.each(["create", "update", "pause", "resume"])(
    "parses a %s result",
    (action) => {
      const result = parseScheduleToolResult(
        JSON.stringify({ action, display: "card", task: view }),
      );
      expect(result?.action).toBe(action);
      expect(result?.display).toBe("card");
      expect(result?.task.id).toBe(view.id);
    },
  );

  it("keeps the trial outcome", () => {
    const result = parseScheduleToolResult(
      JSON.stringify({
        action: "trial",
        display: "card",
        task: view,
        trial: { outcome: "queued", existing: true, thread_id: "t-1" },
      }),
    );
    expect(result?.trial).toEqual({
      outcome: "queued",
      existing: true,
      thread_id: "t-1",
    });
  });

  it("parses a delete result that carries only id and title", () => {
    const result = parseScheduleToolResult(
      JSON.stringify({
        action: "delete",
        display: "card",
        deleted: true,
        task: { id: view.id, title: view.title },
      }),
    );
    expect(result?.action).toBe("delete");
  });

  it("reads text content blocks", () => {
    const result = parseScheduleToolResult([
      {
        type: "text",
        text: JSON.stringify({ action: "create", display: "text", task: view }),
      },
    ]);
    expect(result?.display).toBe("text");
  });

  it.each([
    ["a list", { action: "list", display: "card", tasks: [view] }],
    ["a note", { action: "note", display: "card", task: view }],
    [
      "a coded error",
      {
        error: "Ask the user which timezone to use.",
        code: "timezone_required",
        status_code: 422,
      },
    ],
    ["a missing task id", { action: "create", display: "card", task: {} }],
    ["a non-object task", { action: "create", display: "card", task: "x" }],
    ["a self-stop", { action: "stop", stop_requested: true }],
  ])("rejects %s", (_name, payload) => {
    expect(parseScheduleToolResult(JSON.stringify(payload))).toBeNull();
  });

  it.each([
    "Scheduled task created: task-1",
    "{'action': 'create'}",
    "",
    "null",
    "[]",
  ])("rejects unparsable content %j", (content) => {
    expect(parseScheduleToolResult(content)).toBeNull();
  });
});

describe("snapshotToTask", () => {
  it("turns the model-facing local times back into instants", () => {
    expect(localTimeToIso("2026-10-07 09:00 (Asia/Shanghai)")).toBe(
      "2026-10-07T01:00:00+00:00",
    );
    expect(localTimeToIso("2026-10-07T09:00:00")).toBeNull();
    expect(localTimeToIso(null)).toBeNull();
  });

  it("maps the tool view to a task the card can render", () => {
    const task = snapshotToTask(
      parseScheduleToolResult(
        JSON.stringify({ action: "create", display: "card", task: view }),
      )!.task,
    );
    expect(task).toMatchObject({
      id: view.id,
      title: view.title,
      status: "enabled",
      schedule_type: "cron",
      timezone: "Asia/Shanghai",
      next_run_at: "2026-10-07T01:00:00+00:00",
      end_at: "2026-12-31T10:00:00+00:00",
      stop_condition: view.stop_condition,
      max_runs: 60,
      automatic_runs_used: 2,
      last_error: null,
    });
  });
});

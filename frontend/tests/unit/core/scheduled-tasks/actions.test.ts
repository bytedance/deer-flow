import { describe, expect, it } from "@rstest/core";

import { availableActions } from "@/core/scheduled-tasks/actions";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

type ActionInput = Pick<
  ScheduledTask,
  "status" | "schedule_type" | "active_run_status"
>;

const task = (overrides: Partial<ActionInput>): ActionInput => ({
  status: "enabled",
  schedule_type: "cron",
  active_run_status: null,
  ...overrides,
});

const open = { visible: true, disabled: false };
const hidden = { visible: false, disabled: false };
const blocked = (reason: string, visible = true) => ({
  visible,
  disabled: true,
  reason,
});

describe("availableActions", () => {
  it("an active task can be paused, not resumed", () => {
    expect(availableActions(task({}), { createBlocked: false })).toEqual({
      pause: open,
      resume: hidden,
      runNow: open,
      edit: open,
      duplicate: open,
      delete: open,
    });
  });

  it("a paused task can be resumed, not paused", () => {
    const actions = availableActions(task({ status: "paused" }), {
      createBlocked: false,
    });
    expect(actions.pause).toEqual(hidden);
    expect(actions.resume).toEqual(open);
    expect(actions.runNow).toEqual(open);
  });

  it("a recurring task mid-run (status still enabled) blocks every change", () => {
    const actions = availableActions(
      task({ status: "enabled", active_run_status: "running" }),
      { createBlocked: false },
    );
    expect(actions.pause).toEqual(blocked("running"));
    expect(actions.edit).toEqual(blocked("running"));
    expect(actions.delete).toEqual(blocked("running"));
    expect(actions.runNow).toEqual(blocked("running"));
    expect(actions.resume).toEqual(blocked("running", false));
    expect(actions.duplicate).toEqual(open);
  });

  it("a starting run blocks changes like a running one", () => {
    const actions = availableActions(task({ active_run_status: "launching" }), {
      createBlocked: false,
    });
    expect(actions.pause).toEqual(blocked("running"));
    expect(actions.runNow).toEqual(blocked("running"));
  });

  it("a one-time task in status running blocks changes", () => {
    const actions = availableActions(
      task({ status: "running", schedule_type: "once" }),
      { createBlocked: false },
    );
    expect(actions.pause).toEqual(blocked("running"));
    expect(actions.edit).toEqual(blocked("running"));
  });

  it("a queued run can be cancelled by Pause, and Run once now is already waiting", () => {
    const actions = availableActions(task({ active_run_status: "queued" }), {
      createBlocked: false,
    });
    expect(actions.pause).toEqual(open);
    expect(actions.edit).toEqual(blocked("queued"));
    expect(actions.delete).toEqual(blocked("queued"));
    expect(actions.runNow).toEqual(blocked("alreadyQueued"));
  });

  it.each(["paused", "completed"] as const)(
    "a trial queued on a %s task never points at Pause, which is not offered",
    (status) => {
      const actions = availableActions(
        task({ status, active_run_status: "queued" }),
        { createBlocked: false },
      );
      expect(actions.pause.visible).toBe(false);
      expect(actions.resume).toEqual(blocked("queuedNoPause"));
      expect(actions.edit).toEqual(blocked("queuedNoPause"));
      expect(actions.delete).toEqual(blocked("queuedNoPause"));
      expect(actions.runNow).toEqual(blocked("alreadyQueued"));
    },
  );

  it.each(["completed", "failed", "cancelled"] as const)(
    "a finished recurring task (%s) offers Resume, never Pause",
    (status) => {
      const actions = availableActions(task({ status }), {
        createBlocked: false,
      });
      expect(actions.pause.visible).toBe(false);
      expect(actions.resume).toEqual(open);
      expect(actions.runNow).toEqual(open);
      expect(actions.edit).toEqual(open);
    },
  );

  it.each(["completed", "failed", "cancelled"] as const)(
    "a finished one-time task (%s) is edited instead of resumed",
    (status) => {
      const actions = availableActions(
        task({ status, schedule_type: "once" }),
        { createBlocked: false },
      );
      expect(actions.pause.visible).toBe(false);
      expect(actions.resume.visible).toBe(false);
      expect(actions.edit).toEqual(open);
    },
  );

  it("Duplicate is a create, so it is blocked while automatic runs are off", () => {
    const actions = availableActions(task({}), { createBlocked: true });
    expect(actions.duplicate).toEqual(blocked("createBlocked"));
    expect(actions.pause).toEqual(open);
    expect(actions.runNow).toEqual(open);
  });
});

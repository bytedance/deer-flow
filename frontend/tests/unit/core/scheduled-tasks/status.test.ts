import { describe, expect, it } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import {
  presentTaskStatus,
  taskStatusLabel,
  type TaskStatusKey,
} from "@/core/scheduled-tasks/status";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

type StatusInput = Pick<
  ScheduledTask,
  "status" | "active_run_status" | "last_error"
>;

const task = (overrides: Partial<StatusInput>): StatusInput => ({
  status: "enabled",
  active_run_status: null,
  last_error: null,
  ...overrides,
});

const AGENT_STOP =
  "stopped by the agent in run 3f2a9c1e-8b47-4d2a-9e61-5c0b7a1d4e93";
const AUTO_PAUSE = "paused after 3 unmet scheduled goal runs";

describe("presentTaskStatus", () => {
  it.each<[Partial<StatusInput>, TaskStatusKey]>([
    [{ status: "enabled" }, "active"],
    [{ status: "paused" }, "paused"],
    [{ status: "paused", last_error: "Connection reset" }, "paused"],
    [{ status: "paused", last_error: AGENT_STOP }, "pausedByAgent"],
    [{ status: "paused", last_error: AUTO_PAUSE }, "autoPaused"],
    [{ status: "running" }, "running"],
    [{ status: "completed" }, "finished"],
    [{ status: "failed" }, "failed"],
    [{ status: "cancelled" }, "cancelled"],
  ])("%j → %s", (overrides, key) => {
    expect(presentTaskStatus(task(overrides)).key).toBe(key);
  });

  it("shows a recurring task whose run is in progress as running, not active", () => {
    expect(
      presentTaskStatus(
        task({ status: "enabled", active_run_status: "running" }),
      ),
    ).toMatchObject({ key: "running", tone: "info" });
    expect(
      presentTaskStatus(
        task({ status: "enabled", active_run_status: "launching" }),
      ).key,
    ).toBe("running");
  });

  it("keeps a task with only a queued run in its own state", () => {
    expect(
      presentTaskStatus(
        task({ status: "enabled", active_run_status: "queued" }),
      ).key,
    ).toBe("active");
  });

  it("gives each state a tone and an icon", () => {
    expect(presentTaskStatus(task({ status: "failed" })).tone).toBe("danger");
    expect(
      presentTaskStatus(task({ status: "paused", last_error: AUTO_PAUSE }))
        .tone,
    ).toBe("warn");
    expect(presentTaskStatus(task({})).icon).toBeTruthy();
  });

  it("labels every key in both languages with the glossary words", () => {
    const keys: TaskStatusKey[] = [
      "active",
      "paused",
      "pausedByAgent",
      "autoPaused",
      "running",
      "finished",
      "failed",
      "cancelled",
    ];
    expect(
      keys.map((key) => taskStatusLabel(key, enUS.scheduledTasks.status)),
    ).toEqual([
      "Active",
      "Paused",
      "Paused by agent",
      "Auto-paused",
      "Running now",
      "Finished",
      "Failed",
      "Cancelled",
    ]);
    expect(
      keys.map((key) => taskStatusLabel(key, zhCN.scheduledTasks.status)),
    ).toEqual([
      "已启用",
      "已暂停",
      "已由智能体暂停",
      "已自动暂停",
      "正在运行",
      "已结束",
      "失败",
      "已取消",
    ]);
  });
});
